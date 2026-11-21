"""Connection-driven foregrounding is independent of Startup and respects apps."""
from contextlib import contextmanager
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from hlauncher.config import Preferences
from tools.desktop_simulator.runtime import Simulator


class ProjectionAutoLaunch(unittest.TestCase):
    @contextmanager
    def simulator(self, enabled=True):
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            prefs = Preferences(folder/'settings.json')
            prefs.data.update(setup_complete=True, projection_auto_launch=enabled, default_plugin=None)
            prefs.accept_safety_notice()
            simulator = Simulator(folder)
            try:
                yield simulator
            finally:
                simulator.close()

    def test_home_startup_opens_each_projection_route_once_when_connected(self):
        for phone, engine in (('carplay', 'carplay'), ('android-dongle', 'carplay'),
                              ('android-usb', 'android-auto')):
            with self.subTest(phone=phone), self.simulator() as sim:
                ui = sim.ui
                self.assertEqual(ui.mode, 'home')
                self.assertTrue(ui.projection_auto_launch_pending)
                sim.set_state(dict(phone=phone))
                self.assertEqual((ui.mode, ui.host.active), ('plugin', engine))
                self.assertFalse(ui.projection_auto_launch_pending)
                self.assertIsNone(ui.prefs.data['default_plugin'])
                ui.home()
                sim.tick()
                self.assertEqual(ui.mode, 'home')
                sim.set_state(dict(phone='none'))
                sim.set_state(dict(phone=phone))
                self.assertEqual(ui.mode, 'home')

    def test_disabled_option_keeps_connected_phone_in_background(self):
        with self.simulator(False) as sim:
            sim.set_state(dict(phone='carplay'))
            self.assertEqual(sim.ui.mode, 'home')
            self.assertIsNone(sim.ui.host.active)

    def test_opening_an_app_cancels_even_after_returning_home(self):
        for app in ('obd', 'vehicle', 'carplay'):
            with self.subTest(app=app), self.simulator() as sim:
                sim.ui.open_plugin(app)
                self.assertFalse(sim.ui.projection_auto_launch_pending)
                sim.ui.home()
                sim.set_state(dict(phone='carplay'))
                self.assertEqual(sim.ui.mode, 'home')

    def test_usb_android_does_not_replace_another_foreground_app(self):
        with self.simulator() as sim:
            ui = sim.ui
            ui.open_plugin('vehicle')
            self.assertEqual(ui.host.active, 'vehicle')
            sim.values['phone'] = 'android-usb'
            ui.projection_checked = 0
            ui.projection_usb_devices = set()
            with patch.object(ui.host, 'request_projection') as request:
                sim.tick()
                request.assert_called_once_with('android-auto', False)
            sim.set_state(dict(phone='android-usb'))
            self.assertEqual((ui.mode, ui.host.active), ('plugin', 'vehicle'))
            self.assertTrue(ui.host.workers['android-auto'].metrics['phone_connected'])

    def test_setting_can_rearm_and_settings_navigation_cancels(self):
        with self.simulator() as sim:
            ui = sim.ui
            ui.settings()
            self.assertFalse(ui.projection_auto_launch_pending)
            ui.home()
            sim.set_state(dict(phone='carplay'))
            self.assertEqual(ui.mode, 'home')
            ui.projection_settings_page()
            ui.toggle_projection_auto_launch()  # Off.
            ui.toggle_projection_auto_launch()  # On, armed for the next connection.
            ui.projection_page()
            ui.home()
            sim.tick()
            self.assertEqual((ui.mode, ui.host.active), ('plugin', 'carplay'))

    def test_waits_for_setup_and_allows_projection_when_driving(self):
        with self.simulator() as sim:
            ui = sim.ui
            ui.prefs.data['setup_complete'] = False
            sim.set_state(dict(phone='carplay'))
            self.assertNotEqual(ui.mode, 'plugin')
            ui.prefs.data['setup_complete'] = True
            ui.home()
            sim.set_state(dict(speed=25, brake=False))
            self.assertEqual((ui.mode, ui.host.active), ('plugin', 'carplay'))

    def test_startup_app_takes_precedence_over_connection_auto_launch(self):
        with self.simulator() as sim:
            ui = sim.ui
            ui.prefs.data['default_plugin'] = 'vehicle'
            ui.show_start_page()
            sim.set_state(dict(phone='carplay'))
            self.assertEqual((ui.mode, ui.host.active), ('plugin', 'vehicle'))
            self.assertFalse(ui.projection_auto_launch_pending)

    def test_preference_is_opt_in_persistent_and_rolls_back_a_failed_save(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'settings.json'
            prefs = Preferences(path)
            self.assertFalse(prefs.data['projection_auto_launch'])
            prefs.set_projection_auto_launch(True)
            self.assertTrue(Preferences(path).data['projection_auto_launch'])
            self.assertIsNone(Preferences(path).data['default_plugin'])
            with patch.object(prefs, 'save', side_effect=OSError('Read-only storage')):
                with self.assertRaises(OSError):
                    prefs.set_projection_auto_launch(False)
            self.assertTrue(prefs.data['projection_auto_launch'])
            path.write_text(json.dumps({'projection_auto_launch': 'true'}))
            self.assertFalse(Preferences(path).data['projection_auto_launch'])
