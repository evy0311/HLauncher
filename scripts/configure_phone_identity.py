"""Advertise the Classic Bluetooth smartphone device class; preserve HLauncher name.

Run with --apply as root. This changes configuration only, never pairing data or
services. Restart bluetooth separately when the radio is disconnected.
"""
import argparse
from datetime import datetime, timezone
import os
from pathlib import Path
import re
import shutil
import tempfile

PHONE_CLASS = '0x00020c'  # Phone major class, smartphone minor class.


def phone_config(text):
    lines=text.splitlines(keepends=True)
    start=next((i for i,line in enumerate(lines) if line.strip()=='[General]'),None)
    if start is None:
        return text+('\n' if text and not text.endswith('\n') else '')+'[General]\nClass = '+PHONE_CLASS+'\n'
    end=next((i for i in range(start+1,len(lines)) if lines[i].lstrip().startswith('[')),len(lines))
    found=False
    for i in range(start+1,end):
        if re.match(r'\s*Class\s*=',lines[i]):
            lines[i]='Class = '+PHONE_CLASS+'\n';found=True
    if not found:lines.insert(start+1,'Class = '+PHONE_CLASS+'\n')
    return ''.join(lines)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply',action='store_true')
    args=parser.parse_args()
    path=Path('/etc/bluetooth/main.conf')
    original=path.read_text()
    updated=phone_config(original)
    if updated==original:
        print('Smartphone device class already configured.');return
    if not args.apply:
        print('Smartphone device class needs configuration. Use --apply to save.');return
    if os.geteuid()!=0:parser.error('--apply requires root')
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    backup=path.with_name(path.name+'.hlauncher-'+stamp+'.bak')
    shutil.copy2(path,backup)
    info=path.stat()
    with tempfile.NamedTemporaryFile(mode='w',dir=path.parent,delete=False) as output:
        temp=Path(output.name)
        try:
            output.write(updated);output.flush();os.fsync(output.fileno())
            os.chmod(temp,info.st_mode & 0o777)
            os.chown(temp,info.st_uid,info.st_gid)
            os.replace(temp,path)
        finally:temp.unlink(missing_ok=True)
    print('Configured smartphone device class; backup: '+str(backup))


if __name__=='__main__':main()
