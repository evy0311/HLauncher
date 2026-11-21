"""Approved white home artwork, fitted brand logos and auxiliary glyphs.

No Honda firmware artwork is used. Brand source colors stay fixed when the
launcher accent theme changes.
"""
from functools import lru_cache
from PIL import Image, ImageDraw, ImageOps
from pathlib import Path

S=3


HOME_ART = Path(__file__).parent / 'assets/icons/home'
HOME_ICONS = {
    'phone-projection': 'phone-projection',
    'obd': 'obd',
    'vehicle': 'vehicle-sedan',
    'vehicle-coupe': 'vehicle-coupe',
    'settings': 'settings',
}


@lru_cache(maxsize=5)
def home_coverage(name):
    """Use the approved white ink as coverage over any themed tile.

    Source previews have dark backgrounds. Ignore their low-level texture and
    map the white artwork to opacity, preserving the approved shape and holes.
    Keep the approved source files intact.
    """
    with Image.open(HOME_ART / (name + '.png')) as source:
        coverage = ImageOps.grayscale(source).point(
            lambda value: max(0, min(255, round((value - 40) * 255 / 200))))
    return coverage.crop(coverage.getbbox())


def white_home_icon(name, size):
    coverage = ImageOps.contain(home_coverage(name), (round(size * 8/9),) * 2,
                                Image.Resampling.LANCZOS)
    icon = Image.new('RGBA', coverage.size, 'white')
    icon.putalpha(coverage)
    output = Image.new('RGBA', (size, size))
    output.alpha_composite(icon, ((size-icon.width)//2, (size-icon.height)//2))
    return output


def gradient(size, top, bottom):
    image=Image.new('RGBA',size);d=ImageDraw.Draw(image)
    for y in range(size[1]):
        t=y/max(1,size[1]-1)
        color=tuple(round(a*(1-t)+b*t) for a,b in zip(top,bottom))
        d.line((0,y,size[0],y),fill=(*color,255))
    return image


def render_icon(kind, size):
    if isinstance(kind, str) and kind in HOME_ICONS:
        return white_home_icon(HOME_ICONS[kind], size)
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
    if kind in ('carplay','android-auto'):
        # User-selected brand artwork; fit without redrawing or changing its shape.
        with Image.open(Path(__file__).parent/'assets/icons'/(kind+'.png')) as source:
            icon=ImageOps.contain(source.convert('RGBA'),(56*S,56*S),Image.Resampling.LANCZOS)
        canvas.alpha_composite(icon,((canvas.width-icon.width)//2,7*S))
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
        # Generic external-plugin fallback retains the established app grid.
        mask=Image.new('L',canvas.size);q=ImageDraw.Draw(mask)
        for x,y in ((12,12),(40,12),(12,40),(40,40)):
            q.rounded_rectangle(box(x,y,20,20),radius=3*S,outline=255,width=3*S)
        material(mask,(255,255,255),(174,188,210))
    return canvas.resize((size,size),Image.Resampling.LANCZOS)
