"""Final-output compensation reaches UI/video, persists, and is not doubled in tests."""
import struct
import tempfile
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch
from PIL import Image
from hlauncher.display import Framebuffer,inset_rgb565
from hlauncher.hdmi_calibration import HDMISettings


class DisplayPicture(unittest.TestCase):
    def framebuffer(self):
        fb=Framebuffer();fb.fd=1;fb.w=3;fb.h=1;fb.picture_inset=True
        fb.kms=SimpleNamespace(present=Mock(),close=Mock())
        return fb

    def test_raw_plugin_frames_and_ui_frames_receive_the_same_mapping(self):
        fb=self.framebuffer();raw=struct.pack('<3H',0,0xffff,0xf800)
        fb.blit(raw)
        self.assertEqual(fb.kms.present.call_args.args[0],inset_rgb565(raw))
        black,white,red=struct.unpack('<3H',inset_rgb565(raw))
        self.assertEqual(black,(2<<11)|(4<<5)|2)
        self.assertEqual(white,(29<<11)|(58<<5)|29)
        self.assertEqual(red,(29<<11)|(4<<5)|2)
        im=Image.new('RGB',(3,1));im.putdata([(0,0,0),(255,255,255),(255,0,0)])
        fb.image(im);self.assertEqual(fb.kms.present.call_args.args[0],inset_rgb565(raw))
        fb.picture_inset=False;fb.blit(raw);self.assertEqual(fb.kms.present.call_args.args[0],raw)

    def test_exact_frames_get_one_mapping_and_calibration_bypasses_it(self):
        fb=self.framebuffer();im=Image.new('RGB',(3,1));im.putdata([(0,0,0),(128,128,128),(255,255,255)])
        fb.image_exact(im);raw=fb.kms.present.call_args.args[0]
        self.assertEqual([raw[i] for i in (0,4,8)],[16,126,235])
        fb.image_test(im);raw=fb.kms.present.call_args.args[0]
        self.assertEqual([raw[i] for i in (0,4,8)],[0,128,255])
        fb.image_test(im,exact=False)
        from hlauncher.display import encode
        self.assertEqual(fb.kms.present.call_args.args[0],encode(im))

    def test_exact_fallback_does_not_double_apply_compensation(self):
        fb=self.framebuffer();fb.stride=6;fb.xo=0;fb.yo=0
        fb.kms.present.side_effect=RuntimeError('test failure')
        im=Image.new('RGB',(3,1),(255,255,255))
        from hlauncher.display import encode
        with patch('hlauncher.display.os.pwrite',return_value=6) as write:
            self.assertFalse(fb.image_exact(im))
        self.assertEqual(write.call_args.args[1],inset_rgb565(encode(im)))

    def test_scalar_lookup_matches_accelerated_lookup_for_every_pixel(self):
        raw=struct.pack('<65536H',*range(65536));accelerated=inset_rgb565(raw)
        with patch('hlauncher.display.np',None):self.assertEqual(inset_rgb565(raw),accelerated)

    def test_saved_inset_and_range_preserve_each_other_after_reload(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'hdmi-output.json';a=HDMISettings(p)
            self.assertFalse(a.picture_inset)
            a.save(2);a.save_picture_inset(True)
            b=HDMISettings(p);self.assertTrue(b.picture_inset);self.assertEqual(b.value,2)
            b.save(1);self.assertTrue(HDMISettings(p).picture_inset)
            b.save_picture_inset(False);self.assertEqual(HDMISettings(p).value,1)
            self.assertFalse(HDMISettings(p).picture_inset)

if __name__=='__main__':unittest.main()
