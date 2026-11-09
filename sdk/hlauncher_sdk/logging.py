"""Shared runtime debug policy for host and isolated plugin logs."""
import json
import logging
import os
from pathlib import Path
import re
import threading
import time

_lock=threading.Lock()
_checked=0
_debug=False


def debug_enabled():
    global _checked, _debug
    with _lock:
        now=time.monotonic()
        if now-_checked>1:
            _checked=now
            try:
                path=Path(os.environ.get('HLAUNCHER_STATE_DIR','/var/lib/hlauncher'))/'settings.json'
                _debug=json.loads(path.read_text()).get('debug_mode') is True
            except (OSError,ValueError,AttributeError):_debug=False
        return _debug


def output_summary(line, debug=None):
    if debug is None:debug=debug_enabled()
    text=line.decode(errors='replace') if isinstance(line,bytes) else str(line)
    text=text.rstrip()[:8192]
    if debug:return text
    try:
        data=json.loads(text)
        if isinstance(data,dict):
            state=str(data.get('state',data.get('event','')))
            if not data.get('error') and not any(k in state for k in ('error','failed','unavailable','timeout')):return None
            return json.dumps({k:v for k,v in data.items() if k in ('state','event','error','reason','plugin')})
    except ValueError:pass
    return text if re.search(r'\b(error|exception|traceback|failed|fatal)\b',text,re.I) else None


class DebugFilter(logging.Filter):
    def filter(self, record):
        return record.levelno>=logging.WARNING or debug_enabled()
