"""Read and write Arma 3 Launcher ``.preset2`` files.

The launcher writes these with .NET's XmlWriter: UTF-8 with BOM, CRLF line
endings, two-space indent, no trailing newline. We reproduce that exactly so
untouched presets round-trip byte-for-byte.
"""
from __future__ import annotations

import datetime as _dt
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from xml.sax.saxutils import escape

PRESET_EXT = ".preset2"
DEFAULT_PRESET_NAME = "arma3.defaultpreset2"


@dataclass
class Preset:
    name: str
    mods: list[str] = field(default_factory=list)
    dlcs: list[int] = field(default_factory=list)
    last_update: str = ""

    def same_content(self, other: "Preset") -> bool:
        # Same mods and DLCs, ignoring order (callers compare ``mods`` for order).
        return set(self.mods) == set(other.mods) and set(self.dlcs) == set(other.dlcs)


def read_preset2(path: Path) -> Preset:
    root = ET.fromstring(Path(path).read_bytes())
    mods = [(e.text or "").strip() for e in root.findall("./published-ids/id")]
    dlcs = [int((e.text or "0").strip()) for e in root.findall("./dlcs-appids/id")]
    last = (root.findtext("last-update") or "").strip()
    return Preset(name=Path(path).stem, mods=[m for m in mods if m], dlcs=dlcs, last_update=last)


def now_timestamp() -> str:
    # Matches the launcher's format: 2026-02-02T20:43:14.1075384+02:00
    now = _dt.datetime.now().astimezone()
    off = now.strftime("%z")
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond:06d}0" + f"{off[:3]}:{off[3:]}"


def serialize_preset2(preset: Preset) -> bytes:
    lines = [
        '<?xml version="1.0" encoding="utf-8"?>',
        "<addons-presets>",
        f"  <last-update>{escape(preset.last_update or now_timestamp())}</last-update>",
    ]
    for tag, items in (("published-ids", preset.mods), ("dlcs-appids", preset.dlcs)):
        if items:
            lines.append(f"  <{tag}>")
            lines.extend(f"    <id>{escape(str(i))}</id>" for i in items)
            lines.append(f"  </{tag}>")
        else:
            lines.append(f"  <{tag} />")
    lines.append("</addons-presets>")
    return b"\xef\xbb\xbf" + "\r\n".join(lines).encode("utf-8")


def write_preset2(path: Path, preset: Preset) -> None:
    Path(path).write_bytes(serialize_preset2(preset))


def list_preset_files(presets_dir: Path) -> list[Path]:
    d = Path(presets_dir)
    if not d.is_dir():
        return []
    return sorted(p for p in d.iterdir() if p.suffix.lower() == PRESET_EXT and p.is_file())
