"""Translate the host's monotonic fix age at the projection process boundary."""
import time


def fresh_gps_payload(fix):
    if fix is None:
        return None
    age = max(0, time.monotonic() - fix['at'])
    remaining = int((3 - age) * 1000)
    if remaining <= 0:
        return None
    return dict(latitude=fix['latitude'], longitude=fix['longitude'],
                remaining_ms=remaining, utc_ms=int((time.time() - age) * 1000))
