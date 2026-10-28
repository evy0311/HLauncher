import struct
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

    def test_resampling_and_simultaneous_prompt_mixing(self):
        try:
            import audioop
        except ImportError:
            self.skipTest('audioop mixer runs on supported Pi Python 3.11')
        output = Playback(lambda **v: None, start_worker=False)
        output.feed('carplay', dict(sample_rate=16000, channels=1, stream=1,
            pcm=struct.pack('<h', 1000)*320))
        output.feed('carplay', dict(sample_rate=44100, channels=2, stream=2,
            pcm=struct.pack('<h', 2000)*1764))
        mixed = output.mix(audioop)
        self.assertEqual(len(mixed), 3840)
        self.assertEqual(struct.unpack('<1800h',mixed[:3600]), (3000,)*1800)
