"""Find speech in each clip's camera sound (local Whisper via MLX), so cuts never land mid-sentence.

Writes work/<project>/speech/<clip>.json: spoken lines with start/end (clip time) and text,
plus "has_speech". Clips that are only wind, engine or music come back empty.

Usage: uv run scripts/transcribe_clips.py [--only C1102 C1103] [--force]
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import ROOT, load_project, write_json  # noqa: E402

MODEL = ROOT / "models" / "whisper-large-v3-turbo"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--min-prob", type=float, default=0.5, help="drop lines Whisper is unsure about (wind/engine hallucinations)")
    args = ap.parse_args()
    cfg = load_project()
    import mlx_whisper

    out_dir = cfg["work"] / "speech"
    out_dir.mkdir(exist_ok=True)
    clips = sorted(Path(cfg["shots_dir"]).glob("*.[Mm][Pp]4")) + sorted(Path(cfg["shots_dir"]).glob("*.[Mm][Oo][Vv]"))
    if args.only:
        clips = [c for c in clips if c.stem in args.only]
    for clip in clips:
        out = out_dir / f"{clip.stem}.json"
        if out.exists() and not args.force:
            continue
        with tempfile.TemporaryDirectory() as td:
            wav = Path(td) / "a.wav"
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(clip), "-vn", "-ac", "1", "-ar", "16000", str(wav)], check=True)
            res = mlx_whisper.transcribe(str(wav), path_or_hf_repo=str(MODEL), word_timestamps=True,
                                         condition_on_previous_text=False, no_speech_threshold=0.6, verbose=None)
        lines = []
        for s in res["segments"]:
            words = [w for w in s.get("words", []) if w["end"] > w["start"]]
            if not words:
                continue
            prob = sum(w.get("probability", 0) for w in words) / len(words)
            if prob < args.min_prob or s.get("no_speech_prob", 0) > 0.6:
                continue
            lines.append({"start": round(words[0]["start"], 2), "end": round(words[-1]["end"], 2),
                          "text": s["text"].strip(), "prob": round(prob, 2)})
        write_json(out, {"clip": clip.stem, "language": res.get("language"), "has_speech": bool(lines), "lines": lines})
        print(f"{clip.stem}: {len(lines)} spoken lines" + (f"  e.g. {lines[0]['start']:.1f}-{lines[0]['end']:.1f}s" if lines else ""))


if __name__ == "__main__":
    main()
