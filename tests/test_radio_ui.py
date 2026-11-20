"""All built-in pages share chrome; settings setup and network helpers stay safe."""
from dataclasses import replace
import json
from pathlib import Path
import subprocess
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from PIL import ImageChops
from hlauncher.launcher import Launcher
from hlauncher.config import Preferences,ROOT
from hlauncher.protocol_diagnostics import ProtocolDiagnostics
from hlauncher.catalog import Manifest
from hlauncher.recovery import sample_network,network_status
from test_architecture import Display
from test_themes import theme_document


class RadioUI(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.object(ProtocolDiagnostics, "parked_for_setup", return_value=True))
        self.temp=tempfile.TemporaryDirectory();self.folder=Path(self.temp.name)
        prefs=Preferences(self.folder/'settings.json');prefs.data.update(setup_complete=True,debug_mode=True,tile_color='Red')
        prefs.accept_safety_notice()
        manifests={p:Manifest.load(ROOT/'plugins'/p,bundled=True) for p in ('carplay','android-auto','obd')}
        self.ui=Launcher(framebuffer=Display(),preferences=prefs,manifests=manifests)
    def tearDown(self):self.ui.close();self.temp.cleanup()

    def test_vehicle_plugin_visibility_persists_without_disabling_it(self):
        from hlauncher.vehicle_fields import visible

        ui = self.ui
        manifest = Manifest.load(ROOT/'plugins/vehicle', bundled=True)
        ui.manifests[manifest.id] = manifest
        self.assertTrue(ui.prefs.enabled(manifest))
        ui.settings()
        ui.plugin_settings()
        ui.plugin_detail('vehicle')
        ui.vehicle_fields_page('tires')
        ui.toggle_vehicle_field('126')
        ui.toggle_vehicle_field('tires')
        hidden = set(Preferences(ui.prefs.path).data['vehicle_hidden'])
        self.assertFalse(visible('127', hidden))
        self.assertTrue(visible('42', hidden))
        ui.toggle_vehicle_field('tires')
        hidden = set(Preferences(ui.prefs.path).data['vehicle_hidden'])
        self.assertFalse(visible('126', hidden))
        self.assertTrue(visible('127', hidden))
        self.assertTrue(ui.prefs.enabled(manifest))

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
                 lambda:ui.protocol_tab(4),
                 lambda:ui.set_integration_tab('Buttons'),
                 lambda:ui.set_integration_tab('Display'),
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

    def test_home_launch_error_requires_ok_before_tiles_are_available(self):
        ui = self.ui
        ui.open_plugin('missing-plugin')
        self.assertEqual(ui.mode, 'home')
        self.assertEqual(ui.banner, 'Plugin unavailable')
        self.assertEqual([callback for _, callback in ui.actions], [ui.dismiss_home_notice])
        ui.actions[0][1]()
        self.assertEqual(ui.banner, '')
        self.assertIn(ui.settings, [callback for _, callback in ui.actions])

    def test_camera_frame_sits_below_standard_header(self):
        from hlauncher.display import encode
        from hlauncher.ui.chrome import render

        ui = self.ui
        pixels = bytes([0x1f, 0]) * (720 * 428)
        ui.camera_frame = pixels
        ui.draw_camera()
        header = encode(render('Red', child=True).crop((0, 0, 720, 52)))
        self.assertEqual(ui.fb.frame, header + pixels)

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
        for tab in (0,1,2,3):
            ui.vehicle_tab(tab)
            for (x,y,r,b),_ in ui.actions:self.assertTrue(0<=x<r<=720 and 0<=y<b<=480)
            for index,(a,_) in enumerate(ui.actions):
                for b,_ in ui.actions[index+1:]:
                    self.assertFalse(a[0]<b[2] and b[0]<a[2] and a[1]<b[3] and b[1]<a[3])
        ui.protocols.observe(dict(state='iap_data_session_closed',session=257))
        self.assertFalse(ui.protocols.snapshot()['vehicle_signals'][43]['received'])

    def test_obd_tile_shows_placeholder_without_starting_worker(self):
        ui=self.ui
        self.assertIn('obd', [entry for page in ui.home_pages() for entry in page])
        with patch.object(ui.host,'activate') as activate:
            ui.open_plugin('obd')
            activate.assert_not_called()
        self.assertEqual(ui.mode,'obd_coming_soon')
        self.assertEqual([action for _,action in ui.actions],[ui.home])

    def test_network_sampling_prefers_lan_and_handles_missing_wifi(self):
        def run(args,**kwargs):
            return SimpleNamespace(stdout='192.168.4.1/24' if args[-1]=='wlan0' else '192.168.68.20/24')
        self.assertEqual(sample_network(run)['address'],'192.168.68.20')
        def ethernet(args,**kwargs):
            if args[-1]=='wlan0':raise subprocess.CalledProcessError(1,args)
            return SimpleNamespace(stdout='192.168.68.21/24')
        self.assertEqual(sample_network(ethernet)['address'],'192.168.68.21')
        (self.folder/'network-status.json').write_text(json.dumps(dict(monotonic=time.monotonic()+100,address='old')))
        self.assertEqual(network_status(runtime=self.folder),{})

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
        state=SetupState(self.folder);state.admit('02:00:00:00:00:11',{'Alias':'HandsFreeLink'});state.verify('02:00:00:00:00:11')
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
        ui.plugin_detail('obd')
        self.assertIsNone(ui.actions[-1][1])
        self.assertEqual(ui.mode,'plugin_detail')
        self.assertEqual(ui.settings_plugin_id,'obd')
        ui.appearance_settings()
        self.assertTrue(any(action==ui.toggle_clock for _,action in ui.actions))
        ui.actions[1][1]()
        self.assertEqual(ui.mode,'tile_colors')

    def test_carplay_frame_rate_is_saved_and_used_by_the_next_worker(self):
        ui = self.ui
        ui.plugin_detail('carplay')
        self.assertEqual(ui.prefs.carplay_fps, 30)
        toggle = next(action for _, action in ui.actions if action == ui.toggle_carplay_fps)
        with patch.object(ui.host, 'stop') as stop:
            toggle()
            stop.assert_called_once_with('carplay')
        self.assertEqual(Preferences(ui.prefs.path).carplay_fps, 60)
        with patch('hlauncher.plugin_host.Worker') as start:
            start.return_value.manifest = ui.manifests['carplay']
            try:
                ui.host.ensure_background_carplay()
                self.assertEqual(start.call_args.kwargs['carplay_fps'], 60)
            finally:
                ui.host.stop('carplay')
        toggle()
        self.assertEqual(Preferences(ui.prefs.path).carplay_fps, 30)

    def test_projection_headlight_settings_default_on_and_are_independent(self):
        ui = self.ui
        ui.prefs.path.write_text('{"setup_complete": true}')
        ui.prefs = Preferences(ui.prefs.path)
        self.assertTrue(ui.prefs.auto_night('carplay'))
        self.assertTrue(ui.prefs.auto_night('android-auto'))
        ui.plugin_detail('carplay')
        carplay = SimpleNamespace(manifest=ui.manifests['carplay'], send=Mock(return_value=True))
        with patch.object(ui.host, 'workers', {'carplay': carplay}), \
                patch.object(ui.protocols, 'illumination_night_mode', return_value=True):
            ui.host.sync_projection_appearance()
            ui.host.sync_projection_appearance()
            carplay.send.assert_called_once_with(type='projection.appearance', night_mode=True)
            next(action for box, action in ui.actions if box[:2] == (24, 320))()
            carplay.send.assert_called_with(type='projection.appearance', night_mode=False)
            self.assertTrue(ui.projection_night_mode('android-auto'))
        ui.plugin_detail('android-auto')
        next(action for box, action in ui.actions if box[:2] == (24, 192))()
        saved = Preferences(ui.prefs.path)
        self.assertFalse(saved.auto_night('android-auto'))
        self.assertFalse(saved.auto_night('carplay'))

    def test_car_gps_switch_is_independent_on_both_plugin_pages(self):
        ui = self.ui
        ui.plugin_detail('carplay')
        self.assertFalse(ui.prefs.car_gps('carplay'))
        self.assertFalse(ui.prefs.car_gps('android-auto'))
        next(action for box, action in ui.actions if box[:2] == (24, 384))()
        self.assertTrue(Preferences(ui.prefs.path).car_gps('carplay'))
        ui.plugin_detail('android-auto')
        next(action for box, action in ui.actions if box[:2] == (24, 256))()
        self.assertTrue(Preferences(ui.prefs.path).car_gps('android-auto'))
        self.assertTrue(Preferences(ui.prefs.path).car_gps('carplay'))

    def test_wifi_power_page_queues_power_and_boot_settings(self):
        ui = self.ui
        ui.system_settings()
        self.assertFalse(any(action == ui.wifi_power_page for _, action in ui.actions))
        next(action for _, action in ui.actions if action == ui.recovery_page)()
        self.assertEqual(ui.mode, 'recovery_settings')
        next(action for _, action in ui.actions if action == ui.hotspot_page)()
        self.assertEqual(ui.mode, 'hotspot_settings')
        ui.actions[0][1]()
        next(action for _, action in ui.actions if action == ui.wifi_power_page)()
        self.assertEqual(ui.mode, 'wifi_power_settings')
        with patch('hlauncher.recovery.request_job') as request:
            next(action for box, action in ui.actions if box[:2] == (336, 158))()
            request.assert_called_once_with('wifi_power', mode='sleep')
            request.reset_mock()
            next(action for box, action in ui.actions if box[:2] == (600, 282))()
            request.assert_called_once_with('wifi_boot', enabled=False)
        ui.actions[0][1]()
        self.assertEqual(ui.mode, 'recovery_settings')
        ui.actions[0][1]()
        self.assertEqual(ui.mode, 'system_settings')

    def test_theme_picker_preserves_oem_and_uses_existing_routes(self):
        ui = self.ui
        ui.settings()
        original = ui.fb.last.copy()
        next(action for _, action in ui.actions if action == ui.appearance_settings)()
        next(action for _, action in ui.actions if action == ui.themes_page)()
        self.assertEqual(ui.mode, 'theme_preview')
        self.assertEqual((ui.theme_preview.id, ui.theme_preview_screen), ('oem', 'home'))
        self.assertTrue(any(action == ui.preview_colors for _, action in ui.actions))
        self.assertEqual(tuple(ui.themes.choices), ('oem', 'touring', 'drive'))
        for retired in ('rail', 'stack'):
            self.assertEqual(ui.themes.get(retired).id, 'oem')
        ui.actions[0][1]()
        ui.themes.install_document(theme_document('my-garage', 'My Garage', settings='rail',
                                                  system_settings='rail', recovery_settings='rail'))
        ui.themes.install_document(theme_document('my-workshop', 'My Workshop', home='list'))
        next(action for _, action in ui.actions if action == ui.themes_page)()

        def press_at(x, y):
            next(action for (left, top, right, bottom), action in ui.actions
                 if left <= x < right and top <= y < bottom)()

        press_at(620, 270)
        self.assertEqual(ui.theme_preview.id, 'touring')
        self.assertFalse(any(action == ui.preview_colors for _, action in ui.actions))
        press_at(620, 270)
        self.assertEqual(ui.theme_preview.id, 'drive')
        self.assertFalse(any(action == ui.preview_colors for _, action in ui.actions))
        press_at(620, 270)
        self.assertEqual(ui.theme_preview.id, 'my-garage')
        self.assertFalse(any(action == ui.preview_colors for _, action in ui.actions))
        press_at(220, 436)
        self.assertEqual(ui.theme_preview_screen, 'settings')
        press_at(620, 270)
        self.assertEqual((ui.theme_preview.id, ui.theme_preview_screen), ('my-workshop', 'settings'))
        press_at(620, 270)
        self.assertEqual(ui.theme_preview.id, 'oem')
        press_at(80, 270)
        self.assertEqual(ui.theme_preview.id, 'my-workshop')
        self.assertEqual(Preferences(ui.prefs.path).data['layout_theme'], 'oem')
        ui.actions[0][1]()
        self.assertEqual(ui.mode, 'appearance_settings')
        self.assertEqual(Preferences(ui.prefs.path).data['layout_theme'], 'oem')
        next(action for _, action in ui.actions if action == ui.themes_page)()
        for _ in range(3):
            press_at(620, 270)
        press_at(570, 436)
        self.assertEqual(Preferences(ui.prefs.path).data['layout_theme'], 'my-garage')
        ui.settings()
        rail_box, open_system = next((box, action) for box, action in ui.actions
                                     if action == ui.system_settings)
        self.assertGreaterEqual(rail_box[0], 250)
        open_system()
        next(action for _, action in ui.actions if action == ui.recovery_page)()
        self.assertEqual(ui.mode, 'recovery_settings')
        next(action for _, action in ui.actions if action == ui.wifi_power_page)()
        self.assertEqual(ui.mode, 'wifi_power_settings')
        ui.appearance_settings()
        self.assertFalse(any(action == ui.tile_colors for _, action in ui.actions))
        next(action for _, action in ui.actions if action == ui.themes_page)()
        self.assertEqual(ui.theme_preview.id, 'my-garage')
        for _ in range(3):
            press_at(80, 270)
        press_at(570, 436)
        ui.settings()
        self.assertIsNone(ImageChops.difference(original, ui.fb.last).getbbox())

    def test_theme_color_preview_only_saves_when_applied(self):
        ui = self.ui
        document = theme_document('colorable', 'Colorable', home='rail')
        ui.themes.install_document(dict(document, supports_color_selection=True))
        ui.appearance_settings()
        self.assertTrue(any(action == ui.tile_colors for _, action in ui.actions))
        ui.themes_page()
        ui.move_theme_preview(-1)
        self.assertEqual(ui.theme_preview.id, 'colorable')
        original = ui.fb.last.copy()
        color_action = next(action for _, action in ui.actions if action == ui.preview_colors)
        color_action()
        ui.set_tile_color('Blue')
        ui.actions[0][1]()
        self.assertEqual(ui.mode, 'theme_preview')
        self.assertIsNotNone(ImageChops.difference(original, ui.fb.last).getbbox())
        self.assertEqual(Preferences(ui.prefs.path).data['tile_color'], 'Red')
        ui.actions[0][1]()
        self.assertEqual(Preferences(ui.prefs.path).data['tile_color'], 'Red')
        ui.themes_page()
        ui.move_theme_preview(-1)
        ui.preview_colors()
        ui.custom_color()
        ui.color_picker.set_rgb((136, 36, 190))
        ui.save_custom_color()
        self.assertEqual(ui.mode, 'preview_colors')
        ui.actions[0][1]()
        ui.select_theme()
        self.assertTrue(any(action == ui.tile_colors for _, action in ui.actions))
        saved = Preferences(ui.prefs.path).data
        self.assertEqual((saved['layout_theme'], saved['tile_color'], saved['custom_color']),
                         ('colorable', '#8824BE', '#8824BE'))

    def test_drive_features_the_enabled_startup_app_and_keeps_home_order(self):
        ui = self.ui
        ui.prefs.set_default('android-auto')
        original = ui.home_pages()
        ui.themes_page()
        ui.preview_theme('drive')
        ui.select_theme()
        ui.home()
        with patch.object(ui, 'open_plugin') as open_plugin:
            next(action for box, action in ui.actions if box == (24, 84, 696, 240))()
            open_plugin.assert_called_once_with('android-auto')
        self.assertEqual(ui.home_pages(), original)
        ui.prefs.set_enabled(ui.manifests['android-auto'], False)
        ui.home()
        with patch.object(ui, 'open_plugin') as open_plugin:
            next(action for box, action in ui.actions if box == (24, 84, 696, 240))()
            open_plugin.assert_called_once_with('carplay')
        ui.settings()
        back = next(action for box, action in ui.actions if box == (24, 428, 128, 476))
        back()
        self.assertEqual(ui.mode, 'home')

    def test_all_home_themes_swipe_to_apps_beyond_three_pages(self):
        ui = self.ui
        template = ui.manifests['carplay']
        ui.manifests.clear()
        ui.manifests.update({f'app-{i:02}': replace(template, id=f'app-{i:02}', name=f'App {i:02}')
                             for i in range(44)})

        def touch(action, x):
            ui.update({'contacts': [dict(slot=0, action=action, has_position=action != 'up',
                                         x_raw=round(x / 719 * 32767), y_raw=round(55 / 479 * 32767))]})

        for theme_id in ('oem', 'touring', 'drive'):
            with self.subTest(theme=theme_id), patch.object(ui, 'open_plugin') as opened:
                ui.themes_page()
                ui.preview_theme(theme_id)
                ui.select_theme()
                ui.page = 0
                ui.home()
                for expected in range(1, 8):
                    touch('down', 600)
                    touch('move', 200)
                    touch('up', 200)
                    ui.tick_home_slide(time.monotonic() + 1)
                    self.assertEqual(ui.page, expected)
                opened.assert_not_called()
                ui.actions[0][1]()
                opened.assert_called_once_with('app-42')

    def test_home_page_delete_moves_apps_and_protects_required_pages(self):
        from hlauncher.ui.home_edit import SETTINGS

        ui = self.ui
        editor = ui.home_editor
        ui.prefs.set_home_pages([['carplay', SETTINGS, None, None, None, None],
                                 ['android-auto', 'obd', None, None, None, None]])
        ui.themes_page()
        ui.preview_theme('drive')
        ui.select_theme()
        ui.home()
        ui.change_page(1)
        editor.begin_editing()
        next(action for _, action in ui.actions if action == editor.confirm_delete_page)()
        self.assertEqual(editor.dialog()[0], 'Delete Home page?')
        ui.actions[0][1]()  # Cancel
        self.assertEqual(len(ui.home_pages()), 2)
        next(action for _, action in ui.actions if action == editor.confirm_delete_page)()
        ui.actions[1][1]()  # Delete
        self.assertEqual(Preferences(ui.prefs.path).data['home_pages'],
                         [['carplay', SETTINGS, 'android-auto', 'obd', None, None]])
        self.assertEqual(ui.page, 0)
        self.assertFalse(any(action == editor.confirm_delete_page for _, action in ui.actions))
        next(action for _, action in ui.actions if action == editor.add_page)()
        editor.done()
        self.assertEqual(ui.page, 1)
        next(action for _, action in ui.actions if action == editor.begin_editing)()
        next(action for _, action in ui.actions if action == editor.confirm_delete_page)()
        ui.actions[1][1]()
        self.assertEqual(len(ui.home_pages()), 1)

        template = ui.manifests['carplay']
        for i in range(4):
            ui.manifests[f'extra-{i}'] = replace(template, id=f'extra-{i}', name=f'Extra {i}')
        ui.draw()
        next(action for _, action in ui.actions if action == editor.confirm_delete_page)()
        self.assertEqual(editor.dialog()[0], 'Page is needed')
        self.assertNotIn(editor.delete_page, [action for _, action in ui.actions])
        ui.actions[0][1]()
        self.assertEqual(len(ui.home_pages()), 2)

    def test_audio_returns_to_the_page_that_opened_it(self):
        ui=self.ui;ui.settings()
        next(action for _, action in ui.actions if action == ui.audio_page)()
        self.assertEqual(ui.mode, 'audio_settings')
        self.assertGreater(len(ui.actions), 1)
        ui.actions[0][1]()
        self.assertEqual(ui.mode,'settings')
        ui.audio_page();ui.actions[0][1]()
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

    def test_scroll_position_survives_redraws_but_resets_after_leaving(self):
        from hlauncher.ui.scroll_list import move
        ui=self.ui
        for leave in (ui.settings,ui.home,ui.debug_tools):
            ui.system_settings()
            move(ui,32)
            offset=ui.scroll_view['offset']
            self.assertGreater(offset,0)
            ui.draw()
            self.assertEqual(ui.scroll_view['offset'],offset)
            ui.toggle_debug()
            self.assertEqual(ui.scroll_view['offset'],offset)
            ui.toggle_debug()
            ui.list_drag=dict(key=ui.scroll_view['key'],kind='content')
            leave()
            self.assertIsNone(ui.list_drag)
            ui.system_settings()
            self.assertEqual(ui.scroll_view['offset'],0)

    def test_scroll_resets_between_sections_with_the_same_page_mode(self):
        from hlauncher.ui.scroll_list import move
        ui=self.ui
        ui.manifests['vehicle']=Manifest.load(ROOT/'plugins/vehicle',bundled=True)
        ui.plugin_detail('vehicle')
        ui.vehicle_fields_page('tires');mode=ui.mode
        move(ui,128)
        self.assertGreater(ui.scroll_view['offset'],0)
        ui.toggle_vehicle_field('126')
        self.assertGreater(ui.scroll_view['offset'],0)
        ui.vehicle_fields_page('warnings')
        self.assertEqual(ui.mode,mode)
        self.assertEqual(ui.scroll_view['offset'],0)
        move(ui,128)
        ui.vehicle_fields_page('tires')
        self.assertEqual(ui.scroll_view['offset'],0)

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
