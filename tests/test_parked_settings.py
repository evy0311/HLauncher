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
        self.monitor.vehicle.observe(dict(
            session=1, message=0x61, protocol=(0, 'jp.co.honda.rd.dispaudio.app.generals'),
            payload='10100000000000' if engaged else '10000000000000', monotonic=at,
        ))

    def speed(self, kph, at):
        records = decode_records(can_data([(0x12F85050, bytes([kph]))]), api_ids=[152])
        with patch('hlauncher.protocol_diagnostics.time.monotonic', return_value=at):
            self.monitor.observe(dict(state='honda_can_data', session=1, records=records))

    def test_setup_requires_connection_brake_and_zero_speed(self):
        self.ui.start()
        self.assertTrue(self.ui.parked_screen_locked)
        self.assertEqual(self.ui.actions, [])
        self.ui.accept_safety_notice()
        self.assertFalse(self.prefs.safety_notice_accepted)

        bootstrap = BootstrapLauncher.__new__(BootstrapLauncher)
        bootstrap.ui = self.ui
        self.assertEqual(bootstrap.vehicle_scope(), 'driving')

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
        self.assertTrue(self.ui.parked_screen_locked)
        self.assertEqual(self.ui.actions, [])

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

    def test_brake_heartbeat_and_brake_only_with_stale_zero_speed(self):
        self.monitor.observe(dict(state='connected', uuid='test-cafe'))
        self.brake(True, 100)
        self.speed(0, 104)
        self.assertTrue(self.monitor.parked_for_setup(105))
        self.assertFalse(self.monitor.parked_for_setup(106))

        self.speed(0, 106)
        self.assertFalse(self.monitor.parked_for_setup(106))
        self.brake(True, 106)
        self.assertTrue(self.monitor.parked_for_setup(106))
        self.assertTrue(self.monitor.parked_for_setup(108))
        self.assertTrue(self.monitor.parking_snapshot(108)['brake_only'])

    def test_confirmed_brake_unlocks_settings_without_speed(self):
        self.prefs.data['setup_complete'] = True
        self.prefs.accept_safety_notice()
        self.monitor.observe(dict(state='connected', uuid='test-cafe'))
        self.brake(True, time.monotonic())
        self.ui.settings()
        self.assertFalse(self.ui.parked_screen_locked)
        self.assertEqual(self.monitor.parked_setup_readings(), (None, True))
        self.assertTrue(self.monitor.parking_snapshot()['brake_only'])
        self.assertIn(self.ui.diagnostics_menu, [callback for _, callback in self.ui.actions])
        self.assertIsNone(self.monitor.projection_vehicle_state()['speed_kph'])

    def test_parked_plugin_needs_both_live_signals_and_closes_when_moving(self):
        folder = self.prefs.path.parent
        (folder / 'worker.py').touch()
        (folder / 'plugin.json').write_text(json.dumps(dict(
            api_version=1, id='vehicle', name='Vehicle', entrypoint=['python3', 'worker.py'],
            capabilities=['touch', 'vehicle.parking'], requires_parked=True, default_enabled=True,
        )))
        self.ui.manifests['vehicle'] = Manifest.load(folder, bundled=True)
        self.prefs.data['setup_complete'] = True
        self.prefs.accept_safety_notice()
        self.monitor.observe(dict(state='connected', uuid='test-cafe'))
        now = time.monotonic()
        self.brake(True, now)

        worker = Mock(manifest=self.ui.manifests['vehicle'], last_parking_state=None, car_gps=False)
        with patch('hlauncher.plugin_host.Worker', return_value=worker) as start:
            self.assertTrue(self.monitor.parked_for_setup())
            self.ui.open_plugin('vehicle')
            start.assert_not_called()
            self.assertEqual(self.ui.mode, 'home')
            self.assertEqual(self.ui.banner, 'Park safely to open Vehicle.')

            self.speed(0, now)
            self.ui.open_plugin('vehicle')
            start.assert_called_once()
            self.assertEqual(self.ui.host.active, 'vehicle')
            worker.send.assert_any_call(type='vehicle.parking', connected=True, speed_kph=0,
                                        parking_brake=True, safely_parked=True)
            bootstrap = BootstrapLauncher.__new__(BootstrapLauncher)
            bootstrap.ui = self.ui
            self.assertEqual(bootstrap.vehicle_scope(), 'driving')

            self.speed(5, time.monotonic())
            self.ui.host.touch({'contacts': []})
            worker.close.assert_called_once()
            self.assertFalse(any(call.kwargs.get('type') == 'touch' for call in worker.send.call_args_list))
            self.assertEqual(self.ui.mode, 'home')
            self.assertNotIn('vehicle', self.ui.host.workers)

            self.speed(0, time.monotonic())
            self.ui.open_plugin('vehicle')
            self.assertEqual(self.ui.host.active, 'vehicle')
            with patch('hlauncher.protocol_diagnostics.time.monotonic', return_value=time.monotonic() + 2.1):
                self.ui.host.tick()
            self.assertEqual(worker.close.call_count, 2)
            self.assertEqual(self.ui.mode, 'home')

    def test_plugin_parked_state_expires_and_clears_on_disconnect(self):
        self.monitor.observe(dict(state='connected', uuid='test-cafe'))
        self.brake(True, 100)
        self.speed(0, 100)
        self.assertTrue(self.monitor.plugin_parking_state(101)['safely_parked'])
        self.monitor.observe(dict(state='honda_can_subscription_queued', session=1, scope='vehicle'))
        self.assertTrue(self.monitor.plugin_parking_state(101)['safely_parked'])
        self.assertFalse(self.monitor.plugin_parking_state(102)['safely_parked'])
        self.speed(0, 106)
        self.assertFalse(self.monitor.plugin_parking_state(106)['safely_parked'])
        self.brake(True, 106)
        self.assertTrue(self.monitor.plugin_parking_state(106)['safely_parked'])
        self.monitor.observe(dict(state='closed', uuid='test-cafe'))
        self.assertFalse(self.monitor.plugin_parking_state(106)['safely_parked'])

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
        self.assertTrue(self.monitor.parked_for_setup(105))

    def test_settings_waits_for_first_brake_status(self):
        self.ui.start()
        self.monitor.observe(dict(state='connected', uuid='test-cafe'))
        self.speed(0, time.monotonic())
        self.ui.tick()
        self.assertTrue(self.ui.parked_screen_locked)
        self.assertIsNone(self.ui.parked_overlay_at)

        self.brake(False, time.monotonic())
        self.ui.tick()
        self.assertTrue(self.ui.parked_screen_locked)
        self.brake(True, time.monotonic())
        self.ui.tick()
        self.assertFalse(self.ui.parked_screen_locked)

    def test_warning_double_tap_opens_only_readings_and_close_restores_lock(self):
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
        self.assertEqual(bootstrap.vehicle_scope(), 'driving_parking')
        self.assertFalse(self.monitor.recording)

        self.touch('down', 664, 85)
        self.touch('up', 664, 85)
        self.assertEqual(self.ui.mode, 'safety_notice')
        self.assertTrue(self.ui.parked_screen_locked)
        self.assertEqual(self.ui.actions, [])
        self.assertFalse(self.prefs.safety_notice_accepted)
        self.assertEqual(bootstrap.vehicle_scope(), 'driving')

    def test_parking_status_can_be_opened_from_settings_with_debug_off(self):
        self.prefs.data['setup_complete'] = True
        self.prefs.accept_safety_notice()
        self.monitor.observe(dict(state='connected', uuid='test-cafe'))
        now = time.monotonic()
        self.brake(True, now)
        self.speed(0, now)
        self.ui.settings()
        self.assertFalse(self.prefs.data['debug_mode'])
        next(callback for _, callback in self.ui.actions if callback == self.ui.diagnostics_menu)()
        next(callback for _, callback in self.ui.actions if callback == self.ui.open_parking_status)()
        self.assertEqual(self.ui.mode, 'parking_status')
        self.ui.close_parking_status()
        self.assertEqual(self.ui.mode, 'diagnostics_menu')

    def test_candidate_readings_are_scoped_and_do_not_unlock_settings(self):
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
        self.assertFalse(status['parked'])
        self.monitor.observe(dict(state='closed', uuid='test-cafe'))
        self.assertFalse(any(row['received'] for row in self.monitor.parking_snapshot()['can_signals']))

    def test_short_reading_gap_blocks_touches_without_flashing_the_overlay(self):
        self.prefs.data['setup_complete'] = True
        self.prefs.accept_safety_notice()
        self.monitor.observe(dict(state='connected', uuid='test-cafe'))
        now = time.monotonic()
        self.brake(True, now)
        self.speed(0, now)
        self.ui.home()
        bootstrap = BootstrapLauncher.__new__(BootstrapLauncher)
        bootstrap.ui = self.ui
        self.assertEqual(bootstrap.vehicle_scope(), 'driving')
        self.ui.appearance_settings()
        self.assertEqual(bootstrap.vehicle_scope(), 'driving')
        box = next(box for box, callback in self.ui.actions if callback == self.ui.toggle_clock)
        x, y = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
        self.touch('down', x, y)
        settings_frame = self.ui.fb.last
        with patch('hlauncher.launcher.time.monotonic', return_value=now + 6.2):
            self.touch('up', x, y)
            self.assertTrue(self.ui.parked_screen_locked)
            self.assertIs(self.ui.fb.last, settings_frame)
            self.assertFalse(self.prefs.data['show_clock'])

            self.brake(True, now + 6.2)
            self.ui.tick()
            self.assertFalse(self.ui.parked_screen_locked)
            self.assertIn(self.ui.toggle_clock, [callback for _, callback in self.ui.actions])

        with patch('hlauncher.launcher.time.monotonic', return_value=now + 12.3):
            self.ui.tick()
            self.assertIsNotNone(self.ui.parked_overlay_at)
            self.speed(5, now + 12.3)
            self.ui.tick()
            self.assertIsNone(self.ui.parked_overlay_at)
            self.assertEqual([callback for _, callback in self.ui.actions], [self.ui.home])

    def test_sustained_reading_gap_shows_the_overlay(self):
        self.prefs.data['setup_complete'] = True
        self.prefs.accept_safety_notice()
        self.monitor.observe(dict(state='connected', uuid='test-cafe'))
        now = time.monotonic()
        self.brake(True, now)
        self.speed(0, now)
        self.ui.appearance_settings()

        with patch('hlauncher.launcher.time.monotonic', return_value=now + 6):
            self.ui.tick()
            self.assertTrue(self.ui.parked_screen_locked)
            self.assertEqual(self.ui.actions, [])
        with patch('hlauncher.launcher.time.monotonic', return_value=now + 7):
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
