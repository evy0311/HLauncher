"""Bounded hardware tests and passive hands-free input observation."""
from collections import deque
import json
import math
import os
from pathlib import Path
import queue
import re
import select
import struct
import subprocess
import sys
import threading
import time

from .buttons import LABELS
BUTTONS = tuple(LABELS) + ('play', 'pause', 'stop', 'dial', 'redial')
# Linux input-event-codes.h; never grab the radio's input device exclusively.
KEYS = {169: 'answer', 445: 'answer', 446: 'hang_up', 582: 'voice_assistant',
        163:'next', 165:'previous', 164:'play_pause', 207:'play', 119:'pause', 166:'stop'}
INPUT_EVENT = struct.Struct('@llHHi')


def hfp_command(line):
    """Only received parser records, never outgoing AT messages or warnings."""
    if 'Sending AT message' in line or 'Unsupported AT message' in line:
        return None
    if not ('Received AT message:' in line or re.search(r'at\.c:\d+: AT message:', line)):
        return None
    match = re.search(r'AT message: (CMD|SET): command[:=]([^, ]+)(?:,? value[:=](.*))?', line)
    if not match:
        return None
    kind, command, value = match.groups()
    if kind == 'CMD' and command == 'A':
        return ('answer', 'trigger')
    if kind == 'CMD' and command == '+CHUP':
        return ('hang_up', 'trigger')
    if kind == 'SET' and command == '+BVRA' and value in ('0', '1'):
        return ('voice_assistant', 'activate' if value == '1' else 'deactivate')
    return None


class InputMonitor:
    def __init__(self, event, peer, clock=time.monotonic):
        self.event, self.peer, self.clock = event, peer.upper(), clock
        self.pending = queue.Queue(64)
        self.history = deque(maxlen=8)
        self.buttons = {name: dict(held=False, at=0, count=0, action='none') for name in BUTTONS}
        self.status = 'Starting passive input observer'
        self.stop_event = threading.Event()
        self.thread = None
        self.sequence = 0
        self.control_status = {}
        self.control_epochs = {'avrcp': 0, 'hfp': 0, 'hondalink-iap': 0}
        self.control_process = None
        self.traffic_pending = queue.Queue(128)
        self.control_events = deque(maxlen=128)
        self.traffic = {source:dict(count=0,summary='No messages received',at=0)
                        for source in ('avrcp','hfp','hondalink')}
        self.traffic_dropped = 0
        self.steering_mode = None
        self.volume_status = "Experimental / no command sent"
        self.volume_requests = queue.Queue(1)
        self.volume_last = -100

    def observe(self, source, summary, **fields):
        """Bound receiver-to-UI traffic; unknown messages never become button presses."""
        if not isinstance(source,str) or source not in self.traffic:return
        item=dict(source=source,summary=str(summary)[:96],monotonic=self.clock())
        item.update({key:fields[key] for key in ('bytes','recognized') if key in fields})
        try:self.traffic_pending.put_nowait(item)
        except queue.Full:self.traffic_dropped += 1

    def request_volume(self, direction):
        now=self.clock()
        if direction not in ('up','down') or now-self.volume_last<2:return
        process=self.control_process
        if process is None or process.poll() is not None:
            self.volume_status='Radio control worker unavailable'
            return
        self.volume_last=now
        try:
            self.volume_requests.put_nowait((now,direction))
            self.volume_status='Requesting volume '+direction
        except queue.Full:pass

    def receive_control(self,item):
        if not isinstance(item,dict):return
        if item.get('state')=='radio_volume':
            self.volume_status=str(item.get('status',''))[:100]
            self.control_events.append(dict(state='radio_volume',status=self.volume_status))
            return
        if item.get('state') in ('projection_hfp_tx','projection_hfp_state','protocol_packet'):
            self.control_events.append(item)
            return
        if isinstance(item.get('observation'),dict):
            observation=item['observation']
            self.observe(observation.get('source'),observation.get('summary',''),
                         bytes=observation.get('bytes',0),recognized=bool(item.get('recognized')))
        elif isinstance(item.get('button'),str) and item['button'] in BUTTONS:
            self.offer(item['button'],item.get('action','trigger'),item.get('source','bluetooth'))
        elif item.get('transport') in ('avrcp','hfp'):
            transport=item['transport']
            self.control_epochs[transport] += 1
            self.control_status[transport]=str(item.get('status',''))[:100]
            details={key:item[key] for key in ('rx_packets','session_seconds') if key in item}
            self.control_events.append(dict(state='radio_control_transport',transport=transport,
                                            status=self.control_status[transport],**details))

    def start(self):
        if sys.platform != 'linux' or not self.peer or self.peer == '00:00:00:00:00:00':
            self.status = 'Radio input observer unavailable on this system'
            return
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    def receive_iap_remote(self, event):
        state = event.get('state')
        if state == 'iap_remote_buttons':
            self.observe('hondalink', f"iAP buttons 0x{event['mask']:08x}",
                         bytes=event['bytes'], recognized=not bool(event['unsupported_mask']))
        elif state == 'iap_remote_button':
            self.offer(event['button'], event['action'], 'hondalink-iap')
        elif state == 'iap_remote_reset':
            self.control_epochs['hondalink-iap'] += 1

    def offer(self, button, action, source):
        item = dict(button=button, action=action, source=source, monotonic=self.clock())
        transport = 'hfp' if source == 'hfp-command' else source
        if transport in self.control_epochs:
            item['input_epoch'] = self.control_epochs[transport]
        try:
            self.pending.put_nowait(item)
        except queue.Full:
            pass

    def drain(self):
        # The pipe reader must keep accepting call commands even while the
        # launcher is writing diagnostics or handling a voice transition.
        for _ in range(len(self.control_events)):
            self.event(**self.control_events.popleft())
        while True:
            try:item=self.traffic_pending.get_nowait()
            except queue.Empty:break
            state=self.traffic[item['source']]
            state.update(count=state['count']+1,summary=item['summary'],at=item['monotonic'])
            self.event(state='radio_control_rx',**item)
        result = []
        while True:
            try: item = self.pending.get_nowait()
            except queue.Empty: break
            self.sequence += 1
            item['sequence'] = self.sequence
            state = self.buttons[item['button']]
            if item['action'] in ('down', 'up', 'repeat'):
                state['held'] = item['action'] != 'up'
            if item['source']!='screen':
                state.update(at=item['monotonic'],count=state['count']+1,action=item['action'])
            self.history.appendleft(item)
            self.event(state='radio_button', **item)
            result.append(item)
        return result

    def single_radio_rfcomm(self):
        # Old BlueALSA parser logs do not identify their peer. Only accept them
        # when its object tree identifies exactly one RFCOMM transport: our radio.
        try:
            reply = subprocess.run(
                ['busctl', '--json=short', '--timeout=1', 'call', 'org.bluealsa',
                 '/org/bluealsa', 'org.freedesktop.DBus.ObjectManager', 'GetManagedObjects'],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=1.5, check=True)
            objects = json.loads(reply.stdout)['data'][0]
            paths = [p for p, interfaces in objects.items() if 'org.bluealsa.RFCOMM1' in interfaces]
            return len(paths) == 1 and ('dev_'+self.peer.replace(':', '_')) in paths[0]
        except Exception:
            return False

    def run(self):
        journal = None
        control = None
        devices = {}
        buffers = {}
        next_scan = 0
        journal_trusted = False
        try:
            control = subprocess.Popen([sys.executable, '-m', 'hlauncher.controls_worker'],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=None, bufsize=0)
            self.control_process = control
            os.set_blocking(control.stdin.fileno(), False)
            os.set_blocking(control.stdout.fileno(), False)
            buffers[control.stdout.fileno()] = b''
            journal = subprocess.Popen(['journalctl', '-f', '-n', '0', '-o', 'json', '_COMM=bluealsa'],
                                       stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
            os.set_blocking(journal.stdout.fileno(), False)
            buffers[journal.stdout.fileno()] = b''
            while not self.stop_event.is_set():
                now = self.clock()
                if control.poll() is not None and now >= next_scan:
                    oldfd=control.stdout.fileno();control.stdout.close();control.stdin.close();buffers.pop(oldfd,None)
                    self.control_status.clear()
                    control=subprocess.Popen([sys.executable,'-m','hlauncher.controls_worker'],
                        stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=None,bufsize=0)
                    self.control_process=control
                    os.set_blocking(control.stdin.fileno(),False)
                    os.set_blocking(control.stdout.fileno(),False)
                    buffers[control.stdout.fileno()]=b''
                try:
                    requested,direction=self.volume_requests.get_nowait()
                    if now-requested<.5:
                        raw=(json.dumps(dict(volume=direction))+'\n').encode()
                        if os.write(control.stdin.fileno(),raw)!=len(raw):raise OSError('Short command write')
                    else:self.volume_status='Request expired / tap again'
                except queue.Empty:pass
                except OSError:self.volume_status='Radio control worker unavailable'
                if now >= next_scan:
                    next_scan = now + 2
                    journal_trusted = self.single_radio_rfcomm()
                    for path in Path('/sys/class/input').glob('event*'):
                        try:
                            uniq = (path/'device/uniq').read_text().strip().upper()
                            if uniq != self.peer or str(path) in devices.values(): continue
                            fd = os.open('/dev/input/'+path.name, os.O_RDONLY | os.O_NONBLOCK)
                            devices[fd] = str(path)
                            buffers[fd] = b''
                        except OSError: pass
                    self.status = ('Listening to radio keys / HFP commands' if devices or journal_trusted
                                   else 'Waiting for radio input source (HFP debug logs or input device)')
                fds = list(devices)
                if journal.poll() is None: fds.append(journal.stdout.fileno())
                if control.poll() is None: fds.append(control.stdout.fileno())
                ready = select.select(fds, [], [], .1)[0] if fds else []
                if not fds: self.stop_event.wait(.1)
                for fd in ready:
                    try: data = os.read(fd, 8192)
                    except OSError: data = b''
                    if not data:
                        if fd in devices:
                            os.close(fd); devices.pop(fd); buffers.pop(fd, None)
                            for name, state in self.buttons.items():
                                if state['held']: self.offer(name, 'up', 'evdev-disconnect')
                        continue
                    buffers[fd] = (buffers[fd]+data)[-65536:]
                    if fd in devices:
                        while len(buffers[fd]) >= INPUT_EVENT.size:
                            raw, buffers[fd] = buffers[fd][:INPUT_EVENT.size], buffers[fd][INPUT_EVENT.size:]
                            _, _, kind, code, value = INPUT_EVENT.unpack(raw)
                            if kind == 1 and code in KEYS and value in (0, 1, 2):
                                self.offer(KEYS[code], {0:'up',1:'down',2:'repeat'}[value], 'evdev')
                    elif fd == control.stdout.fileno():
                        while b'\n' in buffers[fd]:
                            raw, buffers[fd] = buffers[fd].split(b'\n', 1)
                            try: item = json.loads(raw)
                            except (ValueError, TypeError): continue
                            self.receive_control(item)
                    else:
                        while b'\n' in buffers[fd]:
                            raw, buffers[fd] = buffers[fd].split(b'\n', 1)
                            # The dispatcher owns HFP input; journal fallback must not duplicate it.
                            if not journal_trusted or (control and control.poll() is None): continue
                            try: message = json.loads(raw).get('MESSAGE', '')
                            except (ValueError, TypeError): continue
                            if parsed := hfp_command(message): self.offer(*parsed, 'hfp-command')
        except Exception as exc:
            self.status = 'Input observer unavailable: '+type(exc).__name__
            self.control_events.append(dict(state='radio_input_observer_error', error=str(exc)))
        finally:
            if control:
                control.terminate()
                try: control.wait(timeout=2)
                except subprocess.TimeoutExpired: control.kill(); control.wait(timeout=1)
                control.stdout.close()
                control.stdin.close()
            for fd in devices: os.close(fd)
            if journal:
                journal.terminate()
                try: journal.wait(timeout=1)
                except subprocess.TimeoutExpired: journal.kill(); journal.wait(timeout=1)
                journal.stdout.close()

    def close(self):
        self.stop_event.set()
        if self.thread: self.thread.join(timeout=2)


class ToneTest:
    """Feed short faded tones through the existing mixer, never claim ALSA."""
    def __init__(self, playback):
        self.playback = playback
        self.until = 0
        self.next_block = 0
        self.sample = 0
        self.channel = 'Stereo'
        self.error = ''
        self.frequency = 440
        self.duration = 1

    def start(self, channel, frequency=440, duration=1):
        self.stop()
        self.error = ''
        self.channel = channel
        self.frequency = frequency
        self.duration = duration
        self.until = time.monotonic()+duration
        self.next_block = time.monotonic()
        self.sample = 0

    def tick(self):
        now = time.monotonic()
        if not self.until: return
        if now >= self.until: self.stop(); return
        if now < self.next_block: return
        self.next_block = now+.02
        data = bytearray()
        for _ in range(960):
            t = self.sample/48000
            envelope = min(1, t/.02, max(0, (self.duration-t)/.02))
            value = round(2200*envelope*math.sin(2*math.pi*self.frequency*t))
            data.extend(struct.pack('<hh', value if self.channel != 'Right' else 0,
                                    value if self.channel != 'Left' else 0))
            self.sample += 1
        try:
            self.playback.feed('diagnostics', dict(sample_rate=48000, channels=2, stream=0, pcm=bytes(data)))
        except Exception as exc:
            self.error = 'Audio test unavailable: '+str(exc)[:90]
            self.stop()

    def stop(self):
        self.until = 0
        self.playback.stop('diagnostics')
