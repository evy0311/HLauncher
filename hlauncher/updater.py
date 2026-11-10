"""Standalone signed-bundle installer. Also installed outside the updatable app.

Only standard-library modules and the image's OpenSSL/systemctl are required.
No release-provided scripts, OS installs or preference migrations are executed.
"""
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import tarfile
import tempfile
import time
from urllib.parse import urlsplit
from urllib.error import HTTPError
from urllib.request import Request, HTTPRedirectHandler, build_opener

FORMAT = 1
SCHEMA = 1
PLATFORM = 'pi4-arm64-bookworm-v1'
REPOSITORY = 'evy0311/HLauncher'
UNITS = ('hlauncher.service', 'hlauncher-connect.service', 'hlauncher-pairing.service',
         'hlauncher-recovery.service', 'hlauncher-audio.service')
MAX_PACKAGE = 2 * 1024**3
MAX_UNPACKED = 6 * 1024**3
RESERVE = 128 * 1024**2


def version(value):
    if not isinstance(value,str) or not re.fullmatch(r'\d{1,5}\.\d{1,5}\.\d{1,5}',value):
        raise ValueError('Invalid release version')
    return tuple(map(int,value.split('.')))


def read(path, default=None):
    try:
        item=json.loads(Path(path).read_text())
        return item if isinstance(item,dict) else (default or {})
    except (OSError,ValueError): return default or {}


def sync_dir(path):
    fd=os.open(path,os.O_RDONLY)
    try:os.fsync(fd)
    finally:os.close(fd)


def atomic(path, data):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    fd,name=tempfile.mkstemp(prefix='.'+path.name,dir=path.parent)
    try:
        with os.fdopen(fd,'w') as output:
            json.dump(data,output,sort_keys=True);output.write('\n');output.flush();os.fsync(output.fileno())
        os.replace(name,path);sync_dir(path.parent)
    finally:
        if os.path.exists(name):os.unlink(name)


def switch(root, name):
    # Both the link replacement and its directory are persisted before proceeding.
    version(name)
    tmp=root/'.current-new'
    tmp.unlink(missing_ok=True)
    tmp.symlink_to('releases/'+name)
    os.replace(tmp,root/'current');sync_dir(root)


def sha256(path):
    digest=hashlib.sha256()
    with Path(path).open('rb') as source:
        for block in iter(lambda:source.read(1024*1024),b''):digest.update(block)
    return digest.hexdigest()


def verify_signature(manifest, signature, key):
    subprocess.run(['openssl','pkeyutl','-verify','-pubin','-inkey',str(key),'-rawin',
                    '-in',str(manifest),'-sigfile',str(signature)],check=True,
                   capture_output=True,timeout=15)


def validate_manifest(item, config):
    version(item.get('version'))
    if item.get('format')!=FORMAT or item.get('updater')!=FORMAT:
        raise ValueError('This release requires a newer image/updater')
    # Only the trusted on-device configuration may approve an older compatible
    # OS contract. Release metadata cannot grant itself compatibility.
    previous=config.get('compatible_contracts',[])
    if not isinstance(previous,list):previous=[]
    trusted=[config['system_contract'],*(value for value in previous if isinstance(value,str))]
    if item.get('platform')!=config['platform'] or item.get('system_contract') not in trusted:
        raise ValueError('This release needs a different system image')
    if item.get('state_schema')!=SCHEMA:
        raise ValueError('This release cannot preserve rollback-compatible settings')
    for key,maximum in (('size',MAX_PACKAGE),('unpacked_size',MAX_UNPACKED)):
        if type(item.get(key)) is not int or not 0<item[key]<=maximum:
            raise ValueError('Invalid release size')
    if not re.fullmatch('[0-9a-f]{64}',str(item.get('sha256',''))):raise ValueError('Invalid package checksum')
    expected='HLauncher-'+item['version']+'-pi4-arm64.tar.xz'
    if item.get('archive')!=expected:raise ValueError('Invalid package filename')
    return item


def allowed_url(url):
    parsed=urlsplit(url)
    return (parsed.scheme=='https' and parsed.username is None and parsed.password is None
            and parsed.port in (None,443) and parsed.hostname in
            ('api.github.com','github.com','release-assets.githubusercontent.com','objects.githubusercontent.com'))


class ReleaseRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        if not allowed_url(newurl):raise ValueError('Unexpected release redirect')
        return super().redirect_request(request,fp,code,msg,headers,newurl)


def download(url, destination, maximum, expected=None):
    if not allowed_url(url):raise ValueError('Unexpected release download URL')
    request=Request(url,headers={'User-Agent':'HLauncher-Updater/1','Accept':'application/vnd.github+json'})
    count=0
    try:response=build_opener(ReleaseRedirect()).open(request,timeout=30)
    except HTTPError as exc:
        if exc.code==404:raise ValueError('No stable release is published yet' if url.endswith('/latest') else 'Release asset is unavailable') from exc
        if exc.code in (403,429):raise ValueError('GitHub access is limited; try again later') from exc
        raise
    with response, Path(destination).open('wb') as output:
        if not allowed_url(response.geturl()):raise ValueError('Unexpected release redirect')
        deadline=time.monotonic()+1800
        while block:=response.read(min(1024*1024,maximum-count+1)):
            count+=len(block)
            if count>maximum or time.monotonic()>deadline:raise ValueError('Download exceeded its limit')
            output.write(block)
        output.flush();os.fsync(output.fileno())
    if expected is not None and count!=expected:raise ValueError('Incomplete release download')


def unpack(archive, destination, expected_size):
    """Extract regular files and confined relative symlinks; never tar.extractall."""
    destination=Path(destination);destination.mkdir()
    total=0;names=set();links=[]
    with tarfile.open(archive,'r:xz') as source:
        for member in source:
            name=PurePosixPath(member.name)
            if (name.is_absolute() or '..' in name.parts or not name.parts or
                    name.parts[0] not in ('app','runtime') or member.name in names):
                raise ValueError('Unsafe or duplicate package path')
            names.add(member.name)
            if len(names)>100000:raise ValueError('Too many package files')
            path=destination.joinpath(*name.parts)
            if member.isdir():path.mkdir(parents=True,exist_ok=True);continue
            path.parent.mkdir(parents=True,exist_ok=True)
            if member.issym():
                target=PurePosixPath(member.linkname)
                if target.is_absolute():raise ValueError('Absolute package symlink')
                resolved=(path.parent/member.linkname).resolve()
                if not resolved.is_relative_to(destination.resolve()):raise ValueError('Escaping package symlink')
                links.append((path,member.linkname));continue
            if not member.isfile():raise ValueError('Unsupported package entry')
            total+=member.size
            if total>expected_size:raise ValueError('Package exceeds declared unpacked size')
            with source.extractfile(member) as data, path.open('xb') as output:
                shutil.copyfileobj(data,output);output.flush();os.fsync(output.fileno())
            path.chmod(0o755 if member.mode&0o111 else 0o644)
    if total!=expected_size:raise ValueError('Incorrect unpacked package size')
    # Links are created last, so no member can traverse a previously created link.
    for path,target in links:
        if path.exists() or path.is_symlink():raise ValueError('Conflicting package symlink')
        path.symlink_to(target)
    for path,_ in links:
        if not path.resolve().is_relative_to(destination.resolve()):raise ValueError('Chained package symlink escapes release')
    if not (destination/'app/hlauncher/__init__.py').is_file():raise ValueError('Missing HLauncher package')
    for folder,_,_ in os.walk(destination,topdown=False):sync_dir(folder)


class RecoveryRequired(RuntimeError):
    """Restart the stable daemon so its boot recovery can finish restoring services."""


class Installer:
    def __init__(self, config, run=subprocess.run, health=None):
        self.config=config;self.root=Path(config['root']);self.run=run
        self.health=health or self.check_health
        self.root.mkdir(parents=True,exist_ok=True)
        (self.root/'releases').mkdir(exist_ok=True)
        self.state_path=self.root/'installed.json'

    @contextmanager
    def lock(self):
        with (self.root/'.lock').open('a') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            yield

    def current(self):
        path=(self.root/'current').resolve()
        if path.parent!=(self.root/'releases').resolve():raise ValueError('Updater image layout is not installed')
        version(path.name)
        return path.name

    def status(self):
        state=read(self.state_path)
        current=self.current()
        previous=state.get('previous')
        if previous:
            version(previous)
            if not (self.root/'releases'/previous/'release.json').is_file():previous=None
        return dict(current=current,previous=previous)

    def active_units(self):
        return [u for u in UNITS if self.run(['systemctl','is-active','--quiet',u],check=False,
                capture_output=True,timeout=10).returncode==0]

    def stop(self, units):
        # The graph follows HLauncher, but explicitly stopping it also handles an idle graph.
        self.run(['systemctl','stop',*units,'hlauncher-pipewire.service'],check=True,capture_output=True,timeout=60)

    def start(self, units):
        if units:self.run(['systemctl','start',*units],check=True,capture_output=True,timeout=60)

    def check_health(self, release, units):
        deadline=time.monotonic()+45;good_since=None
        while time.monotonic()<deadline:
            active=all(self.run(['systemctl','is-active','--quiet',u],check=False,
                       capture_output=True,timeout=5).returncode==0 for u in units)
            heartbeat=read('/run/hlauncher/update-health.json')
            fresh=(heartbeat.get('version')==release and heartbeat.get('profiles_ready') is True and
                   0<=time.monotonic()-heartbeat.get('monotonic',0)<5)
            if active and fresh:
                if good_since is None:good_since=time.monotonic()
                if time.monotonic()-good_since>=5:return
            else:good_since=None
            time.sleep(.5)
        raise RuntimeError('The new version did not become healthy')

    def sync_units(self, release, apply=True):
        if self.config.get('release_units') is not True:return
        packaging=self.root/'releases'/release/'app/packaging'
        destination=Path(self.config.get('unit_root','/'))/'etc/systemd/system'
        names=(*UNITS,'hlauncher-firstboot.service','hlauncher-pipewire.service','hlauncher-grow.service')
        files={name:(packaging/name).read_bytes() for name in names}
        if any(len(data)>65536 or not data.startswith(b'[Unit]') for data in files.values()):
            raise ValueError('Invalid boot service definitions')
        changed={name:data for name,data in files.items()
                 if not (destination/name).is_file() or (destination/name).read_bytes()!=data}
        if changed and 'unit_root' not in self.config:
            result=self.run(['findmnt','-no','FSTYPE','/'],check=True,capture_output=True,text=True,timeout=5)
            if result.stdout.strip()=='overlay':
                raise ValueError('Turn off SD card protection and restart before updating boot services')
        if not apply:return
        destination.mkdir(parents=True,exist_ok=True)
        for name,data in changed.items():
            path=destination/name
            if path.is_symlink():raise ValueError('Unexpected boot service symlink')
            fd,tmp=tempfile.mkstemp(prefix='.'+name,dir=destination)
            try:
                with os.fdopen(fd,'wb') as output:
                    output.write(data);output.flush();os.fsync(output.fileno());os.fchmod(output.fileno(),0o644)
                os.replace(tmp,path);sync_dir(destination)
            finally:
                if os.path.exists(tmp):os.unlink(tmp)
        self.run(['systemctl','daemon-reload'],check=True,capture_output=True,timeout=20)

    def recover(self):
        """Runs before application services on boot, before any new update requests."""
        for path in self.root.glob('.staging-*'):
            if path.is_symlink():path.unlink()
            elif path.is_dir():shutil.rmtree(path)
        state=read(self.state_path)
        if state.get('pending'):
            old=state['pending']['from'];version(old)
            if not (self.root/'releases'/old/'release.json').is_file():raise ValueError('Recovery version is missing')
            switch(self.root,old)
            self.sync_units(old)
            atomic(self.state_path,dict(current=old,previous=state.get('previous'),
                                        recovered=True,resume_units=state.get('units',[]),
                                        last_error='Interrupted update restored the previous version'))

    def activate(self, target):
        old=self.current();version(target)
        if target==old:raise ValueError('That version is already installed')
        info=read(self.root/'releases'/target/'release.json');validate_manifest(info,self.config)
        if info['version']!=target:raise ValueError('Installed release metadata does not match its version')
        self.sync_units(target,apply=False)
        previous=read(self.state_path).get('previous')
        units=self.active_units()
        if 'hlauncher.service' not in units:units.append('hlauncher.service')
        atomic(self.state_path,dict(current=old,previous=previous,pending=dict(to=target,**{'from':old}),units=units))
        try:
            self.stop(units)
            switch(self.root,target)
            self.sync_units(target)
            self.start(units)
            self.run(['/usr/bin/python3','scripts/check.py'],cwd=self.root/'releases'/target/'app',
                     check=True,capture_output=True,timeout=90)
            self.run([str(self.root/'releases'/target/'runtime/bin/hlauncher-android-auto'),'--check'],
                     check=True,capture_output=True,timeout=15)
            self.health(target,units)
        except Exception as error:
            # Leave pending durable until both pointer restoration and restart succeed.
            try:
                self.stop(units);switch(self.root,old);self.sync_units(old);self.start(units)
            except Exception as restore_error:
                raise RecoveryRequired('Restarting updater to finish restoring the previous version') from restore_error
            atomic(self.state_path,dict(current=old,previous=previous,last_error='New version failed; previous version restored'))
            raise RuntimeError('Installation failed; the previous version was restored') from error
        atomic(self.state_path,dict(current=target,previous=old))

    def rollback(self):
        with self.lock():
            self.recover()
            previous=self.status()['previous']
            if not previous:raise ValueError('No previous version is available')
            self.activate(previous)

    def install(self, manifest_path, signature_path, archive):
        with self.lock():
            self.recover()
            verify_signature(manifest_path,signature_path,self.config['public_key'])
            item=validate_manifest(read(manifest_path),self.config)
            if version(item['version'])<=version(self.current()):raise ValueError('Release is not newer than the installed version')
            archive=Path(archive)
            if archive.stat().st_size!=item['size'] or sha256(archive)!=item['sha256']:
                raise ValueError('Downloaded package failed verification')
            if shutil.disk_usage(self.root).free<item['unpacked_size']+RESERVE:raise ValueError('Not enough space to install this release')
            target=self.root/'releases'/item['version']
            if target.exists():
                if read(target/'release.json')!=item:raise ValueError('A different package already uses this version')
            else:
                staging=self.root/('.staging-'+item['version'])
                if staging.exists():shutil.rmtree(staging)
                try:
                    unpack(archive,staging,item['unpacked_size'])
                    atomic(staging/'release.json',item)
                    self.run(['/usr/bin/python3','-m','compileall','-q','hlauncher','sdk'],cwd=staging/'app',
                             check=True,capture_output=True,timeout=60)
                    os.replace(staging,target);sync_dir(target.parent)
                finally:
                    if staging.exists():shutil.rmtree(staging)
            self.activate(item['version'])
            # Retain exactly the running release and its previous installed version.
            keep=set(v for v in self.status().values() if v)
            for path in (self.root/'releases').iterdir():
                if path.is_dir() and path.name not in keep:shutil.rmtree(path)
