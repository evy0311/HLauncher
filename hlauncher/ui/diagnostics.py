"""Radio-style diagnostics. Transport, capture and test actions remain host-owned."""
import time
from ..buttons import LABELS
from ..diagnostics import power_status
from ..protocol_diagnostics import SETUP_BRAKE_MAX_AGE, SPEED_MAX_AGE
from .pages import page_for
from .controls import Page, present
from .scroll_list import Row,draw as draw_rows


def menu(ui):
    p = page_for(ui, 'Diagnostics', ui.settings)
    p.bar((24, 128, 696, 184), 'Parking Status', ui.open_parking_status)
    present(ui, p)


PARKING_LABELS = {
    152: ('Vehicle speed', None),
    80: ('CAN parking brake', ('Released', 'Engaged')),
    78: ('Parking brake lamp', ('Off', 'On')),
    79: ('Parking brake reminder', ('Off', 'On')),
    100: ('Transmission Park', ('Inactive', 'Active')),
    99: ('Transmission Neutral', ('Inactive', 'Active')),
    101: ('Transmission Reverse', ('Inactive', 'Active')),
    95: ('Transmission Drive', ('Inactive', 'Active')),
}


def parking_status(ui):
    p = Page('Parking Status', None, ui.prefs.data['tile_color'], (ui.fb.w, ui.fb.h),
             ui.pressed_box, show_clock=ui.prefs.data['show_clock'], layout_theme=getattr(ui, 'layout_theme', None))
    p.button((632, 62, 696, 108), '×', ui.close_parking_status, secondary=True)
    data = ui.protocols.parking_snapshot()
    link = 'Connected' if data['connected'] else 'Disconnected'
    gate = 'Parked confirmed' if data['parked'] else 'Parked unconfirmed'
    p.text((24, 113), f'HondaLink: {link}  ·  {gate}', 16, fill='#efedf6')
    if data['brake_only']:
        p.text((696, 115), 'Using parking brake only', 13, anchor='rt')

    def row(index, label, identifier, source, value, age, raw, max_age=SPEED_MAX_AGE):
        y = 144 + index * 36
        p.text((24, y + 5), label, 16, fill='#efedf6')
        p.text((228, y), identifier, 14)
        p.text((228, y + 16), p.fit(source, 296, 12), 12, fill='#93929e')
        if age is None:
            reading = 'No data'
        elif not 0 <= age < max_age:
            reading = f'{value} · Stale'
        else:
            reading = f'{value} · {age:.1f}s'
        p.text((696, y), reading, 15, anchor='rt', fill='#efedf6')
        if raw:
            p.text((696, y + 16), raw, 12, anchor='rt', fill='#93929e')
        p.draw.line((24, y + 33, 696, y + 33), fill='#39333f')

    signals = {signal['api_id']: signal for signal in data['can_signals']}
    for index, (api_id, (label, states)) in enumerate(PARKING_LABELS.items()):
        signal = signals[api_id]
        sources = [signal['source']] if signal['received'] else signal['sources']
        source = ' / '.join(f"{s['signal']} 0x{int(s['message_id_hex'], 16):X}"
                            for s in sources)
        value = signal['value']
        if value is not None:
            value = f'{value:g} km/h' if states is None else states[value]
        row(index if index == 0 else index + 1, label, f"{signal['name']} · {api_id}",
            source, value, signal.get('age_seconds'), signal.get('data'))
    brake = 'Engaged' if data['radio_brake'] else 'Released'
    flags = data['radio_flags']
    row(1, 'Radio parking brake', 'General 0x61 / 0x10', 'Status byte bit 4 (0x10)',
        brake, data['radio_age'], f'0x{flags:02X}' if flags is not None else None, SETUP_BRAKE_MAX_AGE)
    present(ui, p)


def system(ui):
    p=page_for(ui,'Diagnostics',ui.system_settings)
    p.button((556,64,696,108),'Shut down',ui.shutdown_page,size=18,secondary=True)
    system,revision,report=ui.diagnostics.snapshot();ui.diagnostic_revision=revision
    runtime=ui.diagnostic_runtime()
    for i,title in enumerate(('Connections','System')):
        x=24+i*344
        p.button((x,112,x+328,156),title,lambda i=i:ui.diagnostic_tab(i),selected=i==ui.diagnostic_page)
    if ui.diagnostic_page==0:
        session=runtime['session'];display=runtime['display'];audio=runtime['audio']
        rows=[('HondaLink','Connected' if session.get('connected') else 'Disconnected'),
              ('Handshake','Verified' if session.get('authenticated') else 'Not verified'),
              ('Display',f"{display['width']} × {display['height']} · {display['backend']}"),
              ('USB dongle',str(len(system['dongles']))+' detected' if 'dongles' in system else 'Checking…'),
              ('Audio',f"{audio['route'].upper()} · {audio['streams']} streams"),
              ('Running apps',', '.join(runtime['plugins']) or 'None')]
    else:
        temp=system.get('temperature_c');uptime=system.get('uptime_seconds')
        total=system.get('memory_total');available=system.get('memory_available');free=system.get('storage_free')
        rows=[('Hardware',system.get('model','Checking…')),
              ('CPU temperature',f'{temp:.1f} °C' if temp is not None else 'Unavailable'),
              ('Power / throttling',power_status(system.get('power_flags'))),
              ('Memory',f'{(total-available)/1024**2:.0f} / {total/1024**2:.0f} MB used' if total is not None and available is not None else 'Unavailable'),
              ('Storage',f'{free/1024**3:.1f} GB free' if free is not None else 'Unavailable'),
              ('Uptime',f'{int(uptime)//3600}h {int(uptime)%3600//60}m' if uptime is not None else 'Unavailable')]
    for i,row in enumerate(rows):p.info(176+i*34,*row)
    p.button((24,404,224,448),'Save report',lambda:ui.diagnostics.save_report(ui.diagnostic_runtime()),size=18)
    p.button((240,404,440,448),'HondaLink',ui.protocol_tests,size=18)
    p.button((456,404,696,448),'Hardware tests',ui.debug_tools,size=18)
    p.notice(report,460)
    present(ui,p)


def protocols(ui):
    p=page_for(ui,'HondaLink diagnostics',ui.system_diagnostics)
    s=ui.protocols.snapshot()
    for i,title in enumerate(('Connection','Vehicle data','Calls / mic','Traffic','Integration')):
        x=24+i*136
        p.button((x,112,x+128,156),title,lambda i=i:ui.protocol_tab(i),selected=i==ui.protocol_page,size=16)
    if ui.protocol_page==0:
        rows=[('HondaLink','Connected' if s['connected'] else 'Waiting for radio'),
              ('Authentication','Verified' if ui.host.session.get('authenticated') else 'Waiting'),
              ('Track channel',ui.inputs.control_status.get('avrcp','Waiting')),
              ('Phone / voice',ui.inputs.control_status.get('hfp','Waiting')),
              ('App sessions',str(len(s['sessions']))+' acknowledged')]
        for i,row in enumerate(rows):p.info(176+i*34,*row)
    elif ui.protocol_page==1:
        from .vehicle_data import draw
        draw(ui,p,s)
        present(ui,p)
        return
    elif ui.protocol_page==2:
        voice=getattr(ui.host,'voice',None);fields=voice.current if voice else {}
        mic=dict(s['mic'])
        if ui.audio.capture:mic.update(ui.audio.capture.snapshot())
        level=mic.get('dbfs');status=mic.get('status','Start Siri or a call to test')
        if isinstance(level,(int,float)):status+=f' ({level:.0f} dBFS)'
        rows=[('Call audio','Active' if fields.get('call_audio') else 'Idle'),
              ('Siri / voice','Active' if fields.get('siri') else 'Idle'),('Radio microphone',status),
              ('Microphone data',f"HFP {mic.get('bytes',0)} B / USB {mic.get('mic_usb_bytes',0)} B")]
        for i,row in enumerate(rows):p.info(176+i*34,*row)
        p.text((24,320),'Voice output',16)
        p.button((252,312,696,356),'Hands-free' if ui.voice_audio.output=='sco' else 'HDMI',ui.toggle_voice_output,size=18)
    elif ui.protocol_page==4:
        from .integration import draw
        draw(ui,p,s)
        present(ui,p)
        return
    else:
        for i,line in enumerate(s['recent'][:7]):p.text((24,176+i*24),p.fit(line,672,15),15)
    p.text((24,366),p.fit(f"{s['status']} · {s['saved']} saved · {s['dropped']} dropped",672,14),14)
    if s['last_marker']:p.text((24,386),p.fit('Marked: '+s['last_marker'],672,13),13)
    p.button((24,412,240,456),'Stop recording' if s['recording'] else 'Start recording',ui.toggle_protocol_capture,size=18)
    p.button((252,412,456,456),'Mark test step',ui.mark_protocol_step,size=18)
    p.button((468,412,696,456),'Test Siri' if ui.protocol_page==2 else 'Hardware tests',
             (lambda:ui.test_radio_button('voice_assistant')) if ui.protocol_page==2 else ui.debug_tools,size=18)
    present(ui,p)


def hardware(ui):
    kind=ui.mode.removeprefix('debug_')
    p=page_for(ui,{'menu':'Hardware tests','audio':'Audio test','colors':'Video colors','inputs':'Radio buttons','volume':'Radio volume'}.get(kind,kind),
               ui.system_diagnostics if kind=='menu' else ui.debug_tools)
    if kind=='menu':
        draw_rows(ui,p,[Row(title,lambda target=target:ui.debug_tools(target)) for title,target in
                        (('Audio','audio'),('Video colors','colors'),('Radio buttons','inputs'),('Radio volume (experimental)','volume'))]+[
                            Row('HondaLink vehicle data',lambda:(ui.protocol_tab(1),ui.protocol_tests()))])
    elif kind=='audio':
        p.text((24,128),'Play a one-second tone through HDMI',19)
        for i,label in enumerate(('Left','Right','Stereo')):
            x=24+i*228;p.button((x,184,x+216,244),label,lambda label=label:ui.tone_test.start(label),size=23)
        p.button((24,280,240,324),'Stop',ui.tone_test.stop,secondary=True,size=22)
        p.notice(ui.tone_test.error or ('Playing '+ui.tone_test.channel if ui.tone_test.until else 'Ready'),360)
    elif kind=='volume':
        p.text((24,128),'Native radio volume · experimental',23)
        p.text((24,170),'One press and release per tap. No automatic repeats.',17)
        p.text((24,200),'Watch the radio volume display to confirm a change.',17)
        p.button((24,248,352,320),'Volume down',lambda:ui.inputs.request_volume('down'),size=24)
        p.button((368,248,696,320),'Volume up',lambda:ui.inputs.request_volume('up'),size=24)
        p.text((24,350),p.fit(ui.inputs.volume_status,672,18),18)
        p.text((24,394),'Sends Bluetooth volume keys to the head unit.',16)
        p.text((24,422),'Radio support and HDMI-source behavior are unverified.',16)
    elif kind=='colors':
        for i,color in enumerate(('#ffffff','#ffff00','#00ffff','#00ff00','#ff00ff','#ff0000','#0000ff','#000000')):
            p.draw.rectangle((24+i*84,120,107+i*84,272),fill=color)
        for y,values in ((304,(0,4,8,12,16,20,24,32)),(388,(223,231,239,243,247,251,253,255))):
            for i,value in enumerate(values):
                p.draw.rectangle((24+i*84,y,107+i*84,y+36),fill=(value,)*3)
                p.text((66+i*84,y+44),value,13,anchor='mt',fill='white')
    elif kind=='inputs':
        index=getattr(ui,'debug_input_page',0)
        for i,title in enumerate(('Buttons','Transport')):
            x=24+i*344;p.button((x,112,x+328,156),title,lambda i=i:ui.input_tab(i),selected=i==index)
        if index==0:
            now=time.monotonic()
            for i,(name,label) in enumerate(LABELS.items()):
                keys=('play_pause','play','pause','stop') if name=='play_pause' else ('answer','dial','redial') if name=='answer' else (name,)
                states=[ui.inputs.buttons[key] for key in keys];state=max(states,key=lambda v:v['at'])
                count=sum(v['count'] for v in states);recent=count and now-state['at']<.7
                x=24+i%3*228;y=168+i//3*136;p.panel((x,y,x+216,y+128))
                p.label((x+12,y+8),'Dial / answer' if name=='answer' else label,20)
                p.text((x+12,y+36),('Held' if state['held'] else 'Received' if recent else 'Waiting')+f' · RX {count}',14)
                result=max((getattr(ui.host,'button_results',{}).get(key,{}) for key in keys),key=lambda v:v.get('sequence',0))
                p.text((x+12,y+58),p.fit(result.get('result','No command yet'),192,12),12)
                p.button((x+8,y+80,x+208,y+124),'Test '+label,lambda name=name:ui.test_radio_button(name),size=16)
            p.text((24,452),'RX counts radio inputs · Test sends a command to the phone',14)
        else:
            p.info(176,'Track controls',ui.inputs.control_status.get('avrcp','Starting'))
            p.info(212,'Phone / voice',ui.inputs.control_status.get('hfp','Starting'))
            for i,(source,label) in enumerate((('avrcp','Track RX'),('hfp','Phone RX'),('hondalink','HondaLink RX'))):
                traffic=ui.inputs.traffic[source];p.text((24,264+i*48),label+f": {traffic['count']}",17)
                p.text((24,288+i*48),p.fit(traffic['summary'],672,14),14)
            if ui.inputs.steering_mode is not None:p.text((24,428),f'Steering mode: {ui.inputs.steering_mode}',14)
            if ui.inputs.history:
                last=ui.inputs.history[0];p.text((24,452),p.fit(f"Last: {last['button']} / {last['source']}",672,14),14)
    present(ui,p,dither=kind!='colors')
