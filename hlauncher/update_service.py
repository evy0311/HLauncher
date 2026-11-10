"""Stable update daemon, copied beside updater.py under /usr/lib at image build."""
import argparse
from pathlib import Path
import shutil
import time
import tarfile
try:
    from . import updater
except ImportError:
    import updater

CONFIG=Path('/etc/hlauncher-updater/config.json')
STATE=Path('/var/lib/hlauncher')


class Service:
    def __init__(self, config, state=STATE, fetch=updater.download, installer=None):
        self.config=config;self.state=Path(state);self.fetch=fetch
        self.installer=installer or updater.Installer(config)
        self.cache=self.installer.root/'download'
        self.cache.mkdir(exist_ok=True)
        self.status_path=self.state/'update-status.json'

    def report(self, phase, message, **fields):
        status=self.installer.status()
        updater.atomic(self.status_path,dict(phase=phase,message=message,**status,**fields))

    def check(self):
        self.report('checking','Checking GitHub Releases')
        # A failed check never leaves an old update offer looking fresh.
        (self.cache/'offer.json').unlink(missing_ok=True)
        self.fetch('https://api.github.com/repos/'+updater.REPOSITORY+'/releases/latest',self.cache/'github.json',1024*1024)
        release=updater.read(self.cache/'github.json')
        tag=release.get('tag_name','')
        if release.get('draft') or release.get('prerelease'):raise ValueError('Only stable releases are supported')
        updater.version(tag.removeprefix('v'))
        assets={a['name']:a for a in release.get('assets',[]) if isinstance(a,dict) and 'name' in a}
        def asset(name):
            row=assets.get(name,{})
            url=row.get('browser_download_url','')
            prefix='https://github.com/'+updater.REPOSITORY+'/releases/download/'+tag+'/'
            if not url.startswith(prefix) or url[len(prefix):]!=name:raise ValueError('The release is missing signed updater assets')
            return url
        self.fetch(asset('hlauncher-release.json'),self.cache/'manifest.json',65536)
        self.fetch(asset('hlauncher-release.sig'),self.cache/'manifest.sig',1024)
        updater.verify_signature(self.cache/'manifest.json',self.cache/'manifest.sig',self.config['public_key'])
        info=updater.validate_manifest(updater.read(self.cache/'manifest.json'),self.config)
        if info['version']!=tag.removeprefix('v'):raise ValueError('Release tag and signed version do not match')
        notes=dict(notes=str(release.get('body') or '')[:128000],notes_version=info['version'])
        current=self.installer.current()
        if updater.version(info['version'])<=updater.version(current):
            self.report('idle','You have the latest version',checked_at=time.time(),**notes);return
        updater.atomic(self.cache/'offer.json',dict(manifest=info,url=asset(info['archive'])))
        self.report('available','Update available',available=info['version'],size=info['size'],
                    checked_at=time.time(),**notes)

    def install(self):
        offer=updater.read(self.cache/'offer.json')
        if not offer:raise ValueError('Check for updates before installing')
        # Reverify cached signed metadata before trusting size or URL.
        updater.verify_signature(self.cache/'manifest.json',self.cache/'manifest.sig',self.config['public_key'])
        info=updater.validate_manifest(updater.read(self.cache/'manifest.json'),self.config)
        expected='https://github.com/'+updater.REPOSITORY+'/releases/download/'
        if info!=offer.get('manifest') or offer.get('url') not in (
            expected+'v'+info['version']+'/'+info['archive'],expected+info['version']+'/'+info['archive']):
            raise ValueError('Update offer changed; check for updates again')
        archive=self.cache/'package.part'
        archive.unlink(missing_ok=True)  # Interrupted downloads are retried from scratch.
        needed=info['size']+info['unpacked_size']+updater.RESERVE
        if shutil.disk_usage(self.installer.root).free<needed:raise ValueError('Not enough storage for this update')
        try:
            self.report('downloading','Downloading '+info['version'],available=info['version'])
            self.fetch(offer['url'],archive,info['size'],info['size'])
            self.report('installing','Installing and restarting HLauncher')
            self.installer.install(self.cache/'manifest.json',self.cache/'manifest.sig',archive)
            (self.cache/'offer.json').unlink(missing_ok=True)
            self.report('idle','Update installed')
        finally:archive.unlink(missing_ok=True)

    def import_local(self):
        uploaded=self.installer.root/'inbox/local-update.hlu'
        staging=self.cache/'local-import'
        if staging.exists():shutil.rmtree(staging)
        staging.mkdir()
        try:
            if uploaded.stat().st_size>updater.MAX_PACKAGE+262144:raise ValueError('Local update file is too large')
            self.report('installing','Verifying local update file')
            allowed={'manifest.json':65536,'manifest.sig':1024,'package.tar.xz':updater.MAX_PACKAGE}
            seen=set()
            with tarfile.open(uploaded,'r:') as container:
                for member in container:
                    if (member.name not in allowed or member.name in seen or not member.isfile() or
                            not 0<member.size<=allowed[member.name]):raise ValueError('Invalid local update container')
                    seen.add(member.name)
                    with container.extractfile(member) as source,(staging/member.name).open('xb') as output:
                        shutil.copyfileobj(source,output)
            if seen!=set(allowed):raise ValueError('Incomplete local update file')
            self.installer.install(staging/'manifest.json',staging/'manifest.sig',staging/'package.tar.xz')
            (self.cache/'offer.json').unlink(missing_ok=True)
            self.report('idle','Local update installed')
        finally:
            uploaded.unlink(missing_ok=True)
            shutil.rmtree(staging,ignore_errors=True)

    def perform(self, operation):
        try:
            if operation=='check':self.check()
            elif operation=='install':self.install()
            elif operation=='import':self.import_local()
            elif operation=='rollback':
                self.report('installing','Restoring the previous installed version')
                self.installer.rollback();self.report('idle','Previous version restored')
            else:raise ValueError('Unknown update operation')
        except Exception as exc:
            # Keep subprocess output and network response bodies out of the UI.
            message=str(exc) if isinstance(exc,(ValueError,RuntimeError)) else 'Update failed; check Wi-Fi and retry'
            self.report('error',message[:240])
            if isinstance(exc,updater.RecoveryRequired):raise

    def run(self):
        queued=updater.read(self.state/'update-request.json')
        if queued.get('operation')!='import':
            (self.installer.root/'inbox/local-update.hlu').unlink(missing_ok=True)
            shutil.rmtree(self.cache/'local-import',ignore_errors=True)
        recovered=updater.read(self.installer.state_path)
        units=[u for u in recovered.get('resume_units',[]) if u in updater.UNITS]
        if units:
            self.installer.run(['systemctl','restart','--no-block',*units],check=True,capture_output=True,timeout=15)
            recovered.pop('resume_units',None);updater.atomic(self.installer.state_path,recovered)
        self.report('idle',recovered.get('last_error','Ready'))
        request=self.state/'update-request.json'
        while True:
            try:
                if request.exists():
                    if request.is_symlink() or request.stat().st_size>1024:raise ValueError('Invalid update request')
                    item=updater.read(request);request.unlink();updater.sync_dir(request.parent)
                    if set(item)!={'operation'}:raise ValueError('Invalid update request')
                    self.perform(item['operation'])
            except (OSError,ValueError):
                request.unlink(missing_ok=True)
                self.report('error','Invalid update request')
            time.sleep(.5)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--recover',action='store_true')
    args=parser.parse_args()
    config=updater.read(CONFIG)
    if not config:raise SystemExit('Updater image configuration is missing')
    installer=updater.Installer(config)
    if args.recover:
        with installer.lock():installer.recover()
    else:
        # Prevent two workers from processing independent requests concurrently.
        import fcntl
        with (installer.root/'.daemon-lock').open('a') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            Service(config,installer=installer).run()


if __name__=='__main__':main()
