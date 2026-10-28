"""Launcher touch feedback and release/cancel behavior."""
from pathlib import Path
import tempfile
import unittest
from hlauncher.launcher import Launcher
from hlauncher.config import Preferences
from test_architecture import Display


def touch(action, x=0, y=0):
    return {'contacts': [{'slot':0, 'action':action, 'has_position':action in ('down','move'),
        'x_raw':round(x*32767/719), 'y_raw':round(y*32767/479)}]}


class ButtonFeedback(unittest.TestCase):
    def test_press_release_and_slide_off(self):
        with tempfile.TemporaryDirectory() as folder:
            fb = Display()
            ui = Launcher(framebuffer=fb, preferences=Preferences(Path(folder)/'settings.json'), manifests={})
            try:
                normal = fb.last.tobytes()
                ui.update(touch('down', 570, 300))
                self.assertEqual(ui.mode, 'home')
                self.assertNotEqual(fb.last.tobytes(), normal)
                ui.update(touch('up'))
                self.assertEqual(ui.mode, 'settings')
                ui.home()
                ui.update(touch('down', 570, 300))
                ui.update(touch('move', 400, 200))
                self.assertEqual(fb.last.tobytes(), normal)
                ui.update(touch('move', 570, 300))
                ui.update(touch('up'))
                self.assertEqual(ui.mode, 'home')
            finally:
                ui.close()


class PixelConversion(unittest.TestCase):
    def test_fast_conversion_matches_portable_path(self):
        from unittest.mock import patch
        from PIL import Image
        from hlauncher import display
        import random
        rng = random.Random(42)
        image = Image.frombytes('RGB', (32, 32), bytes(rng.randrange(256) for _ in range(32*32*3)))
        actual = display.encode(image)
        with patch.object(display, 'np', None):
            reference = display.encode(image)
        self.assertEqual(actual, reference)
