import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from hlauncher.adapter_info import AdapterInfo
from hlauncher.projection_phones import ProjectionPhones
from hlauncher.projection import direct_android_devices


class Phones(unittest.TestCase):
    def test_paired_is_not_connected_and_peer_identity_is_required(self):
        info = AdapterInfo()
        phone = dict(id='02:00:00:00:00:01', name='Fixture phone', type='CarPlay')
        info.update(dict(state='dongle_box_info', settings={'DevList': [phone]}))
        self.assertFalse(info.phone_reports()[0]['connected'])
        info.update(dict(state='phone_connected', phone_type=3, wifi=1))
        self.assertFalse(info.phone_reports()[0]['connected'])
        info.update(dict(state='dongle_box_info', settings=dict(
            btMacAddr=phone['id'], btName=phone['name'], MDLinkType='CarPlay')))
        report = info.phone_reports()[0]
        self.assertTrue(report['connected'])
        self.assertEqual(report['transport'], 'Wireless (reported)')
        self.assertNotIn(phone['id'], json.dumps(report))
        self.assertNotIn(phone['name'], json.dumps(info.snapshot()))
        info.update(dict(state='phone_disconnected'))
        self.assertFalse(info.phone_reports()[0]['connected'])

    def test_names_are_not_identity_and_malformed_records_are_ignored(self):
        info = AdapterInfo()
        for value in (None, [], {'id': 'garbage'}, {'id': '00:00:00:00:00:00'}):
            self.assertIsNone(info.phone(value))
        info.phone(dict(id='02:00:00:00:00:01', name='Same name'))
        info.phone(dict(id='02:00:00:00:00:02', name='Same name'))
        self.assertEqual(len(info.phone_reports()), 2)
        info.update(dict(state='usb_failure'))
        self.assertFalse(info.phone_reports())

    def test_history_survives_restart_without_claiming_a_live_connection(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'phones.json'
            history = ProjectionPhones(path)
            report = dict(id='a'*24, name='Fixture', protocol='CarPlay', transport='Wireless (reported)', connected=True)
            with patch('hlauncher.projection_phones.time.time', return_value=12345):
                history.update([report])
            self.assertTrue(history.snapshot()[0]['connected'])
            with patch('hlauncher.projection_phones.atomic_json') as save:
                history.update([report])
                save.assert_not_called()
            restored = ProjectionPhones(path).snapshot()[0]
            self.assertEqual(restored['last_connected'], 12345)
            self.assertFalse(restored['connected'])
            self.assertFalse(restored['paired'])
            history.update([])
            self.assertFalse(history.snapshot()[0]['connected'])
            self.assertEqual(history.snapshot()[0]['last_connected'], 12345)

    def test_failed_save_is_retried_and_history_is_bounded(self):
        with tempfile.TemporaryDirectory() as folder:
            history = ProjectionPhones(Path(folder)/'phones.json')
            reports = [dict(id=f'{i:024x}', name=f'Phone {i}') for i in range(40)]
            with patch('hlauncher.projection_phones.atomic_json', side_effect=OSError('fixture')):
                with self.assertRaises(OSError):
                    history.update(reports)
            self.assertTrue(history.dirty)
            history.update(reports)
            self.assertFalse(history.dirty)
            self.assertLessEqual(len(history.snapshot()), 32)

    def test_passive_discovery_excludes_dongle_and_unrelated_devices(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for port, vendor, product, label in (
                ('1-1', '1314', '1521', 'Android Auto adapter'),
                ('1-2', '18d1', '2d00', ''),
                ('1-3', '1234', '1234', 'Android phone'),
                ('1-4', '1234', '5678', 'USB camera')):
                path = root/port
                path.mkdir()
                (path/'idVendor').write_text(vendor)
                (path/'idProduct').write_text(product)
                (path/'product').write_text(label)
            self.assertEqual(direct_android_devices(root), {'1-2', '1-3'})
