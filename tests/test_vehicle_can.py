"""Native serializer golden bytes, encrypted stream replay and read-only signals."""
import hashlib
import json
from pathlib import Path
import random
import tempfile
import subprocess
import unittest
from unittest.mock import patch
from hlauncher.protocol.frames import frame
from hlauncher.protocol.session import StartProbe, packet, pi_honda_identity
from hlauncher.protocol.vehicle_can import (GENERAL, GPS_IDS, HONDALINK, ILLUMINATION_ID, IMID_AUDIO_SWITCH_ID, decode_records,
                                            subscription_payloads, session_key)
from hlauncher.protocol.vehicle_signals import SIGNALS, SUBSCRIPTIONS, SignalCache
from hlauncher.protocol_diagnostics import ProtocolDiagnostics

FIXTURE = json.loads((Path(__file__).parent / 'fixtures/hondalink-native-can.json').read_text())
DEVICE=bytes.fromhex('020304050607')
SEED=b'AQIDBAUG'


def incoming(sid, message, payload):
    return packet(b'\x00\x42\x00\x01'+sid.to_bytes(2,'big')+frame(message,payload))


def can_data(records, kind=0, key=None):
    body=len(records).to_bytes(2,'big')+b''.join(mid.to_bytes(4,'big')+bytes([len(raw)])+raw for mid,raw in records)
    if key is not None:
        # Independent OpenSSL command, synthetic test-session keys only.
        body=subprocess.run(['openssl','enc','-aes-128-cbc','-nosalt','-K',key.hex(),'-iv','00'*16],
                            input=body,stdout=subprocess.PIPE,stderr=subprocess.PIPE,check=True).stdout
    return b'\x00\x02\x03'+(20130102).to_bytes(4,'big')+(12345678).to_bytes(4,'big')+bytes([kind])+len(body).to_bytes(3,'big')+body


class VehicleCAN(unittest.TestCase):
    def test_display_probe_requires_session_auth_and_matches_receipt_to_session_and_sequence(self):
        probe = self.probe()
        probe.vehicle_scope = lambda: 'off'
        self.assertFalse(probe.request_display_test('show')[1])
        self.authenticate(probe, flags=0x12)
        events, replies = probe.request_display_test('show')
        self.assertEqual(len(replies), 1)
        self.assertEqual(events[0]['session'], 257)
        payload = bytes.fromhex(events[0]['payload'])
        self.assertEqual(payload, bytes.fromhex('00000104001e') + b'com.honda.hondalink.connect://')
        probe.sessions[258] = (2, HONDALINK)
        for sid, sequence in ((258, 1), (257, 2)):
            events, _ = probe.feed(incoming(sid, 0xC1, bytes((1, sequence, 1))))
            self.assertFalse(any(e['state'] == 'honda_display_test_result' for e in events))
        events, _ = probe.feed(incoming(257, 0xC1, bytes((1, 1, 1))))
        self.assertEqual(next(e['status'] for e in events if e['state'] == 'honda_display_test_result'),
                         'Application receipt')
        events, _ = probe.feed(incoming(257, 0x11, b'\x05'))
        self.assertFalse(any(e['state'] == 'honda_display_status_sent' for e in events))
        probe.feed(incoming(257, 0x53, b'\x01' + payload[6:]))
        events, _ = probe.feed(incoming(257, 0x11, b'\x05'))
        reports = [e['payload'] for e in events if e['state'] == 'honda_display_status_sent']
        self.assertEqual(reports, ['10200000000000', '10600000000000'])
        events, replies = probe.request_display_test('exit')
        self.assertEqual(len(replies), 1)
        self.assertEqual((events[0]['message'], events[0]['payload']), (0xC2, '00010000'))
        events, _ = probe.feed(incoming(257, 0xC1, bytes.fromhex('010001')))
        self.assertFalse(any(e['state'] == 'honda_display_status_sent' for e in events))

    def test_live_gps_requires_a_fresh_complete_pair(self):
        lat, lon = GPS_IDS
        self.assertEqual(subscription_payloads('gps')[0].hex(),
                         '0200000a0101000299f000030204ffffffff99f000040204ffffffff')
        with tempfile.TemporaryDirectory() as folder:
            monitor = ProtocolDiagnostics(folder)
            monitor.observe(dict(state='connected', uuid='test-cafe'))
            def receive(*records):
                raw = [(ident, value.to_bytes(4, 'big', signed=True)) for ident, value in records]
                monitor.observe(dict(state='honda_can_data', session=257, data_type=0,
                                     records=decode_records(can_data(raw))))
            receive((lat, 144000000), (lon, -270000000))
            fix = monitor.projection_gps()
            self.assertEqual((fix['latitude'], fix['longitude']), (40.0, -75.0))
            self.assertTrue(monitor.vehicle.snapshot_gps(fix['at'] + 4)['stale'])
            receive((lat, 144000000))
            receive((lon, -270000000))
            self.assertIsNone(monitor.projection_gps())
            receive((lat, -2147483648), (lon, -270000000))
            self.assertIsNone(monitor.projection_gps())
            receive((lat, 144000000), (lon, -270000000))
            monitor.observe(dict(state='iap_data_session_closed', session=257))
            self.assertIsNone(monitor.projection_gps())
            monitor.close()

    def test_illumination_subscription_follows_lights_regardless_of_dimmer(self):
        probe = self.probe()
        probe.vehicle_scope = lambda: 'illumination'
        events, _ = self.authenticate(probe)
        queued = next(event for event in events if event['state'] == 'honda_can_subscription_queued')
        self.assertEqual(queued['payload'], '0200000a0101000112f854500008c000000000000000')
        diagnostics = ProtocolDiagnostics()
        key = probe.vehicle_subscription.keys[257]
        for raw, expected in ((b'\x00', False), (b'\x40', True), (b'\xc0', True), (b'\x80', False),
                              (bytes.fromhex('d6b68000500a0000'), True),
                              (bytes.fromhex('d6368000b0160000'), True), (b'\x40', True)):
            events, _ = probe.feed(incoming(257, 0xc1, can_data([(ILLUMINATION_ID, raw)], key=key)))
            event = next(event for event in events if event['state'] == 'honda_can_data')
            diagnostics.observe(event)
            self.assertEqual(diagnostics.illumination_night_mode(), expected)

        probe.vehicle_subscription.requests[257]['at'] -= 1
        probe.vehicle_scope = lambda: 'gauges_illumination'
        events, _ = probe.sync_vehicle_scope()
        queued = next(event for event in events if event['state'] == 'honda_can_subscription_queued')
        self.assertIn(ILLUMINATION_ID, queued['can_ids'])
        self.assertIn(0x324, queued['can_ids'])
        diagnostics.observe(queued)
        self.assertTrue(diagnostics.illumination_night_mode())
        self.assertFalse(diagnostics.illumination_night_mode(now=10**12))
        diagnostics.observe(dict(state='iap_data_session_closed', session=257))
        self.assertFalse(diagnostics.illumination_night_mode())

    def test_consumer_scopes_request_only_gauge_bits_and_stop_when_unused(self):
        scope=['off'];p=self.probe();p.vehicle_scope=lambda:scope[0]
        events,_=self.authenticate(p,flags=26)
        self.authenticate(p,flags=18)
        self.assertFalse(p.vehicle_subscription.requests)
        scope[0]='gauges';events,replies=p.sync_vehicle_scope()
        queued=[e for e in events if e['state']=='honda_can_subscription_queued']
        self.assertEqual(len(queued),1)
        self.assertEqual(queued[0]['api_ids'],(44,40,167,1002,12,1003))
        self.assertEqual(queued[0]['can_ids'],[0x17c,0x320,0x324,0x454,0x12f85050,0x12f85150])
        self.assertEqual(queued[0]['interval_seconds'],.1)
        self.assertEqual(queued[0]['payload'],
            '02000001010100060000017c0108ff00ffff00000000'
            '0000032001080040000000000000000003240108ffff000000000000'
            '00000454010800ff00000000000012f85050000600ffff000000'
            '12f851500005000000ff00')
        self.assertEqual(p.sync_vehicle_scope(),([],[]))
        key=p.vehicle_subscription.keys[257]
        raw=can_data([(0x17c,bytes(8)),(0x324,bytes(8)),(0x454,bytes(8)),(0x99f00007,bytes(19))],key=key)
        events,_=p.feed(incoming(257,0xc1,raw))
        data=next(e for e in events if e['state']=='honda_can_data')
        self.assertEqual(len(data['records']),3)
        self.assertEqual({k for r in data['records'] for k in r['signals']},{'40','12','44','167','1002'})
        cache=SignalCache();cache.update(data['records'],100,257)
        self.assertEqual([r['api_id'] for r in cache.snapshot(100)if r['received']],[12,40,44,167])
        p.vehicle_subscription.requests[257]['at']-=1
        scope[0]='diagnostics';events,_=p.sync_vehicle_scope()
        self.assertEqual(len([e for e in events if e['state']=='honda_can_subscription_queued']),2)
        p.vehicle_subscription.requests[257]['at']-=1
        scope[0]='off';events,_=p.sync_vehicle_scope()
        self.assertEqual(events[-1]['payload'],'0200000a0100')
        self.assertEqual(events[-1]['can_ids'],[])
        self.assertEqual(p.sync_vehicle_scope(),([],[]))
        self.assertFalse(any(e['state']=='honda_can_data' for e in p.feed(incoming(257,0xc1,raw))[0]))

    def probe(self, sid=257, name=GENERAL):
        p=StartProbe(lambda _:True);p.authenticated=True;p.active_app='com.honda.hondalink.launcher'
        p.sessions={sid:(1,name)};p.honda_stage[sid]='session_start_notified'
        return p

    def authenticate(self,p,sid=257,flags=8,seed=SEED):
        with patch('hlauncher.protocol.session.pi_honda_device_info',return_value=DEVICE):
            a,b=p.feed(incoming(sid,0xb1,b'\0'))
            c,d=p.feed(incoming(sid,0xb1,b'\1\1'+seed+bytes([flags])+b'US'))
        return a+c,b+d

    def test_full_request_matches_original_arm_serializer_golden(self):
        normal, diagnostic = subscription_payloads()
        self.assertEqual(normal[7],55)
        self.assertEqual(normal[-14:],bytes.fromhex('12f957570008ffffffffffffffff'))
        original=normal[:7]+bytes([54])+normal[8:-14]
        self.assertEqual([hashlib.sha256(x).hexdigest() for x in (original,diagnostic)],
                         FIXTURE['payload_sha256'])
        self.assertEqual([len(x) for x in (normal,diagnostic)],[699,21])
        self.assertEqual(len(SUBSCRIPTIONS),54)
        self.assertEqual([x['api_id'] for x in SIGNALS],list(range(1,169)))
        self.assertEqual(pi_honda_identity(DEVICE)[-6:],bytes.fromhex('0000000000ff'))
        p=self.probe();events,_=self.authenticate(p)
        queued=[e for e in events if e['state']=='honda_can_subscription_queued']
        self.assertEqual(len(queued),2)
        self.assertTrue(all(e['receive_only'] and e['api_count']==168 for e in queued))
        self.assertIn(IMID_AUDIO_SWITCH_ID,queued[0]['can_ids'])
        self.assertEqual([e['part']for e in queued],[1,2])
        self.assertFalse(any(e['state']=='honda_can_subscription_queued'for e in self.authenticate(p)[0]))

    def test_auth_requires_capability_seed_exact_identity_and_session(self):
        for flags,seed in [(0,SEED),(2,SEED),(8,b'!!!!!!!!')]:
            p=self.probe();events,_=self.authenticate(p,flags=flags,seed=seed)
            self.assertFalse(any(e['state']=='honda_can_subscription_queued'for e in events))
        for changed in ('authenticated','active_app','stage','session'):
            p=self.probe()
            if changed=='authenticated':p.authenticated=False
            elif changed=='active_app':p.active_app=None
            elif changed=='stage':p.honda_stage.clear()
            else:p.sessions.clear()
            self.assertFalse(any(e['state']=='honda_can_subscription_queued'for e in self.authenticate(p)[0]))
        p=self.probe();events,_=p.feed(incoming(257,0xb1,b'\1\1'+SEED+b'\x08US'))
        self.assertTrue(any(e['state']=='honda_can_auth_invalid'for e in events))
        self.assertFalse(p.vehicle_subscription.requests)
        for name in (GENERAL,HONDALINK):
            p=self.probe(613,name);self.authenticate(p,613)
            self.assertEqual(set(p.vehicle_subscription.requests),{613})
        p=self.probe();self.authenticate(p);key=p.vehicle_subscription.keys[257]
        self.authenticate(p,flags=18,seed=b'BwgJCgsM')
        self.assertEqual(p.vehicle_subscription.keys[257],key)

    def test_fragmented_encrypted_stream_decodes_synthetic_records_and_unknown_ids(self):
        records = [(int(record['id'], 16), bytes.fromhex(record['data']))
                   for record in FIXTURE['records']]
        raw=can_data(records,key=session_key(SEED,DEVICE))
        for width in (1,2,7,23,1024):
            p=self.probe();self.authenticate(p);wire=incoming(257,0xc1,raw);events=[]
            for at in range(0,len(wire),width):events+=p.feed(wire[at:at+width])[0]
            event=next(e for e in events if e['state']=='honda_can_data')
            self.assertEqual(event['data_type'],0)
            values={k:v for r in event['records']for k,v in r['signals'].items()}
            self.assertEqual(values['40'], 88)
            self.assertEqual(values['132'], 42)
            rpm=next(r for r in event['records']if r['can_id']==0x17c)
            self.assertEqual(rpm['fields']['engine_rpm'], 2450)
            vin=next(r for r in event['records']if r['can_id']==0x99f00007)
            self.assertEqual(vin['dlc'],19)
            self.assertFalse(any(e['state']=='honda_can_receipt_sent'for e in events))
        parsed=decode_records(can_data([(0xf1234567,bytes(255)),(0x17c,bytes(8))]))
        self.assertIsNone(parsed[0]['can_class']);self.assertEqual(parsed[1]['fields']['engine_rpm'],0)

    def test_both_transport_acks_and_settings_result_are_distinct(self):
        p=self.probe();self.authenticate(p);r=p.vehicle_subscription.requests[257]
        for i,txn in enumerate(r['transactions']):
            events,_=p.feed(packet(b'\0\x41'+txn.to_bytes(2,'big')+b'\0\x43'))
            ack=next(e for e in events if e['state']=='honda_can_subscription_transport_ack')
            self.assertEqual(ack['transport_status'],'partial'if i==0 else 'acknowledged')
            self.assertFalse(ack['settings_accepted'])
        for body,expected in [(b'\2\0\xc0','accepted'),(b'\2\0\x12','accepted'),(b'\2\1\xc0','rejected')]:
            events,_=p.feed(incoming(257,0xc1,body))
            self.assertEqual(next(e for e in events if e['state']=='honda_can_subscription_response')['status'],expected)
        self.assertFalse(any(e['state']=='honda_can_subscription_queued'for e in p.tick()))
        self.assertEqual(len(p.vehicle_subscription.tick(r['at']+11)),1)
        self.assertEqual(p.vehicle_subscription.tick(r['at']+12),[])

    def test_diagnostics_acknowledged_and_never_replace_live_readings(self):
        p=self.probe();self.authenticate(p);key=p.vehicle_subscription.keys[257]
        with tempfile.TemporaryDirectory() as folder:
            monitor=ProtocolDiagnostics(folder)
            for kind,rpm in [(0,1000),(1,9000),(2,8000),(3,7000)]:
                events,replies=p.feed(incoming(257,0xc1,can_data([(0x17c,b'\0\0'+rpm.to_bytes(2,'big')+bytes(4))],kind,key)))
                for e in events:monitor.observe(e)
                ack=[e for e in events if e['state']=='honda_can_receipt_sent']
                self.assertEqual(len(ack),int(kind!=0))
                if ack:self.assertEqual(ack[0]['payload'],'010301')
            snap=monitor.snapshot()
            self.assertEqual(snap['vehicle_signals'][43]['value'],1000)
            self.assertEqual(len(snap['vehicle_can_records']),4)
            monitor.close()

    def test_wrong_key_and_malformed_collections_do_not_expose_partial_values(self):
        p=self.probe();self.authenticate(p)
        records=[(0x17c,bytes(8)),(0x324,bytes(8))]
        for raw in (can_data(records),can_data(records,key=bytes(16)),can_data(records,key=p.vehicle_subscription.keys[257])[:-1]):
            events,_=p.feed(incoming(257,0xc1,raw))
            self.assertTrue(any(e['state']=='honda_can_data_invalid'for e in events))
            self.assertFalse(any(e['state']=='honda_can_data'for e in events))
        raw=can_data(records)
        for end in range(len(raw)):
            with self.assertRaises(ValueError):decode_records(raw[:end])
        rng=random.Random(77)
        for _ in range(500):
            try:decode_records(rng.randbytes(rng.randrange(150)))
            except ValueError:pass

    def test_source_priority_scaling_freshness_and_reconnect(self):
        c=SignalCache()
        c.update(decode_records(can_data([(r['message_id'],bytes(r['length']))for r in SUBSCRIPTIONS])),100,257)
        self.assertEqual(sum(r['received']for r in c.snapshot(100)),168)
        c.update(decode_records(can_data([(0x17c,bytes.fromhex('000003e800000000'))])),100,257)
        c.update(decode_records(can_data([(0x12f85050,bytes.fromhex('0007d0000000'))])),130,257)
        self.assertEqual(c.snapshot(130)[43]['value'],1000)
        c.update(decode_records(can_data([(0x12f85050,bytes.fromhex('0007d0000000'))])),131,257)
        self.assertEqual(c.snapshot(131)[43]['value'],2000)
        self.assertTrue(c.snapshot(137)[43]['stale'])
        c.clear(258);self.assertTrue(c.snapshot(137)[43]['received'])
        c.clear(257);self.assertFalse(any(r['received']for r in c.snapshot(137)))
        p=self.probe();self.authenticate(p);p.close_session(257)
        self.assertFalse(p.vehicle_subscription.keys);self.assertFalse(p.vehicle_identities)
        p=self.probe();self.authenticate(p);p.feed(packet(bytes.fromhex('00380001')))
        self.assertFalse(p.vehicle_subscription.keys);self.assertFalse(p.vehicle_auth_sessions)

    def test_capture_contains_all_signal_values_and_refreshes_unchanged_frames(self):
        p=self.probe();events,_=self.authenticate(p)
        with tempfile.TemporaryDirectory() as folder:
            monitor=ProtocolDiagnostics(folder,min_free=0);monitor.start()
            for e in events:monitor.observe(e)
            switch_data=bytes.fromhex('0102030405060708')  # Synthetic; no button mapping.
            wire=incoming(257,0xc1,can_data([(0x324,bytes.fromhex('823c000000000000')),
                                            (IMID_AUDIO_SWITCH_ID,switch_data)],key=p.vehicle_subscription.keys[257]))
            for _ in range(3):
                for e in p.feed(wire)[0]:monitor.observe(e)
            row=monitor.snapshot()['vehicle_signals'][39]
            self.assertEqual((row['value'],row['samples'],row['changes']),(90,3,0))
            monitor.close()
            saved=[json.loads(l)for f in Path(folder).glob('*.jsonl')for l in f.read_text().splitlines()]
            records=next(e for e in saved if e['state']=='honda_can_data')['records']
            self.assertEqual(records[0]['signals']['40'],90)
            self.assertEqual((records[1]['name'],records[1]['can_class'],records[1]['data'],records[1]['signals']),
                             ('IMID_AUDIOSW',0,switch_data.hex(),{}))
            self.assertFalse(any('keys' in e for e in saved))


if __name__=='__main__':unittest.main()
