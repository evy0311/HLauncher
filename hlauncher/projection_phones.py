"""Local, bounded phone history. Paired devices do not imply a live session."""
import json
import hashlib
import math
from pathlib import Path
import re
import time
from .adapter_info import text
from .setup_state import atomic_json


class ProjectionPhones:
    def __init__(self, path):
        self.path = Path(path)
        self.favorite_path = self.path.with_name('projection-favorite.json')
        try:
            favorite = json.loads(self.favorite_path.read_text())
        except (OSError, ValueError):
            favorite = {}
        self.favorite = favorite.get('id') if isinstance(favorite, dict) else None
        self.favorite_address = favorite.get('address', '') if isinstance(favorite, dict) else ''
        if not self.valid_address(self.favorite, self.favorite_address):
            self.favorite, self.favorite_address = None, ''
        self.addresses = {}
        try:
            records = json.loads(self.path.read_text())
        except (OSError, ValueError):
            records = []
        self.records = {}
        self.live = set()
        self.observed = set()
        self.dirty = False
        self.update(records if isinstance(records, list) else [], save=False)

    def update(self, reports, *, save=True):
        if not isinstance(reports, list):
            return
        before = json.dumps(self.records, sort_keys=True)
        live = set()
        for report in reports[:32]:
            if not isinstance(report, dict):
                continue
            key = report.get('id')
            if not isinstance(key, str) or not re.fullmatch('[a-f0-9]{24}', key):
                continue
            previous = self.records.get(key, {})
            current = dict(id=key, name=text(report.get('name')) or 'Phone',
                           protocol=text(report.get('protocol')) or previous.get('protocol', ''),
                           transport=text(report.get('transport')) or previous.get('transport', ''))
            last = previous.get('last_connected') if save else report.get('last_connected')
            if type(last) in (float, int) and math.isfinite(last) and last > 0:
                current['last_connected'] = last
            if save and report.get('connected') is True:
                live.add(key)
                if key not in self.live:
                    current['last_connected'] = int(time.time())
            self.records[key] = current
            if save and self.valid_address(key, report.get('address')):
                self.addresses[key] = report['address'].upper()
        if save:
            self.live = live
            self.observed = {r.get('id') for r in reports if isinstance(r, dict) and r.get('paired') is True and isinstance(r.get('id'), str)}
        self.records = dict(sorted(self.records.items(), key=lambda item: (item[0] == self.favorite, item[1].get('last_connected', 0)), reverse=True)[:32])
        self.addresses = {key: value for key, value in self.addresses.items() if key in self.observed or key in self.live}
        self.dirty = self.dirty or (save and before != json.dumps(self.records, sort_keys=True))
        if save and self.dirty:
            atomic_json(self.path, list(self.records.values()))
            self.dirty = False

    def snapshot(self):
        return [dict(record, connected=key in self.live, paired=key in self.observed, favorite=key == self.favorite)
                for key, record in self.records.items()]

    @staticmethod
    def valid_address(key, address):
        return (isinstance(address, str) and address.upper() != '00:00:00:00:00:00'
                and re.fullmatch(r'(?:[0-9A-F]{2}:){5}[0-9A-F]{2}', address.upper()) is not None
                and hashlib.sha256(address.upper().encode()).hexdigest()[:24] == key)

    def set_favorite(self, key):
        address = self.addresses.get(key, '')
        if key is not None and (key not in self.records or not self.valid_address(key, address)):
            raise ValueError('Connect the dongle and wait for its paired phone list first')
        atomic_json(self.favorite_path, dict(id=key, address=address))
        self.favorite, self.favorite_address = key, address
