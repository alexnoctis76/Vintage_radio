"""Registry for managing multiple libraries (each a separate SQLite DB)."""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Dict, List, Optional

from .resource_paths import app_data_dir

_REGISTRY_DIR = "libraries"
_REGISTRY_FILE = "libraries.json"
_DEFAULT_SLUG = "default"
_DEFAULT_NAME = "Default"


class LibraryRegistry:
    """Tracks available libraries and which one is active.

    State is persisted as ``libraries/libraries.json`` under ``app_data_dir()``.
    The default library maps to the legacy ``radio_manager.db`` at the root of
    ``app_data_dir()`` so existing installs migrate seamlessly.
    """

    def __init__(self, root: Optional[Path] = None) -> None:
        self._root = root or app_data_dir()
        self._lib_dir = self._root / _REGISTRY_DIR
        self._registry_path = self._lib_dir / _REGISTRY_FILE
        self._data = self._load()

    def _load(self) -> dict:
        if self._registry_path.exists():
            try:
                with self._registry_path.open("r", encoding="utf-8") as f:
                    data = json.load(f)
                if "libraries" in data and "active" in data:
                    return data
            except (json.JSONDecodeError, OSError):
                pass
        return self._bootstrap()

    def _bootstrap(self) -> dict:
        """Create the initial registry with a single default library."""
        data = {
            "active": _DEFAULT_SLUG,
            "libraries": {
                _DEFAULT_SLUG: {
                    "name": _DEFAULT_NAME,
                    "filename": "radio_manager.db",
                },
            },
        }
        self._save(data)
        return data

    def _save(self, data: Optional[dict] = None) -> None:
        if data is None:
            data = self._data
        self._lib_dir.mkdir(parents=True, exist_ok=True)
        with self._registry_path.open("w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    def list_libraries(self) -> List[Dict]:
        """Return a list of ``{"slug", "name", "filename", "is_active"}`` dicts."""
        active = self._data["active"]
        return [
            {
                "slug": slug,
                "name": info["name"],
                "filename": info["filename"],
                "is_active": slug == active,
            }
            for slug, info in self._data["libraries"].items()
        ]

    def active_library(self) -> str:
        """Return the slug of the currently active library."""
        return self._data["active"]

    def active_library_name(self) -> str:
        slug = self._data["active"]
        return self._data["libraries"].get(slug, {}).get("name", _DEFAULT_NAME)

    def db_path_for(self, slug: str) -> Path:
        """Absolute path to the SQLite DB for *slug*."""
        info = self._data["libraries"].get(slug)
        if info is None:
            raise KeyError(f"Unknown library: {slug!r}")
        return self._root / info["filename"]

    def set_active(self, slug: str) -> None:
        if slug not in self._data["libraries"]:
            raise KeyError(f"Unknown library: {slug!r}")
        self._data["active"] = slug
        self._save()

    def create_library(self, name: str) -> str:
        """Create a new (empty) library and return its slug."""
        slug = self._slugify(name)
        if slug in self._data["libraries"]:
            raise ValueError(f"Library already exists: {name!r}")
        filename = f"{_REGISTRY_DIR}/{slug}.db"
        self._data["libraries"][slug] = {"name": name, "filename": filename}
        self._save()
        return slug

    def rename_library(self, slug: str, new_name: str) -> None:
        if slug not in self._data["libraries"]:
            raise KeyError(f"Unknown library: {slug!r}")
        self._data["libraries"][slug]["name"] = new_name
        self._save()

    def delete_library(self, slug: str) -> None:
        """Delete a library. Refuses to delete if it's the only one remaining."""
        if slug not in self._data["libraries"]:
            raise KeyError(f"Unknown library: {slug!r}")
        if len(self._data["libraries"]) <= 1:
            raise RuntimeError("Cannot delete the only library.")
        db_path = self.db_path_for(slug)
        del self._data["libraries"][slug]
        if self._data["active"] == slug:
            self._data["active"] = next(iter(self._data["libraries"]))
        self._save()
        # Remove db file + WAL/SHM sidecars
        for suffix in ("", "-wal", "-shm"):
            p = db_path.parent / (db_path.name + suffix)
            if p.exists():
                try:
                    p.unlink()
                except OSError:
                    pass

    def _slugify(self, name: str) -> str:
        slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
        if not slug:
            slug = "library"
        base = slug
        counter = 2
        while slug in self._data["libraries"]:
            slug = f"{base}-{counter}"
            counter += 1
        return slug
