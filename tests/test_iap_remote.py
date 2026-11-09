"""Replay Honda's actual transaction-bearing iAP track keys, never a live radio."""
from collections import Counter
from datetime import datetime
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from hlauncher.debug_tools import InputMonitor
from hlauncher.plugin_host import PluginHost, channel
from hlauncher.protocol.session import StartProbe, packet
from hlauncher_sdk import encode, decode
from hlauncher_sdk.buttons import CARPLAY, ButtonGate

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = json.loads((ROOT/'tests/fixtures/hondalink-remote-buttons.json').read_text())


def press(mask, transaction=1, banks=4):
    return packet(b'\x02\x00'+transaction.to_bytes(2,'big')+mask.to_bytes(banks,'little'))


def buttons(events):
    return [(e['button'], e['action']) for e in events if e['state']=='iap_remote_button']


class IapRemote(unittest.TestCase):
    def parser(self):
        probe = StartProbe()
        probe.authenticated = True
        return probe

    def test_saved_car_packets_decode_five_next_three_previous_at_every_split(self):
        for width in range(1, 18):
            probe = self.parser()
            events = []
            for saved in FIXTURE['packets']:
                raw = packet(bytes.fromhex(saved['payload']))
                for offset in range(0, len(raw), width):
                    decoded, replies = probe.feed(raw[offset:offset+width])
                    self.assertFalse(replies)  # ContextButtonStatus does not request ACK.
                    events.extend(decoded)
            self.assertEqual(Counter(name for name, action in buttons(events) if action=='down'),
                             FIXTURE['expected_presses'])
            self.assertEqual(Counter(name for name, action in buttons(events) if action=='up'),
                             FIXTURE['expected_presses'])
            self.assertFalse(any(e['state']=='iap_unhandled' for e in events))

    def test_repeated_hold_combined_keys_and_release_are_edges(self):
        probe = self.parser()
        events, replies = probe.feed(press(8)+press(8,2)+press(24,3)+press(16,4)+press(0,5))
        self.assertEqual(buttons(events), [('next','down'),('previous','down'),('next','up'),('previous','up')])
        self.assertFalse(replies)

    def test_known_optional_banks_and_unknown_bits_do_not_become_phone_controls(self):
        for mask, expected in ((1,'play_pause'), (0x100,'play'), (0x200,'pause')):
            for banks in range(1 if mask==1 else 2, 5):
                probe = self.parser()
                events, _ = probe.feed(press(mask,banks=banks)+press(0,banks=banks))
                self.assertEqual(buttons(events), [(expected,'down'),(expected,'up')])
        for mask in (2,4,0x20,0x40,0x8000,0x10000,0x80000000):
            events, _ = self.parser().feed(press(mask))
            self.assertFalse(buttons(events))
            self.assertEqual(next(e for e in events if e['state']=='iap_remote_buttons')['unsupported_mask'], mask)

    def test_unauthenticated_malformed_checksum_and_other_commands_do_not_act(self):
        events, replies = StartProbe().feed(press(8))
        self.assertFalse(buttons(events)); self.assertFalse(replies)
        for payload in (b'\x02\x00\x00\x01', b'\x02\x00\x00\x01'+bytes(5), b'\x02\x04\x00\x01\x08'):
            events, replies = self.parser().feed(packet(payload))
            self.assertFalse(buttons(events)); self.assertFalse(replies)
        raw = bytearray(press(8)); raw[-1] ^= 1
        events, replies = self.parser().feed(raw)
        self.assertFalse(buttons(events)); self.assertFalse(replies)
        self.assertTrue(any(e['state']=='iap_bad_checksum' for e in events))

    def test_actual_capture_reaches_carplay_queue_through_host_and_sdk_socket(self):
        def load(name):
            spec = importlib.util.spec_from_file_location('iap_test_'+name, ROOT/'plugins/carplay'/f'{name}.py')
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            return module
        with patch.dict(sys.modules, {name:load(name) for name in ('input','media')}):
            backend = load('backend').CarplayHDMI()
        backend.proc = SimpleNamespace(poll=lambda:None)
        now = [0]
        backend.button_gate = ButtonGate(lambda:now[0])
        probe = self.parser()
        monitor = InputMonitor(lambda **v:None, '', clock=lambda:now[0])
        host = PluginHost({},720,480,lambda **v:None,lambda:None,None)
        tx, rx = channel(); rx.settimeout(1)
        worker = SimpleNamespace(manifest=SimpleNamespace(id='carplay',capabilities={'input.buttons'}),
            ready=True,background_enabled=True,button_subscription=frozenset(CARPLAY),
            send=lambda **v:tx.send(encode(v))>0)
        host.workers['carplay'] = worker
        try:
            for saved in FIXTURE['packets']:
                now[0] = datetime.fromisoformat(saved['wall']).timestamp()
                events, _ = probe.feed(packet(bytes.fromhex(saved['payload'])))
                for event in events: monitor.receive_iap_remote(event)
                for event in monitor.drain():
                    self.assertEqual(event['source'],'hondalink-iap')
                    host.button(event)
                    message = decode(rx.recv(16384))
                    result = backend.button(message)
                    host.button_result(worker,dict(button=message['button'],sequence=message['sequence'],
                        result=result,final=result!='Queued to CarPlay USB'))
                    if result=='Queued to CarPlay USB':
                        backend.finish_button(message['sequence'],'Sent over USB')
                        host.button_result(worker,backend.take_button_results()[0])
            self.assertEqual(Counter(item['command'] for item in backend.queue), {'next':5,'prev':3})
            self.assertEqual(monitor.buttons['next']['count'],10)
            self.assertEqual(monitor.buttons['previous']['count'],6)
            self.assertFalse(host.button_pending)
            self.assertFalse(host.button_owners)
            self.assertFalse(backend.button_gate.held)
            self.assertEqual(host.button_results['next']['result'],'Sent over USB')
            self.assertEqual(host.button_results['previous']['result'],'Sent over USB')
        finally:
            tx.close(); rx.close()

    def test_new_identification_resets_held_keys_and_input_epoch(self):
        probe = self.parser()
        monitor = InputMonitor(lambda **v:None, '')
        for event in probe.feed(press(8))[0]: monitor.receive_iap_remote(event)
        first = monitor.drain()[0]
        events, _ = probe.feed(packet(bytes.fromhex('00380001')))
        for event in events: monitor.receive_iap_remote(event)
        self.assertFalse(probe.simple_remote_state)
        probe.authenticated = True
        for event in probe.feed(press(8,2))[0]: monitor.receive_iap_remote(event)
        second = monitor.drain()[0]
        self.assertGreater(second['input_epoch'],first['input_epoch'])
        self.assertEqual(second['action'],'down')
