"""Expand only an image's final persistent partition; retry safely after interruption."""
import json
import os
from pathlib import Path
import stat
import subprocess
import tempfile


def atomic_json(path,values):
    path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    fd,name=tempfile.mkstemp(prefix=".storage-growth-",dir=path.parent)
    try:
        with os.fdopen(fd,"w") as output:
            json.dump(values,output);output.write("\n");output.flush();os.fsync(output.fileno())
        os.replace(name,path)
        directory=os.open(path.parent,os.O_RDONLY)
        try:os.fsync(directory)
        finally:os.close(directory)
    finally:
        Path(name).unlink(missing_ok=True)


def execute(args,**kwargs):
    return subprocess.run(args,capture_output=True,text=True,**kwargs)


def geometry(mount,run=execute):
    mount=Path(mount).resolve()
    if not (mount/'.hlauncher-state-v1').is_file():raise ValueError('Not an HLauncher image data partition')
    result=run(['findmnt','--json','--target',str(mount),'--output','SOURCE,TARGET,FSTYPE'],check=True,timeout=10)
    item=json.loads(result.stdout)['filesystems'][0]
    if item['target']!=str(mount) or item['fstype']!='ext4':raise ValueError('Expected a dedicated ext4 mount')
    source=Path(item['source']).resolve()
    device=source.stat()
    if not stat.S_ISBLK(device.st_mode):raise ValueError('Data source is not a block device')
    sysdev=(Path('/sys/dev/block')/f'{os.major(device.st_rdev)}:{os.minor(device.st_rdev)}').resolve(strict=True)
    number=int((sysdev/'partition').read_text())
    disk=Path('/dev')/sysdev.parent.name
    table=json.loads(run(['sfdisk','--json',str(disk)],check=True,timeout=10).stdout)['partitiontable']
    if table['label'] not in ('dos','gpt'):raise ValueError('Unsupported partition table')
    partitions=table['partitions']
    current=next(p for p in partitions if Path(p['node']).resolve()==source)
    if current!=max(partitions,key=lambda p:p['start']+p['size']):raise ValueError('Data partition must be last')
    label=run(['blkid','-s','LABEL','-o','value',str(source)],check=True,timeout=10).stdout.strip()
    if label!='HLAUNCHER_STATE':raise ValueError('Unexpected data partition label')
    identity=run(['blkid','-s','UUID','-o','value',str(source)],check=True,timeout=10).stdout.strip()
    if not identity:raise ValueError('Data filesystem UUID is missing')
    size=int(run(['blockdev','--getsize64',str(disk)],check=True,timeout=10).stdout)
    part_size=int(run(['blockdev','--getsize64',str(source)],check=True,timeout=10).stdout)
    return dict(disk=str(disk),source=str(source),number=number,uuid=identity,
                start=current['start'],disk_bytes=size,partition_bytes=part_size)


def expand(mount=Path('/persist'),run=execute,probe=geometry):
    mount=Path(mount)
    marker=mount/'state/storage-expanded.json'
    before=probe(mount,run)
    try:saved=json.loads(marker.read_text())
    except (OSError,ValueError):saved={}
    if all(saved.get(k)==before[k] for k in ('uuid','disk_bytes','partition_bytes')):return 'already expanded'
    result=run(['growpart','--fudge','0',before['disk'],str(before['number'])],timeout=90)
    if result.returncode not in (0,1) or result.returncode==1 and not result.stdout.startswith('NOCHANGE:'):
        raise RuntimeError('Persistent partition expansion failed')
    after=probe(mount,run)
    if any(after[k]!=before[k] for k in ('uuid','source','disk','number','start','disk_bytes')):
        raise RuntimeError('Partition identity changed during expansion')
    if after['partition_bytes']<before['partition_bytes']:raise RuntimeError('Partition unexpectedly shrank')
    # Always retry the filesystem step, even if a previous boot grew only the partition.
    run(['resize2fs',after['source']],check=True,timeout=180)
    atomic_json(marker,{k:after[k] for k in ('uuid','disk_bytes','partition_bytes')})
    return 'expanded'


def main():
    print('HLauncher persistent storage: '+expand(),flush=True)


if __name__=='__main__':main()
