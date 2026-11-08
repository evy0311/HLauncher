"""Bundled OBD renderer; shared radio chrome stays in the UI package."""
from pathlib import Path
import sys
import numpy as np
from hlauncher_sdk.theme import dither_rgb565

# Built-in plugin only: use the same artwork and typography as the host.
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from hlauncher.ui.obd_dashboard import Dashboard


__all__=['Dashboard','encode']


def encode(image):
    rgb_array = np.asarray(dither_rgb565(image), dtype=np.uint16)
    return (((rgb_array[:,:,0]>>3)<<11)|((rgb_array[:,:,1]>>2)<<5)|(rgb_array[:,:,2]>>3)).astype('<u2').tobytes()
