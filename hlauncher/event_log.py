"""Production logs contain bounded errors; debug mode opts into traffic recording."""
from datetime import datetime, timezone
import json
from logging.handlers import RotatingFileHandler
import logging
from pathlib import Path
import threading
import time
from .config import Preferences, LOG_DIR


class EventLog:
    def __init__(self, protocols, prefs=None, folder=None):
        self.protocols = protocols
        self.path = (prefs or Preferences()).path
        self.folder = Path(folder) if folder else LOG_DIR
        self.lock = threading.RLock()
        self.debug = False; self.checked = 0; self.handler = None; self.closed = False
        self.refresh(force=True)

    def refresh(self, force=False):
        with self.lock:
            if not self.closed: self._refresh(force)

    def _refresh(self, force=False):
        if not force and time.monotonic()-self.checked < 1: return
        self.checked = time.monotonic()
        debug = Preferences(self.path).data['debug_mode']
        changed = self.handler is None or debug != self.debug
        if changed:
            if self.handler: self.handler.close()
            self.folder.mkdir(parents=True, exist_ok=True)
            self.handler = RotatingFileHandler(self.folder/('debug.jsonl' if debug else 'errors.jsonl'),
                maxBytes=4*1024*1024 if debug else 256*1024, backupCount=2, encoding='utf-8')
            self.debug = debug
        if changed and debug and not self.protocols.recording: self.protocols.start()
        if changed and not debug and self.protocols.recording: self.protocols.stop()

    def __call__(self, **event):
        with self.lock:
            if self.closed: return
            self.refresh()
            event['wall'] = datetime.now(timezone.utc).isoformat()
            self.protocols.observe(event)  # status stays current without disk capture
            state = str(event.get('state', ''))
            failure = any(x in state for x in ('error', 'failed', 'rejected', 'unavailable', 'timeout'))
            if not self.debug and not failure: return
            if not self.debug:
                event = {k:v for k,v in event.items() if k in
                         ('wall','state','error','reason','plugin','phase','status','result_code')}
            line = json.dumps(event, default=str)
            self.handler.emit(logging.LogRecord('hlauncher', logging.ERROR if failure else logging.DEBUG,
                                                '', 0, line, (), None))
            # journald receives only error summaries in production as well.
            if failure: print(line, flush=True)

    def close(self):
        with self.lock:
            self.closed = True
            if self.handler: self.handler.close()
