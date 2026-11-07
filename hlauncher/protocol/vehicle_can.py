"""HondaLink receive subscriptions, never CAN transmit commands.

Wire layout: stock Communication.exe 169388/16929c (settings), 164d9c
(records). Signal layouts: opendbc _honda_common.dbc; validate against the
actual car before using these observations outside diagnostics.
"""
import time

HONDALINK = 'jp.co.honda.rd.dispaudio.app.hondalink'
GENERAL = 'jp.co.honda.rd.dispaudio.app.generals'
# Explicit masks expose only the requested fields. Temperature layout follows
# rusEFI can_dash_honda.cpp (Honda K dashboard) and the 2015 Civic Si report.
# Newer opendbc calls 0x324 CRUISE: these are generation-specific mappings.
SUBSCRIPTIONS = ((0x17c, bytes.fromhex('0000ffff00000000')),
                 (0x324, bytes.fromhex('ffff000000000000')))


def subscription_payload():
    # Settings, cyclic, cycle=500, category=1, one settings fragment.
    # Each group starts with CAN type=2 (stock preset class=1) and record
    # count. Count zero selects a preset group; nonzero selects explicit IDs.
    data = bytearray.fromhex('020101f40101')
    data.extend((2, len(SUBSCRIPTIONS)))
    for can_id, mask in SUBSCRIPTIONS:
        data.extend(can_id.to_bytes(4, 'big'))
        data.extend((8, len(mask)))
        data.extend(mask)
    return bytes(data)


def decode_records(payload):
    """Return validated plaintext stock-class-1 records; no partial readings."""
    if len(payload) < 17 or payload[:2] != b'\x00\x02':
        raise ValueError('Invalid CAN data header')
    if payload[11] != 1:
        raise ValueError('Unsupported CAN bus type')
    # Size includes the count word and the records, not the preceding header.
    size = int.from_bytes(payload[12:15], 'big')
    count = int.from_bytes(payload[15:17], 'big')
    if size != len(payload)-15 or count > 128:
        raise ValueError('Invalid CAN data size/count')
    records = []
    offset = 17
    for _ in range(count):
        if offset+5 > len(payload):
            raise ValueError('Truncated CAN record')
        can_id = int.from_bytes(payload[offset:offset+4], 'big')
        dlc = payload[offset+4]
        offset += 5
        if can_id > 0x7ff or dlc > 8 or offset+dlc > len(payload):
            raise ValueError('Invalid CAN ID/DLC')
        raw = payload[offset:offset+dlc]
        offset += dlc
        fields = {}
        if dlc == 8:
            if can_id == 0x17c:
                fields['engine_rpm'] = int.from_bytes(raw[2:4], 'big')
            elif can_id == 0x324:
                fields['coolant_temperature_c'] = raw[0] - 40
                fields['intake_temperature_c'] = raw[1] - 40
        records.append(dict(can_id=can_id, dlc=dlc, data=raw.hex(), fields=fields))
    if offset != len(payload):
        raise ValueError('Trailing CAN record data')
    return records


class VehicleSubscription:
    """One bounded request per Honda application connection, no retry flood."""
    def __init__(self):
        self.requests = {}

    def clear(self, session=None):
        if session is None:
            self.requests.clear()
        else:
            self.requests.pop(session, None)

    def request(self, sid, send, events, replies, now=None, protocol=None):
        if sid in self.requests:
            return
        self.requests[sid] = dict(at=time.monotonic() if now is None else now,
                                  status='pending', protocol=protocol, transport_status='pending')
        send(sid, 0xc2, subscription_payload(), events, replies,
             'honda_can_subscription_queued')
        events[-1].update(can_ids=[x[0] for x in SUBSCRIPTIONS], cycle=500,
                          receive_only=True, status='pending', protocol=protocol,
                          authorization_session=sid, transport_status='pending')
        self.requests[sid]['transaction'] = events[-1]['transaction']

    def transport_ack(self, transaction, status, command):
        if command != 0x43:
            return []
        for sid, request in self.requests.items():
            if request.get('transaction') != transaction or request.get('transport_ack'):
                continue
            request['transport_ack'] = True
            request['transport_status'] = 'acknowledged' if status == 0 else 'rejected'
            return [dict(state='honda_can_subscription_transport_ack', session=sid,
                         protocol=request['protocol'], transaction=transaction,
                         transport_status=request['transport_status'], transport_code=status,
                         status=request['status'], settings_accepted=request['status']=='accepted')]
        return []

    def observe(self, sid, message, payload, events):
        request = self.requests.get(sid)
        if message != 0xc1:
            return
        candidate = payload[:1] in (b'\x01', b'\x02') or payload[:2] == b'\x00\x02'
        if request is None:
            if candidate:
                events.append(dict(state='honda_can_unrequested', session=sid,
                                   bytes=len(payload), preview=payload[:64].hex()))
            return
        if len(payload) == 3 and payload[0] == 2:
            # 16589c: subtype, send type (0/1), result + 0x40 (+0x80 flag).
            code = (payload[2]-0x40) & 0x7f
            valid = payload[1] in (0, 1) and bool(payload[2] & 0x40)
            request['status'] = 'accepted' if valid and code == 0 else 'rejected' if valid else 'unrecognized'
            events.append(dict(state='honda_can_subscription_response', session=sid,
                               status=request['status'], result_code=code,
                               response_flag=bool(payload[2]&0x80), payload=payload.hex()))
        elif payload[:2] == b'\x00\x02':
            try:
                records = decode_records(payload)
            except ValueError as exc:
                events.append(dict(state='honda_can_data_invalid', session=sid,
                                   error=str(exc), payload=payload.hex()))
                return
            request['received'] = True
            events.append(dict(state='honda_can_data', session=sid, sequence=payload[2],
                               header=payload[3:11].hex(), records=records,
                               protocol=request['protocol'],
                               settings_status=request['status'],
                               transport_status=request['transport_status']))
        elif payload[:1] == b'\x01':
            events.append(dict(state='honda_can_data_encrypted', session=sid,
                               bytes=len(payload)))

    def tick(self, now=None):
        now = time.monotonic() if now is None else now
        events = []
        for sid, request in self.requests.items():
            if now-request['at'] >= 10 and not request.get('timeout_reported') and not request.get('received'):
                request['timeout_reported'] = True
                phase = ('accepted_no_data' if request['status']=='accepted' else
                         'settings_rejected' if request['status']=='rejected' else
                         'transport_rejected' if request['transport_status']=='rejected' else
                         'no_settings_response' if request['transport_status']=='acknowledged' else
                         'no_transport_ack')
                events.append(dict(state='honda_can_subscription_timeout', session=sid,
                                   status=request['status'], seconds=10,
                                   reason='No CAN data received', retry=False, phase=phase,
                                   protocol=request['protocol'], transaction=request['transaction'],
                                   transport_status=request['transport_status']))
        return events
