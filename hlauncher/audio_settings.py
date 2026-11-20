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
LEGACY_EQ_BANDS = dict(zip(('b31','b50','b80','b125','b200','b315','b500','b1k','b2k','b4k','b8k','b16k'),
                   (31.5,50,80,125,200,315,500,1000,2000,4000,8000,16000)))
LOW_BANDS = {'b20': 20, 'b25': 25}
EQ_BANDS = dict(LOW_BANDS, **LEGACY_EQ_BANDS)
# New UI adjustments use this range. Keep accepting saved ±12 dB values below
# so an update or rollback never silently rewrites an existing curve.
EQ_GAIN_LIMIT = 6
def curve(gains):
    return dict(zip(EQ_BANDS, gains))


PRESETS = {
    'Flat': dict.fromkeys(EQ_BANDS, 0),
    'Bass lift': curve((0,0,1,2,1,0,-1,-1,0,0,0,0,0,0)),
    'Deep bass': curve((0,1,2,2,1,0,-1,-1,0,0,0,0,0,0)),
    'Warm': curve((0,0,0,1,1,1,0,0,0,0,0,-1,-1,-1)),
    'Vocal clarity': curve((0,0,0,0,-1,-1,-1,0,0,1,2,1,0,0)),
    'Acoustic': curve((0,0,0,0,0,-1,-1,0,0,1,1,1,1,0)),
    'Rock': curve((0,0,0,1,2,1,0,-1,0,1,1,1,0,0)),
    'Softer treble': curve((0,0,0,0,0,0,0,0,0,0,0,-1,-2,-2)),
}


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
        self.presets_path = self.path.with_name(self.path.stem+'-presets.json')
        self.user_presets = {}
        self.values = dict(output='hdmi', pipewire=False, eq=True, bass=0, mid=0, treble=0,
                           bands=dict(PRESETS['Flat']), preset='Flat')
        self.refresh()

    def refresh(self):
        before = dict(self.values)
        self.refresh_user_presets()
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
                elif key == 'bands':
                    if self.valid_bands(value):
                        self.values[key] = dict(value)
                    elif self.valid_gains(value, LEGACY_EQ_BANDS):
                        self.values[key] = dict.fromkeys(LOW_BANDS, 0) | dict(value)
                    low=data.get('low_bands')
                    if self.valid_gains(low,LOW_BANDS):
                        self.values[key] = dict(self.values[key], **low)
                elif key=='preset' and isinstance(value,str):
                    self.values[key]=value
        except (OSError, ValueError):
            pass
        return before != self.values

    def save(self, **changes):
        if set(changes) - set(self.values):
            raise ValueError('Unknown audio setting')
        values = dict(self.values, **changes)
        if any(key in changes for key in (*BANDS,'bands')) and 'preset' not in changes:
            values['preset']='Custom'
        if values['output'] != 'hdmi' or any(type(values[k]) is not bool for k in ('pipewire', 'eq')):
            raise ValueError('Invalid audio route')
        if any(type(values[k]) is not int or not -12 <= values[k] <= 12 for k in BANDS):
            raise ValueError('EQ gain must be between -12 and +12 dB')
        if not self.valid_bands(values['bands']):
            raise ValueError('All 14 EQ bands must be integers between -12 and +12 dB')
        if not isinstance(values['preset'],str):raise ValueError('Invalid preset name')
        # Retain the legacy twelve-band shape for older software on rollback.
        saved=dict(values,bands={k:values['bands'][k] for k in LEGACY_EQ_BANDS},
                   low_bands={k:values['bands'][k] for k in LOW_BANDS})
        self.write_json(self.path,saved)
        self.values=values

    @staticmethod
    def write_json(path, data):
        path.parent.mkdir(parents=True,exist_ok=True)
        fd, name = tempfile.mkstemp(prefix='.audio-', dir=path.parent)
        try:
            with os.fdopen(fd, 'w') as f:
                json.dump(data, f, indent=2)
                f.write('\n')
                f.flush()
                os.fsync(f.fileno())
            os.replace(name, path)
            directory=os.open(path.parent,os.O_RDONLY)
            try:os.fsync(directory)
            finally:os.close(directory)
        finally:
            if os.path.exists(name):
                os.unlink(name)

    def device(self):
        # Main media output is fixed to HDMI, including legacy preferences/overrides.
        return 'hlauncher_hdmi'

    @staticmethod
    def valid_gains(value, bands):
        return (isinstance(value, dict) and set(value) == set(bands) and
                all(type(gain) is int and -12 <= gain <= 12 for gain in value.values()))

    @staticmethod
    def valid_bands(value):
        return AudioSettings.valid_gains(value,EQ_BANDS)

    def refresh_user_presets(self):
        try:
            data=json.loads(self.presets_path.read_text())
            presets=data.get('presets',{}) if isinstance(data,dict) and data.get('format')==1 else {}
            if not isinstance(presets,dict):presets={}
        except (OSError,ValueError):presets={}
        self.user_presets={}
        for name in ('User 1','User 2'):
            item=presets.get(name)
            if (isinstance(item,dict) and self.valid_bands(item.get('bands'))
                    and all(type(item.get(k)) is int and -12<=item[k]<=12 for k in BANDS)):
                self.user_presets[name]={k:item[k] for k in BANDS} | {'bands':dict(item['bands'])}

    def save_user_preset(self, name):
        if name not in ('User 1','User 2'):raise ValueError('Choose User 1 or User 2')
        self.refresh_user_presets()
        presets=dict(self.user_presets)
        presets[name]={k:self.values[k] for k in BANDS} | {'bands':dict(self.values['bands'])}
        # Separate storage keeps saved user curves intact when older code saves audio.json.
        self.write_json(self.presets_path,dict(format=1,presets=presets))
        self.user_presets=presets
        self.save(preset=name)

    def preset_changes(self, name):
        if name in PRESETS:
            return dict(bass=0, mid=0, treble=0, bands=dict(PRESETS[name]),preset=name)
        self.refresh_user_presets()
        if name not in self.user_presets:raise ValueError('This user preset is empty')
        saved=self.user_presets[name]
        return {k:saved[k] for k in BANDS} | dict(bands=dict(saved['bands']),preset=name)

    def preset_name(self):
        name=self.values.get('preset')
        if name in self.user_presets and self.user_presets[name]=={k:self.values[k] for k in BANDS} | {'bands':self.values['bands']}:
            return name
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
    parser = argparse.ArgumentParser(description='Explicit maintenance reset of the optional audio route')
    parser.add_argument('--disable-pipewire', action='store_true', required=True)
    parser.parse_args()
    AudioSettings().save(pipewire=False)
