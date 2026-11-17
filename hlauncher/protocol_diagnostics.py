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
from .config import STATE_DIR
from .protocol.vehicle_can import DRIVING_API_IDS, PARKING_DIAGNOSTIC_API_IDS, SCOPED_API_IDS
from .vehicle_last_known import VehicleLastKnown
from .vehicle_protocol import VehicleTraffic

NAMES = {0x01:'Session',0x09:'App information',0x11:'Connection status',0x43:'Touch',
         0x51:'Keyboard status',0x61:'Radio status',0x62:'Status request',0x63:'Status',0xb1:'Device information',
         0xb2:'Device reply',0xb3:'App disconnect',0xc1:'CAN / steering',0xc2:'CAN subscription'}
PREFIXES = ('iap_', 'honda_', 'radio_control_', 'radio_button', 'projection_',
            'audio_meter_', 'audio_capture_', 'audio_hfp_', 'audio_voice_', 'plugin_audio_', 'protocol_')
TRANSPORT = {'rx','protocol_tx','connected','closed','released','registered','socket_error','tx_error'}
SETUP_BRAKE_MAX_AGE = 6
SPEED_MAX_AGE = 2


class ProtocolDiagnostics:
    def __init__(self, folder=None, file_limit=8*1024*1024, total_limit=64*1024*1024,
                 min_free=64*1024*1024, *, vehicle_path=None):
        self.folder=Path(folder) if folder else STATE_DIR/'protocol-captures'
        self.file_limit=file_limit;self.total_limit=total_limit;self.min_free=min_free
        self.lock=threading.RLock();self.pending=queue.Queue(1024)
        self.recording=False;self.thread=None;self.closed=False
        self.status='Ready';self.filename='';self.dropped=0;self.saved=0;self.revision=0
        self.counts=Counter();self.advertised=set();self.sessions={};self.messages={}
        self.recent=deque(maxlen=12);self.voice={};self.mic={};self.connected=False
        self.last_marker='';self.sequence=0
        self.vehicle=VehicleTraffic()
        self.last_reported_speed = None
        self.last_reported_speed_at = None
        self.last_reported_speed_session = None
        self.last_vehicle = VehicleLastKnown(vehicle_path)
        self.app_keys = deque(maxlen=6)
        self.display_trials = deque(maxlen=4)

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
            if state == 'honda_can_data' and self.connected and event.get('data_type', 0) == 0:
                speeds = [record.get('signals', {}).get('152', -1) for record in event['records']]
                valid_speeds = [speed for speed in speeds if 0 <= speed <= 400]
                if valid_speeds:
                    self.last_reported_speed = max(valid_speeds)
                    self.last_reported_speed_at = event['monotonic']
                    self.last_reported_speed_session = event['session']
            speed_session_closed = (state == 'iap_data_session_closed'
                                    or (state == 'honda_can_authorization' and not event.get('authorized')))
            if speed_session_closed and item.get('session') in (None, self.last_reported_speed_session):
                self.last_reported_speed_at = None
            if state=='connected' and str(item.get('uuid','')).endswith('cafe'):
                self.connected = True
                self.last_vehicle.select_device(item.get('device'))
            if state in ('closed','released') and str(item.get('uuid','')).endswith('cafe'):
                self.connected=False;self.sessions.clear();self.vehicle.clear()
                self.last_reported_speed = None
                self.last_reported_speed_at = self.last_reported_speed_session = None
                self.last_vehicle.flush_requested = True
            if state=='iap_remote_reset':
                self.advertised.clear();self.sessions.clear();self.vehicle.clear()
                self.last_reported_speed_at = None
            if state=='honda_app_disconnect_received':
                self.vehicle.clear()
                self.last_reported_speed_at = None
            self.remember_vehicle(event)
            if state=='honda_display_test_result':
                self.display_trials.appendleft(dict(event))
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
            if state=='radio_button' and item.get('source') in ('hondalink-iap','hfp','avrcp'):
                button = str(item.get('button', '')).replace('_', ' ').capitalize()
                self.app_keys.appendleft(dict(event, label=button))
            if state=='honda_frame':
                for detail in self.vehicle.observe(event):self.observe(detail)

    def ensure_writer(self):
        if not self.thread and not self.closed:
            self.thread = threading.Thread(target=self._write, daemon=True)
            self.thread.start()

    def start(self):
        with self.lock:
            if self.recording or self.closed:return
            self.ensure_writer()
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
                app_keys=list(self.app_keys),display_trials=list(self.display_trials),
                vehicle_status=dict(self.vehicle.status),vehicle_changes=self.vehicle.changes,
                vehicle_readings=self.vehicle.snapshot_readings(),
                vehicle_gps=self.vehicle.snapshot_gps(),
                vehicle_signals=self.vehicle.snapshot_signals(),
                vehicle_can_records=self.vehicle.snapshot_can_records(),
                vehicle_subscription=dict(self.vehicle.subscription))

    def remember_vehicle(self, event):
        state = event['state']
        saved = self.last_vehicle
        active = self.vehicle.subscription.get('scope') == 'vehicle'
        now = event['monotonic']
        if state == 'honda_can_data' and active and self.connected and event.get('scope') == 'vehicle':
            if event['data_type']:
                saved.update_report(event['data_type'], event['records'], now)
            else:
                saved.update(self.vehicle_readings_from(event), now)
        elif state == 'honda_radio_status' and active and self.connected:
            saved.update({'brake': event['parking_brake_engaged']}, now)
        elif ((state == 'honda_can_subscription_queued' and event.get('scope') != 'vehicle') or
              state in ('iap_data_session_closed', 'iap_remote_reset', 'honda_app_disconnect_received')):
            saved.flush_requested = True
        if saved.path and saved.revision != saved.written:
            self.ensure_writer()

    def vehicle_readings_from(self, event):
        now = event['monotonic']
        readings = {str(row['api_id']): row['value']
                    for row in self.vehicle.signals.snapshot(now, SCOPED_API_IDS['vehicle'])
                    if row['received'] and row['at'] == now}
        identity = {0x99f00006: 'head-unit', 0x99f00007: 'vin'}
        for record in event['records']:
            if label := identity.get(record['can_id']):
                raw = bytes.fromhex(record['data'])
                value = raw.rstrip(b'\x00').decode('ascii', errors='replace')
                if value:
                    readings[label] = value if value.isascii() and value.isprintable() else raw.hex().upper()
        gps = self.vehicle.gps
        if gps.get('at') == now and gps['fix'] is not None:
            readings['latitude'], readings['longitude'] = gps['fix']
        return readings

    def vehicle_plugin_snapshot(self, now):
        with self.lock:
            saved = self.last_vehicle
            snapshot = dict(last_updated=saved.updated_text(now), readings=dict(saved.readings))
            return snapshot, saved.report_revision, saved.report_view()

    def save_last_vehicle(self, *, force=False):
        saved = self.last_vehicle
        with self.lock:
            update = saved.pending_write(time.monotonic(), force=force)
        if update is None:
            return
        revision, payload = update
        try:
            saved.write(payload)
        except OSError:
            # Keep the pending readings in memory and retry on the next interval.
            return
        with self.lock:
            saved.written = revision

    def gauge_snapshot(self, now=None):
        """Small in-memory handoff; no recorder or persistent-file dependency."""
        now=time.monotonic() if now is None else now
        with self.lock:
            rows=self.vehicle.signals.snapshot(now,{44,40,167,1002,12,1003})
            names={44:'rpm',40:'coolant_c',167:'pedal_percent',1002:'intake_c',12:'baro_native',1003:'vtec'}
            readings={names[row['api_id']]:dict(value=row['value'],monotonic=row['at'],
                interval_seconds=row['interval_seconds'],samples=row['samples'])
                for row in rows if row['received']}
            return dict(connected=self.connected,monotonic=now,readings=readings)

    def projection_speed(self, now):
        speed, = self.vehicle.signals.snapshot(now, {152})
        if speed['received'] and 0 <= speed['age_seconds'] < SPEED_MAX_AGE and 0 <= speed['value'] <= 400:
            return speed['value'], speed['at'] + SPEED_MAX_AGE
        return None, None

    def projection_gps(self, *, include_speed=False):
        now = time.monotonic()
        with self.lock:
            gps = self.vehicle.snapshot_gps(now)
            if not self.connected or not gps or gps['stale'] or gps['fix'] is None:
                return None
            latitude, longitude = gps['fix']
            fix = dict(latitude=latitude, longitude=longitude, at=gps['at'])
            if include_speed:
                speed, until = self.projection_speed(now)
                if until is not None and abs(gps['at'] - (until - 2)) <= 1:
                    fix.update(speed_kph=speed, speed_until=until)
            return fix

    def projection_vehicle_state(self, now=None):
        now = time.monotonic() if now is None else now
        state = dict(speed_kph=None, parking_brake=None, speed_until=None, brake_until=None)
        with self.lock:
            if self.connected:
                state['speed_kph'], state['speed_until'] = self.projection_speed(now)
                brake = self.vehicle.status
                if 'at' in brake and 0 <= now - brake['at'] < 2:
                    state.update(parking_brake=brake['parking_brake_engaged'], brake_until=brake['at'] + 2)
        return state

    def parked_for_setup(self, now=None):
        """Use the radio brake when speed is missing, with reported motion taking priority."""
        speed, brake = self.parked_setup_readings(now)
        return brake is True and speed in (None, 0)

    def plugin_parking_state(self, now=None):
        """Publish only live readings and the stricter parked check for plugins."""
        now = time.monotonic() if now is None else now
        with self.lock:
            speed = brake = None
            if self.connected:
                brake = self._setup_brake(now)
                # Keep the original expiry when a plugin switches CAN subscriptions.
                at = self.last_reported_speed_at
                if at is not None and 0 <= now - at < SPEED_MAX_AGE:
                    speed = self.last_reported_speed
            return dict(connected=self.connected, speed_kph=speed, parking_brake=brake,
                        safely_parked=speed == 0 and brake is True)

    def _setup_brake(self, now):
        brake = self.vehicle.status
        # Civic 0x61 reports brake changes promptly and repeats about every 5 s.
        if 'at' in brake and 0 <= now - brake['at'] < SETUP_BRAKE_MAX_AGE:
            return brake['parking_brake_engaged']
        return None

    def parked_setup_readings(self, now=None):
        now = time.monotonic() if now is None else now
        with self.lock:
            if not self.connected:
                return None, None
            speed, _ = self.projection_speed(now)
            # Losing the speed feed or changing subscriptions must not erase reported motion.
            if self.last_reported_speed:
                speed = self.last_reported_speed
            return speed, self._setup_brake(now)

    def parking_snapshot(self, now=None):
        """Read the gate and candidate signals together for the support screen."""
        now = time.monotonic() if now is None else now
        with self.lock:
            brake = self.vehicle.status
            speed, engaged = self.parked_setup_readings(now)
            return dict(connected=self.connected, parked=self.parked_for_setup(now),
                        brake_only=engaged is True and speed is None,
                        radio_brake=brake.get('parking_brake_engaged'),
                        radio_flags=brake.get('flags'),
                        radio_age=now - brake['at'] if 'at' in brake else None,
                        can_signals=self.vehicle.signals.snapshot(
                            now, set(DRIVING_API_IDS + PARKING_DIAGNOSTIC_API_IDS)))

    def parked_setup_refresh_pending(self):
        """Allow the overlay to wait briefly while a parked page awaits fresh data."""
        with self.lock:
            if not self.connected or self.vehicle.status.get('parking_brake_engaged') is not True:
                return False
            speed, _ = self.parked_setup_readings()
            return speed in (0, None)

    def illumination_night_mode(self, now=None):
        now = time.monotonic() if now is None else now
        with self.lock:
            # HondaLink API 6 (C_ACILL) follows the parking lights or headlights.
            lights, = self.vehicle.signals.snapshot(now, {6})
            return lights['received'] and not lights['stale'] and lights['value'] is True

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
                self.save_last_vehicle()
        finally:
            finish()
            self.save_last_vehicle(force=True)

    def close(self):
        with self.lock:
            if self.closed:
                return
            self.closed = True
        self.stop()
        if self.thread:
            # Called during shutdown, not from a display callback.
            try:self.pending.put(('close',None),timeout=1)
            except queue.Full:return
            self.thread.join(timeout=3)
