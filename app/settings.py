"""Installation paths and the paired radio address."""

import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOG_DIR = Path(os.environ.get("HLAUNCHER_LOG_DIR", "/var/log/hlauncher"))
RADIO_ADDRESS = os.environ.get("HLAUNCHER_RADIO_ADDRESS", "00:00:00:00:00:00").upper()
if not re.fullmatch(r"(?:[0-9A-F]{2}:){5}[0-9A-F]{2}", RADIO_ADDRESS):
    raise ValueError("HLAUNCHER_RADIO_ADDRESS must be a Bluetooth MAC address")
RADIO_PATH = "/org/bluez/hci0/dev_" + RADIO_ADDRESS.replace(":", "_")
RFCOMM_PATH = "/org/bluealsa/hci0/dev_" + RADIO_ADDRESS.replace(":", "_") + "/rfcomm"


def serial_number():
    override = os.environ.get("HLAUNCHER_SERIAL")
    if override:
        return override.encode("ascii")[:32]
    try:
        return Path("/proc/device-tree/serial-number").read_bytes().rstrip(b"\0")[:32]
    except OSError:
        return b"HLauncher"
