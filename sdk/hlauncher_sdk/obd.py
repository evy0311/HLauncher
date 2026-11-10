"""Read-only gauge snapshots: HondaLink IPC first, BLE OBD where available."""
import json
import math
import os
from pathlib import Path
import time

KEYS = ('rpm','coolant','pedal_percent','intake','baro_native','vtec')


def finite(value):
    return isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value)


def snapshot(path=None, now=None, *, vehicle=None,allow_ble=True):
    now=time.monotonic() if now is None else now
    path=Path(path) if path else Path(os.environ.get('HLAUNCHER_STATE_DIR','/var/lib/hlauncher'))/'obd/status.json'
    result=dict(connected=False,values=[None]*6,sources=['']*6,ages=[None]*6,intervals=[None]*6,
                message='Waiting for HondaLink or a BLE OBD adapter')
    try:
        state=json.loads(path.read_text()) if allow_ble else {}
        age=now-state.get('monotonic',0)
        if finite(age) and 0<=age<4 and state.get('state')=='connected':
            result['connected']=True
            for index,key in enumerate(KEYS):
                item=state.get('readings',{}).get(key,{})
                value=item.get('value');age=now-item.get('monotonic',0)
                if finite(value) and finite(age) and 0<=age<5:
                    result['values'][index]=value;result['sources'][index]='BLE OBD';result['ages'][index]=age
    except (OSError,ValueError,TypeError,AttributeError):pass
    try:
        age=now-vehicle.get('monotonic',0)
        if vehicle.get('connected') and finite(age) and 0<=age<1:
            result['connected']=True
            for index,key,convert in ((0,'rpm',lambda v:v),(1,'coolant_c',lambda v:v*9/5+32),
                    (2,'pedal_percent',lambda v:v),(3,'intake_c',lambda v:v*9/5+32),
                    (4,'baro_native',lambda v:v),(5,'vtec',bool)):
                item=vehicle.get('readings',{}).get(key,{})
                value=item.get('value');age=now-item.get('monotonic',0)
                valid=(type(value) is bool or (finite(value) and value in (0,1))) if key=='vtec' else finite(value)
                if valid and finite(age) and 0<=age<5:
                    result['values'][index]=convert(value);result['sources'][index]='HondaLink';result['ages'][index]=age
                    interval=item.get('interval_seconds')
                    result['intervals'][index]=interval if finite(interval) and interval>0 else None
    except (ValueError,TypeError,AttributeError):pass
    sources=set(filter(None,result['sources']))
    if sources:result['message']=' + '.join(sorted(sources))+' · live readings'
    return result
