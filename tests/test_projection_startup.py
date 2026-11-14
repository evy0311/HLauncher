"""Background startup and exclusion across a still-running USB subprocess."""
from pathlib import Path
import os
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from hlauncher.projection import ProjectionLease,ProjectionBusy,carplay_adapter_present
from hlauncher.plugin_host import PluginHost
from hlauncher.adapter_branding import BrandingRequests


class Projection(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.made=[]
        self.manifests={key:SimpleNamespace(id=key,name=key,keep_alive=True,capabilities=set()) for key in ('carplay','android-auto')}
        self.host=PluginHost(self.manifests,720,480,lambda **v:None,lambda *a:None,SimpleNamespace(stop=lambda _:None),state_dir=self.root)
        made=self.made;lock=self.root/'projection.lock'
        class Worker:
            def __init__(self,manifest,*a,**kw):
                self.lease=ProjectionLease(lock);self.manifest=manifest;self.messages=[];self.ready=True;self.closed=False
                self.proc=SimpleNamespace(pid=100+len(made));made.append(self)
            def send(self,**message):self.messages.append(message);return True
            def close(self):self.closed=True  # Simulate a USB child still holding the descriptor.
        self.worker=patch('hlauncher.plugin_host.Worker',Worker);self.worker.start()
    def tearDown(self):
        self.host.close()
        for worker in self.made:worker.lease.close()
        self.worker.stop();self.temp.cleanup()
    def test_standby_does_not_open_the_page_or_start_a_second_projection(self):
        self.host.ensure_background_carplay()
        self.assertIsNone(self.host.active)
        self.assertEqual(list(self.host.workers),['carplay'])
        self.assertFalse(self.made[0].active)
        self.assertTrue(self.made[0].background_enabled)
        self.assertEqual(self.made[0].messages[-1]['type'],'host.start')
        self.host.ensure_background_carplay();self.assertEqual(len(self.made),1)
        self.host.activate('carplay')
        self.assertEqual(len(self.made),1)
        self.assertEqual(self.host.active,'carplay')
        self.assertEqual(self.made[0].messages[-1]['type'],'host.activate')
    def test_handoff_waits_for_usb_lease_not_just_worker_close(self):
        self.host.activate('carplay');old=self.made[0]
        self.host.activate('android-auto')
        self.assertTrue(old.closed)
        self.assertNotIn('android-auto',self.host.workers)
        self.assertEqual(self.host.projection_request,'android-auto')
        self.assertEqual(len(self.made),1)
        old.lease.close();self.host.projection_retry=0;self.host._projection_tick()
        self.assertEqual(list(self.host.workers),['android-auto'])
        self.assertEqual(self.host.active,'android-auto')
    def test_disconnected_projection_discards_and_releases_queued_frame(self):
        from unittest.mock import Mock
        worker=SimpleNamespace(video_available=False,take_frame=Mock(return_value=b'stale'))
        with patch.object(self.host,'workers',{'carplay':worker}):
            self.host.active='carplay'
            self.assertIsNone(self.host.frame())
            worker.take_frame.assert_called_once()
            worker.video_available=True
            self.assertEqual(self.host.frame(),b'stale')
        self.host.active=None

    def test_background_detection_does_not_steal_android_auto(self):
        self.host.activate('android-auto');self.host.ensure_background_carplay()
        self.assertEqual(list(self.host.workers),['android-auto'])
    def test_branding_request_survives_restart_and_stale_reports(self):
        store=BrandingRequests(self.root/'branding.json');request=store.request()
        reopened=BrandingRequests(store.path);self.assertTrue(reopened.pending)
        reopened.update('older-request','sent');self.assertTrue(reopened.pending)
        reopened.update(request,'sent');self.assertFalse(reopened.pending)
        self.assertEqual(reopened.data['status'],'transferred')
        self.assertFalse(reopened.data['verified'])
        reopened.update(request,'waiting');self.assertFalse(reopened.pending)
        reopened.request();self.assertTrue(reopened.pending)
    def test_detects_only_known_adapter_ids(self):
        device=self.root/'usb/1-1';device.mkdir(parents=True)
        (device/'idVendor').write_text('1314');(device/'idProduct').write_text('1520')
        self.assertTrue(carplay_adapter_present(self.root/'usb'))
        (device/'idProduct').write_text('ffff');self.assertFalse(carplay_adapter_present(self.root/'usb'))


class InheritedLease(unittest.TestCase):
    def test_lease_remains_exclusive_until_usb_subprocess_exits(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'lease';lease=ProjectionLease(path)
            child=subprocess.Popen([sys.executable,'-c','import sys; print("ready",flush=True); sys.stdin.read()'],
                                   stdin=subprocess.PIPE,stdout=subprocess.PIPE,pass_fds=(lease.fd,))
            try:
                self.assertEqual(child.stdout.readline(),b'ready\n')
                lease.close()
                with self.assertRaises(ProjectionBusy):ProjectionLease(path)
                child.stdin.close();child.wait(timeout=3)
                acquired=ProjectionLease(path);acquired.close()
            finally:
                if child.poll() is None:child.kill();child.wait()
                child.stdout.close();lease.close()


class LauncherStandby(unittest.TestCase):
    import test_radio_ui as _fixtures
    setUp=_fixtures.RadioUI.setUp
    tearDown=_fixtures.RadioUI.tearDown
    def test_attached_adapter_starts_audio_without_opening_a_tile(self):
        ui=self.ui;ui.prefs.data['setup_complete']=True;ui.home()
        with patch('hlauncher.projection.carplay_adapter_present',return_value=True),patch.object(ui.host,'ensure_background_carplay') as start:
            ui.tick();start.assert_called_once()
            self.assertEqual(ui.mode,'home');self.assertIsNone(ui.host.active)
    def test_disabled_carplay_is_not_started(self):
        ui=self.ui;ui.prefs.data['setup_complete']=True;ui.prefs.set_enabled(ui.manifests['carplay'],False)
        with patch('hlauncher.projection.carplay_adapter_present',return_value=True),patch.object(ui.host,'ensure_background_carplay') as start:
            ui.tick();start.assert_not_called()

    def test_paired_boot_projection_survives_hondalink_open_and_close(self):
        from hlauncher.bootstrap import BootstrapLauncher
        from hlauncher.setup_state import SetupState, atomic_json
        from hlauncher import config

        ui = self.ui
        ui.prefs.data.update(setup_complete=True, default_plugin='carplay')
        state = SetupState(ui.prefs.path.parent)
        atomic_json(state.path, {'address': '02:00:00:00:00:11', 'verified': True})
        bootstrap = BootstrapLauncher(ui.event, ui.protocols, state, lambda *a, **kw: ui)
        worker = SimpleNamespace(
            manifest=ui.manifests['carplay'], ready=False, video_available=False,
            status='Waiting for phone', send=lambda **kw: True, close=lambda: None,
        )
        app_id = 'com.honda.hondalink.connect'
        with patch.multiple(config, RADIO_ADDRESS=config.RADIO_ADDRESS,
                            RADIO_PATH=config.RADIO_PATH, RFCOMM_PATH=config.RFCOMM_PATH), \
                patch.object(bootstrap, 'show_pairing'), patch.object(bootstrap, 'prewarm_home'), \
                patch('hlauncher.plugin_host.Worker', return_value=worker) as create, \
                patch.object(ui.host, 'tick'), patch.object(ui.host, 'frame', return_value=None):
            bootstrap.prepare()
            bootstrap.preparing.join()
            bootstrap.tick()
            self.assertEqual(bootstrap.session, {})
            self.assertEqual(ui.host.active, 'carplay')
            for connected in (True, False, True):
                bootstrap.session_changed(connected=connected, authenticated=connected)
                if connected:
                    self.assertTrue(bootstrap.launch(app_id))
                bootstrap.tick()
                self.assertEqual(ui.mode, 'plugin')
                self.assertIs(ui.host.workers['carplay'], worker)
            create.assert_called_once()
