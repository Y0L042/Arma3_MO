"""Library of reusable mod sets and the configs (presets) composed from them."""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path


def ordered_unique(items):
    seen = set()
    out = []
    for i in items:
        if i not in seen:
            seen.add(i)
            out.append(i)
    return out


@dataclass
class ModSet:
    mods: list[str] = field(default_factory=list)
    notes: str = ""


@dataclass
class Config:
    sets: list[str] = field(default_factory=list)
    add: list[str] = field(default_factory=list)
    exclude: list[str] = field(default_factory=list)
    dlcs: list[int] = field(default_factory=list)
    notes: str = ""


@dataclass
class Settings:
    launcher_dir: str = r"%LOCALAPPDATA%\Arma 3 Launcher"

    @property
    def launcher_path(self) -> Path:
        return Path(os.path.expandvars(self.launcher_dir))

    @property
    def presets_path(self) -> Path:
        return self.launcher_path / "Presets"


@dataclass
class Library:
    sets: dict[str, ModSet] = field(default_factory=dict)
    configs: dict[str, Config] = field(default_factory=dict)
    settings: Settings = field(default_factory=Settings)

    # --- resolution -------------------------------------------------------
    def resolve(self, config_name: str) -> list[str]:
        """Final ordered mod list: included sets in order, then ``add``, minus ``exclude``."""
        cfg = self.configs[config_name]
        mods: list[str] = []
        for s in cfg.sets:
            if s in self.sets:
                mods.extend(self.sets[s].mods)
        mods.extend(cfg.add)
        excluded = set(cfg.exclude)
        return [m for m in ordered_unique(mods) if m not in excluded]

    def resolve_all(self) -> dict[str, list[str]]:
        return {name: self.resolve(name) for name in self.configs}

    def configs_using_set(self, set_name: str) -> list[str]:
        return [c for c, cfg in self.configs.items() if set_name in cfg.sets]

    def rename_set(self, old: str, new: str) -> None:
        if new in self.sets:
            raise ValueError(f"Set '{new}' already exists")
        self.sets = {(new if k == old else k): v for k, v in self.sets.items()}
        for cfg in self.configs.values():
            cfg.sets = [new if s == old else s for s in cfg.sets]

    def delete_set(self, name: str) -> None:
        self.sets.pop(name, None)
        for cfg in self.configs.values():
            cfg.sets = [s for s in cfg.sets if s != name]

    def rename_config(self, old: str, new: str) -> None:
        if new in self.configs:
            raise ValueError(f"Config '{new}' already exists")
        self.configs = {(new if k == old else k): v for k, v in self.configs.items()}

    # --- persistence ------------------------------------------------------
    def to_dict(self) -> dict:
        return {
            "sets": {k: asdict(v) for k, v in self.sets.items()},
            "configs": {k: asdict(v) for k, v in self.configs.items()},
            "settings": asdict(self.settings),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Library":
        return cls(
            sets={k: ModSet(**v) for k, v in d.get("sets", {}).items()},
            configs={k: Config(**v) for k, v in d.get("configs", {}).items()},
            settings=Settings(**d.get("settings", {})),
        )

    @classmethod
    def load(cls, path: Path) -> "Library":
        path = Path(path)
        if not path.exists():
            return cls()
        return cls.from_dict(json.loads(path.read_text(encoding="utf-8")))

    def save(self, path: Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")
        os.replace(tmp, path)
