"""Lightweight local debug MCP-style server for runtime troubleshooting.

This server is intentionally minimal and localhost-only. It is designed for
developer-only workflows and is started explicitly from UI/command surfaces.
Protocol: newline-delimited JSON requests/responses.
"""

from __future__ import annotations

import json
import socket
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, Optional


JsonDict = Dict[str, Any]


class DebugMcpServerManager:
    def __init__(
        self,
        *,
        get_connection_state: Callable[[], JsonDict],
        invoke_action: Callable[[str, Optional[JsonDict]], JsonDict],
        get_log_path: Callable[[], Optional[str]],
        log: Callable[[str], None],
    ) -> None:
        self._get_connection_state = get_connection_state
        self._invoke_action = invoke_action
        self._get_log_path = get_log_path
        self._log = log
        self._host = "127.0.0.1"
        self._port = 0
        self._sock: Optional[socket.socket] = None
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._started_at = 0.0

    def is_running(self) -> bool:
        t = self._thread
        return bool(t and t.is_alive() and self._sock is not None)

    def status(self) -> JsonDict:
        st = self._get_connection_state()
        return {
            "running": self.is_running(),
            "host": self._host,
            "port": self._port,
            "uptime_s": max(0.0, time.time() - self._started_at) if self._started_at else 0.0,
            "device": st,
            "log_path": self._get_log_path(),
        }

    def start(self, *, host: str = "127.0.0.1", port: int = 8765) -> JsonDict:
        with self._lock:
            if self.is_running():
                return {"ok": True, "message": "already running", "status": self.status()}

            # Localhost server is useful for status/log even when the Pico is unplugged;
            # device actions report connection state in their responses.

            self._host = host
            self._port = int(port)
            self._stop.clear()
            self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self._sock.bind((self._host, self._port))
            self._sock.listen(8)
            self._sock.settimeout(0.5)
            self._started_at = time.time()
            self._thread = threading.Thread(target=self._serve, daemon=True, name="DebugMcpServer")
            self._thread.start()
            self._log("MCP debug server started on {}:{}".format(self._host, self._port))
            return {"ok": True, "status": self.status()}

    def stop(self) -> JsonDict:
        with self._lock:
            self._stop.set()
            sock = self._sock
            self._sock = None
            if sock is not None:
                try:
                    sock.close()
                except OSError:
                    pass
            self._log("MCP debug server stopped")
            return {"ok": True, "status": self.status()}

    def _serve(self) -> None:
        sock = self._sock
        if sock is None:
            return
        while not self._stop.is_set():
            try:
                conn, _addr = sock.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            threading.Thread(target=self._handle_client, args=(conn,), daemon=True).start()

    def _handle_client(self, conn: socket.socket) -> None:
        try:
            conn.settimeout(10.0)
            buf = b""
            while not self._stop.is_set():
                chunk = conn.recv(4096)
                if not chunk:
                    break
                buf += chunk
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        req = json.loads(line.decode("utf-8"))
                    except Exception as e:
                        self._send(conn, {"ok": False, "error": "invalid_json", "detail": str(e)})
                        continue
                    if isinstance(req, dict):
                        meth = str(req.get("method", "")).strip()
                        par = req.get("params") if isinstance(req.get("params"), dict) else {}
                        if meth == "line_in_analyze":
                            try:
                                dur = float(par.get("duration_s", 5.0))
                            except (TypeError, ValueError):
                                dur = 5.0
                            conn.settimeout(max(60.0, min(dur + 45.0, 180.0)))
                        elif meth in ("run_full_acceptance", "run_acceptance_suite"):
                            # Suite runs many minutes (gestures + multiple line-in captures).
                            conn.settimeout(7200.0)
                        elif meth == "invoke_action":
                            act = str((par or {}).get("action", "")).strip()
                            if act == "install_basic_to_pico":
                                conn.settimeout(650.0)
                    resp = self._dispatch(req if isinstance(req, dict) else {})
                    conn.settimeout(10.0)
                    self._send(conn, resp)
        except Exception as e:
            self._log("MCP client handler error: {}".format(e))
        finally:
            try:
                conn.close()
            except OSError:
                pass

    @staticmethod
    def _send(conn: socket.socket, payload: JsonDict) -> None:
        data = (json.dumps(payload, ensure_ascii=True) + "\n").encode("utf-8")
        conn.sendall(data)

    def _read_log_tail(self, limit: int) -> JsonDict:
        p = self._get_log_path()
        if not p:
            return {"ok": False, "error": "no_log_path"}
        path = Path(p)
        if not path.exists():
            return {"ok": False, "error": "log_missing", "path": str(path)}
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
            lines = text.splitlines()
            return {"ok": True, "path": str(path), "lines": lines[-max(1, int(limit)) :]}
        except Exception as e:
            return {"ok": False, "error": "log_read_failed", "detail": str(e)}

    def _run_script(self, name: str) -> JsonDict:
        # Minimal built-in script; callers can sequence custom steps via run_button_script.
        if name != "basic_smoke":
            return {"ok": False, "error": "unknown_script", "name": name}
        results = []
        for action in ("start_streaming", "restart_firmware"):
            results.append({"action": action, "result": self._invoke_action(action, None)})
            time.sleep(0.2)
        return {"ok": True, "script": name, "results": results}

    def run_script(self, name: str) -> JsonDict:
        return self._run_script(name)

    def _run_steps(self, steps: Any) -> JsonDict:
        if not isinstance(steps, list):
            return {"ok": False, "error": "steps_must_be_list"}
        out = []
        for idx, step in enumerate(steps):
            if not isinstance(step, dict):
                out.append({"index": idx, "ok": False, "error": "step_not_object"})
                continue
            action = str(step.get("action", "")).strip()
            if action == "wait":
                ms = int(step.get("ms", 250))
                time.sleep(max(0, ms) / 1000.0)
                out.append({"index": idx, "ok": True, "action": "wait", "ms": ms})
                continue
            payload = step.get("payload")
            out.append({"index": idx, "action": action, "result": self._invoke_action(action, payload)})
        return {"ok": True, "results": out}

    def _dispatch(self, req: JsonDict) -> JsonDict:
        method = str(req.get("method", "")).strip()
        params = req.get("params", {})
        if not isinstance(params, dict):
            params = {}

        if method in ("ping", "health"):
            return {"ok": True, "pong": True, "ts": time.time()}
        if method == "status":
            return {"ok": True, "status": self.status()}
        if method == "get_connection_state":
            return {"ok": True, "state": self._get_connection_state()}
        if method == "get_log_tail":
            return self._read_log_tail(int(params.get("limit", 200)))
        if method == "invoke_action":
            action = str(params.get("action", "")).strip()
            return {"ok": True, "result": self._invoke_action(action, params.get("payload"))}
        if method == "run_test_script":
            return self._run_script(str(params.get("name", "basic_smoke")))
        if method == "run_button_script":
            return self._run_steps(params.get("steps", []))
        if method == "get_device_stream_tail":
            return self._invoke_action(
                "device_stream_tail", {"limit": int(params.get("limit", 200))}
            )
        if method == "run_acceptance_suite":
            from .mcp_device_acceptance import run_acceptance_suite

            suite = run_acceptance_suite(
                invoke=self._invoke_action,
                target=str(params.get("target", "device")),
                suite_profile=str(params.get("suite_profile", "minimal")),
            )
            return {"ok": bool(suite.get("ok")), "suite": suite}
        if method == "run_full_acceptance":
            from .mcp_device_acceptance import run_device_acceptance_full

            def _request(method_name: str, method_params: dict) -> dict:
                return self._dispatch({"method": method_name, "params": method_params})

            suite = run_device_acceptance_full(
                invoke=self._invoke_action,
                request=_request,
                target=str(params.get("target", "device")),
            )
            return {"ok": bool(suite.get("ok")), "suite": suite}
        if method == "device_connect":
            return self._invoke_action("connect_device", params)
        if method == "line_in_list_devices":
            from .mcp_line_in_analysis import list_input_devices

            return list_input_devices()
        if method == "line_in_analyze":
            from .mcp_line_in_analysis import capture_and_analyze
            from .resource_paths import resource_path

            ref = params.get("reference_wav")
            ref_s = str(ref).strip() if ref else ""
            if not ref_s:
                am = resource_path("AMradioSound.wav")
                if am.is_file():
                    ref_s = str(am)
            try:
                duration_s = float(params.get("duration_s", 5.0))
            except (TypeError, ValueError):
                duration_s = 5.0
            try:
                sample_rate = int(params.get("sample_rate", 48000))
            except (TypeError, ValueError):
                sample_rate = 48000
            dev = params.get("device")
            device = None
            if dev is not None and str(dev).strip() != "":
                try:
                    device = int(dev)
                except (TypeError, ValueError):
                    device = None
            windows = params.get("windows")
            if windows is not None and not isinstance(windows, list):
                windows = None
            return capture_and_analyze(
                duration_s=duration_s,
                sample_rate=sample_rate,
                device=device,
                reference_wav=ref_s or None,
                windows=windows,
            )
        return {"ok": False, "error": "unknown_method", "method": method}

