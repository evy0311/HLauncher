"""Reboot persistence, legacy curve compatibility and independent user slots."""
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from hlauncher.audio_settings import AudioSettings,PRESETS,EQ_BANDS,LEGACY_EQ_BANDS


class AudioPresets(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.path=Path(self.temp.name)/'audio.json'
    def tearDown(self):self.temp.cleanup()

    def test_route_bypass_full_curve_and_active_preset_survive_fresh_process_state(self):
        for pipewire in (False,True):
            for eq in (False,True):
                settings=AudioSettings(self.path)
                settings.save(pipewire=pipewire,eq=eq,**settings.preset_changes('Deep bass'))
                fresh=AudioSettings(self.path)
                self.assertEqual((fresh.values['pipewire'],fresh.values['eq']),(pipewire,eq))
                self.assertEqual(fresh.values['bands'],PRESETS['Deep bass'])
                self.assertEqual(fresh.preset_name(),'Deep bass')
                self.assertEqual(fresh.controls()['params'][1::2],[0]*(3+len(EQ_BANDS)) if not eq else settings.controls()['params'][1::2])

    def test_two_user_slots_and_active_low_bands_survive_reload_and_legacy_save(self):
        settings=AudioSettings(self.path)
        first=dict(PRESETS['Flat'],b20=-3,b25=2,b80=3)
        second=dict(PRESETS['Flat'],b20=-2,b25=1,b2k=-2)
        settings.save(pipewire=True,eq=False,bass=2,bands=first);settings.save_user_preset('User 1')
        settings.save(bass=0,bands=second);settings.save_user_preset('User 2')
        fresh=AudioSettings(self.path)
        self.assertEqual(fresh.preset_name(),'User 2')
        self.assertEqual(fresh.values['bands'],second)
        fresh.save(**fresh.preset_changes('User 1'))
        self.assertEqual(fresh.values['bands'],first)
        self.assertEqual(fresh.values['bass'],2)
        self.assertTrue(fresh.values['pipewire']);self.assertFalse(fresh.values['eq'])
        persisted=json.loads(self.path.read_text())
        self.assertEqual(set(persisted['bands']),set(('b31','b50','b80','b125','b200','b315','b500','b1k','b2k','b4k','b8k','b16k')))
        # Older software can read all original bands and cannot erase the separate saved slots.
        self.path.write_text(json.dumps({k:v for k,v in persisted.items() if k not in ('low_bands','preset')}))
        recovered=AudioSettings(self.path)
        recovered.save(**recovered.preset_changes('User 2'))
        self.assertEqual(recovered.values['bands'],second)
        self.assertIn('User 1',recovered.user_presets)

    def test_failed_slot_write_retains_existing_curve_and_empty_slot_is_not_flat(self):
        settings=AudioSettings(self.path)
        with self.assertRaisesRegex(ValueError,'empty'):settings.preset_changes('User 1')
        settings.save_user_preset('User 1');before=settings.presets_path.read_bytes()
        settings.save(bands=dict(PRESETS['Flat'],b25=4))
        with patch('hlauncher.audio_settings.os.replace',side_effect=OSError('full')):
            with self.assertRaises(OSError):settings.save_user_preset('User 1')
        self.assertEqual(settings.presets_path.read_bytes(),before)
        self.assertFalse(list(self.path.parent.glob('.audio-*')))
        with self.assertRaises(ValueError):settings.save_user_preset('User 3')

    def test_factory_curves_are_complete_bounded_and_no_edm(self):
        self.assertEqual(len(PRESETS),8);self.assertNotIn('EDM',PRESETS)
        for curve in PRESETS.values():
            self.assertEqual(set(curve),set(EQ_BANDS))
            self.assertTrue(all(type(v) is int and -6<=v<=6 for v in curve.values()))
        self.assertEqual(EQ_BANDS['b20'],20);self.assertEqual(EQ_BANDS['b25'],25)

    def test_firstboot_does_not_stop_the_restored_audio_graph(self):
        from hlauncher import firstboot
        folder=self.path.parent;(folder/'initialized.json').write_text('{}')
        state=SimpleNamespace(folder=folder,credentials=lambda:{'ssid':'fixture','password':'fixture'})
        with patch.object(firstboot,'default_hostname'),patch.object(firstboot,'write_recovery_card'), \
             patch.object(firstboot,'SetupState',return_value=state), \
             patch('hlauncher.ssh_access.MANAGED',folder/'unmanaged'), \
             patch('hlauncher.storage.finish_transition'),patch('hlauncher.audio_settings.PipeWireService') as service:
            firstboot.main()
        service.assert_not_called()


class UserPresetTouchscreen(unittest.TestCase):
    def test_save_load_overwrite_confirmation_and_reopen_preserve_power(self):
        from hlauncher.launcher import Launcher
        from hlauncher.config import Preferences
        from hlauncher.protocol_diagnostics import ProtocolDiagnostics
        from test_architecture import Display
        with tempfile.TemporaryDirectory() as folder,patch.object(ProtocolDiagnostics,'parked_for_setup',return_value=True):
            path=Path(folder)/'settings.json';prefs=Preferences(path);prefs.accept_safety_notice()
            ui=Launcher(framebuffer=Display(),preferences=prefs,manifests={})
            def tap(x,y):
                next(action for (l,t,r,b),action in ui.actions if l<=x<r and t<=y<b)()
            def users():
                tap(530,136);tap(360,456)
            try:
                ui.audio_page()
                first=dict(PRESETS['Flat'],b20=-3,b25=2)
                second=dict(PRESETS['Flat'],b20=-2,b25=1)
                ui.change_audio(pipewire=True,eq=False,bands=first)
                users();tap(530,146)
                self.assertEqual(ui.audio_settings.preset_name(),'User 1')
                ui.change_audio(bands=second);tap(530,266)
                tap(160,146)
                self.assertFalse(ui.audio_presets_open)
                self.assertEqual(ui.audio_settings.values['bands'],first)
                replacement=dict(first,b20=-4);ui.change_audio(bands=replacement)
                users();before=ui.audio_settings.presets_path.read_bytes();tap(530,146)
                self.assertEqual(ui.audio_confirm_save,'User 1')
                self.assertEqual(ui.audio_settings.presets_path.read_bytes(),before)
                tap(180,388);self.assertIsNone(ui.audio_confirm_save)
                tap(530,146);tap(530,388)
                fresh=AudioSettings(Path(folder)/'audio.json')
                self.assertEqual(fresh.preset_name(),'User 1')
                self.assertEqual(fresh.values['bands'],replacement)
                self.assertEqual(fresh.user_presets['User 2']['bands'],second)
                self.assertTrue(fresh.values['pipewire']);self.assertFalse(fresh.values['eq'])
                self.assertTrue(all(0<=l<r<=720 and 0<=t<b<=480 for (l,t,r,b),_ in ui.actions))
            finally:ui.close()
