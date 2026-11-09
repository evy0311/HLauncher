#!/usr/bin/env python3
"""Compact an unmounted HLauncher MBR image; retain UUIDs and all three partitions."""
import argparse
from contextlib import ExitStack
import json
import math
import os
from pathlib import Path
import shutil
import stat
import subprocess
import tempfile

MIB=1024**2


def run(args,**kwargs):
    return subprocess.run([str(x) for x in args],check=True,text=True,**kwargs)


def check(device):
    result=subprocess.run(['e2fsck','-pf',str(device)])
    if result.returncode not in (0,1):raise RuntimeError('Filesystem check failed: '+str(device))


def fs_bytes(device):
    text=run(['dumpe2fs','-h',device],capture_output=True).stdout
    fields=dict(line.split(':',1) for line in text.splitlines() if ':' in line)
    return int(fields['Block count'])*int(fields['Block size'])


def rounded(size):return math.ceil(size/(16*MIB))*16*MIB


def compact(image,root_free_mib=192,state_mib=512):
    image=Path(image).resolve()
    if not image.is_file() or not stat.S_ISREG(image.stat().st_mode):raise ValueError('Use an image FILE, never a disk device')
    if root_free_mib<128 or state_mib<512:raise ValueError('Insufficient runtime/update space')
    if run(['losetup','-j',image],capture_output=True).stdout.strip():raise ValueError('Image must not already be attached')
    table=json.loads(run(['sfdisk','--json',image],capture_output=True).stdout)['partitiontable']
    parts=table['partitions'];sector=table.get('sectorsize',512)
    if table['label']!='dos' or sector!=512 or len(parts)!=3:raise ValueError('Expected HLauncher three-partition MBR image')
    if [p['type'].lower() for p in parts] not in (['c','83','83'],['b','83','83']):raise ValueError('Unexpected partition types')
    loop=run(['losetup','--find','--show','--partscan',image],capture_output=True).stdout.strip()
    root=loop+'p2';state=loop+'p3'
    try:
        for i in (1,2,3):
            node=Path(loop+f'p{i}');major,minor=(Path('/sys/class/block')/node.name/'dev').read_text().strip().split(':')
            if node.exists():node.unlink()
            os.mknod(node,stat.S_IFBLK|0o600,os.makedev(int(major),int(minor)))
        label=run(['blkid','-s','LABEL','-o','value',state],capture_output=True).stdout.strip()
        if label!='HLAUNCHER_STATE':raise ValueError('Not an HLauncher data image')
        for device in (root,state):
            check(device);run(['resize2fs','-M',device])
        root_size=rounded(fs_bytes(root)+root_free_mib*MIB)
        state_size=max(state_mib*MIB,rounded(fs_bytes(state)+256*MIB))
        for device,size in ((root,root_size),(state,state_size)):
            run(['resize2fs',device,str(size//1024)+'K']);check(device)
            run(['zerofree',device])
        start_root=parts[1]['start']*sector
        start_state=(start_root+root_size+MIB-1)//MIB*MIB
        old_start=parts[2]['start']*sector
        with ExitStack() as stack:
            if start_state+state_size<=old_start:
                # Non-overlapping forward relocation needs no extra partition copy.
                saved=stack.enter_context(image.open('rb',buffering=0));saved.seek(old_start)
            else:
                saved=stack.enter_context(tempfile.TemporaryFile(dir=image.parent))
                with open(state,'rb',buffering=0) as source:
                    remaining=state_size
                    while remaining:
                        block=source.read(min(8*MIB,remaining))
                        if not block:raise RuntimeError('Unexpected end of data filesystem')
                        saved.write(block);remaining-=len(block)
                saved.flush();os.fsync(saved.fileno());saved.seek(0)
            run(['losetup','-d',loop]);loop=None
            with image.open('r+b',buffering=0) as target:
                target.seek(start_state);remaining=state_size
                while remaining:
                    block=saved.read(min(8*MIB,remaining))
                    if not block:raise RuntimeError('Unexpected end of data filesystem')
                    if target.write(block)!=len(block):raise RuntimeError('Short image write')
                    remaining-=len(block)
                target.flush();os.fsync(target.fileno())
            parts[1]['size']=(start_state-start_root)//sector
            parts[2]['start']=start_state//sector;parts[2]['size']=state_size//sector
            lines=['label: dos','label-id: '+table['id'],'unit: sectors','sector-size: 512','']
            for part in parts:
                line=f"start={part['start']}, size={part['size']}, type={part['type']}"
                if part.get('bootable'):line+=', bootable'
                lines.append(line)
            run(['sfdisk','--no-reread','--no-tell-kernel','--force',image],input='\n'.join(lines)+'\n')
            with image.open('r+b') as target:target.truncate(start_state+state_size);target.flush();os.fsync(target.fileno())
        result=dict(bytes=image.stat().st_size,root_bytes=parts[1]['size']*sector,state_bytes=state_size,
                    state_grows_at_first_boot=True)
        print(json.dumps(result),flush=True)
        return result
    finally:
        if loop:run(['losetup','-d',loop])


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('image',type=Path)
    parser.add_argument('--root-free-mib',type=int,default=192)
    parser.add_argument('--state-mib',type=int,default=512)
    args=parser.parse_args();compact(args.image,args.root_free_mib,args.state_mib)


if __name__=='__main__':main()
