"""Framebuffer ownership and RGB565 conversion."""

import os, fcntl, struct
from array import array
try:
    import numpy as np
except ImportError:
    np = None


class Framebuffer:
    def __init__(self, event=lambda **values: None):
        self.event = event
        self.kms = None
        self.fd = None
        self.tty_fd = None
        self.tty_mode = None

    def open(self):
        if self.fd is not None:
            return
        fd = os.open("/dev/fb0", os.O_RDWR)
        try:
            v = bytearray(160)
            f = bytearray(80)
            fcntl.ioctl(fd, 0x4600, v, True)
            fcntl.ioctl(fd, 0x4602, f, True)
            self.w, self.h, _, _, self.xo, self.yo, bpp = struct.unpack_from("7I", v)
            self.stride = struct.unpack_from("I", f, 48)[0]
            fields = [struct.unpack_from("3I", v, i) for i in (32, 44, 56)]
            if bpp != 16 or fields != [(11, 5, 0), (5, 6, 0), (0, 5, 0)]:
                raise ValueError("requires RGB565 framebuffer")
            # Suppress fbcon text/cursor while rendering; restore prior mode on exit.
            tty = os.open("/dev/tty1", os.O_RDWR | os.O_NOCTTY)
            try:
                mode = bytearray(4)
                fcntl.ioctl(tty, 0x4B3B, mode, True)
                self.tty_mode = struct.unpack("I", mode)[0]
                fcntl.ioctl(tty, 0x4B3A, 1)  # KDSETMODE KD_GRAPHICS
                self.tty_fd = tty
            except Exception:
                os.close(tty)
                raise
            self.fd = fd
            if os.environ.get("HLAUNCHER_DISPLAY", "drm") != "fbdev":
                try:
                    from .drm import KMSDisplay

                    self.kms = KMSDisplay(self.w, self.h, self.event)
                except (OSError, RuntimeError) as exc:
                    self.event(
                        state="display_backend",
                        backend="fbdev",
                        vsync=False,
                        reason=str(exc),
                    )
            else:
                self.event(
                    state="display_backend",
                    backend="fbdev",
                    vsync=False,
                    reason="Explicit override",
                )
        except Exception:
            os.close(fd)
            raise

    def blit(self, raw):
        self.open()
        if len(raw) != self.w * self.h * 2:
            raise ValueError("frame size mismatch")
        if self.kms is not None:
            try:
                self.kms.present(raw)
                return
            except RuntimeError as exc:
                self.event(state="display_fallback", reason=str(exc))
                self.kms.close()
                self.kms = None
        if self.stride == self.w * 2 and self.xo == 0:
            if os.pwrite(self.fd, raw, self.yo * self.stride) != len(raw):
                raise OSError("short framebuffer write")
        else:
            for y in range(self.h):
                row = raw[y * self.w * 2 : (y + 1) * self.w * 2]
                if os.pwrite(
                    self.fd, row, (y + self.yo) * self.stride + self.xo * 2
                ) != len(row):
                    raise OSError("short framebuffer row write")

    def image(self, im):
        self.blit(encode(im))

    def close(self):
        if self.kms is not None:
            self.kms.close()
            self.kms = None
        if self.tty_fd is not None:
            try:
                fcntl.ioctl(self.tty_fd, 0x4B3A, self.tty_mode)
            finally:
                os.close(self.tty_fd)
                self.tty_fd = None
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None


def encode(im):
    if np is not None:
        rgb = np.asarray(im.convert('RGB'), dtype=np.uint16)
        packed = ((rgb[:, :, 0] >> 3) << 11) | ((rgb[:, :, 1] >> 2) << 5) | (rgb[:, :, 2] >> 3)
        return packed.astype('<u2', copy=False).tobytes()
    a = array(
        "H",
        (
            ((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3)
            for r, g, b in im.convert("RGB").getdata()
        ),
    )
    import sys

    if sys.byteorder != "little":
        a.byteswap()
    return a.tobytes()
