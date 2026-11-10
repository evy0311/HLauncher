#!/usr/bin/env python3
"""Reject booted/personal roots while allowing Raspberry Pi OS's locked pi skeleton."""
from pathlib import Path
import sys


def check(root):
    root=Path(root).resolve()
    if root==Path('/') or not (root/'etc/os-release').is_file():raise ValueError('An offline official OS root is required')
    if (root/'opt/hlauncher').exists():raise ValueError('HLauncher is already installed')
    identity=(root/'etc/machine-id').read_text().strip()
    if identity not in ('','uninitialized'):raise ValueError('The image has already booted')
    accounts={line.split(':')[0]:line.split(':') for line in (root/'etc/passwd').read_text().splitlines()}
    users=[name for name,row in accounts.items() if 1000<=int(row[2])<65000]
    if users not in ([],['pi']):raise ValueError('The image has personal accounts')
    homes=list((root/'home').iterdir())
    if homes:
        if len(homes)!=1 or homes[0].name!='pi':raise ValueError('The image has personal home directories')
        if any(path.name not in ('.bashrc','.profile','.bash_logout') for path in homes[0].iterdir()):
            raise ValueError('The image has personal home files')
        for path in homes[0].iterdir():
            skeleton=root/'etc/skel'/path.name
            if not skeleton.is_file() or path.read_bytes()!=skeleton.read_bytes():raise ValueError('Default home files were modified')
    if 'pi' in users:
        shadow={line.split(':')[0]:line.split(':')[1] for line in (root/'etc/shadow').read_text().splitlines()}
        if shadow.get('pi') not in ('*','!','!!'):raise ValueError('The image has a configured login password')
    for name in ('var/lib/bluetooth','etc/NetworkManager/system-connections'):
        folder=root/name
        if folder.exists() and any(folder.iterdir()):raise ValueError('The image contains pairing or network data')


if __name__=='__main__':
    try:check(sys.argv[1])
    except (ValueError,OSError,IndexError) as exc:raise SystemExit('Use a pristine official OS image: '+str(exc))
