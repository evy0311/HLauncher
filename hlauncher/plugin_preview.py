"""Render the first frame of an author's own plugin to a PNG on a development machine."""

from array import array
from dataclasses import replace
from pathlib import Path
import sys
import tempfile
import time

from PIL import Image

from .catalog import Manifest
from .plugin_host import Worker
from .plugin_packages import unpack
from .plugins import validate_external


def preview(source, output):
    with tempfile.TemporaryDirectory(prefix='hlauncher-preview-') as temporary:
        scratch = Path(temporary)
        if source.is_dir():
            manifest = Manifest.load(source)
        else:
            payload = scratch / 'plugin'
            payload.mkdir()
            manifest = unpack(source, payload)
        validate_external(manifest)
        # This author tool intentionally executes local code as the developer.
        worker = Worker(replace(manifest, bundled=True), 720, 480, lambda **fields: None,
                        log_dir=scratch)
        try:
            worker.send(type='host.activate', visible=True)
            deadline = time.monotonic() + 8
            while time.monotonic() < deadline and worker.proc.poll() is None:
                worker.drain()
                worker.read()
                frame = worker.take_frame()
                if frame is not None:
                    pixels = array('H')
                    pixels.frombytes(frame)
                    if sys.byteorder != 'little':
                        pixels.byteswap()
                    rgb = bytearray()
                    for pixel in pixels:
                        rgb.extend(((pixel >> 11) * 255 // 31,
                                    ((pixel >> 5) & 63) * 255 // 63,
                                    (pixel & 31) * 255 // 31))
                    Image.frombytes('RGB', (720, 480), bytes(rgb)).save(output, format='PNG')
                    return
                time.sleep(.01)
            raise ValueError('Plugin did not draw a preview frame')
        except EOFError as exc:
            raise ValueError('Plugin exited before drawing a preview frame') from exc
        finally:
            worker.close()
