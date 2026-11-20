import math
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from hlauncher.resample import Resampler


from test_architecture import parked_radio


class AudioQuality(unittest.TestCase):
    def test_streaming_flush_preserves_frame_count_and_chunk_boundaries(self):
        signal=(.1*np.sin(2*np.pi*997*np.arange(44100)/44100)).astype(np.float32)
        stereo=np.repeat(signal[:,None],2,axis=1)
        outputs=[]
        for chunk in (137,882,44100):
            converter=Resampler(44100)
            try:
                converted=[converter.process(stereo[i:i+chunk]) for i in range(0,len(stereo),chunk)]
                converted.append(converter.flush())
                converted=np.concatenate(converted)
                self.assertEqual(len(converted),48000)
                outputs.append(converted)
                with self.assertRaises(RuntimeError):converter.process(stereo[:1])
            finally:converter.close()
        for output in outputs[1:]:np.testing.assert_allclose(output,outputs[0],atol=1e-7)

    def test_sinc_conversion_preserves_upper_audio_band_at_unity(self):
        rate = 44100
        signal = .1*np.sin(2*np.pi*20000*np.arange(rate*2)/rate)
        stereo = np.repeat(signal[:,None], 2, axis=1).astype(np.float32)
        converter = Resampler(rate)
        try:
            converted = np.concatenate([converter.process(stereo[i:i+882]) for i in range(0,len(stereo),882)])
        finally:converter.close()
        rms = np.sqrt(np.mean(converted[-48000:]**2))
        self.assertLess(abs(20*math.log10(rms/(.1/math.sqrt(2)))), .15)

    def test_sinc_downsampling_rejects_out_of_band_alias(self):
        signal = .1*np.sin(2*np.pi*12000*np.arange(96000)/48000)
        converter = Resampler(48000,16000)
        try:converted=converter.process(np.repeat(signal[:,None],2,axis=1).astype(np.float32))
        finally:converter.close()
        self.assertLess(float(np.sqrt(np.mean(converted[-16000:]**2))),1e-6)


@parked_radio
class ShutdownUI(unittest.TestCase):
    def test_restart_button_requests_reboot_and_recovers_from_failure(self):
        from hlauncher.launcher import Launcher
        from hlauncher.config import Preferences
        from test_architecture import Display
        for failure in (False,True):
            with self.subTest(failure=failure),tempfile.TemporaryDirectory() as folder:
                prefs=Preferences(Path(folder)/'settings.json');prefs.accept_safety_notice()
                ui=Launcher(framebuffer=Display(),preferences=prefs,manifests={})
                try:
                    with patch('hlauncher.launcher.subprocess.run',side_effect=OSError('unavailable') if failure else None) as command:
                        ui.shutdown_page()
                        command.assert_not_called()
                        next(action for _,action in ui.actions if action==ui.restart_pi)()
                        command.assert_called_once_with(['systemctl','reboot','--no-block'],check=True,
                                                        capture_output=True,text=True,timeout=3)
                    if failure:
                        self.assertEqual(ui.mode,'shutdown_confirm')
                        self.assertIn('Restart failed',ui.banner)
                        self.assertIn(ui.restart_pi,[action for _,action in ui.actions])
                    else:
                        self.assertEqual(ui.mode,'shutdown_pending')
                        self.assertEqual(ui.shutdown_action,'reboot')
                        self.assertFalse(ui.actions)
                finally:ui.close()

    def test_shutdown_action_uses_orderly_systemd_poweroff(self):
        from hlauncher.launcher import Launcher
        from hlauncher.config import Preferences
        from test_architecture import Display
        with tempfile.TemporaryDirectory() as folder:
            ui=Launcher(framebuffer=Display(),preferences=Preferences(Path(folder)/'settings.json'),manifests={})
            try:
                ui.mode='diagnostics';ui.draw()
                action=next(action for _,action in ui.actions if action==ui.shutdown_page)
                with patch('hlauncher.launcher.subprocess.run') as command:
                    action()
                    self.assertEqual(ui.mode,'shutdown_confirm')
                    command.assert_not_called()
                    ui.shutdown_pi()
                    command.assert_called_once_with(['systemctl','poweroff','--no-block'],check=True,
                                                    capture_output=True,text=True,timeout=3)
                    self.assertEqual(ui.mode,'shutdown_pending')
            finally:ui.close()

    def test_failed_shutdown_returns_to_confirmation(self):
        from hlauncher.launcher import Launcher
        from hlauncher.config import Preferences
        from test_architecture import Display
        with tempfile.TemporaryDirectory() as folder:
            ui=Launcher(framebuffer=Display(),preferences=Preferences(Path(folder)/'settings.json'),manifests={})
            try:
                with patch('hlauncher.launcher.subprocess.run',side_effect=OSError('unavailable')):
                    ui.shutdown_pi()
                self.assertEqual(ui.mode,'shutdown_confirm')
                self.assertIn('failed',ui.banner)
            finally:ui.close()


class MicrophoneConversion(unittest.TestCase):
    def test_mono_microphone_conversion_preserves_duration_and_unity(self):
        converter = Resampler(8000, 16000, channels=1, realtime=True)
        try:
            signal = .1 * np.sin(2 * np.pi * 440 * np.arange(8000) / 8000)
            # 20 ms Bluetooth capture periods should fit into individual
            # 20 ms USB frames after a short resampler startup.
            frames = [converter.process(signal[i:i + 160]) for i in range(0, len(signal), 160)]
            self.assertTrue(all(len(frame) <= 320 for frame in frames))
            self.assertTrue(all(len(frame) == 320 for frame in frames[3:]))
            converted = np.concatenate([*frames, converter.flush()])
            self.assertEqual(converted.shape, (16000, 1))
            self.assertAlmostEqual(float(np.max(np.abs(converted[200:-200]))), .1, places=3)
        finally:
            converter.close()
