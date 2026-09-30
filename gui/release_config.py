"""Release-time flags read from ``release_config.json`` at the project / bundle root.

Edit this file before building a release installer — not exposed in the app UI.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Optional

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


def update_check_enabled(*, default: bool = True) -> bool:
    """When False, packaged builds skip GitHub update checks (dev/test installers)."""
    section = load_release_config().get("update")
    if not isinstance(section, dict):
        return default
    if "enabled" not in section:
        return default
    return bool(section.get("enabled"))


def update_channel(*, default: str = "stable") -> str:
    section = load_release_config().get("update")
    if not isinstance(section, dict):
        return default
    raw = str(section.get("channel") or "").strip().lower()
    return raw or default


def _update_section() -> Dict[str, Any]:
    section = load_release_config().get("update")
    return section if isinstance(section, dict) else {}


def update_repo_slug(*, default: str = "alexnoctis76/Vintage_radio") -> str:
    """GitHub ``owner/repo`` slug for release API calls (optional override for private forks)."""
    raw = str(_update_section().get("repo") or "").strip()
    return raw or default


def update_prerelease_only(*, default: Optional[bool] = None) -> bool:
    """When True, only GitHub pre-releases count; when False, only full releases.

    Defaults by channel: ``test`` -> True, ``stable`` -> False.
    """
    section = _update_section()
    if "prerelease_only" in section:
        return bool(section.get("prerelease_only"))
    if default is not None:
        return default
    return update_channel() == "test"


def update_tag_suffix(*, default: str = "") -> str:
    """Optional tag suffix filter (e.g. ``-upgrade-test``) for the test channel."""
    raw = str(_update_section().get("tag_suffix") or "").strip()
    return raw or default


def is_official_firmware_visible(entry_id: str, *, default: bool = True) -> bool:
    """Return whether an official firmware card should appear in Install Firmware."""
    # Legacy ZBVR test card — hidden unless explicitly enabled in release_config.json
    # (dev-only; not part of the normal release_config templates).
    if entry_id == ZBVR_FIRMWARE_ENTRY_ID:
        default = False
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
