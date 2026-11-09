"""Read-only observations of Honda CommonLink traffic; no vehicle commands."""
import hashlib
import time


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

    def clear(self, session=None):
        if session is None:
            self.previous.clear()
            self.status = {}
            self.readings.clear()
            self.subscription.clear()
        else:
            self.previous = {k:v for k,v in self.previous.items() if k[0] != session}
            if self.status.get('session') == session:
                self.status = {}
            self.readings = {k:v for k,v in self.readings.items() if v['session'] != session}
            if self.subscription.get('session') == session:
                self.subscription.clear()

    def observe_can(self, event):
        state = event.get('state')
        if state == 'honda_can_authorization' and not event.get('authorized'):
            self.clear(event.get('session'))
        if state in ('honda_can_subscription_queued', 'honda_can_subscription_response',
                     'honda_can_subscription_transport_ack', 'honda_can_subscription_timeout'):
            self.subscription.update({k:v for k,v in event.items()
                                      if k in ('session','status','result_code','reason','can_ids','cycle','protocol',
                                               'transaction','transport_status','phase')})
            if state == 'honda_can_subscription_queued':
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
            self.subscription.update(session=event['session'],status='Receiving')
            for record in event['records']:
                for name, value in record['fields'].items():
                    self.readings[name] = dict(value=value, session=event['session'],
                        can_id=record['can_id'], data=record['data'],
                        at=event.get('monotonic', time.monotonic()),
                        mapping='honda_generation_candidate')

    def snapshot_readings(self, now=None):
        now = time.monotonic() if now is None else now
        return {k:dict(v, age_seconds=max(0, now-v['at']), stale=now-v['at']>5)
                for k,v in self.readings.items()}

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
        protocol = event.get('protocol')
        name = protocol[1] if isinstance(protocol,(list,tuple)) and len(protocol)==2 else None
        if message == 0x61 and name == 'jp.co.honda.rd.dispaudio.app.generals':
            fields = radio_status(raw)
            if fields:
                self.status = dict(session=key[0], **fields)
                result.append(dict(state='honda_radio_status', **self.status,
                                   physical_meaning='parking_brake_test_mapping', source_sequence=event.get('capture_sequence')))
        return result
