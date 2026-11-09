"""Managed password SSH and cached status for the local network settings UI."""
import json
import os
from pathlib import Path
import shutil
import subprocess
from .setup_state import atomic_json

USERNAME='pi'
DEFAULT_PASSWORD='raspberry'
MANAGED=Path('/etc/hlauncher-ssh-managed')


def execute(args, **kwargs):
    return subprocess.run(args,check=kwargs.pop('check',True),text=True,capture_output=True,timeout=15,**kwargs)


def status(folder):
    try:
        value=json.loads((Path(folder)/'ssh-status.json').read_text())
        return dict(available=value.get('available') is True,enabled=value.get('enabled') is True,
                    username=USERNAME,password=DEFAULT_PASSWORD)
    except (OSError,ValueError,TypeError,AttributeError):
        return dict(available=False,enabled=False,username=USERNAME,password=DEFAULT_PASSWORD)


def refresh(folder,run=execute):
    available=bool(shutil.which('sshd',path='/usr/sbin:/usr/bin:/sbin:/bin'))
    try: enabled=run(['systemctl','is-active','ssh.service'],check=False).returncode==0 if available else False
    except (OSError,subprocess.SubprocessError):enabled=False
    value=dict(available=available,enabled=enabled,username=USERNAME,password=DEFAULT_PASSWORD)
    atomic_json(Path(folder)/'ssh-status.json',value)
    return value


def initialize(folder,run=execute,system=Path('/')):
    """Configure only an explicitly managed image; never reset a later password."""
    folder=Path(folder);system=Path(system)
    marker=folder/'ssh-initialized.json'
    if marker.exists():return
    if not (system/'etc/hlauncher-ssh-managed').exists():return
    users=(system/'etc/passwd').read_text().splitlines()
    if not any(line.startswith(USERNAME+':') for line in users):
        run(['useradd','-m','-s','/bin/bash','-G','sudo',USERNAME])
    else:run(['usermod','-aG','sudo','-s','/bin/bash',USERNAME])
    # Passwords never enter process arguments or logs.
    run(['chpasswd'],input=USERNAME+':'+DEFAULT_PASSWORD+'\n')
    dropin=system/'etc/ssh/sshd_config.d';dropin.mkdir(parents=True,exist_ok=True)
    (dropin/'00-hlauncher.conf').write_text('PasswordAuthentication yes\nKbdInteractiveAuthentication no\nPermitRootLogin no\nPubkeyAuthentication yes\n')
    (dropin/'00-hlauncher-local-test.conf').unlink(missing_ok=True)
    (dropin/'rename_user.conf').unlink(missing_ok=True)
    (system/'run/sshd').mkdir(mode=0o755,parents=True,exist_ok=True)
    run(['ssh-keygen','-A'])
    run(['/usr/sbin/sshd','-t'])
    # The persistent ssh-disabled marker gates boot even with an overlay OS.
    run(['systemctl','enable','ssh.service'])
    run(['systemctl','disable','ssh.socket'],check=False)
    atomic_json(marker,dict(username=USERNAME,configured=True))


def apply(enabled,folder,run=execute,boot=False):
    if type(enabled) is not bool:raise ValueError('Choose SSH On or Off')
    from .config import Preferences
    folder=Path(folder)
    if not shutil.which('sshd',path='/usr/sbin:/usr/bin:/sbin:/bin'):
        raise ValueError('SSH server is not installed')
    initialize(folder,run)
    marker=folder/'ssh-disabled'
    if enabled:
        marker.unlink(missing_ok=True)
        command=['systemctl','start']+(['--no-block'] if boot else [])+['ssh.service']
        run(command)
        if not boot:run(['systemctl','reload','ssh.service'])
    else:
        atomic_json(marker,dict(disabled=True))
        command=['systemctl','stop']+(['--no-block'] if boot else [])
        run([*command,'ssh.socket'],check=False)
        run([*command,'ssh.service'])
    prefs=Preferences(folder/'settings.json');prefs.data['ssh_enabled']=enabled;prefs.save()
    return refresh(folder,run)
