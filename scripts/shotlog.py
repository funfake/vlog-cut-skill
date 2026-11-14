"""Readable shot log: one line per keyframe window merging measurements and descriptions.

Columns: clip, time, local clock, motion / forward travel / lateral pan / shake, brightness,
warmth, highlight %, sound dB, then the vision model's setting / shot / light / beauty / subject.

Usage: uv run scripts/shotlog.py > work/<project>/shotlog.txt
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import load_project  # noqa: E402


def window(samples, t0, t1):
    w = [s for s in samples if t0 <= s["t"] < t1] or samples[-1:]
    avg = lambda k: sum(s.get(k, 0) or 0 for s in w) / len(w)  # noqa: E731
    return {k: avg(k) for k in ("motion", "forward", "pan_x", "shake", "brightness", "warmth", "highlights", "audio_db")}


def main():
    cfg = load_project()
    w = cfg["work"]
    print("clip  t    clock  mot  fwd   pan  shk  bri  warm  hl%  dB   | setting / shot / light  b e | subject ; notable")
    for p in sorted((w / "clips").glob("*.json")):
        c = json.loads(p.read_text())
        name, info = c["info"]["name"], c["info"]
        d = json.loads((w / "descriptions" / f"{name}.json").read_text()) if (w / "descriptions" / f"{name}.json").exists() else {"frames": []}
        by_t = {round(f["t"], 2): f for f in d["frames"]}
        clock = (info.get("creation_time") or "")[11:19]
        print(f"--- {name}  {info['duration']:.1f}s  start {clock}  cuts-inside {c['cuts']}")
        keys = c["keyframes"]
        for i, t in enumerate(keys):
            t1 = keys[i + 1] if i + 1 < len(keys) else info["duration"]
            m = window(c["samples"], t, t1)
            f = by_t.get(round(t, 2), {})
            print(f"{name} {t:5.1f} {m['motion']:4.1f} {m['forward']:5.2f} {m['pan_x']:5.1f} {m['shake']:4.1f} "
                  f"{m['brightness']:.2f} {m['warmth']:5.2f} {100 * m['highlights']:4.1f} {m['audio_db']:5.1f} | "
                  f"{f.get('setting')}/{f.get('shot_type')}/{f.get('light')} {f.get('beauty')} {f.get('energy')} | "
                  f"{f.get('landmark') or ''} {f.get('subject', '')} ; {f.get('notable', '')}")


if __name__ == "__main__":
    main()
