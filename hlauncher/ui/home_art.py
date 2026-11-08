"""Original home-screen artwork. No Honda firmware or generated bitmap assets.

Surfaces and metallic glyphs are rendered once and cached; their accent remains
parametric so every theme gets the same gradients, bevels and reflections.
"""
from functools import lru_cache
import math
from PIL import Image, ImageChops, ImageDraw, ImageOps

THEMES = {'Blue': (48, 24, 244), 'Red': (194, 0, 40),
          'Green': (12, 150, 85), 'Amber': (211, 120, 10),
          'Purple': (140, 35, 221), 'Graphite': (101, 119, 145)}
SCALE = 3
TILE_SIZE = (196,176)


def accent(theme):
    return THEMES.get(theme, THEMES['Blue'])


def blend(a, b, amount):
    return tuple(round(x*(1-amount)+y*amount) for x,y in zip(a,b))


@lru_cache(maxsize=12)
def background(theme, child=False):
    tint=accent(theme)
    small=Image.new('RGB',(120,80)); pixels=small.load()
    for y in range(80):
        for x in range(120):
            halo=math.exp(-((y-44)/13)**2-((x-57)/51)**2)
            pixels[x,y]=tuple(round(base+c*.14*halo) for base,c in zip((9,9,13),tint))
    image=small.resize((720,480),Image.Resampling.BILINEAR)
    d=ImageDraw.Draw(image)
    for y in range(51):
        v=round(21-10*y/50);d.line((0,y,719,y),fill=(v,v,v+4))
    # Home tab reaches BOTH outside edges; only the right edge slopes.
    d.polygon([(0,0),(56,0),(80,51),(0,51)],fill=blend((19,19,26),tint,.13))
    edge=blend(tint,(214,213,235),.52)
    d.line([(0,0),(56,0),(80,51),(719,51)],fill=edge,width=1)
    if child:
        # Original return glyph; the header/tab geometry stays identical to Home.
        button=tile(theme,50,40,radius=6)
        image.paste(button,(8,6),button)
        s=SCALE;arrow=Image.new('RGBA',(40*s,36*s));q=ImageDraw.Draw(arrow)
        q.arc((11*s,8*s,33*s,30*s),270,450,fill='#f5f4fc',width=5*s)
        q.rectangle((10*s,8*s,22*s,12*s),fill='#f5f4fc')
        q.rectangle((5*s,26*s,22*s,30*s),fill='#f5f4fc')
        q.polygon([(2*s,10*s),(12*s,3*s),(12*s,17*s)],fill='#f5f4fc')
        arrow=arrow.resize((32,29),Image.Resampling.LANCZOS)
        image.paste(arrow,(19,12),arrow)
    else:
        for row in range(3):
            for col in range(3):
                x=17+col*9;y=15+row*9
                d.rounded_rectangle((x,y,x+6,y+6),radius=1,fill='#f5f4fc')
    return image


@lru_cache(maxsize=24)
def tile(theme, width=None, height=None, radius=10):
    w,h=(width or TILE_SIZE[0]),(height or TILE_SIZE[1]);s=SCALE;tint=accent(theme)
    panel=Image.new('RGBA',(w*s,h*s));d=ImageDraw.Draw(panel)
    for yy in range(h*s):
        t=yy/(h*s-1)
        bottom=max(0,(t-.53)/.47)**1.75
        top=math.exp(-t/.045)
        # Stock-style color at both ends, with a narrow top band and dark center.
        color=tuple(min(255,round(base+c*(.93*bottom+.80*top)+highlight*top))
                    for base,c,highlight in zip((10,10,16),tint,(14,14,23)))
        d.line((0,yy,w*s,yy),fill=(*color,255))
    mask=Image.new('L',panel.size)
    ImageDraw.Draw(mask).rounded_rectangle((0,0,w*s-1,h*s-1),radius=radius*s,fill=255)
    panel.putalpha(mask)
    edge=blend(tint,(208,205,232),.43)
    d.rounded_rectangle((0,0,w*s-1,h*s-1),radius=radius*s,outline=(*edge,255),width=round(1.3*s))
    # Fine bevel, confined to the edge rather than a reflection across the face.
    d.line((radius*s,2*s,(w-radius)*s,2*s),fill=(*blend(tint,(246,244,255),.65),220),width=s)
    d.rounded_rectangle((2*s,2*s,(w-2)*s-1,(h-2)*s-1),radius=max(1,radius-2)*s,
                        outline=(*blend(tint,(100,98,132),.55),75),width=s)
    return panel.resize((w,h),Image.Resampling.LANCZOS)


@lru_cache(maxsize=48)
def glyph(kind, size=64):
    from .home_icons import render_icon
    return render_icon(kind,size)


@lru_cache(maxsize=48)
def reflection(kind, size=64, fade_height=32):
    # Flip at the original size: resizing the mirror vertically squashes glyphs.
    icon=ImageOps.flip(glyph(kind,size))
    fade=Image.new('L',icon.size);d=ImageDraw.Draw(fade)
    start=icon.getbbox()[1]
    end=min(icon.height,fade_height)
    for y in range(icon.height):
        progress=max(0,min(1,(y-start)/max(1,end-start)))
        # Extra visibility right at the mirror edge, tapering away quickly.
        opacity=32*(1-progress)**2+14*(1-progress)**6
        d.line((0,y,size,y),fill=round(opacity))
    icon.putalpha(ImageChops.multiply(icon.getchannel('A'),fade))
    return icon
