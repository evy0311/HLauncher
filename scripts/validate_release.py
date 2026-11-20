#!/usr/bin/env python3
"""Require a complete, signed fresh-install and updater release before upload."""
import argparse
import hashlib
import lzma
import subprocess
import re
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from hlauncher import updater
from hlauncher.development_builds import metadata


def assets(version):
    updater.version(version)
    return [f'HLauncher-{version}-pi4.img.xz',f'HLauncher-{version}-pi4-arm64.tar.xz',
            f'HLauncher-{version}-local-update.hlu',f'HLauncher-{version}-sources.tar.xz',
            'hlauncher-release.json','hlauncher-release.sig','release.pub',
            'SHA256SUMS','SHA256SUMS.sig']


def validate(folder, version):
    folder=Path(folder)
    names=assets(version)
    for name in names:
        path=folder/name
        if not path.is_file() or not path.stat().st_size:
            raise ValueError('Missing release asset: '+name)
    item=updater.read(folder/'hlauncher-release.json')
    if item.get('local_test') is not False:
        raise ValueError('Publish a production image without developer SSH access')
    if item.get('version')!=version:raise ValueError('Release version mismatch')
    if item.get('channel', 'stable') not in ('stable', 'beta', 'development'):raise ValueError('Invalid release channel')
    if item.get('channel') == 'development':metadata(item)
    if not re.fullmatch('[0-9a-f]{64}',str(item.get('system_contract',''))):
        raise ValueError('Missing system compatibility contract')
    if not re.fullmatch('[0-9a-f]{40}',str(item.get('commit',''))):
        raise ValueError('Missing release source commit')
    updater.validate_manifest(item,dict(platform=updater.PLATFORM,system_contract=item.get('system_contract')))
    updater.verify_signature(folder/'SHA256SUMS',folder/'SHA256SUMS.sig',folder/'release.pub')
    sums={}
    for line in (folder/'SHA256SUMS').read_text().splitlines():
        if not line:continue
        digest,name=line.split('  ',1)
        if Path(name).name!=name or name in sums or not re.fullmatch('[0-9a-f]{64}',digest):
            raise ValueError('Invalid checksum entry')
        sums[name]=digest
    if sums.keys() != set(names) - {'SHA256SUMS', 'SHA256SUMS.sig'}:
        raise ValueError('Checksum list differs from the expected release assets')
    for name in sums:
        if sums.get(name)!=updater.sha256(folder/name):raise ValueError('Missing or incorrect checksum: '+name)
    if item['sha256']!=sums[item['archive']] or item['size']!=(folder/item['archive']).stat().st_size:
        raise ValueError('Update bundle differs from signed metadata')
    updater.verify_signature(folder/'hlauncher-release.json',folder/'hlauncher-release.sig',folder/'release.pub')
    image = folder/names[0]
    try:
        with lzma.open(image, 'rb') as source:
            if source.read(512)[510:] != b'\x55\xaa':
                raise ValueError('Fresh image has no partition table signature')
            while source.read(1024 * 1024):
                pass
    except (EOFError, lzma.LZMAError) as exc:
        raise ValueError('Invalid compressed image') from exc
    with (folder/names[2]).open('rb') as source:
        for name, size in updater.local_members(source):
            if name == 'package.tar.xz':
                digest = hashlib.sha256()
                for block in updater.local_blocks(source, size):
                    digest.update(block)
                if size != item['size'] or digest.hexdigest() != item['sha256']:
                    raise ValueError('Manual update package differs from signed metadata')
            else:
                published = folder/('hlauncher-release.json' if name == 'manifest.json' else 'hlauncher-release.sig')
                if size != published.stat().st_size or source.read(size) != published.read_bytes():
                    raise ValueError('Manual update metadata differs from published metadata')
    return names


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('version');parser.add_argument('folder',type=Path)
    args=parser.parse_args()
    try:
        for name in validate(args.folder,args.version):print(name)
    except (ValueError,OSError,subprocess.SubprocessError) as exc:parser.exit(1,str(exc)+'\n')
