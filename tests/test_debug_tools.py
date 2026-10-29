"""Hardware diagnostics must remain bounded and not consume the BT transport."""
from pathlib import Path
from types import SimpleNamespace
import tempfile
import json
import unittest
from unittest.mock import patch
from hlauncher.debug_tools import InputMonitor, ToneTest, hfp_command
from hlauncher.launcher import Launcher
from hlauncher.config import Preferences
from hlauncher.playback import Playback
from hlauncher.plugin_host import PluginHost
from test_architecture import Display


class DebugTools(unittest.TestCase):
    def test_hfp_rx_only_and_no_phone_number_leak(self):
        prefix='D: at.c:162: AT message: '
        self.assertEqual(hfp_command(prefix+'CMD: command:A, value:(null)'),('answer','trigger'))
        self.assertEqual(hfp_command('D: Received AT message: CMD: command=+CHUP value='),('hang_up','trigger'))
        self.assertEqual(hfp_command(prefix+'SET: command:+BVRA, value:1'),('voice_assistant','activate'))
        for line in ('Sending AT message: CMD: command:A, value:(null)',
                     'Unsupported AT message: CMD: command:A, value:(null)',
                     prefix+'SET: command:+BVRA, value:2',
                     prefix+'CMD: command:D123456789, value:(null)'):
            self.assertIsNone(hfp_command(line))

    def test_hfp_peer_check_is_process_isolated_and_rejects_other_peers(self):
        monitor=InputMonitor(lambda **v:None,'11:22:33:44:55:66')
        path='/org/bluealsa/hci0/dev_11_22_33_44_55_66/rfcomm'
        objects={path:{'org.bluealsa.RFCOMM1':{}}}
        def reply():return SimpleNamespace(stdout=json.dumps({'data':[objects]}).encode())
        with patch('hlauncher.debug_tools.subprocess.run',side_effect=lambda *a,**kw:reply()) as run:
            self.assertTrue(monitor.single_radio_rfcomm())
            self.assertEqual(run.call_args.args[0][0],'busctl')
            objects['/org/bluealsa/hci0/dev_AA_BB_CC_DD_EE_FF/rfcomm']={'org.bluealsa.RFCOMM1':{}}
            self.assertFalse(monitor.single_radio_rfcomm())
        with patch('hlauncher.debug_tools.subprocess.run',side_effect=OSError):
            self.assertFalse(monitor.single_radio_rfcomm())

    def test_held_and_command_pulse_are_different(self):
        monitor=InputMonitor(lambda **v:None,'',clock=lambda:10)
        monitor.offer('answer','down','evdev');monitor.drain()
        self.assertTrue(monitor.buttons['answer']['held'])
        monitor.offer('answer','up','evdev');monitor.drain()
        self.assertFalse(monitor.buttons['answer']['held'])
        monitor.offer('voice_assistant','activate','hfp-command');monitor.drain()
        self.assertFalse(monitor.buttons['voice_assistant']['held'])
        self.assertEqual(monitor.buttons['voice_assistant']['count'],1)

    def test_tone_is_bounded_and_channel_separated(self):
        playback=Playback(lambda **v:None,start_worker=False)
        tone=ToneTest(playback)
        with patch('hlauncher.debug_tools.time.monotonic',return_value=10):
            tone.start('Left');tone.tick()
        stream=playback.streams[('diagnostics',0)]
        pcm=b''.join(stream.queue)
        self.assertEqual(len(pcm),3840)
        self.assertTrue(any(pcm))
        self.assertEqual(pcm[2::4],bytes(960))
        self.assertEqual(pcm[3::4],bytes(960))
        with patch('hlauncher.debug_tools.time.monotonic',return_value=12):tone.tick()
        self.assertFalse(playback.streams)

    def test_pages_render_and_back_stops_audio(self):
        with tempfile.TemporaryDirectory() as folder:
            ui=Launcher(framebuffer=Display(),preferences=Preferences(Path(folder)/'settings.json'),manifests={})
            try:
                for page in ('menu','audio','colors','inputs'):
                    ui.debug_tools(page);self.assertEqual(ui.fb.last.size,(720,480))
                ui.debug_tools('audio');ui.tone_test.start('Stereo')
                ui.system_diagnostics();self.assertEqual(ui.tone_test.until,0)
                ui.debug_tools('inputs')
                ui.inputs.offer('answer','trigger','hfp-command');ui.tick()
                self.assertEqual(ui.inputs.buttons['answer']['count'],1)
            finally:ui.close()

    def test_button_has_one_capable_recipient(self):
        sent=[]
        def worker(name,capable=True):
            return SimpleNamespace(manifest=SimpleNamespace(id=name,capabilities={'input.buttons'} if capable else set()),
                                   background_enabled=True,send=lambda **v:sent.append((name,v)) or True)
        host=PluginHost({},720,480,lambda **v:None,lambda:None,None)
        host.workers={'obd':worker('obd',False),'carplay':worker('carplay'),'android-auto':worker('android-auto')}
        host.active='obd';host.button(dict(button='answer',action='trigger',source='hfp-command',sequence=1))
        self.assertEqual([x[0] for x in sent],['carplay'])
