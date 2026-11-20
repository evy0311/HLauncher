"""Signed development snapshot identity; independent of the on-image updater."""
from datetime import datetime, timezone
import re
from . import updater


def branch_name(value):
    if (not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._/-]{0,199}', value)
            or '..' in value or any(part in ('', '.', '..') or part.startswith('.')
                                  or part.endswith(('.', '.lock')) for part in value.split('/'))):
        raise ValueError('Invalid development branch')
    return value


def metadata(info):
    branch_name(info.get('branch'))
    if not re.fullmatch('[0-9a-f]{40}', str(info.get('commit', ''))):
        raise ValueError('Missing development source commit')
    if not isinstance(info.get('build_id'), str) or not re.fullmatch(r'[A-Za-z0-9._-]{1,80}', info['build_id']):
        raise ValueError('Invalid development build identity')
    version = updater.version(info.get('version'))
    if version[0] < 10000 or info['version'] != '.'.join(map(str, version)):
        raise ValueError('Development builds require a reserved installation version')
    try:
        built = datetime.fromisoformat(info['built_at'].replace('Z', '+00:00'))
        if built.tzinfo is None or built.utcoffset().total_seconds() != 0:
            raise ValueError()
    except (KeyError, ValueError, TypeError, AttributeError):
        raise ValueError('Invalid development build date') from None
    return {key: info[key] for key in ('branch', 'commit', 'built_at', 'build_id')}


def build_version(number):
    """Globally unique build number encoded in the legacy three-part format."""
    if type(number) is not int or not 0 <= number < 90000 * 100000**2:
        raise ValueError('Development build number is out of range')
    return f'{10000+number//100000**2}.{number//100000%100000}.{number%100000}'


def build_metadata(branch, commit, identity):
    return dict(branch=branch_name(branch), commit=commit, build_id=str(identity),
                built_at=datetime.now(timezone.utc).isoformat(timespec='seconds'))
