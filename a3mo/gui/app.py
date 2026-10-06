"""Main window."""
from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QAction, QDesktopServices, QKeySequence
from PySide6.QtWidgets import QApplication, QFileDialog, QMainWindow, QMessageBox, QTabWidget

from .. import BACKUP_DIR, __version__
from ..launcher_data import ModCatalog
from ..model import Library
from ..sync import import_presets
from .analysis_tab import AnalysisTab
from .configs_tab import ConfigsTab
from .generate_dialog import GenerateDialog
from .sets_tab import SetsTab


class MainWindow(QMainWindow):
    def __init__(self, library_path: Path):
        super().__init__()
        self.library_path = Path(library_path)
        self.lib = Library.load(self.library_path)
        self.catalog = ModCatalog.load(self.lib.settings.launcher_path)
        self.dirty = False
        self.resize(1280, 800)

        self.configs_tab = ConfigsTab(self)
        self.sets_tab = SetsTab(self)
        self.analysis_tab = AnalysisTab(self)
        self.tabs = QTabWidget()
        self.tabs.addTab(self.configs_tab, "Configs")
        self.tabs.addTab(self.sets_tab, "Mod Sets")
        self.tabs.addTab(self.analysis_tab, "Analysis")
        self.tabs.currentChanged.connect(lambda _: self.reload_all())
        self.setCentralWidget(self.tabs)
        self._build_toolbar()
        self.reload_all()
        self._update_title()

    def _build_toolbar(self) -> None:
        tb = self.addToolBar("Main")
        tb.setMovable(False)

        def act(text, fn, shortcut=None, tip=None):
            a = QAction(text, self)
            a.triggered.connect(fn)
            if shortcut:
                a.setShortcut(QKeySequence(shortcut))
            if tip:
                a.setToolTip(tip)
            tb.addAction(a)
            return a

        act("Save", self.save, "Ctrl+S", "Save the library (Ctrl+S)")
        act("Generate presets…", self.generate, "Ctrl+G",
            "Write configs as .preset2 files into the launcher's Presets folder (Ctrl+G)")
        tb.addSeparator()
        act("Import launcher presets…", self.import_presets, tip="Create configs from existing launcher presets")
        act("Reload mod list", self.reload_catalog, "F5", "Re-read installed mods from the launcher (F5)")
        tb.addSeparator()
        act("Launcher folder…", self.choose_launcher_dir)
        act("Open backups", lambda: (BACKUP_DIR.mkdir(parents=True, exist_ok=True),
                                     QDesktopServices.openUrl(QUrl.fromLocalFile(str(BACKUP_DIR)))))

    # --- shared state -----------------------------------------------------
    def all_known_mods(self) -> list[str]:
        ids = set(self.catalog.mods)
        for s in self.lib.sets.values():
            ids.update(s.mods)
        for c in self.lib.configs.values():
            ids.update(c.add)
            ids.update(c.exclude)
        return list(ids)

    def mark_dirty(self, reload: bool = False) -> None:
        self.dirty = True
        self._update_title()
        if reload:
            self.reload_all()

    def reload_all(self) -> None:
        current = self.tabs.currentWidget()
        current.reload()  # other tabs refresh when they become visible

    def _update_title(self) -> None:
        self.setWindowTitle(f"{'* ' if self.dirty else ''}Arma 3 Mod Organizer {__version__} — {self.library_path}")
        n_mods = len(self.catalog.mods)
        self.statusBar().showMessage(
            f"{len(self.lib.configs)} configs · {len(self.lib.sets)} sets · {n_mods} mods known · "
            f"launcher: {self.lib.settings.launcher_path}")

    # --- actions ----------------------------------------------------------
    def save(self) -> bool:
        try:
            self.lib.save(self.library_path)
        except OSError as e:
            QMessageBox.critical(self, "Save", f"Could not save library:\n{e}")
            return False
        self.dirty = False
        self._update_title()
        return True

    def generate(self) -> None:
        if not self.lib.configs:
            QMessageBox.information(self, "Generate", "No configs yet. Import launcher presets or create a config.")
            return
        if GenerateDialog(self).exec():
            self.save()

    def import_presets(self) -> None:
        presets = self.lib.settings.presets_path
        overwrite = False
        if self.lib.configs:
            ans = QMessageBox.question(
                self, "Import presets",
                "Import presets that are not in the library yet?\n\n"
                "Yes: add only new presets\nNo: also overwrite existing configs with the launcher's version",
                QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel)
            if ans == QMessageBox.Cancel:
                return
            overwrite = ans == QMessageBox.No
        names = import_presets(self.lib, presets, overwrite=overwrite)
        self.mark_dirty(reload=True)
        msg = f"Imported {len(names)} preset(s) from\n{presets}"
        if names:
            msg += "\n\nTip: Analysis → Suggest sets extracts the shared mods into reusable sets."
        QMessageBox.information(self, "Import presets", msg)

    def reload_catalog(self) -> None:
        self.catalog = ModCatalog.load(self.lib.settings.launcher_path)
        self.reload_all()
        self._update_title()

    def choose_launcher_dir(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Arma 3 Launcher data folder",
                                             str(self.lib.settings.launcher_path))
        if d:
            self.lib.settings.launcher_dir = d
            self.mark_dirty()
            self.reload_catalog()

    def first_run(self) -> None:
        if self.lib.configs or self.lib.sets:
            return
        if not self.lib.settings.presets_path.is_dir():
            QMessageBox.warning(self, "Arma 3 Mod Organizer",
                                f"Launcher presets folder not found:\n{self.lib.settings.presets_path}\n\n"
                                "Use 'Launcher folder…' to point to it.")
            return
        if QMessageBox.question(self, "Welcome",
                                "Import your existing Arma 3 Launcher presets as configs?") == QMessageBox.Yes:
            self.import_presets()

    def closeEvent(self, event) -> None:
        if self.dirty:
            ans = QMessageBox.question(self, "Unsaved changes", "Save changes to the library?",
                                       QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel)
            if ans == QMessageBox.Cancel or (ans == QMessageBox.Save and not self.save()):
                event.ignore()
                return
        event.accept()


def run(library_path: Path) -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("Arma 3 Mod Organizer")
    app.setStyle("Fusion")
    win = MainWindow(library_path)
    win.show()
    win.first_run()
    return app.exec()
