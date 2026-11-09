#!/usr/bin/env python3
"""Create a higher-version, identical-code .hlu from an existing LOCAL TEST release.

This exercises install/restore without building another OS image or publishing
anything. Production releases must use build_release.sh from committed source.
"""
import argparse
from pathlib import Path
import subprocess
import sys
import tempfile

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from hlauncher import updater
from package_release import archive_tree, local_container, public_key


def build(base, version, key, output):
    base,output=Path(base).resolve(),Path(output).resolve()
    item=updater.read(base/'hlauncher-release.json')
    if item.get('local_test') is not True:raise ValueError('Only local-test releases can be repackaged this way')
    if updater.version(version)<=updater.version(item['version']):raise ValueError('Use a higher test version')
    if output.exists():raise ValueError('Use a fresh output directory')
    output.mkdir(parents=True)
    public_key(key,output/'release.pub')
    updater.verify_signature(base/'hlauncher-release.json',base/'hlauncher-release.sig',output/'release.pub')
    original=base/item['archive']
    if original.stat().st_size!=item['size'] or updater.sha256(original)!=item['sha256']:
        raise ValueError('Base release failed verification')
    with tempfile.TemporaryDirectory(prefix='hlauncher-test-update-') as temporary:
        tree=Path(temporary)/'payload'
        updater.unpack(original,tree,item['unpacked_size'])
        (tree/'app/hlauncher/__init__.py').write_text('"""Local update-test version."""\n__version__ = '+repr(version)+'\n')
        info=updater.read(tree/'app/build-info.json')
        updater.atomic(tree/'app/build-info.json',dict(info,version=version,test_parent_version=item['version']))
        filename=f'HLauncher-{version}-pi4-arm64.tar.xz'
        size=archive_tree(output/filename,[('app',tree/'app'),('runtime',tree/'runtime')])
    item=dict(item,version=version,archive=filename,size=(output/filename).stat().st_size,
              unpacked_size=size,sha256=updater.sha256(output/filename),test_parent_version=item['version'])
    updater.atomic(output/'hlauncher-release.json',item)
    subprocess.run(['openssl','pkeyutl','-sign','-rawin','-inkey',str(key),'-in',str(output/'hlauncher-release.json'),
                    '-out',str(output/'hlauncher-release.sig')],check=True,capture_output=True)
    updater.verify_signature(output/'hlauncher-release.json',output/'hlauncher-release.sig',output/'release.pub')
    container=local_container(output,version,output/filename)
    with (output/'SHA256SUMS').open('w') as checksums:
        for path in sorted(output.iterdir()):
            if path.name!='SHA256SUMS' and path.is_file():checksums.write(updater.sha256(path)+'  '+path.name+'\n')
    print(container)
    return item


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base',type=Path,required=True);parser.add_argument('--version',required=True)
    parser.add_argument('--key',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();build(args.base,args.version,args.key,args.output)
