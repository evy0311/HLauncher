#!/usr/bin/env python3
"""Locate overload in known synthetic source, resampler and mixer signals."""
import json
from pathlib import Path
import sys
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from hlauncher.playback import Playback


def main():
    output=Playback(lambda **v:None,start_worker=False)
    pcm=np.full((960,2),24576,dtype='<i2').tobytes()
    for stream in (1,2):output.feed('audit',dict(sample_rate=48000,channels=2,stream=stream,pcm=pcm))
    mixed=np.frombuffer(output.mix(),dtype='<f4')
    levels=[dict(source_peak=s.source_peak,converted_peak=s.converted_peak,
                 source_full_scale_samples=s.source_full_scale_samples) for s in output.streams.values()]
    assert all(s['source_peak']==.75 and s['converted_peak']==.75 for s in levels)
    assert np.all(mixed==1.5) and output.clip_samples==1920
    single=Playback(lambda **v:None,start_worker=False)
    single.feed('audit',dict(sample_rate=48000,channels=2,stream=1,pcm=pcm))
    assert np.all(np.frombuffer(single.mix(),dtype='<f4')==.75)
    rate=44100
    # A bandlimited reconstruction may exceed the discrete sample peak. This is
    # reported separately and must not be silently clipped or attenuated.
    square=(np.where(np.sin(2*np.pi*1000*np.arange(rate//5)/rate)>=0,.9,-.9)*32767).astype('<i2')
    converted=Playback(lambda **v:None,start_worker=False)
    converted.feed('resample',dict(sample_rate=rate,channels=1,stream=1,pcm=square.tobytes()))
    converted.mix()
    s=next(iter(converted.streams.values()))
    report=dict(single_stream_gain=1.0,two_stream_levels=levels,mixer_peak=float(np.max(np.abs(mixed))),
                mixer_above_unity_samples=output.clip_samples,
                resampler_probe=dict(source_peak=s.source_peak,converted_peak=s.converted_peak),
                source_full_scale_note='Full-scale samples indicate saturation risk, not proof that upstream audio clipped.')
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
