"""Fresh setup, pairing ownership, production logging and recovery access contracts."""
import base64
import http.client
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import threading
import unittest
from unittest.mock import patch
from http.server import ThreadingHTTPServer

from hlauncher.config import Preferences, ROOT, SAFETY_NOTICE_VERSION, TILE_COLORS
from hlauncher.catalog import Manifest
from hlauncher.onboarding import Onboarding
from hlauncher.setup_state import SetupState, atomic_json
from hlauncher.bootstrap import BootstrapLauncher
from hlauncher.event_log import EventLog
from hlauncher.protocol_diagnostics import ProtocolDiagnostics
from hlauncher.launcher import Launcher
from hlauncher.recovery import handler_for, Maintenance
from hlauncher import storage
from test_architecture import Display

PEER='02:00:00:00:00:11'
OTHER='AA:BB:CC:DD:EE:FF'


class Setup(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.root=Path(self.temp.name)
        self.prefs=Preferences(self.root/'settings.json')
        self.manifests={x:Manifest.load(ROOT/'plugins'/x,bundled=True) for x in ('carplay','android-auto','obd')}
    def tearDown(self):self.temp.cleanup()

    def test_fresh_wizard_resumes_and_validates_enabled_default(self):
        self.assertFalse(self.prefs.data['setup_complete'])
        wizard=Onboarding(self.prefs,self.manifests)
        wizard.move(1);wizard.theme(next(iter(TILE_COLORS)))
        reloaded=Preferences(self.prefs.path)
        self.assertEqual(reloaded.data['setup_step'],1)
        reloaded.data['enabled']['carplay']=False;reloaded.save()
        wizard=Onboarding(reloaded,self.manifests)
        with self.assertRaises(ValueError):wizard.default('carplay')
        wizard.plugin('carplay');wizard.default('carplay');wizard.plugin('carplay')
        self.assertIsNone(wizard.prefs.data['default_plugin'])
        with self.assertRaises(ValueError):
            wizard.finish()
        reloaded.accept_safety_notice()
        wizard.finish()
        self.assertTrue(Preferences(self.prefs.path).data['setup_complete'])
        self.assertFalse(Preferences(self.prefs.path).data['debug_mode'])

    def test_legacy_settings_migrate_without_resetting_plugins(self):
        self.prefs.path.write_text(json.dumps({'enabled':{'carplay':False},'default_plugin':'obd'}))
        loaded=Preferences(self.prefs.path)
        self.assertTrue(loaded.data['setup_complete'])
        self.assertFalse(loaded.safety_notice_accepted)
        self.assertFalse(loaded.enabled(self.manifests['carplay']))
        self.assertFalse(loaded.data['debug_mode'])

    def test_upgrade_gates_startup_until_current_notice_is_saved(self):
        self.prefs.path.write_text(json.dumps({
            'setup_complete': True, 'default_plugin': 'carplay',
            'safety_notice_version': True,
        }))
        prefs = Preferences(self.prefs.path)
        ui = Launcher(framebuffer=Display(), preferences=prefs, manifests=self.manifests)
        try:
            with patch.object(ui.host, 'activate') as activate:
                self.assertTrue(ui.launch('com.honda.hondalink.launcher'))
                self.assertEqual(ui.mode, 'safety_notice')
                ui.open_plugin('carplay')
                activate.assert_not_called()
            ui.actions[0][1]()
            self.assertEqual(ui.mode, 'recovery_settings')
            ui.actions[0][1]()
            self.assertEqual(ui.mode, 'safety_notice')
            with patch.object(prefs, 'save', side_effect=OSError):
                ui.actions[-1][1]()
            self.assertEqual(ui.mode, 'safety_notice')
            self.assertFalse(prefs.safety_notice_accepted)
            ui.actions[-1][1]()
            self.assertEqual(ui.mode, 'home')
            self.assertTrue(ui.pending_default)
            reloaded = Preferences(prefs.path)
            self.assertTrue(reloaded.safety_notice_accepted)
            self.assertEqual(reloaded.data['safety_notice_version'], SAFETY_NOTICE_VERSION)
            self.assertEqual(reloaded.data['default_plugin'], 'carplay')
            with patch('hlauncher.config.SAFETY_NOTICE_VERSION', SAFETY_NOTICE_VERSION + 1):
                self.assertFalse(Preferences(prefs.path).safety_notice_accepted)
        finally:
            ui.close()

    def test_finish_overrides_concurrent_recovery_debug_setting(self):
        self.prefs.accept_safety_notice()
        web=Preferences(self.prefs.path)
        web.data['debug_mode']=True;web.save()
        Onboarding(self.prefs,self.manifests).finish()
        self.assertFalse(Preferences(self.prefs.path).data['debug_mode'])

    def test_recovery_and_ui_preferences_merge_independent_changes(self):
        self.prefs.save()
        web=Preferences(self.prefs.path)
        web.data['debug_mode']=True;web.save()
        self.prefs.set_tile_color(next(iter(TILE_COLORS)))
        self.assertTrue(Preferences(self.prefs.path).data['debug_mode'])
        ui=Preferences(self.prefs.path);web=Preferences(self.prefs.path)
        ui.data['enabled']['carplay']=False;ui.save()
        web.data['enabled']['obd']=True;web.save()
        self.assertEqual(Preferences(self.prefs.path).data['enabled'],{'carplay':False,'obd':True})

    def test_production_plugin_output_redacts_packets_and_errors_still_show(self):
        from sdk.hlauncher_sdk.logging import output_summary
        self.assertIsNone(output_summary('{"state":"rx","hex":"private"}',False))
        text=output_summary('{"state":"socket_error","error":"closed","hex":"private"}',False)
        self.assertNotIn('private',text)
        self.assertIn('closed',text)
        self.assertIn('private',output_summary('{"state":"rx","hex":"private"}',True))
        self.assertIsNone(output_summary('normal frame counter',False))

    def test_manual_capture_stop_is_not_restarted_by_debug_refresh(self):
        self.prefs.data['debug_mode']=True;self.prefs.save()
        monitor=ProtocolDiagnostics(self.root/'captures',min_free=0)
        log=EventLog(monitor,self.prefs,self.root/'logs')
        self.assertTrue(monitor.recording)
        monitor.stop();log.refresh(force=True)
        self.assertFalse(monitor.recording)
        log.close();monitor.close()

    def test_job_queue_does_not_overwrite_pending_operation(self):
        from hlauncher import recovery
        with patch.object(recovery,'STATE_DIR',self.root):
            recovery.request_job('protect')
            with self.assertRaises(FileExistsError):recovery.request_job('reboot')
        item=json.loads((self.root/'maintenance-request.json').read_text())
        self.assertEqual(item['operation'],'protect')
        self.assertEqual((self.root/'maintenance-request.json').stat().st_mode & 0o777,0o600)

    def test_storage_layout_must_really_bind_state_bluetooth_and_network(self):
        persist=self.root/'persist';persist.mkdir();(persist/'.hlauncher-state-v1').write_text('1')
        mounts={'/':dict(source='/dev/root',target='/',fstype='ext4',options='rw'),
            str(persist):dict(source='/dev/data',target=str(persist),fstype='ext4',options='rw')}
        for path in ('/var/lib/hlauncher','/var/lib/bluetooth','/etc/NetworkManager/system-connections'):
            mounts[path]=dict(source='/dev/data[/state]',target=path,fstype='ext4',options='rw')
        def run(args,**kwargs):return SimpleNamespace(stdout=json.dumps({'filesystems':[mounts[str(args[3])]]}))
        self.assertTrue(storage.status(run,persist)['available'])
        mounts['/var/lib/bluetooth']['source']='/dev/root'
        self.assertFalse(storage.status(run,persist)['available'])

    def test_image_preparation_refuses_live_root_and_recovery_card_is_device_specific(self):
        import importlib.util
        spec=importlib.util.spec_from_file_location('prepare_image',ROOT/'scripts/prepare_image.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        with self.assertRaises(ValueError):module.prepare('/',self.root,'a'*36,'US')
        from hlauncher.firstboot import write_recovery_card
        credentials=SetupState(self.root).credentials()
        write_recovery_card(credentials,self.root)
        self.assertIn(credentials['ssid'],(self.root/'HLAUNCHER-SETUP.txt').read_text())
        self.assertIn(credentials['password'],(self.root/'HLAUNCHER-SETUP.txt').read_text())

    def test_pairing_window_candidate_lock_verification_and_forget(self):
        now=[1];state=SetupState(self.root,clock=lambda:now[0])
        self.assertFalse(state.admit(OTHER,{'Alias':'Someone’s phone'}))
        self.assertTrue(state.admit(PEER,{'Alias':'HandsFreeLink'}))
        self.assertFalse(state.admit(OTHER,{'Alias':'HandsFreeLink'}))
        self.assertTrue(SetupState(self.root).allowed(PEER))
        with self.assertRaises(ValueError):state.verify(OTHER)
        state.verify(PEER)
        self.assertEqual(SetupState(self.root).peer,PEER)
        self.assertFalse(state.admit(OTHER,{'Alias':'HandsFreeLink'}))
        self.assertFalse(state.pairing_open())
        state.forget();self.assertIsNone(state.peer)
        self.assertTrue(state.path.exists())  # tombstone prevents legacy env re-adoption
        now[0]=302
        self.assertFalse(state.admit(PEER,{'Alias':'HandsFreeLink'}))

    def test_candidate_cannot_be_reused_from_an_old_boot(self):
        state=SetupState(self.root)
        self.assertTrue(state.admit(PEER,{'Alias':'HandsFreeLink'}))
        with patch('hlauncher.setup_state.BOOT_ID','another-boot'):
            self.assertFalse(state.allowed(PEER))

    def test_authorization_does_not_extend_candidate_or_pairing_window(self):
        now=[1];state=SetupState(self.root,clock=lambda:now[0])
        state.deadline=20
        with patch('hlauncher.setup_state.time.time',return_value=1000):
            self.assertTrue(state.admit(PEER,{'Alias':'HandsFreeLink'}))
            self.assertEqual(json.loads((self.root/'pairing-candidate.json').read_text())['expires'],1019)
        now[0]=10
        with patch('hlauncher.setup_state.time.time',return_value=1009):
            self.assertTrue(state.admit(PEER,{'Alias':'HandsFreeLink'}))
            self.assertEqual(state.candidate_deadline,20)
        state.open_pairing()
        self.assertFalse(state.allowed(PEER))

    def test_hotspot_name_and_simple_default_password_survive_restart(self):
        first=SetupState(self.root).credentials()
        self.assertEqual(first,SetupState(self.root).credentials())
        self.assertNotEqual(first,SetupState(self.root/'other').credentials())
        self.assertEqual(len(first['password']),16)
        self.assertNotEqual(first['password'], SetupState(self.root/'other').credentials()['password'])
        self.assertEqual((self.root/'recovery.json').stat().st_mode & 0o777,0o600)

    def test_bootstrap_defers_heavy_ui_and_restores_session(self):
        events=[];made=[]
        ui=SimpleNamespace(inputs=object(),session_changed=lambda **v:made.append(v),launch=lambda app:app=='known',close=lambda:None)
        def factory(*a,**kw):made.append('constructed');return ui
        protocols=SimpleNamespace(close=lambda:None)
        bootstrap=BootstrapLauncher(lambda **v:events.append(v),protocols,SetupState(self.root),factory)
        bootstrap.tick();self.assertFalse(made)
        bootstrap.session_changed(connected=True)
        bootstrap.set_peer(PEER)
        from hlauncher import config
        with patch.object(config,'RADIO_ADDRESS',config.RADIO_ADDRESS),patch.object(config,'RADIO_PATH',config.RADIO_PATH),patch.object(config,'RFCOMM_PATH',config.RFCOMM_PATH):
            self.assertTrue(bootstrap.launch('known'))
        self.assertEqual(made,['constructed',{'connected':True}])
        self.assertIs(bootstrap.inputs,ui.inputs)

    def test_normal_logging_never_writes_packets_and_debug_is_live(self):
        monitor=ProtocolDiagnostics(self.root/'captures',min_free=0)
        log=EventLog(monitor,self.prefs,self.root/'logs')
        log(state='rx',hex='secret-payload')
        log(state='socket_error',error='disconnected',hex='secret-payload')
        self.assertFalse(monitor.recording)
        self.assertNotIn('secret-payload',(self.root/'logs/errors.jsonl').read_text())
        self.prefs.data['debug_mode']=True;self.prefs.save();log.refresh(force=True)
        log(state='rx',hex='test-payload')
        self.assertTrue(monitor.recording)
        self.assertIn('test-payload',(self.root/'logs/debug.jsonl').read_text())
        self.prefs.data['debug_mode']=False;self.prefs.save();log.refresh(force=True)
        self.assertFalse(monitor.recording)
        log.close();monitor.close()

    def test_wizard_renders_every_page_and_blocks_default_until_finished(self):
        ui=Launcher(framebuffer=Display(),preferences=self.prefs,manifests=self.manifests)
        try:
            self.assertTrue(ui.launch('com.honda.hondalink.launcher'))
            self.assertEqual(ui.mode, 'safety_notice')
            ui.actions[-1][1]()
            self.assertEqual(ui.mode,'onboarding')
            for step in range(6):
                ui.wizard.save(setup_step=step);ui.draw()
                self.assertEqual(ui.fb.last.size,(720,480))
            ui.protocol_tests();self.assertEqual(ui.mode,'onboarding')
            ui.system_diagnostics();self.assertEqual(ui.mode,'system_settings')
            for method in (ui.system_settings,ui.recovery_page,lambda:ui.storage_confirm(True)):
                method();self.assertTrue(ui.actions)
            with patch('hlauncher.launcher.subprocess.run') as run:
                ui.shutdown_page();ui.draw();run.assert_not_called()
            ui.setup_finish()
            self.assertTrue(self.prefs.data['setup_complete'])
        finally:ui.close()

    def test_themed_wizard_buttons_save_choices_and_navigate(self):
        self.prefs.accept_safety_notice()
        ui=Launcher(framebuffer=Display(),preferences=self.prefs,manifests=self.manifests)
        try:
            ui.setup_page()
            self.assertEqual(len(ui.actions),1)
            ui.actions[-1][1]()
            self.assertEqual(ui.wizard.step,1)
            app=sorted(self.manifests.values(),key=lambda m:m.name)[0]
            enabled=self.prefs.enabled(app)
            ui.actions[1][1]()
            self.assertEqual(self.prefs.enabled(app),not enabled)
            ui.actions[-1][1]()
            self.assertEqual(ui.wizard.step,2)
            ui.actions[1][1]()  # Home startup option
            self.assertIsNone(self.prefs.data['default_plugin'])
            ui.actions[-1][1]()
            self.assertEqual(ui.wizard.step,3)
            ui.actions[1][1]()  # Blue theme preview
            self.assertEqual(Preferences(self.prefs.path).data['tile_color'],'Blue')
            ui.actions[0][1]()  # Shared header returns to previous step
            self.assertEqual(ui.wizard.step,2)
            ui.wizard.save(setup_step=4);ui.draw()
            with patch.object(ui,'maintenance') as maintenance:
                ui.actions[1][1]();self.assertEqual(ui.mode,'recovery_settings')
                next(action for _, action in ui.actions if action == ui.hotspot_page)()
                self.assertEqual(ui.mode, 'hotspot_settings')
                ui.actions[1][1]();maintenance.assert_called_once_with('hotspot')
                ui.actions[0][1]();self.assertEqual(ui.mode,'recovery_settings')
                ui.actions[0][1]();self.assertEqual(ui.mode,'onboarding')
                self.assertEqual(ui.wizard.step,4)
            ui.wizard.save(setup_step=5);ui.storage_info['available']=True;ui.draw()
            with patch.object(ui,'setup_finish') as finish:
                left,right=sorted(ui.actions[1:],key=lambda item:item[0][0])
                self.assertEqual(left[0][1:],(400,348,460))
                self.assertEqual(right[0][1:],(400,696,460))
                right[1]();finish.assert_called_once_with(True)
                finish.reset_mock();left[1]();finish.assert_called_once_with()
        finally:ui.close()

    def test_recovery_http_requires_device_password_and_rejects_cross_origin_posts(self):
        state=SetupState(self.root);maintenance=Maintenance(state)
        server=ThreadingHTTPServer(('127.0.0.1',0),handler_for(state,maintenance))
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        connection=http.client.HTTPConnection(*server.server_address,timeout=3)
        try:
            connection.request('GET','/');response=connection.getresponse();self.assertEqual(response.status,401);response.read()
            auth='Basic '+base64.b64encode(('hlauncher:'+state.credentials()['password']).encode()).decode()
            headers={'Content-Type':'application/json','Origin':'http://evil.invalid','Authorization':auth}
            connection.request('POST','/api/debug','{}',headers)
            response=connection.getresponse();self.assertEqual(response.status,403);response.read()
            headers.pop('Origin')
            connection.request('POST','/api/job',json.dumps({'operation':'reboot'}),headers)
            response=connection.getresponse();self.assertEqual(response.status,400);response.read()
            connection.request('POST','/api/job','{"operation":"ssh","enabled":true}',headers)
            response=connection.getresponse();self.assertEqual(response.status,400);response.read()
            connection.request('GET','/',headers=headers)
            response=connection.getresponse();self.assertEqual(response.status,200);response.read()
        finally:
            connection.close();server.shutdown();server.server_close();thread.join(3)

    def test_protection_refuses_unverified_persistence(self):
        commands=[]
        def run(args,**kwargs):commands.append(args);return SimpleNamespace(stdout='0')
        with patch('hlauncher.storage.status',return_value=dict(available=False,message='No persistent partition')):
            with self.assertRaises(ValueError):storage.configure(True,run,self.root)
            self.assertFalse(commands)

    def test_protection_refuses_missing_boot_support_before_configuring(self):
        with patch('hlauncher.storage.status',return_value=dict(available=True,protected=False)), \
             patch('hlauncher.storage.verify_support',side_effect=ValueError('Missing boot support')):
            with self.assertRaisesRegex(ValueError,'Missing boot support'):storage.configure(True,state_dir=self.root)
        self.assertFalse((self.root/'storage-transition.json').exists())


if __name__=='__main__':unittest.main()
