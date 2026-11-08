"""Shared stock-style background, header and navigation tab."""
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
from sdk.hlauncher_sdk.fonts import font as interface_font
from . import home_art as art

CLOCK_FONT=Path(__file__).parent/'assets/fonts/BarlowCondensed-SemiBold.ttf'
BACK_BOUNDS=(0,0,80,52)


@lru_cache(maxsize=4)
def clock_font(size):
    return ImageFont.truetype(str(CLOCK_FONT),size)


def scale_bounds(box,size):
    return tuple(round(value*size[i%2]/(720 if i%2==0 else 480)) for i,value in enumerate(box))


def render(theme, *, child=False, clock=None, pressed=False):
    image=art.background(theme,child).copy();d=ImageDraw.Draw(image)
    if child and pressed:
        overlay=Image.new('RGBA',(50,40))
        ImageDraw.Draw(overlay).rounded_rectangle((0,0,49,39),radius=6,fill=(255,255,255,30),
            outline=(*art.blend(art.accent(theme),(245,243,255),.65),180),width=2)
        image.paste(overlay,(8,6),overlay)
    title_font=interface_font(25)
    d.text((92,16),'HLauncher',font=title_font,fill='#f4f4f7',anchor='lt')
    credit_x=92+d.textlength('HLauncher',font=title_font)+12
    baseline=16-title_font.getbbox('HLauncher',anchor='ls')[1]
    d.text((credit_x,baseline),'by Evan Horsley',font=interface_font(14),fill='#9a9aa6',anchor='ls')
    d.text((698,8),clock or datetime.now().strftime('%-I:%M'),font=clock_font(39),fill='#f4f4f7',anchor='rt')
    return image
