"""Hotspot activation must enable the radio and retain safe, actionable failures."""
import contextlib
import io
import json
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch,PropertyMock
from hlauncher.recovery import Maintenance
from hlauncher.setup_state import SetupState


class Hotspot(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.folder=Path(self.temp.name)
        self.state=SetupState(self.folder);self.creds=self.state.credentials();self.calls=[]
    def tearDown(self):self.temp.cleanup()
    def fake_run(self,args,**kwargs):
        self.calls.append(args)
        if args==['iw','reg','get']:return SimpleNamespace(stdout='country US: DFS-FCC\n')
        return SimpleNamespace(stdout='')
    def test_disabled_wifi_is_enabled_before_activation(self):
        m=Maintenance(self.state,self.fake_run)
        m.hotspot();self.assertTrue(m.ap)
        self.assertLess(self.calls.index(['rfkill','unblock','wifi']),self.calls.index(['nmcli','radio','wifi','on']))
        self.assertLess(self.calls.index(['nmcli','radio','wifi','on']),next(i for i,a in enumerate(self.calls) if 'up' in a))
    def test_unknown_country_does_not_enable_radio(self):
        calls=[]
        def run(args,**kw):calls.append(args);return SimpleNamespace(stdout='country 00: DFS-UNSET\n')
        with self.assertRaisesRegex(ValueError,'country'):Maintenance(self.state,run).hotspot()
        self.assertEqual(calls,[['iw','reg','get']])
    def test_failure_preserves_stage_and_error_but_not_password_or_ssid(self):
        def run(args,**kwargs):
            if 'add' in args:
                raise subprocess.CalledProcessError(4,args,stderr='Cannot create '+self.creds['ssid']+' with password '+self.creds['password'])
            return self.fake_run(args,**kwargs)
        output=io.StringIO();m=Maintenance(self.state,run)
        with contextlib.redirect_stdout(output):m.process(dict(operation='hotspot'))
        status=json.loads((self.folder/'maintenance-status.json').read_text())
        failure=json.loads((self.folder/'maintenance-failure.json').read_text())
        self.assertEqual(status['status'],'Failed');self.assertIn('profile creation',status['message'])
        self.assertEqual(failure['returncode'],4)
        for text in (output.getvalue(),json.dumps(status),json.dumps(failure)):
            self.assertNotIn(self.creds['password'],text);self.assertNotIn(self.creds['ssid'],text)
        m.run=self.fake_run;m.hotspot();self.assertFalse((self.folder/'maintenance-failure.json').exists())
    def test_missing_tool_has_actionable_message(self):
        def run(args,**kwargs):raise FileNotFoundError('not installed')
        with contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(ValueError,'tool is missing: iw'):Maintenance(self.state,run).hotspot()

    def test_manual_hotspot_stays_up_after_completed_setup(self):
        m=Maintenance(self.state,self.fake_run)
        with patch.object(type(self.state),'peer',new_callable=PropertyMock,return_value={'address':'AA:BB:CC:DD:EE:FF'}):
            m.perform(dict(operation='hotspot'))
            self.assertFalse(m.finish_initial_hotspot(True));self.assertTrue(m.ap)
            m.perform(dict(operation='hotspot',automatic=True))
            self.assertTrue(m.finish_initial_hotspot(True));self.assertFalse(m.ap)
