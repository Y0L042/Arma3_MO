"""Mod metadata read from the Arma 3 Launcher's own JSON caches (read-only)."""
from __future__ import annotations

import json
import os
import re
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
    tags: list[str] = field(default_factory=list)  # Workshop type tags, see workshop.py


def _load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return {}


def read_meta_cpp(mod_dir: Path) -> tuple[str, str] | None:
    """``(publishedid, name)`` from a Workshop mod folder's ``meta.cpp``, or None."""
    try:
        text = (Path(mod_dir) / "meta.cpp").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    pid = re.search(r"publishedid\s*=\s*(\d+)", text)
    name = re.search(r'name\s*=\s*"([^"]*)"', text)
    return (pid.group(1), name.group(1) if name else "") if pid and pid.group(1) != "0" else None


def scan_workshop_dirs(dirs, mods: dict[str, "ModInfo"]) -> None:
    """Add / mark installed the Workshop mods found on disk that ``Steam.json`` doesn't (yet) list.

    The launcher rewrites ``Steam.json`` only now and then, so a mod subscribed while it runs is
    missing there until later; Steam has already put it into ``!Workshop``.
    """
    for d in dirs:
        try:
            children = [c for c in Path(d).iterdir() if c.name.startswith("@")]
        except OSError:
            continue
        for child in children:
            meta = read_meta_cpp(child)
            if not meta:
                continue
            mid = f"steam:{meta[0]}"
            info = mods.get(mid)
            if info is None:
                mods[mid] = ModInfo(
                    id=mid, name=meta[1] or child.name.lstrip("@"), installed=True, path=str(child),
                    url=f"https://steamcommunity.com/sharedfiles/filedetails/?id={meta[0]}",
                )
            elif not info.installed:
                info.installed, info.path = True, info.path or str(child)


def local_mod_name(mod_id: str) -> str:
    path = mod_id.split(":", 1)[1].rstrip("\\/")
    return os.path.basename(path) or path


def local_mod_id(path: str) -> str:
    """The launcher's id for a local mod folder: ``local:`` + upper-case path + ``\\``."""
    return "local:" + str(path).replace("/", "\\").rstrip("\\").upper() + "\\"


def find_local_mod_folders(known_paths) -> dict[str, str]:
    """``@mod`` folders near the launcher's local mods (``MyMods\\@X`` or ``MyMods\\X\\@X``), id -> path.

    Used to find where a local mod went after its folder was moved.
    """
    roots = set()
    for p in known_paths:
        parent = os.path.dirname(str(p).rstrip("\\/"))
        roots.update({parent, os.path.dirname(parent)})
    found: dict[str, str] = {}
    for root in filter(None, roots):
        try:
            entries = list(os.scandir(root))
        except OSError:
            continue
        for e in entries:
            if not e.is_dir():
                continue
            if e.name.startswith("@"):
                found.setdefault(local_mod_id(e.path), e.path)
                continue
            try:
                subs = [s for s in os.scandir(e.path) if s.name.startswith("@") and s.is_dir()]
            except OSError:
                continue
            for s in subs:
                found.setdefault(local_mod_id(s.path), s.path)
    return found


class ModCatalog:
    """Lookup of display names / install state for ``steam:`` and ``local:`` mod ids.

    A local mod counts as installed if its folder exists. ``local_folders`` lists ``@mod`` folders
    found near the launcher's local mods (id -> path), used to relink moved local mods.
    """

    def __init__(self, mods: dict[str, ModInfo] | None = None):
        self.mods: dict[str, ModInfo] = mods or {}
        self.local_folders: dict[str, str] = {}
        self._titles: dict[str, str] = {}
        self._tags: dict[str, list[str]] = {}

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
        # The folders holding the launcher's Workshop mods (normally just <Arma 3>/!Workshop).
        scan_workshop_dirs({os.path.dirname(m.path.rstrip("\\/")) for m in mods.values()
                            if m.id.startswith("steam:") and m.path}, mods)
        # Local mods added in the launcher. Current launchers store plain folder paths.
        local = _load_json(Path(launcher_dir) / "Local.json")
        local_paths = []
        for e in local.get("knownLocalMods", []) or []:
            if isinstance(e, str):
                e = {"ExtensionPath": e}
            if not isinstance(e, dict):
                continue
            path = e.get("ExtensionPath") or ""
            mid = e.get("Id") or (local_mod_id(path) if path else "")
            if mid and mid not in mods:
                path = path or mid.split(":", 1)[1]
                local_paths.append(path)
                mods[mid] = ModInfo(
                    id=mid,
                    name=e.get("DisplayName") or os.path.basename(path.rstrip("\\/")) or local_mod_name(mid),
                    installed=os.path.isdir(path),
                    path=path,
                )
        catalog = cls(mods)
        catalog.local_folders = find_local_mod_folders(local_paths)
        return catalog

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
        self._decorate(info)
        self.mods[mod_id] = info
        return info

    def name(self, mod_id: str) -> str:
        return self.info(mod_id).name

    def installed(self, mod_id: str) -> bool:
        return self.info(mod_id).installed

    def apply_workshop(self, titles: dict[str, str] | None = None, tags: dict[str, list[str]] | None = None) -> None:
        """Workshop details (see workshop.py). Titles name mods the launcher doesn't know (whose name
        would otherwise be the bare id). Applied to known mods now and to others when first looked up,
        so cached entries don't add mods to the catalog."""
        self._titles.update(titles or {})
        self._tags.update(tags or {})
        for info in self.mods.values():
            self._decorate(info)

    def _decorate(self, info: ModInfo) -> None:
        if info.id in self._tags:
            info.tags = list(self._tags[info.id])
        if info.name == info.id and (title := self._titles.get(info.id)):
            info.name = title

    def tags(self, mod_id: str) -> list[str]:
        return self.info(mod_id).tags

    def tag_counts(self, ids) -> dict[str, int]:
        """Tag -> number of ``ids`` carrying it, most common first."""
        counts: dict[str, int] = {}
        for m in ids:
            for t in self.info(m).tags:
                counts[t] = counts.get(t, 0) + 1
        return dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0].lower())))

    def all_ids(self) -> list[str]:
        return sorted(self.mods, key=lambda m: self.mods[m].name.lower())
