#!/usr/bin/env python3
"""Inspect or select HLauncher's HDMI output and optionally play a quiet tone."""
import argparse
from datetime import datetime
import math
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('route', choices=('status', 'hdmi'))
    parser.add_argument('--test', action='store_true', help='Play a quiet 440 Hz tone for 3 seconds; pause CarPlay music first')
    args = parser.parse_args()
    path = Path('/etc/hlauncher.env')
    if os.geteuid() != 0:
        parser.error('Run with sudo to read/update the service environment.')
    text = path.read_text()
    values = dict(line.split('=', 1) for line in text.splitlines()
                  if '=' in line and not line.lstrip().startswith('#'))
    os.environ['HLAUNCHER_RADIO_ADDRESS'] = values.get('HLAUNCHER_RADIO_ADDRESS', '').strip()
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from hlauncher.audio_settings import AudioSettings
    settings = AudioSettings()
    device = settings.device()
    if args.route != 'status':
        device = 'hlauncher_hdmi'
        backup = path.with_name(path.name + '.before-audio-route-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
        shutil.copy2(path, backup)
        lines = [line for line in text.splitlines() if not line.startswith('HLAUNCHER_AUDIO_DEVICE=')]
        temp = path.with_name(path.name + '.audio-route-tmp')
        with temp.open('x') as output:
            os.fchmod(output.fileno(), path.stat().st_mode & 0o777)
            output.write('\n'.join(lines) + '\nHLAUNCHER_AUDIO_DEVICE=' + device + '\n')
        temp.replace(path)
        settings.save(output=args.route)
        subprocess.run(['systemctl', 'restart', 'hlauncher'], check=True)
        print('Previous environment:', backup)
    print('Configured output:', device)
    print('PipeWire:', settings.values['pipewire'], 'EQ:', settings.values['eq'])
    subprocess.run(['systemctl', 'is-active', 'hlauncher'], check=True)
    if not args.test:
        return
    print('Playing a quiet 3-second tone. Pause other audio and keep HondaLink DA open.')
    os.environ['HLAUNCHER_AUDIO_DEVICE'] = device
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from hlauncher.playback import Playback
    playback = Playback(lambda **event: print(event, flush=True))
    for block in range(150):
        samples = (int(1200 * math.sin(2 * math.pi * 440 * (block * 960 + i) / 48000)) for i in range(960))
        pcm = b''.join(struct.pack('<hh', sample, sample) for sample in samples)
        playback.feed('audio-route-test', dict(sample_rate=48000, channels=2, stream=1, pcm=pcm))
        time.sleep(.02)
    time.sleep(.3)
    playback.stop('audio-route-test')
    if playback.thread:
        playback.thread.join(timeout=3)
    print('PCM bytes written:', playback.written, 'Playback failures:', playback.failures)
    if playback.failures or not playback.written:
        raise SystemExit('Playback failed. Check radio connection and BlueALSA logs.')
    print('Software playback passed. Confirm the sound through the car speakers separately.')


if __name__ == '__main__':
    main()
