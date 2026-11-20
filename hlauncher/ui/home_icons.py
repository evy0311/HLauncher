"""Home glyphs and fitted brand artwork with a restrained radio finish.

Drawn from geometry at 3× resolution; no Honda firmware artwork is used.
Branded source colors stay fixed when the launcher accent theme changes.
"""
import math
from PIL import Image, ImageDraw, ImageChops, ImageOps
from pathlib import Path

S=3


def gradient(size, top, bottom):
    image=Image.new('RGBA',size);d=ImageDraw.Draw(image)
    for y in range(size[1]):
        t=y/max(1,size[1]-1)
        color=tuple(round(a*(1-t)+b*t) for a,b in zip(top,bottom))
        d.line((0,y,size[0],y),fill=(*color,255))
    return image


def render_icon(kind, size):
    if isinstance(kind, Path):
        try:
            with Image.open(kind, formats=['PNG']) as source:
                if max(source.size) <= 256 and not getattr(source, 'is_animated', False):
                    icon = ImageOps.contain(source.convert('RGBA'), (size, size), Image.Resampling.LANCZOS)
                    if icon.getbbox():
                        output = Image.new('RGBA', (size, size))
                        output.alpha_composite(icon, ((size-icon.width)//2, (size-icon.height)//2))
                        return output
        except (OSError, ValueError, Image.DecompressionBombError):
            pass
    canvas=Image.new('RGBA',(72*S,72*S));d=ImageDraw.Draw(canvas)
    def box(x,y,w,h):return tuple(round(v*S) for v in (x,y,x+w,y+h))
    def points(values):return [(round(x*S),round(y*S)) for x,y in values]
    def line(values,fill,width=2):d.line(points(values),fill=fill,width=round(width*S),joint='curve')
    def material(mask,top,bottom):
        layer=gradient(canvas.size,top,bottom);layer.putalpha(mask)
        canvas.alpha_composite(layer)
    def white_symbol(draw):
        mask=Image.new('L',canvas.size);draw(ImageDraw.Draw(mask))
        material(mask,(255,255,255),(196,208,225))
    if kind in ('carplay','android-auto'):
        # User-selected brand artwork; fit without redrawing or changing its shape.
        with Image.open(Path(__file__).parent/'assets/icons'/(kind+'.png')) as source:
            icon=ImageOps.contain(source.convert('RGBA'),(56*S,56*S),Image.Resampling.LANCZOS)
        canvas.alpha_composite(icon,((canvas.width-icon.width)//2,7*S))
    elif kind == 'phone-projection':
        ink = '#dbe5f0'
        d.rounded_rectangle(box(26,16,40,30),radius=4*S,outline=ink,width=2*S)
        line([(41,47),(41,54),(53,54)],ink,2)
        d.rounded_rectangle(box(7,26,23,38),radius=4*S,fill='#111820',outline=ink,width=2*S)
        line([(14,31),(23,31)],ink,1.5)
        line([(16,59),(21,59)],ink,1.5)
        # A link between the phone and display, rather than either protocol's logo.
        line([(37,30),(45,30),(45,37)],'#8bbde6',2)
        line([(41,34),(45,38),(49,34)],'#8bbde6',2)
    elif kind == 'vehicle':
        ink = '#eef3fa'
        line([(8,49),(9,39),(18,34),(27,23),(46,23),(55,34),(64,39),
              (65,49),(58,49)], ink, 3)
        line([(15,49),(8,49)], ink, 3)
        line([(27,49),(46,49)], ink, 3)
        for x in (21,52):
            d.ellipse(box(x-6,43,12,12),outline=ink,width=3*S)
        line([(20,34),(54,34)], ink, 2)
    elif kind=='obd':
        # One instrument, with a silver bezel, dark dial and a colored redline.
        mask=Image.new('L',canvas.size);q=ImageDraw.Draw(mask)
        q.ellipse(box(6,6,60,60),fill=255)
        material(mask,(249,251,255),(116,132,155))
        d.ellipse(box(9,9,54,54),fill='#151d2c',outline='#e2eaf2',width=S)
        d.ellipse(box(12,12,48,48),fill='#111926')
        # A balanced 270-degree sweep, with an equal opening on either side.
        d.arc(box(15,15,42,42),135,365,fill='#45c0ec',width=3*S)
        d.arc(box(15,15,42,42),365,405,fill='#e35a53',width=3*S)
        for angle in (135+i*270/8 for i in range(9)):
            a=math.radians(angle)
            line([(36+23*math.cos(a),36+23*math.sin(a)),
                  (36+18*math.cos(a),36+18*math.sin(a))],'#eef3fa',1.4)
        # Red needle with a silver center cap, like the stock Navi/instrument art.
        d.polygon(points([(34,34),(51,21),(38,38)]),fill='#ef5854')
        d.ellipse(box(31,31,10,10),fill='#dce6ef',outline='#ffffff',width=S)
        line([(28,53),(44,53)],'#75899e',1)
    elif kind=='audio':
        # Equalizer/fader symbol: three chrome rails and blue slider handles.
        for x,y in ((18,26),(36,43),(54,19)):
            d.rounded_rectangle(box(x-2,10,4,51),radius=2*S,fill='#8b9aad')
            line([(x-1,12),(x-1,59)],'#edf4fc',1)
            mask=Image.new('L',canvas.size)
            ImageDraw.Draw(mask).rounded_rectangle(box(x-7,y-5,14,10),radius=2*S,fill=255)
            material(mask,(134,217,255),(27,110,187))
            d.rounded_rectangle(box(x-7,y-5,14,10),radius=2*S,outline='#bde9ff',width=S)
            line([(x-4,y-1),(x+4,y-1)],'#e8f8ff',1)
    else:
        # Retain the established silver settings gear and generic-app vocabulary.
        mask=Image.new('L',canvas.size);q=ImageDraw.Draw(mask)
        if kind=='settings':
            shape=[]
            for i in range(72):
                a=i*math.pi/36;r=29 if i%6 in (0,1,4,5) else 23
                shape.append((36+math.cos(a)*r,36+math.sin(a)*r))
            q.polygon(points(shape),fill=255);q.ellipse(box(25,25,22,22),fill=0)
        else:
            for x,y in ((12,12),(40,12),(12,40),(40,40)):
                q.rounded_rectangle(box(x,y,20,20),radius=3*S,outline=255,width=3*S)
        if kind=='settings':
            material(mask,(189,200,217),(99,114,138))
            # Directional chamfers add depth to both the teeth and center hole.
            lower=ImageChops.subtract(mask,ImageChops.offset(mask,-S,-S))
            upper=ImageChops.subtract(mask,ImageChops.offset(mask,S,S))
            material(lower,(81,98,123),(49,63,84))
            material(upper,(235,241,250),(151,168,192))
        else:
            material(mask,(255,255,255),(174,188,210))
    return canvas.resize((size,size),Image.Resampling.LANCZOS)
