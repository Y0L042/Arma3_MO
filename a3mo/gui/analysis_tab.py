"""Analysis tab: suggest shared sets, diff two configs, overlap matrix, mod usage."""
from __future__ import annotations

from html import escape

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QDoubleSpinBox, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMessageBox, QPushButton, QSpinBox, QTableWidget, QTableWidgetItem, QTabWidget,
    QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from ..analysis import apply_suggestions, diff_configs, mod_usage, overlap_matrix, suggest_sets
from .widgets import ID_ROLE, ModTable


class AnalysisTab(QWidget):
    def __init__(self, main):
        super().__init__()
        self.main = main
        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_suggest(), "Suggest sets")
        self.tabs.addTab(self._build_diff(), "Compare configs")
        self.tabs.addTab(self._build_overlap(), "Overlap")
        self.tabs.addTab(self._build_usage(), "Mod usage")
        self.tabs.currentChanged.connect(lambda _: self.reload())
        QVBoxLayout(self).addWidget(self.tabs)
        self._suggestions = []

    def reload(self) -> None:
        names = list(self.main.lib.configs)
        for combo in (self.diff_a, self.diff_b):
            cur = combo.currentText()
            combo.blockSignals(True)
            combo.clear()
            combo.addItems(names)
            if cur in names:
                combo.setCurrentText(cur)
            combo.blockSignals(False)
        if self.diff_b.currentIndex() == 0 and len(names) > 1 and self.diff_a.currentIndex() == 0:
            self.diff_b.setCurrentIndex(1)
        idx = self.tabs.currentIndex()
        if idx == 1:
            self._run_diff()
        elif idx == 2:
            self._run_overlap()
        elif idx == 3:
            self._run_usage()

    # --- suggestions ------------------------------------------------------
    def _build_suggest(self) -> QWidget:
        w = QWidget()
        self.threshold = QDoubleSpinBox(minimum=0.3, maximum=1.0, singleStep=0.05, value=0.8)
        self.threshold.setToolTip("Mods present in at least this fraction of configs go into 'Core'")
        self.min_size = QSpinBox(minimum=1, maximum=50, value=2)
        self.min_size.setToolTip("Minimum mods for a suggested set (besides Core)")
        run = QPushButton("Analyze")
        run.clicked.connect(self._run_suggest)
        top = QHBoxLayout()
        top.addWidget(QLabel("Core threshold:"))
        top.addWidget(self.threshold)
        top.addWidget(QLabel("Min set size:"))
        top.addWidget(self.min_size)
        top.addWidget(run)
        top.addStretch(1)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Suggested set / mod", "Mods", "Used by configs"])
        self.tree.setColumnWidth(0, 360)
        self.tree.itemDoubleClicked.connect(self._rename_suggestion)
        apply = QPushButton("Apply checked suggestions")
        apply.clicked.connect(self._apply_suggest)
        info = QLabel("Checked suggestions become sets; configs get them included and their 'extra' "
                      "mods are cleaned up. Every preset keeps exactly the same mods (load order may change; Generate shows it as \"reordered\"). Double-click a set to rename it.")
        info.setWordWrap(True)
        bottom = QHBoxLayout()
        bottom.addWidget(info, 1)
        bottom.addWidget(apply)
        lay = QVBoxLayout(w)
        lay.addLayout(top)
        lay.addWidget(self.tree, 1)
        lay.addLayout(bottom)
        return w

    def _run_suggest(self) -> None:
        cat = self.main.catalog
        self._suggestions = suggest_sets(self.main.lib, self.threshold.value(), 0.5, self.min_size.value(), cat)
        self.tree.clear()
        for i, s in enumerate(self._suggestions):
            top = QTreeWidgetItem([s.name, str(len(s.mods)), ", ".join(s.configs)])
            top.setData(0, Qt.UserRole, i)
            top.setFlags(top.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsEditable)
            top.setCheckState(0, Qt.Checked)
            top.setToolTip(2, "\n".join(s.configs))
            for m in s.mods:
                QTreeWidgetItem(top, [cat.name(m), "", m])
            if s.excludes:
                ex = QTreeWidgetItem(top, [f"(excluded in {len(s.excludes)} config(s) that lack some of these)"])
                for cfg, mods in s.excludes.items():
                    QTreeWidgetItem(ex, [cfg, str(len(mods)), ", ".join(cat.name(m) for m in mods)])
            self.tree.addTopLevelItem(top)
        if not self._suggestions:
            self.tree.addTopLevelItem(QTreeWidgetItem(["No shared groups found"]))

    def _rename_suggestion(self, item: QTreeWidgetItem, col: int) -> None:
        if item.parent() is None and col == 0 and item.data(0, Qt.UserRole) is not None:
            self.tree.editItem(item, 0)

    def _apply_suggest(self) -> None:
        chosen = []
        names = set(self.main.lib.sets)
        for i in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(i)
            idx = item.data(0, Qt.UserRole)
            if idx is None or item.checkState(0) != Qt.Checked:
                continue
            s = self._suggestions[idx]
            s.name = item.text(0).strip() or s.name
            if s.name in names:
                QMessageBox.warning(self, "Suggest sets", f"Duplicate set name '{s.name}'. Rename it first.")
                return
            names.add(s.name)
            chosen.append(s)
        if not chosen:
            return
        try:
            self.main.lib = apply_suggestions(self.main.lib, chosen)
        except RuntimeError as e:
            QMessageBox.critical(self, "Suggest sets", str(e))
            return
        self._suggestions = []
        self.tree.clear()
        self.main.mark_dirty(reload=True)
        QMessageBox.information(self, "Suggest sets", f"Created {len(chosen)} set(s). Review them in the Mod Sets tab.")

    # --- diff -------------------------------------------------------------
    def _build_diff(self) -> QWidget:
        w = QWidget()
        self.diff_a, self.diff_b = QComboBox(), QComboBox()
        for c in (self.diff_a, self.diff_b):
            c.currentIndexChanged.connect(lambda _: self._run_diff())
        top = QHBoxLayout()
        top.addWidget(self.diff_a, 1)
        top.addWidget(QLabel("vs"))
        top.addWidget(self.diff_b, 1)
        self.only_a, self.only_b, self.common = ModTable(), ModTable(), ModTable()
        self.only_a_lbl, self.only_b_lbl, self.common_lbl = QLabel(), QLabel(), QLabel()
        cols = QHBoxLayout()
        for lbl, tbl in ((self.only_a_lbl, self.only_a), (self.common_lbl, self.common), (self.only_b_lbl, self.only_b)):
            v = QVBoxLayout()
            v.addWidget(lbl)
            v.addWidget(tbl)
            cols.addLayout(v)
        lay = QVBoxLayout(w)
        lay.addLayout(top)
        lay.addLayout(cols, 1)
        return w

    def _run_diff(self) -> None:
        a, b = self.diff_a.currentText(), self.diff_b.currentText()
        if a not in self.main.lib.configs or b not in self.main.lib.configs:
            return
        only_a, only_b, common = diff_configs(self.main.lib, a, b)
        cat = self.main.catalog
        self.only_a.set_mods(only_a, cat)
        self.only_b.set_mods(only_b, cat)
        self.common.set_mods(common, cat)
        self.only_a_lbl.setText(f"<b>Only in {a}</b> ({len(only_a)})")
        self.only_b_lbl.setText(f"<b>Only in {b}</b> ({len(only_b)})")
        self.common_lbl.setText(f"<b>In both</b> ({len(common)})")

    # --- overlap ----------------------------------------------------------
    def _build_overlap(self) -> QWidget:
        w = QWidget()
        self.matrix = QTableWidget()
        self.matrix.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.matrix.horizontalHeader().setDefaultSectionSize(44)
        self.matrix.verticalHeader().setDefaultSectionSize(22)
        self.matrix.cellDoubleClicked.connect(self._matrix_to_diff)
        lay = QVBoxLayout(w)
        lay.addWidget(QLabel("Shared mod count between configs (diagonal = total). Double-click a cell to compare."))
        lay.addWidget(self.matrix)
        return w

    def _run_overlap(self) -> None:
        names, m = overlap_matrix(self.main.lib)
        self.matrix.clear()
        self.matrix.setRowCount(len(names))
        self.matrix.setColumnCount(len(names))
        self.matrix.setVerticalHeaderLabels(names)
        self.matrix.setHorizontalHeaderLabels([str(i + 1) for i in range(len(names))])
        for i, name in enumerate(names):
            self.matrix.horizontalHeaderItem(i).setToolTip(name)
            self.matrix.verticalHeaderItem(i).setText(f"{i + 1}. {name}")
        for i in range(len(names)):
            for j in range(len(names)):
                item = QTableWidgetItem(str(m[i][j]))
                item.setTextAlignment(Qt.AlignCenter)
                denom = max(1, min(m[i][i], m[j][j]))
                frac = m[i][j] / denom
                item.setBackground(QBrush(QColor.fromHsvF(0.58, 0.7 * frac, 1.0 - 0.25 * frac)))
                item.setForeground(QBrush(QColor("black")))
                item.setToolTip(f"{names[i]} ∩ {names[j]}: {m[i][j]} mods ({frac:.0%} of the smaller)")
                self.matrix.setItem(i, j, item)

    def _matrix_to_diff(self, row: int, col: int) -> None:
        self.diff_a.setCurrentIndex(row)
        self.diff_b.setCurrentIndex(col)
        self.tabs.setCurrentIndex(1)

    # --- mod usage --------------------------------------------------------
    def _build_usage(self) -> QWidget:
        w = QWidget()
        self.usage_filter = QLineEdit(placeholderText="Filter mods…")
        self.usage_mods = QListWidget()
        self.usage_filter.textChanged.connect(self._filter_usage)
        self.usage_mods.currentItemChanged.connect(lambda *_: self._show_usage())
        self.usage_info = QLabel()
        self.usage_info.setWordWrap(True)
        self.usage_info.setAlignment(Qt.AlignTop)
        self.usage_info.setTextInteractionFlags(Qt.TextSelectableByMouse)
        left = QVBoxLayout()
        left.addWidget(self.usage_filter)
        left.addWidget(self.usage_mods)
        lay = QHBoxLayout(w)
        lay.addLayout(left, 1)
        lay.addWidget(self.usage_info, 1)
        return w

    def _run_usage(self) -> None:
        lib, cat = self.main.lib, self.main.catalog
        counts: dict[str, int] = {}
        for c in lib.configs:
            for m in lib.resolve(c):
                counts[m] = counts.get(m, 0) + 1
        for s in lib.sets.values():
            for m in s.mods:
                counts.setdefault(m, 0)
        self.usage_mods.clear()
        for m in sorted(counts, key=lambda m: cat.name(m).lower()):
            item = QListWidgetItem(f"{cat.name(m)}   [{counts[m]}]")
            item.setData(ID_ROLE, m)
            self.usage_mods.addItem(item)
        self._filter_usage(self.usage_filter.text())

    def _filter_usage(self, text: str) -> None:
        t = text.lower()
        for i in range(self.usage_mods.count()):
            item = self.usage_mods.item(i)
            item.setHidden(bool(t) and t not in item.text().lower() and t not in item.data(ID_ROLE).lower())

    def _show_usage(self) -> None:
        item = self.usage_mods.currentItem()
        if not item:
            self.usage_info.setText("")
            return
        mid = item.data(ID_ROLE)
        info = self.main.catalog.info(mid)
        sets, configs = mod_usage(self.main.lib, mid)
        excluded_in = [c for c, cfg in self.main.lib.configs.items() if mid in cfg.exclude]
        cat = self.main.catalog
        sets, configs, excluded_in = map(lambda xs: [escape(x) for x in xs], (sets, configs, excluded_in))
        html = [f"<h3>{escape(info.name)}</h3><p>{mid}<br>{'Installed' if info.installed else '<b>Not installed</b>'}"
                + (f"<br>Author: {escape(info.author)}" if info.author else "") + "</p>",
                f"<p><b>In sets ({len(sets)}):</b><br>{'<br>'.join(sets) or '—'}</p>",
                f"<p><b>In configs ({len(configs)}):</b><br>{'<br>'.join(configs) or '—'}</p>"]
        if excluded_in:
            html.append(f"<p><b>Excluded in:</b><br>{'<br>'.join(excluded_in)}</p>")
        if info.dependencies:
            html.append("<p><b>Requires:</b><br>" + "<br>".join(escape(cat.name(d)) for d in info.dependencies) + "</p>")
        self.usage_info.setText("".join(html))
