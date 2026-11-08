"""Register Bluetooth before loading the framebuffer, plugins or projection runtime."""
from .setup_state import SetupState


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
        if self.ui: self.ui.tick()

    def show_pairing(self):
        if self.ui or self.state.peer: return False
        # A static HDMI instruction screen needs no full app or Bluetooth input.
        try:
            from PIL import Image, ImageDraw
            from .display import Framebuffer
            from sdk.hlauncher_sdk.fonts import font
            import subprocess
            subprocess.run(['fbset','-depth','16'], check=True, capture_output=True, timeout=3)
            self.splash = Framebuffer(self.event); self.splash.open()
            image = Image.new('RGB',(self.splash.w,self.splash.h),'#111820')
            draw = ImageDraw.Draw(image)
            creds = self.state.credentials()
            lines = ['Welcome to HLauncher','On the radio: HandsFreeLink → Add phone',
                     'Select HLauncher and confirm pairing.',
                     'Need help? Connect your phone to:',creds['ssid'],
                     'Wi-Fi / login password: '+creds['password'],
                     'http://192.168.4.1:8080 · user: hlauncher']
            for i,line in enumerate(lines):
                draw.text((24,28+i*54),line,font=font(27 if i==0 else 17),fill='white')
            self.splash.image(image)
        except Exception as exc:
            self.event(state='setup_display_error',error=str(exc))
        return False

    def close(self):
        if self.ui: self.ui.close()
        else: self.protocols.close()
        if self.splash: self.splash.close()
