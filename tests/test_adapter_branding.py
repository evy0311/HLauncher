"""Verify OEM file delivery and launcher-owned controls without a physical adapter."""
from pathlib import Path
import shutil
import subprocess
from types import SimpleNamespace
import unittest
from unittest.mock import Mock
import test_radio_ui
from hlauncher.config import ROOT


class AdapterBrandingUI(unittest.TestCase):
    setUp=test_radio_ui.RadioUI.setUp
    tearDown=test_radio_ui.RadioUI.tearDown
    def test_adapter_icon_navigation_and_offline_apply(self):
        ui=self.ui;ui.plugin_detail('carplay')
        next(action for _,action in ui.actions if action==ui.adapter_branding_page)()
        self.assertEqual(ui.mode,'adapter_branding')
        self.assertTrue(any(action==ui.plugin_detail for _,action in ui.actions))
        from unittest.mock import patch
        from hlauncher.adapter_branding import BrandingRequests
        with patch.object(ui.host,'request_projection') as start:
            ui.apply_adapter_branding()
            start.assert_called_once_with('carplay',False)
        self.assertTrue(ui.host.branding.pending)
        self.assertTrue(BrandingRequests(ui.host.branding.path).pending)
        request_id=ui.host.branding.data['request_id']
        worker=SimpleNamespace(send=Mock(return_value=True),metrics={},ready=True,proc=SimpleNamespace(pid=123))
        ui.host.workers['carplay']=worker
        try:
            ui.host._branding_tick();ui.host._branding_tick()
            worker.send.assert_called_once_with(type='host.adapter.branding',request_id=request_id)
            self.assertEqual(ui.mode,'adapter_branding')
            ui.host.branding.update(request_id,'transferred')
            self.assertFalse(ui.host.branding.pending)
            self.assertFalse(ui.host.branding.data['verified'])
        finally:ui.host.workers.clear()



class AdapterBrandingProtocol(unittest.TestCase):
    def test_usb_files_and_failure_handling(self):
        if not shutil.which('node'):self.skipTest('Node unavailable')
        if not (ROOT/'plugins/carplay/runtime/usb/vendor/node-carplay/dist/modules/index.js').is_file():
            self.skipTest('Fetched node-CarPlay dependency unavailable')
        subprocess.run(['node',str(ROOT/'tests/adapter_branding.mjs')],check=True,capture_output=True,timeout=20)
