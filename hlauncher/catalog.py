"""Discover data-only manifests. Plugin code is never imported into the host."""

from dataclasses import dataclass
import json
from pathlib import Path
import re
from .config import ROOT

API_VERSION = 1
RESERVED_IDS = frozenset(('carplay', 'android-auto', 'obd', 'vehicle'))
PLUGIN_ID = re.compile(r"[a-z][a-z0-9_-]{0,47}")
PERMISSIONS = frozenset(('camera', 'network'))
PARKING_CAPABILITY = 'vehicle.parking'
EXTERNAL_CAPABILITIES = frozenset(('display', 'touch', 'session', 'audio.playback', 'media.publish', PARKING_CAPABILITY))

CAPABILITIES = {"display", "touch", "session", "audio.status", "audio.capture", "audio.playback", "media.publish", "input.buttons", "projection.voice", PARKING_CAPABILITY}


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

    api_version: int = API_VERSION
    version: str = "0.0.0"
    icon: Path | None = None
    permissions: frozenset = frozenset()
    revision: str = ""
    origin: str = ""
    camera: str = ""
    endpoint: str = ""
    blocked: str = ""
    enabled: bool = False
    data_path: Path | None = None
    requires_parked: bool = False

    @classmethod
    def load(cls, folder, bundled=False, *, allow_incompatible=False):
        folder = Path(folder).resolve()
        descriptor = folder / "plugin.json"
        if descriptor.stat().st_size > 16384:
            raise ValueError("Plugin manifest is too large")
        try:
            data = json.loads(descriptor.read_text())
        except (ValueError, RecursionError) as exc:
            raise ValueError("Invalid plugin manifest JSON") from exc
        if not isinstance(data, dict):
            raise ValueError("manifest must be an object")
        api = data.get("api_version")
        if type(api) is not int or not 1 <= api <= 65535:
            raise ValueError("invalid plugin API version")
        blocked = "" if api == API_VERSION else f"Requires plugin API {api}"
        if blocked and not allow_incompatible:
            raise ValueError(blocked)
        plugin_id = data.get("id", "")
        if not isinstance(plugin_id, str) or not PLUGIN_ID.fullmatch(plugin_id):
            raise ValueError("invalid plugin id")
        name = data.get("name")
        if not isinstance(name, str) or not 1 <= len(name) <= 32 or not name.isprintable():
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
        relative = Path(entry[1])
        script = (folder / relative).resolve()
        if (relative.is_absolute() or ".." in relative.parts or entry[1].startswith("-")
                or not script.is_relative_to(folder) or not script.is_file()):
            raise ValueError("entrypoint escapes plugin folder or is missing")
        caps = data.get("capabilities", [])
        if not isinstance(caps, list) or not all(
            isinstance(c, str) and c in CAPABILITIES for c in caps
        ):
            raise ValueError("unknown plugin capability")
        requires_parked = data.get("requires_parked", False)
        if type(requires_parked) is not bool:
            raise ValueError("requires_parked must be a boolean")
        if requires_parked and PARKING_CAPABILITY not in caps:
            raise ValueError("requires_parked needs the vehicle.parking capability")
        color = data.get("color", "#18416e")
        if not isinstance(color, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", color):
            raise ValueError("invalid tile color")
        version = data.get("version", "0.0.0")
        if not isinstance(version, str) or not re.fullmatch(r"(?:0|[1-9][0-9]{0,4})(?:\.(?:0|[1-9][0-9]{0,4})){2}", version):
            raise ValueError("Plugin version must be major.minor.patch")
        icon = None
        if "icon" in data:
            if data["icon"] != "icon.png":
                raise ValueError("Plugin icon must be named icon.png")
            icon = folder / "icon.png"
            if icon.is_symlink() or not icon.is_file() or icon.stat().st_size > 65536:
                raise ValueError("Plugin icon must be a PNG under 64 KiB")
        permissions = data.get("permissions", [])
        if not isinstance(permissions, list) or any(not isinstance(p, str) or p not in PERMISSIONS for p in permissions):
            raise ValueError("Unknown external plugin permission")
        return cls(
            plugin_id,
            name,
            [entry[0], str(script)],
            set(caps),
            folder,
            bundled,
            data.get("default_enabled") is True,
            data.get("keep_alive") is True,
            color, api_version=api, version=version, icon=icon,
            permissions=frozenset(permissions), blocked=blocked, requires_parked=requires_parked,
        )


def discover(event=lambda **kw: None, roots=None):
    result = {}
    roots = (
        roots
        if roots is not None
        else [(ROOT / "plugins", True)]
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
