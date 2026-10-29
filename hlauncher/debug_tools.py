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

BUTTONS = ('answer', 'hang_up', 'voice_assistant')
# Linux input-event-codes.h; never grab the radio's input device exclusively.
KEYS = {169: 'answer', 445: 'answer', 446: 'hang_up', 582: 'voice_assistant'}
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
    if kind == 'CMD' and command in ('A', 'D', '+BLDN'):
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

    def start(self):
        if sys.platform != 'linux' or not self.peer or self.peer == '00:00:00:00:00:00':
            self.status = 'Radio input observer unavailable on this system'
            return
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    def offer(self, button, action, source):
        try:
            self.pending.put_nowait(dict(button=button, action=action, source=source, monotonic=self.clock()))
        except queue.Full:
            pass

    def drain(self):
        result = []
        while True:
            try: item = self.pending.get_nowait()
            except queue.Empty: break
            self.sequence += 1
            item['sequence'] = self.sequence
            state = self.buttons[item['button']]
            if item['action'] in ('down', 'up', 'repeat'):
                state['held'] = item['action'] != 'up'
            state.update(at=item['monotonic'], count=state['count']+1, action=item['action'])
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
        devices = {}
        buffers = {}
        next_scan = 0
        journal_trusted = False
        try:
            journal = subprocess.Popen(['journalctl', '-f', '-n', '0', '-o', 'json', '_COMM=bluealsa'],
                                       stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
            os.set_blocking(journal.stdout.fileno(), False)
            buffers[journal.stdout.fileno()] = b''
            while not self.stop_event.is_set():
                now = self.clock()
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
                    else:
                        while b'\n' in buffers[fd]:
                            raw, buffers[fd] = buffers[fd].split(b'\n', 1)
                            if not journal_trusted: continue
                            try: message = json.loads(raw).get('MESSAGE', '')
                            except (ValueError, TypeError): continue
                            if parsed := hfp_command(message): self.offer(*parsed, 'hfp-command')
        except Exception as exc:
            self.status = 'Input observer unavailable: '+type(exc).__name__
            self.event(state='radio_input_observer_error', error=str(exc))
        finally:
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

    def start(self, channel):
        self.stop()
        self.error = ''
        self.channel = channel
        self.until = time.monotonic()+1
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
            envelope = min(1, t/.02, max(0, (1-t)/.02))
            value = round(2200*envelope*math.sin(2*math.pi*440*t))
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
