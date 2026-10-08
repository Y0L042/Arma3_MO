import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtWidgets = pytest.importorskip("PySide6.QtWidgets")
from PySide6.QtCore import QMimeData, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QDropEvent  # noqa: E402

from a3mo.gui.widgets import ModTable  # noqa: E402
from a3mo.launcher_data import ModCatalog, ModInfo  # noqa: E402

IDS = ["steam:1", "steam:2", "steam:3", "steam:4"]


@pytest.fixture(scope="module")
def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


@pytest.fixture
def table(app):
    cat = ModCatalog({m: ModInfo(m, f"Mod {chr(68 - i)}", True) for i, m in enumerate(IDS)})  # D, C, B, A
    t = ModTable(reorderable=True)
    t.resize(400, 300)
    t.show()
    t.set_mods(IDS, cat)
    got = []
    t.reordered.connect(lambda order: (got.append(order), t.set_mods(order, cat)))
    return t, got


def select(t, *ids):
    t.clearSelection()
    for r in range(t.rowCount()):
        if t.item(r, 0).data(Qt.UserRole) in ids:
            t.selectionModel().select(t.model().index(r, 0), t.selectionModel().SelectionFlag.Select
                                      | t.selectionModel().SelectionFlag.Rows)


def test_number_column_and_default_order(table):
    t, _ = table
    assert [t.item(r, t.col["#"]).data(Qt.DisplayRole) for r in range(4)] == [1, 2, 3, 4]
    assert t.visible_ids() == IDS and t.in_order_view()


def test_move_up_down(table):
    t, got = table
    select(t, "steam:3")
    t.move_selected(-1)
    assert got[-1] == ["steam:1", "steam:3", "steam:2", "steam:4"]
    t.move_selected(-1)
    t.move_selected(-1)  # already at top: no-op
    assert got[-1] == ["steam:3", "steam:1", "steam:2", "steam:4"] and len(got) == 2


def test_drop_inside_table(table):
    t, got = table
    select(t, "steam:1", "steam:2")
    rect = t.visualRect(t.model().index(3, 1))  # lower half of the last row -> after it
    ev = QDropEvent(QPointF(rect.center().x(), rect.bottom() - 2), Qt.MoveAction, QMimeData(),
                    Qt.LeftButton, Qt.NoModifier)
    # QDropEvent.source() is only set by a real drag; patch it for the test.
    ev.source = lambda: t
    t.dropEvent(ev)
    assert got[-1] == ["steam:3", "steam:4", "steam:1", "steam:2"]


def test_no_reorder_when_sorted_by_name_or_filtered(table):
    t, got = table
    t.sortByColumn(t.col["Name"], Qt.AscendingOrder)
    select(t, "steam:2")
    t.move_selected(1)
    t.sortByColumn(t.col["#"], Qt.AscendingOrder)
    t.apply_filter("Mod")
    t.move_selected(1)
    assert got == []
    t.apply_filter("")
    t.move_selected(1)
    assert got[-1] == ["steam:1", "steam:3", "steam:2", "steam:4"]


def test_configs_tab_set_order(app, tmp_path):
    from a3mo.gui.app import MainWindow
    from a3mo.model import Config, Library, ModSet
    lib = Library()
    lib.settings.launcher_dir = str(tmp_path)
    lib.sets = {"A": ModSet(["steam:1"]), "B": ModSet(["steam:2"]), "C": ModSet(["steam:3"])}
    lib.configs["X"] = Config(sets=["B", "A"])
    lib.save(tmp_path / "lib.json")
    w = MainWindow(tmp_path / "lib.json")
    tab = w.configs_tab
    names = [tab.sets.item(i).data(Qt.UserRole) for i in range(tab.sets.count())]
    assert names == ["B", "A", "C"]  # included first, in config order
    tab.sets.model().moveRow(tab.sets.model().index(0, 0).parent(), 0, tab.sets.model().index(0, 0).parent(), 2)
    app.processEvents()
    assert w.lib.configs["X"].sets == ["A", "B"]
    assert w.lib.resolve("X") == ["steam:1", "steam:2"] and w.dirty


def test_configs_tab_available_panels(app, tmp_path):
    from a3mo.gui.app import MainWindow
    from a3mo.model import Config, Library, ModSet
    lib = Library()
    lib.settings.launcher_dir = str(tmp_path)
    lib.sets = {"A": ModSet(["steam:1", "steam:2"]), "B": ModSet(["steam:3"])}
    lib.configs["X"] = Config(sets=["A"], add=["steam:9"], exclude=["steam:2"])
    lib.save(tmp_path / "lib.json")
    w = MainWindow(tmp_path / "lib.json")
    tab = w.configs_tab
    cfg = w.lib.configs["X"]

    # Extra mods panel: everything known, minus what the config already has.
    shown = set(tab.add_avail.table.visible_ids())
    assert {"steam:2", "steam:3"} <= shown and not ({"steam:1", "steam:9"} & shown)
    # Exclude panel: only mods from included sets, minus already excluded.
    assert tab.exclude_avail.table.visible_ids() == ["steam:1"]

    tab.add_avail.add_requested.emit(["steam:3"])
    assert cfg.add == ["steam:9", "steam:3"] and "steam:3" not in tab.add_avail.table.visible_ids()

    # Adding an excluded mod as an extra un-excludes it.
    tab.add_avail.add_requested.emit(["steam:2"])
    assert "steam:2" in cfg.add and cfg.exclude == [] and "steam:2" in w.lib.resolve("X")

    tab.exclude_avail.add_requested.emit(["steam:1"])
    assert cfg.exclude == ["steam:1"] and "steam:1" not in w.lib.resolve("X")
    assert "steam:1" in tab.add_avail.table.visible_ids()  # excluded -> no longer in the config

    # Dragging back onto the panel removes.
    tab.exclude_avail.remove_requested.emit(["steam:1"])
    tab.add_avail.remove_requested.emit(["steam:3"])
    assert cfg.exclude == [] and cfg.add == ["steam:9", "steam:2"] and w.dirty


def test_tag_filter(app):
    from a3mo.gui.widgets import UNTAGGED, AvailableModsPanel
    cat = ModCatalog({m: ModInfo(m, f"Mod {m[-1]}", True) for m in IDS})
    cat.apply_workshop(tags={"steam:1": ["Terrain"], "steam:2": ["Weapon", "Terrain"], "steam:3": ["Sound"]})
    t = ModTable(reorderable=True, show_tags=True)
    t.set_mods(IDS, cat)
    assert t.item(1, t.col["Tags"]).text() == "Weapon, Terrain"
    t.set_tag_filter({"Terrain"})
    assert t.visible_ids() == ["steam:1", "steam:2"] and not t.in_order_view()
    t.set_tag_filter({"Sound", UNTAGGED})
    assert t.visible_ids() == ["steam:3", "steam:4"]
    t.apply_filter("mod 4")
    assert t.visible_ids() == ["steam:4"]
    t.apply_filter("")
    t.set_tag_filter(set())
    assert t.visible_ids() == IDS and t.in_order_view()
    t.apply_filter("weap")  # text filter also matches tags
    assert t.visible_ids() == ["steam:2"]

    panel = AvailableModsPanel()
    panel.set_context(IDS, [], {}, cat)
    menu = {a.data(): a for a in panel.tag_filter.menu().actions() if a.isCheckable()}
    assert set(menu) == {"Terrain", "Weapon", "Sound", UNTAGGED}
    menu["Weapon"].setChecked(True)
    assert panel.table.visible_ids() == ["steam:2"] and panel.count.text() == "1 shown"
    panel.refresh()  # rebuilding the menu keeps the selection
    assert panel.tag_filter.selected() == {"Weapon"} and panel.table.visible_ids() == ["steam:2"]
    panel.tag_filter.clear()
    assert len(panel.table.visible_ids()) == 4
