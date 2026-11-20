#!/usr/bin/env python3
"""Package an OFFLINE, fully built ARM64 image and seed its update layout.

Called by build_image.sh after native/Node dependencies are built. Never packages
an active user's Pi, settings, accounts, Bluetooth bonds or Wi-Fi credentials.
"""
import argparse
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from hlauncher import updater
from hlauncher.development_builds import build_metadata, metadata
from hlauncher.catalog import API_VERSION


def public_key(private, output):
    subprocess.run(['openssl','pkey','-in',str(private),'-pubout','-out',str(output)],
                   check=True,capture_output=True,timeout=15)
    description=subprocess.run(['openssl','pkey','-pubin','-in',str(output),'-text','-noout'],
                               check=True,capture_output=True,text=True,timeout=15).stdout
    if 'ED25519' not in description.upper():raise ValueError('Use an Ed25519 signing key')


def contract(app):
    # Bundles cannot silently alter immutable system services/dependencies/updater.
    # Application-owned units are installed and rolled back with the bundle.
    patterns=('packaging/hlauncher-updater.service','packaging/*.conf','scripts/install*.sh','scripts/configure_phone_identity.py',
              'hlauncher/updater.py','hlauncher/update_service.py','scripts/trim_runtime.py')
    paths=sorted({path for pattern in patterns for path in app.glob(pattern) if path.is_file()})
    digest=hashlib.sha256()
    for path in paths:
        digest.update(str(path.relative_to(app)).encode()+b'\0'+path.read_bytes()+b'\0')
    return digest.hexdigest()


def archive_tree(destination, trees):
    """Deterministic file metadata, internal symlinks only, no tar hardlinks."""
    total=0
    with tarfile.open(destination,'w:xz',format=tarfile.PAX_FORMAT) as archive:
        for prefix,root in trees:
            root=Path(root)
            for path in [root,*sorted(root.rglob('*'))]:
                if any(p in ('.git','__pycache__','.npm-cache') or p.startswith('._') for p in path.relative_to(root).parts):continue
                if path.suffix in ('.pyc','.pyo') or path.name=='.DS_Store':continue
                name=str(Path(prefix)/path.relative_to(root))
                info=archive.gettarinfo(str(path),arcname=name)
                info.uid=info.gid=0;info.uname=info.gname='root';info.mtime=0
                info.pax_headers={}
                if path.is_symlink():
                    if Path(os.readlink(path)).is_absolute() or not path.resolve().is_relative_to(root.resolve()):
                        raise ValueError('External symlink cannot be packaged: '+name)
                    archive.addfile(info)
                elif path.is_file():
                    info.type=tarfile.REGTYPE;info.linkname='';info.size=path.stat().st_size
                    info.mode=0o755 if path.stat().st_mode&0o111 else 0o644
                    with path.open('rb') as source:archive.addfile(info,source)
                    total+=info.size
                elif path.is_dir():info.mode=0o755;archive.addfile(info)
                else:raise ValueError('Unsupported release file: '+name)
    return total


def local_container(output, version, archive):
    """One portable signed file for authenticated local upload, with no GitHub dependency."""
    output=Path(output)
    path=output/f'HLauncher-{version}-local-update.hlu'
    with tarfile.open(path,'w',format=tarfile.USTAR_FORMAT) as container:
        for name,source in (('manifest.json',output/'hlauncher-release.json'),
                            ('manifest.sig',output/'hlauncher-release.sig'),('package.tar.xz',Path(archive))):
            info=container.gettarinfo(str(source),arcname=name)
            info.uid=info.gid=0;info.uname=info.gname='root';info.mtime=0
            with source.open('rb') as data:container.addfile(info,data)
    return path


def verify_storage_image(root):
    # Do not package an image that only has the protection toggle, without boot support.
    subprocess.run(['chroot',str(root),'/usr/bin/env','PYTHONPATH=/opt/hlauncher',
                    '/usr/bin/python3','-m','hlauncher.storage','--verify'],
                   check=True,capture_output=True,text=True,timeout=120)


def package(root, persist, version, key, output, commit, *, channel='stable'):
    root,persist,output=Path(root).resolve(),Path(persist).resolve(),Path(output).resolve()
    updater.version(version)
    if channel not in ('stable', 'beta', 'development'):
        raise ValueError('Invalid release channel')
    development = build_metadata(os.environ.get('HLAUNCHER_RELEASE_BRANCH'), commit, os.environ.get('HLAUNCHER_RELEASE_BUILD_ID', version)) if channel == 'development' else {}
    if development:metadata(dict(version=version, **development))
    if root==Path('/') or not (root/'etc/os-release').is_file():raise ValueError('Use an offline OS root')
    if not (root/'opt/hlauncher').is_dir() or (root/'opt/hlauncher').is_symlink():raise ValueError('Image is already packaged or HLauncher is missing')
    if 'VERSION_CODENAME=bookworm' not in (root/'etc/os-release').read_text():raise ValueError('Release platform requires Bookworm')
    output.mkdir(parents=True,exist_ok=True)
    if (output/'hlauncher-release.json').exists():raise ValueError('Use a fresh release output directory')
    app=root/'opt/hlauncher';deps=root/'opt/hlauncher-deps'
    for required in ('plugins/carplay/runtime/usb/node_modules/usb/package.json',
                     'plugins/carplay/runtime/usb/vendor/node-carplay/CarPlay.js',
                     'build/hlauncher-pw-input'):
        if not (app/required).is_file():
            # Upstream's node-CarPlay entrypoint is checked by the installer's self-test.
            if 'vendor/' in required and (app/'plugins/carplay/runtime/usb/vendor/node-carplay').is_dir():continue
            raise ValueError('Build dependencies before packaging: '+required)
    if not (deps/'bin/hlauncher-android-auto').is_file() or not (deps/'bluealsa-buttons/bin/bluealsa').is_file():
        raise ValueError('Android Auto and BlueALSA runtimes must be built first')
    verify_storage_image(root)
    public_key(key,output/'release.pub')
    system_contract=contract(app)
    # Corresponding project/upstream sources accompany each binary release.
    source_trees=[('HLauncher',app)]
    if (deps/'src').is_dir():source_trees.append(('external-sources',deps/'src'))
    archive_tree(output/f'HLauncher-{version}-sources.tar.xz',source_trees)
    location=persist/'hlauncher';release=location/'releases'/version
    release.mkdir(parents=True)
    shutil.move(str(app),release/'app')
    runtime=release/'runtime';runtime.mkdir()
    for name in ('bin','lib','lib64','share','bluealsa-buttons'):
        if (deps/name).exists():shutil.move(str(deps/name),runtime/name)
    # Discard image build trees only after their corresponding source was archived.
    shutil.rmtree(deps)
    app=release/'app'
    (app/'hlauncher/__init__.py').write_text('"""HLauncher application version."""\n__version__ = '+repr(version)+'\n')
    config=dict(root='/persist/hlauncher',public_key='/etc/hlauncher-updater/release.pub',
                platform=updater.PLATFORM,system_contract=system_contract,release_units=True)
    updater.atomic(app/'build-info.json',dict(version=version,commit=commit,platform=updater.PLATFORM,
                                             system_contract=system_contract,channel=channel) | development)
    filename=f'HLauncher-{version}-pi4-arm64.tar.xz'
    unpacked=archive_tree(output/filename,[('app',app),('runtime',runtime)])
    item=dict(format=1,updater=1,state_schema=1,platform=updater.PLATFORM,system_contract=system_contract,
              plugin_api=API_VERSION, local_test=bool(os.environ.get('HLAUNCHER_LOCAL_TEST_SSH_KEY')),
              version=version,archive=filename,size=(output/filename).stat().st_size,
              unpacked_size=unpacked,sha256=updater.sha256(output/filename),commit=commit)
    item.update(development)
    if channel in ('beta', 'development'):
        item['channel'] = channel
    updater.validate_manifest(item,config)
    updater.atomic(output/'hlauncher-release.json',item)
    subprocess.run(['openssl','pkeyutl','-sign','-rawin','-inkey',str(key),'-in',str(output/'hlauncher-release.json'),
                    '-out',str(output/'hlauncher-release.sig')],check=True,capture_output=True,timeout=15)
    updater.verify_signature(output/'hlauncher-release.json',output/'hlauncher-release.sig',output/'release.pub')
    local_container(output,version,output/filename)
    updater.atomic(release/'release.json',item)
    updater.switch(location,version)
    updater.atomic(location/'installed.json',dict(current=version,previous=None))
    (root/'opt/hlauncher').symlink_to('/persist/hlauncher/current/app')
    (root/'opt/hlauncher-deps').symlink_to('/persist/hlauncher/current/runtime')
    stable=root/'usr/lib/hlauncher-updater';stable.mkdir(parents=True,exist_ok=True)
    for name in ('updater.py','update_service.py'):shutil.copy2(app/'hlauncher'/name,stable/name)
    trust=root/'etc/hlauncher-updater';trust.mkdir(parents=True,exist_ok=True)
    shutil.copy2(output/'release.pub',trust/'release.pub');updater.atomic(trust/'config.json',config)
    # Cache real boot units on root: systemd reads them before /persist is mounted.
    (root/'etc/systemd/system').mkdir(parents=True,exist_ok=True)
    for name in (*updater.UNITS,'hlauncher-firstboot.service','hlauncher-pipewire.service','hlauncher-grow.service'):
        path=root/'etc/systemd/system'/name
        if (app/'packaging'/name).is_file():
            path.unlink(missing_ok=True)
            shutil.copy2(app/'packaging'/name,path)
    stock=root/'etc/systemd/system/bluealsa.service'
    stock.unlink(missing_ok=True);stock.symlink_to('/dev/null')
    return item


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('root','persist','key','output'):parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--version',required=True);parser.add_argument('--commit',required=True)
    parser.add_argument('--channel', choices=('stable', 'beta', 'development'), default='stable')
    args=parser.parse_args()
    package(args.root,args.persist,args.version,args.key,args.output,args.commit,channel=args.channel)


if __name__=='__main__':main()
