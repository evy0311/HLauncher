#!/usr/bin/env python3
"""Require a complete, signed fresh-install and updater release before upload."""
import argparse
import re
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from hlauncher import updater


def assets(version):
    updater.version(version)
    return [f'HLauncher-{version}-pi4.img.xz',f'HLauncher-{version}-pi4-arm64.tar.xz',
            f'HLauncher-{version}-local-update.hlu',f'HLauncher-{version}-sources.tar.xz',
            'hlauncher-release.json','hlauncher-release.sig','release.pub','os-packages.txt',
            'RELEASE-NOTES.md','SHA256SUMS']


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
    if not re.fullmatch('[0-9a-f]{64}',str(item.get('system_contract',''))):
        raise ValueError('Missing system compatibility contract')
    if not re.fullmatch('[0-9a-f]{40}',str(item.get('commit',''))):
        raise ValueError('Missing release source commit')
    updater.validate_manifest(item,dict(platform=updater.PLATFORM,system_contract=item.get('system_contract')))
    sums={}
    for line in (folder/'SHA256SUMS').read_text().splitlines():
        if not line:continue
        digest,name=line.split('  ',1)
        if Path(name).name!=name or name in sums or len(digest)!=64:
            raise ValueError('Invalid checksum entry')
        sums[name]=digest
    for name in names:
        if name=='SHA256SUMS':continue
        if sums.get(name)!=updater.sha256(folder/name):raise ValueError('Missing or incorrect checksum: '+name)
    if item['sha256']!=sums[item['archive']] or item['size']!=(folder/item['archive']).stat().st_size:
        raise ValueError('Update bundle differs from signed metadata')
    updater.verify_signature(folder/'hlauncher-release.json',folder/'hlauncher-release.sig',folder/'release.pub')
    return names


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('version');parser.add_argument('folder',type=Path)
    args=parser.parse_args()
    try:
        for name in validate(args.folder,args.version):print(name)
    except (ValueError,OSError) as exc:parser.exit(1,str(exc)+'\n')
