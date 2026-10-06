"""Mod Sets tab: sets | mods in the selected set | always-visible available mods."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox,
    QPlainTextEdit, QPushButton, QSizePolicy, QSplitter, QVBoxLayout, QWidget,
)

from ..model import ModSet
from .widgets import AvailableModsPanel, ModTable, ask_mod_ids


class SetsTab(QWidget):
    def __init__(self, main):
        super().__init__()
        self.main = main

        # --- left: set list ---
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
        ll.addWidget(QLabel("<b>Mod sets</b>"))
        ll.addWidget(self.list)
        ll.addLayout(btns)

        # --- middle: mods in the selected set ---
        self.set_title = QLabel()
        self.used_by = QLabel()
        # Long config lists must not force the pane wider; full list is in the tooltip.
        self.used_by.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.set_title.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.set_filter = QLineEdit(placeholderText="Filter mods in set…")
        self.set_filter.setClearButtonEnabled(True)
        self.set_mods = ModTable(drag=True, accept_drops=True, reorderable=True)
        self.set_mods.setToolTip("Drag rows to reorder (Ctrl+Up/Down) · Delete or drag to the right to remove · "
                                 "double-click opens the Workshop page")
        self.set_filter.textChanged.connect(self.set_mods.apply_filter)
        self.set_mods.dropped.connect(self._add_mods)
        self.set_mods.reordered.connect(self._reorder)
        # Keep the name readable in this narrow pane: status is shown by colour, both in the tooltip.
        self.set_mods.setColumnHidden(self.set_mods.col["Status"], True)
        self.set_mods.setColumnHidden(self.set_mods.col["ID"], True)
        self.set_mods.delete_pressed.connect(self._remove_mods)
        remove = QPushButton("Remove  ▶")
        remove.clicked.connect(lambda: self._remove_mods(self.set_mods.selected_ids()))
        paste = QPushButton("Paste ids / URLs…")
        paste.setToolTip("Add mods that aren't in the list (Workshop URLs, ids, local @mod paths)")
        paste.clicked.connect(self._paste)
        self.notes = QPlainTextEdit()
        self.notes.setPlaceholderText("Notes")
        self.notes.setMaximumHeight(50)
        self.notes.textChanged.connect(self._notes_changed)
        mb = QHBoxLayout()
        mb.addWidget(paste)
        mb.addStretch(1)
        mb.addWidget(remove)
        middle = QWidget()
        ml = QVBoxLayout(middle)
        ml.setContentsMargins(0, 0, 0, 0)
        ml.addWidget(self.set_title)
        ml.addWidget(self.used_by)
        ml.addWidget(self.set_filter)
        ml.addWidget(self.set_mods, 1)
        ml.addLayout(mb)
        ml.addWidget(self.notes)

        # --- right: available mods ---
        self.available = AvailableModsPanel()
        self.available.add_requested.connect(self._add_mods)
        self.available.remove_requested.connect(self._remove_mods)

        split = QSplitter()
        split.addWidget(left)
        split.addWidget(middle)
        split.addWidget(self.available)
        split.setStretchFactor(0, 2)
        split.setStretchFactor(1, 4)
        split.setStretchFactor(2, 5)
        split.setSizes([240, 440, 560])
        QVBoxLayout(self).addWidget(split)

    # --- helpers ----------------------------------------------------------
    def current_name(self) -> str | None:
        item = self.list.currentItem()
        return item.data(Qt.UserRole) if item else None

    def current(self) -> ModSet | None:
        name = self.current_name()
        return self.main.lib.sets.get(name) if name else None

    def _label(self, name: str) -> str:
        s = self.main.lib.sets[name]
        return f"{name}   ({len(s.mods)} mods · {len(self.main.lib.configs_using_set(name))} configs)"

    def reload(self, select: str | None = None) -> None:
        select = select or self.current_name()
        self.list.blockSignals(True)
        self.list.clear()
        for name in self.main.lib.sets:
            item = QListWidgetItem(self._label(name))
            item.setData(Qt.UserRole, name)
            self.list.addItem(item)
            if name == select:
                self.list.setCurrentItem(item)
        self.list.blockSignals(False)
        if self.list.currentItem() is None and self.list.count():
            self.list.setCurrentRow(0)
        self._show_current()

    def _usage(self) -> dict[str, list[str]]:
        usage: dict[str, list[str]] = {}
        for name, s in self.main.lib.sets.items():
            for m in s.mods:
                usage.setdefault(m, []).append(name)
        return usage

    def _show_current(self) -> None:
        name, s = self.current_name(), self.current()
        self.set_title.setText(f"<b>Mods in set: {name}</b> ({len(s.mods)})" if s else "<b>No set selected</b>")
        users = self.main.lib.configs_using_set(name) if s else []
        shown = ", ".join(users[:4]) + (f", … (+{len(users) - 4} more, hover to see all)" if len(users) > 4 else "")
        self.used_by.setText(f"Used by {len(users)} config(s): {shown or '—'}" if s else "")
        self.used_by.setToolTip("\n".join(users))
        self.set_mods.set_mods(s.mods if s else [], self.main.catalog)
        self.set_mods.setEnabled(s is not None)
        self.notes.blockSignals(True)
        self.notes.setPlainText(s.notes if s else "")
        self.notes.setEnabled(s is not None)
        self.notes.blockSignals(False)
        self._refresh_available()

    def _refresh_available(self) -> None:
        s = self.current()
        cat = self.main.catalog
        all_ids = sorted(self.main.all_known_mods(), key=lambda m: cat.name(m).lower())
        self.available.set_context(all_ids, s.mods if s else None, self._usage(), cat)

    def _after_mod_edit(self) -> None:
        item = self.list.currentItem()
        if item:
            item.setText(self._label(item.data(Qt.UserRole)))
        self._show_current()
        self.main.mark_dirty()

    # --- mod edits --------------------------------------------------------
    def _add_mods(self, ids: list[str]) -> None:
        s = self.current()
        if not s:
            return
        new = [m for m in ids if m not in s.mods]
        if new:
            s.mods.extend(new)
            self._after_mod_edit()

    def _remove_mods(self, ids: list[str]) -> None:
        s = self.current()
        drop = set(ids)
        if s and drop & set(s.mods):
            s.mods[:] = [m for m in s.mods if m not in drop]
            self._after_mod_edit()

    def _reorder(self, order: list[str]) -> None:
        s = self.current()
        if s and sorted(order) == sorted(s.mods) and order != s.mods:
            s.mods[:] = order
            self.set_mods.set_mods(s.mods, self.main.catalog)
            self.main.mark_dirty()

    def _paste(self) -> None:
        if self.current():
            self._add_mods(ask_mod_ids(self, f"Add mods to '{self.current_name()}'"))

    def _notes_changed(self) -> None:
        s = self.current()
        if s:
            s.notes = self.notes.toPlainText()
            self.main.mark_dirty()

    # --- set list actions -------------------------------------------------
    def _ask_name(self, title: str, default: str = "") -> str | None:
        name, ok = QInputDialog.getText(self, title, "Set name:", text=default)
        name = name.strip()
        if not ok or not name:
            return None
        if name in self.main.lib.sets:
            QMessageBox.warning(self, title, f"A set named '{name}' already exists.")
            return None
        return name

    def _created(self, name: str) -> None:
        self.main.mark_dirty(reload=True)
        self.reload(select=name)
        self.available.filter.setFocus()
        self.available.filter.selectAll()

    def _new(self) -> None:
        if name := self._ask_name("New set"):
            self.main.lib.sets[name] = ModSet()
            self._created(name)

    def _duplicate(self) -> None:
        cur = self.current_name()
        if cur and (name := self._ask_name("Duplicate set", f"{cur} copy")):
            src = self.main.lib.sets[cur]
            self.main.lib.sets[name] = ModSet(list(src.mods), src.notes)
            self._created(name)

    def _rename(self) -> None:
        cur = self.current_name()
        if cur and (name := self._ask_name("Rename set", cur)):
            self.main.lib.rename_set(cur, name)
            self.main.mark_dirty(reload=True)
            self.reload(select=name)

    def _delete(self) -> None:
        cur = self.current_name()
        if not cur:
            return
        users = self.main.lib.configs_using_set(cur)
        msg = f"Delete set '{cur}'?"
        if users:
            msg += f"\n\nIt is used by {len(users)} config(s), which will lose its mods:\n" + "\n".join(users)
        if QMessageBox.question(self, "Delete set", msg) == QMessageBox.Yes:
            self.main.lib.delete_set(cur)
            self.main.mark_dirty(reload=True)
            self.reload()
