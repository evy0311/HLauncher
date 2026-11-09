"""Shared launcher/plugin chrome."""
from .fonts import font as ui_font
from .theme import button_surface, load_accent

BACK_BOX = (16,14,134,56)


def draw_back_button(draw, box=BACK_BOX, scale=1, pressed=False, color=None):
    x,y,right,bottom=box
    button_surface(draw, box, color or load_accent(), pressed=pressed, scale=scale)
    cy=(y+bottom)/2
    points=[(x+25,cy-7),(x+18,cy),(x+25,cy+7)]
    draw.line([tuple(round(v*scale) for v in p) for p in points],fill='white',width=max(1,round(2*scale)))
    draw.line(tuple(round(v*scale) for v in (x+18,cy,x+32,cy)),fill='white',width=max(1,round(2*scale)))
    font = ui_font(round(21*scale), 600)
    draw.text((round((x+42)*scale),round(cy*scale)),'Back',font=font,fill='white',anchor='lm')
