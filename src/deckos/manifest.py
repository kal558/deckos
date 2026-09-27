"""Launcher manifests: each module installs /usr/share/deckos/apps/<module>.toml.

Format:

    [[app]]
    id = "wikipedia"
    name = "Wikipedia"
    icon = "accessories-dictionary-symbolic"
    command = ["deck-reader", "--open", "wikipedia"]
    heavy = false            # heavy apps obey the one-at-a-time rule
    requires = ["ssd"]       # hardware ids from deckos.hardware
    order = 10               # position on the home screen
    status = "library"       # optional deck-status tile key for live text
"""
from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from . import paths


class ManifestError(ValueError):
    pass


@dataclass(frozen=True)
class App:
    id: str
    name: str
    command: tuple[str, ...]
    icon: str = "application-x-executable-symbolic"
    heavy: bool = False
    requires: tuple[str, ...] = field(default_factory=tuple)
    order: int = 100
    status: str | None = None
    module: str = ""
    description: str = ""


def _parse_app(raw: dict, module: str) -> App:
    for key in ("id", "name", "command"):
        if key not in raw:
            raise ManifestError(f"{module}: app missing '{key}'")
    command = raw["command"]
    if isinstance(command, str) or not command or not all(isinstance(c, str) for c in command):
        raise ManifestError(f"{module}/{raw['id']}: command must be a non-empty list of strings")
    return App(
        id=str(raw["id"]),
        name=str(raw["name"]),
        command=tuple(command),
        icon=str(raw.get("icon", App.icon)),
        heavy=bool(raw.get("heavy", False)),
        requires=tuple(raw.get("requires", ())),
        order=int(raw.get("order", 100)),
        status=raw.get("status"),
        module=module,
        description=str(raw.get("description", "")),
    )


def parse(text: str, module: str) -> list[App]:
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:
        raise ManifestError(f"{module}: {e}") from e
    return [_parse_app(a, module) for a in data.get("app", [])]


def load_all(directory: Path | None = None) -> list[App]:
    """Load every manifest; a broken manifest is skipped, not fatal."""
    directory = directory or paths.apps_dir()
    apps: dict[str, App] = {}
    for f in sorted(directory.glob("*.toml")):
        try:
            for app in parse(f.read_text(), f.stem):
                apps[app.id] = app
        except (ManifestError, OSError) as e:
            print(f"deckos: skipping manifest {f}: {e}")
    return sorted(apps.values(), key=lambda a: (a.order, a.name))


def find(app_id: str, directory: Path | None = None) -> App | None:
    return next((a for a in load_all(directory) if a.id == app_id), None)
