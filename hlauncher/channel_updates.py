"""Check signed stable and beta releases using the image's installer contract."""
import argparse
import json
import os
import shutil
import subprocess
import time

from . import updater
from .development_builds import metadata, branch_name
from .update_service import CONFIG, STATE, Service

RELEASES = 'https://api.github.com/repos/' + updater.REPOSITORY + '/releases'
ASSETS = 'https://github.com/' + updater.REPOSITORY + '/releases/download/'


def channel(info):
    value = info.get('channel', 'stable')
    if value not in ('stable', 'beta', 'development'):
        raise ValueError('Invalid signed release channel')
    return value


class ChannelInstaller(updater.Installer):
    def current_channel(self):
        return channel(updater.read(self.root/'releases'/self.current()/'release.json'))

    def selected_transition(self, manifest, signature, archive, development=False):
        """Use the same verified staging and activation for an explicit beta exit."""
        with self.lock():
            self.recover()
            updater.verify_signature(manifest, signature, self.config['public_key'])
            info = updater.validate_manifest(updater.read(manifest), self.config)
            current = self.current()
            target_version = info['version']
            if development:
                if channel(info) != 'development':
                    raise ValueError('Only signed development builds support branch switching')
                metadata(info)
            elif self.current_channel() not in ('beta', 'development') or channel(info) != 'stable':
                raise ValueError('Only a development or beta build can return to stable')
            if target_version == current:
                raise ValueError('That version is already installed')
            if archive.stat().st_size != info['size'] or updater.sha256(archive) != info['sha256']:
                raise ValueError('Downloaded package failed verification')
            if shutil.disk_usage(self.root).free < info['unpacked_size'] + updater.RESERVE:
                raise ValueError('Not enough space to install this release')
            target = self.root/'releases'/target_version
            if target.exists():
                if updater.read(target/'release.json') != info:
                    raise ValueError('A different package already uses this version')
            else:
                staging = self.root/('.staging-' + target_version)
                try:
                    if staging.exists():
                        shutil.rmtree(staging)
                    updater.unpack(archive, staging, info['unpacked_size'])
                    updater.atomic(staging/'release.json', info)
                    self.run(['/usr/bin/python3', '-m', 'compileall', '-q', 'hlauncher', 'sdk'],
                             cwd=staging/'app', check=True, capture_output=True, timeout=60)
                    os.replace(staging, target)
                    updater.sync_dir(target.parent)
                finally:
                    if staging.exists():
                        shutil.rmtree(staging)
            self.activate(target_version)
            keep = set(self.status().values())
            for path in (self.root/'releases').iterdir():
                if path.is_dir() and path.name not in keep:
                    shutil.rmtree(path)

    def return_to_stable(self, manifest, signature, archive):
        return self.selected_transition(manifest, signature, archive)

    def install_development(self, manifest, signature, archive):
        return self.selected_transition(manifest, signature, archive, development=True)


class ChannelService(Service):
    def __init__(self, config, state=STATE, fetch=updater.download, installer=None):
        super().__init__(config, state, fetch, installer or ChannelInstaller(config))
        self.cache = self.installer.root/'channel-download'
        self.cache.mkdir(exist_ok=True)

    def report(self, phase, message, **fields):
        current = updater.read(self.installer.root/'releases'/self.installer.current()/'release.json')
        super().report(phase, message, current_channel=self.installer.current_channel(),
                       current_branch=current.get('branch'), current_commit=current.get('commit'), **fields)

    def beta_enabled(self):
        return updater.read(self.state/'settings.json').get('include_beta_updates') is True

    def selected_branch(self):
        try:return branch_name(updater.read(self.state/'settings.json').get('development_branch', 'develop'))
        except ValueError:return 'develop'

    def release(self, release, expected_channel):
        tag = release.get('tag_name', '')
        tag_version = tag.removeprefix('dev-') if expected_channel == 'development' else tag.removeprefix('v')
        updater.version(tag_version)
        if release.get('draft') or (release.get('prerelease') is True) != (expected_channel in ('beta', 'development')):
            raise ValueError('Unexpected GitHub release channel')
        assets = {row.get('name'): row.get('browser_download_url')
                  for row in release.get('assets', []) if isinstance(row, dict)}
        prefix = ASSETS + tag + '/'

        def asset(name):
            expected = prefix + name
            if assets.get(name) != expected:
                raise ValueError('The release is missing signed updater assets')
            return expected

        folder = self.cache/(expected_channel+'-'+tag_version)
        folder.mkdir(exist_ok=True)
        manifest_url, signature_url = asset('hlauncher-release.json'), asset('hlauncher-release.sig')
        # Immutable versioned builds may reuse their signed metadata cache.
        if not (folder/'manifest.json').is_file() or not (folder/'manifest.sig').is_file():
            self.fetch(manifest_url, folder/'manifest.json', 65536)
            self.fetch(signature_url, folder/'manifest.sig', 1024)
        updater.verify_signature(folder/'manifest.json', folder/'manifest.sig', self.config['public_key'])
        info = updater.validate_manifest(updater.read(folder/'manifest.json'), self.config)
        if expected_channel == 'development':
            metadata(info)
            if tag != 'dev-'+info['version']:
                raise ValueError('Invalid development release tag')
        if info['version'] != tag_version or channel(info) != expected_channel:
            raise ValueError('GitHub release and signed metadata disagree')
        return dict(manifest=info, url=asset(info['archive']), tag=tag,
                    notes=str(release.get('body') or '')[:128000])

    def check(self):
        self.report('checking', 'Checking GitHub Releases')
        offers_path = self.cache/'offers.json'
        offers_path.unlink(missing_ok=True)
        current = updater.version(self.installer.current())
        installed_beta = self.installer.current_channel() in ('beta', 'development')
        listing = self.cache/'github.json'
        self.fetch(RELEASES + '/latest', listing, 1024*1024)
        stable = self.release(updater.read(listing), 'stable')
        stable_version = updater.version(stable['manifest']['version'])
        offers = []
        if stable_version > current or (installed_beta and stable_version < current):
            offers.append(stable)
        beta_error = False
        branches = {}
        selected = self.selected_branch()
        if self.beta_enabled():
            try:
                self.fetch(RELEASES + '?per_page=50', listing, 4*1024*1024)
                releases = json.loads(listing.read_text())
                if not isinstance(releases, list):
                    raise ValueError('Invalid GitHub release listing')
                page = 1
                count = len(releases)
                while count == 50 and page < 10:
                    page += 1
                    self.fetch(RELEASES+f'?per_page=50&page={page}', listing, 4*1024*1024)
                    more = json.loads(listing.read_text())
                    if not isinstance(more, list):
                        raise ValueError('Invalid GitHub release listing')
                    releases.extend(more)
                    count = len(more)
                # A bounded recent-release catalogue; no unsigned branch names reach the UI.
                for release in releases:
                    if not isinstance(release, dict) or release.get('draft') or release.get('prerelease') is not True:
                        continue
                    if not str(release.get('tag_name', '')).startswith('dev-'):
                        continue
                    try:
                        snapshot = self.release(release, 'development')
                        item = snapshot['manifest']
                        name = item['branch']
                        if name not in branches or updater.version(item['version']) > updater.version(branches[name]['manifest']['version']):
                            branches[name] = snapshot
                    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError):
                        continue
                snapshot = branches.get(selected)
                if snapshot and snapshot['manifest']['version'] != self.installer.current():
                    offers.append(snapshot)
                candidates = []
                for release in releases:
                    if not isinstance(release, dict) or release.get('draft') or release.get('prerelease') is not True:
                        continue
                    try:
                        candidate = updater.version(release.get('tag_name', '').removeprefix('v'))
                    except ValueError:
                        continue
                    if candidate > current:
                        candidates.append((candidate, release))
                if candidates and not snapshot and selected == 'develop':
                    offers.append(self.release(max(candidates, key=lambda item: item[0])[1], 'beta'))
            except (OSError, ValueError, RuntimeError, subprocess.SubprocessError):
                beta_error = True
        branch_rows = [dict(version=offer['manifest']['version'], **metadata(offer['manifest']))
                       for _, offer in sorted(branches.items())]
        branch_status = dict(branches=branch_rows, selected_branch=selected)
        missing_branch = self.beta_enabled() and selected not in branches and selected != 'develop'
        if not offers:
            self.report('idle', 'No compatible build for the selected branch' if missing_branch else 'Beta releases unavailable' if beta_error else 'You have the latest version',
                        checked_at=time.time(), notes=stable['notes'], notes_version=stable['manifest']['version'], **branch_status)
            return
        offers.sort(key=lambda offer: updater.version(offer['manifest']['version']), reverse=True)
        updater.atomic(offers_path, {offer['manifest']['version']: offer for offer in offers})
        first = next((offer for offer in offers if channel(offer['manifest']) == 'development'), offers[0])
        info = first['manifest']
        self.report('available', 'Stable release available. Development check failed.' if beta_error else 'No compatible branch build; stable release available' if missing_branch else 'Update available',
                    available=info['version'], available_channel=channel(info), size=info['size'],
                    stable_available=stable['manifest']['version'] if stable in offers else None,
                    stable_return=installed_beta and stable in offers and stable_version < current,
                    checked_at=time.time(), notes=first['notes'], notes_version=info['version'],
                    available_branch=info.get('branch'), available_commit=info.get('commit'),
                    available_built_at=info.get('built_at'), **branch_status)

    def install_version(self, version):
        updater.version(version)
        offer = updater.read(self.cache/'offers.json').get(version)
        if not offer:
            raise ValueError('Check for updates before installing')
        offered = offer['manifest']
        offered_channel = channel(offered)
        if offered_channel in ('beta', 'development') and not self.beta_enabled():
            raise ValueError('Enable beta builds and check for updates again')
        if offered_channel == 'development':
            metadata(offered)
            if offered['branch'] != self.selected_branch():
                raise ValueError('The selected branch changed; check for updates again')
        folder = self.cache/(offered_channel+'-'+version)
        manifest, signature = folder/'manifest.json', folder/'manifest.sig'
        updater.verify_signature(manifest, signature, self.config['public_key'])
        info = updater.validate_manifest(updater.read(manifest), self.config)
        if (info != offered or info['version'] != version
                or offer['tag'] not in (('dev-'+version,) if offered_channel == 'development' else ('v'+version, version))
                or offer['url'] != ASSETS + offer['tag'] + '/' + info['archive']):
            raise ValueError('Update offer changed; check for updates again')
        current = updater.version(self.installer.current())
        returning = updater.version(version) < current
        if returning and offered_channel != 'development' and (offered_channel != 'stable' or self.installer.current_channel() not in ('beta', 'development')):
            raise ValueError('Only a beta can return to an older stable release')
        if updater.version(version) == current:
            raise ValueError('That version is already installed')
        archive = self.cache/'package.part'
        archive.unlink(missing_ok=True)
        if shutil.disk_usage(self.installer.root).free < info['size'] + info['unpacked_size'] + updater.RESERVE:
            raise ValueError('Not enough storage for this update')
        try:
            self.report('downloading', 'Downloading ' + version, available=version)
            self.fetch(offer['url'], archive, info['size'], info['size'])
            if offered_channel in ('beta', 'development') and not self.beta_enabled():
                raise ValueError('Development builds were disabled during download')
            if offered_channel == 'development' and self.selected_branch() != info['branch']:
                raise ValueError('The selected branch changed during download')
            self.report('installing', 'Installing and restarting HLauncher')
            install = (self.installer.install_development if offered_channel == 'development'
                       else self.installer.return_to_stable if returning else self.installer.install)
            install(manifest, signature, archive)
            (self.cache/'offers.json').unlink(missing_ok=True)
            self.report('idle', 'Stable release installed' if returning else 'Update installed')
        finally:
            archive.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('operation', choices=('check', 'install'))
    parser.add_argument('version', nargs='?')
    args = parser.parse_args()
    service = ChannelService(updater.read(CONFIG))
    try:
        if args.operation == 'check':
            service.check()
        else:
            service.install_version(args.version)
    except Exception as exc:
        message = str(exc) if isinstance(exc, (ValueError, RuntimeError)) else 'Update failed; check Wi-Fi and retry'
        service.report('error', message[:240])
        if isinstance(exc, updater.RecoveryRequired):
            subprocess.run(['systemctl', 'restart', '--no-block', 'hlauncher-updater.service'],
                           check=False, capture_output=True, timeout=10)


if __name__ == '__main__':
    main()
