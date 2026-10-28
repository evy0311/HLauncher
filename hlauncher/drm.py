"""RGB565 KMS buffers, presented on vertical blank by a dedicated thread."""

import ctypes as C
import ctypes.util
import errno
import fcntl
import mmap
import os
from pathlib import Path
import select
import struct
import threading
import time

U32 = C.c_uint32
P32 = C.POINTER(U32)


class Mode(C.Structure):
    _fields_ = (
        [("clock", U32)]
        + [
            (name, C.c_uint16)
            for name in (
                "hdisplay",
                "hsync_start",
                "hsync_end",
                "htotal",
                "hskew",
                "vdisplay",
                "vsync_start",
                "vsync_end",
                "vtotal",
                "vscan",
            )
        ]
        + [("vrefresh", U32), ("flags", U32), ("type", U32), ("name", C.c_char * 32)]
    )


class Resources(C.Structure):
    _fields_ = [
        ("count_fbs", C.c_int),
        ("fbs", P32),
        ("count_crtcs", C.c_int),
        ("crtcs", P32),
        ("count_connectors", C.c_int),
        ("connectors", P32),
        ("count_encoders", C.c_int),
        ("encoders", P32),
        ("min_width", U32),
        ("max_width", U32),
        ("min_height", U32),
        ("max_height", U32),
    ]


class Connector(C.Structure):
    _fields_ = [
        ("connector_id", U32),
        ("encoder_id", U32),
        ("connector_type", U32),
        ("connector_type_id", U32),
        ("connection", C.c_int),
        ("mmWidth", U32),
        ("mmHeight", U32),
        ("subpixel", C.c_int),
        ("count_modes", C.c_int),
        ("modes", C.POINTER(Mode)),
        ("count_props", C.c_int),
        ("props", P32),
        ("prop_values", C.POINTER(C.c_uint64)),
        ("count_encoders", C.c_int),
        ("encoders", P32),
    ]


class Encoder(C.Structure):
    _fields_ = [
        (name, U32)
        for name in (
            "encoder_id",
            "encoder_type",
            "crtc_id",
            "possible_crtcs",
            "possible_clones",
        )
    ]


class Crtc(C.Structure):
    _fields_ = [
        (name, U32) for name in ("crtc_id", "buffer_id", "x", "y", "width", "height")
    ] + [("mode_valid", C.c_int), ("mode", Mode), ("gamma_size", C.c_int)]


class CreateDumb(C.Structure):
    _fields_ = [
        (name, U32) for name in ("height", "width", "bpp", "flags", "handle", "pitch")
    ] + [("size", C.c_uint64)]


class MapDumb(C.Structure):
    _fields_ = [("handle", U32), ("pad", U32), ("offset", C.c_uint64)]


class DestroyDumb(C.Structure):
    _fields_ = [("handle", U32)]


def library():
    lib = C.CDLL(ctypes.util.find_library("drm") or "libdrm.so.2", use_errno=True)
    functions = {
        "drmSetMaster": (C.c_int, [C.c_int]),
        "drmDropMaster": (C.c_int, [C.c_int]),
        "drmModeGetResources": (C.POINTER(Resources), [C.c_int]),
        "drmModeFreeResources": (None, [C.POINTER(Resources)]),
        "drmModeGetConnector": (C.POINTER(Connector), [C.c_int, U32]),
        "drmModeFreeConnector": (None, [C.POINTER(Connector)]),
        "drmModeGetEncoder": (C.POINTER(Encoder), [C.c_int, U32]),
        "drmModeFreeEncoder": (None, [C.POINTER(Encoder)]),
        "drmModeGetCrtc": (C.POINTER(Crtc), [C.c_int, U32]),
        "drmModeFreeCrtc": (None, [C.POINTER(Crtc)]),
        "drmModeAddFB": (
            C.c_int,
            [C.c_int, U32, U32, C.c_uint8, C.c_uint8, U32, U32, P32],
        ),
        "drmModeRmFB": (C.c_int, [C.c_int, U32]),
        "drmModeSetCrtc": (
            C.c_int,
            [C.c_int, U32, U32, U32, U32, P32, C.c_int, C.POINTER(Mode)],
        ),
        "drmModePageFlip": (C.c_int, [C.c_int, U32, U32, U32, C.c_void_p]),
    }
    for name, (result, args) in functions.items():
        fn = getattr(lib, name)
        fn.restype = result
        fn.argtypes = args
    return lib


def checked(result, operation):
    if result != 0:
        code = C.get_errno() or errno.EIO
        raise OSError(code, operation + ": " + os.strerror(code))


class KMSDisplay:
    def __init__(self, width, height, event):
        self.w, self.h = width, height
        self.event = event
        self.lib = library()
        self.fd = None
        self.buffers = []
        self.original = None
        self.master = False
        self.changed = False
        self.error = None
        self.pending = None
        self.frames = 0
        self.dropped = 0
        self.stop = threading.Event()
        self.condition = threading.Condition()
        self.thread = None
        try:
            self.connect()
            for _ in range(2):
                self.buffers.append(self.allocate())
            self.set_crtc(self.buffers[0]["fb"])
            self.changed = True
            self.thread = threading.Thread(
                target=self.run, name="kms-present", daemon=True
            )
            self.thread.start()
            self.event(
                state="display_backend",
                backend="drm",
                width=width,
                height=height,
                buffers=2,
                vsync=True,
                card=self.card,
            )
        except Exception:
            self.cleanup()
            raise

    def connect(self):
        for path in sorted(Path("/sys/class/drm").glob("card*-HDMI-A-1")):
            if (path / "status").read_text().strip() != "connected":
                continue
            self.card = "/dev/dri/" + path.name.split("-")[0]
            self.fd = os.open(self.card, os.O_RDWR | os.O_CLOEXEC | os.O_NONBLOCK)
            break
        if self.fd is None:
            raise RuntimeError("No connected HDMI-A-1 DRM card")
        res = self.lib.drmModeGetResources(self.fd)
        if not res:
            raise RuntimeError("DRM resources unavailable")
        try:
            for index in range(res.contents.count_connectors):
                connector = self.lib.drmModeGetConnector(
                    self.fd, res.contents.connectors[index]
                )
                if not connector:
                    continue
                try:
                    c = connector.contents
                    if (
                        c.connection != 1
                        or c.connector_type != 11
                        or c.connector_type_id != 1
                    ):
                        continue
                    encoder = self.lib.drmModeGetEncoder(self.fd, c.encoder_id)
                    if not encoder:
                        continue
                    try:
                        crtc_id = encoder.contents.crtc_id
                    finally:
                        self.lib.drmModeFreeEncoder(encoder)
                    crtc = self.lib.drmModeGetCrtc(self.fd, crtc_id)
                    if not crtc:
                        continue
                    try:
                        original = Crtc.from_buffer_copy(
                            C.string_at(crtc, C.sizeof(Crtc))
                        )
                    finally:
                        self.lib.drmModeFreeCrtc(crtc)
                    if not original.mode_valid:
                        continue
                    if (original.mode.hdisplay, original.mode.vdisplay) != (
                        self.w,
                        self.h,
                    ):
                        raise RuntimeError("DRM mode differs from framebuffer viewport")
                    self.original = original
                    self.connector = U32(c.connector_id)
                    break
                finally:
                    self.lib.drmModeFreeConnector(connector)
        finally:
            self.lib.drmModeFreeResources(res)
        if self.original is None:
            raise RuntimeError("Active HDMI CRTC not found")
        checked(self.lib.drmSetMaster(self.fd), "DRM master")
        self.master = True

    def allocate(self):
        req = CreateDumb(height=self.h, width=self.w, bpp=16)
        fcntl.ioctl(self.fd, 0xC02064B2, req, True)
        fb = U32()
        memory = None
        try:
            checked(
                self.lib.drmModeAddFB(
                    self.fd, self.w, self.h, 16, 16, req.pitch, req.handle, C.byref(fb)
                ),
                "Add RGB565 framebuffer",
            )
            mapping = MapDumb(handle=req.handle)
            fcntl.ioctl(self.fd, 0xC01064B3, mapping, True)
            memory = mmap.mmap(
                self.fd,
                req.size,
                flags=mmap.MAP_SHARED,
                prot=mmap.PROT_READ | mmap.PROT_WRITE,
                offset=mapping.offset,
            )
            return {
                "handle": req.handle,
                "pitch": req.pitch,
                "fb": fb.value,
                "memory": memory,
            }
        except Exception:
            if memory is not None:
                memory.close()
            if fb.value:
                self.lib.drmModeRmFB(self.fd, fb.value)
            fcntl.ioctl(self.fd, 0xC00464B4, DestroyDumb(handle=req.handle), True)
            raise

    def set_crtc(self, fb):
        checked(
            self.lib.drmModeSetCrtc(
                self.fd,
                self.original.crtc_id,
                fb,
                0,
                0,
                C.byref(self.connector),
                1,
                C.byref(self.original.mode),
            ),
            "Set scanout buffer",
        )

    def present(self, raw):
        if len(raw) != self.w * self.h * 2:
            raise ValueError("DRM frame size mismatch")
        if self.error:
            raise RuntimeError("DRM presentation failed: " + self.error)
        with self.condition:
            if self.pending is not None:
                self.dropped += 1
            self.pending = raw
            self.condition.notify()

    def wait_flip(self):
        deadline = time.monotonic() + 1
        while not self.stop.is_set():
            if time.monotonic() > deadline:
                raise RuntimeError("Page flip completion timed out")
            if not select.select([self.fd], [], [], 0.1)[0]:
                continue
            events = os.read(self.fd, 4096)
            offset = 0
            while offset + 8 <= len(events):
                kind, length = struct.unpack_from("II", events, offset)
                if length < 8 or offset + length > len(events):
                    raise RuntimeError("Malformed DRM event")
                if kind == 2:
                    return True  # DRM_EVENT_FLIP_COMPLETE
                offset += length
        return False

    def run(self):
        front = 0
        last_log = time.monotonic()
        try:
            while not self.stop.is_set():
                with self.condition:
                    while self.pending is None and not self.stop.is_set():
                        self.condition.wait(0.2)
                    if self.stop.is_set():
                        break
                    frame, self.pending = self.pending, None
                back = 1 - front
                buffer = self.buffers[back]
                memory = buffer["memory"]
                pitch = buffer["pitch"]
                if pitch == self.w * 2:
                    memory[: len(frame)] = frame
                else:
                    for row in range(self.h):
                        memory[row * pitch : row * pitch + self.w * 2] = frame[
                            row * self.w * 2 : (row + 1) * self.w * 2
                        ]
                # No ASYNC flag: the kernel switches the complete buffer at vblank.
                checked(
                    self.lib.drmModePageFlip(
                        self.fd, self.original.crtc_id, buffer["fb"], 1, None
                    ),
                    "Queue page flip",
                )
                if not self.wait_flip():
                    break
                front = back
                self.frames += 1
                if time.monotonic() - last_log > 5:
                    self.event(
                        state="display_pageflips",
                        frames=self.frames,
                        dropped=self.dropped,
                    )
                    last_log = time.monotonic()
        except Exception as exc:
            self.error = str(exc)
            self.event(state="display_error", backend="drm", error=self.error)
        finally:
            self.cleanup()

    def close(self):
        self.stop.set()
        with self.condition:
            self.condition.notify_all()
        if self.thread:
            self.thread.join(timeout=2)

    def cleanup(self):
        if self.fd is None:
            return
        if self.changed:
            c = self.original
            result = self.lib.drmModeSetCrtc(
                self.fd,
                c.crtc_id,
                c.buffer_id,
                c.x,
                c.y,
                C.byref(self.connector),
                1,
                C.byref(c.mode),
            )
            if result:
                self.event(state="display_restore_error", errno=C.get_errno())
            self.changed = False
        for buffer in self.buffers:
            buffer["memory"].close()
            self.lib.drmModeRmFB(self.fd, buffer["fb"])
            try:
                fcntl.ioctl(
                    self.fd, 0xC00464B4, DestroyDumb(handle=buffer["handle"]), True
                )
            except OSError:
                pass
        self.buffers.clear()
        if self.master:
            self.lib.drmDropMaster(self.fd)
            self.master = False
        os.close(self.fd)
        self.fd = None
