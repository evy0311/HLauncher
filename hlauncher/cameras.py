"""Discover USB video capture devices and their names from Linux."""

from collections import Counter
import fcntl
import os
from pathlib import Path
import re
import struct

# struct v4l2_capability from linux/videodev2.h.
CAPABILITY = struct.Struct('=16s32s32s6I')
QUERY_CAPABILITY = 0x80685600
DEVICE_CAPS = 0x80000000
VIDEO_CAPTURE = 0x00000001 | 0x00001000  # Single-plane and multiplanar capture.


def camera_info(device):
    fd = os.open(device, os.O_RDONLY | os.O_NONBLOCK)
    try:
        buffer = bytearray(CAPABILITY.size)
        fcntl.ioctl(fd, QUERY_CAPABILITY, buffer)
    finally:
        os.close(fd)
    _, name, bus, _, capabilities, device_caps, *_ = CAPABILITY.unpack(buffer)
    flags = device_caps if capabilities & DEVICE_CAPS else capabilities
    if bus.startswith(b'usb-') and flags & VIDEO_CAPTURE:
        return name.split(b'\0', 1)[0].decode('utf-8', errors='replace').strip()


def usb_cameras(dev=Path('/dev')):
    cameras = {}
    for path in sorted(dev.glob('video*'), key=lambda item: item.name):
        if not re.fullmatch(r'video[0-9]{1,3}', path.name):
            continue
        try:
            name = camera_info(path)
        except OSError:
            continue
        if name:
            # Some UVC drivers repeat the product name on either side of a colon.
            name = name.partition(':')[0].strip()
            if name.startswith(('Brio ', 'BRIO ')):
                name = 'Logitech ' + name
            cameras[str(path)] = name
    totals = Counter(cameras.values())
    seen = Counter()
    for device, name in cameras.items():
        if totals[name] > 1:
            seen[name] += 1
            cameras[device] = f'{name} ({seen[name]})'
    return cameras
