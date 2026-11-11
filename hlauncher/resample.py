"""Streaming SoXR conversion for playback and real-time microphone capture."""
import ctypes as C
from ctypes.util import find_library
import numpy as np

SOXR_HQ = 4
SOXR_VHQ = 6
SOXR_DOUBLE_PRECISION = 16
SOXR_VR = 32


class Quality(C.Structure):
    _fields_=[('precision',C.c_double),('phase_response',C.c_double),
              ('passband_end',C.c_double),('stopband_begin',C.c_double),
              ('reserved',C.c_void_p),('flags',C.c_ulong)]


class Resampler:
    def __init__(self,input_rate,output_rate=48000,channels=2,*,realtime=False):
        self.state=None
        if channels not in (1,2):raise ValueError('Unsupported channel count')
        self.channels=channels
        name=find_library('soxr')
        if not name:raise RuntimeError('Install libsoxr0')
        self.lib=C.CDLL(name)
        self.lib.soxr_quality_spec.argtypes=[C.c_ulong,C.c_ulong]
        self.lib.soxr_quality_spec.restype=Quality
        self.lib.soxr_create.argtypes=[C.c_double,C.c_double,C.c_uint,C.POINTER(C.c_char_p),
                                       C.c_void_p,C.POINTER(Quality),C.c_void_p]
        self.lib.soxr_create.restype=C.c_void_p
        self.lib.soxr_process.argtypes=[C.c_void_p,C.c_void_p,C.c_size_t,C.POINTER(C.c_size_t),
                                       C.c_void_p,C.c_size_t,C.POINTER(C.c_size_t)]
        self.lib.soxr_process.restype=C.c_char_p
        self.lib.soxr_delete.argtypes=[C.c_void_p]
        self.lib.soxr_delete.restype=None
        # The variable-rate engine also works at a fixed ratio and emits small
        # capture blocks without waiting for a playback-sized FFT batch.
        if realtime:
            quality = self.lib.soxr_quality_spec(SOXR_HQ, SOXR_VR)
        else:
            quality = self.lib.soxr_quality_spec(SOXR_VHQ, SOXR_DOUBLE_PRECISION)
        error=C.c_char_p()
        self.state=self.lib.soxr_create(input_rate,output_rate,channels,C.byref(error),None,C.byref(quality),None)
        if not self.state:raise RuntimeError(error.value.decode() if error.value else 'SoXR create failed')
        self.ratio=output_rate/input_rate
        self.finished=False

    def process(self,samples):
        if self.finished:raise RuntimeError('Resampler already flushed')
        samples=np.ascontiguousarray(samples,dtype=np.float32).reshape(-1,self.channels)
        offset=0;blocks=[]
        while offset<len(samples):
            source=samples[offset:]
            out=np.empty((int(np.ceil(len(source)*self.ratio))+8192,self.channels),dtype=np.float32)
            used,produced=C.c_size_t(),C.c_size_t()
            error=self.lib.soxr_process(self.state,source.ctypes.data,len(source),C.byref(used),
                                         out.ctypes.data,len(out),C.byref(produced))
            if error:raise RuntimeError(error.decode())
            if not used.value and not produced.value:raise RuntimeError('Resampler made no progress')
            offset+=used.value
            if produced.value:blocks.append(out[:produced.value].copy())
        return np.concatenate(blocks) if blocks else np.empty((0,self.channels),dtype=np.float32)

    def flush(self):
        blocks=[]
        while not self.finished:
            out=np.empty((8192,self.channels),dtype=np.float32);used,produced=C.c_size_t(),C.c_size_t()
            error=self.lib.soxr_process(self.state,None,0,C.byref(used),out.ctypes.data,len(out),C.byref(produced))
            if error:raise RuntimeError(error.decode())
            if produced.value:blocks.append(out[:produced.value].copy())
            else:self.finished=True
        return np.concatenate(blocks) if blocks else np.empty((0,self.channels),dtype=np.float32)

    def close(self):
        if self.state:self.lib.soxr_delete(self.state);self.state=None

    def __del__(self):self.close()
