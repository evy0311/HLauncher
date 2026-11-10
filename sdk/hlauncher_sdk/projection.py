"""Pass the host's projection lease to USB-owning subprocesses."""
import os


def inherited_fds():
    value=os.environ.get('HLAUNCHER_PROJECTION_FD')
    if value is None:return ()
    fd=int(value);os.fstat(fd)
    return (fd,)
