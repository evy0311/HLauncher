"""Exercise the setup and settings lock with simulated HondaLink data."""
from pathlib import Path
import json
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

from hlauncher.bootstrap import BootstrapLauncher
from hlauncher.catalog import Manifest
from hlauncher.config import Preferences, SAFETY_NOTICE_VERSION
from hlauncher.launcher import Launcher
from hlauncher.protocol.vehicle_can import SCOPED_API_IDS, decode_records, subscription_rows
from hlauncher.protocol_diagnostics import ProtocolDiagnostics
from test_architecture import Display
from test_vehicle_can import can_data


class ParkedSettings(unittest.TestCase):
    def setUp(self):
        temp = self.enterContext(tempfile.TemporaryDirectory())
        self.prefs = Preferences(Path(temp) / 'settings.json')
        self.monitor = ProtocolDiagnostics(Path(temp) / 'captures')
        self.ui = Launcher(framebuffer=Display(), preferences=self.prefs, manifests={},
                           protocol_diagnostics=self.monitor)
        self.addCleanup(self.ui.close)

    def brake(self, engaged, at):
        with patch('hlauncher.protocol_diagnostics.time.monotonic', return_value=at):
            self.monitor.observe(dict(
                state='honda_frame', session=1, message=0x61,
                protocol=(0, 'jp.co.honda.rd.dispaudio.app.generals'),
                payload='10100000000000' if engaged else '10000000000000',
            ))

    def speed(self, kph, at):
        records = decode_records(can_data([(0x12F85050, bytes([kph]))]), api_ids=[152])
        with patch('hlauncher.protocol_diagnostics.time.monotonic', return_value=at):
            self.monitor.observe(dict(state='honda_can_data', session=1, records=records))

    def test_setup_allows_missing_data_and_locks_on_reported_motion(self):
        self.ui.start()
        self.assertFalse(self.ui.parked_screen_locked)
        self.assertTrue(self.ui.actions)
        self.ui.accept_safety_notice()
        self.assertFalse(self.prefs.safety_notice_accepted)

        bootstrap = BootstrapLauncher.__new__(BootstrapLauncher)
        bootstrap.ui = self.ui
        self.assertEqual(bootstrap.vehicle_scope(), 'driving_identity')

        now = time.monotonic()
        self.monitor.observe(dict(state='connected', uuid='test-cafe'))
        self.brake(True, now)
        self.speed(10, now)
        self.ui.tick()
        self.assertTrue(self.ui.parked_screen_locked)

        self.speed(0, time.monotonic())
        self.ui.tick()
        self.assertFalse(self.ui.parked_screen_locked)
        self.ui.accept_safety_notice()
        self.assertFalse(self.prefs.safety_notice_accepted)
        self.assertNotIn(self.ui.accept_safety_notice, [callback for _, callback in self.ui.actions])
        self.touch('down', 360, 315)
        self.touch('move', 360, 295)
        self.touch('up', 360, 295)
        self.assertGreater(self.ui.scroll_view['offset'], 0)
        self.assertLess(self.ui.scroll_view['offset'], self.ui.scroll_view['maximum'])
        self.touch('down', 360, 315)
        self.touch('move', 360, 160)
        self.touch('up', 360, 160)
        self.assertEqual(self.ui.scroll_view['offset'], self.ui.scroll_view['maximum'])
        self.touch('down', 556, 434)
        self.touch('up', 556, 434)
        self.assertEqual(self.ui.mode, 'onboarding')
        self.assertEqual(self.prefs.data['safety_notice_version'], SAFETY_NOTICE_VERSION)

        self.monitor.observe(dict(state='closed', uuid='test-cafe'))
        self.ui.tick()
        self.assertFalse(self.ui.parked_screen_locked)
        self.assertTrue(self.ui.actions)

    def touch(self, action, x, y):
        contact = dict(slot=0, action=action, has_position=True,
                       x_raw=round(x * 32767 / 719), y_raw=round(y * 32767 / 479))
        self.ui.update({'contacts': [contact]})

    def test_agreement_that_fits_can_be_accepted_without_scrolling(self):
        self.monitor.observe(dict(state='connected', uuid='test-cafe'))
        now = time.monotonic()
        self.brake(True, now)
        self.speed(0, now)
        with patch('hlauncher.ui.onboarding.SAFETY_AGREEMENT_LINES', ('A short agreement.',)):
            self.ui.start()
            self.assertEqual(self.ui.scroll_view['maximum'], 0)
            self.touch('down', 556, 434)
            self.touch('up', 556, 434)
        self.assertTrue(self.prefs.safety_notice_accepted)

    def test_safe_reports_do_not_expire_out_of_the_parking_gate(self):
        self.monitor.observe(dict(state='connected', uuid='test-cafe'))
        self.brake(True, 100)
        self.speed(0, 104)
        self.assertTrue(self.monitor.parked_for_setup(105))
        self.assertTrue(self.monitor.parked_for_setup(106))

        self.speed(0, 106)
        self.assertTrue(self.monitor.parked_for_setup(106))
        self.brake(True, 106)
        self.assertTrue(self.monitor.parked_for_setup(106))
        self.assertTrue(self.monitor.parked_for_setup(108))
        self.assertFalse(self.monitor.parking_snapshot(108)['brake_only'])
        self.assertTrue(self.monitor.parked_for_setup(1000))
        state = self.monitor.plugin_parking_state(1000)
        self.assertTrue(state['safely_parked'])
        self.assertIsNone(state['speed_kph'])
        self.assertIsNone(state['parking_brake'])

    def test_confirmed_brake_unlocks_settings_without_speed(self):
        self.prefs.data['setup_complete'] = True
        self.prefs.accept_safety_notice()
        self.monitor.observe(dict(state='connected', uuid='test-cafe'))
        self.brake(True, time.monotonic())
        self.ui.settings()
        self.assertFalse(self.ui.parked_screen_locked)
        self.assertEqual(self.monitor.parked_setup_readings(), (None, True))
        self.assertTrue(self.monitor.parking_snapshot()['brake_only'])
        self.assertIn(self.ui.system_settings, [callback for _, callback in self.ui.actions])
        self.assertIsNone(self.monitor.projection_vehicle_state()['speed_kph'])

    def test_parked_plugin_allows_no_frames_and_closes_on_reported_unsafe_state(self):
        folder = self.prefs.path.parent
        (folder / 'worker.py').touch()
        (folder / 'plugin.json').write_text(json.dumps(dict(
            api_version=1, id='vehicle', name='Vehicle', entrypoint=['python3', 'worker.py'],
            capabilities=['touch', 'vehicle.parking'], requires_parked=True, default_enabled=True,
        )))
        self.ui.manifests['vehicle'] = Manifest.load(folder, bundled=True)
        self.prefs.data['setup_complete'] = True
        self.prefs.accept_safety_notice()
        worker = Mock(manifest=self.ui.manifests['vehicle'], last_parking_state=None, car_gps=False)
        worker.proc.poll.return_value = None
        worker.read.return_value = []
        with patch('hlauncher.plugin_host.Worker', return_value=worker) as start:
            self.ui.open_plugin('vehicle')
            start.assert_called_once()
            self.assertEqual(self.ui.host.active, 'vehicle')
            worker.send.assert_any_call(type='vehicle.parking', connected=False, speed_kph=None,
                                        parking_brake=None, safely_parked=True)
            self.monitor.observe(dict(state='connected', uuid='test-cafe'))
            self.speed(5, time.monotonic())
            self.ui.host.touch({'contacts': []})
            worker.close.assert_called_once()
            self.assertFalse(any(call.kwargs.get('type') == 'touch' for call in worker.send.call_args_list))
            self.assertEqual(self.ui.mode, 'parked_plugin')
            self.assertNotIn('vehicle', self.ui.host.workers)
            self.assertTrue(self.ui.parked_screen_locked)

            self.speed(0, time.monotonic())
            with patch.object(self.ui.host, 'tick'):
                self.ui.tick()
            self.assertEqual(self.ui.host.active, 'vehicle')
            with patch('hlauncher.protocol_diagnostics.time.monotonic', return_value=time.monotonic() + 60):
                worker.last_message = time.monotonic()
                self.ui.host.tick()
            self.assertEqual(worker.close.call_count, 1)
            self.monitor.observe(dict(state='closed', uuid='test-cafe'))
            self.ui.host.session_changed(connected=False)
            self.assertEqual(worker.close.call_count, 1)
            self.assertEqual(self.ui.host.active, 'vehicle')

            self.monitor.observe(dict(state='connected', uuid='test-cafe'))
            self.brake(False, time.monotonic())
            self.ui.host.touch({'contacts': []})
            self.assertEqual(worker.close.call_count, 2)
            self.assertEqual(self.ui.mode, 'parked_plugin')
            self.brake(True, time.monotonic())
            self.ui.open_plugin('vehicle')
            self.assertEqual(self.ui.host.active, 'vehicle')

    def test_plugin_gate_retains_unsafe_inputs_through_expiry_and_disconnect(self):
        self.assertTrue(self.monitor.plugin_parking_state(100)['safely_parked'])
        self.monitor.observe(dict(state='connected', uuid='test-cafe'))
        self.brake(False, 100)
        self.speed(10, 100)
        self.assertFalse(self.monitor.plugin_parking_state(101)['safely_parked'])
        self.monitor.observe(dict(state='honda_can_subscription_queued', session=1, scope='vehicle'))
        self.assertFalse(self.monitor.plugin_parking_state(300)['safely_parked'])
        self.monitor.observe(dict(state='closed', uuid='test-cafe'))
        state = self.monitor.plugin_parking_state(301)
        self.assertFalse(state['connected'])
        self.assertIsNone(state['speed_kph'])
        self.assertIsNone(state['parking_brake'])
        self.assertFalse(state['safely_parked'])
        self.assertFalse(self.monitor.parked_for_setup(301))
        self.monitor.observe(dict(state='connected', uuid='test-cafe'))
        self.speed(0, 302)
        self.assertFalse(self.monitor.plugin_parking_state(302)['safely_parked'])
        self.brake(True, 303)
        self.assertTrue(self.monitor.plugin_parking_state(303)['safely_parked'])
        self.assertTrue(self.monitor.parked_for_setup(303))

    def test_last_moving_speed_vetoes_brake_only_after_subscription_changes(self):
        self.monitor.observe(dict(state='connected', uuid='test-cafe'))
        self.brake(True, 100)
        self.speed(10, 100)
        self.assertFalse(self.monitor.parked_for_setup(100))
        self.assertFalse(self.monitor.parked_for_setup(103))
        self.monitor.observe(dict(state='honda_can_subscription_queued', session=1))
        self.assertFalse(self.monitor.parked_for_setup(103))
        self.speed(0, 103)
        self.assertTrue(self.monitor.parked_for_setup(103))

        self.speed(10, 104)
        self.monitor.observe(dict(state='closed', uuid='test-cafe'))
        self.monitor.observe(dict(state='connected', uuid='test-cafe'))
        self.assertFalse(self.monitor.parked_for_setup(105))
        self.brake(True, 105)
        self.assertFalse(self.monitor.parked_for_setup(105))
        self.speed(0, 105)
        self.assertTrue(self.monitor.parked_for_setup(105))

    def test_settings_allows_missing_brake_until_a_released_brake_is_reported(self):
        self.ui.start()
        self.monitor.observe(dict(state='connected', uuid='test-cafe'))
        self.speed(0, time.monotonic())
        self.ui.tick()
        self.assertFalse(self.ui.parked_screen_locked)
        self.assertIsNone(self.ui.parked_overlay_at)

        self.brake(False, time.monotonic())
        self.ui.tick()
        self.assertTrue(self.ui.parked_screen_locked)
        self.brake(True, time.monotonic())
        self.ui.tick()
        self.assertFalse(self.ui.parked_screen_locked)

    def test_warning_double_tap_opens_only_readings_and_close_restores_lock(self):
        self.monitor.observe(dict(state='connected', uuid='test-cafe'))
        self.brake(False, time.monotonic())
        self.ui.start()
        self.touch('down', 360, 148)
        self.ui.update({'contacts': [{'slot': 0, 'action': 'up', 'has_position': False}]})
        self.assertEqual(self.ui.mode, 'safety_notice')
        self.assertTrue(self.ui.parked_screen_locked)
        self.touch('down', 360, 148)
        self.ui.update({'contacts': [{'slot': 0, 'action': 'up', 'has_position': False}]})

        self.assertEqual(self.ui.mode, 'parking_status')
        self.assertEqual([callback for _, callback in self.ui.actions], [self.ui.close_parking_status])
        bootstrap = BootstrapLauncher.__new__(BootstrapLauncher)
        bootstrap.ui = self.ui
        self.assertEqual(bootstrap.vehicle_scope(), 'driving_parking_identity')
        self.assertFalse(self.monitor.recording)

        self.touch('down', 664, 85)
        self.touch('up', 664, 85)
        self.assertEqual(self.ui.mode, 'safety_notice')
        self.assertTrue(self.ui.parked_screen_locked)
        self.assertEqual(self.ui.actions, [])
        self.assertFalse(self.prefs.safety_notice_accepted)
        self.assertEqual(bootstrap.vehicle_scope(), 'driving_identity')

    def test_parking_status_is_under_system_debug_diagnostics(self):
        self.prefs.data['setup_complete'] = True
        self.prefs.accept_safety_notice()
        self.monitor.observe(dict(state='connected', uuid='test-cafe'))
        now = time.monotonic()
        self.brake(True, now)
        self.speed(0, now)
        self.ui.settings()
        self.assertFalse(self.prefs.data['debug_mode'])
        self.assertNotIn(self.ui.diagnostics_menu, [callback for _, callback in self.ui.actions])
        next(callback for _, callback in self.ui.actions if callback == self.ui.system_settings)()
        self.assertNotIn(self.ui.debug_tools, [callback for _, callback in self.ui.actions])
        self.ui.toggle_debug()
        next(callback for _, callback in self.ui.actions if callback == self.ui.debug_tools)()
        next(callback for _, callback in self.ui.actions if callback == self.ui.diagnostics_menu)()
        next(callback for _, callback in self.ui.actions if callback == self.ui.open_parking_status)()
        self.assertEqual(self.ui.mode, 'parking_status')
        self.ui.close_parking_status()
        self.assertEqual(self.ui.mode, 'diagnostics_menu')

    def test_candidate_readings_are_scoped_without_requiring_a_radio_brake_report(self):
        scope = 'driving_parking'
        self.assertEqual({row['message_id'] for row in subscription_rows(scope)},
                         {0x158, 0x1A6, 0x12F85050, 0x12F85150, 0x12F97350})
        self.monitor.observe(dict(state='connected', uuid='test-cafe'))
        records = decode_records(can_data([(0x12F85050, bytes(6)),
                                          (0x12F85150, bytes.fromhex('4002000000'))]),
                                 api_ids=SCOPED_API_IDS[scope])
        self.monitor.observe(dict(state='honda_can_data', session=1, records=records))
        status = self.monitor.parking_snapshot()
        signals = {row['api_id']: row for row in status['can_signals']}
        self.assertTrue(signals[80]['value'])
        self.assertEqual(signals[80]['source']['signal'], 'C_PBRAKE')
        self.assertTrue(signals[100]['value'])
        self.assertFalse(signals[78]['received'])
        self.assertIsNone(status['radio_brake'])
        self.assertTrue(status['parked'])
        self.assertTrue(status['assumed_parked'])
        self.monitor.observe(dict(state='closed', uuid='test-cafe'))
        self.assertFalse(any(row['received'] for row in self.monitor.parking_snapshot()['can_signals']))

    def test_reading_gap_does_not_cancel_a_pressed_setting(self):
        self.prefs.data['setup_complete'] = True
        self.prefs.accept_safety_notice()
        self.monitor.observe(dict(state='connected', uuid='test-cafe'))
        now = time.monotonic()
        self.brake(True, now)
        self.speed(0, now)
        self.ui.appearance_settings()
        box = next(box for box, callback in self.ui.actions if callback == self.ui.toggle_clock)
        x, y = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
        self.touch('down', x, y)
        with patch('hlauncher.launcher.time.monotonic', return_value=now + 60):
            self.touch('up', x, y)
            self.assertFalse(self.ui.parked_screen_locked)
            self.assertTrue(self.prefs.data['show_clock'])
            self.assertIsNone(self.ui.parked_overlay_at)

    def test_sustained_reading_gap_keeps_settings_available(self):
        self.prefs.data['setup_complete'] = True
        self.prefs.accept_safety_notice()
        self.monitor.observe(dict(state='connected', uuid='test-cafe'))
        now = time.monotonic()
        self.brake(True, now)
        self.speed(0, now)
        self.ui.appearance_settings()
        with patch('hlauncher.launcher.time.monotonic', return_value=now + 60):
            self.ui.tick()
            self.assertFalse(self.ui.parked_screen_locked)
            self.assertIn(self.ui.toggle_clock, [callback for _, callback in self.ui.actions])
            self.assertIsNone(self.ui.parked_overlay_at)
            self.speed(1, now + 60)
            self.ui.tick()
            self.assertTrue(self.ui.parked_screen_locked)
            self.assertEqual([callback for _, callback in self.ui.actions], [self.ui.home])

    def test_brake_release_cancels_a_pressed_setting_and_home_is_available(self):
        self.prefs.data['setup_complete'] = True
        self.prefs.accept_safety_notice()
        self.ui.home()
        self.monitor.observe(dict(state='connected', uuid='test-cafe'))
        now = time.monotonic()
        self.brake(True, now)
        self.speed(0, now)
        self.ui.appearance_settings()
        self.assertFalse(self.ui.parked_screen_locked)

        box = next(box for box, callback in self.ui.actions if callback == self.ui.toggle_clock)
        x, y = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
        contact = dict(slot=0, has_position=True, x_raw=round(x * 32767 / 719),
                       y_raw=round(y * 32767 / 479))
        self.ui.update({'contacts': [dict(contact, action='down')]})
        self.assertEqual(self.ui.pressed_box, box)

        self.brake(False, time.monotonic())
        self.ui.update({'contacts': [dict(contact, action='up')]})
        self.assertTrue(self.ui.parked_screen_locked)
        self.assertFalse(self.prefs.data['show_clock'])
        self.assertEqual([callback for _, callback in self.ui.actions], [self.ui.home])
        self.ui.actions[0][1]()
        self.assertEqual(self.ui.mode, 'home')
        self.assertFalse(self.ui.parked_screen_locked)

    def test_projection_and_device_picker_work_while_driving_but_settings_lock(self):
        import hashlib
        from hlauncher.config import ROOT

        self.prefs.data['setup_complete'] = True
        self.prefs.accept_safety_notice()
        self.monitor.observe(dict(state='connected', uuid='test-cafe'))
        self.speed(25, time.monotonic())
        self.brake(False, time.monotonic())
        self.ui.manifests.update({ident: Manifest.load(ROOT/'plugins'/ident, bundled=True)
                                 for ident in ('carplay', 'android-auto')})
        for ident in ('carplay', 'android-auto'):
            self.ui.open_plugin(ident)
            self.assertEqual(self.ui.mode, 'phone_projection')
            self.assertFalse(self.ui.parked_screen_locked)
        bootstrap = BootstrapLauncher.__new__(BootstrapLauncher)
        bootstrap.ui = self.ui
        self.assertEqual(bootstrap.vehicle_scope(), 'driving_identity')

        address = '02:00:00:00:00:01'
        key = hashlib.sha256(address.encode()).hexdigest()[:24]
        self.ui.host.projection_phones.update([dict(id=key, address=address, name='Saved phone', paired=True)])
        self.touch('down', 596, 436)
        self.touch('up', 596, 436)
        self.assertTrue(self.ui.projection_devices_open)
        self.assertFalse(self.ui.parked_screen_locked)
        self.assertNotIn(self.ui.projection_settings_page, [action for _, action in self.ui.actions])
        with patch.object(self.ui.host, 'connect_phone', return_value='fixture-request') as connect:
            self.touch('down', 300, 206)
            self.touch('up', 300, 206)
            connect.assert_called_once_with(key)
        self.assertEqual(self.ui.projection_device_key, key)
        self.assertFalse(self.ui.parked_screen_locked)
        self.touch('down', 608, 120)
        self.touch('up', 608, 120)
        self.assertFalse(self.ui.projection_devices_open)
        self.touch('down', 52, 436)
        self.touch('up', 52, 436)
        self.assertEqual(self.ui.mode, 'projection_settings')
        self.assertTrue(self.ui.parked_screen_locked)
