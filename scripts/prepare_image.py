#!/usr/bin/env python3
"""Sanitize an OFFLINE image root and configure its dedicated /persist partition.

Never run against / or a live Pi. The image builder mounts both filesystems first.
"""
import argparse
from pathlib import Path
import shutil
import subprocess
import os


def prepare(root, persist, state_uuid, country):
    root, persist = Path(root).resolve(), Path(persist).resolve()
    if root == Path('/') or not (root/'etc/os-release').is_file():
        raise ValueError('An offline Raspberry Pi OS root mount is required')
    if not os.path.ismount(root) or not os.path.ismount(persist):
        raise ValueError('Both root and persistent image filesystems must be mounted')
    import re
    if not re.fullmatch(r'[0-9a-fA-F-]{36}',state_uuid) or not re.fullmatch('[A-Z]{2}',country):
        raise ValueError('Invalid state UUID or Wi-Fi country')
    # This function is intentionally image-only; never clone a development system.
    for name in ('var/lib/hlauncher','var/lib/bluetooth','var/log/hlauncher','etc/NetworkManager/system-connections'):
        folder = root/name
        folder.mkdir(parents=True,exist_ok=True)
        for item in folder.iterdir():
            if item.is_dir() and not item.is_symlink():shutil.rmtree(item)
            else:item.unlink()
    for key in (root/'etc/ssh').glob('ssh_host_*'):key.unlink()
    (root/'etc/machine-id').write_text('')
    dbus_id=root/'var/lib/dbus/machine-id'
    if dbus_id.exists() or dbus_id.is_symlink():dbus_id.unlink()
    dbus_id.parent.mkdir(parents=True,exist_ok=True)
    dbus_id.symlink_to('/etc/machine-id')
    for folder in ('state','bluetooth','network'):
        (persist/folder).mkdir(mode=0o700,parents=True,exist_ok=True)
    (persist/'.hlauncher-state-v1').write_text('1\n')
    (root/'persist').mkdir(exist_ok=True)
    fstab=root/'etc/fstab'
    text=fstab.read_text()
    if '# HLauncher persistence' in text:raise ValueError('Image already prepared')
    text += f'''\n# HLauncher persistence: required mounts fail closed, never silently use RAM.
UUID={state_uuid} /persist ext4 defaults,noatime 0 2
/persist/state /var/lib/hlauncher none bind,x-systemd.requires-mounts-for=/persist 0 0
/persist/bluetooth /var/lib/bluetooth none bind,x-systemd.requires-mounts-for=/persist 0 0
/persist/network /etc/NetworkManager/system-connections none bind,x-systemd.requires-mounts-for=/persist 0 0
tmpfs /var/log tmpfs defaults,noatime,nosuid,nodev,size=32m,mode=0755 0 0
'''
    fstab.write_text(text)
    (root/'etc/hlauncher.env').write_text('HLAUNCHER_RADIO_ADDRESS=00:00:00:00:00:00\nHLAUNCHER_LOG_DIR=/var/log/hlauncher\nHLAUNCHER_WIFI_COUNTRY='+country+'\n')
    (root/'etc/modprobe.d/hlauncher-country.conf').write_text('options cfg80211 ieee80211_regdom='+country+'\n')
    journal=root/'etc/systemd/journald.conf.d';journal.mkdir(parents=True,exist_ok=True)
    (journal/'hlauncher.conf').write_text('[Journal]\nStorage=volatile\nRuntimeMaxUse=16M\n')
    # Fresh images should not boot an account-creation wizard on the radio console.
    for service in ('userconfig.service','userconfig-pi.service','resize2fs_once.service'):
        subprocess.run(['systemctl','--root',str(root),'mask',service],check=True,capture_output=True)
    for service in ('hlauncher','hlauncher-audio','hlauncher-connect','hlauncher-pairing','hlauncher-recovery','hlauncher-firstboot','hlauncher-grow'):
        subprocess.run(['systemctl','--root',str(root),'enable',service+'.service'],check=True,capture_output=True)
    if (root/'etc/hlauncher-updater/config.json').is_file():
        subprocess.run(['systemctl','--root',str(root),'enable','hlauncher-updater.service'],check=True,capture_output=True)
    subprocess.run(['systemctl','--root',str(root),'disable','ssh.service'],check=True,capture_output=True)
    # Kernel/partitions cannot expand past the state partition. The builder sizes root first.
    for path in (root/'boot/cmdline.txt', root/'boot/firmware/cmdline.txt'):
        if path.exists():
            words=[x for x in path.read_text().split() if not x.startswith('init=') or 'init_resize' not in x]
            words = [x for x in words if not x.startswith('video=HDMI-A-1:')]
            words.append('video=HDMI-A-1:720x480@60D')
            path.write_text(' '.join(words)+'\n')


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root',type=Path,required=True);p.add_argument('--persist',type=Path,required=True)
    p.add_argument('--state-uuid',required=True);p.add_argument('--country',required=True)
    a=p.parse_args();prepare(a.root,a.persist,a.state_uuid,a.country)


if __name__=='__main__':main()
