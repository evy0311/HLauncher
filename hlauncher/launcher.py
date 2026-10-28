"""Built-in launcher/settings UI and the sole owner of the radio display."""

import math
import time
from PIL import Image, ImageDraw, ImageFont
from .audio import AudioBroker
from .catalog import discover
from .config import Preferences
from .display import Framebuffer
from .plugin_host import PluginHost
from .touch import pixels, for_viewport

REPOSITORY = "github.com/evy0311/HLauncher"


class Launcher:
    def __init__(
        self,
        event=lambda **kw: None,
        framebuffer=None,
        preferences=None,
        manifests=None,
    ):
        self.event = event
        self.fb = framebuffer or Framebuffer(event)
        self.fb.open()
        self.prefs = preferences or Preferences()
        self.manifests = discover(event) if manifests is None else manifests
        self.audio = AudioBroker(event)
        self.host = PluginHost(
            self.manifests, self.fb.w, self.fb.h, event, self.home, self.audio
        )
        self.mode = "home"
        self.page = 0
        self.settings_page = 0
        self.actions = []
        self.press = None
        self.last_xy = None
        self.banner = ""
        self.last_status = None
        self.has_frame = False
        self.pending_default = False
        self.last_frame_at = 0
        self.draw()

    def font(self, size):
        try:
            return ImageFont.truetype(
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", size
            )
        except OSError:
            return ImageFont.load_default()

    def button(self, draw, box, label, action, color="#18416e", size=19):
        draw.rounded_rectangle(box, radius=12, fill=color)
        draw.text((box[0] + 12, box[1] + 10), label, font=self.font(size), fill="white")
        self.actions.append((box, action))

    def enabled(self):
        return [m for m in self.manifests.values() if self.prefs.enabled(m)]

    def launch(self, app_id):
        if app_id not in (
            "com.honda.hondalink.connect",
            "com.honda.hondalink.launcher",
        ):
            return False
        self.home()
        self.pending_default = True
        return True

    def home(self, message=""):
        self.host.deactivate()
        self.mode = "home"
        self.press = None
        self.has_frame = False
        self.pending_default = False
        self.banner = message
        self.draw()
        self.event(state="launcher_home", message=message)

    def settings(self):
        self.host.deactivate()
        self.mode = "settings"
        self.settings_page = 0
        self.banner = ""
        self.press = None
        self.draw()

    def open_plugin(self, plugin_id):
        if plugin_id not in self.manifests or not self.prefs.enabled(
            self.manifests[plugin_id]
        ):
            self.home("Plugin unavailable")
            return
        try:
            self.mode = "plugin"
            self.has_frame = False
            self.press = None
            self.last_status = None
            self.host.activate(plugin_id)
            self.draw()
        except (OSError, ValueError) as exc:
            self.event(state="plugin_launch_failed", plugin=plugin_id, error=str(exc))
            self.home("Could not start " + self.manifests[plugin_id].name)

    def toggle_plugin(self, plugin_id):
        manifest = self.manifests[plugin_id]
        enabled = not self.prefs.enabled(manifest)
        try:
            self.prefs.set_enabled(manifest, enabled)
            if not enabled:
                self.host.stop(plugin_id)
            self.banner = ""
            self.event(
                state="plugin_enabled_changed", plugin=plugin_id, enabled=enabled
            )
        except OSError as exc:
            self.banner = "Could not save settings"
            self.event(state="settings_save_failed", error=str(exc))
        self.draw()

    def cycle_default(self):
        choices = [None] + [m.id for m in self.enabled()]
        old = self.prefs.data["default_plugin"]
        next_id = (
            choices[(choices.index(old) + 1) % len(choices)] if old in choices else None
        )
        try:
            self.prefs.set_default(next_id)
            self.banner = ""
        except OSError as exc:
            self.banner = "Could not save settings"
            self.event(state="settings_save_failed", error=str(exc))
        self.draw()

    def footer(self, draw):
        w, h = self.fb.w, self.fb.h
        draw.text(
            (24, h - 42), "Get more plugins at", font=self.font(14), fill="#b4b4b4"
        )
        draw.text((24, h - 23), REPOSITORY, font=self.font(14), fill="#98bed4")

    def draw(self):
        w, h = self.fb.w, self.fb.h
        image = Image.new("RGB", (w, h), "#080c14")
        d = ImageDraw.Draw(image)
        self.actions = []
        if self.mode == "home":
            d.text((24, 16), "HLauncher", font=self.font(28), fill="white")
            if self.banner:
                d.text((24, 55), self.banner[:66], font=self.font(15), fill="#ffbc75")
            entries = [("Settings", self.settings, "#18416e", "⚙")]
            entries += [
                (
                    m.name,
                    lambda pid=m.id: self.open_plugin(pid),
                    m.color,
                    m.name[:2].upper(),
                )
                for m in self.enabled()
            ]
            pages = max(1, math.ceil(len(entries) / 6))
            self.page = min(self.page, pages - 1)
            tw = (w - 72) // 3
            top = 88
            bottom = h - 100
            th = (bottom - top - 12) // 2
            for i in range(6):
                col, row = i % 3, i // 3
                x = 24 + col * (tw + 12)
                y = top + row * (th + 12)
                box = (x, y, x + tw, y + th)
                at = self.page * 6 + i
                if at >= len(entries):
                    d.rounded_rectangle(box, radius=14, outline="#1d2838", width=1)
                    continue
                label, action, color, icon = entries[at]
                d.rounded_rectangle(box, radius=14, fill=color)
                # Simple vector icon treatment; no radio firmware assets required.
                d.ellipse((x + 16, y + 14, x + 61, y + 59), fill="#ffffff")
                text = "S" if label == "Settings" else icon
                d.text((x + 24, y + 20), text, font=self.font(19), fill=color)
                d.text(
                    (x + 16, y + th - 36), label[:18], font=self.font(20), fill="white"
                )
                self.actions.append((box, action))
            if pages > 1:
                self.button(
                    d,
                    (w - 185, h - 85, w - 110, h - 48),
                    "Prev",
                    lambda: self.change_page(-1),
                    size=15,
                )
                self.button(
                    d,
                    (w - 100, h - 85, w - 24, h - 48),
                    "Next",
                    lambda: self.change_page(1),
                    size=15,
                )
                d.text(
                    (24, h - 80),
                    f"{self.page+1} / {pages}",
                    font=self.font(15),
                    fill="white",
                )
        elif self.mode == "settings":
            self.button(d, (16, 14, 110, 56), "Back", self.home)
            d.text((130, 18), "Settings", font=self.font(27), fill="white")
            entries = list(self.manifests.values())
            pages = max(1, math.ceil(len(entries) / 3))
            self.settings_page = min(self.settings_page, pages - 1)
            if not entries:
                d.text(
                    (24, 100), "No plugins installed", font=self.font(20), fill="white"
                )
            for i, m in enumerate(
                entries[self.settings_page * 3 : self.settings_page * 3 + 3]
            ):
                y = 85 + i * 58
                d.text((24, y + 12), m.name, font=self.font(21), fill="white")
                on = self.prefs.enabled(m)
                self.button(
                    d,
                    (w - 165, y, w - 24, y + 48),
                    "Enabled" if on else "Disabled",
                    lambda pid=m.id: self.toggle_plugin(pid),
                    color="#246b48" if on else "#424955",
                    size=18,
                )
            default = self.prefs.data["default_plugin"]
            label = (
                self.manifests[default].name
                if default in self.manifests
                and self.prefs.enabled(self.manifests[default])
                else "Launcher"
            )
            self.button(
                d,
                (24, h - 182, w - 24, h - 130),
                "Start with: " + label,
                self.cycle_default,
            )
            if pages > 1:
                self.button(
                    d,
                    (w - 185, h - 120, w - 110, h - 77),
                    "Prev",
                    lambda: self.change_settings_page(-1),
                    size=15,
                )
                self.button(
                    d,
                    (w - 100, h - 120, w - 24, h - 77),
                    "Next",
                    lambda: self.change_settings_page(1),
                    size=15,
                )
            if self.banner:
                d.text(
                    (24, h - 75), self.banner[:60], font=self.font(15), fill="#ffbc75"
                )
        else:
            manifest = self.manifests.get(self.host.active)
            self.button(d, (16, 14, 110, 56), "Home", self.home)
            d.text(
                (130, 18),
                manifest.name if manifest else "Plugin",
                font=self.font(27),
                fill="white",
            )
            text = self.host.status() or "Starting plugin..."
            words = text.split()
            lines = [""]
            for word in words:
                if len(lines[-1]) + len(word) > 48:
                    lines.append("")
                lines[-1] += word + " "
            for i, line in enumerate(lines[:4]):
                d.text((24, 155 + i * 30), line, font=self.font(20), fill="white")
        self.footer(d)
        self.fb.image(image)

    def change_page(self, delta):
        count = math.ceil((1 + len(self.enabled())) / 6)
        self.page = (self.page + delta) % max(1, count)
        self.draw()

    def change_settings_page(self, delta):
        count = math.ceil(len(self.manifests) / 3)
        self.settings_page = (self.settings_page + delta) % max(1, count)
        self.draw()

    def update(self, touch):
        touch = for_viewport(touch, self.fb.w, self.fb.h)
        primary = touch.get("contacts", [])
        primary = primary[0] if primary else {"action": "unused", "has_position": False}
        point = pixels(primary, self.fb.w, self.fb.h)
        if point:
            self.last_xy = point
        action = primary["action"]
        # Plugins own their full viewport after their first frame. Home is provided
        # by the app's own host-return action (the Honda icon in CarPlay).
        if self.mode == "plugin" and self.has_frame:
            self.host.touch(touch)
            return
        if action == "down":
            self.press = point
        elif action in ("up", "unused"):
            start, self.press = self.press, None
            if (
                start
                and self.last_xy
                and max(
                    abs(start[0] - self.last_xy[0]), abs(start[1] - self.last_xy[1])
                )
                < 25
            ):
                for box, callback in self.actions:
                    if box[0] <= start[0] <= box[2] and box[1] <= start[1] <= box[3]:
                        callback()
                        return
        if self.mode == "plugin":
            self.host.touch(touch)

    def session_changed(self, **values):
        self.host.session_changed(**values)
        if values.get("connected") is False:
            self.home()

    def tick(self):
        self.host.tick()
        if self.pending_default:
            self.pending_default = False
            plugin_id = self.prefs.data["default_plugin"]
            if plugin_id in self.manifests and self.prefs.enabled(
                self.manifests[plugin_id]
            ):
                self.open_plugin(plugin_id)
        if self.mode != "plugin":
            return
        try:
            frame = self.host.frame()
        except (OSError, ValueError, RuntimeError) as exc:
            plugin_id = self.host.active
            if plugin_id:
                self.host.failed(plugin_id, exc)
            return
        if frame is not None:
            self.fb.blit(frame)
            self.has_frame = True
            self.last_frame_at = time.monotonic()
        else:
            status = self.host.status()
            if status != self.last_status:
                self.last_status = status
                # A disconnect/error replaces stale CarPlay pixels with a waiting page.
                worker = self.host.workers.get(self.host.active)
                if worker is not None and not worker.video_available:
                    self.has_frame = False
                    self.draw()

    def close(self):
        self.host.close()
        self.fb.close()
