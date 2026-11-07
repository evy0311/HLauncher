"""Receive-to-plugin routing, with a real SDK socket and CarPlay input queue."""
import importlib.util
from pathlib import Path
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from hlauncher.plugin_host import PluginHost, Worker, channel
from hlauncher.catalog import Manifest
from hlauncher.control_protocols import AvrcpTarget, hfp_request
from hlauncher.debug_tools import InputMonitor
from hlauncher_sdk import encode, decode
from hlauncher_sdk.buttons import CARPLAY, ButtonGate


class ButtonRouting(unittest.TestCase):
    def setUp(self):
        self.events = []
        self.sent = []
        self.host = PluginHost({}, 720, 480, lambda **v: self.events.append(v), lambda: None,
                               SimpleNamespace(stop=lambda _: None))

    def worker(self, name, buttons=(), capable=True, background=True):
        worker = SimpleNamespace(manifest=SimpleNamespace(id=name,
            capabilities={'input.buttons'} if capable else set()), ready=True,
            background_enabled=background, button_subscription=frozenset(),
            send=lambda **v: self.sent.append((name, v)) or True, close=lambda: None)
        self.host.workers[name] = worker
        self.host.subscribe_buttons(worker, dict(buttons=list(buttons)))
        return worker

    def press(self, name='next', action='trigger', sequence=1):
        message = dict(button=name, action=action, source='avrcp', sequence=sequence)
        self.host.button(message)
        return message

    def test_capability_is_not_subscription_and_background_carplay_receives(self):
        self.worker('android-auto')
        self.host.active = 'android-auto'
        self.worker('carplay', CARPLAY)
        self.press()
        self.assertEqual([name for name, _ in self.sent], ['carplay'])

    def test_foreground_subscriber_wins_without_broadcast(self):
        self.worker('carplay', CARPLAY)
        self.worker('other', ['next'])
        self.host.active = 'other'
        self.press()
        self.assertEqual([name for name, _ in self.sent], ['other'])

    def test_release_stays_with_original_owner_and_preserves_command_status(self):
        first = self.worker('carplay', CARPLAY)
        self.worker('other', CARPLAY)
        self.host.active = 'carplay'
        self.press(action='down')
        self.host.button_result(first, dict(button='next', sequence=1, result='Sent over USB'))
        self.host.active = 'other'
        self.press(action='up', sequence=2)
        self.host.button_result(first, dict(button='next', sequence=2, result='Ignored release'))
        self.assertEqual([name for name, _ in self.sent], ['carplay', 'carplay'])
        self.assertEqual(self.host.button_results['next']['result'], 'Sent over USB')
        self.assertFalse(self.host.button_owners)

    def test_subscription_validation_unsubscribe_and_unsupported_dial(self):
        worker = self.worker('carplay', CARPLAY)
        for buttons in (None, ['bad'], [{}], 'next', ['next']*100):
            self.host.subscribe_buttons(worker, dict(buttons=buttons))
            self.assertEqual(worker.button_subscription, frozenset(CARPLAY))
        self.press('redial')
        self.assertFalse(self.sent)
        self.assertIn('No plugin subscribed', self.host.button_results['redial']['result'])
        self.host.subscribe_buttons(worker, dict(buttons=[]))
        self.press()
        self.assertFalse(self.sent)
        unprivileged = self.worker('other', ['next'], capable=False)
        self.assertFalse(unprivileged.button_subscription)

    def test_ack_is_matched_by_plugin_sequence_and_button_and_times_out(self):
        worker = self.worker('carplay', CARPLAY)
        other = self.worker('other', CARPLAY)
        self.press()
        self.host.button_result(other, dict(button='next', sequence=1, result='wrong plugin'))
        self.host.button_result(worker, dict(button='previous', sequence=1, result='wrong button'))
        self.assertEqual(self.host.button_results['next']['result'], 'Sent to plugin')
        self.host.button_result(worker, dict(button='next', sequence=1, result='Queued', final=False))
        self.host.workers.clear()
        with patch('hlauncher.plugin_host.time.monotonic', return_value=10**12):
            self.host.tick()
        self.assertIn('timed out', self.host.button_results['next']['result'])
        self.host.button_result(worker, dict(button='next', sequence=1, result='late'))
        self.assertIn('timed out', self.host.button_results['next']['result'])

    def test_newer_command_is_not_overwritten_by_older_ack(self):
        worker = self.worker('carplay', CARPLAY)
        self.press(sequence=1)
        self.press(sequence=2)
        self.host.button_result(worker, dict(button='next', sequence=2, result='New'))
        self.host.button_result(worker, dict(button='next', sequence=1, result='Old'))
        self.assertEqual(self.host.button_results['next']['result'], 'New')

    def test_queue_backpressure_never_falls_through_to_another_phone(self):
        worker = self.worker('carplay', CARPLAY)
        self.worker('other', CARPLAY)
        worker.send = lambda **v: False
        self.press()
        self.assertFalse(self.sent)
        self.assertIn('queue full', self.host.button_results['next']['result'])
        self.assertFalse(self.host.button_pending)

    def test_long_hold_and_voice_release_cannot_retrigger(self):
        now = [10]
        gate = ButtonGate(lambda: now[0])
        for name, press, release in [('next', 'down', 'up'), ('voice_assistant', 'activate', 'deactivate')]:
            message = dict(button=name, source='avrcp', action=press)
            self.assertEqual(gate.command(message, CARPLAY), CARPLAY[name])
            now[0] += 1
            self.assertIsNone(gate.command(message, CARPLAY))
            self.assertIsNone(gate.command(dict(message, action=release), CARPLAY))
            self.assertEqual(gate.command(message, CARPLAY), CARPLAY[name])

    def test_reconnection_clears_a_lost_release_and_previous_destination(self):
        now = [10]
        gate = ButtonGate(lambda:now[0])
        monitor = InputMonitor(lambda **v:None, '')
        self.worker('carplay', CARPLAY)
        self.worker('other', CARPLAY)
        self.host.active = 'carplay'
        monitor.offer('next', 'down', 'avrcp')
        first = monitor.drain()[0]
        self.host.button(first)
        self.assertEqual(gate.command(first, CARPLAY), 'next')
        monitor.receive_control(dict(transport='avrcp', status='Disconnected'))
        monitor.receive_control(dict(transport='avrcp', status='Connected'))
        now[0] += 1
        self.host.active = 'other'
        monitor.offer('next', 'down', 'avrcp')
        second = monitor.drain()[0]
        self.assertNotEqual(first['input_epoch'], second['input_epoch'])
        self.host.button(second)
        self.assertEqual(gate.command(second, CARPLAY), 'next')
        self.assertEqual([name for name, _ in self.sent], ['carplay', 'other'])

    def test_real_socket_to_carplay_queue_for_every_supported_command(self):
        root = Path(__file__).resolve().parents[1]
        def load(name, path):
            spec = importlib.util.spec_from_file_location(name, path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            return module
        modules = {name: load('routing_'+name, root/'plugins/carplay'/f'{name}.py') for name in ('input', 'media')}
        with patch.dict(sys.modules, modules):
            backend = load('routing_backend', root/'plugins/carplay/backend.py').CarplayHDMI()
        backend.proc = SimpleNamespace(poll=lambda: None)
        worker = self.worker('carplay', CARPLAY)
        tx, rx = channel()
        rx.settimeout(1)
        worker.send = lambda **v: tx.send(encode(v)) > 0
        monitor = InputMonitor(lambda **v:None, '')
        target = AvrcpTarget()
        operations = {'next':0x4b, 'previous':0x4c, 'play':0x44, 'pause':0x46, 'stop':0x45}
        phone = {'voice_assistant':b'AT+BVRA=1', 'answer':b'ATA', 'hang_up':b'AT+CHUP'}
        try:
            for sequence, (button, command) in enumerate(CARPLAY.items(), 1):
                if button in operations:
                    _, event = target.receive(b'\x30\x11\x0e\x00\x48\x7c'+bytes([operations[button], 0]))
                    monitor.offer(*event, 'avrcp')
                elif button in phone:
                    _, event = hfp_request(phone[button])
                    monitor.offer(*event, 'hfp-command')
                else:
                    monitor.offer(button, 'trigger', 'screen')
                self.host.button(monitor.drain()[0])
                received = decode(rx.recv(16384))
                self.assertEqual(backend.button(received), 'Queued to CarPlay USB')
                self.assertEqual(backend.queue[-1]['command'], command)
                self.host.button_result(worker, dict(button=button, sequence=sequence,
                    result='Queued to CarPlay USB', final=False))
                backend.finish_button(sequence, 'Sent over USB')
                self.host.button_result(worker, backend.take_button_results()[0])
                self.assertEqual(self.host.button_results[button]['result'], 'Sent over USB')
            self.assertFalse(self.host.button_pending)
            self.assertFalse(backend.button_pending)
        finally:
            tx.close()
            rx.close()

    def test_expired_input_is_reported_and_not_written_to_bridge(self):
        root = Path(__file__).resolve().parents[1]
        # Reuse the module loaded by the integration test, without loading USB/decoder libraries.
        def load(name):
            spec = importlib.util.spec_from_file_location('expiry_'+name, root/'plugins/carplay'/f'{name}.py')
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            return module
        with patch.dict(sys.modules, {name:load(name) for name in ('input','media')}):
            backend = load('backend').CarplayHDMI()
        writes = []
        proc = SimpleNamespace(poll=lambda:None, stdin=SimpleNamespace(write=writes.append, flush=lambda:None))
        backend.proc = proc
        backend.button(dict(button='next',action='trigger',sequence=1))
        backend.queue[0]['queued_at'] = -100
        backend.notify = lambda *a, **kw: backend.stop_event.set()
        backend.send_inputs(proc)
        self.assertFalse(writes)
        self.assertEqual(backend.take_button_results()[0]['result'], 'Command expired')

    def test_actual_carplay_worker_subscribes_and_reports_unavailable_bridge(self):
        root = Path(__file__).resolve().parents[1]
        manifest = Manifest.load(root/'plugins/carplay', bundled=True)
        with tempfile.TemporaryDirectory() as folder, patch('hlauncher.plugin_host.LOG_DIR', Path(folder)):
            worker = Worker(manifest, 720, 480, lambda **v:None)
            worker.background_enabled = True
            self.host.workers['carplay'] = worker
            try:
                deadline = time.monotonic()+3
                while not worker.button_subscription and time.monotonic() < deadline:
                    self.host.tick()
                    time.sleep(.01)
                self.assertTrue(worker.ready)
                self.assertEqual(worker.button_subscription, frozenset(CARPLAY))
                self.press()
                while self.host.button_pending and time.monotonic() < deadline:
                    self.host.tick()
                    time.sleep(.01)
                self.assertEqual(self.host.button_results['next']['result'], 'CarPlay USB bridge unavailable')
                self.assertIsNone(worker.proc.poll())
            finally:
                self.host.close()
