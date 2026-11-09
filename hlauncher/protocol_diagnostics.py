"""Bounded protocol capture: event callbacks never perform disk I/O."""
from collections import Counter, deque
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import queue
import shutil
import threading
import time
from .vehicle_protocol import VehicleTraffic

from .config import STATE_DIR

NAMES = {0x01:'Session',0x09:'App information',0x11:'Connection status',0x43:'Touch',
         0x51:'Keyboard status',0x61:'Radio status',0x62:'Status request',0x63:'Status',0xb1:'Device information',
         0xb2:'Device reply',0xb3:'App disconnect',0xc1:'CAN / steering',0xc2:'CAN subscription'}
PREFIXES = ('iap_', 'honda_', 'radio_control_', 'radio_button', 'projection_',
            'audio_meter_', 'audio_capture_', 'audio_hfp_', 'audio_voice_', 'plugin_audio_', 'protocol_')
TRANSPORT = {'rx','protocol_tx','connected','closed','released','registered','socket_error','tx_error'}


class ProtocolDiagnostics:
    def __init__(self, folder=None, file_limit=8*1024*1024, total_limit=64*1024*1024,
                 min_free=64*1024*1024):
        self.folder=Path(folder) if folder else STATE_DIR/'protocol-captures'
        self.file_limit=file_limit;self.total_limit=total_limit;self.min_free=min_free
        self.lock=threading.RLock();self.pending=queue.Queue(1024)
        self.recording=False;self.thread=None;self.closed=False
        self.status='Ready';self.filename='';self.dropped=0;self.saved=0;self.revision=0
        self.counts=Counter();self.advertised=set();self.sessions={};self.messages={}
        self.recent=deque(maxlen=12);self.voice={};self.mic={};self.connected=False
        self.last_marker='';self.sequence=0
        self.vehicle=VehicleTraffic()

    def observe(self, item):
        state=item.get('state','')
        if not isinstance(state,str) or not (state.startswith(PREFIXES) or state in TRANSPORT):return
        # No microphone samples or PCM payloads enter this recorder.
        event={k:v for k,v in item.items() if k not in ('pcm','audio','samples')}
        event=dict(event,wall=item.get('wall') or datetime.now(timezone.utc).isoformat(),
                   monotonic=time.monotonic())
        with self.lock:
            self.sequence+=1;event['capture_sequence']=self.sequence
            self.counts[state]+=1;self.revision+=1
            self.vehicle.observe_can(event)
            if state=='iap_ea_protocol':self.advertised.add(str(item.get('name',''))[:160])
            if state=='iap_data_session_result':
                if item.get('status')==0:self.sessions[str(item.get('session'))]=dict(protocol=item.get('protocol'),status=0)
                else:self.sessions.pop(str(item.get('session')),None)
            if state=='iap_data_session_closed':
                self.sessions.pop(str(item.get('session')),None)
                self.vehicle.clear(item.get('session'))
            if state=='connected' and str(item.get('uuid','')).endswith('cafe'):self.connected=True
            if state in ('closed','released') and str(item.get('uuid','')).endswith('cafe'):
                self.connected=False;self.sessions.clear();self.vehicle.clear()
            if state=='iap_remote_reset':
                self.advertised.clear();self.sessions.clear();self.vehicle.clear()
            if state=='honda_app_disconnect_received':self.vehicle.clear()
            if state in ('projection_voice_state','projection_voice_route'):self.voice={k:v for k,v in item.items() if k!='state'}
            if state.startswith(('audio_meter_','audio_capture_')):self.mic.update({k:v for k,v in item.items() if k!='state'})
            if state=='projection_mic_stats':self.mic.update({k:v for k,v in item.items() if k!='state'})
            if state=='honda_frame':
                message=item.get('message');key=f"{item.get('session')}:{message}"
                payload=str(item.get('payload',''))
                if key not in self.messages and len(self.messages)>=512:return
                row=self.messages.setdefault(key,dict(session=item.get('session'),message=message,
                    name=NAMES.get(message,'Unmapped message'),count=0,bytes=0,preview=''))
                row.update(count=row['count']+1,bytes=row['bytes']+len(payload)//2,preview=payload[:64])
                summary=f"Honda 0x{message:02x} · {len(payload)//2} bytes" if isinstance(message,int) else 'Honda frame'
            elif state=='radio_control_rx':summary=f"{item.get('source')}: {item.get('summary')}"
            elif state=='protocol_marker':summary='Marked: '+str(item.get('label'))
            else:summary=state.replace('_',' ')
            if state!='protocol_capture_stats':self.recent.appendleft(summary[:90])
            if self.recording:
                try:self.pending.put_nowait(('event',event))
                except queue.Full:self.dropped+=1
            if state=='honda_frame':
                for detail in self.vehicle.observe(event):self.observe(detail)

    def start(self):
        with self.lock:
            if self.recording or self.closed:return
            if not self.thread:
                self.thread=threading.Thread(target=self._write,daemon=True);self.thread.start()
            try:self.pending.put_nowait(('start',None))
            except queue.Full:self.status='Capture queue full';return
            self.recording=True;self.status='Recording';self.revision+=1
        self.marker('Capture started')
        from . import __version__
        try:boot_id=Path('/proc/sys/kernel/random/boot_id').read_text().strip()
        except OSError:boot_id=None
        self.observe(dict(state='protocol_capture_info',schema=2,version=__version__,
                          launcher_pid=os.getpid(),boot_id=boot_id,microphone_audio_recorded=False))

    def stop(self):
        with self.lock:
            if not self.recording:return
        self.observe(dict(state='protocol_capture_stats',saved=self.saved,dropped=self.dropped))
        self.marker('Capture stopped')
        with self.lock:
            if not self.recording:return
            try:self.pending.put_nowait(('stop',None))
            except queue.Full:self.status='Capture queue full';return
            self.recording=False;self.status='Capture saved';self.revision+=1

    def marker(self, label):
        with self.lock:self.last_marker=str(label)[:60]
        self.observe(dict(state='protocol_marker',label=self.last_marker))

    def snapshot(self):
        with self.lock:
            return dict(recording=self.recording,status=self.status,filename=self.filename,
                saved=self.saved,dropped=self.dropped,revision=self.revision,connected=self.connected,
                counts=dict(self.counts),advertised=sorted(self.advertised),sessions=dict(self.sessions),
                messages=[dict(v) for v in self.messages.values()],recent=list(self.recent),
                voice=dict(self.voice),mic=dict(self.mic),last_marker=self.last_marker,
                vehicle_status=dict(self.vehicle.status),vehicle_changes=self.vehicle.changes,
                vehicle_readings=self.vehicle.snapshot_readings(),
                vehicle_subscription=dict(self.vehicle.subscription))

    def _write(self):
        output=None;written=0;part=0;last_flush=time.monotonic()
        def finish():
            nonlocal output
            old,output=output,None
            if old:
                try:
                    old.flush();os.fsync(old.fileno())
                except OSError as exc:
                    with self.lock:self.status='Capture error: '+str(exc)[:80];self.recording=False;self.revision+=1
                try:old.close()
                except OSError as exc:
                    with self.lock:self.status='Capture error: '+str(exc)[:80];self.recording=False;self.revision+=1
        def open_part():
            nonlocal output,written,part
            finish();self.folder.mkdir(parents=True,exist_ok=True,mode=0o700)
            if shutil.disk_usage(self.folder).free < self.min_free:raise OSError('Capture storage is full')
            old=sorted(self.folder.glob('protocol-*.jsonl'))
            size=sum(p.stat().st_size for p in old)
            while old and size>max(0,self.total_limit-self.file_limit):
                path=old.pop(0);size-=path.stat().st_size;path.unlink()
            part+=1
            name='protocol-'+datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S-%f')+f'-{part:03}.jsonl'
            output=(self.folder/name).open('x',encoding='utf-8');written=0
            # The parent folder is private; keep protocol captures private too.
            os.chmod(self.folder/name,0o600)
            with self.lock:self.filename=name;self.revision+=1
        try:
            while True:
                try:kind,item=self.pending.get(timeout=.5)
                except queue.Empty:kind,item='flush',None
                try:
                    if kind=='close':break
                    if kind=='start':open_part()
                    elif kind=='stop':finish()
                    elif kind=='event' and output:
                        line=json.dumps(item,ensure_ascii=False,allow_nan=False)+'\n'
                        if written+len(line.encode())>self.file_limit:open_part()
                        output.write(line);written+=len(line.encode())
                        with self.lock:self.saved+=1
                    if output and time.monotonic()-last_flush>1:
                        output.flush();os.fsync(output.fileno());last_flush=time.monotonic()
                        if self.recording:self.observe(dict(state='protocol_capture_stats',saved=self.saved,dropped=self.dropped))
                        if shutil.disk_usage(self.folder).free<self.min_free:raise OSError('Capture storage is full')
                except (OSError,ValueError,TypeError) as exc:
                    finish()
                    with self.lock:
                        self.status='Capture error: '+str(exc)[:80];self.recording=False;self.revision+=1
                finally:
                    if kind!='flush':self.pending.task_done()
        finally:finish()

    def close(self):
        self.stop()
        with self.lock:self.closed=True
        if self.thread:
            # Called during shutdown, not from a display callback.
            try:self.pending.put(('close',None),timeout=1)
            except queue.Full:return
            self.thread.join(timeout=3)
