#!/bin/bash
set -euo pipefail
cd -- "$(dirname -- "$0")/.."
mkdir -p build
cc -std=gnu11 -O2 -Wall -Wextra -Werror native/pipewire_pcm.c -o build/hlauncher-pw-input \
    $(pkg-config --cflags --libs libpipewire-0.3) -pthread
