"""VIN-driven Home artwork, saved overrides and startup identity delivery."""
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from hlauncher.config import Preferences
from hlauncher.launcher import Launcher
from hlauncher.protocol_diagnostics import ProtocolDiagnostics
from hlauncher.vehicle_models import MODELS, icon_for_model, model_from_vin
import test_vehicle_can as vehicle_fixture
from test_vehicle_can import can_data, incoming
from hlauncher.protocol.vehicle_can import VIN_ID


def vin(code, serial='123456'):
    return f'2HG{code}E50EH{serial}'


class VehicleModels(unittest.TestCase):
    def test_supported_civic_variants_and_invalid_identity(self):
        for code, model in MODELS.items():
            with self.subTest(code=code):
                self.assertEqual(model_from_vin(vin(code)), code)
                self.assertEqual(model_from_vin(vin(code).lower() + '\0\0'), code)
                self.assertEqual(icon_for_model(code), 'vehicle-coupe' if model.body == 'coupe' else 'vehicle')
        for value in (None, '', 'FG4', vin('ZZ9'), 'XXX' + vin('FG4')[3:], vin('FG4')[:-1], vin('FG4').replace('E', 'I')):
            self.assertIsNone(model_from_vin(value))
        self.assertEqual(icon_for_model(None), 'vehicle')

    def test_encrypted_startup_vin_reaches_persistent_identity_without_vehicle_page(self):
        fixture = vehicle_fixture.VehicleCAN()
        probe = fixture.probe()
        probe.vehicle_scope = lambda: 'driving_identity'
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'vehicle.json'
            monitor = ProtocolDiagnostics(vehicle_path=path)
            self.addCleanup(monitor.close)
            monitor.observe(dict(state='connected', uuid='test-cafe', device='radio'))
            events, _ = fixture.authenticate(probe)
            queued = [event for event in events if event['state'] == 'honda_can_subscription_queued']
            self.assertIn(VIN_ID, queued[0]['can_ids'])
            for event in events:
                monitor.observe(event)
            key = probe.vehicle_subscription.keys[257]
            raw = can_data([(VIN_ID, vin('FG4').encode() + b'\0\0')], key=key)
            events, _ = probe.feed(incoming(257, 0xC1, raw))
            for event in events:
                monitor.observe(event)
            self.assertEqual(monitor.vehicle_vin(live=True), vin('FG4'))
            self.assertIsNone(monitor.vehicle_feed_at)
            monitor.save_last_vehicle(force=True)
            restored = ProtocolDiagnostics(vehicle_path=path)
            self.addCleanup(restored.close)
            self.assertEqual(restored.vehicle_vin(), vin('FG4'))
            self.assertIsNone(restored.vehicle_vin(live=True))

    def test_model_override_survives_reboot_same_vin_and_new_vin_replaces_it(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'settings.json'
            ui = Launcher.__new__(Launcher)
            ui.prefs = Preferences(path)
            ui.protocols = SimpleNamespace(vehicle_vin=Mock(return_value=vin('FG4')))
            ui.draw = Mock()
            ui.event = Mock()
            ui.mode = 'home'
            ui.sync_vehicle_model()
            self.assertEqual(Preferences(path).data['vehicle_model'], 'FG4')
            self.assertEqual(ui.vehicle_icon(), 'vehicle-coupe')
            ui.set_vehicle_model('FB6')
            ui.prefs = Preferences(path)  # Reboot with the same VIN and saved override.
            ui.sync_vehicle_model()
            self.assertEqual(ui.vehicle_icon(), 'vehicle')
            self.assertEqual(ui.prefs.data['vehicle_model'], 'FB6')
            ui.protocols.vehicle_vin.return_value = None
            ui.sync_vehicle_model()
            self.assertEqual(ui.prefs.data['vehicle_model'], 'FB6')
            ui.protocols.vehicle_vin.return_value = vin('FG3', '654321')
            ui.sync_vehicle_model()
            self.assertEqual(Preferences(path).data['vehicle_model'], 'FG3')
            self.assertEqual(ui.vehicle_icon(), 'vehicle-coupe')
            # A new unsupported Honda VIN cannot inherit the previous coupe.
            ui.protocols.vehicle_vin.return_value = vin('ZZ9')
            ui.sync_vehicle_model()
            self.assertEqual(ui.vehicle_icon(), 'vehicle')

    def test_invalid_saved_choice_and_failed_save_preserve_preferences(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'settings.json'
            path.write_text(json.dumps({'vehicle_model': ['FG4'], 'vehicle_model_vin': 12}))
            prefs = Preferences(path)
            self.assertEqual(prefs.data['vehicle_model'], 'auto')
            self.assertIsNone(prefs.data['vehicle_model_vin'])
            ui = Launcher.__new__(Launcher)
            ui.prefs, ui.event = prefs, Mock()
            with patch.object(prefs, 'save', side_effect=OSError('Read-only storage')):
                self.assertFalse(ui.save_vehicle_model(dict(vehicle_model='FG4', vehicle_model_vin=vin('FG4'))))
            self.assertEqual(prefs.data['vehicle_model'], 'auto')
            self.assertIsNone(prefs.data['vehicle_model_vin'])
