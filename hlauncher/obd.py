"""Nonblocking launcher control of the isolated BLE OBD worker."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from .config import ROOT, STATE_DIR, LOG_DIR, RADIO_ADDRESS


def read_json(path, default=None):
    try:
        value = json.loads(Path(path).read_text())
        return value if isinstance(value, dict) else (default or {})
    except (OSError, ValueError):
        return default or {}


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(value, allow_nan=False))
    os.replace(tmp, path)


class ObdManager:
    def __init__(self, event):
        self.event = event
        self.folder = STATE_DIR / 'obd'
        self.proc = self.log = None
        self.enabled = False
        self.last_heartbeat = self.last_read = self.retry_at = 0
        self.state = {'state':'disconnected', 'message':'No OBD dongle connected', 'devices':[]}
        self.revision = 0

    def start(self):
        self.enabled = True

    def command(self, action, **fields):
        self.start()
        try:
            atomic_json(self.folder/'command.json', dict(id=time.time_ns(), time=time.time(), action=action, **fields))
        except OSError as exc:
            self.event(state='obd_command_failed', error=str(exc))

    def tick(self, session):
        if not self.enabled:
            return
        now = time.monotonic()
        ready = bool(session.get('connected') and session.get('authenticated'))
        if now-self.last_heartbeat >= 1 or ready != getattr(self,'last_ready',None):
            self.last_heartbeat, self.last_ready = now, ready
            try:
                atomic_json(self.folder/'radio.json', dict(ready=ready, monotonic=now, radio_address=RADIO_ADDRESS))
            except OSError as exc:
                self.event(state='obd_priority_write_failed', error=str(exc))
        if (self.proc is None or self.proc.poll() is not None) and now >= self.retry_at:
            self.retry_at = now+30
            try:
                LOG_DIR.mkdir(parents=True, exist_ok=True)
                if self.log:self.log.close()
                # Worker logging rotates internally; keep startup failures small.
                self.log = (LOG_DIR/'obd-worker-startup.log').open('wb')
                self.proc = subprocess.Popen([sys.executable,'-m','hlauncher.obd_service'],
                    cwd=ROOT, stdin=subprocess.DEVNULL, stdout=self.log, stderr=self.log)
            except OSError as exc:
                self.event(state='obd_worker_start_failed', error=str(exc))
        if now-self.last_read >= .5:
            self.last_read = now
            state = read_json(self.folder/'status.json')
            if not state or now-state.get('monotonic',0) > 5:
                state = dict(state='disconnected', message='OBD service unavailable', devices=[])
            visible = lambda item: {key:value for key,value in item.items() if key not in ('monotonic','readings')}
            if visible(state) != visible(self.state):self.revision += 1
            self.state = state

    def close(self):
        # No Bluetooth teardown in the UI thread. Expiring the heartbeat also
        # makes a surviving child release only its own BLE device.
        try:
            if self.enabled:atomic_json(self.folder/'radio.json',dict(ready=False,monotonic=0))
        except OSError:
            pass
        if self.proc and self.proc.poll() is None:self.proc.terminate()
        if self.log:self.log.close()
