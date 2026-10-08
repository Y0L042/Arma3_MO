"""Main window."""
from __future__ import annotations

import sys
import threading
from pathlib import Path

from PySide6.QtCore import QObject, QUrl, Signal
from PySide6.QtGui import QAction, QDesktopServices, QKeySequence
from PySide6.QtWidgets import QApplication, QFileDialog, QLabel, QMainWindow, QMessageBox, QTabWidget

from .. import BACKUP_DIR, __version__
from ..launcher_data import ModCatalog
from ..model import Library
from ..sync import find_moved_local_mods, import_presets
from ..workshop import WorkshopCache, fetch_details
from .analysis_tab import AnalysisTab
from .configs_tab import ConfigsTab
from .generate_dialog import GenerateDialog
from .sets_tab import SetsTab


class _WorkshopFetcher(QObject):
    """Fetches Workshop details on a worker thread; ``done`` is delivered on the GUI thread."""

    done = Signal(object, object, str)  # requested ids, {id: {"title", "tags"}}, error text

    def start(self, ids: list[str]) -> None:
        threading.Thread(target=self._run, args=(ids,), daemon=True).start()

    def _run(self, ids: list[str]) -> None:
        try:
            self.done.emit(ids, fetch_details(ids), "")
        except (OSError, ValueError) as e:
            self.done.emit(ids, {}, str(e))


class MainWindow(QMainWindow):
    def __init__(self, library_path: Path):
        super().__init__()
        self.library_path = Path(library_path)
        self.lib = Library.load(self.library_path)
        self.workshop = WorkshopCache.load(self.library_path.parent / "workshop_cache.json")
        self.catalog = self._load_catalog()
        self.dirty = False
        self._fetcher = _WorkshopFetcher(self)
        self._fetcher.done.connect(self._workshop_fetched)
        self._fetching = False
        self.workshop_status = QLabel()
        self.statusBar().addPermanentWidget(self.workshop_status)
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
        act("Refresh Workshop info", lambda: self.start_workshop_fetch(refresh_all=True),
            tip="Re-download names and type tags of all Workshop mods (tags are used by the Type filters)")
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
        self.start_workshop_fetch()
        msg = f"Imported {len(names)} preset(s) from\n{presets}"
        if names:
            msg += "\n\nTip: Analysis → Suggest sets extracts the shared mods into reusable sets."
        QMessageBox.information(self, "Import presets", msg)

    def _load_catalog(self) -> ModCatalog:
        catalog = ModCatalog.load(self.lib.settings.launcher_path)
        self._apply_workshop(catalog)
        return catalog

    def reload_catalog(self) -> None:
        self.catalog = self._load_catalog()
        self.reload_all()
        self._update_title()
        self.relink_moved_local_mods()
        self.start_workshop_fetch()

    def relink_moved_local_mods(self) -> None:
        """Point library entries of local mods whose folder moved to the new folder."""
        moved = find_moved_local_mods(self.lib.all_mod_ids(), self.catalog)
        if moved:
            self.lib.replace_mods(moved)
            self.mark_dirty(reload=True)
            self.statusBar().showMessage(f"Updated {len(moved)} moved local mod folder(s)", 10000)

    # --- Workshop details -------------------------------------------------
    def _apply_workshop(self, catalog: ModCatalog) -> None:
        catalog.apply_workshop(self.workshop.titles(), self.workshop.all())

    def start_workshop_fetch(self, refresh_all: bool = False) -> None:
        """Download names and tags of Workshop mods not cached yet (or all of them) in the background."""
        if self._fetching:
            return
        known = self.all_known_mods()
        ids = [m for m in known if m.startswith("steam:")] if refresh_all else self.workshop.missing(known)
        if not ids:
            return
        self._fetching = True
        self.workshop_status.setText(f"Fetching Workshop info for {len(ids)} mod(s)…")
        self._fetcher.start(sorted(ids))

    def _workshop_fetched(self, ids: list[str], details: dict[str, dict], error: str) -> None:
        self._fetching = False
        if error:
            self.workshop_status.setText("Workshop info: fetch failed")
            self.workshop_status.setToolTip(error)
            return
        # Items Steam didn't return (removed / private) are cached untagged so they aren't re-requested.
        self.workshop.update({m: details.get(m, {}) for m in ids})
        try:
            self.workshop.save()
        except OSError as e:
            self.workshop_status.setToolTip(f"Could not save the Workshop cache: {e}")
        self._apply_workshop(self.catalog)
        self.workshop_status.setText(f"Workshop info: {len(details)} updated")
        self.reload_all()

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
    win.relink_moved_local_mods()
    win.start_workshop_fetch()
    return app.exec()
