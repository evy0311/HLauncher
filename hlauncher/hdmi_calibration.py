"""Temporary HDMI range comparison using the launcher's existing DRM connection."""

import ctypes as C


class Property(C.Structure):
    _fields_ = [('id', C.c_uint32), ('flags', C.c_uint32), ('name', C.c_char * 32),
                ('count_values', C.c_int), ('values', C.POINTER(C.c_uint64)),
                ('count_enums', C.c_int), ('enums', C.c_void_p),
                ('count_blobs', C.c_int), ('blob_ids', C.POINTER(C.c_uint32))]


def broadcast_rgb(kms, value=None):
    if kms is None:
        raise RuntimeError('HDMI range control requires the DRM display')
    lib = kms.lib
    lib.drmModeGetProperty.argtypes = [C.c_int, C.c_uint32]
    lib.drmModeGetProperty.restype = C.POINTER(Property)
    lib.drmModeFreeProperty.argtypes = [C.POINTER(Property)]
    lib.drmModeConnectorSetProperty.argtypes = [C.c_int, C.c_uint32, C.c_uint32, C.c_uint64]
    lib.drmModeConnectorSetProperty.restype = C.c_int
    connector = lib.drmModeGetConnector(kms.fd, kms.connector)
    if not connector:
        raise RuntimeError('HDMI connector unavailable')
    try:
        c = connector.contents
        for i in range(c.count_props):
            prop = lib.drmModeGetProperty(kms.fd, c.props[i])
            if not prop:
                continue
            try:
                if bytes(prop.contents.name) != b'Broadcast RGB':
                    continue
                before = int(c.prop_values[i])
                if value is not None:
                    if value not in (0, 1, 2):
                        raise ValueError('Invalid HDMI range')
                    if lib.drmModeConnectorSetProperty(kms.fd, kms.connector, c.props[i], value):
                        raise OSError(C.get_errno(), 'Cannot set HDMI RGB range')
                return before
            finally:
                lib.drmModeFreeProperty(prop)
    finally:
        lib.drmModeFreeConnector(connector)
    raise RuntimeError('HDMI RGB range control unavailable')


def pattern(draw, width, font):
    draw.text((24, 80), 'Dark steps: look for separate blocks near black', font=font(16), fill='white')
    for row, values in enumerate(([0, 4, 8, 12, 16, 20, 24, 32], [223, 231, 235, 239, 243, 247, 251, 255])):
        y = 112 + row * 85
        step = (width - 48) // len(values)
        for i, value in enumerate(values):
            x = 24 + i * step
            draw.rectangle((x, y, x+step-1, y+49), fill=(value,)*3)
            draw.text((x+4, y+52), str(value), font=font(13), fill='white')
    draw.text((24, 280), 'Pale colors: each block should differ from white', font=font(16), fill='white')
    colors = [(255,255,255), (240,248,232), (220,240,200), (232,242,252), (248,236,220), (240,232,248)]
    step = (width - 48) // len(colors)
    for i, color in enumerate(colors):
        x = 24 + i * step
        draw.rectangle((x, 312, x+step-1, 365), fill=color)
