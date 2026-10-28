"""CommonLink framing from Civic firmware. No assumed touch-state names."""

from functools import reduce
from operator import xor


def frame(message, payload):
    body = bytes([message]) + payload
    return (
        b"\x9f\x02"
        + (body + bytes([reduce(xor, body, 0)])).replace(b"\x9f", b"\x9f\x9f")
        + b"\x9f\x03"
    )


class Frames:
    def __init__(self):
        self.buffer = bytearray()

    def feed(self, data):
        self.buffer.extend(data)
        out = []
        if len(self.buffer) > 65536:
            self.buffer.clear()
            return [{"state": "honda_frame_overflow"}]
        while True:
            i = self.buffer.find(b"\x9f\x02")
            if i < 0:
                self.buffer[:] = b"\x9f" if self.buffer.endswith(b"\x9f") else b""
                return out
            del self.buffer[:i]
            body = bytearray()
            i = 2
            while i < len(self.buffer):
                c = self.buffer[i]
                if c != 0x9F:
                    body.append(c)
                    i += 1
                    continue
                if i + 1 == len(self.buffer):
                    return out
                n = self.buffer[i + 1]
                if n == 0x9F:
                    body.append(0x9F)
                    i += 2
                    continue
                if n == 3:
                    del self.buffer[: i + 2]
                    if len(body) >= 2 and reduce(xor, body, 0) == 0:
                        out.append(
                            {
                                "state": "honda_frame",
                                "message": body[0],
                                "payload": bytes(body[1:-1]).hex(),
                            }
                        )
                    else:
                        out.append({"state": "honda_frame_invalid_checksum"})
                    break
                if n == 2:
                    del self.buffer[:i]
                    break
                del self.buffer[: i + 2]
                out.append({"state": "honda_frame_invalid_escape"})
                break
            else:
                return out
