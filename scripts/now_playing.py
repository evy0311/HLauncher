#!/usr/bin/env python3
"""Watch HLauncher media updates over SSH."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from hlauncher.media import main
main(sys.argv[1:] or ['--watch'])
