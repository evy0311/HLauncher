"""Bounded local HFP call-state probe. Never dials a number or uses a phone."""

import argparse, json, select, signal, socket, threading, time
from settings import RFCOMM_PATH

BEGIN = ("+CIEV:1,1", "+CIEV:5,5", "+CIEV:2,1")
END = ("+CIEV:2,0", "+CIEV:5,0", "+CIEV:1,0")


def response(text):
    if text.startswith("AT+CLCC"):
        return ("+CLCC:1,0,0,0,0", "OK")
    if text.startswith(("AT+CLIP=", "AT+CCWA=", "AT+CMEE=")):
        return ("OK",)
    if text.startswith("AT"):
        return ("ERROR",)
    return ()


def main():
    import dbus

    p = argparse.ArgumentParser()
    p.add_argument("--seconds", type=int, default=60)
    p.add_argument("--clear-only", action="store_true")
    a = p.parse_args()
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    bus = dbus.SystemBus(private=True)
    s = None

    def emit(**v):
        print(json.dumps(v), flush=True)

    def send(text):
        s.send(("\r\n" + text + "\r\n").encode())

    try:
        fd = dbus.Interface(
            bus.get_object("org.bluealsa", RFCOMM_PATH), "org.bluealsa.RFCOMM1"
        ).Open(timeout=3)
        s = socket.socket(fileno=fd.take())
        s.settimeout(0.3)
        if not a.clear_only:
            for text in BEGIN:
                send(text)
            emit(state="mic_test_call_enabled", seconds=max(1, min(60, a.seconds)))
            end = time.monotonic() + max(1, min(60, a.seconds))
            while not stop.is_set() and time.monotonic() < end:
                if select.select([s], [], [], 0.1)[0]:
                    raw = s.recv(2048)
                    if not raw:
                        break
                    for text in response(raw.decode(errors="replace").strip()):
                        send(text)
    finally:
        sent = 0
        if s:
            for text in END:
                try:
                    send(text)
                    sent += 1
                except OSError:
                    break
            s.close()
        bus.close()
        emit(
            state=(
                "mic_test_call_cleared"
                if sent == len(END)
                else "mic_test_call_cleanup_failed"
            ),
            commands_sent=sent,
            radio_state_verified=False,
        )


if __name__ == "__main__":
    main()
