"""Set suggestions, diffs and overlap statistics over a Library."""
from __future__ import annotations

import copy
from collections import defaultdict
from dataclasses import dataclass, field

from .launcher_data import ModCatalog
from .model import Library, ModSet


@dataclass
class SuggestedSet:
    name: str
    mods: list[str]
    configs: list[str]
    # Configs that take the set but lack some of its mods get those excluded.
    excludes: dict[str, list[str]] = field(default_factory=dict)


_NOISE = {"a3", "_dev_", "dev", "debug", "combined"}


def _common_words_name(names: list[str]) -> str:
    """Longest run of words found in every config name (ignoring noise words)."""
    split = [[w for w in n.split() if w.lower() not in _NOISE] for n in names]
    if not split or not split[0]:
        return ""
    lowered = [" " + " ".join(w.lower() for w in ws) + " " for ws in split[1:]]
    first = split[0]
    for length in range(len(first), 0, -1):
        for start in range(len(first) - length + 1):
            run = first[start:start + length]
            needle = " " + " ".join(w.lower() for w in run) + " "
            if all(needle in hay for hay in lowered):
                return " ".join(run)
    return ""


def _unique(name: str, taken: set[str]) -> str:
    out, i = name, 2
    while out in taken:
        out = f"{name} ({i})"
        i += 1
    taken.add(out)
    return out


def suggest_sets(
    lib: Library,
    core_threshold: float = 0.8,
    core_min_coverage: float = 0.5,
    min_set_size: int = 2,
    catalog: ModCatalog | None = None,
) -> list[SuggestedSet]:
    """Propose shared sets from what the configs currently resolve to.

    * "Core": mods present in at least ``core_threshold`` of configs. It is assigned
      to every config containing at least ``core_min_coverage`` of the core mods;
      the core mods such a config lacks become excludes.
    * Remaining mods are grouped by exact presence signature (the set of configs
      containing them). Groups shared by 2+ configs with ``min_set_size``+ mods
      become candidate sets.
    """
    resolved = {c: lib.resolve(c) for c in lib.configs}
    if not resolved:
        return []
    order: list[str] = []
    presence: dict[str, set[str]] = defaultdict(set)
    for cfg, mods in resolved.items():
        for m in mods:
            if m not in presence:
                order.append(m)
            presence[m].add(cfg)

    taken = set(lib.sets)
    out: list[SuggestedSet] = []
    n = len(resolved)
    core = [m for m in order if len(presence[m]) >= max(2, core_threshold * n)]
    core_set = set(core)
    if core:
        members, excludes = [], {}
        for cfg, mods in resolved.items():
            have = core_set.intersection(mods)
            if len(have) >= core_min_coverage * len(core):
                members.append(cfg)
                lacking = [m for m in core if m not in have]
                if lacking:
                    excludes[cfg] = lacking
        # Configs that don't take Core simply keep those mods in their own `add`.
        out.append(SuggestedSet(_unique("Core", taken), core, members, excludes))

    groups: dict[frozenset[str], list[str]] = defaultdict(list)
    for m in order:
        if m not in core_set:
            groups[frozenset(presence[m])].append(m)
    cfg_order = list(resolved)
    candidates = [(sig, mods) for sig, mods in groups.items() if len(sig) >= 2 and len(mods) >= min_set_size]
    candidates.sort(key=lambda x: (-len(x[1]), -len(x[0])))
    for sig, mods in candidates:
        configs = [c for c in cfg_order if c in sig]
        base = _common_words_name(configs)
        if not base:
            first = catalog.name(mods[0]) if catalog else mods[0]
            base = f"{first} +{len(mods) - 1}"
        out.append(SuggestedSet(_unique(base, taken), mods, configs))
    return out


def apply_suggestions(lib: Library, suggestions: list[SuggestedSet]) -> Library:
    """Return a new Library with the suggested sets applied. Raises if output would change."""
    new = copy.deepcopy(lib)
    before = {c: set(new.resolve(c)) for c in new.configs}
    for s in suggestions:
        new.sets[s.name] = ModSet(mods=list(s.mods))
        set_mods = set(s.mods)
        for cfg_name in s.configs:
            cfg = new.configs[cfg_name]
            if s.name not in cfg.sets:
                cfg.sets.append(s.name)
            cfg.add = [m for m in cfg.add if m not in set_mods]
            for m in s.excludes.get(cfg_name, []):
                if m not in cfg.exclude:
                    cfg.exclude.append(m)
    after = {c: set(new.resolve(c)) for c in new.configs}
    bad = [c for c in before if before[c] != after[c]]
    if bad:
        raise RuntimeError(f"Applying suggestions would change: {', '.join(bad)}")
    return new


def diff_configs(lib: Library, a: str, b: str) -> tuple[list[str], list[str], list[str]]:
    ra, rb = lib.resolve(a), lib.resolve(b)
    sa, sb = set(ra), set(rb)
    return [m for m in ra if m not in sb], [m for m in rb if m not in sa], [m for m in ra if m in sb]


def overlap_matrix(lib: Library) -> tuple[list[str], list[list[int]]]:
    names = list(lib.configs)
    res = {n: set(lib.resolve(n)) for n in names}
    return names, [[len(res[a] & res[b]) for b in names] for a in names]


def mod_usage(lib: Library, mod_id: str) -> tuple[list[str], list[str]]:
    """(sets containing the mod, configs resolving to include it)."""
    sets = [s for s, ms in lib.sets.items() if mod_id in ms.mods]
    configs = [c for c in lib.configs if mod_id in lib.resolve(c)]
    return sets, configs
