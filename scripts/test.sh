#!/bin/bash
set -euo pipefail
cd -- "$(dirname -- "$0")/.."
python3 tests/test_protocol.py
python3 tests/test_launcher.py
node runtime/carplay/bridge.mjs --self-test >/dev/null
