#!/usr/bin/env python3
"""Isolated PCM timing and frequency-response measurements; never opens HDMI/BlueZ."""
import argparse
import json
import os
import resource
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
RATE=48000
# Seventeen float32 biquads have a numerical residual even at 0 dB.
# This tolerance is below -80 dBFS, far below a missing/misaligned test frame;
# separate spectral checks enforce unity gain. Do not claim bit-exact DSP.
PCM_ERROR_LIMIT=1e-4


def align(reference, captured):
    # FFT cross-correlation locates the exact first source frame despite graph startup silence.
    left=captured[:RATE*4,0].astype(np.float64)
    right=reference[:RATE,0].astype(np.float64)
    n=1 << (len(left)+len(right)-1).bit_length()
    corr=np.fft.irfft(np.fft.rfft(left,n)*np.conj(np.fft.rfft(right,n)),n)
    before=min(RATE*2,len(right))
    candidates=np.concatenate((corr[-before:],corr[:len(left)]))
    lag=int(np.argmax(candidates))-before
    source_start=max(0,-lag);capture_start=max(0,lag)
    count=min(len(reference)-source_start,len(captured)-capture_start)
    if count<RATE:raise RuntimeError('Too little captured signal')
    error=captured[capture_start:capture_start+count]-reference[source_start:source_start+count]
    return dict(offset_frames=lag,source_frames_missing_at_start=source_start,
                compared_frames=count,max_error=float(np.max(np.abs(error))),
                rms_error=float(np.sqrt(np.mean(error**2))),bad_frames=int(np.count_nonzero(np.max(np.abs(error),axis=1)>PCM_ERROR_LIMIT)))


def cpu_seconds(pid):
    try:
        fields=Path(f'/proc/{pid}/stat').read_text().rsplit(')',1)[1].split()
        return (int(fields[11])+int(fields[12]))/os.sysconf('SC_CLK_TCK')
    except (OSError,IndexError,ValueError):return 0.0


class Bench:
    def __init__(self,folder):
        self.folder=Path(folder)
        runtime=self.folder/'runtime';runtime.mkdir(mode=0o700)
        self.env=dict(os.environ,PIPEWIRE_RUNTIME_DIR=str(runtime),XDG_RUNTIME_DIR=str(runtime),
            HLAUNCHER_PIPEWIRE_RUNTIME_DIR=str(runtime),HLAUNCHER_STATE_DIR=str(self.folder),
            HLAUNCHER_LOG_DIR=str(self.folder/'logs'),PYTHONPATH=str(ROOT))
        self.graph_log=(self.folder/'graph.log').open('w+')
        self.graph=subprocess.Popen(['pipewire','-c',str(ROOT/'config/pipewire.conf')],env=self.env,
                                    stdout=self.graph_log,stderr=subprocess.STDOUT)
        self.stress=None
        for _ in range(100):
            if (runtime/'pipewire-0').exists():break
            if self.graph.poll() is not None:raise RuntimeError('Isolated PipeWire graph failed')
            time.sleep(.02)
        else:raise RuntimeError('Isolated PipeWire graph did not start')

    def render(self,signal,*,values=None,paced=False,old_client=False):
        settings=dict(output='hdmi',pipewire=True,eq=True,bass=0,mid=0,treble=0)
        settings.update(values or {})
        (self.folder/'audio.json').write_text(json.dumps(settings))
        dest=self.folder/'capture.f32'
        err=(self.folder/'worker.log').open('w+')
        graph_offset=(self.folder/'graph.log').stat().st_size
        top_log=(self.folder/'top.log').open('w+')
        top=subprocess.Popen(['pw-top','-b'],env=self.env,stdout=top_log,stderr=subprocess.STDOUT)
        command=[sys.executable,'-m','hlauncher.pipewire_worker','--device','null','--capture-file',str(dest)]
        if old_client:command.append('--compare-pw-cat')
        proc=subprocess.Popen(command,cwd=ROOT,env=self.env,stdin=subprocess.PIPE,
                              stdout=subprocess.DEVNULL,stderr=err,bufsize=0)
        started=time.monotonic()
        graph_cpu=cpu_seconds(self.graph.pid)
        ui_cpu=cpu_seconds(self.stress.pid) if self.stress else 0
        child_cpu=resource.getrusage(resource.RUSAGE_CHILDREN)
        child_cpu=child_cpu.ru_utime+child_cpu.ru_stime
        try:
            # Writes are confined to this non-realtime producer. Deterministic 40 ms pauses
            # model packet jitter; the production callback must never wait for this pipe.
            for block,at in enumerate(range(0,len(signal),960)):
                if paced:
                    deadline=started+block*.02+(.04 if block%50==20 else 0)
                    time.sleep(max(0,deadline-time.monotonic()))
                raw=memoryview(signal[at:at+960].astype('<f4',copy=False)).cast('B')
                while raw:
                    written=os.write(proc.stdin.fileno(),raw);raw=raw[written:]
            proc.stdin.close()
            proc.wait(timeout=15)
            if proc.returncode:raise RuntimeError('Audio worker failed')
        except Exception as exc:
            err.flush();err.seek(0)
            raise RuntimeError(f'{exc}: '+err.read()) from exc
        finally:
            if proc.poll() is None:proc.kill();proc.wait(timeout=3)
            if not proc.stdin.closed:proc.stdin.close()
            err.seek(0);log=err.read();err.close()
            top.terminate();top.wait(timeout=3);top_log.seek(0);top_text=top_log.read();top_log.close()
        stats=[]
        for line in log.splitlines():
            try:
                item=json.loads(line)
                if item.get('state')=='pipewire_pcm_stats':stats.append(item)
            except ValueError:pass
        elapsed=time.monotonic()-started
        children=resource.getrusage(resource.RUSAGE_CHILDREN)
        cpu=dict(graph_percent_of_one_core=100*(cpu_seconds(self.graph.pid)-graph_cpu)/elapsed,
                 client_tree_percent_of_one_core=100*(children.ru_utime+children.ru_stime-child_cpu)/elapsed,
                 ui_percent_of_one_core=100*(cpu_seconds(self.stress.pid)-ui_cpu)/elapsed if self.stress else 0)
        pcm=np.fromfile(dest,dtype='<f4').reshape(-1,2)
        graph_text=(self.folder/'graph.log').read_text()[graph_offset:]
        graph_errors={}
        for line in top_text.splitlines():
            fields=line.split()
            if len(fields)>9 and fields[0] in ('R','S','I') and fields[8].isdigit():
                name=' '.join(fields[9:])
                graph_errors[name]=max(graph_errors.get(name,0),int(fields[8]))
        return pcm,dict(elapsed_seconds=elapsed,cpu=cpu,client_stats=stats,
                        graph_error_counters=graph_errors,graph_diagnostic_tail=graph_text[-2000:],
                        xrun_messages=log.lower().count('xrun')+graph_text.lower().count('xrun'),diagnostic_tail=log[-2000:])

    def start_ui_stress(self):
        code='''import sys,time
from pathlib import Path
sys.path.insert(0,str(Path.cwd()/'tests'))
from test_architecture import Display
from hlauncher.launcher import Launcher
ui=Launcher(framebuffer=Display(),manifests={})
try:
 while True:
  for page in (ui.settings,ui.audio_page,ui.home):
   page();ui.tick();time.sleep(.025)
finally:ui.close()
'''
        self.stress_log=(self.folder/'ui.log').open('w+')
        self.stress=subprocess.Popen([sys.executable,'-c',code],cwd=ROOT,env=self.env,
                                     stdout=self.stress_log,stderr=subprocess.STDOUT)

    def close(self):
        if self.stress:
            self.stress.terminate();self.stress.wait(timeout=5);self.stress_log.close()
        self.graph.terminate();self.graph.wait(timeout=5);self.graph_log.close()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seconds',type=int,default=90)
    parser.add_argument('--output',type=Path)
    parser.add_argument('--compare-old',action='store_true')
    args=parser.parse_args()
    if not 3<=args.seconds<=600:parser.error('seconds must be 3–600')
    report={}
    with tempfile.TemporaryDirectory(prefix='hlauncher-audio-bench-') as folder:
        bench=Bench(folder)
        try:
            bench.start_ui_stress()
            signal=np.random.default_rng(345).uniform(-.1,.1,(args.seconds*RATE,2)).astype('<f4')
            if args.compare_old:
                pcm,stats=bench.render(signal,paced=True,old_client=True)
                report['former_pw_cat']=dict(stats,**align(signal,pcm))
            pcm,stats=bench.render(signal,paced=True)
            result=dict(stats,**align(signal,pcm))
            result['ui_stress_alive']=bench.stress.poll() is None
            report['buffered_flat']=result
            if args.output:args.output.write_text(json.dumps(report,indent=2)+'\n')
            assert result['max_error']<PCM_ERROR_LIMIT and result['rms_error']<2e-5 and result['bad_frames']==0,result
            assert result['compared_frames']>=len(signal)-960,result
            assert result['source_frames_missing_at_start']==0,result
            assert result['client_stats'] and all(s['underrun_frames']==0 for s in result['client_stats']),result
            assert not any(result['graph_error_counters'].values()),result
            assert result['graph_error_counters'], 'PipeWire profiler counters missing'
            assert all(s['max_callback_gap_ms']<40 for s in result['client_stats'] if s.get('mode')=='playback'),result
            assert result['ui_stress_alive'], 'UI stress exited before audio completed'
        finally:bench.close()
    if args.output:args.output.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
