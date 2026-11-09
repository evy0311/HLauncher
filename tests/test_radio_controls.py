"""Exercise malformed radio traffic and actual projection command translation."""
import random
import struct
import unittest
from hlauncher.control_protocols import AvrcpTarget,hfp_request,hfp_observation,avrcp_observation
from hlauncher.buttons import ButtonGate,CARPLAY,ANDROID

class RadioControls(unittest.TestCase):
    def vendor(self,pdu,payload=b'',ctype=1):
        return b'\x10\x11\x0e'+bytes([ctype,0x48,0,0,0x19,0x58,pdu,0])+struct.pack('!H',len(payload))+payload

    def test_track_press_release_and_unsupported_operation(self):
        target=AvrcpTarget()
        raw=b'\x30\x11\x0e\x00\x48\x7c\x4b\x00'
        reply,event=target.receive(raw)
        self.assertEqual(event,('next','down'));self.assertEqual(reply[3],9)
        self.assertEqual(target.receive(raw[:-2]+b'\xcb\x00')[1],('next','up'))
        reply,event=target.receive(raw[:-2]+b'\x7f\x00')
        self.assertIsNone(event);self.assertEqual(reply[3],10)

    def test_metadata_and_registered_notifications(self):
        target=AvrcpTarget();reply,_=target.receive(self.vendor(0x31,b'\x02\0\0\0\0',3))
        self.assertEqual(reply[3],15)
        changed=target.update({'title':'Test song','artist':'Artist'})
        self.assertEqual(len(changed),1);self.assertEqual(changed[0][3],13)
        self.assertFalse(target.update({'title':'Test song','artist':'Artist'}))
        reply,_=target.receive(self.vendor(0x20,bytes(9)))
        self.assertIn(b'Test song',reply);self.assertLessEqual(len(reply),512)
        reply,_=target.receive(self.vendor(0x30));self.assertEqual(reply[-1],255)

    def test_observed_honda_setup_pdus_accept_empty_settings_and_keep_track_receiver_usable(self):
        target=AvrcpTarget()
        # PDU ordering seen in the in-car logs; valid parameters supplied here.
        for request in (self.vendor(0x10,b'\x03'),
                        self.vendor(0x31,b'\x01\0\0\0\0',3),
                        self.vendor(0x31,b'\x02\0\0\0\0',3),
                        self.vendor(0x11)):
            reply,event=target.receive(request)
            self.assertIn(reply[3],(12,15));self.assertIsNone(event)
        self.assertEqual(reply,target.vendor(b'\x12\x11\x0e',0x11,b'\x00',12))
        for operation,name in ((0x4b,'next'),(0x4c,'previous')):
            self.assertEqual(target.receive(b'\x30\x11\x0e\x00\x48\x7c'+bytes([operation,0]))[1],(name,'down'))
        for request in (self.vendor(0x11,b'\x01'),self.vendor(0x11,ctype=0)):
            status=1 if request[3]==1 else 0
            self.assertEqual(target.receive(request),(target.vendor(b'\x12\x11\x0e',0x11,bytes([status]),10),None))

    def test_invalid_packets_and_fuzz_are_bounded(self):
        target=AvrcpTarget();rng=random.Random(123)
        for _ in range(3000):
            packet=rng.randbytes(rng.randrange(0,1050))
            reply,event=target.receive(packet)
            if reply:self.assertLessEqual(len(reply),512)
        self.assertEqual(target.receive(self.vendor(0x20,b'\0'*8+b'\xff')),(target.vendor(b'\x12\x11\x0e',0x20,b'\x01',10),None))

    def test_hfp_support_and_no_fake_call_or_dial(self):
        self.assertEqual(hfp_request(b'AT+APLSIRI?\r')[0],('+APLSIRI:1','OK'))
        self.assertEqual(hfp_request(b'AT+BVRA=1\r')[1],('voice_assistant','activate'))
        self.assertEqual(hfp_request(b'ATA\r')[1],('answer','trigger'))
        self.assertEqual(hfp_request(b'AT+CHUP\r')[1],('hang_up','trigger'))
        for raw,name in ((b'ATD123456;','dial'),(b'AT+BLDN','redial')):
            self.assertEqual(hfp_request(raw),(('ERROR',),(name,'trigger')))
        self.assertEqual(hfp_request(b'AT+CLCC'),(('OK',),None))
        self.assertEqual(hfp_request(b'AT+XAPL=123-456-1,24'),((),None))

    def test_receive_observations_preserve_unknown_operations_without_private_values(self):
        self.assertIn('0x7f',avrcp_observation(b'\x30\x11\x0e\x00\x48\x7c\x7f\x00')['summary'])
        target=AvrcpTarget()
        self.assertIsNone(target.receive(b'\x30\x11\x0e\x00\x48\x7c\x7f\x00')[1])
        for raw in (b'ATD123456789;',b'AT+CLIP="123456789",129',b'AT+UNKNOWN=123456789'):
            self.assertNotIn('123456789',str(hfp_observation(raw)))
        self.assertEqual(hfp_observation(b'AT+BVRA=1\r')['summary'],'AT+BVRA=1')

    def test_receiver_reports_unknown_packet_and_real_press_before_ui_filtering(self):
        import socket
        import threading
        from unittest.mock import patch
        from hlauncher import controls_worker as worker
        received=[]
        server,peer=socket.socketpair();peer.settimeout(2)
        thread=threading.Thread(target=worker.serve_avrcp,args=(server,),daemon=True)
        with patch.object(worker,'STOP',threading.Event()),patch.object(worker,'emit',side_effect=lambda **v:received.append(v)):
            try:
                thread.start()
                for operation in (0x7f,0x4b):
                    peer.sendall(b'\x30\x11\x0e\x00\x48\x7c'+bytes([operation,0]))
                    self.assertTrue(peer.recv(512))
            finally:
                peer.close();thread.join(timeout=2)
                if thread.is_alive():worker.STOP.set();thread.join(timeout=2)
        self.assertFalse(thread.is_alive())
        observations=[e for e in received if 'observation' in e]
        self.assertEqual([e['recognized'] for e in observations],[False,True])
        self.assertEqual([e['button'] for e in received if 'button' in e],['next'])
        self.assertEqual(received[-1]['rx_packets'],2)

    def test_stock_steering_mode_report_is_not_a_button_or_outbound_enable(self):
        from hlauncher.protocol.session import StartProbe,packet
        from hlauncher.protocol.frames import frame
        raw=packet(bytes.fromhex('004200220101')+frame(0xc1,b'\x00\x01\x64\x02'))
        for width in (1,3,len(raw)):
            probe=StartProbe();probe.authenticated=True
            probe.sessions={257:(1,'jp.co.honda.rd.dispaudio.app.generals')}
            events=[];replies=[]
            for offset in range(0,len(raw),width):
                e,r=probe.feed(raw[offset:offset+width]);events.extend(e);replies.extend(r)
            reports=[e for e in events if e['state']=='honda_steering_mode']
            self.assertEqual(reports,[dict(state='honda_steering_mode',session=257,mode=2)])
            self.assertEqual(replies,[packet(bytes.fromhex('000200220042'))])

    def test_projection_actions_are_one_shot_and_releases_are_not_toggles(self):
        now=[10];gate=ButtonGate(lambda:now[0])
        for name,command in CARPLAY.items():
            self.assertEqual(gate.command(dict(button=name,action='down'),CARPLAY),command)
            self.assertIsNone(gate.command(dict(button=name,action='up'),CARPLAY))
            self.assertIsNone(gate.command(dict(button=name,action='trigger'),CARPLAY))
        now[0]+=1
        self.assertEqual(gate.command(dict(button='next',action='trigger'),ANDROID),87)

    def test_real_plugin_queues_use_sdk_contract_and_reject_disconnected_engines(self):
        import importlib.util
        from pathlib import Path
        import sys
        from types import SimpleNamespace
        root=Path(__file__).resolve().parents[1]
        def load(name,path):
            spec=importlib.util.spec_from_file_location(name,path)
            mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod);return mod
        saved={name:sys.modules.get(name) for name in ('input','media')}
        try:
            sys.modules['input']=load('car_input',root/'plugins/carplay/input.py')
            sys.modules['media']=load('car_media',root/'plugins/carplay/media.py')
            backend=load('car_backend',root/'plugins/carplay/backend.py').CarplayHDMI()
            message=dict(button='next',action='trigger',sequence=13)
            backend.proc=SimpleNamespace(poll=lambda:None)
            self.assertEqual(backend.button(message),'Queued to CarPlay USB')
            self.assertEqual(backend.queue[-1]['command'],'next')
            backend.proc=None
            self.assertIn('unavailable',backend.button(dict(button='answer',action='trigger',sequence=14)))
            sys.modules['input']=load('android_input',root/'plugins/android-auto/input.py')
            engine=load('android_worker',root/'plugins/android-auto/worker.py').Engine(SimpleNamespace())
            engine.proc=SimpleNamespace(poll=lambda:None)
            self.assertEqual(engine.button(message),'Queued to Android Auto')
            self.assertEqual(engine.inputs.get_nowait()['code'],87)
        finally:
            for name,value in saved.items():
                if value is None:sys.modules.pop(name,None)
                else:sys.modules[name]=value

    def test_hondalink_profiles_recover_after_bluetooth_owner_changes(self):
        from hlauncher.radio import ProfileRegistry
        from types import SimpleNamespace
        registered=[];closed=[];available=[True]
        profile=SimpleNamespace(uuid='honda',registered=False,close_all=lambda:closed.append(True))
        def manager():
            if not available[0]:raise RuntimeError('Bluetooth unavailable')
            return SimpleNamespace(RegisterProfile=lambda *args:registered.append(args))
        registry=ProfileRegistry([('/honda',profile,{'Channel':11})],manager,lambda **v:None)
        registry.tick();registry.tick();self.assertEqual(len(registered),1)
        registry.lost();available[0]=False;registry.tick();self.assertFalse(profile.registered)
        available[0]=True;registry.tick();self.assertEqual(len(registered),2)
        self.assertEqual(closed,[True]);self.assertTrue(profile.registered)
