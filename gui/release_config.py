"""Release-time flags read from ``release_config.json`` at the project / bundle root.

Edit this file before building a release installer — not exposed in the app UI.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict

from .resource_paths import project_root

CONFIG_FILENAME = "release_config.json"
ZBVR_FIRMWARE_ENTRY_ID = "zbvr_26_0_1"


def release_config_path() -> Path:
    return project_root() / CONFIG_FILENAME


@lru_cache(maxsize=1)
def load_release_config() -> Dict[str, Any]:
    path = release_config_path()
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return raw if isinstance(raw, dict) else {}


def reload_release_config() -> Dict[str, Any]:
    load_release_config.cache_clear()
    return load_release_config()


def is_official_firmware_visible(entry_id: str, *, default: bool = True) -> bool:
    """Return whether an official firmware card should appear in Install Firmware."""
    section = load_release_config().get("official_firmware")
    if not isinstance(section, dict):
        return default
    if entry_id not in section:
        return default
    value = section[entry_id]
    if isinstance(value, bool):
        return value
    if isinstance(value, dict):
        return bool(value.get("visible", default))
    return default
