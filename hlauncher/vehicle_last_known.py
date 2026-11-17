"""Bounded, per-radio last-known readings kept in persistent launcher state."""

from datetime import datetime
import json
from math import isfinite
from pathlib import Path
import time

from .setup_state import BOOT_ID, atomic_json
from .vehicle_fields import FIELD_GROUP


SYNC_MARKER = Path('/run/systemd/timesync/synchronized')
SAVE_INTERVAL = 30
RECORD_LIMIT = 512
MODULE_LIMIT = 32
STORED_RECORDS_PER_KIND = 3072


class VehicleLastKnown:
    def __init__(self, path=None):
        self.path = Path(path) if path else None
        self.device = ''
        self.readings = {}
        self.reports = {}
        self.at = self.wall = None
        self.revision = self.report_revision = self.written = 0
        self.next_write = 0
        self.flush_requested = False
        if self.path:
            self.load()

    def load(self):
        try:
            with self.path.open('rb') as source:
                raw = source.read(8_000_001)
            if len(raw) > 8_000_000:
                return
            state = json.loads(raw)
            if state.get('version') != 1:
                return
            readings = {
                key: value for key, value in state['readings'].items()
                if key in FIELD_GROUP and (
                    type(value) in (int, bool) or isinstance(value, float) and isfinite(value)
                    or isinstance(value, str) and len(value) <= 510
                )
            }
            reports = {}
            for key, modules in state['reports'].items():
                kind = int(key)
                if kind not in (1, 2, 3):
                    continue
                reports[kind] = {}
                for module, records, total in modules[-MODULE_LIMIT:]:
                    rows = [(mid, bytes.fromhex(data).hex()) for mid, data in records[:RECORD_LIMIT]]
                    if any(type(mid) is not int or not 0 <= mid <= 0xffffffff or len(data) > 510
                           for mid, data in rows):
                        raise ValueError('Invalid diagnostic record')
                    if type(total) is not int or total < len(rows):
                        raise ValueError('Invalid diagnostic record count')
                    reports[kind][module] = (rows, total)
            wall = state.get('wall')
            at = state.get('monotonic') if state.get('boot_id') == BOOT_ID else None
            self.wall = wall if type(wall) in (int, float) and 0 < wall < 4102444800 else None
            self.at = at if type(at) in (int, float) and 0 <= at <= time.monotonic() else None
            device = state.get('device')
            self.device = device if isinstance(device, str) else ''
            self.readings, self.reports = readings, reports
        except (OSError, ValueError, TypeError, KeyError, AttributeError, RecursionError):
            return

    def select_device(self, device):
        if not device or device == self.device:
            return
        if self.device:
            self.readings.clear()
            self.reports.clear()
            self.at = self.wall = None
            self.report_revision += 1
            self.revision += 1
            self.flush_requested = True
        self.device = device

    def touch(self, at):
        if self.at is None and self.wall is None:
            self.flush_requested = True
        self.at = at
        self.wall = time.time() if SYNC_MARKER.is_file() else None
        self.revision += 1

    def update(self, readings, at):
        if readings:
            self.readings.update(readings)
            self.touch(at)

    def update_report(self, kind, records, at):
        # When present, the legacy count record precedes the first module's records.
        module = next((row['can_id'] for row in records if row['can_id'] not in (0x99f00001, 0x99f00002)), None)
        reports = self.reports.setdefault(kind, {})
        compact = [(row['can_id'], row['data']) for row in records[:RECORD_LIMIT]]
        report = (compact, len(records))
        if reports.get(module) != report:
            reports.pop(module, None)
            reports[module] = report
            while (len(reports) > MODULE_LIMIT or
                   sum(len(batch) for batch, _ in reports.values()) > STORED_RECORDS_PER_KIND):
                reports.pop(next(iter(reports)))
            self.report_revision += 1
        self.touch(at)

    def report_view(self):
        result = {}
        for kind, reports in self.reports.items():
            records = []
            total = 0
            for batch, count in reversed(reports.values()):
                records.extend(batch[:RECORD_LIMIT-len(records)])
                total += count
            result[kind] = (records, total)
        return result

    def resolved_wall(self, now):
        if self.wall is not None:
            return self.wall
        if self.at is not None and SYNC_MARKER.is_file():
            return time.time() - max(0, now-self.at)
        return None

    def updated_text(self, now):
        wall = self.resolved_wall(now)
        if wall is not None:
            return datetime.fromtimestamp(wall).astimezone().strftime('%b %-d, %Y · %-I:%M %p %Z')
        if self.at is not None:
            minutes = max(0, int(now-self.at)) // 60
            if minutes < 1:
                return 'Just now'
            return f'{minutes} min ago' if minutes < 60 else f'{minutes//60} hr ago'
        return 'Date unavailable' if self.readings or self.reports else 'No readings yet'

    def pending_write(self, now, *, force=False):
        if not self.path:
            return None
        if self.wall is None and (wall := self.resolved_wall(now)) is not None:
            self.wall = wall
            self.revision += 1
        if self.revision == self.written or not (force or self.flush_requested or now >= self.next_write):
            return None
        self.next_write = now + SAVE_INTERVAL
        self.flush_requested = False
        return self.revision, dict(
            version=1, device=self.device, boot_id=BOOT_ID, monotonic=self.at, wall=self.wall,
            readings=dict(self.readings),
            reports={kind: [(module, records, total) for module, (records, total) in modules.items()]
                     for kind, modules in self.reports.items()},
        )

    def write(self, state):
        atomic_json(self.path, state)
