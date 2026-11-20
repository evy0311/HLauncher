import unittest

from hlauncher.adapter_info import AdapterInfo


class AdapterInfoTests(unittest.TestCase):
    def test_capabilities_are_reported_not_inferred_from_model_or_firmware(self):
        info = AdapterInfo()
        info.update(dict(state='dongle_software_version', version='fixture-version\x00'))
        info.update(dict(state='dongle_box_info', settings=dict(
            productType='fixture-product', hwVersion='fixture-hardware',
            DevList=[{'name': 'Private phone'}], btMacAddr='private')))
        self.assertNotIn('aa_support', info.snapshot())
        self.assertEqual(info.snapshot()['firmware'], 'fixture-version')
        self.assertNotIn('Private phone', str(info.snapshot()))
        for report, expected in (('CarPlay,AndroidAuto', 'Reported'),
                                 ('CarPlay; Android-Auto', 'Reported'),
                                 ('CarPlay', 'Not advertised')):
            info.update(dict(state='dongle_box_info', settings={'supportLinkType': report}))
            self.assertEqual(info.snapshot()['aa_support'], expected)

    def test_disconnect_clears_phone_and_reconnect_clears_previous_adapter(self):
        info = AdapterInfo()
        info.update(dict(state='dongle_identity', vendor_id=0x1314, product_id=0x1521))
        info.update(dict(state='dongle_software_version', version='fixture-version'))
        info.update(dict(state='phone_connected', phone_type=5, wifi=1))
        self.assertEqual(info.snapshot()['usb_id'], '1314:1521')
        self.assertEqual(info.snapshot()['protocol'], 'Android Auto')
        self.assertEqual(info.snapshot()['transport'], 'Wireless (reported)')
        info.update(dict(state='phone_disconnected'))
        self.assertNotIn('protocol', info.snapshot())
        self.assertNotIn('transport', info.snapshot())
        self.assertEqual(info.snapshot()['firmware'], 'fixture-version')
        info.update(dict(state='usb_failure'))
        self.assertEqual(info.snapshot(), {})
        info.update(dict(state='dongle_identity', vendor_id=0x1314, product_id=0x1520))
        self.assertNotIn('firmware', info.snapshot())
        info.update(dict(state='waiting_dongle'))
        self.assertEqual(info.snapshot(), {})

    def test_unknown_and_malformed_values_are_bounded_and_never_guessed(self):
        info = AdapterInfo()
        for vendor in (True, -1, 65536, '1314'):
            info.update(dict(state='dongle_identity', vendor_id=vendor, product_id=0x1520))
        self.assertNotIn('usb_id', info.snapshot())
        info.update(dict(state='phone_connected', phone_type=8, wifi=99))
        self.assertEqual(info.snapshot(), {})
        info.update(dict(state='dongle_box_info', settings=['not an object']))
        info.update(dict(state='dongle_software_version', version={'secret': 'value'}))
        self.assertEqual(info.snapshot(), {})
        info.update(dict(state='dongle_software_version', version='x'*500))
        self.assertEqual(len(info.snapshot()['firmware']), 80)
        snapshot = info.snapshot()
        snapshot.clear()
        self.assertTrue(info.snapshot())
