#!/usr/bin/env python3
"""Keep the already-paired Civic peer connected, without an interactive console."""
import argparse
import os
import logging
import re
import signal
import subprocess
import threading
import time

log = logging.getLogger("civic-bt-connect")
STOP = threading.Event()


def command(*args, timeout=8):
    try:
        p = subprocess.run(
            ["/usr/bin/bluetoothctl", *args],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=timeout,
        )
        return p.returncode, p.stdout
    except subprocess.TimeoutExpired:
        return 124, "Bluetooth command timed out (daemon may be restarting)"
    except OSError as exc:
        return 127, str(exc)


def present(text, field):
    return (
        re.search(r"^\s*" + re.escape(field) + r":\s+yes\s*$", text, re.M) is not None
    )


def classify_controller(code, text):
    if code or "Controller " not in text:
        return "waiting_daemon"
    if not present(text, "Powered"):
        return "power_off"
    needed = (
        "0000110a-0000-1000-8000-00805f9b34fb",
        "0000111f-0000-1000-8000-00805f9b34fb",
    )
    if not all(u in text.lower() for u in needed):
        return "waiting_audio_profiles"
    return "ready"


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--peer", default=os.environ.get("HLAUNCHER_RADIO_ADDRESS"))
    a = p.parse_args()
    if not a.peer or not re.fullmatch(r"(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}", a.peer):
        raise SystemExit("Invalid peer address")
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    signal.signal(signal.SIGTERM, lambda *_: STOP.set())
    signal.signal(signal.SIGINT, lambda *_: STOP.set())
    last = None
    backoff = 5
    next_connect = 0

    def note(state, message):
        nonlocal last
        if state != last:
            log.info(message)
            last = state

    while not STOP.is_set():
        rc, controller = command("show")
        status = classify_controller(rc, controller)
        if status != "ready":
            if status == "power_off":
                note(status, "Powering on the Pi Bluetooth controller")
                command("power", "on")
            else:
                note(
                    status,
                    (
                        "Waiting for Bluetooth daemon"
                        if status == "waiting_daemon"
                        else "Waiting for A2DP Source and HFP Audio Gateway registration"
                    ),
                )
            STOP.wait(5)
            continue
        rc, info = command("info", a.peer)
        if rc or not present(info, "Paired"):
            note(
                "not_paired",
                "HandsFreeLink pairing unavailable; pair once interactively, then this service can reconnect automatically",
            )
            STOP.wait(10)
            continue
        if not present(info, "Trusted"):
            note("trusting", "Marking the existing paired HandsFreeLink device trusted")
            command("trust", a.peer)
        if present(info, "Connected"):
            note("connected", "HandsFreeLink connected")
            backoff = 5
            next_connect = 0
        elif time.monotonic() >= next_connect:
            note("connecting", "Connecting to HandsFreeLink")
            rc, result = command("connect", a.peer, timeout=12)
            if rc:
                # Keep a bounded diagnostic; avoid continuous connection attempts.
                lines = [s.strip() for s in result.splitlines() if s.strip()]
                log.warning(
                    "Connect not ready: %s; retry in %ss",
                    " | ".join(lines[-3:])[:400],
                    backoff,
                )
                last = "retry"
                next_connect = time.monotonic() + backoff
                backoff = min(30, backoff * 2)
            else:
                last = None
                next_connect = time.monotonic() + 5
        STOP.wait(5)


if __name__ == "__main__":
    main()
