import struct
import tempfile
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'sdk'))
from hlauncher_sdk import decode
from hlauncher.playback import Playback


class AudioPlayback(unittest.TestCase):
    def test_framing_preserves_pcm_and_rejects_short_header(self):
        raw = b'\x01\x00\xff\xff'
        message = decode(b'P' + struct.pack('!IBB', 48000, 2, 1) + raw)
        self.assertEqual(message['pcm'], raw)
        self.assertEqual((message['sample_rate'], message['channels'], message['stream']), (48000, 2, 1))
        with self.assertRaises(ValueError):
            decode(b'P\x00')

    def test_mixed_streams_format_change_and_stop(self):
        output = Playback(lambda **v: None, start_worker=False)
        def feed(rate, channels, stream, pcm):
            output.feed('carplay', dict(sample_rate=rate, channels=channels, stream=stream, pcm=pcm))
        feed(44100, 2, 1, b'\x01\x00' * 2)
        feed(16000, 1, 2, b'\x02\x00')
        old = output.streams[('carplay', 2)]
        feed(24000, 1, 2, b'\x03\x00')
        self.assertIsNot(old, output.streams[('carplay', 2)])
        self.assertEqual(len(output.streams), 2)
        self.assertEqual(output.streams[('carplay', 1)].queue[0], b'\x01\x00' * 2)
        with self.assertRaises(ValueError):
            feed(44100, 2, 1, b'\x00\x00')
        with self.assertRaises(ValueError):
            feed(96000, 2, 1, b'\x00' * 4)
        output.stop('carplay')
        self.assertFalse(output.streams)

    def test_pcm_queue_is_bounded(self):
        output = Playback(lambda **v: None, start_worker=False)
        message = dict(sample_rate=48000, channels=2, stream=1, pcm=bytes(3840))
        for _ in range(100):
            output.feed('carplay', message)
        stream = output.streams[('carplay', 1)]
        self.assertLessEqual(stream.queued, stream.limit)
        self.assertGreater(stream.dropped, 0)

    def test_input_gap_diagnostics_preserve_pcm_and_identify_the_stream(self):
        events = []
        output = Playback(lambda **event: events.append(event), start_worker=False)
        message = dict(sample_rate=48000, channels=2, stream=1, pcm=bytes(3840))
        with patch('hlauncher.playback.time.monotonic', return_value=100):
            output.feed('carplay', message)
        with patch('hlauncher.playback.time.monotonic', return_value=100.2):
            output.feed('carplay', message)
        gaps = [event for event in events if event['state'] == 'audio_input_gap']
        self.assertEqual(len(gaps), 1)
        self.assertEqual((gaps[0]['plugin'], gaps[0]['stream'], gaps[0]['gap_ms']), ('carplay', 1, 200))
        self.assertEqual(b''.join(output.streams[('carplay', 1)].queue), message['pcm']*2)

    def test_float_mixing_keeps_unity_and_does_not_clip_or_normalize(self):
        import numpy as np
        output = Playback(lambda **v: None, start_worker=False)
        for stream in (1,2):
            output.feed('carplay', dict(sample_rate=48000, channels=2, stream=stream,
                pcm=struct.pack('<h', 24576)*1920))
        mixed = np.frombuffer(output.mix(), dtype='<f4')
        self.assertEqual(len(mixed), 1920)
        np.testing.assert_array_equal(mixed, np.full(1920, 1.5, dtype=np.float32))
        self.assertEqual(output.clip_samples,1920)
        for stream in output.streams.values():
            self.assertEqual(stream.source_peak,.75)
            self.assertEqual(stream.converted_peak,.75)
            self.assertEqual(stream.source_full_scale_samples,0)

    def test_voice_block_does_not_consume_partial_music(self):
        import numpy as np

        output = Playback(lambda **event: None, start_worker=False)
        def feed(plugin, sample, frames):
            output.feed(plugin, dict(sample_rate=48000, channels=2, stream=1,
                                     pcm=struct.pack('<hh', sample, sample) * frames))

        feed('music', 8192, 480)
        feed('voice', 16384, 960)
        np.testing.assert_array_equal(np.frombuffer(output.mix(), '<f4'), np.full(1920, .5))
        feed('music', 8192, 480)
        np.testing.assert_array_equal(np.frombuffer(output.mix(), '<f4'), np.full(1920, .25))

    def test_idle_flush_preserves_resampler_tail_and_restarts_after_a_gap(self):
        import numpy as np
        output=Playback(lambda **v:None,start_worker=False)
        pcm=np.full((4410,2),3277,dtype='<i2').tobytes()
        message=dict(sample_rate=44100,channels=2,stream=1,pcm=pcm)
        output.feed('tail',message)
        blocks=[]
        while (mixed:=output.mix()) is not None:blocks.append(mixed)
        entry=output.streams[('tail',1)]
        entry.last_input-=1
        while (mixed:=output.mix()) is not None:blocks.append(mixed)
        self.assertEqual(sum(map(len,blocks)),4800*8)
        self.assertIsNone(entry.resampler)
        self.assertIsNone(output.mix())
        output.feed('tail',message)
        output.mix()
        self.assertIsNotNone(entry.resampler)

    def test_legacy_bluetooth_override_cannot_redirect_main_hdmi_audio(self):
        device = 'bluealsa:DEV=11:22:33:44:55:66,PROFILE=a2dp'
        events = []
        with tempfile.TemporaryDirectory() as folder, patch('hlauncher.audio_settings.STATE_DIR', Path(folder)), patch.dict('os.environ', HLAUNCHER_AUDIO_DEVICE=device):
            output = Playback(lambda **event: events.append(event), start_worker=False)
        output.feed('carplay', dict(sample_rate=48000, channels=2, stream=1, pcm=bytes(3840)))
        self.assertEqual(events[-1]['route'], 'hdmi')
        self.assertEqual(events[-1]['device'], 'hlauncher_hdmi')
