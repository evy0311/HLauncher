"""Latest-position framebuffer overlay; no input injection or protocol changes."""

import os, fcntl, struct, time
from array import array
from PIL import Image, ImageDraw
from honda_touch_v28 import pixels


class TouchOverlay:
    def __init__(self):
        self.fd = None
        self.position = None
        self.release_at = None
        self.last_box = None
        self.signature = None
        self.last_input = 0
        self.enabled = True

    def reset(self):
        self.close()
        self.enabled = True

    def close(self):
        if self.fd is not None:
            os.close(self.fd)
        self.fd = None
        self.position = None
        self.last_box = None
        self.signature = None

    def open(self):
        if self.fd is not None:
            return
        fd = os.open("/dev/fb0", os.O_RDWR)
        try:
            v = bytearray(160)
            fix = bytearray(80)
            fcntl.ioctl(fd, 0x4600, v, True)
            fcntl.ioctl(fd, 0x4602, fix, True)
            self.w, self.h, _, _, self.xo, self.yo, bpp = struct.unpack_from("7I", v)
            self.stride = struct.unpack_from("I", fix, 48)[0]
            self.fields = [struct.unpack_from("3I", v, o) for o in (32, 44, 56)]
            if bpp != 16 or self.fields != [(11, 5, 0), (5, 6, 0), (0, 5, 0)]:
                raise ValueError("overlay requires tested RGB565 framebuffer")
            rows = [
                os.pread(fd, self.w * 2, (y + self.yo) * self.stride + self.xo * 2)
                for y in range(self.h)
            ]
            if any(len(r) != self.w * 2 for r in rows):
                raise ValueError("short framebuffer read")
            self.base = Image.frombytes(
                "RGB", (self.w, self.h), b"".join(rows), "raw", "BGR;16"
            )
            self.fd = fd
        except Exception:
            os.close(fd)
            raise

    def update(self, touch):
        if not self.enabled:
            return
        self.open()
        now = time.monotonic()
        self.last_input = now
        # Primary slot only for this single-circle proof. Slot2 is still decoded/logged.
        primary = touch["contacts"][0] if touch["contacts"] else None
        if primary and primary["has_position"]:
            self.position = pixels(primary, self.w, self.h)
            self.release_at = None
        elif self.position is not None and self.release_at is None:
            self.release_at = now

    def tick(self):
        if not self.enabled or self.fd is None:
            return
        now = time.monotonic()
        if (
            self.position is not None
            and self.release_at is None
            and now - self.last_input > 5
        ):
            self.release_at = now
        alpha = (
            1.0
            if self.release_at is None
            else max(0.0, 1.0 - (now - self.release_at) / 1.0)
        )
        sig = (self.position, round(alpha * 30))
        if sig == self.signature:
            return
        self.signature = sig
        box = None
        if self.position is not None and alpha > 0:
            x, y = self.position
            r = 39
            box = (
                max(0, x - r),
                max(0, y - r),
                min(self.w, x + r + 1),
                min(self.h, y + r + 1),
            )
        dirty = box
        if self.last_box:
            old = self.last_box
            dirty = (
                old
                if dirty is None
                else (
                    min(old[0], dirty[0]),
                    min(old[1], dirty[1]),
                    max(old[2], dirty[2]),
                    max(old[3], dirty[3]),
                )
            )
        if dirty:
            patch = self.base.crop(dirty)
            if box:
                over = Image.new("RGBA", patch.size)
                d = ImageDraw.Draw(over)
                x, y = self.position
                cx = x - dirty[0]
                cy = y - dirty[1]
                d.ellipse(
                    (cx - 36, cy - 36, cx + 36, cy + 36),
                    outline=(0, 0, 0, round(220 * alpha)),
                    width=8,
                )
                d.ellipse(
                    (cx - 32, cy - 32, cx + 32, cy + 32),
                    outline=(0, 255, 255, round(255 * alpha)),
                    width=4,
                )
                patch = Image.alpha_composite(patch.convert("RGBA"), over).convert(
                    "RGB"
                )
            data = array(
                "H",
                (
                    ((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3)
                    for r, g, b in patch.getdata()
                ),
            )
            import sys

            if sys.byteorder != "little":
                data.byteswap()
            raw = data.tobytes()
            width = patch.width
            for y in range(patch.height):
                row = raw[y * width * 2 : (y + 1) * width * 2]
                off = (y + dirty[1] + self.yo) * self.stride + (dirty[0] + self.xo) * 2
                if os.pwrite(self.fd, row, off) != len(row):
                    raise OSError("short framebuffer write")
        self.last_box = box
