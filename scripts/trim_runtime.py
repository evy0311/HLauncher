#!/usr/bin/env python3
"""Remove build-only dependencies/caches inside a fresh OFFLINE image chroot."""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess

RUNTIME = '''python3 python3-pil python3-numpy python3-dbus python3-gi python3-bleak
bluez bluez-alsa-utils libasound2-plugin-bluez alsa-utils openssl pipewire pipewire-bin
libspa-0.2-modules libsamplerate0 libsoxr0 nodejs libusb-1.0-0 libdrm2 libavcodec59
libavutil57 libswscale6 fonts-dejavu-core fbset usbutils network-manager iproute2 iw rfkill
raspi-config initramfs-tools overlayroot openssh-server cloud-guest-utils fdisk e2fsprogs util-linux'''.split()
TOOLS = set('build-essential cmake cmake-data make git git-man autoconf automake autotools-dev libtool libtool-bin pkg-config pkgconf pkgconf-bin m4 dpkg-dev fakeroot patch npm node-gyp protobuf-compiler mkvtoolnix ffmpeg'.split())


def run(args,**kwargs):
    if args[0]=='apt-get':args=[args[0],'-o','Dpkg::Use-Pty=0',*args[1:]]
    return subprocess.run(args,check=True,text=True,**kwargs)


def owners(path):
    # Debian's /usr merge may expose libraries through either spelling.
    names={path,os.path.realpath(path)}
    if path.startswith('/usr/lib/'):names.add(path[4:])
    elif path.startswith('/lib/'):names.add('/usr'+path)
    for name in names:
        result=subprocess.run(['dpkg-query','-S',name],capture_output=True,text=True)
        if result.returncode==0:
            return {line.rsplit(': ',1)[0] for line in result.stdout.splitlines() if ': ' in line}
    raise ValueError('No runtime package owns '+path)


def native_dependencies():
    packages=set()
    for root in (Path('/opt/hlauncher'),Path('/opt/hlauncher-deps')):
        for path in root.rglob('*'):
            if not path.is_file():continue
            with path.open('rb') as f:magic=f.read(4)
            if magic!=b'\x7fELF':continue
            result=subprocess.run(['ldd',str(path)],text=True,capture_output=True,env=dict(os.environ,LD_LIBRARY_PATH='/opt/hlauncher-deps/lib:/opt/hlauncher-deps/lib64'))
            if 'not found' in result.stdout:raise ValueError('Missing runtime library: '+str(path))
            for line in result.stdout.splitlines():
                match=re.search(r'(?:=>\s*)?(/\S+)',line)
                if match and not match[1].startswith(('/opt/','/persist/')):packages.update(owners(match[1]))
    return packages


def remove(path):
    if path.is_dir() and not path.is_symlink():shutil.rmtree(path)
    else:path.unlink(missing_ok=True)


def main():
    if Path('/run/systemd/system').exists() or Path('/etc/machine-id').read_text().strip():
        raise ValueError('Use only an offline fresh-image chroot')
    for folder in ('state','network','bluetooth'):
        if any((Path('/persist')/folder).iterdir()):raise ValueError('Image contains user state')
    os.environ['DEBIAN_FRONTEND']='noninteractive'
    run(['apt-get','install','-y','--no-install-recommends',*RUNTIME])
    # npm ships builds for Android, Windows, macOS and other CPU architectures.
    for folder in Path('/opt/hlauncher').rglob('prebuilds'):
        if folder.is_dir():
            for path in folder.iterdir():
                if path.name!='linux-arm64':remove(path)
    keep=native_dependencies()
    run(['apt-mark','manual',*RUNTIME,*sorted(keep)])
    listing=run(['dpkg-query','-W','-f=${binary:Package}\t${db:Status-Status}\n'],capture_output=True).stdout
    installed={line.split('\t')[0] for line in listing.splitlines() if line.endswith('\tinstalled')}
    purge=sorted(name for name in installed if (plain:=name.split(':')[0]) in TOOLS or plain.endswith('-dev') or plain.startswith('linux-headers-') or re.fullmatch(r'linux-image-(?:rpi-2712|.+-rpi-2712)',plain) or re.fullmatch(r'(gcc|g\+\+|cpp)(-\d+)?',plain))
    if set(purge)&keep:raise ValueError('Development package is still a native runtime dependency')
    if purge:run(['apt-get','purge','-y',*purge])
    run(['apt-get','autoremove','--purge','-y'])
    run(['apt-get','clean'])
    for path in Path('/var/lib/apt/lists').iterdir():
        if path.name!='lock':remove(path)
    for name in ('/root/.cache','/root/.npm','/usr/share/man','/usr/share/info'):
        path=Path(name)
        if path.exists():remove(path)
    for folder in Path('/usr/share/doc').iterdir():
        if not folder.is_dir() or folder.is_symlink():continue
        for path in folder.iterdir():
            if not path.name.lower().startswith(('copyright','license','licence','copying')):remove(path)
    for path in Path('/usr/share/locale').iterdir():
        if path.is_dir() and path.name not in ('en','en_GB','en_US'):remove(path)
    native_dependencies()  # Check again AFTER APT has removed automatic packages.
    manifest=dict(runtime_packages=RUNTIME,native_library_packages=sorted(keep),removed_build_packages=purge)
    Path('/etc/hlauncher-runtime-packages.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print('Runtime image trimmed; native libraries and package copyright notices retained',flush=True)


if __name__=='__main__':main()
