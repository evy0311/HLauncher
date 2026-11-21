"""Sparse and partial telemetry must stay honest in the concise Vehicle UI."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

from hlauncher.vehicle_fields import GROUPS, minder_oil_life

ROOT = Path(__file__).resolve().parents[1]


class VehicleDashboard(unittest.TestCase):
    def setUp(self):
        with patch.object(sys, 'path', [str(ROOT/'plugins/vehicle'), str(ROOT/'sdk'), *sys.path]):
            from dashboard import Dashboard
        self.dashboard = Dashboard((720, 480))

    def labels(self, readings, tab):
        dashboard = self.dashboard
        dashboard.navigate(tab=tab)
        dashboard.update(dict(readings=readings, last_updated='Just now', link='Receiving vehicle data'),
                         [], {}, 'menu', oem_color='Red')
        with patch.object(dashboard, 'text', wraps=dashboard.text) as text:
            dashboard.render()
        return [str(call.args[2]) for call in text.call_args_list]

    def test_unknown_warnings_do_not_become_a_clear_health_report(self):
        fields = GROUPS['warnings'][1]
        partial = self.labels({fields[0]: False}, 1)
        self.assertIn('Readings incomplete', partial)
        self.assertNotIn('No active warnings reported', partial)
        complete = self.labels(dict.fromkeys(fields, False), 1)
        self.assertIn('No active warnings reported', complete)
        active = self.labels({fields[0]: True}, 1)
        self.assertIn('1 active', active)

    def test_missing_summary_values_are_omitted_but_zero_is_shown(self):
        labels = self.labels({'75': 0}, 0)
        self.assertIn('Odometer', labels)
        self.assertIn('0', labels)
        self.assertNotIn('Range', labels)
        self.assertNotIn('Coolant', labels)
        self.assertIn('Not reported', labels)


    def test_cluster_minder_code_supplies_the_oil_dial_without_engine_oil_life(self):
        # Synthetic inputs; conversions verified against the original ARM routine.
        self.assertIn('15%', self.labels({'72': 10}, 0))
        self.assertIn('Service due soon', self.labels({'72': 10}, 0))
        self.assertIn('20%', self.labels({'72': 9, '42': 0}, 0))
        self.assertIn('35%', self.labels({'72': 0, '42': 35}, 0))
        self.assertIn('Not reported', self.labels({'72': 15}, 0))
        self.assertIn('0%', self.labels({'72': 14}, 0))

    def test_all_cluster_oil_life_codes_match_original_connect_conversion(self):
        self.assertEqual([minder_oil_life(code) for code in range(16)],
                         [None, 100, 90, 80, 70, 60, 50, 40, 30, 20, 15, 10, 5, 0, 0, None])
        for invalid in (None, True, False, -1, 16, '10', 10.0):
            self.assertIsNone(minder_oil_life(invalid))
