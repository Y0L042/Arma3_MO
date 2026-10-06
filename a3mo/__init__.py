"""Arma 3 Mod Organizer: compose launcher presets from reusable mod sets."""
import sys
from pathlib import Path

__version__ = "0.1.0"

if getattr(sys, "frozen", False):
    APP_DIR = Path(sys.executable).parent
else:
    APP_DIR = Path(__file__).resolve().parent.parent

DATA_DIR = APP_DIR / "data"
LIBRARY_PATH = DATA_DIR / "library.json"
BACKUP_DIR = DATA_DIR / "backups"
