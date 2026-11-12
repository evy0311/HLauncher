"""A host-owned Home button over external plugin frames."""

from functools import lru_cache

from PIL import Image, ImageDraw

from sdk.hlauncher_sdk.fonts import font
from ..display import encode
from .chrome import BACK_BOUNDS, render as chrome, scale_bounds


def camera_top(height):
    return round(BACK_BOUNDS[3] * height / 480)


@lru_cache(maxsize=12)
def camera_header(theme, width, height, *, show_clock=False, pressed=False, clock=None):
    header = chrome(theme, child=True, pressed=pressed, show_clock=show_clock, clock=clock)
    header = header.crop((0, 0, 720, BACK_BOUNDS[3]))
    return encode(header.resize((width, camera_top(height)), Image.Resampling.LANCZOS))


def back_box(width, height, *, camera=False):
    return scale_bounds(BACK_BOUNDS, (width, height)) if camera else home_box(width, height)


def home_box(width, height):
    return (0, 0, max(1, round(width * 92 / 720)), max(1, round(height * 42 / 480)))


@lru_cache(maxsize=8)
def home_pixels(width, height):
    image = Image.new('RGB', (width, height), '#201b26')
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, width - 1, height - 1), outline='#88798f')
    draw.text((width // 2, height // 2), 'Home', font=font(max(9, round(height * .52))),
              anchor='mm', fill='#ffffff')
    return encode(image)


def overlay(frame, width, height):
    _, _, w, h = home_box(width, height)
    button = home_pixels(w, h)
    output = bytearray(frame)
    for row in range(h):
        output[row * width * 2:row * width * 2 + w * 2] = button[row * w * 2:(row + 1) * w * 2]
    return bytes(output)
