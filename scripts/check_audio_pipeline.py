#!/usr/bin/env python3
"""Check resampling, float playback and PCM continuity without an HDMI receiver.
Run with HLauncher playback idle: this uses the private EQ graph, with ALSA null output.
"""
import json
import os
from pathlib import Path
import sys
import tempfile
import time

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from hlauncher.audio_settings import AudioSettings
from hlauncher.playback import Playback


def main():
    restore = AudioSettings()
    with tempfile.TemporaryDirectory() as folder:
        os.environ['HLAUNCHER_STATE_DIR']=folder
        settings=AudioSettings(Path(folder)/'audio.json')
        settings.save(output='hdmi',pipewire=True,eq=True,bass=6,mid=0,treble=0)
        settings.device=lambda:'null'
        output=Playback(lambda **event:print(event,flush=True))
        output.settings=settings
        stream=None
        try:
            for block in range(150):
                signal=(np.sin(2*np.pi*1000*(np.arange(882)+block*882)/44100)*1000).astype('<i2')
                pcm=np.repeat(signal[:,None],2,axis=1).tobytes()
                output.feed('quality-test',dict(sample_rate=44100,channels=2,stream=1,pcm=pcm))
                time.sleep(.02)
            time.sleep(.4)
            stream=output.streams[('quality-test',1)]
        finally:
            output.stop('quality-test')
            if output.thread:output.thread.join(timeout=4)
            restore.apply_eq()
        result=dict(bytes_written=output.written,failures=output.failures,
                    dropped_bytes=stream.dropped if stream else None,
                    worker_alive=bool(output.thread and output.thread.is_alive()))
        print(json.dumps(result,indent=2))
        assert result['bytes_written']>1000000 and result['failures']==0
        assert result['dropped_bytes']==0 and not result['worker_alive']
        print('PASS: sinc resampling → float mixer → PipeWire EQ → ALSA, no dropped PCM or leaked worker')


if __name__=='__main__':main()
