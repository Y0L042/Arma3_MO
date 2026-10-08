import io
import json
import urllib.parse

from a3mo import workshop
from a3mo.launcher_data import ModCatalog, ModInfo
from a3mo.workshop import WorkshopCache, fetch_details, type_tags


def test_type_tags_drops_noise():
    assert type_tags(["Mod", "Terrain", "Apex", "Tag Review", "Weapon"]) == ["Terrain", "Weapon"]


def test_fetch_details_batches_and_parses(monkeypatch):
    calls = []

    def fake_urlopen(url, data, timeout):
        form = urllib.parse.parse_qs(data.decode())
        ids = [form[f"publishedfileids[{i}]"][0] for i in range(int(form["itemcount"][0]))]
        calls.append(ids)
        items = [{"publishedfileid": n, "result": 9 if n == "5" else 1, "title": f"Mod {n}",
                  "tags": [{"tag": "Mod"}, {"tag": f"T{n}"}]} for n in ids]
        return io.BytesIO(json.dumps({"response": {"publishedfiledetails": items}}).encode())

    monkeypatch.setattr(workshop.urllib.request, "urlopen", fake_urlopen)
    ids = [f"steam:{i}" for i in range(150)] + ["local:C:\\X\\"]
    details = fetch_details(ids)
    assert [len(c) for c in calls] == [100, 50]
    assert details["steam:7"] == {"title": "Mod 7", "tags": ["Mod", "T7"]}
    assert "steam:5" not in details and len(details) == 149


def test_workshop_cache_roundtrip(tmp_path):
    path = tmp_path / "cache.json"
    cache = WorkshopCache.load(path)  # missing file -> empty
    assert cache.missing(["steam:1", "steam:2", "local:C:\\X\\"]) == ["steam:1", "steam:2"]
    cache.update({"steam:1": {"title": "Map", "tags": ["Mod", "Terrain"]}, "steam:2": {}})
    cache.mods["steam:4"] = {"tags": ["Weapon"], "fetched": 0}  # older cache format: no title
    cache.save()
    again = WorkshopCache.load(path)
    assert again.missing(["steam:1", "steam:2", "steam:3", "steam:4"]) == ["steam:3", "steam:4"]
    assert again.tags("steam:1") == ["Terrain"] and again.all()["steam:2"] == []
    assert again.titles() == {"steam:1": "Map"}


def test_catalog_workshop_titles_do_not_add_mods():
    cat = ModCatalog({"steam:1": ModInfo("steam:1", "Launcher name", True)})
    cat.apply_workshop(titles={"steam:1": "Workshop name", "steam:2": "Unsubscribed mod"},
                       tags={"steam:2": ["Terrain"]})
    assert list(cat.mods) == ["steam:1"]  # cached entries don't become "known" mods
    assert cat.name("steam:1") == "Launcher name"  # the launcher's name wins
    assert cat.name("steam:2") == "Unsubscribed mod" and cat.tags("steam:2") == ["Terrain"]
    assert not cat.installed("steam:2") and cat.name("steam:3") == "steam:3"


def test_catalog_tag_counts():
    cat = ModCatalog()
    cat.apply_workshop(tags={"steam:1": ["Terrain"], "steam:2": ["Weapon", "Terrain"], "steam:3": ["Sound"]})
    assert cat.tags("steam:2") == ["Weapon", "Terrain"]
    assert list(cat.tag_counts(["steam:1", "steam:2", "steam:3", "steam:4"]).items()) == \
        [("Terrain", 2), ("Sound", 1), ("Weapon", 1)]


def test_catalog_finds_workshop_mods_missing_from_steam_json(tmp_path):
    ws = tmp_path / "Arma 3" / "!Workshop"
    for folder, meta in (("@Known", 'publishedid = 1;\nname = "Known";'),
                         ("@UMB Colombia", 'protocol = 1;\npublishedid = 2266710560;\nname = "UMB Colombia";'),
                         ("@Stale", 'publishedid = 3;\nname = "Stale";'),
                         ("@NoMeta", None)):
        (ws / folder).mkdir(parents=True)
        if meta:
            (ws / folder / "meta.cpp").write_text(meta, encoding="utf-8")
    launcher = tmp_path / "launcher"
    launcher.mkdir()
    ext = [{"Id": "steam:1", "DisplayName": "Known", "IsInstalled": True, "ExtensionPath": str(ws / "@Known")},
           {"Id": "steam:3", "DisplayName": "Stale", "IsInstalled": False, "ExtensionPath": ""}]
    (launcher / "Steam.json").write_text(json.dumps({"Extensions": ext}), encoding="utf-8")
    cat = ModCatalog.load(launcher)
    assert set(cat.mods) == {"steam:1", "steam:2266710560", "steam:3"}
    umb = cat.info("steam:2266710560")
    assert umb.name == "UMB Colombia" and umb.installed and umb.url.endswith("id=2266710560")
    assert cat.installed("steam:3")  # on disk although Steam.json still says not installed
