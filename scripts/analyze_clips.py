"""Measure every clip: motion, direction, shake, light, colour, sharpness, sound energy.

Writes work/<project>/clips/<clip>.json, keyframes for the vision model and a
contact sheet per clip. Read-only on the source media.

Usage: uv run scripts/analyze_clips.py [--fps 4] [--only C1102]
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).parent))
from common import ffprobe, load_project, write_json  # noqa: E402

W, H = 320, 180          # analysis resolution
KEY_EVERY = 2.0          # seconds between keyframes for the vision model


def read_frames(path: Path, fps: float) -> np.ndarray:
    cmd = ["ffmpeg", "-v", "error", "-i", str(path), "-vf", f"fps={fps},scale={W}:{H}",
           "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
    raw = subprocess.run(cmd, check=True, capture_output=True).stdout
    return np.frombuffer(raw, np.uint8).reshape(-1, H, W, 3)


def read_audio_rms(path: Path, hop: float) -> list[float]:
    cmd = ["ffmpeg", "-v", "error", "-i", str(path), "-ac", "1", "-ar", "16000", "-f", "f32le", "-"]
    raw = subprocess.run(cmd, check=True, capture_output=True).stdout
    a = np.frombuffer(raw, np.float32)
    n = int(16000 * hop)
    if len(a) < n:
        return []
    a = a[: len(a) // n * n].reshape(-1, n)
    rms = np.sqrt((a ** 2).mean(axis=1) + 1e-12)
    return [round(float(20 * np.log10(r + 1e-9)), 1) for r in rms]


def frame_stats(rgb: np.ndarray) -> dict:
    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV).astype(np.float32)
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    r, g, b = (rgb[..., i].astype(np.float32) for i in range(3))
    bright = hsv[..., 2] / 255
    return {
        "brightness": round(float(bright.mean()), 3),
        "contrast": round(float(gray.std() / 255), 3),
        "saturation": round(float(hsv[..., 1].mean() / 255), 3),
        "warmth": round(float((r - b).mean() / 255), 3),          # >0 warm (sodium/golden), <0 cool (blue hour/LED)
        "highlights": round(float((bright > 0.9).mean()), 3),     # bright points: street lights, neon, headlights
        "sharpness": round(float(cv2.Laplacian(gray, cv2.CV_64F).var()), 1),
        "dominant_hue": int(np.median(hsv[..., 0][hsv[..., 1] > 60])) if (hsv[..., 1] > 60).any() else None,
    }


def flow_stats(prev: np.ndarray, cur: np.ndarray) -> dict:
    p = cv2.cvtColor(prev, cv2.COLOR_RGB2GRAY)
    c = cv2.cvtColor(cur, cv2.COLOR_RGB2GRAY)
    f = cv2.calcOpticalFlowFarneback(p, c, None, 0.5, 3, 15, 3, 5, 1.2, 0)
    dx, dy = f[..., 0], f[..., 1]
    mag = np.sqrt(dx ** 2 + dy ** 2)
    ys, xs = np.mgrid[0:H, 0:W]
    rx, ry = xs - W / 2, ys - H / 2
    norm = np.sqrt(rx ** 2 + ry ** 2) + 1e-6
    radial = (dx * rx + dy * ry) / norm                          # >0: things expand outward = moving forward
    return {
        "motion": round(float(mag.mean()), 2),
        "pan_x": round(float(np.median(dx)), 2),                  # global horizontal motion (camera pan / lateral travel)
        "pan_y": round(float(np.median(dy)), 2),
        "forward": round(float(radial.mean()), 2),
    }


def contact_sheet(frames: list[tuple[float, np.ndarray]], out: Path, title: str) -> None:
    cols = 6
    tw, th = 240, 135
    rows = max(1, (len(frames) + cols - 1) // cols)
    sheet = Image.new("RGB", (cols * tw, rows * (th + 16) + 22), (20, 20, 20))
    d = ImageDraw.Draw(sheet)
    d.text((6, 4), title, fill=(255, 255, 255))
    for i, (t, img) in enumerate(frames):
        x, y = (i % cols) * tw, 22 + (i // cols) * (th + 16)
        sheet.paste(Image.fromarray(img).resize((tw, th)), (x, y))
        d.text((x + 4, y + th + 1), f"{t:5.1f}s", fill=(200, 200, 200))
    sheet.save(out, quality=85)


def analyze(path: Path, work: Path, fps: float) -> str:
    info = ffprobe(path)
    frames = read_frames(path, fps)
    hop = 1 / fps
    samples = []
    for i, fr in enumerate(frames):
        s = {"t": round(i * hop, 3), **frame_stats(fr)}
        if i > 0:
            s.update(flow_stats(frames[i - 1], fr))
        samples.append(s)
    if len(samples) > 1:
        samples[0].update({k: samples[1][k] for k in ("motion", "pan_x", "pan_y", "forward")})

    # shake = jitter of global motion around its smoothed trend
    gx = np.array([s.get("pan_x", 0) for s in samples])
    gy = np.array([s.get("pan_y", 0) for s in samples])
    k = max(1, min(len(gx), max(3, int(fps * 1.5))))   # very short clips: smaller window
    smooth = lambda a: np.convolve(a, np.ones(k) / k, mode="same")  # noqa: E731
    shake = np.sqrt((gx - smooth(gx)) ** 2 + (gy - smooth(gy)) ** 2)
    for s, v in zip(samples, shake):
        s["shake"] = round(float(v), 2)

    audio = read_audio_rms(path, hop)
    for s, a in zip(samples, audio):
        s["audio_db"] = a

    # scene cuts inside the clip (big frame-to-frame histogram change)
    cuts = []
    for i in range(1, len(frames)):
        h1 = cv2.calcHist([frames[i - 1]], [0, 1, 2], None, [8, 8, 8], [0, 256] * 3)
        h2 = cv2.calcHist([frames[i]], [0, 1, 2], None, [8, 8, 8], [0, 256] * 3)
        if cv2.compareHist(h1, h2, cv2.HISTCMP_BHATTACHARYYA) > 0.45:
            cuts.append(samples[i]["t"])

    # keyframes for the vision model + contact sheet
    kdir = work / "frames" / path.stem
    kdir.mkdir(parents=True, exist_ok=True)
    step = max(1, int(round(KEY_EVERY * fps)))
    keys = []
    for i in range(0, len(frames), step):
        t = samples[i]["t"]
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{t + 0.05:.3f}", "-i", str(path),
                        "-frames:v", "1", "-vf", "scale=768:-2", "-q:v", "3",
                        str(kdir / f"{path.stem}_{t:06.2f}.jpg")], check=True)
        keys.append((t, frames[i]))
    contact_sheet(keys, work / "sheets" / f"{path.stem}.jpg",
                  f"{path.stem}  {info['duration']:.1f}s  {info.get('creation_time') or ''}")

    def avg(key):
        vals = [s[key] for s in samples if s.get(key) is not None]
        return round(float(np.mean(vals)), 3) if vals else None

    summary = {k: avg(k) for k in ("brightness", "warmth", "saturation", "highlights", "sharpness",
                                   "motion", "pan_x", "forward", "shake", "audio_db")}
    write_json(work / "clips" / f"{path.stem}.json",
               {"info": info, "sample_fps": fps, "summary": summary, "cuts": cuts,
                "keyframes": [round(t, 3) for t, _ in keys], "samples": samples})
    return f"{path.stem}: {info['duration']:.1f}s motion={summary['motion']} shake={summary['shake']} bright={summary['brightness']}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fps", type=float, default=4)
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--jobs", type=int, default=6)
    ap.add_argument("--force", action="store_true", help="re-analyse clips that already have results")
    args = ap.parse_args()
    cfg = load_project()
    clips = sorted(Path(cfg["shots_dir"]).glob("*.MP4")) + sorted(Path(cfg["shots_dir"]).glob("*.mov"))
    if args.only:
        clips = [c for c in clips if c.stem in args.only]
    elif not args.force:
        clips = [c for c in clips if not (cfg["work"] / "clips" / f"{c.stem}.json").exists()]
    with ProcessPoolExecutor(args.jobs) as ex:
        for line in ex.map(analyze, clips, [cfg["work"]] * len(clips), [args.fps] * len(clips)):
            print(line, flush=True)


if __name__ == "__main__":
    main()
