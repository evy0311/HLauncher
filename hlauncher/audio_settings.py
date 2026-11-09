"""Persistent route/EQ controls and bounded access to HLauncher's private PipeWire graph."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import time

from .config import STATE_DIR

RUNTIME = os.environ.get('HLAUNCHER_PIPEWIRE_RUNTIME_DIR', '/run/hlauncher-pipewire')
BANDS = {'bass': ('Bass', 100), 'mid': ('Mid', 1000), 'treble': ('Treble', 8000)}
EQ_BANDS = dict(zip(('b31','b50','b80','b125','b200','b315','b500','b1k','b2k','b4k','b8k','b16k'),
                   (31.5,50,80,125,200,315,500,1000,2000,4000,8000,16000)))
PRESETS = {'Flat': dict.fromkeys(EQ_BANDS, 0),
           'EDM Bass': dict(zip(EQ_BANDS, (2,3,2,0,-1,-1,0,0,0,0,0,0)))}


class PipeWireService:
    """The isolated audio process owns the optional graph, including while idle."""
    def __init__(self):
        self.enabled = None
        self.lock = threading.Lock()

    def set_enabled(self, enabled):
        with self.lock:
            if self.enabled is enabled:
                return
            subprocess.run(['systemctl', 'start' if enabled else 'stop',
                            'hlauncher-pipewire.service'], check=True,
                           capture_output=True, text=True, timeout=5)
            self.enabled = None
            if enabled:
                deadline = time.monotonic() + 3
                while time.monotonic() < deadline:
                    try:
                        eq_node()
                        break
                    except (OSError, ValueError, StopIteration, subprocess.SubprocessError):
                        time.sleep(.05)
                else:
                    raise RuntimeError('PipeWire graph did not become ready')
            self.enabled = enabled


def pw_run(args, **kwargs):
    env = dict(os.environ, PIPEWIRE_RUNTIME_DIR=RUNTIME, XDG_RUNTIME_DIR=RUNTIME)
    env.pop('ALSA_CONFIG_PATH', None)
    return subprocess.run(args, env=env, check=True, capture_output=True, text=True, timeout=2, **kwargs)


def eq_node():
    nodes = json.loads(pw_run(['pw-dump']).stdout)
    return next(o['id'] for o in nodes if o.get('info', {}).get('props', {}).get('node.name') == 'hlauncher_eq')


class AudioSettings:
    def __init__(self, path=None):
        self.path = Path(path) if path else STATE_DIR / 'audio.json'
        self.values = dict(output='hdmi', pipewire=False, eq=True, bass=0, mid=0, treble=0,
                           bands=dict(PRESETS['Flat']))
        self.refresh()

    def refresh(self):
        before = dict(self.values)
        try:
            data = json.loads(self.path.read_text())
            if not isinstance(data, dict):
                return False
            for key in self.values:
                value = data.get(key)
                if key in ('pipewire', 'eq') and type(value) is bool:
                    self.values[key] = value
                elif key in BANDS and type(value) is int and -12 <= value <= 12:
                    self.values[key] = value
                elif key == 'bands' and self.valid_bands(value):
                    self.values[key] = dict(value)
        except (OSError, ValueError):
            pass
        return before != self.values

    def save(self, **changes):
        if set(changes) - set(self.values):
            raise ValueError('Unknown audio setting')
        values = dict(self.values, **changes)
        if values['output'] != 'hdmi' or any(type(values[k]) is not bool for k in ('pipewire', 'eq')):
            raise ValueError('Invalid audio route')
        if any(type(values[k]) is not int or not -12 <= values[k] <= 12 for k in BANDS):
            raise ValueError('EQ gain must be between -12 and +12 dB')
        if not self.valid_bands(values['bands']):
            raise ValueError('All 12 EQ bands must be integers between -12 and +12 dB')
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(prefix='.audio-', dir=self.path.parent)
        try:
            with os.fdopen(fd, 'w') as f:
                json.dump(values, f, indent=2)
                f.write('\n')
                f.flush()
                os.fsync(f.fileno())
            os.replace(name, self.path)
            self.values = values
        finally:
            if os.path.exists(name):
                os.unlink(name)

    def device(self):
        # Main media output is fixed to HDMI, including legacy preferences/overrides.
        return 'hlauncher_hdmi'

    @staticmethod
    def valid_bands(value):
        return (isinstance(value, dict) and set(value) == set(EQ_BANDS) and
                all(type(gain) is int and -12 <= gain <= 12 for gain in value.values()))

    def preset_changes(self, name):
        return dict(bass=0, mid=0, treble=0, bands=dict(PRESETS[name]))

    def preset_name(self):
        if not any(self.values[key] for key in BANDS):
            for name, bands in PRESETS.items():
                if self.values['bands'] == bands:
                    return name
        return 'Custom'

    def controls(self):
        gains = {k: self.values[k] if self.values['eq'] else 0 for k in BANDS}
        # Independent band gains: no preamp compensation, normalization or limiter.
        params = []
        for key, gain in gains.items():
            params += [key + ':Gain', gain]
        for key, gain in self.values['bands'].items():
            params += [key + ':Gain', gain if self.values['eq'] else 0]
        return dict(params=params)

    def apply_eq(self):
        pw_run(['pw-cli', 'set-param', str(eq_node()), 'Props', json.dumps(self.controls())])

    def status(self):
        try:
            eq_node()
            return 'PipeWire ready'
        except (OSError, ValueError, StopIteration, subprocess.SubprocessError):
            return 'PipeWire unavailable'


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Reset the optional audio route at service startup')
    parser.add_argument('--disable-pipewire', action='store_true', required=True)
    parser.parse_args()
    AudioSettings().save(pipewire=False)
