import shutil

import pytest

from a3mo.analysis import apply_suggestions, diff_configs, overlap_matrix, suggest_sets
from a3mo.launcher_data import ModCatalog, ModInfo, default_launcher_dir
from a3mo.model import Library
from a3mo.preset_io import Preset, list_preset_files, read_preset2, write_preset2
from a3mo.sync import apply_generate, import_presets, plan_generate

CORE = [f"steam:{i}" for i in range(1, 6)]


def write_fixture(d):
    write_preset2(d / "SOG.preset2", Preset("SOG", CORE + ["steam:100", "steam:101"], [1227700]))
    write_preset2(d / "SOG ASU.preset2", Preset("SOG ASU", CORE + ["steam:100", "steam:101", "steam:200"], [1227700]))
    write_preset2(d / "Cold War.preset2", Preset("Cold War", CORE[:-1] + ["steam:300", "steam:301"], []))
    write_preset2(d / "Combined.preset2", Preset("Combined", CORE + ["steam:300"], []))
    write_preset2(d / "Sandbox.preset2", Preset("Sandbox", ["steam:1"], []))
    write_preset2(d / "arma3.defaultpreset2", Preset("arma3", ["steam:999"], []))


def catalog():
    ids = CORE + ["steam:100", "steam:101", "steam:200", "steam:300", "steam:301"]
    mods = {m: ModInfo(m, m, True) for m in ids}
    mods["steam:200"].dependencies = ["steam:404"]
    return ModCatalog(mods)


def test_import_suggest_generate_is_noop(tmp_path):
    write_fixture(tmp_path)
    lib = Library()
    assert sorted(import_presets(lib, tmp_path)) == ["Cold War", "Combined", "SOG", "SOG ASU", "Sandbox"]
    sugg = suggest_sets(lib, core_threshold=0.6)
    names = {s.name: s for s in sugg}
    assert names["Core"].mods == CORE
    assert set(names["Core"].configs) == {"SOG", "SOG ASU", "Cold War", "Combined"}
    assert names["Core"].excludes == {"Cold War": ["steam:5"]}
    assert names["SOG"].mods == ["steam:100", "steam:101"]
    lib = apply_suggestions(lib, sugg)
    assert lib.configs["SOG ASU"].sets == ["Core", "SOG"]
    assert lib.configs["SOG ASU"].add == ["steam:200"]
    plan = plan_generate(lib, catalog(), tmp_path)
    assert all(i.status == "unchanged" for i in plan.items)
    assert apply_generate(plan, tmp_path, tmp_path / "bk") is None


def test_edit_core_changes_only_dependents(tmp_path):
    write_fixture(tmp_path)
    lib = Library()
    import_presets(lib, tmp_path)
    lib = apply_suggestions(lib, suggest_sets(lib, core_threshold=0.6))
    lib.sets["Core"].mods.append("steam:777")
    plan = plan_generate(lib, catalog(), tmp_path)
    status = {i.config: i.status for i in plan.items}
    assert status == {"SOG": "changed", "SOG ASU": "changed", "Cold War": "changed", "Combined": "changed",
                      "Sandbox": "unchanged"}
    sog = next(i for i in plan.items if i.config == "SOG ASU")
    assert sog.added == ["steam:777"] and "steam:777" in sog.missing
    assert sog.missing_deps == {"steam:200": ["steam:404"]}
    backup = apply_generate(plan, tmp_path, tmp_path / "bk")
    assert (backup / "SOG.preset2").exists() and (backup / "arma3.defaultpreset2").exists()
    assert "steam:777" in read_preset2(tmp_path / "SOG.preset2").mods
    assert read_preset2(tmp_path / "arma3.defaultpreset2").mods == ["steam:999"]


def test_new_config_and_unmanaged(tmp_path):
    write_fixture(tmp_path)
    lib = Library()
    import_presets(lib, tmp_path)
    del lib.configs["Sandbox"]
    lib.rename_config("SOG", "SOG v2")
    plan = plan_generate(lib, catalog(), tmp_path)
    assert {i.config: i.status for i in plan.items}["SOG v2"] == "new"
    assert plan.unmanaged == ["SOG", "Sandbox"]


def test_diff_and_overlap(tmp_path):
    write_fixture(tmp_path)
    lib = Library()
    import_presets(lib, tmp_path)
    only_a, only_b, common = diff_configs(lib, "SOG", "SOG ASU")
    assert only_a == [] and only_b == ["steam:200"] and len(common) == 7
    names, m = overlap_matrix(lib)
    i, j = names.index("SOG"), names.index("Sandbox")
    assert m[i][j] == 1 and m[i][i] == 7


REAL_DIR = default_launcher_dir() / "Presets"


@pytest.mark.skipif(not list_preset_files(REAL_DIR), reason="no launcher presets on this machine")
def test_real_presets_suggest_is_noop(tmp_path):
    for p in list_preset_files(REAL_DIR):
        shutil.copy2(p, tmp_path / p.name)
    lib = Library()
    import_presets(lib, tmp_path)
    lib = apply_suggestions(lib, suggest_sets(lib))
    plan = plan_generate(lib, ModCatalog.load(default_launcher_dir()), tmp_path)
    # Same mods everywhere; only the load order may differ.
    assert [i.config for i in plan.items if i.status not in ("unchanged", "reordered")] == []
    plan.include_reordered = False
    assert plan.to_write == []


def test_reorder_set_is_written_as_reordered(tmp_path):
    write_fixture(tmp_path)
    lib = Library()
    import_presets(lib, tmp_path)
    lib = apply_suggestions(lib, suggest_sets(lib, core_threshold=0.6))
    lib.sets["SOG"].mods.reverse()
    plan = plan_generate(lib, catalog(), tmp_path)
    status = {i.config: i.status for i in plan.items}
    assert status["SOG"] == status["SOG ASU"] == "reordered" and status["Cold War"] == "unchanged"
    plan.include_reordered = False
    assert plan.to_write == []
    plan.include_reordered = True
    apply_generate(plan, tmp_path, tmp_path / "bk")
    assert read_preset2(tmp_path / "SOG.preset2").mods == CORE + ["steam:101", "steam:100"]


def test_set_order_in_config_controls_load_order(tmp_path):
    write_fixture(tmp_path)
    lib = Library()
    import_presets(lib, tmp_path)
    lib = apply_suggestions(lib, suggest_sets(lib, core_threshold=0.6))
    lib.configs["SOG"].sets = ["SOG", "Core"]
    assert lib.resolve("SOG") == ["steam:100", "steam:101"] + CORE
