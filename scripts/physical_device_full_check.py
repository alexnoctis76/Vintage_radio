#!/usr/bin/env python3
"""Rigorous physical Pico check: mpremote (if port free), MCP, VRTEST suite, boot logs, optional line-in.

Examples:
  python scripts/physical_device_full_check.py
  python scripts/physical_device_full_check.py --port COM6
  python scripts/physical_device_full_check.py --use-running   # app already up, MCP on 8765
  python scripts/physical_device_full_check.py --strict        # exit 1 on any warning
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

JsonDict = Dict[str, Any]


@dataclass
class Check:
    name: str
    ok: bool
    severity: str  # "critical" | "warn" | "info"
    detail: str = ""
    data: JsonDict = field(default_factory=dict)


def _find_pico_port(hint: Optional[str]) -> Optional[str]:
    if hint and str(hint).strip():
        return str(hint).strip()
    try:
        import serial.tools.list_ports
    except ImportError:
        return None
    for p in serial.tools.list_ports.comports():
        vid = getattr(p, "vid", None)
        if vid is not None and int(vid) == 0x2E8A:
            return str(p.device)
        hwid = (getattr(p, "hwid", "") or "").upper()
        if "2E8A" in hwid:
            return str(p.device)
    return None


def _mpremote_quiet(args: List[str], timeout: float = 25.0) -> tuple[int, str, str]:
    try:
        r = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(ROOT),
        )
        return r.returncode, (r.stdout or "").strip(), (r.stderr or "").strip()
    except subprocess.TimeoutExpired as e:
        return 124, "", f"timeout: {e}"
    except OSError as e:
        return 1, "", str(e)


class McpTcpClient:
    def __init__(self, host: str, port: int) -> None:
        self._host = host
        self._port = int(port)

    def request(self, obj: JsonDict, timeout: float = 120.0) -> JsonDict:
        data = (json.dumps(obj, ensure_ascii=True) + "\n").encode("utf-8")
        s = socket.create_connection((self._host, self._port), timeout=30.0)
        try:
            s.settimeout(timeout)
            s.sendall(data)
            buf = b""
            while b"\n" not in buf:
                chunk = s.recv(65536)
                if not chunk:
                    break
                buf += chunk
            line = buf.split(b"\n", 1)[0].strip()
            return json.loads(line.decode("utf-8")) if line else {"ok": False, "error": "empty_response"}
        finally:
            s.close()

    def invoke_action(self, action: str, payload: Optional[JsonDict] = None) -> JsonDict:
        r = self.request(
            {
                "method": "invoke_action",
                "params": {"action": action, "payload": payload or {}},
            }
        )
        if not r.get("ok"):
            return r
        inner = r.get("result")
        return inner if isinstance(inner, dict) else r

    def device_connect(self, port: str, auto_stream: bool = True) -> JsonDict:
        return self.request(
            {
                "method": "device_connect",
                "params": {"port": port, "auto_start_streaming": auto_stream},
            }
        )


def _wait_mcp_port(host: str, port: int, timeout_s: float = 90.0) -> bool:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            s = socket.socket()
            s.settimeout(0.25)
            if s.connect_ex((host, port)) == 0:
                s.close()
                return True
        except OSError:
            pass
        else:
            s.close()
        time.sleep(0.4)
    return False


def _spawn_app(env_extra: Dict[str, str]) -> subprocess.Popen:
    env = os.environ.copy()
    env.setdefault("QT_QPA_PLATFORM", "offscreen")
    env["VINTAGE_RADIO_ENABLE_MCP_DEBUG"] = "1"
    env["VINTAGE_RADIO_MCP_AUTOSTART"] = "1"
    env.update(env_extra)
    return subprocess.Popen(
        [sys.executable, str(ROOT / "run_vintage_radio.py")],
        cwd=str(ROOT),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )


def _tail_lines(cli: McpTcpClient, limit: int = 400) -> List[str]:
    r = cli.invoke_action("device_stream_tail", {"limit": int(limit)})
    if not r.get("ok"):
        return []
    lines = r.get("lines")
    return [str(x) for x in lines] if isinstance(lines, list) else []


def _make_invoke(cli: McpTcpClient) -> Callable[[str, JsonDict], JsonDict]:
    def invoke(action: str, payload: JsonDict) -> JsonDict:
        return cli.invoke_action(action, payload)

    return invoke


def _analyze_boot_log(lines: List[str]) -> tuple[bool, List[str]]:
    """Return (critical_ok, warning_messages)."""
    warnings: List[str] = []
    joined = "\n".join(lines)
    fatal = ("Traceback (most recent call last)", "MemoryError", "SyntaxError")
    for token in fatal:
        if token in joined:
            return False, [f"boot log contains `{token}`"]
    if "VRTEST IPC: uselect stdin polling enabled" not in joined and "VRTEST" not in joined:
        warnings.append("no explicit VRTEST IPC banner in tail (may still work if poll_ipc runs silently)")
    if "DFPlayer" not in joined and "dfplayer" not in joined.lower():
        warnings.append("no DFPlayer string in boot tail (non-basic image?)")
    return True, warnings


def _optional_line_in(cli: McpTcpClient) -> Check:
    try:
        r = cli.request({"method": "line_in_list_devices"})
        if not r.get("ok"):
            return Check(
                "line_in_list_devices",
                True,
                "info",
                "skipped or unavailable",
                {"result": r},
            )
        return Check(
            "line_in_list_devices",
            True,
            "info",
            f"devices={len(r.get('devices', []))}",
            {"sample": r.get("devices", [])[:5]},
        )
    except (OSError, json.JSONDecodeError, socket.timeout) as e:
        return Check("line_in_list_devices", True, "info", f"skip: {e}")


def main() -> int:
    ap = argparse.ArgumentParser(description="Full physical device acceptance via MCP (+ optional mpremote).")
    ap.add_argument("--port", default="", help="Serial port (default: auto-detect RP2040)")
    ap.add_argument("--mcp-host", default="127.0.0.1")
    ap.add_argument("--mcp-port", type=int, default=8765)
    ap.add_argument("--use-running", action="store_true", help="Do not spawn the app; MCP must already listen.")
    ap.add_argument("--no-spawn-reboot", action="store_true", help="Skip restart_firmware boot-log phase.")
    ap.add_argument("--suite", choices=("minimal", "standard", "full"), default="full")
    ap.add_argument("--strict", action="store_true", help="Exit 1 if any warning-level check fails.")
    args = ap.parse_args()

    port = _find_pico_port(args.port or None)
    checks: List[Check] = []

    if not port:
        checks.append(
            Check(
                "detect_pico_port",
                False,
                "critical",
                "No RP2040/Pico serial port found. Plug in USB or pass --port COMx.",
            )
        )
        _print_report(checks, strict=args.strict)
        return 1

    checks.append(Check("detect_pico_port", True, "info", port))

    # 1) mpremote preflight only if port is likely free
    rc, out, err = _mpremote_quiet(
        [sys.executable, "-m", "mpremote", "connect", port, "exec", "import gc; gc.collect(); print('MEM', gc.mem_free())"],
        timeout=20.0,
    )
    if rc == 0 and "MEM" in out:
        checks.append(Check("mpremote_mem", True, "info", out.splitlines()[-1] if out else "ok"))
        # mpremote leaves the device at the >>> REPL (main.py not running). Soft-reset so main restarts
        # before Vintage Radio opens the port; otherwise VRTEST lines are parsed as Python (SyntaxError).
        _mpremote_quiet(
            [
                sys.executable,
                "-m",
                "mpremote",
                "connect",
                port,
                "exec",
                "import machine; machine.soft_reset()",
            ],
            timeout=20.0,
        )
        time.sleep(8.5)
    else:
        checks.append(
            Check(
                "mpremote_mem",
                True,
                "warn",
                "skipped (port busy or mpremote failed — normal if another app holds COM)",
                {"rc": rc, "stderr": err[:500]},
            )
        )

    proc: Optional[subprocess.Popen] = None
    if not args.use_running:
        proc = _spawn_app({})
        if not _wait_mcp_port(args.mcp_host, args.mcp_port, timeout_s=95.0):
            if proc:
                proc.terminate()
                proc.wait(timeout=8)
            checks.append(
                Check(
                    "mcp_listen",
                    False,
                    "critical",
                    "Vintage Radio did not open MCP on {}:{}".format(args.mcp_host, args.mcp_port),
                )
            )
            _print_report(checks, strict=args.strict)
            return 1
        checks.append(Check("mcp_listen", True, "info", "spawned app + MCP ready"))
    else:
        if not _wait_mcp_port(args.mcp_host, args.mcp_port, timeout_s=3.0):
            checks.append(
                Check(
                    "mcp_listen",
                    False,
                    "critical",
                    "No MCP on {}:{} (--use-running)".format(args.mcp_host, args.mcp_port),
                )
            )
            _print_report(checks, strict=args.strict)
            return 1
        checks.append(Check("mcp_listen", True, "info", "using running MCP"))

    cli = McpTcpClient(args.mcp_host, args.mcp_port)

    st = cli.request({"method": "status"})
    checks.append(
        Check(
            "mcp_status",
            bool(st.get("ok")),
            "critical" if not st.get("ok") else "info",
            json.dumps(st.get("status", {}), indent=2)[:600] if st.get("ok") else str(st)[:400],
        )
    )

    dc = cli.device_connect(port, auto_stream=True)
    checks.append(
        Check(
            "device_connect",
            bool(dc.get("ok")),
            "critical",
            str(dc)[:500],
        )
    )
    time.sleep(4.5)

    cs = cli.request({"method": "get_connection_state"})
    state = cs.get("state") if isinstance(cs.get("state"), dict) else {}
    connected = bool(state.get("connected"))
    streaming = bool(state.get("streaming"))
    checks.append(
        Check(
            "serial_connected",
            connected,
            "critical",
            json.dumps(state),
        )
    )
    checks.append(
        Check(
            "serial_streaming",
            streaming or connected,
            "warn" if connected and not streaming else "critical",
            "streaming={}".format(streaming),
        )
    )

    if not connected:
        _cleanup(proc)
        _print_report(checks, strict=args.strict)
        return 1

    cli.invoke_action("start_streaming", {})
    time.sleep(1.5)

    # Ensure main.py is running (not stale REPL) before VRTEST.
    cli.invoke_action("restart_firmware", {})
    time.sleep(10.5)
    cli.device_connect(port, auto_stream=True)
    time.sleep(5.0)
    cli.invoke_action("start_streaming", {})
    time.sleep(3.0)
    checks.append(
        Check(
            "pre_vrtest_reboot",
            True,
            "info",
            "Issued restart_firmware + reconnect so poll_ipc / VRTEST are active",
        )
    )

    from gui.mcp_device_acceptance import run_acceptance_suite

    invoke = _make_invoke(cli)
    suite = run_acceptance_suite(invoke=invoke, target="device", suite_profile=args.suite)
    steps = suite.get("steps") if isinstance(suite.get("steps"), list) else []
    failed_named = [s for s in steps if not s.get("ok")]
    checks.append(
        Check(
            "vrtest_suite_ok",
            bool(suite.get("ok")),
            "critical" if not suite.get("ok") else "info",
            "profile={} track_changed={} failed_steps={}".format(
                args.suite,
                suite.get("track_changed"),
                [x.get("name") for x in failed_named],
            ),
            {"steps": steps},
        )
    )
    if failed_named:
        checks.append(
            Check(
                "vrtest_failed_detail",
                True,
                "info",
                json.dumps(failed_named, indent=2)[:3500],
            )
        )

    if not suite.get("track_changed"):
        checks.append(
            Check(
                "track_advanced_after_tap",
                False,
                "warn",
                "Track index did not change after single_tap (valid if single-track folder or edge of list).",
            )
        )

    gesture_log_step = next(
        (s for s in suite.get("steps", []) if s.get("name") == "serial_log_gesture_hint"),
        None,
    )
    if gesture_log_step and not gesture_log_step.get("ok"):
        checks.append(
            Check(
                "serial_gesture_visible",
                False,
                "warn",
                "Serial ring did not show obvious tap/gesture debug lines.",
            )
        )

    # Filesystem via list_files (interrupts main → REPL); then soft-reset to restore
    cli.invoke_action("list_files", {})
    time.sleep(4.0)
    tail_ls = _tail_lines(cli, 250)
    joined_ls = "\n".join(tail_ls).lower()
    saw_py = (
        ".py" in joined_ls
        or "[dir]" in joined_ls
        or "main.py" in joined_ls
        or "lib/" in joined_ls
    )
    checks.append(
        Check(
            "list_files_serial_evidence",
            saw_py,
            "warn",
            "Expected .py or main.py in stream after list_files" if not saw_py else "saw python files in stream",
            {"tail_lines": len(tail_ls)},
        )
    )

    if not args.no_spawn_reboot:
        cli.invoke_action("restart_firmware", {})
        time.sleep(11.0)
        cli.device_connect(port, auto_stream=True)
        time.sleep(5.0)
        cli.invoke_action("start_streaming", {})
        time.sleep(3.5)
        boot_lines = _tail_lines(cli, 500)
        boot_ok, boot_warns = _analyze_boot_log(boot_lines)
        checks.append(
            Check(
                "post_reboot_boot_log",
                boot_ok,
                "critical",
                "; ".join(boot_warns) if boot_warns else "no fatal strings in tail",
                {"lines": len(boot_lines)},
            )
        )
        for w in boot_warns:
            checks.append(Check("boot_log_hint", True, "info", w))

        ping = cli.invoke_action(
            "physical_gesture",
            {"gesture": "ping", "target": "device"},
        )
        ok_ping = bool(ping.get("ok")) and bool((ping.get("device") or {}).get("ok", True))
        checks.append(
            Check(
                "vrtest_ping_after_reboot",
                ok_ping,
                "critical",
                str(ping)[:400],
            )
        )

    checks.append(_optional_line_in(cli))

    _cleanup(proc)
    return _print_report(checks, strict=args.strict)


def _cleanup(proc: Optional[subprocess.Popen]) -> None:
    if proc is None:
        return
    try:
        proc.terminate()
        proc.wait(timeout=15)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=8)
    except Exception:
        pass


def _print_report(checks: List[Check], *, strict: bool) -> int:
    critical_fail = any(not c.ok and c.severity == "critical" for c in checks)
    warn_fail = any(not c.ok and c.severity == "warn" for c in checks)

    print("\n========== Physical device full check ==========\n")
    for c in checks:
        mark = "PASS" if c.ok else "FAIL"
        print(f"[{mark}] ({c.severity}) {c.name}")
        if c.detail:
            safe = c.detail[:900].encode("ascii", errors="replace").decode("ascii")
            print(f"       {safe}")
        if c.data and c.name.startswith("vrtest"):
            print(f"       data keys: {list(c.data.keys())}")
    print("\n===============================================\n")

    if critical_fail:
        print("OVERALL: FAIL (critical)\n")
        return 1
    if strict and warn_fail:
        print("OVERALL: FAIL (--strict, warnings treated as failures)\n")
        return 1
    if warn_fail:
        print("OVERALL: PASS with warnings (re-run with --strict to fail on these)\n")
        return 0
    print("OVERALL: PASS\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
