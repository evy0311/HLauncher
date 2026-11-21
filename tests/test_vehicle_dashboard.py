"""Sparse and partial telemetry must stay honest in the concise Vehicle UI."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

from hlauncher.vehicle_fields import FIELD_GROUP, GROUPS, field_label, minder_oil_life

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
        self.assertIn('Odometer (raw)', labels)
        self.assertIn('0', labels)
        self.assertNotIn('Range', labels)
        self.assertNotIn('Coolant', labels)
        self.assertIn('Not reported', labels)


    def test_cluster_minder_code_supplies_the_oil_dial_without_engine_oil_life(self):
        # Synthetic inputs; conversions verified against the original ARM routine.
        self.assertIn('15%', self.labels({'72': 10}, 0))
        self.assertIn('Service due soon', self.labels({'72': 10}, 0))
        self.assertIn('20%', self.labels({'72': 9, '42': 0}, 0))
        self.assertIn('5%', self.labels({'72': 0, '42': 12}, 0))
        self.assertIn('Unavailable', self.labels({'72': 15}, 0))
        self.assertIn('0%', self.labels({'72': 14}, 0))

    def test_all_cluster_oil_life_codes_match_original_connect_conversion(self):
        self.assertEqual([minder_oil_life(code) for code in range(16)],
                         [None, 100, 90, 80, 70, 60, 50, 40, 30, 20, 15, 10, 5, 0, 0, None])
        for invalid in (None, True, False, -1, 16, '10', 10.0):
            self.assertIsNone(minder_oil_life(invalid))


    def test_engine_oil_life_is_a_code_and_missing_distances_are_explicit(self):
        self.assertIn('100%', self.labels({'42': 1}, 0))
        self.assertIn('Unavailable', self.labels({'42': 35}, 0))
        labels = self.labels({}, 0)
        self.assertIn('Odometer (raw)', labels)
        self.assertIn('Minder interval (raw)', labels)
        self.assertIn('Not received', labels)

    def test_cluster_odometer_fallback_and_native_minder_interval(self):
        labels = self.labels({'1009': 123456, '70': -234}, 0)
        self.assertIn('123,456', labels)
        self.assertIn('-234', labels)
        labels = self.labels({'75': 654321, '1009': 123456, '70': 0}, 0)
        self.assertIn('654,321', labels)
        self.assertIn('0', labels)
        self.assertNotIn('123,456', labels)

    def test_field_values_distinguish_no_request_no_receipt_and_unavailable(self):
        dashboard = self.dashboard
        dashboard.update(dict(readings={'42': 10, '72': 12, '77': 1023},
                              requested_fields=['42', '72', '77', '75'], last_updated='Just now'),
                         [], {}, 'menu')
        self.assertEqual(dashboard.value('42'), '15% (code 10)')
        self.assertEqual(dashboard.value('72'), '5% (code 12)')
        self.assertEqual(dashboard.value('75'), 'Not received')
        self.assertEqual(dashboard.value('1009'), 'Not requested')
        self.assertEqual(dashboard.value('77'), 'Unavailable')
        dashboard.readings['42'] = 35
        self.assertEqual(dashboard.value('42'), 'Unavailable (code 35)')
        dashboard.readings['77'] = 123
        self.assertEqual(dashboard.value('77'), '123')  # Native code, not verified Celsius.


    def test_all_reading_fields_are_renderable_and_each_source_has_a_visible_row(self):
        from hlauncher.protocol.vehicle_signals import BY_ID
        from hlauncher.protocol.vehicle_can import decode_records
        from test_vehicle_can import can_data
        from collections import Counter
        numeric = [key for _, fields in GROUPS.values() for key in fields if key.isdecimal()]
        self.assertEqual(Counter(numeric), Counter(map(str, BY_ID)))
        messages = {s['message_id']: s['length'] for info in BY_ID.values() for s in info['sources']}
        records = decode_records(can_data([(mid, bytes([0x55])*length) for mid, length in messages.items()]),
                                 api_ids=tuple(BY_ID))
        values = {key: value for row in records for key, value in row['signals'].items()}
        values.update(vin='TEST-VEHICLE', **{'head-unit': '12345678', 'latitude': 40.0,
                                         'longitude': -75.0, 'brake': False})
        dashboard = self.dashboard
        dashboard.update(dict(readings=values, requested_fields=list(map(str, BY_ID)), last_updated='Synthetic'),
                         [], {}, 'menu')
        visited = set()
        for group, (_, fields) in GROUPS.items():
            if group == 'diagnostics':
                continue
            dashboard.navigate(group, tab=3)
            for page in range((len(fields)+4)//5):
                dashboard.page = page
                with patch.object(dashboard, 'list_row', wraps=dashboard.list_row) as rows:
                    dashboard.render()
                for call in rows.call_args_list:
                    key, label, value = call.args[1:4]
                    visited.add(key)
                    self.assertEqual(label, field_label(key))
                    self.assertTrue(value)
                    self.assertNotEqual(value, 'Not received')
        self.assertEqual(visited, set(FIELD_GROUP)-{'bc-dtc', 'fc-dtc', 'freeze'})
