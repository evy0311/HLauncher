"""Read-only vehicle API definitions recovered from the legacy HondaLink SDK.

Names containing REQUEST/RESET denote observed CAN flags, never operations.
Only the subscription builder in vehicle_can.py emits protocol requests.
"""
import json
from pathlib import Path

DATA = json.loads(Path(__file__).with_name('vehicle_signals.json').read_text())
SIGNALS = tuple(DATA['signals'])
BY_ID = {s['api_id']: s for s in SIGNALS}
MESSAGES = {m['id']: m for m in DATA['messages']}
SUBSCRIPTIONS = tuple(DATA['subscriptions'])
SESSION_PREFIX = bytes.fromhex(DATA['session_prefix'])
# Internal IDs are separate from the original 168-entry vehicle API.
EXTRA_SIGNALS = []
for ident,name,mid,signal,bits,shift,factor,offset,kind in (
    (1001,'ENGINE_OIL_TEMPERATURE_RAW',0x320,'ENG_OIL_TEMP',8,32,1,0,'INT32'),
    (1002,'INTAKE_AIR_TEMPERATURE',0x324,'ENG_INTAKE_AIR_TEMP',8,48,1,-40,'INT32'),
    (1003,'VTEC_STATUS',0x320,'ENG_VTEC_STATUS',1,54,1,0,'BOOLEAN'),
    (1004,'ENGINE_OIL_LIFE_YEAR_RAW',0x454,'ENG_OIL_LIFE_YEAR',4,40,1,0,'INT32'),
    (1005,'ENGINE_OIL_LIFE_DISTANCE_RAW',0x454,'ENG_OIL_LIFE_DISTANCE',16,24,1,0,'INT32'),
    (1006,'MAINTENANCE_RESULT_RAW',0x12f96750,'C_MAINT_RESULT',2,36,1,0,'INT32'),
    (1007,'MAINTENANCE_DISPLAY_CONDITION_RAW',0x12f96750,'C_I_DISPLAY_CONDITION_MAINT',4,20,1,0,'INT32'),
    (1008,'MAINTENANCE_VEHICLE_CONDITION_RAW',0x12f96750,'C_I_CAR_CONDITION_MAINT',1,19,1,0,'BOOLEAN'),
    (1009,'CLUSTER_ODOMETER_RAW',0x12f95f50,'C_DISPLAY_ODO',20,0,1,0,'INT32'),
    *((1010+i, f'MAINTENANCE_ITEM_{item}_APPLIED', 0x12f96750, f'C_MAINT_ITEM_{item}_APPLIED',
       1, 11-i, 1, 0, 'BOOLEAN') for i, item in enumerate('AB0123456789'))):
    m=MESSAGES[mid]
    info=dict(api_id=ident,name=name,value_type=kind,source_type='SIGNAL',sources=[dict(
        message_id=mid,message_id_hex=f'0x{mid:08X}',bus=m['canType'],message_name=m['name'],
        length=m['size'],variable_length=m['sizeVariable'],signal=signal,bits=bits,
        trailing_offset=shift,signed=False,factor=factor,offset=offset)])
    EXTRA_SIGNALS.append(info);BY_ID[ident]=info
BY_MESSAGE = {}
for info in (*SIGNALS,*EXTRA_SIGNALS):
    for source in info['sources']:
        BY_MESSAGE.setdefault(source['message_id'], []).append((info, source))

# Only annotate units established by the corresponding native field/layout.
# Unannotated values retain their SDK conversion and display as native units.
UNITS = {40:'°C', 44:'rpm', 113:'°', 132:'cycles', 152:'km/h', 167:'%', 1002:'°C'}
LABELS = {40:'Coolant temperature', 44:'Engine RPM', 152:'Vehicle speed',
          167:'Accelerator pedal position'}
ALIASES = {40:'coolant_temperature_c', 44:'engine_rpm'}


def label(info):
    return LABELS.get(info['api_id'], info['name'].replace('_', ' ').capitalize())


def decode_value(info, source, raw):
    if 'signal' in source:
        # The SDK preserves leading bytes on variable-length signal packs.
        raw = raw[:source['length']].ljust(source['length'], b'\0')
        value = (int.from_bytes(raw, 'big') >> source['trailing_offset']) & ((1 << source['bits'])-1)
        if source['signed'] and value & (1 << (source['bits']-1)):
            value -= 1 << source['bits']
        value = value * source['factor'] + source['offset']
    else:
        value = int.from_bytes(raw, 'big')
    if info['value_type'] == 'BOOLEAN':
        return bool(value)
    if info['value_type'] == 'INT32':
        value = int(value) & 0xffffffff
        return value - (1 << 32) if value & 0x80000000 else value
    return value


def field_present(source, byte_count):
    # Omitted trailing bytes are unknown, including Minder flags and mileage.
    # Padding them would turn a partial record into a false zero/False reading.
    if 'signal' not in source:
        return byte_count >= source['length']
    return byte_count * 8 >= source['length'] * 8 - source['trailing_offset']


def record_signals(mid, raw, api_ids=None):
    return {str(info['api_id']): decode_value(info, source, raw)
            for info, source in BY_MESSAGE.get(mid, ())
            if ((api_ids is None and info['api_id'] <= 168) or (api_ids is not None and info['api_id'] in api_ids))
            and field_present(source, len(raw))}


GAUGE_API_IDS = (44,40,167,1002,12,1003)


def signal_subscriptions(api_ids):
    masks={}
    for ident in api_ids:
        for source in BY_ID[ident]['sources']:
            mid=source['message_id']
            masks[mid]=masks.get(mid,0)|(((1<<source['bits'])-1)<<source['trailing_offset'])
    return tuple(dict(message_id=mid,can_type={'B-CAN':0,'F-CAN':1,'OTHER':2}[MESSAGES[mid]['canType']],
                      length=MESSAGES[mid]['size'],mask=mask.to_bytes(MESSAGES[mid]['size'],'big').hex())
                 for mid,mask in sorted(masks.items()))


def gauge_subscriptions():
    return signal_subscriptions(GAUGE_API_IDS)


class SignalCache:
    """Cache normal-data records; keep source priority and the SDK's 30s rule."""
    def __init__(self):
        self.records = {}

    def update(self, records, at, session):
        for record in records:
            mid = record['can_id']
            if mid not in BY_MESSAGE:
                continue
            old = self.records.get(mid)
            self.records[mid] = dict(at=at, session=session, data=record['data'],
                api_ids=record.get('api_ids'),
                samples=(old['samples'] if old else 0)+1,
                changes=(old['changes'] if old else 0)+int(old is not None and old['data'] != record['data']),
                interval_seconds=max(0, at-old['at']) if old else None)

    def clear(self, session=None):
        if session is None:self.records.clear()
        else:self.records = {k:v for k,v in self.records.items() if v['session'] != session}

    def snapshot(self, now, api_ids=None):
        result = []
        selected_infos = SIGNALS if api_ids is None else (BY_ID[ident] for ident in sorted(api_ids) if ident in BY_ID)
        for info in selected_infos:
            selected = None
            for source in info['sources']:
                record = self.records.get(source['message_id'])
                if record and info['api_id'] > 168:
                    if record.get('api_ids') is None:
                        continue
                    received_bits = 4 * len(record['data'])
                    missing_bits = 8 * source['length'] - received_bits
                    if source['trailing_offset'] < missing_bits:
                        continue
                if record and record.get('api_ids') is not None and info['api_id'] not in record['api_ids']:continue
                if record and not field_present(source, len(record['data']) // 2):
                    continue
                if record and (selected is None or record['at']-selected[0]['at'] > 30):
                    selected = (record, source)
            row = dict(api_id=info['api_id'], name=info['name'], label=label(info),
                       value_type=info['value_type'], unit=UNITS.get(info['api_id'], ''),
                       sources=info['sources'], received=False, value=None)
            if selected:
                record, source = selected
                age = max(0, now-record['at'])
                row.update(record, received=True, source=source,
                           value=decode_value(info, source, bytes.fromhex(record['data'])),
                           age_seconds=age, stale=age>5)
            result.append(row)
        return result
