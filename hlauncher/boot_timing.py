"""Small, always-on startup milestones; no graphics, traffic or state-file I/O."""
import json
import os
import threading
import time


class BootTimeline:
    def __init__(self, clock=time.monotonic, emit=None):
        self.clock = clock
        self.started = clock()
        self.emit = emit or self.journal
        self.seen = set()
        self.lock = threading.Lock()

    @staticmethod
    def journal(item):
        try:
            print(json.dumps(item, separators=(',', ':')), flush=True)
        except OSError:
            pass  # Timing diagnostics must never prevent startup.

    def mark(self, phase):
        with self.lock:
            if phase in self.seen:
                return None
            self.seen.add(phase)
            now = self.clock()
            item = dict(state='boot_milestone', phase=phase, pid=os.getpid(),
                        boot_ms=round(now*1000, 3), process_ms=round((now-self.started)*1000, 3))
            self.emit(item)
            return item


timeline = BootTimeline()
mark = timeline.mark
