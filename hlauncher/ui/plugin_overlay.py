"""A host-owned Home button over external plugin frames."""

from functools import lru_cache

from PIL import Image, ImageDraw

from sdk.hlauncher_sdk.fonts import font
from ..display import encode


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
