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

    def test_live_picture_edit_redraws_retained_frame_without_new_video_packet(self):
        from unittest.mock import Mock,patch
        from types import SimpleNamespace
        old=sys.modules.get('input');sys.modules['input']=inputs
        try:
            spec=importlib.util.spec_from_file_location('aa_live_worker',ROOT/'plugins/android-auto/worker.py')
            worker=importlib.util.module_from_spec(spec);spec.loader.exec_module(worker)
        finally:
            if old is None:sys.modules.pop('input',None)
            else:sys.modules['input']=old
        engine=worker.Engine(SimpleNamespace(width=720,height=480))
        engine.visible.set()
        decoder=SimpleNamespace(decoder=SimpleNamespace(picture=None,redraw=Mock(return_value=b'preview')),close=Mock())
        settings=Mock(values=dict(saturation=85,contrast=95,brightness=0))
        def idle(*args):
            engine.done.set()
            return ([],[],[])
        process=Mock()
        with patch.object(worker,'ENGINE') as path,patch.object(worker.subprocess,'Popen',return_value=process), \
             patch.object(worker.threading,'Thread'),patch.object(worker,'H264StreamDecoder',return_value=decoder), \
             patch.object(worker,'PictureSettings',return_value=settings),patch.object(worker.select,'select',side_effect=idle):
            path.is_file.return_value=True
            settings.refresh.return_value=True
            engine.run()
        decoder.decoder.redraw.assert_called_once()
        self.assertEqual(decoder.decoder.picture,settings.values)
        self.assertEqual(engine.frame,b'preview')
        self.assertEqual(engine.sequence,1)
        decoder.close.assert_called_once()
