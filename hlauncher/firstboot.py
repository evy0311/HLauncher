"""Idempotent identity setup. Image sanitization is an offline-only build action."""
import os
import re
from pathlib import Path
import subprocess
from .setup_state import SetupState, atomic_json
from .storage import finish_transition


def write_recovery_card(credentials, boot):
    """An SD-reader fallback when a radio gates HDMI until pairing succeeds."""
    boot = Path(boot)
    text = ('HLauncher setup recovery\n\nRadio pairing: Settings > Phone > Connect a phone > Add Bluetooth device.\nSelect HLauncher and confirm the pairing code.\n\nConnect your phone to Wi-Fi: '+credentials['ssid']+
            '\nWi-Fi password: '+credentials['password']+
            '\nOpen: http://192.168.4.1:8080\nLogin username: hlauncher\nLogin password: '+credentials['password']+
            '\n\nKeep this file private. It contains this device’s setup credentials.\n')
    import tempfile
    fd,name=tempfile.mkstemp(prefix='.hlauncher-setup-',dir=boot)
    try:
        with os.fdopen(fd,'w') as output:
            output.write(text); output.flush(); os.fsync(output.fileno())
        os.replace(name,boot/'HLAUNCHER-SETUP.txt')
    finally:
        if os.path.exists(name):os.unlink(name)


def main():
    state = SetupState()
    credentials = state.credentials()
    marker = state.folder/'initialized.json'
    if not marker.exists():
        # No default account/password or shared SSH host keys are shipped by our image.
        subprocess.run(['systemd-machine-id-setup'],check=True,timeout=10)
        boot = Path('/boot/firmware') if Path('/boot/firmware/config.txt').exists() else Path('/boot')
        write_recovery_card(credentials, boot)
        atomic_json(marker, {'initialized':True, 'schema':1})
    country = os.environ.get('HLAUNCHER_WIFI_COUNTRY','')
    if re.fullmatch('[A-Z]{2}', country):
        # Network setup does not hold up the Bluetooth enrollment service.
        subprocess.run(['rfkill','unblock','wifi'],check=False,timeout=5)
    finish_transition()


if __name__ == '__main__': main()
