"""Discover data-only manifests. Plugin code is never imported into the host."""

from dataclasses import dataclass
import json
from pathlib import Path
import re
from .config import ROOT, STATE_DIR

CAPABILITIES = {"display", "touch", "session", "audio.status", "audio.capture", "audio.playback", "media.publish"}


@dataclass
class Manifest:
    id: str
    name: str
    entrypoint: list
    capabilities: set
    path: Path
    bundled: bool = False
    default_enabled: bool = False
    keep_alive: bool = False
    color: str = "#18416e"

    @classmethod
    def load(cls, folder, bundled=False):
        folder = Path(folder).resolve()
        data = json.loads((folder / "plugin.json").read_text())
        if not isinstance(data, dict):
            raise ValueError("manifest must be an object")
        if data.get("api_version") != 1:
            raise ValueError("unsupported plugin API")
        plugin_id = data.get("id", "")
        if not isinstance(plugin_id, str) or not re.fullmatch(
            r"[a-z][a-z0-9_-]{0,47}", plugin_id
        ):
            raise ValueError("invalid plugin id")
        name = data.get("name")
        if not isinstance(name, str) or not 1 <= len(name) <= 32:
            raise ValueError("invalid plugin name")
        entry = data.get("entrypoint")
        if (
            not isinstance(entry, list)
            or len(entry) != 2
            or entry[0] not in ("python3", "node")
        ):
            raise ValueError("entrypoint must be [python3|node, relative script]")
        if not isinstance(entry[1], str):
            raise ValueError("invalid entrypoint")
        script = (folder / entry[1]).resolve()
        if not script.is_relative_to(folder) or not script.is_file():
            raise ValueError("entrypoint escapes plugin folder or is missing")
        caps = data.get("capabilities", [])
        if not isinstance(caps, list) or not all(
            isinstance(c, str) and c in CAPABILITIES for c in caps
        ):
            raise ValueError("unknown plugin capability")
        color = data.get("color", "#18416e")
        if not isinstance(color, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", color):
            raise ValueError("invalid tile color")
        return cls(
            plugin_id,
            name,
            [entry[0], str(script)],
            set(caps),
            folder,
            bundled,
            data.get("default_enabled") is True,
            data.get("keep_alive") is True,
            color,
        )


def discover(event=lambda **kw: None, roots=None):
    result = {}
    roots = (
        roots
        if roots is not None
        else [(ROOT / "plugins", True), (STATE_DIR / "plugins", False)]
    )
    for root, bundled in roots:
        root = Path(root)
        if not root.exists():
            continue
        for folder in sorted(root.iterdir()):
            if (
                folder.name.startswith(".")
                or not folder.is_dir()
                or not (folder / "plugin.json").exists()
            ):
                continue
            try:
                manifest = Manifest.load(folder, bundled)
                if manifest.id in result:
                    raise ValueError("duplicate plugin id")
                result[manifest.id] = manifest
            except (ValueError, OSError, TypeError) as exc:
                event(
                    state="plugin_manifest_rejected", folder=folder.name, error=str(exc)
                )
    return result
