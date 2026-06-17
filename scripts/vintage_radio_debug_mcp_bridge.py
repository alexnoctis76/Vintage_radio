#!/usr/bin/env python3
"""Stdio MCP server that forwards to Vintage Radio's in-app debug TCP server.

Cursor (and other MCP clients) spawn this process and talk MCP over stdin/stdout.
This bridge translates tool calls into newline-delimited JSON on 127.0.0.1.

Prerequisites (end-to-end):
  1. Vintage Radio: Tools → Developer mode; Developer → MCP debug server ON (or env flags).
  2. Device tab: Connect + Start streaming when you need serial logs or VRTEST gestures.
  3. Pico: ``components/vintage_radio_ipc.py`` on flash + ``poll_ipc()`` in the main loop
     (Developer → Deploy MCP / VRTEST support to Pico… in the app).
  4. Cursor: ``.cursor/mcp.json`` points here; ``pip install mcp``; restart Cursor.

  Default TCP port 8765; override with env ``VINTAGE_RADIO_MCP_PORT``.

Install: ``pip install mcp`` (see requirements.txt).
"""

from __future__ import annotations

import json
import os
import socket
import sys
from typing import Any, Dict, Optional

try:
    from mcp.server.fastmcp import FastMCP
except ImportError:
    print(
        "Missing package 'mcp'. Install with: pip install mcp",
        file=sys.stderr,
    )
    sys.exit(1)

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
READ_TIMEOUT_S = 300.0
INSTALL_READ_TIMEOUT_S = 660.0


def _agent_debug_log(*_a: Any, **_k: Any) -> None:
    """No-op placeholder (optional local NDJSON logging removed)."""
    return


def _tcp_json_request(method: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    host = os.environ.get("VINTAGE_RADIO_MCP_HOST", DEFAULT_HOST).strip() or DEFAULT_HOST
    try:
        port = int(os.environ.get("VINTAGE_RADIO_MCP_PORT", str(DEFAULT_PORT)))
    except ValueError:
        port = DEFAULT_PORT
    params = params if isinstance(params, dict) else {}
    line = json.dumps({"method": method, "params": params}, ensure_ascii=True) + "\n"
    buf = b""
    read_timeout = READ_TIMEOUT_S
    if method == "invoke_action" and str((params or {}).get("action", "")).strip() == (
        "install_basic_to_pico"
    ):
        read_timeout = float(
            os.environ.get("VINTAGE_RADIO_MCP_INSTALL_TIMEOUT_S", str(INSTALL_READ_TIMEOUT_S))
        )
    try:
        with socket.create_connection((host, port), timeout=10.0) as sock:
            sock.settimeout(read_timeout)
            sock.sendall(line.encode("utf-8"))
            while b"\n" not in buf:
                chunk = sock.recv(65536)
                if not chunk:
                    break
                buf += chunk
    except OSError as e:
        # region agent log
        _agent_debug_log(
            "bridge:_tcp_json_request",
            "tcp_failed",
            {"detail": str(e), "host": host, "port": port},
            "H1",
        )
        # endregion agent log
        return {
            "ok": False,
            "error": "tcp_failed",
            "detail": str(e),
            "hint": "Start Vintage Radio and turn on the MCP debug server (Developer menu).",
            "host": host,
            "port": port,
        }
    if not buf.strip():
        return {"ok": False, "error": "empty_response"}
    first = buf.split(b"\n", 1)[0].strip()
    try:
        out = json.loads(first.decode("utf-8"))
        # region agent log
        _agent_debug_log(
            "bridge:_tcp_json_request",
            "response_ok",
            {
                "method": method,
                "top_ok": bool(out.get("ok", True))
                if isinstance(out, dict)
                else True,
            },
            "H2",
        )
        # endregion agent log
        return out
    except json.JSONDecodeError as e:
        # region agent log
        _agent_debug_log(
            "bridge:_tcp_json_request",
            "response_bad_json",
            {"detail": str(e)[:100]},
            "H2",
        )
        # endregion agent log
        return {
            "ok": False,
            "error": "invalid_json",
            "detail": str(e),
            "raw": first.decode("utf-8", errors="replace")[:500],
        }


mcp = FastMCP(
    "Vintage Radio Debug",
    instructions=(
        "Bridge to the Vintage Radio desktop app debug server (localhost TCP). "
        "The app must be running with Developer mode and the MCP debug server enabled. "
        "Use vintage_radio_debug_request with method names such as: ping, status, "
        "get_connection_state, device_connect, get_log_tail, get_device_stream_tail, "
        "invoke_action (e.g. action install_basic_to_pico to copy basic firmware via the "
        "same path as the app Install to Pico), run_acceptance_suite, run_button_script, "
        "run_test_script, line_in_list_devices, line_in_analyze."
    ),
)


@mcp.tool()
def vintage_radio_debug_request(
    method: str,
    params: Optional[Dict[str, Any]] = None,
) -> str:
    """Send one request to the Vintage Radio debug TCP API and return JSON text.

    Common methods:
      - ping / health — connectivity check
      - status — server + device connection summary
      - get_connection_state — serial connect / streaming flags
      - get_log_tail — host session log (params: limit)
      - get_device_stream_tail — recent device serial lines (params: limit)
      - invoke_action — run a GUI / Device-tab action (params: action, payload)
          e.g. {\"action\": \"restart_firmware\"} (Pico soft reset + main.py)
          e.g. {\"action\": \"install_basic_to_pico\"} — disconnects serial if needed, runs Install to Pico (basic) worker (several minutes)
          e.g. {\"action\": \"physical_gesture\", \"payload\": {\"gesture\": \"single_tap\", \"target\": \"device\"}}
          Actions include: connect, connect_device (or top-level device_connect), disconnect, scan_ports,
          start_streaming, stop_streaming, restart_firmware, soft_reset, list_files, send_command,
          physical_gesture, device_stream_tail.
      - run_acceptance_suite — scripted tests (params: target, suite_profile)
      - run_button_script — sequence of invoke_action steps (params: steps)
      - line_in_list_devices — audio input devices (needs numpy, sounddevice)
      - line_in_analyze — record line-in + metrics vs reference WAV (params: duration_s,
        sample_rate, device index optional, reference_wav optional, windows for AM vs music)
      - device_connect — select Pico port and connect (params: port optional e.g. COM6,
        auto_start_streaming default true); or invoke_action connect_device with same params
    """
    m = (method or "").strip()
    if not m:
        return json.dumps({"ok": False, "error": "missing_method"}, indent=2)
    resp = _tcp_json_request(m, params)
    return json.dumps(resp, indent=2, ensure_ascii=False)


def main() -> None:
    # Cursor lists "No tools" if the process dies before stdio handshake; log readiness on stderr.
    try:
        print(
            "vintage-radio-debug MCP bridge: stdio server starting "
            "(tool: vintage_radio_debug_request). "
            "If ping fails, start Vintage Radio with MCP TCP (port 8765).",
            file=sys.stderr,
            flush=True,
        )
    except Exception:
        pass
    mcp.run(transport="stdio")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--probe":
        print(json.dumps(_tcp_json_request("ping", {}), indent=2))
        sys.exit(0)
    if len(sys.argv) > 1 and sys.argv[1] == "--probe-all":
        for meth, par in (
            ("ping", {}),
            ("status", {}),
            ("get_connection_state", {}),
            (
                "invoke_action",
                {
                    "action": "physical_gesture",
                    "payload": {"gesture": "ping", "target": "device"},
                },
            ),
        ):
            r = _tcp_json_request(meth, par)
            print("===", meth, "===")
            print(json.dumps(r, indent=2, ensure_ascii=False)[:2500])
        sys.exit(0)
    main()
