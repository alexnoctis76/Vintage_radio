#!/usr/bin/env python3
"""Integrity checks for a built macOS ``.app`` bundle (no GUI, no hardware).

These catch packaging regressions that a plain "app starts and answers MCP ping" smoke
test misses, each of which has shipped broken before:

* ``Info.plist`` version hardcoded/stale, or ``CFBundleExecutable`` missing / not executable
* ``Contents/Frameworks/Python`` (and other framework symlinks) flattened into text files
  by a naive zip extract, so the updated app dies at launch with "not a valid mach-o file"
* ``mpremote_helper`` crashing on every call because it bundles ``mpy_cross`` without the
  ``mpy-cross`` binary (mpremote only guards that import with ``except ImportError``)
* bundled ``mpy-cross`` missing its executable bit or failing to compile

Used by ``scripts/packaged_app_smoke.py`` (post-build) and ``tests/scripts``.
"""

from __future__ import annotations

import os
import plistlib
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

CheckResult = Dict[str, Any]

_MACHO_MAGICS = {
    b"\xcf\xfa\xed\xfe",  # 64-bit little endian
    b"\xce\xfa\xed\xfe",  # 32-bit little endian
    b"\xfe\xed\xfa\xcf",
    b"\xfe\xed\xfa\xce",
    b"\xca\xfe\xba\xbe",  # universal
    b"\xbe\xba\xfe\xca",
}

_HELPER_FAILURE_MARKERS = ("No mpy-cross binary", "Traceback (most recent call last)")


def _result(name: str, ok: bool, detail: str = "", **extra: Any) -> CheckResult:
    row: CheckResult = {"name": name, "ok": bool(ok)}
    if detail:
        row["detail"] = detail
    row.update(extra)
    return row


def is_macho_file(path: Path) -> bool:
    """True when *path* (symlinks followed) starts with a Mach-O / universal magic."""
    try:
        with open(path, "rb") as fh:
            return fh.read(4) in _MACHO_MAGICS
    except OSError:
        return False


def read_plist(app: Path) -> Dict[str, Any]:
    plist_path = app / "Contents" / "Info.plist"
    return plistlib.loads(plist_path.read_bytes())


def expected_plist_version(project_version: str) -> str:
    """``v1.1.0-upgrade-test`` -> ``1.1.0-upgrade-test`` (what the spec writes to the plist)."""
    v = (project_version or "").strip()
    return v[1:] if v.startswith("v") else v


def check_plist_version(app: Path, project_version: str) -> CheckResult:
    try:
        actual = str(read_plist(app).get("CFBundleShortVersionString", ""))
    except (OSError, ValueError) as exc:
        return _result("plist_version_matches_project", False, f"cannot read Info.plist: {exc}")
    want = expected_plist_version(project_version)
    return _result(
        "plist_version_matches_project",
        actual == want,
        f"CFBundleShortVersionString={actual!r} expected={want!r}",
    )


def check_main_executable(app: Path) -> CheckResult:
    """``CFBundleExecutable`` exists, is executable, and is a Mach-O binary."""
    try:
        exe_name = str(read_plist(app).get("CFBundleExecutable") or "")
    except (OSError, ValueError) as exc:
        return _result("main_executable_valid", False, f"cannot read Info.plist: {exc}")
    if not exe_name:
        return _result("main_executable_valid", False, "CFBundleExecutable missing from Info.plist")
    exe = app / "Contents" / "MacOS" / exe_name
    if not exe.is_file():
        return _result("main_executable_valid", False, f"{exe} does not exist")
    if not os.access(exe, os.X_OK):
        return _result("main_executable_valid", False, f"{exe} is not executable (codesign --remove strips +x)")
    if not is_macho_file(exe):
        return _result("main_executable_valid", False, f"{exe} is not a Mach-O binary")
    return _result("main_executable_valid", True, str(exe))


def check_python_shared_library(app: Path) -> CheckResult:
    """PyInstaller macOS bundles expose ``Frameworks/Python`` (symlink) or ``libpython3.*.dylib``."""
    fw = app / "Contents" / "Frameworks"
    lib = fw / "Python"
    if lib.exists():
        if not is_macho_file(lib):
            return _result(
                "python_shared_library_valid",
                False,
                f"{lib} is not a Mach-O file (symlink flattened to text by a bad extract?)",
            )
        return _result("python_shared_library_valid", True, str(lib.resolve()))
    for candidate in sorted(fw.glob("libpython3.*.dylib")):
        if is_macho_file(candidate):
            return _result("python_shared_library_valid", True, str(candidate))
    return _result(
        "python_shared_library_valid",
        False,
        f"{fw / 'Python'} missing and no libpython3.*.dylib under Frameworks",
    )


def collect_symlinks(root: Path) -> Dict[str, str]:
    """Map ``relative/path -> link target`` for every symlink under *root*."""
    links: Dict[str, str] = {}
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        for name in [*dirnames, *filenames]:
            p = Path(dirpath) / name
            if p.is_symlink():
                links[str(p.relative_to(root))] = os.readlink(p)
    return links


def check_helper_runs(app: Path, *, timeout_s: float = 60.0) -> CheckResult:
    """``mpremote_helper`` must start and run a command that needs no device."""
    helper = Path(os.path.abspath(app)) / "Contents" / "MacOS" / "mpremote_helper" / "mpremote_helper"
    if not helper.is_file():
        return _result("mpremote_helper_runs", False, f"{helper} missing")
    try:
        proc = subprocess.run(
            [str(helper), "devs"],
            capture_output=True,
            text=True,
            timeout=timeout_s,
            cwd=tempfile.gettempdir(),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return _result("mpremote_helper_runs", False, f"could not run helper: {exc}")
    combined = (proc.stdout or "") + (proc.stderr or "")
    bad = next((m for m in _HELPER_FAILURE_MARKERS if m in combined), None)
    ok = proc.returncode == 0 and bad is None
    detail = f"rc={proc.returncode}"
    if bad:
        detail += f" output contains {bad!r}: {combined.strip()[:300]}"
    elif proc.returncode != 0:
        detail += f" {combined.strip()[:300]}"
    return _result("mpremote_helper_runs", ok, detail)


def check_mpy_cross_runs(app: Path) -> CheckResult:
    """Bundled ``mpy-cross`` must compile a trivial module for the RP2040 (armv6m)."""
    candidates = [
        Path(os.path.abspath(app)) / "Contents" / "Frameworks" / "mpy_cross" / "mpy-cross",
        Path(os.path.abspath(app)) / "Contents" / "Resources" / "mpy_cross" / "mpy-cross",
    ]
    binary = next((c for c in candidates if c.is_file()), None)
    if binary is None:
        return _result("mpy_cross_compiles", False, "mpy-cross binary not found in bundle")
    with tempfile.TemporaryDirectory(prefix="vr_mpy_check_") as td:
        src = Path(td) / "t.py"
        out = Path(td) / "t.mpy"
        src.write_text("print(1)\n", encoding="utf-8")
        try:
            proc = subprocess.run(
                [str(binary), "-march=armv6m", "-o", str(out), str(src)],
                capture_output=True,
                text=True,
                timeout=30,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return _result("mpy_cross_compiles", False, f"could not run {binary}: {exc}")
        ok = proc.returncode == 0 and out.is_file() and out.stat().st_size > 0
        return _result("mpy_cross_compiles", ok, f"rc={proc.returncode} {(proc.stderr or '').strip()[:200]}")


def check_helper_bundle_consistent(app: Path) -> CheckResult:
    """If the helper bundles the ``mpy_cross`` package it must also ship the binary."""
    internal = app / "Contents" / "MacOS" / "mpremote_helper" / "_internal"
    pkg = internal / "mpy_cross"
    if not pkg.exists():
        return _result("mpremote_helper_bundle_consistent", True, "helper does not bundle mpy_cross")
    has_binary = any(pkg.glob("mpy-cross*"))
    return _result(
        "mpremote_helper_bundle_consistent",
        has_binary,
        "mpy_cross package present with binary" if has_binary
        else "mpy_cross package bundled WITHOUT its binary; import raises SystemExit",
    )


def run_static_checks(app: Path, project_version: str) -> List[CheckResult]:
    """All checks that only read/execute helpers inside the bundle."""
    checks: List[Callable[[], CheckResult]] = [
        lambda: check_plist_version(app, project_version),
        lambda: check_main_executable(app),
        lambda: check_python_shared_library(app),
        lambda: check_helper_bundle_consistent(app),
        lambda: check_helper_runs(app),
        lambda: check_mpy_cross_runs(app),
    ]
    return [c() for c in checks]


def zip_and_extract_like_updater(app: Path, workdir: Path) -> Tuple[CheckResult, Optional[Path]]:
    """Zip *app* the way release assets are built, extract it via the real updater code path.

    Returns a result comparing symlinks before/after plus the extracted ``.app`` path.
    """
    from gui import updater

    zip_path = workdir / "release.zip"
    extract_dir = workdir / "extracted"
    try:
        subprocess.run(
            ["ditto", "-c", "-k", "--sequesterRsrc", "--keepParent", str(app), str(zip_path)],
            check=True,
            capture_output=True,
        )
        updater._extract_zip(zip_path, extract_dir)
    except (OSError, subprocess.CalledProcessError, RuntimeError) as exc:
        return _result("update_zip_roundtrip_symlinks", False, f"zip/extract failed: {exc}"), None

    extracted = updater._pick_macos_app_bundle_from_root(extract_dir)
    if extracted is None:
        return _result("update_zip_roundtrip_symlinks", False, "no .app found after extract"), None

    before = collect_symlinks(app)
    after = collect_symlinks(extracted)
    lost = sorted(k for k in before if after.get(k) != before[k])
    if lost:
        sample = ", ".join(lost[:5])
        return _result(
            "update_zip_roundtrip_symlinks",
            False,
            f"{len(lost)} of {len(before)} symlinks lost/changed by updater extract, e.g. {sample}",
        ), extracted
    return _result(
        "update_zip_roundtrip_symlinks", True, f"{len(before)} symlinks preserved"
    ), extracted


def cleanup(path: Path) -> None:
    shutil.rmtree(path, ignore_errors=True)
