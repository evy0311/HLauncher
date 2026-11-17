"""Installation paths, peer identity and atomic launcher preferences."""

import json
import copy
import fcntl
import os
from pathlib import Path
import re
import tempfile

ROOT = Path(__file__).resolve().parents[1]
STATE_DIR = Path(os.environ.get("HLAUNCHER_STATE_DIR", "/var/lib/hlauncher"))
RUNTIME_DIR = Path(os.environ.get("HLAUNCHER_RUNTIME_DIR", "/run/hlauncher"))
LOG_DIR = Path(os.environ.get("HLAUNCHER_LOG_DIR", "/var/log/hlauncher"))
RADIO_ADDRESS = os.environ.get("HLAUNCHER_RADIO_ADDRESS", "00:00:00:00:00:00").upper()
if not re.fullmatch(r"(?:[0-9A-F]{2}:){5}[0-9A-F]{2}", RADIO_ADDRESS):
    raise ValueError("Invalid HLAUNCHER_RADIO_ADDRESS")
try:
    _peer = json.loads((STATE_DIR/'radio.json').read_text())
    if _peer.get('verified') is True and re.fullmatch(r"(?:[0-9A-F]{2}:){5}[0-9A-F]{2}", _peer.get('address','')):
        RADIO_ADDRESS = _peer['address']
except (OSError, ValueError, TypeError, AttributeError):
    pass
RADIO_PATH = "/org/bluez/hci0/dev_" + RADIO_ADDRESS.replace(":", "_")
RFCOMM_PATH = "/org/bluealsa/hci0/dev_" + RADIO_ADDRESS.replace(":", "_") + "/rfcomm"


from sdk.hlauncher_sdk.palette import PALETTE as TILE_COLORS, normalize_color


def serial_number():
    if value := os.environ.get("HLAUNCHER_SERIAL"):
        return value.encode("ascii")[:32]
    try:
        return Path("/proc/device-tree/serial-number").read_bytes().rstrip(b"\0")[:32]
    except OSError:
        return b"HLauncher"


SAFETY_NOTICE_VERSION = 2
CARPLAY_FRAME_RATES = (30, 60)
WIFI_POWER_MODES = ('on', 'off', 'sleep')


def tile_color_values(name):
    if not isinstance(name, str) or name not in TILE_COLORS:
        name = normalize_color(name)
    return {'tile_color': name, 'custom_color': name} if name.startswith('#') else {'tile_color': name}


class Preferences:
    def __init__(self, path=None):
        self.path = Path(path) if path else STATE_DIR / "settings.json"
        self.data = {"enabled": {}, "background": {}, "default_plugin": None, "tile_color": "Red", "custom_color": "#198B96",
                     "setup_complete": False, "setup_step": 0, "safety_notice_version": 0,
                     "debug_mode": False, "show_clock": False, "ssh_enabled": False, "wifi_power": "off",
                     "wifi_delay_boot": True,
                     "layout_theme": "oem",
                     "home_pages": [], "carplay_fps": CARPLAY_FRAME_RATES[0],
                     "carplay_auto_night": True, "android_auto_auto_night": True,
                     "carplay_car_gps": False, "android_auto_car_gps": False}
        try:
            loaded = json.loads(self.path.read_text())
            if not isinstance(loaded, dict) or not isinstance(
                loaded.get("enabled", {}), dict
            ):
                raise ValueError("invalid settings")
            # Existing installations retain their choices; only fresh images auto-onboard.
            self.data['setup_complete'] = loaded.get('setup_complete', True) is True
            version = loaded.get('safety_notice_version')
            if type(version) is int:
                self.data['safety_notice_version'] = version
            self.data['debug_mode'] = loaded.get('debug_mode', False) is True
            self.data['show_clock'] = loaded.get('show_clock', False) is True
            self.data['ssh_enabled'] = loaded.get('ssh_enabled', False) is True
            # Settings from before the Wi-Fi controls used always-on Wi-Fi.
            previous_mode = 'on' if self.data['setup_complete'] else 'off'
            mode = loaded.get('wifi_power')
            self.data['wifi_power'] = mode if mode in WIFI_POWER_MODES else previous_mode
            delay = loaded.get('wifi_delay_boot')
            self.data['wifi_delay_boot'] = delay if type(delay) is bool else not self.data['setup_complete']
            layout_theme = loaded.get('layout_theme')
            if isinstance(layout_theme, str) and re.fullmatch(r'[a-z][a-z0-9-]{0,31}', layout_theme):
                self.data['layout_theme'] = layout_theme
            fps = loaded.get('carplay_fps')
            if type(fps) is int and fps in CARPLAY_FRAME_RATES:
                self.data['carplay_fps'] = fps
            for key in ('carplay_auto_night', 'android_auto_auto_night',
                        'carplay_car_gps', 'android_auto_car_gps'):
                if type(loaded.get(key)) is bool:
                    self.data[key] = loaded[key]
            pages = loaded.get('home_pages')
            if isinstance(pages, list) and all(isinstance(page, list) and len(page) == 6 for page in pages):
                self.data['home_pages'] = [[item if isinstance(item, str) else None for item in page]
                                           for page in pages]
            step = loaded.get('setup_step', 0)
            self.data['setup_step'] = step if type(step) is int and 0 <= step <= 5 else 0
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
            try:self.data['custom_color']=normalize_color(loaded.get('custom_color',self.data['custom_color']))
            except ValueError:pass
            if isinstance(loaded.get('tile_color'),str) and loaded['tile_color'] not in TILE_COLORS:
                try:
                    self.data['tile_color']=normalize_color(loaded['tile_color'])
                    self.data['custom_color']=self.data['tile_color']
                except ValueError:pass
            value = loaded.get("default_plugin")
            if value is None or isinstance(value, str):
                self.data["default_plugin"] = value
        except FileNotFoundError:
            pass
        except (ValueError, OSError):
            # Keep the file for diagnosis; a bad preference file must not stop boot.
            pass

        self._saved = copy.deepcopy(self.data)

    @property
    def safety_notice_accepted(self):
        version = self.data['safety_notice_version']
        return type(version) is int and version == SAFETY_NOTICE_VERSION

    def accept_safety_notice(self):
        previous = self.data['safety_notice_version']
        self.data['safety_notice_version'] = SAFETY_NOTICE_VERSION
        try:
            self.save(force=('safety_notice_version',))
        except OSError:
            self.data['safety_notice_version'] = previous
            raise

    def enabled(self, manifest):
        if getattr(manifest, 'revision', ''):
            return manifest.enabled and not manifest.blocked
        return self.data["enabled"].get(
            manifest.id, manifest.bundled and manifest.default_enabled
        )

    def background_enabled(self, manifest):
        if getattr(manifest, 'revision', ''):
            return False
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
        changes = tile_color_values(name)
        before = {key: self.data[key] for key in changes}
        self.data.update(changes)
        try:
            self.save()
        except OSError:
            self.data.update(before)
            raise

    def save(self, force=()):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        lock_fd = os.open(self.path.with_name('.'+self.path.name+'.lock'), os.O_CREAT|os.O_RDWR, 0o600)
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX)
            try:
                current = json.loads(self.path.read_text())
                if not isinstance(current, dict): current = {}
            except (OSError, ValueError): current = {}
            merged = dict(current)  # Preserve settings introduced by a newer release during rollback.
            for key, value in self.data.items():
                if key in ('enabled','background') and isinstance(current.get(key),dict):
                    item = dict(current[key])
                    old = self._saved.get(key,{})
                    item.update({k:v for k,v in value.items() if k not in item or old.get(k)!=v})
                    merged[key] = item
                else:
                    merged[key] = (value if key in force or key not in current or self._saved.get(key)!=value
                                   else current[key])
            fd, name = tempfile.mkstemp(prefix=".settings-", dir=self.path.parent)
            try:
                with os.fdopen(fd, "w") as f:
                    json.dump(merged, f, indent=2)
                    f.write("\n"); f.flush(); os.fsync(f.fileno())
                os.replace(name, self.path)
                directory = os.open(self.path.parent, os.O_RDONLY)
                try: os.fsync(directory)
                finally: os.close(directory)
                self.data = merged
                self._saved = copy.deepcopy(merged)
            finally:
                if os.path.exists(name): os.unlink(name)
        finally:
            os.close(lock_fd)

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

    @property
    def carplay_fps(self):
        fps = self.data['carplay_fps']
        return fps if type(fps) is int and fps in CARPLAY_FRAME_RATES else CARPLAY_FRAME_RATES[0]

    def set_carplay_fps(self, fps):
        if type(fps) is not int or fps not in CARPLAY_FRAME_RATES:
            raise ValueError('CarPlay frame rate must be 30 or 60 FPS')
        previous = self.data['carplay_fps']
        self.data['carplay_fps'] = fps
        try:
            self.save(force=('carplay_fps',))
        except OSError:
            self.data['carplay_fps'] = previous
            raise

    def auto_night(self, plugin_id):
        return self.data.get(plugin_id.replace('-', '_') + '_auto_night') is True

    def set_auto_night(self, plugin_id, enabled):
        key = plugin_id.replace('-', '_') + '_auto_night'
        previous = self.data[key]
        self.data[key] = bool(enabled)
        try:
            self.save(force=(key,))
        except OSError:
            self.data[key] = previous
            raise

    def car_gps(self, plugin_id):
        return self.data.get(plugin_id.replace('-', '_') + '_car_gps') is True

    def set_car_gps(self, plugin_id, enabled):
        key = plugin_id.replace('-', '_') + '_car_gps'
        previous = self.data[key]
        self.data[key] = bool(enabled)
        try:
            self.save(force=(key,))
        except OSError:
            self.data[key] = previous
            raise

    def set_wifi_power(self, mode):
        if mode not in WIFI_POWER_MODES:
            raise ValueError('Unknown Wi-Fi mode')
        previous = self.data['wifi_power']
        self.data['wifi_power'] = mode
        try:
            self.save(force=('wifi_power',))
        except OSError:
            self.data['wifi_power'] = previous
            raise

    def set_home_pages(self, pages):
        previous = self.data['home_pages']
        self.data['home_pages'] = copy.deepcopy(pages)
        try:
            self.save()
        except OSError:
            self.data['home_pages'] = previous
            raise
