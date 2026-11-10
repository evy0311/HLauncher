"""Six large live dials, with a touch-revealed fullscreen exit control."""
import math
import time
from PIL import Image, ImageDraw
from sdk.hlauncher_sdk.fonts import font
from sdk.hlauncher_sdk.theme import load_accent, PALETTE
from . import home_art as art
from .chrome import render as chrome, BACK_BOUNDS, scale_bounds
from .home import caption

GAUGES=[('Engine RPM','rpm',0,8000),('Coolant temp','°F',40,260),
        ('Accelerator pedal','%',0,100),('Intake air temp','°F',-40,200),
        ('Barometric pressure','native',0,800),('VTEC','status',0,1)]
FULLSCREEN_BOUNDS=(654,6,710,46)


def point(cx,cy,radius,angle):
    a=math.radians(angle)
    return cx+math.cos(a)*radius,cy+math.sin(a)*radius


def inside(point,box):
    return point is not None and box[0]<=point[0]<=box[2] and box[1]<=point[1]<=box[3]


class Dashboard:
    def __init__(self,width,height):
        self.w,self.h=width,height
        from ..config import Preferences
        self.show_clock=Preferences().data['show_clock']
        self.accent=load_accent()
        self.theme=next((name for name,value in PALETTE.items() if value==self.accent),self.accent)
        self.home_box=scale_bounds(BACK_BOUNDS,(width,height))
        self.fullscreen_box=scale_bounds(FULLSCREEN_BOUNDS,(width,height))
        self.fullscreen=False;self.controls_visible=False;self.touch_target=None
        self.centers=[(x,y,78) for y in (144,354) for x in (120,360,600)]
        self.fullscreen_centers=[(x,y,94) for y in (104,344) for x in (120,360,600)]
        self.bases={False:self.build_base(self.centers),True:self.build_base(self.fullscreen_centers,True)}
        self.header_key=None;self.header=None
        self.needle_values=[None]*6;self.needle_at=None

    def build_base(self,centers,fullscreen=False):
        image=Image.new('RGB',(720,480),'#09090d') if fullscreen else art.background(self.theme,True).copy()
        d=ImageDraw.Draw(image)
        for (label,unit,lo,hi),(cx,cy,r) in zip(GAUGES,centers):
            d.ellipse((cx-r,cy-r,cx+r,cy+r),fill='#101017',outline='#a09da9',width=2)
            if unit=='status':
                title=caption(label,18);image.paste(title,(round(cx-title.width/2),cy+r+12),title)
                continue
            d.arc((cx-r+5,cy-r+5,cx+r-5,cy+r-5),135,405,
                  fill=art.blend(art.accent(self.theme),(220,220,240),.25),width=4)
            for tick in range(19):
                angle=135+270*tick/18;major=tick%3==0
                d.line((*point(cx,cy,r-10,angle),*point(cx,cy,r-(20 if major else 15),angle)),
                       fill='#dbd9e3' if major else '#75717f',width=2 if major else 1)
            title=caption(label,18)
            image.paste(title,(round(cx-title.width/2),cy+r+12),title)
        return image

    def touch(self,action,point,now=None):
        now=time.monotonic() if now is None else now
        if action=='cancel':self.touch_target=None;return None
        if action=='down':
            if self.fullscreen:
                self.touch_target='minimize' if self.controls_visible and inside(point,self.fullscreen_box) else 'reveal'
            else:
                self.touch_target='expand' if inside(point,self.fullscreen_box) else 'home' if inside(point,self.home_box) else None
        elif action=='move':
            box=self.home_box if self.touch_target=='home' else self.fullscreen_box
            if self.touch_target in ('home','expand','minimize') and not inside(point,box):self.touch_target=None
        elif action in ('up','unused'):
            target,self.touch_target=self.touch_target,None
            box=self.home_box if target=='home' else self.fullscreen_box
            if target in ('home','expand','minimize') and not inside(point,box):return None
            if target=='expand':self.fullscreen=True;self.controls_visible=False
            elif target=='minimize':self.fullscreen=False;self.controls_visible=False
            elif target=='reveal':self.controls_visible=not self.controls_visible
            return target
        return None

    def draw_fullscreen_button(self,d):
        x,y,r,b=FULLSCREEN_BOUNDS
        pressed=self.touch_target in ('expand','minimize')
        d.rounded_rectangle((x,y,r,b),radius=5,fill='#36323b' if pressed else '#19171e',outline='#77717e',width=1)
        left,top,right,bottom=x+17,y+10,r-17,b-10
        if self.fullscreen:
            # Four corners pointing inward.
            for cx,cy,sx,sy in ((left+6,top+6,-1,-1),(right-6,top+6,1,-1),
                                (left+6,bottom-6,-1,1),(right-6,bottom-6,1,1)):
                d.line([(cx+sx*6,cy),(cx,cy),(cx,cy+sy*6)],fill='#eeeaf3',width=2)
        else:
            for cx,cy,sx,sy in ((left,top,1,1),(right,top,-1,1),(left,bottom,1,-1),(right,bottom,-1,-1)):
                d.line([(cx+sx*6,cy),(cx,cy),(cx,cy+sy*6)],fill='#eeeaf3',width=2)

    def render(self,values,pressed=False,connected=True, *, sources=None,ages=None,intervals=None,now=None):
        now=time.monotonic() if now is None else now
        image=self.bases[self.fullscreen].copy()
        if not self.fullscreen:
            key=(time.strftime('%Y-%m-%d %H:%M'),pressed or self.touch_target=='home')
            if key!=self.header_key:
                self.header=chrome(self.theme,child=True,pressed=key[1],show_clock=self.show_clock).crop((0,0,720,52))
                self.header_key=key
            image.paste(self.header,(0,0))
        d=ImageDraw.Draw(image)
        values=(list(values)+[None]*6)[:6]
        dt=max(0,min(.25,now-self.needle_at)) if self.needle_at is not None else .25
        self.needle_at=now
        centers=self.fullscreen_centers if self.fullscreen else self.centers
        for index,(value,(_,unit,lo,hi),(cx,cy,r)) in enumerate(zip(values,GAUGES,centers)):
            available=connected and value is not None
            if unit=='status':
                self.needle_values[index]=None
                color='#67d78b' if available and bool(value) else '#77727d'
                d.ellipse((cx-13,cy-38,cx+13,cy-12),fill=color if available else '#28262d')
                d.text((cx,cy+18),'ON' if available and bool(value) else 'OFF' if available else '—',
                    font=font(32,700),fill='#f4f4f7' if available else '#86828f',anchor='mm')
                continue
            if available:
                old=self.needle_values[index]
                # RPM follows a rev quickly; slower sensors retain more damping.
                alpha=1-math.exp(-dt/(.025 if index==0 else .06))
                self.needle_values[index]=value if old is None else old+(value-old)*alpha
                fraction=max(0,min(1,(self.needle_values[index]-lo)/(hi-lo)));angle=135+270*fraction
                d.line((*point(cx,cy,r-5,angle),*point(cx,cy,r+5,angle)),fill='#f2edf9',width=5)
                display=f'{value:+.1f}' if unit=='%' and lo<0 else f'{value:.1f}' if unit=='native' else f'{value:.0f}'
            else:display='—';self.needle_values[index]=None
            d.text((cx,cy-9),display,font=font(40 if self.fullscreen else 36,700),fill='#f4f4f7' if available else '#86828f',anchor='mm')
            d.text((cx,cy+24),unit,font=font(18),fill='#c2c0cc',anchor='mm')
        if not self.fullscreen or self.controls_visible:self.draw_fullscreen_button(d)
        return image if (self.w,self.h)==(720,480) else image.resize((self.w,self.h),Image.Resampling.LANCZOS)
