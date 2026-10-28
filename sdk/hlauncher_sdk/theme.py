"""Glass tile surfaces and vector app glyphs, drawn without external assets."""
import math
from PIL import Image, ImageDraw, ImageFilter


def rgb(color):
    return tuple(int(color[i:i+2],16) for i in (1,3,5))


def background(width,height,color):
    accent=rgb(color)
    small=Image.new('RGB',(90,60))
    pixels=small.load()
    for y in range(60):
        for x in range(90):
            glow=math.exp(-(((x-32)/46)**2+((y-36)/30)**2))
            pixels[x,y]=tuple(round(base+c*.085*glow) for base,c in zip((5,9,16),accent))
    return small.resize((width,height),Image.Resampling.BILINEAR)


def border_color(color, pressed=False):
    tint = rgb(color)
    strength, offset = (.38, 34) if pressed else (.30, 30)
    return tuple(min(248, round((component * strength + offset) / 8) * 8) for component in tint)


def glass_tile(image,box,color):
    x,y,right,bottom=box;w,h=right-x,bottom-y
    tint=rgb(color)
    shadow=Image.new('RGBA',(w+16,h+16))
    ImageDraw.Draw(shadow).rounded_rectangle((8,10,w+8,h+10),radius=19,fill=(0,0,0,110))
    shadow=shadow.filter(ImageFilter.GaussianBlur(4))
    image.paste(shadow,(x-8,y-8),shadow)
    crop=image.crop(box).convert('RGBA')
    # Uniform tint avoids broad quantization bands and a visible reflection seam.
    crop=Image.alpha_composite(crop,Image.new('RGBA',(w,h),(*tint,88)))
    mask=Image.new('L',(w,h));ImageDraw.Draw(mask).rounded_rectangle((0,0,w-1,h-1),radius=18,fill=255)
    image.paste(crop.convert('RGB'),(x,y),mask)
    # Muted theme tint, snapped to RGB565 steps to avoid colored edge speckling.
    border=border_color(color)
    d=ImageDraw.Draw(image)
    d.rounded_rectangle((x,y,right-1,bottom-1),radius=18,outline=border,width=3)


def draw_icon(image,kind,center,size=76):
    # Supersampling keeps glyphs clean at the radio's modest resolution.
    scale=3;canvas=Image.new('RGBA',(size*scale,size*scale))
    d=ImageDraw.Draw(canvas)
    def coords(values):return tuple(round(v*size*scale/100) for v in values)
    def line(points,width=5,fill='white'):
        d.line([coords(point) for point in points],fill=fill,width=round(width*size*scale/100),joint='curve')
    if kind=='carplay':
        d.rounded_rectangle(coords((9,19,91,79)),radius=round(size*scale*.12),outline='white',width=round(size*scale*.055))
        d.polygon([coords(p) for p in ((42,33),(67,49),(42,65))],fill='white')
        line([(34,89),(66,89)],4)
    elif kind=='android-auto':
        d.polygon([coords(p) for p in ((50,8),(91,85),(65,71),(50,43),(35,71),(9,85))],fill='white')
        line([(37,85),(50,62),(63,85)],5,fill=(223,234,249,150))
    elif kind=='obd':
        d.arc(coords((8,9,92,93)),start=145,end=395,fill='white',width=round(size*scale*.055))
        for angle in (150,190,230,270,310,350,390):
            a=math.radians(angle)
            line([(50+35*math.cos(a),51+35*math.sin(a)),(50+41*math.cos(a),51+41*math.sin(a))],3)
        line([(50,51),(71,27)],5)
        d.ellipse(coords((44,45,56,57)),fill='white')
        line([(32,91),(68,91)],4)
    elif kind=='settings':
        points=[]
        for i in range(48):
            a=2*math.pi*i/48;r=44 if i%6 in (1,2,3,4) else 35
            points.append(coords((50+r*math.cos(a),50+r*math.sin(a))))
        d.polygon(points,fill='white')
        d.ellipse(coords((32,32,68,68)),fill=(0,0,0,0))
    else:
        for x,y in ((14,14),(56,14),(14,56),(56,56)):
            d.rounded_rectangle(coords((x,y,x+30,y+30)),radius=round(size*scale*.05),outline='white',width=round(size*scale*.04))
    icon=canvas.resize((size,size),Image.Resampling.LANCZOS)
    image.paste(icon,(round(center[0]-size/2),round(center[1]-size/2)),icon)


# Shared chrome uses flatter surfaces than the large launcher tiles.
PALETTE = {'Blue':'#377bb5','Red':'#c9384a','Green':'#318f69',
           'Amber':'#d68c32','Purple':'#9369c4','Graphite':'#8796aa'}


def load_accent():
    import json,os
    from pathlib import Path
    try:
        settings=Path(os.environ.get('HLAUNCHER_STATE_DIR','/var/lib/hlauncher'))/'settings.json'
        value=json.loads(settings.read_text()).get('tile_color','Blue')
        return PALETTE.get(value,PALETTE['Blue'])
    except (OSError,ValueError,TypeError,AttributeError):
        return PALETTE['Blue']


def button_surface(draw,box,color,pressed=False,scale=1):
    tint=rgb(color)
    fill=tuple(round(c*(.47 if pressed else .29)+base) for c,base in zip(tint,(12,17,23)))
    edge=border_color(color,pressed)
    rect=tuple(round(v*scale) for v in box)
    draw.rounded_rectangle(rect,radius=round(11*scale),fill=fill,
                           outline=edge,width=max(1,round(3*scale)))


def dither_rgb565(image):
    """Static ordered dithering for RGB565 UI surfaces; never applied to video."""
    import numpy as np
    values=np.asarray(image.convert('RGB'),dtype=np.uint16)
    h,w=values.shape[:2]
    bayer=np.array([[0,8,2,10],[12,4,14,6],[3,11,1,9],[15,7,13,5]],dtype=np.uint16)
    threshold=np.tile(bayer,((h+3)//4,(w+3)//4))[:h,:w]
    out=np.empty((h,w,3),dtype=np.uint8)
    for channel,shift in enumerate((3,2,3)):
        quantized=np.minimum((values[:,:,channel]*(16>>shift)+threshold)>>4,(256>>shift)-1)
        out[:,:,channel]=quantized<<shift
    return Image.fromarray(out)
