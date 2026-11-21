#!/bin/bash
# One-command native Mac developer app; dependencies stay in a private venv.
set -euo pipefail
sim_repo="$(cd "$(dirname "$0")/.." && pwd)"
sim_python="${HLAUNCHER_SIMULATOR_PYTHON:-$sim_repo/.venv-simulator/bin/python3}"
if [ ! -x "$sim_python" ]; then
    python3 -m venv "$sim_repo/.venv-simulator"
fi
if ! "$sim_python" -c 'import PIL, numpy, cryptography' >/dev/null 2>&1; then
    "$sim_python" -m pip install -r "$sim_repo/tools/desktop_simulator/requirements.txt"
fi
HLAUNCHER_SIMULATOR_PYTHON="$sim_python" bash "$sim_repo/scripts/build_desktop_simulator.sh"
open "$sim_repo/build/HLauncher Simulator.app"
