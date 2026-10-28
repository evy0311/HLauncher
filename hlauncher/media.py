"""Plugin-neutral now-playing state. This module never talks to the radio."""

import argparse
import json
import math
import os
from pathlib import Path
import tempfile
import time

RUNTIME = Path(os.environ.get('HLAUNCHER_RUNTIME_DIR', '/run/hlauncher'))
TEXT = ('title', 'artist', 'album', 'app')
TIMES = ('position_ms', 'duration_ms')
STATES = ('unknown', 'playing', 'paused', 'stopped')


def validate(fields):
    if not isinstance(fields, dict):
        raise ValueError('media fields must be an object')
    if set(fields) - set(TEXT + TIMES + ('playback_state',)):
        raise ValueError('unknown media field')
    result = {}
    for key, value in fields.items():
        if value is None:
            result[key] = None
        elif key in TEXT:
            if not isinstance(value, str) or len(value) > 512:
                raise ValueError('invalid media text')
            result[key] = ''.join(c for c in value if c.isprintable())
        elif key in TIMES:
            if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 604800000:
                raise ValueError('invalid media time in milliseconds')
            result[key] = round(value)
        elif key == 'playback_state':
            if value not in STATES:
                raise ValueError('invalid playback state')
            result[key] = value
    return result


class NowPlaying:
    def __init__(self, event=lambda **kw: None, path=None):
        self.event = event
        self.path = Path(path) if path else RUNTIME / 'now-playing.json'
        self.sources = {}
        self.selected = None
        self.revision = 0
        self.dirty = True
        self.last_write = 0
        self.last_error = 0

    def publish(self, plugin, fields, clear=False):
        fields = validate(fields)
        old = self.sources.get(plugin, {})
        new_track = ('title' in fields and fields['title'] != old.get('title'))
        if clear or new_track:
            current = {key: None for key in TEXT + TIMES}
            current['playback_state'] = 'unknown'
            current['field_updated_unix'] = {}
        else:
            current = dict(old)
            current['field_updated_unix'] = dict(old.get('field_updated_unix', {}))
        now = time.time()
        current.update(fields)
        for key in fields:
            current['field_updated_unix'][key] = now
        current.update(plugin=plugin, updated_unix=now, updated_monotonic=time.monotonic())
        if clear:
            current['available'] = bool(fields)
        else:
            current['available'] = bool(fields) or old.get('available', False)
        self.sources[plugin] = current
        self.selected = plugin
        self.revision += 1
        self.dirty = True

    def clear(self, plugin):
        if plugin in self.sources:
            self.publish(plugin, {}, clear=True)

    def snapshot(self):
        return dict(schema=1, revision=self.revision, launcher_pid=os.getpid(),
                    selected_plugin=self.selected, now_playing=self.sources.get(self.selected),
                    sources=self.sources, radio_forwarding=False)

    def flush(self, force=False):
        if not self.dirty or (not force and time.monotonic()-self.last_write < .2):
            return
        tmp = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(mode='w', dir=self.path.parent, delete=False) as f:
                tmp = f.name
                json.dump(self.snapshot(), f, ensure_ascii=False, allow_nan=False)
                f.write('\n')
                os.fchmod(f.fileno(), 0o644)
            os.replace(tmp, self.path)
            self.dirty = False
        except OSError as exc:
            if time.monotonic()-self.last_error > 10:
                self.event(state='now_playing_export_failed', error=str(exc))
                self.last_error = time.monotonic()
        finally:
            self.last_write = time.monotonic()
            if tmp:
                try: os.unlink(tmp)
                except OSError: pass


def clock(ms):
    if ms is None:
        return '--:--'
    seconds = int(ms)//1000
    return f'{seconds//60}:{seconds%60:02d}'


def main(argv=None):
    parser = argparse.ArgumentParser(description='Watch plugin now-playing reports; nothing is sent to the radio')
    parser.add_argument('--watch', action='store_true')
    parser.add_argument('--json', action='store_true')
    parser.add_argument('--path', type=Path, default=RUNTIME/'now-playing.json')
    args = parser.parse_args(argv)
    try:
        while True:
            try:
                state = json.loads(args.path.read_text())
                p = state.get('now_playing') or {}
                age = max(0, time.time()-p['updated_unix']) if 'updated_unix' in p else None
                position_age = max(0, time.time()-p.get('field_updated_unix', {}).get('position_ms', time.time())) if p.get('position_ms') is not None else None
                if args.json:
                    output = json.dumps(dict(state, update_age_seconds=age, position_age_seconds=position_age), ensure_ascii=False)
                elif not p.get('available'):
                    output = 'Waiting for now-playing metadata from a plugin.'
                else:
                    output = '\n'.join([
                        f"Plugin: {p.get('plugin')}    App: {p.get('app') or 'unknown'}",
                        f"Track:  {p.get('title') or '(not reported)'}",
                        f"Artist: {p.get('artist') or '(not reported)'}",
                        f"Album:  {p.get('album') or '(not reported)'}",
                        f"Position: {clock(p.get('position_ms'))} / {clock(p.get('duration_ms'))}    State: {p.get('playback_state', 'unknown')}",
                        f"Last report: {age:.1f}s ago" + (f"    Position report: {position_age:.1f}s ago" if position_age is not None else ''),
                        'Position is reported, not extrapolated. Radio forwarding is off.',
                    ])
            except (OSError, ValueError, KeyError, TypeError):
                output = 'Waiting for HLauncher now-playing service.'
            if args.watch and not args.json and os.isatty(1):
                print('\033[2J\033[H' + output, flush=True)
            else:
                print(output, flush=True)
            if not args.watch:
                break
            time.sleep(.5)
    except KeyboardInterrupt:
        pass
