"""Shared helpers: project config, ffprobe, paths."""
from __future__ import annotations

import json
import subprocess
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load_project(path: str | None = None) -> dict:
    """Movie settings: explicit path, else $VLOG_PROJECT (e.g. projects/my-movie.json), else project.json."""
    import os
    path = path or os.environ.get("VLOG_PROJECT")
    p = Path(path) if path else ROOT / "project.json"
    if not p.is_absolute() and not p.exists():
        p = ROOT / p
    cfg = json.loads(p.read_text())
    work = ROOT / cfg["work_dir"]
    cfg["work"] = work                       # internal analysis cache (frames, shot logs...)
    for sub in ("clips", "frames", "sheets", "descriptions"):
        (work / sub).mkdir(parents=True, exist_ok=True)
    # everything you use (FCPXML, stills Final Cut links to, thumbnails, previews) goes next to the
    # footage, in <movie folder>/AI, unless project.json sets "output_dir"
    out = Path(cfg.get("output_dir") or Path(cfg["shots_dir"]).parent / "AI")
    cfg["out"], cfg["stills"] = out, out / "stills"
    cfg["stills"].mkdir(parents=True, exist_ok=True)
    return cfg


KIND_DIRS = {".fcpxml": "fcpxml", ".wav": "audio", ".m4a": "audio", ".mp4": "previews", ".mov": "previews",
             ".txt": "desc", ".md": "desc"}


def out_path(cfg: dict, p: str | Path) -> Path:
    """Relative output paths land in the movie's AI folder, sorted by kind:
    fcpxml/, audio/, previews/ (videos, preview images), thumbnails/, desc/ (title, description);
    stills/ is used directly.
    Absolute paths are used as given."""
    p = Path(p)
    if p.is_absolute():
        return p
    if len(p.parts) > 1:                        # caller already chose a subfolder
        dest = cfg["out"] / p
    else:
        kind = "thumbnails" if p.name.startswith("thumbnail") else KIND_DIRS.get(p.suffix.lower(), "previews")
        dest = cfg["out"] / kind / p
    dest.parent.mkdir(parents=True, exist_ok=True)
    return dest


def ffprobe(path: Path) -> dict:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)],
        check=True, capture_output=True, text=True,
    ).stdout
    data = json.loads(out)
    v = next((s for s in data["streams"] if s["codec_type"] == "video"), None)
    a = next((s for s in data["streams"] if s["codec_type"] == "audio"), None)
    info = {
        "file": str(path),
        "name": path.stem,
        "duration": float(data["format"]["duration"]),
        "creation_time": data["format"].get("tags", {}).get("creation_time"),
        "timecode": None,
    }
    if v:
        rate = Fraction(v.get("r_frame_rate", "0/1"))
        info.update(
            width=v["width"], height=v["height"], codec=v["codec_name"],
            fps_num=rate.numerator, fps_den=rate.denominator, fps=float(rate) if rate else None,
            nb_frames=int(v["nb_frames"]) if v.get("nb_frames") else None,
            pix_fmt=v.get("pix_fmt"), color_transfer=v.get("color_transfer"),
            color_primaries=v.get("color_primaries"),
        )
        info["timecode"] = v.get("tags", {}).get("timecode")
    if a:
        info.update(audio_rate=int(a["sample_rate"]), audio_channels=a["channels"])
    if not info["timecode"]:
        for s in data["streams"]:
            tc = s.get("tags", {}).get("timecode")
            if tc:
                info["timecode"] = tc
                break
    return info


def write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False))
