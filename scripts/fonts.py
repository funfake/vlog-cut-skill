"""Font helpers: replace characters a font draws blank (e.g. accents in some handwriting fonts)."""
from __future__ import annotations

import unicodedata
from functools import lru_cache

from PIL import ImageFont


@lru_cache(maxsize=None)
def _blank(font_path: str, ch: str) -> bool:
    if ch.isspace():
        return False
    f = ImageFont.truetype(font_path, 48)
    return f.getmask(ch).getbbox() is None


def drawable(text: str, font_path: str) -> str:
    """Swap every character the font can't draw for its unaccented base letter (é -> e)."""
    out = []
    for ch in text:
        if _blank(font_path, ch):
            base = unicodedata.normalize("NFKD", ch)[0]
            out.append(base if not _blank(font_path, base) else "")
        else:
            out.append(ch)
    return "".join(out)
