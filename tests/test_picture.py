import json
from pathlib import Path
import tempfile
import unittest
from sdk.hlauncher_sdk.picture import PictureSettings, DEFAULTS, validate
from hlauncher.launcher import Launcher
from hlauncher.config import Preferences
from test_architecture import Display, parked_radio


@parked_radio
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

    def test_legacy_values_migrate_on_save_and_new_file_takes_precedence(self):
        with tempfile.TemporaryDirectory() as folder:
            legacy = Path(folder)/'carplay-color.json'
            legacy.write_text(json.dumps(dict(DEFAULTS,saturation=85)))
            picture = PictureSettings(Path(folder)/'picture.json')
            self.assertEqual(picture.values['saturation'],85)
            picture.save(dict(DEFAULTS,contrast=90))
            legacy.write_text(json.dumps(dict(DEFAULTS,saturation=20)))
            loaded = PictureSettings(picture.path)
            self.assertEqual(loaded.values,dict(DEFAULTS,contrast=90))

    def test_drag_applies_before_release_and_external_edits_leave_video_to_decoder(self):
        from unittest.mock import Mock
        with tempfile.TemporaryDirectory() as folder:
            display=Display()
            display.set_picture=Mock()
            display.redraw_picture=Mock()
            ui=Launcher(framebuffer=display,preferences=Preferences(Path(folder)/'settings.json'),manifests={})
            try:
                ui.color_settings()
                key,box=ui.picture_sliders[0]
                ui.color_touch('down',(box[0],box[1]+5))
                self.assertEqual(display.set_picture.call_args.args[0]['saturation'],0)
                ui.color_touch('up',(box[0],box[1]+5))
                ui.mode='plugin'
                other=PictureSettings(ui.picture.path)
                other.save(dict(DEFAULTS,contrast=90))
                ui.picture_checked=0
                ui.tick()
                self.assertEqual(display.set_picture.call_args.args[0]['contrast'],90)
                display.redraw_picture.assert_not_called()
            finally:ui.close()

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
