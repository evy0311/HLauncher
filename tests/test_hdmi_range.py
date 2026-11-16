"""Exact calibration pixels, real modeset requests and explicit saved defaults."""
from pathlib import Path
import ctypes as C
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch,Mock
from PIL import Image
from hlauncher.display import Framebuffer
from hlauncher.hdmi_calibration import HDMISettings,broadcast_rgb,commit_range,startup_range
import test_radio_ui


class HDMI(unittest.TestCase):
    def test_exact_test_pixels_bypass_rgb565_quantization(self):
        fb=Framebuffer();fb.fd=1;fb.kms=SimpleNamespace(present=Mock())
        image=Image.new('RGB',(3,1));image.putdata([(235,235,235),(239,239,239),(251,251,251)])
        self.assertTrue(fb.image_test(image))
        raw=fb.kms.present.call_args.args[0]
        self.assertEqual(len(raw),12)
        self.assertEqual([tuple(raw[i:i+3]) for i in (0,4,8)],[(235,235,235),(239,239,239),(251,251,251)])
    def test_atomic_commit_allows_the_required_modeset_and_frees_request(self):
        lib=SimpleNamespace(drmSetClientCap=Mock(return_value=0),drmModeAtomicAlloc=Mock(return_value=123),
             drmModeAtomicAddProperty=Mock(return_value=0),drmModeAtomicCommit=Mock(return_value=0),drmModeAtomicFree=Mock())
        kms=SimpleNamespace(fd=7,connector=C.c_uint32(42),lib=lib)
        commit_range(kms,9,1)
        lib.drmModeAtomicAddProperty.assert_called_once_with(123,42,9,1)
        lib.drmModeAtomicCommit.assert_called_once_with(7,123,0x400,None)
        lib.drmModeAtomicFree.assert_called_once_with(123)
        lib.drmModeAtomicCommit.return_value=-1
        with self.assertRaises(OSError):commit_range(kms,9,2)
        self.assertEqual(lib.drmModeAtomicFree.call_count,2)
    def test_readback_failure_is_not_a_success(self):
        kms=SimpleNamespace(fd=1,io_lock=threading.RLock())
        with patch('hlauncher.hdmi_calibration.properties',return_value={'Broadcast RGB':(9,2)}),patch('hlauncher.hdmi_calibration.commit_range'):
            with self.assertRaisesRegex(RuntimeError,'readback'):broadcast_rgb(kms,1)
    def test_native_color_probe_reports_actual_crtc_capabilities_and_frees_objects(self):
        from hlauncher.hdmi_calibration import native_color_status,ObjectProperties,Property
        for names,values in ((('GAMMA_LUT_SIZE','CTM'),(256,0)), ((),())):
            with self.subTest(names=names):
                ids=(C.c_uint32*len(names))(*range(1,len(names)+1))
                numbers=(C.c_uint64*len(values))(*values)
                obj=ObjectProperties(len(names),ids,numbers)
                props=[Property(name=name.encode()) for name in names]
                lib=SimpleNamespace(
                    drmModeObjectGetProperties=Mock(return_value=C.pointer(obj)),
                    drmModeFreeObjectProperties=Mock(),
                    drmModeGetProperty=Mock(side_effect=[C.pointer(p) for p in props]),
                    drmModeFreeProperty=Mock())
                kms=SimpleNamespace(fd=7,lib=lib,original=SimpleNamespace(crtc_id=42))
                status=native_color_status(kms)
                self.assertEqual(status,dict(available=True,ctm=bool(names),
                    gamma_lut_size=256 if names else 0,degamma_lut_size=0))
                lib.drmModeObjectGetProperties.assert_called_once_with(7,42,0xcccccccc)
                self.assertEqual(lib.drmModeFreeProperty.call_count,len(names))
                lib.drmModeFreeObjectProperties.assert_called_once()

    def test_saved_range_survives_a_new_settings_instance(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'hdmi.json';a=HDMISettings(path);self.assertEqual(a.value,2)
            a.save(1);self.assertEqual(HDMISettings(path).value,1)
            with self.assertRaises(ValueError):a.save(True)

    def test_saved_ui_choice_wins_over_legacy_environment_default(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'hdmi.json'
            self.assertEqual(startup_range(path,{'HLAUNCHER_HDMI_RGB':'full'}),'full')
            HDMISettings(path).save(2)
            self.assertEqual(startup_range(path,{'HLAUNCHER_HDMI_RGB':'full'}),'limited')


class PreviewUI(unittest.TestCase):
    setUp=test_radio_ui.RadioUI.setUp
    tearDown=test_radio_ui.RadioUI.tearDown
    def test_test_controls_change_only_the_chart_and_buffer(self):
        from hlauncher.ui.pages import hdmi
        ui=self.ui;before=ui.prefs.path.read_bytes()
        ui.mode='hdmi_test';ui.fb.image_exact=Mock(side_effect=ui.fb.image)
        hdmi(ui);self.assertEqual(ui.fb.image_exact.call_count,1)
        self.assertEqual(ui.fb.last.getpixel((40,150)),(0,0,0))
        ui.toggle_hdmi_test('levels')
        self.assertEqual(ui.fb.last.getpixel((40,150)),(16,16,16))
        self.assertEqual(ui.fb.last.getpixel((680,150)),(235,235,235))
        self.assertEqual(ui.fb.last.getpixel((152,350)),(222,229,215))
        calls=ui.fb.image_exact.call_count;ui.toggle_hdmi_test('buffer')
        self.assertEqual(ui.fb.image_exact.call_count,calls)
        self.assertFalse(ui.hdmi_test_exact)
        self.assertEqual(ui.prefs.path.read_bytes(),before)
        self.assertFalse(ui.hdmi_settings.path.exists())
        diagnostic=__import__('json').loads((self.folder/'hdmi-diagnostics.json').read_text())
        self.assertEqual(diagnostic['requested_buffer'],'RGB565')
        self.assertEqual(diagnostic['test_levels'],'inset')

    def test_reopening_test_resets_comparisons_without_saving_them(self):
        ui=self.ui;ui.hdmi_test_exact=False;ui.hdmi_test_inset=True
        with patch('hlauncher.hdmi_calibration.broadcast_rgb',return_value=2):ui.hdmi_calibration()
        self.assertTrue(ui.hdmi_test_exact);self.assertFalse(ui.hdmi_test_inset)
        self.assertFalse(ui.hdmi_settings.path.exists())

    def test_full_range_reference_is_not_limited_to_extreme_shades(self):
        from hlauncher.ui.pages import hdmi
        hdmi(self.ui)
        image=self.ui.fb.last
        for i,value in enumerate((0,32,64,96,128,160,192,224,255)):
            x=24+(2*i+1)*672//18
            self.assertEqual(image.getpixel((x,150)),(value,)*3)
        self.assertEqual(image.getpixel((40,330)),(192,0,0))
        self.assertEqual(image.getpixel((152,330)),(0,192,0))

    def test_back_discards_preview_save_keeps_it(self):
        ui=self.ui;value=[2]
        def setting(kms,selected=None):
            if selected is not None:value[0]=selected
            return value[0]
        with patch('hlauncher.hdmi_calibration.broadcast_rgb',side_effect=setting):
            ui.hdmi_calibration();ui.set_hdmi_range(1)
            self.assertEqual(value[0],1)
            ui.color_settings();self.assertEqual(value[0],2)
            self.assertFalse(ui.hdmi_settings.path.exists())
            ui.hdmi_calibration();ui.set_hdmi_range(1);ui.save_hdmi_range()
            self.assertEqual(ui.mode,'colors');self.assertEqual(value[0],1)
            self.assertEqual(HDMISettings(ui.hdmi_settings.path).value,1)
