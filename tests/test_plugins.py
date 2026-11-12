"""Plugin package, permission, upgrade, and home navigation regressions."""

from dataclasses import replace
import json
import threading
from pathlib import Path
import select
import socket
import tempfile
import unittest
from unittest.mock import Mock, patch
import zipfile

from hlauncher.cameras import CAPABILITY, DEVICE_CAPS, usb_cameras
from hlauncher.catalog import Manifest
from hlauncher.config import Preferences, ROOT
from hlauncher.launcher import Launcher
from hlauncher.plugin_packages import pack
from hlauncher.plugin_host import Worker
from hlauncher.plugin_network import Network
from hlauncher.plugin_sources import usb_packages
from hlauncher.plugins import PluginStore
from sdk.hlauncher_sdk import Client
from test_architecture import Display


class ManagedPlugins(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory()
        self.addCleanup(self.scratch.cleanup)
        self.root = Path(self.scratch.name)
        self.store = PluginStore(self.root / 'state')
        self.source = self.root / 'source'
        self.source.mkdir()
        (self.source / 'worker.py').write_text('raise RuntimeError("installer must not run this")')

    def package(self, version, permissions=(), plugin_id='fixture'):
        manifest = dict(api_version=1, version=version, id=plugin_id, name='Fixture',
                        entrypoint=['python3', 'worker.py'], capabilities=['display'],
                        permissions=list(permissions))
        (self.source / 'plugin.json').write_text(json.dumps(manifest))
        package = self.root / 'fixture.hlp'
        pack(self.source, package)
        return package

    def test_packages_keep_data_and_require_approval_for_new_permissions(self):
        installed = self.store.install(self.package('1.0.0'))
        self.assertFalse(installed.enabled)
        self.store.change('fixture', 'enable')
        data = installed.data_path / 'settings.txt'
        data.write_text('camera preferences')
        updated = self.store.install(self.package('2.0.0', ['camera']), update=True)
        self.assertFalse(updated.enabled)
        with self.assertRaisesRegex(ValueError, 'Configure'):
            self.store.change('fixture', 'enable')
        self.store.change('fixture', 'enable', camera='/dev/video0')
        self.assertEqual(self.store.manifests()['fixture'].camera, '/dev/video0')
        self.store.change('fixture', 'rollback')
        restored = self.store.manifests()['fixture']
        self.assertEqual(restored.revision, installed.revision)
        self.assertEqual(restored.camera, '')
        self.store.change('fixture', 'remove')
        self.assertEqual(self.store.manifests(), {})
        self.assertEqual(data.read_text(), 'camera preferences')
        self.assertFalse(restored.path.exists())

    def test_untrusted_archives_never_replace_an_installed_version(self):
        current = self.store.install(self.package('1.0.0'))
        package = self.package('2.0.0')
        with self.assertRaisesRegex(ValueError, 'changed after review'):
            self.store.install(package, update=True, expected=current.revision)
        with zipfile.ZipFile(package, 'a') as archive:
            archive.writestr('../../state-escape', 'escape')
        with self.assertRaisesRegex(ValueError, 'Invalid path'):
            self.store.install(package, update=True)
        self.assertEqual(self.store.manifests()['fixture'].revision, current.revision)
        self.assertFalse((self.store.root / 'state-escape').exists())
        with self.assertRaisesRegex(ValueError, 'bundled'):
            self.store.install(self.package('3.0.0', plugin_id='carplay'))

    def test_legacy_plugins_are_kept_out_of_old_launchers_discovery(self):
        old = self.store.state / 'plugins' / 'old'
        old.mkdir(parents=True)
        (old / 'plugin.json').write_text('{}')
        (old / 'settings').write_text('saved')
        self.store.park_legacy()
        self.store.park_legacy()
        self.assertFalse(old.exists())
        saved = self.store.legacy_sources()[0]
        self.assertEqual((saved / 'settings').read_text(), 'saved')
        self.assertEqual(self.store.manifests(), {})

    def test_home_swipes_between_pages_and_do_not_launch_tiles(self):
        bundled = Manifest.load(ROOT / 'plugins/carplay', bundled=True)
        manifests = {f'app{i}': replace(bundled, id=f'app{i}', name=f'App {i}') for i in range(7)}
        preferences = Preferences(self.root / 'settings.json')
        preferences.data['setup_complete'] = True
        preferences.accept_safety_notice()
        ui = Launcher(framebuffer=Display(), preferences=preferences, manifests=manifests)
        self.addCleanup(ui.close)

        def touch(action, x, y):
            ui.update({'contacts': [dict(slot=0, action=action, has_position=action != 'up',
                                         x_raw=round(x / 719 * 32767), y_raw=round(y / 479 * 32767))]})

        with patch.object(ui, 'open_plugin') as opened:
            initial = ui.fb.last.tobytes()
            touch('down', 190, 140)
            touch('move', 75, 145)
            self.assertEqual(ui.page, 0)
            self.assertLess(ui.home_slide, 0)
            self.assertNotEqual(ui.fb.last.tobytes(), initial)
            touch('up', 75, 145)
            self.assertEqual(ui.page, 1)
            self.assertGreater(ui.home_slide, 0)
            ui.tick_home_slide(ui.home_settle[0] + .25)
            self.assertEqual(ui.home_slide, 0)
            opened.assert_not_called()
            touch('down', 75, 140)
            touch('move', 193, 144)
            touch('up', 193, 144)
            self.assertEqual(ui.page, 0)
            opened.assert_not_called()
            touch('down', 75, 140)
            touch('up', 75, 140)
            opened.assert_called_once_with('app0')

    def test_crashing_enabled_plugin_keeps_its_home_tile_and_can_relaunch(self):
        self.store.install(self.package('1.0.0'))
        self.store.change('fixture', 'enable')
        preferences = Preferences(self.root / 'settings.json')
        preferences.data['setup_complete'] = True
        preferences.accept_safety_notice()
        ui = Launcher(framebuffer=Display(), preferences=preferences, manifests=self.store.manifests())
        self.addCleanup(ui.close)
        workers = [Mock(manifest=ui.manifests['fixture']) for _ in range(3)]
        for worker in workers[:2]:
            worker.proc.poll.return_value = 1

        with patch('hlauncher.plugin_host.Worker', side_effect=workers) as start:
            for attempt, worker in enumerate(workers[:2], start=1):
                ui.actions[0][1]()
                self.assertEqual(start.call_count, attempt)
                ui.host.tick()
                worker.close.assert_called_once()
                self.assertEqual(ui.mode, 'home')
                self.assertEqual(ui.banner, 'Fixture closed unexpectedly')
                self.assertEqual([callback for _, callback in ui.actions], [ui.dismiss_home_notice])
                ui.actions[0][1]()
            ui.actions[0][1]()
            self.assertEqual(start.call_count, 3)
            self.assertEqual(ui.host.active, 'fixture')

    def test_home_edit_moves_tiles_across_pages_and_saves_gaps(self):
        from hlauncher.ui.home_edit import EDGE_SECONDS, HOLD_SECONDS, SETTINGS

        bundled = Manifest.load(ROOT / 'plugins/carplay', bundled=True)
        preferences = Preferences(self.root / 'settings.json')
        preferences.data['setup_complete'] = True
        preferences.accept_safety_notice()
        ui = Launcher(framebuffer=Display(), preferences=preferences, manifests={bundled.id: bundled})
        self.addCleanup(ui.close)
        editor = ui.home_editor

        def touch(action, x, y):
            ui.update({'contacts': [dict(slot=0, action=action, has_position=action != 'up',
                                         x_raw=round(x / 719 * 32767), y_raw=round(y / 479 * 32767))]})

        def tap(x, y):
            touch('down', x, y)
            touch('up', x, y)

        with patch('hlauncher.ui.home_edit.time.monotonic', return_value=10) as clock:
            touch('down', 140, 160)
            clock.return_value += HOLD_SECONDS + .01
            editor.tick(clock.return_value)
            self.assertTrue(editor.editing)
            touch('up', 140, 160)
            tap(590, 26)
            tap(590, 26)
            self.assertEqual((ui.page, len(ui.home_pages())), (2, 3))
            self.assertNotIn(editor.add_page, [action for _, action in ui.actions])
            tap(316, 467)  # Jump back to the first page using its bar.
            self.assertEqual(ui.page, 0)
            touch('down', 140, 160)
            touch('move', 707, 165)
            clock.return_value += EDGE_SECONDS + .2
            editor.tick(clock.return_value)
            self.assertEqual(ui.page, 1)
            touch('move', 574, 364)
            touch('up', 574, 364)
            tap(665, 26)
        self.assertFalse(editor.editing)
        self.assertEqual(Preferences(preferences.path).data['home_pages'], [
            [None, SETTINGS, None, None, None, None],
            [None, None, None, None, None, 'carplay'],
            [None] * 6,
        ])

    def test_home_edit_confirms_bundled_disable_and_managed_uninstall(self):
        self.store.install(self.package('1.0.0'))
        self.store.change('fixture', 'enable')
        preferences = Preferences(self.store.state / 'settings.json')
        preferences.data['setup_complete'] = True
        preferences.accept_safety_notice()
        ui = Launcher(framebuffer=Display(), preferences=preferences)
        self.addCleanup(ui.close)
        editor = ui.home_editor
        editor.editing = True

        ui.draw()
        for action in ('down', 'up'):
            ui.update({'contacts': [dict(slot=0, action=action, has_position=action == 'down',
                                         x_raw=round(233 / 719 * 32767), y_raw=round(76 / 479 * 32767))]})
        self.assertEqual(editor.confirmation, 'carplay')
        self.assertEqual(len(ui.actions), 2)
        ui.actions[1][1]()  # No
        self.assertTrue(preferences.enabled(ui.manifests['carplay']))
        editor.confirm('carplay')
        ui.actions[0][1]()  # Yes
        self.assertFalse(preferences.enabled(ui.manifests['carplay']))

        editor.confirm('fixture')
        self.assertEqual(len(ui.actions), 3)
        ui.actions[2][1]()  # Cancel
        self.assertTrue(ui.manifests['fixture'].enabled)
        editor.confirm('fixture')
        ui.actions[1][1]()  # Uninstall
        ui.plugin_manager.job[0].result(timeout=3)
        ui.plugin_manager.tick()
        self.assertNotIn('fixture', ui.manifests)
        self.assertTrue(editor.editing)

    def test_usb_scan_lists_only_visible_package_files(self):
        folder = self.root / 'HLauncher'
        folder.mkdir()
        for name in ('baby-monitor.hlp', '._baby-monitor.hlp', '.hidden.hlp', 'notes.txt', 'package.hlp.bak'):
            (self.root / name).touch()
        (self.root / 'folder.hlp').mkdir()
        (self.root / 'link.hlp').symlink_to(self.root / 'baby-monitor.hlp')
        (folder / 'Dashboard.HLP').touch()
        device = ('/dev/sda1', 'exfat', '8:1')
        with patch('hlauncher.plugin_sources.usb_devices', return_value=[device]), \
                patch('hlauncher.plugin_sources.mount_usb') as mount:
            mount.return_value.__enter__.return_value = self.root
            self.assertEqual(usb_packages(), [
                ('baby-monitor.hlp', device, Path('baby-monitor.hlp')),
                ('Dashboard.HLP', device, Path('HLauncher/Dashboard.HLP')),
            ])

    def test_network_handoff_uses_only_the_approved_address(self):
        outbound, peer = socket.socketpair()
        with outbound, peer, patch('hlauncher.plugin_network.socket.create_connection',
                                    return_value=outbound) as connect:
            broker = Network('192.168.1.23:9554')
            client = Client.__new__(Client)
            client.network = broker.child.dup()
            client.network.settimeout(3)
            client.lock = threading.Lock()
            try:
                broker.start()
                with client.connect() as approved:
                    approved.sendall(b'camera')
                    self.assertEqual(peer.recv(6), b'camera')
                connect.assert_called_once_with(('192.168.1.23', 9554), timeout=2)
            finally:
                client.network.close()
                broker.close()

    def test_usb_picker_excludes_metadata_and_internal_capture(self):
        for name in ('video0', 'video1', 'video10'):
            (self.root / name).touch()
        responses = iter((
            (b'Brio 100', b'usb-pi-1', 1),
            (b'Brio 100', b'usb-pi-1', 0x00800000),
            (b'Pi codec', b'platform:codec', 1),
        ))

        def query(_fd, _request, buffer):
            name, bus, node_caps = next(responses)
            buffer[:] = CAPABILITY.pack(b'driver', name, bus, 0, DEVICE_CAPS | 1, node_caps, 0, 0, 0)

        with patch('hlauncher.cameras.fcntl.ioctl', side_effect=query):
            self.assertEqual(usb_cameras(self.root), {str(self.root / 'video0'): 'Logitech Brio 100'})

    def test_external_worker_can_import_launcher_code_and_sdk(self):
        package = self.package('1.0.0')
        (self.source / 'worker.py').write_text(
            'import os\n'
            'from pathlib import Path\n'
            'from hlauncher import __version__\n'
            'from hlauncher_sdk import Client\n'
            'assert __version__ and Path(os.environ["HLAUNCHER_DATA_DIR"]).is_dir()\n'
            'client = Client()\n'
            'client.present(bytes(client.width * client.height * 2))\n'
        )
        pack(self.source, package)
        manifest = self.store.install(package)
        worker = Worker(manifest, 4, 4, lambda **_event: None, log_dir=self.root)
        try:
            self.assertTrue(select.select([worker.socket], [], [], 3)[0])
            self.assertIn('plugin.ready', [message['type'] for message in worker.read()])
            if worker.pending is None:
                self.assertTrue(select.select([worker.socket], [], [], 3)[0])
                worker.read()
            self.assertEqual(worker.take_frame(), bytes(32))
        finally:
            worker.close()
