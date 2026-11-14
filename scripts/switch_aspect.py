"""Make the other aspect-ratio version of a finished edit (16:9 <-> 4:3), as a NEW project.

The source export is only read. The new FCPXML keeps every cut, the grade (adjustment clips), the audio
mix and sound design, and changes only what depends on the frame:
  * the project's frame size (4:3 = 1440x1080, 16:9 = 1920x1080), same frame rate
  * footage set to Fill, so it covers the new frame (center crop; reframe in Final Cut if a subject is cut)
  * the photo recap + story card re-rendered for the new frame (from the editor settings)
  * the handwritten stamps re-rendered so they stay inside the new frame
New images get new file names (Final Cut copies media on import).

Usage: uv run scripts/switch_aspect.py "<movie>/AI/fcpxml/<final>.fcpxmld" --to 4:3 [--project NAME]
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime
from fractions import Fraction
from pathlib import Path
from urllib.parse import quote
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).parent))
from common import ROOT, load_project, out_path  # noqa: E402

SIZES = {"4:3": (1440, 1080), "16:9": (1920, 1080)}
SLUG = {"4:3": "4-3", "16:9": "16-9"}
BEFORE_CONFORM = {"note", "conform-rate", "timeMap", "object-tracker", "adjust-crop", "adjust-corners"}


def tf(s):
    s = (s or "0s").rstrip("s")
    return float(Fraction(s)) if s else 0.0


def set_fill(el) -> bool:
    """Spatial conform = Fill: the clip covers the new frame (center crop, no black bars)."""
    c = el.find("adjust-conform")
    if c is None:
        idx = next((i for i, ch in enumerate(el) if ch.tag not in BEFORE_CONFORM), len(el))
        c = ET.Element("adjust-conform")
        el.insert(idx, c)
    c.set("type", "fill")
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("export")
    ap.add_argument("--to", choices=list(SIZES), required=True)
    ap.add_argument("--project", help="name of the new project (default: source name + aspect)")
    ap.add_argument("--event", help="Final Cut event to import into (default: the movie's fcp_event setting)")
    ap.add_argument("--state", default=str(ROOT / "edit" / "editor-state.json"),
                    help="editor settings with the recap/card/stamps text (default: edit/editor-state.json)")
    args = ap.parse_args()
    cfg = load_project()
    w, h = SIZES[args.to]

    src = Path(args.export)
    src = src / "Info.fcpxml" if src.is_dir() else src
    tree = ET.parse(src)
    root = tree.getroot()
    res = root.find("resources")
    proj = next(root.iter("project"))
    seq = proj.find("sequence")
    old_fmt = next(r for r in res if r.tag == "format" and r.get("id") == seq.get("format"))
    if (int(old_fmt.get("width")), int(old_fmt.get("height"))) == (w, h):
        raise SystemExit(f"the source is already {args.to}")

    used = {r.get("id") for r in res}
    counter = [0]

    def new_id():
        while True:
            counter[0] += 1
            if f"a{counter[0]}" not in used:
                used.add(f"a{counter[0]}")
                return f"a{counter[0]}"

    # 1. the project's frame
    fid = new_id()
    # square pixels stated explicitly: a bare 1440x1080 can otherwise be taken as HDV (stretched pixels)
    fmt = ET.Element("format", id=fid, frameDuration=old_fmt.get("frameDuration"), fieldOrder="progressive",
                     width=str(w), height=str(h), paspH="1", paspV="1",
                     colorSpace=old_fmt.get("colorSpace", "1-1-1 (Rec. 709)"))
    res.insert(0, fmt)
    seq.set("format", fid)
    name = args.project or f"{proj.get('name')} ({args.to})"
    proj.set("name", name)
    # import into the movie's normal event, not whatever event name the source export carried
    event_name = args.event or cfg.get("fcp_event")
    for ev in root.iter("event"):
        if event_name:
            ev.set("name", event_name)

    # 2. footage fills the new frame (stills/stamps are re-rendered at frame size below; adjustment clips,
    #    which carry the grade, are left exactly as exported)
    effects = {r.get("id") for r in res if r.tag == "effect"}
    spine = seq.find("spine")
    filled = 0
    for e in spine.iter():
        if e.tag == "asset-clip" and e.get("ref") not in effects:
            lane = e.get("lane")
            if lane is None or int(lane) > 0:
                a = next((r for r in res if r.get("id") == e.get("ref")), None)
                if a is not None and a.get("hasVideo") == "1":
                    # THE important line: a clip without its own format inherits the sequence's ("default is
                    # same as parent"). Final Cut omits it on export when clip and project match, so after the
                    # project turns 4:3 every clip would become a 4:3 container with the 16:9 picture
                    # letterboxed INSIDE it (black bars; Fill and position then do nothing).
                    if not e.get("format") and a.get("format"):
                        e.set("format", a.get("format"))
                    filled += set_fill(e)

    # 3. re-render stills at the new size (recap prints, card, stamps)
    import render_table_stills as T
    import render_recap_styles  # noqa: F401  (registered for set_canvas)
    import render_stamps
    T.set_canvas(w, h)
    import editor                                   # reuses the editor's renderer and settings handling
    st = json.loads(Path(args.state).read_text())
    tag = f"{SLUG[args.to]}-{datetime.now():%m%d-%H%M%S}"
    stills_dir = cfg["stills"]
    fmt_by_size: dict[tuple[int, int], str] = {}

    def image_asset(path: Path, size: tuple[int, int]) -> str:
        if size not in fmt_by_size:
            fmt_by_size[size] = new_id()
            res.insert(0, ET.Element("format", id=fmt_by_size[size], name="FFVideoFormatRateUndefined",
                                     width=str(size[0]), height=str(size[1]), colorSpace="1-13-1"))
        rid = new_id()
        a = ET.SubElement(res, "asset", id=rid, name=path.stem, start="0s", duration="0s", hasVideo="1",
                          format=fmt_by_size[size], videoSources="1")
        ET.SubElement(a, "media-rep", kind="original-media", src="file://" + quote(str(path)))
        return rid

    frames, final = editor.render_recap(st)
    recap = []
    for i, f in enumerate(frames, 1):
        p = stills_dir / f"{st['style']}-{tag}_{i:02d}.jpg"
        f.convert("RGB").save(p, quality=93)
        recap.append(p)
    tp = stills_dir / f"{st['style']}-{tag}_title.jpg"
    final.convert("RGB").save(tp, quality=93)
    recap.append(tp)
    stills = [e for e in spine if e.tag == "video" and e.get("ref") not in effects]
    if len(stills) < len(recap):
        print(f"warning: timeline has {len(stills)} stills, recap has {len(recap)}; stills left as they were")
    else:
        for e, p in zip(stills, recap):
            e.set("ref", image_asset(p, (w, h)))
            e.set("name", p.stem)

    n_st = 0
    texts = st.get("stamps", [])
    for host in spine:
        for c in list(host):
            if c.tag == "video" and (c.get("name") or "").startswith("stamp"):
                at = tf(host.get("offset")) + tf(c.get("offset")) - tf(host.get("start"))
                m = min(texts, key=lambda s: abs(s["at"] - at)) if texts else None
                if not m or abs(m["at"] - at) > 0.5:
                    print(f"warning: no stamp text near {at:.2f}s, kept as is")
                    continue
                n_st += 1
                p = stills_dir / f"stamp-{tag}_{n_st:02d}.png"
                render_stamps.stamp(m["text"], st["font"], int(st.get("stamp_size", 58))).save(p)
                c.set("ref", image_asset(p, (w, h)))

    # 4. tidy resources: drop assets nothing uses any more (the old 16:9 stills), and relink media whose
    #    path is gone (e.g. a renamed Final Cut event) to the real files in the movie folders
    refs = {el.get("ref") for el in root.iter() if el.get("ref")}
    for a in [r for r in res if r.tag == "asset" and r.get("id") not in refs]:
        res.remove(a)
    from urllib.parse import unquote
    search = [Path(cfg["shots_dir"]), Path(cfg["pics_dir"]), Path(cfg["music"]).parent, cfg["stills"]]
    relinked = []
    for mr in root.iter("media-rep"):
        p = Path(unquote(mr.get("src").replace("file://", "")))
        if p.exists():
            continue
        hit = next((d / p.name for d in search if (d / p.name).exists()), None)
        if hit is None:
            hit = next((f for d in search if d.exists() for f in d.iterdir() if f.name.lower() == p.name.lower()), None)
        if hit is not None:
            mr.set("src", "file://" + quote(str(hit)))
            relinked.append(p.name)
    still_missing = [unquote(m.get("src")) for m in root.iter("media-rep")
                     if not Path(unquote(m.get("src").replace("file://", ""))).exists()]

    # 5. write + validate
    out = out_path(cfg, f"{name}.fcpxml")
    tree.write(out, encoding="UTF-8", xml_declaration=True)
    txt = out.read_text()
    if "<!DOCTYPE fcpxml>" not in txt:
        out.write_text(txt.replace("?>", "?>\n<!DOCTYPE fcpxml>", 1))
    ver = root.get("version").replace(".", "_")
    dtd = ROOT / "vendor" / f"FCPXMLv{ver}.dtd"
    app = Path(f"/Applications/Final Cut Pro.app/Contents/Frameworks/Interchange.framework/Versions/A/Resources/FCPXMLv{ver}.dtd")
    if not dtd.exists() and app.exists():
        dtd.parent.mkdir(exist_ok=True)
        dtd.write_bytes(app.read_bytes())
    if dtd.exists():
        r = subprocess.run(["xmllint", "--noout", "--dtdvalid", str(dtd), str(out)], capture_output=True, text=True)
        print("DTD valid" if r.returncode == 0 else "DTD ERRORS:\n" + r.stderr[:2000])
    print(f"{args.to} version: {out}")
    print(f"  frame {w}x{h}, {filled} clips keep their own format and are set to Fill (center crop), {len(recap)} recap stills, {n_st} stamps re-rendered")
    if relinked:
        print(f"  relinked {len(relinked)} media files whose old path is gone (to SHOTS / PICS / music / stills)")
    if still_missing:
        print(f"  WARNING: {len(still_missing)} media still missing: {still_missing[:3]}")


if __name__ == "__main__":
    main()
