"""Resumable on-screen setup; preferences are committed on each choice."""
from .config import TILE_COLORS

STEPS = ('Welcome', 'Apps', 'Startup', 'Appearance', 'Network', 'Finish')
REQUIREMENTS = {'carplay': 'CarPlay USB adapter required',
                'android-auto': 'Android phone connected directly by USB',
                'obd': 'Bluetooth LE ELM327 adapter required'}


class Onboarding:
    def __init__(self, prefs, manifests):
        self.prefs, self.manifests = prefs, manifests

    @property
    def step(self): return self.prefs.data['setup_step']

    def save(self, force=(), **changes):
        before = dict(self.prefs.data)
        self.prefs.data.update(changes)
        try: self.prefs.save(force=force)
        except OSError:
            self.prefs.data = before
            raise

    def move(self, delta):
        self.save(setup_step=max(0, min(len(STEPS)-1, self.step+delta)))

    def plugin(self, plugin_id):
        manifest = self.manifests[plugin_id]
        enabled = dict(self.prefs.data['enabled'])
        enabled[plugin_id] = not self.prefs.enabled(manifest)
        changes = dict(enabled=enabled)
        if not enabled[plugin_id] and self.prefs.data['default_plugin'] == plugin_id:
            changes['default_plugin'] = None
        self.save(**changes)

    def default(self, plugin_id):
        if plugin_id is not None and (plugin_id not in self.manifests or
                                      not self.prefs.enabled(self.manifests[plugin_id])):
            raise ValueError('Enable the startup app first')
        self.save(default_plugin=plugin_id)

    def theme(self, name):
        if name not in TILE_COLORS: raise ValueError('Unknown theme')
        self.save(tile_color=name)

    def finish(self):
        if not self.prefs.safety_notice_accepted:
            raise ValueError('Review the safety notice before finishing setup')
        selected=self.prefs.data['default_plugin']
        if selected not in self.manifests or not self.prefs.enabled(self.manifests[selected]):selected=None
        self.default(selected)
        self.save(force=('debug_mode',), setup_complete=True, setup_step=0, debug_mode=False)

    def restart(self): self.save(setup_complete=False, setup_step=0)
