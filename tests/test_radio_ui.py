"""All built-in pages share chrome; settings setup and network helpers stay safe."""
import json
from pathlib import Path
import subprocess
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from PIL import ImageChops
from hlauncher.launcher import Launcher
from hlauncher.config import Preferences,ROOT
from hlauncher.catalog import Manifest
from hlauncher.recovery import sample_network,network_status
from test_architecture import Display


class RadioUI(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.folder=Path(self.temp.name)
        prefs=Preferences(self.folder/'settings.json');prefs.data.update(setup_complete=True,debug_mode=True,tile_color='Red')
        prefs.save()
        manifests={p:Manifest.load(ROOT/'plugins'/p,bundled=True) for p in ('carplay','android-auto','obd')}
        self.ui=Launcher(framebuffer=Display(),preferences=prefs,manifests=manifests)
    def tearDown(self):self.ui.close();self.temp.cleanup()

    def test_revisit_wizard_exit_is_available_every_step_and_does_not_reset_setup(self):
        ui=self.ui;ui.system_settings();ui.setup_page(True)
        self.assertTrue(ui.setup_can_exit)
        for step in range(6):
            ui.wizard.save(setup_step=step);ui.draw()
            self.assertTrue(any(callback==ui.exit_setup for _,callback in ui.actions))
            self.assertTrue(Preferences(ui.prefs.path).data['setup_complete'])
        ui.wizard.theme('Green');ui.exit_setup()
        self.assertEqual(ui.mode,'system_settings')
        self.assertEqual(Preferences(ui.prefs.path).data['tile_color'],'Green')
        ui.home();self.assertEqual(ui.mode,'home')

    def test_fresh_setup_still_requires_completion(self):
        ui=self.ui;ui.prefs.data['setup_complete']=False;ui.prefs.save();ui.mode='home';ui.setup_page()
        self.assertFalse(ui.setup_can_exit)
        self.assertFalse(any(callback==ui.exit_setup for _,callback in ui.actions))
        ui.exit_setup();self.assertEqual(ui.mode,'onboarding')

    def test_every_settings_and_diagnostics_page_has_identical_header_and_valid_actions(self):
        ui=self.ui
        ui.system_settings();header=ui.fb.last.crop((80,0,720,52))
        methods=[ui.ssh_settings,ui.adapter_branding_page,ui.appearance_settings,ui.startup_settings,ui.recovery_page,lambda:ui.storage_confirm(True),ui.plugin_settings,lambda:ui.plugin_detail('carplay'),lambda:ui.plugin_detail('obd'),ui.tile_colors,
                 ui.color_settings,ui.system_diagnostics,ui.protocol_tests,
                 lambda:ui.debug_tools('menu'),lambda:ui.debug_tools('audio'),
                 lambda:ui.debug_tools('colors'),lambda:ui.debug_tools('inputs'),lambda:ui.debug_tools('volume'),ui.shutdown_page]
        with patch('hlauncher.ui.chrome.datetime') as clock:
            clock.now.return_value.strftime.return_value=time.strftime('%-I:%M')
            for method in methods:
                method()
                self.assertIsNone(ImageChops.difference(header,ui.fb.last.crop((80,0,720,52))).getbbox(),ui.mode)
                for (x,y,right,bottom),_ in ui.actions:
                    self.assertTrue(0<=x<right<=720 and 0<=y<bottom<=480,ui.mode)
                for i,(a,_) in enumerate(ui.actions):
                    for b,_ in ui.actions[i+1:]:
                        self.assertFalse(a[0]<b[2] and b[0]<a[2] and a[1]<b[3] and b[1]<a[3],ui.mode)

    def test_projection_disconnect_with_unchanged_status_restores_back_control(self):
        ui=self.ui;ui.mode='plugin';ui.host.active='carplay';ui.has_frame=True
        ui.last_status='iPhone disconnected';ui.projection_checked=time.monotonic()
        worker=SimpleNamespace(video_available=False,status='iPhone disconnected')
        with patch.object(ui.host,'workers',{'carplay':worker}),patch.object(ui.host,'tick'),patch.object(ui.host,'frame',return_value=None):
            ui.tick()
            self.assertFalse(ui.has_frame)
            self.assertTrue(any(action==ui.home for _,action in ui.actions))
        ui.host.active=None

    def test_volume_page_routes_both_buttons_to_head_unit_bridge(self):
        ui=self.ui;ui.debug_tools('volume')
        with patch.object(ui.inputs,'request_volume') as request:
            next(callback for box,callback in ui.actions if box==(24,248,352,320))()
            next(callback for box,callback in ui.actions if box==(368,248,696,320))()
        self.assertEqual(request.call_args_list,[(("down",),),(("up",),)])

    def test_picture_slider_drag_still_saves_and_storage_requires_completed_change(self):
        ui=self.ui;ui.color_settings();key,box=ui.picture_sliders[0]
        ui.color_touch('down',(box[2],(box[1]+box[3])//2));ui.color_touch('up',(box[2],(box[1]+box[3])//2))
        self.assertTrue((self.folder/'picture.json').is_file())
        ui.storage_info=dict(available=True,protected=False,message='Ready')
        ui.storage_confirm(True)
        with patch.object(ui,'maintenance') as request:
            next(callback for box,callback in ui.actions if box[0]==372)()
            request.assert_called_once_with('protect')
        (self.folder/'storage-transition.json').write_text(json.dumps(dict(target='protected')))
        (self.folder/'maintenance-status.json').write_text(json.dumps(dict(status='Done')))
        ui.draw()
        with patch.object(ui,'maintenance') as request:
            next(callback for box,callback in ui.actions if box[0]==372)()
            request.assert_called_once_with('reboot')

    def test_vehicle_tabs_show_all_entries_select_live_signal_and_keep_hits_bounded(self):
        from hlauncher.protocol.vehicle_can import decode_records
        from test_vehicle_can import can_data
        ui=self.ui
        ui.protocol_tests();ui.protocol_tab(1)
        self.assertEqual(len(ui.protocols.snapshot()['vehicle_signals']),168)
        self.assertEqual(ui.scroll_view['key'],'vehicle-signals')
        ui.list_offsets['vehicle-signals']=43*40;ui.draw()
        self.assertGreater(ui.scroll_view['offset'],0)
        ui.vehicle_select(44)
        self.assertEqual(ui.vehicle_data_tab,1)
        ui.protocols.observe(dict(state='honda_can_data',session=257,data_type=0,
            records=decode_records(can_data([(0x17c,bytes.fromhex('000003e800000000'))]))))
        ui.draw()
        self.assertEqual(ui.protocols.snapshot()['vehicle_signals'][43]['value'],1000)
        for tab in (0,1,2):
            ui.vehicle_tab(tab)
            for (x,y,r,b),_ in ui.actions:self.assertTrue(0<=x<r<=720 and 0<=y<b<=480)
            for index,(a,_) in enumerate(ui.actions):
                for b,_ in ui.actions[index+1:]:
                    self.assertFalse(a[0]<b[2] and b[0]<a[2] and a[1]<b[3] and b[1]<a[3])
        ui.protocols.observe(dict(state='iap_data_session_closed',session=257))
        self.assertFalse(ui.protocols.snapshot()['vehicle_signals'][43]['received'])

    def test_opening_gauges_stops_ble_and_does_not_start_it(self):
        ui=self.ui
        ui.obd.enabled=True
        with patch.object(ui.obd,'close') as close,patch.object(ui.obd,'start') as start,patch.object(ui.host,'activate'):
            ui.open_plugin('obd')
        close.assert_called_once();start.assert_not_called()
        self.assertFalse(ui.obd.enabled)

    def test_network_sampling_prefers_lan_and_handles_missing_wifi(self):
        def run(args,**kwargs):
            return SimpleNamespace(stdout='192.168.4.1/24' if args[-1]=='wlan0' else '192.168.68.20/24')
        self.assertEqual(sample_network(run)['address'],'192.168.68.20')
        def ethernet(args,**kwargs):
            if args[-1]=='wlan0':raise subprocess.CalledProcessError(1,args)
            return SimpleNamespace(stdout='192.168.68.21/24')
        self.assertEqual(sample_network(ethernet)['address'],'192.168.68.21')
        (self.folder/'network-status.json').write_text(json.dumps(dict(monotonic=time.monotonic()+100,address='old')))
        self.assertEqual(network_status(self.folder),{})

    def test_red_is_fresh_default_and_saved_theme_is_preserved(self):
        path=self.folder/'fresh.json'
        prefs=Preferences(path)
        self.assertEqual(prefs.data['tile_color'],'Red')
        prefs.set_tile_color('Blue')
        self.assertEqual(Preferences(path).data['tile_color'],'Blue')

    def test_plugin_switch_and_debug_switch_save_their_values(self):
        ui=self.ui;ui.plugin_settings();ui.actions[1][1]();self.assertEqual(ui.mode,'plugin_detail')
        before=ui.prefs.enabled(ui.manifests['carplay'])
        ui.actions[3 if before else 2][1]()
        self.assertEqual(ui.prefs.enabled(ui.manifests['carplay']),before)
        ui.actions[1][1]()
        self.assertEqual(Preferences(ui.prefs.path).enabled(ui.manifests['carplay']),not before)
        ui.system_settings();next(action for _,action in ui.actions if action==ui.toggle_debug)()
        self.assertFalse(Preferences(ui.prefs.path).data['debug_mode'])

    def test_boot_welcome_matches_wizard_and_shows_for_saved_radio(self):
        from hlauncher.bootstrap import BootstrapLauncher
        from hlauncher.setup_state import SetupState
        from hlauncher.ui.first_boot import render
        from sdk.hlauncher_sdk.theme import dither_rgb565
        state=SetupState(self.folder);state.admit('64:D4:BD:EE:25:FC',{'Alias':'HandsFreeLink'});state.verify('64:D4:BD:EE:25:FC')
        bootstrap=BootstrapLauncher(lambda **v:None,SimpleNamespace(close=lambda:None),state)
        with patch('hlauncher.display.Framebuffer',side_effect=lambda event:Display()),patch('hlauncher.bootstrap.time.strftime',return_value='now'),patch('subprocess.run'):
            bootstrap.show_pairing()
        try:
            self.assertIsNotNone(bootstrap.splash)
            self.assertIsNone(bootstrap.ui)
            self.ui.setup_page(True)
            expected=dither_rgb565(render(theme='Red'))
            self.assertIsNone(ImageChops.difference(expected.crop((24,136,696,380)),self.ui.fb.last.crop((24,136,696,380))).getbbox())
        finally:bootstrap.close()

    def test_picture_returns_to_appearance_and_carplay_has_adapter_options(self):
        ui=self.ui;ui.plugin_detail('carplay')
        self.assertFalse(any(action==ui.color_settings for _,action in ui.actions))
        ui.appearance_settings()
        next(action for _,action in ui.actions if action==ui.color_settings)()
        self.assertEqual(ui.mode,'colors')
        ui.actions[0][1]()
        self.assertEqual(ui.mode,'appearance_settings')
        ui.plugin_detail('obd');ui.actions[-1][1]()
        self.assertEqual(ui.mode,'obd_settings')
        ui.actions[0][1]()
        self.assertEqual(ui.mode,'plugin_detail')
        self.assertEqual(ui.settings_plugin_id,'obd')
        ui.appearance_settings()
        self.assertTrue(any(action==ui.toggle_clock for _,action in ui.actions))
        ui.actions[1][1]()
        self.assertEqual(ui.mode,'tile_colors')

    def test_audio_returns_to_the_page_that_opened_it(self):
        ui=self.ui;ui.settings();ui.audio_page();ui.actions[0][1]()
        self.assertEqual(ui.mode,'settings')
        ui.home();ui.audio_page();ui.actions[0][1]()
        self.assertEqual(ui.mode,'home')

    def test_settings_drag_and_scrollbar_never_activate_rows(self):
        ui=self.ui
        for width in (720,800):
            ui.fb.w=width;ui.list_offsets={}
            def event(action,x=0,y=0):
                return {'contacts':[dict(slot=0,action=action,has_position=action!='up',
                    x_raw=round(x*width/720/(width-1)*32767),y_raw=round(y/479*32767))]}
            with patch.object(ui,'recovery_page') as opened:
                ui.system_settings()
                self.assertGreater(ui.scroll_view['maximum'],0)
                ui.update(event('down',80,156));ui.update(event('move',80,100));ui.update(event('up'))
                opened.assert_not_called()
                self.assertEqual(ui.mode,'system_settings')
                self.assertGreater(ui.scroll_view['offset'],0)
                self.assertIsNone(ui.pressed_box)
                ui.update(event('down',654,ui.scroll_view['track'][3]));ui.update(event('up'))
                self.assertEqual(ui.scroll_view['offset'],ui.scroll_view['maximum'])
                ui.actions[-2][1]()
                self.assertLess(ui.scroll_view['offset'],ui.scroll_view['maximum'])
                for (x,y,r,b),_ in ui.actions:self.assertTrue(0<=x<r<=width and 0<=y<b<=480)

    def test_clock_is_hidden_by_default_and_toggle_persists_across_pages(self):
        ui=self.ui
        self.assertFalse(Preferences(self.folder/'new-settings.json').data['show_clock'])
        self.assertFalse(ui.prefs.data['show_clock'])
        # Missing values from earlier installations also migrate to hidden.
        legacy=self.folder/'legacy.json';legacy.write_text('{"enabled":{}}')
        self.assertFalse(Preferences(legacy).data['show_clock'])
        ui.appearance_settings();ui.toggle_clock()
        self.assertTrue(Preferences(ui.prefs.path).data['show_clock'])
        enabled=[]
        pages=[ui.home,ui.settings,ui.appearance_settings,ui.audio_page,
               ui.adapter_branding_page,lambda:ui.setup_page(True)]
        with patch('hlauncher.ui.chrome.datetime') as clock:
            clock.now.return_value.strftime.return_value='8:05'
            for open_page in pages:
                open_page();enabled.append(ui.fb.last.crop((620,0,720,52)))
            ui.appearance_settings();ui.toggle_clock()
            self.assertFalse(Preferences(ui.prefs.path).data['show_clock'])
            for open_page,header in zip(pages,enabled):
                open_page()
                self.assertIsNotNone(ImageChops.difference(header,ui.fb.last.crop((620,0,720,52))).getbbox())
        with patch.object(ui.prefs,'save',side_effect=OSError('Read only')):
            with self.assertRaises(OSError):ui.toggle_clock()
        self.assertFalse(ui.prefs.data['show_clock'])

    def test_scroll_track_spans_arrow_rows(self):
        ui=self.ui;ui.system_settings()
        view=ui.scroll_view
        self.assertLessEqual(view['track'][1],view['bounds'][1]+2)
        self.assertGreaterEqual(view['track'][3],view['bounds'][3]-2)
