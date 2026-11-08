#!/usr/bin/env python3
"""Read the active HDMI0 RGB565 DRM scanout without stopping HLauncher.

Run as root on the Pi. This maps the current scanout read-only and never takes
DRM master, changes a mode, or substitutes a re-rendered image for the display.
"""
import argparse
import ctypes as C
import fcntl
import mmap
import os
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from hlauncher.drm import library, MapDumb, U32
from PIL import Image
import numpy as np


class Framebuffer(C.Structure):
    _fields_=[(field,U32) for field in ('id','width','height','pitch','bpp','depth','handle')]


class GemClose(C.Structure):
    _fields_=[('handle',U32),('pad',U32)]


def capture(card):
    lib=library()
    lib.drmModeGetFB.restype=C.POINTER(Framebuffer)
    lib.drmModeGetFB.argtypes=[C.c_int,U32]
    lib.drmModeFreeFB.restype=None
    lib.drmModeFreeFB.argtypes=[C.POINTER(Framebuffer)]
    fd=os.open(card,os.O_RDWR|os.O_CLOEXEC)
    try:
        resources=lib.drmModeGetResources(fd)
        if not resources:raise RuntimeError('DRM resources unavailable')
        try:
            for i in range(resources.contents.count_connectors):
                connector=lib.drmModeGetConnector(fd,resources.contents.connectors[i])
                if not connector:continue
                try:
                    c=connector.contents
                    if c.connection!=1 or c.connector_type!=11 or c.connector_type_id!=1:continue
                    encoder=lib.drmModeGetEncoder(fd,c.encoder_id)
                    if not encoder:continue
                    try:crtc_id=encoder.contents.crtc_id
                    finally:lib.drmModeFreeEncoder(encoder)
                    crtc=lib.drmModeGetCrtc(fd,crtc_id)
                    if not crtc:continue
                    try:fb_id=crtc.contents.buffer_id
                    finally:lib.drmModeFreeCrtc(crtc)
                    fb=lib.drmModeGetFB(fd,fb_id)
                    if not fb:raise OSError(C.get_errno(),'Read active framebuffer')
                    try:
                        f=fb.contents
                        if f.bpp!=16 or f.depth!=16 or not f.handle:
                            raise RuntimeError('Expected a root-readable RGB565 scanout')
                        mapping=MapDumb(handle=f.handle)
                        fcntl.ioctl(fd,0xC01064B3,mapping,True)
                        with mmap.mmap(fd,f.pitch*f.height,flags=mmap.MAP_SHARED,
                                       prot=mmap.PROT_READ,offset=mapping.offset) as memory:
                            values=np.frombuffer(memory,dtype='<u2').reshape(f.height,f.pitch//2)[:,:f.width].copy()
                        r=(values>>11)&31;g=(values>>5)&63;b=values&31
                        rgb=np.stack(((r<<3)|(r>>2),(g<<2)|(g>>4),(b<<3)|(b>>2)),axis=-1).astype('uint8')
                        return Image.fromarray(rgb)
                    finally:
                        if fb.contents.handle:
                            fcntl.ioctl(fd,0x40086409,GemClose(handle=fb.contents.handle))
                        lib.drmModeFreeFB(fb)
                finally:lib.drmModeFreeConnector(connector)
        finally:lib.drmModeFreeResources(resources)
    finally:os.close(fd)
    raise RuntimeError('No active HDMI0 scanout found')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output',type=Path)
    args=parser.parse_args()
    cards=[Path('/dev/dri')/p.name.split('-')[0] for p in Path('/sys/class/drm').glob('card*-HDMI-A-1')
           if (p/'status').read_text().strip()=='connected']
    if not cards:raise SystemExit('HDMI0 is not connected')
    image=capture(str(cards[0]));image.save(args.output)
    print(f'Captured actual DRM scanout: {image.width}x{image.height} -> {args.output}')


if __name__=='__main__':main()
