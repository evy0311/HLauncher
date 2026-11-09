"""Opt-in Raspberry Pi overlay protection with explicit persistent-state checks."""
import json
from pathlib import Path
import subprocess
from .setup_state import atomic_json
from .config import STATE_DIR

PERSIST = Path('/persist')


def execute(args, **kwargs):
    return subprocess.run(args, check=True, capture_output=True, text=True,
                          timeout=kwargs.pop('timeout', 180), **kwargs)


def mount_for(path, run=execute):
    data = json.loads(run(['findmnt', '--json', '--target', str(path),
                          '--output', 'SOURCE,TARGET,FSTYPE,OPTIONS']).stdout)
    return data['filesystems'][0]


def status(run=execute, persist=PERSIST):
    try:
        root = mount_for('/', run)
        data = mount_for(persist, run)
        # Bind mounts have SOURCE like /dev/mmcblk0p3[/state]; compare backing device.
        source = lambda row: row['source'].split('[')[0]
        persistent = ((persist/'.hlauncher-state-v1').is_file() and data['target']==str(persist)
                      and data['fstype']=='ext4' and 'rw' in data['options'].split(',')
                      and source(root) != source(data))
        for folder in ('/var/lib/hlauncher', '/var/lib/bluetooth', '/etc/NetworkManager/system-connections'):
            persistent = persistent and source(mount_for(folder, run)) == source(data)
        return dict(protected=root['fstype']=='overlay', available=bool(persistent),
                    message='Ready' if persistent else 'Requires the HLauncher persistent-data image layout')
    except (OSError, ValueError, KeyError, subprocess.SubprocessError):
        return dict(protected=False, available=False, message='Storage layout could not be verified')


def configure(enabled, run=execute, state_dir=STATE_DIR, persist=PERSIST):
    info = status(run, persist)
    if not info['available']: raise ValueError(info['message'])
    if info['protected'] == enabled: return 'Already enabled' if enabled else 'Already writable'
    atomic_json(Path(state_dir)/'storage-transition.json', {'target': 'protected' if enabled else 'writable'})
    try:
        run(['/usr/bin/raspi-config', 'nonint', 'do_overlayfs', '0' if enabled else '1'])
        configured = run(['/usr/bin/raspi-config','nonint','get_overlay_conf']).stdout.strip()
        if configured != ('0' if enabled else '1'):
            raise ValueError('Storage protection could not be configured')
        if enabled and run(['/usr/bin/raspi-config','nonint','get_bootro_conf']).stdout.strip() != '0':
            raise ValueError('Boot partition protection could not be configured')
    except BaseException:
        atomic_json(Path(state_dir)/'storage-transition.json', {'target': 'failed'})
        raise
    return 'Restart required to apply storage mode'


def finish_transition():
    path = STATE_DIR/'storage-transition.json'
    try: target = json.loads(path.read_text())['target']
    except (OSError, ValueError, KeyError): return
    info = status()
    if target == 'writable' and info['available'] and not info['protected']:
        # Second pass on the real writable root also clears persistent boot-ro fstab.
        execute(['/usr/bin/raspi-config', 'nonint', 'do_overlayfs', '1'])
        atomic_json(path, {'target': 'complete'})
    elif target == 'protected' and info['protected']:
        atomic_json(path, {'target': 'complete'})


if __name__ == '__main__': finish_transition()
