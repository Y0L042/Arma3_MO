import pytest

from a3mo.launcher_data import default_launcher_dir
from a3mo.preset_io import Preset, list_preset_files, read_preset2, serialize_preset2, write_preset2

REAL = list_preset_files(default_launcher_dir() / "Presets")


def test_roundtrip_synthetic(tmp_path):
    p = Preset("x", ["steam:1", r"local:E:\A&B\@MOD\\"], [1042220], "2026-01-01T00:00:00.0000000+02:00")
    write_preset2(tmp_path / "x.preset2", p)
    q = read_preset2(tmp_path / "x.preset2")
    assert (q.mods, q.dlcs, q.last_update) == (p.mods, p.dlcs, p.last_update)


def test_empty_sections_self_close():
    data = serialize_preset2(Preset("x", [], [], "t"))
    assert data.startswith(b"\xef\xbb\xbf<?xml")
    assert b"<published-ids />" in data and b"<dlcs-appids />" in data
    assert not data.endswith(b"\n")


@pytest.mark.skipif(not REAL, reason="no launcher presets on this machine")
@pytest.mark.parametrize("path", REAL, ids=lambda p: p.name)
def test_roundtrip_real_bytes(path):
    assert serialize_preset2(read_preset2(path)) == path.read_bytes()
