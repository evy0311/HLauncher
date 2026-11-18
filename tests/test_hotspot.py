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
from hlauncher.recovery import Maintenance,parse_wifi_scan
from hlauncher.setup_state import SetupState


class Hotspot(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.folder=Path(self.temp.name)
        self.state=SetupState(self.folder);self.creds=self.state.credentials();self.calls=[]
        self.enterContext(patch('hlauncher.captive_portal.configure_dns'))
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
    def test_unknown_country_defaults_to_us_before_enabling_radio(self):
        def run(args,**kw):
            if args==['iw','reg','get']:
                self.calls.append(args)
                return SimpleNamespace(stdout='country 00: DFS-UNSET\n')
            return self.fake_run(args, **kw)
        with patch.dict('os.environ', HLAUNCHER_WIFI_COUNTRY=''):
            Maintenance(self.state,run).hotspot()
        self.assertEqual(self.calls[:3], [['iw','reg','get'],
            ['raspi-config','nonint','do_wifi_country','US'], ['rfkill','unblock','wifi']])

    def test_scan_preserves_names_and_strength_and_retains_pre_hotspot_results(self):
        output = r"""50:Garage
90:Wi\:Fi
40:Garage
75:Literal\\Backslash
99:
"""
        self.assertEqual(parse_wifi_scan(output), ['Wi:Fi', r'Literal\Backslash', 'Garage'])
        def run(args,**kwargs):
            if '--rescan' in args:
                if m.ap:
                    raise subprocess.CalledProcessError(4,args)
                return SimpleNamespace(stdout=output)
            return self.fake_run(args,**kwargs)
        m=Maintenance(self.state,run)
        m.hotspot()
        m.scan_at = float('-inf')
        scan = m.wifi_scan(refresh=True)
        self.assertEqual(scan['networks'], ['Wi:Fi', r'Literal\Backslash', 'Garage'])
        self.assertIn('last scan', scan['message'])

    def test_failed_wifi_join_restores_hotspot_and_previous_profile(self):
        profile = self.folder/'wifi.nmconnection'
        profile.write_text('previous profile')
        def run(args,**kwargs):
            if 'uuid' in args and 'up' in args:
                raise subprocess.CalledProcessError(4,args)
            return self.fake_run(args,**kwargs)
        m=Maintenance(self.state,run)
        m.ap = True
        with patch('hlauncher.recovery.WIFI_PROFILE',profile):
            with self.assertRaisesRegex(ValueError,'Could not join'):
                m.perform(dict(operation='wifi',ssid='Hidden network',password='personal-pass',hidden=True))
        self.assertEqual(profile.read_text(), 'previous profile')
        self.assertTrue(m.ap)
        self.assertIn(['nmcli','--wait','15','connection','up','HLauncher Recovery'],self.calls)

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
