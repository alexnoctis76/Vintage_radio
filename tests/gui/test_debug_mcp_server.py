from __future__ import annotations

import json
import socket
import time

import pytest

from gui.debug_mcp_server import DebugMcpServerManager


def _free_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return int(p)


def _send_line(port: int, payload: dict) -> dict:
    with socket.create_connection(("127.0.0.1", port), timeout=2.0) as c:
        c.sendall((json.dumps(payload) + "\n").encode("utf-8"))
        data = b""
        while b"\n" not in data:
            data += c.recv(4096)
    return json.loads(data.split(b"\n", 1)[0].decode("utf-8"))


def test_server_starts_when_device_disconnected():
    mgr = DebugMcpServerManager(
        get_connection_state=lambda: {"connected": False, "port": ""},
        invoke_action=lambda _a, _p: {"ok": True},
        get_log_path=lambda: None,
        log=lambda _m: None,
    )
    port = _free_port()
    res = mgr.start(port=port)
    assert res["ok"] is True
    try:
        st = _send_line(port, {"method": "status"})
        assert st["ok"] is True
        assert st["status"]["device"]["connected"] is False
    finally:
        time.sleep(0.05)
        mgr.stop()


def test_server_status_and_invoke_action_roundtrip():
    calls = []
    state = {"connected": True, "port": "COM6", "streaming": True}

    def invoke(action, payload):
        calls.append((action, payload))
        return {"ok": True, "action": action}

    port = _free_port()
    mgr = DebugMcpServerManager(
        get_connection_state=lambda: dict(state),
        invoke_action=invoke,
        get_log_path=lambda: None,
        log=lambda _m: None,
    )
    started = mgr.start(port=port)
    assert started["ok"] is True
    try:
        st = _send_line(port, {"method": "status"})
        assert st["ok"] is True
        assert st["status"]["device"]["connected"] is True

        iv = _send_line(
            port,
            {"method": "invoke_action", "params": {"action": "restart_firmware", "payload": {"x": 1}}},
        )
        assert iv["ok"] is True
        assert calls and calls[-1][0] == "restart_firmware"

        rs = _send_line(
            port,
            {
                "method": "run_button_script",
                "params": {"steps": [{"action": "restart_firmware"}, {"action": "wait", "ms": 10}]},
            },
        )
        assert rs["ok"] is True
    finally:
        time.sleep(0.05)
        mgr.stop()


def test_device_connect_dispatches_to_invoke():
    calls: list[tuple[str, dict]] = []

    def invoke(action, payload):
        calls.append((action, payload or {}))
        return {"ok": True, "action": action, "payload": payload or {}}

    port = _free_port()
    mgr = DebugMcpServerManager(
        get_connection_state=lambda: {"connected": False, "port": ""},
        invoke_action=invoke,
        get_log_path=lambda: None,
        log=lambda _m: None,
    )
    mgr.start(port=port)
    try:
        r = _send_line(
            port,
            {
                "method": "device_connect",
                "params": {"port": "COM6", "auto_start_streaming": False},
            },
        )
        assert r.get("ok") is True
        assert r.get("action") == "connect_device"
        assert calls == [
            (
                "connect_device",
                {"port": "COM6", "auto_start_streaming": False},
            )
        ]
    finally:
        time.sleep(0.05)
        mgr.stop()


def test_line_in_list_devices_tcp():
    pytest.importorskip("numpy")
    pytest.importorskip("sounddevice")
    mgr = DebugMcpServerManager(
        get_connection_state=lambda: {"connected": False, "port": ""},
        invoke_action=lambda _a, _p: {"ok": True},
        get_log_path=lambda: None,
        log=lambda _m: None,
    )
    port = _free_port()
    mgr.start(port=port)
    try:
        r = _send_line(port, {"method": "line_in_list_devices"})
        assert r.get("ok") is True
        assert "devices" in r
        assert isinstance(r["devices"], list)
    finally:
        time.sleep(0.05)
        mgr.stop()

