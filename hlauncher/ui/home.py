"""Stock-era home screen only; no dependency on Bluetooth, plugins or framebuffer."""
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Callable
from PIL import Image, ImageDraw, ImageFont
from sdk.hlauncher_sdk.fonts import font as interface_font
from . import home_art as art
from .chrome import render as render_chrome

FONT = Path(__file__).parent/'assets/fonts/NotoSansJP.ttf'
LABEL_SIZE = 26
LABEL_WIDTH = .84


@lru_cache(maxsize=48)
def label_font(size):
    face=ImageFont.truetype(str(FONT),size)
    face.set_variation_by_axes([700])
    return face


@lru_cache(maxsize=128)
def caption(text, size):
    """Match the factory's compact proportions with antialiased label artwork."""
    scale=3;face=label_font(size*scale);left,top,right,bottom=face.getbbox(text)
    image=Image.new('RGBA',(right-left+6,bottom-top+6))
    ImageDraw.Draw(image).text((3-left,3-top),text,font=face,fill='#f5f4fb')
    return image.resize((round(image.width/scale*LABEL_WIDTH),round(image.height/scale)),Image.Resampling.LANCZOS)


@dataclass(frozen=True)
class Entry:
    label: str
    icon: str | Path
    action: Callable


@dataclass
class Frame:
    image: Image.Image
    actions: list
    page: int


def render(entries, *, theme='Red', size=(720,480), page=0, clock=None,
           banner='', change_page=None, pressed=None, show_clock=False):
    """Render from a canonical 720×480 layout and return matching touch regions.

    Up to four plugin entries per page, followed by persistent Audio/Settings.
    The ordinary three-plugin setup matches the approved five-tile mockup.
    """
    plugins=list(entries[:-2]);utilities=list(entries[-2:])
    pages=max(1,(len(plugins)+3)//4);page=max(0,min(page,pages-1))
    visible=plugins[page*4:page*4+4]+utilities
    image=render_chrome(theme,clock=clock,show_clock=show_clock);d=ImageDraw.Draw(image)
    sx,sy=size[0]/720,size[1]/480
    def bounds(box):return tuple(round(v*(sx if i%2==0 else sy)) for i,v in enumerate(box))
    actions=[]
    tw,th=art.TILE_SIZE
    for i,entry in enumerate(visible):
        # 28 px above/below the grid, measured from the bottom of the header.
        x=46+(i%3)*(tw+20);y=80+(i//3)*(th+20);box=(x,y,x+tw,y+th)
        shadow=art.tile_shadow(tw,th)
        image.paste(shadow,(x-8,y-5),shadow)
        surface=art.tile(theme)
        image.paste(surface,(x,y),surface)
        icon_size=80;icon_x=(tw-icon_size)//2;caption_y=th-40
        icon=art.glyph(entry.icon,icon_size)
        image.paste(icon,(x+icon_x,y+20),icon)
        # Mirror around the visible glyph's bottom, not its transparent padding.
        floor=icon.getbbox()[3]
        mirror_y=20+2*floor-icon.height+3
        # End the gradient six pixels above the caption; never squash the mirror.
        reflected=art.reflection(entry.icon,icon_size,max(1,caption_y-6-mirror_y))
        image.paste(reflected,(x+icon_x,y+mirror_y),reflected)
        text=entry.label;size_text=LABEL_SIZE
        while size_text>18 and d.textlength(text,font=label_font(size_text))*LABEL_WIDTH>tw-20:size_text-=1
        if d.textlength(text,font=label_font(size_text))*LABEL_WIDTH>tw-20:
            while text and d.textlength(text+'…',font=label_font(size_text))*LABEL_WIDTH>tw-20:text=text[:-1]
            text+='…'
        label=caption(text,size_text)
        image.paste(label,(x+(tw-label.width)//2,y+caption_y-1),label)
        actual=bounds(box)
        if pressed==actual:
            tint=art.blend(art.accent(theme),(245,243,255),.65)
            d.rounded_rectangle((x+2,y+2,x+tw-3,y+th-3),radius=8,outline=tint,width=2)
            # Small neutral highlight, not the other screens' oversized glow.
            wash=Image.new('RGBA',(tw-4,th-4),(255,255,255,20))
            mask=Image.new('L',wash.size);ImageDraw.Draw(mask).rounded_rectangle((0,0,tw-5,th-5),radius=8,fill=20)
            image.paste(wash,(x+2,y+2),mask)
        actions.append((actual,entry.action))
    if pages>1 and change_page is not None:
        for x,label,delta in ((470,'‹',-1),(598,'›',1)):
            b=(x,4,x+40,48)
            d.text((x+20,9),label,font=interface_font(28),fill='white',anchor='mt')
            actions.append((bounds(b),lambda delta=delta:change_page(delta)))
        d.text((554,20),f'{page+1} / {pages}',font=interface_font(16),fill='#c4c2d1',anchor='mt')
    if banner:
        text=banner
        font=interface_font(14)
        while text and d.textlength(text,font=font)>380:text=text[:-1]
        d.text((24,454),text,font=font,fill='#efbd82',anchor='lt')
    if size!=(720,480):image=image.resize(size,Image.Resampling.LANCZOS)
    return Frame(image,actions,page)


def draw_launcher(launcher):
    """Thin adapter; callbacks and enabled/default plugin policy remain core-owned."""
    entries=[Entry(m.name,m.icon or m.id,lambda pid=m.id:launcher.open_plugin(pid))
             for m in sorted(launcher.enabled(),key=lambda m:(not m.bundled,m.id!='carplay',m.name.casefold()))]
    entries += [Entry('Audio','audio',launcher.audio_page),Entry('Settings','settings',launcher.settings)]
    frame=render(entries,theme=launcher.prefs.data['tile_color'],size=(launcher.fb.w,launcher.fb.h),
                 page=launcher.page,banner=launcher.banner,change_page=launcher.change_page,
                 pressed=launcher.pressed_box if launcher.press is not None else None,show_clock=launcher.prefs.data['show_clock'])
    launcher.actions=frame.actions;launcher.page=frame.page
    launcher.home_clock=datetime.now().strftime('%Y-%m-%d %H:%M')
    # Preserve the existing RGB565 dithering path; home handles its own touch style.
    from sdk.hlauncher_sdk.theme import dither_rgb565
    launcher.fb.image(dither_rgb565(frame.image))
