"""Import launcher presets into the library, and generate presets from it."""
from __future__ import annotations

import datetime as _dt
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from .launcher_data import ModCatalog
from .model import Config, Library
from .preset_io import DEFAULT_PRESET_NAME, Preset, list_preset_files, read_preset2, write_preset2


def import_presets(lib: Library, presets_dir: Path, overwrite: bool = False) -> list[str]:
    """Create one config per ``.preset2`` file (all mods in ``add``). Returns imported names."""
    imported = []
    for path in list_preset_files(presets_dir):
        if path.name.lower() == DEFAULT_PRESET_NAME:
            continue
        p = read_preset2(path)
        if p.name in lib.configs and not overwrite:
            continue
        lib.configs[p.name] = Config(add=list(p.mods), dlcs=list(p.dlcs))
        imported.append(p.name)
    return imported


@dataclass
class PlanItem:
    config: str
    status: str  # "new" | "changed" | "reordered" (same mods, different order) | "unchanged"
    mods: list[str]
    dlcs: list[int]
    added: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    missing_deps: dict[str, list[str]] = field(default_factory=dict)  # mod -> deps not in preset

    @property
    def filename(self) -> str:
        return f"{self.config}.preset2"


@dataclass
class GeneratePlan:
    items: list[PlanItem]
    unmanaged: list[str]  # preset files in the folder that no config produces
    include_reordered: bool = True  # also write presets whose only change is mod order

    @property
    def to_write(self) -> list[PlanItem]:
        skip = {"unchanged"} if self.include_reordered else {"unchanged", "reordered"}
        return [i for i in self.items if i.status not in skip]


def check_issues(mods: list[str], catalog: ModCatalog) -> tuple[list[str], dict[str, list[str]]]:
    present = set(mods)
    missing = [m for m in mods if not catalog.installed(m)]
    deps = {}
    for m in mods:
        lacking = [d for d in catalog.info(m).dependencies if d not in present]
        if lacking:
            deps[m] = lacking
    return missing, deps


def plan_generate(lib: Library, catalog: ModCatalog, presets_dir: Path | None = None) -> GeneratePlan:
    presets_dir = Path(presets_dir or lib.settings.presets_path)
    existing = {p.stem: p for p in list_preset_files(presets_dir) if p.name.lower() != DEFAULT_PRESET_NAME}
    items = []
    for name in lib.configs:
        mods = lib.resolve(name)
        dlcs = list(lib.configs[name].dlcs)
        missing, deps = check_issues(mods, catalog)
        item = PlanItem(config=name, status="new", mods=mods, dlcs=dlcs, missing=missing, missing_deps=deps)
        if name in existing:
            old = read_preset2(existing[name])
            if old.same_content(Preset(name, mods, dlcs)):
                item.status = "unchanged" if old.mods == mods else "reordered"
            else:
                item.status = "changed"
                old_set, new_set = set(old.mods), set(mods)
                item.added = [m for m in mods if m not in old_set]
                item.removed = [m for m in old.mods if m not in new_set]
        items.append(item)
    unmanaged = sorted(n for n in existing if n not in lib.configs)
    return GeneratePlan(items=items, unmanaged=unmanaged)


def backup_presets(presets_dir: Path, backup_root: Path) -> Path:
    stamp = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    dest = Path(backup_root) / stamp
    dest.mkdir(parents=True, exist_ok=True)
    for p in Path(presets_dir).iterdir():
        if p.is_file():
            shutil.copy2(p, dest / p.name)
    return dest


def apply_generate(plan: GeneratePlan, presets_dir: Path, backup_root: Path) -> Path | None:
    """Back up the Presets folder, then write new/changed presets. Returns the backup path."""
    if not plan.to_write:
        return None
    presets_dir = Path(presets_dir)
    presets_dir.mkdir(parents=True, exist_ok=True)
    backup = backup_presets(presets_dir, backup_root)
    for item in plan.to_write:
        write_preset2(presets_dir / item.filename, Preset(item.config, item.mods, item.dlcs))
    return backup


def launcher_running() -> bool:
    try:
        out = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq arma3launcher.exe", "/NH"],
            capture_output=True, text=True, timeout=5,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return False
    return "arma3launcher.exe" in out.lower()
