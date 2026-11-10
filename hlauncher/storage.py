"""Root-only RAM overlay protection with independently writable HLauncher state."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
from .setup_state import atomic_json
from .config import STATE_DIR

PERSIST = Path('/persist')
OVERLAY = 'overlayroot=tmpfs:recurse=0'


def execute(args, **kwargs):
    return subprocess.run(args, check=True, capture_output=True, text=True,
                          timeout=kwargs.pop('timeout', 180), **kwargs)


def mount_for(path, run=execute):
    data = json.loads(run(['findmnt', '--json', '--target', str(path),
                          '--output', 'SOURCE,TARGET,FSTYPE,OPTIONS']).stdout)
    return data['filesystems'][0]


def status(run=execute, persist=PERSIST, state_dir=STATE_DIR):
    try:
        root = mount_for('/', run)
        data = mount_for(persist, run)
        source = lambda row: row['source'].split('[')[0]
        persistent = ((persist/'.hlauncher-state-v1').is_file() and data['target']==str(persist)
                      and data['fstype']=='ext4' and 'rw' in data['options'].split(',')
                      and source(root) != source(data))
        for folder in ('/var/lib/hlauncher', '/var/lib/bluetooth', '/etc/NetworkManager/system-connections'):
            row=mount_for(folder, run)
            persistent = persistent and source(row)==source(data) and 'rw' in row['options'].split(',')
        message='Ready' if persistent else 'Requires the HLauncher persistent-data image layout'
        try:
            transition=json.loads((Path(state_dir)/'storage-transition.json').read_text())
            if transition.get('target')=='failed':message=transition.get('message','SD protection did not activate')
        except (OSError,ValueError,TypeError):pass
        return dict(protected=root['fstype']=='overlay', available=bool(persistent),message=message)
    except (OSError, ValueError, KeyError, subprocess.SubprocessError):
        return dict(protected=False, available=False, message='Storage layout could not be verified')


def boot_folder(system=Path('/')):
    system=Path(system)
    return system/('boot/firmware' if (system/'boot/firmware/config.txt').is_file() else 'boot')


def verify_support(run=execute, system=Path('/'), kernel=None):
    """Check the firmware-loaded image, rather than just the requested boot flag."""
    system=Path(system);boot=boot_folder(system)
    try:
        installed=run(['dpkg-query','-W','-f=${db:Status-Status}','overlayroot']).stdout.strip()
        if installed!='installed':raise ValueError('SD protection support is missing from this image')
        if not re.search(r'^\s*auto_initramfs\s*=\s*1\s*$',(boot/'config.txt').read_text(),re.M):
            raise ValueError('Automatic initramfs loading is not enabled')
        image=boot/'initramfs8'
        if not image.is_file():raise ValueError('SD protection boot image is missing')
        kernel=kernel or run(['uname','-r']).stdout.strip()
        members=run(['lsinitramfs',str(image)],timeout=60).stdout.splitlines()
        if 'scripts/init-bottom/overlayroot' not in members:
            raise ValueError('SD protection is missing from the boot initramfs')
        if not any('/lib/modules/'+kernel+'/kernel/fs/overlayfs/overlay.ko' in '/'+name for name in members):
            raise ValueError('SD protection boot image does not match the kernel')
        canonical=system/'boot'/('initrd.img-'+kernel)
        if not canonical.is_file() or hashlib.sha256(canonical.read_bytes()).digest()!=hashlib.sha256(image.read_bytes()).digest():
            raise ValueError('SD protection boot image is out of date')
    except (OSError,subprocess.SubprocessError) as exc:
        raise ValueError('SD protection boot support could not be verified; repair the system image') from exc


def image_kernel(system=Path('/')):
    versions=[p.name for p in (Path(system)/'lib/modules').glob('*-v8') if p.is_dir()]
    if not versions:raise ValueError('The Raspberry Pi 4 kernel modules are missing')
    return max(versions,key=lambda value:tuple(int(v) for v in re.findall(r'\d+',value)))


def prepare(run=execute):
    kernel=image_kernel()
    run(['update-initramfs','-u','-k',kernel],timeout=300)
    verify_support(run,kernel=kernel)


def write_file(path, text):
    """Replace boot configuration atomically, retaining the original file mode."""
    path=Path(path);mode=path.stat().st_mode & 0o777
    fd,name=tempfile.mkstemp(prefix='.'+path.name,dir=path.parent)
    try:
        with os.fdopen(fd,'w') as output:
            output.write(text);output.flush();os.fsync(output.fileno());os.fchmod(output.fileno(),mode)
        os.replace(name,path)
        fd=os.open(path.parent,os.O_RDONLY)
        try:os.fsync(fd)
        finally:os.close(fd)
    finally:
        if os.path.exists(name):os.unlink(name)


def boot_readonly(enabled, system=Path('/')):
    path=Path(system)/'etc/fstab';lines=path.read_text().splitlines();found=False
    for index,line in enumerate(lines):
        fields=line.split()
        if line.lstrip().startswith('#') or len(fields)<4 or fields[1] not in ('/boot','/boot/firmware'):continue
        options=[v for v in fields[3].split(',') if v not in ('ro','rw')]
        if enabled:options.append('ro')
        fields[3]=','.join(options);lines[index]='\t'.join(fields);found=True
    if not found:raise ValueError('Boot partition mount configuration is missing')
    write_file(path,'\n'.join(lines)+'\n')


def configure(enabled, run=execute, state_dir=STATE_DIR, persist=PERSIST, system=Path('/')):
    if type(enabled) is not bool:raise ValueError('Choose protection On or Off')
    info=status(run,persist,state_dir)
    if not info['available']:raise ValueError(info['message'])
    if enabled and info['protected']:return 'Already enabled'
    # There are no downloads at toggle time. A complete image contains these already.
    if enabled:verify_support(run,system)
    boot=boot_folder(system);cmdline=boot/'cmdline.txt'
    previous=cmdline.read_text();fstab=Path(system)/'etc/fstab';old_fstab=fstab.read_text()
    was_ro='ro' in mount_for(boot,run)['options'].split(',')
    path=Path(state_dir)/'storage-transition.json'
    atomic_json(path,{'target':'protected' if enabled else 'writable'})
    try:
        run(['mount','-o','remount,rw',str(boot)])
        words=[word for word in previous.split() if not word.startswith('overlayroot=')]
        if enabled:words.insert(0,OVERLAY)
        write_file(cmdline,' '.join(words)+'\n')
        # An active overlay cannot persist /etc/fstab edits. Finish disabling next boot.
        if not info['protected']:boot_readonly(enabled,system)
        run(['sync'])
        if enabled or info['protected'] or was_ro:
            run(['mount','-o','remount,ro',str(boot)])
        if not enabled and not info['protected']:
            run(['mount','-o','remount,rw',str(boot)])
    except BaseException:
        try:
            run(['mount','-o','remount,rw',str(boot)])
            write_file(cmdline,previous)
            if not info['protected']:write_file(fstab,old_fstab)
            if was_ro:run(['mount','-o','remount,ro',str(boot)])
        finally:atomic_json(path,{'target':'failed','message':'SD protection configuration failed'})
        raise
    return 'Restart required to apply storage mode'


def finish_transition(run=execute, state_dir=STATE_DIR, persist=PERSIST, system=Path('/')):
    path=Path(state_dir)/'storage-transition.json'
    try:target=json.loads(path.read_text())['target']
    except (OSError,ValueError,KeyError):return
    if target not in ('protected','writable'):return
    info=status(run,persist,state_dir)
    if target=='writable' and info['available'] and not info['protected']:
        boot_readonly(False,system)
        run(['mount','-o','remount,rw',str(boot_folder(system))])
        atomic_json(path,{'target':'complete'})
    elif target=='protected' and info['protected'] and info['available']:
        atomic_json(path,{'target':'complete'})
    else:
        message='SD protection did not activate after restart' if target=='protected' else 'Writable mode did not activate after restart'
        atomic_json(path,{'target':'failed','message':message})
        atomic_json(Path(state_dir)/'maintenance-status.json',{'status':'Failed','message':message})


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser();group=parser.add_mutually_exclusive_group()
    group.add_argument('--prepare',action='store_true');group.add_argument('--verify',action='store_true')
    args=parser.parse_args()
    if args.prepare:prepare()
    elif args.verify:verify_support(kernel=image_kernel())
    else:finish_transition()
