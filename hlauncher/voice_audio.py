"""Voice-only route; ordinary projection media always retains its HDMI path."""
import json
import os
from pathlib import Path
import tempfile
from .config import STATE_DIR


class VoiceAudio:
    def __init__(self,path=None):
        self.path=Path(path) if path else STATE_DIR/'voice-audio.json'
        self.output='sco';self.refresh()

    def refresh(self):
        before=self.output
        try:
            value=json.loads(self.path.read_text()).get('output')
            if value in ('hdmi','sco'):self.output=value
        except (OSError,ValueError,AttributeError):pass
        return before!=self.output

    def save(self,output):
        if output not in ('hdmi','sco'):raise ValueError('Invalid voice output')
        self.path.parent.mkdir(parents=True,exist_ok=True)
        fd,name=tempfile.mkstemp(prefix='.voice-audio-',dir=self.path.parent)
        try:
            with os.fdopen(fd,'w') as f:json.dump(dict(output=output),f)
            os.replace(name,self.path);self.output=output
        finally:
            if os.path.exists(name):os.unlink(name)


class VoicePlaybackSettings:
    values=dict(output='sco',pipewire=False)
    def device(self):return 'hlauncher_voice'
    def refresh(self):return False
