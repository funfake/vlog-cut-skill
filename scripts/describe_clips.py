"""Describe keyframes with a local vision model (Qwen3-VL via MLX). Nothing leaves the Mac.

For each keyframe (every ~2 s) the model returns a small JSON record: setting,
shot type, subject, light, mood, notable details and a beauty score.
Writes work/<project>/descriptions/<clip>.json. Resumable: finished clips are skipped.

Usage: uv run scripts/describe_clips.py [--only C1102 C1103] [--max-side 640]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).parent))
from common import ROOT, load_project, write_json  # noqa: E402

PROMPT = """You are a film editor logging footage for a cinematic, music-driven video about {context}.
Look at this frame and answer with ONE JSON object only, no prose:
{
 "setting": "garage | street | boulevard | tunnel | bridge | river/quai | landmark | parking | interior | other",
 "landmark": "name if a recognisable landmark is visible, else null",
 "shot_type": "pov_windshield | dashboard/interior | driver | car_exterior | car_detail | passenger_window | street_static | handheld_walk | other",
 "subject": "short: what the eye goes to",
 "light": "daylight | golden_hour | blue_hour | night_streetlights | night_neon | headlights | indoor",
 "mood": "2-3 words",
 "composition": "short: leading lines, symmetry, framing, bokeh, reflections...",
 "notable": "anything striking or a problem (blur, obstruction, overexposed, nothing happens)",
 "beauty": 1-10,
 "energy": 1-10
}"""


def parse_json(text: str) -> dict:
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return {"raw": text.strip()}
    blob = m.group(0)
    try:
        return json.loads(blob)
    except json.JSONDecodeError:
        blob = re.sub(r",\s*}", "}", blob)
        try:
            return json.loads(blob)
        except json.JSONDecodeError:
            return {"raw": text.strip()}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--max-side", type=int, default=640)
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    cfg = load_project()
    from mlx_vlm import generate, load
    from mlx_vlm.prompt_utils import apply_chat_template

    model_path = str(ROOT / cfg["vlm_model"])
    model, processor = load(model_path)
    context = cfg.get("context", "a personal short film")   # e.g. "a drive through a city at dusk" (project config)
    prompt = apply_chat_template(processor, model.config, PROMPT.replace("{context}", context), num_images=1)

    frames_root = cfg["work"] / "frames"
    clips = sorted(p for p in frames_root.iterdir() if p.is_dir())
    if args.only:
        clips = [c for c in clips if c.name in args.only]
    tmp = cfg["work"] / "frames_small"
    tmp.mkdir(exist_ok=True)

    t0 = time.time()
    n = 0
    for clip in clips:
        out = cfg["work"] / "descriptions" / f"{clip.name}.json"
        if out.exists() and not args.force:
            continue
        records = []
        for jpg in sorted(clip.glob("*.jpg")):
            t = float(jpg.stem.rsplit("_", 1)[1])
            small = tmp / jpg.name
            if not small.exists():
                im = Image.open(jpg)
                im.thumbnail((args.max_side, args.max_side))
                im.save(small, quality=88)
            res = generate(model, processor, prompt, image=[str(small)], max_tokens=260,
                           temperature=0.0, verbose=False)
            text = res.text if hasattr(res, "text") else str(res)
            rec = {"t": t, **parse_json(text)}
            records.append(rec)
            n += 1
            print(f"{clip.name} {t:6.2f}s  {rec.get('setting')}/{rec.get('shot_type')}  "
                  f"{rec.get('light')}  beauty={rec.get('beauty')}  "
                  f"[{(time.time() - t0) / n:.1f}s/frame]", flush=True)
        write_json(out, {"clip": clip.name, "model": cfg["vlm_model"], "frames": records})
    print(f"DESCRIBE DONE: {n} frames in {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
