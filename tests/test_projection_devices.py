"""Exercise the on-page device picker without a phone or USB dongle."""
import hashlib
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from hlauncher.catalog import Manifest
from hlauncher.config import Preferences, ROOT
from hlauncher.launcher import Launcher
from hlauncher.protocol_diagnostics import ProtocolDiagnostics
from hlauncher.ui.pages import projection_phone_status
from test_architecture import Display


class Devices(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.object(ProtocolDiagnostics, 'parked_for_setup', return_value=True))
        folder = Path(self.enterContext(tempfile.TemporaryDirectory()))
        prefs = Preferences(folder/'settings.json')
        prefs.data['setup_complete'] = True
        prefs.accept_safety_notice()
        manifests = {ident: Manifest.load(ROOT/'plugins'/ident, bundled=True)
                     for ident in ('carplay', 'android-auto')}
        self.ui = Launcher(framebuffer=Display(), preferences=prefs, manifests=manifests)
        self.addCleanup(self.ui.close)
        self.ui.projection_page()

    def phones(self, count):
        records = []
        for index in range(count):
            address = f'02:00:00:00:00:{index+1:02X}'
            key = hashlib.sha256(address.encode()).hexdigest()[:24]
            records.append(dict(id=key, address=address, name=f'Saved phone {index+1}', paired=True))
        self.ui.host.projection_phones.update(records)
        return [record['id'] for record in records]

    def test_modal_pages_select_the_right_phone_and_hide_background_actions(self):
        ui = self.ui
        keys = self.phones(5)
        ui.open_projection_devices()
        self.assertEqual(len(ui.actions), 5)  # Close, three phones, next page.
        self.assertNotIn(ui.home, [action for _, action in ui.actions])
        self.assertNotIn(ui.projection_settings_page, [action for _, action in ui.actions])
        for action in ('down', 'up'):
            ui.update({'contacts': [dict(slot=0, action=action, has_position=True,
                       x_raw=round(52*32767/719), y_raw=round(436*32767/479))]})
        self.assertEqual(ui.mode, 'phone_projection')
        self.assertTrue(ui.projection_devices_open)
        ui.actions[-1][1]()
        self.assertEqual(ui.projection_devices_index, 1)
        with patch.object(ui.host, 'connect_phone', return_value='request') as connect:
            ui.actions[1][1]()
            connect.assert_called_once_with(keys[3])
        self.assertTrue(ui.projection_devices_open)
        self.assertEqual(ui.projection_phone_request[:2], (keys[3], 'request'))
        ui.actions[0][1]()
        self.assertFalse(ui.projection_devices_open)
        self.assertIn(ui.open_projection_devices, [action for _, action in ui.actions])

    def test_empty_modal_only_has_close_and_scaled_rows_stay_inside_the_modal(self):
        ui = self.ui
        ui.open_projection_devices()
        self.assertEqual([action for _, action in ui.actions], [ui.close_projection_devices])
        self.phones(32)
        ui.fb.w, ui.fb.h = 800, 480
        ui.projection_devices_index = 99
        ui.draw()
        self.assertEqual(ui.projection_devices_index, 10)
        self.assertEqual(ui.fb.last.size, (800, 480))
        for index, ((left, top, right, bottom), _) in enumerate(ui.actions):
            self.assertTrue(64*800/720 <= left < right <= 656*800/720)
            self.assertTrue(80 <= top < bottom <= 456)
            for (x, y, r, b), _ in ui.actions[index+1:]:
                self.assertFalse(left < r and x < right and top < b and y < bottom)

    def test_errors_and_matching_request_timeouts_are_shown_without_closing(self):
        ui = self.ui
        key, = self.phones(1)
        ui.open_projection_devices()
        with patch.object(ui.host, 'connect_phone', side_effect=ValueError('Connect the dongle first')):
            ui.select_projection_device(key)
        self.assertEqual(ui.projection_device_notice, 'Connect the dongle first')
        self.assertTrue(ui.projection_devices_open)
        with patch.object(ui.host, 'connect_phone', return_value='new-request'):
            ui.select_projection_device(key)
        worker = SimpleNamespace(metrics=dict(phone_connection=dict(
            phone_id=key, request_id='old-request', result='connected')))
        with patch.object(ui.host, 'workers', {'carplay': worker}):
            self.assertEqual(projection_phone_status(ui, key, 'Connection requested'), 'Connection requested')
            with patch('hlauncher.ui.pages.time.monotonic', return_value=ui.projection_phone_request[2]+1):
                self.assertIn('timed out', projection_phone_status(ui, key, 'Connection requested'))
            worker.metrics['phone_connection'].update(request_id='new-request', result='failed', reason='connection_timeout')
            self.assertEqual(projection_phone_status(ui, key, ''), 'Selected phone did not connect')

    def test_connected_old_phone_does_not_replace_modal_but_selected_phone_does(self):
        ui = self.ui
        old, selected = self.phones(2)
        ui.host.projection_phones.live = {old}
        ui.open_projection_devices()
        worker = SimpleNamespace(manifest=ui.manifests['carplay'], metrics={'phone_connected': True})
        ui.projection_checked = ui.projection_appearance_checked = ui.setup_redraw = time.monotonic()
        with patch.object(ui.host, 'workers', {'carplay': worker}), patch.object(ui.host, 'tick'), \
                patch.object(ui, 'open_plugin') as opened:
            ui.tick()
            opened.assert_not_called()
            with patch.object(ui.host, 'connect_phone', return_value='request'):
                ui.select_projection_device(selected)
            ui.tick()
            opened.assert_not_called()
            ui.host.projection_phones.live = {selected}
            ui.tick()
            opened.assert_called_once_with('carplay', projection_engine=True)
            self.assertFalse(ui.projection_devices_open)

    def test_usb_arrival_starts_in_background_while_the_modal_is_open(self):
        ui = self.ui
        ui.open_projection_devices()
        ui.projection_checked = 0
        with patch('hlauncher.projection.direct_android_devices', return_value={'1-2'}), \
                patch.object(ui.host, 'tick'), patch.object(ui.host, 'request_projection') as request:
            ui.tick()
            request.assert_called_once_with('android-auto', False)
        self.assertEqual(ui.mode, 'phone_projection')
        self.assertTrue(ui.projection_devices_open)
