"""One projection process tree at a time, including detached USB bridges."""
import fcntl
import os
from pathlib import Path
import sys
import tempfile

PROJECTIONS=frozenset(('carplay','android-auto'))


class ProjectionBusy(RuntimeError):pass


class ProjectionLease:
    def __init__(self,path=None):
        runtime=os.environ.get('HLAUNCHER_RUNTIME_DIR','/run/hlauncher' if sys.platform.startswith('linux') else str(Path(tempfile.gettempdir())/('hlauncher-'+str(os.getuid()))))
        path=Path(path) if path else Path(runtime)/'projection.lock'
        path.parent.mkdir(parents=True,exist_ok=True)
        self.fd=os.open(path,os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600)
        try:fcntl.flock(self.fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:
            self.close();raise ProjectionBusy('Waiting for the previous projection session to stop') from None
        except BaseException:self.close();raise
    def close(self):
        if getattr(self,'fd',None) is not None:os.close(self.fd);self.fd=None
    def __del__(self):self.close()


def carplay_adapter_present(root=None):
    root=Path(root) if root is not None else Path(os.environ.get('HLAUNCHER_USB_SYSFS','/sys/bus/usb/devices'))
    for device in root.glob('*'):
        try:
            if int((device/'idVendor').read_text().strip(),16)==0x1314 and int((device/'idProduct').read_text().strip(),16) in (0x1520,0x1521):return True
        except (OSError,ValueError):pass
    return False
