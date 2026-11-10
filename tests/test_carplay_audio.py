"""CarPlay PCM must flow while screen decode/render is stalled."""
import importlib.util
import json
import os
from pathlib import Path
import struct
import sys
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
with patch.object(sys, 'path', [str(ROOT/'sdk'), str(ROOT/'plugins/carplay'), *sys.path]):
    spec = importlib.util.spec_from_file_location('carplay_audio_backend', ROOT/'plugins/carplay/backend.py')
    backend = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(backend)


def packet(kind, data):
    return struct.pack('!BI', kind, len(data)) + data


class CarplayAudio(unittest.TestCase):
    def setUp(self):
        read, write = os.pipe()
        self.input = os.fdopen(read, 'rb', buffering=0)
        self.output = os.fdopen(write, 'wb', buffering=0)
        self.stop = threading.Event()
        self.reader = None

    def tearDown(self):
        self.stop.set()
        self.output.close()
        if self.reader:
            self.reader.thread.join(timeout=2)
            self.assertFalse(self.reader.thread.is_alive())
        self.input.close()

    def test_pcm_passes_while_video_consumer_is_blocked_and_preserves_bytes(self):
        received = []
        done = threading.Event()
        def audio(*args, **kwargs):
            received.append((args, kwargs))
            if len(received) == 50:
                done.set()
            return True
        carplay = backend.CarplayHDMI(audio=audio)
        self.reader = backend.BridgePackets(self.input, self.stop, carplay.forward_audio, carplay.receive_state)
        pcm = struct.pack('<hhhh', -32768, -1, 0, 32767)
        wire_audio = struct.pack('<IIf', 4, 1, 1.0) + pcm
        # Simulate a slow transition: no video consumption until ALL audio arrives.
        for i in range(50):
            self.output.write(packet(1, struct.pack('!I', i)))
            self.output.write(packet(3, wire_audio))
        self.assertTrue(done.wait(2), 'PCM waited for video decoding')
        self.assertEqual(received, [((pcm, 48000, 2, 1), {})]*50)
        self.assertEqual(carplay.audio_forwarded, 50)
        self.assertEqual(carplay.audio_dropped, 0)
        # Encoded frames retain exact ordering; dropping references would corrupt H264.
        self.assertEqual([self.reader.take() for _ in range(50)],
                         [(1, struct.pack('!I', i)) for i in range(50)])

    def test_voice_controls_take_effect_before_pcm_without_video_polling(self):
        received = []
        done = threading.Event()
        def audio(*args, **kwargs):
            received.append(kwargs)
            if len(received) == 2:
                done.set()
            return True
        carplay = backend.CarplayHDMI(audio=audio)
        carplay.proc = SimpleNamespace(poll=lambda: None)
        self.reader = backend.BridgePackets(self.input, self.stop, carplay.forward_audio, carplay.receive_state)
        def state(**fields):
            self.output.write(packet(2, json.dumps(fields).encode()))
        state(state='projection_voice', fields=dict(call_audio=False, siri=True, recording=True))
        state(state='audio_control', command=8, audio_type=2)
        pcm = struct.pack('<IIf', 5, 2, 1.0) + bytes(640)
        self.output.write(packet(3, pcm))
        state(state='audio_control', command=9, audio_type=2)
        state(state='projection_voice', fields=dict(call_audio=False, siri=False, recording=False))
        self.output.write(packet(3, pcm))
        self.assertTrue(done.wait(2))
        self.assertEqual(received, [dict(voice=True), {}])

    def test_backlog_is_bounded_and_reports_failure_instead_of_dropping_video(self):
        self.reader = backend.BridgePackets(self.input, self.stop, lambda _: None, lambda _: None)
        self.output.write(packet(1, b'x')*257)
        self.reader.thread.join(timeout=2)
        self.assertFalse(self.reader.thread.is_alive())
        with self.assertRaisesRegex(RuntimeError, 'backlog exceeded'):
            self.reader.take()
        self.assertEqual(len(self.reader.pending), 256)

    def test_bad_bridge_packet_wakes_consumer(self):
        self.reader = backend.BridgePackets(self.input, self.stop, lambda _: None, lambda _: None)
        self.output.write(packet(99, b''))
        self.reader.thread.join(timeout=2)
        with self.assertRaisesRegex(ValueError, 'invalid bridge packet'):
            self.reader.take()

    def test_cached_video_is_hidden_until_phone_connects_and_cleared_on_disconnect(self):
        carplay=backend.CarplayHDMI()
        carplay.frame=b'adapter splash or stale phone frame'
        self.assertIsNone(carplay.snapshot()[1])
        carplay.receive_state(dict(state='phone_connected'))
        carplay.frame=b'current phone video'
        self.assertEqual(carplay.snapshot()[1],b'current phone video')
        for state in ('phone_disconnected','usb_failure','waiting_dongle','dongle_ready'):
            carplay.receive_state(dict(state='phone_connected'))
            carplay.frame=b'current phone video'
            carplay.receive_state(dict(state=state))
            self.assertIsNone(carplay.frame)
            # A late redraw cannot make the worker advertise stale video.
            carplay.frame=b'late cached redraw'
            self.assertIsNone(carplay.snapshot()[1])
