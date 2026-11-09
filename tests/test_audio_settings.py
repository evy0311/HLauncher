import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from hlauncher.audio_settings import AudioSettings, EQ_BANDS, PRESETS


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
                action = next(action for _,action in ui.actions if action == ui.audio_page)
                action()
                self.assertEqual(ui.mode, 'audio_settings')
                ui.adjust_eq('bass', 1)
                self.assertEqual(AudioSettings(Path(folder)/'audio.json').values['bass'], 1)
                with patch.object(ui.audio_settings, 'status', return_value='PipeWire ready'):
                    ui.change_audio(pipewire=True)
                self.assertTrue(AudioSettings(Path(folder)/'audio.json').values['pipewire'])
                self.assertEqual(len(ui.actions), 28)
            finally:ui.close()

    def test_themed_audio_controls_route_each_band_and_home(self):
        from hlauncher.launcher import Launcher
        from hlauncher.config import Preferences
        from test_architecture import Display
        with tempfile.TemporaryDirectory() as folder:
            ui=Launcher(framebuffer=Display(),preferences=Preferences(Path(folder)/'settings.json'),manifests={})
            try:
                ui.audio_page()
                for i,key in enumerate(EQ_BANDS):
                    ui.actions[4+2*i][1]()
                    self.assertEqual(ui.audio_settings.values['bands'][key],1)
                self.assertEqual(list(ui.audio_settings.values['bands'].values()),[1]*12)
                ui.adjust_eq('bass',2)
                ui.actions[2][1]()  # EQ Off
                ui.actions[3][1]()  # Reset EQ
                self.assertEqual(ui.audio_settings.values['bass'],0)
                self.assertFalse(ui.audio_settings.values['eq'])
                self.assertEqual(ui.audio_settings.preset_name(),'Flat')
                self.assertFalse(ui.audio_settings.values['pipewire'])
                ui.actions[0][1]()
                self.assertEqual(ui.mode,'home')
            finally:ui.close()

    def test_twelve_band_presets_persist_and_flat_clears_legacy_gains(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'audio.json'
            settings=AudioSettings(path)
            settings.save(bass=12)
            settings.save(**settings.preset_changes('EDM Bass'))
            self.assertEqual(settings.preset_name(),'EDM Bass')
            self.assertFalse(settings.values['bass'])
            self.assertEqual(AudioSettings(path).values['bands'], PRESETS['EDM Bass'])
            bands=dict(settings.values['bands'],b50=4)
            settings.save(bands=bands)
            self.assertEqual(settings.preset_name(),'Custom')
            self.assertEqual(settings.values['bands']['b31'],2)
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
