"""Built-in launcher/settings UI and the sole owner of the radio display."""

import math
import time
import subprocess
from sdk.hlauncher_sdk.fonts import font as ui_font
from . import __version__
from .debug_tools import InputMonitor, ToneTest
from . import config
from .diagnostics import Diagnostics
from .obd import ObdManager
from .audio_settings import AudioSettings, EQ_BANDS
from .audio import AudioBroker
from .catalog import discover
from .config import Preferences
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
        independent_audio=False,
        protocol_diagnostics=None,
    ):
        self.event = event
        self.fb = framebuffer or Framebuffer(event)
        self.fb.open()
        self.prefs = preferences or Preferences()
        self.audio_settings = AudioSettings(self.prefs.path.with_name('audio.json'))
        self.audio_notice = ''
        self.audio_checked = 0
        self.picture = PictureSettings(self.prefs.path.with_name('picture.json'))
        self.picture_values = dict(self.picture.values)
        self.apply_picture()
        self.picture_drag = None
        self.picture_dirty = False
        self.picture_saved = self.picture_checked = 0
        self.picture_sliders = []
        self.hdmi_range_original = None
        self.hdmi_range_label = "Automatic"
        from .hdmi_calibration import HDMISettings
        self.hdmi_settings=HDMISettings(self.prefs.path.with_name('hdmi-output.json'))
        self.hdmi_range_selected=None
        self.hdmi_output={}
        self.hdmi_test_exact=True
        self.hdmi_test_inset=False
        self.manifests = discover(event) if manifests is None else manifests
        self.audio = AudioBroker(event, independent=independent_audio)
        self.host = PluginHost(
            self.manifests, self.fb.w, self.fb.h, event, self.home, self.audio,
            background_allowed=self.prefs.background_enabled, state_dir=self.prefs.path.parent,
        )
        self.diagnostics = Diagnostics()
        from .protocol_diagnostics import ProtocolDiagnostics
        self.protocols = protocol_diagnostics or ProtocolDiagnostics(self.prefs.path.parent/'protocol-captures')
        self.protocol_page = 0
        self.vehicle_data_tab = 0
        self.vehicle_signal_id = 44
        self.protocol_marker_index = 0
        self.protocol_redraw = 0
        from .voice_audio import VoiceAudio
        self.voice_audio=VoiceAudio(self.prefs.path.with_name('voice-audio.json'))
        self.inputs = InputMonitor(event, config.RADIO_ADDRESS)
        self.inputs.start()
        self.tone_test = ToneTest(self.audio.playback)
        self.debug_touch = {}
        self.debug_redraw = 0
        self.obd = ObdManager(event)
        self.obd_page = 0
        self.obd_revision = -1
        self.diagnostic_page = 0
        self.diagnostic_revision = -1
        self.storage_info = dict(protected=False, available=False, message='Checking storage layout')
        self.storage_checked = 0
        self.setup_list_page = 0
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

    def setup_page(self, restart=False):
        from .onboarding import Onboarding
        self.tone_test.stop()
        self.host.deactivate()
        self.setup_can_exit = bool(self.prefs.data['setup_complete'] and self.mode in ('settings','system_settings'))
        self.wizard = Onboarding(self.prefs, self.manifests)
        if restart:
            if self.prefs.data['setup_complete']:self.wizard.save(setup_step=0)
            else:self.wizard.restart()
        self.mode = 'onboarding'
        self.setup_list_page = 0
        self.press = None
        self.draw()

    def exit_setup(self):
        if getattr(self,'setup_can_exit',False):
            self.system_settings()

    def setup_action(self, function, *args):
        try:
            function(*args)
            self.banner = ''
        except (ValueError, OSError) as exc:
            self.banner = str(exc)[:70]
        self.draw()

    def setup_next(self, delta):
        self.setup_list_page = 0
        self.setup_action(self.wizard.move, delta)

    def setup_finish(self, protect=False):
        try:
            self.wizard.finish()
        except (OSError, ValueError) as exc:
            self.banner = str(exc)[:70]; self.draw(); return
        for plugin_id, manifest in self.manifests.items():
            if not self.prefs.enabled(manifest): self.host.stop(plugin_id)
        self.event(state='setup_completed')
        if protect:
            self.storage_confirm(True)
        else:
            self.home('Setup complete. Storage protection is available in System settings.')
            self.pending_default = not getattr(self,'setup_can_exit',False)

    def system_settings(self):
        self.tone_test.stop()
        self.diagnostics.stop()
        self.host.deactivate()
        self.mode = 'system_settings'
        self.press = None
        self.banner = ''
        self.draw()

    def appearance_settings(self):
        self.host.deactivate()
        self.mode='appearance_settings'
        self.press=None
        self.banner=''
        self.draw()

    def startup_settings(self):
        self.host.deactivate()
        self.mode='startup_settings'
        self.press=None
        self.banner=''
        self.draw()

    def updates_page(self):
        self.host.deactivate()
        self.mode = 'updates'
        self.press = None
        self.banner = ''
        self.draw()

    def release_notes_page(self):
        from .update_client import status
        self.release_notes_info = status(self.prefs.path.parent)
        self.update_notes_index = 0
        self.mode = 'update_notes'
        self.press = None
        self.draw()

    def release_notes_move(self, delta):
        self.update_notes_index = max(0,self.update_notes_index+delta)
        self.press = None
        self.draw()

    def install_update(self):
        self.updates_page()
        self.update_request('install')

    def update_request(self, operation):
        from .update_client import request
        try:
            request(operation,self.prefs.path.parent)
            self.banner = 'Requested'
        except FileExistsError:self.banner = 'An update operation is already queued'
        except (OSError,ValueError):self.banner = 'Could not request the update operation'
        self.draw()

    def toggle_clock(self):
        before=self.prefs.data['show_clock']
        self.prefs.data['show_clock']=not before
        try:self.prefs.save()
        except OSError:
            self.prefs.data['show_clock']=before
            raise
        self.draw()

    def toggle_debug(self):
        before = self.prefs.data['debug_mode']
        self.prefs.data['debug_mode'] = not before
        try: self.prefs.save()
        except OSError:
            self.prefs.data['debug_mode'] = before
            raise
        if not self.prefs.data['debug_mode']:
            self.protocols.stop()
        self.draw()

    def recovery_page(self):
        self.recovery_return = self.setup_resume if self.mode=='onboarding' else self.updates_page if self.mode=='updates' else self.system_settings
        self.host.deactivate()
        self.mode = 'recovery_settings'
        self.press = None
        self.draw()

    def setup_resume(self):
        self.mode='onboarding'
        self.press=None
        self.banner=''
        self.draw()

    def network_resume(self):
        self.mode='recovery_settings'
        self.press=None
        self.banner=''
        self.draw()

    def ssh_settings(self):
        self.ssh_return=self.hotspot_page if self.mode=='hotspot_settings' else self.recovery_page
        self.host.deactivate()
        self.mode='ssh_settings';self.press=None;self.banner='';self.draw()

    def set_ssh(self,enabled):
        from .recovery import request_job
        try:
            request_job('ssh',enabled=enabled)
            self.banner=''
        except FileExistsError:self.banner='A setup operation is already queued'
        except (OSError,ValueError):self.banner='Could not request the SSH setting'
        self.draw()

    def hotspot_page(self):
        self.mode='hotspot_settings'
        self.press=None
        self.banner=''
        self.draw()

    def maintenance(self, operation):
        from .recovery import request_job
        try:
            request_job(operation)
            self.banner = ''
        except FileExistsError: self.banner = 'A setup operation is already queued.'
        except (OSError, ValueError): self.banner = 'Could not request the setup operation.'
        self.draw()

    def storage_confirm(self, enabled):
        self.host.deactivate()
        self.storage_target = enabled
        self.mode = 'storage_confirm'
        self.press = None
        self.draw()

    def setup_more(self, total):
        self.setup_list_page = (self.setup_list_page+1)%total
        self.draw()

    def enabled(self):
        return [m for m in self.manifests.values() if self.prefs.enabled(m)]

    def launch(self, app_id):
        if app_id not in (
            "com.honda.hondalink.connect",
            "com.honda.hondalink.launcher",
        ):
            return False
        if not self.prefs.data['setup_complete']:
            self.setup_page()
        else:
            self.home()
            self.pending_default = True
        return True

    def home(self, message=""):
        if hasattr(self, 'wizard') and not self.prefs.data['setup_complete']:
            self.setup_page()
            return
        self.diagnostics.stop()
        self.tone_test.stop()
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

    def audio_page(self):
        self.audio_return=self.settings if self.mode=='settings' else self.home
        self.tone_test.stop()
        self.host.deactivate()
        self.audio_settings.refresh()
        self.mode = 'audio_settings'
        self.press = None
        self.audio_notice = ''
        self.draw()

    def change_audio(self, **changes):
        try:
            self.audio_settings.save(**changes)
            self.audio.playback.settings = self.audio_settings
            self.audio_notice = 'Saved'
        except (OSError, ValueError, RuntimeError) as exc:
            self.audio_notice = str(exc)[:72]
        self.draw()

    def adjust_eq(self, key, delta):
        if key in EQ_BANDS:
            bands = dict(self.audio_settings.values['bands'])
            bands[key] = max(-12, min(12, bands[key]+delta))
            self.change_audio(bands=bands)
        else:
            self.change_audio(**{key: max(-12, min(12, self.audio_settings.values[key]+delta))})

    def plugin_settings(self):
        self.host.deactivate()
        self.mode = 'plugins_settings'
        self.press = None
        self.draw()

    def plugin_detail(self, plugin_id=None):
        if plugin_id is not None:self.settings_plugin_id=plugin_id
        if getattr(self,'settings_plugin_id',None) not in self.manifests:
            self.plugin_settings()
            return
        self.host.deactivate()
        self.mode='plugin_detail'
        self.press=None
        self.banner=''
        self.draw()

    def adapter_branding_page(self):
        self.host.deactivate()
        self.mode='adapter_branding'
        self.press=None
        self.banner=''
        self.draw()

    def apply_adapter_branding(self):
        manifest=self.manifests.get('carplay')
        if not manifest or not self.prefs.enabled(manifest):
            self.banner='Enable the CarPlay plugin first'
        else:
            try:
                self.host.request_branding()
                self.banner=''
            except (OSError,ValueError) as exc:self.banner=str(exc)[:100]
        self.draw()

    def obd_settings(self):
        self.obd_return=self.plugin_detail if self.mode=='plugin_detail' else self.settings if self.mode=='settings' else self.home
        self.host.deactivate()
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
        if not self.prefs.data['debug_mode']:
            self.system_settings()
            return
        self.tone_test.stop()
        self.host.deactivate()
        self.mode = 'diagnostics'
        self.press = None
        self.diagnostic_page = 0
        self.diagnostic_revision = -1
        self.diagnostics.start()
        self.draw()

    def debug_tools(self, page='menu'):
        if not self.prefs.data['debug_mode']: return
        self.tone_test.stop()
        self.host.deactivate()
        self.mode = 'debug_'+page
        self.press = self.pressed_box = None
        self.debug_touch = {}
        self.draw()

    def protocol_tests(self):
        if not self.prefs.data['debug_mode']: return
        self.tone_test.stop()
        self.host.deactivate()
        self.mode = 'protocol_tests'
        self.press = self.pressed_box = None
        self.draw()

    def protocol_tab(self, page):
        self.protocol_page = page
        self.draw()

    def vehicle_tab(self, tab):
        self.vehicle_data_tab = tab
        self.draw()

    def vehicle_select(self, api_id):
        self.vehicle_signal_id = max(1,min(168,api_id))
        self.vehicle_data_tab = 1
        self.draw()

    def toggle_protocol_capture(self):
        if not self.prefs.data['debug_mode']: return
        if self.protocols.snapshot()['recording']:self.protocols.stop()
        else:self.protocols.start()
        self.draw()

    def mark_protocol_step(self):
        labels = ('Connection test','Next / previous test','Siri test','Incoming call test',
                  'Outgoing call test','Call ended','Vehicle controls test','Test complete')
        self.protocols.marker(labels[self.protocol_marker_index % len(labels)])
        self.protocol_marker_index += 1
        self.draw()

    def toggle_voice_output(self):
        try:
            self.voice_audio.save('hdmi' if self.voice_audio.output=='sco' else 'sco')
            self.event(state='projection_voice_output',output=self.voice_audio.output)
            self.protocols.marker('Voice output: '+self.voice_audio.output.upper())
        except OSError as exc:self.event(state='projection_voice_output_error',error=str(exc))
        self.draw()

    def shutdown_page(self):
        self.tone_test.stop()
        self.diagnostics.stop()
        self.shutdown_return = self.system_diagnostics if self.mode in ('diagnostics','protocol_tests') or self.mode.startswith('debug_') else self.system_settings
        self.mode = 'shutdown_confirm'
        self.press = self.pressed_box = None
        self.banner = ''
        self.draw()

    def shutdown_pi(self):
        self.tone_test.stop()
        self.mode = 'shutdown_pending'
        self.banner = ''
        self.draw()
        try:
            subprocess.run(['systemctl','poweroff','--no-block'], check=True,
                           capture_output=True, text=True, timeout=3)
            self.event(state='system_poweroff_requested')
        except (OSError, subprocess.SubprocessError) as exc:
            self.mode = 'shutdown_confirm'
            self.banner = 'Shutdown failed; Pi is still running.'
            self.event(state='system_poweroff_failed', error=str(exc))
            self.draw()

    def diagnostic_runtime(self):
        playback = self.audio.playback
        with playback.condition:
            streams = len(playback.streams)
            queued = sum(stream.queued for stream in playback.streams.values())
            dropped = sum(stream.dropped for stream in playback.streams.values())
            levels={str(key):dict(source_peak=getattr(stream,'source_peak',0),
                source_full_scale_samples=getattr(stream,'source_full_scale_samples',0),
                converted_peak=getattr(stream,'converted_peak',0)) for key,stream in playback.streams.items()}
        return dict(inputs=dict(status=self.inputs.status, volume=self.inputs.volume_status, transports=dict(self.inputs.control_status), buttons=self.inputs.buttons, results=dict(getattr(self.host,'button_results',{})), recent=list(self.inputs.history)), version=__version__, session=dict(self.host.session),
                    display=dict(width=self.fb.w,height=self.fb.h,
                                 backend='DRM' if getattr(self.fb,'kms',None) else 'Framebuffer'),
                    audio=dict(route=playback.route,device=playback.device,pipewire=playback.settings.values['pipewire'],
                               rate=48000,channels=2,processing_format='float32',hdmi_requested_format='S32_LE',
                               resampler='libsoxr VHQ 28-bit linear phase',streams=streams,queued_bytes=queued,
                               dropped_bytes=dropped,written_bytes=playback.written,failures=playback.failures,
                               peak=getattr(playback,'peak',0),clip_samples=getattr(playback,'clip_samples',0),stream_levels=levels),
                    protocols=self.protocols.snapshot(),
                    plugins=[self.manifests[key].name for key in self.host.workers],
                    plugin_status={key:dict(status=worker.status,background=not worker.active,
                                           received_frames=worker.frames_received)
                                   for key,worker in self.host.workers.items()})

    def diagnostic_tab(self, index):
        self.diagnostic_page=index
        self.press=None
        self.draw()

    def change_diagnostic_page(self):
        self.diagnostic_page = 1 - self.diagnostic_page
        self.draw()

    def tile_colors(self):
        self.host.deactivate()
        self.mode = 'tile_colors'
        self.press = None
        self.banner = ''
        self.draw()

    def custom_color(self):
        from .ui.color_picker import Picker
        self.custom_color_return=self.setup_resume if self.mode=='onboarding' else self.tile_colors
        self.color_picker=Picker(self.prefs.data['custom_color'])
        self.host.deactivate()
        self.mode='custom_color'
        self.press=self.pressed_box=None
        self.banner=''
        self.draw()

    def cancel_custom_color(self):
        self.custom_color_return()

    def save_custom_color(self):
        try:self.prefs.set_tile_color(self.color_picker.hex)
        except (OSError,ValueError):
            self.banner='Could not save custom color'
            self.draw()
            return
        self.custom_color_return()

    def picker_key(self, key):
        self.color_picker.key(key)
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
        self.apply_picture()
        self.mode = 'colors'
        self.press = self.picture_drag = None
        self.banner = ''
        self.draw()

    def restore_hdmi_range(self):
        if self.hdmi_range_original is not None:
            from .hdmi_calibration import broadcast_rgb
            try:
                broadcast_rgb(getattr(self.fb,'kms',None), self.hdmi_range_original)
                self.event(state='hdmi_range_restored', value=self.hdmi_range_original)
                self.hdmi_range_original = None
            except (OSError, RuntimeError) as exc:
                self.event(state='hdmi_range_failed', error=str(exc))

    def capture_hdmi_status(self,error=''):
        from .hdmi_calibration import output_status
        from .setup_state import atomic_json
        try:
            self.hdmi_output=output_status(getattr(self.fb,'kms',None))
            self.hdmi_output['test_bits']=32 if self.hdmi_test_exact and getattr(self.fb,'kms',None) is not None else 16
            self.hdmi_output.update(error=error,saved_range=self.hdmi_settings.value,
                                    preview_range=self.hdmi_range_selected,
                                    requested_buffer='XRGB8888' if self.hdmi_test_exact else 'RGB565',
                                    test_levels='inset' if self.hdmi_test_inset else 'standard')
            atomic_json(self.prefs.path.with_name('hdmi-diagnostics.json'),self.hdmi_output)
            self.event(state='hdmi_output_status',**self.hdmi_output)
        except (OSError,RuntimeError) as exc:self.event(state='hdmi_diagnostics_failed',error=str(exc))

    def hdmi_calibration(self):
        from .hdmi_calibration import broadcast_rgb,RANGES
        self.host.deactivate()
        self.mode='hdmi_test';self.banner=''
        self.hdmi_test_exact=True;self.hdmi_test_inset=False
        try:
            if self.hdmi_range_original is None:
                self.hdmi_range_original=broadcast_rgb(getattr(self.fb,'kms',None))
            self.hdmi_range_selected=broadcast_rgb(getattr(self.fb,'kms',None))
            self.hdmi_range_label=RANGES[self.hdmi_range_selected]
        except (OSError,RuntimeError) as exc:
            self.hdmi_range_selected=None;self.banner=str(exc)
        self.capture_hdmi_status(self.banner)
        self.draw()

    def toggle_hdmi_test(self,control):
        # Diagnostic source changes only: never saved or applied to video/UI.
        if control=='buffer':self.hdmi_test_exact=not self.hdmi_test_exact
        elif control=='levels':self.hdmi_test_inset=not self.hdmi_test_inset
        else:raise ValueError('Unknown HDMI test control')
        self.capture_hdmi_status()
        self.draw()

    def set_hdmi_range(self, value):
        from .hdmi_calibration import broadcast_rgb,RANGES
        error=''
        try:
            if self.hdmi_range_original is None:raise RuntimeError('HDMI range control is unavailable')
            actual=broadcast_rgb(getattr(self.fb,'kms',None),value)
            self.hdmi_range_selected=actual;self.hdmi_range_label=RANGES[actual]
            self.banner='Preview only · Save to keep this range'
            self.event(state='hdmi_range_test',value=actual)
        except (OSError,RuntimeError) as exc:self.banner=error=str(exc)
        self.capture_hdmi_status(error)
        self.draw()

    def save_hdmi_range(self):
        from .hdmi_calibration import broadcast_rgb
        try:
            if self.hdmi_range_selected is None:raise RuntimeError('Choose an available HDMI range first')
            actual=broadcast_rgb(getattr(self.fb,'kms',None))
            if actual!=self.hdmi_range_selected:raise RuntimeError('HDMI range changed; select it again')
            self.hdmi_settings.save(actual)
            self.hdmi_range_original=actual
            self.capture_hdmi_status()
            self.color_settings()
            self.banner='HDMI range saved';self.draw()
        except (OSError,RuntimeError,ValueError) as exc:self.banner=str(exc);self.draw()

    def apply_picture(self):
        if hasattr(self.fb, 'set_picture'):
            self.fb.set_picture(self.picture_values)

    def save_picture(self):
        if not self.picture_dirty:
            return
        try:
            self.picture.save(self.picture_values)
            self.picture_dirty = False
            self.picture_saved = time.monotonic()
            self.event(state='display_picture_saved', **self.picture_values)
        except OSError as exc:
            self.banner = 'Could not save picture settings'
            self.event(state='settings_save_failed', error=str(exc))
            self.picture_saved = time.monotonic()

    def reset_picture(self):
        self.picture_values = dict(DEFAULTS)
        self.apply_picture()
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
                    self.apply_picture()
                    self.picture_dirty = True
                    self.draw()
            if action in ('up', 'unused'):
                self.picture_drag = None
                self.save_picture()
            return True
        return False

    def open_plugin(self, plugin_id):
        if plugin_id == 'obd':
            self.obd.close()
            self.obd.enabled=False
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

    def draw(self):
        self.scroll_view=None
        if self.mode == "home":
            from .ui.home import draw_launcher
            draw_launcher(self)
            return
        if self.mode == "settings":
            from .ui.settings import draw_launcher
            draw_launcher(self)
            return
        if self.mode == "update_notes":
            from .ui.release_notes import draw_launcher
            draw_launcher(self)
            return
        if self.mode == "updates":
            from .ui.updates import draw_launcher
            draw_launcher(self)
            return
        if self.mode == "onboarding":
            from .ui.onboarding import draw_launcher
            draw_launcher(self)
            return
        if self.mode in ("audio_settings", "obd_settings"):
            from .ui import audio, obd
            (audio if self.mode == "audio_settings" else obd).draw_launcher(self)
            return
        if self.mode == "plugin" and self.host.active in ('carplay','android-auto'):
            if not self.has_frame:
                from .ui.projection import draw_launcher
                draw_launcher(self)
            return
        from .ui import pages,diagnostics
        if self.mode=='custom_color':
            from .ui.color_picker import draw_launcher
            draw_launcher(self)
        elif self.mode in pages.PAGES:pages.PAGES[self.mode](self)
        elif self.mode=='diagnostics':diagnostics.system(self)
        elif self.mode=='protocol_tests':diagnostics.protocols(self)
        elif self.mode.startswith('debug_'):diagnostics.hardware(self)
        elif self.mode=='plugin' and not self.has_frame:pages.waiting(self)

    def input_tab(self, index):
        self.debug_input_page=index
        self.press=None
        self.draw()

    def test_radio_button(self, name):
        self.inputs.offer(name,'trigger','screen')

    def change_page(self, delta):
        count = math.ceil(len(self.enabled()) / 4)
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
        from .ui.scroll_list import touch as scroll_touch
        if scroll_touch(self,action,point or self.last_xy):return
        if self.mode=='custom_color':
            from .ui.color_picker import touch
            if touch(self,action,point or self.last_xy):return
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
        if 'connected' in values:
            self.inputs.steering_mode=None
            self.inputs.control_epochs['hondalink-iap'] += 1
        if values.get("connected") is False:
            self.home()

    def tick(self):
        waiting_projection = (self.mode == "plugin" and self.host.active in ('carplay','android-auto')
                              and not self.has_frame)
        if (self.mode not in ("plugin","shutdown_pending") or waiting_projection) and time.strftime('%Y-%m-%d %H:%M') != getattr(self, 'home_clock', None):
            self.draw()
        # Storage inspection runs off the renderer thread and never delays Bluetooth.
        if time.monotonic()-self.storage_checked > 5:
            self.storage_checked = time.monotonic()
            import threading
            def inspect_storage():
                from .storage import status
                self.storage_info = status()
            threading.Thread(target=inspect_storage,daemon=True).start()
        if self.mode in ('onboarding','system_settings','recovery_settings','hotspot_settings','storage_confirm','updates','update_notes','adapter_branding','ssh_settings'):
            if time.monotonic()-getattr(self,'setup_redraw',0)>1:
                self.setup_redraw=time.monotonic()
                if self.mode=='updates' and self.banner=='Requested':self.banner=''
                self.draw()
        # A debug toggle from the recovery site takes effect without restarting.
        if time.monotonic()-getattr(self,'debug_checked',0)>1:
            self.debug_checked=time.monotonic()
            self.prefs.data['debug_mode'] = Preferences(self.prefs.path).data['debug_mode']
            if not self.prefs.data['debug_mode'] and (self.mode.startswith('debug_') or self.mode in ('protocol_tests','diagnostics')):
                self.protocols.stop(); self.system_settings()
        for button in self.inputs.drain():
            self.host.button(button)
        if self.mode == 'audio_settings' and time.monotonic()-self.audio_checked > .5:
            self.audio_checked = time.monotonic()
            if self.audio_settings.refresh():self.draw()
        self.tone_test.tick()
        self.host.tick()
        if self.host.active=='obd' and time.monotonic()-getattr(self,'vehicle_gauge_sent',0)>=1/30:
            self.vehicle_gauge_sent=time.monotonic()
            self.host.vehicle_gauges(self.protocols.gauge_snapshot())
        if time.monotonic()-getattr(self,'projection_checked',0)>1:
            self.projection_checked=time.monotonic()
            manifest=self.manifests.get('carplay')
            if (self.prefs.data['setup_complete'] and not self.pending_default and self.mode not in ('onboarding','shutdown_pending')
                    and manifest and self.prefs.enabled(manifest)):
                from .projection import carplay_adapter_present
                if self.host.branding.pending or carplay_adapter_present():
                    try:self.host.ensure_background_carplay()
                    except (OSError,ValueError) as exc:self.event(state='projection_background_failed',error=str(exc))
        self.obd.tick(self.host.session)
        now = time.monotonic()
        if self.mode in ('debug_inputs','debug_audio','debug_volume') and now-self.debug_redraw >= .05:
            self.debug_redraw = now
            self.draw()
        if self.mode == "obd_settings" and self.obd.revision != self.obd_revision:self.draw()
        if self.mode == 'diagnostics':
            _, revision, _ = self.diagnostics.snapshot()
            if revision != self.diagnostic_revision:self.draw()
        if self.mode == 'protocol_tests' and now-self.protocol_redraw>.25:
            self.protocol_redraw=now
            self.draw()
        if self.picture_dirty and now-self.picture_saved > .1:
            self.save_picture()
        elif not self.picture_dirty and self.picture_drag is None and now-self.picture_checked > .2:
            self.picture_checked = now
            if self.picture.refresh():
                self.picture_values = dict(self.picture.values)
                self.apply_picture()
                if self.mode != 'plugin':self.draw()
        if self.pending_default and self.prefs.data['setup_complete']:
            self.pending_default = False
            plugin_id = self.prefs.data["default_plugin"]
            if plugin_id in self.manifests and self.prefs.enabled(
                self.manifests[plugin_id]
            ):
                self.open_plugin(plugin_id)
        if self.mode != "plugin":
            return
        worker=self.host.workers.get(self.host.active)
        projection_cleared=(self.host.active in ('carplay','android-auto') and self.has_frame
                            and worker is not None and not worker.video_available)
        if projection_cleared:self.has_frame=False
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
            if status != self.last_status or projection_cleared:
                self.last_status = status
                # A disconnect/error replaces stale CarPlay pixels with a waiting page.
                worker = self.host.workers.get(self.host.active)
                if worker is not None and not worker.video_available:
                    self.has_frame = False
                    self.draw()

    def close(self):
        self.inputs.close()
        self.tone_test.stop()
        self.diagnostics.stop()
        self.obd.close()
        self.host.close()
        self.protocols.close()
        if hasattr(self.audio.playback,'close'):self.audio.playback.close()
        self.fb.close()
