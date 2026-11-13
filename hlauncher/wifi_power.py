"""Wi-Fi radio policy for the recovery service."""
import json
from pathlib import Path
import subprocess
import time

BOOT_HOLD = Path('/run/hlauncher-wifi-boot-hold')


def hold_at_boot():
    from .config import Preferences
    from .storage import execute

    prefs = Preferences().data
    if not (prefs['wifi_delay_boot'] or prefs['wifi_power'] == 'off'):
        return
    # The unit can also be restarted during an update on an already running Pi.
    manager = execute(['systemctl', 'show', '-p', 'ActiveState', '--value', 'NetworkManager.service'], timeout=3)
    if manager.stdout.strip() in ('active', 'reloading'):
        return
    execute(['rfkill', 'block', 'wifi'], timeout=3)
    BOOT_HOLD.touch()


class WifiPower:
    IDLE_SECONDS = 180
    # Ignore the small bursts of discovery and link-maintenance traffic on a LAN.
    ACTIVE_BYTES = 4096

    def __init__(self, run, clock=time.monotonic,
                 statistics=Path('/sys/class/net/wlan0/statistics')):
        self.run = run
        self.clock = clock
        self.statistics = statistics
        self.mode = None
        self.state = 'unknown'
        self.last_use = clock()
        self.last_bytes = None
        self.hotspot_override = False

    def wake(self):
        self.last_use = self.clock()
        self.last_bytes = None
        self.state = 'unknown'

    def select(self, mode):
        self.mode = mode
        self.hotspot_override = False
        self.wake()

    def hotspot_started(self):
        self.hotspot_override = True
        self.wake()
        self.state = 'on'

    def set_radio(self, enabled):
        if enabled:
            self.run(['rfkill', 'unblock', 'wifi'], timeout=5)
        self.run(['nmcli', 'radio', 'wifi', 'on' if enabled else 'off'], timeout=5)

    def has_wifi_connection(self):
        # At the idle deadline, keep existing TCP sessions on wlan0 alive.
        # Connections using Ethernet or loopback don't keep Wi-Fi awake.
        interfaces = json.loads(self.run(['ip', '-j', 'address', 'show', 'dev', 'wlan0'], timeout=3).stdout)
        addresses = {entry['local'] for dev in interfaces for entry in dev.get('addr_info', [])}
        if not addresses:
            return False
        output = self.run(['ss', '-Htn', 'state', 'established'], timeout=3).stdout
        for line in output.splitlines():
            fields = line.split()
            if len(fields) >= 4:
                local = fields[-2].rsplit(':', 1)[0].strip('[]').split('%', 1)[0]
                if local in addresses or local.removeprefix('::ffff:') in addresses:
                    return True
        return False

    def tick(self, mode, *, setup_hotspot=False, updating=False):
        if mode != self.mode:
            # Starting an explicit hotspot before our first tick still wakes Wi-Fi.
            if self.mode is None:
                self.mode = mode
            else:
                self.select(mode)
        if setup_hotspot:
            self.last_use = self.clock()
            return self.state
        if mode == 'off' and not self.hotspot_override:
            if self.state != 'off':
                self.set_radio(False)
                self.state = 'off'
            return self.state
        if self.state == 'asleep':
            return self.state
        if self.state != 'on':
            self.set_radio(True)
            self.state = 'on'
            self.last_use = self.clock()
        if mode == 'on':
            return self.state

        now = self.clock()
        if updating:
            self.last_use = now
        try:
            received = int((self.statistics/'rx_bytes').read_text())
            sent = int((self.statistics/'tx_bytes').read_text())
            counts = (received, sent)
            if self.last_bytes is not None:
                activity = sum(max(0, current - previous)
                               for current, previous in zip(counts, self.last_bytes))
                if activity >= self.ACTIVE_BYTES:
                    self.last_use = now
            self.last_bytes = counts
            if now - self.last_use >= self.IDLE_SECONDS:
                if self.has_wifi_connection():
                    self.last_use = now
                else:
                    self.set_radio(False)
                    self.state = 'off' if mode == 'off' else 'asleep'
                    self.hotspot_override = False
        except (OSError, ValueError, subprocess.SubprocessError):
            # With no reliable activity reading, keep the current connection up.
            pass
        return self.state


if __name__ == '__main__':
    hold_at_boot()
