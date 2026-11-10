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
