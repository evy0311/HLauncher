"""Minimal paired-boot frame, independent of themed controls and home artwork."""
from PIL import Image, ImageDraw
from sdk.hlauncher_sdk.fonts import font


def render(size=(720,480)):
    image=Image.new('RGB',size,'#08090d')
    draw=ImageDraw.Draw(image)
    x,y=size[0]//2,size[1]//2
    draw.text((x,y-22),'HLauncher',font=font(38,500),fill='#f4f2f7',anchor='mm')
    draw.text((x,y+30),'Connecting to your radio',font=font(18),fill='#a6a4ad',anchor='mm')
    return image
