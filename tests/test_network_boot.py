import subprocess
import sys
import tempfile
from pathlib import Path
import unittest
from hlauncher.network_boot import signal_ui_ready


class NetworkBoot(unittest.TestCase):
    def test_ready_marker_is_idempotent_and_never_truncates_existing_file(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'ready'
            self.assertTrue(signal_ui_ready(path))
            path.write_text('existing')
            self.assertTrue(signal_ui_ready(path))
            self.assertEqual(path.read_text(),'existing')
            self.assertFalse(signal_ui_ready(Path(folder)/'missing'/'ready'))

    def test_early_frame_does_not_load_numpy_and_has_a_framebuffer_fallback(self):
        code='''
from types import SimpleNamespace
from unittest.mock import Mock, patch
from PIL import Image
from hlauncher.display import Framebuffer, encode
import sys
fb=Framebuffer();fb.fd=1;fb.w=2;fb.h=1
fb.kms=SimpleNamespace(present=Mock(),close=Mock())
im=Image.new('RGB',(2,1),(255,0,0))
fb.image_early(im)
assert fb.kms.present.call_args.args[0]==im.tobytes('raw','BGRX')
assert 'numpy' not in sys.modules
fb.kms.present.side_effect=RuntimeError('fixture')
fb.stride=4;fb.xo=fb.yo=0
with patch('hlauncher.display.os.pwrite',return_value=4) as write:
    fb.image_early(im)
    assert write.call_args.args[1]==encode(im)
assert fb.kms is None
'''
        result=subprocess.run([sys.executable,'-c',code],capture_output=True,text=True,
                              cwd=Path(__file__).resolve().parents[1])
        self.assertEqual(result.returncode,0,result.stderr)
