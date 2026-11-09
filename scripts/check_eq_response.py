#!/usr/bin/env python3
"""Measure the actual isolated PipeWire graph against independent RBJ responses."""
import argparse
import json
from pathlib import Path
import sys
import tempfile
import numpy as np
from check_audio_stack import Bench, RATE
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from hlauncher.audio_settings import EQ_BANDS, PRESETS


def expected_response(freqs,bands):
    response=np.ones(len(freqs),dtype=np.float64)
    z=np.exp(-2j*np.pi*np.asarray(freqs)/RATE)
    for key,center in EQ_BANDS.items():
        gain=bands[key]
        a=10**(gain/40);w=2*np.pi*center/RATE;alpha=np.sin(w)/(2*1.4);c=np.cos(w)
        numerator=(1+alpha*a)-2*c*z+(1-alpha*a)*z*z
        denominator=(1+alpha/a)-2*c*z+(1-alpha/a)*z*z
        response*=np.abs(numerator/denominator)
    return 20*np.log10(response)


def spectrum(pcm,freqs):
    nonzero=np.flatnonzero(np.max(np.abs(pcm),axis=1)>1e-5)
    if not len(nonzero):raise RuntimeError('Captured silence')
    start=int(nonzero[0])+RATE
    window=pcm[start:start+RATE*2]
    if len(window)!=RATE*2:raise RuntimeError('Capture too short for settled spectrum')
    bins=np.asarray(np.asarray(freqs)*2,dtype=int)
    return np.abs(np.fft.rfft(window,axis=0)[bins])*2/len(window)


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True);args=p.parse_args()
    freqs=list(EQ_BANDS.values())
    t=np.arange(RATE*4)/RATE
    signal=sum(.003*np.sin(2*np.pi*f*t+.17*i) for i,f in enumerate(freqs))
    stereo=np.column_stack((signal,signal*.7)).astype('<f4')
    report=dict(frequencies_hz=freqs,bands={},presets={})
    with tempfile.TemporaryDirectory(prefix='hlauncher-eq-response-') as folder:
        bench=Bench(folder)
        try:
            flat_pcm,_=bench.render(stereo,values=dict(bands=PRESETS['Flat']))
            flat=spectrum(flat_pcm,freqs)
            reference=np.column_stack((np.full(len(freqs),.003),np.full(len(freqs),.003*.7)))
            report['flat_gain_db']=(20*np.log10(flat/reference)).tolist()
            assert np.max(np.abs(report['flat_gain_db']))<.02,report['flat_gain_db']
            for key in EQ_BANDS:
                checks={}
                for gain in (-6,6):
                    bands=dict(PRESETS['Flat'],**{key:gain})
                    pcm,_=bench.render(stereo,values=dict(bands=bands))
                    actual=20*np.log10(spectrum(pcm,freqs)/flat)
                    expected=expected_response(freqs,bands)
                    error=float(np.max(np.abs(actual-expected[:,None])))
                    assert error<.12,(key,gain,error)
                    checks[str(gain)]=dict(measured_db=actual[:,0].tolist(),max_model_error_db=error)
                report['bands'][key]=checks
                print('Verified',key,flush=True)
            for name,bands in PRESETS.items():
                pcm,_=bench.render(stereo,values=dict(bands=bands))
                actual=20*np.log10(spectrum(pcm,freqs)/flat)
                expected=expected_response(freqs,bands)
                error=float(np.max(np.abs(actual-expected[:,None])))
                assert error<.12,(name,error)
                report['presets'][name]=dict(measured_db=actual[:,0].tolist(),max_model_error_db=error)
            bypass,_=bench.render(stereo,values=dict(eq=False,bands=PRESETS['EDM Bass'],bass=12,mid=-6,treble=4))
            report['bypass_gain_db']=(20*np.log10(spectrum(bypass,freqs)/flat)).tolist()
            assert np.max(np.abs(report['bypass_gain_db']))<.02
            # Large boost must remain visible above unity in float, not trigger compensation.
            wave=.8*np.sin(2*np.pi*50*np.arange(RATE*4)/RATE)
            pcm,_=bench.render(np.column_stack((wave,wave)).astype('<f4'),values=dict(bands=dict(PRESETS['Flat'],b50=12)))
            report['boost_overload_float_peak']=float(np.max(np.abs(pcm)))
            assert report['boost_overload_float_peak']>3
        finally:bench.close()
    args.output.write_text(json.dumps(report,indent=2)+'\n')
    print('PASS: Flat, 24 independent band responses, presets, bypass and uncompensated overload',flush=True)


if __name__=='__main__':main()
