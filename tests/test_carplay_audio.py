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
        read, write = os.pipe()
        self.video = os.fdopen(read, 'rb', buffering=0)
        self.video_output = os.fdopen(write, 'wb', buffering=0)
        self.stop = threading.Event()
        self.reader = None

    def tearDown(self):
        self.stop.set()
        self.output.close()
        if self.reader:
            self.reader.thread.join(timeout=2)
            self.assertFalse(self.reader.thread.is_alive())
        self.input.close()
        self.video.close()
        self.video_output.close()

    def test_pcm_passes_while_video_consumer_is_blocked_and_preserves_bytes(self):
        received = []
        done = threading.Event()
        def audio(*args, **kwargs):
            received.append((args, kwargs))
            if len(received) == 50:
                done.set()
            return True
        carplay = backend.CarplayHDMI(audio=audio)
        self.reader = backend.BridgePackets(self.input, self.stop, carplay.forward_audio,
                                            carplay.receive_state, video=self.video)
        pcm = struct.pack('<hhhh', -32768, -1, 0, 32767)
        wire_audio = struct.pack('<IIf', 4, 1, 1.0) + pcm
        # Simulate a slow transition: no video consumption until ALL audio arrives.
        for i in range(50):
            self.video_output.write(packet(1, struct.pack('!I', i)))
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
        self.reader = backend.BridgePackets(self.input, self.stop, carplay.forward_audio,
                                            carplay.receive_state, video=self.video)
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

    def test_status_backlog_sheds_notifications_without_interrupting_audio(self):
        got_audio = threading.Event()
        self.reader = backend.BridgePackets(self.input, self.stop, lambda _: got_audio.set(),
                                            lambda _: None, video=self.video)
        for index in range(300):
            self.output.write(packet(2, json.dumps({'index': index}).encode()))
        self.output.write(packet(3, b'pcm'))
        self.assertTrue(got_audio.wait(2))
        self.assertEqual(len(self.reader.pending), 256)
        self.assertEqual(json.loads(self.reader.take()[1]), {'index': 44})

    def test_caller_details_reach_active_voice_state_without_entering_status_queue(self):
        carplay = backend.CarplayHDMI()
        carplay.proc = SimpleNamespace(poll=lambda: None)
        self.reader = backend.BridgePackets(self.input, self.stop, lambda _: None,
                                            carplay.receive_state, video=self.video)
        details = dict(name='Test Caller', number='+15550100', incoming=True)
        voice = dict(call_audio=True, siri=False, recording=True)
        self.output.write(packet(2, json.dumps(dict(state='projection_call', call=details)).encode()))
        status = dict(state='projection_voice', fields=voice)
        self.output.write(packet(2, json.dumps(status).encode()))
        with self.reader.condition:
            self.assertTrue(self.reader.condition.wait_for(lambda: self.reader.pending, timeout=2))
        self.assertEqual(json.loads(self.reader.take()[1]), status)
        self.assertEqual(carplay.voice_snapshot()['call'], details)
        carplay.receive_state(dict(state='phone_disconnected'))
        self.assertNotIn('call', carplay.voice_snapshot())

    def test_bad_bridge_packet_wakes_consumer(self):
        self.reader = backend.BridgePackets(self.input, self.stop, lambda _: None,
                                            lambda _: None, video=self.video)
        self.output.write(packet(99, b''))
        self.reader.thread.join(timeout=2)
        with self.assertRaisesRegex(ValueError, 'invalid bridge packet'):
            self.reader.take()

    def test_unplug_updates_landing_status_while_video_consumer_is_blocked(self):
        carplay = backend.CarplayHDMI()
        carplay.receive_state(dict(state='phone_connected'))
        carplay.frame = b'last phone frame'
        audio_received = threading.Event()
        self.reader = backend.BridgePackets(self.input, self.stop, lambda _: audio_received.set(),
                                            carplay.receive_state, video=self.video)
        self.output.write(packet(2, b'{"state":"phone_disconnected"}'))
        self.output.write(packet(3, b'pcm'))
        self.assertTrue(audio_received.wait(2))
        _, frame, _, status = carplay.snapshot()
        self.assertIsNone(frame)
        self.assertEqual(status, 'Phone disconnected')

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
