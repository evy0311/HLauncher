#!/usr/bin/env python3
"""Sustained direct-ALSA-null playback with real SDK PCM and independent UI load.
No receiver is opened; this checks application queues, not hardware clock continuity.
"""
import argparse
import struct
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import numpy as np
ROOT=Path(__file__).resolve().parents[1]


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--seconds',type=int,default=60);p.add_argument('--output',type=Path,required=True);p.add_argument('--pipewire',action='store_true');args=p.parse_args()
    if not 5<=args.seconds<=600:p.error('seconds must be 5–600')
    with tempfile.TemporaryDirectory(prefix='hlauncher-bypass-check-') as folder:
        os.environ.update(HLAUNCHER_STATE_DIR=folder,HLAUNCHER_LOG_DIR=folder+'/logs')
        sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'sdk'))
        from check_audio_stack import Bench
        bench=Bench(folder) if args.pipewire else None
        if bench:
            os.environ.update({key:bench.env[key] for key in ('PIPEWIRE_RUNTIME_DIR','XDG_RUNTIME_DIR','HLAUNCHER_PIPEWIRE_RUNTIME_DIR')})
        (Path(folder)/'audio.json').write_text(json.dumps(dict(pipewire=args.pipewire,eq=True,bass=0,mid=0,treble=0)))
        from hlauncher.audio_process import AudioProcess
        # Render the same navigation workload, using a separate process and no real display.
        holder=bench or SimpleNamespace(folder=Path(folder),env=dict(os.environ,PYTHONPATH=str(ROOT)),stress=None)
        Bench.start_ui_stress(holder)
        events=[]
        capture=Path(folder)/'pipeline.f32' if args.pipewire else None
        audio=AudioProcess(lambda **e:events.append(e),test_device='null',test_capture_file=capture)
        plugin=audio.open_plugin(SimpleNamespace(id='bypass-audit',capabilities={'audio.playback'}))
        plugin.settimeout(.2);audio.enable('bypass-audit',True)
        time.sleep(.2)
        started=time.monotonic();sent=0
        try:
            for block in range(args.seconds*50):
                deadline=started+block*.02+(.04 if block%50==20 else 0)
                time.sleep(max(0,deadline-time.monotonic()))
                t=(np.arange(882)+882*block)/44100
                wave=(.2*np.sin(2*np.pi*997*t)*32767).astype('<i2')
                pcm=np.repeat(wave[:,None],2,axis=1).tobytes()
                raw=b'P'+struct.pack('!IBB',44100,2,1)+pcm
                assert plugin.send(raw)==len(raw)
                sent+=len(pcm)
            time.sleep(.7)
            with audio.condition:
                streams={key:vars(value) for key,value in audio.streams.items()}
            report=dict(seconds=args.seconds,route='PipeWire flat capture' if args.pipewire else 'direct ALSA null',source_rate=44100,input_bytes=sent,
                written_float_bytes=audio.written,failures=audio.failures,peak=audio.peak,
                above_unity_samples=audio.clip_samples,streams=streams,ui_stress_alive=holder.stress.poll() is None,
                hardware_clock_continuity_verified=False)
            args.output.write_text(json.dumps(report,indent=2)+'\n')
            assert audio.failures==0 and audio.clip_samples==0,report
            assert streams and all(s['dropped']==0 for s in streams.values()),report
            assert report['ui_stress_alive'],report
            expected=args.seconds*48000*8
            assert expected-960*8<=audio.written<=expected,report
            if args.pipewire:
                # Do not infer HDMI timing from software-clock capture. Check the
                # steady flat gain after conversion and the complete plugin path.
                values=np.fromfile(capture,dtype='<f4').reshape(-1,2)
                active=np.flatnonzero(np.max(np.abs(values),axis=1)>1e-4)
                settled=values[int(active[0])+48000:int(active[0])+144000]
                report['captured_frames']=len(values)
                report['flat_gain_db']=float(20*np.log10(np.sqrt(np.mean(settled**2))/(.2/np.sqrt(2))))
                assert abs(report['flat_gain_db'])<.02,report
                args.output.write_text(json.dumps(report,indent=2)+'\n')
            print(json.dumps(report,indent=2))
        finally:
            plugin.close();audio.close()
            if bench:bench.close()
            else:holder.stress.terminate();holder.stress.wait(timeout=5);holder.stress_log.close()


if __name__=='__main__':main()
