"""Reusable widgets: mod table, mod picker dialog, editable mod list."""
from __future__ import annotations

import re
from typing import Callable

from PySide6.QtCore import QItemSelectionModel, Qt, QUrl, Signal
from PySide6.QtGui import QBrush, QColor, QCursor, QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QMenu, QToolTip, QDialog, QDialogButtonBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QPlainTextEdit, QPushButton, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

from ..launcher_data import ModCatalog

DLC_NAMES = {
    1021790: "Contact",
    1042220: "Global Mobilization",
    1175380: "Spearhead 1944",
    1227700: "S.O.G. Prairie Fire",
    1294440: "CSLA Iron Curtain",
    1681170: "Western Sahara",
    2647760: "Reaction Forces",
    2647830: "Expeditionary Forces",
}

WARN_COLOR = QColor("#d9822b")
ID_ROLE = Qt.UserRole


def parse_mod_ids(text: str) -> list[str]:
    """Accept workshop URLs, bare numbers, ``steam:N``, ``local:PATH`` or local @mod paths."""
    out = []
    for raw in text.splitlines():
        line = raw.strip().strip('"')
        if not line:
            continue
        if m := re.search(r"[?&]id=(\d+)", line):
            out.append(f"steam:{m.group(1)}")
        elif m := re.fullmatch(r"(?:steam:)?(\d+)", line):
            out.append(f"steam:{m.group(1)}")
        elif line.lower().startswith("local:") or re.match(r"^[A-Za-z]:[\\/]", line):
            path = line.split(":", 1)[1] if line.lower().startswith("local:") else line
            path = path.replace("/", "\\").upper()
            out.append("local:" + path.rstrip("\\") + "\\")
    return out


class ModTable(QTableWidget):
    """Read-only table of mods: [#] | Name | Status | [extra column] | ID.

    Emits ``activated`` (double-click / Enter), ``delete_pressed`` (Delete key) and
    ``dropped`` (ids dragged in from another ModTable). By default activating a row
    opens its Workshop page (``open_on_activate``).

    ``numbered`` adds a "#" column with each mod's position in the list. ``reorderable``
    (implies numbered) lets the user drag rows within the table, press Ctrl+Up/Down,
    or sort by name from the context menu; the new order is emitted via ``reordered``.
    Reordering needs the view sorted by "#" with no filter, so what you see is the
    real order.
    """

    activated = Signal(list)
    delete_pressed = Signal(list)
    dropped = Signal(list)
    reordered = Signal(list)

    def __init__(self, extra_header: str | None = None, parent=None, open_on_activate: bool = True,
                 drag: bool = False, accept_drops: bool = False, numbered: bool = False,
                 reorderable: bool = False):
        self.extra_header = extra_header
        self.reorderable = reorderable
        self.numbered = numbered or reorderable
        headers = (["#"] if self.numbered else []) + ["Name", "Status"] + ([extra_header] if extra_header else []) + ["ID"]
        self.col = {h: i for i, h in enumerate(headers)}
        super().__init__(0, len(headers), parent)
        self.setHorizontalHeaderLabels(headers)
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.setWordWrap(False)
        self.setTextElideMode(Qt.ElideRight)
        self.setStyleSheet("QTableWidget::item { padding: 0px 8px; }")
        self.verticalHeader().setVisible(False)
        self.verticalHeader().setDefaultSectionSize(self.fontMetrics().height() + 10)
        h = self.horizontalHeader()
        h.setStretchLastSection(False)
        h.setMinimumSectionSize(36)
        # Name takes the remaining width; long free-text columns (extra, ID) get a
        # fixed, user-resizable width so they can't squeeze the name column.
        h.setSectionResizeMode(self.col["Name"], QHeaderView.Stretch)
        h.setSectionResizeMode(self.col["Status"], QHeaderView.ResizeToContents)
        if self.numbered:
            h.setSectionResizeMode(self.col["#"], QHeaderView.Fixed)
            self.setColumnWidth(self.col["#"], self.fontMetrics().horizontalAdvance("9999") + 26)
        widths = {"ID": 150, extra_header: 130} if extra_header else {"ID": 150}
        for name, width in widths.items():
            h.setSectionResizeMode(self.col[name], QHeaderView.Interactive)
            self.setColumnWidth(self.col[name], width)
        self.setSortingEnabled(True)
        self.sortByColumn(self.col["#"] if self.numbered else self.col["Name"], Qt.AscendingOrder)
        self.setDragEnabled(drag or reorderable)
        self.setAcceptDrops(accept_drops or reorderable)
        if drag or accept_drops or reorderable:
            self.setDragDropMode(QAbstractItemView.DragDrop)
            self.setDefaultDropAction(Qt.CopyAction)
            self.setDropIndicatorShown(True)
        self._ids: list[str] = []
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._context_menu)
        if open_on_activate:
            self.setToolTip("Double-click to open the Workshop page")
            self.activated.connect(lambda ids: self._open_url(ids[0]) if ids else None)
        self.cellDoubleClicked.connect(lambda r, _c: self.activated.emit([self.item(r, 0).data(ID_ROLE)]))
        self._catalog: ModCatalog | None = None
        self._filter = ""

    def set_mods(self, ids: list[str], catalog: ModCatalog, extra: dict[str, str] | None = None,
                 warn: dict[str, str] | None = None) -> None:
        """``warn`` maps mod id -> extra warning text appended to the status column."""
        self._catalog = catalog
        self._ids = list(ids)
        selected = set(self.selected_ids())
        self.clearSelection()
        self.setSortingEnabled(False)
        self.setRowCount(len(ids))
        for row, mid in enumerate(ids):
            info = catalog.info(mid)
            status = "OK" if info.installed else "Not installed"
            if warn and mid in warn:
                status = warn[mid] if info.installed else f"{status}; {warn[mid]}"
            extra_text = (extra or {}).get(mid, "")
            cells = ([row + 1] if self.numbered else []) + [info.name, status] + \
                ([extra_text] if self.extra_header else []) + [mid]
            bad = not info.installed or bool(warn and mid in warn)
            tip = f"{info.name}\n{mid}\n{status}" + (f"\n{self.extra_header}: {extra_text}" if extra_text else "")
            if self.reorderable:
                tip += "\n\nDrag to reorder (Ctrl+Up/Down)"
            for col, value in enumerate(cells):
                item = QTableWidgetItem()
                item.setData(Qt.DisplayRole, value)  # ints sort numerically
                item.setData(ID_ROLE, mid)
                item.setToolTip(tip)
                if bad:
                    item.setForeground(QBrush(WARN_COLOR))
                self.setItem(row, col, item)
        self.setSortingEnabled(True)
        self.apply_filter(self._filter)
        sel = self.selectionModel()
        for r in range(self.rowCount()):
            if self.item(r, 0).data(ID_ROLE) in selected:
                sel.select(self.model().index(r, 0), QItemSelectionModel.Select | QItemSelectionModel.Rows)

    def apply_filter(self, text: str) -> None:
        self._filter = text
        t = text.lower()
        for r in range(self.rowCount()):
            hide = bool(t) and not any(t in self.item(r, c).text().lower() for c in range(self.columnCount())
                                       if c != self.col.get("#"))
            self.setRowHidden(r, hide)

    def visible_ids(self) -> list[str]:
        return [self.item(r, 0).data(ID_ROLE) for r in range(self.rowCount()) if not self.isRowHidden(r)]

    def selected_ids(self) -> list[str]:
        rows = sorted({i.row() for i in self.selectedIndexes() if not self.isRowHidden(i.row())})
        return [self.item(r, 0).data(ID_ROLE) for r in rows]

    def keyPressEvent(self, event) -> None:
        key, ctrl = event.key(), bool(event.modifiers() & Qt.ControlModifier)
        if key in (Qt.Key_Delete, Qt.Key_Backspace):
            self.delete_pressed.emit(self.selected_ids())
        elif key in (Qt.Key_Return, Qt.Key_Enter):
            self.activated.emit(self.selected_ids())
        elif ctrl and key in (Qt.Key_Up, Qt.Key_Down) and self.reorderable:
            self.move_selected(-1 if key == Qt.Key_Up else 1)
        else:
            super().keyPressEvent(event)

    # --- reordering ---------------------------------------------------------
    def in_order_view(self) -> bool:
        h = self.horizontalHeader()
        return (self.reorderable and not self._filter and h.sortIndicatorSection() == self.col["#"]
                and h.sortIndicatorOrder() == Qt.AscendingOrder)

    def _order_hint(self) -> None:
        QToolTip.showText(QCursor.pos(), "To reorder, sort by the # column (ascending) and clear the filter.", self)

    def move_selected(self, step: int) -> None:
        if not self.in_order_view():
            self._order_hint()
            return
        moving = set(self.selected_ids())
        order = list(self._ids)
        idxs = [i for i, m in enumerate(order) if m in moving]
        if not idxs or (step < 0 and idxs[0] == 0) or (step > 0 and idxs[-1] == len(order) - 1):
            return
        for i in (idxs if step < 0 else reversed(idxs)):
            order[i], order[i + step] = order[i + step], order[i]
        self.reordered.emit(order)

    def _move_to(self, moving: list[str], target: str | None, after: bool) -> None:
        if target in moving:
            return
        rest = [m for m in self._ids if m not in set(moving)]
        pos = len(rest) if target is None else rest.index(target) + (1 if after else 0)
        moving = [m for m in self._ids if m in set(moving)]  # keep their relative order
        new = rest[:pos] + moving + rest[pos:]
        if new != self._ids:
            self.reordered.emit(new)

    # Drag & drop. From another ModTable: payload is that table's selection (emits
    # ``dropped``). Within this table: reorder (emits ``reordered``).
    def dragEnterEvent(self, event) -> None:
        src = event.source()
        if src is self and self.reorderable:
            if self.in_order_view():
                event.accept()
            else:
                self._order_hint()
                event.ignore()
        elif self.acceptDrops() and isinstance(src, ModTable) and src is not self:
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event) -> None:
        if event.source() is self and self.reorderable and self.in_order_view():
            super().dragMoveEvent(event)  # draws the drop indicator line
            event.setDropAction(Qt.MoveAction)
            event.accept()
        else:
            self.dragEnterEvent(event)

    def dropEvent(self, event) -> None:
        src = event.source()
        if src is self and self.reorderable:
            event.setDropAction(Qt.IgnoreAction)  # we reorder the data ourselves
            event.accept()
            self.setState(QAbstractItemView.NoState)
            self.viewport().update()
            if self.in_order_view():
                pos = event.position().toPoint()
                index = self.indexAt(pos)
                if index.isValid():
                    target = self.item(index.row(), 0).data(ID_ROLE)
                    after = pos.y() > self.visualRect(index).center().y()
                else:
                    target, after = None, True
                self._move_to(self.selected_ids(), target, after)
        elif isinstance(src, ModTable) and src is not self:
            event.setDropAction(Qt.CopyAction)
            event.accept()
            self.dropped.emit(src.selected_ids())

    def _context_menu(self, pos) -> None:
        item = self.itemAt(pos)
        if not item or not self._catalog:
            return
        mid = item.data(ID_ROLE)
        menu = QMenu(self)
        menu.addAction("Open Workshop page", lambda: self._open_url(mid)).setEnabled(bool(self._catalog.info(mid).url))
        menu.addAction("Copy id(s)", lambda: QApplication.clipboard().setText("\n".join(self.selected_ids() or [mid])))
        if self.reorderable:
            menu.addSeparator()
            menu.addAction("Move up\tCtrl+Up", lambda: self.move_selected(-1))
            menu.addAction("Move down\tCtrl+Down", lambda: self.move_selected(1))
            menu.addAction("Move to top", lambda: self._move_to(self.selected_ids(), self._ids[0], False)
                           if self.in_order_view() else self._order_hint())
            menu.addAction("Move to bottom", lambda: self._move_to(self.selected_ids(), None, True)
                           if self.in_order_view() else self._order_hint())
            menu.addAction("Set order by name (A→Z)", lambda: self.reordered.emit(
                sorted(self._ids, key=lambda m: self._catalog.name(m).lower())))
            menu.addAction("Show in load order (sort by #)", lambda: self.sortByColumn(self.col["#"], Qt.AscendingOrder))
        menu.exec(self.viewport().mapToGlobal(pos))

    def _open_url(self, mid: str) -> None:
        if self._catalog and (url := self._catalog.info(mid).url):
            QDesktopServices.openUrl(QUrl(url))


class AvailableModsPanel(QWidget):
    """Always-visible list of all known mods, for quickly adding mods to a set."""

    add_requested = Signal(list)
    remove_requested = Signal(list)  # mods dragged back here from the set table

    def __init__(self, parent=None):
        super().__init__(parent)
        self.filter = QLineEdit(placeholderText="Filter available mods… (name, id, set)   Enter = add if one match")
        self.filter.setClearButtonEnabled(True)
        self.hide_in_set = QCheckBox("Hide mods already in set")
        self.hide_in_set.setChecked(True)
        self.installed_only = QCheckBox("Installed only")
        self.unassigned_only = QCheckBox("Not in any set")
        self.table = ModTable(extra_header="In sets", open_on_activate=False, drag=True, accept_drops=True)
        self.table.setToolTip("Double-click, Enter or drag onto the set to add")
        # Status is shown by colour and ID in the tooltip; hidden columns are still filterable.
        self.table.setColumnHidden(self.table.col["Status"], True)
        self.table.setColumnHidden(self.table.col["ID"], True)
        self.count = QLabel()
        add = QPushButton("◀  Add to set")
        add.clicked.connect(lambda: self._emit_add(self.table.selected_ids()))
        self.table.activated.connect(self._emit_add)
        self.table.dropped.connect(self.remove_requested)
        self.filter.textChanged.connect(self._filter_changed)
        self.filter.returnPressed.connect(self._enter_in_filter)
        for cb in (self.hide_in_set, self.installed_only, self.unassigned_only):
            cb.toggled.connect(self.refresh)

        opts = QHBoxLayout()
        for cb in (self.hide_in_set, self.installed_only, self.unassigned_only):
            opts.addWidget(cb)
        opts.addStretch(1)
        bottom = QHBoxLayout()
        bottom.addWidget(add)
        bottom.addWidget(self.count, 1)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(QLabel("<b>Available mods</b>"))
        lay.addWidget(self.filter)
        lay.addLayout(opts)
        lay.addWidget(self.table, 1)
        lay.addLayout(bottom)
        self._all: list[str] = []
        self._in_set: set[str] = set()
        self._usage: dict[str, list[str]] = {}
        self._catalog: ModCatalog | None = None
        self._active = False

    def set_context(self, all_ids: list[str], in_set: list[str] | None, usage: dict[str, list[str]],
                    catalog: ModCatalog) -> None:
        """``usage``: mod id -> names of sets containing it. ``in_set`` None means no set is selected."""
        self._all, self._usage, self._catalog = all_ids, usage, catalog
        self._active = in_set is not None
        self._in_set = set(in_set or [])
        self.refresh()

    def refresh(self) -> None:
        if self._catalog is None:
            return
        ids = [m for m in self._all
               if not (self.hide_in_set.isChecked() and m in self._in_set)
               and not (self.installed_only.isChecked() and not self._catalog.installed(m))
               and not (self.unassigned_only.isChecked() and self._usage.get(m))]
        self.table.set_mods(ids, self._catalog, extra={m: ", ".join(self._usage.get(m, [])) for m in ids})
        self._update_count()
        self.setEnabled(self._active)

    def _filter_changed(self, text: str) -> None:
        self.table.apply_filter(text)
        self._update_count()

    def _update_count(self) -> None:
        self.count.setText(f"{len(self.table.visible_ids())} shown")

    def _emit_add(self, ids: list[str]) -> None:
        ids = [m for m in ids if m not in self._in_set]
        if ids and self._active:
            self.add_requested.emit(ids)

    def _enter_in_filter(self) -> None:
        visible = self.table.visible_ids()
        if len(visible) == 1:
            self._emit_add(visible)
            self.filter.selectAll()
        elif visible:
            self.table.setFocus()
            self.table.selectRow(next(r for r in range(self.table.rowCount()) if not self.table.isRowHidden(r)))


class ModPickerDialog(QDialog):
    """Pick mods from the known catalog, or paste ids / Workshop URLs."""

    def __init__(self, catalog: ModCatalog, candidates: list[str], title="Add mods", parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(640, 560)
        self.filter = QLineEdit(placeholderText="Filter by name or id…")
        self.list = QListWidget()
        self.list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        for mid in sorted(candidates, key=lambda m: catalog.name(m).lower()):
            info = catalog.info(mid)
            item = QListWidgetItem(f"{info.name}   ({mid})" + ("" if info.installed else "   [not installed]"))
            item.setData(ID_ROLE, mid)
            if not info.installed:
                item.setForeground(QBrush(WARN_COLOR))
            self.list.addItem(item)
        self.paste = QPlainTextEdit()
        self.paste.setPlaceholderText("…or paste one per line: Workshop URL, workshop id, steam:ID, or local @mod path")
        self.paste.setMaximumHeight(90)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        self.filter.textChanged.connect(self._apply_filter)
        self.list.itemDoubleClicked.connect(lambda _: self.accept())

        lay = QVBoxLayout(self)
        lay.addWidget(self.filter)
        lay.addWidget(self.list, 1)
        lay.addWidget(self.paste)
        lay.addWidget(buttons)

    def _apply_filter(self, text: str) -> None:
        t = text.lower()
        for i in range(self.list.count()):
            item = self.list.item(i)
            item.setHidden(bool(t) and t not in item.text().lower())

    def result_ids(self) -> list[str]:
        ids = [i.data(ID_ROLE) for i in self.list.selectedItems() if not i.isHidden()]
        return ids + [m for m in parse_mod_ids(self.paste.toPlainText()) if m not in ids]


class ModListEditor(QWidget):
    """A titled ModTable bound to a mutable list of ids, with Add/Remove buttons."""

    changed = Signal()

    def __init__(self, title: str, candidates: Callable[[], list[str]], parent=None, reorderable: bool = False):
        super().__init__(parent)
        self._ids: list[str] | None = None
        self._catalog: ModCatalog | None = None
        self._candidates = candidates
        self.title = QLabel(f"<b>{title}</b>")
        self.table = ModTable(reorderable=reorderable)
        self.table.reordered.connect(self._reordered)
        self.table.delete_pressed.connect(lambda _ids: self._remove())
        self.add_btn = QPushButton("Add…")
        self.remove_btn = QPushButton("Remove")
        self.add_btn.clicked.connect(self._add)
        self.remove_btn.clicked.connect(self._remove)
        top = QHBoxLayout()
        top.addWidget(self.title)
        top.addStretch(1)
        top.addWidget(self.add_btn)
        top.addWidget(self.remove_btn)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addLayout(top)
        lay.addWidget(self.table)

    def bind(self, ids: list[str] | None, catalog: ModCatalog) -> None:
        self._ids, self._catalog = ids, catalog
        self.setEnabled(ids is not None)
        self.refresh()

    def refresh(self) -> None:
        if self._catalog is not None:
            self.table.set_mods(self._ids or [], self._catalog)

    def _reordered(self, order: list[str]) -> None:
        if self._ids is not None and sorted(order) == sorted(self._ids):
            self._ids[:] = order
            self.refresh()
            self.changed.emit()

    def _add(self) -> None:
        if self._ids is None:
            return
        current = set(self._ids)
        dlg = ModPickerDialog(self._catalog, [m for m in self._candidates() if m not in current], parent=self)
        if dlg.exec():
            new = [m for m in dlg.result_ids() if m not in current]
            if new:
                self._ids.extend(new)
                self.refresh()
                self.changed.emit()

    def _remove(self) -> None:
        if self._ids is None:
            return
        drop = set(self.table.selected_ids())
        if drop:
            self._ids[:] = [m for m in self._ids if m not in drop]
            self.refresh()
            self.changed.emit()
