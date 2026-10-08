"""Configs tab: compose a preset from sets + added mods − excluded mods."""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QBrush
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QGridLayout, QGroupBox, QHBoxLayout, QInputDialog, QLabel, QListWidget,
    QListWidgetItem, QMessageBox, QPushButton, QSplitter, QTabWidget, QVBoxLayout, QWidget,
)

from ..model import Config
from ..sync import check_issues
from .widgets import DLC_NAMES, WARN_COLOR, AvailableModsPanel, ModListEditor, ModTable, TagFilterButton


class ConfigsTab(QWidget):
    def __init__(self, main):
        super().__init__()
        self.main = main

        # --- left: config list ---
        self.list = QListWidget()
        self.list.currentItemChanged.connect(lambda *_: self._show_current())
        btns = QHBoxLayout()
        for text, fn in (("New", self._new), ("Rename", self._rename), ("Duplicate", self._duplicate),
                         ("Delete", self._delete)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            btns.addWidget(b)
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.addWidget(QLabel("<b>Configs</b> (one launcher preset each)"))
        ll.addWidget(self.list)
        ll.addLayout(btns)

        # --- right: composition ---
        self.sets = QListWidget()
        self.sets.setDragDropMode(QAbstractItemView.InternalMove)
        self.sets.setDefaultDropAction(Qt.MoveAction)
        self.sets.setToolTip("Tick sets to include · drag to change their order in the preset")
        self.sets.itemChanged.connect(self._set_toggled)
        # Internal moves arrive as model row moves; re-read the order once the move settles.
        self.sets.model().rowsMoved.connect(lambda *_: QTimer.singleShot(0, self._sets_reordered))
        sets_box = QGroupBox("Included sets (drag to order)")
        QVBoxLayout(sets_box).addWidget(self.sets)

        self.dlc_boxes: dict[int, QCheckBox] = {}
        dlc_box = QGroupBox("Creator DLC / DLC to load")
        grid = QGridLayout(dlc_box)
        for i, (appid, name) in enumerate(DLC_NAMES.items()):
            cb = QCheckBox(name)
            cb.toggled.connect(self._dlcs_changed)
            self.dlc_boxes[appid] = cb
            grid.addWidget(cb, i // 2, i % 2)
        self.extra_dlcs = QLabel()
        grid.addWidget(self.extra_dlcs, len(DLC_NAMES) // 2 + 1, 0, 1, 2)

        top = QHBoxLayout()
        top.addWidget(sets_box, 1)
        top.addWidget(dlc_box, 1)

        self.add = ModListEditor("Extra mods (only in this config) — drag to reorder", reorderable=True,
                                 allow_paste=True, before_add=self._unexclude)
        self.add.changed.connect(self._edited)
        self.add_avail = AvailableModsPanel(target="config", hide_text="Hide mods already in config")
        self.add_avail.add_requested.connect(self.add.add_ids)
        self.add_avail.remove_requested.connect(self.add.remove_ids)

        self.exclude = ModListEditor("Excluded mods (removed from included sets)")
        self.exclude.changed.connect(self._edited)
        self.exclude_avail = AvailableModsPanel(
            target="exclusions", title="Mods from included sets", add_text="◀  Exclude",
            hide_text="Hide already excluded", show_unassigned=False)
        self.exclude_avail.add_requested.connect(self.exclude.add_ids)
        self.exclude_avail.remove_requested.connect(self.exclude.remove_ids)

        self.summary = QLabel()
        self.resolved = ModTable(extra_header="Source", numbered=True)
        self.resolved.setToolTip("Final load order: included sets in order, then extra mods. "
                                 "Reorder within the Mod Sets tab, the Extra mods tab, or by dragging sets above.")
        rm = QPushButton("Remove selected from config")
        rm.setToolTip("Removes from 'Extra mods', or excludes if it comes from a set")
        rm.clicked.connect(self._remove_resolved)
        mv = QPushButton("Move selected to set…")
        mv.setToolTip("Moves extra mods into a shared set (which also adds them to every config using that set)")
        mv.clicked.connect(self._move_to_set)
        self.resolved_tag_filter = TagFilterButton()
        self.resolved_tag_filter.changed.connect(self.resolved.set_tag_filter)
        resolved_page = QWidget()
        rl = QVBoxLayout(resolved_page)
        top_row = QHBoxLayout()
        top_row.addWidget(self.summary, 1)
        top_row.addWidget(self.resolved_tag_filter)
        rl.addLayout(top_row)
        rl.addWidget(self.resolved, 1)
        rb = QHBoxLayout()
        rb.addStretch(1)
        rb.addWidget(mv)
        rb.addWidget(rm)
        rl.addLayout(rb)

        self.pages = QTabWidget()
        self.pages.addTab(resolved_page, "Resulting preset")
        for editor, panel, label in ((self.add, self.add_avail, "Extra mods"),
                                     (self.exclude, self.exclude_avail, "Excluded")):
            page = QSplitter()
            page.addWidget(editor)
            page.addWidget(panel)
            page.setSizes([450, 450])
            page.setChildrenCollapsible(False)
            self.pages.addTab(page, label)

        right = QWidget()
        r = QVBoxLayout(right)
        r.setContentsMargins(0, 0, 0, 0)
        r.addLayout(top)
        r.addWidget(self.pages, 1)

        split = QSplitter()
        split.addWidget(left)
        split.addWidget(right)
        split.setStretchFactor(1, 3)
        QVBoxLayout(self).addWidget(split)

    # --- state ------------------------------------------------------------
    def current_name(self) -> str | None:
        item = self.list.currentItem()
        return item.data(Qt.UserRole) if item else None

    def current(self) -> Config | None:
        name = self.current_name()
        return self.main.lib.configs.get(name) if name else None

    def _set_mods_of_current(self) -> list[str]:
        cfg = self.current()
        if not cfg:
            return []
        out = []
        for s in cfg.sets:
            out.extend(self.main.lib.sets.get(s).mods if s in self.main.lib.sets else [])
        return list(dict.fromkeys(out))

    def _label(self, name: str) -> tuple[str, bool]:
        mods = self.main.lib.resolve(name)
        missing, deps = check_issues(mods, self.main.catalog)
        bad = bool(missing or deps)
        return f"{'⚠ ' if bad else ''}{name}   ({len(mods)})", bad

    def reload(self, select: str | None = None) -> None:
        select = select or self.current_name()
        self.list.blockSignals(True)
        self.list.clear()
        for name in self.main.lib.configs:
            text, bad = self._label(name)
            item = QListWidgetItem(text)
            item.setData(Qt.UserRole, name)
            if bad:
                item.setForeground(QBrush(WARN_COLOR))
                item.setToolTip("Some mods are not installed or have missing dependencies")
            self.list.addItem(item)
            if name == select:
                self.list.setCurrentItem(item)
        self.list.blockSignals(False)
        if self.list.currentItem() is None and self.list.count():
            self.list.setCurrentRow(0)
        self._show_current()

    def _show_current(self) -> None:
        cfg = self.current()
        lib = self.main.lib
        self.sets.blockSignals(True)
        self.sets.clear()
        if cfg:
            # Included sets first, in load order; the rest after in library order.
            names = [n for n in cfg.sets if n in lib.sets] + [n for n in lib.sets if n not in cfg.sets]
            for name in names:
                s = lib.sets[name]
                item = QListWidgetItem(f"{name}  ({len(s.mods)})")
                item.setData(Qt.UserRole, name)
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                item.setCheckState(Qt.Checked if name in cfg.sets else Qt.Unchecked)
                self.sets.addItem(item)
        self.sets.blockSignals(False)
        for appid, cb in self.dlc_boxes.items():
            cb.blockSignals(True)
            cb.setChecked(bool(cfg) and appid in cfg.dlcs)
            cb.setEnabled(cfg is not None)
            cb.blockSignals(False)
        unknown = [str(d) for d in (cfg.dlcs if cfg else []) if d not in DLC_NAMES]
        self.extra_dlcs.setText(f"Other app ids: {', '.join(unknown)}" if unknown else "")
        self.add.bind(cfg.add if cfg else None, self.main.catalog)
        self.exclude.bind(cfg.exclude if cfg else None, self.main.catalog)
        self._refresh_resolved()

    def _refresh_available(self) -> None:
        cfg, lib, cat = self.current(), self.main.lib, self.main.catalog
        usage: dict[str, list[str]] = {}
        for name, s in lib.sets.items():
            for m in s.mods:
                usage.setdefault(m, []).append(name)
        by_name = lambda ids: sorted(ids, key=lambda m: cat.name(m).lower())  # noqa: E731
        in_config = (set(lib.resolve(self.current_name())) | set(cfg.add)) if cfg else None
        self.add_avail.set_context(by_name(self.main.all_known_mods()), in_config, usage, cat)
        self.exclude_avail.set_context(by_name(self._set_mods_of_current()), cfg.exclude if cfg else None, usage, cat)

    def _unexclude(self, ids: list[str]) -> None:
        """A mod added as an extra must not stay excluded (exclude would win)."""
        cfg = self.current()
        if cfg and set(ids) & set(cfg.exclude):
            cfg.exclude[:] = [m for m in cfg.exclude if m not in set(ids)]
            self.exclude.refresh()

    def _refresh_resolved(self) -> None:
        cfg = self.current()
        self._refresh_available()
        if not cfg:
            self.resolved.set_mods([], self.main.catalog)
            self.resolved_tag_filter.set_mods([], self.main.catalog)
            self.summary.setText("")
            return
        lib, cat = self.main.lib, self.main.catalog
        mods = lib.resolve(self.current_name())
        source = {}
        for s in cfg.sets:
            for m in lib.sets.get(s).mods if s in lib.sets else []:
                source.setdefault(m, s)
        for m in cfg.add:
            source.setdefault(m, "extra")
        missing, deps = check_issues(mods, cat)
        warn = {m: "needs " + ", ".join(cat.name(d) for d in ds) for m, ds in deps.items()}
        self.resolved.set_mods(mods, cat, extra=source, warn=warn)
        self.resolved_tag_filter.set_mods(mods, cat)
        parts = [f"<b>{len(mods)}</b> mods"]
        if missing:
            parts.append(f"<span style='color:{WARN_COLOR.name()}'>{len(missing)} not installed</span>")
        if deps:
            parts.append(f"<span style='color:{WARN_COLOR.name()}'>{len(deps)} with missing dependencies</span>")
        if cfg.exclude:
            parts.append(f"{len(cfg.exclude)} excluded")
        self.summary.setText(" · ".join(parts))
        self.pages.setTabText(1, f"Extra mods ({len(cfg.add)})")
        self.pages.setTabText(2, f"Excluded ({len(cfg.exclude)})")

    def _update_list_label(self) -> None:
        item = self.list.currentItem()
        if item:
            text, bad = self._label(item.data(Qt.UserRole))
            item.setText(text)
            item.setForeground(QBrush(WARN_COLOR) if bad else self.list.palette().text())

    def _edited(self) -> None:
        self._refresh_resolved()
        self._update_list_label()
        self.main.mark_dirty()

    # --- composition edits -----------------------------------------------
    def _sets_reordered(self) -> None:
        cfg = self.current()
        if not cfg:
            return
        order = [self.sets.item(i).data(Qt.UserRole) for i in range(self.sets.count())
                 if self.sets.item(i).checkState() == Qt.Checked]
        if order != cfg.sets:
            cfg.sets = order
            self._edited()

    def _set_toggled(self, _item) -> None:
        cfg = self.current()
        if not cfg:
            return
        cfg.sets = [self.sets.item(i).data(Qt.UserRole) for i in range(self.sets.count())
                    if self.sets.item(i).checkState() == Qt.Checked]
        self._edited()

    def _dlcs_changed(self) -> None:
        cfg = self.current()
        if not cfg:
            return
        known = [a for a, cb in self.dlc_boxes.items() if cb.isChecked()]
        cfg.dlcs = [d for d in cfg.dlcs if d not in DLC_NAMES] + known
        self.main.mark_dirty()

    def _remove_resolved(self) -> None:
        cfg = self.current()
        ids = self.resolved.selected_ids()
        if not cfg or not ids:
            return
        from_sets = set(self._set_mods_of_current())
        for m in ids:
            if m in cfg.add:
                cfg.add.remove(m)
            if m in from_sets and m not in cfg.exclude:
                cfg.exclude.append(m)
        self.add.refresh()
        self.exclude.refresh()
        self._edited()

    def _move_to_set(self) -> None:
        cfg = self.current()
        ids = [m for m in self.resolved.selected_ids() if cfg and m in cfg.add]
        lib = self.main.lib
        if not ids:
            QMessageBox.information(self, "Move to set", "Select one or more mods whose source is 'extra'.")
            return
        if not lib.sets:
            QMessageBox.information(self, "Move to set", "Create a set first (Mod Sets tab).")
            return
        name, ok = QInputDialog.getItem(self, "Move to set", f"Move {len(ids)} mod(s) into set:",
                                        list(lib.sets), 0, False)
        if not ok:
            return
        others = [c for c in lib.configs_using_set(name) if c != self.current_name()]
        if others and QMessageBox.question(
            self, "Move to set",
            f"Set '{name}' is also used by {len(others)} other config(s):\n" + "\n".join(others)
            + "\n\nThey will get these mods too. Continue?") != QMessageBox.Yes:
            return
        target = lib.sets[name].mods
        target.extend(m for m in ids if m not in target)
        cfg.add[:] = [m for m in cfg.add if m not in ids]
        if name not in cfg.sets:
            cfg.sets.append(name)
        self.main.mark_dirty(reload=True)

    # --- config list actions ----------------------------------------------
    def _ask_name(self, title: str, default: str = "") -> str | None:
        name, ok = QInputDialog.getText(self, title, "Config / preset name:", text=default)
        name = name.strip()
        if not ok or not name:
            return None
        if any(c in name for c in '<>:"/\\|?*'):
            QMessageBox.warning(self, title, "Name can't contain any of  < > : \" / \\ | ? *")
            return None
        if name in self.main.lib.configs:
            QMessageBox.warning(self, title, f"A config named '{name}' already exists.")
            return None
        return name

    def _new(self) -> None:
        if name := self._ask_name("New config"):
            self.main.lib.configs[name] = Config()
            self.main.mark_dirty(reload=True)
            self.reload(select=name)

    def _duplicate(self) -> None:
        cur = self.current_name()
        if cur and (name := self._ask_name("Duplicate config", f"{cur} copy")):
            src = self.main.lib.configs[cur]
            self.main.lib.configs[name] = Config(list(src.sets), list(src.add), list(src.exclude),
                                                 list(src.dlcs), src.notes)
            self.main.mark_dirty(reload=True)
            self.reload(select=name)

    def _rename(self) -> None:
        cur = self.current_name()
        if cur and (name := self._ask_name("Rename config", cur)):
            self.main.lib.rename_config(cur, name)
            self.main.mark_dirty(reload=True)
            self.reload(select=name)
            QMessageBox.information(self, "Rename config",
                                    f"On next Generate, '{name}.preset2' is created.\n"
                                    f"The old '{cur}.preset2' is left in place; delete it in the launcher if unwanted.")

    def _delete(self) -> None:
        cur = self.current_name()
        if cur and QMessageBox.question(
                self, "Delete config",
                f"Delete config '{cur}'?\n\nThe launcher preset file is not deleted.") == QMessageBox.Yes:
            del self.main.lib.configs[cur]
            self.main.mark_dirty(reload=True)
            self.reload()
