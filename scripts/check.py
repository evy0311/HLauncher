#!/usr/bin/env python3
"""Check dependencies and decode a fixture without touching the radio or dongle."""
import argparse
import importlib
import io
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "plugins/carplay/runtime/video")]


def packet(stream):
    import struct

    header = stream.read(5)
    if not header:
        raise EOFError
    if len(header) != 5:
        raise ValueError("short bridge header")
    kind, size = struct.unpack("!BI", header)
    body = stream.read(size)
    if len(body) != size:
        raise ValueError("short bridge body")
    return kind, body


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--display", action="store_true", help="also inspect /dev/fb0 read-only"
    )
    args = parser.parse_args()
    for module in ["PIL", "dbus", "gi", "hlauncher.config", "hlauncher.launcher"]:
        importlib.import_module(module)
    runtime = ROOT / "plugins/carplay/runtime/usb"
    subprocess.run(
        ["node", "--input-type=module", "-e", "await import('usb')"],
        cwd=runtime,
        check=True,
        timeout=20,
    )
    bridge = subprocess.run(
        ["node", str(runtime / "bridge.mjs"), "--self-test"],
        capture_output=True,
        check=True,
        timeout=20,
    )
    stream = io.BytesIO(bridge.stdout)
    states = []
    while stream.tell() < len(bridge.stdout):
        kind, body = packet(stream)
        if kind == 2:
            states.append(json.loads(body)["state"])
    if not {"host_ui_requested", "self_test_ok"}.issubset(states):
        raise RuntimeError("bridge touch/Home self-test failed")
    from h264 import H264StreamDecoder

    decoder = H264StreamDecoder(720, 480)
    count = 0
    try:
        data = (ROOT / "plugins/carplay/runtime/usb/test-pattern.h264").read_bytes()
        for offset in range(0, len(data), 211):
            for frame in decoder.feed(data[offset : offset + 211]):
                if len(frame) != 720 * 480 * 2:
                    raise RuntimeError("incorrect RGB565 output size")
                count += 1
    finally:
        decoder.close()
    if count < 6:
        raise RuntimeError("too few decoded fixture frames")
    if args.display:
        import fcntl
        import os
        import struct

        fd = os.open("/dev/fb0", os.O_RDONLY)
        try:
            var, fix = bytearray(160), bytearray(80)
            fcntl.ioctl(fd, 0x4600, var, True)
            fcntl.ioctl(fd, 0x4602, fix, True)
            width, height, _, _, _, _, depth = struct.unpack_from("7I", var)
            fields = [struct.unpack_from("3I", var, i) for i in (32, 44, 56)]
            print(f"HDMI framebuffer: {width}x{height}, {depth} bpp")
            if depth != 16 or fields != [(11, 5, 0), (5, 6, 0), (0, 5, 0)]:
                raise RuntimeError("RGB565 framebuffer required; see docs/setup.md")
        finally:
            os.close(fd)
    print(
        f"Runtime checks passed; decoded {count} fixture frames. No dongle was opened."
    )


if __name__ == "__main__":
    main()
