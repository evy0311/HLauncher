"""Foreground ownership and automatic projection background audio are separate lifetimes."""
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from hlauncher.catalog import Manifest
from hlauncher.config import Preferences
from hlauncher.plugin_host import PluginHost
from hlauncher.audio import AudioBroker
from hlauncher.playback import Playback

ROOT=Path(__file__).resolve().parents[1]


class Background(unittest.TestCase):
    def test_preferences_and_worker_lifetimes(self):
        with tempfile.TemporaryDirectory() as folder:
            prefs=Preferences(Path(folder)/'settings.json')
            cp=Manifest.load(ROOT/'plugins/carplay',bundled=True)
            obd=Manifest.load(ROOT/'plugins/obd',bundled=True)
            self.assertTrue(prefs.background_enabled(cp))
            self.assertFalse(prefs.background_enabled(obd))
            with self.assertRaises(ValueError):prefs.set_background(obd,True)
            audio=SimpleNamespace(stop_capture=lambda p:None,stop=lambda p:None)
            host=PluginHost({'carplay':cp,'obd':obd},720,480,lambda **v:None,lambda t:None,audio,prefs.background_enabled)
            def worker(manifest):
                return SimpleNamespace(manifest=manifest,active=True,send=lambda **kw:True,close=lambda:None)
            host.workers={'carplay':worker(cp),'obd':worker(obd)}
            host.active='carplay';host.deactivate()
            self.assertIn('carplay',host.workers)
            self.assertTrue(host.workers['carplay'].background_enabled)
            host.active='obd';host.deactivate()
            self.assertNotIn('obd',host.workers)
            with self.assertRaises(ValueError):prefs.set_background(cp,False)
            prefs.data['background']['carplay']=False
            prefs.save()
            self.assertTrue(Preferences(prefs.path).background_enabled(cp))
            aa=Manifest.load(ROOT/'plugins/android-auto',bundled=True)
            prefs.data['background']['android-auto']=False
            self.assertTrue(prefs.background_enabled(aa))
            with self.assertRaises(ValueError):prefs.set_background(aa,False)
            host.background_changed('carplay')
            self.assertIn('carplay',host.workers)
            host.stop('carplay')
            self.assertNotIn('carplay',host.workers)

    def test_background_audio_requires_enabled_permission(self):
        cp=Manifest.load(ROOT/'plugins/carplay',bundled=True)
        audio=AudioBroker(lambda **v:None)
        audio.playback=Playback(lambda **v:None,start_worker=False)
        worker=SimpleNamespace(manifest=cp,background_enabled=False)
        message=dict(type='audio.playback.pcm',sample_rate=48000,channels=2,stream=1,pcm=bytes(80))
        audio.request(worker,message,active=False)
        self.assertFalse(audio.playback.streams)
        worker.background_enabled=True
        audio.request(worker,message,active=False)
        self.assertIn(('carplay',1),audio.playback.streams)
        audio.stop('carplay')
