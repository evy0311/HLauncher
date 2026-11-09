"""Shared settings, connection and picture pages; no display or service ownership."""
import math
from ..config import TILE_COLORS
from ..colors import DEFAULTS,LIMITS
from ..recovery import job_status, network_status
from ..setup_state import SetupState
from .controls import Page,present
from .scroll_list import Row,draw as draw_rows
from .chrome import scale_bounds
from . import home_art as art
from .projection import wrap_status
from sdk.hlauncher_sdk.fonts import font


def page_for(ui,title,back=None):
    return Page(title,back or ui.settings,ui.prefs.data['tile_color'],(ui.fb.w,ui.fb.h),
                ui.pressed_box if ui.press is not None else None,show_clock=ui.prefs.data['show_clock'])


def system(ui):
    p=page_for(ui,'System',ui.settings)
    info=ui.storage_info
    rows=[('Wi-Fi & pairing','',ui.recovery_page),
          ('Setup wizard','',lambda:ui.setup_page(True)),
          ('Software updates','',ui.updates_page),
          ('Debug mode','On' if ui.prefs.data['debug_mode'] else 'Off',ui.toggle_debug),
          ('Storage protection','Enabled' if info['protected'] else 'Off' if info['available'] else 'Unavailable',lambda:ui.storage_confirm(not info['protected'])),
          ('Shut down','',ui.shutdown_page)]
    if ui.prefs.data['debug_mode']:rows.append(('Diagnostics','',ui.system_diagnostics))
    draw_rows(ui,p,[Row(title,action,value=value) if title!='Debug mode' else
                    Row(title,action,toggle=ui.prefs.data['debug_mode']) for title,value,action in rows])
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
    connection=network_status(ui.prefs.path.parent);address=connection.get('address')
    if not address or address=='192.168.4.1':return hotspot(ui)
    p=page_for(ui,'Wi-Fi & pairing',getattr(ui,'recovery_return',ui.system_settings))
    creds=SetupState(ui.prefs.path.parent).credentials()
    p.label((24,128),'http://'+address+':8080',26)
    p.text((24,176),'Open this page on a device on the same network as the Pi',17)
    p.panel((24,216,696,312))
    for y,label,value in ((236,'Username','hlauncher'),(272,'Password',creds['password'])):
        p.text((42,y),label,16);p.text((240,y),value,17,fill='#efedf6')
    p.button((24,348,696,392),'Use setup hotspot instead',ui.hotspot_page,size=21,secondary=True)
    p.text((24,420),'Use the page to connect Wi-Fi, pair a radio or install an update',16)
    p.notice(ui.banner)
    present(ui,p)


def hotspot(ui):
    parent=ui.network_resume if ui.mode=='hotspot_settings' else getattr(ui,'recovery_return',ui.system_settings)
    p=page_for(ui,'Setup hotspot',parent)
    creds=SetupState(ui.prefs.path.parent).credentials()
    connection=network_status(ui.prefs.path.parent);ready=connection.get('address')=='192.168.4.1'
    p.text((24,116),'Connect your phone or computer to this temporary network',17)
    p.panel((24,156,696,280))
    for y,label,value in ((172,'Network',creds['ssid']),(204,'Password',creds['password']),
                           (236,'Page login','hlauncher · same password')):
        p.text((42,y),label,16);p.text((240,y),p.fit(value,432,17),17,fill='#efedf6')
    p.label((24,304),'http://192.168.4.1:8080',25)
    result=job_status(ui.prefs.path.parent)
    queued=(ui.prefs.path.parent/'maintenance-request.json').exists()
    busy=queued or result.get('status')=='Working'
    if busy:p.text((24,372),'Applying connection changes…',20,fill='#efedf6')
    else:p.button((24,360,696,404),'Restart hotspot' if ready else 'Start setup hotspot',lambda:ui.maintenance('hotspot'),size=22)
    message=ui.banner or (result.get('message','') if result.get('status')=='Failed' else '')
    if message:p.notice(message,420)
    else:p.text((24,420),'This temporarily disconnects the Pi from its current Wi-Fi',15)
    p.text((24,452),'Use the setup page to connect the Pi to your normal Wi-Fi',14)
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
    p=page_for(ui,'Plugins',ui.settings)
    entries=sorted(ui.manifests.values(),key=lambda m:m.id!='carplay')
    draw_rows(ui,p,[Row(m.name,lambda pid=m.id:ui.plugin_detail(pid)) for m in entries])
    if not entries:p.text((24,128),'No plugins installed',20)
    p.notice(ui.banner,462)
    present(ui,p)


def plugin_detail(ui):
    manifest=ui.manifests.get(ui.settings_plugin_id)
    if manifest is None:return plugins(ui)
    p=page_for(ui,manifest.name,ui.plugin_settings)
    rows=[Row('Enabled',lambda:ui.toggle_plugin(manifest.id),toggle=ui.prefs.enabled(manifest))]
    if manifest.id=='carplay':
        rows.extend([Row('CarPlay picture',ui.color_settings),Row('Adapter icon',ui.adapter_branding_page)])
    elif manifest.id=='obd':rows.append(Row('OBD adapter',ui.obd_settings))
    elif manifest.keep_alive and manifest.id!='android-auto':
        rows.append(Row('Run in background',lambda:ui.toggle_background(manifest.id),toggle=ui.prefs.background_enabled(manifest)))
    draw_rows(ui,p,rows,key='plugin:'+manifest.id)
    p.notice(ui.banner)
    present(ui,p)


def adapter_branding(ui):
    from PIL import Image
    from ..config import ROOT
    p=page_for(ui,'CarPlay adapter icon',ui.plugin_detail)
    with Image.open(ROOT/'hlauncher/ui/assets/branding/hlauncher-180.png') as icon:
        icon=icon.convert('RGBA').resize((132,132),Image.Resampling.LANCZOS)
        p.image.paste(icon,(294,120),icon)
    p.label((286,274),'HLauncher',30)
    p.text((24,330),'Added automatically when CarPlay starts.',21)
    p.text((24,366),'Reconnect your phone after applying to refresh its icon.',18)
    p.button((24,408,696,448),'Apply to adapter',ui.apply_adapter_branding,size=24)
    worker=ui.host.workers.get('carplay')
    result=getattr(worker,'metrics',{}).get('adapter_branding','waiting')
    text={'waiting':'','sending':'Sending icon to adapter…',
          'sent':'Icon sent · reconnect your phone if needed','failed':'Icon transfer failed · tap Apply to retry'}
    p.notice(ui.banner or text.get(result,text['waiting']))
    present(ui,p)


def appearance(ui):
    p=page_for(ui,'Appearance',ui.settings)
    draw_rows(ui,p,[Row('Background color',ui.tile_colors,value='Custom' if ui.prefs.data['tile_color'].startswith('#') else ui.prefs.data['tile_color']),
                    Row('Show clock',ui.toggle_clock,toggle=ui.prefs.data['show_clock'])])
    present(ui,p)


def startup(ui):
    p=page_for(ui,'Startup',ui.settings)
    manifest=ui.manifests.get(ui.prefs.data['default_plugin'])
    value=manifest.name if manifest and ui.prefs.enabled(manifest) else 'Home'
    draw_rows(ui,p,[Row('Start with',ui.cycle_default,value=value)])
    p.text((24,204),'Select to cycle through Home and your enabled apps',17)
    present(ui,p)


def themes(ui):
    p=page_for(ui,'Background color',ui.appearance_settings)
    for i,name in enumerate(TILE_COLORS):
        x=24+i%3*228;y=128+i//3*104;previous=p.theme;p.theme=name
        p.button((x,y,x+216,y+88),name,lambda name=name:ui.set_tile_color(name),
                 selected=name==ui.prefs.data['tile_color'],size=24)
        p.theme=previous
    p.button((24,364,696,420),'Custom color',ui.custom_color,selected=ui.prefs.data['tile_color'].startswith('#'),size=24)
    p.notice(ui.banner)
    present(ui,p)


def picture(ui):
    p=page_for(ui,'CarPlay picture',getattr(ui,'picture_return',ui.plugin_settings))
    ui.picture_sliders=[]
    accent=art.blend(art.accent(p.theme),(240,237,250),.5)
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
    p.button((24,396,200,440),'Reset',ui.reset_picture,secondary=True)
    if 'carplay' in ui.manifests and ui.prefs.enabled(ui.manifests['carplay']):
        p.button((212,396,446,440),'Preview',lambda:ui.open_plugin('carplay'))
    p.button((458,396,696,440),'HDMI test',ui.hdmi_calibration)
    p.notice(ui.banner)
    present(ui,p)


def hdmi(ui):
    p=page_for(ui,'HDMI range',ui.color_settings)
    p.text((696,88),ui.hdmi_range_label,16,anchor='rm')
    for row,values in enumerate(((0,4,8,12,16,20,24,32),(223,231,235,239,243,247,251,255))):
        y=128+row*88
        for i,value in enumerate(values):
            x=24+i*84;p.draw.rectangle((x,y,x+83,y+46),fill=(value,)*3)
            p.text((x+42,y+52),value,13,anchor='mt',fill='white')
    p.text((24,304),'Each pale block should look different from white',16)
    for i,color in enumerate(((255,255,255),(240,248,232),(220,240,200),(232,242,252),(248,236,220),(240,232,248))):
        p.draw.rectangle((24+i*112,332,135+i*112,376),fill=color)
    for i,label in enumerate(('Auto','Full','Limited')):
        x=24+i*228;p.button((x,396,x+216,440),label,lambda value=i:ui.set_hdmi_range(value),size=21)
    p.notice(ui.banner)
    present(ui,p,dither=False)


def shutdown(ui):
    pending=ui.mode=='shutdown_pending'
    p=page_for(ui,'Shutting down' if pending else 'Shut down',getattr(ui,'shutdown_return',ui.system_settings))
    p.label((24,144),'Shutting down the Pi…' if pending else 'Shut down the Pi?',28)
    p.text((24,208),'Wait for shutdown to finish before disconnecting power',18)
    if not pending:
        p.button((24,320,348,380),'Cancel',getattr(ui,'shutdown_return',ui.system_settings),secondary=True,size=22)
        p.button((372,320,696,380),'Shut down',ui.shutdown_pi,selected=True,size=22)
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


PAGES={'adapter_branding':adapter_branding,'appearance_settings':appearance,'startup_settings':startup,'system_settings':system,'recovery_settings':network,'hotspot_settings':hotspot,'storage_confirm':storage,
       'plugins_settings':plugins,'plugin_detail':plugin_detail,'tile_colors':themes,'colors':picture,'hdmi_test':hdmi,
       'shutdown_confirm':shutdown,'shutdown_pending':shutdown}
