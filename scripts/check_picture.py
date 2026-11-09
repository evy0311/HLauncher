#!/usr/bin/env python3
"""Verify picture controls survive incoming full-range frames. No radio access."""
import ctypes
import importlib.util
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'plugins/carplay/runtime/video'))
import h264
from avdecode import AvDecoder,_FrameHead


def run():
    if len(sys.argv)>1:
        spec=importlib.util.spec_from_file_location('candidate_decoder',sys.argv[1])
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        h264.AvDecoder=module.AvDecoder
    x=h264.H264StreamDecoder(720,480)
    d=x.decoder
    original=d._convert
    # YUVJ420P has the same memory layout as YUV420P; force that cache path
    # without requiring a phone capture or relying on AVFrame color-field offsets.
    fmt=d.lib.avutil.av_get_pix_fmt(b'yuvj420p')
    def convert(frame=None):
        frame=frame or d.frame
        _FrameHead.from_address(frame.value).format=fmt
        return original(frame)
    d._convert=convert
    d.read_source_color=lambda:dict(colorspace=6,color_range=2,color_primaries=1,color_trc=13)
    values=dict(saturation=35,contrast=98,brightness=-7)
    rows=[]
    try:
        data=(ROOT/'plugins/carplay/runtime/usb/test-pattern.h264').read_bytes()
        for at in range(0,len(data),211):
            for frame in x.feed(data[at:at+211]):
                if not rows:
                    d.picture=values
                    d.redraw()
                inv,table=ctypes.c_void_p(),ctypes.c_void_p()
                src,dst,brightness,contrast,saturation=(ctypes.c_int() for _ in range(5))
                result=d.lib.swscale.sws_getColorspaceDetails(d.sws,ctypes.byref(inv),ctypes.byref(src),ctypes.byref(table),ctypes.byref(dst),ctypes.byref(brightness),ctypes.byref(contrast),ctypes.byref(saturation))
                assert result>=0
                actual=(saturation.value,contrast.value,brightness.value)
                wanted=tuple(round(values[k]*65536/100) for k in ('saturation','contrast','brightness'))
                assert actual==wanted,(len(rows)+1,actual,wanted)
                assert src.value==1
                rows.append(dict(frame=len(rows)+1,controls=actual,context=d.sws))
        assert len(rows)>=6
        print(json.dumps(dict(result='passed',frames=len(rows),full_range_controls_preserved=True,contexts=len({r['context'] for r in rows}))))
    finally:x.close()

if __name__=='__main__':run()
