"""Installation paths, peer identity and atomic launcher preferences."""

import json
import os
from pathlib import Path
import re
import tempfile

ROOT = Path(__file__).resolve().parents[1]
STATE_DIR = Path(os.environ.get("HLAUNCHER_STATE_DIR", "/var/lib/hlauncher"))
LOG_DIR = Path(os.environ.get("HLAUNCHER_LOG_DIR", "/var/log/hlauncher"))
RADIO_ADDRESS = os.environ.get("HLAUNCHER_RADIO_ADDRESS", "00:00:00:00:00:00").upper()
if not re.fullmatch(r"(?:[0-9A-F]{2}:){5}[0-9A-F]{2}", RADIO_ADDRESS):
    raise ValueError("Invalid HLAUNCHER_RADIO_ADDRESS")
RADIO_PATH = "/org/bluez/hci0/dev_" + RADIO_ADDRESS.replace(":", "_")
RFCOMM_PATH = "/org/bluealsa/hci0/dev_" + RADIO_ADDRESS.replace(":", "_") + "/rfcomm"


from sdk.hlauncher_sdk.theme import PALETTE as TILE_COLORS


def serial_number():
    if value := os.environ.get("HLAUNCHER_SERIAL"):
        return value.encode("ascii")[:32]
    try:
        return Path("/proc/device-tree/serial-number").read_bytes().rstrip(b"\0")[:32]
    except OSError:
        return b"HLauncher"


class Preferences:
    def __init__(self, path=None):
        self.path = Path(path) if path else STATE_DIR / "settings.json"
        self.data = {"enabled": {}, "background": {}, "default_plugin": None, "tile_color": "Blue"}
        try:
            loaded = json.loads(self.path.read_text())
            if not isinstance(loaded, dict) or not isinstance(
                loaded.get("enabled", {}), dict
            ):
                raise ValueError("invalid settings")
            self.data["enabled"] = {
                k: v
                for k, v in loaded.get("enabled", {}).items()
                if isinstance(k, str) and isinstance(v, bool)
            }
            background = loaded.get('background', {})
            if isinstance(background, dict):
                self.data['background'] = {k:v for k,v in background.items() if isinstance(k,str) and type(v) is bool}
            if isinstance(loaded.get("tile_color"), str) and loaded["tile_color"] in TILE_COLORS:
                self.data["tile_color"] = loaded["tile_color"]
            value = loaded.get("default_plugin")
            if value is None or isinstance(value, str):
                self.data["default_plugin"] = value
        except FileNotFoundError:
            pass
        except (ValueError, OSError):
            # Keep the file for diagnosis; a bad preference file must not stop boot.
            pass

    def enabled(self, manifest):
        return self.data["enabled"].get(
            manifest.id, manifest.bundled and manifest.default_enabled
        )

    def background_enabled(self, manifest):
        if manifest.id in ("carplay", "android-auto"):
            return manifest.keep_alive
        return manifest.keep_alive and self.data['background'].get(manifest.id, True)

    def set_background(self, manifest, enabled):
        if manifest.id in ("carplay", "android-auto"):
            raise ValueError("Background mode is automatic for this plugin")
        if not manifest.keep_alive:
            raise ValueError('Plugin does not support background mode')
        before = dict(self.data['background'])
        self.data['background'][manifest.id] = bool(enabled)
        try:
            self.save()
        except OSError:
            self.data['background'] = before
            raise

    def set_tile_color(self, name):
        if name not in TILE_COLORS:
            raise ValueError("Unknown tile color")
        before = self.data['tile_color']
        self.data['tile_color'] = name
        try:
            self.save()
        except OSError:
            self.data['tile_color'] = before
            raise

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(prefix=".settings-", dir=self.path.parent)
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(self.data, f, indent=2)
                f.write("\n")
                f.flush()
                os.fsync(f.fileno())
            os.replace(name, self.path)
            directory = os.open(self.path.parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            if os.path.exists(name):
                os.unlink(name)

    def set_enabled(self, manifest, enabled):
        before = json.loads(json.dumps(self.data))
        self.data["enabled"][manifest.id] = bool(enabled)
        if not enabled and self.data["default_plugin"] == manifest.id:
            self.data["default_plugin"] = None
        try:
            self.save()
        except OSError:
            self.data = before
            raise

    def set_default(self, plugin_id):
        before = self.data["default_plugin"]
        self.data["default_plugin"] = plugin_id
        try:
            self.save()
        except OSError:
            self.data["default_plugin"] = before
            raise
