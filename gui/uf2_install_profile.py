"""Classify UF2 images for install UX (bare MicroPython runtime vs frozen app)."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, FrozenSet, Optional, Set

# Frozen apps (e.g. ZBVR) can place module-name strings late in a multi-MB image.
_UF2_SCAN_BYTES = 4 * 1024 * 1024

# ``name.py`` tokens embedded in official RPI_PICO UF2 + common frozen stdlib drift.
_BARE_MICROPYTHON_FROZEN_MODULES: FrozenSet[str] = frozenset(
    {
        "_boot.py",
        "_boot_fat.py",
        "main.py",
        "asyncio/__init__.py",
        "asyncio/core.py",
        "asyncio/event.py",
        "asyncio/funcs.py",
        "asyncio/lock.py",
        "asyncio/stream.py",
        "dht.py",
        "ds18x20.py",
        "neopixel.py",
        "onewire.py",
        "rp2.py",
        "uasyncio.py",
        "machine.py",
        "os.py",
        "gc.py",
        "sys.py",
        "time.py",
        "io.py",
        "struct.py",
        "json.py",
        "array.py",
        "collections.py",
        "select.py",
        "errno.py",
        "builtins.py",
        "micropython.py",
        "ubinascii.py",
        "uctypes.py",
        "framebuf.py",
        "heapq.py",
        "random.py",
        "math.py",
        "bisect.py",
        "hashlib.py",
        "ssl.py",
        "socket.py",
        "network.py",
        "bluetooth.py",
    }
)

_PY_MODULE_RE = re.compile(rb"(?:[A-Za-z_][\w]*/)*[A-Za-z_][\w]*\.py\b")


def _extract_embedded_py_modules(data: bytes) -> Set[str]:
    """Return ``module.py`` paths/names found in UF2 payload (frozen module listings)."""
    return {
        m.group(0).decode("ascii", "replace").lower()
        for m in _PY_MODULE_RE.finditer(data)
    }


def _is_allowed_bare_micropython_module(name: str) -> bool:
    if name in _BARE_MICROPYTHON_FROZEN_MODULES:
        return True
    if name.startswith("asyncio/"):
        return True
    return False


def _application_py_modules(modules: Set[str]) -> Set[str]:
    """Modules present in the UF2 that are not typical bare-MicroPython frozen stdlib."""
    return {m for m in modules if not _is_allowed_bare_micropython_module(m)}


def _has_micropython_boot_modules(modules: Set[str]) -> bool:
    return "_boot.py" in modules or "_boot_fat.py" in modules


def _read_uf2_payload(path: Path) -> bytes:
    try:
        size = path.stat().st_size
    except OSError:
        return b""
    read_len = min(size, _UF2_SCAN_BYTES)
    try:
        with path.open("rb") as handle:
            return handle.read(read_len)
    except OSError:
        return b""


def uf2_image_supports_attached_config(uf2_path: Path) -> bool:
    """True when a UF2 is a bare MicroPython runtime suitable for post-flash config copy.

    Detection inspects embedded frozen ``*.py`` module names in the binary — official
    bare MicroPython UF2 images only carry boot/stdlib modules, while frozen application
    builds (e.g. ZBVR) add project ``*.py`` files such as ``config.py`` and ``dfplayer.py``.
    """
    path = Path(uf2_path)
    if not path.is_file() or path.suffix.lower() != ".uf2":
        return False

    chunk = _read_uf2_payload(path)
    if not chunk:
        return False

    modules = _extract_embedded_py_modules(chunk)
    if not _has_micropython_boot_modules(modules):
        return False

    if _application_py_modules(modules):
        return False

    return True


def uf2_image_likely_micropython(uf2_path: Path) -> bool:
    """Backward-compatible alias — see ``uf2_image_supports_attached_config``."""
    return uf2_image_supports_attached_config(uf2_path)


def firmware_entry_supports_config(entry: Optional[Dict[str, Any]]) -> bool:
    """True when attached config / mpremote copy is meaningful for this firmware entry."""
    if not entry:
        return False
    kind = str(entry.get("kind") or "").lower()
    if kind in ("folder", "micropython"):
        return True
    if kind == "remote_uf2":
        if "supports_config" in entry:
            return bool(entry.get("supports_config"))
        return False
    if kind == "uf2":
        path = str(entry.get("path") or "").strip()
        if path and Path(path).is_file():
            return uf2_image_supports_attached_config(Path(path))
        if "supports_config" in entry:
            return bool(entry.get("supports_config"))
        return False
    return False
