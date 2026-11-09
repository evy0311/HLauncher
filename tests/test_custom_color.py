"""Custom themes persist atomically without changing presets or first-run flow."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from hlauncher.config import Preferences
from hlauncher.ui import home_art as art
from hlauncher.ui.color_picker import Picker,touch
from sdk.hlauncher_sdk.theme import load_accent,normalize_color
import test_radio_ui as radio_tests


class ColorPersistence(unittest.TestCase):
    def test_custom_theme_survives_reload_preset_switch_and_concurrent_settings(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'settings.json';prefs=Preferences(path);prefs.save()
            concurrent=Preferences(path)
            presets={name:art.tile(name).tobytes() for name in art.THEMES}
            prefs.set_tile_color('#ab35df')
            concurrent.data['debug_mode']=True;concurrent.save()
            reboot=Preferences(path)
            self.assertEqual(reboot.data['tile_color'],'#AB35DF')
            self.assertEqual(reboot.data['custom_color'],'#AB35DF')
            self.assertTrue(reboot.data['debug_mode'])
            with patch.dict('os.environ',HLAUNCHER_STATE_DIR=folder):self.assertEqual(load_accent(),'#AB35DF')
            self.assertEqual(art.accent(reboot.data['tile_color']),(171,53,223))
            reboot.set_tile_color('Blue')
            self.assertEqual(Preferences(path).data['custom_color'],'#AB35DF')
            for name in presets:self.assertEqual(presets[name],art.tile(name).tobytes())

    def test_invalid_colors_cannot_replace_saved_theme_and_write_failure_restores_both_fields(self):
        with tempfile.TemporaryDirectory() as folder:
            prefs=Preferences(Path(folder)/'settings.json');prefs.set_tile_color('Amber')
            for invalid in ('#12345','##123456','#ABCDEX',None,[], '<script>'):
                with self.assertRaises(ValueError):prefs.set_tile_color(invalid)
                self.assertEqual(Preferences(prefs.path).data['tile_color'],'Amber')
            before=dict(prefs.data)
            with patch.object(prefs,'save',side_effect=OSError('full')):
                with self.assertRaises(OSError):prefs.set_tile_color('#123456')
            self.assertEqual(prefs.data,before)
            prefs.path.write_text(json.dumps(dict(tile_color=['bad'],custom_color='bad')))
            self.assertEqual(Preferences(prefs.path).data['tile_color'],'Red')

    def test_hex_keypad_validation_and_round_trip(self):
        for color in ('#000000','#FFFFFF','#198B96','#9A35D8'):
            self.assertEqual(Picker(color).hex,color)
        picker=Picker('#198B96');picker.key('hex');picker.key('F');picker.key('apply-hex')
        self.assertTrue(picker.keyboard);self.assertTrue(picker.error)
        self.assertEqual(picker.hex,'#198B96')
        picker.key('clear')
        for key in 'A235D8':picker.key(key)
        picker.key('apply-hex')
        self.assertFalse(picker.keyboard);self.assertEqual(picker.hex,'#A235D8')
        self.assertEqual(normalize_color(' a235d8 '),'#A235D8')


class CustomColorUI(unittest.TestCase):
    setUp=radio_tests.RadioUI.setUp
    tearDown=radio_tests.RadioUI.tearDown

    def test_picker_cancel_save_reload_and_touch_scaling(self):
        ui=self.ui;ui.tile_colors();original=ui.prefs.path.read_bytes();ui.custom_color()
        ui.picker_key('hex');ui.actions[0][1]()
        self.assertEqual(ui.mode,'custom_color');self.assertFalse(ui.color_picker.keyboard)
        ui.color_picker.set_rgb((136,36,190));ui.draw()
        self.assertEqual(ui.prefs.path.read_bytes(),original)
        ui.cancel_custom_color();self.assertEqual(ui.mode,'tile_colors')
        ui.custom_color();ui.color_picker.set_rgb((136,36,190));ui.save_custom_color()
        self.assertEqual(ui.mode,'tile_colors')
        self.assertEqual(Preferences(ui.prefs.path).data['tile_color'],'#8824BE')
        ui.custom_color()
        for size in ((720,480),(800,480)):
            ui.fb.w,ui.fb.h=size
            point=lambda x,y:(x*size[0]/720,y*size[1]/480)
            self.assertTrue(touch(ui,'down',point(384,216)))
            self.assertTrue(touch(ui,'move',point(628,216)))
            self.assertTrue(touch(ui,'up',point(628,216)))
            self.assertEqual(ui.color_picker.channels[0],255)
            self.assertIsNone(ui.color_picker.drag)
        ui.color_picker.set_rgb((33,99,177))
        with patch.object(ui.prefs,'save',side_effect=OSError('full')):ui.save_custom_color()
        self.assertEqual(ui.mode,'custom_color');self.assertTrue(ui.banner)
        self.assertEqual(Preferences(ui.prefs.path).data['tile_color'],'#8824BE')


    def test_wizard_exit_is_only_from_settings_and_picker_returns_to_same_step(self):
        ui=self.ui;ui.home();ui.setup_page(True)
        self.assertFalse(ui.setup_can_exit)
        ui.system_settings();ui.setup_page(True);self.assertTrue(ui.setup_can_exit)
        ui.wizard.save(setup_step=3);ui.custom_color();ui.color_picker.set_rgb((22,111,150));ui.save_custom_color()
        self.assertEqual(ui.mode,'onboarding');self.assertEqual(ui.wizard.step,3)
        self.assertTrue(ui.setup_can_exit)
        ui.prefs.data['setup_complete']=False;ui.prefs.save();ui.mode='home';ui.setup_page()
        self.assertFalse(ui.setup_can_exit)
        ui.wizard.save(setup_step=3);ui.custom_color();ui.save_custom_color()
        self.assertEqual(ui.mode,'onboarding');self.assertFalse(ui.setup_can_exit)
        self.assertFalse(Preferences(ui.prefs.path).data['setup_complete'])
