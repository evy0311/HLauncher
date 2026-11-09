#!/usr/bin/env python3
"""Measure independent PipeWire band gain and bypass from float PCM, without speakers."""
import array
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    with tempfile.TemporaryDirectory() as folder:
        state = Path(folder)
        env = dict(os.environ, HLAUNCHER_STATE_DIR=folder, PYTHONPATH=str(ROOT))
        def render(bass, enabled, amplitude=.04):
            pcm = b''.join(array.array('f', [amplitude*math.sin(2*math.pi*50*i/48000),
                                            amplitude*math.sin(2*math.pi*1000*i/48000)]).tobytes()
                           for i in range(48000*3))
            (state/'audio.json').write_text(json.dumps(dict(output='hdmi',pipewire=True,
                                                           eq=enabled,bass=bass,mid=0,treble=0)))
            dest=state/'output.raw'
            result=subprocess.run([sys.executable,'-m','hlauncher.pipewire_worker','--device','null',
                                   '--capture-file',str(dest)],input=pcm,env=env,
                                  stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=12)
            if result.returncode:raise RuntimeError(result.stderr.decode(errors='replace'))
            samples=array.array('f',dest.read_bytes())
            # Exclude stream drain silence; measure one settled second before the tail.
            end=len(samples)//2
            while end and max(abs(samples[(end-1)*2]),abs(samples[(end-1)*2+1]))<1e-6:end-=1
            samples=samples[max(0,end-48000)*2:end*2]
            if len(samples)<96000:raise RuntimeError('Too little non-silent captured PCM')
            rms=[math.sqrt(sum(v*v for v in samples[ch::2])/48000) for ch in (0,1)]
            if min(rms)<1e-6:raise RuntimeError('Captured silent PCM')
            return rms,max(abs(v) for v in samples)
        flat,_=render(0,True)
        cut,_=render(-12,True)
        boost,_=render(12,True)
        bypass,_=render(-12,False)
        _,overload_peak=render(12,True,.5)
        def db(values):return [20*math.log10(b/a) for a,b in zip(flat,values)]
        report=dict(cut_db=db(cut),boost_db=db(boost),bypass_db=db(bypass),overload_float_peak=overload_peak)
        print(json.dumps(report,indent=2))
        assert report['cut_db'][0]<-9,'Bass cut did not attenuate the low frequency'
        assert report['boost_db'][0]>9,'Bass boost did not increase absolute low-frequency level'
        assert abs(report['boost_db'][1])<.2,'Bass boost changed the 1 kHz reference level'
        assert all(abs(v)<.1 for v in report['bypass_db']),'Bypass changed flat output'
        assert overload_peak>1.4,'Float EQ appears to be limiting or normalizing overload'
        print('PASS: independent bass gain, unchanged reference level, unity bypass and no hidden limiter')


if __name__=='__main__':main()
