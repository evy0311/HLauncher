"""Android contact ordering and native bridge framing, without a USB phone."""
import base64
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
    def test_worker_uses_radio_buttons_and_the_requested_microphone_format(self):
        from types import SimpleNamespace
        from unittest.mock import patch
        with patch.dict(sys.modules, input=inputs):
            spec = importlib.util.spec_from_file_location('aa_controls_worker', ROOT/'plugins/android-auto/worker.py')
            worker = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(worker)
        engine = worker.Engine(SimpleNamespace())
        engine.proc = SimpleNamespace(poll=lambda: None)
        button = dict(button='next', action='down', sequence=19, source='avrcp')
        self.assertEqual(engine.button(button), 'Queued to Android Auto')
        key = engine.inputs.get_nowait()
        self.assertEqual((key['code'], key['sequence']), (87, 19))
        # The radio can start another voice session after Android Auto ends
        # the first one without receiving a BVRA=0 from the radio.
        voice = dict(button='voice_assistant', action='activate', source='hfp-command')
        with patch.object(engine.button_gate, 'clock', side_effect=[1, 1.05, 2]):
            self.assertEqual(engine.button(dict(voice, sequence=20)), 'Queued to Android Auto')
            self.assertEqual(engine.button(dict(voice, sequence=21)), 'Ignored release / duplicate')
            self.assertEqual(engine.button(dict(voice, sequence=22)), 'Queued to Android Auto')
        self.assertEqual([engine.inputs.get_nowait()['code'] for _ in range(2)], [84, 84])
        pcm = b'\x01\x00' * 160
        engine.microphone(pcm)
        self.assertTrue(engine.inputs.empty())
        engine.mic_requested = True
        engine.mic_format = (16000, 1)
        engine.microphone(pcm)
        mic = engine.inputs.get_nowait()
        self.assertEqual(mic['type'], 'microphone.pcm')
        self.assertEqual(base64.b64decode(mic['pcm']), pcm)

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
