"""Read-only Wi-Fi telemetry collected by the maintenance service."""
import re
import subprocess

from .storage import execute


def sample(run=execute):
    try:
        radio = run(['nmcli', 'radio', 'wifi'], timeout=3).stdout.strip()
        if radio == 'disabled':
            return {'wifi_link': 'off'}
        if radio != 'enabled':
            return {'wifi_link': 'unknown'}
        link = run(['iw', 'dev', 'wlan0', 'link'], timeout=3).stdout
        if 'Not connected.' in link:
            return {'wifi_link': 'disconnected'}
        if 'Connected to ' in link:
            match = re.search(r'signal:\s*(-?\d+(?:\.\d+)?)\s*dBm', link)
            return dict(wifi_link='connected',
                        wifi_signal_dbm=float(match[1]) if match else None)
    except (OSError, subprocess.SubprocessError):
        pass
    return {'wifi_link': 'unknown'}


def indicator(network=None):
    """A stable, hashable visual state, including stale/missing telemetry."""
    if network is None:
        from .recovery import network_status
        network = network_status()
    state = network.get('wifi_link', 'unknown')
    if state != 'connected':
        return (state if state in ('off', 'disconnected') else 'unknown', 0)
    signal = network.get('wifi_signal_dbm')
    if not isinstance(signal, (int, float)):
        return ('connected', 0)
    return ('connected', 1 + sum(signal >= threshold for threshold in (-80, -67, -55)))
