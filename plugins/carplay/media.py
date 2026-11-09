"""Translate node-carplay MediaData patches to the launcher media contract."""
import math

NAMES = {'MediaSongName':'title', 'MediaArtistName':'artist',
         'MediaAlbumName':'album', 'MediaAPPName':'app',
         'MediaSongDuration':'duration_ms', 'MediaSongPlayTime':'position_ms'}


def normalize(raw):
    if not isinstance(raw, dict):
        return {}
    fields = {}
    for key, target in NAMES.items():
        if key not in raw:
            continue
        value = raw[key]
        if value is None:
            fields[target] = None
        elif target.endswith('_ms'):
            if type(value) in (int, float) and math.isfinite(value) and 0 <= value <= 604800000:
                fields[target] = round(value)
        elif isinstance(value, str):
            fields[target] = value[:512]
    # Unknown playback status codes remain unknown; do not guess from PCM traffic.
    return fields
