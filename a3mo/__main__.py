"""Entry point: ``python -m a3mo`` opens the GUI; flags run headless."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import BACKUP_DIR, LIBRARY_PATH
from .launcher_data import ModCatalog
from .model import Library
from .sync import apply_generate, find_moved_local_mods, import_presets, launcher_running, plan_generate


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="a3mo", description="Arma 3 Mod Organizer")
    ap.add_argument("--library", type=Path, default=LIBRARY_PATH, help="library JSON path")
    ap.add_argument("--presets-dir", type=Path, help="override the launcher Presets folder")
    ap.add_argument("--import", dest="do_import", action="store_true", help="import launcher presets as configs")
    ap.add_argument("--generate", action="store_true", help="write presets from the library")
    ap.add_argument("--dry-run", action="store_true", help="with --generate: only show what would change")
    ap.add_argument("--ignore-order", action="store_true", help="with --generate: skip presets that only differ in mod order")
    args = ap.parse_args(argv)

    if not (args.do_import or args.generate):
        from .gui.app import run
        return run(args.library)

    lib = Library.load(args.library)
    presets_dir = args.presets_dir or lib.settings.presets_path
    if args.do_import:
        names = import_presets(lib, presets_dir)
        lib.save(args.library)
        print(f"Imported {len(names)} preset(s) into {args.library}")
    if args.generate:
        catalog = ModCatalog.load(lib.settings.launcher_path)
        if moved := find_moved_local_mods(lib.all_mod_ids(), catalog):
            lib.replace_mods(moved)
            if not args.dry_run:
                lib.save(args.library)
            print(f"Updated {len(moved)} moved local mod folder(s)")
        plan = plan_generate(lib, catalog, presets_dir)
        plan.include_reordered = not args.ignore_order
        for item in plan.items:
            extra = f" +{len(item.added)} -{len(item.removed)}" if item.status == "changed" else ""
            warn = f"  [{len(item.missing)} not installed]" if item.missing else ""
            print(f"{item.status:9} {item.config}{extra}{warn}")
        for name in plan.unmanaged:
            print(f"unmanaged {name}")
        if not args.dry_run:
            if launcher_running():
                print("Note: Arma 3 Launcher is running; restart it to see updated presets.")
            backup = apply_generate(plan, presets_dir, BACKUP_DIR)
            print(f"Wrote {len(plan.to_write)} preset(s)" + (f"; backup in {backup}" if backup else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
