"""Media partial updates, isolation, lifecycle and dongle normalization."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

from hlauncher.media import NowPlaying, validate, clock

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('carplay_metadata', ROOT/'plugins/carplay/media.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class Media(unittest.TestCase):
    def test_partial_updates_track_change_and_disconnect(self):
        with tempfile.TemporaryDirectory() as folder:
            broker = NowPlaying(path=Path(folder)/'state.json')
            broker.publish('carplay', {'title':'First', 'artist':'Artist', 'duration_ms':180000})
            broker.publish('carplay', {'position_ms':12000})
            broker.flush(force=True)
            p = json.loads(broker.path.read_text())['now_playing']
            self.assertEqual((p['title'],p['position_ms'],p['duration_ms']),('First',12000,180000))
            broker.publish('carplay', {'title':'Second'})
            self.assertIsNone(broker.sources['carplay']['position_ms'])
            self.assertIsNone(broker.sources['carplay']['artist'])
            broker.publish('other', {'title':'Podcast'})
            self.assertEqual(broker.sources['carplay']['title'],'Second')
            broker.clear('other')
            self.assertFalse(broker.snapshot()['now_playing']['available'])
            self.assertEqual(broker.snapshot()['radio_forwarding_mode'],'source_only')

    def test_bad_updates_and_export_failure_do_not_damage_state(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'not-a-directory';path.write_text('x')
            broker=NowPlaying(path=path/'state.json')
            broker.publish('carplay', {'title':'Good'})
            for bad in [{'position_ms':float('nan')},{'position_ms':True},{'duration_ms':-1},{'title':[]},{'unrecognized':1}]:
                with self.assertRaises(ValueError):broker.publish('carplay',bad)
            broker.flush(force=True)
            self.assertEqual(broker.sources['carplay']['title'],'Good')

    def test_carplay_time_fields_and_partial_values(self):
        self.assertEqual(module.normalize({'MediaSongName':'Song','MediaArtistName':'Artist',
            'MediaSongDuration':180000,'MediaSongPlayTime':12000}),
            {'title':'Song','artist':'Artist','duration_ms':180000,'position_ms':12000})
        self.assertEqual(module.normalize({'MediaSongPlayTime':0}),{'position_ms':0})
        self.assertEqual(module.normalize({'MediaSongDuration':float('inf')}),{})
        self.assertEqual(clock(12000),'0:12')
        self.assertEqual(clock(None),'--:--')

    def test_selected_audio_source_is_independent_of_song_reports_and_foreground(self):
        from hlauncher.media import radio_metadata
        with tempfile.TemporaryDirectory() as folder:
            broker=NowPlaying(path=Path(folder)/'state.json')
            broker.select_source('carplay')
            broker.publish('carplay',dict(title='Private song',artist='Private artist',duration_ms=1000))
            broker.publish('background',dict(title='Other song'))
            self.assertEqual(broker.snapshot()['radio_metadata'],dict(title='Carplay',artist='HLauncher'))
            broker.select_source('android-auto')
            self.assertEqual(broker.snapshot()['radio_metadata'],dict(title='Android Auto',artist='HLauncher'))
            broker.clear('carplay')
            self.assertEqual(broker.source_plugin,'android-auto')
            broker.clear('android-auto')  # Android Auto does not need to publish song metadata.
            self.assertEqual(broker.snapshot()['radio_metadata'],{})
            for unknown in (None,'unknown',[],{}):self.assertEqual(radio_metadata(unknown),{})

    def test_control_worker_exports_only_source_and_rejects_dead_launcher(self):
        import os
        from unittest.mock import patch
        from hlauncher import controls_worker as worker
        with tempfile.TemporaryDirectory() as folder,patch.dict(os.environ,HLAUNCHER_RUNTIME_DIR=folder):
            path=Path(folder)/'now-playing.json'
            path.write_text(json.dumps(dict(launcher_pid=os.getpid(),source_plugin='android-auto',
                now_playing=dict(title='Private song',artist='Private artist',album='Private album',duration_ms=123))))
            self.assertEqual(worker.metadata(),dict(title='Android Auto',artist='HLauncher'))
            with patch('hlauncher.controls_worker.os.kill',side_effect=ProcessLookupError):
                self.assertEqual(worker.metadata(),{})
