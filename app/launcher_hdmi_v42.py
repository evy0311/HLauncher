"""Functional HDMI launcher; Bluetooth touch routes to test/UI/CarPlay."""

import os, fcntl, struct, time
from array import array
from PIL import Image, ImageDraw, ImageFont
from honda_touch_v28 import pixels
from touch_overlay_v28 import TouchOverlay
from carplay_hdmi_v35 import CarplayHDMI
from audio_meter_v41 import AudioMeter


class Framebuffer:
    def __init__(self):
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
        except Exception:
            os.close(fd)
            raise

    def blit(self, raw):
        self.open()
        if len(raw) != self.w * self.h * 2:
            raise ValueError("frame size mismatch")
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
        if self.tty_fd is not None:
            try:
                fcntl.ioctl(self.tty_fd, 0x4B3A, self.tty_mode)
            finally:
                os.close(self.tty_fd)
                self.tty_fd = None
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None

    def home_badge(self):
        raw = encode(self.badge)
        for y in range(self.badge.height):
            os.pwrite(
                self.fd,
                raw[y * self.badge.width * 2 : (y + 1) * self.badge.width * 2],
                (y + self.yo) * self.stride + self.xo * 2,
            )


def encode(im):
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


class Launcher:
    def __init__(self, event=lambda **kw: None):
        self.carplay_has_frame = False
        self.audio = AudioMeter(event)
        self.audio_tick = 0
        self.event = event
        self.fb = Framebuffer()
        self.overlay = TouchOverlay()
        self.carplay = CarplayHDMI(event)
        self.mode = "home"
        self.press = None
        self.xy = None
        self.last_frame = -1
        self.last_status = -1
        self.pending_start = False

    def launch(self, app_id):
        if app_id not in (
            "com.honda.hondalink.connect",
            "com.honda.hondalink.launcher",
        ):
            return False
        if self.mode == "audio" and self.audio.snapshot().get("call_mode"):
            self.draw()
            return True
        self.show("home")
        return True

    def show(self, mode):
        self.overlay.reset()
        if mode != "audio":
            self.audio.stop()
        # Keep dongle session alive while showing launcher or touch test.
        self.fb.open()
        self.carplay_has_frame = False
        self.mode = mode
        self.press = None
        self.last_frame = -1
        self.last_status = -1
        self.draw()
        if mode == "audio":
            self.audio.start()
        if mode == "carplay":
            self.pending_start = not self.carplay.start(self.fb.w, self.fb.h)
        self.event(state="hdmi_launcher_page", page=mode)

    def font(self, n):
        try:
            return ImageFont.truetype(
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", n
            )
        except OSError:
            return ImageFont.load_default()

    def draw(self, status=""):
        w, h = self.fb.w, self.fb.h
        im = Image.new("RGB", (w, h), (8, 12, 20) if self.mode != "touch" else "black")
        d = ImageDraw.Draw(im)
        if self.mode == "home":
            d.text((28, 25), "HLauncher", font=self.font(28), fill="white")
            d.text(
                (28, 77),
                "Microphone test / CarPlay",
                font=self.font(19),
                fill=(180, 180, 180),
            )
            self.tiles = []
            for i, name in enumerate(["Microphone", "CarPlay"]):
                x = 28 + i * (w - 56) // 2
                box = (x, 150, x + (w - 80) // 2, h - 55)
                self.tiles.append(box)
                d.rounded_rectangle(box, radius=18, fill=(24, 65, 110))
                d.text((x + 12, 175), name, font=self.font(24), fill="white")
        else:
            if self.mode == "audio":
                v = self.audio.snapshot()
                d.text(
                    (95, 18), "Radio microphone test", font=self.font(25), fill="white"
                )
                words = v["status"].split()
                lines = [""]
                for word in words:
                    if len(lines[-1]) + len(word) > 48:
                        lines.append("")
                    lines[-1] += word + " "
                for i, line in enumerate(lines[:3]):
                    d.text((28, 100 + i * 28), line, font=self.font(20), fill="white")
                level = max(0.0, min(1.0, (v["dbfs"] + 80) / 80))
                d.rectangle((28, 210, w - 28, 255), fill=(35, 40, 45))
                if level:
                    d.rectangle(
                        (28, 210, 28 + int((w - 56) * level), 255), fill=(50, 210, 100)
                    )
                d.text(
                    (28, 270),
                    f"RMS: {v['dbfs']:.1f} dBFS    Peak: {v['peak']:.3f}",
                    font=self.font(21),
                    fill="white",
                )
                d.text(
                    (28, 310),
                    f"{v['rate']} Hz  {v['codec']}  {v['bytes']} bytes",
                    font=self.font(19),
                    fill="white",
                )
                d.text(
                    (28, 350),
                    v.get("gate_status", "Speak near the radio microphone."),
                    font=self.font(16),
                    fill="white",
                )
                self.enable_box = (28, h - 62, w - 175, h - 15)
                d.rounded_rectangle(self.enable_box, radius=9, fill=(90, 50, 25))
                d.text(
                    (44, h - 54),
                    "End mic test" if v.get("call_mode") else "Enable mic (60s)",
                    font=self.font(21),
                    fill="white",
                )
                self.retry_box = (w - 150, h - 62, w - 28, h - 15)
                d.rounded_rectangle(self.retry_box, radius=9, fill=(30, 80, 110))
                d.text((w - 132, h - 54), "Retry", font=self.font(21), fill="white")
            elif self.mode == "touch":
                d.text((90, 18), "Touch test", font=self.font(24), fill="white")
            else:
                d.text((28, 115), "CarPlay", font=self.font(30), fill="white")
                # Wrap status for narrow framebuffer.
                words = status.split()
                lines = [""]
                for word in words:
                    if len(lines[-1]) + len(word) > 48:
                        lines.append("")
                    lines[-1] += word + " "
                for i, line in enumerate(lines):
                    d.text(
                        (28, 180 + i * 32),
                        line,
                        font=self.font(21),
                        fill=(225, 225, 225),
                    )
                d.text(
                    (28, h - 65),
                    "Video + touch test; audio not routed",
                    font=self.font(18),
                    fill=(180, 180, 180),
                )
            if self.mode != "carplay" or not self.carplay_has_frame:
                self.fb.badge = Image.new("RGB", (78, 42), (30, 40, 50))
                ImageDraw.Draw(self.fb.badge).text(
                    (7, 8), "Home", font=self.font(19), fill="white"
                )
                im.paste(self.fb.badge, (0, 0))
        self.fb.image(im)

    def update(self, touch):
        self.fb.open()
        c = (
            touch["contacts"][0]
            if touch["contacts"]
            else {"action": "unused", "has_position": False}
        )
        point = pixels(c, self.fb.w, self.fb.h)
        if point:
            self.xy = point
        if c["action"] == "down":
            self.press = point
        if self.mode == "carplay":
            if (
                not self.carplay_has_frame
                and self.press
                and self.press[0] < 78
                and self.press[1] < 42
            ):
                if c["action"] in ("up", "unused"):
                    self.show("home")
                return
            self.carplay.touch(c)
            return
        self.overlay.update(touch)
        if c["action"] in ("up", "unused"):
            start = self.press
            end = self.xy
            self.press = None
            if (
                start
                and end
                and max(abs(start[0] - end[0]), abs(start[1] - end[1])) < 25
            ):
                if self.mode != "home" and start[0] < 78 and start[1] < 42:
                    self.show("home")
                    return
                if self.mode == "audio":
                    box = self.enable_box
                    if box[0] <= start[0] <= box[2] and box[1] <= start[1] <= box[3]:
                        self.audio.enable_test_call()
                        return
                    box = self.retry_box
                    if box[0] <= start[0] <= box[2] and box[1] <= start[1] <= box[3]:
                        self.audio.start()
                        return
                if self.mode == "home":
                    for box, page in zip(self.tiles, ["audio", "carplay"]):
                        if (
                            box[0] <= start[0] <= box[2]
                            and box[1] <= start[1] <= box[3]
                        ):
                            self.show(page)
                            return

    def tick(self):
        if self.mode == "audio":
            if time.monotonic() - self.audio_tick > 0.1:
                self.draw()
                self.audio_tick = time.monotonic()
            return
        if self.mode != "carplay":
            self.overlay.tick()
            return
        if self.carplay.take_host_ui_request():
            self.show("home")
            return
        if self.pending_start and not self.carplay.thread.is_alive():
            self.pending_start = not self.carplay.start(self.fb.w, self.fb.h)
        version, frame, status_version, status = self.carplay.snapshot()
        if frame is not None and version != self.last_frame:
            self.carplay_has_frame = True
            self.fb.blit(frame)
            self.last_frame = version
        elif frame is None and status_version != self.last_status:
            self.carplay_has_frame = False
            self.draw(status)
            self.last_status = status_version

    def close(self):
        self.audio.stop()
        self.carplay.stop()
        self.overlay.close()
        self.fb.close()
