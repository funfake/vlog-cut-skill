"""Music map: tempo, beats, downbeats (bar starts), energy per beat, sections, big hits.

Usage: uv run scripts/analyze_music.py
Writes work/<project>/music.json and music.png (energy plot with sections).
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

import librosa
import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from common import load_project, write_json  # noqa: E402

SR = 22050
HOP = 512


def main():
    cfg = load_project()
    src = Path(cfg["music"])
    with tempfile.TemporaryDirectory() as td:
        wav = Path(td) / "music.wav"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(src), "-ac", "1", "-ar", str(SR), str(wav)], check=True)
        y, sr = librosa.load(wav, sr=SR)
    duration = len(y) / sr

    onset_env = librosa.onset.onset_strength(y=y, sr=sr, hop_length=HOP)
    tempo, beat_frames = librosa.beat.beat_track(onset_envelope=onset_env, sr=sr, hop_length=HOP)
    tempo = float(np.atleast_1d(tempo)[0])
    beats = librosa.frames_to_time(beat_frames, sr=sr, hop_length=HOP)

    # downbeats: choose the 4-beat phase whose beats carry the most low-end + onset energy
    S = np.abs(librosa.stft(y, hop_length=HOP))
    freqs = librosa.fft_frequencies(sr=sr)
    low = S[freqs < 150].mean(axis=0)
    strength = onset_env / (onset_env.max() + 1e-9) + low / (low.max() + 1e-9)
    phase_scores = [strength[beat_frames[p::4]].mean() for p in range(4)]
    phase = int(np.argmax(phase_scores))
    downbeats = beats[phase::4]

    # energy per beat (dB RMS) and brightness (spectral centroid)
    rms = librosa.feature.rms(y=y, hop_length=HOP)[0]
    cent = librosa.feature.spectral_centroid(y=y, sr=sr, hop_length=HOP)[0]
    beat_info = []
    edges = list(beat_frames) + [len(rms)]
    for i, b in enumerate(beat_frames):
        seg = slice(b, max(b + 1, edges[i + 1]))
        beat_info.append({
            "t": round(float(beats[i]), 3),
            "downbeat": bool((i - phase) % 4 == 0),
            "energy_db": round(float(20 * np.log10(rms[seg].mean() + 1e-9)), 1),
            "onset": round(float(onset_env[b]), 2),
            "brightness": round(float(cent[seg].mean()), 0),
        })

    # sections: structural novelty on chroma + mfcc, snapped to downbeats
    chroma = librosa.feature.chroma_cqt(y=y, sr=sr, hop_length=HOP)
    mfcc = librosa.feature.mfcc(y=y, sr=sr, hop_length=HOP, n_mfcc=13)
    feats = np.vstack([librosa.util.normalize(chroma, axis=1), librosa.util.normalize(mfcc, axis=1)])
    sync = librosa.util.sync(feats, beat_frames, aggregate=np.median)
    k = max(4, min(12, int(duration // 20)))
    bounds = librosa.segment.agglomerative(sync, k)
    bound_times = sorted({float(beats[min(b, len(beats) - 1)]) for b in bounds} | {0.0})
    snapped = sorted({min(downbeats, key=lambda d: abs(d - t)) if t > 0 else 0.0 for t in bound_times})
    sections = []
    for i, start in enumerate(snapped):
        end = snapped[i + 1] if i + 1 < len(snapped) else duration
        bb = [b for b in beat_info if start <= b["t"] < end]
        sections.append({
            "start": round(float(start), 3), "end": round(float(end), 3),
            "bars": round((end - start) / (4 * 60 / tempo), 1),
            "energy_db": round(float(np.mean([b["energy_db"] for b in bb])), 1) if bb else None,
            "brightness": round(float(np.mean([b["brightness"] for b in bb])), 0) if bb else None,
        })
    # rank energy so the editor can read "intro / build / drop" at a glance
    es = sorted(s["energy_db"] for s in sections if s["energy_db"] is not None)
    for s in sections:
        if s["energy_db"] is None:
            continue
        q = es.index(s["energy_db"]) / max(1, len(es) - 1)
        s["level"] = "low" if q < 0.34 else "mid" if q < 0.67 else "high"

    # strongest hits (for impact cuts / speed-ramp landings)
    top = sorted(beat_info, key=lambda b: b["onset"], reverse=True)[:24]
    hits = sorted(round(b["t"], 3) for b in top)

    # first beat where real energy starts (useful for a cold open)
    thresh = np.percentile([b["energy_db"] for b in beat_info], 40)
    entry = next((b["t"] for b in beat_info if b["energy_db"] > thresh), 0.0)

    out = {
        "file": str(src), "duration": round(duration, 3), "tempo": round(tempo, 2),
        "beat_period": round(60 / tempo, 4), "downbeat_phase": phase,
        "energy_entry": entry, "sections": sections, "hits": hits, "beats": beat_info,
    }
    write_json(cfg["work"] / "music.json", out)

    try:
        import matplotlib  # optional
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        fig, ax = plt.subplots(figsize=(16, 3))
        ax.plot([b["t"] for b in beat_info], [b["energy_db"] for b in beat_info], lw=1)
        for s in sections:
            ax.axvline(s["start"], color="r", alpha=.5)
            ax.text(s["start"], ax.get_ylim()[1], s.get("level", ""), fontsize=8, va="top")
        fig.savefig(cfg["work"] / "music.png", dpi=90, bbox_inches="tight")
    except ImportError:
        pass

    print(f"tempo {tempo:.1f} BPM, {len(beats)} beats, {len(downbeats)} bars, entry at {entry:.2f}s")
    for s in sections:
        print(f"  {s['start']:7.2f}-{s['end']:7.2f}  {s['bars']:5.1f} bars  {s['energy_db']} dB  {s.get('level')}")


if __name__ == "__main__":
    main()
