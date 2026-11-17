"""Read-only HondaLink subscriptions: no CAN writes, resets or actuator commands."""
import base64
import hashlib
from itertools import combinations
import time
from .vehicle_signals import SUBSCRIPTIONS, SESSION_PREFIX, MESSAGES, record_signals, ALIASES, GAUGE_API_IDS, EXTRA_SIGNALS, signal_subscriptions
from .aes import decrypt as decrypt_body

HONDALINK = 'jp.co.honda.rd.dispaudio.app.hondalink'
GENERAL = 'jp.co.honda.rd.dispaudio.app.generals'

# Stock Civic Diag.exe reads eight bytes for IMID_AUDIOSW (0x12F95757).
# Keep the raw probe out of the recovered SDK inventory and the gauge feed.
IMID_AUDIO_SWITCH_ID = 0x12F95757
IMID_AUDIO_SWITCH = dict(message_id=IMID_AUDIO_SWITCH_ID, can_type=0,
                         length=8, mask='ffffffffffffffff')
ILLUMINATION_ID = 0x12F85450
ILLUMINATION_API_IDS = (5, 6)
ILLUMINATION_SUBSCRIPTION = next(row for row in SUBSCRIPTIONS if row['message_id'] == ILLUMINATION_ID)
DRIVING_API_IDS = (152,)
SPEED_RETRY_DELAYS = (2, 4)
PARKING_DIAGNOSTIC_API_IDS = (78, 79, 80, 95, 99, 100, 101)
GPS_IDS = (0x99F00003, 0x99F00004)
GPS_SUBSCRIPTIONS = tuple(row for row in SUBSCRIPTIONS if row['message_id'] in GPS_IDS)

SCOPE_GROUPS = (('gauges', GAUGE_API_IDS), ('illumination', ILLUMINATION_API_IDS),
                ('driving', DRIVING_API_IDS), ('gps', ()), ('parking', PARKING_DIAGNOSTIC_API_IDS))
SCOPED_API_IDS = {'off': ()}
for count in range(1, len(SCOPE_GROUPS) + 1):
    for groups in combinations(SCOPE_GROUPS, count):
        SCOPED_API_IDS['_'.join(name for name, _ in groups)] = tuple(
            api for _, ids in groups for api in ids)
SCOPED_API_IDS['vehicle'] = tuple(range(1, 169)) + tuple(row['api_id'] for row in EXTRA_SIGNALS)
SCOPES = (*SCOPED_API_IDS, 'diagnostics')
DIAGNOSTIC_SCOPES = ('diagnostics', 'vehicle')

# Optional CRM snapshot settings recovered from the original native serializer.
# Selectors 3–5 address B-CAN, F-CAN and virtual records within diagnostics.
CRM_CONTEXT = (
    (
        (0x158, 4, '00000000ffff0000'),
        (0x335, 4, 'ffffffff00'),
        (0x454, 4, '00ff000000000000'),
        (0x12f85050, 3, '00ffff000000'),
        (0x12f85150, 3, '000000ff00'),
        (0x12f85351, 3, '000000000000ffc0'),
        (0x12f96750, 3, 'f000000fff000000'),
        (0x99f00006, 5, 'ffffffffffffffff'),
    ),
    (
        (0x158, 4, '00000000ffff0000'),
        (0x1c0, 4, '00000c00000000'),
        (0x320, 4, '0000000000070000'),
        (0x335, 4, 'ffffffff00'),
        (0x35e, 4, '3000000000000000'),
        (0x409, 4, '0000010000'),
        (0x454, 4, '00ff000000000000'),
        (0x12f85050, 3, '00ffff000000'),
        (0x12f85150, 3, '000000ff00'),
        (0x12f85351, 3, '000000000000ffc0'),
        (0x12f96750, 3, 'f000000fff000000'),
        (0x99f00006, 5, 'ffffffffffffffff'),
    ),
)


def diagnostic_subscriptions():
    return (*SUBSCRIPTIONS, IMID_AUDIO_SWITCH)


def subscription_rows(scope):
    if scope == 'diagnostics':
        return diagnostic_subscriptions()
    if scope == 'vehicle':
        rows = {row['message_id']: row for row in SUBSCRIPTIONS}
        for extra in signal_subscriptions(row['api_id'] for row in EXTRA_SIGNALS):
            mid = extra['message_id']
            base = rows.get(mid)
            if base:
                mask = int(base['mask'], 16) | int(extra['mask'], 16)
                extra = dict(extra, mask=mask.to_bytes(extra['length'], 'big').hex())
            rows[mid] = extra
        return tuple(rows[mid] for mid in sorted(rows))
    # Preserve the known full illumination mask, even in mixed subscriptions.
    api_ids = tuple(api for api in SCOPED_API_IDS[scope] if api not in ILLUMINATION_API_IDS)
    rows = signal_subscriptions(api_ids)
    if 'illumination' in scope:
        rows = (*rows, ILLUMINATION_SUBSCRIPTION)
    return (*rows, *GPS_SUBSCRIPTIONS) if 'gps' in scope else rows


def decode_gps_pair(records):
    """Return decimal degrees from a complete HondaLink normal-data batch."""
    pair = {}
    for record in records:
        ident = record['can_id']
        if ident not in GPS_IDS:
            continue
        if ident in pair or record['dlc'] != 4 or len(record['data']) != 8:
            return None
        pair[ident] = int.from_bytes(bytes.fromhex(record['data']), 'big', signed=True)
    if len(pair) != 2:
        return None
    lat, lon = (pair[ident] for ident in GPS_IDS)
    if abs(lat) > 324000000 or abs(lon) > 648000000:
        return None
    return lat / 3600000, lon / 3600000


def subscription_ticks(scope):
    return 1 if 'gauges' in scope or 'driving' in scope else 10


def subscription_payloads(scope='diagnostics'):
    if scope=='off':return (bytes.fromhex('0200000a0100'),)
    rows=subscription_rows(scope)
    normal = serialize_setting(0, ((r['message_id'], r['can_type'], r['mask']) for r in rows))
    ticks = subscription_ticks(scope)
    if scope not in DIAGNOSTIC_SCOPES:
        return (bytes((2, 0, 0, ticks, 1, 1)) + normal,)
    settings = [normal]
    for data_type in (1, 2, 3):
        settings.append(bytes((data_type, 0, 0, 0, 0)))
        if scope == 'vehicle':
            settings.append(serialize_setting(data_type, CRM_CONTEXT[min(data_type-1, 1)]))
    header = bytes((2, 0, 0, ticks, 1, len(settings)))
    # The native serializer sends the normal list and diagnostic settings separately.
    return (header + settings[0], header + b''.join(settings[1:]))


def serialize_setting(data_type, rows):
    rows = tuple(rows)
    result = bytearray((data_type, len(rows)))
    for mid, selector, mask_hex in rows:
        mask = bytes.fromhex(mask_hex)
        result.extend(mid.to_bytes(4, 'big'))
        result.extend((selector, len(mask)))
        result.extend(mask)
    return bytes(result)


def subscription_payload():
    """First payload; live callers must send both subscription_payloads()."""
    return subscription_payloads()[0]


def session_key(seed_ascii, device_info):
    try:
        seed = base64.b64decode(seed_ascii, validate=True)
    except (ValueError, TypeError) as exc:
        raise ValueError('Invalid HondaLink authentication seed') from exc
    if len(seed_ascii) != 8 or not seed or not device_info:
        raise ValueError('Missing HondaLink session identity/seed')
    # Fixed application protocol prefix, not an Apple account credential.
    return hashlib.md5(SESSION_PREFIX+seed+device_info).digest()


def decode_records(payload, key=None, api_ids=None):
    """Validate complete collection before exposing data. key=None is offline only."""
    if len(payload) < 15 or payload[:2] != b'\x00\x02':
        raise ValueError('Invalid CAN data header')
    data_type = payload[11]
    if data_type not in (0, 1, 2, 3):
        raise ValueError('Unsupported CAN data category')
    size = int.from_bytes(payload[12:15], 'big')
    if size != len(payload)-15:
        raise ValueError('Invalid CAN body size')
    body = decrypt_body(payload[15:], key) if key is not None else payload[15:]
    if len(body) < 2:raise ValueError('Missing CAN record count')
    count = int.from_bytes(body[:2], 'big')
    if count > (len(body)-2)//5:raise ValueError('Invalid CAN record count')
    records = []
    offset = 2
    for _ in range(count):
        if offset+5 > len(body):raise ValueError('Truncated CAN record header')
        mid = int.from_bytes(body[offset:offset+4], 'big')
        length = body[offset+4]
        offset += 5
        if offset+length > len(body):raise ValueError('Truncated CAN record data')
        raw = body[offset:offset+length]
        offset += length
        layout = MESSAGES.get(mid)
        values = record_signals(mid, raw, api_ids) if data_type == 0 else {}
        fields = {alias: values[str(api_id)] for api_id, alias in ALIASES.items() if str(api_id) in values}
        imid_switch = data_type == 0 and mid == IMID_AUDIO_SWITCH_ID
        records.append(dict(can_id=mid, can_class=({'B-CAN':0, 'F-CAN':1, 'OTHER':2}[layout['canType']] if layout else 0 if imid_switch else None),
            data_type=data_type, name=layout['name'] if layout else 'IMID_AUDIOSW' if imid_switch else 'Unknown message',
            dlc=length, data=raw.hex(), fields=fields, signals=values,
            api_ids=list(api_ids) if api_ids is not None else None))
    if offset != len(body):raise ValueError('Trailing CAN record data')
    return records


class VehicleSubscription:
    """One bounded subscription per authenticated application connection."""
    def __init__(self):
        self.requests = {}
        self.keys = {}

    def clear(self, session=None):
        if session is None:self.requests.clear();self.keys.clear()
        else:self.requests.pop(session, None);self.keys.pop(session, None)

    def authorize(self, sid, seed, device_info):
        # Native SDK ignores duplicate finish seeds once configured.
        if sid not in self.keys:self.keys[sid] = session_key(seed, device_info)

    def needs_request(self, sid, scope, now):
        if sid not in self.keys:
            return False
        previous = self.requests.get(sid)
        if previous is None:
            return scope != 'off'
        age = now - previous['at']
        if previous['scope'] != scope:
            return age >= .35
        retries = previous['speed_retries']
        return ('driving' in scope and not previous.get('speed_received')
                and retries < len(SPEED_RETRY_DELAYS) and age >= SPEED_RETRY_DELAYS[retries])

    def request(self, sid, send, events, replies, now=None, protocol=None, scope='diagnostics'):
        at=time.monotonic() if now is None else now
        if not self.needs_request(sid, scope, at):
            return
        previous=self.requests.get(sid)
        speed_retries = previous['speed_retries'] + 1 if previous and previous['scope'] == scope else 0
        rows = subscription_rows(scope)
        api_ids = SCOPED_API_IDS.get(scope)
        cycle = subscription_ticks(scope)
        payloads=subscription_payloads(scope)
        request = self.requests[sid] = dict(at=at,scope=scope,api_ids=api_ids,
            previous_api_ids=previous['api_ids'] if previous else None,can_ids={r['message_id'] for r in rows},
            status='pending', protocol=protocol, transport_status='pending', transactions=[], acks={},
            speed_retries=speed_retries)
        for index, payload in enumerate(payloads):
            send(sid, 0xc2, payload, events, replies, 'honda_can_subscription_queued')
            events[-1].update(can_ids=[r['message_id'] for r in rows], cycle=cycle,
                interval_seconds=cycle/10,scope=scope,api_ids=api_ids,
                can_classes=sorted({r['can_type'] for r in rows}),api_count=168 if api_ids is None else len(api_ids),
                settings_count=payloads[0][5],
                part=index+1, parts=len(payloads), receive_only=True, status='pending', protocol=protocol,
                authorization_session=sid, transport_status='pending', speed_retries=speed_retries)
            request['transactions'].append(events[-1]['transaction'])
        request['transaction'] = request['transactions'][0]

    def transport_ack(self, transaction, status, command):
        if command != 0x43:return []
        for sid, request in self.requests.items():
            if transaction not in request['transactions'] or transaction in request['acks']:continue
            request['acks'][transaction] = status
            request['transport_status'] = ('rejected' if any(request['acks'].values()) else
                'acknowledged' if len(request['acks']) == len(request['transactions']) else 'partial')
            return [dict(state='honda_can_subscription_transport_ack', session=sid,
                protocol=request['protocol'], transaction=transaction,
                transport_status=request['transport_status'], transport_code=status,
                status=request['status'], settings_accepted=request['status']=='accepted')]
        return []

    def observe(self, sid, message, payload, events, send=None, replies=None):
        if message != 0xc1:return
        request = self.requests.get(sid)
        candidate = payload[:1] == b'\x02' or payload[:2] == b'\x00\x02'
        if request is None:
            if candidate:events.append(dict(state='honda_can_unrequested', session=sid,
                bytes=len(payload), preview=payload[:64].hex()))
            return
        if len(payload) == 3 and payload[0] == 2:
            request['status'] = 'accepted' if payload[1] == 0 else 'rejected'
            events.append(dict(state='honda_can_subscription_response', session=sid,
                status=request['status'],scope=request['scope'], result_code=payload[1], settings_info=payload[2], payload=payload.hex()))
        elif payload[:2] == b'\x00\x02':
            if request['scope']=='off':return
            try:
                # Never fall back to guessed plaintext on a live session.
                allowed=request['api_ids']
                if request['scope'] in DIAGNOSTIC_SCOPES and request['status']=='pending':
                    allowed=request['previous_api_ids']
                    if request['scope'] == 'vehicle' and allowed is None:
                        # Until the new mask is accepted, decode only original API fields.
                        allowed=range(1, 169)
                records = decode_records(payload, self.keys[sid], allowed)
                if request['scope'] not in DIAGNOSTIC_SCOPES:
                    records=[r for r in records if r['data_type']==0 and r['can_id'] in request['can_ids']]
            except ValueError as exc:
                events.append(dict(state='honda_can_data_invalid', session=sid,
                    error=str(exc), bytes=len(payload), preview=payload[:64].hex()))
                return
            request['received'] = True
            if payload[11] == 0:
                request['normal_received'] = True
                if any(0 <= record['signals'].get('152', -1) <= 400 for record in records):
                    request['speed_received'] = True
            events.append(dict(state='honda_can_data', session=sid, sequence=payload[2], scope=request['scope'],
                data_type=payload[11], vehicle_date=int.from_bytes(payload[3:7],'big'),
                vehicle_time=int.from_bytes(payload[7:11],'big'), header=payload[3:11].hex(),
                records=records, protocol=request['protocol'], settings_status=request['status'],
                transport_status=request['transport_status']))
            # Normal cyclic frames need no application ACK; completed diagnostics do.
            if payload[11] != 0 and send is not None and request['scope'] in DIAGNOSTIC_SCOPES:
                send(sid, 0xc2, bytes((1,payload[2],1)), events, replies, 'honda_can_receipt_sent')

    def tick(self, now=None):
        now = time.monotonic() if now is None else now
        events = []
        for sid, request in self.requests.items():
            if request['scope']=='off':continue
            if now-request['at'] >= 10 and not request.get('timeout_reported') and not request.get('normal_received'):
                request['timeout_reported'] = True
                phase = ('accepted_no_data' if request['status']=='accepted' else
                    'settings_rejected' if request['status']=='rejected' else
                    'transport_rejected' if request['transport_status']=='rejected' else
                    'no_settings_response' if request['transport_status']=='acknowledged' else 'no_transport_ack')
                events.append(dict(state='honda_can_subscription_timeout', session=sid,
                    status=request['status'], seconds=10, reason='No normal CAN data received',
                    retry=False, phase=phase, protocol=request['protocol'],
                    transaction=request['transaction'], transport_status=request['transport_status']))
        return events
