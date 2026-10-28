"""Compatibility import for the shared projection decoder."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[4]/'sdk'))
from hlauncher_sdk.video.avdecode import *
