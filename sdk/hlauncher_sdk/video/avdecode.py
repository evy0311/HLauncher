"""H.264 → RGB565 decoding with FFmpeg's libavcodec + libswscale via ctypes.

Why not PyAV: on Pi OS Lite, python3-av drags in 165 packages (SDL, X11, …) and
~411 MB — more than the ~300 MB free on a freshly written card before its first
boot. libavcodec + libswscale alone are 71 packages / ~102 MB. Why not the ffmpeg
command-line tool: its demuxer buffers about a second of video; handing each scrcpy
packet (one access unit) straight to avcodec returns the frame immediately.

ABI notes. Packets are filled with av_malloc + av_packet_from_data, and codec
settings go through AVOptions, so no AVPacket/AVCodecContext field offsets are
needed. Only the leading AVFrame fields are read — data[8], linesize[8],
extended_data, width, height, nb_samples, format — whose layout has been unchanged
across FFmpeg 4–7. Pixel-format numbers come from av_get_pix_fmt() at run time.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import errno

_VP = ctypes.c_void_p
_INT = ctypes.c_int
PADDING = 64                                # AV_INPUT_BUFFER_PADDING_SIZE
SWS_FAST_BILINEAR = 1


class DecoderError(RuntimeError):
    pass


def _load(name: str, versions: tuple[int, ...]) -> ctypes.CDLL:
    candidates = [ctypes.util.find_library(name)] + [f"lib{name}.so.{v}" for v in versions]
    for candidate in candidates:
        if not candidate:
            continue
        try:
            return ctypes.CDLL(candidate)
        except OSError:
            continue
    raise DecoderError(f"lib{name} not found (install libavcodec/libswscale)")


class _Libs:
    _instance: _Libs | None = None

    def __init__(self) -> None:
        self.avutil = _load("avutil", (59, 58, 57, 56))
        self.avcodec = _load("avcodec", (61, 60, 59, 58))
        self.swscale = _load("swscale", (8, 7, 6, 5))
        u, c, s = self.avutil, self.avcodec, self.swscale
        for fn, res, args in [
            (u.av_malloc, _VP, [ctypes.c_size_t]),
            (u.av_frame_alloc, _VP, []),
            (u.av_frame_ref, _INT, [_VP, _VP]),
            (u.av_frame_unref, None, [_VP]),
            (u.av_frame_free, None, [ctypes.POINTER(_VP)]),
            (u.av_get_pix_fmt, _INT, [ctypes.c_char_p]),
            (u.av_get_pix_fmt_name, ctypes.c_char_p, [_INT]),
            (u.av_opt_get_int, _INT, [_VP, ctypes.c_char_p, _INT, ctypes.POINTER(ctypes.c_int64)]),
            (s.sws_getCoefficients, _VP, [_INT]),
            (u.av_opt_set_int, _INT, [_VP, ctypes.c_char_p, ctypes.c_int64, _INT]),
            (u.av_opt_set, _INT, [_VP, ctypes.c_char_p, ctypes.c_char_p, _INT]),
            (u.av_log_set_level, None, [_INT]),
            (c.avcodec_find_decoder_by_name, _VP, [ctypes.c_char_p]),
            (c.avcodec_alloc_context3, _VP, [_VP]),
            (c.avcodec_open2, _INT, [_VP, _VP, _VP]),
            (c.avcodec_free_context, None, [ctypes.POINTER(_VP)]),
            (c.avcodec_send_packet, _INT, [_VP, _VP]),
            (c.avcodec_receive_frame, _INT, [_VP, _VP]),
            (c.av_packet_alloc, _VP, []),
            (c.av_packet_free, None, [ctypes.POINTER(_VP)]),
            (c.av_packet_from_data, _INT, [_VP, _VP, _INT]),
            (c.av_packet_unref, None, [_VP]),
            (s.sws_getCachedContext, _VP, [_VP, _INT, _INT, _INT, _INT, _INT, _INT, _INT,
                                           _VP, _VP, _VP]),
            (s.sws_scale, _INT, [_VP, _VP, _VP, _INT, _INT, _VP, _VP]),
            (s.sws_freeContext, None, [_VP]),
            (s.sws_getColorspaceDetails, _INT, [_VP, ctypes.POINTER(_VP), ctypes.POINTER(_INT), ctypes.POINTER(_VP), ctypes.POINTER(_INT), ctypes.POINTER(_INT), ctypes.POINTER(_INT), ctypes.POINTER(_INT)]),
            (s.sws_setColorspaceDetails, _INT, [_VP, _VP, _INT, _VP, _INT, _INT, _INT, _INT]),
        ]:
            fn.restype = res
            fn.argtypes = args
        u.av_log_set_level(16)              # AV_LOG_ERROR: no chatter on stderr
        self.rgb565le = u.av_get_pix_fmt(b"rgb565le")
        if self.rgb565le < 0:
            raise DecoderError("libavutil does not know rgb565le")

    @classmethod
    def get(cls) -> _Libs:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance


class _FrameHead(ctypes.Structure):
    """The leading, long-stable part of AVFrame."""
    _fields_ = [("data", _VP * 8), ("linesize", _INT * 8), ("extended_data", _VP),
                ("width", _INT), ("height", _INT), ("nb_samples", _INT), ("format", _INT)]


class AvDecoder:
    """Decode H.264 access units; each decoded picture comes back as RGB565LE bytes
    scaled to ``width``×``height``.

    ``canvas=(full_w, full_h, x, y)`` places the picture at x, y inside a black
    full_w×full_h frame instead (black bars for portrait apps): libswscale writes into
    the bigger buffer directly, so this costs nothing extra. ``overlay`` is a list of
    (byte offset, bytes) runs stamped onto every picture (the launcher's Home button),
    also without copying the frame.
    """

    def __init__(self, width: int, height: int, *, codec: str = "h264", threads: int = 1,
                 canvas: tuple[int, int, int, int] | None = None,
                 overlay: list[tuple[int, bytes]] | None = None) -> None:
        self.lib = _Libs.get()
        self.picture = dict(saturation=100, contrast=100, brightness=0)
        self.picture_applied = None
        self.source_color = {}
        self.conversion_color = {}
        self.base_colors = None
        self.last_frame = _VP(self.lib.avutil.av_frame_alloc())
        self.overlay = overlay or []
        self.width, self.height = width, height
        full_w, full_h, x, y = canvas or (width, height, 0, 0)
        if not (0 <= x and 0 <= y and x + width <= full_w and y + height <= full_h):
            raise ValueError(f"{width}x{height} at {x},{y} does not fit {full_w}x{full_h}")
        self.out_bytes = full_w * full_h * 2
        c = self.lib.avcodec
        decoder = c.avcodec_find_decoder_by_name((codec or "h264").encode())
        if not decoder:
            raise DecoderError(f"no FFmpeg decoder named {codec!r}")
        self.ctx = _VP(c.avcodec_alloc_context3(decoder))
        # Frame threading would add (threads-1) frames of latency: keep 1 by default.
        self.lib.avutil.av_opt_set_int(self.ctx, b"threads", max(1, threads), 0)
        self.lib.avutil.av_opt_set(self.ctx, b"flags", b"+low_delay", 0)
        if c.avcodec_open2(self.ctx, decoder, None) < 0:
            raise DecoderError(f"cannot open decoder {codec!r}")
        self.pkt = _VP(c.av_packet_alloc())
        self.frame = _VP(self.lib.avutil.av_frame_alloc())
        self.sws: int | None = None
        self.out = ctypes.create_string_buffer(self.out_bytes + PADDING)   # zeroed = black
        start = ctypes.cast(self.out, _VP).value + (y * full_w + x) * 2
        self._dst = (_VP * 4)(start, None, None, None)
        self._dst_stride = (_INT * 4)(full_w * 2, 0, 0, 0)

    def decode(self, data: bytes, render=True) -> list[bytes]:
        """Feed one access unit; returns the pictures it completed (usually one)."""
        lib, c = self.lib, self.lib.avcodec
        buf = lib.avutil.av_malloc(len(data) + PADDING)
        if not buf:
            raise MemoryError("av_malloc")
        ctypes.memmove(buf, data, len(data))
        ctypes.memset(buf + len(data), 0, PADDING)
        if c.av_packet_from_data(self.pkt, buf, len(data)) < 0:
            raise DecoderError("av_packet_from_data failed")
        ret = c.avcodec_send_packet(self.ctx, self.pkt)
        c.av_packet_unref(self.pkt)
        if ret < 0 and ret != -errno.EAGAIN:
            raise DecoderError(f"avcodec_send_packet: {ret}")
        pictures = []
        while c.avcodec_receive_frame(self.ctx, self.frame) >= 0:
            self.source_color = self.read_source_color()
            self.lib.avutil.av_frame_unref(self.last_frame)
            if self.lib.avutil.av_frame_ref(self.last_frame, self.frame) < 0:
                raise DecoderError('Cannot retain preview frame')
            if render:
                pictures.append(self._convert())
        return pictures

    def read_source_color(self):
        values = {}
        for key in ('colorspace', 'color_range', 'color_primaries', 'color_trc'):
            value = ctypes.c_int64()
            result = self.lib.avutil.av_opt_get_int(self.ctx, key.encode(), 0, ctypes.byref(value))
            values[key] = value.value if result >= 0 else None
        return values

    def redraw(self):
        if self.last_frame and _FrameHead.from_address(self.last_frame.value).width:
            return self._convert(self.last_frame)
        return None

    def _convert(self, frame=None) -> bytes:
        frame = frame or self.frame
        head = _FrameHead.from_address(frame.value)
        if not (0 < head.width <= 8192 and 0 < head.height <= 8192) or \
                not self.lib.avutil.av_get_pix_fmt_name(head.format):
            raise DecoderError("unexpected AVFrame layout — unsupported FFmpeg version?")
        source_format = self.lib.avutil.av_get_pix_fmt_name(head.format).decode()
        input_format = head.format
        legacy_full_range = source_format.startswith('yuvj')
        if legacy_full_range:
            # swscale normalizes YUVJ internally. Passing YUVJ into its cache
            # repeatedly can rebuild the context at the SAME address, resetting
            # picture controls while fooling a pointer-based settings cache.
            normalized = self.lib.avutil.av_get_pix_fmt(source_format.replace('yuvj', 'yuv', 1).encode())
            if normalized >= 0:
                input_format = normalized
        previous_sws = self.sws
        self.sws = self.lib.swscale.sws_getCachedContext(
            self.sws, head.width, head.height, input_format, self.width, self.height,
            self.lib.rgb565le, SWS_FAST_BILINEAR, None, None, None)
        if not self.sws:
            raise DecoderError("sws_getCachedContext failed")
        settings = tuple(self.picture[k] for k in ('saturation', 'contrast', 'brightness'))
        signature = (self.sws, settings, head.width, head.height, head.format, tuple(sorted(self.source_color.items())))
        # Reassert controls on every context acquisition, even if its address repeats.
        inv, table = _VP(), _VP()
        src, dst, bright, contrast, saturation = (_INT() for _ in range(5))
        if self.lib.swscale.sws_getColorspaceDetails(self.sws, ctypes.byref(inv), ctypes.byref(src), ctypes.byref(table), ctypes.byref(dst), ctypes.byref(bright), ctypes.byref(contrast), ctypes.byref(saturation)) < 0:
            raise DecoderError('Cannot read video color conversion')
        base_key = (self.sws, head.width, head.height, head.format)
        if self.base_colors is None or self.base_colors[0] != base_key:
            # Keep an independent copy; swscale mutates its internal coefficients.
            saved_inv = (_INT * 4)(*ctypes.cast(inv, ctypes.POINTER(_INT * 4)).contents)
            saved_table = (_INT * 4)(*ctypes.cast(table, ctypes.POINTER(_INT * 4)).contents)
            self.base_colors = (base_key, saved_inv, src.value, saved_table, dst.value)
        _, saved_inv, source_default, saved_table, destination_default = self.base_colors
        inv, table = _VP(ctypes.addressof(saved_inv)), _VP(ctypes.addressof(saved_table))
        src.value, dst.value = source_default, destination_default
        # sws_getCachedContext does not receive the AVFrame's color metadata.
        # Honor declared H.264 metadata; retain previous defaults if unspecified.
        matrix = {1: 1, 5: 5, 6: 5, 7: 7, 9: 9}.get(self.source_color.get('colorspace'))
        if matrix is not None:
            coefficients = self.lib.swscale.sws_getCoefficients(matrix)
            if coefficients:
                inv = _VP(coefficients)
        declared_range = self.source_color.get('color_range')
        if legacy_full_range:
            src.value = 1
        elif declared_range in (1, 2):
            src.value = 1 if declared_range == 2 else 0
        self.conversion_color = dict(source_range=src.value, destination_range=dst.value,
                                     matrix=matrix if matrix is not None else 'default',
                                     source=self.source_color, source_format=source_format)
        if self.lib.swscale.sws_setColorspaceDetails(self.sws, inv, src.value, table, dst.value,
                round(settings[2] * 65536 / 100), round(settings[1] * 65536 / 100), round(settings[0] * 65536 / 100)) < 0:
            raise DecoderError('Cannot apply video color conversion')
        self.picture_applied = signature
        self.lib.swscale.sws_scale(self.sws, ctypes.addressof(head.data),
                                   ctypes.addressof(head.linesize), 0, head.height,
                                   self._dst, self._dst_stride)
        base = ctypes.addressof(self.out)
        for offset, run in self.overlay:
            ctypes.memmove(base + offset, run, len(run))
        return ctypes.string_at(self.out, self.out_bytes)

    def close(self) -> None:
        if self.last_frame:
            self.lib.avutil.av_frame_free(ctypes.byref(self.last_frame))
        if self.ctx:
            self.lib.avcodec.avcodec_free_context(ctypes.byref(self.ctx))
            self.lib.avcodec.av_packet_free(ctypes.byref(self.pkt))
            self.lib.avutil.av_frame_free(ctypes.byref(self.frame))
            if self.sws:
                self.lib.swscale.sws_freeContext(self.sws)
            self.ctx = _VP()
            self.sws = None
