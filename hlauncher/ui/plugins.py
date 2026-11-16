"""Radio plugin workflows. Imports and downloads run off the display thread."""

from concurrent.futures import Future
from pathlib import Path
import tempfile
import threading

from .. import plugin_sources
from ..cameras import usb_cameras
from ..plugin_packages import unpack
from ..plugins import validate_external
from ..updater import sha256
from .controls import present
from .pages import page_for
from .projection import wrap_status
from .scroll_list import Row, draw as draw_rows
from sdk.hlauncher_sdk.fonts import font


class Manager:
    def __init__(self, ui, store):
        self.ui = ui
        self.store = store
        self.view = 'sources'
        self.rows = []
        self.value = ''
        self.notice = ''
        self.job = None
        self.review = None
        self.update_target = None

    def go(self, view):
        self.view = view
        self.ui.mode = 'plugin_manager'
        self.ui.press = None
        self.ui.draw()

    def add(self):
        self.update_target = None
        self.notice = ''
        self.go('sources')

    def start(self, message, operation, done):
        if self.job:
            return
        self.notice = message
        future = Future()
        self.job = future, done

        def run():
            try:
                future.set_result(operation())
            except Exception as exc:
                future.set_exception(exc)

        threading.Thread(target=run, daemon=True).start()
        self.ui.draw()

    def tick(self):
        if not self.job or not self.job[0].done():
            return
        future, done = self.job
        self.job = None
        try:
            result = future.result()
            self.notice = ''
            done(result)
        except Exception as exc:
            self.notice = str(exc)[:160] if isinstance(exc, ValueError) else 'Could not complete the operation. Check the source and try again.'
            if self.ui.mode != 'plugin_manager':
                self.ui.banner = self.notice
            self.ui.draw()

    def sources(self, origin):
        if origin == 'github':
            self.value = ''
            self.notice = ''
            self.go('github')
        elif origin == 'usb':
            self.start('Scanning USB drives…', plugin_sources.usb_packages,
                       lambda rows: self.show_packages(rows, 'usb'))

    def lookup(self):
        try:
            repo = plugin_sources.github_repo('github.com/' + self.value)
        except ValueError as exc:
            self.notice = str(exc)
            self.ui.draw()
            return
        self.start('Checking GitHub…', lambda: plugin_sources.github_assets(repo),
                   lambda rows: self.show_packages(rows, 'github'))

    def check_update(self, manifest):
        self.update_target = manifest.id
        self.value = manifest.origin.split(' @ ', 1)[0].removeprefix('GitHub ')
        self.go('github')
        self.lookup()

    def show_packages(self, rows, source):
        self.package_source = source
        if source == 'usb':
            self.rows = [Row(item[0], lambda item=item: self.prepare(
                lambda path: plugin_sources.copy_usb(item, path))) for item in rows]
        else:
            self.rows = [Row(item['name'], lambda item=item: self.prepare(
                lambda path: plugin_sources.fetch_asset(item, path)), value=item['tag']) for item in rows]
        self.notice = '' if rows or source == 'usb' else 'No .hlp packages found.'
        self.ui.list_offsets = getattr(self.ui, 'list_offsets', {})
        self.ui.list_offsets['plugin-packages'] = 0
        self.go('packages')

    def prepare(self, fetch):
        target = self.update_target

        def inspect():
            scratch = tempfile.TemporaryDirectory(prefix='hlauncher-review-')
            try:
                root = Path(scratch.name)
                package = root / 'plugin.hlp'
                origin = fetch(package)
                payload = root / 'inspect'
                payload.mkdir()
                manifest = unpack(package, payload)
                validate_external(manifest)
                if target and manifest.id != target:
                    raise ValueError('This package belongs to a different plugin')
                return scratch, package, manifest, origin, sha256(package)
            except Exception:
                scratch.cleanup()
                raise

        def ready(review):
            self.review = review
            self.go('review')

        self.start('Reading plugin package…', inspect, ready)

    def cancel_review(self):
        if self.review:
            self.review[0].cleanup()
            self.review = None
        self.go('packages')

    def install(self):
        scratch, package, manifest, origin, digest = self.review
        update = manifest.id in self.ui.manifests

        def work():
            return self.store.install(package, origin=origin, expected=digest, update=update)

        def done(installed):
            scratch.cleanup()
            self.review = None
            self.update_target = None
            self.ui.refresh_plugins()
            self.ui.plugin_detail(installed.id)

        self.start('Installing plugin…', work, done)

    def change(self, plugin_id, operation, **options):
        def done(_result):
            self.ui.refresh_plugins()
            if operation == 'remove':
                self.ui.plugin_settings()
            else:
                self.ui.plugin_detail(plugin_id)

        self.go('change')
        self.start('Saving plugin settings…',
                   lambda: self.store.change(plugin_id, operation, **options), done)

    def toggle(self, manifest):
        self.notice = ''
        if manifest.enabled:
            self.change(manifest.id, 'disable')
        elif 'camera' in manifest.permissions and not manifest.camera:
            self.camera_page(manifest.id)
        elif 'network' in manifest.permissions and not manifest.endpoint:
            self.endpoint_page(manifest.id)
        else:
            self.change(manifest.id, 'enable')

    def camera_page(self, plugin_id):
        self.target = plugin_id
        self.pending_camera = None
        self.notice = ''
        self.rows = []
        self.go('camera')
        self.start('Scanning USB cameras…', usb_cameras, self.show_cameras)

    def show_cameras(self, cameras):
        self.rows = [Row(name, lambda device=device: self.choose_camera(device))
                     for device, name in cameras.items()]
        self.go('camera')

    def choose_camera(self, device):
        self.pending_camera = device
        manifest = self.ui.manifests[self.target]
        if 'network' in manifest.permissions and not manifest.endpoint:
            self.endpoint_page(self.target, camera=device)
        else:
            self.change(self.target, 'enable', camera=device)

    def endpoint_page(self, plugin_id, camera=None):
        self.target = plugin_id
        self.pending_camera = camera
        self.value = self.ui.manifests[plugin_id].endpoint
        self.notice = ''
        self.go('endpoint')

    def key(self, key):
        if key == 'Delete':
            self.value = self.value[:-1]
        elif key == 'Clear':
            self.value = ''
        elif len(self.value) < 141:
            self.value += key
        self.ui.draw()

    def confirm_remove(self, plugin_id):
        self.target = plugin_id
        self.notice = ''
        self.go('remove')

    def draw(self):
        ui = self.ui
        title = {'sources': 'Add plugin', 'github': 'GitHub repository', 'packages': 'Plugin packages',
                 'review': 'Review plugin', 'camera': 'Select USB camera',
                 'endpoint': 'Set TCP endpoint', 'remove': 'Uninstall plugin', 'change': 'Plugin settings'}[self.view]
        back = {
            'sources': ui.plugin_settings,
            'packages': self.add,
            'review': self.cancel_review,
            'github': self.add,
        }.get(self.view, ui.plugin_detail)
        page = page_for(ui, title, back)
        if self.job:
            page.actions.clear()
            page.text((24, 138), self.notice, 21)
        elif self.view == 'sources':
            draw_rows(ui, page, [Row('Scan USB drive', lambda: self.sources('usb')),
                                 Row('Add GitHub repository', lambda: self.sources('github'))])
            page.text((24, 296), 'Plugins installed over SSH appear in Settings → Plugins.', 20)
        elif self.view in ('packages', 'camera'):
            if self.view == 'camera' and not self.rows:
                page.text((24, 132), 'Connect the USB camera, then scan again.', 20)
                page.button((24, 212, 696, 264), 'Scan again', lambda: self.camera_page(self.target))
            elif self.view == 'packages' and self.package_source == 'usb' and not self.rows:
                page.text((24, 132), 'No .hlp packages found. Check the USB drive.', 20)
                page.button((24, 212, 696, 264), 'Scan again', lambda: self.sources('usb'))
            else:
                draw_rows(ui, page, self.rows, bottom=415, key='plugin-' + self.view, size=23)
        elif self.view == 'review':
            _, _, manifest, origin, digest = self.review
            installed = ui.manifests.get(manifest.id)
            page.label((24, 116), f'{manifest.name}  {manifest.version}', 28)
            page.text((24, 158), origin[:82], 18)
            page.text((24, 196), 'Requests ' + (', '.join(sorted(manifest.permissions | manifest.capabilities)) or 'no launcher features'), 18)
            if installed:
                page.text((24, 236), f'Currently installed {installed.version} · {installed.origin[:55]}', 18)
            page.text((24, 276), 'Runs as root with full access to your Pi and its data.', 19)
            page.text((24, 300), 'Install only code you trust.', 18)
            page.text((24, 329), 'SHA-256  ' + digest[:24] + '…', 17)
            page.button((24, 360, 696, 414), 'Install update' if installed else 'Install plugin', self.install)
        elif self.view == 'remove':
            page.label((24, 120), ui.manifests[self.target].name, 27)
            page.text((24, 174), 'The tile will be removed. Plugin data is kept.', 19)
            page.button((24, 258, 696, 312), 'Uninstall', lambda: self.change(self.target, 'remove'))
        elif self.view in ('github', 'endpoint'):
            self.keyboard(page)
        notice_y = 432 if self.view in ('github', 'endpoint') else 445
        for i, line in enumerate(wrap_status('' if self.job else self.notice, page.draw, font(15), 660)[:2]):
            page.text((24, notice_y + i * 19), line, 15, fill='#efbd82')
        present(ui, page)

    def keyboard(self, page):
        github = self.view == 'github'
        page.panel((24, 106, 696, 151))
        page.text((38, 119), page.fit(self.value[-58:] or ('owner/repo' if github else '192.168.1.10:8554'), 640, 19), 19)
        rows = ('1234567890', 'qwertyuiop', 'asdfghjkl-', 'zxcvbnm/._') if github else (
            '1234567890', 'abcdef.:[]')
        for y, keys in enumerate(rows):
            for x, key in enumerate(keys):
                left, top = 24 + x * 67, 162 + y * 51
                page.button((left, top, left + 61, top + 44), key, lambda key=key: self.key(key), size=23)
        if github:
            submit = self.lookup
        else:
            submit = lambda: self.change(self.target, 'enable', camera=self.pending_camera, endpoint=self.value)
        for x, label, action in ((24, 'Clear', lambda: self.key('Clear')),
                                 (251, 'Delete', lambda: self.key('Delete')),
                                 (478, 'Find release' if github else 'Allow and enable', submit)):
            page.button((x, 369, x + 218, 418), label, action, size=20)
