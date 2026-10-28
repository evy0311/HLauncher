"""Annex-B streaming parser used by the HDMI CarPlay bridge."""
import ctypes
from avdecode import AvDecoder

class H264StreamDecoder:
    """Parse arbitrary Annex-B chunks before feeding complete access units."""
    def __init__(self, width=800, height=480):
        self.decoder = AvDecoder(width, height)
        lib = self.decoder.lib.avcodec
        lib.av_parser_init.argtypes = [ctypes.c_int]
        lib.av_parser_init.restype = ctypes.c_void_p
        lib.av_parser_parse2.argtypes = [ctypes.c_void_p, ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_int),
            ctypes.c_void_p, ctypes.c_int, ctypes.c_int64, ctypes.c_int64, ctypes.c_int64]
        lib.av_parser_parse2.restype = ctypes.c_int
        lib.av_parser_close.argtypes = [ctypes.c_void_p]
        lib.av_parser_close.restype = None
        self.parser = lib.av_parser_init(27)  # AV_CODEC_ID_H264
        if not self.parser:
            self.decoder.close()
            raise RuntimeError('FFmpeg H.264 parser unavailable')

    def feed(self, data):
        if not data:
            return []
        if len(data) > 8 * 1024 * 1024:
            raise ValueError('Oversized H.264 chunk')
        buf = ctypes.create_string_buffer(data + b'\0' * 64)
        offset, pictures = 0, []
        # A malformed parser must not spin indefinitely on one unconsumed byte.
        no_progress = 0
        while offset < len(data):
            out, size = ctypes.c_void_p(), ctypes.c_int()
            used = self.decoder.lib.avcodec.av_parser_parse2(self.parser,
                self.decoder.ctx, ctypes.byref(out), ctypes.byref(size),
                ctypes.addressof(buf) + offset, len(data) - offset,
                -(1 << 63), -(1 << 63), 0)
            if used < 0 or used > len(data) - offset:
                raise RuntimeError('Invalid H.264 parser result')
            if size.value:
                if not out.value or not 0 < size.value <= 8 * 1024 * 1024:
                    raise RuntimeError('Invalid H.264 parser output')
                pictures.extend(self.decoder.decode(ctypes.string_at(out, size.value)))
            offset += used
            no_progress = no_progress + 1 if used == 0 else 0
            if used == 0 and not size.value or no_progress > 4:
                raise RuntimeError('H.264 parser made no progress')
        return pictures

    def close(self):
        if self.parser:
            self.decoder.lib.avcodec.av_parser_close(self.parser)
            self.parser = None
        self.decoder.close()
