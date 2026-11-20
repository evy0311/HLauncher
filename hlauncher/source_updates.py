"""Explicit unsigned GitHub source snapshots, using existing durable activation."""
import ast
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import tarfile
import time
from urllib.request import Request, build_opener, HTTPRedirectHandler
from . import updater
from .development_builds import branch_name, build_version

MAX_DOWNLOAD=128*1024**2
MAX_SOURCE=512*1024**2
SOURCE_UPDATE_API=1
ROOT=Path(__file__).resolve().parents[1]
API='https://api.github.com/repos/'+updater.REPOSITORY
OVERLAY_FILES=('channel_updates.py','development_builds.py','source_updates.py',
               'update_client.py','ui/updates.py')
ACTIONS=('updates_page','release_notes_page','release_notes_move','toggle_beta_updates',
         'development_branches_page','select_development_branch','toggle_source_updates',
         'install_update','confirm_update','update_request')


def enabled(service):
    settings=updater.read(service.state/'settings.json')
    return settings.get('include_beta_updates') is True and settings.get('source_updates') is True


def check(service):
    service.report('checking','Checking GitHub source branches')
    (service.cache/'source-offer.json').unlink(missing_ok=True)
    (service.cache/'offers.json').unlink(missing_ok=True)
    rows=[]
    for page in range(1,6):
        listing=service.cache/'source-branches.json'
        service.fetch(API+f'/branches?per_page=100&page={page}',listing,4*1024**2)
        values=json.loads(listing.read_text())
        if not isinstance(values,list):raise ValueError('Invalid GitHub branch listing')
        for value in values:
            try:
                name=branch_name(value['name']);commit=value['commit']['sha']
                if not re.fullmatch('[0-9a-f]{40}',commit):continue
                rows.append(dict(branch=name,commit=commit,unsigned=True))
            except (KeyError,TypeError,ValueError):continue
        if len(values)<100:break
    selected=service.selected_branch()
    current=updater.read(service.installer.root/'releases'/service.installer.current()/'release.json')
    fields=dict(branches=sorted(rows,key=lambda r:r['branch']),selected_branch=selected,
                available_channel='source',available=None,available_branch=None,
                available_commit=None,available_built_at=None,stable_available=None,
                stable_return=False,notes_version=None)
    # Retain the signed path back to stable while source testing is selected.
    try:
        listing=service.cache/'source-stable.json'
        service.fetch(API+'/releases/latest',listing,1024**2)
        stable=service.release(updater.read(listing),'stable')
        if (updater.version(stable['manifest']['version'])>updater.version(service.installer.current())
                or current.get('channel') in ('beta','development','source')):
            info=stable['manifest'];updater.atomic(service.cache/'offers.json',{info['version']:stable})
            fields.update(stable_available=info['version'],stable_return=updater.version(info['version'])<updater.version(service.installer.current()))
    except (OSError,ValueError,RuntimeError,subprocess.SubprocessError):pass
    row=next((r for r in rows if r['branch']==selected),None)
    if row and (current.get('channel')!='source' or current.get('branch')!=selected or current.get('commit')!=row['commit']):
        version=build_version(time.time_ns()//1000000)
        offer=dict(version=version,branch=selected,commit=row['commit'],unsigned=True)
        updater.atomic(service.cache/'source-offer.json',offer)
        fields.update(available=version,available_branch=selected,available_commit=row['commit'])
        service.report('available','Unsigned source snapshot available',**fields)
    else:
        if fields['stable_available']:
            fields.update(available=fields['stable_available'],available_channel='stable')
            service.report('available','Source is current; stable release available' if row else 'Source branch unavailable; stable release available',**fields)
        else:
            service.report('idle','Already running this source commit' if row else 'Selected source branch is unavailable',**fields)


def download(commit,destination):
    if not re.fullmatch('[0-9a-f]{40}',commit):raise ValueError('Invalid source commit')
    url='https://codeload.github.com/'+updater.REPOSITORY+'/tar.gz/'+commit
    class NoRedirect(HTTPRedirectHandler):
        def redirect_request(self,*args,**kwargs):raise ValueError('Unexpected source redirect')
    request=Request(url,headers={'User-Agent':'HLauncher-Source-Testing/1'})
    with build_opener(NoRedirect()).open(request,timeout=30) as response,Path(destination).open('wb') as out:
        if response.geturl()!=url:raise ValueError('Unexpected source URL')
        total=0;deadline=time.monotonic()+300
        while block:=response.read(min(1024**2,MAX_DOWNLOAD-total+1)):
            total+=len(block)
            if total>MAX_DOWNLOAD or time.monotonic()>deadline:raise ValueError('Source download exceeded its limit')
            out.write(block)
        out.flush()
        import os
        os.fsync(out.fileno())


def unpack(archive,destination):
    destination=Path(destination);destination.mkdir()
    prefix=None;names=set();links=[];total=0
    with tarfile.open(archive,'r:gz') as source:
        for member in source:
            path=PurePosixPath(member.name)
            if path.is_absolute() or '..' in path.parts or not path.parts:raise ValueError('Unsafe source path')
            if prefix is None:prefix=path.parts[0]
            if path.parts[0]!=prefix:raise ValueError('Multiple source roots')
            parts=path.parts[1:]
            if not parts:
                if not member.isdir():raise ValueError('Invalid source root')
                continue
            name='/'.join(parts)
            if name in names or len(names)>=50000 or parts[0]=='.git':raise ValueError('Unsafe or duplicate source entry')
            names.add(name);target=destination.joinpath(*parts)
            if member.isdir():target.mkdir(parents=True,exist_ok=True);continue
            target.parent.mkdir(parents=True,exist_ok=True)
            if member.issym():
                if PurePosixPath(member.linkname).is_absolute() or not (target.parent/member.linkname).resolve().is_relative_to(destination.resolve()):raise ValueError('Escaping source symlink')
                links.append((target,member.linkname));continue
            if not member.isfile() or member.size<0:raise ValueError('Unsupported source entry')
            total+=member.size
            if total>MAX_SOURCE:raise ValueError('Source archive too large')
            with source.extractfile(member) as data,target.open('xb') as out:shutil.copyfileobj(data,out)
            target.chmod(0o755 if member.mode&0o111 else 0o644)
    for path,target in links:
        if path.exists() or path.is_symlink():raise ValueError('Conflicting source symlink')
        path.symlink_to(target)
    for path,_ in links:
        if not path.resolve().is_relative_to(destination.resolve()):raise ValueError('Chained source symlink escapes')
    for name in ('hlauncher/__init__.py','hlauncher/launcher.py','hlauncher/config.py','scripts/check.py'):
        if not (destination/name).is_file():raise ValueError('Incomplete HLauncher source')


def fingerprints(root):
    root=Path(root);result={}
    for path in root.rglob('*'):
        relative=path.relative_to(root)
        if any(p in ('node_modules','vendor','.git','__pycache__','build','.dependency-cache') for p in relative.parts):continue
        if not path.is_file():continue
        name=relative.as_posix()
        native=(path.suffix in ('.c','.cpp','.cc','.h','.hpp','.cmake','.proto','.rs','.pyx')
                or path.name in ('CMakeLists.txt','Makefile','package.json','package-lock.json')
                or name.startswith('third_party/') or name.startswith('scripts/install')
                or name=='scripts/fetch_dependencies.py')
        if native:result[name]=updater.sha256(path)
    return result


def contract(root):
    paths=sorted({p for pattern in ('packaging/hlauncher-updater.service','packaging/*.conf','scripts/install*.sh',
                 'scripts/configure_phone_identity.py','hlauncher/updater.py','hlauncher/update_service.py','scripts/trim_runtime.py')
                 for p in Path(root).glob(pattern) if p.is_file()})
    digest=hashlib.sha256()
    for path in paths:digest.update(str(path.relative_to(root)).encode()+b'\0'+path.read_bytes()+b'\0')
    return digest.hexdigest()


def overlay(current,target):
    """Keep this updater available when testing branches that predate its UI."""
    candidate=target/'hlauncher/source_updates.py'
    if candidate.is_file():
        tree=ast.parse(candidate.read_text())
        if any(isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='SOURCE_UPDATE_API' for t in n.targets)
               and isinstance(n.value,ast.Constant) and n.value.value==SOURCE_UPDATE_API for n in tree.body):return False
    previous=current/'hlauncher/source_updater_overlay.py'
    source=(previous if previous.is_file() else current/'hlauncher/launcher.py').read_text();lines=source.splitlines(keepends=True)
    cls=next(n for n in ast.parse(source).body if isinstance(n,ast.ClassDef) and n.name==('Actions' if previous.is_file() else 'Launcher'))
    methods={n.name:''.join(lines[n.lineno-1:n.end_lineno])+'\n' for n in cls.body if isinstance(n,ast.FunctionDef)}
    if any(name not in methods for name in ACTIONS):raise ValueError('Current app lacks source updater actions')
    module='import subprocess\nclass Actions:\n'+''.join(methods[n] for n in ACTIONS)
    module+='''
def apply(launcher):
    from .config import Preferences
    from .updater import read
    from .development_builds import branch_name
    original_init=Preferences.__init__
    def initialize(self,*args,**kwargs):
        original_init(self,*args,**kwargs)
        saved=read(self.path)
        try:self.data['development_branch']=branch_name(saved.get('development_branch','develop'))
        except ValueError:self.data['development_branch']='develop'
        self.data['source_updates']=saved.get('source_updates') is True
        self.data['include_beta_updates']=saved.get('include_beta_updates') is True
    Preferences.__init__=initialize
    original_launcher_init=launcher.__init__
    def initialize_launcher(self,*args,**kwargs):
        original_launcher_init(self,*args,**kwargs)
        # Older branches lack BootstrapLauncher's network-ready notification.
        # Preserve the installed UI-first network policy after their UI is done.
        from pathlib import Path
        try:Path('/run/hlauncher-ui-ready').touch(exist_ok=True)
        except OSError:pass
    launcher.__init__=initialize_launcher
    original_draw=launcher.draw
    def draw(self):
        if self.mode in ('updates','update_confirm','development_branches'):
            from .ui.updates import draw_launcher
            return draw_launcher(self)
        return original_draw(self)
    launcher.draw=draw
    for name in ACTIONS:setattr(launcher,name,getattr(Actions,name))
'''
    # The generated module uses a literal action list, not source-controlled eval.
    module=module.replace('for name in ACTIONS:',f'for name in {ACTIONS!r}:')
    (target/'hlauncher/source_updater_overlay.py').write_text(module)
    launcher=target/'hlauncher/launcher.py'
    launcher.write_text(launcher.read_text()+"\nfrom .source_updater_overlay import apply as _source_updater_apply\n_source_updater_apply(Launcher)\n")
    for name in OVERLAY_FILES:shutil.copy2(current/'hlauncher'/name,target/'hlauncher'/name)
    return True


def install(service,offer,fetch=download):
    if not enabled(service) or service.selected_branch()!=offer.get('branch'):raise ValueError('Enable unsigned source testing and select this branch again')
    branch_name(offer['branch']);commit=offer.get('commit','')
    if not re.fullmatch('[0-9a-f]{40}',commit) or offer.get('unsigned') is not True:raise ValueError('Invalid source offer')
    version=offer['version'];updater.version(version)
    if updater.version(version)[0]<10000:raise ValueError('Invalid source installation version')
    installer=service.installer;archive=service.cache/'source.tar.gz'
    staging=installer.root/('.staging-'+version);target=installer.root/'releases'/version
    with installer.lock():
        installer.recover()
        current=installer.root/'releases'/installer.current();app=current/'app'
        if target.exists():raise ValueError('Source installation version already exists; check again')
        # Reserve for both archive expansion and the installed runtime copy.
        current_bytes=sum(p.stat().st_size for p in current.rglob('*') if p.is_file())
        if shutil.disk_usage(installer.root).free<MAX_SOURCE+MAX_DOWNLOAD+current_bytes+updater.RESERVE:raise ValueError('Not enough storage for a source checkout')
        try:
            service.report('downloading','Downloading unsigned source '+commit[:8])
            fetch(commit,archive)
            staging.mkdir();unpack(archive,staging/'app')
            checkout=staging/'app'
            if contract(checkout)!=contract(app):raise ValueError('This branch changes the system contract; use a compatible built update')
            if fingerprints(checkout)!=fingerprints(app):raise ValueError('This branch needs different native dependencies; a built update is required')
            for name in (*updater.UNITS,'hlauncher-firstboot.service','hlauncher-pipewire.service','hlauncher-grow.service'):
                if (checkout/'packaging'/name).read_bytes()!=(app/'packaging'/name).read_bytes():raise ValueError('This branch changes boot services; use a built update')
            for name in ('build','plugins/carplay/runtime/usb/node_modules','plugins/carplay/runtime/usb/vendor'):
                dest=checkout/name
                if dest.exists():shutil.rmtree(dest)
                shutil.copytree(app/name,dest,symlinks=True)
            shutil.copytree(current/'runtime',staging/'runtime',symlinks=True)
            applied_overlay=overlay(app,checkout)
            (checkout/'hlauncher/__init__.py').write_text('__version__ = '+repr(version)+'\n')
            info=dict(updater.read(current/'release.json'),version=version,channel='source',branch=offer['branch'],commit=commit,
                      unsigned=True,source_overlay=applied_overlay,built_at=datetime.now(timezone.utc).isoformat(),
                      build_id='source-'+version,archive=f'HLauncher-{version}-pi4-arm64.tar.xz',
                      size=archive.stat().st_size,sha256=updater.sha256(archive),unpacked_size=1)
            info['unpacked_size']=sum(p.stat().st_size for p in staging.rglob('*') if p.is_file())
            updater.validate_manifest(info,installer.config)
            updater.atomic(checkout/'build-info.json',info)
            updater.atomic(staging/'release.json',info)
            installer.run(['/usr/bin/python3','-m','compileall','-q','hlauncher','sdk'],cwd=checkout,check=True,capture_output=True,timeout=60)
            if not enabled(service) or service.selected_branch()!=offer['branch']:raise ValueError('Source selection changed during download')
            for folder,_,_ in __import__('os').walk(staging,topdown=False):updater.sync_dir(folder)
            staging.rename(target);updater.sync_dir(target.parent)
            service.report('installing','Installing unsigned source '+commit[:8])
            installer.activate(version)
            (service.cache/'source-offer.json').unlink(missing_ok=True)
            service.report('idle','Unsigned source installed',current_unsigned=True)
        finally:
            archive.unlink(missing_ok=True)
            if staging.exists():shutil.rmtree(staging)
