from a3mo.model import Config, Library, ModSet


def make_lib():
    lib = Library()
    lib.sets["Core"] = ModSet(["a", "b", "c"])
    lib.sets["Maps"] = ModSet(["m1", "b"])
    lib.configs["X"] = Config(sets=["Core", "Maps"], add=["z", "a"], exclude=["c"])
    return lib


def test_resolve_order_dedupe_exclude():
    assert make_lib().resolve("X") == ["a", "b", "m1", "z"]


def test_missing_set_ignored():
    lib = make_lib()
    lib.configs["X"].sets.append("Nope")
    assert lib.resolve("X") == ["a", "b", "m1", "z"]


def test_rename_and_delete_set():
    lib = make_lib()
    lib.rename_set("Core", "Base")
    assert lib.configs["X"].sets == ["Base", "Maps"]
    lib.delete_set("Base")
    assert lib.configs["X"].sets == ["Maps"]


def test_save_load(tmp_path):
    lib = make_lib()
    lib.save(tmp_path / "lib.json")
    assert Library.load(tmp_path / "lib.json").to_dict() == lib.to_dict()
