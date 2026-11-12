"""Nonblocking UI client; downloads and service restarts belong to the updater."""
import json
import os
from pathlib import Path
from .config import STATE_DIR


def status(folder=STATE_DIR):
    try:
        value=json.loads((Path(folder)/'update-status.json').read_text())
        if isinstance(value,dict):return value
    except (OSError,ValueError):pass
    return dict(phase='unavailable',message='Updates require an update-enabled HLauncher image')


def offered_plugin_api(version):
    from .updater import read
    # The updater creates this offer only after verifying signed release metadata.
    offer = read('/persist/hlauncher/download/offer.json').get('manifest')
    if version and isinstance(offer, dict) and offer.get('version') == version:
        api = offer.get('plugin_api')
        if type(api) is int and 1 <= api <= 65535:
            return api
    return None


def request(operation, folder=STATE_DIR):
    if operation not in ('check','install','rollback','import'):raise ValueError('Unknown update operation')
    path=Path(folder)/'update-request.json'
    # Write a private complete file, then publish it without replacing queued work.
    import tempfile
    fd,name=tempfile.mkstemp(prefix='.update-request-',dir=path.parent)
    try:
        with os.fdopen(fd,'w') as output:
            json.dump(dict(operation=operation),output);output.flush();os.fsync(output.fileno())
        os.link(name,path)
        directory=os.open(path.parent,os.O_RDONLY)
        try:os.fsync(directory)
        finally:os.close(directory)
    finally:os.unlink(name)
