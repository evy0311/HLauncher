"""Shared settings, connection and picture pages; no display or service ownership."""
import math
import time
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from PIL import Image, ImageDraw, ImageFilter
from .. import __version__
from ..config import TILE_COLORS
from ..colors import DEFAULTS,LIMITS
from ..recovery import job_status, network_status
from ..setup_state import SetupState
from .controls import Page,present
from .scroll_list import Row,draw as draw_rows
from .chrome import scale_bounds
from . import home_art as art
from .projection import wrap_status
from .theme_menu import Item, row_items, settings_menu
from sdk.hlauncher_sdk.fonts import font


def page_for(ui,title,back=None):
    return Page.for_launcher(ui, title, back or ui.settings)


@lru_cache(maxsize=1)
def about_logo():
    path = Path(__file__).parent/'assets/branding/hlauncher-180.png'
    with Image.open(path) as image:
        return image.convert('RGBA').resize((144, 144), Image.Resampling.LANCZOS)


def about(ui):
    page = page_for(ui, 'About', ui.settings)
    logo = about_logo()
    page.image.paste(logo, (24, 130), logo)
    page.label((192, 133), 'HLauncher', 34)
    page.text((192, 184), f'Version {__version__}', 21, fill='#efedf6')
    page.text((192, 224), 'Created by Evan Horsley (evy0311)', 20)
    page.text((192, 256), 'Open source under the GNU GPL', 17)
    page.info(313, 'GitHub', 'https://github.com/evy0311/HLauncher')
    page.bar((24, 368, 696, 424), 'Legal info', ui.legal_info)
    present(ui, page)


def audio_coming_soon(ui):
    page = page_for(ui, 'Audio', ui.settings)
    page.text((360, 244), 'Coming soon', 25, anchor='mm')
    present(ui, page)


def legal_info(ui):
    from .onboarding import safety_notice_text
    page = page_for(ui, 'Legal', ui.about_settings)
    safety_notice_text(page)
    page.bar((24,256,696,312), 'Safety agreement', ui.safety_agreement)
    present(ui, page)


def safety_agreement(ui):
    from .onboarding import safety_agreement_text
    page = page_for(ui, 'Safety agreement', ui.legal_info)
    safety_agreement_text(ui, page, top=132, bottom=448)
    present(ui, page)


PARKED_TITLE_BOUNDS = (168, 120, 552, 176)


def parked_backdrop(ui):
    snapshot = getattr(ui.fb, 'snapshot', None)
    prior = snapshot() if snapshot else None
    black = Image.new('RGB', (720, 480), 'black')
    if prior is None:
        return black
    # Remove lettering and detail at low resolution before the heavy dimming pass.
    blur = prior.convert('RGB').resize((36, 24)).filter(ImageFilter.GaussianBlur(2))
    return Image.blend(black, blur.resize(black.size, Image.Resampling.BILINEAR), .07)


def parked_only(ui):
    page = Page.for_launcher(ui, '', None)
    page.image = ui.parked_backdrop.copy()
    page.draw = ImageDraw.Draw(page.image)
    page.draw.rounded_rectangle((332, 106, 388, 110), 2, fill=page.accent)
    page.draw.text((360, 148), 'Park safely to continue', font=font(30, 600), fill='white', anchor='mm')
    page.draw.text((360, 203), 'Come to a complete stop and engage the parking brake.',
                   font=font(19), fill='#e8e8e8', anchor='mm')
    speed, brake = ui.protocols.parked_setup_readings()
    if speed is not None and speed > 0:
        lines = ('The radio reports that the vehicle is moving.',)
    elif brake is False:
        lines = ('The radio reports that the parking brake is released.',)
    else:
        lines = ('Waiting for vehicle status to update.',)
    for index, line in enumerate(lines):
        page.draw.text((360, 254 + index * 28), line, font=font(17), fill='#bbbbbb', anchor='mm')
    if ui.prefs.safety_notice_accepted and ui.prefs.data['setup_complete']:
        page.button((240, 360, 480, 414), 'Back to Home', ui.home, secondary=True)
    present(ui, page)

def obd_coming_soon(ui):
    page = page_for(ui, 'OBD Gauges', ui.home)
    page.text((360, 236), 'Coming soon', 28, fill='#ffffff', anchor='mm')
    present(ui, page)


def system(ui):
    info=ui.storage_info
    rows=[('Wi-Fi','',ui.recovery_page),
          ('Setup wizard','',lambda:ui.setup_page(True)),
          ('Software updates','',ui.updates_page),
          ('Debug mode','On' if ui.prefs.data['debug_mode'] else 'Off',ui.toggle_debug),
          ('Storage protection','Enabled' if info['protected'] else 'Off' if info['available'] else 'Unavailable',lambda:ui.storage_confirm(not info['protected'])),
          ('Shut down','',ui.shutdown_page)]
    if ui.prefs.data['debug_mode']:rows.insert(4,('Debug','',ui.debug_tools))
    rows = [Row(title, action, toggle=ui.prefs.data['debug_mode']) if title == 'Debug mode'
            else Row(title, action, value=value) for title, value, action in rows]
    if settings_menu(ui, 'System', ui.settings, row_items(rows)):
        return
    p=page_for(ui,'System',ui.settings)
    draw_rows(ui,p,rows)
    p.notice(ui.banner)
    present(ui,p)


def network(ui):
    result=job_status(ui.prefs.path.parent)
    if result.get('status')=='Working' and result.get('operation')=='wifi':
        p=page_for(ui,'Connecting to Wi-Fi',getattr(ui,'recovery_return',ui.system_settings))
        p.label((24,144),'The Pi is switching networks',27)
        p.text((24,208),'Connect your phone or computer to the same Wi-Fi',18)
        p.text((24,248),'The new setup-page address will appear here when ready',17)
        present(ui,p);return
    connection = network_status()
    address = connection.get('address')
    back = getattr(ui, 'recovery_return', ui.system_settings)
    from ..ssh_access import status
    ssh = status()
    ssh_value = 'On' if ssh['enabled'] else 'Off'
    if settings_menu(ui, 'Wi-Fi', back, (
            Item('Setup hotspot', ui.hotspot_page),
            Item('Wi-Fi power', ui.wifi_power_page),
            Item('SSH access', ui.ssh_settings, ssh_value),
    ), footer=f'http://{address}' if address else 'No network connection'):
        return
    p=page_for(ui,'Wi-Fi',back)
    if address:
        p.label((24,128),'http://'+address,26)
        p.text((24,176),'Open this page on a device on the same network as the Pi',17)
    else:
        p.label((24,128),'No network connection',26)
        p.text((24,176),'Start the setup hotspot to connect this Pi to Wi-Fi',17)
    p.bar((24, 218, 696, 274), 'Setup hotspot', ui.hotspot_page, size=27)
    p.bar((24, 286, 696, 342), 'Wi-Fi power', ui.wifi_power_page, size=27)
    p.bar((24, 354, 696, 410), 'SSH access', ui.ssh_settings,
          value=ssh_value, size=27)
    p.notice(ui.banner)
    present(ui,p)


def wifi_power(ui):
    from ..config import Preferences
    prefs = Preferences(ui.prefs.path).data
    mode = prefs['wifi_power']
    delay = prefs['wifi_delay_boot']
    p = page_for(ui, 'Wi-Fi power', ui.network_resume)
    status = network_status().get('wifi_state')
    p.text((24, 121), {'on':'Wi-Fi is on', 'off':'Wi-Fi is off', 'asleep':'Wi-Fi is asleep',
                        'unavailable':'Wi-Fi status unavailable'}.get(status, 'Wi-Fi status pending'), 20)
    for left, right, label, value in ((24, 168, 'On', 'on'), (180, 324, 'Off', 'off'),
                                      (336, 696, 'Sleep after 3 minutes', 'sleep')):
        p.button((left, 158, right, 214), label, lambda value=value: ui.set_wifi_power(value),
                 selected=mode == value, size=22)
    p.text((24, 230), 'Tap Sleep again to wake Wi-Fi for another idle period.', 17)
    p.bar((24, 282, 696, 338), 'Wi-Fi during boot', lambda: ui.set_wifi_boot(not delay),
          toggle=not delay, size=27)
    p.text((24, 357), 'When off, Wi-Fi waits for HLauncher before starting in On or Sleep mode.', 17)
    result = job_status(ui.prefs.path.parent)
    if (ui.prefs.path.parent/'maintenance-request.json').exists() or result.get('status') == 'Working':
        p.notice('Applying Wi-Fi setting…')
    else:
        p.notice(ui.banner or (result.get('message', '') if result.get('status') == 'Failed' else ''))
    present(ui, p)


def hotspot(ui):
    p=page_for(ui,'Setup hotspot',ui.network_resume)
    creds=SetupState(ui.prefs.path.parent).credentials()
    connection=network_status();ready=connection.get('address')=='192.168.4.1'
    p.text((24,116),'Connect your phone or computer to this temporary network',17)
    p.panel((24,156,696,244))
    for y,label,value in ((172,'Network',creds['ssid']),(208,'Password',creds['password'])):
        p.text((42,y),label,16);p.text((240,y),p.fit(value,432,17),17,fill='#efedf6')
    p.label((24,266),'http://192.168.4.1',25)
    p.text((24,298),'If setup does not open automatically, use this address',16)
    result=job_status(ui.prefs.path.parent)
    queued=(ui.prefs.path.parent/'maintenance-request.json').exists()
    busy=queued or result.get('status')=='Working'
    if busy:p.text((24,334),'Applying connection changes…',20,fill='#efedf6')
    else:p.button((24,316,696,364),'Restart hotspot' if ready else 'Start setup hotspot',lambda:ui.maintenance('hotspot'),size=22)
    message=ui.banner or (result.get('message','') if result.get('status')=='Failed' else '')
    if message:p.notice(message)
    else:p.text((24,452),'Starting the hotspot disconnects the Pi from its current Wi-Fi',14)
    present(ui,p)


def ssh(ui):
    from ..ssh_access import status
    info=status()
    p=page_for(ui,'SSH access',getattr(ui,'ssh_return',ui.recovery_page))
    p.bar((24,128,696,184),'SSH',lambda:ui.set_ssh(not info['enabled']),toggle=info['enabled'],size=30)
    p.panel((24,216,696,328))
    p.text((42,236),'Username',20);p.text((292,236),info['username'],22,fill='#efedf6')
    p.text((42,280),'Default password',20);p.text((292,280),info['password'],22,fill='#efedf6')
    p.text((24,338),'Enable only on a trusted network. Change the password with passwd.',16)
    address=network_status().get('address')
    if address:p.text((24,368),'ssh '+info['username']+'@'+address,24,fill='#efedf6')
    result=job_status(ui.prefs.path.parent)
    busy=(ui.prefs.path.parent/'maintenance-request.json').exists() or result.get('status')=='Working'
    p.notice('Applying SSH setting…' if busy else result.get('message','') if result.get('status')=='Failed' else ui.banner)
    present(ui,p)


def storage(ui):
    p=page_for(ui,'Storage protection',ui.system_settings)
    enabled=ui.storage_target
    p.label((24,128),'Enable protection?' if enabled else 'Allow system changes?',26)
    for i,text in enumerate((('Protects system files from unexpected power cuts' if enabled else 'Makes system files writable for maintenance'),
                             'HLauncher updates, settings and pairing still save normally',
                             'A restart is required to change this mode')):
        p.text((24,180+i*32),text,17)
    result=job_status(ui.prefs.path.parent)
    queued=(ui.prefs.path.parent/'maintenance-request.json').exists()
    busy=queued or result.get('status')=='Working'
    transition=ui.prefs.path.parent/'storage-transition.json'
    from ..obd import read_json
    pending=read_json(transition).get('target')==('protected' if enabled else 'writable')
    if not ui.storage_info['available']:p.notice('This SD card does not have the required storage layout',320)
    elif busy:p.text((24,320),'Applying changes…',20,fill='#efedf6')
    elif pending and result.get('status')=='Done':
        p.text((24,300),'Changes are ready. Restart to apply them',18)
        p.button((372,364,696,416),'Restart',lambda:ui.maintenance('reboot'),selected=True,size=23)
    else:
        p.button((372,364,696,416),'Enable protection' if enabled else 'Allow system changes',
                 lambda:ui.maintenance('protect' if enabled else 'unprotect'),size=21,selected=True)
    p.button((24,364,348,416),'Back',ui.system_settings,secondary=True,size=22)
    p.notice(ui.banner or (result.get('message','') if result.get('status')=='Failed' else ''),452)
    present(ui,p)


def plugins(ui):
    entries=sorted(ui.manifests.values(),key=lambda m:m.id!='carplay')
    projection = [m for m in entries if m.id in ('carplay', 'android-auto')]
    rows = ([Row('Phone Projection', ui.projection_settings_page)] if projection else [])
    rows += [Row(m.name, lambda pid=m.id: ui.plugin_detail(pid),
                 value='' if m.bundled else m.version) for m in entries
             if m.id not in ('carplay', 'android-auto')]
    if ui.plugin_manager:
        rows.append(Row('Add plugin', ui.plugin_manager.add))
        if ui.plugin_store.legacy_sources():
            rows.append(Row('Older plugins saved', ui.legacy_plugin_notice))
    if settings_menu(ui, 'Plugins', ui.settings, row_items(rows), footer='' if rows else 'No plugins installed'):
        return
    p=page_for(ui,'Plugins',ui.settings)
    draw_rows(ui, p, rows)
    if not rows:p.text((24,128),'No plugins installed',20)
    p.notice(ui.banner,462)
    present(ui,p)


def vehicle_settings(ui, rows):
    from ..vehicle_fields import GROUPS, field_label, visible

    hidden = set(ui.prefs.data['vehicle_hidden'])
    group = getattr(ui, 'vehicle_field_group', None)
    if group is None:
        title = 'Vehicle'
        back = ui.plugin_settings
        for key, (name, fields) in GROUPS.items():
            count = sum(visible(field, hidden) for field in fields)
            rows.append(Row(name, lambda key=key: ui.vehicle_fields_page(key),
                            value=f'{count} of {len(fields)}' if count else 'Hidden'))
    else:
        title, fields = GROUPS[group]
        back = lambda: ui.vehicle_fields_page(None)
        rows = [Row('Show this group', lambda: ui.toggle_vehicle_field(group), toggle=group not in hidden)]
        for field in fields:
            action = lambda field=field: ui.toggle_vehicle_field(field)
            enabled = field not in hidden
            if group in hidden:
                rows.append(Row(field_label(field), action, value='Saved on' if enabled else 'Saved off'))
            else:
                rows.append(Row(field_label(field), action, toggle=enabled))
    key = 'vehicle-settings:' + (group or 'groups')
    footer = ('Group hidden · individual choices are saved' if group in hidden
              else 'Controls which readings appear in Vehicle')
    if settings_menu(ui, title, back, row_items(rows), footer=footer, key=key):
        return
    p = page_for(ui, title, back)
    draw_rows(ui, p, rows, bottom=436, key=key, size=23)
    p.notice(ui.banner or footer)
    present(ui, p)


def plugin_detail(ui):
    manifest=ui.manifests.get(ui.settings_plugin_id)
    if manifest is None:return plugins(ui)
    rows=[Row('Enabled',lambda:ui.toggle_plugin(manifest.id),toggle=ui.prefs.enabled(manifest))]
    if manifest.revision and ui.plugin_manager:
        manager = ui.plugin_manager
        rows = [Row('Enabled', lambda: manager.toggle(manifest), toggle=ui.prefs.enabled(manifest)),
                Row('Version', None, value=manifest.version)]
        if 'camera' in manifest.permissions:
            from ..cameras import usb_cameras
            camera = usb_cameras().get(manifest.camera) if manifest.camera else None
            rows.append(Row('USB camera', lambda: manager.camera_page(manifest.id),
                            value=camera or ('Unavailable' if manifest.camera else 'Select')))
        if 'network' in manifest.permissions:
            rows.append(Row('TCP endpoint', lambda: manager.endpoint_page(manifest.id), value=manifest.endpoint))
        if manifest.origin.startswith('GitHub '):
            rows.append(Row('Check GitHub for update', lambda: manager.check_update(manifest)))
        if ui.plugin_store.has_previous(manifest.id):
            rows.append(Row('Restore previous version', lambda: manager.change(manifest.id, 'rollback')))
        rows.append(Row('Uninstall', lambda: manager.confirm_remove(manifest.id)))
        message = ui.banner or manifest.blocked or manifest.origin
        if settings_menu(ui, manifest.name, ui.plugin_settings, row_items(rows), footer=message):
            return
        p=page_for(ui,manifest.name,ui.plugin_settings)
        draw_rows(ui, p, rows, bottom=422, key='plugin:'+manifest.id, size=25)
        p.notice(message)
        present(ui, p)
        return
    if manifest.bundled and manifest.id == 'vehicle':
        vehicle_settings(ui, rows)
        return
    if manifest.id=='carplay':
        rows.append(Row('Dongle info', ui.adapter_info_page))
        rows.append(Row('Frame rate', ui.toggle_carplay_fps, value=f'{ui.prefs.carplay_fps} FPS'))
        rows.append(Row('Adapter icon',ui.adapter_branding_page))
    elif manifest.id=='obd':rows.append(Row('Coming soon', None))
    elif manifest.keep_alive and manifest.id!='android-auto':
        rows.append(Row('Run in background',lambda:ui.toggle_background(manifest.id),toggle=ui.prefs.background_enabled(manifest)))
    if manifest.id in ('carplay', 'android-auto'):
        rows.append(Row('Follow headlights', lambda: ui.toggle_auto_night(manifest.id),
                        toggle=ui.prefs.auto_night(manifest.id)))
        rows.append(Row('Use car built-in GPS', lambda: ui.toggle_car_gps(manifest.id),
                        toggle=ui.prefs.car_gps(manifest.id)))
    if settings_menu(ui, manifest.name, ui.plugin_settings, row_items(rows)):
        return
    p=page_for(ui,manifest.name,ui.plugin_settings)
    draw_rows(ui,p,rows,key='plugin:'+manifest.id)
    p.notice(ui.banner)
    present(ui,p)


def phone_projection(ui):
    p = page_for(ui, 'Phone Projection', ui.home)
    source = ui.host.active if ui.host.active in ('carplay', 'android-auto') else next(
        (ident for ident in ('carplay', 'android-auto') if ident in ui.host.workers), None)
    worker = ui.host.workers.get(source)
    metrics = getattr(worker, 'metrics', {})
    info = metrics.get('adapter_info', {})
    connected = metrics.get('phone_connected') is True
    protocol = 'Android Auto' if source == 'android-auto' else info.get('protocol') or 'phone projection'
    title = 'Starting ' + protocol if connected else 'Waiting for your phone'
    detail = ('Connect your Android phone to the Pi by USB' if source == 'android-auto'
              else 'Connect to the dongle, or plug Android into the Pi')
    status = getattr(worker, 'status', '')
    if connected:
        detail = status or 'Your phone is connected · preparing the display'
    if ui.banner or any(word in status.casefold() for word in ('failed', 'error', 'lost', 'not installed', 'paused')):
        title, detail = 'Check phone connection', ui.banner or status
    icon = art.glyph('phone-projection', 144)
    p.image.paste(icon, (288, 124), icon)
    p.text((360, 288), title, 30, fill='#ffffff', anchor='mm')
    lines = wrap_status(detail, p.draw, font(19), 624)[:2]
    for index, line in enumerate(lines):
        p.text((360, 328 + index*24), line, 19, anchor='mm')
    modes = 'CarPlay · Android Auto'
    if info.get('aa_support') == 'Not advertised':
        modes = 'CarPlay via dongle · Android Auto via direct USB'
    p.text((360, 384), modes, 16, anchor='mm')
    p.button((24, 408, 80, 464), '', ui.projection_settings_page, secondary=True)
    gear = art.glyph('settings', 36)
    p.image.paste(gear, (34, 418), gear)
    p.text((96, 436), 'Settings', 18, anchor='lm')
    present(ui, p)


def projection_settings(ui):
    rows = []
    for ident, label in (('carplay', 'Use USB dongle'), ('android-auto', 'Use direct USB Android Auto')):
        manifest = ui.manifests.get(ident)
        if manifest:
            rows.append(Row(label, lambda ident=ident: ui.toggle_plugin(ident), toggle=ui.prefs.enabled(manifest)))
    rows += [Row('Phones', ui.projection_phones_page), Row('Dongle info', ui.adapter_info_page),
             Row('Dongle frame rate', ui.toggle_carplay_fps, value=f'{ui.prefs.carplay_fps} FPS'),
             Row('Adapter icon', ui.adapter_branding_page)]
    for ident, label in (('carplay', 'Dongle'), ('android-auto', 'Direct USB')):
        if ident in ui.manifests:
            rows += [Row(label + ': follow headlights', lambda ident=ident: ui.toggle_auto_night(ident), toggle=ui.prefs.auto_night(ident)),
                     Row(label + ': car GPS', lambda ident=ident: ui.toggle_car_gps(ident), toggle=ui.prefs.car_gps(ident))]
    for ident, label in (('carplay', 'Connect through dongle'), ('android-auto', 'Connect Android Auto via direct USB')):
        manifest = ui.manifests.get(ident)
        if manifest and ui.prefs.enabled(manifest):
            rows.append(Row(label, lambda ident=ident: ui.start_projection(ident)))
    back = getattr(ui, 'projection_settings_return', ui.plugin_settings)
    if settings_menu(ui, 'Phone Projection', back, row_items(rows), footer=ui.banner):
        return
    p = page_for(ui, 'Phone Projection', back)
    draw_rows(ui, p, rows, bottom=422, key='projection-settings', size=22)
    p.notice(ui.banner)
    present(ui, p)


def projection_phones(ui):
    rows = []
    for phone in ui.host.projection_phones.snapshot():
        status = 'Connected' if phone['connected'] else 'Paired with dongle' if phone['paired'] else 'Previously connected' if phone.get('last_connected') else 'Previously reported'
        detail = status
        rows.append(Row(('Favorite · ' if phone.get('favorite') else '') + phone['name'], lambda key=phone['id']: ui.projection_phone_page(key), value=detail))
    if 'android-auto' in ui.host.workers:
        worker = ui.host.workers['android-auto']
        rows.insert(0, Row('Direct USB Android Auto', None, value='Connected' if (getattr(worker, 'video_available', False) or getattr(worker, 'metrics', {}).get('phone_connected') is True) else 'Waiting for phone'))
    footer = '' if rows else 'No phones reported yet. Connect a phone through the dongle or direct USB.'
    if settings_menu(ui, 'Phones', ui.projection_settings_page, row_items(rows), footer=footer):
        return
    p = page_for(ui, 'Phones', ui.projection_settings_page)
    draw_rows(ui, p, rows, bottom=422, key='projection-phones', size=21)
    p.notice(footer)
    present(ui, p)


def projection_phone(ui):
    phone = next((phone for phone in ui.host.projection_phones.snapshot()
                  if phone['id'] == getattr(ui, 'projection_phone_id', None)), {})
    p = page_for(ui, phone.get('name', 'Phone'), ui.projection_phones_page)
    last = phone.get('last_connected')
    try:
        last = datetime.fromtimestamp(last).strftime('%b %d, %Y %H:%M') if last else 'Not observed'
    except (ValueError, OverflowError, OSError):
        last = 'Unknown'
    key = phone.get('id')
    known = key in ui.host.projection_phones.addresses and phone.get('paired')
    favorite = phone.get('favorite', False)
    rows = [Row('Connect now', ui.connect_projection_phone if known else None,
                value='Connected' if phone.get('connected') else '' if known else 'Connect dongle')]
    if favorite or known:
        rows.append(Row('Favorite phone', ui.favorite_projection_phone, toggle=favorite))
    else:
        rows.append(Row('Favorite phone', None, value='Connect dongle'))
    worker = ui.host.workers.get('carplay')
    attempt = getattr(worker, 'metrics', {}).get('phone_connection', {})
    request = getattr(ui, 'projection_phone_request', None)
    detail = ui.banner or 'Connect now switches away from the current dongle phone'
    if (not ui.banner or ui.banner == 'Connection requested') and isinstance(attempt, dict) and attempt.get('phone_id') == key:
        result = attempt.get('result')
        labels = {'disconnecting':'Disconnecting current phone', 'connecting':'Connecting to phone',
                  'connected':'Selected phone connected', 'failed':'Connection failed',
                  'skipped':'Current session kept'}
        if not request or request[0] != key or attempt.get('request_id') == request[1]:
            detail = labels.get(result, 'Waiting for dongle')
            reasons = {'busy':'Another connection attempt is running', 'not_paired':'Phone is not in the dongle paired list',
                       'disconnect_send_failed':'Dongle rejected the disconnect request',
                       'connect_send_failed':'Dongle rejected the connection request',
                       'autoconnect_send_failed':'Dongle rejected auto-connect setup',
                       'disconnect_timeout':'Current phone did not disconnect',
                       'connection_timeout':'Selected phone did not connect',
                       'adapter_disconnected':'Dongle connection lost', 'worker_queue_full':'Dongle command queue is full'}
            if attempt.get('reason') in reasons:
                detail = reasons[attempt['reason']]
    if request and request[0] == key and time.monotonic() > request[2] and (attempt.get('request_id') != request[1] or attempt.get('result') in ('connecting', 'disconnecting')):
        detail = 'Connection request timed out · no dongle response'
    rows += [Row('Status', None, value='Connected' if phone.get('connected') else 'Disconnected'),
             Row('Last protocol', None, value=phone.get('protocol') or 'Unknown'),
             Row('Last transport', None, value=phone.get('transport') or 'Unknown'),
             Row('Last connected', None, value=last)]
    if settings_menu(ui, phone.get('name', 'Phone'), ui.projection_phones_page, row_items(rows), footer=detail):
        return
    draw_rows(ui, p, rows, bottom=422, key='projection-phone', size=22)
    p.notice(detail)
    present(ui, p)


def adapter_info(ui):
    p = page_for(ui, 'Dongle info', ui.projection_settings_page)
    worker = ui.host.workers.get('carplay')
    info = getattr(worker, 'metrics', {}).get('adapter_info', {})
    if not isinstance(info, dict):
        info = {}
    from ..adapter_info import text
    fields = (('USB ID', 'usb_id'), ('Firmware', 'firmware'), ('Product', 'product'),
              ('Hardware', 'hardware'), ('AA support', 'aa_support'),
              ('Phone protocol', 'protocol'), ('Transport', 'transport'))
    rows = [Row(label, None, value=text(info.get(key)) or 'Unknown') for label, key in fields]
    rows.append(Row('Parking brake forwarding', None, value='Unverified'))
    draw_rows(ui, p, rows, bottom=422, key='adapter-info', size=22)
    p.notice('Live adapter reports; AA support still needs a connection test' if info
             else 'Waiting for reports; enable the dongle and connect it')
    present(ui, p)


def adapter_branding(ui):
    from ..config import ROOT
    p=page_for(ui,'Adapter icon',ui.projection_settings_page)
    with Image.open(ROOT/'hlauncher/ui/assets/branding/hlauncher-180.png') as icon:
        icon=icon.convert('RGBA').resize((132,132),Image.Resampling.LANCZOS)
        p.image.paste(icon,(294,120),icon)
    p.label((286,274),'HLauncher',30)
    p.text((24,330),'Added automatically when CarPlay starts.',21)
    p.text((24,366),'Reconnect your phone after applying to refresh its icon.',18)
    p.button((24,408,696,448),'Apply to adapter',ui.apply_adapter_branding,size=24)
    worker=ui.host.workers.get('carplay')
    saved=ui.host.branding.data
    result=saved.get('status') or getattr(worker,'metrics',{}).get('adapter_branding','waiting')
    text={'queued':'Waiting for the adapter connection…','waiting':'Waiting for the adapter connection…','transferred':'Files transferred · reconnect your iPhone','sending':'Sending icon to adapter…',
          'sent':'Files transferred · reconnect your iPhone','failed':'Icon transfer failed · tap Apply to retry'}
    p.notice(ui.banner or text.get(result,text['waiting']))
    present(ui,p)


def appearance(ui):
    color = ui.prefs.data['tile_color']
    color_name = 'Custom' if color.startswith('#') else color
    clock = ui.prefs.data['show_clock']
    theme = ui.layout_theme
    rows = []
    if theme.supports_color_selection:
        rows.append(Row('Background color' if theme.id == 'oem' else 'Theme color', ui.tile_colors, value=color_name))
    rows.extend((Row('Show clock', ui.toggle_clock, toggle=clock),
                 Row('Picture', ui.color_settings),
                 Row('Change theme', ui.themes_page, value=theme.name)))
    if settings_menu(ui, 'Appearance', ui.settings, row_items(rows)):
        return
    p = page_for(ui, 'Appearance', ui.settings)
    draw_rows(ui, p, rows)
    present(ui, p)


def theme_preview(ui):
    from . import home, settings, theme_menu

    theme = ui.theme_preview
    screen = ui.theme_preview_screen
    choices = tuple(ui.themes.choices)
    current = choices.index(theme.id) + 1
    p = page_for(ui, 'Change theme', ui.appearance_settings)
    p.label((24, 112), p.fit(theme.name, 480, 25), 25)
    status = f'{current} / {len(choices)}'
    if theme.id == ui.layout_theme.id:
        status += '  ·  Active'
    p.text((696, 128), status, 17, anchor='rm')
    size = (384, 256)
    layout = theme.layouts.get(screen)
    color = ui.theme_preview_color or ui.prefs.data['tile_color']
    show_clock = ui.prefs.data['show_clock']
    clock = datetime.now().strftime('%-I:%M') if show_clock else None
    if screen == 'home':
        pages = home.launcher_layout(ui, layout)
        if layout:
            preview = theme_menu.render(theme, layout, 'Home', theme_menu.home_items(pages),
                                        size=size, clock=clock, change_page=ui.change_page, color=color)
        else:
            preview = home.render(pages, theme=color, size=size, clock=clock, show_clock=show_clock)
    else:
        rows = settings.categories(ui)
        if layout:
            items = [Item(row.title, row.action) for row in rows]
            preview = theme_menu.render(theme, layout, 'Settings', [items], size=size,
                                        back=ui.home, clock=clock, footer=f'Version {__version__}', color=color)
        else:
            preview = settings.render(rows, ui.home, theme=color, size=size, clock=clock,
                                      version=__version__, show_clock=show_clock)
    p.image.paste(preview.image, (168, 144))
    p.draw.rectangle((167, 143, 552, 400), outline='#64616d')
    if len(choices) > 1:
        p.button((24, 246, 152, 298), '‹  Previous', lambda: ui.move_theme_preview(-1), secondary=True)
        p.button((568, 246, 696, 298), 'Next  ›', lambda: ui.move_theme_preview(1), secondary=True)
    p.button((24, 414, 148, 458), 'Home', lambda: ui.set_theme_preview_screen('home'),
             selected=screen == 'home')
    p.button((160, 414, 284, 458), 'Settings', lambda: ui.set_theme_preview_screen('settings'),
             selected=screen == 'settings')
    if theme.supports_color_selection:
        p.button((296, 414, 396, 458), 'Color', ui.preview_colors, secondary=True)
    p.button((408, 414, 696, 458), 'Use theme', ui.select_theme, selected=True, size=22)
    p.notice(ui.banner, 462)
    present(ui, p)



def startup(ui):
    manifest=ui.manifests.get(ui.prefs.data['default_plugin'])
    value=('Phone Projection' if manifest.id in ('carplay', 'android-auto') else manifest.name) if manifest and manifest.id != 'obd' and ui.prefs.enabled(manifest) else 'Home'
    if settings_menu(ui, 'Startup', ui.settings, (Item('Start with', ui.cycle_default, value),),
                     footer='Tap to cycle through Home and enabled apps'):
        return
    p=page_for(ui,'Startup',ui.settings)
    draw_rows(ui,p,[Row('Start with',ui.cycle_default,value=value)])
    p.text((24,204),'Select to cycle through Home and your enabled apps',17)
    present(ui,p)


def themes(ui):
    preview = ui.mode == 'preview_colors'
    theme = ui.theme_preview if preview else ui.layout_theme
    color = (ui.theme_preview_color if preview else None) or ui.prefs.data['tile_color']
    back = ui.resume_theme_preview if preview else ui.appearance_settings
    p = page_for(ui, 'Background color' if theme.id == 'oem' else 'Theme color', back)
    for i,name in enumerate(TILE_COLORS):
        x=24+i%3*228;y=128+i//3*104;previous=p.theme;p.theme=name
        p.button((x,y,x+216,y+88),name,lambda name=name:ui.set_tile_color(name),
                 selected=name==color,size=24)
        p.theme=previous
    p.button((24,364,696,420),'Custom color',ui.custom_color,selected=color.startswith('#'),size=24)
    p.notice(ui.banner)
    present(ui,p)


def picture(ui):
    p=page_for(ui,'Picture',ui.appearance_settings)
    ui.picture_sliders=[]
    accent=p.accent
    for i,key in enumerate(DEFAULTS):
        y=128+i*80;value=ui.picture_values[key];low,high=LIMITS[key]
        p.label((24,y),key.capitalize(),24)
        p.text((696,y),f'{value:+d}' if key=='brightness' else f'{value}%',18,anchor='rt')
        box=(236,y+12,636,y+44);cy=y+28
        x=box[0]+round((value-low)/(high-low)*(box[2]-box[0]))
        default=box[0]+round((DEFAULTS[key]-low)/(high-low)*(box[2]-box[0]))
        p.draw.line((box[0],cy,box[2],cy),fill='#514957',width=8)
        p.draw.line((box[0],cy,x,cy),fill=accent,width=8)
        p.draw.line((default,cy-10,default,cy+10),fill='#a099aa',width=2)
        p.draw.ellipse((x-12,cy-12,x+12,cy+12),fill='#f1edf7')
        ui.picture_sliders.append((key,scale_bounds((box[0],y+4,box[2],y+52),p.size)))
    # Stable references for tuning saturation and shadow/highlight detail live.
    for i,color in enumerate(('#ff0000','#ffff00','#00ff00','#00ffff','#0000ff','#ff00ff')):
        x=24+i*112
        p.draw.rectangle((x,348,x+111,364),fill=color)
    for i,level in enumerate((0,16,32,64,128,192,235,255)):
        x=24+i*84
        p.draw.rectangle((x,370,x+83,382),fill=(level,level,level))
    p.button((24,396,200,440),'Reset',ui.reset_picture,secondary=True)
    if 'carplay' in ui.manifests and ui.prefs.enabled(ui.manifests['carplay']):
        p.button((212,396,446,440),'Preview',lambda:ui.open_plugin('carplay'))
    p.button((458,396,696,440),'HDMI test',ui.hdmi_calibration)
    p.notice(ui.banner)
    present(ui,p)


def hdmi(ui):
    from ..hdmi_calibration import RANGES
    p=page_for(ui,'HDMI range',ui.color_settings)
    exact=ui.hdmi_test_exact
    inset=ui.hdmi_test_inset
    def color(values):return tuple(16+round(v*219/255) for v in values) if inset else values
    p.button((24,100,352,126),'Buffer: '+('8-bit RGB' if exact else 'Original RGB565'),lambda:ui.toggle_hdmi_test('buffer'),size=17)
    p.button((368,100,696,126),'Test levels: '+('Inset 16–235' if inset else 'Standard 0–255'),lambda:ui.toggle_hdmi_test('levels'),size=17)
    p.text((24,126),'Overall levels',12)
    for i,value in enumerate((0,32,64,96,128,160,192,224,255)):
        x=24+i*672//9;right=24+(i+1)*672//9-1
        p.draw.rectangle((x,140,right,169),fill=color((value,)*3))
        p.text(((x+right)//2,172),color((value,)*3)[0],12,anchor='mt',fill='white')
    for row,values in enumerate(((0,4,8,12,16,20,24,32),(223,231,235,239,243,247,251,255))):
        y=208+row*62
        p.text((24,y-17),'Black detail' if row==0 else 'White detail',12)
        for i,value in enumerate(values):
            x=24+i*84;p.draw.rectangle((x,y,x+83,y+25),fill=color((value,)*3))
            p.text((x+42,y+28),color((value,)*3)[0],12,anchor='mt',fill='white')
    saturated=((192,0,0),(0,192,0),(0,0,192),(192,192,0),(0,192,192),(192,0,192))
    pale=((255,255,255),(240,248,232),(220,240,200),(232,242,252),(248,236,220),(240,232,248))
    for row,colors in enumerate((saturated,pale)):
        for i,swatch in enumerate(colors):p.draw.rectangle((24+i*112,320+row*22,135+i*112,340+row*22),fill=color(swatch))
    for i,label in enumerate(('Auto','Full','Limited')):
        x=24+i*228;p.button((x,368,x+216,408),label,lambda value=i:ui.set_hdmi_range(value),
                           selected=ui.hdmi_range_selected==i,size=21)
    p.button((24,420,696,460),'Save HDMI range',ui.save_hdmi_range,size=22)
    p.notice(ui.banner if getattr(ui.fb,'kms',None) is not None else 'DRM unavailable · RGB565 fallback',464)
    present(ui,p,dither=False,exact=exact,calibration=True)


def shutdown(ui):
    pending=ui.mode=='shutdown_pending'
    restarting=getattr(ui,'shutdown_action','poweroff')=='reboot'
    title=('Restarting' if restarting else 'Shutting down') if pending else 'Shut down or restart'
    p=page_for(ui,title,getattr(ui,'shutdown_return',ui.system_settings))
    p.label((24,144),('Restarting the Pi…' if restarting else 'Shutting down the Pi…') if pending else 'Shut down or restart the Pi?',28)
    if not pending:
        p.button((24,320,240,380),'Cancel',getattr(ui,'shutdown_return',ui.system_settings),secondary=True,size=22)
        p.button((252,320,468,380),'Restart',ui.restart_pi,secondary=True,size=22)
        p.button((480,320,696,380),'Shut down',ui.shutdown_pi,selected=True,size=22)
    else:p.actions=[]
    p.notice(ui.banner)
    present(ui,p)


def waiting(ui):
    m=ui.manifests.get(ui.host.active)
    p=page_for(ui,m.name if m else 'App',ui.home)
    icon=art.glyph(m.id if m else '',80);p.image.paste(icon,(320,128),icon)
    p.panel((24,256,696,392))
    for i,line in enumerate(wrap_status(ui.host.status() or 'Starting app…',p.draw,font(18),624)):
        p.text((360,280+i*24),line,18,anchor='mt',fill='#efedf6')
    present(ui,p)


PAGES={'projection_phone':projection_phone,'phone_projection':phone_projection,'projection_settings':projection_settings,'projection_phones':projection_phones,'ssh_settings':ssh,'adapter_branding':adapter_branding,'adapter_info':adapter_info,'appearance_settings':appearance,'startup_settings':startup,'system_settings':system,'recovery_settings':network,'hotspot_settings':hotspot,'wifi_power_settings':wifi_power,'storage_confirm':storage,
       'plugins_settings':plugins,'plugin_detail':plugin_detail,'tile_colors':themes,'colors':picture,'hdmi_test':hdmi,
       'shutdown_confirm':shutdown,'shutdown_pending':shutdown,'about_settings':about,
       'legal_info':legal_info,'audio_coming_soon':audio_coming_soon,
       'theme_preview':theme_preview,'preview_colors':themes,
       'safety_agreement':safety_agreement,'obd_coming_soon':obd_coming_soon}
