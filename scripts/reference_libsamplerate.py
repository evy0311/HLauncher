"""Streaming float32 sample-rate conversion using libsamplerate's best sinc mode."""
import ctypes as C
from ctypes.util import find_library
import numpy as np


class Data(C.Structure):
    _fields_ = [('data_in', C.POINTER(C.c_float)), ('data_out', C.POINTER(C.c_float)),
                ('input_frames', C.c_long), ('output_frames', C.c_long),
                ('input_frames_used', C.c_long), ('output_frames_gen', C.c_long),
                ('end_of_input', C.c_int), ('src_ratio', C.c_double)]


class Resampler:
    def __init__(self, input_rate, output_rate=48000):
        name = find_library('samplerate')
        if not name:
            raise RuntimeError('High-quality resampling requires libsamplerate0')
        self.lib = C.CDLL(name)
        self.lib.src_new.argtypes = [C.c_int, C.c_int, C.POINTER(C.c_int)]
        self.lib.src_new.restype = C.c_void_p
        self.lib.src_process.argtypes = [C.c_void_p, C.POINTER(Data)]
        self.lib.src_process.restype = C.c_int
        self.lib.src_delete.argtypes = [C.c_void_p]
        self.lib.src_delete.restype = C.c_void_p
        self.lib.src_strerror.argtypes = [C.c_int]
        self.lib.src_strerror.restype = C.c_char_p
        error = C.c_int()
        self.state = self.lib.src_new(0, 2, C.byref(error))  # SRC_SINC_BEST_QUALITY
        if not self.state:
            raise RuntimeError(self.lib.src_strerror(error.value).decode())
        self.ratio = output_rate / input_rate

    def process(self, samples):
        samples = np.ascontiguousarray(samples, dtype=np.float32).reshape(-1, 2)
        offset = 0
        blocks = []
        while offset < len(samples):
            source = samples[offset:]
            out = np.empty((int(np.ceil(len(source)*self.ratio))+512, 2), dtype=np.float32)
            data = Data(source.ctypes.data_as(C.POINTER(C.c_float)), out.ctypes.data_as(C.POINTER(C.c_float)),
                        len(source), len(out), 0, 0, 0, self.ratio)
            error = self.lib.src_process(self.state, C.byref(data))
            if error:
                raise RuntimeError(self.lib.src_strerror(error).decode())
            if not data.input_frames_used and not data.output_frames_gen:
                raise RuntimeError('Resampler made no progress')
            offset += data.input_frames_used
            blocks.append(out[:data.output_frames_gen].copy())
        return np.concatenate(blocks) if blocks else np.empty((0, 2), dtype=np.float32)

    def close(self):
        if getattr(self, 'state', None):
            self.lib.src_delete(self.state)
            self.state = None

    def __del__(self):
        self.close()
