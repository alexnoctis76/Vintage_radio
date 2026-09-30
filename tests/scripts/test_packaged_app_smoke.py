from __future__ import annotations

from pathlib import Path

from scripts.packaged_app_smoke import (
    _bundle_root_for_launch,
    _log_has_fatal,
    _macos_executable,
    run_smoke,
)


def test_log_has_fatal_detects_traceback():
    lines = ["INFO boot", "Traceback (most recent call last):", "  File x"]
    assert _log_has_fatal(lines) is not None


def test_log_has_fatal_clean_boot():
    lines = ["INFO boot", "MCP debug server started"]
    assert _log_has_fatal(lines) is None


def test_macos_executable_path(tmp_path: Path):
    app = tmp_path / "Vintage Radio.app"
    exe = app / "Contents" / "MacOS" / "Vintage Radio"
    exe.parent.mkdir(parents=True)
    exe.write_text("", encoding="utf-8")
    assert _macos_executable(app) == exe


def test_bundle_root_prefers_internal_on_windows_layout(tmp_path: Path):
    exe = tmp_path / "Vintage Radio.exe"
    exe.write_text("", encoding="utf-8")
    internal = exe.parent / "_internal"
    internal.mkdir()
    assert _bundle_root_for_launch(exe=exe, mac_app=None) == internal


def test_run_smoke_fails_when_firmware_bundle_missing(tmp_path: Path, monkeypatch):
    exe = tmp_path / "Vintage Radio.exe"
    exe.write_text("", encoding="utf-8")
    (exe.parent / "_internal").mkdir()

    from gui import commercials

    monkeypatch.setattr(
        commercials,
        "missing_firmware_bundle_paths",
        lambda root: ["missing/path"],
    )

    report = run_smoke(exe=exe, mac_app=None, port=8766, report_path=None)
    assert report["ok"] is False
    assert report["failed_steps"] == ["bundled_firmware_paths_present"]


def test_run_smoke_passes_when_mcp_checks_succeed(tmp_path: Path, monkeypatch):
    exe = tmp_path / "Vintage Radio.exe"
    exe.write_text("", encoding="utf-8")
    (exe.parent / "_internal").mkdir()

    from gui import commercials

    monkeypatch.setattr(commercials, "missing_firmware_bundle_paths", lambda root: [])

    class FakeProc:
        pid = 4242

        def poll(self):
            return None

    monkeypatch.setattr(
        "scripts.packaged_app_smoke._launch_packaged",
        lambda **kw: FakeProc(),
    )
    monkeypatch.setattr(
        "scripts.packaged_app_smoke._wait_for_ping",
        lambda *a, **k: (True, ""),
    )

    def fake_tcp(host, port, method, params=None, **kw):
        if method == "status":
            return True, {"ok": True, "status": {"running": True}}
        if method == "get_log_tail":
            return True, {"ok": True, "lines": ["INFO boot ok"]}
        return True, {"ok": True}

    monkeypatch.setattr("scripts.packaged_app_smoke._tcp_request", fake_tcp)
    monkeypatch.setattr("scripts.packaged_app_smoke._terminate_process", lambda proc: True)

    report = run_smoke(exe=exe, mac_app=None, port=8766, report_path=None)
    assert report["ok"] is True
    assert report["failed_steps"] == []
    step_names = [s["name"] for s in report["steps"]]
    assert "mcp_ping" in step_names
    assert "terminate_packaged_app" in step_names
