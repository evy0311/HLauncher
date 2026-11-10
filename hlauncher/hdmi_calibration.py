"""Serialized atomic HDMI range changes, saved defaults and calibration diagnostics."""
import ctypes as C
from contextlib import nullcontext
import json
import os
from pathlib import Path
from .config import STATE_DIR
from .setup_state import atomic_json

RANGES=('Automatic','Full','Limited')
NAMES=('auto','full','limited')


class HDMISettings:
    def __init__(self,path=None):
        self.path=Path(path) if path else STATE_DIR/'hdmi-output.json'
        data=self.read()
        value=data.get('range','limited')
        self.value=NAMES.index(value) if value in NAMES else 2
    def read(self):
        try:
            data=json.loads(self.path.read_text())
            return data if isinstance(data,dict) else {}
        except (OSError,ValueError):return {}
    def save(self,value):
        if type(value) is not int or value not in (0,1,2):raise ValueError('Choose Auto, Full or Limited')
        data=self.read();data['range']=NAMES[value]
        atomic_json(self.path,data);self.value=value


def startup_range(path=None,environ=None):
    saved=HDMISettings(path)
    env=os.environ if environ is None else environ
    return NAMES[saved.value] if saved.path.exists() else env.get('HLAUNCHER_HDMI_RGB','limited').lower()


class Property(C.Structure):
    _fields_=[('id',C.c_uint32),('flags',C.c_uint32),('name',C.c_char*32),
              ('count_values',C.c_int),('values',C.POINTER(C.c_uint64)),
              ('count_enums',C.c_int),('enums',C.c_void_p),
              ('count_blobs',C.c_int),('blob_ids',C.POINTER(C.c_uint32))]


def properties(kms):
    if kms is None or kms.fd is None:raise RuntimeError('HDMI range control requires the DRM display')
    lib=kms.lib
    lib.drmModeGetProperty.argtypes=[C.c_int,C.c_uint32]
    lib.drmModeGetProperty.restype=C.POINTER(Property)
    lib.drmModeFreeProperty.argtypes=[C.POINTER(Property)]
    connector=lib.drmModeGetConnector(kms.fd,kms.connector)
    if not connector:raise RuntimeError('HDMI connector unavailable')
    found={}
    try:
        c=connector.contents
        for i in range(c.count_props):
            prop=lib.drmModeGetProperty(kms.fd,c.props[i])
            if not prop:continue
            try:found[bytes(prop.contents.name).decode(errors='replace')]=(int(c.props[i]),int(c.prop_values[i]))
            finally:lib.drmModeFreeProperty(prop)
    finally:lib.drmModeFreeConnector(connector)
    return found


def commit_range(kms,prop_id,value):
    """ALLOW_MODESET is required when the driver must reprogram HDMI quantization."""
    lib=kms.lib
    lib.drmSetClientCap.argtypes=[C.c_int,C.c_uint64,C.c_uint64];lib.drmSetClientCap.restype=C.c_int
    if lib.drmSetClientCap(kms.fd,3,1):raise OSError(C.get_errno(),'Atomic HDMI control unavailable')
    lib.drmModeAtomicAlloc.restype=C.c_void_p
    lib.drmModeAtomicAddProperty.argtypes=[C.c_void_p,C.c_uint32,C.c_uint32,C.c_uint64]
    lib.drmModeAtomicAddProperty.restype=C.c_int
    lib.drmModeAtomicCommit.argtypes=[C.c_int,C.c_void_p,C.c_uint32,C.c_void_p]
    lib.drmModeAtomicCommit.restype=C.c_int
    lib.drmModeAtomicFree.argtypes=[C.c_void_p]
    request=lib.drmModeAtomicAlloc()
    if not request:raise RuntimeError('Could not allocate HDMI update')
    try:
        if lib.drmModeAtomicAddProperty(request,int(kms.connector.value),prop_id,value)<0:
            raise OSError(C.get_errno(),'Could not stage HDMI range')
        if lib.drmModeAtomicCommit(kms.fd,request,0x400,None):
            raise OSError(C.get_errno(),'Could not apply HDMI range modeset')
    finally:lib.drmModeAtomicFree(request)


def broadcast_rgb(kms,value=None):
    if kms is None or kms.fd is None:raise RuntimeError('HDMI range control requires the DRM display')
    if value is not None and (type(value) is not int or value not in (0,1,2)):raise ValueError('Invalid HDMI range')
    with getattr(kms,'io_lock',nullcontext()):
        fields=properties(kms)
        if 'Broadcast RGB' not in fields:raise RuntimeError('HDMI RGB range control unavailable')
        prop_id,before=fields['Broadcast RGB']
        if value is None:return before
        commit_range(kms,prop_id,value)
        actual=properties(kms)['Broadcast RGB'][1]
        if actual!=value:raise RuntimeError('HDMI range readback did not match')
        return actual


class ObjectProperties(C.Structure):
    _fields_=[('count_props',C.c_uint32),('props',C.POINTER(C.c_uint32)),
              ('prop_values',C.POINTER(C.c_uint64))]


def native_color_status(kms):
    """Probe actual CRTC capabilities; HDMI connector settings are separate."""
    if kms is None or kms.fd is None:return dict(available=False)
    lib=kms.lib
    lib.drmModeObjectGetProperties.argtypes=[C.c_int,C.c_uint32,C.c_uint32]
    lib.drmModeObjectGetProperties.restype=C.POINTER(ObjectProperties)
    lib.drmModeFreeObjectProperties.argtypes=[C.POINTER(ObjectProperties)]
    lib.drmModeGetProperty.argtypes=[C.c_int,C.c_uint32]
    lib.drmModeGetProperty.restype=C.POINTER(Property)
    lib.drmModeFreeProperty.argtypes=[C.POINTER(Property)]
    with getattr(kms,'io_lock',nullcontext()):
        obj=lib.drmModeObjectGetProperties(kms.fd,kms.original.crtc_id,0xcccccccc)
        if not obj:raise RuntimeError('Could not inspect native display color controls')
        found={}
        try:
            for i in range(obj.contents.count_props):
                prop=lib.drmModeGetProperty(kms.fd,obj.contents.props[i])
                if not prop:continue
                try:
                    name=bytes(prop.contents.name).decode(errors='replace')
                    found[name]=int(obj.contents.prop_values[i])
                finally:lib.drmModeFreeProperty(prop)
        finally:lib.drmModeFreeObjectProperties(obj)
    return dict(available=True,ctm='CTM' in found,
                gamma_lut_size=found.get('GAMMA_LUT_SIZE',0),
                degamma_lut_size=found.get('DEGAMMA_LUT_SIZE',0))


def output_status(kms):
    if kms is None:return dict(backend='fbdev',test_bits=16,range='Unavailable')
    with getattr(kms,'io_lock',nullcontext()):fields=properties(kms)
    value=fields.get('Broadcast RGB',(None,None))[1]
    result=dict(backend='drm',connector=int(kms.connector.value),test_bits=32,
                range=RANGES[value] if value in (0,1,2) else 'Unavailable')
    for name in ('Colorspace','max bpc','link-status'):
        if name in fields:result[name]=fields[name][1]
    try:result['native_color']=native_color_status(kms)
    except (OSError,RuntimeError,AttributeError) as exc:result['native_color']=dict(available=False,error=str(exc))
    # Kernel state is diagnostic evidence, not a promise of what the radio displays.
    card=Path(os.readlink('/proc/self/fd/'+str(kms.fd))).name if Path('/proc/self/fd/'+str(kms.fd)).exists() else ''
    try:
        if card.startswith('card'):
            text=(Path('/sys/kernel/debug/dri')/card[4:]/'state').read_text()
            result['kernel_state']=text[:24576]
    except OSError:pass
    return result
