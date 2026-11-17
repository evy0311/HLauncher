"""Touch color picker with an unsaved preview, wheel, RGB and hex input."""
import colorsys
from functools import lru_cache
import math
from PIL import Image, ImageDraw, ImageEnhance
from sdk.hlauncher_sdk.theme import normalize_color, rgb
from .controls import Page, present
from . import home_art as art


class Picker:
    def __init__(self, color):
        self.hue,self.saturation,self.value=colorsys.rgb_to_hsv(*(c/255 for c in rgb(normalize_color(color))))
        self.keyboard=False
        self.buffer=''
        self.replace=True
        self.error=''
        self.drag=None

    @property
    def channels(self):
        return tuple(round(c*255) for c in colorsys.hsv_to_rgb(self.hue,self.saturation,self.value))

    @property
    def hex(self):
        return '#'+''.join(f'{c:02X}' for c in self.channels)

    def set_rgb(self, channels):
        hue,saturation,value=colorsys.rgb_to_hsv(*(max(0,min(255,c))/255 for c in channels))
        if saturation:self.hue=hue
        self.saturation,self.value=saturation,value

    def key(self,key):
        self.error=''
        if key=='hex':
            self.keyboard=True;self.buffer=self.hex[1:];self.replace=True
        elif key=='cancel-hex':self.keyboard=False
        elif key=='apply-hex':
            try:color=normalize_color(self.buffer)
            except ValueError:self.error='Enter all 6 hex digits';return
            self.set_rgb(rgb(color));self.keyboard=False
        elif key=='clear':self.buffer='';self.replace=False
        elif key=='back':self.buffer=self.buffer[:-1];self.replace=False
        elif len(key)==1 and key in '0123456789ABCDEF':
            if self.replace:self.buffer='';self.replace=False
            if len(self.buffer)<6:self.buffer+=key


@lru_cache(maxsize=1)
def wheel():
    image=Image.new('RGBA',(209,209));pixels=image.load()
    for y in range(209):
        for x in range(209):
            dx,dy=x-104,y-104;saturation=math.hypot(dx,dy)/104
            if saturation<=1:
                hue=(math.atan2(dy,dx)/(2*math.pi))%1
                pixels[x,y]=tuple(round(c*255) for c in colorsys.hsv_to_rgb(hue,saturation,1))+(255,)
    return image


def draw_launcher(ui):
    picker=ui.color_picker
    p=Page('Hex color' if picker.keyboard else 'Custom color',
           (lambda:ui.picker_key('cancel-hex')) if picker.keyboard else ui.cancel_custom_color,
           picker.hex,(ui.fb.w,ui.fb.h),ui.pressed_box if ui.press is not None else None,show_clock=ui.prefs.data['show_clock'], layout_theme=getattr(ui, 'layout_theme', None))
    if picker.keyboard:
        p.panel((24,120,324,192))
        p.label((48,140),'#'+picker.buffer.ljust(6,'_'),32)
        for i,key in enumerate('0123456789ABCDEF'):
            x=348+i%4*88;y=120+i//4*60
            p.button((x,y,x+76,y+48),key,lambda key=key:ui.picker_key(key),size=25)
        p.button((24,216,164,264),'Clear',lambda:ui.picker_key('clear'),secondary=True)
        p.button((176,216,324,264),'Delete',lambda:ui.picker_key('back'),secondary=True)
        p.text((24,304),'Enter 6 hex digits',19)
        p.button((24,416,240,460),'Cancel',lambda:ui.picker_key('cancel-hex'),secondary=True)
        p.button((480,416,696,460),'Apply',lambda:ui.picker_key('apply-hex'),size=23)
        p.notice(picker.error,376)
    else:
        p.text((160,120),'Hue & saturation',16,anchor='mt')
        image=ImageEnhance.Brightness(wheel()).enhance(picker.value)
        p.image.paste(image,(56,140),image)
        angle=picker.hue*2*math.pi
        x=160+104*picker.saturation*math.cos(angle);y=244+104*picker.saturation*math.sin(angle)
        p.draw.ellipse((x-7,y-7,x+7,y+7),outline='#16131a',width=4)
        p.draw.ellipse((x-6,y-6,x+6,y+6),outline='white',width=2)
        p.bar((336,120,504,176),picker.hex,lambda:ui.picker_key('hex'),size=22)
        preview=art.tile(picker.hex,176,80,radius=8)
        p.image.paste(preview,(520,112),preview);p.label((560,140),'Preview',22)
        for i,(channel,value) in enumerate(zip('RGB',picker.channels)):
            cy=216+i*48;p.label((336,cy-12),channel,23)
            for x in range(384,629):
                channels=list(picker.channels);channels[i]=round((x-384)/244*255)
                p.draw.line((x,cy-7,x,cy+7),fill=tuple(channels))
            x=384+value/255*244
            p.draw.rounded_rectangle((x-5,cy-13,x+5,cy+13),radius=3,fill='#eeebf2',outline='#524b58')
            p.text((696,cy),str(value),19,anchor='rm',fill='#efedf6')
        p.text((56,360),'Brightness',16)
        p.text((264,360),f'{picker.value*100:.0f}%',16,anchor='rt')
        for x in range(56,265):
            channels=colorsys.hsv_to_rgb(picker.hue,picker.saturation,(x-56)/208)
            p.draw.line((x,384,x,398),fill=tuple(round(c*255) for c in channels))
        x=56+picker.value*208
        p.draw.rounded_rectangle((x-5,378,x+5,404),radius=3,fill='#eeebf2',outline='#524b58')
        p.text((336,360),'Tap the hex code to enter a color',16)
        p.button((24,416,240,460),'Cancel',ui.cancel_custom_color,secondary=True,size=23)
        p.button((480,416,696,460),'Save color',ui.save_custom_color,size=23)
        p.notice(ui.banner,392)
    present(ui,p)


def touch(ui,action,point):
    picker=ui.color_picker
    if picker.keyboard:return False
    if not point:return False
    x,y=point[0]*720/ui.fb.w,point[1]*480/ui.fb.h
    if action=='down':
        if math.hypot(x-160,y-244)<=104:picker.drag='wheel'
        elif 56<=x<=264 and 374<=y<=407:picker.drag='value'
        else:
            for i in range(3):
                if 378<=x<=634 and abs(y-(216+i*48))<=18:picker.drag=i
    if picker.drag is None:return False
    if action in ('down','move','up','unused'):
        if picker.drag=='wheel':
            picker.hue=(math.atan2(y-244,x-160)/(2*math.pi))%1
            picker.saturation=min(1,math.hypot(x-160,y-244)/104)
        elif picker.drag=='value':picker.value=max(0,min(1,(x-56)/208))
        else:
            channels=list(picker.channels);channels[picker.drag]=round(max(0,min(1,(x-384)/244))*255)
            picker.set_rgb(channels)
        if action in ('up','unused'):picker.drag=None
        ui.press=ui.pressed_box=None
        ui.draw()
        return True
    return False
