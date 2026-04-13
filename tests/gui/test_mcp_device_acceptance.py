from __future__ import annotations

import gui.mcp_device_acceptance as mda
from gui.mcp_device_acceptance import (
    _lines_appended,
    measure_library_shuffle_auto_advance,
    measure_library_shuffle_auto_advance_best_effort,
    measure_library_shuffle_auto_advance_serial,
    pick_line_in_device_index,
    run_acceptance_suite,
)


def _make_state(track: int, album: int = 0, power_on: bool = True, busy_pin: int = 0) -> dict:
    return {
        "mode": "playlist",
        "current_track": track,
        "current_album_index": album,
        "is_playing": busy_pin == 0,
        "busy_pin": busy_pin,
        "power_on": power_on,
        "tap_count_pending": 0,
        "button_down": False,
    }


def test_acceptance_suite_minimal_mocked():
    state = {"track": 1, "album": 0}

    def invoke(action: str, payload: dict) -> dict:
        if action == "physical_gesture":
            g = payload.get("gesture")
            if g == "ping":
                return {"ok": True, "device": {"ok": True, "cmd": "ping"}}
            if g == "get_state":
                return {
                    "ok": True,
                    "device": {
                        "ok": True,
                        "cmd": "get_state",
                        "state": _make_state(state["track"], state["album"]),
                    },
                }
            if g == "single_tap":
                state["track"] = 2
                return {"ok": True, "device": {"ok": True, "cmd": "single_tap"}}
        if action == "device_stream_tail":
            return {
                "ok": True,
                "lines": [
                    "Button PRESSED at 1000",
                    "Button RELEASED at 1050, duration: 50ms",
                    "Single tap: next track",
                    "_resolve_input: taps=1, hold=False",
                ],
            }
        return {"ok": False, "error": "unexpected", "action": action}

    r = run_acceptance_suite(invoke=invoke, target="device", suite_profile="minimal")
    assert r["ok"] is True
    assert r["track_changed"] is True
    assert any(s["name"] == "ping" and s["ok"] for s in r["steps"])
    assert any(s["name"] == "power_on_flag" and s["ok"] for s in r["steps"])
    assert any(s["name"] == "single_tap" and s["ok"] for s in r["steps"])


def test_acceptance_suite_emulator_skips_serial_ring():
    etrack = {"n": 3, "album": 0}

    def invoke(action: str, payload: dict) -> dict:
        if action == "physical_gesture":
            g = payload.get("gesture")
            if g == "ping":
                return {"ok": True, "device": {"ok": True}}
            if g == "get_state":
                return {
                    "ok": True,
                    "device": {
                        "ok": True,
                        "state": _make_state(etrack["n"], etrack["album"]),
                    },
                }
            if g == "single_tap":
                etrack["n"] = 4
                return {"ok": True, "device": {"ok": True}}
        if action == "device_stream_tail":
            raise AssertionError("emulator suite should not request stream tail")
        return {"ok": False}

    r = run_acceptance_suite(invoke=invoke, target="emulator", suite_profile="minimal")
    assert r["ok"] is True
    assert r["track_changed"] is True


def test_acceptance_suite_power_off_fails():
    """If power_on is False, power_on_flag step fails (buttons won't work)."""
    def invoke(action: str, payload: dict) -> dict:
        if action == "physical_gesture":
            g = payload.get("gesture")
            if g == "ping":
                return {"ok": True, "device": {"ok": True}}
            if g == "get_state":
                return {
                    "ok": True,
                    "device": {"ok": True, "state": _make_state(1, power_on=False, busy_pin=1)},
                }
            if g == "single_tap":
                return {"ok": True, "device": {"ok": True}}
        if action == "device_stream_tail":
            return {"ok": True, "lines": []}
        return {"ok": False}

    r = run_acceptance_suite(invoke=invoke, target="device", suite_profile="minimal")
    power_step = next((s for s in r["steps"] if s["name"] == "power_on_flag"), None)
    assert power_step is not None
    assert power_step["ok"] is False


def test_acceptance_suite_ping_fail_stops_early():
    """If ping fails the suite returns immediately with ok=False."""
    def invoke(action: str, payload: dict) -> dict:
        if action == "physical_gesture" and payload.get("gesture") == "ping":
            return {"ok": False, "error": "ipc_timeout"}
        return {"ok": False}

    r = run_acceptance_suite(invoke=invoke, target="device", suite_profile="full")
    assert r["ok"] is False
    assert len(r["steps"]) == 1
    assert r["steps"][0]["name"] == "ping"
    assert r["steps"][0]["ok"] is False


def test_acceptance_suite_standard_double_tap():
    """Standard profile exercises double_tap and checks track retreat."""
    state = {"track": 5, "album": 0}

    def invoke(action: str, payload: dict) -> dict:
        if action == "physical_gesture":
            g = payload.get("gesture")
            if g == "ping":
                return {"ok": True, "device": {"ok": True}}
            if g == "get_state":
                return {
                    "ok": True,
                    "device": {"ok": True, "state": _make_state(state["track"], state["album"])},
                }
            if g == "single_tap":
                state["track"] += 1
                return {"ok": True, "device": {"ok": True}}
            if g == "double_tap":
                state["track"] -= 1
                return {"ok": True, "device": {"ok": True}}
        if action == "device_stream_tail":
            return {
                "ok": True,
                "lines": [
                    "Button PRESSED at 2000",
                    "Button RELEASED at 2045",
                    "TAP #2 (45ms)",
                    "_resolve_input: taps=2",
                ],
            }
        return {"ok": False}

    r = run_acceptance_suite(invoke=invoke, target="device", suite_profile="standard")
    double_step = next((s for s in r["steps"] if s["name"] == "double_tap"), None)
    assert double_step is not None and double_step["ok"] is True
    retreat_step = next((s for s in r["steps"] if s["name"] == "track_retreated_after_double_tap"), None)
    assert retreat_step is not None and retreat_step["ok"] is True


def test_pick_line_in_prefers_vintage_radio_name():
    devices = [
        {"index": 1, "name": "Line In (Realtek USB Audio)"},
        {"index": 7, "name": "Vintage Radio Line In"},
        {"index": 2, "name": "Microphone (Something)"},
    ]
    assert pick_line_in_device_index(devices, 1) == 7


def test_pick_line_in_fallback_realtek():
    devices = [
        {"index": 3, "name": "Line In (Realtek USB Audio)"},
        {"index": 0, "name": "Microsoft Sound Mapper - Input"},
    ]
    assert pick_line_in_device_index(devices, 0) == 3


def test_pick_line_in_empty():
    assert pick_line_in_device_index([], 1) is None


def test_measure_library_shuffle_auto_advance_two_fast_gaps():
    """Busy HIGH -> busy LOW gaps under 1s should pass."""
    q = [
        {"busy_pin": 0},
        {"busy_pin": 0},
        {"busy_pin": 1},
        {"busy_pin": 0},
        {"busy_pin": 0},
        {"busy_pin": 1},
        {"busy_pin": 0},
    ]

    def get_state():
        return q.pop(0) if q else {"busy_pin": 0}

    logs: list[str] = []
    r = measure_library_shuffle_auto_advance(
        get_state=get_state,
        log=lambda m: logs.append(m),
        num_samples=2,
        max_gap_ok_s=1.0,
        max_wait_track_end_s=5.0,
        max_wait_next_start_s=5.0,
        poll_s=0.001,
    )
    assert r["ok"] is True
    assert len(r["gaps_detail"]) == 2
    assert r["max_gap_s"] < 1.0


def test_lines_appended_prefix_extension():
    assert _lines_appended(["a", "b"], ["a", "b", "c", "d"]) == ["c", "d"]


def test_measure_library_shuffle_auto_advance_serial_one_sample(monkeypatch):
    monkeypatch.setattr("gui.mcp_device_acceptance.time.sleep", lambda *a, **k: None)
    calls = [0]

    def tail(_n):
        calls[0] += 1
        c = calls[0]
        if c == 1:
            return ["a"]
        if c == 2:
            return ["a", "Track finished, auto-advancing"]
        if c == 3:
            return ["a", "Track finished, auto-advancing", "DF: BUSY went LOW -> playback started"]
        return ["a", "Track finished, auto-advancing", "DF: BUSY went LOW -> playback started"]

    r = measure_library_shuffle_auto_advance_serial(
        tail_lines_fn=tail,
        log=lambda _m: None,
        num_samples=1,
        max_gap_ok_s=1.0,
        max_wait_track_end_s=10.0,
        max_wait_next_start_s=10.0,
        poll_s=0.001,
    )
    assert r["ok"] is True
    assert r["method"] == "serial_log"
    assert len(r["gaps_detail"]) == 1


def test_measure_library_shuffle_auto_advance_fails_slow_gap():
    """Gap > limit fails."""
    import time as time_module

    t0 = time_module.time()

    def get_state():
        elapsed = time_module.time() - t0
        # playing -> idle at 0.02s -> next play at 0.02 + 1.5s
        if elapsed < 0.02:
            return {"busy_pin": 0}
        if elapsed < 0.025:
            return {"busy_pin": 1}
        if elapsed < 2.0:
            return {"busy_pin": 1}
        return {"busy_pin": 0}

    r = measure_library_shuffle_auto_advance(
        get_state=get_state,
        log=lambda _m: None,
        num_samples=1,
        max_gap_ok_s=1.0,
        max_wait_track_end_s=5.0,
        max_wait_next_start_s=10.0,
        poll_s=0.01,
    )
    assert r["ok"] is False
    assert r["gaps_detail"] and r["gaps_detail"][0]["gap_s"] > 1.0


def test_measure_auto_advance_best_effort_does_not_fallback_when_serial_gaps_fail(monkeypatch):
    """Gap-over-limit serial result must not be replaced by a passing busy_pin pass."""

    def fake_serial(**kwargs):
        return {
            "ok": False,
            "gaps_detail": [{"sample": 1, "gap_s": 2.0, "ok": False}],
            "max_gap_s": 2.0,
            "threshold_s": 1.15,
            "method": "serial_log",
        }

    def fake_busy(**kwargs):
        return {"ok": True, "method": "busy_pin", "gaps_detail": [{"sample": 1, "gap_s": 0.1, "ok": True}]}

    monkeypatch.setattr(mda, "measure_library_shuffle_auto_advance_serial", lambda **k: fake_serial())
    monkeypatch.setattr(mda, "measure_library_shuffle_auto_advance", lambda **k: fake_busy())
    r = measure_library_shuffle_auto_advance_best_effort(
        get_state=lambda: None,
        tail_lines_fn=lambda n: [],
        log=lambda _m: None,
    )
    assert r["method"] == "serial_log"
    assert r["ok"] is False
    assert r["max_gap_s"] == 2.0
