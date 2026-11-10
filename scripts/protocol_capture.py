#!/usr/bin/env python3
"""Summarize saved HondaLink drive captures without printing phone or audio payloads."""
import argparse
from collections import Counter
import json
from pathlib import Path


def summarize(paths):
    counts=Counter();iap=Counter();frames=Counter();timeline=[];files=[];dropped=0
    mic=dict(samples_received=False,peak=0,radio_bytes=0,usb_bytes=0,usb_errors=0)
    vehicle_readings={};vehicle_ranges={};subscriptions=[];can_records=Counter();can_connections=[];can_activity={}
    signal_readings={};signal_ranges={}
    for path in paths:
        files.append(str(path))
        with path.open(errors='replace') as source:
            for line in source:
                if len(line)>262144:continue
                try:event=json.loads(line)
                except ValueError:continue
                if not isinstance(event,dict):continue
                state=event.get('state','unknown');counts[state]+=1
                if state=='protocol_capture_stats':dropped=max(dropped,event.get('dropped',0))
                if state=='iap_packet':iap[f"{event.get('lingo')}:{event.get('command')}"]+=1
                if state=='honda_frame':frames[f"{event.get('session')}:0x{event.get('message',0):02x}"]+=1
                if state.startswith('honda_can_subscription_') or state in ('honda_can_authorization','honda_can_session_selected'):
                    target=subscriptions if state.startswith('honda_can_subscription_') else can_connections
                    target.append({k:event[k] for k in ('wall','monotonic','state','session','status',
                        'can_ids','can_classes','cycle','result_code','response_flag','reason','payload','protocol',
                        'authorization_session','authorized','result','flags','transaction','transport_status',
                        'transport_code','settings_accepted','phase') if k in event})
                    del target[:-128]
                if state=='honda_can_data':
                    for record in event.get('records',[]):
                        can_records[f"0x{record['can_id']:03x}"]+=1
                        key=f"{record.get('can_class',event.get('can_class',1))}:0x{record['can_id']:03x}"
                        if record.get('data_type',event.get('data_type',0)):
                            key=f"diagnostic{record.get('data_type',event.get('data_type'))}:"+key
                        row=can_activity.setdefault(key,dict(samples=0,changes=0))
                        changed=row['samples']>0 and row['data']!=record['data']
                        row.update(samples=row['samples']+1,changes=row['changes']+int(changed),
                            data=record['data'],dlc=record['dlc'],session=event.get('session'),
                            wall=event.get('wall'),monotonic=event.get('monotonic'))
                        for key,value in record.get('fields',{}).items():
                            bounds=vehicle_ranges.setdefault(key,dict(min=value,max=value,samples=0))
                            bounds.update(min=min(bounds['min'],value),max=max(bounds['max'],value),samples=bounds['samples']+1)
                            vehicle_readings[key]=dict(value=value,wall=event.get('wall'),monotonic=event.get('monotonic'),
                                session=event.get('session'),can_id=record['can_id'],raw=record['data'])
                        for api_id,value in record.get('signals',{}).items():
                            bounds=signal_ranges.setdefault(api_id,dict(min=value,max=value,samples=0))
                            bounds.update(min=min(bounds['min'],value),max=max(bounds['max'],value),samples=bounds['samples']+1)
                            signal_readings[api_id]=dict(value=value,wall=event.get('wall'),session=event.get('session'),
                                can_id=record['can_id'],raw=record['data'])
                if state in ('protocol_marker','projection_voice_state','projection_hfp_tx','projection_voice_output',
                             'audio_capture_open','audio_meter_error','audio_voice_open','audio_voice_error',
                             'audio_capture_stop_requested','audio_capture_closing','audio_capture_bus_closed',
                             'audio_capture_closed','honda_radio_status','protocol_capture_info'):
                    keys=('wall','state','label','plugin','call_audio','siri','recording','summary','output','rate','channels','codec','error','device',
                          'cancelled','session','flags','bit0','bit1','bit4','physical_meaning',
                          'parking_brake_engaged','parking_brake_evidence','boot_id','launcher_pid')
                    timeline.append({key:event[key] for key in keys if key in event})
                    if len(timeline)>256:timeline.pop(0)
                if state=='audio_meter_level':
                    mic['peak']=max(mic['peak'],event.get('peak',0));mic['radio_bytes']=max(mic['radio_bytes'],event.get('bytes',0))
                    mic['samples_received']=mic['radio_bytes']>0
                if state=='projection_mic_stats':
                    mic['usb_bytes']=max(mic['usb_bytes'],event.get('mic_usb_bytes',0))
                    mic['usb_errors']=max(mic['usb_errors'],event.get('mic_usb_errors',0))
    return dict(files=files,capture_dropped_events=dropped,events=dict(counts),iap_commands=dict(iap),honda_messages=dict(frames),
                microphone=mic,timeline=timeline,vehicle_readings=vehicle_readings,
                vehicle_ranges=vehicle_ranges,vehicle_signals=signal_readings,signal_ranges=signal_ranges,
                can_subscriptions=subscriptions,can_connections=can_connections,can_records=dict(can_records),can_activity=can_activity)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('paths',nargs='*',type=Path)
    args=parser.parse_args();paths=args.paths or [Path('/var/lib/hlauncher/protocol-captures')]
    files=[]
    for path in paths:files.extend(sorted(path.glob('protocol-*.jsonl')) if path.is_dir() else [path])
    print(json.dumps(summarize(files),indent=2))


if __name__=='__main__':main()
