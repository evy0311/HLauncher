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
    text = ('HLauncher setup\n\nRadio pairing: Settings > Phone > Connect a phone > Add Bluetooth device.\nSelect HLauncher.\n\n'
            'Wi-Fi starts off. From HLauncher, open Settings > System > Wi-Fi > Setup hotspot and select Start setup hotspot.\n'
            'If the radio screen is unavailable, use Ethernet to reach the setup page on port 8080.\n\n'
            'Connect to Wi-Fi: '+credentials['ssid']+
            '\nWi-Fi password: '+credentials['password']+
            '\nOpen: http://192.168.4.1:8080\nSetup username: hlauncher\nUse the Wi-Fi password above to sign in.\n'
            '\nSSH is off by default. Turn it on from the Wi-Fi menu on the radio.\n')
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
    first_boot = not marker.exists()
    if first_boot:
        # Device identity is generated on first boot.
        subprocess.run(['systemd-machine-id-setup'],check=True,timeout=10)
        boot = Path('/boot/firmware') if Path('/boot/firmware/config.txt').exists() else Path('/boot')
        write_recovery_card(credentials, boot)
    country = os.environ.get('HLAUNCHER_WIFI_COUNTRY','')
    from .config import Preferences
    prefs = Preferences(state.folder/'settings.json')
    if re.fullmatch('[A-Z]{2}', country) and not prefs.data['wifi_delay_boot'] and prefs.data['wifi_power'] != 'off':
        # Network setup does not hold up the Bluetooth enrollment service.
        subprocess.run(['rfkill','unblock','wifi'],check=False,timeout=5)
    from .ssh_access import MANAGED,apply
    if MANAGED.exists():
        # A positive marker represents an owner opt-in. Old preference defaults do not enable SSH.
        opted_in = (state.folder/'ssh-enabled').is_file()
        development_image = first_boot and Path('/etc/hlauncher-ssh-autostart').is_file()
        apply(opted_in or development_image,state.folder,boot=True)
    if first_boot:
        atomic_json(marker, {'initialized':True, 'schema':1})
    from .storage import finish_transition
    finish_transition()


if __name__ == '__main__': main()
