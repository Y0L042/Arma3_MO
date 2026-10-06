"""Mod metadata read from the Arma 3 Launcher's own JSON caches (read-only)."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path


def default_launcher_dir() -> Path:
    return Path(os.path.expandvars(r"%LOCALAPPDATA%\Arma 3 Launcher"))


@dataclass
class ModInfo:
    id: str
    name: str
    installed: bool
    path: str = ""
    url: str = ""
    author: str = ""
    dependencies: list[str] = field(default_factory=list)


def _load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return {}


def local_mod_name(mod_id: str) -> str:
    path = mod_id.split(":", 1)[1].rstrip("\\/")
    return os.path.basename(path) or path


class ModCatalog:
    """Lookup of display names / install state for ``steam:`` and ``local:`` mod ids."""

    def __init__(self, mods: dict[str, ModInfo] | None = None):
        self.mods: dict[str, ModInfo] = mods or {}

    @classmethod
    def load(cls, launcher_dir: Path) -> "ModCatalog":
        mods: dict[str, ModInfo] = {}
        steam = _load_json(Path(launcher_dir) / "Steam.json")
        for e in steam.get("Extensions", []):
            mid = e.get("Id")
            if not mid:
                continue
            mods[mid] = ModInfo(
                id=mid,
                name=e.get("DisplayName") or mid,
                installed=bool(e.get("IsInstalled")),
                path=e.get("ExtensionPath") or "",
                url=e.get("Url") or "",
                author=e.get("Author") or "",
                dependencies=[f"steam:{d}" for d in e.get("SteamDependencies") or []],
            )
        local = _load_json(Path(launcher_dir) / "Local.json")
        for e in local.get("knownLocalMods", []) or []:
            if not isinstance(e, dict):
                continue
            mid = e.get("Id")
            if mid and mid not in mods:
                mods[mid] = ModInfo(
                    id=mid,
                    name=e.get("DisplayName") or local_mod_name(mid),
                    installed=os.path.isdir(e.get("ExtensionPath") or mid.split(":", 1)[-1]),
                    path=e.get("ExtensionPath") or "",
                )
        return cls(mods)

    def info(self, mod_id: str) -> ModInfo:
        if mod_id in self.mods:
            return self.mods[mod_id]
        if mod_id.startswith("local:"):
            path = mod_id.split(":", 1)[1]
            info = ModInfo(id=mod_id, name=local_mod_name(mod_id), installed=os.path.isdir(path), path=path)
        else:
            num = mod_id.split(":", 1)[-1]
            info = ModInfo(
                id=mod_id,
                name=mod_id,
                installed=False,
                url=f"https://steamcommunity.com/sharedfiles/filedetails/?id={num}",
            )
        self.mods[mod_id] = info
        return info

    def name(self, mod_id: str) -> str:
        return self.info(mod_id).name

    def installed(self, mod_id: str) -> bool:
        return self.info(mod_id).installed

    def all_ids(self) -> list[str]:
        return sorted(self.mods, key=lambda m: self.mods[m].name.lower())
