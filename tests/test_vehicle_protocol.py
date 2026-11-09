import json
from pathlib import Path
import tempfile
import unittest
from hlauncher.vehicle_protocol import VehicleTraffic, radio_status
from hlauncher.protocol_diagnostics import ProtocolDiagnostics

GENERAL=(1,'jp.co.honda.rd.dispaudio.app.generals')


class VehicleProtocol(unittest.TestCase):
    def test_parking_brake_mapping_tracks_bit4_and_clears_on_disconnect(self):
        monitor=VehicleTraffic()
        frame=dict(state='honda_frame',session=257,message=0x61,protocol=GENERAL,
                   payload='10110000000000')
        first=monitor.observe(frame)
        self.assertEqual(first[-1]['flags'],0x11)
        self.assertEqual(monitor.observe(frame),[])
        changed=monitor.observe(dict(frame,payload='10010000000000'))
        self.assertEqual(changed[0]['changed_bytes'],[dict(offset=1,before=17,after=1,xor=16)])
        self.assertFalse(changed[-1]['bit4'])
        self.assertEqual(changed[-1]['physical_meaning'],'parking_brake_test_mapping')
        self.assertFalse(changed[-1]['parking_brake_engaged'])
        self.assertTrue(first[-1]['parking_brake_engaged'])
        self.assertEqual(first[-1]['parking_brake_evidence'],'in_car_test')
        monitor.clear(257)
        self.assertFalse(monitor.status)
        self.assertTrue(monitor.observe(frame)[0]['first'])

    def test_unknown_shapes_and_other_protocols_are_not_decoded_as_status(self):
        for raw in (b'',bytes.fromhex('101100'),bytes.fromhex('11110000000000')):
            self.assertIsNone(radio_status(raw))
        monitor=VehicleTraffic()
        rows=monitor.observe(dict(message=0x61,session=3,payload='10110000000000',protocol=(2,'other')))
        self.assertEqual(len(rows),1)
        self.assertFalse(monitor.status)
        self.assertEqual(monitor.observe(dict(message=0x43,payload='0001')),[])

    def test_change_tracking_is_bounded_and_session_scoped(self):
        monitor=VehicleTraffic()
        for i in range(1000):
            monitor.observe(dict(session=i,message=0x70,payload='ff'*512))
        self.assertEqual(len(monitor.previous),512)
        rows=monitor.observe(dict(session=0,message=0x70,payload='00'*512))
        self.assertEqual(len(rows[0]['changed_bytes']),64)
        self.assertTrue(rows[0]['changed_bytes_truncated'])
        self.assertEqual(len(rows[0]['preview']),512)

    def test_packet_context_and_changes_are_saved_in_capture(self):
        with tempfile.TemporaryDirectory() as folder:
            monitor=ProtocolDiagnostics(folder,min_free=0)
            monitor.start()
            for payload in ('10110000000000','10010000000000'):
                monitor.observe(dict(state='honda_frame',session=257,message=0x61,
                                     protocol=GENERAL,payload=payload))
            self.assertEqual(monitor.snapshot()['vehicle_status']['flags'],1)
            monitor.close()
            events=[json.loads(l) for p in Path(folder).glob('*.jsonl') for l in p.read_text().splitlines()]
            self.assertEqual(len([e for e in events if e['state']=='honda_radio_status']),2)
            change=[e for e in events if e['state']=='honda_payload_change'][-1]
            self.assertEqual(change['protocol'],list(GENERAL))
            self.assertEqual(change['changed_bytes'][0]['xor'],16)
