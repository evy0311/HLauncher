"""Minimal app: draw a frame and return to HLauncher when touched."""

import time
from PIL import Image, ImageDraw
from hlauncher_sdk import Client

client = Client()
active = False
heartbeat = 0
try:
    while True:
        while message := client.receive(0):
            kind = message["type"]
            if kind == "host.activate":
                active = True
            if kind == "host.deactivate":
                active = False
            if kind == "touch" and any(
                c["action"] == "down" for c in message["contacts"]
            ):
                client.home()
            if kind == "host.stop":
                raise SystemExit
        if active:
            im = Image.new("RGB", (client.width, client.height), "#252033")
            ImageDraw.Draw(im).text(
                (30, 60), "Hello from a plugin. Touch to go home.", fill="white"
            )
            from array import array

            frame = array(
                "H",
                (
                    ((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3)
                    for r, g, b in im.getdata()
                ),
            )
            import sys

            if sys.byteorder != "little":
                frame.byteswap()
            client.present(frame.tobytes())
            active = False
        if time.monotonic() - heartbeat > 2:
            client.send(type="health")
            heartbeat = time.monotonic()
        time.sleep(0.02)
finally:
    client.close()
