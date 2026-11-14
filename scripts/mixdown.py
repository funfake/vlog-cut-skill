"""Render the audio of an FCPXML timeline with ffmpeg and measure loudness (EBU R128).

Reads spine clips (camera sound) and connected audio (music, sound effects) with their
volume, including fade keyframes, and mixes them like Final Cut would (approximately:
no audio effects, no roles). Prints integrated loudness (LUFS), loudness range and
true peak per stem and for the full mix.

Usage: uv run scripts/mixdown.py file.fcpxml [--project NAME] [--out mix.wav]
"""
from __future__ import annotations

import argparse
import re
import subprocess
import tempfile
from fractions import Fraction
from pathlib import Path
from urllib.parse import unquote
import sys
sys.path.insert(0, str(Path(__file__).parent))
from common import load_project, out_path  # noqa: E402
import xml.etree.ElementTree as ET


def t(s):
    if not s:
        return 0.0
    s = s.rstrip("s")
    return float(Fraction(s)) if s else 0.0


def volume(el):
    """(static dB, [(local_time, dB), ...]) from an element's adjust-volume."""
    av = el.find("adjust-volume")
    if av is None:
        return 0.0, []
    if av.get("amount"):
        return float(av.get("amount").replace("dB", "")), []
    kfs = [(t(k.get("time")), float(k.get("value").replace("dB", ""))) for k in av.iter("keyframe")]
    return 0.0, kfs


def items(root, project=None):
    res = {}
    for r in root.find("resources"):
        mr = r.find("media-rep")
        if mr is not None:
            res[r.get("id")] = (unquote(mr.get("src").replace("file://", "")), r.get("hasAudio") == "1", t(r.get("start")))
    proj = next(p for p in root.iter("project") if not project or p.get("name") == project)
    out = []
    for e in proj.find("sequence").find("spine"):
        if e.tag == "transition":
            continue
        off, start, dur = t(e.get("offset")), t(e.get("start")), t(e.get("duration"))
        if e.tag == "asset-clip" and e.get("ref") in res and res[e.get("ref")][1]:
            db, kf = volume(e)
            path, _, a0 = res[e.get("ref")]
            out.append(("camera", path, start - a0, dur, off, db, kf, start))
        for ch in e:
            if ch.tag == "asset-clip" and ch.get("ref") in res and res[ch.get("ref")][1] and ch.get("lane", "0").startswith("-"):
                cdur = t(ch.get("duration"))
                coff = off + t(ch.get("offset")) - start
                db, kf = volume(ch)
                path, _, a0 = res[ch.get("ref")]
                stem = "music" if (ch.get("name") or "").startswith("music") else "sfx"
                out.append((stem, path, t(ch.get("start")) - a0, cdur, coff, db, kf, t(ch.get("start"))))
    return out


def gain_filter(db, kf, src_start_local, dur):
    if not kf:
        return f"volume={db}dB"
    # piecewise-linear dB envelope, keyframe times are in the clip's local (source) time
    pts = sorted((k - src_start_local, v) for k, v in kf)
    expr = f"{pts[0][1]}"
    for (t0, v0), (t1, v1) in zip(pts, pts[1:]):
        expr = f"if(between(t,{t0:.4f},{t1:.4f}),{v0}+({v1}-{v0})*(t-{t0:.4f})/{max(t1 - t0, 1e-4):.4f},{expr})"
    expr = f"if(gte(t,{pts[-1][0]:.4f}),{pts[-1][1]},{expr})"
    return f"volume='pow(10,({expr})/20)':eval=frame"


def render(parts, out_wav: Path, total: float):
    if not parts:
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"anullsrc=r=48000:cl=stereo", "-t", str(total), str(out_wav)], check=True)
        return
    args, filt = [], []
    for i, (_, path, src, dur, off, db, kf, local0) in enumerate(parts):
        args += ["-ss", f"{max(0.0, src):.4f}", "-t", f"{dur:.4f}", "-i", path]
        filt.append(f"[{i}:a]aformat=sample_rates=48000:channel_layouts=stereo,asetpts=PTS-STARTPTS,"
                    f"{gain_filter(db, kf, local0, dur)},adelay={int(off * 1000)}:all=1[a{i}]")
    mix = "".join(f"[a{i}]" for i in range(len(parts)))
    filt.append(f"{mix}amix=inputs={len(parts)}:normalize=0:dropout_transition=0,atrim=0:{total:.3f}[out]")
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as fs:
        fs.write(";\n".join(filt))
    subprocess.run(["ffmpeg", "-v", "error", "-y", *args, "-/filter_complex", fs.name, "-map", "[out]", str(out_wav)], check=True)


def loudness(wav: Path) -> dict:
    r = subprocess.run(["ffmpeg", "-nostats", "-i", str(wav), "-af", "ebur128=peak=true", "-f", "null", "-"],
                       capture_output=True, text=True).stderr
    summ = r[r.rfind("Summary:"):]
    get = lambda k: float(re.search(k + r":\s+(-?[\d.]+|-inf)", summ).group(1).replace("-inf", "-99"))  # noqa: E731
    return {"I": get("I"), "LRA": get("LRA"), "TP": get("Peak")}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("file")
    ap.add_argument("--project")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    root = ET.parse(args.file).getroot()
    proj = next(p for p in root.iter("project") if not args.project or p.get("name") == args.project)
    total = t(proj.find("sequence").get("duration"))
    parts = items(root, args.project)
    with tempfile.TemporaryDirectory() as td:
        for stem in ("music", "camera", "sfx", None):
            sel = [p for p in parts if stem is None or p[0] == stem]
            wav = out_path(load_project(), args.out) if (stem is None and args.out) else Path(td) / f"{stem or 'mix'}.wav"
            render(sel, wav, total)
            L = loudness(wav)
            print(f"{(stem or 'FULL MIX'):9s} {len(sel):3d} clips   integrated {L['I']:6.1f} LUFS   range {L['LRA']:4.1f} LU   true peak {L['TP']:5.1f} dBTP")


if __name__ == "__main__":
    main()
