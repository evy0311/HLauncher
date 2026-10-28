"""Android contact ordering and native bridge framing, without a USB phone."""
import importlib.util
import io
from pathlib import Path
import struct
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'sdk'))
spec=importlib.util.spec_from_file_location('aa_input',ROOT/'plugins/android-auto/input.py')
inputs=importlib.util.module_from_spec(spec);spec.loader.exec_module(inputs)

def contact(slot,x=10000,y=20000,action='down'):
    return dict(slot=slot,x_raw=x,y_raw=y,action=action,has_position=True)


class AndroidAuto(unittest.TestCase):
    def test_simultaneous_pinch_and_release_preserve_contact_ids(self):
        router=inputs.TouchRouter()
        events=router.feed({'contacts':[contact(0),contact(1,20000)]})
        self.assertEqual([e['action'] for e in events],[0,5])
        self.assertEqual([p['id'] for p in events[0]['points']],[0])
        self.assertEqual([p['id'] for p in events[1]['points']],[0,1])
        self.assertEqual(events[1]['index'],1)
        events=router.feed({'contacts':[contact(1,25000,action='move')]})
        self.assertEqual(events[0]['action'],6)
        self.assertEqual(events[0]['index'],0)
        events=router.feed({'contacts':[]})
        self.assertEqual(events[0]['action'],1)
        self.assertEqual(events[0]['points'][0]['id'],1)
        self.assertEqual(router.feed({'contacts':[]}),[])

    def test_drag_coordinates_clamped_to_android_video(self):
        router=inputs.TouchRouter()
        router.feed({'contacts':[contact(0)]})
        event=router.feed({'contacts':[contact(0,99999,-5,'move')]})[0]
        self.assertEqual(event['action'],2)
        self.assertEqual(event['points'],[dict(id=0,x=799,y=0)])

    def test_packet_reader_rejects_truncated_or_invalid_packets(self):
        # worker imports its sibling input module; isolate that name for this read.
        old=sys.modules.get('input');sys.modules['input']=inputs
        try:
            spec=importlib.util.spec_from_file_location('aa_worker',ROOT/'plugins/android-auto/worker.py')
            worker=importlib.util.module_from_spec(spec);spec.loader.exec_module(worker)
        finally:
            if old is None:sys.modules.pop('input',None)
            else:sys.modules['input']=old
        data=b'abc'
        self.assertEqual(worker.read_packet(io.BytesIO(struct.pack('!I',4)+b'\x01'+data)),(1,data))
        with self.assertRaises(ValueError):worker.read_packet(io.BytesIO(b'\0\0\0\0'))
        with self.assertRaises(EOFError):worker.read_packet(io.BytesIO(struct.pack('!I',10)+b'\x01a'))
        with self.assertRaises(ValueError):worker.read_packet(io.BytesIO(struct.pack('!I',1)+b'\x09'))
