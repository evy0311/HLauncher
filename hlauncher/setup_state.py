"""Durable setup identity and pairing admission policy, independent of the UI."""
import fcntl
import json
import os
from pathlib import Path
import re
import secrets
import tempfile
import time
from .config import STATE_DIR

ADDRESS = re.compile(r'(?:[0-9A-F]{2}:){5}[0-9A-F]{2}')
EMPTY = '00:00:00:00:00:00'
try: BOOT_ID = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
except OSError: BOOT_ID = 'local-test'


def address(value):
    value = str(value).upper()
    if not ADDRESS.fullmatch(value) or value == EMPTY:
        raise ValueError('Invalid Bluetooth address')
    return value


def atomic_json(path, value, *, durable=True):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.'+path.name, dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as f:
            json.dump(value, f, indent=2)
            f.write('\n')
            if durable:
                f.flush()
                os.fsync(f.fileno())
        os.replace(name, path)
        if durable:
            fd = os.open(path.parent, os.O_RDONLY)
            try: os.fsync(fd)
            finally: os.close(fd)
    finally:
        if os.path.exists(name): os.unlink(name)


class SetupState:
    def __init__(self, folder=None, clock=time.monotonic):
        self.folder = Path(folder) if folder else STATE_DIR
        self.clock = clock
        self.path = self.folder/'radio.json'
        self.data = self.load()
        self.deadline = clock()+300 if not self.peer else 0
        self.candidate = None
        self.candidate_deadline = 0

    def load(self):
        try:
            data = json.loads(self.path.read_text())
            if not isinstance(data, dict): return {}
            address(data['address'])
            if data.get('verified') is not True: return {}
            return data
        except (OSError, ValueError, KeyError): return {}

    @property
    def peer(self):
        # Read changes made by the pairing/recovery process on every admission.
        self.data = self.load()
        return self.data.get('address')

    def open_pairing(self):
        self.deadline = self.clock()+300
        self.candidate = None
        (self.folder/'pairing-candidate.json').unlink(missing_ok=True)
        atomic_json(self.folder/'pairing-request.json', {'at': time.time()})

    def pairing_open(self):
        return not self.peer and self.clock() < self.deadline

    @staticmethod
    def looks_like_radio(properties):
        name = str(properties.get('Alias', properties.get('Name', ''))).lower().replace(' ', '')
        uuids = {str(x).lower() for x in properties.get('UUIDs', [])}
        return ('handsfreelink' in name or 'hondalink' in name or
                {'0000110b-0000-1000-8000-00805f9b34fb',
                 '0000111e-0000-1000-8000-00805f9b34fb'} <= uuids)

    def admit(self, peer, properties=None, manual=False):
        peer = address(peer)
        saved = self.peer
        if saved: return saved == peer
        now = self.clock()
        if self.candidate and now >= self.candidate_deadline:
            self.candidate = None
        if not self.pairing_open(): return False
        if self.candidate and self.candidate != peer: return False
        if not manual and not self.looks_like_radio(properties or {}): return False
        if self.candidate != peer:
            self.candidate = peer
            self.candidate_deadline = min(self.deadline, now+90)
        atomic_json(self.folder/'pairing-candidate.json', {'address': peer,
            'expires': time.time()+max(0,self.candidate_deadline-now), 'boot_id': BOOT_ID})
        return True

    def allowed(self, peer):
        peer = address(peer)
        if self.peer: return self.peer == peer
        try:
            item = json.loads((self.folder/'pairing-candidate.json').read_text())
            return (item.get('boot_id') == BOOT_ID and item['address'] == peer
                    and time.time() < item['expires'])
        except (OSError, ValueError, KeyError, TypeError): return False

    def verify(self, peer):
        peer = address(peer)
        if self.peer == peer: return
        if not self.allowed(peer): raise ValueError('Radio was not admitted for pairing')
        atomic_json(self.path, {'address': peer, 'verified': True})
        self.data = self.load()
        (self.folder/'pairing-candidate.json').unlink(missing_ok=True)
        self.deadline = 0

    def forget(self):
        atomic_json(self.path, {'forgotten': True})
        (self.folder/'pairing-candidate.json').unlink(missing_ok=True)
        self.data = {}
        self.open_pairing()

    def credentials(self):
        path = self.folder/'recovery.json'
        self.folder.mkdir(parents=True, exist_ok=True)
        with (self.folder/'.recovery.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                item = json.loads(path.read_text())
            except (OSError, ValueError):
                item = {}
            if not isinstance(item, dict):
                item = {}
            ssid = item.get('ssid')
            if not isinstance(ssid, str) or not re.fullmatch(r'HLauncher-[0-9A-F]{4}', ssid):
                ssid = 'HLauncher-'+secrets.token_hex(2).upper()
            password = item.get('password')
            if isinstance(password, str) and re.fullmatch(r'[A-Za-z0-9_-]{16}', password) and ssid == item.get('ssid'):
                return {'ssid': ssid, 'password': password}
            item = {'ssid': ssid, 'password': secrets.token_urlsafe(12)}
            atomic_json(path, item)
            return item
