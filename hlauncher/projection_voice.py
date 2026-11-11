"""Lease actual projection audio/voice state to the isolated HFP controller."""
import json
import os
from pathlib import Path
import re
import tempfile
import time

RUNTIME=Path(os.environ.get('HLAUNCHER_RUNTIME_DIR','/run/hlauncher'))
VOICE_FLAGS = ('call_audio', 'siri', 'recording')


def normalize_call(details):
    """Bound caller fields for the private lease and quoted HFP parameters."""
    if not isinstance(details, dict):
        return {}
    call = {}
    name = details.get('name')
    if isinstance(name, str):
        name = ''.join(c for c in name[:128] if c.isprintable() and c not in '"\\').strip()
        name = name.encode('utf-8')[:64].decode('utf-8', errors='ignore')
        if name:
            call['name'] = name
    number = details.get('number')
    if isinstance(number, str) and len(number) <= 64:
        number = re.sub(r'[ ().-]', '', number)
        if re.fullmatch(r'\+?[0-9]{1,32}', number):
            call['number'] = number
    if type(details.get('incoming')) is bool:
        call['incoming'] = details['incoming']
    return call


def read_voice(path=None):
    try:
        path=Path(path) if path else RUNTIME/'projection-voice.json'
        if path.stat().st_size>4096:return {}
        doc=json.loads(path.read_text())
        if not isinstance(doc,dict) or not 0<=time.monotonic()-doc['updated_monotonic']<6:return {}
        if type(doc.get('launcher_pid')) is not int:return {}
        os.kill(doc['launcher_pid'],0)
        if any(type(doc.get(k)) is not bool for k in VOICE_FLAGS):return {}
        if 'call' in doc:
            doc['call'] = normalize_call(doc['call']) if doc['call_audio'] else {}
        return doc
    except (OSError,ValueError,KeyError,TypeError):return {}


class ProjectionVoice:
    def __init__(self,event=lambda **kw:None,path=None):
        self.path=Path(path) if path else RUNTIME/'projection-voice.json'
        self.event=event;self.sources={};self.current={};self.updated=0

    def update(self,plugin,fields):
        if (not isinstance(fields, dict) or set(fields).difference((*VOICE_FLAGS, 'call'))
                or any(type(fields.get(key)) is not bool for key in VOICE_FLAGS)):
            raise ValueError('Invalid projection voice state')
        flags = {key: fields[key] for key in VOICE_FLAGS}
        call = normalize_call(fields.get('call')) if flags['call_audio'] else {}
        old=self.sources.get(plugin,{}).get('fields')
        self.sources[plugin]=dict(fields=flags,call=call,at=time.monotonic())
        if old!=flags:self.event(state='projection_voice_state',plugin=plugin,**flags)

    def clear(self,plugin):
        self.sources.pop(plugin,None)

    def tick(self,selected,force=False):
        now=time.monotonic()
        if not self.sources and not self.current:return
        source=self.sources.get(selected,{})
        if not 0 <= now - source.get('at', -100) < 5:
            source = {}
        fields = {key: source.get('fields', {}).get(key, False) for key in VOICE_FLAGS}
        current=dict(plugin=selected,**fields)
        if source.get('call'):
            current['call'] = source['call']
        if not force and current==self.current and now-self.updated<1:return
        if selected != self.current.get('plugin') or any(fields[k] != self.current.get(k) for k in VOICE_FLAGS):
            self.event(state='projection_voice_route',plugin=selected,**fields)
        self.current=current;self.updated=now
        self.path.parent.mkdir(parents=True,exist_ok=True)
        fd,name=tempfile.mkstemp(prefix='.voice-',dir=self.path.parent)
        try:
            with os.fdopen(fd,'w') as out:
                json.dump(dict(current,launcher_pid=os.getpid(),updated_monotonic=now),out)
            os.replace(name,self.path)
        finally:
            if os.path.exists(name):os.unlink(name)
