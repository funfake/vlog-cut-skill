"""Local editor for the recap card, photos and handwritten stamps, with live preview.

Run:   uv run scripts/editor.py            (then open http://localhost:8765)
It renders with the same code as the command-line scripts, so what you see is what goes
into Final Cut. "Build FCPXML" writes the images and a new .fcpxml layered on top of your
Final Cut export (your cut and grade are never touched).

Settings are saved in edit/editor-state.json between sessions.
"""
from __future__ import annotations

import io
import json
import random
import subprocess
import sys
import time
from datetime import datetime
from fractions import Fraction
from functools import lru_cache
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).parent))
import render_recap_styles as R  # noqa: E402
from common import ROOT, load_project, out_path  # noqa: E402
from render_stamps import stamp  # noqa: E402

from PIL import Image  # noqa: E402

PORT = 8765
CFG = load_project()
WORK: Path = CFG["work"]
STATE = ROOT / "edit" / "editor-state.json"
HTML = ROOT / "editor" / "index.html"

DEFAULT = {                     # generic starting point; your movie's values live in edit/editor-state.json (not in git)
    "style": "polaroid-note",
    "seed": 11,
    "font": str(Path.home() / "Library/Fonts/penoftruth.ttf"),
    "photos": [],
    "card": {"title": "title", "lines": ["a line or two about the day"], "date": "dd.mm.yy",
             "title_size": 84, "body_size": 42, "date_size": 32, "rule": 44, "gap": 30, "width": 0},
    "stamps": [],
    "stamp_size": 58,
    "export": "",
    "audio_layers": "examples/audio-mix.json",
    "include_audio": True,
    "project": CFG.get("name", "movie") + " - editor cut",
}


def load_state() -> dict:
    if STATE.exists():
        return {**DEFAULT, **json.loads(STATE.read_text())}
    return json.loads(json.dumps(DEFAULT))


def save_state(st: dict) -> None:
    STATE.write_text(json.dumps(st, indent=2, ensure_ascii=False))


# ------------------------------------------------------------------ discovery
def fonts() -> list[dict]:
    dirs = [Path.home() / "Library/Fonts", Path("/Library/Fonts"), Path("/System/Library/Fonts/Supplemental"), Path("/System/Library/Fonts")]
    keep = ("handwritten", "penoftruth", "patrickhand", "bradleyhand", "noteworthy", "chalkboard", "chalkduster",
            "snellroundhand", "savoye", "brushscript", "markerfelt", "caveat", "kalam", "indieflower")
    out = []
    for d in dirs:
        for f in sorted(d.glob("*.[ot]t[fc]")):
            if any(k in f.stem.lower().replace(" ", "").replace("-", "") for k in keep):
                out.append({"name": f.stem, "path": str(f)})
    return out


def pics() -> list[str]:
    return sorted(p.stem for p in Path(CFG["pics_dir"]).glob("*.[Jj][Pp][Gg]"))


def exports() -> list[str]:
    roots = {Path(CFG["shots_dir"]).parent, ROOT / "work"}
    found = set()
    for r in roots:
        found |= {str(p) for p in r.rglob("*.fcpxmld")}
        found |= {str(p) for p in r.rglob("*.fcpxml") if "/out/" not in str(p) and ".fcpxmld/" not in str(p)}
    return sorted(found)


@lru_cache(maxsize=8)
def surface(seed: int) -> Image.Image:
    return R.black_surface(seed).convert("RGBA")


@lru_cache(maxsize=256)
def thumb(name: str) -> bytes:
    f = next(Path(CFG["pics_dir"]).glob(name + ".*"))
    im = Image.open(f)
    im.draft("RGB", (320, 180))
    im = im.convert("RGB")
    im.thumbnail((240, 135))
    b = io.BytesIO()
    im.save(b, "JPEG", quality=80)
    return b.getvalue()


# ------------------------------------------------------------------ rendering
def card_lines(st: dict) -> list[str]:
    c = st["card"]
    return [c["title"], *[ln for ln in c["lines"] if ln.strip()], c["date"]]


def apply_note_opts(st: dict) -> None:
    c = st["card"]
    R.NOTE_OPTS.clear()
    R.NOTE_OPTS.update(title_size=c["title_size"], body_size=c["body_size"], date_size=c["date_size"],
                       rule=c["rule"], gap=c["gap"], width=(c["width"] or None))


def render_recap(st: dict):
    apply_note_opts(st)
    pics_dir = Path(CFG["pics_dir"])
    photos = [next(pics_dir.glob(p["name"] + ".*")) for p in st["photos"]]
    caps = [p["caption"] for p in st["photos"]]
    fn = R.STYLES[st["style"]]
    random.seed(st["seed"])
    return fn(photos, caps, card_lines(st), st["font"], random.Random(st["seed"]), surface(int(st["seed"])))


def timeline_frame(st: dict, at: float) -> Image.Image:
    """The footage under a stamp: find the clip playing at `at` in the export and use its nearest keyframe."""
    try:
        src = Path(st["export"])
        src = src / "Info.fcpxml" if src.is_dir() else src
        root = ET.parse(src).getroot()
        names = {r.get("id"): r.get("name") for r in root.find("resources")}
        spine = next(root.iter("project")).find("sequence").find("spine")
        tf = lambda s: float(Fraction(s.rstrip("s"))) if s and s != "0s" else 0.0  # noqa: E731
        for e in spine:
            o, d = tf(e.get("offset")), tf(e.get("duration"))
            if o <= at < o + d and e.tag == "asset-clip":
                clip, t = names[e.get("ref")], tf(e.get("start")) + (at - o)
                keys = sorted((WORK / "frames" / clip).glob("*.jpg"))
                best = min(keys, key=lambda k: abs(float(k.stem.rsplit("_", 1)[1]) - t))
                return Image.open(best).convert("RGBA").resize((1920, 1080))
    except Exception:
        pass
    return surface(int(st["seed"])).copy()


def jpeg(im: Image.Image, w=1280) -> bytes:
    im = im.convert("RGB")
    if im.width > w:
        im = im.resize((w, round(im.height * w / im.width)), Image.LANCZOS)
    b = io.BytesIO()
    im.save(b, "JPEG", quality=86)
    return b.getvalue()


def preview(st: dict, view: str, index: int) -> bytes:
    if view == "card":
        apply_note_opts(st)
        pg = R.notebook_page(card_lines(st), st["font"])
        bg = Image.new("RGBA", (pg.width + 80, pg.height + 80), (18, 18, 18, 255))
        bg.alpha_composite(pg, (40, 40))
        return jpeg(bg, w=max(900, pg.width + 80))
    if view == "stamp":
        s = st["stamps"][index]
        fr = timeline_frame(st, float(s["at"]) + 0.05)        # just after the cut: the clip the stamp is about
        fr.alpha_composite(stamp(s["text"], st["font"], int(st["stamp_size"])))
        return jpeg(fr)
    frames, final = render_recap(st)
    return jpeg(final if view == "final" else frames[min(index, len(frames) - 1)])


# ------------------------------------------------------------------ save / build
def save_assets(st: dict) -> dict:
    tag = datetime.now().strftime("ed%m%d-%H%M%S")      # unique names: Final Cut copies media on import
    stills = CFG["stills"]
    frames, final = render_recap(st)
    recap = []
    for i, f in enumerate(frames, 1):
        p = stills / f"{st['style']}-{tag}_{i:02d}.jpg"
        f.convert("RGB").save(p, quality=93)
        recap.append(p)
    tp = stills / f"{st['style']}-{tag}_title.jpg"
    final.convert("RGB").save(tp, quality=93)
    stamps = []
    for i, s in enumerate(st["stamps"], 1):
        p = stills / f"stamp-{tag}_{i:02d}.png"
        stamp(s["text"], st["font"], int(st["stamp_size"])).save(p)
        stamps.append(p)
    rel = lambda p: str(p)  # absolute: images live in the movie's AI folder  # noqa: E731
    layers = {"project": st["project"], "replace_stills": [rel(p) for p in recap] + [rel(tp)],
              "remove_overlays": "stamp",
              "overlays": [{"name": f"stamp {s['text'].split(' ')[0]}", "file": rel(p), "at": float(s["at"]), "dur": float(s["dur"]), "lane": 2}
                           for s, p in zip(st["stamps"], stamps)]}
    if st.get("include_audio") and st.get("audio_layers"):
        base = json.loads((ROOT / st["audio_layers"]).read_text())
        for k in ("gain", "audio", "mute", "volume_keys", "fades"):
            if k in base:
                layers[k] = base[k]
    lp = ROOT / "edit" / f"layers-{tag}.json"
    lp.write_text(json.dumps(layers, indent=2, ensure_ascii=False))
    return {"tag": tag, "layers": str(lp), "files": [rel(p) for p in recap + [tp] + stamps]}


def build(st: dict) -> dict:
    saved = save_assets(st)
    slug = "".join(ch if ch.isalnum() or ch in " -()" else "_" for ch in st["project"]).strip() or saved["tag"]
    out = out_path(CFG, f"{slug}.fcpxml")                 # <movie>/AI/fcpxml/
    if out.exists():                                      # never overwrite an earlier build
        out = out_path(CFG, f"{slug} {saved['tag']}.fcpxml")
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "augment_fcpxml.py"), st["export"],
                        str(Path(saved["layers"]).relative_to(ROOT)), "--out", str(out)],
                       capture_output=True, text=True, cwd=ROOT)
    return {**saved, "fcpxml": str(out), "ok": r.returncode == 0 and "DTD valid" in r.stdout, "log": (r.stdout + r.stderr)[-2000:]}


# ------------------------------------------------------------------ http
class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send(self, code, body: bytes, ctype: str):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def json(self, obj, code=200):
        self.send(code, json.dumps(obj, ensure_ascii=False).encode(), "application/json")

    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        if u.path == "/":
            return self.send(200, HTML.read_bytes(), "text/html; charset=utf-8")
        if u.path == "/api/state":
            return self.json({"state": load_state(), "fonts": fonts(), "pics": pics(), "exports": exports(),
                              "styles": list(R.STYLES)})
        if u.path == "/api/thumb":
            return self.send(200, thumb(q["name"][0]), "image/jpeg")
        if u.path.startswith("/files/"):
            p = (ROOT / u.path[len("/files/"):]).resolve()
            if ROOT in p.parents and p.exists():
                return self.send(200, p.read_bytes(), "image/png" if p.suffix == ".png" else "image/jpeg")
        self.send(404, b"not found", "text/plain")

    def do_POST(self):
        u = urlparse(self.path)
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        try:
            if u.path == "/api/render":
                st = body["state"]
                save_state(st)
                t = time.time()
                img = preview(st, body.get("view", "final"), int(body.get("index", 0)))
                self.send_response(200)
                self.send_header("Content-Type", "image/jpeg")
                self.send_header("X-Render-Ms", str(int((time.time() - t) * 1000)))
                self.send_header("Content-Length", str(len(img)))
                self.end_headers()
                return self.wfile.write(img)
            if u.path == "/api/save":
                save_state(body["state"])
                return self.json(save_assets(body["state"]))
            if u.path == "/api/build":
                save_state(body["state"])
                return self.json(build(body["state"]))
            if u.path == "/api/reset":
                if STATE.exists():
                    STATE.unlink()
                return self.json({"state": load_state()})
        except Exception as e:  # show errors in the page instead of a silent failure
            return self.json({"error": f"{type(e).__name__}: {e}"}, 500)
        self.send(404, b"not found", "text/plain")


def main():
    print(f"editor running at http://localhost:{PORT}  (Ctrl-C to stop)")
    ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()


if __name__ == "__main__":
    main()
