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
    subprocess.run(['chroot',str(root),'useradd','-m','-s','/bin/bash','-G','sudo','hlauncher'],check=True)
    uid=int(subprocess.run(['chroot',str(root),'id','-u','hlauncher'],capture_output=True,text=True,check=True).stdout)
    gid=int(subprocess.run(['chroot',str(root),'id','-g','hlauncher'],capture_output=True,text=True,check=True).stdout)
    ssh=root/'home/hlauncher/.ssh';ssh.mkdir(mode=0o700)
    (ssh/'authorized_keys').write_text(key+'\n');(ssh/'authorized_keys').chmod(0o600)
    for path in (ssh,ssh/'authorized_keys'):os.chown(path,uid,gid)
    dropin=root/'etc/ssh/sshd_config.d';dropin.mkdir(parents=True,exist_ok=True)
    (dropin/'00-hlauncher-local-test.conf').write_text('PasswordAuthentication no\nKbdInteractiveAuthentication no\nPermitRootLogin no\nPubkeyAuthentication yes\nAllowUsers hlauncher\n')
    sudo=root/'etc/sudoers.d/hlauncher-local-test';sudo.write_text('hlauncher ALL=(ALL) NOPASSWD: ALL\n');sudo.chmod(0o440)
    (root/'etc/hlauncher-ssh-autostart').write_text('1\n')
    boot=root/'boot/firmware' if (root/'boot/firmware/config.txt').exists() else root/'boot'
    (boot/'HLAUNCHER-LOCAL-TEST.txt').write_text('LOCAL TEST IMAGE - DO NOT PUBLISH\nSSH user: hlauncher\nUse the configured development key.\nNo previous radio pairing, Wi-Fi or HLauncher settings are included.\n')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',required=True);parser.add_argument('--public-key',required=True)
    args=parser.parse_args();configure(args.root,args.public_key)
