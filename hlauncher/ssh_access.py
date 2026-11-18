"""Managed password SSH and cached status for the local network settings UI."""
import json
from pathlib import Path
import shutil
import subprocess
from .config import RUNTIME_DIR
from .setup_state import DEFAULT_PASSWORD, atomic_json

USERNAME='hlauncher'
MANAGED=Path('/etc/hlauncher-ssh-managed')


def execute(args, **kwargs):
    return subprocess.run(args,check=kwargs.pop('check',True),text=True,capture_output=True,timeout=15,**kwargs)


def status(runtime=None):
    try:
        value=json.loads(((runtime or RUNTIME_DIR)/'ssh-status.json').read_text())
        return dict(available=value.get('available') is True,enabled=value.get('enabled') is True,
                    username=USERNAME,password=DEFAULT_PASSWORD)
    except (OSError,ValueError,TypeError,AttributeError):
        return dict(available=False,enabled=False,username=USERNAME,password=DEFAULT_PASSWORD)


def refresh(run=execute, *, runtime=None):
    available=MANAGED.is_file() and bool(shutil.which('sshd',path='/usr/sbin:/usr/bin:/sbin:/bin'))
    try: enabled=run(['systemctl','is-active','ssh.service'],check=False).returncode==0 if available else False
    except (OSError,subprocess.SubprocessError):enabled=False
    value=dict(available=available,enabled=enabled,username=USERNAME,password=DEFAULT_PASSWORD)
    atomic_json((runtime or RUNTIME_DIR)/'ssh-status.json', value, durable=False)
    return value


def initialize(folder,run=execute,system=Path('/')):
    """Configure only an explicitly managed image; never reset a later password."""
    folder=Path(folder);system=Path(system)
    marker=folder/'ssh-initialized.json'
    dev_image = (system/'etc/hlauncher-ssh-autostart').is_file()
    if marker.exists():
        try:
            initialized = json.loads(marker.read_text())
            if initialized.get('username') == USERNAME and (not dev_image or initialized.get('password_enabled')):
                return
        except (OSError, ValueError, AttributeError):pass
    if not (system/'etc/hlauncher-ssh-managed').exists():return
    users=(system/'etc/passwd').read_text().splitlines()
    if not any(line.startswith(USERNAME+':') for line in users):
        run(['useradd','-m','-s','/bin/bash','-G','sudo',USERNAME])
    else:run(['usermod','-aG','sudo','-s','/bin/bash',USERNAME])
    if any(line.startswith('pi:') for line in users):
        run(['passwd','-l','pi'])
    # Passwords never enter process arguments or logs.
    dropin=system/'etc/ssh/sshd_config.d';dropin.mkdir(parents=True,exist_ok=True)
    run(['chpasswd'],input=USERNAME+':'+DEFAULT_PASSWORD+'\n')
    (dropin/'00-hlauncher.conf').write_text(
        'PasswordAuthentication yes\nKbdInteractiveAuthentication no\nPermitRootLogin no\n'
        'PubkeyAuthentication yes\nAllowUsers hlauncher\n')
    (dropin/'00-hlauncher-local-test.conf').unlink(missing_ok=True)
    (dropin/'rename_user.conf').unlink(missing_ok=True)
    (system/'run/sshd').mkdir(mode=0o755,parents=True,exist_ok=True)
    run(['ssh-keygen','-A'])
    run(['/usr/sbin/sshd','-t'])
    atomic_json(marker,dict(username=USERNAME,configured=True,password_enabled=True))


def apply(enabled,folder,run=execute,boot=False, *, runtime=None):
    if type(enabled) is not bool:raise ValueError('Choose SSH On or Off')
    from .config import Preferences
    folder=Path(folder)
    if not shutil.which('sshd',path='/usr/sbin:/usr/bin:/sbin:/bin'):
        raise ValueError('SSH server is not installed')
    if not MANAGED.is_file():raise ValueError('SSH controls require a managed HLauncher image')
    initialize(folder,run)
    marker=folder/'ssh-enabled'
    if enabled:
        atomic_json(marker, dict(enabled=True))
        command=['systemctl','start']+(['--no-block'] if boot else [])+['ssh.service']
        try:
            run(command)
        except (OSError, subprocess.SubprocessError):
            marker.unlink(missing_ok=True)
            raise
    else:
        marker.unlink(missing_ok=True)
        command=['systemctl','stop']+(['--no-block'] if boot else [])
        run([*command,'ssh.socket'],check=False)
        run([*command,'ssh.service'])
    if not boot:
        prefs=Preferences(folder/'settings.json');prefs.data['ssh_enabled']=enabled;prefs.save(force=('ssh_enabled',))
    return refresh(run, runtime=runtime)
