"""Boot ordering, asynchronous reconnect policy and graphics isolation."""
import importlib.util
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('radio_reconnect',ROOT/'bluetooth/reconnect.py')
reconnect=importlib.util.module_from_spec(spec);spec.loader.exec_module(reconnect)


class Boot(unittest.TestCase):
    def test_reconnect_attempts_immediately_when_profiles_arrive_and_bounds_retries(self):
        now=[0];p=reconnect.ReconnectPolicy(lambda:now[0]);device={'Paired':True}
        controller={'Powered':True,'UUIDs':[]}
        self.assertFalse(p.ready('radio',controller,device))
        controller['UUIDs']=list(reconnect.REQUIRED)
        self.assertTrue(p.ready('radio',controller,device))
        p.begin();self.assertFalse(p.ready('radio',controller,device))
        p.complete(False);now[0]=1.99;self.assertFalse(p.ready('radio',controller,device))
        now[0]=2;self.assertTrue(p.ready('radio',controller,device))
        for _ in range(10):p.begin();p.complete(False)
        self.assertEqual(p.backoff,30)
        self.assertFalse(p.ready('radio',controller,{'Paired':False}))
        device['Connected']=True;self.assertFalse(p.ready('radio',controller,device))
        device['Connected']=False;self.assertTrue(p.ready('radio',controller,device))
        p.begin();self.assertTrue(p.ready('new-radio',controller,device))

    def test_preferences_do_not_load_the_graphics_stack(self):
        result=subprocess.run([sys.executable,'-c',
            'from hlauncher.config import Preferences; import sys; '
            'assert not any(n=="PIL" or n.startswith("PIL.") or n=="numpy" for n in sys.modules)'],
            cwd=ROOT,capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)

    @unittest.skipUnless(hasattr(socket,'AF_UNIX'),'Unix notification socket')
    def test_notify_marks_profile_readiness(self):
        from hlauncher.boot import notify_ready
        with tempfile.TemporaryDirectory() as d:
            path=str(Path(d)/'notify')
            with socket.socket(socket.AF_UNIX,socket.SOCK_DGRAM) as server:
                server.bind(path);server.settimeout(1)
                with patch.dict(os.environ,{'NOTIFY_SOCKET':path}):notify_ready()
                self.assertIn(b'READY=1',server.recv(1024))

    def test_display_preparation_does_not_block_bluetooth_thread(self):
        from hlauncher.bootstrap import BootstrapLauncher
        entered=threading.Event();release=threading.Event()
        launcher=BootstrapLauncher(lambda **kw:None,SimpleNamespace(close=lambda:None),state=SimpleNamespace())
        def show():entered.set();release.wait(2)
        with patch.object(launcher,'show_pairing',side_effect=show):
            launcher.prepare()
            try:
                self.assertTrue(entered.wait(1))
                self.assertTrue(launcher.preparing.is_alive())
                launcher.closing=True
            finally:release.set();launcher.close()

    def test_home_art_can_be_prepared_without_starting_the_launcher(self):
        from hlauncher.bootstrap import BootstrapLauncher
        from hlauncher.setup_state import SetupState
        from hlauncher.ui import home_art
        with tempfile.TemporaryDirectory() as d:
            state=SetupState(Path(d))
            launcher=BootstrapLauncher(lambda **kw:None,SimpleNamespace(close=lambda:None),state)
            home_art.glyph.cache_clear()
            launcher.prewarm_home()
            self.assertIsNone(launcher.ui)
            self.assertGreater(home_art.glyph.cache_info().currsize,0)
            self.assertEqual(type(launcher.inputs).__name__,'QuietInputs')
            launcher.close()

    def test_maintenance_waits_for_profile_readiness_without_blocking_pairing(self):
        main=(ROOT/'packaging/hlauncher.service').read_text()
        pairing=(ROOT/'packaging/hlauncher-pairing.service').read_text()
        maintenance=(ROOT/'packaging/hlauncher-firstboot.service').read_text()
        self.assertIn('Type=notify',main)
        self.assertNotIn('ExecStartPre=',main)
        self.assertNotIn('hlauncher-firstboot.service',pairing)
        self.assertIn('After=local-fs.target hlauncher.service',maintenance)
        audio=(ROOT/'packaging/hlauncher-audio.service').read_text()
        self.assertIn('Type=dbus\nBusName=org.bluealsa',audio)
