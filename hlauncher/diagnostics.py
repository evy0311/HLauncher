"""Read-only system sampling off the radio/UI thread."""
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import subprocess
import threading
import time

from .config import STATE_DIR


def read(path):
    try:
        return Path(path).read_text().strip().strip('\0')
    except OSError:
        return None


def collect():
    result={'sampled_at':datetime.now(timezone.utc).isoformat()}
    result['model']=read('/proc/device-tree/model') or 'Unavailable'
    try:result['temperature_c']=int(read('/sys/class/thermal/thermal_zone0/temp'))/1000
    except (ValueError,TypeError):result['temperature_c']=None
    memory={}
    for line in (read('/proc/meminfo') or '').splitlines():
        key,_,rest=line.partition(':')
        try:memory[key]=int(rest.split()[0])*1024
        except (ValueError,IndexError):pass
    result['memory_total']=memory.get('MemTotal')
    result['memory_available']=memory.get('MemAvailable')
    try:result['uptime_seconds']=float((read('/proc/uptime') or '').split()[0])
    except (ValueError,IndexError):result['uptime_seconds']=None
    try:
        disk=shutil.disk_usage(STATE_DIR if STATE_DIR.exists() else '/')
        result.update(storage_total=disk.total,storage_free=disk.free)
    except OSError:result.update(storage_total=None,storage_free=None)
    result['dongles']=[]
    for device in Path('/sys/bus/usb/devices').glob('*'):
        if read(device/'idVendor')=='1314':
            result['dongles'].append({'vendor':'1314','product':read(device/'idProduct'),
                                      'name':read(device/'product') or 'USB adapter'})
    try:result['load_average']=[float(v) for v in (read('/proc/loadavg') or '').split()[:3]]
    except ValueError:result['load_average']=None
    result['power_flags']=None
    if executable:=shutil.which('vcgencmd'):
        try:
            output=subprocess.run([executable,'get_throttled'],capture_output=True,text=True,timeout=1,check=True)
            result['power_flags']=int(output.stdout.strip().split('=')[1],16)
        except (OSError,subprocess.SubprocessError,ValueError,IndexError):pass
    return result


def power_status(flags):
    if flags is None:return 'Unavailable'
    current=[]
    for bit,label in ((0,'Low voltage'),(1,'Frequency capped'),(2,'Throttled'),(3,'Temperature limit')):
        if flags & (1<<bit):current.append(label)
    if current:return ', '.join(current)
    return 'OK · earlier warning recorded' if flags & 0xf0000 else 'OK · no warnings'


class Diagnostics:
    def __init__(self):
        self.lock=threading.Lock()
        self.values={};self.revision=0;self.report_status=''
        self.cancel=threading.Event();self.thread=None;self.saving=False

    def start(self):
        if self.thread and self.thread.is_alive() and not self.cancel.is_set():return
        self.cancel=threading.Event()
        cancel=self.cancel
        def run():
            while not cancel.is_set():
                try:values=collect()
                except Exception as exc:values={'error':str(exc)}
                with self.lock:self.values=values;self.revision+=1
                if cancel.wait(2):break
        self.thread=threading.Thread(target=run,daemon=True);self.thread.start()

    def stop(self):
        self.cancel.set()

    def snapshot(self):
        with self.lock:return dict(self.values),self.revision,self.report_status

    def save_report(self,runtime):
        with self.lock:
            if self.saving:return
            self.saving=True;self.report_status='Saving report…';self.revision+=1
            snapshot=dict(self.values)
        def save():
            try:
                folder=STATE_DIR/'diagnostics';folder.mkdir(parents=True,exist_ok=True)
                name='hlauncher-'+datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S-%f')+'.json'
                path=folder/name
                payload={'schema':1,'system':snapshot,'launcher':runtime}
                with path.open('x') as output:json.dump(payload,output,indent=2);output.write('\n')
                message='Report saved locally'
            except (OSError,TypeError,ValueError):message='Could not save report'
            with self.lock:self.report_status=message;self.saving=False;self.revision+=1
        threading.Thread(target=save,daemon=True).start()
