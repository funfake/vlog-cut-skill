"""Render photo stills as prints dropped onto a table, one image per photo, piling up.

Each output frame (1920x1080) shows a dark wooden tabletop with the photos so far as
white-bordered prints, slightly rotated, with soft shadows; the newest print lands on top.

Usage: uv run scripts/render_table_stills.py DSC02267 DSC02268 DSC02269 DSC02270 [--seed 7]
Writes <movie>/AI/stills/table_<photo>.jpg (use "photo": "table_DSC02267" in a plan).
"""
from __future__ import annotations

import argparse
import random
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageFilter

sys.path.insert(0, str(Path(__file__).parent))
from common import load_project  # noqa: E402
from fonts import drawable  # noqa: E402

W, H = 1920, 1080


def set_canvas(w: int, h: int) -> None:
    """Render every still (surface, recap, stamps) at w x h instead of 1920x1080 (e.g. 1440x1080 for 4:3)."""
    import sys as _s
    for name in ("render_table_stills", "render_recap_styles", "render_stamps"):
        m = _s.modules.get(name)
        if m is not None:
            m.W, m.H = w, h


def smooth_noise(rng: np.random.Generator, scale: int, sx: float = 1, sy: float = 1) -> np.ndarray:
    n = rng.standard_normal((H // scale + 2, W // scale + 2)).astype(np.float32)
    n = cv2.resize(n, (W, H), interpolation=cv2.INTER_CUBIC)
    return cv2.GaussianBlur(n, (0, 0), sigmaX=scale * sx, sigmaY=scale * sy)


def wood_table(seed: int) -> Image.Image:
    rng = np.random.default_rng(seed)
    y, x = np.mgrid[0:H, 0:W].astype(np.float32)
    plank_h = 230
    plank = (y // plank_h).astype(int)
    img = np.zeros((H, W, 3), np.float32)
    base = np.array([58, 38, 26], np.float32)        # dark walnut (RGB)
    light = np.array([96, 64, 42], np.float32)
    warp = smooth_noise(rng, 40, 4, 0.5) * 18          # slow wandering of the grain lines
    blotch = smooth_noise(rng, 90, 3, 1.0)              # broad colour variation
    streak = smooth_noise(rng, 1, 30, 0.25)             # long thin fibres along the plank
    for p in range(plank.max() + 1):
        m = plank == p
        phase = rng.uniform(0, 100)
        grain = np.sin((y + warp + phase) * 0.55 + np.sin(x * 0.002 + phase) * 6)
        grain = np.sign(grain) * np.abs(grain) ** 3      # thin dark lines, not even bands
        t = 0.55 + 0.10 * grain + 0.25 * np.clip(blotch / (np.abs(blotch).max() + 1e-6), -1, 1) \
            + 0.12 * np.clip(streak / (np.abs(streak).max() + 1e-6), -1, 1)
        tone = rng.uniform(0.85, 1.12)
        for c in range(3):
            img[..., c][m] = ((base[c] + (light[c] - base[c]) * t) * tone)[m]
        seam = (np.abs(y - (p + 1) * plank_h) < 2)
        img[seam] *= 0.45
    # warm pool of light from upper left + vignette
    cx, cy = W * 0.38, H * 0.35
    d = np.sqrt(((x - cx) / W) ** 2 + ((y - cy) / H) ** 2)
    img *= (1.25 - 0.9 * d)[..., None]
    return Image.fromarray(np.clip(img, 0, 255).astype(np.uint8))


def black_surface(seed: int) -> Image.Image:
    """Near-black textured surface (like black card / slate): fine grain, soft mottling, light pool."""
    rng = np.random.default_rng(seed)
    y, x = np.mgrid[0:H, 0:W].astype(np.float32)
    grain = rng.standard_normal((H, W)).astype(np.float32)
    grain = cv2.GaussianBlur(grain, (0, 0), 0.7)
    fibre = smooth_noise(rng, 1, 6, 1.2)
    mottle = smooth_noise(rng, 70, 2, 2)
    norm = lambda a: a / (np.abs(a).max() + 1e-6)  # noqa: E731
    v = 16 + 5.0 * norm(grain) + 3.0 * norm(fibre) + 5.0 * norm(mottle)
    cx, cy = W * 0.5, H * 0.42
    d = np.sqrt(((x - cx) / W) ** 2 + ((y - cy) / H) ** 2)
    v *= 1.35 - 1.1 * d                                   # soft light from above, dark corners
    rgb = np.stack([v * 1.0, v * 0.98, v * 0.96], axis=-1)  # a hint of warmth
    return Image.fromarray(np.clip(rgb, 0, 255).astype(np.uint8))


def surface(seed: int, kind: str) -> Image.Image:
    return wood_table(seed) if kind == "wood" else black_surface(seed)


def make_print(photo: Path, width: int) -> Image.Image:
    im = Image.open(photo)
    im.draft("RGB", (width * 2, width * 2))
    im = im.convert("RGB")
    h = round(width * im.height / im.width)
    im = im.resize((width, h), Image.LANCZOS)
    border = round(width * 0.035)
    card = Image.new("RGB", (width + 2 * border, h + 2 * border), (246, 244, 239))
    card.paste(im, (border, border))
    return card.convert("RGBA")


def place(canvas: Image.Image, card: Image.Image, center: tuple[int, int], angle: float) -> None:
    rot = card.rotate(angle, resample=Image.BICUBIC, expand=True)
    alpha = rot.split()[-1]
    shadow = Image.new("RGBA", rot.size, (0, 0, 0, 0))
    shadow.putalpha(alpha.point(lambda v: int(v * 0.55)))
    shadow = shadow.filter(ImageFilter.GaussianBlur(14))
    x = center[0] - rot.width // 2
    y = center[1] - rot.height // 2
    canvas.alpha_composite(shadow, (x + 12, y + 16))
    canvas.alpha_composite(rot, (x, y))


# recap: prints land clockwise around a centre note card, in story order
RECAP_SLOTS = [(380, 215), (960, 190), (1540, 215), (1590, 540),
               (1540, 870), (960, 890), (380, 870), (330, 540)]
DEFAULT_FONT = "/System/Library/Fonts/Supplemental/Bradley Hand Bold.ttf"


def note_card(lines: list[str], font_path: str, width: int = 780) -> Image.Image:
    """Cream card with handwritten lines; first line is the title."""
    from PIL import ImageDraw, ImageFont
    lines = [drawable(t, font_path) for t in lines]
    sizes = [84] + [44] * (len(lines) - 2) + [36] if len(lines) > 1 else [84]
    fonts = [ImageFont.truetype(font_path, s) for s in sizes]
    pad, gap = 48, 14
    heights = [f.getbbox(t)[3] - f.getbbox(t)[1] for f, t in zip(fonts, lines)]
    height = pad * 2 + sum(heights) + gap * (len(lines) - 1) + 24
    card = Image.new("RGBA", (width, height), (247, 243, 232, 255))
    d = ImageDraw.Draw(card)
    rnd = random.Random(len("".join(lines)))
    y = pad
    ink = (28, 34, 64, 255)                       # blue-black pen
    for i, (f, t, h) in enumerate(zip(fonts, lines, heights)):
        x = pad + rnd.randint(-6, 10)
        if i == len(lines) - 1 and len(lines) > 1:      # date line, bottom right
            x = width - pad - (f.getbbox(t)[2] - f.getbbox(t)[0])
            y += 18
        d.text((x, y - f.getbbox(t)[1]), t, font=f, fill=ink)
        if i == 0:                                       # pen underline under the title
            tw = f.getbbox(t)[2] - f.getbbox(t)[0]
            d.line([(x, y + h + 10), (x + tw * 0.62, y + h + 6)], fill=ink, width=3)
            y += 12
        y += h + gap
    return card


def render_recap(cfg, photos: list[str], lines: list[str], font: str, seed: int, width: int, kind: str = "black") -> None:
    out_dir = cfg["stills"]
    out_dir.mkdir(exist_ok=True)
    rnd = random.Random(seed)
    table = surface(seed, kind).convert("RGBA")
    pics = Path(cfg["pics_dir"])
    placed = []
    for i, name in enumerate(photos):
        card = make_print(next(pics.glob(name + ".*")), width)
        sx, sy = RECAP_SLOTS[i % len(RECAP_SLOTS)]
        placed.append((card, (sx + rnd.randint(-25, 25), sy + rnd.randint(-20, 20)), rnd.uniform(-7, 7)))
        frame = table.copy()
        for c, ctr, ang in placed:
            place(frame, c, ctr, ang)
        out = out_dir / f"recap_{i + 1:02d}.jpg"
        frame.convert("RGB").save(out, quality=94)
        print(out)
    frame = table.copy()
    for c, ctr, ang in placed:
        place(frame, c, ctr, ang)
    place(frame, note_card(lines, font), (W // 2, H // 2 + 10), -2.5)
    out = out_dir / "recap_title.jpg"
    frame.convert("RGB").save(out, quality=94)
    print(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("photos", nargs="+")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--width", type=int, default=980, help="print width in pixels (without border)")
    ap.add_argument("--recap", action="store_true",
                    help="lay prints out clockwise (max 8) and finish with a handwritten note card")
    ap.add_argument("--title", nargs="+", default=["driving in paris"],
                    help="note card lines: title, story lines..., date (last line goes bottom right)")
    ap.add_argument("--font", default=DEFAULT_FONT)
    ap.add_argument("--surface", choices=["black", "wood"], default="black")
    args = ap.parse_args()
    cfg = load_project()
    if args.recap:
        render_recap(cfg, args.photos, args.title, args.font, args.seed, min(args.width, 500), args.surface)
        return
    out_dir = cfg["stills"]
    out_dir.mkdir(exist_ok=True)
    rnd = random.Random(args.seed)
    table = surface(args.seed, args.surface).convert("RGBA")
    pics = Path(cfg["pics_dir"])

    placed = []
    for name in args.photos:
        src = next(pics.glob(name + ".*"))
        card = make_print(src, args.width)
        # land near the centre, each one a little off from the last
        center = (W // 2 + rnd.randint(-170, 170), H // 2 + rnd.randint(-90, 90))
        angle = rnd.uniform(-7, 7)
        placed.append((card, center, angle))
        frame = table.copy()
        for c, ctr, ang in placed:
            place(frame, c, ctr, ang)
        out = out_dir / f"table_{name}.jpg"
        frame.convert("RGB").save(out, quality=94)
        print(out)


if __name__ == "__main__":
    main()
