"""USB inventory includes unsupported adapters and survives hot-unplug."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from hlauncher.diagnostics import collect, collect_usb


class UsbDiagnostics(unittest.TestCase):
    def setUp(self):
        self.temp=self.enterContext(tempfile.TemporaryDirectory())
        self.root=Path(self.temp)

    def device(self,port,vendor,product,name=None):
        path=self.root/port;path.mkdir()
        for key,value in (('idVendor',vendor),('idProduct',product),('product',name)):
            if value is not None:(path/key).write_text(value)
        return path

    def test_all_vendors_hubs_and_unnamed_devices_are_visible(self):
        self.device('usb1','1d6b','0002','Linux root hub')
        self.device('1-2','ABCD','1234','Different adapter\n')
        self.device('1-3','1314','1520')
        (self.root/'1-2:1.0').mkdir()
        result=collect_usb(self.root)
        self.assertIsNone(result['usb_error'])
        self.assertEqual([(d['port'],d['vendor'],d['product'],d['name'])
                          for d in result['usb_devices']],
                         [('1-2','abcd','1234','Different adapter'),
                          ('1-3','1314','1520','USB device'),
                          ('usb1','1d6b','0002','Linux root hub')])

    def test_unplugged_or_incomplete_devices_do_not_break_scan(self):
        self.device('1-1','1314','1520')
        path=self.device('1-2','1314','1521')
        (path/'idProduct').unlink()
        self.device('1-3','oops','1234')
        self.assertEqual(len(collect_usb(self.root)['usb_devices']),1)
        (self.root/'1-1'/'idVendor').unlink()
        self.assertEqual(collect_usb(self.root)['usb_devices'],[])

    def test_unavailable_inventory_is_distinct_from_empty_inventory(self):
        self.assertIsNone(collect_usb(self.root)['usb_error'])
        self.assertTrue(collect_usb(self.root/'missing')['usb_error'])
        with patch.object(Path,'iterdir',side_effect=PermissionError):
            self.assertTrue(collect_usb(self.root)['usb_error'])

    def test_system_report_retains_complete_inventory_and_dongle_summary(self):
        self.device('1-1','1314','1520','Carlinkit')
        self.device('1-2','1234','5678','Other device')
        inventory=collect_usb(self.root)
        with patch('hlauncher.diagnostics.collect_usb',return_value=inventory):
            report=collect()
        self.assertEqual(report['usb_devices'],inventory['usb_devices'])
        self.assertEqual(report['dongles'],[
            {'vendor':'1314','product':'1520','name':'Carlinkit'}])
