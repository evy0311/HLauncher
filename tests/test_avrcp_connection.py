"""Audit basic AVRCP negotiation, channel ownership and actual receive delivery."""
import socket
import struct
import threading
import types
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

from hlauncher.control_protocols import AvrcpTarget
from hlauncher.controls_worker import ControlConnections, SDP, outbound_mtu, radio_ready, serve_avrcp
from hlauncher import controls_worker
from hlauncher.debug_tools import InputMonitor


def request(pdu,args=b'',ctype=1,transaction=1):
    return bytes([transaction<<4])+b'\x11\x0e'+bytes([ctype,0x48,0,0,0x19,0x58,pdu,0])+struct.pack('!H',len(args))+args


class AvrcpConnection(unittest.TestCase):
    def test_sdp_role_features_and_control_channel_are_consistent(self):
        record=ET.fromstring(SDP)
        attributes={int(a.attrib['id'],16):a for a in record}
        self.assertEqual(attributes[1].find('.//uuid').attrib['value'],'0x110c')
        descriptors=attributes[4].find('sequence').findall('sequence')
        self.assertEqual([int(d.find('uint16').attrib['value'],16) for d in descriptors],[0x17,0x104])
        self.assertEqual(attributes[9].find('.//uuid').attrib['value'],'0x110e')
        self.assertEqual(int(attributes[9].find('.//uint16').attrib['value'],16),0x103)
        self.assertEqual(int(attributes[0x311].find('uint16').attrib['value'],16),1)
        self.assertNotIn(0xd,attributes)  # No unimplemented browsing channel.

    def test_setup_queries_and_invalid_controls_are_bounded(self):
        target=AvrcpTarget()
        for pdu,args in ((0x10,b'\x02'),(0x10,b'\x03'),(0x11,b''),
                         (0x17,b'\x01\x00\x6a'),(0x18,b'\x00'),(0x30,b'')):
            reply,event=target.receive(request(pdu,args,transaction=7))
            self.assertEqual(reply[0],0x72)
            self.assertEqual(reply[3],12);self.assertIsNone(event)
            self.assertEqual(struct.unpack('!H',reply[11:13])[0],len(reply)-13)
        self.assertEqual(target.receive(request(0x30))[0][-1],0)  # Idle target, no error state.
        target.update({'title':'Unknown status','playback_state':'unknown','available':True})
        self.assertEqual(target.receive(request(0x30))[0][-1],255)
        for pdu,args in ((0x17,b''),(0x17,b'\x02\x00\x6a'),(0x18,b'\x05'),(0x31,b'\x7f\0\0\0\0')):
            reply,event=target.receive(request(pdu,args,ctype=3 if pdu==0x31 else 1))
            self.assertEqual(reply[3],10);self.assertEqual(reply[-1],1);self.assertIsNone(event)
        for pdu in (0x10,0x11,0x17,0x18,0x20,0x30):
            self.assertEqual(target.receive(request(pdu,ctype=0))[0][3],10)
        self.assertIsNone(target.receive(bytes.fromhex('10110e00007c4b00'))[1])  # Wrong subunit.
        for opcode in (0x30,0x31):
            reply,event=target.receive(b'\xa0\x11\x0e\x01\xff'+bytes([opcode,7,255,255,255,255]))
            self.assertEqual(reply[0],0xa2);self.assertEqual(reply[3],12)
            self.assertEqual(len(reply),11);self.assertIsNone(event)
        foreign=bytearray(request(0x10,b'\x03'));foreign[6:9]=bytes.fromhex('00004c')
        self.assertEqual(target.receive(foreign)[0],bytes.fromhex('12110e084800'))

    def test_metadata_continuation_matches_single_response_at_minimum_mtu(self):
        media=dict(title='Low end '*20,artist='Artist '*20,album='Album '*20,duration_ms=0)
        small=AvrcpTarget(48);large=AvrcpTarget(512)
        small.update(media);large.update(media)
        query=request(0x20,bytes(9))
        expected=large.receive(query)[0][13:]
        reply,_=small.receive(query)
        self.assertEqual(reply[10],1)
        chunks=[reply[13:]]
        for transaction in range(2,15):
            reply,_=small.receive(request(0x40,b'\x20',ctype=0,transaction=transaction))
            self.assertLessEqual(len(reply),48)
            self.assertEqual(reply[0],transaction<<4|2)
            self.assertEqual(reply[9],0x20)
            chunks.append(reply[13:])
            if reply[10]==3:break
            self.assertEqual(reply[10],2)
        else:self.fail('Metadata continuation did not finish')
        self.assertEqual(b''.join(chunks),expected)
        self.assertIn(b'\x00\x01' + b'0',expected)  # Zero duration retained, not empty.
        self.assertIsNone(small.pending)
        self.assertEqual(small.receive(request(0x40,b'\x20',ctype=0))[0][3],10)
        small.receive(query)
        reply,_=small.receive(request(0x41,b'\x20',ctype=0))
        self.assertEqual(reply[3],9);self.assertIsNone(small.pending)
        small.receive(query)
        small.receive(request(0x30))
        self.assertIsNone(small.pending)

    def test_notifications_use_subscription_transaction_once_and_can_be_reregistered(self):
        target=AvrcpTarget()
        for event in (1,2):
            reply,_=target.receive(request(0x31,bytes([event])+bytes(4),ctype=3,transaction=event+4))
            self.assertEqual(reply[3],15)
        changed=target.update(dict(title='A',artist='B',playback_state='playing'))
        self.assertEqual([r[0] for r in changed],[0x52,0x62])
        self.assertTrue(all(r[3]==13 for r in changed))
        self.assertFalse(target.update(dict(title='A',artist='B',playback_state='playing')))
        target.receive(request(0x31,b'\x02'+bytes(4),ctype=3,transaction=9))
        changed=target.update(dict(title='C',artist='B',playback_state='playing'))
        self.assertEqual(len(changed),1);self.assertEqual(changed[0][0],0x92)

    def test_connection_collision_and_bluez_restart_do_not_replace_live_channel(self):
        pool=ControlConnections();self.assertIsNone(pool.token());pool.enable()
        token=pool.token()
        first,first_peer=socket.socketpair();second,second_peer=socket.socketpair()
        stale,stale_peer=socket.socketpair();replacement,replacement_peer=socket.socketpair()
        try:
            self.assertTrue(pool.attach('radio',first))
            self.assertFalse(pool.attach('radio',second,token))
            self.assertEqual(second.fileno(),-1)
            first_peer.sendall(b'live');self.assertEqual(first.recv(4),b'live')
            pool.release();pool.enable()
            self.assertFalse(pool.attach('radio',stale,token))
            self.assertTrue(pool.attach('radio',replacement,pool.token()))
            pool.discard('radio',first)
            self.assertIsNone(pool.token())  # Stale receiver cannot remove replacement.
            pool.disconnect('radio')
            self.assertIsNotNone(pool.token())
        finally:
            pool.release()
            for sock in (first,first_peer,second,second_peer,stale,stale_peer,replacement,replacement_peer):sock.close()

    def test_outbound_mtu_uses_negotiated_size_and_safe_fallback(self):
        class FakeSocket:
            def getsockopt(self,*args):return struct.pack('<HHHBBHH',96,672,0,0,0,0,0)
        self.assertEqual(outbound_mtu(FakeSocket()),96)
        left,right=socket.socketpair()
        try:self.assertEqual(outbound_mtu(left),48)
        finally:left.close();right.close()

    def test_reconnect_uses_authenticated_resolved_peer_independently_of_hfp(self):
        properties=dict(Connected=True,Paired=True,Trusted=True,ServicesResolved=True)
        self.assertTrue(radio_ready(properties))
        for key in properties:
            self.assertFalse(radio_ready(dict(properties,**{key:False})))
        self.assertFalse(radio_ready({}))

    def test_hfp_eof_clears_connected_gate_used_by_avrcp_reconnect(self):
        left,right=socket.socketpair();right.close()
        stop=threading.Event();statuses=[];closed=[]
        class Descriptor:
            def take(self):return left.detach()
        class Bus:
            def get_object(self,*args):return types.SimpleNamespace(Open=lambda **kw:Descriptor())
            def close(self):closed.append(True)
        dbus=types.SimpleNamespace(SystemBus=lambda **kw:Bus(),Interface=lambda obj,*args:obj)
        def output(**event):
            if event.get('transport')=='hfp':
                statuses.append(event['status'])
                if event['status']=='Waiting for radio':stop.set()
        with patch.dict('sys.modules',{'dbus':dbus}),patch.object(controls_worker,'STOP',stop),\
             patch.object(controls_worker,'STATUS',{}),patch.object(controls_worker,'emit',side_effect=output):
            controls_worker.serve_hfp()
            self.assertEqual(controls_worker.STATUS['hfp'],'Waiting for radio')
        self.assertEqual(statuses,['Connected','Waiting for radio'])
        self.assertEqual(closed,[True])

    def test_real_receiver_delivers_next_previous_to_hlauncher_after_full_negotiation(self):
        monitor=InputMonitor(lambda **v:None,'')
        left,right=socket.socketpair();right.settimeout(2)
        stop=threading.Event()
        thread=threading.Thread(target=serve_avrcp,args=(left,),daemon=True)
        with patch.object(controls_worker,'STOP',stop),patch.object(controls_worker,'metadata',return_value={}),patch.object(controls_worker,'emit',side_effect=lambda **v:monitor.receive_control(v)):
            try:
                thread.start()
                for pdu,args,ctype in ((0x10,b'\x03',1),(0x31,b'\x01'+bytes(4),3),
                                       (0x31,b'\x02'+bytes(4),3),(0x11,b'',1),
                                       (0x17,b'\x01\x00\x6a',1),(0x18,b'\x00',1),(0x30,b'',1)):
                    right.sendall(request(pdu,args,ctype));self.assertIn(right.recv(512)[3],(12,15))
                for op in (0x4b,0xcb,0x4c,0xcc):
                    right.sendall(bytes.fromhex('30110e00487c')+bytes([op,0]))
                    self.assertEqual(right.recv(512)[3],9)
            finally:
                right.close();thread.join(timeout=2)
                if thread.is_alive():stop.set();thread.join(timeout=2)
        self.assertFalse(thread.is_alive())
        events=monitor.drain()
        self.assertEqual([(e['button'],e['action']) for e in events],
                         [('next','down'),('next','up'),('previous','down'),('previous','up')])
        self.assertEqual(monitor.buttons['next']['count'],2)
        self.assertEqual(monitor.buttons['previous']['count'],2)
        self.assertFalse(monitor.buttons['next']['held'])
        self.assertEqual(monitor.traffic['avrcp']['count'],11)

    def test_first_metadata_query_and_source_change_notification(self):
        from hlauncher.media import radio_metadata
        stop=threading.Event()
        selected=[radio_metadata('carplay')]
        left,right=socket.socketpair();right.settimeout(2)
        thread=threading.Thread(target=serve_avrcp,args=(left,),daemon=True)
        with patch.object(controls_worker,'STOP',stop), \
             patch.object(controls_worker,'metadata',side_effect=lambda:selected[0]), \
             patch.object(controls_worker,'emit'):
            try:
                thread.start()
                # Ask only for title and artist, before any setup or subscription.
                query=request(0x20,bytes(8)+b'\x02'+struct.pack('!II',1,2))
                right.sendall(query)
                reply=right.recv(512)
                expected=b'\x02'+struct.pack('!IHH',1,106,7)+b'Carplay'+struct.pack('!IHH',2,106,9)+b'HLauncher'
                self.assertEqual(reply[13:],expected)
                right.sendall(request(0x31,b'\x02'+bytes(4),ctype=3,transaction=8))
                self.assertEqual(right.recv(512)[3],15)
                selected[0]=radio_metadata('android-auto')
                changed=right.recv(512)
                self.assertEqual((changed[0],changed[3],changed[9]),(0x82,13,0x31))
                right.sendall(query)
                reply=right.recv(512)
                payload=reply[13:]
                while reply[10] in (1,2):
                    right.sendall(request(0x40,b'\x20',ctype=0))
                    reply=right.recv(512)
                    payload+=reply[13:]
                self.assertIn(b'Android Auto',payload)
                self.assertIn(b'HLauncher',payload)
            finally:
                stop.set();right.close();thread.join(timeout=2)
        self.assertFalse(thread.is_alive())
