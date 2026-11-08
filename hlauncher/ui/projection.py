"""Launcher-owned CarPlay/Android Auto connection pages; never phone video."""
from datetime import datetime
from PIL import Image, ImageDraw
from sdk.hlauncher_sdk.fonts import font as interface_font
from sdk.hlauncher_sdk.theme import dither_rgb565
from . import home_art as art
from .chrome import render as render_chrome, scale_bounds, BACK_BOUNDS
from .home import caption, Frame

SOURCES={
    'carplay':('CarPlay','Connect your iPhone through the CarPlay USB adapter'),
    'android-auto':('Android Auto','Unlock your phone and approve Android Auto when prompted'),
}


def wrap_status(text, draw, font, width):
    lines=[];line=''
    for word in str(text)[:512].split():
        while draw.textlength(word,font=font)>width:
            if line:lines.append(line);line=''
            cut=1
            while cut<len(word) and draw.textlength(word[:cut+1],font=font)<=width:cut+=1
            lines.append(word[:cut]);word=word[cut:]
        joined=(line+' '+word).strip()
        if line and draw.textlength(joined,font=font)>width:
            lines.append(line);line=word
        else:line=joined
    if line:lines.append(line)
    if len(lines)>4:
        lines=lines[:4]
        while draw.textlength(lines[-1]+'…',font=font)>width:lines[-1]=lines[-1][:-1]
        lines[-1]+='…'
    return lines or ['Starting app…']


def render(source, status, back, *, theme='Blue', size=(720,480), clock=None, pressed=None):
    name,hint=SOURCES[source]
    back_box=scale_bounds(BACK_BOUNDS,size)
    image=render_chrome(theme,child=True,clock=clock,pressed=pressed==back_box)
    d=ImageDraw.Draw(image)
    icon=art.glyph(source,96);x=(720-icon.width)//2;y=88
    image.paste(icon,(x,y),icon)
    floor=icon.getbbox()[3];mirror_y=y+2*floor-icon.height+3
    mirror=art.reflection(source,96,max(1,207-mirror_y))
    image.paste(mirror,(x,mirror_y),mirror)
    title=caption(name,30)
    image.paste(title,((720-title.width)//2,218),title)
    panel=art.tile(theme,592,112)
    image.paste(panel,(64,284),panel)
    font=interface_font(19)
    lines=wrap_status(status or 'Starting '+name+'…',d,font,548)
    start=340-(len(lines)*24)/2
    for index,line in enumerate(lines):
        d.text((360,start+index*24),line,font=font,fill='#eff0f6',anchor='mt')
    d.text((360,425),hint,font=interface_font(17),fill='#b6b5c1',anchor='mt')
    if size!=(720,480):image=image.resize(size,Image.Resampling.LANCZOS)
    return Frame(image,[(back_box,back)],0)


def draw_launcher(launcher):
    frame=render(launcher.host.active,launcher.host.status(),launcher.home,
                 theme=launcher.prefs.data['tile_color'],size=(launcher.fb.w,launcher.fb.h),
                 pressed=launcher.pressed_box if launcher.press is not None else None)
    launcher.actions=frame.actions
    launcher.home_clock=datetime.now().strftime('%Y-%m-%d %H:%M')
    launcher.fb.image(dither_rgb565(frame.image))
