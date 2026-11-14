"""Timestamps for the video description, from the stamps in your final Final Cut export.

Reads every stamp overlay (connected video named "stamp …") from the export, takes its text from the
editor state (matched by time), and prints / writes the list as `00:07 17h42 on part en ville` (YouTube mm:ss text).
Also prints the music credit from the movie settings.

Usage: uv run scripts/video_chapters.py "<movie>/AI/fcpxml/<final>.fcpxmld" [--json]
"""
from __future__ import annotations

import argparse
import json
import sys
from fractions import Fraction
from pathlib import Path
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).parent))
from common import ROOT, load_project  # noqa: E402


def tf(s):
    s = (s or "0s").rstrip("s")
    return float(Fraction(s)) if s else 0.0


def stamps_in(export: Path) -> list[tuple[float, str]]:
    p = export / "Info.fcpxml" if export.is_dir() else export
    root = ET.parse(p).getroot()
    spine = next(root.iter("project")).find("sequence").find("spine")
    out = []
    for e in spine:
        for c in e:
            if c.tag == "video" and (c.get("name") or "").startswith("stamp"):
                out.append((tf(e.get("offset")) + tf(c.get("offset")) - tf(e.get("start")), c.get("name")))
    return sorted(out)


def mmss(t: float) -> str:
    """YouTube timestamp, always mm:ss (00:07)."""
    t = int(t + 0.05)                       # a stamp 1 frame before a second still belongs to it
    return f"{t // 60:02d}:{t % 60:02d}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("export")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    cfg = load_project()
    texts = []
    st = ROOT / "edit" / "editor-state.json"
    if st.exists():
        texts = json.loads(st.read_text()).get("stamps", [])
    rows = []
    for at, name in stamps_in(Path(args.export)):
        m = min(texts, key=lambda s: abs(s["at"] - at)) if texts else None
        text = m["text"] if m and abs(m["at"] - at) < 0.5 else name.replace("stamp ", "")
        text = " ".join(text.replace("·", " ").split())   # description text: no separators, plain words
        rows.append({"at": round(at, 2), "ts": mmss(at), "text": text})
    if rows and rows[0]["ts"] != "00:00":         # YouTube timestamps start at 00:00
        rows.insert(0, {"at": 0.0, "ts": "00:00", "text": "intro"})
    music = Path(cfg.get("music", "")).stem.replace(" (Explicit)", "")
    if args.json:
        print(json.dumps({"chapters": rows, "music": music}, ensure_ascii=False, indent=2))
        return
    for r in rows:
        print(f"{r['ts']} {r['text']}")                # YouTube format: mm:ss text (no dashes)
    if music:
        print(f"\nmusic: {music}")
    short = [b["at"] - a["at"] for a, b in zip(rows, rows[1:]) if b["at"] - a["at"] < 10]
    if short:
        print(f"\nnote: {len(short)} gaps are under 10 s, so YouTube won't turn these into chapters "
              "(it needs ≥10 s each); they still work as clickable timestamps.")


if __name__ == "__main__":
    main()
