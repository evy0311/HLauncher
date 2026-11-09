#!/usr/bin/env python3
"""Size the approved full-name HLauncher artwork for the adapter and UI."""
from pathlib import Path
from PIL import Image

DEST=Path(__file__).resolve().parents[1]/'hlauncher/ui/assets/branding'
SOURCE=DEST/'hlauncher-source.png'
SIZES=(120,180,256,512)


def render(size):
    with Image.open(SOURCE) as source:
        if source.width!=source.height:
            raise ValueError('OEM icon source must be square')
        return source.convert('RGBA').resize((size,size),Image.Resampling.LANCZOS)


if __name__=='__main__':
    for size in SIZES:
        render(size).save(DEST/f'hlauncher-{size}.png',optimize=True)
