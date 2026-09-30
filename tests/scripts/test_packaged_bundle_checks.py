"""Regression tests for macOS packaging problems that once shipped broken.

Unit tests build tiny synthetic ``.app`` folders so every failure mode is proven to be
*detected*. The integration test at the bottom runs the same checks against a real
``dist/*.app`` when one has been built locally.
"""

from __future__ import annotations

import os
import plistlib
import stat
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import packaged_bundle_checks as bc  # noqa: E402

MACHO = b"\xcf\xfa\xed\xfe" + b"\x00" * 64
pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="macOS bundle layout")


def _make_app(
    tmp_path: Path,
    *,
    version: str = "1.1.0",
    exe_name: str = "Vintage Radio",
    exe_mode: int = 0o755,
    python_lib: str = "macho",  # macho | text | missing
) -> Path:
    app = tmp_path / "Vintage Radio-x86_64.app"
    macos = app / "Contents" / "MacOS"
    fw = app / "Contents" / "Frameworks"
    macos.mkdir(parents=True)
    fw.mkdir(parents=True)
    (app / "Contents" / "Info.plist").write_bytes(
        plistlib.dumps(
            {"CFBundleExecutable": exe_name, "CFBundleShortVersionString": version}
        )
    )
    exe = macos / exe_name
    exe.write_bytes(MACHO)
    exe.chmod(exe_mode)

    real = fw / "Python.framework" / "Versions" / "3.14" / "Python"
    real.parent.mkdir(parents=True)
    real.write_bytes(MACHO)
    if python_lib == "macho":
        (fw / "Python").symlink_to("Python.framework/Versions/3.14/Python")
    elif python_lib == "text":
        # What zipfile.extractall produces for a symlink entry.
        (fw / "Python").write_text("Python.framework/Versions/3.14/Python")
    return app


def test_valid_bundle_passes_plist_executable_and_python_checks(tmp_path):
    app = _make_app(tmp_path)
    assert bc.check_plist_version(app, "v1.1.0")["ok"]
    assert bc.check_main_executable(app)["ok"]
    assert bc.check_python_shared_library(app)["ok"]


def test_plist_version_mismatch_is_detected(tmp_path):
    """The spec once hardcoded CFBundleShortVersionString to 1.0.0 for every build."""
    app = _make_app(tmp_path, version="1.0.0")
    assert not bc.check_plist_version(app, "v1.1.0-upgrade-test")["ok"]


def test_plist_version_strips_leading_v():
    assert bc.expected_plist_version("v1.2.3-beta") == "1.2.3-beta"
    assert bc.expected_plist_version("1.2.3") == "1.2.3"


def test_non_executable_main_binary_is_detected(tmp_path):
    """codesign --remove strips the execute bit; `open` then fails silently."""
    app = _make_app(tmp_path, exe_mode=0o644)
    assert not bc.check_main_executable(app)["ok"]


def test_missing_cf_bundle_executable_file_is_detected(tmp_path):
    app = _make_app(tmp_path)
    (app / "Contents" / "MacOS" / "Vintage Radio").unlink()
    assert not bc.check_main_executable(app)["ok"]


def test_flattened_python_symlink_is_detected(tmp_path):
    """Extracting the update zip with zipfile turned Frameworks/Python into a text file."""
    app = _make_app(tmp_path, python_lib="text")
    res = bc.check_python_shared_library(app)
    assert not res["ok"]
    assert "not a Mach-O" in res["detail"]


def test_missing_python_library_is_detected(tmp_path):
    app = _make_app(tmp_path, python_lib="missing")
    assert not bc.check_python_shared_library(app)["ok"]


def test_helper_bundling_mpy_cross_without_binary_is_detected(tmp_path):
    """mpremote_helper died on every call: mpy_cross module present, binary absent."""
    app = _make_app(tmp_path)
    pkg = app / "Contents" / "MacOS" / "mpremote_helper" / "_internal" / "mpy_cross"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("")
    assert not bc.check_helper_bundle_consistent(app)["ok"]
    (pkg / "mpy-cross").write_bytes(MACHO)
    assert bc.check_helper_bundle_consistent(app)["ok"]


def test_helper_without_mpy_cross_package_is_consistent(tmp_path):
    app = _make_app(tmp_path)
    (app / "Contents" / "MacOS" / "mpremote_helper" / "_internal").mkdir(parents=True)
    assert bc.check_helper_bundle_consistent(app)["ok"]


def _fake_helper(app: Path, script: str) -> None:
    helper = app / "Contents" / "MacOS" / "mpremote_helper" / "mpremote_helper"
    helper.parent.mkdir(parents=True, exist_ok=True)
    helper.write_text("#!/bin/sh\n" + script + "\n")
    helper.chmod(helper.stat().st_mode | stat.S_IXUSR)


def test_helper_that_exits_with_mpy_cross_error_is_detected(tmp_path):
    app = _make_app(tmp_path)
    _fake_helper(app, 'echo "Error: No mpy-cross binary found in: x" >&2; exit 1')
    res = bc.check_helper_runs(app, timeout_s=10)
    assert not res["ok"]
    assert "mpy-cross" in res["detail"]


def test_helper_that_runs_cleanly_passes(tmp_path):
    app = _make_app(tmp_path)
    _fake_helper(app, "exit 0")
    assert bc.check_helper_runs(app, timeout_s=10)["ok"]


def test_missing_helper_is_detected(tmp_path):
    app = _make_app(tmp_path)
    assert not bc.check_helper_runs(app, timeout_s=5)["ok"]


def test_updater_extract_preserves_symlinks(tmp_path):
    """Real ditto zip -> real updater._extract_zip: symlinks must survive."""
    from gui import updater

    app = _make_app(tmp_path / "src")
    zip_path = tmp_path / "u.zip"
    subprocess.run(
        ["ditto", "-c", "-k", "--sequesterRsrc", "--keepParent", str(app), str(zip_path)],
        check=True,
    )
    out = tmp_path / "out"
    updater._extract_zip(zip_path, out)
    extracted = next(out.glob("*.app"))
    lib = extracted / "Contents" / "Frameworks" / "Python"
    assert lib.is_symlink()
    assert bc.check_python_shared_library(extracted)["ok"]


def test_zipfile_extract_would_flatten_symlinks(tmp_path):
    """Documents WHY ditto is required: pure-Python extraction destroys the symlink."""
    import zipfile

    app = _make_app(tmp_path / "src")
    zip_path = tmp_path / "u.zip"
    subprocess.run(
        ["ditto", "-c", "-k", "--sequesterRsrc", "--keepParent", str(app), str(zip_path)],
        check=True,
    )
    out = tmp_path / "naive"
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(out)
    lib = next(out.glob("*.app")) / "Contents" / "Frameworks" / "Python"
    assert not lib.is_symlink()
    assert not bc.check_python_shared_library(next(out.glob("*.app")))["ok"]


def test_apply_script_launches_cf_bundle_executable_not_bundle_stem(tmp_path):
    """The relaunch script once exec'd 'Vintage Radio-x86_64' (the folder stem) and failed."""
    from unittest import mock

    from gui import updater

    src = _make_app(tmp_path / "src")
    target = _make_app(tmp_path / "dst")
    with mock.patch("gui.updater.subprocess.Popen") as popen:
        updater._launch_macos_apply_script(src, target, pid=1)
    script = (src.parent / "apply_update.sh").read_text()
    assert "Contents/MacOS/Vintage Radio'" in script
    assert "Vintage Radio-x86_64'" not in script.split("INNER=")[1].splitlines()[0]
    popen.assert_called_once()


def _built_app() -> Path | None:
    dist = ROOT / "dist"
    if not dist.is_dir():
        return None
    apps = sorted(dist.glob("Vintage Radio*.app"))
    return apps[0] if apps else None


@pytest.mark.skipif(_built_app() is None, reason="no built dist/*.app (run build_macos.sh first)")
def test_real_built_bundle_passes_static_checks():
    from project_version import PROJECT_VERSION

    app = _built_app()
    plist_ver = str(bc.read_plist(app).get("CFBundleShortVersionString"))
    if plist_ver != bc.expected_plist_version(PROJECT_VERSION):
        pytest.skip(
            f"dist app was built as {plist_ver}, working tree is {PROJECT_VERSION}"
        )
    failures = [r for r in bc.run_static_checks(app, PROJECT_VERSION) if not r["ok"]]
    assert not failures, failures


def test_spec_does_not_hardcode_bundle_version():
    """vintage_radio.spec once pinned CFBundleShortVersionString to '1.0.0' for every build."""
    text = (ROOT / "build" / "vintage_radio.spec").read_text(encoding="utf-8")
    line = next(ln for ln in text.splitlines() if "'CFBundleShortVersionString'" in ln)
    assert "PROJECT_VERSION" in text
    assert not any(ch.isdigit() for ch in line.split(":", 1)[1]), line
