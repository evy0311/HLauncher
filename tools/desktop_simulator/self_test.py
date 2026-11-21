"""Fast checks of the desktop adapter against production UI behavior."""
def check(sim):
    ui=sim.ui;checks=[]
    assert ui.mode=='home' and ui.protocols.parked_for_setup()
    for route in (ui.settings,ui.system_settings,ui.audio_page,ui.updates_page,ui.projection_page,ui.projection_settings_page,ui.adapter_info_page,ui.projection_phones_page,ui.shutdown_page):
        route();sim.tick();assert sim.display.png.startswith(b'\x89PNG')
    checks.append('Production launcher pages render and navigate')
    ui.audio_page()
    next(fn for (l,t,r,b),fn in ui.actions if l<=530<r and t<=136<b)()
    next(fn for (l,t,r,b),fn in ui.actions if l<=180<r and t<=202<b)()
    assert ui.audio_presets_open
    checks.append('EQ picker uses current application navigation')
    ui.system_settings();sim.set_state(dict(brake=False))
    assert ui.parked_screen_locked
    sim.set_state(dict(brake=True,speed=30));assert ui.parked_screen_locked
    sim.set_state(dict(speed=0));assert not ui.parked_screen_locked
    checks.append('Real brake/speed telemetry locks and unlocks settings')
    for phone,ident,label in (('carplay','carplay','CarPlay'),('android-dongle','carplay','Android Auto'),('android-usb','android-auto','Android Auto')):
        ui.home();sim.set_state(dict(phone=phone,dongle='dual'))
        assert ui.projection_tile()[0]==label,ui.projection_tile()
        ui.projection_page();sim.tick()
        assert ui.host.active==ident and ui.has_frame
        ui.home();ui.projection_page();sim.tick();assert ui.has_frame
    checks.append('CarPlay, dongle AA and direct USB AA route through the real host')
    ui.inputs.offer('next','down','hondalink-iap');ui.inputs.offer('next','up','hondalink-iap');sim.tick()
    assert not ui.host.button_pending
    assert ui.host.button_results['next']['result']=='Simulated button received'
    checks.append('Steering input routes through the host and receives acknowledgement')
    ui.home();sim.set_state(dict(phone='android-dongle',dongle='carplay'))
    assert not ui.host.workers['carplay'].metrics['phone_connected']
    sim.set_state(dict(phone='android-usb'));assert 'android-auto' in ui.host.workers
    checks.append('CarPlay-only adapter cannot fake AA; direct USB fallback works')
    ui.home();sim.set_state(dict(phone='none',dongle='dual'));ui.open_plugin('vehicle');sim.tick()
    assert ui.has_frame
    assert ui.protocols.last_vehicle.readings['152']==0
    assert ui.protocols.last_vehicle.readings['brake'] is True
    checks.append('Real Vehicle dashboard renders without a plugin subprocess')
    ui.home();ui.hdmi_calibration();assert sim.display.png.startswith(b'\x89PNG')
    checks.append('HDMI test pattern is rendered without accessing a display device')
    ui.shutdown_page();ui.restart_pi();assert ui.mode=='shutdown_confirm'
    assert any(e['state']=='simulated_power_request' for e in sim.events)
    ui.updates_page();ui.update_request('install');assert ui.mode=='updates'
    checks.append('Restart and update actions are simulated')
    ui.prefs.data['include_beta_updates']=True;ui.prefs.save()
    ui.development_branches_page();ui.toggle_source_updates();ui.select_development_branch('feature/desktop-simulator')
    ui.install_update();assert ui.confirm_update_source
    ui.confirm_update();assert ui.mode=='updates'
    checks.append('Development branch selection and unsigned-source confirmation use the real UI')
    import subprocess
    try:subprocess.run(['must-never-launch'])
    except OSError:pass
    else:raise AssertionError('Hardware guard did not block process creation')
    checks.append('External processes are blocked')
    return dict(passed=len(checks),checks=checks)
