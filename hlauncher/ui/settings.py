"""Settings categories in the factory-style two-column layout."""
from dataclasses import dataclass
from datetime import datetime
from typing import Callable
from PIL import Image, ImageDraw
from sdk.hlauncher_sdk.fonts import font as interface_font
from sdk.hlauncher_sdk.theme import dither_rgb565
from .. import __version__
from . import home_art as art
from .chrome import render as render_chrome, scale_bounds, BACK_BOUNDS
from .home import caption, Frame


@dataclass(frozen=True)
class Row:
    title: str
    detail: str
    action: Callable


def render(rows, back, *, theme='Red', size=(720,480), clock=None,
           pressed=None, banner='', version='', show_clock=False):
    back_box=scale_bounds(BACK_BOUNDS,size)
    image=render_chrome(theme,child=True,clock=clock,pressed=pressed==back_box,show_clock=show_clock)
    d=ImageDraw.Draw(image)
    heading=caption('Settings',28)
    image.paste(heading,(24,72),heading)
    actions=[(back_box,back)]
    tiles = []
    for i,row in enumerate(rows):
        x=24+(i%2)*344;y=144+(i//2)*88
        tiles.append((row, (x,y,x+328,y+76), 29))
    for row, box, font_size in tiles:
        x, y, right, bottom = box
        width, height = right-x, bottom-y
        actual=scale_bounds(box,size)
        image.paste(art.settings_bar(theme,width,height),(x,y))
        if pressed==actual:
            overlay=Image.new('RGBA',(width,height),(255,255,255,25))
            image.paste(overlay,(x,y),overlay)
        title=caption(row.title,font_size)
        image.paste(title,(x+(width-title.width)//2,y+(height-title.height)//2),title)
        actions.append((actual,row.action))
    if version:d.text((24,452),'HLauncher '+version,font=interface_font(14),fill='#93929e',anchor='lt')
    if banner:
        text=str(banner);font=interface_font(14)
        while text and d.textlength(text,font=font)>430:text=text[:-1]
        d.text((696,452),text,font=font,fill='#efbd82',anchor='rt')
    if size!=(720,480):image=image.resize(size,Image.Resampling.LANCZOS)
    return Frame(image,actions,0)


def draw_launcher(launcher):
    rows=[Row('Plugins','',launcher.plugin_settings),
          Row('Appearance','',launcher.appearance_settings),
          Row('About','',launcher.about_settings),
          Row('Startup','',launcher.startup_settings),
          Row('System','',launcher.system_settings),
          Row('Audio','',launcher.audio_coming_soon)]
    frame=render(rows,launcher.home,theme=launcher.prefs.data['tile_color'],
                 size=(launcher.fb.w,launcher.fb.h),banner=launcher.banner,version=__version__,
                 pressed=launcher.pressed_box if launcher.press is not None else None,
                 show_clock=launcher.prefs.data['show_clock'])
    launcher.actions=frame.actions
    launcher.home_clock=datetime.now().strftime('%Y-%m-%d %H:%M')
    launcher.fb.image(dither_rgb565(frame.image))
