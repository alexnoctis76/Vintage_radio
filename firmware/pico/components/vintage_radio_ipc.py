"""Non-REPL test IPC: read VRTEST lines from USB stdin while main loop runs.

Host sends lines like: VRTEST single_tap
Device replies (stdout): VRTEST_RESULT {"ok": true, ...}

Requires MicroPython uselect + pollable sys.stdin (RP2040 USB VCP).
"""

import json
import time

try:
    import uselect
except ImportError:
    uselect = None

_ipc_line_buf = ""
_poller = None
_ipc_warned = False


def _ensure_poller():
    global _poller, _ipc_warned
    if uselect is None:
        if not _ipc_warned:
            print("VRTEST: uselect missing, IPC disabled")
            _ipc_warned = True
        return None
    if _poller is not None:
        return _poller
    try:
        import sys

        p = uselect.poll()
        p.register(sys.stdin, uselect.POLLIN)
        _poller = p
        print("VRTEST IPC: uselect stdin polling enabled")
        return p
    except Exception as e:
        if not _ipc_warned:
            print("VRTEST: stdin poll unavailable:", e)
            _ipc_warned = True
        return None


def _emit(obj) -> None:
    print("VRTEST_RESULT " + json.dumps(obj))


def _pump(fw, total_ms: int) -> None:
    from radio_core import ticks_ms, ticks_diff

    deadline = ticks_ms() + int(total_ms)
    while ticks_diff(ticks_ms(), deadline) < 0:
        ts = getattr(fw.hw, "tick_stream", None)
        if ts:
            n = 4 if getattr(fw.hw, "_stream_file", None) is not None else 1
            for _ in range(n):
                ts()
        if getattr(fw.hw, "_df_read_pending", None):
            fw.hw._df_read_pending()
        fw.core.tick()
        time.sleep_ms(2)


def _resolve_pending_input(fw) -> None:
    from radio_core import TAP_WINDOW_MS

    _pump(fw, TAP_WINDOW_MS + 60)
    for _ in range(80):
        ts = getattr(fw.hw, "tick_stream", None)
        if ts:
            n = 4 if getattr(fw.hw, "_stream_file", None) is not None else 1
            for _ in range(n):
                ts()
        if getattr(fw.hw, "_df_read_pending", None):
            fw.hw._df_read_pending()
        fw.core.tick()
        time.sleep_ms(1)


def _tap_press_release(fw, hold_ms: int = 45) -> None:
    c = fw.core
    c.on_button_press()
    time.sleep_ms(int(hold_ms))
    c.on_button_release()


def _cmd_single_tap(fw) -> None:
    _tap_press_release(fw, 45)
    _resolve_pending_input(fw)


def _cmd_double_tap(fw) -> None:
    _tap_press_release(fw, 45)
    time.sleep_ms(90)
    _tap_press_release(fw, 45)
    _resolve_pending_input(fw)


def _cmd_triple_tap(fw) -> None:
    _tap_press_release(fw, 45)
    time.sleep_ms(85)
    _tap_press_release(fw, 45)
    time.sleep_ms(85)
    _tap_press_release(fw, 45)
    _resolve_pending_input(fw)


def _cmd_four_tap(fw) -> None:
    for _ in range(3):
        _tap_press_release(fw, 45)
        time.sleep_ms(85)
    _tap_press_release(fw, 45)
    _resolve_pending_input(fw)


def _cmd_five_tap(fw) -> None:
    for _ in range(4):
        _tap_press_release(fw, 45)
        time.sleep_ms(85)
    _tap_press_release(fw, 45)
    _resolve_pending_input(fw)


def _cmd_long_press(fw) -> None:
    from radio_core import LONG_PRESS_MS

    c = fw.core
    c.on_button_press()
    time.sleep_ms(LONG_PRESS_MS + 80)
    c.on_button_release()
    _resolve_pending_input(fw)


def _cmd_combo_tap_then_long(fw, n_taps: int) -> None:
    """n_taps quick taps followed by a long press.

    Gesture semantics (basic mode):
      1 tap + hold  -> exit shuffle to playlist (MODE_PLAYLIST)
      2 taps + hold -> track shuffle / reshuffle current station (MODE_SHUFFLE, source='station')
      3 taps + hold -> station 1 + track shuffle (reshuffle; stays in shuffle, not ordered mode)
    """
    from radio_core import LONG_PRESS_MS

    c = fw.core
    for _ in range(n_taps):
        c.on_button_press()
        time.sleep_ms(45)
        c.on_button_release()
        time.sleep_ms(80)
    c.on_button_press()
    time.sleep_ms(LONG_PRESS_MS + 80)
    c.on_button_release()
    _resolve_pending_input(fw)


def _cmd_get_state(fw) -> dict:
    c = fw.core
    playing = None
    busy = None
    try:
        playing = bool(fw.hw.is_playing())
    except Exception:
        playing = None
    try:
        busy = int(fw.hw.pin_busy.value()) if getattr(fw.hw, "pin_busy", None) else None
    except Exception:
        busy = None
    return {
        "mode": c.mode,
        "current_track": c.current_track,
        "current_album_index": c.current_album_index,
        "is_playing": playing,
        "busy_pin": busy,
        "power_on": c.power_on,
        "tap_count_pending": c.tap_count,
        "button_down": c.button_down,
        "shuffle_source_type": getattr(c, "_shuffle_source_type", None),
        "station_cycle_shuffle_active": False,
        "total_playlists": len(c.playlists) if getattr(c, "playlists", None) else 0,
        "playing_folder": getattr(fw.hw, "_playing_folder", None),
        "playing_track": getattr(fw.hw, "_playing_track", None),
    }


def _handle_line(fw, arg: str) -> None:
    cmd = arg.strip()
    if not cmd or cmd == "ping":
        _emit({"ok": True, "cmd": "ping"})
        return
    if cmd == "get_state":
        _emit({"ok": True, "cmd": "get_state", "state": _cmd_get_state(fw)})
        return
    if cmd == "single_tap":
        _cmd_single_tap(fw)
        _emit({"ok": True, "cmd": "single_tap"})
        return
    if cmd == "double_tap":
        _cmd_double_tap(fw)
        _emit({"ok": True, "cmd": "double_tap"})
        return
    if cmd == "triple_tap":
        _cmd_triple_tap(fw)
        _emit({"ok": True, "cmd": "triple_tap"})
        return
    if cmd == "four_tap":
        _cmd_four_tap(fw)
        _emit({"ok": True, "cmd": "four_tap"})
        return
    if cmd == "five_tap":
        _cmd_five_tap(fw)
        _emit({"ok": True, "cmd": "five_tap"})
        return
    if cmd == "long_press":
        _cmd_long_press(fw)
        _emit({"ok": True, "cmd": "long_press"})
        return
    if cmd == "tap_long_press":
        _cmd_combo_tap_then_long(fw, 1)
        _emit({"ok": True, "cmd": "tap_long_press"})
        return
    if cmd == "double_tap_long_press":
        _cmd_combo_tap_then_long(fw, 2)
        _emit({"ok": True, "cmd": "double_tap_long_press"})
        return
    if cmd == "triple_tap_long_press":
        _cmd_combo_tap_then_long(fw, 3)
        _emit({"ok": True, "cmd": "triple_tap_long_press"})
        return
    _emit({"ok": False, "error": "unknown_command", "cmd": cmd})


def poll_ipc(fw) -> None:
    """Call once per main-loop iteration. Drains at most one VRTEST line per call."""
    global _ipc_line_buf
    p = _ensure_poller()
    if p is None:
        return
    try:
        if not p.poll(0):
            return
    except Exception:
        return
    try:
        import sys

        # read(256) can block until that many bytes arrive on USB CDC, freezing the main loop.
        # Drain only what poll() indicates is ready, one byte at a time (max per iteration).
        chunk_parts = []
        for _ in range(256):
            try:
                ready = p.poll(0)
            except Exception:
                break
            if not ready:
                break
            c = sys.stdin.read(1)
            if not c:
                break
            chunk_parts.append(c)
        chunk = "".join(chunk_parts)
    except Exception as e:
        _emit({"ok": False, "error": "stdin_read_failed", "detail": str(e)})
        return
    if not chunk:
        return
    _ipc_line_buf += chunk
    while "\n" in _ipc_line_buf:
        raw, _ipc_line_buf = _ipc_line_buf.split("\n", 1)
        line = raw.strip()
        if not line.startswith("VRTEST "):
            continue
        arg = line[7:].strip()
        fw._ipc_synthetic_active = True
        try:
            _handle_line(fw, arg)
        except Exception as e:
            try:
                import sys

                sys.print_exception(e)
            except Exception:
                pass
            _emit({"ok": False, "error": "exception", "detail": str(e)})
        finally:
            fw._ipc_synthetic_active = False
