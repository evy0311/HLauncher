"""CarPlay picture preferences shared by the launcher and video plugin."""

import json
import os
from pathlib import Path
import tempfile

DEFAULTS = dict(saturation=100, contrast=100, brightness=0)
LIMITS = dict(saturation=(0, 150), contrast=(50, 150), brightness=(-25, 25))


def validate(values):
    result = dict(DEFAULTS)
    for key, value in values.items():
        if key not in LIMITS or type(value) is not int or not LIMITS[key][0] <= value <= LIMITS[key][1]:
            raise ValueError(f'Invalid {key}: {value}; expected integer in {LIMITS.get(key)}')
        result[key] = value
    return result


class PictureSettings:
    def __init__(self, path=None):
        self.path = Path(path) if path else Path(os.environ.get('HLAUNCHER_STATE_DIR', '/var/lib/hlauncher')) / 'carplay-color.json'
        self.values = dict(DEFAULTS)
        self.signature = None
        self.refresh()

    def refresh(self):
        try:
            stat = self.path.stat()
            signature = (stat.st_ino, stat.st_mtime_ns, stat.st_size)
            if signature == self.signature:
                return False
            values = json.loads(self.path.read_text())
            if not isinstance(values, dict):
                return False
            values = validate(values)
            changed = values != self.values
            self.values, self.signature = values, signature
            return changed
        except (OSError, ValueError, TypeError):
            # Bad external edits must not interrupt playback or reset a live picture.
            return False

    def save(self, values):
        values = validate(values)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix='.carplay-color-', dir=self.path.parent)
        try:
            with os.fdopen(fd, 'w') as f:
                json.dump(values, f, indent=2)
                f.write('\n')
                f.flush()
                os.fsync(f.fileno())
            os.replace(temporary, self.path)
            self.signature = None
            self.refresh()
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
