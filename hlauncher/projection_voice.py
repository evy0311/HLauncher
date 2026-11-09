"""Lease actual projection audio/voice state to the isolated HFP controller."""
import json
import os
from pathlib import Path
import tempfile
import time

RUNTIME=Path(os.environ.get('HLAUNCHER_RUNTIME_DIR','/run/hlauncher'))


def read_voice(path=None):
    try:
        path=Path(path) if path else RUNTIME/'projection-voice.json'
        if path.stat().st_size>4096:return {}
        doc=json.loads(path.read_text())
        if not isinstance(doc,dict) or not 0<=time.monotonic()-doc['updated_monotonic']<6:return {}
        if type(doc.get('launcher_pid')) is not int:return {}
        os.kill(doc['launcher_pid'],0)
        if any(type(doc.get(k)) is not bool for k in ('call_audio','siri','recording')):return {}
        return doc
    except (OSError,ValueError,KeyError,TypeError):return {}


class ProjectionVoice:
    def __init__(self,event=lambda **kw:None,path=None):
        self.path=Path(path) if path else RUNTIME/'projection-voice.json'
        self.event=event;self.sources={};self.current={};self.updated=0

    def update(self,plugin,fields):
        if not isinstance(fields,dict) or set(fields)!={'call_audio','siri','recording'} or any(type(v) is not bool for v in fields.values()):
            raise ValueError('Invalid projection voice state')
        old=self.sources.get(plugin,{}).get('fields')
        self.sources[plugin]=dict(fields=dict(fields),at=time.monotonic())
        if old!=fields:self.event(state='projection_voice_state',plugin=plugin,**fields)

    def clear(self,plugin):
        self.sources.pop(plugin,None)

    def tick(self,selected,force=False):
        now=time.monotonic()
        if not self.sources and not self.current:return
        source=self.sources.get(selected,{})
        fields=source.get('fields',{}) if 0<=now-source.get('at',-100)<5 else {}
        fields=dict(call_audio=bool(fields.get('call_audio')),siri=bool(fields.get('siri')),recording=bool(fields.get('recording')))
        current=dict(plugin=selected,**fields)
        if not force and current==self.current and now-self.updated<1:return
        if current!=self.current:self.event(state='projection_voice_route',**current)
        self.current=current;self.updated=now
        self.path.parent.mkdir(parents=True,exist_ok=True)
        fd,name=tempfile.mkstemp(prefix='.voice-',dir=self.path.parent)
        try:
            with os.fdopen(fd,'w') as out:
                json.dump(dict(current,launcher_pid=os.getpid(),updated_monotonic=now),out)
            os.replace(name,self.path)
        finally:
            if os.path.exists(name):os.unlink(name)
