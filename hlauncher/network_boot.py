"""Publish completed UI initialization to the optional system network boot gate."""
import os
from pathlib import Path

UI_READY = Path('/run/hlauncher-ui-ready')


def signal_ui_ready(path=UI_READY):
    try:
        fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    except FileExistsError:
        return True  # Restarting the UI must not interrupt an existing network.
    except OSError:
        return False  # The independent recovery timer can still release networking.
    os.close(fd)
    return True
