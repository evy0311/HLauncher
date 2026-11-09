"""Install plugin source without executing it or fetching its dependencies."""

import argparse
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
from .catalog import Manifest, discover
from .config import STATE_DIR, ROOT


def install(source, destination=None, subdir=None):
    destination = Path(destination) if destination else STATE_DIR / "plugins"
    with tempfile.TemporaryDirectory(prefix="hlauncher-install-") as tmp:
        path = Path(source).expanduser()
        if not path.is_dir():
            if not source.startswith(("https://", "ssh://", "git@")):
                raise ValueError("Use a plugin folder or an HTTPS/SSH Git repository")
            path = Path(tmp) / "repository"
            subprocess.run(
                ["git", "clone", "--depth", "1", "--", source, str(path)],
                check=True,
                timeout=120,
            )
        if subdir:
            base = path.resolve()
            path = (base / subdir).resolve()
            if not path.is_relative_to(base):
                raise ValueError("plugin subdirectory escapes repository")
        manifest = Manifest.load(path)
        if manifest.id in discover(roots=[(ROOT / "plugins", True)]):
            raise ValueError(
                "This plugin is bundled; update it through the HLauncher repository"
            )
        destination.mkdir(parents=True, exist_ok=True)
        target = destination / manifest.id
        if target.exists():
            raise ValueError(
                "Plugin already installed; remove the existing copy before replacing it"
            )
        staged = Path(tempfile.mkdtemp(prefix=".install-", dir=destination))
        try:
            count = size = 0
            for source_file in path.rglob("*"):
                relative = source_file.relative_to(path)
                if any(
                    p in {".git", "node_modules", "__pycache__", ".venv"}
                    for p in relative.parts
                ):
                    continue
                if source_file.is_symlink():
                    raise ValueError("Plugin symlinks are not accepted")
                if source_file.is_file():
                    count += 1
                    size += source_file.stat().st_size
                    if count > 4096 or size > 64 * 1024 * 1024:
                        raise ValueError("Plugin source exceeds install limits")
                    output = staged / relative
                    output.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source_file, output)
            Manifest.load(staged)
            staged.rename(target)
        finally:
            if staged.exists():
                shutil.rmtree(staged)
        return target


def main(argv):
    parser = argparse.ArgumentParser(prog="python3 -m hlauncher plugins")
    commands = parser.add_subparsers(dest="action", required=True)
    commands.add_parser("list")
    add = commands.add_parser("install")
    add.add_argument("source")
    add.add_argument("--subdir")
    args = parser.parse_args(argv)
    if args.action == "list":
        for manifest in discover().values():
            print(
                f'{manifest.id}: {manifest.name} ({"bundled" if manifest.bundled else "local"})'
            )
    else:
        print("Installed:", install(args.source, subdir=args.subdir))
        print(
            "Install the plugin dependencies described by its author, restart HLauncher, then enable it in Settings."
        )
