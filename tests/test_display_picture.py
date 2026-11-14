"""Native UI previews, untouched plugin frames, and exact calibration stimuli."""
import struct
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from PIL import Image
from hlauncher.display import Framebuffer, adjust_image, encode
from sdk.hlauncher_sdk.picture import DEFAULTS, NEUTRAL


class DisplayPicture(unittest.TestCase):
    def framebuffer(self):
        fb=Framebuffer();fb.fd=1;fb.w=3;fb.h=1
        fb.kms=SimpleNamespace(present=Mock(),close=Mock())
        return fb

    def test_raw_video_is_untouched_even_with_controls_and_legacy_inset(self):
        fb=self.framebuffer();fb.picture_inset=True
        fb.set_picture(dict(saturation=0,contrast=75,brightness=10))
        raw=struct.pack('<3H',0,0xffff,0xf800)
        with patch('hlauncher.display.adjust_image') as transform:
            fb.blit(raw)
        self.assertIs(fb.kms.present.call_args.args[0],raw)
        transform.assert_not_called()

    def test_ui_preview_applies_defaults_and_neutral_preserves_pixels(self):
        fb=self.framebuffer()
        im=Image.new('RGB',(3,1));im.putdata([(0,0,0),(255,255,255),(255,0,0)])
        original=encode(im);values=dict(DEFAULTS,saturation=0)
        fb.set_picture(values);fb.image(im)
        expected=encode(adjust_image(im,values))
        self.assertNotEqual(expected,original)
        self.assertEqual(fb.kms.present.call_args.args[0],expected)
        fb.set_picture(DEFAULTS);fb.image(im)
        self.assertEqual(fb.kms.present.call_args.args[0],encode(adjust_image(im,DEFAULTS)))
        self.assertNotEqual(fb.kms.present.call_args.args[0],original)
        fb.set_picture(NEUTRAL);fb.image(im)
        self.assertEqual(fb.kms.present.call_args.args[0],original)

    def test_exact_frames_and_calibration_bypass(self):
        fb=self.framebuffer();fb.set_picture(dict(DEFAULTS,brightness=10))
        im=Image.new('RGB',(3,1));im.putdata([(0,0,0),(128,128,128),(255,255,255)])
        fb.image_exact(im);raw=fb.kms.present.call_args.args[0]
        self.assertEqual([raw[i] for i in (0,4,8)],[26,154,255])
        fb.image_test(im);raw=fb.kms.present.call_args.args[0]
        self.assertEqual([raw[i] for i in (0,4,8)],[0,128,255])
        fb.image_test(im,exact=False)
        self.assertEqual(fb.kms.present.call_args.args[0],encode(im))

    def test_exact_fallback_applies_controls_once(self):
        fb=self.framebuffer();fb.stride=6;fb.xo=0;fb.yo=0
        fb.set_picture(dict(DEFAULTS,contrast=75))
        fb.kms.present.side_effect=RuntimeError('test failure')
        im=Image.new('RGB',(3,1),(255,255,255))
        with patch('hlauncher.display.os.pwrite',return_value=6) as write:
            self.assertFalse(fb.image_exact(im))
        self.assertEqual(write.call_args.args[1],encode(adjust_image(im,fb.picture)))

if __name__=='__main__':unittest.main()
