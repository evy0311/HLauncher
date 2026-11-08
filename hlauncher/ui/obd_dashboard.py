"""Live OBD dials with the same stock-radio chrome as the launcher."""
import math
import time
from PIL import Image, ImageDraw
from sdk.hlauncher_sdk.fonts import font
from sdk.hlauncher_sdk.theme import load_accent, PALETTE
from . import home_art as art
from .chrome import render as chrome, BACK_BOUNDS, scale_bounds
from .home import caption

GAUGES=[('Coolant temp','°F',100,260),('Oil temp','°F',140,300),
        ('Long term fuel trim','%',-20,20),('MAF','g/s',0,100)]


def point(cx,cy,radius,angle):
    a=math.radians(angle)
    return cx+math.cos(a)*radius,cy+math.sin(a)*radius


class Dashboard:
    def __init__(self,width,height):
        self.w,self.h=width,height
        self.accent=load_accent()
        self.theme=next((name for name,value in PALETTE.items() if value==self.accent),'Blue')
        self.home_box=scale_bounds(BACK_BOUNDS,(width,height))
        self.centers=[(190,178,60),(530,178,60),(190,358,60),(530,358,60)]
        self.base=art.background(self.theme,True).copy()
        d=ImageDraw.Draw(self.base)
        title=caption('OBD Gauges',28);self.base.paste(title,(24,72),title)
        for (label,unit,lo,hi),(cx,cy,r) in zip(GAUGES,self.centers):
            d.ellipse((cx-r,cy-r,cx+r,cy+r),fill='#101017',outline='#a09da9',width=2)
            d.arc((cx-r+5,cy-r+5,cx+r-5,cy+r-5),135,405,
                  fill=art.blend(art.accent(self.theme),(220,220,240),.25),width=4)
            for tick in range(19):
                angle=135+270*tick/18;major=tick%3==0
                d.line((*point(cx,cy,r-10,angle),*point(cx,cy,r-(19 if major else 15),angle)),
                       fill='#dbd9e3' if major else '#75717f',width=2 if major else 1)
            title=caption(label,20)
            self.base.paste(title,(round(cx-title.width/2),cy+72),title)
        self.header_key=None
        self.header=None

    def render(self,values,pressed=False,connected=True):
        key=(time.strftime('%Y-%m-%d %H:%M'),pressed)
        if key!=self.header_key:
            self.header=chrome(self.theme,child=True,pressed=pressed).crop((0,0,720,52))
            self.header_key=key
        image=self.base.copy();image.paste(self.header,(0,0));d=ImageDraw.Draw(image)
        d.text((696,88),'Live' if connected else 'OBD disconnected',font=font(16),
               fill='#c2c0cc',anchor='rm')
        for value,(_,unit,lo,hi),(cx,cy,r) in zip(values,GAUGES,self.centers):
            available=connected and value is not None
            if available:
                fraction=max(0,min(1,(value-lo)/(hi-lo)));angle=135+270*fraction
                d.line((*point(cx,cy,r-5,angle),*point(cx,cy,r+5,angle)),fill='#f2edf9',width=5)
                display=f'{value:+.1f}' if unit=='%' else f'{value:.1f}' if unit=='g/s' else f'{value:.0f}'
            else:display='—'
            d.text((cx,cy-8),display,font=font(32,700),fill='#f4f4f7' if available else '#86828f',anchor='mm')
            d.text((cx,cy+21),unit,font=font(16),fill='#c2c0cc',anchor='mm')
        d.text((24,456),'Live readings only · — unavailable' if connected else 'Connect your adapter in Settings › OBD Gauges',
               font=font(14),fill='#a3a0ae',anchor='lt')
        return image if (self.w,self.h)==(720,480) else image.resize((self.w,self.h),Image.Resampling.LANCZOS)
