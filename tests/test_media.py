"""Media partial updates, isolation, lifecycle and dongle normalization."""
import importlib.util
import json
from pathlib import Path
import struct
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
            broker.publish('carplay', {'title':'First', 'artist':'Artist', 'duration_ms':180000,
                                       'playback_state':'playing'})
            broker.publish('carplay', {'position_ms':12000})
            broker.flush(force=True)
            p = json.loads(broker.path.read_text())['now_playing']
            self.assertEqual((p['title'],p['position_ms'],p['duration_ms']),('First',12000,180000))
            broker.publish('carplay', {'title':'Second'})
            self.assertIsNone(broker.sources['carplay']['position_ms'])
            self.assertIsNone(broker.sources['carplay']['artist'])
            self.assertEqual(broker.sources['carplay']['playback_state'], 'playing')
            broker.publish('other', {'title':'Podcast'})
            self.assertEqual(broker.sources['carplay']['title'],'Second')
            broker.clear('other')
            self.assertFalse(broker.snapshot()['now_playing']['available'])
            self.assertEqual(broker.snapshot()['radio_forwarding_mode'],'selected_track')

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

    def test_radio_follows_the_audio_owner_and_clears_its_track_on_disconnect(self):
        from hlauncher.media import radio_metadata
        with tempfile.TemporaryDirectory() as folder:
            broker=NowPlaying(path=Path(folder)/'state.json')
            broker.select_source('carplay')
            broker.publish('carplay',dict(title='Private song',artist='Private artist',duration_ms=1000))
            broker.publish('background',dict(title='Other song'))
            self.assertEqual(broker.snapshot()['radio_metadata']['title'],'Private song')
            broker.select_source('android-auto')
            self.assertEqual(broker.snapshot()['radio_metadata'],dict(title='Android Auto',artist='HLauncher'))
            broker.clear('carplay')
            self.assertEqual(broker.source_plugin,'android-auto')
            broker.clear('android-auto')
            self.assertEqual(broker.snapshot()['radio_metadata'],{})
            for unknown in (None,'unknown',[],{}):self.assertEqual(radio_metadata(unknown),{})

    def test_control_worker_exports_selected_track_and_rejects_dead_launcher(self):
        import os
        from unittest.mock import patch
        from hlauncher import controls_worker as worker
        with tempfile.TemporaryDirectory() as folder,patch.dict(os.environ,HLAUNCHER_RUNTIME_DIR=folder):
            path=Path(folder)/'now-playing.json'
            path.write_text(json.dumps(dict(launcher_pid=os.getpid(),source_plugin='android-auto',
                now_playing=dict(title='Background song'),
                sources={'android-auto':dict(plugin='android-auto',available=True,title='Selected song',
                                             artist='Selected artist',duration_ms=123)})))
            self.assertEqual(worker.metadata(),dict(title='Selected song',artist='Selected artist',duration_ms=123))
            with patch('hlauncher.controls_worker.os.kill',side_effect=ProcessLookupError):
                self.assertEqual(worker.metadata(),{})

    def test_avrcp_track_change_and_element_attributes(self):
        from hlauncher.control_protocols import AvrcpTarget
        target = AvrcpTarget()
        header = bytes.fromhex('10110e')
        subscribe = target.vendor(header, 0x31, bytes([2, 0, 0, 0, 0]), ctype=3)
        interim, _ = target.receive(subscribe)
        self.assertEqual(interim[3], 15)
        changed, = target.update(dict(title='Écho', artist='Artist', playback_state='playing'))
        self.assertEqual((changed[3], changed[9], changed[13]), (13, 0x31, 2))
        request = target.vendor(header, 0x20, bytes(8) + struct.pack('!BII', 2, 1, 2), ctype=1)
        reply, _ = target.receive(request)
        title = 'Écho'.encode()
        self.assertEqual(reply[13:], bytes([2]) + struct.pack('!IHH', 1, 106, len(title)) + title
                         + struct.pack('!IHH', 2, 106, 6) + b'Artist')
