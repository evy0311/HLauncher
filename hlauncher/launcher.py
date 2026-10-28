"""Built-in launcher/settings UI and the sole owner of the radio display."""

import math
import time
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter
from sdk.hlauncher_sdk.fonts import font as ui_font
from . import __version__
from .diagnostics import Diagnostics, power_status
from .obd import ObdManager
from .audio import AudioBroker
from .catalog import discover
from .config import Preferences, TILE_COLORS
from .appearance import background as draw_background, glass_tile, draw_icon, button_surface, dither_rgb565, border_color
from .colors import PictureSettings, DEFAULTS, LIMITS
from .display import Framebuffer
from .plugin_host import PluginHost
from .touch import pixels, for_viewport


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
        self.picture = PictureSettings(self.prefs.path.with_name('carplay-color.json'))
        self.picture_values = dict(self.picture.values)
        self.picture_drag = None
        self.picture_dirty = False
        self.picture_saved = self.picture_checked = 0
        self.picture_sliders = []
        self.hdmi_range_original = None
        self.hdmi_range_label = "Automatic"
        self.manifests = discover(event) if manifests is None else manifests
        self.audio = AudioBroker(event)
        self.host = PluginHost(
            self.manifests, self.fb.w, self.fb.h, event, self.home, self.audio,
            background_allowed=self.prefs.background_enabled,
        )
        self.diagnostics = Diagnostics()
        self.obd = ObdManager(event)
        self.obd_page = 0
        self.obd_revision = -1
        self.diagnostic_page = 0
        self.diagnostic_revision = -1
        self.mode = "home"
        self.page = 0
        self.settings_page = 0
        self.actions = []
        self.press = None
        self.pressed_box = None
        self.last_xy = None
        self.banner = ""
        self.last_status = None
        self.has_frame = False
        self.pending_default = False
        self.last_frame_at = 0
        self.draw()

    def font(self, size):
        return ui_font(size + 2 if size >= 18 else size, 600 if size >= 18 else 400)

    def draw_brand(self, draw, xy, size):
        x, y = xy
        title_font = self.font(size)
        baseline = y + title_font.getbbox("HLauncher")[3]
        draw.text((x, baseline), "HLauncher", font=title_font, fill="white", anchor="ls")
        credit_x = x + draw.textlength("HLauncher", font=title_font) + 12
        draw.text((credit_x, baseline), "by Evan Horsley", font=ui_font(16 if size >= 28 else 14, 600),
                  fill="#b4b4b4", anchor="ls")

    def button(self, draw, box, label, action, color=None, size=19):
        if label in ('Home', 'Back'):
            from hlauncher_sdk.ui import draw_back_button
            box = (box[0], box[1], box[0]+118, box[3])
            draw_back_button(draw, box, color=TILE_COLORS[self.prefs.data["tile_color"]])
        else:
            button_surface(draw, box, color or TILE_COLORS[self.prefs.data["tile_color"]])
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
        self.diagnostics.stop()
        self.restore_hdmi_range()
        self.host.deactivate()
        self.mode = "home"
        self.press = None
        self.has_frame = False
        self.pending_default = False
        self.banner = message
        self.draw()
        self.event(state="launcher_home", message=message)

    def settings(self):
        self.diagnostics.stop()
        self.host.deactivate()
        self.mode = "settings"
        self.settings_page = 0
        self.banner = ""
        self.press = None
        self.draw()

    def plugin_settings(self):
        self.host.deactivate()
        self.mode = 'plugins_settings'
        self.press = None
        self.draw()

    def obd_settings(self):
        self.host.deactivate()
        self.obd.start()
        self.mode = 'obd_settings'
        self.press = None
        self.obd_page = 0
        self.draw()

    def obd_scan(self):
        self.obd.command('scan')
        self.obd_page = 0
        self.draw()

    def obd_connect(self, address):
        self.obd.command('connect', address=address)
        self.draw()

    def obd_disconnect(self):
        self.obd.command('disconnect')
        self.draw()

    def obd_devices_page(self, delta):
        self.obd_page = max(0, self.obd_page+delta)
        self.draw()

    def system_diagnostics(self):
        self.host.deactivate()
        self.mode = 'diagnostics'
        self.press = None
        self.diagnostic_page = 0
        self.diagnostic_revision = -1
        self.diagnostics.start()
        self.draw()

    def diagnostic_runtime(self):
        playback = self.audio.playback
        with playback.condition:
            streams = len(playback.streams)
            queued = sum(stream.queued for stream in playback.streams.values())
            dropped = sum(stream.dropped for stream in playback.streams.values())
        return dict(version=__version__, session=dict(self.host.session),
                    display=dict(width=self.fb.w,height=self.fb.h,
                                 backend='DRM' if getattr(self.fb,'kms',None) else 'Framebuffer'),
                    audio=dict(route='HDMI',streams=streams,queued_bytes=queued,
                               dropped_bytes=dropped,written_bytes=playback.written,failures=playback.failures),
                    plugins=[self.manifests[key].name for key in self.host.workers],
                    plugin_status={key:dict(status=worker.status,background=not worker.active,
                                           received_frames=worker.frames_received)
                                   for key,worker in self.host.workers.items()})

    def change_diagnostic_page(self):
        self.diagnostic_page = 1 - self.diagnostic_page
        self.draw()

    def menu_row(self, draw, box, title, detail, action):
        button_surface(draw,box,TILE_COLORS[self.prefs.data['tile_color']])
        x,y,right,bottom=box
        draw.text((x+16,y+9),title,font=self.font(20),fill='white')
        draw.text((x+16,y+37),detail,font=self.font(14),fill='#adbcc8')
        draw.text((right-25,(y+bottom)/2),'›',font=self.font(27),fill='#adbcc8',anchor='mm')
        self.actions.append((box,action))

    def tile_colors(self):
        self.host.deactivate()
        self.mode = 'tile_colors'
        self.press = None
        self.banner = ''
        self.draw()

    def set_tile_color(self, name):
        try:
            self.prefs.set_tile_color(name)
            self.banner = ''
        except OSError as exc:
            self.banner = 'Could not save tile color'
            self.event(state='settings_save_failed', error=str(exc))
        self.draw()

    def color_settings(self):
        self.restore_hdmi_range()
        self.host.deactivate()
        self.picture.refresh()
        self.picture_values = dict(self.picture.values)
        self.mode = 'colors'
        self.press = self.picture_drag = None
        self.banner = ''
        self.draw()

    def restore_hdmi_range(self):
        if self.hdmi_range_original is not None:
            from .hdmi_calibration import broadcast_rgb
            try:
                broadcast_rgb(self.fb.kms, self.hdmi_range_original)
                self.event(state='hdmi_range_restored', value=self.hdmi_range_original)
                self.hdmi_range_original = None
            except (OSError, RuntimeError) as exc:
                self.event(state='hdmi_range_failed', error=str(exc))

    def hdmi_calibration(self):
        from .hdmi_calibration import broadcast_rgb
        self.host.deactivate()
        self.mode = 'hdmi_test'
        self.banner = ''
        try:
            if self.hdmi_range_original is None:
                self.hdmi_range_original = broadcast_rgb(self.fb.kms)
            self.hdmi_range_label = ['Automatic', 'Full', 'Limited'][self.hdmi_range_original]
        except (OSError, RuntimeError) as exc:
            self.banner = str(exc)
        self.draw()

    def set_hdmi_range(self, value):
        from .hdmi_calibration import broadcast_rgb
        try:
            if self.hdmi_range_original is None:
                raise RuntimeError('Original HDMI range was not saved')
            broadcast_rgb(self.fb.kms, value)
            actual = broadcast_rgb(self.fb.kms)
            if actual != value:
                raise RuntimeError('HDMI range readback did not match')
            self.hdmi_range_label = ['Automatic', 'Full', 'Limited'][actual]
            self.banner = ''
            self.event(state='hdmi_range_test', value=actual)
        except (OSError, RuntimeError) as exc:
            self.banner = str(exc)
        self.draw()

    def save_picture(self):
        if not self.picture_dirty:
            return
        try:
            self.picture.save(self.picture_values)
            self.picture_dirty = False
            self.picture_saved = time.monotonic()
            self.event(state='carplay_picture_saved', **self.picture_values)
        except OSError as exc:
            self.banner = 'Could not save picture settings'
            self.event(state='settings_save_failed', error=str(exc))
            self.picture_saved = time.monotonic()

    def reset_picture(self):
        self.picture_values = dict(DEFAULTS)
        self.picture_dirty = True
        self.save_picture()
        self.draw()

    def color_touch(self, action, point):
        if action == 'down' and point:
            for key, box in self.picture_sliders:
                if box[0] <= point[0] <= box[2] and box[1] <= point[1] <= box[3]:
                    self.picture_drag = (key, box)
                    self.press = None
                    break
        if self.picture_drag:
            key, box = self.picture_drag
            if point:
                low, high = LIMITS[key]
                value = round(low + max(0,min(1,(point[0]-box[0])/(box[2]-box[0]))) * (high-low))
                if value != self.picture_values[key]:
                    self.picture_values[key] = value
                    self.picture_dirty = True
                    self.draw()
            if action in ('up', 'unused'):
                self.picture_drag = None
                self.save_picture()
            return True
        return False

    def open_plugin(self, plugin_id):
        if plugin_id == 'obd':self.obd.start()
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

    def toggle_background(self, plugin_id):
        manifest = self.manifests[plugin_id]
        try:
            self.prefs.set_background(manifest, not self.prefs.background_enabled(manifest))
            self.host.background_changed(plugin_id)
            self.banner = ''
        except (OSError, ValueError) as exc:
            self.banner = 'Could not save background setting'
            self.event(state='settings_save_failed', error=str(exc))
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

    def present_ui(self, image):
        # Brighten the existing control without changing its size or position.
        box = self.pressed_box if self.press is not None else None
        if box is not None and any(bounds == box for bounds, _ in self.actions):
            left, top, right, bottom = box
            tile = ImageEnhance.Brightness(image.crop(box)).enhance(1.28)
            image.paste(tile, (left, top))
            # A small local overlay keeps the glow inexpensive to render.
            pad = 6
            overlay = Image.new('RGBA', (right-left+pad*2+1, bottom-top+pad*2+1))
            bounds = (pad+1, pad+1, pad+right-left-1, pad+bottom-top-1)
            glow = ImageDraw.Draw(overlay)
            edge = border_color(TILE_COLORS[self.prefs.data['tile_color']], pressed=True)
            glow.rounded_rectangle(bounds, radius=13, outline=(*edge,160), width=3)
            overlay = overlay.filter(ImageFilter.GaussianBlur(2))
            ImageDraw.Draw(overlay).rounded_rectangle(
                bounds, radius=13, outline=(*edge,190), width=2)
            image.paste(overlay, (left-pad, top-pad), overlay)
        self.fb.image(dither_rgb565(image) if self.mode != "hdmi_test" else image)

    def draw(self):
        w, h = self.fb.w, self.fb.h
        tile_color = TILE_COLORS[self.prefs.data["tile_color"]]
        image = draw_background(w, h, tile_color) if self.mode != "hdmi_test" else Image.new("RGB", (w, h), "#080c14")
        d = ImageDraw.Draw(image)
        self.actions = []
        if self.mode == "home":
            self.draw_brand(d, (24, 16), 28)
            if self.banner:
                d.text((24, 55), self.banner[:66], font=self.font(15), fill="#ffbc75")
            entries = [
                (
                    m.name,
                    lambda pid=m.id: self.open_plugin(pid),
                    m.color,
                    m.id,
                )
                for m in sorted(self.enabled(), key=lambda m: m.id != 'carplay')
            ]
            pages = max(1, math.ceil(len(entries) / 5))
            self.page = min(self.page, pages - 1)
            top = 72
            bottom = h - (62 if pages > 1 else 12)
            tw = th = min((w - 72) // 3, (bottom - top - 12) // 2)
            left = (w - (3 * tw + 24)) // 2
            for i in range(6):
                col, row = i % 3, i // 3
                x = left + col * (tw + 12)
                y = top + row * (th + 12)
                box = (x, y, x + tw, y + th)
                at = self.page * 5 + i
                if i == 5:
                    entry = ('Settings', self.settings, tile_color, 'settings')
                elif at < len(entries):
                    entry = entries[at]
                else:
                    d.rounded_rectangle(box, radius=14, outline="#1d2838", width=1)
                    continue
                label, action, color, icon = entry
                glass_tile(image, box, tile_color)
                draw_icon(image, icon, (x + tw / 2, y + th * .40), round(tw * .40))
                label_size = 20
                while label_size > 14 and d.textlength(label[:18], font=self.font(label_size)) > tw - 32:
                    label_size -= 1
                d.text(
                    (x + tw / 2, y + th - 48), label[:18], font=self.font(label_size), fill="white", anchor="mt"
                )
                self.actions.append((box, action))
            if pages > 1:
                self.button(
                    d,
                    (w - 185, h - 52, w - 110, h - 12),
                    "Prev",
                    lambda: self.change_page(-1),
                    size=15,
                )
                self.button(
                    d,
                    (w - 100, h - 52, w - 24, h - 12),
                    "Next",
                    lambda: self.change_page(1),
                    size=15,
                )
                d.text(
                    (24, h - 44),
                    f"{self.page+1} / {pages}",
                    font=self.font(15),
                    fill="white",
                )
        elif self.mode == "settings":
            self.button(d, (16,14,110,56), 'Back', self.home)
            self.draw_brand(d, (150,20), 21)
            default=self.prefs.data['default_plugin']
            default_label=self.manifests[default].name if default in self.manifests and self.prefs.enabled(self.manifests[default]) else 'Launcher'
            rows=[('Plugins','Enable apps and adjust CarPlay picture',self.plugin_settings),
                  ('OBD Gauges','Connect a Bluetooth LE ELM327 dongle',self.obd_settings),
                  ('Tile color',self.prefs.data['tile_color'],self.tile_colors),
                  ('Start with',default_label,self.cycle_default),
                  ('System diagnostics','Connections, hardware and reports',self.system_diagnostics)]
            for i,(title,detail,action) in enumerate(rows):
                y=77+i*69
                self.menu_row(d,(24,y,w-24,y+61),title,detail,action)
            d.text((24,h-33),'HLauncher '+__version__,font=self.font(14),fill='#a3adb8')
            if self.banner:d.text((w-24,h-33),self.banner[:50],font=self.font(14),fill='#ffbc75',anchor='rt')
        elif self.mode == 'plugins_settings':
            self.button(d,(16,14,110,56),'Back',self.settings)
            d.text((150,20),'Plugins',font=self.font(27),fill='white')
            entries = sorted(self.manifests.values(), key=lambda m: m.id != 'carplay')
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
                if m.id == 'obd':
                    self.button(d, (w-365,y,w-175,y+48), 'Connect dongle',self.obd_settings,size=17)
                if m.id == 'carplay':
                    self.button(d, (w-365, y, w-175, y+48), 'CarPlay color',
                                self.color_settings, size=17)
                if m.keep_alive and m.id not in ("carplay", "android-auto"):
                    background = self.prefs.background_enabled(m)
                    self.button(d, (w-335, y, w-175, y+48),
                                'Background On' if background else 'Background Off',
                                lambda pid=m.id: self.toggle_background(pid),
                                color='#246b48' if background else '#424955', size=16)
                self.button(
                    d,
                    (w - 165, y, w - 24, y + 48),
                    "Enabled" if on else "Disabled",
                    lambda pid=m.id: self.toggle_plugin(pid),
                    color="#246b48" if on else "#424955",
                    size=18,
                )
            if pages > 1:
                self.button(
                    d,
                    (w - 185, h - 76, w - 110, h - 34),
                    "Prev",
                    lambda: self.change_settings_page(-1),
                    size=15,
                )
                self.button(
                    d,
                    (w - 100, h - 76, w - 24, h - 34),
                    "Next",
                    lambda: self.change_settings_page(1),
                    size=15,
                )
            if self.banner:d.text((24,h-28),self.banner[:60],font=self.font(14),fill='#ffbc75')
        elif self.mode == 'obd_settings':
            self.button(d,(16,14,110,56),'Back',self.settings)
            d.text((150,20),'OBD Gauges',font=self.font(27),fill='white')
            state = self.obd.state
            self.obd_revision = self.obd.revision
            message = state.get('message','No OBD dongle connected')
            # Wrap long adapter errors so they stay readable on this screen.
            import textwrap
            for i,line in enumerate(textwrap.wrap(message,64)[:2]):
                d.text((24,76+i*23),line,font=self.font(17),fill='white')
            self.button(d,(24,132,240,178),'Scan',self.obd_scan,size=18)
            self.button(d,(260,132,450,178),'Disconnect',self.obd_disconnect,size=18)
            devices=state.get('devices',[])
            pages=max(1,math.ceil(len(devices)/3))
            self.obd_page=min(self.obd_page,pages-1)
            for i,row in enumerate(devices[self.obd_page*3:self.obd_page*3+3]):
                y=194+i*61
                name=row.get('name','BLE device')[:35]
                address=row['address']
                self.menu_row(d,(24,y,w-24,y+58),name,address,
                              lambda address=address:self.obd_connect(address))
            if not devices:
                d.text((24,205),'Scan nearby BLE devices, then select your dongle.',font=self.font(18),fill='#c0c8d0')
            if pages>1:
                self.button(d,(w-190,h-68,w-110,h-24),'Prev',lambda:self.obd_devices_page(-1),size=16)
                self.button(d,(w-100,h-68,w-24,h-24),'Next',lambda:self.obd_devices_page(1),size=16)
            d.text((24,h-25),'BLE ELM327 · unsupported sensors show —',font=self.font(14),fill='#adbcc8')
        elif self.mode == 'diagnostics':
            self.button(d,(16,14,110,56),'Back',self.settings)
            d.text((150,20),'System diagnostics',font=self.font(25),fill='white')
            system,revision,report_status=self.diagnostics.snapshot()
            self.diagnostic_revision=revision
            runtime=self.diagnostic_runtime()
            def capacity(value):return f'{value/1024**3:.1f} GB' if value is not None else 'Unavailable'
            if self.diagnostic_page == 0:
                session=runtime['session'];display=runtime['display'];audio=runtime['audio']
                rows=[('HondaLink control','Connected' if session.get('connected') else 'Disconnected'),
                      ('Handshake','Verified' if session.get('authenticated') else 'Not verified'),
                      ('Display',f"{display['width']} × {display['height']} · {display['backend']}"),
                      ('USB dongle',str(len(system['dongles']))+' detected' if 'dongles' in system else 'Checking…'),
                      ('Audio',f"HDMI · {audio['streams']} stream(s)"),
                      ('Running apps',', '.join(runtime['plugins']) or 'None')]
            else:
                temp=system.get('temperature_c');uptime=system.get('uptime_seconds')
                total=system.get('memory_total');available=system.get('memory_available')
                memory=f'{(total-available)/1024**2:.0f} / {total/1024**2:.0f} MB used' if total is not None and available is not None else 'Unavailable'
                rows=[('Hardware',system.get('model','Checking…')),
                      ('CPU temperature',f'{temp:.1f} °C' if temp is not None else 'Unavailable'),
                      ('Power / throttling',power_status(system.get('power_flags'))),
                      ('Memory',memory),
                      ('Storage',capacity(system.get('storage_free'))+' free'),
                      ('Uptime',f'{int(uptime)//3600}h {int(uptime)%3600//60}m' if uptime is not None else 'Unavailable')]
            for i,(label,value) in enumerate(rows):
                y=91+i*45
                d.text((24,y),label,font=self.font(16),fill='#a3b2c0')
                value_size=17
                while value_size>12 and d.textlength(value,font=self.font(value_size))>w-250:value_size-=1
                d.text((225,y),value,font=self.font(value_size),fill='white')
                d.line((24,y+33,w-24,y+33),fill='#26313d')
            self.button(d,(24,h-77,222,h-32),'Save report',lambda:self.diagnostics.save_report(self.diagnostic_runtime()),size=17)
            self.button(d,(w-225,h-77,w-24,h-32),'System  ›' if self.diagnostic_page==0 else '‹  Connections',self.change_diagnostic_page,size=17)
            if report_status:d.text((24,h-23),report_status,font=self.font(13),fill='#a3b2c0')
        elif self.mode == 'tile_colors':
            self.button(d, (16,14,110,56), 'Back', self.settings)
            d.text((150,20), 'Tile color', font=self.font(27), fill='white')
            cell_w = (w - 72) // 3
            cell_h = (h - 112) // 2
            for i, (name, color) in enumerate(TILE_COLORS.items()):
                x = 24 + (i % 3) * (cell_w + 12)
                y = 82 + (i // 3) * (cell_h + 12)
                box = (x, y, x + cell_w, y + cell_h)
                glass_tile(image, box, color)
                draw_icon(image, 'obd', (x + cell_w/2, y + cell_h*.36), 62)
                text = name + ('  ✓' if self.prefs.data['tile_color'] == name else '')
                d.text((x+cell_w/2,y+cell_h-40),text,font=self.font(19),fill='white',anchor='mt')
                self.actions.append((box, lambda value=name: self.set_tile_color(value)))
            if self.banner:
                d.text((24,h-26),self.banner,font=self.font(14),fill='#ffbc75')
        elif self.mode == 'hdmi_test':
            from .hdmi_calibration import pattern
            self.button(d, (16,14,110,56), 'Back', self.color_settings)
            d.text((150,18), 'HDMI range: ' + self.hdmi_range_label, font=self.font(25), fill='white')
            pattern(d, w, self.font)
            for i, label in enumerate(('Auto', 'Full', 'Limited')):
                x = 24 + i * ((w-48)//3)
                self.button(d, (x,380,x+(w-48)//3-8,425), label,
                            lambda value=i: self.set_hdmi_range(value))
            if self.banner:
                d.text((24,440),self.banner[:75],font=self.font(13),fill='#ffbc75')
            self.present_ui(image)
            return
        elif self.mode == 'colors':
            self.button(d, (16,14,110,56), 'Back', self.plugin_settings)
            d.text((150,18), 'CarPlay color', font=self.font(27), fill='white')
            d.text((24,75), 'Adjust CarPlay only. 100% / 100% / 0 is the original picture.', font=self.font(16), fill='#b4b4b4')
            self.picture_sliders = []
            for i, key in enumerate(DEFAULTS):
                y = 114 + i*76
                value = self.picture_values[key]
                suffix = f'{value:+d}' if key == 'brightness' else f'{value}%'
                d.text((24,y-6), key.capitalize(), font=self.font(20), fill='white')
                d.text((w-90,y-6), suffix, font=self.font(18), fill='#98bed4')
                box=(215,y+5,w-115,y+37)
                low,high=LIMITS[key]
                x=box[0]+round((value-low)/(high-low)*(box[2]-box[0]))
                cy=y+21
                d.line((box[0],cy,box[2],cy), fill='#424955', width=8)
                d.line((box[0],cy,x,cy), fill='#397bb8', width=8)
                default_x=box[0]+round((DEFAULTS[key]-low)/(high-low)*(box[2]-box[0]))
                d.line((default_x,cy-9,default_x,cy+9), fill='#aaaaaa', width=2)
                d.ellipse((x-12,cy-12,x+12,cy+12), fill='white')
                self.picture_sliders.append((key,(box[0],y-3,box[2],y+45)))
            self.button(d,(24,h-135,190,h-88),'Reset',self.reset_picture)
            if 'carplay' in self.manifests and self.prefs.enabled(self.manifests['carplay']):
                self.button(d,(210,h-135,w-24,h-88),'Preview CarPlay',lambda:self.open_plugin('carplay'))
            self.button(d,(24,h-80,w-24,h-45),'HDMI test pattern',self.hdmi_calibration,size=15)
            if self.banner:
                d.text((24,h-78),self.banner,font=self.font(15),fill='#ffbc75')
        else:
            manifest = self.manifests.get(self.host.active)
            self.button(d, (16, 14, 110, 56), "Home", self.home)
            color = TILE_COLORS[self.prefs.data['tile_color']]
            glass_tile(image, (24,88,w-24,h-30), color)
            draw_icon(image, manifest.id if manifest else '', (w/2,168), 82)
            if manifest:
                d.text((w/2,226), manifest.name, font=self.font(25), fill='white', anchor='mt')
            text = self.host.status() or "Starting plugin..."
            words = text.split()
            lines = [""]
            for word in words:
                if len(lines[-1]) + len(word) > 45:
                    lines.append("")
                lines[-1] += word + " "
            for i, line in enumerate(lines[:4]):
                d.text((w/2,286+i*29), line.strip(), font=self.font(18), fill='#d2dce5', anchor='mt')
        self.present_ui(image)

    def change_page(self, delta):
        count = math.ceil(len(self.enabled()) / 5)
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
        if self.mode == 'colors' and self.color_touch(action, point or self.last_xy):
            return
        # Plugins own their full viewport after their first frame. Home is provided
        # by the app's own host-return action (the Honda icon in CarPlay).
        if self.mode == "plugin" and self.has_frame:
            self.host.touch(touch)
            return
        if action == "down":
            self.press = point
            self.pressed_box = next((box for box, _ in self.actions if point and
                box[0] <= point[0] <= box[2] and box[1] <= point[1] <= box[3]), None)
            if self.pressed_box is not None:
                self.draw()
        elif action == "move" and self.pressed_box is not None:
            box = self.pressed_box
            if point and not (box[0] <= point[0] <= box[2] and box[1] <= point[1] <= box[3]):
                self.press = self.pressed_box = None
                self.draw()
        elif action in ("up", "unused"):
            box = self.pressed_box if self.press is not None else None
            callback = next((fn for bounds, fn in self.actions if bounds == box), None)
            self.press = self.pressed_box = None
            if callback is not None:
                callback()
                return
            if box is not None:
                self.draw()
        if self.mode == "plugin":
            self.host.touch(touch)

    def session_changed(self, **values):
        self.host.session_changed(**values)
        self.obd.tick(self.host.session)
        if values.get("connected") is False:
            self.home()

    def tick(self):
        self.host.tick()
        self.obd.tick(self.host.session)
        now = time.monotonic()
        if self.mode == "obd_settings" and self.obd.revision != self.obd_revision:self.draw()
        if self.mode == 'diagnostics':
            _, revision, _ = self.diagnostics.snapshot()
            if revision != self.diagnostic_revision:self.draw()
        if self.mode == 'colors':
            if self.picture_dirty and now-self.picture_saved > .1:
                self.save_picture()
            elif not self.picture_dirty and self.picture_drag is None and now-self.picture_checked > .2:
                self.picture_checked = now
                if self.picture.refresh():
                    self.picture_values = dict(self.picture.values)
                    self.draw()
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
        self.diagnostics.stop()
        self.obd.close()
        self.host.close()
        self.fb.close()
