"""Alternative looks for the photo recap (prints arriving one by one, then the story card).

Styles:
  polaroid   square instant prints with the time handwritten underneath, piling in the centre
  filmstrip  frames filling two strips of 35mm film, card taped below
  scrapbook  prints taped in a loose grid with masking tape, story on a torn notebook page

Each style writes <movie>/AI/stills/<style>_01..N.jpg (one per arriving photo) and
<style>_title.jpg (final frame with the card), plus out/recap-<style>.mp4 preview.

Usage: uv run scripts/render_recap_styles.py polaroid filmstrip scrapbook \
         --photos DSC02265 ... --captions 17h39 ... --title "title" "line" "line" "dd.mm.yy"
"""
from __future__ import annotations

import argparse
from functools import lru_cache
import random
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

sys.path.insert(0, str(Path(__file__).parent))
from common import load_project, out_path  # noqa: E402
from fonts import drawable  # noqa: E402
from render_table_stills import black_surface, note_card, place  # noqa: E402

W, H = 1920, 1080                                         # frame size; switch_aspect.set_canvas() changes it
INK = (28, 34, 64, 255)
PAPER = (246, 244, 239, 255)


# Card layout overrides (set by the editor): any notebook_page() argument, e.g.
# {"title_size": 84, "body_size": 42, "date_size": 32, "rule": 44, "gap": 30, "width": None}
NOTE_OPTS: dict = {}


@lru_cache(maxsize=64)
def _photo(path: str, w: int, h: int) -> Image.Image:
    im = Image.open(path)
    im.draft("RGB", (w * 2, h * 2))
    return ImageOps.fit(im.convert("RGB"), (w, h), Image.LANCZOS)


def load_photo(path: Path, w: int, h: int) -> Image.Image:
    return _photo(str(path), w, h).copy()


# ---------------------------------------------------------------- polaroid
def polaroid(photo: Path, caption: str, font: str) -> Image.Image:
    side, m, bottom = 380, 22, 96
    card = Image.new("RGBA", (side + 2 * m, side + m + bottom), PAPER)
    card.paste(load_photo(photo, side, side), (m, m))
    f = ImageFont.truetype(font, 46)
    txt = drawable(caption, font)
    ImageDraw.Draw(card).text((m + 14, side + m + 22), txt, font=f, fill=INK)
    return card


def style_polaroid(photos, captions, lines, font, rnd, surface):
    frames, placed = [], []
    for i, (p, c) in enumerate(zip(photos, captions)):
        card = polaroid(p, c, font)
        # loose pile: each print lands in its own zone around the centre so all stay readable
        zones = [(-560, -170), (-190, -230), (190, -210), (560, -150), (600, 190), (210, 230), (-200, 200), (-580, 170)]
        zx, zy = zones[i % len(zones)]
        zx = int(zx * W / 1920)                            # zones are designed for 16:9; squeeze for narrower frames
        ctr = (W // 2 + zx + rnd.randint(-40, 40), H // 2 + zy + rnd.randint(-30, 30))
        placed.append((card, ctr, rnd.uniform(-13, 13)))
        f = surface.copy()
        for c_, ctr_, a in placed:
            place(f, c_, ctr_, a)
        frames.append(f)
    final = frames[-1].copy()
    place(final, note_card(lines, font, width=700), (W // 2, H // 2 + 10), -3)
    return frames, final


# ---------------------------------------------------------------- film strip
def film_strip(n: int) -> tuple[Image.Image, list[tuple[int, int]]]:
    fw, fh, gap, pad = 400, 225, 28, 30
    w = n * fw + (n + 1) * gap
    h = fh + 2 * (pad + 34)
    strip = Image.new("RGBA", (w, h), (24, 18, 12, 255))          # dark film base
    d = ImageDraw.Draw(strip)
    for x in range(14, w - 20, 36):                                  # sprocket holes
        for y in (14, h - 34):
            d.rounded_rectangle((x, y, x + 20, y + 18), 4, fill=(232, 226, 210, 255))
    slots = [(gap + k * (fw + gap), pad + 34) for k in range(n)]
    for x, y in slots:
        d.rectangle((x - 2, y - 2, x + fw + 2, y + fh + 2), fill=(8, 6, 4, 255))
    return strip, slots


def style_filmstrip(photos, captions, lines, font, rnd, surface):
    per = (len(photos) + 1) // 2
    strips = [film_strip(per), film_strip(len(photos) - per)]
    rows = [(W // 2, 300, -2.0), (W // 2 + 30, 640, 1.5)]
    small = ImageFont.truetype(font, 30)
    frames = []
    filled: list[tuple[int, int, Image.Image]] = []
    for i, (p, c) in enumerate(zip(photos, captions)):
        r, k = (0, i) if i < per else (1, i - per)
        filled.append((r, k, load_photo(p, 400, 225)))
        f = surface.copy()
        for row, (strip, slots) in enumerate(strips):
            s = strip.copy()
            for rr, kk, img in filled:
                if rr == row:
                    s.paste(img, slots[kk])
            # frame numbers along the edge, like real film
            d = ImageDraw.Draw(s)
            for kk, (x, y) in enumerate(slots):
                d.text((x + 170, s.height - 30), f"{row * per + kk + 1:02d}", font=small, fill=(230, 160, 60, 255))
            cx, cy, ang = rows[row]
            place(f, s, (cx, cy), ang)
        frames.append(f)
    final = frames[-1].copy()
    place(final, note_card(lines, font, width=720), (W // 2 + 360, H - 175), -4)
    return frames, final


# ---------------------------------------------------------------- scrapbook
TAPE_COLORS = [(226, 212, 170), (150, 192, 232)]      # beige masking tape, blue washi tape


def tape(rnd: random.Random, color=(226, 212, 170), w=150, h=46) -> Image.Image:
    t = Image.new("RGBA", (w, h), (*color, 170))
    noise = (np.random.default_rng(rnd.randint(0, 10**6)).random((h, w)) * 30).astype(np.uint8)
    t.putalpha(Image.fromarray((150 + noise).astype(np.uint8)))
    d = ImageDraw.Draw(t)                                   # torn ends
    for y in range(0, h, 6):
        d.line((0, y, rnd.randint(0, 6), y + 3), fill=(0, 0, 0, 0), width=4)
        d.line((w, y, w - rnd.randint(0, 6), y + 3), fill=(0, 0, 0, 0), width=4)
    return t


def taped_print(photo: Path, rnd: random.Random) -> Image.Image:
    """Print with 1-3 strips of tape at random spots (corners, top, sides, bottom), random colour each."""
    w, h, b, m = 400, 225, 16, 90                            # m = room around the print for tape overhang
    pw, ph = w + 2 * b, h + 2 * b
    card = Image.new("RGBA", (pw + 2 * m, ph + 2 * m), (0, 0, 0, 0))
    base = Image.new("RGBA", (pw, ph), PAPER)
    base.paste(load_photo(photo, w, h), (b, b))
    card.paste(base, (m, m))
    spots = {  # (centre x, centre y, angle) relative to the print's top-left
        "tl": (0, 0, 35), "tr": (pw, 0, -35), "bl": (0, ph, -35), "br": (pw, ph, 35),
        "top": (pw / 2, 0, rnd.uniform(-8, 8)), "left": (0, ph / 2, 90 + rnd.uniform(-8, 8)),
        "right": (pw, ph / 2, 90 + rnd.uniform(-8, 8)), "bottom": (pw / 2, ph, rnd.uniform(-8, 8)),
    }
    choice = rnd.choice([["tl", "tr"], ["top"], ["tl", "br"], ["tr", "bl"], ["left", "right"], ["top", "bottom"], ["tl", "tr", "bottom"], ["tr"], ["tl"]])
    for k in choice:
        cx, cy, ang = spots[k]
        t = tape(rnd, rnd.choice(TAPE_COLORS), w=rnd.randint(120, 170)).rotate(ang + rnd.uniform(-6, 6), expand=True)
        card.alpha_composite(t, (int(m + cx - t.width / 2), int(m + cy - t.height / 2)))
    return card


def notebook_page(lines, font, width=None, rule=44, gap=None, pad_top=40, pad_bottom=22, verbose=False,
                  title_size=84, body_size=42, date_size=32) -> Image.Image:
    """Torn lined notebook page: title / text lines / date.
    Text lines sit on a uniform ruling (`rule` px); the date sits two rules below the last line;
    the title is placed so the visible gap title->text equals the gap text->date (measured on ink)."""
    o = {"width": width, "rule": rule, "gap": gap, "pad_top": pad_top, "pad_bottom": pad_bottom,
         "title_size": title_size, "body_size": body_size, "date_size": date_size, **NOTE_OPTS}
    width, rule, gap, pad_top, pad_bottom = o["width"], o["rule"], o["gap"], o["pad_top"], o["pad_bottom"]
    title, body, date = lines[0], lines[1:-1], lines[-1]
    tf, bf, df = (ImageFont.truetype(font, int(s)) for s in (o["title_size"], o["body_size"], o["date_size"]))
    title, date = drawable(title, font), drawable(date, font)
    body = [drawable(t, font) for t in body]
    if width is None:
        width = max([tf.getbbox(title)[2]] + [bf.getbbox(t)[2] for t in body]) + 108 + 56
    ink = lambda f, t: f.getbbox(t, anchor="ls")            # (x0, top<0, x1, bottom>0) around baseline  # noqa: E731
    base = [k * rule for k in range(len(body))]             # text baselines, relative
    cap = lambda f: -ink(f, "H")[1]                         # cap height: where letters visually start  # noqa: E731
    # perceived gaps (baseline of a block -> cap line of the next block), both equal to `gap`
    if gap is None:
        gap = 30
    date_b = base[-1] + gap + cap(df)                       # text -> date
    desc = lambda f: ink(f, "gp")[3]                       # descender depth  # noqa: E731
    # the big title's descenders eat into the gap: add half the extra depth so both gaps look equal
    title_b = (base[0] - cap(bf)) - (gap + (desc(tf) - desc(bf)) / 2)
    off = pad_top - (title_b + ink(tf, title)[1])           # shift everything so the title has top padding
    height = int(date_b + off + ink(df, date)[3] + pad_bottom)
    pg = Image.new("RGBA", (width, height), (250, 249, 244, 255))
    d = ImageDraw.Draw(pg)
    y = (base[0] + off) % rule                              # ruling aligned with the text baselines,
    last_rule = base[-1] + off                              # stops at the last text line: blank bottom margin
    while y <= last_rule + 0.5:
        if y > 6:
            d.line((0, y + 5, width, y + 5), fill=(150, 185, 220, 255), width=2)
        y += rule
    d.line((84, 0, 84, height), fill=(225, 120, 120, 255), width=2)          # margin
    d.text((108, title_b + off), title, font=tf, fill=INK, anchor="ls")
    for t, bl in zip(body, base):
        d.text((108, bl + off), t, font=bf, fill=INK, anchor="ls")
    d.text((width - 40, date_b + off), date, font=df, fill=INK, anchor="rs")
    if verbose:
        print(f"visible gap title->text = text->date = {gap:.0f}px")
    # torn top edge
    mask = Image.new("L", pg.size, 255)
    md = ImageDraw.Draw(mask)
    rnd = random.Random(3)
    pts = [(0, 0)] + [(x, rnd.randint(0, 12)) for x in range(0, width + 20, 20)] + [(width, 0)]
    md.polygon(pts, fill=0)
    pg.putalpha(mask)
    return pg


def style_scrapbook(photos, captions, lines, font, rnd, surface):
    """Prints evenly spaced on an oval around the notebook page, clockwise in story order."""
    import math
    n = len(photos)
    rx, ry = int(720 * W / 1920), 375                     # oval follows the frame width (16:9 or 4:3)
    frames, placed = [], []
    for i, p in enumerate(photos):
        ang = math.radians(-157.5 + i * 360 / n)          # start top-left, go clockwise
        ctr = (int(W / 2 + rx * math.cos(ang)), int(H / 2 + ry * math.sin(ang)))
        tilt = 2.5 if i % 2 else -2.5                      # gentle, regular - not random
        placed.append((taped_print(p, rnd), ctr, tilt))
        f = surface.copy()
        for c, ctr_, a in placed:
            place(f, c, ctr_, a)
        frames.append(f)
    final = frames[-1].copy()
    place(final, notebook_page(lines, font, width=720), (W // 2, H // 2 + 5), -1.5)
    return frames, final


def style_polaroid_note(photos, captions, lines, font, rnd, surface):
    """Polaroid pile, finished with the torn notebook page instead of the cream card."""
    frames, _ = style_polaroid(photos, captions, lines, font, rnd, surface)
    final = frames[-1].copy()
    place(final, notebook_page(lines, font), (W // 2, H // 2 + 10), -2)
    return frames, final


STYLES = {"polaroid-note": style_polaroid_note, "polaroid": style_polaroid, "filmstrip": style_filmstrip, "scrapbook": style_scrapbook}


def preview_mp4(frames: list[Path], final: Path, out: Path, per_frame=3, hold_s=2.5, fps=30):
    lst = out.with_suffix(".txt")
    with lst.open("w") as fh:
        for f in frames:
            fh.write(f"file '{f}'\nduration {per_frame / fps:.4f}\n")
        fh.write(f"file '{final}'\nduration {hold_s}\nfile '{final}'\n")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(lst), "-vf", f"fps={fps},scale=1280:-2",
                    "-pix_fmt", "yuv420p", "-c:v", "libx264", "-crf", "20", str(out)], check=True)
    lst.unlink()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("styles", nargs="+", choices=list(STYLES))
    ap.add_argument("--photos", nargs="+", required=True)
    ap.add_argument("--captions", nargs="+", required=True)
    ap.add_argument("--title", nargs="+", required=True)
    ap.add_argument("--font", default=str(Path.home() / "Library/Fonts/penoftruth.ttf"))
    ap.add_argument("--seed", type=int, default=11)
    args = ap.parse_args()
    cfg = load_project()
    st, out = cfg["stills"], cfg["out"]
    st.mkdir(exist_ok=True)
    pics = Path(cfg["pics_dir"])
    photos = [next(pics.glob(n + ".*")) for n in args.photos]
    surface = black_surface(args.seed).convert("RGBA")
    for name in args.styles:
        random.seed(args.seed)
        frames, final = STYLES[name](photos, args.captions, args.title, args.font, random.Random(args.seed), surface)
        paths = []
        for i, f in enumerate(frames, 1):
            p = st / f"{name}_{i:02d}.jpg"
            f.convert("RGB").save(p, quality=93)
            paths.append(p)
        fp = st / f"{name}_title.jpg"
        final.convert("RGB").save(fp, quality=93)
        preview_mp4(paths, fp, out_path(cfg, f"recap-{name}.mp4"))
        print(name, "->", fp, "+", out_path(cfg, f"recap-{name}.mp4"))


if __name__ == "__main__":
    main()
