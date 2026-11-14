"""Render handwritten chapter stamps ("17:39 · the garage") as transparent 1920x1080 PNG overlays.

Usage: uv run scripts/render_stamps.py "17:39 · the garage" "17:42 · into the city" ... [--font F]
Writes <movie>/AI/stills/stamp_01.png ...
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

sys.path.insert(0, str(Path(__file__).parent))
from common import load_project  # noqa: E402
from fonts import drawable  # noqa: E402

W, H = 1920, 1080


def stamp(text: str, font_path: str, size: int = 58) -> Image.Image:
    font = ImageFont.truetype(font_path, size)
    text = drawable(text, font_path)
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    x, y = 96, H - 96 - size
    shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).text((x + 2, y + 3), text, font=font, fill=(0, 0, 0, 170))
    img.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(4)))
    ImageDraw.Draw(img).text((x, y), text, font=font, fill=(250, 248, 242, 240))
    return img


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("labels", nargs="+")
    ap.add_argument("--font", default=str(Path.home() / "Library/Fonts/penoftruth.ttf"))
    args = ap.parse_args()
    out = load_project()["stills"]
    out.mkdir(exist_ok=True)
    for i, label in enumerate(args.labels, 1):
        p = out / f"stamp_{i:02d}.png"
        stamp(label, args.font).save(p)
        print(p)


if __name__ == "__main__":
    main()
