"""Shared, bundled Roboto faces for launcher and plugin UI."""
from functools import lru_cache
from pathlib import Path
from PIL import ImageFont

FONT_PATH = Path(__file__).parent / 'assets' / 'fonts' / 'Roboto.ttf'


@lru_cache(maxsize=96)
def font(size, weight=400):
    face = ImageFont.truetype(str(FONT_PATH), max(1, round(size)))
    # Roboto's axes are weight, then width. Keep the normal width for readability.
    face.set_variation_by_axes([max(100, min(900, weight)), 100])
    return face
