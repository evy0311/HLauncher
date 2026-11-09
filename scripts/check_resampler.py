#!/usr/bin/env python3
"""Compare Pi CPU cost and measure VHQ passband/alias rejection; no audio output."""
import argparse
import json
from pathlib import Path
import sys
import time
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from hlauncher.resample import Resampler
from reference_libsamplerate import Resampler as Reference


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    report={}
    for name,kind in (('libsamplerate_best',Reference),('soxr_vhq',Resampler)):
        converter=kind(44100);samples=np.full((882,2),.1,dtype=np.float32)
        start=time.process_time();wall=time.monotonic()
        for _ in range(500):converter.process(samples)
        report[name]=dict(input_seconds=10,cpu_seconds=time.process_time()-start,wall_seconds=time.monotonic()-wall)
        converter.close()
    converter=Resampler(44100)
    signal=.1*np.sin(2*np.pi*20000*np.arange(88200)/44100)
    stereo=np.repeat(signal[:,None],2,axis=1).astype(np.float32)
    converted=np.concatenate([converter.process(stereo[i:i+882]) for i in range(0,len(stereo),882)])
    report['gain_at_20khz_db']=float(20*np.log10(np.sqrt(np.mean(converted[-48000:]**2))/(.1/np.sqrt(2))))
    converter.close()
    converter=Resampler(48000,16000)
    signal=.1*np.sin(2*np.pi*12000*np.arange(96000)/48000)
    converted=converter.process(np.repeat(signal[:,None],2,axis=1).astype(np.float32))
    report['out_of_band_alias_rms']=float(np.sqrt(np.mean(converted[-16000:]**2)))
    converter.close()
    assert abs(report['gain_at_20khz_db'])<.15
    assert report['out_of_band_alias_rms']<1e-6
    assert report['soxr_vhq']['cpu_seconds']<report['libsamplerate_best']['cpu_seconds']/5
    args.output.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
