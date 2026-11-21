"""Desktop-only hardware substitutes around the production Launcher and PluginHost.

Run in a dedicated process: the process-wide hardware guard is intentional.
Nothing here is imported by the Pi application.
"""
import hashlib
import io
import json
import subprocess
import sys
import time
from collections import deque
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from PIL import Image, ImageDraw
from hlauncher.config import ROOT, Preferences
from hlauncher.launcher import Launcher
from hlauncher.protocol_diagnostics import ProtocolDiagnostics


class Display:
    w,h=720,480
    kms=None
    def __init__(self):
        self.revision=0;self.png=b''
    def open(self):pass
    def close(self):pass
    def image(self,image,**options):
        self.last=image.copy();output=io.BytesIO();image.save(output,format='PNG')
        self.png=output.getvalue();self.revision+=1
    image_exact=image
    image_test=image
    def blit(self,raw):
        self.image(Image.frombytes('RGB',(self.w,self.h),bytes(raw),'raw','BGR;16'))


class Worker:
    """In-process peer for the real host; no USB, codecs, subprocesses or audio."""
    def __init__(self,manifest,width,height,event,**options):
        self.manifest=manifest;self.width=width;self.height=height;self.event=event
        self.proc=SimpleNamespace(pid=0,poll=lambda:None)
        self.metrics={};self.ready=True;self.active=False;self.closed=False
        self.status='Simulator · waiting for phone';self.video_available=False
        self.last_message=time.monotonic();self.pending=None;self.last_parking_state=None
        self.frames_received=self.frames_superseded=self.frames_copied=0
        self.car_gps=options.get('car_gps',False);self.favorite_sent=None
        from sdk.hlauncher_sdk.buttons import BUTTONS
        self.button_subscription=BUTTONS
        self.messages=deque(maxlen=30);self.incoming=[];self.dashboard=None;self.dirty=True
        if manifest.id=='vehicle':
            sys.path.insert(0,str(ROOT/'plugins/vehicle'))
            from dashboard import Dashboard
            self.dashboard=Dashboard((width,height));self.video_available=True
    def send(self,**message):
        self.messages.append(message);kind=message['type']
        if kind=='host.activate':self.dirty=True
        if kind=='radio.button':
            self.incoming.append(dict(type='radio.button.result',sequence=message['sequence'],button=message['button'],result='Simulated button received'))
        if self.dashboard:
            if kind=='vehicle.dashboard':
                self.dashboard.update(message['snapshot'],message['hidden'],message['colors'],message['layout'],oem_color=message.get('oem_color'));self.dirty=True
            elif kind=='touch':
                contact=next(iter(message.get('contacts',[])),{})
                point=(contact['x_px'],contact['y_px']) if contact.get('x_px') is not None else None
                result=self.dashboard.touch(contact.get('action','unused'),point);self.dirty=True
                if result=='home':self.incoming.append(dict(type='launcher.home'))
                elif result=='refresh':self.incoming.append(dict(type='vehicle.refresh'))
        if kind=='host.adapter.connect':
            self.metrics['phone_connection']=dict(result='connected',request_id=message['request_id'],updated_at=time.monotonic())
            if hasattr(self,'on_connect'):self.on_connect(message.get('address'))
            self.event(state='simulated_phone_request',address=message.get('address'))
        return True
    def drain(self):self.last_message=time.monotonic()
    def read(self):result,self.incoming=self.incoming,[];return result
    def close(self):self.closed=True
    def release(self,slot):pass
    def take_frame(self):
        if not self.video_available or not self.dirty:return None
        from hlauncher.display import encode
        if self.dashboard:image=self.dashboard.render()
        else:
            from sdk.hlauncher_sdk.fonts import font
            image=Image.new('RGB',(self.width,self.height),'#10151b');draw=ImageDraw.Draw(image)
            protocol=self.metrics.get('adapter_info',{}).get('protocol','Android Auto')
            draw.text((32,36),protocol,font=font(36),fill='#f2f6fb')
            draw.text((32,112),'Simulated phone display',font=font(24),fill='#aebbcb')
            draw.text((32,160),'Connection and launcher routing are real application logic',font=font(18),fill='#aebbcb')
            draw.text((32,192),'Phone video, USB transport and audio are not emulated',font=font(18),fill='#aebbcb')
            draw.rounded_rectangle((24,376,232,440),radius=8,fill='#283442')
            draw.text((48,396),'Back to HLauncher',font=font(20),fill='#f2f6fb')
        self.dirty=False;self.frames_received+=1
        return encode(image)


class DesktopLauncher(Launcher):
    def request_power_action(self,action):
        self.event(state='simulated_power_request',action=action)
        self.banner='Simulated '+('restart' if action=='reboot' else 'shutdown')+' · Mac stays running'
        self.draw()
    def update_request(self,operation,target=None):
        self.simulator.update_action(operation,target)
        self.draw()
    def maintenance(self,operation):
        self.simulator.job(operation);self.draw()


class Simulator:
    def __init__(self,folder,*,fresh=False):
        self.folder=Path(folder);self.folder.mkdir(parents=True,exist_ok=True)
        self.events=deque(maxlen=80);self.guard=ExitStack();self.last_telemetry=0
        self.values=dict(radio=True,brake=True,speed=0,dongle='dual',phone='none',wifi=True,video=True)
        self.display=Display();self.ui=None
        try:
            self._install_guard()
            prefs=Preferences(self.folder/'settings.json')
            if not prefs.path.exists() or fresh:
                prefs.accept_safety_notice();prefs.data.update(setup_complete=True,debug_mode=True,wifi_power='on');prefs.save()
            self.protocols=ProtocolDiagnostics(self.folder/'captures',vehicle_path=self.folder/'vehicle-last-known.json')
            self.ui=DesktopLauncher(event=self.event,framebuffer=self.display,preferences=prefs,protocol_diagnostics=self.protocols)
            self.ui.simulator=self;self.ui.audio.playback.start_worker=False
            self.ui.inputs.status='Simulated radio inputs'
            self.ui.storage_info=dict(protected=False,available=True,message='Simulator storage')
            if not (self.folder/'update-status.json').exists():self.set_update('ready')
            try:scenario=json.loads((self.folder/'simulator-scenario.json').read_text())
            except (OSError,ValueError):scenario={}
            self.set_state(scenario if isinstance(scenario,dict) else {})
        except BaseException:
            self.guard.close();raise
    def event(self,**item):
        self.events.append(dict(item,at=round(time.monotonic(),2)))
    def _install_guard(self):
        def deny(*args,**kwargs):
            self.event(state='simulator_hardware_blocked',command=str(args[0] if args else '')[:200])
            raise OSError('Hardware operation is unavailable in the desktop simulator')
        for target in ('subprocess.Popen','subprocess.run','os.system','socket.create_connection','socket.socket.connect'):
            self.guard.enter_context(patch(target,side_effect=deny))
        for target in ('hlauncher.debug_tools.InputMonitor.start','hlauncher.diagnostics.Diagnostics.start','hlauncher.debug_tools.ToneTest.tick'):
            self.guard.enter_context(patch(target,lambda *a,**kw:None))
        self.guard.enter_context(patch('hlauncher.plugin_host.Worker',Worker))
        self.guard.enter_context(patch('hlauncher.projection.carplay_adapter_present',lambda:self.values['dongle']!='none'))
        self.guard.enter_context(patch('hlauncher.projection.direct_android_devices',lambda:{'simulated-usb'} if self.values['phone']=='android-usb' else set()))
        self.guard.enter_context(patch('hlauncher.storage.status',lambda:dict(protected=False,available=True,message='Simulator storage')))
        self.guard.enter_context(patch('hlauncher.recovery.network_status',lambda *a,**kw:self.network()))
        self.guard.enter_context(patch('hlauncher.recovery.request_job',self.job))
        self.guard.enter_context(patch('hlauncher.update_client.request_channel',self.update_action))
        self.guard.enter_context(patch('hlauncher.update_client.offered_plugin_api',lambda version:1))
    def network(self):
        return dict(wifi_link='connected' if self.values['wifi'] else 'disconnected',wifi_signal_dbm=-48,
                    wifi='Simulator Wi-Fi' if self.values['wifi'] else 'Not connected',address='192.0.2.10',monotonic=time.monotonic())
    def job(self,operation,**values):
        self.event(state='simulated_maintenance',operation=operation,values=values)
        if self.ui:
            if operation=='ssh':self.ui.prefs.data['ssh_enabled']=values['enabled']
            elif operation=='wifi_power':self.ui.prefs.data['wifi_power']=values.get('mode','on')
            elif operation=='wifi_boot':self.ui.prefs.data['wifi_delay_boot']=values.get('enabled',False)
            self.ui.prefs.save()
        (self.folder/'maintenance-status.json').write_text(json.dumps(dict(status='Ready',message='Simulated '+operation)))
    def set_update(self,phase):
        from hlauncher import __version__
        if phase not in ('ready','available','beta','checking','downloading','installing','failed','unavailable'):raise ValueError('Unknown update state')
        info=dict(phase='available' if phase=='beta' else phase,current=__version__,current_channel='stable',previous='0.2.11',
                  message={'ready':'HLauncher is up to date','available':'An update is available','beta':'A beta update is available',
                           'failed':'Simulated update failure · retry the check','unavailable':'Updater unavailable in this scenario'}.get(phase,phase.capitalize()+' · simulated'),
                  notes_version='0.2.13',notes='Simulator release notes\n\n- Test navigation and update confirmation\n- No download or installation takes place')
        info['branches']=[dict(branch='develop',commit='1234abcd'),dict(branch='feature/desktop-simulator',commit='5678abcd')]
        if phase in ('available','beta'):info.update(available='0.2.14' if phase=='beta' else '0.2.13',available_channel='beta' if phase=='beta' else 'stable',stable_available='0.2.13')
        if phase=='available' and self.ui and self.ui.prefs.data['include_beta_updates']:
            prefs=self.ui.prefs.data
            info.update(available='0.2.14',available_channel='source' if prefs.get('source_updates') else 'development',
                        available_branch=prefs['development_branch'],available_commit='5678abcd'*5)
        (self.folder/'update-status.json').write_text(json.dumps(info))
        if self.ui:self.ui.draw()
    def update_action(self,operation,target=None):
        self.event(state='simulated_update',operation=operation,target=target)
        self.set_update('available' if operation=='check' else 'installing' if operation in ('install','rollback') else 'ready')
    def telemetry(self):
        p=self.protocols;v=self.values
        if v['radio']:
            p.observe(dict(state='honda_frame',session=1,message=0x61,protocol=(0,'jp.co.honda.rd.dispaudio.app.generals'),
                           payload='10100000000000' if v['brake'] else '10000000000000')) if v['brake'] is not None else None
            if v['speed'] is not None:
                from hlauncher.protocol.vehicle_can import decode_records
                body=b'\0\1'+(0x12F85050).to_bytes(4,'big')+bytes([1,int(v['speed'])])
                payload=b'\0\2'+b'\0'*9+b'\0'+len(body).to_bytes(3,'big')+body
                records=decode_records(payload,api_ids=[152])
                p.observe(dict(state='honda_can_data',session=1,scope='vehicle',data_type=0,records=records))
        self.last_telemetry=time.monotonic()
    def set_state(self,changes):
        allowed=set(self.values)
        if set(changes)-allowed:raise ValueError('Unknown simulator setting')
        new=dict(self.values,**changes)
        for key in ('radio','wifi','video'):
            if type(new[key]) is not bool:raise ValueError('Expected boolean '+key)
        if (new['brake'] is not None and type(new['brake']) is not bool) or (new['speed'] is not None and (type(new['speed']) is not int or not 0<=new['speed']<=200)):raise ValueError('Invalid parking telemetry')
        if new['phone'] not in ('none','carplay','android-dongle','android-usb') or new['dongle'] not in ('none','carplay','dual'):raise ValueError('Invalid projection scenario')
        old=self.values;self.values=new;ui=self.ui;p=self.protocols
        if new['radio']!=old['radio'] or not p.connected:
            p.observe(dict(state='connected' if new['radio'] else 'closed',uuid='simulator-cafe',device='02:00:00:00:00:01'))
            ui.session_changed(connected=new['radio'],authenticated=new['radio'])
            if new['radio']:
                p.observe(dict(state='honda_can_subscription_queued',session=1,scope='vehicle',can_ids=[0x12F85050],cycle=1))
        if new['brake'] is None:p.parking_brake=None;p.vehicle.status.clear()
        if new['speed'] is None:p.parking_speed=None;p.last_reported_speed_at=None
        self.telemetry()
        phone=new['phone'];ident='android-auto' if phone=='android-usb' else 'carplay'
        for key in list(ui.host.workers):
            if key in ('carplay','android-auto') and (key!=ident or new['dongle']=='none' and key=='carplay'):ui.host.stop(key)
        if new['dongle']!='none' or ident=='android-auto':
            foreground = (ui.mode == 'phone_projection' and not ui.projection_devices_open or
                          ui.mode == 'plugin' and ui.host.active in ('carplay', 'android-auto'))
            ui.host.request_projection(ident,foreground)
            worker=ui.host.workers.get(ident)
            if worker:
                connected=phone!='none' and (phone!='android-dongle' or new['dongle']=='dual')
                protocol='Android Auto' if phone.startswith('android') else 'CarPlay'
                worker.metrics=dict(phone_connected=connected,adapter_info=dict(product='CPC200-CCPA (simulated)',firmware='Simulator',
                    usb_id='1314:1520',protocol=protocol if connected else '',transport='USB' if ident=='android-auto' else 'Wireless',
                    aa_support='Reported' if new['dongle']=='dual' else 'Not advertised'))
                worker.video_available=connected and new['video'];worker.dirty=True
                worker.status=('Simulated '+protocol+' connected' if connected else 'Waiting for phone')
                reports=[]
                for address,name in (('02:00:00:00:01:01','Alex’s iPhone'),('02:00:00:00:01:02','Sam’s phone')):
                    reports.append(dict(id=hashlib.sha256(address.encode()).hexdigest()[:24],name=name,address=address,paired=True,
                                        connected=connected and name.startswith('Alex'),protocol=protocol,transport='Wireless'))
                if ident=='carplay':
                    ui.host.projection_phones.update(reports)
                    def connect(address,reports=reports,worker=worker):
                        for report in reports:report['connected']=report['address']==address
                        ui.host.projection_phones.update(reports)
                        worker.metrics['phone_connected']=True;worker.metrics['adapter_info']['protocol']='CarPlay';worker.video_available=self.values['video'];worker.dirty=True
                    worker.on_connect=connect
        from hlauncher.setup_state import atomic_json
        atomic_json(self.folder/'simulator-scenario.json',self.values)
        ui.projection_checked=time.monotonic();ui.draw();self.tick()
    def touch(self,action,x,y):
        if action not in ('down','move','up'):raise ValueError('Unknown touch action')
        if not isinstance(x,(int,float)) or not isinstance(y,(int,float)):raise ValueError('Invalid touch point')
        ui=self.ui
        # Simulated phone video provides a return tile instead of copying Apple's UI.
        if ui.mode=='plugin' and ui.host.active in ('carplay','android-auto') and ui.has_frame and action=='up' and 24<=x<=232 and 376<=y<=440:
            ui.home();return
        ui.update(dict(contacts=[dict(slot=0,action=action,has_position=action!='up',x_raw=round(max(0,min(719,x))*32767/719),y_raw=round(max(0,min(479,y))*32767/479))]))
    def tick(self):
        if time.monotonic()-self.last_telemetry>.5:self.telemetry()
        self.ui.tick()
    def snapshot(self):
        return dict(mode=self.ui.mode,active=self.ui.host.active,parking=self.protocols.plugin_parking_state(),
                    controls=self.values,update=json.loads((self.folder/'update-status.json').read_text())['phase'],revision=self.display.revision,events=list(self.events)[-12:])
    def close(self):
        try:
            if self.ui:self.ui.close()
        finally:self.guard.close()
