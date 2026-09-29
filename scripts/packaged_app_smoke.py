#!/usr/bin/env python3
"""Post-build smoke tests for packaged Vintage Radio binaries.

Spawns the frozen app with MCP debug enabled, runs TCP health checks, then exits.
Used automatically at the end of build_windows.bat / build_linux.sh / build_macos.sh.

Usage:
    python scripts/packaged_app_smoke.py --exe "dist/Vintage Radio/Vintage Radio.exe"
    python scripts/packaged_app_smoke.py --mac-app "dist/Vintage Radio.app"
    python scripts/packaged_app_smoke.py --exe "dist/Vintage Radio/Vintage Radio" --port 8766
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

DEFAULT_HOST = "127.0.0.1"
DEFAULT_SMOKE_PORT = 8766
PING_TIMEOUT_S = 90.0
PING_POLL_S = 0.5
TERMINATE_GRACE_S = 8.0

_FATAL_LOG_MARKERS = (
    "Traceback (most recent call last)",
    "FATAL:",
    "Boot init error:",
)


def _project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _tcp_request(
    host: str,
    port: int,
    method: str,
    params: Optional[Dict[str, Any]] = None,
    *,
    timeout_s: float = 15.0,
) -> Tuple[bool, Dict[str, Any]]:
    params = params if isinstance(params, dict) else {}
    line = json.dumps({"method": method, "params": params}, ensure_ascii=True) + "\n"
    try:
        with socket.create_connection((host, port), timeout=10.0) as sock:
            sock.settimeout(timeout_s)
            sock.sendall(line.encode("utf-8"))
            buf = b""
            while b"\n" not in buf:
                chunk = sock.recv(65536)
                if not chunk:
                    break
                buf += chunk
        if not buf:
            return False, {"error": "empty_response", "method": method}
        payload = json.loads(buf.split(b"\n", 1)[0].decode("utf-8"))
        if not isinstance(payload, dict):
            return False, {"error": "invalid_json_shape", "method": method}
        return bool(payload.get("ok")), payload
    except OSError as exc:
        return False, {"error": str(exc), "method": method}
    except json.JSONDecodeError as exc:
        return False, {"error": f"json_decode: {exc}", "method": method}


def _wait_for_ping(host: str, port: int, timeout_s: float) -> Tuple[bool, str]:
    deadline = time.time() + timeout_s
    last_err = "no response"
    while time.time() < deadline:
        ok, resp = _tcp_request(host, port, "ping", timeout_s=5.0)
        if ok:
            return True, ""
        last_err = str(resp.get("error") or resp)
        time.sleep(PING_POLL_S)
    return False, last_err


def _bundle_root_for_launch(
    *,
    exe: Optional[Path],
    mac_app: Optional[Path],
) -> Path:
    """PyInstaller one-folder layout stores datas under ``_internal`` on Windows."""
    if mac_app is not None:
        return mac_app / "Contents" / "Resources"
    if exe is not None:
        internal = exe.parent / "_internal"
        if internal.is_dir():
            return internal
        return exe.parent
    raise ValueError("need --exe or --mac-app")


def _macos_executable(app_bundle: Path) -> Path:
    exe = app_bundle / "Contents" / "MacOS" / "Vintage Radio"
    if not exe.is_file():
        raise FileNotFoundError(f"macOS executable not found: {exe}")
    return exe


def _launch_packaged(
    *,
    exe: Optional[Path],
    mac_app: Optional[Path],
    port: int,
    data_dir: Optional[Path] = None,
) -> subprocess.Popen[Any]:
    args = [
        "--enable-mcp-debug",
        "--mcp-autostart",
        f"--mcp-port={port}",
    ]
    if mac_app is not None:
        binary = _macos_executable(mac_app)
        cmd = [str(binary), *args]
        cwd = str(mac_app.parent)
    elif exe is not None:
        cmd = [str(exe), *args]
        cwd = str(exe.parent)
    else:
        raise ValueError("need --exe or --mac-app")

    env = os.environ.copy()
    if data_dir is not None:
        env["VINTAGE_RADIO_DATA_DIR"] = str(data_dir)

    creationflags = 0
    if platform.system() == "Windows":
        creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)

    return subprocess.Popen(
        cmd,
        cwd=cwd,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=creationflags,
    )


def _terminate_process(proc: subprocess.Popen[Any]) -> bool:
    """Stop the packaged app; return True when the process is no longer running."""
    if proc.poll() is not None:
        return True
    try:
        if platform.system() == "Windows":
            subprocess.run(
                ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                check=False,
                capture_output=True,
            )
        else:
            proc.terminate()
            try:
                proc.wait(timeout=TERMINATE_GRACE_S)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5.0)
    except OSError:
        try:
            proc.kill()
        except OSError:
            pass
    deadline = time.time() + TERMINATE_GRACE_S
    while time.time() < deadline:
        if proc.poll() is not None:
            return True
        time.sleep(0.2)
    return proc.poll() is not None


def _log_has_fatal(lines: List[str]) -> Optional[str]:
    for ln in lines:
        for marker in _FATAL_LOG_MARKERS:
            if marker in ln:
                return ln.strip()
    return None


def run_smoke(
    *,
    exe: Optional[Path],
    mac_app: Optional[Path],
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_SMOKE_PORT,
    report_path: Optional[Path] = None,
) -> Dict[str, Any]:
    steps: List[Dict[str, Any]] = []
    proc: Optional[subprocess.Popen[Any]] = None

    def record(name: str, ok: bool, **extra: Any) -> None:
        row: Dict[str, Any] = {"name": name, "ok": ok}
        row.update(extra)
        steps.append(row)

    root = _project_root()
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    from gui.commercials import missing_firmware_bundle_paths

    bundle_root = _bundle_root_for_launch(exe=exe, mac_app=mac_app)
    missing_fw = missing_firmware_bundle_paths(bundle_root)
    record(
        "bundled_firmware_paths_present",
        not missing_fw,
        missing=missing_fw,
        bundle_root=str(bundle_root),
    )
    if missing_fw:
        return _finish(steps, False, report_path)

    with tempfile.TemporaryDirectory(prefix="vr_smoke_data_") as smoke_data:
        proc = _launch_packaged(
            exe=exe,
            mac_app=mac_app,
            port=port,
            data_dir=Path(smoke_data),
        )
        record(
            "launch_packaged_app",
            True,
            pid=proc.pid,
            port=port,
            data_dir=smoke_data,
        )
        try:
            ping_ok, ping_err = _wait_for_ping(host, port, PING_TIMEOUT_S)
            record("mcp_ping", ping_ok, error=ping_err or None)
            if not ping_ok:
                return _finish(steps, False, report_path)

            ok, resp = _tcp_request(host, port, "status")
            running = bool((resp.get("status") or {}).get("running")) if ok else False
            record("mcp_status", ok and running, response=resp)

            ok, resp = _tcp_request(host, port, "get_connection_state")
            record("mcp_get_connection_state", ok, response=resp)

            ok, resp = _tcp_request(
                host,
                port,
                "invoke_action",
                {"action": "scan_ports", "payload": {}},
            )
            record("mcp_scan_ports", ok, response=resp)

            ok, resp = _tcp_request(host, port, "get_log_tail", {"limit": 120})
            log_lines: List[str] = []
            if ok:
                raw = resp.get("lines") or resp.get("tail")
                if isinstance(raw, list):
                    log_lines = [str(x) for x in raw]
                elif isinstance(raw, str):
                    log_lines = raw.splitlines()
            fatal = _log_has_fatal(log_lines)
            # Log file may not exist yet on first boot — not a failure if MCP otherwise healthy.
            log_ok = fatal is None and (
                ok or resp.get("error") in ("no_log_path", "log_missing")
            )
            record(
                "mcp_log_tail_no_fatal",
                log_ok,
                fatal_line=fatal,
                line_count=len(log_lines),
                log_response_error=resp.get("error") if not ok else None,
            )
        finally:
            if proc is not None:
                terminated = _terminate_process(proc)
                record(
                    "terminate_packaged_app",
                    terminated,
                    returncode=proc.poll(),
                )

    failed = [s["name"] for s in steps if not s.get("ok")]
    overall = not failed
    return _finish(steps, overall, report_path)


def _finish(steps: List[Dict[str, Any]], overall: bool, report_path: Optional[Path]) -> Dict[str, Any]:
    failed = [s["name"] for s in steps if not s.get("ok")]
    report: Dict[str, Any] = {
        "ok": overall,
        "failed_steps": failed,
        "steps": steps,
        "platform": platform.system(),
    }
    if report_path is not None:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def _default_report_path() -> Path:
    return _project_root() / "agent_workshop" / "packaged_smoke_report.json"


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Packaged Vintage Radio MCP smoke tests")
    parser.add_argument("--exe", type=Path, help="Path to packaged executable")
    parser.add_argument("--mac-app", type=Path, help="Path to Vintage Radio.app bundle (macOS)")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_SMOKE_PORT)
    parser.add_argument(
        "--report",
        type=Path,
        default=_default_report_path(),
        help="JSON report path (default: agent_workshop/packaged_smoke_report.json)",
    )
    args = parser.parse_args(argv)

    if not args.exe and not args.mac_app:
        parser.error("one of --exe or --mac-app is required")
    if args.exe and not args.exe.is_file():
        print(f"Error: executable not found: {args.exe}", file=sys.stderr)
        return 1
    if args.mac_app and not args.mac_app.is_dir():
        print(f"Error: .app bundle not found: {args.mac_app}", file=sys.stderr)
        return 1

    print(f"Packaged app smoke (port {args.port})...")
    report = run_smoke(
        exe=args.exe,
        mac_app=args.mac_app,
        host=args.host,
        port=args.port,
        report_path=args.report,
    )
    for step in report["steps"]:
        mark = "PASS" if step.get("ok") else "FAIL"
        print(f"  [{mark}] {step['name']}")
    print(f"Report: {args.report}")
    if report["ok"]:
        print("Packaged smoke: PASS")
        return 0
    print(f"Packaged smoke: FAIL ({', '.join(report['failed_steps'])})", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
