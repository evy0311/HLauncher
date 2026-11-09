#!/usr/bin/env python3
"""Meter the private EQ output without changing gain or producing test audio."""
import argparse
import json
import math
import os
from pathlib import Path
import select
import subprocess
import sys
import time
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from hlauncher.audio_settings import RUNTIME,pw_run

def main():
    p=argparse.ArgumentParser();p.add_argument('--seconds',type=float,default=5);a=p.parse_args()
    env=dict(os.environ,PIPEWIRE_RUNTIME_DIR=RUNTIME,XDG_RUNTIME_DIR=RUNTIME)
    name='hlauncher_peak_meter_'+str(os.getpid())
    proc=subprocess.Popen(['pw-cat','--record','--target=0','--rate=48000','--channels=2','--format=f32',
        '--latency=80ms','--properties='+json.dumps({'node.name':name}),'-'],
        stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,env=env)
    peak=0.;over=samples=0;pending=b''
    try:
        for _ in range(30):
            objects=json.loads(pw_run(['pw-dump']).stdout)
            nodes={o.get('info',{}).get('props',{}).get('node.name'):o['id'] for o in objects if o['type'].endswith(':Node')}
            if name in nodes:break
            time.sleep(.03)
        else:raise RuntimeError('Meter node unavailable')
        config=dict(direction='Input',mode='dsp',format=dict(mediaType='audio',mediaSubtype='raw',
            format='F32P',rate=48000,channels=2,position=['FL','FR']))
        pw_run(['pw-cli','set-param',str(nodes[name]),'PortConfig',json.dumps(config)])
        for channel in ('FL','FR'):pw_run(['pw-link','hlauncher_eq_output:capture_'+channel,name+':input_'+channel])
        os.set_blocking(proc.stdout.fileno(),False);until=time.monotonic()+max(1,min(10,a.seconds))
        while time.monotonic()<until:
            if not select.select([proc.stdout],[],[],.1)[0]:continue
            raw=os.read(proc.stdout.fileno(),65536)
            if not raw:break
            pending+=raw;n=len(pending)//4*4
            values=np.frombuffer(pending[:n],dtype='<f4');pending=pending[n:]
            peak=max(peak,float(np.max(np.abs(values))) if len(values) else 0)
            over+=int(np.count_nonzero(np.abs(values)>1));samples+=len(values)
        print(json.dumps(dict(point='post-EQ float output',peak=peak,peak_dbfs=20*math.log10(peak) if peak else None,
            above_full_scale_samples=over,samples=samples),indent=2))
    finally:
        proc.terminate()
        try:proc.wait(timeout=2)
        except subprocess.TimeoutExpired:proc.kill();proc.wait(timeout=1)
        proc.stdout.close();proc.stderr.close()

if __name__=='__main__':main()
