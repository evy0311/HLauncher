"""Exercise gauge rendering, frame leases and Home through a real plugin process."""
from pathlib import Path
import sys,time
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from hlauncher.catalog import Manifest
from hlauncher.plugin_host import PluginHost
from hlauncher.audio import AudioBroker
manifest=Manifest.load(ROOT/'plugins/obd',bundled=True)
home=[]
host=PluginHost({'obd':manifest},720,480,lambda **v:None,home.append,AudioBroker(lambda **v:None))
frames=0
try:
    host.activate('obd')
    end=time.monotonic()+2
    while time.monotonic()<end:
        host.tick()
        if (frame:=host.frame()) is not None:
            assert len(frame)==720*480*2
            frames+=1
        time.sleep(.005)
    assert frames>=15, f'Too few frames: {frames}'
    host.touch({'contacts':[{'action':'down','x_px':60,'y_px':30}]})
    host.touch({'contacts':[{'action':'up','x_px':None,'y_px':None}]})
    end=time.monotonic()+2
    while time.monotonic()<end and not home:
        host.tick();time.sleep(.01)
    assert home and host.active is None
    # In the actual launcher home() deactivates the host too; the control handler
    # already deactivated it before invoking this callback.
    assert 'obd' not in host.workers
    print(f'PASS: {frames} gauge frames, Home handled, foreground-only worker closed')
finally:host.close()
