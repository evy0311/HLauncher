"""Translate the host's monotonic fix age at the projection process boundary."""
import time


def fresh_gps_payload(fix):
    if fix is None:
        return None
    now = time.monotonic()
    age = max(0, now - fix['at'])
    remaining = int((3 - age) * 1000)
    if remaining <= 0:
        return None
    wall = time.time()
    payload = dict(latitude=fix['latitude'], longitude=fix['longitude'],
                   remaining_ms=remaining, utc_ms=int((wall - age) * 1000))
    if fix.get('speed_until', 0) > now:
        payload['speed_kph'] = fix['speed_kph']
        payload['speed_expires_ms'] = int((wall + fix['speed_until'] - now) * 1000)
    return payload
