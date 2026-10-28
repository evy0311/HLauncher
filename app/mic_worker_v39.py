"""Disposable microphone worker; stdout contains level/status JSON only."""

import json, signal, threading, time
from audio_meter_v37 import AudioMeter

stop = threading.Event()
lock = threading.Lock()


def emit(kind, value):
    with lock:
        print(json.dumps({"type": kind, "value": value}), flush=True)


def main():
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    meter = AudioMeter(lambda **v: emit("event", v))
    try:
        meter.start()
        while not stop.is_set():
            emit("status", meter.snapshot())
            if meter.thread and not meter.thread.is_alive():
                break
            stop.wait(0.1)
    finally:
        meter.stop()


if __name__ == "__main__":
    main()
