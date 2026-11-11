"""Volume probes must release, match replies and never imply physical success."""
import socket
import threading
import time
import unittest
from unittest.mock import patch
from hlauncher.radio_volume import RadioVolume


class VolumeTests(unittest.TestCase):
    def setUp(self):
        self.now=10.;self.reports=[]
        self.volume=RadioVolume(self.reports.append,lambda:self.now)

    @staticmethod
    def reply(raw,code=9):
        return bytes([raw[0]|2])+raw[1:3]+bytes([code])+raw[4:]

    def test_one_press_release_for_each_direction_and_cooldown(self):
        for direction,operation in (('up',0x41),('down',0x42)):
            commands=self.volume.start(direction)
            self.assertEqual([c[6] for c in commands],[operation,operation|0x80])
            self.assertEqual(commands[0][1:6],bytes.fromhex('110e00487c'))
            self.assertNotEqual(commands[0][0],commands[1][0])
            self.assertFalse(self.volume.start(direction))
            for raw in commands:self.volume.receive(self.reply(raw))
            self.assertEqual(self.reports[-1],'Radio accepted / check its volume display')
            self.assertFalse(self.volume.start(direction))
            self.now+=2.1
        self.assertFalse(self.volume.start('mute'))

    def test_rejected_and_missing_replies_never_report_accepted(self):
        commands=self.volume.start('down')
        self.volume.receive(self.reply(commands[0],10))
        self.volume.receive(self.reply(commands[1]))
        self.assertIn('rejected',self.reports[-1])
        self.now+=3
        self.volume.start('down');self.now+=3;self.volume.tick()
        self.assertIn('unconfirmed',self.reports[-1])
        self.assertFalse(self.volume.pending)

    def test_mismatched_reply_does_not_ack(self):
        commands=self.volume.start('down');raw=self.reply(commands[0])
        self.assertTrue(self.volume.receive(raw[:-2]+bytes([0x41,0])))
        self.assertEqual(len(self.volume.pending),2)
        self.assertTrue(self.volume.receive(raw[:3]))
        self.assertEqual(len(self.volume.pending),2)
        self.assertFalse(self.volume.receive(commands[0]))
        self.volume.receive(bytes([commands[0][0]|3])+commands[0][1:3])
        self.assertFalse(self.volume.pending)
        self.assertIn('does not support',self.reports[-1])

    def test_ui_bridge_is_bounded_and_reports_unavailable_worker(self):
        from hlauncher.debug_tools import InputMonitor
        from unittest.mock import Mock
        monitor=InputMonitor(lambda **v:None,'00:00:00:00:00:00',lambda:self.now)
        monitor.request_volume('up')
        self.assertIn('unavailable',monitor.volume_status)
        process=Mock();process.poll.return_value=None;monitor.control_process=process
        monitor.request_volume('down');monitor.request_volume('up')
        self.assertEqual(monitor.volume_requests.qsize(),1)
        self.assertEqual(monitor.volume_requests.get_nowait(),(self.now,'down'))
        monitor.receive_control(dict(state='radio_volume',status='Radio rejected volume command'))
        self.assertEqual(monitor.volume_status,'Radio rejected volume command')

    def test_disconnected_tap_requests_one_bounded_command_and_failure_clears_it(self):
        import io
        import queue
        from hlauncher import controls_worker as worker
        reports=[];wake=threading.Event();connected=threading.Event();requests=queue.Queue(1)
        with patch.object(worker.sys,'stdin',io.StringIO('{"volume":"down"}\n')), \
             patch.object(worker,'RECONNECT',wake),patch.object(worker,'AVRCP_CONNECTED',connected), \
             patch.object(worker,'VOLUME_REQUESTS',requests),patch.object(worker,'volume_report',reports.append):
            worker.read_commands()
        self.assertTrue(wake.is_set())
        self.assertEqual(requests.qsize(),1)
        self.assertIn('Connecting AVRCP',reports[-1])
        with patch.object(worker,'VOLUME_REQUESTS',requests),patch.object(worker,'volume_report',reports.append):
            worker.fail_volume('AVRCP connect failed')
        self.assertTrue(requests.empty())
        self.assertEqual(reports[-1],'AVRCP connect failed')

    def test_worker_pair_acks_and_track_keys_share_one_channel(self):
        from hlauncher import controls_worker as worker
        server,peer=socket.socketpair(socket.AF_UNIX,socket.SOCK_DGRAM);peer.settimeout(2)
        records=[];stop=threading.Event()
        thread=threading.Thread(target=worker.serve_avrcp,args=(server,),daemon=True)
        with patch.object(worker,'STOP',stop),patch.object(worker,'emit',side_effect=lambda **v:records.append(v)):
            try:
                thread.start()
                self.assertTrue(worker.AVRCP_CONNECTED.wait(1))
                worker.VOLUME_REQUESTS.put_nowait((time.monotonic(),'down'))
                commands=[peer.recv(512),peer.recv(512)]
                self.assertEqual([c[6] for c in commands],[0x42,0xc2])
                for raw in commands:peer.send(self.reply(raw))
                peer.send(bytes.fromhex('30110e00487c4b00'))
                self.assertEqual(peer.recv(512)[3],9)
            finally:
                stop.set();peer.close();thread.join(2)
                if thread.is_alive():stop.set();thread.join(2)
        self.assertFalse(thread.is_alive())
        self.assertTrue(any(v.get('button')=='next' for v in records))
        self.assertTrue(any('Radio accepted' in v.get('status','') for v in records))
        self.assertFalse(worker.AVRCP_CONNECTED.is_set())
