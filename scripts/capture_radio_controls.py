"""Capture a bounded in-car receive trace without sending radio commands."""
import argparse
from datetime import datetime, timezone
import os
from pathlib import Path
import shutil
import subprocess
import time


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seconds',type=int,default=180)
    parser.add_argument('--output',type=Path)
    parser.add_argument('--check',action='store_true',help='Check tools without starting a capture')
    args=parser.parse_args()
    if not 10<=args.seconds<=900:parser.error('--seconds must be between 10 and 900')
    missing=[tool for tool in ('btmon','journalctl','systemctl','bluetoothctl') if not shutil.which(tool)]
    if missing:parser.error('Missing tools: '+', '.join(missing))
    if args.check:
        print('Receive capture tools available; no capture started.');return
    if os.geteuid()!=0:parser.error('Run with sudo to capture Bluetooth traffic')
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    root=args.output or Path('captures')/('radio-controls-'+stamp)
    os.umask(0o077)
    root.mkdir(parents=True,exist_ok=False)
    processes=[];handles=[]
    try:
        for name,command in (
            ('services.txt',['systemctl','show','bluetooth','civic-bt-bench','civic-bt-connect','hlauncher',
                             '-p','Id','-p','ActiveState','-p','SubState','-p','NRestarts']),
            ('controller.txt',['bluetoothctl','show'])):
            with (root/name).open('w') as output:
                subprocess.run(command,stdout=output,stderr=subprocess.STDOUT,timeout=10,check=False)
        for name,command in (
            ('bluetooth.txt',['btmon','-w',str(root/'controller.btsnoop')]),
            ('services-live.txt',['journalctl','-f','-n','0','-o','short-iso-precise',
                                  '-u','bluetooth','-u','civic-bt-bench','-u','hlauncher'])):
            output=(root/name).open('w');handles.append(output)
            processes.append(subprocess.Popen(command,stdout=output,stderr=subprocess.STDOUT))
        print(f'Receive capture running for {args.seconds}s: {root}',flush=True)
        print('Press each vehicle button separately. Capture files remain local and may contain phone information.',flush=True)
        deadline=time.monotonic()+args.seconds
        while time.monotonic()<deadline:
            if any(process.poll() is not None for process in processes):
                raise RuntimeError('A capture process exited; inspect capture logs')
            time.sleep(.2)
    except KeyboardInterrupt:
        print('Ending receive capture.',flush=True)
    finally:
        for process in processes:
            if process.poll() is None:process.terminate()
        for process in processes:
            try:process.wait(timeout=3)
            except subprocess.TimeoutExpired:process.kill();process.wait(timeout=3)
        for handle in handles:handle.close()
        print('Saved local capture: '+str(root),flush=True)


if __name__=='__main__':main()
