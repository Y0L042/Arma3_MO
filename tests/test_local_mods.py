import json

from a3mo.launcher_data import ModCatalog, local_mod_id
from a3mo.model import Config, Library, ModSet
from a3mo.sync import find_moved_local_mods


def make_launcher(tmp_path, known):
    launcher = tmp_path / "launcher"
    launcher.mkdir()
    (launcher / "Local.json").write_text(json.dumps({"knownLocalMods": [str(p) for p in known]}), encoding="utf-8")
    return launcher


def test_local_mod_id_matches_launcher_format():
    assert local_mod_id("E:\\vlamf\\Documents\\Arma 3\\MyMods\\ScriptMenu\\@ScriptMenu") == \
        "local:E:\\VLAMF\\DOCUMENTS\\ARMA 3\\MYMODS\\SCRIPTMENU\\@SCRIPTMENU\\"


def test_local_json_plain_paths_and_unknown_local_mods(tmp_path):
    mymods = tmp_path / "MyMods"
    known = mymods / "ScriptMenu" / "@ScriptMenu"
    other = mymods / "UberPilot" / "@UberPilot"
    known.mkdir(parents=True)
    other.mkdir(parents=True)
    cat = ModCatalog.load(make_launcher(tmp_path, [known]))
    mid = local_mod_id(str(known))
    assert cat.installed(mid) and cat.name(mid) == "@ScriptMenu"
    assert local_mod_id(str(other)) in cat.local_folders
    assert cat.installed(local_mod_id(str(other)))  # folder exists


def test_moved_local_mods_are_relinked(tmp_path):
    mymods = tmp_path / "MyMods"
    known = mymods / "ScriptMenu" / "@ScriptMenu"
    other = mymods / "UberPilot" / "@UberPilot"
    known.mkdir(parents=True)
    other.mkdir(parents=True)
    cat = ModCatalog.load(make_launcher(tmp_path, [known]))
    old_known = "local:Z:\\GONE\\MYMODS\\SCRIPTMENU\\@SCRIPTMENU\\"
    old_other = "local:Z:\\GONE\\MYMODS\\UBERPILOT\\@UBERPILOT\\"
    lost = "local:Z:\\GONE\\MYMODS\\NOWHERE\\@NOWHERE\\"
    moved = find_moved_local_mods([old_known, old_other, lost, "steam:1"], cat)
    assert moved == {old_known: local_mod_id(str(known)), old_other: local_mod_id(str(other))}

    lib = Library(sets={"S": ModSet(["steam:1", old_known, lost])},
                  configs={"C": Config(add=[old_other, local_mod_id(str(other))], exclude=[old_known])})
    lib.replace_mods(moved)
    assert lib.sets["S"].mods == ["steam:1", local_mod_id(str(known)), lost]
    assert lib.configs["C"].add == [local_mod_id(str(other))]  # de-duplicated
    assert lib.configs["C"].exclude == [local_mod_id(str(known))]
