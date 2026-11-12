"""Plugin package, permission, upgrade, and home navigation regressions."""

from dataclasses import replace
import json
import threading
from pathlib import Path
import socket
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from hlauncher.catalog import Manifest
from hlauncher.config import Preferences, ROOT
from hlauncher.launcher import Launcher
from hlauncher.plugin_packages import pack
from hlauncher.plugin_sandbox import Network
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
        with self.assertRaisesRegex(ValueError, 'Approve'):
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
        manifests = {f'app{i}': replace(bundled, id=f'app{i}', name=f'App {i}') for i in range(6)}
        preferences = Preferences(self.root / 'settings.json')
        preferences.data['setup_complete'] = True
        preferences.accept_safety_notice()
        ui = Launcher(framebuffer=Display(), preferences=preferences, manifests=manifests)
        self.addCleanup(ui.close)

        def touch(action, x, y):
            ui.update({'contacts': [dict(slot=0, action=action, has_position=action != 'up',
                                         x_raw=round(x / 719 * 32767), y_raw=round(y / 479 * 32767))]})

        with patch.object(ui, 'open_plugin') as opened:
            touch('down', 190, 140)
            touch('move', 75, 145)
            touch('up', 75, 145)
            self.assertEqual(ui.page, 1)
            opened.assert_not_called()
            touch('down', 75, 140)
            touch('move', 193, 144)
            touch('up', 193, 144)
            self.assertEqual(ui.page, 0)
            opened.assert_not_called()
            touch('down', 75, 140)
            touch('up', 75, 140)
            opened.assert_called_once_with('app0')

    def test_network_handoff_uses_only_the_approved_address(self):
        outbound, peer = socket.socketpair()
        with outbound, peer, patch('hlauncher.plugin_sandbox.socket.create_connection',
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
