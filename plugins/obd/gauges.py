"""High-contrast live dials designed for the radio's low-resolution display."""
import math
from PIL import Image, ImageDraw, ImageEnhance
import numpy as np
from hlauncher_sdk.ui import BACK_BOX, draw_back_button
from hlauncher_sdk.fonts import font
from hlauncher_sdk.theme import load_accent, dither_rgb565, border_color

BG = '#000000'
WHITE = '#f0f0f0'
GAUGES = [('COOLANT TEMP', '°F', 100, 260), ('OIL TEMP', '°F', 140, 300),
          ('LONG TERM FUEL TRIM', '%', -20, 20), ('MAF', 'g/s', 0, 100)]


def point(cx, cy, radius, angle):
    a = math.radians(angle)
    return cx + math.cos(a)*radius, cy + math.sin(a)*radius


class Dashboard:
    def __init__(self, width, height):
        self.w, self.h = width, height
        self.accent = load_accent()
        self.home_box = BACK_BOX
        self.scale = 2
        self.centers = []
        self.base = self.make_base().resize((width, height), Image.Resampling.LANCZOS)
        self.scale = 1

    def text(self, draw, xy, text, size, fill=WHITE, weight=500):
        draw.text(tuple(v*self.scale for v in xy), text,
                  font=font(round(size*self.scale), weight), fill=fill, anchor='mm')

    def line(self, draw, begin, end, color, width):
        draw.line(tuple(v*self.scale for v in (*begin, *end)), fill=color,
                  width=max(1, round(width*self.scale)))

    def arc(self, draw, cx, cy, radius, start, end, color, width):
        r = radius + width/2
        draw.arc(tuple(v*self.scale for v in (cx-r, cy-r, cx+r, cy+r)),
                 start=start, end=end, fill=color, width=max(1, round(width*self.scale)))

    def make_base(self):
        image = Image.new('RGB', (self.w*self.scale, self.h*self.scale), BG)
        d = ImageDraw.Draw(image)
        draw_back_button(d, self.home_box, scale=self.scale, color=self.accent)
        cellh = (self.h-70)/2
        for index, (label, unit, lo, hi) in enumerate(GAUGES):
            cx = self.w*(.25 if index%2 == 0 else .75)
            cy = 70 + (index//2)*cellh + cellh*.41
            r = min(self.w/4-30, cellh*.38)
            self.centers.append((cx, cy, r))
            # A complete dial, without gradients, textures or a broken outer arc.
            self.arc(d, cx, cy, r, 0, 360, '#b8c4d0', 3)
            for tick in range(24):
                angle = -90 + 360*tick/24
                major = tick%3 == 0
                self.line(d, point(cx, cy, r-7, angle), point(cx, cy, r-(17 if major else 12), angle),
                          WHITE if major else '#8898a8', 3 if major else 2)
            limits = f'{lo:+g} to {hi:+g}' if unit == '%' else f'{lo:g} to {hi:g}'
            self.text(d, (cx, cy+52), limits, 15, '#c0c8d0')
            self.text(d, (cx, cy+r+21), label, 21, weight=600)
        return image

    def render(self, values, pressed=False, connected=True):
        image = self.base.copy()
        d = ImageDraw.Draw(image)
        if pressed:
            draw_back_button(d, self.home_box, pressed=True, color=self.accent)
        if not connected:
            d.text((156,18),'Connect an OBD ELM327 dongle in',font=font(18,500),fill=WHITE)
            d.text((156,41),'Launcher Settings > OBD Gauges',font=font(18,500),fill=WHITE)
        for value, (label, unit, lo, hi), (cx, cy, r) in zip(values, GAUGES, self.centers):
            if value is None:
                box=tuple(round(v) for v in (cx-r-9,cy-r-9,cx+r+10,cy+r+10))
                image.paste(ImageEnhance.Brightness(image.crop(box)).enhance(.5),box[:2])
                d=ImageDraw.Draw(image)
                self.text(d,(cx,cy-10),'—',42,weight=700)
                self.text(d,(cx,cy+25),unit,22,WHITE)
                continue
            fraction = max(0, min(1, (value-lo)/(hi-lo)))
            angle = -90 + 360*fraction
            # The compact outer pointer keeps the center clear for the reading.
            self.line(d, point(cx, cy, r-3, angle), point(cx, cy, r+7, angle),
                      border_color(self.accent, pressed=True), 9)
            self.line(d, point(cx, cy, r-2, angle), point(cx, cy, r+6, angle), WHITE, 3)
            displayed = f'{value:+.1f}' if unit == '%' else f'{value:.1f}' if unit == 'g/s' else f'{value:.0f}'
            self.text(d, (cx, cy-10), displayed, 42, weight=700)
            self.text(d, (cx, cy+25), unit, 22, WHITE, weight=500)
        return image


def encode(image):
    rgb_array = np.asarray(dither_rgb565(image), dtype=np.uint16)
    return (((rgb_array[:,:,0]>>3)<<11)|((rgb_array[:,:,1]>>2)<<5)|(rgb_array[:,:,2]>>3)).astype('<u2').tobytes()
