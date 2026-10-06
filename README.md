# Arma 3 Mod Organizer

A companion to the official Arma 3 Launcher (not a replacement). It manages your mod **presets** by
composing them from reusable **mod sets**, so a change to a shared set reaches every preset that uses it.

## Concepts
- **Mod set**: a named list of mods (e.g. `Core`, `Cold War Maps`).
- **Config**: one launcher preset = included sets + extra mods − excluded mods, plus DLCs to load.
- **Generate** writes each config as `<name>.preset2` into the launcher's `Presets` folder. Presets whose
  content is unchanged are not touched. Order-only changes show as *reordered* and can be skipped. Every write
  first backs up the whole `Presets` folder to `data\backups\<timestamp>\`. Presets that no config manages
  and `arma3.defaultpreset2` are never modified.

## Usage
Run `run.bat` (it creates `.venv` on first run), or `.venv\Scripts\python -m a3mo`.

1. On first start, import your existing launcher presets. Each one becomes a config.
2. **Analysis → Suggest sets** proposes a `Core` set plus groups of mods shared by the same configs.
   Rename or uncheck the suggestions, then apply. Every preset keeps exactly the same mods (this is verified); load order may change.
3. Edit sets in **Mod Sets**: the available mods list is always shown on the right. Add with
   double-click, Enter, *◀ Add to set* or by dragging. Typing a filter that matches one mod and pressing
   Enter adds it. Remove with Delete, *Remove ▶* or by dragging back. Click column headers to sort.
   **Order:** a config's load order is its included sets in order, then its extra mods. Drag rows to reorder
   a set's mods or a config's extra mods (or Ctrl+↑/↓, or right-click → move/sort by name). Drag the
   included sets in a config to order them. Reordering works while the list is sorted by **#** with no filter.
   In **Configs → Resulting preset**, use *Move selected to set…* to promote a
   config's extra mods into a shared set.
4. **Generate presets** (Ctrl+G) shows a dry run (new/changed, +/− mods, warnings), then writes the files.
   Restart the launcher if it was open.

Warnings (orange) mark mods that are not installed according to the launcher's `Steam.json`, local mod
folders that don't exist, and mods missing a Workshop dependency. They never block generating.

Headless: `python -m a3mo --import`, `python -m a3mo --generate [--dry-run] [--ignore-order] [--presets-dir DIR]`.

Data lives in `data\library.json`. Tests: `.venv\Scripts\python -m pytest`.
