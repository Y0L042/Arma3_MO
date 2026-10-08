"""Steam Workshop details (title, type tags), fetched from Steam's public API and cached locally."""
from __future__ import annotations

import json
import os
import time
import urllib.parse
import urllib.request
from pathlib import Path

API_URL = "https://api.steampowered.com/ISteamRemoteStorage/GetPublishedFileDetails/v1/"
BATCH = 100

# Tags that say nothing about what a mod is: on every item, moderation markers, or
# DLC / terrain compatibility flags.
IGNORED_TAGS = frozenset({
    "Mod", "Tag Review", "Content Review", "x64",
    "Apex", "Malden", "Tanoa", "OtherMap", "KartsDLC", "MarksmenDLC", "HelicoptersDLC", "Jets", "Tanks",
    "Laws of War", "Contact", "Contact (Platform)", "Global Mobilization", "S.O.G. Prairie Fire",
    "CSLA Iron Curtain", "Western Sahara", "Spearhead 1944", "Reaction Forces", "Expeditionary Forces",
})


def type_tags(tags: list[str]) -> list[str]:
    return [t for t in tags if t not in IGNORED_TAGS]


def fetch_details(steam_ids: list[str], timeout: float = 15) -> dict[str, dict]:
    """``steam:N`` ids -> ``{"title": str, "tags": [raw tags]}``. Items Steam doesn't return are left out.

    Raises ``OSError`` (incl. ``urllib.error.URLError``) or ``ValueError`` on failure.
    """
    nums = [m.split(":", 1)[1] for m in steam_ids if m.startswith("steam:")]
    out: dict[str, dict] = {}
    for i in range(0, len(nums), BATCH):
        batch = nums[i:i + BATCH]
        form = {"itemcount": len(batch)} | {f"publishedfileids[{j}]": n for j, n in enumerate(batch)}
        with urllib.request.urlopen(API_URL, urllib.parse.urlencode(form).encode(), timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        for item in data.get("response", {}).get("publishedfiledetails", []):
            if item.get("result") == 1:
                out[f"steam:{item['publishedfileid']}"] = {
                    "title": item.get("title") or "",
                    "tags": [t["tag"] for t in item.get("tags", []) if t.get("tag")],
                }
    return out


class WorkshopCache:
    """``{"mods": {"steam:N": {"title": str, "tags": [...], "fetched": unix_ts}}}`` stored as JSON."""

    def __init__(self, path: Path, mods: dict[str, dict] | None = None):
        self.path = Path(path)
        self.mods: dict[str, dict] = mods or {}

    @classmethod
    def load(cls, path: Path) -> "WorkshopCache":
        try:
            mods = json.loads(Path(path).read_text(encoding="utf-8")).get("mods", {})
        except (OSError, ValueError, AttributeError):
            mods = {}
        return cls(path, mods if isinstance(mods, dict) else {})

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"mods": self.mods}, indent=1), encoding="utf-8")
        os.replace(tmp, self.path)

    def missing(self, ids) -> list[str]:
        """Workshop ids not cached yet (or cached before titles were stored)."""
        return [m for m in ids if m.startswith("steam:") and "title" not in self.mods.get(m, {})]

    def update(self, details: dict[str, dict]) -> None:
        now = int(time.time())
        for mid, d in details.items():
            self.mods[mid] = {"title": d.get("title", ""), "tags": list(d.get("tags", [])), "fetched": now}

    def title(self, mod_id: str) -> str:
        return self.mods.get(mod_id, {}).get("title", "")

    def titles(self) -> dict[str, str]:
        return {m: t for m in self.mods if (t := self.title(m))}

    def tags(self, mod_id: str) -> list[str]:
        return type_tags(self.mods.get(mod_id, {}).get("tags", []))

    def all(self) -> dict[str, list[str]]:
        """Type tags (noise removed) for every cached mod."""
        return {m: self.tags(m) for m in self.mods}
