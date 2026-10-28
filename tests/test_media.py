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
            self.assertFalse(broker.snapshot()['radio_forwarding'])

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
