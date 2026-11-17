"""Exercise the setup and settings lock with simulated HondaLink data."""
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from hlauncher.bootstrap import BootstrapLauncher
from hlauncher.config import Preferences, SAFETY_NOTICE_VERSION
from hlauncher.launcher import Launcher
from hlauncher.protocol_diagnostics import ProtocolDiagnostics
from test_architecture import Display


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
        self.monitor.vehicle.signals.update([
            dict(can_id=0x12F85050, data=bytes([kph, 0, 0, 0, 0, 0]).hex(), api_ids=[152]),
        ], at, 1)

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

    def test_brake_heartbeat_and_stale_speed(self):
        self.monitor.observe(dict(state='connected', uuid='test-cafe'))
        self.brake(True, 100)
        self.speed(0, 104)
        self.assertTrue(self.monitor.parked_for_setup(105))
        self.assertFalse(self.monitor.parked_for_setup(106))

        self.speed(0, 106)
        self.assertFalse(self.monitor.parked_for_setup(106))
        self.brake(True, 106)
        self.assertTrue(self.monitor.parked_for_setup(106))
        self.assertFalse(self.monitor.parked_for_setup(108))

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
