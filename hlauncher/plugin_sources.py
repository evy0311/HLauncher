"""Offline USB and GitHub Release sources for the same .hlp package format."""

from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import tempfile
from urllib.parse import quote

from .plugin_packages import MAX_BYTES
from .updater import download, sha256

REPO = r'[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9_.-]{1,100}'
ASSET = re.compile(r'[A-Za-z0-9._-]{1,120}\.hlp')
USB_TYPES = {'vfat', 'exfat'}


def github_repo(source):
    value = source.strip()
    for prefix in ('https://github.com/', 'github.com/'):
        if value.startswith(prefix):
            value = value.removeprefix(prefix).rstrip('/').removesuffix('.git')
            if not re.fullmatch(REPO, value) or value.split('/')[1] in ('.', '..'):
                raise ValueError('Enter a GitHub repository as owner/repo')
            return value
    return None


def github_assets(repo):
    repo = github_repo('github.com/' + repo)
    with tempfile.TemporaryDirectory() as scratch:
        info = Path(scratch) / 'release.json'
        download('https://api.github.com/repos/' + repo + '/releases/latest', info, 1024 * 1024)
        release = json.loads(info.read_text())
    if not isinstance(release, dict) or release.get('draft') or release.get('prerelease'):
        raise ValueError('Choose a repository with a published stable release')
    tag = release.get('tag_name')
    if not isinstance(tag, str) or not tag or len(tag) > 128 or not tag.isprintable():
        raise ValueError('Invalid GitHub release tag')
    assets = []
    for item in release.get('assets', []):
        name, size = item.get('name'), item.get('size')
        if not isinstance(name, str) or not ASSET.fullmatch(name) or type(size) is not int or not 0 < size <= MAX_BYTES:
            continue
        # Build the URL from the repository we requested, not from asset metadata.
        url = f'https://github.com/{repo}/releases/download/{quote(tag, safe="")}/{name}'
        digest = item.get('digest')
        if digest is not None and (not isinstance(digest, str) or not re.fullmatch(r'sha256:[a-f0-9]{64}', digest)):
            raise ValueError('Invalid GitHub release asset digest')
        assets.append(dict(name=name, size=size, url=url, digest=digest, repo=repo, tag=tag))
    if not assets:
        raise ValueError('The latest GitHub release has no .hlp packages')
    return assets[:32]


def fetch_asset(asset, destination):
    download(asset['url'], destination, MAX_BYTES, asset['size'])
    if asset['digest'] and asset['digest'] != 'sha256:' + sha256(destination):
        raise ValueError('GitHub package digest does not match')
    return f"GitHub {asset['repo']} @ {asset['tag']}"


def usb_devices():
    result = subprocess.run(['/usr/bin/lsblk', '--json', '--paths',
                             '--output', 'NAME,TYPE,TRAN,FSTYPE,MAJ:MIN'],
                            capture_output=True, check=True, timeout=5)
    devices = []

    def visit(node, attached=False):
        attached = attached or node.get('tran') == 'usb'
        path = node.get('name', '')
        filesystem = node.get('fstype')
        if (attached and node.get('type') in ('disk', 'part') and filesystem in USB_TYPES
                and re.fullmatch(r'/dev/[A-Za-z0-9_-]+', path)):
            devices.append((path, filesystem, node.get('maj:min')))
        for child in node.get('children', []):
            visit(child, attached)

    for node in json.loads(result.stdout)['blockdevices']:
        visit(node)
    return devices[:8]


@contextmanager
def mount_usb(device):
    path, filesystem, number = device
    if device not in usb_devices():
        raise ValueError('The USB drive was removed. Scan again')
    info = Path(path).stat()
    if not stat.S_ISBLK(info.st_mode) or number != f'{os.major(info.st_rdev)}:{os.minor(info.st_rdev)}':
        raise ValueError('The USB drive changed. Scan again')
    mount = Path(tempfile.mkdtemp(prefix='hlauncher-usb-'))
    try:
        subprocess.run(['/usr/bin/mount', '-t', filesystem, '-o', 'ro,nosuid,nodev,noexec',
                        '--', path, str(mount)], check=True, capture_output=True, timeout=8)
        try:
            yield mount
        finally:
            subprocess.run(['/usr/bin/umount', '-l', '--', str(mount)],
                           check=True, capture_output=True, timeout=5)
    finally:
        # rmdir cannot traverse a mount even if umount fails.
        if not os.path.ismount(mount):
            mount.rmdir()


def usb_packages():
    packages = []
    for device in usb_devices():
        with mount_usb(device) as root:
            folders = [root]
            if (root / 'HLauncher').is_dir() and not (root / 'HLauncher').is_symlink():
                folders.append(root / 'HLauncher')
            for folder in folders:
                with os.scandir(folder) as entries:
                    for index, item in enumerate(entries):
                        if index >= 4096 or len(packages) >= 32:
                            break
                        if (not item.name.startswith('.') and item.name.lower().endswith('.hlp')
                                and len(item.name) <= 120
                                and item.name.isprintable() and item.is_file(follow_symlinks=False)):
                            packages.append((item.name, device, Path(item.path).relative_to(root)))
    return sorted(packages, key=lambda package: package[0].casefold())


def copy_usb(candidate, destination):
    _, device, relative = candidate
    with mount_usb(device) as root:
        path = root / relative
        if not path.resolve().is_relative_to(root) or path.is_symlink():
            raise ValueError('Invalid USB package path')
        with path.open('rb') as source, destination.open('xb') as target:
            remaining = MAX_BYTES
            while block := source.read(min(65536, remaining + 1)):
                remaining -= len(block)
                if remaining < 0:
                    raise ValueError('Plugin package is too large')
                target.write(block)
    return 'USB'
