"""Bundled / cached Pico firmware assets for Install Firmware."""

from __future__ import annotations

import re
import urllib.request
from pathlib import Path
from typing import Optional

from gui.resource_paths import project_root

_UF2_PATTERN = re.compile(r'href="(/resources/firmware/RPI_PICO[^"]*\.uf2)"')
MICROPYTHON_PICO_URL = "https://micropython.org/download/RPI_PICO/"
FLASH_NUKE_URL = "https://datasheets.raspberrypi.com/soft/flash_nuke.uf2"


def _flash_nuke_cache_dir() -> Path:
    cache = project_root() / "data" / "firmware_cache" / "flash_nuke"
    cache.mkdir(parents=True, exist_ok=True)
    return cache


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
    cache = project_root() / "data" / "firmware_cache" / "micropython"
    cache.mkdir(parents=True, exist_ok=True)
    return cache


def bundled_vintage_radio_full_uf2() -> Optional[Path]:
    """Return a one-file full-flash Vintage Radio UF2 if shipped or built locally."""
    root = project_root()
    for base in (root / "firmware" / "release", root / "dist"):
        if not base.is_dir():
            continue
        matches = sorted(base.glob("vintage-radio-firmware-*-full.uf2"), reverse=True)
        if matches and matches[0].is_file():
            return matches[0]
    return None


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
