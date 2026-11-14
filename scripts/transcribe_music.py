"""Find where the vocals are in the song (local Whisper via MLX).

Writes work/<project>/vocals.json: every sung line with start/end and word timings,
plus the gaps between lines. Lyrics text is NOT stored by default (only timing is
needed for editing); pass --keep-text to keep it for your own reference.

Usage: uv run scripts/transcribe_music.py [--keep-text]
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
    ap.add_argument("--keep-text", action="store_true")
    args = ap.parse_args()
    cfg = load_project()
    import mlx_whisper

    with tempfile.TemporaryDirectory() as td:
        wav = Path(td) / "song.wav"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", cfg["music"], "-ac", "1", "-ar", "16000", str(wav)], check=True)
        res = mlx_whisper.transcribe(str(wav), path_or_hf_repo=str(MODEL), word_timestamps=True,
                                     condition_on_previous_text=False, no_speech_threshold=0.5,
                                     compression_ratio_threshold=2.2, verbose=False)
    lines = []
    for s in res["segments"]:
        words = [w for w in s.get("words", []) if w["end"] > w["start"]]
        if not words:
            continue
        # drop obvious hallucinations: very low confidence on every word
        if max(w.get("probability", 1) for w in words) < 0.2:
            continue
        line = {"start": round(words[0]["start"], 2), "end": round(words[-1]["end"], 2), "n_words": len(words),
                "avg_prob": round(sum(w.get("probability", 0) for w in words) / len(words), 2),
                "words": [{"start": round(w["start"], 2), "end": round(w["end"], 2)} for w in words]}
        if args.keep_text:
            line["text"] = s["text"].strip()
        lines.append(line)
    gaps = []
    prev = 0.0
    for ln in lines:
        if ln["start"] - prev > 0.4:
            gaps.append({"start": round(prev, 2), "end": ln["start"], "len": round(ln["start"] - prev, 2)})
        prev = ln["end"]
    write_json(cfg["work"] / "vocals.json", {"language": res.get("language"), "lines": lines, "gaps": gaps})
    print(f"language {res.get('language')}, {len(lines)} sung lines")
    for ln in lines:
        print(f"  line {ln['start']:7.2f} - {ln['end']:7.2f}  ({ln['n_words']} words, p={ln['avg_prob']})")


if __name__ == "__main__":
    main()
