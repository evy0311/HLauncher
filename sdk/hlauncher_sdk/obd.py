"""Read-only OBD snapshots from the launcher-owned BLE service."""
import json
import math
import os
from pathlib import Path
import time

KEYS = ('coolant','oil','ltft','maf')


def snapshot(path=None, now=None):
    now = time.monotonic() if now is None else now
    path = Path(path) if path else Path(os.environ.get('HLAUNCHER_STATE_DIR','/var/lib/hlauncher'))/'obd/status.json'
    fallback = dict(connected=False,values=[None]*4,message='Connect an OBD ELM327 dongle in Launcher Settings')
    try:
        state=json.loads(path.read_text())
        age=now-state.get('monotonic',0)
        if not 0<=age<4 or state.get('state')!='connected':return fallback
        values=[]
        for key in KEYS:
            item=state.get('readings',{}).get(key,{})
            value=item.get('value')
            age=now-item.get('monotonic',0)
            values.append(value if isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value) and 0<=age<5 else None)
        return dict(connected=True,values=values,message='Live OBD · unavailable sensors show —')
    except (OSError,ValueError,TypeError,AttributeError):
        return fallback
