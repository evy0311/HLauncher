"""Early splash rendering must not load the full UI or image-processing stack."""
import subprocess
import sys
from pathlib import Path
import unittest


class BootSplash(unittest.TestCase):
    def test_render_before_heavy_ui_imports(self):
        result=subprocess.run([sys.executable,'-c',
            'from hlauncher.ui.boot_splash import render; import sys; '
            'frame=render((720,480)); assert frame.size==(720,480); '
            'assert frame.mode=="RGB" and frame.getbbox() is None; '
            'assert "hlauncher.ui.controls" not in sys.modules; '
            'assert "hlauncher.ui.home_art" not in sys.modules; '
            'assert "numpy" not in sys.modules'],
            cwd=Path(__file__).resolve().parents[1],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
