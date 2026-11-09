"""Confirm background decoding skips RGB output but resumes a complete picture."""
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'plugins/carplay/runtime/video'))
from h264 import H264StreamDecoder
raw=(ROOT/'plugins/carplay/runtime/usb/test-pattern.h264').read_bytes()
visible=H264StreamDecoder(720,480);hidden=H264StreamDecoder(720,480)
try:
    expected=visible.feed(raw)
    assert expected
    assert hidden.feed(raw,render=False)==[]
    assert hidden.decoder.redraw()==expected[-1]
    resumed=hidden.feed(raw,render=True)
    assert resumed and len(resumed[-1])==720*480*2
    print('PASS: background returns no RGB frames; retained picture and resumed stream match')
finally:
    visible.close();hidden.close()
