#!/usr/bin/env python3
"""Fetch pinned upstream code and apply the small HLauncher patch set."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import urllib.request

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    spec = json.loads((ROOT/'third_party/dependencies.json').read_text())['node-carplay']
    patch = ROOT/spec['patch']
    fingerprint = hashlib.sha256((json.dumps(spec,sort_keys=True)+digest(patch)+'typescript5.7.3-program').encode()).hexdigest()
    target = ROOT/'plugins/carplay/runtime/usb/vendor/node-carplay'
    stamp = target/'.hlauncher-dependency.json'
    try:
        saved=json.loads(stamp.read_text())
        valid=saved.get('fingerprint')==fingerprint and bool(saved.get('files')) and all(
            (target/name).is_file() and digest(target/name)==value for name,value in saved['files'].items())
    except (OSError,ValueError):
        valid=False
    if args.check:
        if not valid:
            raise SystemExit('Run python3 scripts/fetch_dependencies.py to prepare node-CarPlay.')
        print('node-CarPlay: pinned dependency and HLauncher patches prepared')
        return
    if valid:
        print('node-CarPlay: already prepared')
        return
    cache = ROOT/'.dependency-cache'
    cache.mkdir(exist_ok=True)
    archive = cache/(spec['commit']+'.tar.gz')
    if not archive.exists() or digest(archive) != spec['sha256']:
        part=archive.with_suffix('.download')
        with urllib.request.urlopen(spec['url'],timeout=60) as response, part.open('wb') as out:
            shutil.copyfileobj(response,out)
        if digest(part) != spec['sha256']:
            part.unlink()
            raise SystemExit('Upstream archive checksum mismatch')
        part.replace(archive)
    tools=ROOT/'third_party/toolchain'
    subprocess.run(['npm','ci','--prefix',str(tools),'--ignore-scripts','--no-audit','--no-fund'],check=True)
    with tempfile.TemporaryDirectory(dir=cache) as temp:
        stage=Path(temp)/'node-carplay';stage.mkdir()
        with tarfile.open(archive) as bundle:
            prefix=bundle.getmembers()[0].name.split('/')[0]+'/'
            for name in ['LICENSE']+spec['files']:
                path=stage/name;path.parent.mkdir(parents=True,exist_ok=True)
                with bundle.extractfile(prefix+name) as src:path.write_bytes(src.read())
        subprocess.run(['patch','-p1','--batch','-i',str(patch)],cwd=stage,check=True)
        js="""const fs=require('fs'),path=require('path'),ts=require(process.argv[1]);
const root=process.argv[2],files=[];
function walk(dir){for(const file of fs.readdirSync(dir)){const p=path.join(dir,file);
if(fs.statSync(p).isDirectory())walk(p);else if(p.endsWith('.ts'))files.push(p);}}
walk(path.join(root,'src'));
const program=ts.createProgram(files,{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.ES2022,
rootDir:path.join(root,'src'),outDir:path.join(root,'dist'),skipLibCheck:true,noEmitOnError:false});
if(program.emit().emitSkipped)process.exit(1);"""
        subprocess.run(['node','-e',js,str(tools/'node_modules/typescript'),str(stage)],check=True)
        (stage/'package.json').write_text(json.dumps({'name':'node-carplay','private':True,'type':'module','upstream_commit':spec['commit']},indent=2)+'\n')
        (stage/'.hlauncher-dependency.json').write_text(json.dumps({'fingerprint':fingerprint,'commit':spec['commit'],
            'files':{str(p.relative_to(stage)):digest(p) for p in stage.rglob('*') if p.is_file()}})+'\n')
        target.parent.mkdir(parents=True,exist_ok=True)
        if target.exists():shutil.rmtree(target)
        shutil.move(str(stage),target)
    print('node-CarPlay: fetched, verified and patched')


if __name__=='__main__':main()
