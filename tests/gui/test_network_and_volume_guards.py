"""Guards against two classes of bug that only bite on real user machines.

1. HTTPS downloads without a certifi CA bundle fail on python.org/PyInstaller macOS builds
   (``CERTIFICATE_VERIFY_FAILED``) while working on the dev machine.
2. A wedged removable volume makes ``stat()`` block forever; volume scans run on the UI
   thread at startup, so the whole app appeared to "not open".
"""

from __future__ import annotations

import ast
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

GUI_DIR = Path(__file__).resolve().parents[2] / "gui"

# urlopen() calls allowed without ``context=``: each is the plain-HTTPS fallback that runs
# only after a certifi-backed attempt in the same function failed. Do not add to this list;
# route new downloads through a certifi context (see gui/services/firmware_bundle.py::_urlopen).
_ALLOWED_BARE_URLOPEN = {
    "radio_manager.py": 1,
    "remote_firmware.py": 2,
}


def _bare_urlopen_counts() -> dict[str, list[int]]:
    found: dict[str, list[int]] = {}
    for path in sorted(GUI_DIR.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            fn = node.func
            name = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", "")
            if name == "urlopen" and not any(k.arg == "context" for k in node.keywords):
                found.setdefault(path.name, []).append(node.lineno)
    return found


def test_no_new_urlopen_without_ssl_context():
    found = _bare_urlopen_counts()
    unexpected = {
        name: lines
        for name, lines in found.items()
        if len(lines) > _ALLOWED_BARE_URLOPEN.get(name, 0)
    }
    assert not unexpected, (
        "urlopen() without an SSL context (fails with CERTIFICATE_VERIFY_FAILED on macOS "
        f"packaged builds): {unexpected}"
    )


@pytest.fixture
def fast_probe(monkeypatch):
    from gui import sd_manager

    monkeypatch.setattr(sd_manager, "_VOLUME_PROBE_TIMEOUT_S", 0.3)
    sd_manager._hung_volumes.clear()
    yield sd_manager
    sd_manager._hung_volumes.clear()


def test_probe_returns_none_for_wedged_volume_and_does_not_block(fast_probe, monkeypatch):
    release = threading.Event()

    def wedged_is_dir(self):
        release.wait(10)
        return True

    monkeypatch.setattr(Path, "is_dir", wedged_is_dir)
    start = time.monotonic()
    try:
        assert fast_probe._probe_volume_readable(Path("/Volumes/WEDGED")) is None
        elapsed = time.monotonic() - start
        assert elapsed < 2.0
        # Second scan must short-circuit (cooldown) instead of spawning another stuck thread.
        start = time.monotonic()
        assert fast_probe._probe_volume_readable(Path("/Volumes/WEDGED")) is None
        assert time.monotonic() - start < 0.1
    finally:
        release.set()


def test_probe_reports_normal_directory(fast_probe, tmp_path):
    assert fast_probe._probe_volume_readable(tmp_path) is True
    assert fast_probe._probe_volume_readable(tmp_path / "missing") is False


def test_detect_sd_roots_macos_survives_wedged_volume(fast_probe, monkeypatch, tmp_path):
    """One hung /Volumes entry must not stop other volumes from being listed."""
    good = tmp_path / "GOODSD"
    bad = tmp_path / "RPI-RP2"
    good.mkdir()
    bad.mkdir()
    release = threading.Event()
    real_is_dir = Path.is_dir

    def selective_is_dir(self):
        if self.name == "RPI-RP2":
            release.wait(10)
        return real_is_dir(self)

    fake_parts = [
        SimpleNamespace(mountpoint=str(good), fstype="msdos", opts="rw"),
        SimpleNamespace(mountpoint=str(bad), fstype="msdos", opts="rw"),
    ]
    real_path = Path

    def fake_path(*args, **kwargs):
        if args and args[0] == "/Volumes":
            return tmp_path
        return real_path(*args, **kwargs)

    monkeypatch.setattr(Path, "is_dir", selective_is_dir)
    try:
        with (
            patch("gui.sd_manager.platform.system", return_value="Darwin"),
            patch("gui.sd_manager.psutil.disk_partitions", return_value=fake_parts),
            patch("gui.sd_manager.Path", fake_path),
        ):
            start = time.monotonic()
            roots = fast_probe.SDManager.detect_sd_roots()
            assert time.monotonic() - start < 3.0
    finally:
        release.set()
    assert [label for _p, label in roots] == ["GOODSD"]
