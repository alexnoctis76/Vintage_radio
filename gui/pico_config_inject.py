"""Post-flash config file injection for Pico (any UF2, any file type)."""

from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

CONFIG_SIZE_CONFIRM_BYTES = 512 * 1024
_WINDOWS_EXE_SUFFIXES = {".exe", ".dll", ".msi"}


def default_config_remote(local_path: Path) -> str:
    return local_path.name.replace("\\", "/")


def local_file_fingerprint(path: Path) -> Tuple[int, str]:
    """Return (size_bytes, sha256_hex) for read-back verification."""
    data = path.read_bytes()
    return len(data), hashlib.sha256(data).hexdigest()


def validate_config_local_file(
    local_path: Path,
    *,
    uf2_path: Optional[Path] = None,
) -> Optional[str]:
    """Return error message if file cannot be injected; None if OK."""
    if not local_path.is_file():
        return f"Config file not found: {local_path}"
    if uf2_path is not None:
        try:
            if local_path.resolve() == uf2_path.resolve():
                return "Config file cannot be the same as the UF2 being flashed."
        except OSError:
            pass
    if local_path.suffix.lower() == ".py":
        try:
            ast.parse(local_path.read_text(encoding="utf-8"))
        except SyntaxError as exc:
            return f"Config Python syntax error: {exc}"
        except UnicodeDecodeError as exc:
            return f"Config file is not valid UTF-8: {exc}"
        except OSError as exc:
            return f"Could not read config file: {exc}"
    return None


def needs_config_inject_confirm(local_path: Path) -> Tuple[bool, str]:
    """Return (needs_confirm, reason) for unusual config files."""
    if local_path.suffix.lower() in _WINDOWS_EXE_SUFFIXES:
        return True, "This file type is unusual for Pico configuration."
    try:
        size = local_path.stat().st_size
    except OSError:
        return False, ""
    if size > CONFIG_SIZE_CONFIRM_BYTES:
        return True, f"Config file is large ({size // 1024} KB)."
    return False, ""


def _iter_bundle_files(folder: Path) -> Iterable[Tuple[Path, str]]:
    manifest = folder / "pico_inject_manifest.json"
    if manifest.is_file():
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            data = None
        if isinstance(data, dict):
            for item in data.get("files") or []:
                if not isinstance(item, dict):
                    continue
                rel = str(item.get("local") or "").strip()
                remote = str(item.get("remote") or "").strip().replace("\\", "/")
                if not rel or not remote:
                    continue
                local = folder / rel
                if local.is_file():
                    yield local, remote
            return
    for fp in sorted(folder.rglob("*")):
        if not fp.is_file():
            continue
        rel = fp.relative_to(folder).as_posix()
        if rel.startswith(".git/") or "__pycache__" in rel:
            continue
        if fp.name == "pico_inject_manifest.json":
            continue
        yield fp, rel


def build_injections_from_entry(
    entry: Optional[Dict[str, Any]],
    *,
    uf2_path: Optional[Path] = None,
) -> List[Tuple[Path, str]]:
    """Build (local, remote) injection pairs from a firmware list entry."""
    from gui.uf2_install_profile import firmware_entry_supports_config

    if not entry or not entry.get("inject_config", True):
        return []
    if not firmware_entry_supports_config(entry):
        return []
    raw = str(entry.get("config_path") or "").strip()
    if not raw:
        return []
    local = Path(raw)
    if not local.exists():
        return []
    if local.is_dir():
        return list(_iter_bundle_files(local))
    remote = str(entry.get("config_remote") or default_config_remote(local)).strip()
    remote = remote.replace("\\", "/").lstrip("/")
    if not remote:
        remote = default_config_remote(local)
    return [(local, remote)]


def inject_pico_config_files(
    mpremote_cmd: List[str],
    injections: List[Tuple[Path, str]],
    *,
    cwd: Optional[str] = None,
    timeout: int = 20,
    wait_serial_ready: Callable[..., Optional[str]],
    run_mpremote_cp: Callable[[Path, str], bool],
    progress_callback: Optional[Callable[..., Any]] = None,
    overwrite_existing: bool = True,
    read_remote_exists: Optional[Callable[[str], bool]] = None,
) -> None:
    """Copy config files to Pico flash after UF2 flash or folder install."""
    if not injections:
        return
    wait_err = wait_serial_ready(
        mpremote_cmd,
        cwd=cwd,
        progress_callback=progress_callback,
        after_uf2_flash=True,
    )
    if wait_err:
        raise RuntimeError(wait_err)

    total = len(injections)
    for idx, (local_fp, remote_rel) in enumerate(injections, start=1):
        err = validate_config_local_file(local_fp, uf2_path=None)
        if err:
            raise RuntimeError(err)
        remote_rel = remote_rel.replace("\\", "/")
        remote_arg = ":" + remote_rel if not remote_rel.startswith(":") else remote_rel
        if (
            not overwrite_existing
            and read_remote_exists is not None
            and read_remote_exists(remote_rel)
        ):
            if progress_callback:
                progress_callback(idx - 1, total, f"Skipping existing {remote_rel}")
            continue
        if progress_callback:
            progress_callback(
                idx - 1,
                total,
                f"Injecting config ({idx}/{total}): {local_fp.name} → {remote_rel}",
            )
        if not run_mpremote_cp(local_fp, remote_arg):
            raise RuntimeError(f"Failed to copy config to {remote_rel}")
    if progress_callback:
        progress_callback(total, total, "Config injection complete")
