"""PCM reaches its separate mixer process without UI/control polling."""
import os
from pathlib import Path
import select
import socket
import struct
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from hlauncher.audio import Capture, PATH
from hlauncher.audio_process import AudioProcess
from hlauncher.playback import Playback, BLOCK

class AudioIsolation(unittest.TestCase):
    def test_radio_mic_negotiates_codec_before_opening_sco(self):
        pcm_path = '/org/bluealsa/radio/pcm'
        unconfigured = dict(Device=PATH, Transport='HFP-AG', Mode='source', Sampling=0)
        configured = dict(unconfigured, Sampling=8000, Channels=1, Codec='CVSD')
        manager = Mock()
        manager.GetManagedObjects.side_effect = [
            {pcm_path: {'org.bluealsa.PCM1': pcm}} for pcm in (unconfigured, configured)
        ]
        codec = Mock()
        bus = Mock()
        dbus = SimpleNamespace(SystemBus=Mock(return_value=bus), Dictionary=lambda value, **_: value,
                               Interface=Mock(side_effect=[manager, codec]))
        capture = Capture()

        def open_capture(args, **kwargs):
            codec.SelectCodec.assert_called_once_with('CVSD', {}, timeout=3)
            self.assertIn('8000', args)
            self.assertTrue(any('PROFILE=sco' in arg for arg in args))
            raise RuntimeError('capture reached')

        with (
            patch.dict(sys.modules, {'dbus': dbus, 'dbus.mainloop': SimpleNamespace(NULL_MAIN_LOOP=None)}),
            patch('hlauncher.audio.subprocess.Popen', side_effect=open_capture) as launch,
        ):
            capture.run()
        launch.assert_called_once()
        self.assertEqual(capture.snapshot()['status'], 'capture reached')

    def test_partial_packets_are_preserved_instead_of_zero_padded(self):
        import numpy as np
        p=Playback(lambda **v:None,start_worker=False)
        message=dict(sample_rate=48000,channels=2,stream=1,pcm=struct.pack('<h',1000)*960)
        p.feed('carplay',message)
        self.assertIsNone(p.mix())
        self.assertEqual(len(p.streams[('carplay',1)].pending),BLOCK//2)
        p.feed('carplay',message)
        np.testing.assert_array_equal(np.frombuffer(p.mix(),dtype='<f4'),np.full(1920,1000/32768,dtype=np.float32))

    @unittest.skipUnless(os.sys.platform=='linux','Uses Linux ALSA null output')
    def test_dedicated_pcm_channel_runs_without_ui_polling(self):
        with tempfile.TemporaryDirectory() as directory,patch.dict(os.environ,HLAUNCHER_STATE_DIR=directory):
            (Path(directory)/'audio.json').write_text('{"pipewire":false}')
            audio=AudioProcess(lambda **v:None,test_device='null')
            sender=audio.open_plugin(SimpleNamespace(id='carplay',capabilities={'audio.playback'}))
            try:
                audio.enable('carplay',True)
                raw=b'P'+struct.pack('!IBB',48000,2,1)+struct.pack('<h',1000)*1920
                # The UI does not call tick/read/feed while the plugin's FD sends PCM.
                for _ in range(50):
                    self.assertTrue(select.select([],[sender],[],1)[1]);sender.send(raw)
                    time.sleep(.02)
                until=time.monotonic()+3
                while audio.written<50*BLOCK and time.monotonic()<until:time.sleep(.05)
                self.assertGreaterEqual(audio.written,50*BLOCK)
                self.assertEqual(audio.failures,0)
                self.assertEqual(sum(v.dropped for v in audio.streams.values()),0)
                self.assertGreater(audio.peak,0)
                self.assertEqual(audio.clip_samples,0)
            finally:
                sender.close();audio.close()

    @unittest.skipUnless(os.sys.platform=='linux','Uses Linux ALSA null output')
    def test_voice_pcm_uses_independent_sink_and_stop_does_not_interrupt_media(self):
        with tempfile.TemporaryDirectory() as directory,patch.dict(os.environ,HLAUNCHER_STATE_DIR=directory):
            (Path(directory)/'audio.json').write_text('{"pipewire":false}')
            events=[];audio=AudioProcess(lambda **v:events.append(v),test_device='null')
            sender=audio.open_plugin(SimpleNamespace(id='carplay',capabilities={'audio.playback'}))
            try:
                audio.enable('carplay',True)
                voice=b'C'+struct.pack('!IBB',16000,1,2)+struct.pack('<h',1000)*320
                media=b'P'+struct.pack('!IBB',48000,2,1)+struct.pack('<h',1000)*1920
                for _ in range(60):
                    sender.send(voice);sender.send(media);time.sleep(.02)
                self.assertTrue(any(e.get('state')=='audio_voice_open' for e in events),events)
                self.assertFalse(any(e.get('state')=='audio_voice_error' for e in events),events)
                audio.stop_voice('carplay')
                before=audio.written
                for _ in range(30):sender.send(media);time.sleep(.02)
                until=time.monotonic()+2
                while audio.written<=before and time.monotonic()<until:time.sleep(.05)
                self.assertGreater(audio.written,before)
                self.assertEqual(audio.failures,0)
                other=audio.open_plugin(SimpleNamespace(id='android-auto',capabilities={'audio.playback'}))
                try:
                    audio.enable('android-auto',True)
                    other.send(voice);time.sleep(.1)
                    self.assertFalse(any(e.get('plugin')=='android-auto:voice' for e in events))
                    audio.select_source('android-auto')
                    for _ in range(20):other.send(voice);time.sleep(.02)
                    until=time.monotonic()+2
                    while not any(e.get('plugin')=='android-auto:voice' for e in events) and time.monotonic()<until:time.sleep(.05)
                    self.assertTrue(any(e.get('plugin')=='android-auto:voice' for e in events))
                finally:other.close()
            finally:sender.close();audio.close()
