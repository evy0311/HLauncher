"""Register Bluetooth before loading the framebuffer, plugins or projection runtime."""
from .setup_state import SetupState
import time


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

    def set_peer(self, peer): self.peer_address = peer

    def open(self):
        if self.ui is not None: return self.ui
        if not self.peer_address: raise RuntimeError('Waiting for radio connection')
        from . import config
        config.RADIO_ADDRESS = self.peer_address
        config.RADIO_PATH = '/org/bluez/hci0/dev_'+self.peer_address.replace(':','_')
        config.RFCOMM_PATH = '/org/bluealsa/hci0/dev_'+self.peer_address.replace(':','_')+'/rfcomm'
        if self.splash:
            self.splash.close(); self.splash = None
        if self.factory is None:
            import subprocess
            subprocess.run(['fbset','-depth','16'], check=True, capture_output=True, timeout=3)
            from .launcher import Launcher
            factory = Launcher
        else: factory = self.factory
        self.ui = factory(self.event, independent_audio=True, protocol_diagnostics=self.protocols)
        self.inputs = self.ui.inputs
        if self.session: self.ui.session_changed(**self.session)
        self.event(state='launcher_ui_ready')
        return self.ui

    def launch(self, app_id): return self.open().launch(app_id)

    def session_changed(self, **values):
        self.session.update(values)
        if self.ui: self.ui.session_changed(**values)

    def update(self, touch):
        if self.ui: self.ui.update(touch)

    def tick(self):
        if self.ui:self.ui.tick()
        elif self.splash and time.monotonic()-getattr(self,'splash_checked',0)>1:
            self.splash_checked=time.monotonic()
            key=(bool(self.state.peer),time.strftime('%Y-%m-%d %H:%M'))
            if key!=getattr(self,'splash_key',None):self.render_splash()

    def render_splash(self):
        from .ui.first_boot import render
        from .config import Preferences
        from sdk.hlauncher_sdk.theme import dither_rgb565
        paired=bool(self.state.peer)
        prefs=Preferences(self.state.folder/'settings.json')
        self.splash.image(dither_rgb565(render(self.state.credentials(),paired,
            prefs.data['tile_color'],(self.splash.w,self.splash.h),show_clock=prefs.data['show_clock'])))
        self.splash_key=(paired,time.strftime('%Y-%m-%d %H:%M'))

    def show_pairing(self):
        if self.ui or self.splash: return False
        # A static HDMI instruction screen needs no full app or Bluetooth input.
        try:
            from .display import Framebuffer
            import subprocess
            subprocess.run(['fbset','-depth','16'], check=True, capture_output=True, timeout=3)
            self.splash = Framebuffer(self.event); self.splash.open()
            self.render_splash()
        except Exception as exc:
            self.event(state='setup_display_error',error=str(exc))
        return False

    def close(self):
        if self.ui: self.ui.close()
        else: self.protocols.close()
        if self.splash: self.splash.close()
