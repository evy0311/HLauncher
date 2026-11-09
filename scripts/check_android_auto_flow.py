"""Exercise AA plugin video/audio/touch/home with a framed protocol fixture.

This checks our plugin boundary, not a real Android Auto phone handshake.
"""
from pathlib import Path
from types import SimpleNamespace
import json
import os
import sys
import tempfile
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from hlauncher.catalog import Manifest
from hlauncher.plugin_host import PluginHost

manifest=Manifest.load(ROOT/'plugins/android-auto',bundled=True)
with tempfile.TemporaryDirectory() as folder:
    temp=Path(folder);engine=temp/'engine';touches=temp/'touches.jsonl'
    engine.write_text('''#!/usr/bin/python3
import json,os,select,struct,sys,time
from pathlib import Path
raw=Path('''+repr(str(ROOT/'plugins/carplay/runtime/usb/test-pattern.h264'))+''').read_bytes()
def packet(kind,data):
 sys.stdout.buffer.write(struct.pack('!I',len(data)+1)+bytes([kind])+data);sys.stdout.buffer.flush()
packet(2,b'{"status":"Fixture connected"}')
end=time.monotonic()+8;pending=b''
while time.monotonic()<end:
 packet(1,raw)
 packet(3,struct.pack('!IBB',48000,2,0)+bytes(1920))
 if select.select([sys.stdin],[],[],.04)[0]:
  chunk=os.read(0,65536)
  if not chunk:break
  pending+=chunk
  while b'\\n' in pending:
   line,pending=pending.split(b'\\n',1)
   line=line.decode()+'\\n'
   with open('''+repr(str(touches))+''','a') as log:log.write(line)
   event=json.loads(line)
   if event.get('action')==1:packet(2,b'{"home":true}')
''')
    engine.chmod(0o755)
    os.environ['HLAUNCHER_OPENAUTO_ENGINE']=str(engine)
    os.environ['HLAUNCHER_LOG_DIR']=str(temp/'logs')
    audio=[];home=[];events=[]
    broker=SimpleNamespace(stop_capture=lambda _:None,stop=lambda _:None,
                           request=lambda worker,message,active:audio.append(message))
    host=PluginHost({'android-auto':manifest},720,480,lambda **v:events.append(v),home.append,broker)
    try:
        host.activate('android-auto');frames=0
        end=time.monotonic()+5
        while time.monotonic()<end and (frames<2 or not audio):
            host.tick()
            if (frame:=host.frame()) is not None:
                assert len(frame)==720*480*2;frames+=1
            time.sleep(.01)
        assert frames>=2 and audio,(frames,audio,events[-5:])
        def contact(slot,action,x):
            return dict(slot=slot,action=action,x_raw=x,y_raw=10000,has_position=True)
        host.touch({'contacts':[contact(0,'down',10000),contact(1,'down',22000)]})
        host.touch({'contacts':[contact(0,'move',8000),contact(1,'move',24000)]})
        host.touch({'contacts':[]})
        end=time.monotonic()+3
        while time.monotonic()<end and not home:host.tick();time.sleep(.01)
        assert home and host.active is None
        assert host.workers['android-auto'].proc.poll() is None
        received=[json.loads(line) for line in touches.read_text().splitlines()]
        assert [e['action'] for e in received][:2]==[0,5],received
        assert any(e['action']==1 for e in received),received
        print(f'PASS: {frames} projected frames, PCM forwarding, two contacts, native return and background worker')
    finally:
        host.close()
        os.environ.pop('HLAUNCHER_OPENAUTO_ENGINE',None)
        os.environ.pop('HLAUNCHER_LOG_DIR',None)
