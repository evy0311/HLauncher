"""Shared stock-radio surfaces for launcher-owned control pages."""
from datetime import datetime
from PIL import Image, ImageDraw
from sdk.hlauncher_sdk.fonts import font
from sdk.hlauncher_sdk.theme import dither_rgb565
from . import home_art as art
from .chrome import render as chrome, scale_bounds, BACK_BOUNDS
from .home import caption, Frame


class Page:
    def __init__(self, title, back, theme, size, pressed=None, clock=None, detail=''):
        self.theme,self.size,self.pressed=theme,size,pressed
        box=scale_bounds(BACK_BOUNDS,size)
        self.image=chrome(theme,child=back is not None,clock=clock,pressed=pressed==box)
        self.draw=ImageDraw.Draw(self.image)
        self.actions=[(box,back)] if back is not None else []
        self.label((24,72),title,28)
        self.text((696,88),detail,16,anchor='rm')

    def label(self,xy,text,size=24):
        label=caption(str(text),size)
        self.image.paste(label,tuple(round(v) for v in xy),label)

    def text(self,xy,text,size=16,fill='#c2c0cc',anchor='lt'):
        self.draw.text(xy,str(text),font=font(size),fill=fill,anchor=anchor)

    def fit(self,text,width,size=16):
        text=str(text)
        if self.draw.textlength(text,font=font(size))<=width:return text
        while text and self.draw.textlength(text+'…',font=font(size))>width:text=text[:-1]
        return text+'…'

    def panel(self,box):
        x,y,r,b=box
        tile=art.tile(self.theme,r-x,b-y,radius=6)
        self.image.paste(tile,(x,y),tile)

    def button(self,box,title,action,selected=False,size=20,secondary=False):
        x,y,r,b=box;actual=scale_bounds(box,self.size)
        if secondary:
            self.draw.rounded_rectangle((x,y,r-1,b-1),radius=6,
                fill='#38363e' if self.pressed==actual else '#27262d',
                outline='#93909b' if self.pressed==actual else '#64616d',width=1)
        else:self.panel(box)
        if not secondary and (selected or self.pressed==actual):
            overlay=Image.new('RGBA',(r-x,b-y))
            ImageDraw.Draw(overlay).rounded_rectangle((0,0,r-x-1,b-y-1),radius=6,
                fill=(255,255,255,26 if self.pressed==actual else 12),
                outline=(*art.blend(art.accent(self.theme),(245,243,255),.72),220),width=2)
            self.image.paste(overlay,(x,y),overlay)
        label=caption(title,size)
        self.image.paste(label,(round((x+r-label.width)/2),round((y+b-label.height)/2)),label)
        self.actions.append((actual,action))

    def row(self,y,title,detail,action):
        self.button((24,y,696,y+44),'',action)
        self.label((42,y+8),self.fit(title,360,24),24)
        self.text((648,y+22),self.fit(detail,208),anchor='rm')
        self.draw.line([(672,y+16),(678,y+22),(672,y+28)],fill='#ddd9e9',width=2)

    def frame(self):
        image=self.image if self.size==(720,480) else self.image.resize(self.size,Image.Resampling.LANCZOS)
        return Frame(image,self.actions,0)


def present(launcher,page):
    frame=page.frame()
    launcher.actions=frame.actions
    launcher.home_clock=datetime.now().strftime('%Y-%m-%d %H:%M')
    launcher.fb.image(dither_rgb565(frame.image))
