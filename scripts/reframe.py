"""Reframe shots in a generated FCPXML (typically the 4:3 version): slide the picture sideways so the
subject stays in frame after the crop.

  --shot C1137=+240     show 240 px more of the RIGHT side of the clip (picture moves left)
  --shot C1103=-120     show 120 px more of the LEFT side
  --shot C1137@41.6=+240  only the use of C1137 that starts at 41.6 s on the timeline (if a clip is used twice)

Pixels are source pixels of 1920x1080 footage; Final Cut stores the offset as a percentage of the frame
height, which this converts. Only use it on files this workflow generated, never on your own export
(it edits the file in place, then re-validates it against Final Cut's DTD).

Usage: uv run scripts/reframe.py "<movie>/AI/fcpxml/<name> 4-3.fcpxml" --shot C1137=+240 --shot C1140=+240
"""
from __future__ import annotations

import argparse
import re
import subprocess
from fractions import Fraction
from pathlib import Path
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parent.parent
BEFORE_TRANSFORM = {"note", "conform-rate", "timeMap", "object-tracker", "adjust-crop", "adjust-corners", "adjust-conform"}


def tf(s):
    s = (s or "0s").rstrip("s")
    return float(Fraction(s)) if s else 0.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("file")
    ap.add_argument("--shot", action="append", required=True)
    args = ap.parse_args()
    path = Path(args.file)
    if path.is_dir() or path.suffix != ".fcpxml":
        raise SystemExit("give a generated .fcpxml file (not a .fcpxmld export)")
    tree = ET.parse(path)
    root = tree.getroot()
    res = {r.get("id"): r for r in root.find("resources")}
    seq = next(root.iter("project")).find("sequence")
    frame_h = int(res[seq.get("format")].get("height"))
    spine = seq.find("spine")
    done = []
    for spec in args.shot:
        m = re.fullmatch(r"(\w+)(?:@([\d.]+))?=([+-]?\d+(?:\.\d+)?)", spec)
        if not m:
            raise SystemExit(f"bad --shot {spec!r}; use CLIP=+240 or CLIP@41.6=+240")
        clip, at, px = m.group(1), m.group(2), float(m.group(3))
        hits = [e for e in spine if e.tag == "asset-clip" and res.get(e.get("ref"), {}).get("name") == clip
                and (at is None or abs(tf(e.get("offset")) - float(at)) < 0.1)]
        if not hits:
            raise SystemExit(f"{clip} not found on the timeline" + (f" at {at}s" if at else ""))
        x = round(-px / frame_h * 100, 4)            # show more of the right side = move the picture left
        for e in hits:
            t = e.find("adjust-transform")
            if t is None:
                idx = next((i for i, ch in enumerate(e) if ch.tag not in BEFORE_TRANSFORM), len(e))
                t = ET.Element("adjust-transform")
                e.insert(idx, t)
            y = (t.get("position") or "0 0").split()[1]
            t.set("position", f"{x} {y}")
            done.append(f"{clip} at {tf(e.get('offset')):.2f}s: position x {x} ({px:+.0f} px)")
    tree.write(path, encoding="UTF-8", xml_declaration=True)
    txt = path.read_text()
    if "<!DOCTYPE fcpxml>" not in txt:
        path.write_text(txt.replace("?>", "?>\n<!DOCTYPE fcpxml>", 1))
    dtd = ROOT / "vendor" / f"FCPXMLv{root.get('version').replace('.', '_')}.dtd"
    if dtd.exists():
        r = subprocess.run(["xmllint", "--noout", "--dtdvalid", str(dtd), str(path)], capture_output=True, text=True)
        print("DTD valid" if r.returncode == 0 else "DTD ERRORS:\n" + r.stderr[:2000])
    print("\n".join(done))


if __name__ == "__main__":
    main()
