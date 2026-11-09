"""Check the real OpenAuto worker without a phone; no radio/display ownership."""
import os
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from hlauncher.catalog import Manifest
from hlauncher.plugin_host import PluginHost
from hlauncher.audio import AudioBroker

manifest=Manifest.load(ROOT/'plugins/android-auto',bundled=True)
events=[]
host=PluginHost({'android-auto':manifest},720,480,lambda **v:events.append(v),lambda _:None,AudioBroker(lambda **v:None))
try:
    host.activate('android-auto')
    end=time.monotonic()+8
    while time.monotonic()<end:
        host.tick()
        if host.status().startswith('Connect an Android phone'):break
        time.sleep(.01)
    assert host.status().startswith('Connect an Android phone'),host.status()
    worker=host.workers['android-auto']
    assert worker.proc.poll() is None
    host.deactivate()
    for _ in range(30):host.tick();time.sleep(.01)
    assert host.workers['android-auto'] is worker and worker.proc.poll() is None
    host.activate('android-auto')
    for _ in range(30):host.tick();time.sleep(.01)
    assert host.workers['android-auto'] is worker
    print('PASS: real OpenAuto engine waiting for USB; background/return retains worker')
finally:host.close()
