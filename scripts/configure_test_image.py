#!/usr/bin/env python3
"""Optional development SSH public key on an OFFLINE image; no private keys."""
import argparse
import os
from pathlib import Path
import re
import subprocess


def configure(root, public_key):
    root=Path(root).resolve();key=Path(public_key).read_text().strip()
    if root==Path('/') or not (root/'etc/os-release').is_file():raise ValueError('Use an offline image root')
    if '\n' in key or not re.fullmatch(r'ssh-ed25519 [A-Za-z0-9+/]+=*(?: [^\r\n]*)?',key):
        raise ValueError('Use an Ed25519 SSH public key')
    if any(row.startswith('pi:') for row in (root/'etc/passwd').read_text().splitlines()):
        existing=(root/'home/pi')
        if any(path.name not in ('.bashrc','.profile','.bash_logout') for path in existing.iterdir()):
            raise ValueError('Refusing to change an existing personal pi account')
        shadow={row.split(':')[0]:row.split(':')[1] for row in (root/'etc/shadow').read_text().splitlines()}
        if shadow.get('pi') not in ('*','!','!!'):raise ValueError('Refusing to change a configured login')
        subprocess.run(['chroot',str(root),'usermod','-aG','sudo','-s','/bin/bash','pi'],check=True)
    else:
        subprocess.run(['chroot',str(root),'useradd','-m','-s','/bin/bash','-G','sudo','pi'],check=True)
    subprocess.run(['chroot',str(root),'chpasswd'],input='pi:raspberry\n',text=True,check=True,capture_output=True)
    uid=int(subprocess.run(['chroot',str(root),'id','-u','pi'],capture_output=True,text=True,check=True).stdout)
    gid=int(subprocess.run(['chroot',str(root),'id','-g','pi'],capture_output=True,text=True,check=True).stdout)
    ssh=root/'home/pi/.ssh';ssh.mkdir(mode=0o700)
    (ssh/'authorized_keys').write_text(key+'\n');(ssh/'authorized_keys').chmod(0o600)
    for path in (ssh,ssh/'authorized_keys'):os.chown(path,uid,gid)
    dropin=root/'etc/ssh/sshd_config.d';dropin.mkdir(parents=True,exist_ok=True)
    (dropin/'00-hlauncher-local-test.conf').write_text('PasswordAuthentication yes\nKbdInteractiveAuthentication no\nPermitRootLogin no\n')
    sudo=root/'etc/sudoers.d/hlauncher-local-test';sudo.write_text('pi ALL=(ALL) NOPASSWD: ALL\n');sudo.chmod(0o440)
    subprocess.run(['systemctl','--root',str(root),'enable','ssh.service'],check=True,capture_output=True)
    boot=root/'boot/firmware' if (root/'boot/firmware/config.txt').exists() else root/'boot'
    (boot/'HLAUNCHER-LOCAL-TEST.txt').write_text('LOCAL TEST IMAGE - DO NOT PUBLISH\nSSH user: pi\nDefault SSH password: raspberry. An optional local development key is also installed.\nNo previous radio pairing, Wi-Fi or HLauncher settings are included.\n')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',required=True);parser.add_argument('--public-key',required=True)
    args=parser.parse_args();configure(args.root,args.public_key)
