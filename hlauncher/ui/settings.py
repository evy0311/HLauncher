"""Main Settings menu: stock-style thin bars, shared header, existing actions."""
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


def render(rows, back, *, theme='Blue', size=(720,480), clock=None,
           pressed=None, banner='', version=''):
    back_box=scale_bounds(BACK_BOUNDS,size)
    image=render_chrome(theme,child=True,clock=clock,pressed=pressed==back_box)
    d=ImageDraw.Draw(image)
    heading=caption('Settings',28)
    image.paste(heading,(24,72),heading)
    actions=[(back_box,back)]
    surface=art.tile(theme,672,44,radius=6)
    for i,row in enumerate(rows):
        y=112+i*52;box=(24,y,696,y+44);actual=scale_bounds(box,size)
        image.paste(surface,(24,y),surface)
        if pressed==actual:
            overlay=Image.new('RGBA',(672,44))
            ImageDraw.Draw(overlay).rounded_rectangle((0,0,671,43),radius=6,
                fill=(255,255,255,24),outline=(*art.blend(art.accent(theme),(245,243,255),.65),180),width=2)
            image.paste(overlay,(24,y),overlay)
        title=caption(row.title,24)
        image.paste(title,(42,y+(44-title.height)//2),title)
        detail=str(row.detail);font=interface_font(16)
        available=648-(42+title.width+24)
        if d.textlength(detail,font=font)>available:
            while detail and d.textlength(detail+'…',font=font)>available:detail=detail[:-1]
            detail+='…'
        d.text((648,y+22),detail,font=font,fill='#c2c0cc',anchor='rm')
        d.line([(672,y+16),(678,y+22),(672,y+28)],fill='#ddd9e9',width=2,joint='curve')
        actions.append((actual,row.action))
    if version:d.text((24,452),'HLauncher '+version,font=interface_font(14),fill='#93929e',anchor='lt')
    if banner:
        text=str(banner);font=interface_font(14)
        while text and d.textlength(text,font=font)>430:text=text[:-1]
        d.text((696,452),text,font=font,fill='#efbd82',anchor='rt')
    if size!=(720,480):image=image.resize(size,Image.Resampling.LANCZOS)
    return Frame(image,actions,0)


def draw_launcher(launcher):
    selected=launcher.prefs.data['default_plugin']
    manifest=launcher.manifests.get(selected)
    default=manifest.name if manifest and launcher.prefs.enabled(manifest) else 'Launcher'
    # An older Pi deployment may still expose the direct diagnostics destination.
    system=getattr(launcher,'system_settings',launcher.system_diagnostics)
    rows=[Row('Plugins','Apps and CarPlay picture',launcher.plugin_settings),
          Row('OBD Gauges','Bluetooth LE adapter',launcher.obd_settings),
          Row('Tile color',launcher.prefs.data['tile_color'],launcher.tile_colors),
          Row('Start with',default,launcher.cycle_default),
          Row('Audio & EQ','HDMI audio',launcher.audio_page),
          Row('System','Setup and diagnostics' if hasattr(launcher,'system_settings') else 'Connections and diagnostics',system)]
    frame=render(rows,launcher.home,theme=launcher.prefs.data['tile_color'],
                 size=(launcher.fb.w,launcher.fb.h),banner=launcher.banner,version=__version__,
                 pressed=launcher.pressed_box if launcher.press is not None else None)
    launcher.actions=frame.actions
    launcher.home_clock=datetime.now().strftime('%Y-%m-%d %H:%M')
    launcher.fb.image(dither_rgb565(frame.image))
