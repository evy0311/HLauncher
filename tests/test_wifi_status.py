"""Wi-Fi link telemetry and header placement without touching the radio."""
import subprocess
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from PIL import ImageChops

from hlauncher.wifi_status import indicator, sample
from hlauncher.ui.chrome import render, clock_font
from hlauncher.ui.plugin_overlay import camera_header


class WifiStatus(unittest.TestCase):
    def test_radio_off_does_not_query_link(self):
        run = Mock(return_value=SimpleNamespace(stdout='disabled\n'))
        self.assertEqual(sample(run), {'wifi_link': 'off'})
        run.assert_called_once_with(['nmcli', 'radio', 'wifi'], timeout=3)

    def test_link_and_signal_are_independent_of_ip_address(self):
        run = Mock(side_effect=[SimpleNamespace(stdout='enabled\n'),
                               SimpleNamespace(stdout='Connected to aa:bb:cc:dd:ee:ff (on wlan0)\n signal: -64.5 dBm\n')])
        self.assertEqual(indicator(sample(run)), ('connected', 3))
        self.assertEqual(run.call_args.args[0], ['iw', 'dev', 'wlan0', 'link'])

    def test_disconnected_and_failed_reads_are_distinct(self):
        run = Mock(side_effect=[SimpleNamespace(stdout='enabled'),
                               SimpleNamespace(stdout='Not connected.\n')])
        self.assertEqual(indicator(sample(run)), ('disconnected', 0))
        run = Mock(side_effect=subprocess.TimeoutExpired('iw', 3))
        self.assertEqual(indicator(sample(run)), ('unknown', 0))
        self.assertEqual(indicator({}), ('unknown', 0))

    def test_strength_bands_and_missing_signal(self):
        for dbm, bars in ((-90, 1), (-80, 2), (-68, 2), (-67, 3), (-56, 3), (-55, 4), (-30, 4), (None, 0)):
            with self.subTest(dbm=dbm):
                self.assertEqual(indicator(dict(wifi_link='connected', wifi_signal_dbm=dbm)), ('connected', bars))

    def test_header_states_move_left_of_clock_without_changing_clock_pixels(self):
        for clock in (None, '8:05', '12:59'):
            with self.subTest(clock=clock):
                off = render('Red', clock=clock, show_clock=bool(clock), wifi=('off', 0))
                connected = render('Red', clock=clock, show_clock=bool(clock), wifi=('connected', 4))
                box = ImageChops.difference(off, connected).getbbox()
                self.assertGreater(box[0], 500)
                self.assertLess(box[3], 52)
                if clock:
                    self.assertLess(box[2], 698 - clock_font(39).getlength(clock))
                else:
                    self.assertGreater(box[2], 680)
                disconnected = render('Red', clock=clock, show_clock=bool(clock), wifi=('disconnected', 0))
                self.assertIsNotNone(ImageChops.difference(off, disconnected).getbbox())

    def test_camera_header_cache_tracks_wifi(self):
        off = camera_header('Red', 720, 480, wifi=('off', 0))
        connected = camera_header('Red', 720, 480, wifi=('connected', 4))
        self.assertNotEqual(off, connected)


if __name__ == '__main__':
    unittest.main()
