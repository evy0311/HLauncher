"""Plugin library shared by the radio and the SSH command."""

import argparse
from contextlib import contextmanager
from dataclasses import replace
import fcntl
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
import sys

from .catalog import EXTERNAL_CAPABILITIES, Manifest, PLUGIN_ID, RESERVED_IDS, discover
from .config import ROOT, STATE_DIR
from .plugin_packages import MAX_BYTES, pack, unpack
from .updater import atomic, sha256, sync_dir


def validate_external(manifest):
    if manifest.id in RESERVED_IDS:
        raise ValueError('This plugin is bundled and updates with HLauncher')
    denied = manifest.capabilities - EXTERNAL_CAPABILITIES
    if denied:
        raise ValueError('Reserved launcher capabilities: ' + ', '.join(sorted(denied)))


class PluginStore:
    def __init__(self, state=STATE_DIR):
        self.state = Path(state)
        self.root = self.state / 'plugin-manager'
        self.code = self.root / 'revisions'
        self.index = self.root / 'installed.json'
        self.legacy = self.root / 'legacy'

    @contextmanager
    def lock(self):
        self.root.mkdir(parents=True, mode=0o700, exist_ok=True)
        with (self.root / 'lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            yield

    def park_legacy(self):
        old = self.state / 'plugins'
        if old.is_dir() or old.is_symlink():
            with self.lock():
                if not old.exists() and not old.is_symlink():
                    return
                if self.legacy.exists() or self.legacy.is_symlink():
                    # Preserve another set of installs made after a launcher rollback.
                    destination = Path(tempfile.mkdtemp(prefix='legacy-', dir=self.root))
                    os.replace(old, destination / 'plugins')
                    sync_dir(destination)
                else:
                    os.replace(old, self.legacy)
                sync_dir(self.root)
                sync_dir(self.state)

    def legacy_sources(self):
        roots = [self.legacy, *(path / 'plugins' for path in sorted(self.root.glob('legacy-*')))]
        return [path for root in roots if root.is_dir() and not root.is_symlink() for path in sorted(root.iterdir())
                if path.is_dir() and not path.is_symlink() and (path / 'plugin.json').is_file()]

    def records(self):
        try:
            with self.index.open('rb') as source:
                payload = source.read(256 * 1024 + 1)
        except FileNotFoundError:
            return {}
        if len(payload) > 256 * 1024:
            raise ValueError('Plugin library index is too large')
        try:
            records = json.loads(payload)
        except (ValueError, RecursionError) as exc:
            raise ValueError('Plugin library index could not be read') from exc
        if (not isinstance(records, dict) or any(not PLUGIN_ID.fullmatch(plugin_id)
                or not isinstance(record, dict) for plugin_id, record in records.items())):
            raise ValueError('Plugin library index is invalid')
        return records

    def manifest(self, plugin_id, record):
        revision = record['current']
        if not re.fullmatch(r'[a-f0-9]{64}', revision):
            raise ValueError('Invalid plugin revision')
        folder = self.code / plugin_id / revision
        manifest = Manifest.load(folder, allow_incompatible=True)
        validate_external(manifest)
        if manifest.id != plugin_id:
            raise ValueError('Plugin ID does not match its record')
        grant = record.get('grant', {})
        camera = grant.get('camera', '')
        endpoint = grant.get('network', '')
        blocked = manifest.blocked
        if not blocked and 'camera' in grant and not re.fullmatch(r'/dev/video[0-9]{1,3}', camera):
            blocked = 'Invalid camera selection'
        if not blocked and not manifest.permissions <= grant.keys():
            blocked = 'Configure the camera or TCP endpoint before enabling'
        return replace(manifest, revision=revision, origin=record.get('origin', 'Local'),
                       enabled=record.get('enabled') is True, blocked=blocked,
                       camera=camera if 'camera' in manifest.permissions else '',
                       endpoint=endpoint if 'network' in manifest.permissions else '',
                       data_path=self.root / 'data' / plugin_id)

    def manifests(self, event=lambda **kw: None):
        result = {}
        try:
            records = self.records()
        except (OSError, ValueError) as exc:
            event(state='plugin_library_rejected', error=str(exc))
            return result
        for plugin_id, record in records.items():
            try:
                result[plugin_id] = self.manifest(plugin_id, record)
            except (ValueError, OSError, TypeError, KeyError, AttributeError) as exc:
                event(state='plugin_manifest_rejected', folder=plugin_id, error=str(exc))
        return result

    def install(self, package, *, origin='Local', update=False, expected=None):
        with self.lock(), tempfile.TemporaryDirectory(prefix='.stage-', dir=self.root) as temporary:
            stage = Path(temporary)
            snapshot = stage / 'package.hlp'
            with Path(package).open('rb') as source, snapshot.open('xb') as target:
                remaining = MAX_BYTES
                while block := source.read(min(65536, remaining + 1)):
                    remaining -= len(block)
                    if remaining < 0:
                        raise ValueError('Plugin package is too large')
                    target.write(block)
            revision = sha256(snapshot)
            if expected is not None and revision != expected:
                raise ValueError('Package changed after review')
            payload = stage / 'code'
            payload.mkdir()
            manifest = unpack(snapshot, payload)
            validate_external(manifest)
            records = self.records()
            old = records.get(manifest.id)
            if old is None and len(records) >= 128:
                raise ValueError('The plugin library is full')
            if bool(old) != update:
                raise ValueError('Use update for an installed plugin' if old else 'Plugin is not installed')
            if old:
                current = self.manifest(manifest.id, old)
                if version_tuple(manifest.version) <= version_tuple(current.version):
                    raise ValueError('Plugin updates need a higher version')
            versions = self.code / manifest.id
            versions.mkdir(parents=True, exist_ok=True)
            target = versions / revision
            if not target.exists():
                payload.chmod(0o755)
                for path in payload.rglob('*'):
                    path.chmod(0o755 if path.is_dir() else 0o644)
                    if path.is_file():
                        with path.open('rb') as source:
                            os.fsync(source.fileno())
                for directory, _, _ in os.walk(payload, topdown=False):
                    sync_dir(directory)
                os.replace(payload, target)
                sync_dir(versions)
                sync_dir(self.code)
            grant = dict(old.get('grant', {})) if old else {}
            grant = {key: value for key, value in grant.items() if key in manifest.permissions}
            data = self.root / 'data' / manifest.id
            data.mkdir(mode=0o700, parents=True, exist_ok=True)
            sync_dir(data.parent)
            record = dict(current=revision, origin=origin, grant=grant,
                          enabled=bool(old and old.get('enabled') and manifest.permissions <= grant.keys()))
            if old:
                record.update(previous=old['current'], previous_origin=old.get('origin', 'Local'))
            records[manifest.id] = record
            atomic(self.index, records)
            self.prune(manifest.id, record)
            return self.manifest(manifest.id, record)

    def prune(self, plugin_id, record):
        folder = self.code / plugin_id
        keep = {record.get('current'), record.get('previous')}
        if folder.is_dir():
            for revision in folder.iterdir():
                if re.fullmatch(r'[a-f0-9]{64}', revision.name) and revision.name not in keep:
                    shutil.rmtree(revision, ignore_errors=True)

    def has_previous(self, plugin_id):
        try:
            return bool(self.records().get(plugin_id, {}).get('previous'))
        except (OSError, ValueError):
            return False

    def change(self, plugin_id, operation, *, camera=None, endpoint=None):
        if not PLUGIN_ID.fullmatch(plugin_id):
            raise ValueError('Invalid plugin ID')
        with self.lock():
            records = self.records()
            record = records.get(plugin_id)
            if record is None:
                raise ValueError('External plugin is not installed')
            if operation == 'remove':
                # Keep the data directory available for a later reinstall.
                del records[plugin_id]
            elif operation == 'rollback':
                if not record.get('previous'):
                    raise ValueError('No previous plugin version')
                record['current'], record['previous'] = record['previous'], record['current']
                record['origin'], record['previous_origin'] = record['previous_origin'], record['origin']
                manifest = self.manifest(plugin_id, record)
                record['grant'] = {key: value for key, value in record['grant'].items() if key in manifest.permissions}
                if manifest.blocked:
                    record['enabled'] = False
            elif operation == 'disable':
                record['enabled'] = False
            elif operation == 'enable':
                manifest = self.manifest(plugin_id, record)
                grant = dict(record.get('grant', {}))
                if camera is not None:
                    if 'camera' not in manifest.permissions or not re.fullmatch(r'/dev/video[0-9]{1,3}', camera):
                        raise ValueError('Choose a requested /dev/videoN camera')
                    grant['camera'] = camera
                if endpoint is not None:
                    if 'network' not in manifest.permissions:
                        raise ValueError('This plugin did not request a network connection')
                    from .plugin_network import parse_endpoint
                    parse_endpoint(endpoint)
                    grant['network'] = endpoint
                if not manifest.permissions <= grant.keys():
                    raise ValueError('Configure the requested camera or TCP endpoint first')
                record['grant'] = grant
                if self.manifest(plugin_id, record).blocked:
                    raise ValueError(manifest.blocked)
                record['enabled'] = True
            else:
                raise ValueError('Unknown plugin operation')
            atomic(self.index, records)
            if operation == 'remove':
                self.prune(plugin_id, {})


def version_tuple(version):
    return tuple(map(int, version.split('.')))


def install(source, destination=None, subdir=None):
    """Compatibility helper for callers staging a source tree into a custom directory."""
    path = Path(source).expanduser().resolve()
    if subdir:
        nested = (path / subdir).resolve()
        if not nested.is_relative_to(path):
            raise ValueError('Plugin subdirectory escapes source')
        path = nested
    if destination is None:
        return install_source(PluginStore(), path).path
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.install-', dir=destination) as temporary:
        root = Path(temporary)
        package = root / 'plugin.hlp'
        pack(path, package)
        payload = root / 'code'
        payload.mkdir()
        manifest = unpack(package, payload)
        validate_external(manifest)
        target = destination / manifest.id
        if target.exists():
            raise ValueError('Plugin is already installed')
        payload.rename(target)
        return target


def install_source(store, source, **options):
    source = Path(source).expanduser()
    if source.is_dir():
        with tempfile.TemporaryDirectory(prefix='hlauncher-plugin-') as scratch:
            package = Path(scratch) / 'plugin.hlp'
            pack(source, package)
            return store.install(package, **options)
    return store.install(source, **options)


def main(argv):
    parser = argparse.ArgumentParser(prog='python3 -m hlauncher plugins')
    commands = parser.add_subparsers(dest='action', required=True)
    commands.add_parser('list')
    for name in ('pack', 'validate', 'preview', 'install', 'update'):
        command = commands.add_parser(name)
        command.add_argument('source')
        if name in ('pack', 'preview'):
            command.add_argument('output')
        if name in ('install', 'update'):
            command.add_argument('--subdir')
            command.add_argument('--asset', help='Choose a .hlp asset in a GitHub release')
    for name in ('enable', 'disable', 'rollback', 'remove'):
        command = commands.add_parser(name)
        command.add_argument('id')
        if name == 'enable':
            command.add_argument('--camera', metavar='/dev/videoN')
            command.add_argument('--endpoint', metavar='HOST:PORT')
    args = parser.parse_args(argv)
    store = PluginStore()
    try:
        if args.action == 'list':
            for manifest in [*discover().values(), *store.manifests().values()]:
                status = 'bundled' if manifest.bundled else manifest.blocked or ('enabled' if manifest.enabled else 'disabled')
                print(f'{manifest.id} {manifest.version} · {status}')
            for path in store.legacy_sources():
                print(f'Legacy source (review and install manually): {path}')
        elif args.action == 'pack':
            validate_external(Manifest.load(Path(args.source)))
            manifest = pack(args.source, args.output)
            print(f'Packaged {manifest.id} {manifest.version}: {args.output}')
        elif args.action == 'validate':
            source = Path(args.source)
            if source.is_dir():
                manifest = Manifest.load(source)
            else:
                with tempfile.TemporaryDirectory() as scratch:
                    manifest = unpack(source, Path(scratch))
            validate_external(manifest)
            print(f'{manifest.id} {manifest.version} · permissions: {", ".join(sorted(manifest.permissions)) or "none"}')
        elif args.action == 'preview':
            from .plugin_preview import preview
            preview(Path(args.source), Path(args.output))
        elif args.action in ('install', 'update'):
            print('External plugins run as root on the Pi. Install only code you trust.', file=sys.stderr)
            from .plugin_sources import github_repo, github_assets, fetch_asset
            repo = github_repo(args.source)
            if repo is None and not Path(args.source).expanduser().exists():
                from .plugin_sources import REPO
                if re.fullmatch(REPO, args.source):
                    repo = github_repo('github.com/' + args.source)
            if repo:
                if args.subdir:
                    raise ValueError('GitHub installs use release packages. Copy a source checkout over SSH for --subdir')
                assets = github_assets(repo)
                choices = [item for item in assets if args.asset is None or item['name'] == args.asset]
                if len(choices) != 1:
                    raise ValueError('Select a package using --asset: ' + ', '.join(item['name'] for item in assets))
                with tempfile.TemporaryDirectory() as scratch:
                    package = Path(scratch) / 'plugin.hlp'
                    origin = fetch_asset(choices[0], package)
                    manifest = store.install(package, origin=origin, update=args.action == 'update')
            else:
                source = Path(args.source).expanduser().resolve()
                if args.subdir:
                    nested = (source / args.subdir).resolve()
                    if not nested.is_relative_to(source):
                        raise ValueError('Plugin subdirectory escapes source')
                    source = nested
                manifest = install_source(store, source, update=args.action == 'update')
            print(f'Installed {manifest.id} {manifest.version} · {"enabled" if manifest.enabled else "disabled"}')
        else:
            store.change(args.id, args.action, camera=getattr(args, 'camera', None), endpoint=getattr(args, 'endpoint', None))
            print(f'{args.id}: {args.action} complete')
    except (OSError, ValueError, RuntimeError) as exc:
        parser.exit(1, f'Plugin error: {exc}\n')
