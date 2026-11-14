"""Plain, read-only HondaLink signal list and live selected-signal inspector."""
from .scroll_list import Row, draw as draw_rows
from ..protocol.vehicle_can import IMID_AUDIO_SWITCH_ID


def value_text(row):
    if not row['received']:return 'Waiting'
    value = row['value']
    text = ('True' if value else 'False') if isinstance(value,bool) else f'{value:.5g}' if isinstance(value,float) else str(value)
    if row['unit']:text += ' '+row['unit']
    return text+(' · stale' if row['stale'] else '')


def draw(ui, p, snapshot):
    rows = snapshot['vehicle_signals']
    sub = snapshot.get('vehicle_subscription',{})
    for index,title in enumerate(('All signals','Selected signal','Raw / status','GPS')):
        x=24+index*170
        p.button((x,164,x+162,200),title,lambda index=index:ui.vehicle_tab(index),
                 selected=ui.vehicle_data_tab==index,size=17)
    received=sum(row['received'] for row in rows)
    fresh=sum(row['received'] and not row['stale'] for row in rows)
    status=f"{received}/168 received · {fresh} fresh · {sub.get('status','Waiting for CAN-capable session')}"
    p.text((24,206),p.fit(status,672,13),13)
    if ui.vehicle_data_tab==0:
        draw_rows(ui,p,[Row(f"{row['api_id']:03d}  {row['label']}",
                           lambda ident=row['api_id']:ui.vehicle_select(ident),value=value_text(row)) for row in rows],
                  top=228,bottom=388,key='vehicle-signals',height=36,step=40,size=17)
    elif ui.vehicle_data_tab==1:
        row=rows[ui.vehicle_signal_id-1]
        p.text((24,230),p.fit(f"{row['api_id']:03d}  {row['label']}",672,21),21,fill='#efedf6')
        p.text((24,258),p.fit(value_text(row),672,26),26,fill='#efedf6')
        if row['received']:
            source=row['source']
            p.text((24,294),p.fit(f"{source['bus']} {source['message_id_hex']} · {row['age_seconds']:.1f}s ago · {row['samples']} RX / {row['changes']} changes",672,14),14)
            p.text((24,316),p.fit('Raw: '+row['data'].upper(),672,14),14)
        else:p.text((24,294),'No value received for this signal. Zero is shown only after data arrives.',14)
        sources=' / '.join(s['message_id_hex'] for s in row['sources'])
        p.text((24,338),p.fit('Sources: '+sources,672,13),13)
        p.text((24,358),'Native scaling applied · '+(row['unit'] or ('Boolean status' if row['value_type']=='BOOLEAN' else 'unit not confirmed')),13)
        p.button((24,376,188,406),'Previous',lambda:ui.vehicle_select(ui.vehicle_signal_id-1),size=15)
        p.button((200,376,364,406),'Next',lambda:ui.vehicle_select(ui.vehicle_signal_id+1),size=15)
        p.text((380,386),p.fit(row['name'],316,12),12)
    elif ui.vehicle_data_tab == 2:
        raw=snapshot.get('vehicle_can_records',[])
        normal=[r for r in raw if r.get('data_type',0)==0]
        diagnostics=[r for r in raw if r.get('data_type',0)!=0]
        switch=next((r for r in normal if r['can_id']==IMID_AUDIO_SWITCH_ID),None)
        switch_status=(f"{switch['data'].upper()} · {switch['samples']} RX / {switch['changes']} changes"
                       if switch else 'Waiting for data')
        lines=[f"{len(sub.get('can_ids',[]))} normal IDs requested · 1-second cycle",
               f"{len(normal)} normal records · {len(diagnostics)} diagnostic records cached",
               f'Steering audio switch 0x12F95757: {switch_status}',
               'Request / reset names are observed flags; no actions are sent.',
               'Record a short capture to save raw bytes and decoded signal values.',
               sub.get('last_error') or 'No CAN decoder error reported']
        for index,line in enumerate(lines):p.text((24,234+index*26),p.fit(line,672,15),15)
    else:
        gps = snapshot.get('vehicle_gps', {})
        fix = gps.get('fix')
        if fix is None:
            p.text((24,245), 'Invalid or incomplete GPS pair' if gps else 'Waiting for car GPS', 23)
        else:
            latitude, longitude = fix
            p.text((24,240), f'Latitude    {latitude:.7f}°', 25)
            p.text((24,280), f'Longitude  {longitude:.7f}°', 25)
            label = 'Stale' if gps['stale'] else 'Live'
            p.text((24,324), f"{label} · received {gps['age_seconds']:.1f}s ago", 17)
    p.button((24,416,240,456),'Stop recording' if snapshot['recording'] else 'Start recording',ui.toggle_protocol_capture,size=17)
    p.button((252,416,456,456),'Mark test step',ui.mark_protocol_step,size=17)
    p.button((468,416,696,456),'Hardware tests',ui.debug_tools,size=17)
    p.text((24,462),p.fit(f"Read-only · {snapshot['status']} · {snapshot['saved']} saved · {snapshot['dropped']} dropped",672,12),12)
