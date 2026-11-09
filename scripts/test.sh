#!/bin/bash
set -euo pipefail
cd -- "$(dirname -- "$0")/.."
python3 tests/test_protocol.py
python3 -m unittest discover -s tests -p "test_*.py"
node plugins/carplay/runtime/usb/bridge.mjs --self-test >/dev/null
