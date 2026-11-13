import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from hlauncher.config import Preferences
from hlauncher.recovery import Maintenance
from hlauncher.setup_state import SetupState
from hlauncher.wifi_power import WifiPower, hold_at_boot


class WifiPowerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.now = 0
        self.calls = []
        self.connections = ''
        self.set_counters(0, 0)
        self.power = WifiPower(self.run_command, lambda: self.now, self.folder)

    def set_counters(self, received, sent):
        (self.folder/'rx_bytes').write_text(str(received))
        (self.folder/'tx_bytes').write_text(str(sent))

    def run_command(self, args, **kwargs):
        self.calls.append(args)
        if args[0] == 'ip':
            return SimpleNamespace(stdout=json.dumps([{'addr_info': [{'local': '192.168.1.42'}]}]))
        return SimpleNamespace(stdout=self.connections if args[0] == 'ss' else '')

    def test_sleep_tracks_traffic_and_waits_for_active_ssh(self):
        self.assertEqual(self.power.tick('sleep'), 'on')
        self.now = 179
        self.set_counters(8000, 100)
        self.assertEqual(self.power.tick('sleep'), 'on')
        self.now = 358
        self.assertEqual(self.power.tick('sleep'), 'on')
        self.now = 359
        self.connections = '0 0 [::ffff:192.168.1.42]:22 [::ffff:192.168.1.2]:40000\n'
        self.assertEqual(self.power.tick('sleep'), 'on')
        self.now = 539
        self.connections = '0 0 192.168.1.43:22 192.168.1.2:40000\n'
        self.assertEqual(self.power.tick('sleep'), 'asleep')
        self.assertEqual(self.calls[-1], ['nmcli', 'radio', 'wifi', 'off'])
        self.assertEqual(self.power.tick('sleep'), 'asleep')
        self.power.select('sleep')
        self.assertEqual(self.power.tick('sleep'), 'on')

    def test_setup_and_updates_postpone_sleep(self):
        self.power.hotspot_started()
        for now in (180, 360):
            self.now = now
            self.assertEqual(self.power.tick('sleep', setup_hotspot=True), 'on')
        self.now = 540
        self.assertEqual(self.power.tick('sleep', updating=True), 'on')
        self.now = 720
        self.assertEqual(self.power.tick('sleep'), 'asleep')

    def test_maintenance_saves_mode_and_separate_boot_delay(self):
        maintenance = Maintenance(SetupState(self.folder), self.run_command)
        settings = self.folder/'settings.json'
        self.assertEqual(Preferences(settings).data['wifi_power'], 'on')
        maintenance.perform({'operation': 'wifi_power', 'mode': 'off'})
        self.assertEqual(self.calls[-1], ['nmcli', 'radio', 'wifi', 'off'])
        maintenance.perform({'operation': 'wifi_boot', 'enabled': True})
        prefs = Preferences(settings)
        self.assertTrue(prefs.data['wifi_delay_boot'])
        self.assertEqual(prefs.data['wifi_power'], 'off')
        maintenance.perform({'operation': 'wifi_power', 'mode': 'sleep'})
        self.assertTrue(Preferences(settings).data['wifi_delay_boot'])
        self.assertEqual(Preferences(settings).data['wifi_power'], 'sleep')

    def test_boot_hold_only_blocks_before_networkmanager(self):
        marker = self.folder/'boot-hold'
        prefs = SimpleNamespace(data={'wifi_power': 'on', 'wifi_delay_boot': True})
        with patch('hlauncher.wifi_power.BOOT_HOLD', marker), patch('hlauncher.config.Preferences', return_value=prefs), \
                patch('hlauncher.storage.execute', return_value=SimpleNamespace(stdout='inactive')) as run:
            hold_at_boot()
            self.assertTrue(marker.exists())
            run.assert_called_with(['rfkill', 'block', 'wifi'], timeout=3)
            marker.unlink()
            run.reset_mock()
            run.return_value.stdout = 'active'
            hold_at_boot()
            self.assertFalse(marker.exists())
            self.assertEqual(run.call_count, 1)
