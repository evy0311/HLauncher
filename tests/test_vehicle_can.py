"""Exercise firmware-derived subscription wire shapes and bounded RX parsing."""
import importlib.util
import json
from pathlib import Path
import random
import tempfile
import unittest

from hlauncher.protocol.frames import frame
from hlauncher.protocol.session import StartProbe, packet
from hlauncher.protocol.vehicle_can import (GENERAL, HONDALINK, VehicleSubscription,
                                           decode_records, subscription_payload)
from hlauncher.protocol_diagnostics import ProtocolDiagnostics


def incoming(sid, message, payload):
    return packet(b'\x00\x42\x00\x01'+sid.to_bytes(2,'big')+frame(message,payload))


def can_data(records, bus=1):
    data=b''.join(can_id.to_bytes(4,'big')+bytes([len(raw)])+raw for can_id,raw in records)
    return (b'\x00\x02\x03'+bytes.fromhex('0000000100000002')+bytes([bus])+
            (len(data)+2).to_bytes(3,'big')+len(records).to_bytes(2,'big')+data)


class VehicleCAN(unittest.TestCase):
    def probe(self):
        probe=StartProbe(lambda _:True)
        probe.authenticated=True
        probe.active_app='com.honda.hondalink.launcher'
        probe.sessions={257:(1,GENERAL),258:(2,HONDALINK)}
        probe.honda_stage[257]='session_start_notified'
        return probe

    def authenticate(self, probe):
        return probe.feed(incoming(257,0xb1,b'\x01\x01'+bytes(9)+b'KA'))

    def test_explicit_receive_only_subscription_has_two_ids_and_one_fragment(self):
        # 16929c reads fragment count at5. 169388 reads bus/count at6,7,
        # then each big-endian ID, DLC, mask length, mask. No preset groups.
        self.assertEqual(subscription_payload().hex(),
            '020101f4010102020000017c08080000ffff00000000000003240808ffff000000000000')
        probe=self.probe()
        events,replies=self.authenticate(probe)
        request=[e for e in events if e['state']=='honda_can_subscription_queued']
        self.assertEqual(len(request),1)
        self.assertEqual(request[0]['session'],257)
        self.assertEqual(request[0]['can_ids'],[0x17c,0x324])
        self.assertTrue(request[0]['receive_only'])
        self.assertEqual(len(replies),2)  # iAP ACK, followed by settings.
        events,_=self.authenticate(probe)
        self.assertFalse(any(e['state']=='honda_can_subscription_queued' for e in events))

    def test_authentication_session_and_app_are_required_and_order_independent(self):
        for changed in ('authenticated','active_app','stage','session'):
            probe=self.probe()
            if changed=='authenticated':probe.authenticated=False
            elif changed=='active_app':probe.active_app=None
            elif changed=='stage':probe.honda_stage.clear()
            else:probe.sessions.pop(257)
            events,_=self.authenticate(probe)
            self.assertFalse(any(e['state']=='honda_can_subscription_queued' for e in events))
        probe=self.probe();probe.honda_stage[257]='auth_requested'
        self.authenticate(probe)
        events,_=probe.feed(incoming(257,1,bytes.fromhex('001000000000')))
        self.assertEqual(len([e for e in events if e['state']=='honda_can_subscription_queued']),1)

    def test_fragmented_iap_and_commonlink_decode_both_sensors_and_zero(self):
        raw=can_data([(0x17c,bytes.fromhex('0000032000000000')),
                      (0x324,bytes.fromhex('823c000000000000'))])
        for width in range(1,25):
            probe=self.probe();self.authenticate(probe)
            wire=incoming(257,0xc1,raw);events=[]
            for offset in range(0,len(wire),width):events+=probe.feed(wire[offset:offset+width])[0]
            records=[e for e in events if e['state']=='honda_can_data'][0]['records']
            self.assertEqual(records[0]['fields'],dict(engine_rpm=800))
            self.assertEqual(records[1]['fields'],dict(coolant_temperature_c=90,intake_temperature_c=20))
        self.assertEqual(decode_records(can_data([(0x17c,bytes(8))]))[0]['fields']['engine_rpm'],0)
        probe=self.probe();self.authenticate(probe)
        events,_=probe.feed(incoming(258,0xc1,raw))
        self.assertTrue(any(e['state']=='honda_can_unrequested' for e in events))
        self.assertFalse(any(e['state']=='honda_can_data' for e in events))

    def test_response_errors_timeout_and_late_data_are_logged_without_retry(self):
        for raw,status in (('020040','accepted'),('0201c0','accepted'),('020141','rejected'),('020100','unrecognized')):
            probe=self.probe();self.authenticate(probe)
            events,_=probe.feed(incoming(257,0xc1,bytes.fromhex(raw)))
            self.assertEqual([e for e in events if e['state']=='honda_can_subscription_response'][0]['status'],status)
        request=probe.vehicle_subscription.requests[257]
        events=probe.vehicle_subscription.tick(request['at']+11)
        self.assertEqual(events[0]['state'],'honda_can_subscription_timeout')
        self.assertFalse(events[0]['retry'])
        self.assertEqual(probe.vehicle_subscription.tick(request['at']+12),[])
        events,_=probe.feed(incoming(257,0xc1,can_data([(0x324,bytes(8))])))
        self.assertTrue(any(e['state']=='honda_can_data' for e in events))

    def test_reset_and_session_close_rearm_without_duplicate_requests(self):
        probe=self.probe();self.authenticate(probe)
        probe.close_session(257)
        self.assertFalse(probe.vehicle_subscription.requests)
        probe.sessions[257]=(1,GENERAL);probe.honda_stage[257]='session_start_notified'
        self.assertTrue(self.authenticate(probe)[1])
        self.assertTrue(probe.vehicle_subscription.requests)
        probe.feed(packet(bytes.fromhex('00380001')))
        self.assertFalse(probe.vehicle_subscription.requests)
        self.assertFalse(probe.vehicle_auth_sessions)

    def test_auth_is_scoped_and_bootstrap_close_does_not_revoke_owner(self):
        probe=self.probe()
        probe.honda_stage[258]='session_start_notified'
        events,_=self.authenticate(probe)
        self.assertEqual(probe.vehicle_session,257)
        probe.close_session(258)
        self.assertIn(257,probe.vehicle_subscription.requests)
        self.assertIn(257,probe.vehicle_auth_sessions)
        events,_=probe.feed(incoming(257,0xb1,b'\x01\x00'+bytes(9)+b'KA'))
        self.assertFalse(probe.vehicle_subscription.requests)
        self.assertIsNone(probe.vehicle_session)
        self.assertTrue(any(e['state']=='honda_can_authorization' and not e['authorized'] for e in events))

    def test_either_protocol_can_own_subscription_without_fixed_session_ids(self):
        for name in (GENERAL,HONDALINK):
            probe=self.probe();probe.sessions={613:(1,name)}
            probe.honda_stage={613:'session_start_notified'}
            events,_=probe.feed(incoming(613,0xb1,b'\x01\x01'+bytes(9)+b'KA'))
            queued=[e for e in events if e['state']=='honda_can_subscription_queued']
            self.assertEqual([(e['session'],e['authorization_session'],e['protocol']) for e in queued],[(613,613,name)])
            events,_=probe.feed(incoming(613,0xc1,can_data([(0x17c,bytes(8))])))
            self.assertTrue(any(e['state']=='honda_can_data' for e in events))

    def test_second_authenticated_channel_does_not_duplicate_subscription(self):
        probe=self.probe();self.authenticate(probe)
        probe.honda_stage[258]='session_start_notified'
        events,_=probe.feed(incoming(258,0xb1,b'\x01\x01'+bytes(9)+b'KA'))
        self.assertFalse(any(e['state']=='honda_can_subscription_queued' for e in events))
        self.assertEqual(set(probe.vehicle_subscription.requests),{257})

    def test_transport_ack_and_settings_result_are_distinct_and_persisted(self):
        for transport_code,phase in ((0,'no_settings_response'),(1,'transport_rejected')):
            probe=self.probe();events,_=self.authenticate(probe)
            request=probe.vehicle_subscription.requests[257];txn=request['transaction']
            events2,_=probe.feed(packet(b'\x00\x41'+txn.to_bytes(2,'big')+bytes([transport_code,0x43])))
            ack=[e for e in events2 if e['state']=='honda_can_subscription_transport_ack'][0]
            self.assertFalse(ack['settings_accepted'])
            self.assertEqual(ack['transaction'],txn)
            self.assertEqual(probe.vehicle_subscription.tick(request['at']+11)[0]['phase'],phase)
            duplicate,_=probe.feed(packet(b'\x00\x41'+txn.to_bytes(2,'big')+bytes([transport_code,0x43])))
            self.assertFalse(any(e['state']=='honda_can_subscription_transport_ack' for e in duplicate))
            with tempfile.TemporaryDirectory() as folder:
                monitor=ProtocolDiagnostics(folder,min_free=0);monitor.start()
                for event in events+events2:monitor.observe(event)
                self.assertEqual(monitor.snapshot()['vehicle_subscription']['status'],
                    'Awaiting settings reply' if transport_code==0 else 'Transport rejected')
                monitor.close()
                spec=importlib.util.spec_from_file_location('capture_ack',Path(__file__).parents[1]/'scripts/protocol_capture.py')
                module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
                summary=module.summarize(list(Path(folder).glob('*.jsonl')))
                self.assertEqual(summary['can_connections'][0]['session'],257)
                self.assertEqual(summary['can_subscriptions'][-1]['transport_code'],transport_code)
        probe=self.probe();self.authenticate(probe)
        events,_=probe.feed(incoming(257,0xc1,bytes.fromhex('020140')))
        request=probe.vehicle_subscription.requests[257]
        self.assertEqual(probe.vehicle_subscription.tick(request['at']+11)[0]['phase'],'accepted_no_data')

    def test_invalid_packets_never_yield_partial_readings_or_unknown_sensors(self):
        raw=can_data([(0x17c,bytes(8)),(0x324,bytes(8))])
        for malformed in (raw[:-1],raw+b'\x00',raw[:11]+b'\x00'+raw[12:],
                          raw[:15]+b'\xff\xff'+raw[17:]):
            with self.assertRaises(ValueError):decode_records(malformed)
        self.assertEqual(decode_records(can_data([(0x123,bytes(8))]))[0]['fields'],{})
        self.assertEqual(decode_records(can_data([(0x17c,bytes(4))]))[0]['fields'],{})
        rng=random.Random(77)
        for _ in range(500):
            try:decode_records(rng.randbytes(rng.randrange(150)))
            except ValueError:pass
        probe=self.probe();self.authenticate(probe)
        events,_=probe.feed(incoming(257,0xc1,raw[:-1]))
        self.assertTrue(any(e['state']=='honda_can_data_invalid' for e in events))
        self.assertFalse(any(e['state']=='honda_can_data' for e in events))

    def test_samples_refresh_even_unchanged_and_captures_include_requests_and_values(self):
        with tempfile.TemporaryDirectory() as folder:
            monitor=ProtocolDiagnostics(folder,min_free=0);monitor.start()
            probe=self.probe()
            for event in self.authenticate(probe)[0]:monitor.observe(event)
            events,_=probe.feed(incoming(257,0xc1,can_data([(0x17c,bytes(8)),(0x324,bytes.fromhex('823c000000000000'))])))
            for event in events:monitor.observe(event)
            snap=monitor.snapshot()
            self.assertEqual(snap['vehicle_subscription']['status'],'Receiving')
            self.assertEqual(snap['vehicle_readings']['coolant_temperature_c']['value'],90)
            old=monitor.vehicle.readings['engine_rpm']['at']
            self.assertTrue(monitor.vehicle.snapshot_readings(old+6)['engine_rpm']['stale'])
            for event in events:monitor.observe(event)
            self.assertGreater(monitor.vehicle.readings['engine_rpm']['at'],old)
            monitor.observe(dict(state='iap_data_session_closed',session=257))
            self.assertFalse(monitor.snapshot()['vehicle_readings'])
            monitor.close()
            spec=importlib.util.spec_from_file_location('can_capture',Path(__file__).parents[1]/'scripts/protocol_capture.py')
            module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
            summary=module.summarize(list(Path(folder).glob('*.jsonl')))
            self.assertEqual(summary['vehicle_readings']['engine_rpm']['value'],0)
            self.assertEqual(summary['can_subscriptions'][0]['can_ids'],[0x17c,0x324])
            self.assertEqual(summary['can_records']['0x324'],2)


if __name__=='__main__':unittest.main()
