"""Durable adapter-branding requests; USB transfer is not firmware read-back."""
import json
from pathlib import Path
import time
from .config import STATE_DIR
from .setup_state import atomic_json


class BrandingRequests:
    def __init__(self,path=None):
        self.path=Path(path) if path else STATE_DIR/'adapter-branding.json'
        try:self.data=json.loads(self.path.read_text())
        except (OSError,ValueError):self.data={}
        if not isinstance(self.data,dict):self.data={}
    @property
    def pending(self):return self.data.get('status') in ('queued','waiting','sending')
    def request(self):
        data=dict(request_id=str(time.time_ns()),status='queued',label='HLauncher',verified=False)
        atomic_json(self.path,data);self.data=data
        return data['request_id']
    def update(self,request_id,status,error=''):
        if request_id!=self.data.get('request_id') or not request_id:return
        if self.data.get('status') in ('transferred','failed'):return
        if status=='sent':status='transferred'
        if status not in ('waiting','sending','transferred','failed'):return
        data=dict(self.data,status=status,error=str(error or '')[:160],verified=False)
        if data!=self.data:atomic_json(self.path,data);self.data=data
