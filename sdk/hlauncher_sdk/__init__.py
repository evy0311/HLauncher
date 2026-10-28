"""HLauncher plugin API 1. Control messages are JSON; video uses leased slots."""

import collections
import json
import mmap
import os
import select
import socket
import threading

API_VERSION = 1
SLOTS = 3
MAX_PACKET = 16384


def encode(message):
    raw = b"J" + json.dumps(message, separators=(",", ":"), allow_nan=False).encode()
    if len(raw) > MAX_PACKET:
        raise ValueError("control message too large")
    return raw


def decode(raw):
    if not raw or len(raw) > MAX_PACKET:
        raise ValueError("invalid packet size")
    if raw[:1] == b"A":
        return {"type": "audio.pcm", "pcm": raw[1:]}
    if raw[:1] != b"J":
        raise ValueError("unknown packet type")
    value = json.loads(raw[1:])
    if not isinstance(value, dict) or not isinstance(value.get("type"), str):
        raise ValueError("invalid control message")
    return value


class Client:
    def __init__(self):
        self.socket = socket.socket(fileno=int(os.environ["HLAUNCHER_CONTROL_FD"]))
        self.socket.setblocking(False)
        self.width = int(os.environ["HLAUNCHER_WIDTH"])
        self.height = int(os.environ["HLAUNCHER_HEIGHT"])
        self.frame_bytes = self.width * self.height * 2
        self.memory = mmap.mmap(
            int(os.environ["HLAUNCHER_FRAME_FD"]), self.frame_bytes * SLOTS
        )
        self.free = collections.deque(range(SLOTS))
        self.sequence = 0
        self.lock = threading.Lock()
        self.send(type="plugin.ready", api_version=API_VERSION)

    def send(self, **message):
        raw = encode(message)
        with self.lock:
            try:
                return self.socket.send(raw) == len(raw)
            except BlockingIOError:
                return False

    def receive(self, timeout=0):
        if not select.select([self.socket], [], [], timeout)[0]:
            return None
        raw, _, flags, _ = self.socket.recvmsg(MAX_PACKET)
        if not raw:
            raise EOFError("launcher disconnected")
        if flags & socket.MSG_TRUNC:
            raise ValueError("truncated control packet")
        message = decode(raw)
        if message["type"] == "frame.release":
            slot = message["slot"]
            if isinstance(slot, int) and 0 <= slot < SLOTS and slot not in self.free:
                self.free.append(slot)
        return message

    def present(self, pixels):
        if len(pixels) != self.frame_bytes:
            raise ValueError("expected full-size RGB565LE frame")
        if not self.free:
            return False
        slot = self.free.popleft()
        at = slot * self.frame_bytes
        self.memory[at : at + self.frame_bytes] = pixels
        self.sequence += 1
        if self.send(
            type="frame.ready",
            slot=slot,
            sequence=self.sequence,
            bytes=self.frame_bytes,
        ):
            return True
        self.free.appendleft(slot)
        return False

    def status(self, text, **extra):
        return self.send(type="plugin.status", text=str(text)[:240], **extra)

    def home(self):
        return self.send(type="launcher.home")

    def close(self):
        self.memory.close()
        self.socket.close()
