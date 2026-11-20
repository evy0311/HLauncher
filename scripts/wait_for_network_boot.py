#!/usr/bin/env python3
"""Delay the network-capable updater daemon; its boot preflight remains separate."""
import os
from pathlib import Path
import sys
import time


def main():
    # The independent network release timer is the recovery fallback. Do not
    # bypass the gate just because the app is slow or a daemon restarts.
    while not Path('/run/hlauncher-network-ready').exists():
        time.sleep(.1)
    os.execv(sys.argv[1],sys.argv[1:])


if __name__=='__main__':main()
