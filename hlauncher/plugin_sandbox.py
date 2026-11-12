"""Linux sandbox and the opt-in connection to one approved TCP endpoint."""

from array import array
import ipaddress
import os
from pathlib import Path
import re
import socket
import stat
import sys
import threading
import time

from .config import ROOT

UID = 65534


def parse_endpoint(value):
    host, separator, port = value.rpartition(':')
    if not separator or not re.fullmatch(r'[0-9]{1,5}', port) or not 1 <= int(port) <= 65535:
        raise ValueError('Enter a numeric IP address and TCP port')
    try:
        address = ipaddress.ip_address(host.strip('[]'))
    except ValueError as exc:
        raise ValueError('Enter a numeric IP address and TCP port') from exc
    if address.is_unspecified or address.is_multicast:
        raise ValueError('Choose a specific unicast IP address')
    return str(address), int(port)


def cameras():
    devices = []
    for path in sorted(Path('/dev').glob('video*')):
        if not re.fullmatch(r'video[0-9]{1,3}', path.name):
            continue
        try:
            camera_stat(path)
            devices.append(str(path))
        except (ValueError, OSError):
            continue
    return devices


def camera_stat(path):
    device = Path(path).lstat()
    if not stat.S_ISCHR(device.st_mode) or os.major(device.st_rdev) != 81:
        raise ValueError('Selected camera is not a V4L2 device')
    return device


def command(manifest):
    if sys.platform != 'linux' or os.geteuid() != 0 or not Path('/usr/bin/bwrap').is_file():
        raise ValueError('External plugins need the Linux bubblewrap sandbox')
    args = [
        '/usr/bin/systemd-run', '--scope', '--quiet', '--collect',
        '-p', 'MemoryMax=384M', '-p', 'TasksMax=48', '-p', 'CPUQuota=200%',
        '/usr/bin/bwrap', '--unshare-pid', '--unshare-net', '--unshare-ipc',
        '--unshare-uts', '--die-with-parent',
        '--cap-drop', 'ALL', '--cap-add', 'CAP_SETUID', '--cap-add', 'CAP_SETGID', '--cap-add', 'CAP_SETPCAP',
        '--ro-bind', '/usr', '/usr', '--ro-bind-try', '/etc/ssl/certs', '/etc/ssl/certs',
        '--dev', '/dev', '--proc', '/proc',
        '--size', '33554432', '--tmpfs', '/tmp',
        '--ro-bind', str(manifest.path), '/plugin',
        '--ro-bind', str(ROOT / 'sdk'), '/sdk',
        '--bind', str(manifest.data_path), '/data',
        '--chdir', '/plugin',
    ]
    for name in ('bin', 'sbin', 'lib', 'lib64'):
        path = Path('/') / name
        if path.is_symlink():
            args.extend(('--symlink', os.readlink(path), str(path)))
        elif path.is_dir():
            args.extend(('--ro-bind', str(path), str(path)))
    groups = ['--clear-groups']
    if manifest.camera:
        try:
            device = camera_stat(manifest.camera)
        except FileNotFoundError as exc:
            raise ValueError('Connect the selected USB camera and try again') from exc
        args.extend(('--dev-bind', manifest.camera, manifest.camera))
        groups = ['--groups', str(device.st_gid)] if device.st_gid else ['--clear-groups']
    interpreter = '/usr/bin/python3' if manifest.entrypoint[0] == 'python3' else '/usr/bin/node'
    entry = str(Path('/plugin') / Path(manifest.entrypoint[1]).relative_to(manifest.path))
    return args + [
        '--remount-ro', '/', '--',
        '/usr/bin/setpriv', f'--reuid={UID}', f'--regid={UID}', *groups,
        '--bounding-set=-all', '--inh-caps=-all', '--ambient-caps=-all', '--no-new-privs', '--',
        '/usr/bin/prlimit', '--nofile=128',
        '--fsize=33554432', '--core=0', '--', interpreter, entry,
    ]


def environment(env, manifest):
    keys = ('HLAUNCHER_CONTROL_FD', 'HLAUNCHER_FRAME_FD', 'HLAUNCHER_PLAYBACK_FD',
            'HLAUNCHER_WIDTH', 'HLAUNCHER_HEIGHT', 'HLAUNCHER_NETWORK_FD')
    allowed = {key: env[key] for key in keys if key in env}
    allowed.update(PATH='/usr/bin:/bin', LANG='C.UTF-8', PYTHONPATH='/sdk',
                   PYTHONUNBUFFERED='1', PYTHONDONTWRITEBYTECODE='1',
                   HOME='/data', HLAUNCHER_DATA_DIR='/data', HLAUNCHER_STATE_DIR='/data',
                   HLAUNCHER_LOG_DIR='/data')
    if manifest.camera:
        allowed['HLAUNCHER_CAMERA_DEVICE'] = manifest.camera
    return allowed


class Network:
    def __init__(self, endpoint):
        self.endpoint = parse_endpoint(endpoint)
        try:
            self.host, self.child = socket.socketpair(socket.AF_UNIX, socket.SOCK_SEQPACKET)
        except OSError:
            self.host, self.child = socket.socketpair(socket.AF_UNIX, socket.SOCK_DGRAM)
        self.host.settimeout(.5)
        self.closed = threading.Event()

    def start(self):
        self.child.close()
        threading.Thread(target=self.serve, daemon=True).start()

    def serve(self):
        last_attempt = 0
        with self.host:
            while not self.closed.is_set():
                try:
                    request = self.host.recv(16)
                except TimeoutError:
                    continue
                except OSError:
                    return
                if not request:
                    return
                if request != b'connect' or time.monotonic() - last_attempt < 1:
                    return
                last_attempt = time.monotonic()
                try:
                    with socket.create_connection(self.endpoint, timeout=2) as connection:
                        if self.closed.is_set():
                            return
                        connection.setblocking(True)
                        rights = [(socket.SOL_SOCKET, socket.SCM_RIGHTS, array('i', [connection.fileno()]))]
                        self.host.sendmsg([b'+'], rights)
                except OSError:
                    try:
                        self.host.send(b'-')
                    except OSError:
                        return

    def close(self):
        self.closed.set()
        self.child.close()
        self.host.close()
