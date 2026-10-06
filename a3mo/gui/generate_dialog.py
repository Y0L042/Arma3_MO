"""Dry-run summary of preset generation, then apply with backup."""
from __future__ import annotations

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QBrush, QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QLabel, QMessageBox, QPushButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout,
)

from .. import BACKUP_DIR
from ..sync import GeneratePlan, apply_generate, launcher_running, plan_generate
from .widgets import WARN_COLOR


class GenerateDialog(QDialog):
    def __init__(self, main):
        super().__init__(main)
        self.main = main
        self.setWindowTitle("Generate launcher presets")
        self.resize(820, 600)
        self.presets_dir = main.lib.settings.presets_path
        self.plan: GeneratePlan = plan_generate(main.lib, main.catalog, self.presets_dir)

        n = {s: sum(1 for i in self.plan.items if i.status == s)
             for s in ("new", "changed", "reordered", "unchanged")}
        head = QLabel(f"Target: <code>{self.presets_dir}</code><br>"
                      f"<b>{n['new']}</b> new · <b>{n['changed']}</b> changed · <b>{n['reordered']}</b> reordered"
                      f" · {n['unchanged']} unchanged"
                      + (f" · {len(self.plan.unmanaged)} not managed (left untouched)" if self.plan.unmanaged else ""))
        head.setTextFormat(Qt.RichText)
        head.setWordWrap(True)

        tree = QTreeWidget()
        tree.setHeaderLabels(["Preset", "Status", "Mods", "Warnings"])
        tree.setColumnWidth(0, 320)
        cat = main.catalog
        order = {"new": 0, "changed": 1, "reordered": 2, "unchanged": 3}
        for it in sorted(self.plan.items, key=lambda i: (order[i.status], i.config.lower())):
            warn = []
            if it.missing:
                warn.append(f"{len(it.missing)} not installed")
            if it.missing_deps:
                warn.append(f"{len(it.missing_deps)} missing deps")
            status = it.status + (f"  +{len(it.added)} −{len(it.removed)}" if it.status == "changed" else "")
            top = QTreeWidgetItem([it.config, status, str(len(it.mods)), ", ".join(warn)])
            if warn:
                top.setForeground(3, QBrush(WARN_COLOR))
            for m in it.added:
                QTreeWidgetItem(top, [f"+ {cat.name(m)}", "", "", m])
            for m in it.removed:
                QTreeWidgetItem(top, [f"− {cat.name(m)}", "", "", m])
            for m in it.missing:
                c = QTreeWidgetItem(top, [f"⚠ not installed: {cat.name(m)}", "", "", m])
                c.setForeground(0, QBrush(WARN_COLOR))
            for m, deps in it.missing_deps.items():
                c = QTreeWidgetItem(top, [f"⚠ {cat.name(m)} needs: " + ", ".join(cat.name(d) for d in deps), "", "",
                                          ", ".join(deps)])
                c.setForeground(0, QBrush(WARN_COLOR))
            tree.addTopLevelItem(top)
        if self.plan.unmanaged:
            un = QTreeWidgetItem(["Presets not managed by this tool", "untouched", "", ""])
            for name in self.plan.unmanaged:
                QTreeWidgetItem(un, [name])
            tree.addTopLevelItem(un)

        lay = QVBoxLayout(self)
        lay.addWidget(head)
        if launcher_running():
            w = QLabel("⚠ The Arma 3 Launcher is running. Restart it after generating to see the changes.")
            w.setStyleSheet(f"color: {WARN_COLOR.name()}; font-weight: bold")
            lay.addWidget(w)
        lay.addWidget(tree, 1)

        self.reorder_cb = QCheckBox(f"Also write presets whose only change is mod order ({n['reordered']})")
        self.reorder_cb.setChecked(True)
        self.reorder_cb.setEnabled(n["reordered"] > 0)
        self.reorder_cb.toggled.connect(self._update_apply)
        lay.addWidget(self.reorder_cb)

        buttons = QDialogButtonBox(QDialogButtonBox.Cancel)
        self.apply_btn = QPushButton()
        self.apply_btn.setDefault(True)
        buttons.addButton(self.apply_btn, QDialogButtonBox.AcceptRole)
        open_btn = QPushButton("Open Presets folder")
        open_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.presets_dir))))
        buttons.addButton(open_btn, QDialogButtonBox.ActionRole)
        buttons.accepted.connect(self._apply)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)
        self._update_apply()

    def _update_apply(self) -> None:
        self.plan.include_reordered = self.reorder_cb.isChecked()
        self.apply_btn.setText(f"Write {len(self.plan.to_write)} preset(s)")
        self.apply_btn.setEnabled(bool(self.plan.to_write))

    def _apply(self) -> None:
        try:
            backup = apply_generate(self.plan, self.presets_dir, BACKUP_DIR)
        except OSError as e:
            QMessageBox.critical(self, "Generate", f"Failed to write presets:\n{e}")
            return
        QMessageBox.information(self, "Generate",
                                f"Wrote {len(self.plan.to_write)} preset(s).\nBackup of previous presets:\n{backup}")
        self.accept()
