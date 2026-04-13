"""Experimental: pack a synced SD folder tree into a FAT32 disk image for faster flashing.

Uses ``pyfatfs`` only: ``PyFat.mkfs`` creates the FAT32 image (no system ``mkfs.fat`` / WSL).
"""

from __future__ import annotations

import errno
import importlib
import importlib.util
import posixpath
import sys
from pathlib import Path
from typing import Any, Callable, Optional, Tuple

# Minimum image size for FAT32 (PyFat FAT32 layout)
_MIN_IMAGE_BYTES = 64 * 1024 * 1024


def pyfatfs_dependency_message() -> Optional[str]:
    """Return None if pyfatfs imports succeed, else a message for the user (install hint)."""
    if getattr(sys, "frozen", False):
        try:
            from pyfatfs.PyFat import PyFat  # noqa: F401
            from pyfatfs.PyFatFS import PyFatFS  # noqa: F401
        except ImportError as e:
            return (
                "SD disk image export could not load pyfatfs. This build may be missing bundled "
                "dependencies; rebuild the app with pyfatfs included, or run from source.\n\n"
                f"Import error: {e!s}"
            )
        return None

    exe = sys.executable
    prefix = sys.prefix
    spec = importlib.util.find_spec("pyfatfs")

    steps = (
        ("pyfatfs", "import pyfatfs"),
        ("pyfatfs.PyFat", "from pyfatfs.PyFat import PyFat"),
        ("pyfatfs.PyFatFS", "from pyfatfs.PyFatFS import PyFatFS"),
    )
    for mod_name, step_label in steps:
        try:
            importlib.import_module(mod_name)
        except ImportError as e:
            detail = str(e).strip() or repr(e)
            spec_hint = ""
            if "pkg_resources" in detail:
                spec_hint = (
                    "\nThe 'fs' package (used by pyfatfs) imports pkg_resources. Setuptools 82+ "
                    "removed that module; you need setuptools 81.x or older:\n"
                    f'  "{exe}" -m pip install "setuptools>=65,<82"\n\n'
                    "Or reinstall from the project requirements (pins setuptools<82):\n"
                    f'  "{exe}" -m pip install -r requirements.txt\n'
                )
            elif spec is not None and mod_name != "pyfatfs":
                spec_hint = (
                    "\nThe pyfatfs package is visible, but a sub-import failed. "
                    "A dependency (often the 'fs' package) may be broken. Try:\n"
                    f'  "{exe}" -m pip install --force-reinstall "fs>=2.4" pyfatfs\n'
                )
            lines = [
                "SD disk image export could not load pyfatfs.",
                "",
                "This GUI process is using:",
                f"  Executable: {exe}",
                f"  sys.prefix: {prefix}",
                "",
                f"Failed step: {step_label}",
                f"Error: {detail}",
                spec_hint,
                "Confirm pip targets this same interpreter:",
                f'  "{exe}" -m pip show pyfatfs',
                "",
                "If needed, reinstall into this environment:",
                f'  "{exe}" -m pip install --force-reinstall -r requirements.txt',
            ]
            return "\n".join(s for s in lines if s)
    return None


def _fat_volume_label(label: str) -> str:
    """FAT volume label: up to 11 ASCII characters."""
    s = "".join(c if 32 <= ord(c) < 127 else "_" for c in label.strip())[:11]
    return s or "NO NAME"


def estimate_folder_bytes(root: Path) -> int:
    total = 0
    try:
        for p in root.rglob("*"):
            if p.is_file():
                try:
                    total += p.stat().st_size
                except OSError:
                    pass
    except OSError:
        pass
    return total


def suggest_image_size_bytes(sd_root: Path) -> int:
    """Total data + ~15% FAT overhead + small margin, rounded up to 64 MiB."""
    data = estimate_folder_bytes(sd_root)
    raw = int(data * 1.15) + 32 * 1024 * 1024
    return max(_MIN_IMAGE_BYTES, ((raw + _MIN_IMAGE_BYTES - 1) // _MIN_IMAGE_BYTES) * _MIN_IMAGE_BYTES)


def create_fat32_image_file(
    image_path: Path,
    size_bytes: int,
    *,
    label: str = "VINTAGERADIO",
) -> Tuple[bool, str]:
    """Allocate a file of *size_bytes* and format it as FAT32 using ``pyfatfs.PyFat.mkfs``."""
    if size_bytes < _MIN_IMAGE_BYTES:
        return False, f"Image size must be at least {_MIN_IMAGE_BYTES // (1024 * 1024)} MiB for FAT32."
    try:
        from pyfatfs.PyFat import PyFat
    except ImportError:
        return False, "Install the pyfatfs package: pip install pyfatfs"

    image_path = Path(image_path).resolve()
    image_path.parent.mkdir(parents=True, exist_ok=True)
    if image_path.exists():
        try:
            image_path.unlink()
        except OSError as e:
            return False, str(e)

    try:
        open(image_path, "wb").close()
    except OSError as e:
        return False, str(e)

    vol = _fat_volume_label(label)
    pf: Any = None
    try:
        pf = PyFat()
        pf.mkfs(str(image_path), PyFat.FAT_TYPE_FAT32, size=size_bytes, label=vol)
    except Exception as e:
        try:
            image_path.unlink(missing_ok=True)
        except OSError:
            pass
        return False, (str(e) or "PyFat mkfs failed")[:800]
    finally:
        if pf is not None:
            try:
                pf.close()
            except Exception:
                pass
    return True, ""


def _fat_makedirs(fs: Any, path: str) -> None:
    path = path.strip("/")
    if not path:
        return
    parts = path.split("/")
    acc = ""
    for part in parts:
        acc = f"{acc}/{part}" if acc else f"/{part}"
        try:
            fs.makedir(acc, recreate=True)
        except Exception as e:
            try:
                from fs.errors import DirectoryExists

                if isinstance(e, DirectoryExists):
                    continue
            except ImportError:
                pass
            if getattr(e, "errno", None) == errno.EEXIST:
                continue
            raise


def copy_sd_folder_into_fat_image(
    sd_root: Path,
    image_path: Path,
    *,
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
    should_cancel: Optional[Callable[[], bool]] = None,
) -> Tuple[bool, str]:
    """Copy all files under *sd_root* into an existing FAT32 *image_path*."""
    try:
        from pyfatfs.PyFatFS import PyFatFS
    except ImportError:
        return False, "Install the pyfatfs package: pip install pyfatfs"

    sd_root = Path(sd_root).resolve()
    image_path = Path(image_path).resolve()
    if not sd_root.is_dir():
        return False, f"SD folder not found: {sd_root}"

    fs = PyFatFS(str(image_path), read_only=False)
    try:
        files = sorted([p for p in sd_root.rglob("*") if p.is_file()])
        total = len(files)
        if total == 0:
            return False, "No files found under the SD folder. Sync to the card (or folder) first."

        for i, src_path in enumerate(files):
            if should_cancel and should_cancel():
                return False, "Cancelled"
            rel = src_path.relative_to(sd_root)
            fat_path = "/" + rel.as_posix().replace("\\", "/")
            fat_path = fat_path.replace("//", "/")
            parent = posixpath.dirname(fat_path)
            if parent and parent != "/":
                _fat_makedirs(fs, parent.strip("/"))
            data = src_path.read_bytes()
            with fs.openbin(fat_path, "w") as out:
                out.write(data)
            if progress_callback and (i % 10 == 0 or i == total - 1):
                progress_callback(
                    i + 1,
                    total,
                    f"Writing disk image ({i + 1}/{total} files)...",
                )
        fs.close()
        return True, ""
    except Exception as e:
        try:
            fs.close()
        except Exception:
            pass
        return False, str(e)


def run_experimental_sd_disk_image_export(
    sd_root: Path,
    image_path: Path,
    *,
    size_bytes: Optional[int] = None,
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
    should_cancel: Optional[Callable[[], bool]] = None,
) -> Tuple[bool, str]:
    """Create a FAT32 image and copy *sd_root* into it."""
    sd_root = Path(sd_root).resolve()
    nfiles = len([p for p in sd_root.rglob("*") if p.is_file()])
    content_size = suggest_image_size_bytes(sd_root)
    if size_bytes is None:
        size_bytes = content_size
    elif size_bytes < content_size:
        # Caller passed a disk size that is somehow smaller than the content — fall back
        # to the content-derived size rather than silently producing a truncated image.
        size_bytes = content_size
    ok, err = create_fat32_image_file(image_path, size_bytes)
    if not ok:
        try:
            image_path.unlink(missing_ok=True)
        except OSError:
            pass
        return False, err
    if progress_callback and nfiles > 0:
        progress_callback(
            0,
            nfiles,
            "FAT32 image created — packing files into disk image…",
        )
    ok2, err2 = copy_sd_folder_into_fat_image(
        sd_root,
        image_path,
        progress_callback=progress_callback,
        should_cancel=should_cancel,
    )
    if not ok2:
        try:
            image_path.unlink(missing_ok=True)
        except OSError:
            pass
        return False, err2
    return True, ""
