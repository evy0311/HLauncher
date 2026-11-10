"""Original UI surfaces and fitted brand icons. No Honda firmware assets.

Surfaces and metallic glyphs are rendered once and cached; their accent remains
parametric so every theme gets the same gradients, bevels and reflections.
"""
from functools import lru_cache
import math
from PIL import Image, ImageChops, ImageDraw, ImageOps, ImageFilter

THEMES = {'Blue': (34, 20, 170), 'Red': (112, 12, 29),
          'Green': (10, 105, 59), 'Amber': (148, 81, 9),
          'Purple': (98, 25, 154), 'Graphite': (72, 85, 104)}
SCALE = 3
TILE_SIZE = (196,176)


def accent(theme):
    if theme in THEMES:return THEMES[theme]
    from sdk.hlauncher_sdk.theme import normalize_color, rgb
    try:return rgb(normalize_color(theme))
    except ValueError:return THEMES['Red']


def blend(a, b, amount):
    return tuple(round(x*(1-amount)+y*amount) for x,y in zip(a,b))


def smoothstep(start, end, value):
    amount=max(0,min(1,(value-start)/(end-start)))
    return amount*amount*(3-2*amount)


@lru_cache(maxsize=12)
def background(theme, child=False):
    tint=accent(theme)
    small=Image.new('RGB',(120,80)); pixels=small.load()
    for y in range(80):
        for x in range(120):
            halo=math.exp(-((y-44)/13)**2-((x-57)/51)**2)
            pixels[x,y]=tuple(round(base+c*.10*halo) for base,c in zip((9,9,13),tint))
    image=small.resize((720,480),Image.Resampling.BILINEAR)
    d=ImageDraw.Draw(image)
    for y in range(51):
        v=round(21-10*y/50);d.line((0,y,719,y),fill=(v,v,v+4))
    # Home tab reaches BOTH outside edges; only the right edge slopes.
    d.polygon([(0,0),(56,0),(80,51),(0,51)],fill=blend((19,19,26),tint,.13))
    edge=blend(tint,(214,213,235),.36)
    d.line([(0,0),(56,0),(80,51),(719,51)],fill=edge,width=1)
    if child:
        # Original return glyph; the header/tab geometry stays identical to Home.
        button=tile(theme,50,40,radius=6,control=True)
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
def tile(theme, width=None, height=None, radius=10, control=False):
    w,h=(width or TILE_SIZE[0]),(height or TILE_SIZE[1]);s=SCALE;tint=accent(theme)
    panel=Image.new('RGBA',(w*s,h*s));d=ImageDraw.Draw(panel)
    for yy in range(h*s):
        t=yy/(h*s-1)
        if control:
            # Small controls need a broad tonal wash, not a compressed home tile.
            strength=.10+.12*(1-smoothstep(0,.55,t))+.18*smoothstep(.25,1,t)
            color=tuple(round(base+c*strength) for base,c in zip((22,20,25),tint))
        else:
            # Keep the center charcoal; broad, eased tails avoid a red/black seam.
            top=math.exp(-(t/.105)**1.45)
            bottom=smoothstep(.40,1.04,t)
            color=tuple(round(base+c*(.64*bottom+.43*top)+3*top)
                        for base,c in zip((19,18,23),tint))
        d.line((0,yy,w*s,yy),fill=(*color,255))
    mask=Image.new('L',panel.size)
    ImageDraw.Draw(mask).rounded_rectangle((0,0,w*s-1,h*s-1),radius=radius*s,fill=255)
    panel.putalpha(mask)
    edge=blend(tint,(185,166,178),.24)
    d.rounded_rectangle((0,0,w*s-1,h*s-1),radius=radius*s,outline=(*edge,255),width=round(1.3*s))
    # Fine bevel, confined to the edge rather than a reflection across the face.
    d.line((radius*s,2*s,(w-radius)*s,2*s),fill=(*blend(tint,(246,244,255),.40),200),width=s)
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


@lru_cache(maxsize=48)
def settings_bar(theme, width, height):
    """Factory-style horizontal color wash, with square ends and a fine bevel."""
    tint=accent(theme);image=Image.new('RGB',(width,height));d=ImageDraw.Draw(image)
    for x in range(width):
        center=max(0,math.sin(math.pi*x/max(1,width-1)))**1.3
        color=blend((22,18,23),tint,.22+.40*center)
        d.line((x,0,x,height-1),fill=color)
    edge=blend(tint,(133,119,128),.22)
    d.line((0,0,width-1,0),fill=edge)
    d.line((0,height-1,width-1,height-1),fill=blend(tint,(8,8,12),.65))
    return image


@lru_cache(maxsize=4)
def tile_shadow(width, height):
    image=Image.new('RGBA',(width+16,height+16))
    ImageDraw.Draw(image).rounded_rectangle((7,9,width+9,height+11),radius=11,fill=(0,0,0,108))
    return image.filter(ImageFilter.GaussianBlur(3))
