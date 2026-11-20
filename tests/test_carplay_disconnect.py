"""Disconnected CarPlay video must not replace the launcher's Back control."""
import importlib.util
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
with patch.object(sys,'path',[str(ROOT/'sdk'),str(ROOT/'plugins/carplay'),*sys.path]):
    spec=importlib.util.spec_from_file_location('carplay_disconnect_backend',ROOT/'plugins/carplay/backend.py')
    backend=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(backend)


class CarplayDisconnect(unittest.TestCase):
    def test_adapter_reports_reach_health_without_inventing_device_support(self):
        carplay = backend.CarplayHDMI()
        carplay.receive_state(dict(state='dongle_software_version', version='fixture-version'))
        carplay.receive_state(dict(state='dongle_box_info', settings={'productType': 'fixture-product'}))
        carplay.receive_state(dict(state='phone_connected', phone_type=3, wifi=1))
        info = carplay.metrics()['adapter_info']
        self.assertEqual(info['firmware'], 'fixture-version')
        self.assertEqual(info['protocol'], 'CarPlay')
        self.assertNotIn('aa_support', info)
        carplay.receive_state(dict(state='usb_failure'))
        self.assertEqual(carplay.metrics()['adapter_info'], {})

    def test_missing_unplug_event_hides_frozen_video_and_allows_recovery(self):
        carplay = backend.CarplayHDMI()
        carplay.receive_state(dict(state='phone_connected'))
        carplay.frame = b'phone video'
        carplay.last_decoded_at = 100
        deadline = 100 + backend.VIDEO_TIMEOUT_SECONDS
        with patch.object(backend.time, 'monotonic', return_value=deadline - .01):
            self.assertEqual(carplay.snapshot()[1], b'phone video')
        with patch.object(backend.time, 'monotonic', return_value=deadline):
            _, frame, _, status = carplay.snapshot()
            self.assertIsNone(frame)
            self.assertIn('video paused', status)
            self.assertTrue(carplay.phone_connected)
            carplay.last_decoded_at = deadline
            carplay.frame = b'resumed video'
            self.assertEqual(carplay.snapshot()[1], b'resumed video')

    def test_cached_video_requires_connected_phone_and_clears_on_disconnect(self):
        carplay=backend.CarplayHDMI()
        carplay.frame=b'adapter splash or stale phone frame'
        self.assertIsNone(carplay.snapshot()[1])
        carplay.receive_connection_state(dict(state='phone_connected'))
        carplay.frame=b'current phone video'
        self.assertEqual(carplay.snapshot()[1],b'current phone video')
        for state in ('phone_disconnected','usb_failure','waiting_dongle','dongle_ready'):
            carplay.receive_connection_state(dict(state='phone_connected'))
            carplay.frame=b'current phone video'
            carplay.receive_connection_state(dict(state=state))
            self.assertIsNone(carplay.frame)
            carplay.frame=b'late cached redraw'
            self.assertIsNone(carplay.snapshot()[1])
