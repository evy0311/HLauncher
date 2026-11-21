"""Sparse and partial telemetry must stay honest in the concise Vehicle UI."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

from hlauncher.vehicle_fields import GROUPS

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
