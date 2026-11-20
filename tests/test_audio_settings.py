import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from hlauncher.audio_settings import AudioSettings, EQ_BANDS, LEGACY_EQ_BANDS, PRESETS


from test_architecture import parked_radio


@parked_radio
class AudioSettingsTests(unittest.TestCase):
    def test_persistence_bounds_and_independent_gains(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'audio.json'
            settings = AudioSettings(path)
            settings.save(output='hdmi', pipewire=True, bass=6, mid=3, treble=-4)
            self.assertEqual(AudioSettings(path).values, settings.values)
            path.write_text(json.dumps(dict(settings.values, output='bluetooth')))
            loaded = AudioSettings(path)
            self.assertEqual(loaded.device(), 'hlauncher_hdmi')
            self.assertEqual(loaded.values['bass'], 6)
            loaded.save()
            self.assertEqual(json.loads(path.read_text())['output'], 'hdmi')
            controls = settings.controls()['params']
            self.assertEqual(controls[:6], ['bass:Gain', 6, 'mid:Gain', 3, 'treble:Gain', -4])
            self.assertEqual(controls[6:], [v for key in EQ_BANDS for v in (key+':Gain',0)])
            before = path.read_text()
            for invalid in (13, -13, True, '6'):
                with self.assertRaises(ValueError):settings.save(bass=invalid)
            self.assertEqual(path.read_text(), before)
            settings.save(eq=False)
            self.assertTrue(all(gain==0 for gain in settings.controls()['params'][1::2]))

    def test_bad_file_keeps_defaults_and_atomic_write_cleans_temp(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'audio.json'
            path.write_text('{bad')
            settings = AudioSettings(path)
            self.assertEqual(settings.values['bass'], 0)
            settings.save(bass=-6)
            self.assertEqual(json.loads(path.read_text())['bass'], -6)
            self.assertFalse(list(path.parent.glob('.audio-*')))

    def test_settings_page_saves_bass_and_route(self):
        from hlauncher.launcher import Launcher
        from hlauncher.config import Preferences
        from test_architecture import Display
        with tempfile.TemporaryDirectory() as folder:
            ui = Launcher(framebuffer=Display(), preferences=Preferences(Path(folder)/'settings.json'), manifests={})
            try:
                ui.settings()
                self.assertIn(ui.audio_page, [action for _, action in ui.actions])
                ui.audio_page()
                self.assertEqual(ui.mode, 'audio_settings')
                ui.adjust_eq('bass', 1)
                self.assertEqual(AudioSettings(Path(folder)/'audio.json').values['bass'], 1)
                with patch.object(ui.audio_settings, 'status', return_value='PipeWire ready'):
                    ui.change_audio(pipewire=True)
                self.assertTrue(AudioSettings(Path(folder)/'audio.json').values['pipewire'])
                self.assertEqual(len(ui.actions), 13)
            finally:ui.close()

    def test_six_band_pages_keep_all_gains_and_presets_keep_bypass_state(self):
        from hlauncher.launcher import Launcher
        from hlauncher.config import Preferences
        from test_architecture import Display
        with tempfile.TemporaryDirectory() as folder:
            prefs = Preferences(Path(folder)/'settings.json')
            prefs.accept_safety_notice()
            ui = Launcher(framebuffer=Display(), preferences=prefs, manifests={})

            def tap(x, y):
                next(action for (l, t, r, b), action in ui.actions
                     if l <= x < r and t <= y < b)()

            try:
                ui.audio_page()
                from hlauncher.ui.audio import BAND_PAGES
                for bank,keys in enumerate(BAND_PAGES):
                    if bank:tap(610,456)
                    for i, key in enumerate(keys):
                        before = dict(ui.audio_settings.values['bands'])
                        tap(80+i*112 if len(keys)==6 else 248+i*224,300)
                        self.assertEqual(ui.audio_settings.values['bands'], before)
                        tap(636, 406)  # Shared increase control.
                        self.assertEqual(ui.audio_settings.values['bands'][key], 1)
                self.assertEqual(list(ui.audio_settings.values['bands'].values()), [1]*14)
                # Editing remains possible while bypassed; it does not change the route.
                self.assertFalse(ui.audio_settings.values['pipewire'])
                tap(100,456)
                tap(80, 300)
                tap(84, 406)
                self.assertEqual(ui.audio_settings.values['bands']['b200'], 0)
                tap(100, 456)
                self.assertEqual(ui.audio_selected_bands[0], 'b125')
                tap(610, 456)
                self.assertEqual(ui.audio_selected_bands[1], 'b200')
                ui.change_audio(eq=False)
                for index, name in enumerate(PRESETS):
                    ui.adjust_eq('bass', 2)
                    tap(580, 132)  # Presets
                    tap(180+(index%2)*344,138+(index//2)*64)
                    self.assertFalse(ui.audio_presets_open)
                    self.assertEqual(ui.audio_bank, 1)
                    self.assertEqual(ui.audio_settings.preset_name(), name)
                    self.assertEqual(ui.audio_settings.values['bass'], 0)
                    self.assertFalse(ui.audio_settings.values['eq'])
                    self.assertFalse(ui.audio_settings.values['pipewire'])
                    self.assertEqual(AudioSettings(Path(folder)/'audio.json').values,
                                     ui.audio_settings.values)
                tap(580, 132)
                tap(40, 26)  # Preset back returns to the same EQ bank.
                self.assertFalse(ui.audio_presets_open)
                self.assertEqual(ui.audio_bank, 1)
                tap(40, 26)
                self.assertEqual(ui.mode, 'home')
            finally:
                ui.close()

    def test_frequency_swipes_change_one_page_without_selecting_a_band(self):
        from hlauncher.launcher import Launcher
        from hlauncher.config import Preferences
        from test_architecture import Display
        with tempfile.TemporaryDirectory() as folder:
            prefs=Preferences(Path(folder)/'settings.json');prefs.accept_safety_notice()
            ui=Launcher(framebuffer=Display(),preferences=prefs,manifests={})
            def event(action,x=0,y=0):
                ui.update({'contacts':[dict(slot=0,action=action,has_position=action!='up',
                    x_raw=round(x*32767/719),y_raw=round(y*32767/479))]})
            def swipe(start,end):
                event('down',*start);event('move',*end);event('up')
            try:
                ui.audio_page();before=dict(ui.audio_settings.values['bands'])
                selected=dict(ui.audio_selected_bands)
                swipe((600,280),(160,280));self.assertEqual(ui.audio_bank,1)
                swipe((600,280),(160,280));self.assertEqual(ui.audio_bank,2)
                swipe((600,280),(160,280));self.assertEqual(ui.audio_bank,2)
                swipe((160,280),(600,280));self.assertEqual(ui.audio_bank,1)
                swipe((160,240),(160,350));self.assertEqual(ui.audio_bank,1)
                swipe((416,280),(430,280));self.assertEqual(ui.audio_bank,1)
                self.assertEqual(ui.audio_selected_bands,selected)
                self.assertEqual(ui.audio_settings.values['bands'],before)
                # Preset selection remains a tap, never frequency-page navigation.
                event('down',530,136);event('up')
                self.assertTrue(ui.audio_presets_open)
                swipe((600,280),(160,280));self.assertEqual(ui.audio_bank,1)
            finally:ui.close()

    def test_single_pipewire_control_applies_eq_and_preserves_curve(self):
        from hlauncher.launcher import Launcher
        from hlauncher.config import Preferences
        from test_architecture import Display
        with tempfile.TemporaryDirectory() as folder:
            prefs = Preferences(Path(folder)/'settings.json')
            prefs.accept_safety_notice()
            ui = Launcher(framebuffer=Display(), preferences=prefs, manifests={})
            try:
                for pipewire, eq in ((False, False), (False, True), (True, False), (True, True)):
                    with self.subTest(pipewire=pipewire, eq=eq):
                        ui.audio_settings.save(pipewire=pipewire, eq=eq,
                                               **ui.audio_settings.preset_changes('Vocal clarity'))
                        ui.audio_page()
                        # The route control is the only processing toggle.
                        next(action for (l, t, r, b), action in ui.actions
                             if l <= 180 < r and t <= 132 < b)()
                        saved = AudioSettings(Path(folder)/'audio.json')
                        self.assertEqual(saved.values['pipewire'], not (pipewire and eq))
                        self.assertTrue(saved.values['eq'])
                        self.assertEqual(saved.values['bands'], PRESETS['Vocal clarity'])
            finally:
                ui.close()

    def test_six_db_adjustment_limits_preserve_and_allow_reducing_old_gains(self):
        from hlauncher.launcher import Launcher
        from hlauncher.config import Preferences
        from test_architecture import Display
        with tempfile.TemporaryDirectory() as folder:
            prefs = Preferences(Path(folder)/'settings.json')
            prefs.accept_safety_notice()
            ui = Launcher(framebuffer=Display(), preferences=prefs, manifests={})
            try:
                bands = dict.fromkeys(EQ_BANDS, 0)
                bands.update(b31=12, b50=-12, b80=6, b125=-6)
                ui.audio_settings.save(bands=bands)
                ui.audio_page()
                self.assertEqual(ui.audio_settings.values['bands'], bands)
                for key, delta in (('b31', 1), ('b50', -1), ('b80', 1), ('b125', -1)):
                    ui.adjust_eq(key, delta)
                    self.assertEqual(ui.audio_settings.values['bands'], bands)
                ui.adjust_eq('b31', -1)
                ui.adjust_eq('b50', 1)
                self.assertEqual(ui.audio_settings.values['bands']['b31'], 11)
                self.assertEqual(ui.audio_settings.values['bands']['b50'], -11)
                for _ in range(5):
                    ui.adjust_eq('b31', -1)
                    ui.adjust_eq('b50', 1)
                ui.adjust_eq('b31', 1)
                ui.adjust_eq('b50', -1)
                loaded = AudioSettings(Path(folder)/'audio.json')
                self.assertEqual(loaded.values['bands']['b31'], 6)
                self.assertEqual(loaded.values['bands']['b50'], -6)
            finally:
                ui.close()

    def test_twelve_band_presets_persist_and_flat_clears_legacy_gains(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'audio.json'
            settings=AudioSettings(path)
            settings.save(bass=12)
            settings.save(**settings.preset_changes('Bass lift'))
            self.assertEqual(settings.preset_name(),'Bass lift')
            self.assertFalse(settings.values['bass'])
            self.assertEqual(AudioSettings(path).values['bands'], PRESETS['Bass lift'])
            bands=dict(settings.values['bands'],b50=4)
            settings.save(bands=bands)
            self.assertEqual(settings.preset_name(),'Custom')
            self.assertEqual(settings.values['bands']['b31'],1)
            before=path.read_bytes()
            for invalid in ({},dict(bands,b50=True),dict(bands,b50=13),dict(bands,unknown=0)):
                with self.assertRaises(ValueError):settings.save(bands=invalid)
                self.assertEqual(path.read_bytes(),before)
            settings.save(**settings.preset_changes('Flat'))
            self.assertEqual(settings.preset_name(),'Flat')
            self.assertTrue(all(gain==0 for gain in settings.controls()['params'][1::2]))

    def test_previous_tone_settings_are_preserved_until_an_explicit_preset(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'audio.json'
            path.write_text(json.dumps(dict(output='hdmi',pipewire=False,eq=True,bass=4,mid=-2,treble=1)))
            settings=AudioSettings(path)
            self.assertEqual(settings.values['bass'],4)
            self.assertEqual(settings.preset_name(),'Custom')
            self.assertEqual(settings.values['bands'], PRESETS['Flat'])

    def test_retired_preset_curve_survives_as_custom_without_rewriting_state(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'audio.json'
            old_curve = dict(zip(LEGACY_EQ_BANDS, (2,3,2,0,-1,-1,0,0,0,0,0,0)))
            path.write_text(json.dumps(dict(pipewire=True, eq=False, bands=old_curve)))
            original = path.read_bytes()
            settings = AudioSettings(path)
            self.assertEqual(settings.preset_name(), 'Custom')
            self.assertEqual(settings.values['bands'], dict(b20=0,b25=0,**old_curve))
            self.assertTrue(settings.values['pipewire'])
            self.assertFalse(settings.values['eq'])
            self.assertEqual(path.read_bytes(), original)

    def test_graph_is_started_on_demand_and_stopped_on_bypass(self):
        from hlauncher.audio_settings import PipeWireService
        import subprocess
        service = PipeWireService()
        with patch('hlauncher.audio_settings.subprocess.run') as run, \
             patch('hlauncher.audio_settings.eq_node', return_value=42) as ready:
            service.set_enabled(False)
            service.set_enabled(False)
            service.set_enabled(True)
            service.set_enabled(True)
            service.set_enabled(False)
            self.assertEqual([call.args[0][1] for call in run.call_args_list], ['stop','start','stop'])
            self.assertEqual(ready.call_count, 1)
            run.side_effect = subprocess.CalledProcessError(1, 'systemctl')
            with self.assertRaises(subprocess.CalledProcessError):service.set_enabled(True)
            self.assertFalse(service.enabled)
            run.side_effect = None
            service.set_enabled(True)
            self.assertTrue(service.enabled)

    def test_service_start_resets_only_pipewire_without_discarding_eq(self):
        import os
        import subprocess
        import sys
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'audio.json'
            settings = AudioSettings(path)
            settings.save(pipewire=True, bass=3)
            subprocess.run([sys.executable,'-m','hlauncher.audio_settings','--disable-pipewire'],
                           env=dict(os.environ,HLAUNCHER_STATE_DIR=folder),check=True)
            loaded=AudioSettings(path)
            self.assertFalse(loaded.values['pipewire'])
            self.assertEqual(loaded.values['bass'],3)
