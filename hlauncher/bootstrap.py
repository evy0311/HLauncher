"""Register Bluetooth before loading the framebuffer, plugins or projection runtime."""
from .setup_state import SetupState
import time
import threading
from .boot_timing import mark


class QuietInputs:
    steering_mode = None
    def receive_iap_remote(self, event): pass
    def observe(self, *args, **kwargs): pass


class BootstrapLauncher:
    def __init__(self, event, protocols, state=None, factory=None):
        self.event, self.protocols = event, protocols
        self.state = state or SetupState()
        self.factory = factory
        self.ui = None
        self.inputs = QuietInputs()
        self.session = {}
        self.peer_address = None
        self.splash = None
        self.display_lock=threading.RLock()
        self.preparing=None
        self.boot_pending = False
        self.closing=False
        self.display_test = None

    def set_peer(self, peer): self.peer_address = peer

    def open(self):
        with self.display_lock:return self._open()

    def _open(self):
        if self.ui is not None: return self.ui
        if not self.peer_address: raise RuntimeError('Waiting for radio connection')
        from . import config
        config.RADIO_ADDRESS = self.peer_address
        config.RADIO_PATH = '/org/bluez/hci0/dev_'+self.peer_address.replace(':','_')
        config.RFCOMM_PATH = '/org/bluealsa/hci0/dev_'+self.peer_address.replace(':','_')+'/rfcomm'
        if self.factory is None:
            import subprocess
            if self.splash is None:
                subprocess.run(['fbset','-depth','16'], check=True, capture_output=True, timeout=3)
            from .launcher import Launcher
            factory = Launcher
        else: factory = self.factory
        options=dict(independent_audio=True,protocol_diagnostics=self.protocols)
        if self.splash is not None:options['framebuffer']=self.splash
        mark('launcher_initialization_started')
        self.ui = factory(self.event,**options)
        mark('launcher_initialized')
        from .network_boot import signal_ui_ready
        if not signal_ui_ready():
            self.event(state='network_boot_signal_error')
        self.ui.request_hondalink_display_test = self.queue_display_test
        self.splash=None
        self.inputs = self.ui.inputs
        if self.session: self.ui.session_changed(**self.session)
        self.event(state='launcher_ui_ready')
        return self.ui

    def launch(self, app_id): return self.open().launch(app_id)

    def vehicle_scope(self):
        if self.ui is None:return 'off'
        if self.ui.mode=='protocol_tests' and self.ui.protocol_page==1:return 'diagnostics'
        from .projection import PROJECTIONS
        host = self.ui.host
        if self.ui.mode == 'plugin' and host.active == 'vehicle':
            return 'vehicle'
        if (self.ui.mode == 'parked_plugin' and self.ui.locked_plugin == 'vehicle'
                and self.protocols.parked_setup_readings()[1] is True):
            # A full stream includes speed. Keep its retries running while the
            # worker is blocked waiting for that speed confirmation.
            return 'vehicle'
        illumination = any(ident in PROJECTIONS and getattr(worker.manifest, 'bundled', False) and
                           self.ui.prefs.auto_night(ident)
                           for ident, worker in getattr(host, 'workers', {}).copy().items())
        gauges = self.ui.mode == 'plugin' and host.active == 'obd'
        android = getattr(host, 'workers', {}).get('android-auto')
        carplay = getattr(host, 'workers', {}).get('carplay')
        # Keep speed sampled on Home so opening Settings can use a live reading.
        parking = self.ui.mode == 'parking_status'
        from .catalog import PARKING_CAPABILITY
        plugin_parking = any(PARKING_CAPABILITY in worker.manifest.capabilities
                             for worker in getattr(host, 'workers', {}).copy().values())
        driving = (parking or plugin_parking or self.ui.mode == 'home' or getattr(self.ui, 'parked_only_screen', False)
                   or (android is not None and getattr(android.manifest, 'bundled', False))
                   or getattr(carplay, 'car_gps', False))
        gps = any(getattr(worker, 'car_gps', False) for worker in getattr(host, 'workers', {}).copy().values())
        return '_'.join(name for enabled, name in (
            (gauges, 'gauges'), (illumination, 'illumination'), (driving, 'driving'), (gps, 'gps'),
            (parking, 'parking'),
        ) if enabled) or 'off'

    def queue_display_test(self, action):
        if self.display_test is not None and action != 'exit':
            self.event(state='honda_display_test_result', action=action, status='Already queued')
            return
        delay = 8 if action == 'show' else 0
        self.display_test = (action, time.monotonic() + delay)
        self.event(state='honda_display_test_result', action=action,
                   status=f'Sending in {delay}s' if delay else 'Queued')

    def session_changed(self, **values):
        if values.get('connected') is False and self.display_test:
            action, _ = self.display_test
            self.display_test = None
            self.event(state='honda_display_test_result', action=action, status='Radio disconnected')
        self.session.update(values)
        if self.ui: self.ui.session_changed(**values)

    def update(self, touch):
        if self.ui: self.ui.update(touch)

    def tick(self):
        if self.boot_pending and not self.preparing.is_alive():
            self.boot_pending = False
            if self.ui is None and not self.closing:
                # Fresh installs still wait for the radio pairing and launch flow.
                if peer := self.state.peer:
                    try:
                        if self.peer_address is None:
                            self.set_peer(peer)
                        self.open().start()
                    except Exception as exc:
                        self.event(state='launcher_boot_start_error', error=str(exc))
        if self.ui:self.ui.tick()
        elif self.splash and time.monotonic()-getattr(self,'splash_checked',0)>1:
            self.splash_checked=time.monotonic()
            key=(bool(self.state.peer),time.strftime('%Y-%m-%d %H:%M'))
            if key!=getattr(self,'splash_key',None):
                if self.display_lock.acquire(blocking=False):
                    try:
                        if self.splash:self.render_splash()
                    finally:self.display_lock.release()

    def render_splash(self):
        paired=bool(self.state.peer)
        if paired:
            # Get a simple frame out before loading themed controls and artwork.
            from .ui.boot_splash import render
            self.splash.image_early(render((self.splash.w,self.splash.h)))
            self.splash_key=(True,time.strftime('%Y-%m-%d %H:%M'))
            return
        from .ui.first_boot import render
        from .config import Preferences
        from sdk.hlauncher_sdk.theme import dither_rgb565
        from .themes import Themes
        prefs=Preferences(self.state.folder/'settings.json')
        self.splash.image(dither_rgb565(render(self.state.credentials(),paired,
            prefs.data['tile_color'],(self.splash.w,self.splash.h),show_clock=prefs.data['show_clock'],
            layout_theme=Themes(prefs.path.parent).get(prefs.data['layout_theme']))))
        self.splash_key=(paired,time.strftime('%Y-%m-%d %H:%M'))

    def prepare(self):
        # Bluetooth profiles are already registered. Display I/O/imports run off its loop.
        if self.preparing or self.closing:return
        def work():
            mark('display_preparation_started')
            self.show_pairing()
            if not self.closing:
                try:
                    from . import launcher  # cache imports before the radio asks to launch
                    mark('launcher_imports_loaded')
                    # Paired boots open the real UI immediately after imports.
                    # Do not hold that up with a complete offscreen Home render.
                    if self.ui is None and not self.closing and not self.state.peer:
                        self.prewarm_home()
                    self.event(state="display_prepared",monotonic=time.monotonic())
                except Exception as exc:self.event(state="display_prepare_error",error=str(exc))
        self.preparing=threading.Thread(target=work,name="display-prepare",daemon=True)
        self.preparing.start()
        self.boot_pending = True

    def prewarm_home(self):
        # Render offscreen to cache the actual theme, labels, icons and reflections.
        # No plugins, input monitors or audio processes start during this preparation.
        from .catalog import discover
        from .config import Preferences
        from .ui.home import Entry,render
        from .ui.home_edit import SETTINGS, layout
        prefs=Preferences(self.state.folder/'settings.json')
        manifests=sorted(discover(self.event).values(),key=lambda m:(m.id!='carplay',m.name.casefold()))
        entries = {m.id: Entry(m.name, m.id, lambda: None) for m in manifests if prefs.enabled(m)}
        pages = layout(entries, prefs.data['home_pages'])
        # entries[AUDIO] = Entry('Audio', 'audio', lambda: None)
        entries[SETTINGS] = Entry('Settings', 'settings', lambda: None)
        render([[entries.get(pid) for pid in page] for page in pages],
               theme=prefs.data['tile_color'],show_clock=prefs.data['show_clock'])

    def show_pairing(self):
        with self.display_lock:
            if self.closing:return False
            return self._show_pairing()

    def _show_pairing(self):
        if self.ui or self.splash: return False
        # A static HDMI instruction screen needs no full app or Bluetooth input.
        try:
            from .display import Framebuffer
            import subprocess
            subprocess.run(['fbset','-depth','16'], check=True, capture_output=True, timeout=3)
            self.splash = Framebuffer(self.event)
            self.splash.boot_stage = 'splash_frame_submitted'
            self.splash.open()
            self.render_splash()
        except Exception as exc:
            if self.splash:self.splash.close();self.splash=None
            self.event(state='setup_display_error',error=str(exc))
        return False

    def close(self):
        self.closing=True
        if self.preparing:self.preparing.join()
        with self.display_lock:
            if self.ui: self.ui.close()
            else: self.protocols.close()
            if self.splash: self.splash.close()
