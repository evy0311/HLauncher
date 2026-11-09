import json
from pathlib import Path
import tempfile
import unittest
from sdk.hlauncher_sdk.picture import PictureSettings, DEFAULTS, validate
from hlauncher.launcher import Launcher
from hlauncher.config import Preferences
from test_architecture import Display


class Picture(unittest.TestCase):
    def test_atomic_preferences_and_invalid_external_file(self):
        with tempfile.TemporaryDirectory() as folder:
            p = Path(folder)/'carplay-color.json'
            a,b = PictureSettings(p),PictureSettings(p)
            self.assertEqual(a.values,DEFAULTS)
            a.save(dict(DEFAULTS,saturation=85))
            self.assertTrue(b.refresh())
            self.assertEqual(b.values['saturation'],85)
            p.write_text('{bad')
            self.assertFalse(b.refresh())
            self.assertEqual(b.values['saturation'],85)
            with self.assertRaises(ValueError):validate({'saturation':151})
            with self.assertRaises(ValueError):validate({'contrast':True})
            with self.assertRaises(ValueError):validate({'brightness':float('nan')})

    def test_ui_slider_reset_and_external_reload(self):
        with tempfile.TemporaryDirectory() as folder:
            ui=Launcher(framebuffer=Display(),preferences=Preferences(Path(folder)/'settings.json'),manifests={})
            try:
                ui.settings()
                ui.color_settings()
                self.assertEqual(ui.mode,'colors')
                key,box=ui.picture_sliders[0]
                ui.color_touch('down',(box[0],box[1]+5))
                ui.color_touch('up',(box[0],box[1]+5))
                self.assertEqual(ui.picture.values['saturation'],0)
                ui.reset_picture()
                self.assertEqual(ui.picture.values,DEFAULTS)
                other=PictureSettings(ui.picture.path)
                other.save(dict(DEFAULTS,contrast=90))
                ui.tick()
                self.assertEqual(ui.picture_values['contrast'],90)
            finally:ui.close()
