"""Read-only observations of Honda CommonLink traffic; no vehicle commands."""
import hashlib
import time
from .protocol.vehicle_signals import SignalCache, ALIASES
from .protocol.vehicle_can import GPS_IDS, ILLUMINATION_ID, decode_gps_pair


def radio_status(payload):
    # Communication.exe 00196afc builds message 0x61: 0x10, three flags,
    # four zero bytes, zero. Bit 4 is mapped to parking brake from the owner's
    # engaged/released/engaged test; the underlying firmware input is untraced.
    if len(payload) != 7 or payload[0] != 0x10:
        return None
    flags = payload[1]
    return dict(flags=flags, bit0=bool(flags & 1), bit1=bool(flags & 2),
                bit4=bool(flags & 16), unknown_flags=flags & ~0x13,
                trailing_hex=payload[2:].hex(),parking_brake_engaged=bool(flags & 16),
                parking_brake_evidence='in_car_test')


class VehicleTraffic:
    """Bounded per-session change detection, preserving unknown field names."""
    def __init__(self):
        self.previous = {}
        self.status = {}
        self.changes = 0
        self.readings = {}
        self.subscription = {}
        self.can_records = {}
        self.signals = SignalCache()
        self.gps = {}

    def clear(self, session=None):
        self.signals.clear(session)
        if session is None or self.gps.get('session') == session:
            self.gps = {}
        if session is None:
            self.previous.clear()
            self.status = {}
            self.readings.clear()
            self.subscription.clear()
            self.can_records.clear()
        else:
            self.previous = {k:v for k,v in self.previous.items() if k[0] != session}
            if self.status.get('session') == session:
                self.status = {}
            self.readings = {k:v for k,v in self.readings.items() if v['session'] != session}
            self.can_records = {k:v for k,v in self.can_records.items() if v['session'] != session}
            if self.subscription.get('session') == session:
                self.subscription.clear()

    def observe_can(self, event):
        state = event.get('state')
        if state == 'honda_can_authorization' and not event.get('authorized'):
            self.clear(event.get('session'))
        if state in ('honda_can_subscription_queued', 'honda_can_subscription_response',
                     'honda_can_subscription_transport_ack', 'honda_can_subscription_timeout'):
            same_scope = (self.subscription.get('scope') == event.get('scope')
                          and self.subscription.get('session') == event.get('session'))
            self.subscription.update({k:v for k,v in event.items()
                                      if k in ('session','status','result_code','reason','can_ids','cycle','protocol',
                                               'transaction','transport_status','phase','can_classes','interval_seconds','api_count','settings_count')})
            if state == 'honda_can_subscription_queued':
                if event.get('part',1)==1 and not same_scope:
                    if not set(GPS_IDS).issubset(event.get('can_ids', ())):
                        self.gps = {}
                    illumination = self.signals.records.get(ILLUMINATION_ID)
                    self.signals.clear();self.readings.clear();self.can_records.clear()
                    if (illumination and illumination['session'] == event.get('session')
                            and ILLUMINATION_ID in event.get('can_ids', ())):
                        self.signals.records[ILLUMINATION_ID] = illumination
                self.subscription['scope']=event.get('scope','diagnostics')
                self.subscription['status'] = 'Awaiting transport ACK'
            elif state == 'honda_can_subscription_transport_ack' and event.get('status')=='pending':
                self.subscription['status'] = ('Awaiting settings reply' if event.get('transport_status')=='acknowledged'
                                               else 'Transport rejected')
            elif state == 'honda_can_subscription_timeout':
                self.subscription['status'] = {'accepted_no_data':'Accepted; no data',
                    'settings_rejected':'Settings rejected', 'transport_rejected':'Transport rejected',
                    'no_settings_response':'No settings reply', 'no_transport_ack':'No transport ACK'}.get(
                        event.get('phase'), 'No data received')
        elif state == 'honda_can_data':
            normal = event.get('data_type', 0) == 0
            self.subscription.update(session=event['session'])
            if normal and event['records']:
                self.subscription.update(status='Receiving',last_error='')
                self.signals.update(event['records'],event.get('monotonic',time.monotonic()),event['session'])
                if any(record['can_id'] in GPS_IDS for record in event['records']):
                    fix = decode_gps_pair(event['records'])
                    self.gps = dict(session=event['session'], fix=fix,
                                    at=event.get('monotonic', time.monotonic()))
            for record in event['records']:
                can_class = record.get('can_class', event.get('can_class', 1))
                data_type = record.get('data_type', event.get('data_type',0))
                key = (event['session'], data_type, record['can_id'])
                old = self.can_records.get(key)
                if old is not None or len(self.can_records) < 512:
                    at = event.get('monotonic', time.monotonic())
                    self.can_records[key] = dict(session=event['session'], can_class=can_class,
                        can_id=record['can_id'], dlc=record['dlc'], data=record['data'], at=at,
                        data_type=data_type,name=record.get('name',''),
                        samples=(old['samples'] if old else 0)+1,
                        changes=(old['changes'] if old else 0)+int(old is not None and old['data'] != record['data']),
                        interval_seconds=max(0, at-old['at']) if old else None)
            if normal:
                for reading in self.signals.snapshot(event.get('monotonic',time.monotonic()), ALIASES.keys()):
                    alias = ALIASES.get(reading['api_id'])
                    if alias and reading['received']:
                        self.readings[alias] = dict(value=reading['value'],session=reading['session'],
                            can_id=reading['source']['message_id'],data=reading['data'],at=reading['at'],
                            mapping='legacy_hondalink_native_sdk')
        elif state in ('honda_can_data_invalid','honda_can_auth_invalid'):
            self.subscription['last_error'] = event.get('error','Unknown CAN error')

    def snapshot_gps(self, now=None):
        if not self.gps:
            return {}
        now = time.monotonic() if now is None else now
        age = max(0, now - self.gps['at'])
        return dict(self.gps, age_seconds=age, stale=age > 3)

    def snapshot_signals(self, now=None):
        return self.signals.snapshot(time.monotonic() if now is None else now)

    def snapshot_readings(self, now=None):
        now = time.monotonic() if now is None else now
        return {k:dict(v, age_seconds=max(0, now-v['at']), stale=now-v['at']>5)
                for k,v in self.readings.items()}

    def snapshot_can_records(self, now=None):
        now = time.monotonic() if now is None else now
        return [dict(v, age_seconds=max(0, now-v['at']), stale=now-v['at']>5)
                for v in self.can_records.values()]

    def observe(self, event):
        message = event.get('message')
        if message == 0x43:  # Touch has its own decoder and much higher rate.
            return []
        try:
            raw = bytes.fromhex(event['payload'])
        except (KeyError, TypeError, ValueError):
            return []
        key = (event.get('session'), message)
        if key not in self.previous and len(self.previous) >= 512:
            return []
        protocol = event.get('protocol')
        name = protocol[1] if isinstance(protocol, (list, tuple)) and len(protocol) == 2 else None
        fields = radio_status(raw) if message == 0x61 and name == 'jp.co.honda.rd.dispaudio.app.generals' else None
        if fields:
            self.status = dict(session=key[0], at=event.get('monotonic', time.monotonic()), **fields)
        preview = raw[:256]
        digest = hashlib.sha256(raw).digest()
        old = self.previous.get(key)
        if old and old[0] == digest:
            return []
        self.previous[key] = (digest, preview, len(raw))
        self.changes += 1
        before = old[1] if old else b''
        changed = [dict(offset=i, before=before[i] if i < len(before) else None,
                        after=preview[i] if i < len(preview) else None,
                        xor=(before[i] ^ preview[i]) if i < min(len(before),len(preview)) else None)
                   for i in range(max(len(before),len(preview)))
                   if i >= min(len(before),len(preview)) or before[i] != preview[i]]
        result = [dict(state='honda_payload_change', session=key[0], message=message,
                       protocol=event.get('protocol'), first=old is None,
                       length=len(raw), previous_length=old[2] if old else None,
                       preview=preview.hex(), changed_bytes=changed[:64],
                       changed_bytes_truncated=len(changed)>64 or len(raw)>256,
                       source_sequence=event.get('capture_sequence'))]
        if fields:
            result.append(dict(state='honda_radio_status', **self.status,
                               physical_meaning='parking_brake_test_mapping', source_sequence=event.get('capture_sequence')))
        return result
