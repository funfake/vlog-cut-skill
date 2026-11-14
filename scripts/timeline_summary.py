"""Summarise any FCPXML project timeline: spine items with offset/in/duration, connected clips by lane,
effects/titles/transitions. Use it to diff an exported Final Cut edit against a generated one.

Usage: uv run scripts/timeline_summary.py path/to/file.fcpxml [--project NAME]
"""
from __future__ import annotations

import argparse
from fractions import Fraction
import xml.etree.ElementTree as ET


def t(s: str | None) -> float:
    if not s:
        return 0.0
    s = s.rstrip("s")
    return float(Fraction(s)) if s else 0.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("file")
    ap.add_argument("--project")
    args = ap.parse_args()
    root = ET.parse(args.file).getroot()
    names = {r.get("id"): r.get("name") for r in root.find("resources")}
    projects = root.iter("project")
    for proj in projects:
        if args.project and proj.get("name") != args.project:
            continue
        seq = proj.find("sequence")
        print(f"PROJECT {proj.get('name')}  duration {t(seq.get('duration')):.2f}s")
        for e in seq.find("spine"):
            tag = e.tag
            nm = e.get("name") or names.get(e.get("ref"), "")
            extra = []
            for ch in e:
                if ch.get("lane"):
                    extra.append(f"[lane {ch.get('lane')}: {ch.tag} {ch.get('name') or names.get(ch.get('ref'), '')} "
                                 f"@{t(ch.get('offset')) - t(e.get('start')):+.2f} dur {t(ch.get('duration')):.2f}]")
                elif ch.tag in ("filter-video", "filter-audio"):
                    extra.append(f"<{ch.tag} {names.get(ch.get('ref'), ch.get('ref'))}>")
                elif ch.tag.startswith("adjust-"):
                    extra.append(f"<{ch.tag} {ch.get('amount') or ''}>")
                elif ch.tag in ("timeMap", "conform-rate"):
                    extra.append(f"<{ch.tag}>")
            print(f"  {t(e.get('offset')):7.2f}  {tag:10s} {nm:28s} in {t(e.get('start')):7.2f}  dur {t(e.get('duration')):5.2f}  {' '.join(extra)}")


if __name__ == "__main__":
    main()
