"""Framebuffer ownership and RGB565 conversion."""

import os, fcntl, struct
from array import array
from functools import lru_cache
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
        self.picture_inset = False

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
            from .hdmi_calibration import HDMISettings
            self.picture_inset=HDMISettings().picture_inset
            self.event(state='display_picture',inset=self.picture_inset)
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

    def blit(self, raw, *, apply_picture=True):
        self.open()
        if len(raw) != self.w * self.h * 2:
            raise ValueError("frame size mismatch")
        if apply_picture and self.picture_inset:raw=inset_rgb565(raw)
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

    def image_exact(self,im, *, apply_picture=True):
        """Keep all 8 bits per channel on the HDMI calibration screen only."""
        self.open()
        if self.kms is None:
            self.blit(encode(im),apply_picture=apply_picture);return False
        try:
            rgb=im.convert('RGB')
            if apply_picture and self.picture_inset:rgb=rgb.point(INSET_CHANNEL*3)
            self.kms.present(rgb.tobytes('raw','BGRX'))
            return True
        except RuntimeError as exc:
            self.event(state='display_fallback',reason=str(exc))
            self.kms.close();self.kms=None
            self.blit(encode(im),apply_picture=apply_picture);return False

    def image_test(self,im, *, exact=True):
        """Calibration owns its stimulus; do not apply the global inset twice."""
        if exact:return self.image_exact(im,apply_picture=False)
        self.blit(encode(im),apply_picture=False);return False

    def close(self):
        if self.kms is not None:
            self.kms.close()
            self.kms = None
        if self.tty_fd is not None:
            try:
                fcntl.ioctl(self.tty_fd, 0x4B3A, self.tty_mode)
            except OSError as exc:
                import errno
                if exc.errno not in (errno.EIO, errno.ENODEV, errno.ENXIO): raise
            finally:
                os.close(self.tty_fd)
                self.tty_fd = None
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None


INSET_CHANNEL=tuple(16+(v*219+127)//255 for v in range(256))


@lru_cache(maxsize=1)
def inset_table():
    """One final-output lookup for every RGB565 value; no video decoder changes."""
    five=[(16+(v*219+15)//31)>>3 for v in range(32)]
    six=[(16+(v*219+31)//63)>>2 for v in range(64)]
    return array('H',((five[v>>11]<<11)|(six[(v>>5)&63]<<5)|five[v&31] for v in range(65536)))


def inset_rgb565(raw):
    table=inset_table()
    if np is not None:
        source=np.frombuffer(raw,dtype='<u2')
        return np.frombuffer(table,dtype=np.uint16)[source].astype('<u2',copy=False).tobytes()
    import sys
    source=array('H');source.frombytes(raw)
    if sys.byteorder!='little':source.byteswap()
    result=array('H',(table[v] for v in source))
    if sys.byteorder!='little':result.byteswap()
    return result.tobytes()


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
