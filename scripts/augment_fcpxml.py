"""Add layers on top of a hand-edited Final Cut export without touching the edit.

Takes an exported .fcpxml / .fcpxmld (your cut + grade) and a layers JSON, writes a new
.fcpxml with the project renamed. Never moves, trims or deletes your clips; it only:
  * changes audio levels (music / sound-effect / named clip gains, in dB, relative)
  * adds connected audio (sound effects, ambience) and overlay images on their own lanes

layers JSON:
{
  "project": "driving in paris - AI cut v14",
  "gain": {"music": -3, "sfx card": 6, "spine:0-2": 9},   # relative dB; spine:i-j = spine clips i..j
  "audio": [{"file": ".../Whoosh 13.caf", "at": 25.87, "src": 0.0, "dur": 1.32, "db": -8,
             "fade_in": 0, "fade_out": 0.2, "lane": -4, "name": "whoosh drop"}],
  "overlays": [{"file": "work/.../stamp_01.png", "at": 0.0, "dur": 1.8, "lane": 2, "name": "stamp 17:39"}]
}
Usage: uv run scripts/augment_fcpxml.py export.fcpxmld layers.json --out out.fcpxml
"""
from __future__ import annotations

import argparse
import copy
import json
import subprocess
import sys
from fractions import Fraction
from pathlib import Path
from urllib.parse import quote
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).parent))
from common import ROOT, load_project, out_path  # noqa: E402

FRAME = Fraction(1001, 30000)
ANCHORABLE = {"audio", "video", "clip", "title", "caption", "mc-clip", "ref-clip", "sync-clip", "asset-clip", "audition", "spine", "live-drawing"}
AFTER_ANCHORS = {"marker", "chapter-marker", "rating", "keyword", "analysis-marker", "hidden-clip-marker",
                 "audio-channel-source", "filter-video", "filter-video-mask", "filter-audio", "metadata", "reserved"}


def tf(s):
    if not s:
        return Fraction(0)
    s = s.rstrip("s")
    return Fraction(s) if s else Fraction(0)


def T(x: Fraction) -> str:
    x = Fraction(round(x / FRAME)) * FRAME          # snap to frame
    return "0s" if x == 0 else (f"{x.numerator}/{x.denominator}s" if x.denominator != 1 else f"{x.numerator}s")


def shift_volume(el, db):
    av = el.find("adjust-volume")
    if av is None:
        av = ET.SubElement(el, "adjust-volume", amount="0dB")
        el.remove(av)
        # intrinsic params go before anchored items
        idx = next((i for i, c in enumerate(el) if c.tag in ANCHORABLE or c.tag in AFTER_ANCHORS), len(el))
        el.insert(idx, av)
    if av.get("amount") is not None:
        cur = float(av.get("amount").replace("dB", ""))
        av.set("amount", f"{round(cur + db, 2)}dB")
    for k in av.iter("keyframe"):
        v = float(k.get("value").replace("dB", ""))
        if v > -50:                                   # keep fade floors at silence
            k.set("value", f"{round(v + db, 2)}dB")


def insert_anchor(parent, child):
    idx = next((i for i, c in enumerate(parent) if c.tag in AFTER_ANCHORS), len(parent))
    parent.insert(idx, child)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("export")
    ap.add_argument("layers")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    src = Path(args.export)
    if src.is_dir():
        src = src / "Info.fcpxml"
    tree = ET.parse(src)
    root = tree.getroot()
    L = json.loads((ROOT / args.layers).read_text())
    res = root.find("resources")
    proj = next(root.iter("project"))
    proj.set("name", L["project"])
    spine = proj.find("sequence").find("spine")
    items = [e for e in spine if e.tag != "transition"]

    # ---- gains
    for key, db in L.get("gain", {}).items():
        if key.startswith("spine:"):
            a, b = (int(x) for x in key[6:].split("-"))
            for e in items[a:b + 1]:
                shift_volume(e, db)
        else:
            for e in spine.iter():
                if e.tag == "asset-clip" and e.get("lane", "").startswith("-") and (e.get("name") or "").startswith(key):
                    shift_volume(e, db)

    # ---- mute camera sound that isn't needed (absolute, -96 dB = silent)
    for key in L.get("mute", []):
        a, b = (int(x) for x in key[6:].split("-"))
        for e in items[a:b + 1]:
            if e.tag != "asset-clip":
                continue
            av = e.find("adjust-volume")
            if av is None:
                shift_volume(e, 0)
                av = e.find("adjust-volume")
            for p in list(av):
                av.remove(p)
            av.set("amount", "-96dB")

    # ---- volume ramps on timeline clips: {"spine:0": [[0.0, -30], [1.2, -8]]}  (seconds from clip start, dB)
    for key, pts in L.get("volume_keys", {}).items():
        e = items[int(key.split(":")[1])]
        av = e.find("adjust-volume")
        if av is None:
            shift_volume(e, 0)
            av = e.find("adjust-volume")
        for ch in list(av):
            av.remove(ch)
        av.attrib.pop("amount", None)
        kfa = ET.SubElement(ET.SubElement(av, "param", name="amount"), "keyframeAnimation")
        s0 = tf(e.get("start"))
        for t_rel, db in pts:
            ET.SubElement(kfa, "keyframe", time=T(s0 + Fraction(str(t_rel))), value=f"{db}dB")

    # ---- fades on connected audio by name, keeping its existing keyframes: {"music 1": {"in": 0.5}}
    for name, fd in L.get("fades", {}).items():
        for e in spine.iter("asset-clip"):
            if not (e.get("lane", "").startswith("-") and (e.get("name") or "") == name):
                continue
            av = e.find("adjust-volume")
            if av is None:
                shift_volume(e, 0)
                av = e.find("adjust-volume")
            s0, dur = tf(e.get("start")), tf(e.get("duration"))
            kf = [(tf(k.get("time")), float(k.get("value").replace("dB", ""))) for k in av.iter("keyframe")]
            level = next((v for _, v in kf if v > -50), float((av.get("amount") or "0dB").replace("dB", "")))
            if fd.get("in"):
                fi = Fraction(str(fd["in"]))
                kf = [(t, v) for t, v in kf if t > s0 + fi] + [(s0, -60.0), (s0 + fi, level)]
            if fd.get("out"):
                fo = Fraction(str(fd["out"]))
                kf = [(t, v) for t, v in kf if t < s0 + dur - fo] + [(s0 + dur - fo, level), (s0 + dur, -96.0)]
            for ch in list(av):
                av.remove(ch)
            av.attrib.pop("amount", None)
            kfa = ET.SubElement(ET.SubElement(av, "param", name="amount"), "keyframeAnimation")
            for t, v in sorted(kf):
                ET.SubElement(kfa, "keyframe", time=T(t), value=f"{round(v, 2)}dB")

    # ---- new resources
    used = {r.get("id") for r in res}
    n = [0]

    def new_id():
        while True:
            n[0] += 1
            if f"x{n[0]}" not in used:
                used.add(f"x{n[0]}")
                return f"x{n[0]}"

    asset_ids = {}

    def audio_asset(path):
        if path in asset_ids:
            return asset_ids[path]
        info = json.loads(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=sample_rate,channels",
                                          "-of", "json", path], capture_output=True, text=True, check=True).stdout)
        rid = new_id()
        a = ET.SubElement(res, "asset", id=rid, name=Path(path).stem, start="0s", duration=T(Fraction(info["format"]["duration"])),
                          hasAudio="1", audioSources="1", audioChannels=str(info["streams"][0]["channels"]),
                          audioRate=str(info["streams"][0]["sample_rate"]))
        ET.SubElement(a, "media-rep", kind="original-media", src="file://" + quote(path))
        asset_ids[path] = rid
        return rid

    fmt_id = None

    def image_asset(path):
        nonlocal fmt_id
        if path in asset_ids:
            return asset_ids[path]
        if fmt_id is None:
            fmt_id = new_id()
            res.insert(0, ET.Element("format", id=fmt_id, name="FFVideoFormatRateUndefined", width="1920", height="1080", colorSpace="1-13-1"))
        rid = new_id()
        a = ET.SubElement(res, "asset", id=rid, name=Path(path).stem, start="0s", duration="0s", hasVideo="1", format=fmt_id, videoSources="1")
        ET.SubElement(a, "media-rep", kind="original-media", src="file://" + quote(path))
        asset_ids[path] = rid
        return rid

    def host_at(t):
        return next(e for e in items if tf(e.get("offset")) <= t < tf(e.get("offset")) + tf(e.get("duration")))

    def anchor_time(host, t):
        return tf(host.get("start")) + (t - tf(host.get("offset")))

    # ---- connected audio
    for s in L.get("audio", []):
        path = str(Path(s["file"]).expanduser())
        t = Fraction(str(s["at"]))
        host = host_at(max(t, Fraction(0)))
        dur = Fraction(str(s["dur"]))
        el = ET.Element("asset-clip", ref=audio_asset(path), lane=str(s.get("lane", -4)), offset=T(anchor_time(host, t)),
                        name=s.get("name", Path(path).stem), start=T(Fraction(str(s.get("src", 0)))), duration=T(dur), audioRole="effects")
        db = s.get("db", 0)
        fi, fo = Fraction(str(s.get("fade_in", 0))), Fraction(str(s.get("fade_out", 0)))
        if fi or fo:
            av = ET.SubElement(el, "adjust-volume")
            kfs = ET.SubElement(ET.SubElement(av, "param", name="amount"), "keyframeAnimation")
            s0 = Fraction(str(s.get("src", 0)))
            pts = []
            if fi:
                pts += [(s0, -60), (s0 + fi, db)]
            else:
                pts += [(s0, db)]
            if fo:
                pts += [(s0 + dur - fo, db), (s0 + dur, -96)]
            for tt, v in pts:
                ET.SubElement(kfs, "keyframe", time=T(tt), value=f"{v}dB")
        else:
            ET.SubElement(el, "adjust-volume", amount=f"{db}dB")
        insert_anchor(host, el)

    # ---- swap a still for a new image, same timing ("replace": {"recap_title": "work/.../story_card_v2.jpg"})
    for name, file in L.get("replace", {}).items():
        path = str((ROOT / file).resolve())
        hits = [e for e in items if e.tag == "video" and (e.get("name") == name)]
        if not hits:
            raise SystemExit(f"replace: no still named {name} on the timeline")
        for e in hits:
            e.set("ref", image_asset(path))
            e.set("name", Path(path).stem)

    # ---- swap the first N stills of the timeline, in order (works whatever they're called)
    if L.get("replace_stills"):
        stills = [e for e in items if e.tag == "video" and not e.get("lane")]
        files = L["replace_stills"]
        if len(stills) < len(files):
            raise SystemExit(f"replace_stills: timeline has {len(stills)} stills, {len(files)} given")
        for e, file in zip(stills, files):
            path = str((ROOT / file).resolve())
            e.set("ref", image_asset(path))
            e.set("name", Path(path).stem)

    # ---- drop earlier overlays (e.g. old stamps) before adding new ones
    if L.get("remove_overlays"):
        prefix = L["remove_overlays"]
        for e in items:
            for ch in list(e):
                if ch.tag == "video" and ch.get("lane") and (ch.get("name") or "").startswith(prefix):
                    e.remove(ch)

    # ---- overlay images
    for o in L.get("overlays", []):
        path = str((ROOT / o["file"]).resolve())
        t = Fraction(str(o["at"]))
        host = host_at(t)
        el = ET.Element("video", ref=image_asset(path), lane=str(o.get("lane", 2)), offset=T(anchor_time(host, t)),
                        name=o.get("name", Path(path).stem), start="0s", duration=T(Fraction(str(o["dur"]))))
        insert_anchor(host, el)

    out = out_path(load_project(), args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    tree.write(out, encoding="UTF-8", xml_declaration=True)
    txt = out.read_text()
    if "<!DOCTYPE fcpxml>" not in txt:
        txt = txt.replace("?>", "?>\n<!DOCTYPE fcpxml>", 1)
        out.write_text(txt)
    ver = root.get("version")
    dtd = ROOT / "vendor" / f"FCPXMLv{ver.replace('.', '_')}.dtd"
    if not dtd.exists():
        app = Path(f"/Applications/Final Cut Pro.app/Contents/Frameworks/Interchange.framework/Versions/A/Resources/FCPXMLv{ver.replace('.', '_')}.dtd")
        if app.exists():
            dtd.write_bytes(app.read_bytes())
    if dtd.exists():
        r = subprocess.run(["xmllint", "--noout", "--dtdvalid", str(dtd), str(out)], capture_output=True, text=True)
        print("DTD valid" if r.returncode == 0 else "DTD ERRORS:\n" + r.stderr[:3000])
    print(out)


if __name__ == "__main__":
    main()
