"""Desktop simulator runs production UI in a separate hardware-guarded process."""
import base64
import json
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from urllib.error import HTTPError
from urllib.parse import urlsplit,parse_qs
from urllib.request import Request,urlopen

ROOT=Path(__file__).resolve().parents[1]


class DesktopSimulator(unittest.TestCase):
    def test_real_ui_and_hardware_guard(self):
        result=subprocess.run([sys.executable,'-m','tools.desktop_simulator','--self-test'],cwd=ROOT,
                              check=True,capture_output=True,text=True,timeout=20)
        self.assertEqual(json.loads(result.stdout)['passed'],11)

    def test_http_controls_and_frame_authentication(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder=Path(temporary);ready=folder/'ready.txt'
            proc=subprocess.Popen([sys.executable,'-m','tools.desktop_simulator','--state-dir',str(folder/'state'),
                                   '--ready-file',str(ready)],cwd=ROOT,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,text=True)
            try:
                for _ in range(100):
                    if ready.exists():break
                    if proc.poll() is not None:self.fail(proc.stderr.read())
                    time.sleep(.05)
                self.assertTrue(ready.exists(),'Simulator did not start')
                url=urlsplit(ready.read_text());base='http://'+url.netloc
                token=parse_qs(url.query)['token'][0]
                def request(path,data=None,authenticated=True):
                    headers={'X-Simulator-Token':token} if authenticated else {}
                    if data is not None:headers['Content-Type']='application/json'
                    with urlopen(Request(base+path,data=json.dumps(data).encode() if data is not None else None,headers=headers),timeout=3) as response:
                        return response.read()
                with self.assertRaises(HTTPError) as denied:request('/api/view',authenticated=False)
                self.assertEqual(denied.exception.code,403);denied.exception.close()
                request('/api/navigate',dict(page='audio'))
                state=json.loads(request('/api/view'))
                self.assertEqual(state['mode'],'audio_settings')
                self.assertTrue(base64.b64decode(state['frame']).startswith(b'\x89PNG'))
                request('/api/state',dict(brake=False))
                state=json.loads(request('/api/view'))
                self.assertFalse(state['parking']['safely_parked'])
                request('/api/state',dict(brake=True,phone='android-usb'))
                request('/api/navigate',dict(page='projection'))
                state=json.loads(request('/api/view'))
                self.assertEqual(state['active'],'android-auto')
                self.assertTrue(request('/api/screenshot').startswith(b'\x89PNG'))
                with self.assertRaises(HTTPError) as invalid:request('/api/navigate',dict(page='__class__'))
                self.assertEqual(invalid.exception.code,400);invalid.exception.close()
                request('/api/navigate',dict(page='power'))
                self.assertTrue((folder/'state/settings.json').is_file())
            finally:
                if proc.poll() is None:proc.send_signal(signal.SIGINT)
                try:proc.wait(timeout=5)
                except subprocess.TimeoutExpired:proc.kill();proc.wait()
                proc.stderr.close()

            # A new backend process restores the same scenario and preferences.
            ready.unlink()
            proc=subprocess.Popen([sys.executable,'-m','tools.desktop_simulator','--state-dir',str(folder/'state'),
                                   '--ready-file',str(ready)],cwd=ROOT,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,text=True)
            try:
                for _ in range(100):
                    if ready.exists():break
                    if proc.poll() is not None:self.fail(proc.stderr.read())
                    time.sleep(.05)
                self.assertTrue(ready.exists())
                url=urlsplit(ready.read_text());base='http://'+url.netloc;token=parse_qs(url.query)['token'][0]
                state=json.loads(request('/api/view'))
                self.assertEqual(state['controls']['phone'],'android-usb')
                self.assertTrue(state['parking']['safely_parked'])
            finally:
                if proc.poll() is None:proc.send_signal(signal.SIGINT)
                try:proc.wait(timeout=5)
                except subprocess.TimeoutExpired:proc.kill();proc.wait()
                proc.stderr.close()
