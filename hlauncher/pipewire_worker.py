"""Bridge mixed PCM through the private PipeWire EQ, then the existing ALSA route.

No session manager or Bluetooth monitor: BlueALSA retains the HondaLink profiles.
"""
import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

from .audio_settings import AudioSettings, RUNTIME, pw_run


def configure_ports(sink="hlauncher_record"):
    names = {'hlauncher_input': 'Output', 'hlauncher_eq': 'Input',
             'hlauncher_eq_output': 'Output', sink: 'Input'}
    for attempt in range(30):
        objects = json.loads(pw_run(['pw-dump']).stdout)
        found = {o.get('info', {}).get('props', {}).get('node.name'): o['id']
                 for o in objects if o['type'] == 'PipeWire:Interface:Node'}
        if all(name in found for name in names):
            break
        time.sleep(.03)
    else:
        raise RuntimeError('PipeWire stream ports did not appear')
    for name, direction in names.items():
        # The persistent EQ ports remain configured between output sessions.
        # Reconfiguring a running adapter can fail and interrupt its graph.
        existing={o.get('info',{}).get('props',{}).get('port.name','').rsplit('_',1)[-1]
            for o in objects if o['type']=='PipeWire:Interface:Port'
            and o.get('info',{}).get('props',{}).get('node.id')==found[name]
            and o.get('info',{}).get('direction','').lower()==direction.lower()}
        if {'FL','FR'} <= existing:continue
        config = dict(direction=direction, mode='dsp', format=dict(mediaType='audio',
                      mediaSubtype='raw', format='F32P', rate=48000, channels=2, position=['FL', 'FR']))
        pw_run(['pw-cli', 'set-param', str(found[name]), 'PortConfig', json.dumps(config)])
    for channel in ('FL', 'FR'):
        pw_run(['pw-link', f'hlauncher_input:output_{channel}', f'hlauncher_eq:playback_{channel}'])
        port=('input_' if sink=='hlauncher_record' else 'playback_')+channel
        pw_run(['pw-link', f'hlauncher_eq_output:capture_{channel}', f'{sink}:{port}'])


def hdmi_card_index():
    for path in Path('/proc/asound').glob('card[0-9]*/id'):
        if path.read_text().strip() == 'vc4hdmi0':
            return int(path.parent.name[4:])
    raise RuntimeError('HDMI audio card vc4hdmi0 is unavailable')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--device', required=True)
    parser.add_argument('--capture-file', help='Diagnostic PCM capture instead of ALSA playback')
    parser.add_argument('--compare-pw-cat', action='store_true', help='Capture-only comparison with the former stdin client')
    args = parser.parse_args()
    if args.compare_pw_cat and not args.capture_file:
        parser.error('--compare-pw-cat requires --capture-file')
    env = dict(os.environ, PIPEWIRE_RUNTIME_DIR=RUNTIME, XDG_RUNTIME_DIR=RUNTIME)
    env.pop('ALSA_CONFIG_PATH', None)
    children = []
    ready_read = ready_write = None
    def stop(*_):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        settings = AudioSettings()
        settings.apply_eq()
        source_binary = Path(__file__).resolve().parents[1] / 'build/hlauncher-pw-input'
        if not source_binary.is_file():
            raise RuntimeError('Buffered PipeWire input is not built; run scripts/build_pipewire_pcm.sh')
        if not args.capture_file:
            # The ALSA node is created by a persistent pw-cli client and destroyed
            # with that client. HDMI therefore clocks the EQ graph directly and
            # the device is released immediately when PipeWire is bypassed.
            props = {
                'factory.name': 'api.alsa.pcm.sink',
                'node.name': 'hlauncher_hdmi_sink', 'media.class': 'Audio/Sink',
                'api.alsa.path': args.device, 'api.alsa.pcm.card': hdmi_card_index() if args.device=='hlauncher_hdmi' else 0,
                'audio.format': 'S32LE',
                'audio.rate': 48000, 'audio.channels': 2, 'audio.position': ['FL','FR'],
                'api.alsa.period-size': 960, 'api.alsa.period-num': 4,
                'node.driver': True, 'priority.driver': 30000,
                'node.pause-on-idle': True, 'node.suspend-on-idle': True,
            }
            sink = subprocess.Popen(['pw-cli', '-m', 'create-node', 'adapter', json.dumps(props)],
                                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, env=env)
            children.append(sink)
        common = ['pw-cat', '--target=0', '--rate=48000', '--channels=2', '--format=f32',
                  '--latency=80ms', '--quality=14']
        if args.capture_file:
            record = subprocess.Popen([str(source_binary), '--capture-file', args.capture_file], env=env)
            children.append(record)
        if not args.compare_pw_cat:
            ready_read, ready_write = os.pipe()
        source_command = (common + ['--playback', '--properties={ node.name=hlauncher_input }', '-']
                          if args.compare_pw_cat else [str(source_binary), '--ready-fd', str(ready_read)])
        source = subprocess.Popen(source_command,
                                  stdin=sys.stdin.buffer, env=env,
                                  pass_fds=() if ready_read is None else (ready_read,))
        if ready_read is not None:
            os.close(ready_read)
            ready_read = None
        children.append(source)
        configure_ports('hlauncher_record' if args.capture_file else 'hlauncher_hdmi_sink')
        if ready_write is not None:
            os.write(ready_write, b'1')
            os.close(ready_write)
            ready_write = None
        while source.poll() is None:
            for child in children[:-1]:
                if child.poll() is not None:
                    raise RuntimeError(f'Audio subprocess exited: {child.returncode}')
            if settings.refresh():
                settings.apply_eq()
            time.sleep(.1)
        if source.returncode:
            raise RuntimeError(f'PipeWire input exited: {source.returncode}')
        time.sleep(.2)
    except KeyboardInterrupt:
        pass
    finally:
        for fd in (ready_read, ready_write):
            if fd is not None:
                os.close(fd)
        for child in reversed(children):
            if child.poll() is None:
                child.terminate()
        for child in reversed(children):
            try:
                child.wait(timeout=.5)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait(timeout=.5)


if __name__ == '__main__':
    main()
