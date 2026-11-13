"""Idempotent identity setup. Image sanitization is an offline-only build action."""
import os
import re
from pathlib import Path
import subprocess
from .setup_state import SetupState, atomic_json


def default_hostname(system=Path('/'), run=subprocess.run):
    """Replace the base-image hostname, including after a RAM-overlay reboot."""
    system = Path(system)
    name = (system/'etc/hostname').read_text().strip()
    if name != 'raspberrypi':
        return
    run(['hostnamectl','set-hostname','hlauncher'],check=True,timeout=10)
    hosts = system/'etc/hosts'
    text = hosts.read_text()
    text = re.sub(r'(?m)^(127\.0\.1\.1\s+).*$', r'\1hlauncher', text)
    hosts.write_text(text)


def write_recovery_card(credentials, boot):
    """An SD-reader fallback when a radio gates HDMI until pairing succeeds."""
    boot = Path(boot)
    text = ('HLauncher setup\n\nRadio pairing: Settings > Phone > Connect a phone > Add Bluetooth device.\nSelect HLauncher.\n\nConnect to Wi-Fi: '+credentials['ssid']+
            '\nWi-Fi password: '+credentials['password']+
            '\nOpen: http://192.168.4.1:8080\nNo page login is required.\n'
            '\nSSH username: pi\nDefault SSH password: raspberry\nSSH can be switched on or off in Wi-Fi & pairing.\n')
    import tempfile
    fd,name=tempfile.mkstemp(prefix='.hlauncher-setup-',dir=boot)
    try:
        with os.fdopen(fd,'w') as output:
            output.write(text); output.flush(); os.fsync(output.fileno())
        os.replace(name,boot/'HLAUNCHER-SETUP.txt')
    finally:
        if os.path.exists(name):os.unlink(name)


def main():
    # Runs after HondaLink profile readiness, outside the connection critical path.
    default_hostname()
    from .audio_settings import PipeWireService
    PipeWireService().set_enabled(False)
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
    from .config import Preferences
    prefs = Preferences(state.folder/'settings.json')
    if re.fullmatch('[A-Z]{2}', country) and not prefs.data['wifi_delay_boot'] and prefs.data['wifi_power'] != 'off':
        # Network setup does not hold up the Bluetooth enrollment service.
        subprocess.run(['rfkill','unblock','wifi'],check=False,timeout=5)
    from .ssh_access import MANAGED,apply
    if MANAGED.exists():
        apply(prefs.data['ssh_enabled'],state.folder,boot=True)
    from .storage import finish_transition
    finish_transition()


if __name__ == '__main__': main()
