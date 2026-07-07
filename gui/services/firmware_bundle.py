"""Bundled / cached Pico firmware assets for Install Firmware."""

from __future__ import annotations

import re
import urllib.request
from pathlib import Path
from typing import List, Optional, Tuple

from gui.resource_paths import app_data_dir, project_root

_FULL_UF2_GLOB = "vintage-radio-firmware-*-full.uf2"
_FULL_UF2_VERSION_RE = re.compile(
    r"^vintage-radio-firmware-(?P<ver>\d+(?:\.\d+)*)-full\.uf2$",
    re.IGNORECASE,
)

_UF2_PATTERN = re.compile(r'href="(/resources/firmware/RPI_PICO[^"]*\.uf2)"')
MICROPYTHON_PICO_URL = "https://micropython.org/download/RPI_PICO/"
FLASH_NUKE_URL = "https://datasheets.raspberrypi.com/soft/flash_nuke.uf2"


def _writable_firmware_cache_dir(*parts: str) -> Path:
    """User-writable cache (never inside a frozen .app bundle / _MEIPASS)."""
    cache = app_data_dir().joinpath("firmware_cache", *parts)
    cache.mkdir(parents=True, exist_ok=True)
    return cache


def _flash_nuke_cache_dir() -> Path:
    return _writable_firmware_cache_dir("flash_nuke")


def fetch_flash_nuke_uf2(*, force: bool = False) -> Path:
    """Download (or reuse cache) the official flash_nuke.uf2 erase image."""
    cache = _flash_nuke_cache_dir()
    out = cache / "flash_nuke.uf2"
    if not force and out.is_file() and out.stat().st_size > 1000:
        return out
    req = urllib.request.Request(FLASH_NUKE_URL, headers={"User-Agent": "VintageRadio/1.0"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = resp.read()
    if len(data) < 1000:
        raise RuntimeError(f"flash_nuke download too small ({len(data)} bytes)")
    out.write_bytes(data)
    return out


def _micropython_cache_dir() -> Path:
    return _writable_firmware_cache_dir("micropython")


def _full_uf2_version_sort_key(path: Path) -> Tuple[Tuple[int, ...], int, str]:
    """Sort newest semver first; prefer ``firmware/release`` over ``dist`` on ties."""
    m = _FULL_UF2_VERSION_RE.match(path.name)
    if m is None:
        return ((0,), 0, path.name.lower())
    parts = tuple(int(p) for p in m.group("ver").split("."))
    base_rank = 1 if "firmware" in path.parts and "release" in path.parts else 0
    return (parts, base_rank, path.name.lower())


def list_bundled_vintage_radio_full_uf2() -> List[Path]:
    """All shipped full-flash UF2 images, newest version first.

    Older builds (e.g. 1.0.0) remain on disk for manual use; Smart Install and
    bundled flash paths call :func:`bundled_vintage_radio_full_uf2` for the default.
    One path per semver — ``firmware/release`` wins over ``dist`` on duplicates.
    """
    root = project_root()
    by_version: dict[Tuple[int, ...], Path] = {}
    for base in (root / "firmware" / "release", root / "dist"):
        if not base.is_dir():
            continue
        for path in base.glob(_FULL_UF2_GLOB):
            if not path.is_file():
                continue
            ver = full_uf2_version_string(path)
            if ver is None:
                continue
            key = tuple(int(p) for p in ver.split("."))
            existing = by_version.get(key)
            if existing is None:
                by_version[key] = path
                continue
            if "release" in path.parts and "release" not in existing.parts:
                by_version[key] = path
    return sorted(by_version.values(), key=_full_uf2_version_sort_key, reverse=True)


def bundled_vintage_radio_full_uf2() -> Optional[Path]:
    """Return the newest one-file full-flash Vintage Radio UF2, if any are bundled."""
    matches = list_bundled_vintage_radio_full_uf2()
    return matches[0] if matches else None


def full_uf2_version_string(path: Path) -> Optional[str]:
    """Semver from ``vintage-radio-firmware-X.Y.Z-full.uf2`` filename, or ``None``."""
    m = _FULL_UF2_VERSION_RE.match(path.name)
    if m is None:
        return None
    return m.group("ver")


def vintage_radio_firmware_entry_id(version: str) -> str:
    """Stable Install Firmware list id for a bundled Vintage Radio UF2 version."""
    return "vintage_radio_" + version.replace(".", "_")


def is_older_bundled_vintage_radio_full_uf2(path: Path) -> bool:
    """True when *path* is a bundled image but not the newest shipped release."""
    if not path.is_file():
        return False
    newest = bundled_vintage_radio_full_uf2()
    if newest is None:
        return False
    ver_path = full_uf2_version_string(path)
    ver_newest = full_uf2_version_string(newest)
    if ver_path and ver_newest:
        return ver_path != ver_newest
    return path.resolve() != newest.resolve()


def cached_micropython_uf2() -> Optional[Path]:
    """Latest cached official RPI_PICO MicroPython UF2, if any."""
    cache = _micropython_cache_dir()
    matches = sorted(cache.glob("RPI_PICO-*.uf2"), reverse=True)
    return matches[0] if matches else None


def fetch_micropython_uf2(*, force: bool = False) -> Path:
    """Download (or reuse cache) the newest RPI_PICO MicroPython UF2."""
    if not force:
        existing = cached_micropython_uf2()
        if existing is not None:
            return existing

    cache = _micropython_cache_dir()
    req = urllib.request.Request(MICROPYTHON_PICO_URL, headers={"User-Agent": "VintageRadio/1.0"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        html = resp.read().decode("utf-8", errors="replace")

    links = _UF2_PATTERN.findall(html)
    if not links:
        raise RuntimeError(f"No RPI_PICO .uf2 links found on {MICROPYTHON_PICO_URL}")

    href = links[0]
    filename = href.rsplit("/", 1)[-1]
    out = cache / filename
    if out.is_file():
        return out

    download_url = "https://micropython.org" + href
    req2 = urllib.request.Request(download_url, headers={"User-Agent": "VintageRadio/1.0"})
    with urllib.request.urlopen(req2, timeout=120) as resp:
        out.write_bytes(resp.read())
    return out
