"""Read and build bounded, data-only HLauncher plugin packages."""

import os
from pathlib import Path, PurePosixPath
import re
import stat
import tempfile
import zipfile

from .catalog import Manifest

MAX_BYTES = 64 * 1024 * 1024
MAX_FILES = 4096
SKIP = {'.git', '__pycache__', '.venv', '.DS_Store', '.env'}


def file_name(name):
    path = PurePosixPath(name)
    if (not name or len(name) > 512 or len(path.parts) > 16 or path.is_absolute()
            or path.as_posix() != name
            or any(part in ('..', '.') or not re.fullmatch(r'[A-Za-z0-9._@+ -]{1,128}', part)
                   for part in path.parts)):
        raise ValueError('Invalid path in plugin package')
    return path


def source_files(folder):
    count = size = 0
    for directory, dirs, files in os.walk(folder):
        dirs[:] = sorted(set(dirs) - SKIP)
        for name in [*dirs, *sorted(set(files) - SKIP)]:
            path = Path(directory) / name
            relative = file_name(path.relative_to(folder).as_posix())
            mode = path.lstat().st_mode
            if stat.S_ISDIR(mode):
                continue
            if not stat.S_ISREG(mode):
                raise ValueError('Plugin packages cannot contain links or special files')
            count += 1
            size += path.stat().st_size
            if count > MAX_FILES or size > MAX_BYTES:
                raise ValueError('Plugin package exceeds install limits')
            yield path, relative


def unpack(source, destination):
    if source.stat().st_size > MAX_BYTES:
        raise ValueError('Plugin package is too large')
    try:
        with zipfile.ZipFile(source) as archive:
            members = archive.infolist()
            if len(members) > MAX_FILES or sum(m.file_size for m in members) > MAX_BYTES:
                raise ValueError('Plugin package exceeds install limits')
            names = set()
            for member in members:
                name = file_name(member.filename)
                mode = stat.S_IFMT(member.external_attr >> 16)
                if (name in names or member.orig_filename != member.filename
                        or member.is_dir() or mode not in (0, stat.S_IFREG)
                        or member.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED)
                        or member.flag_bits & 1):
                    raise ValueError('Plugin package must contain unique regular files')
                names.add(name)
                output = destination / name
                output.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(member) as data, output.open('xb') as target:
                    remaining = member.file_size
                    while block := data.read(min(65536, remaining + 1)):
                        remaining -= len(block)
                        if remaining < 0:
                            raise ValueError('Plugin file exceeds its declared size')
                        target.write(block)
                    if remaining:
                        raise ValueError('Plugin file is incomplete')
    except (zipfile.BadZipFile, FileExistsError, NotADirectoryError, IsADirectoryError) as exc:
        raise ValueError('Invalid HLauncher plugin package') from exc
    return Manifest.load(destination)


def pack(folder, output):
    folder = Path(folder).resolve()
    output = Path(output).resolve()
    if output.is_relative_to(folder):
        raise ValueError('Write the package outside the source directory')
    manifest = Manifest.load(folder)
    with tempfile.TemporaryDirectory(dir=output.parent) as scratch:
        staged = Path(scratch) / 'package.hlp'
        with zipfile.ZipFile(staged, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
            for path, relative in source_files(folder):
                info = zipfile.ZipInfo(str(relative))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = (stat.S_IFREG | 0o644) << 16
                archive.writestr(info, path.read_bytes())
        if staged.stat().st_size > MAX_BYTES:
            raise ValueError('Plugin package is too large')
        os.replace(staged, output)
    return manifest
