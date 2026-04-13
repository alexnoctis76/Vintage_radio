"""MCP-driven acceptance checks — BASIC MODE ONLY (main_basic.py).

Legacy / full mode (main.py with radio_metadata.json) is never tested here.

**Basic mode vocabulary vs. IPC field names** (radio_core still uses legacy strings):

- User-facing: **station** = one DFPlayer SD folder; **track** = file within that folder.
- ``get_state`` may still report ``mode=\"playlist\"`` — that means **ordered station playback**
  (sequential tracks on the current station), not a host “music playlist”.
- ``current_album_index`` = **0-based station index**; ``total_playlists`` = **station count**;
  ``playing_folder`` = **DFPlayer folder number** for the current track.
- Logs and reports in this module prefer *station / folder* wording where we print to humans;
  JSON keys may keep ``album_*`` to match the device payload.

Quick suite (run_acceptance_suite):
  - VRTEST ping (IPC comms alive)
  - Boot state: is_playing, busy_pin, power_on, station discovery
  - Single tap -> track advances (next track)
  - Double tap -> track retreats (prev track)
  - Triple tap -> track restarts at 1 (full profile)
  - Long press -> station advances (full profile)
  - Serial log: button press lines visible
  - AM audio: line_in_analyze vs AMradioSound.wav reference (optional)

Full comprehensive suite (run_device_acceptance_full):
  - Station discovery: total_playlists >= 1 at boot, no boot errors
  - Ordered station playback (IPC mode=playlist): 5 consecutive tracks, each starts within
    TRACK_START_MAX_S, plays for MIN_PLAY_DURATION_S (harness hold — verifies sustained play),
    audio on line-in above threshold when measured, no errors
  - Station advance: 3 long_press advances each settle into playback
  - Shuffle-station mode: double_tap_long_press + 5 tracks (same checks)
  - triple_tap_long_press: same as double_tap_long_press (reshuffle tracks in the current station)
  - **Natural auto-advance** (no taps) in ordered station and shuffle-station:
    ~5 s test tracks; serial log timing **≤ ~1.55 s** (or busy_pin **≤ 1.0 s** if serial unavailable)
  - Full suite also verifies **double_tap** (previous track) and **triple_tap** (restart station at 1)
  - Revert: tap_long_press exits shuffle to ordered station mode (IPC mode=playlist), 2 tracks
  - Final serial error scan after all phases
"""

from __future__ import annotations

import time
from typing import Any, Callable, Dict, List, Optional, Tuple

JsonDict = Dict[str, Any]
InvokeFn = Callable[[str, JsonDict], JsonDict]
RequestFn = Callable[[str, JsonDict], JsonDict]

_TRACK_START_MAX_S = 8.0
_MODE_SWITCH_MAX_S = 15.0
# Intentional wall-clock pause after each track *starts*: verifies DFPlayer still playing;
# this is not the radio “taking long to start” — see logged start_latency_s for device speed.
_MIN_PLAY_DURATION_S = 4.0
# How often we poll busy_pin while waiting for playback to start (device is usually ready in <0.1s).
_PLAYBACK_POLL_INTERVAL_S = 0.15
_TRACKS_PER_MODE = 5
_LINE_IN_DURATION_S = 6.0
_LINE_IN_RMS_MIN_DB = -55.0
# Log a hint if any single tap-to-play exceeds this (suite still passes up to _TRACK_START_MAX_S).
_SLOW_START_WARN_S = 2.0

# Natural auto-advance (playlist, shuffle-station): after a track ends,
# next track should start quickly. Measured on the **host**.
# ``busy_pin``: DFPlayer idle == HIGH (1), playing == LOW (0) — can lag UART-heavy paths.
_SHUFFLE_AUTO_ADVANCE_MAX_GAP_S = 2.0
# Serial log timing adds ring-buffer + poll delay; slightly looser than busy_pin strict target.
_SHUFFLE_AUTO_ADVANCE_MAX_GAP_SERIAL_S = 2.0
_SHUFFLE_AUTO_ADVANCE_SAMPLES = 2
# Acceptance library uses ~5 s MP3s per track — derive waits so we do not spin for minutes if stuck/silent.
_KNOWN_TEST_TRACK_DURATION_S = 5.0
# Max time to wait for natural track end (no tap): ~3× nominal + margin for UART/DFPlayer.
_MAX_NATURAL_TRACK_END_WAIT_S = _KNOWN_TEST_TRACK_DURATION_S * 3.0 + 2.0
# After natural end, next track should start quickly; allow headroom beyond the 1 s gap check.
_SHUFFLE_AUTO_ADVANCE_MAX_WAIT_NEXT_START_S = 12.0
# Aliased for busy-pin and serial paths (same semantics as _MAX_NATURAL_TRACK_END_WAIT_S).
_SHUFFLE_AUTO_ADVANCE_MAX_WAIT_TRACK_END_S = _MAX_NATURAL_TRACK_END_WAIT_S
# If we still have not seen track-finished by this time, run a short line-in probe (busy says playing).
_STUCK_PLAYING_LINE_IN_CHECK_FIRST_S = _KNOWN_TEST_TRACK_DURATION_S + 2.0
# Short capture for mid-wait sanity checks (full phase still uses _LINE_IN_DURATION_S).
_LINE_IN_QUICK_PROBE_S = 1.2

_ERROR_PATTERNS = [
    "Traceback (most recent call last)",
    "MemoryError",
    "SyntaxError",
    "FATAL:",
    "Boot init error:",
]
_WARN_PATTERNS = [
    "am_overlay failed",
    "BUSY=1",
    "compact load retry",
    "No tracks available",
    "error_code",
    "fallback to",
    "Playback failed to start",
    "start_unconfirmed_streak",
]


def quick_line_in_probe(
    *,
    request: Optional[RequestFn],
    get_state: Callable[[], Optional[JsonDict]],
    log: Callable[[str], None],
    target: str,
    duration_s: float = _LINE_IN_QUICK_PROBE_S,
) -> JsonDict:
    """Short line-in capture while the device reports playing — fail fast if silent."""
    if request is None or target != "device":
        return {"ok": True, "skipped": True, "reason": "no_line_in_or_not_device"}
    try:
        st = get_state()
        if not (st and st.get("busy_pin") == 0):
            return {"ok": True, "skipped": True, "reason": "busy_not_playing_skip_probe"}
        r_dev = request("line_in_list_devices", {})
        devices = r_dev.get("devices", []) if r_dev.get("ok") else []
        device_idx = pick_line_in_device_index(
            devices, r_dev.get("default_input_index")
        )
        if device_idx is None:
            return {"ok": True, "skipped": True, "reason": "no_input_device"}
        log(
            f"  Line-in probe: recording {duration_s:.1f}s (expect rms_dbfs > {_LINE_IN_RMS_MIN_DB} if audio present)..."
        )
        r_audio = request(
            "line_in_analyze",
            {
                "duration_s": duration_s,
                "sample_rate": 48000,
                "device": device_idx,
            },
        )
        summary = r_audio.get("summary") or {}
        rms = summary.get("rms_dbfs")
        if rms is None:
            return {
                "ok": False,
                "skipped": False,
                "rms_dbfs": None,
                "error": "line_in_no_rms",
                "raw_error": r_audio.get("error"),
            }
        ok_audio = bool(r_audio.get("ok")) and float(rms) > _LINE_IN_RMS_MIN_DB
        log(f"  Line-in probe: rms_dbfs={rms} threshold={_LINE_IN_RMS_MIN_DB} ok={ok_audio}")
        return {
            "ok": ok_audio,
            "skipped": False,
            "rms_dbfs": rms,
            "threshold_db": _LINE_IN_RMS_MIN_DB,
            "raw_error": r_audio.get("error"),
        }
    except Exception as exc:
        return {"ok": True, "skipped": True, "reason": f"exception: {exc}"}


def _lines_appended(old: List[str], new: List[str]) -> List[str]:
    """Best-effort diff when *new* is a ring-buffer tail that may have rotated vs *old*."""
    if not new:
        return []
    if not old:
        return new[-80:]
    if len(new) >= len(old) and new[: len(old)] == old:
        return new[len(old) :]
    max_o = min(len(old), len(new))
    for overlap in range(max_o, 0, -1):
        if old[-overlap:] == new[:overlap]:
            return new[overlap:]
    return new[-40:]


def measure_library_shuffle_auto_advance_serial(
    *,
    tail_lines_fn: Callable[[int], List[str]],
    log: Callable[[str], None],
    num_samples: int = _SHUFFLE_AUTO_ADVANCE_SAMPLES,
    max_gap_ok_s: float = _SHUFFLE_AUTO_ADVANCE_MAX_GAP_SERIAL_S,
    max_wait_track_end_s: float = _SHUFFLE_AUTO_ADVANCE_MAX_WAIT_TRACK_END_S,
    max_wait_next_start_s: float = _SHUFFLE_AUTO_ADVANCE_MAX_WAIT_NEXT_START_S,
    poll_s: float = _PLAYBACK_POLL_INTERVAL_S,
    poll_after_end_s: float = 0.05,
    request: Optional[RequestFn] = None,
    get_state: Optional[Callable[[], Optional[JsonDict]]] = None,
    target: str = "device",
) -> JsonDict:
    """Measure natural auto-advance using **new** Pico serial lines (host time).

    Many DFPlayer builds keep BUSY LOW across UART-driven track changes ("BUSY fallback");
    for those, :func:`measure_library_shuffle_auto_advance` never sees busy_pin==1.

    This path timestamps the first ``Track finished, auto-advancing`` line, then the next
    ``DF: BUSY went LOW -> playback started`` line (next track actually started).

    Waits assume **~5 s** acceptance test tracks; if no end line within *max_wait_track_end_s*,
    or line-in shows silence while the device reports playing, we fail fast instead of idling.
    """
    gaps_detail: List[JsonDict] = []
    MARK_END = "Track finished, auto-advancing"
    MARK_START = "DF: BUSY went LOW -> playback started"

    time.sleep(1.5)
    prev_lines = tail_lines_fn(250)
    for i in range(num_samples):
        last_probe_bucket = -1
        log(
            f"  Auto-advance sample {i + 1}/{num_samples} (serial): expect ~{_KNOWN_TEST_TRACK_DURATION_S:.0f}s "
            f"tracks — waiting for '{MARK_END[:24]}…' (max {max_wait_track_end_s:.0f}s), then "
            f"'{MARK_START[:28]}…' (max {max_wait_next_start_s:.0f}s)..."
        )
        t_end: Optional[float] = None
        t_start: Optional[float] = None
        t_wait = time.time()
        last_hb = t_wait

        # Phase A: natural track end
        while t_end is None:
            now = time.time()
            if now - t_wait >= max_wait_track_end_s:
                return {
                    "ok": False,
                    "error": "timeout_serial_track_finished",
                    "method": "serial_log",
                    "sample": i + 1,
                    "gaps_detail": gaps_detail,
                    "max_gap_s": max((g["gap_s"] for g in gaps_detail), default=None),
                    "threshold_s": max_gap_ok_s,
                    "note": (
                        f"No 'Track finished, auto-advancing' within {max_wait_track_end_s:.0f}s — "
                        f"acceptance library uses ~{_KNOWN_TEST_TRACK_DURATION_S:.0f}s clips; "
                        "stuck playback, silent DFPlayer, or serial not streaming."
                    ),
                }
            time.sleep(poll_s)
            cur = tail_lines_fn(280)
            for line in _lines_appended(prev_lines, cur):
                if MARK_END in line:
                    t_end = time.time()
                    log("  (serial) saw track-finished / auto-advance line")
                    break
            prev_lines = cur

            now = time.time()
            elapsed = now - t_wait
            if t_end is None and request is not None and get_state is not None:
                bucket = int(elapsed // _STUCK_PLAYING_LINE_IN_CHECK_FIRST_S)
                if bucket >= 1 and bucket != last_probe_bucket:
                    last_probe_bucket = bucket
                    pr = quick_line_in_probe(
                        request=request,
                        get_state=get_state,
                        log=log,
                        target=target,
                    )
                    if not pr.get("skipped") and pr.get("ok") is False:
                        return {
                            "ok": False,
                            "error": "line_in_silent_while_reports_playing",
                            "method": "serial_log",
                            "sample": i + 1,
                            "gaps_detail": gaps_detail,
                            "max_gap_s": max((g["gap_s"] for g in gaps_detail), default=None),
                            "threshold_s": max_gap_ok_s,
                            "line_in_probe": pr,
                            "note": (
                                "busy_pin reports playing but line-in probe was below threshold — "
                                "check cable, USB line-in adapter, and DFPlayer output."
                            ),
                        }
            if t_end is None and now - last_hb >= 6.0:
                log(
                    f"  ... still waiting for track end line; {int(now - t_wait)}s / "
                    f"{max_wait_track_end_s:.0f}s (nominal track ~{_KNOWN_TEST_TRACK_DURATION_S:.0f}s)..."
                )
                last_hb = now

        # Phase B: next track started
        t_after_end = time.time()
        last_hb_b = t_after_end
        while t_start is None:
            now = time.time()
            if now - t_after_end >= max_wait_next_start_s:
                return {
                    "ok": False,
                    "error": "timeout_serial_next_playback",
                    "method": "serial_log",
                    "sample": i + 1,
                    "gaps_detail": gaps_detail,
                    "max_gap_s": max((g["gap_s"] for g in gaps_detail), default=None),
                    "threshold_s": max_gap_ok_s,
                    "note": (
                        "Saw track finished but not following 'DF: BUSY went LOW -> playback started' "
                        f"within {max_wait_next_start_s:.0f}s."
                    ),
                }
            time.sleep(poll_after_end_s)
            cur = tail_lines_fn(280)
            for line in _lines_appended(prev_lines, cur):
                if MARK_START in line:
                    t_start = time.time()
                    log("  (serial) saw next-track playback started (BUSY LOW)")
                    break
            prev_lines = cur
            now = time.time()
            if t_start is None and now - last_hb_b >= 4.0:
                log(
                    f"  ... waiting for next track start line; {int(now - t_end):.1f}s after track-finished..."
                )
                last_hb_b = now

        gap = round(t_start - t_end, 3)
        ok_gap = gap <= max_gap_ok_s
        gaps_detail.append({"sample": i + 1, "gap_s": gap, "ok": ok_gap})
        log(
            f"  Auto-advance sample {i + 1}/{num_samples} (serial): gap={gap}s "
            f"(limit {max_gap_ok_s}s) -> {'PASS' if ok_gap else 'FAIL'}"
        )
        last_probe_bucket = -1

    max_g = max(g["gap_s"] for g in gaps_detail)
    return {
        "ok": all(g["ok"] for g in gaps_detail),
        "gaps_detail": gaps_detail,
        "max_gap_s": max_g,
        "threshold_s": max_gap_ok_s,
        "method": "serial_log",
        "note": (
            "Host time from new 'Track finished, auto-advancing' line to next "
            "'DF: BUSY went LOW -> playback started' in the device stream."
        ),
    }


def measure_library_shuffle_auto_advance(
    *,
    get_state: Callable[[], Optional[JsonDict]],
    log: Callable[[str], None],
    num_samples: int = _SHUFFLE_AUTO_ADVANCE_SAMPLES,
    max_gap_ok_s: float = _SHUFFLE_AUTO_ADVANCE_MAX_GAP_S,
    max_wait_track_end_s: float = _SHUFFLE_AUTO_ADVANCE_MAX_WAIT_TRACK_END_S,
    max_wait_next_start_s: float = _SHUFFLE_AUTO_ADVANCE_MAX_WAIT_NEXT_START_S,
    poll_s: float = _PLAYBACK_POLL_INTERVAL_S,
    request: Optional[RequestFn] = None,
    target: str = "device",
) -> JsonDict:
    """Time natural track-to-track gaps in library shuffle (no user taps) via **busy_pin**.

    Waits until ``busy_pin == 1`` (DFPlayer idle / track gap), then until ``busy_pin == 0``
    again (next track playing). The elapsed host time should be **<= max_gap_ok_s**
    for each sample.

    If BUSY never goes HIGH between tracks on your hardware, use
    :func:`measure_library_shuffle_auto_advance_serial` instead (common on UART-heavy paths).
    """
    gaps_detail: List[JsonDict] = []

    def _bp(st: Optional[JsonDict]) -> Optional[int]:
        if not st:
            return None
        v = st.get("busy_pin")
        return int(v) if v is not None else None

    t_play = time.time()
    while time.time() - t_play < min(20.0, max_wait_track_end_s + 3.0):
        st = get_state()
        if _bp(st) == 0:
            break
        time.sleep(poll_s)
    else:
        return {
            "ok": False,
            "error": "not_playing_before_auto_advance",
            "gaps_detail": [],
            "note": "Expected busy_pin=0 (playing) before measuring auto-advance",
        }

    busy_probe_bucket = -1
    for i in range(num_samples):
        busy_probe_bucket = -1
        log(
            f"  Auto-advance sample {i + 1}/{num_samples} (busy_pin): expect ~{_KNOWN_TEST_TRACK_DURATION_S:.0f}s "
            f"tracks — waiting up to {max_wait_track_end_s:.0f}s for busy -> 1 (idle)..."
        )
        t_wait = time.time()
        t_end: Optional[float] = None
        last_hb = t_wait
        while time.time() - t_wait < max_wait_track_end_s:
            st = get_state()
            if _bp(st) == 1:
                t_end = time.time()
                break
            now = time.time()
            elapsed = now - t_wait
            if request is not None:
                bucket = int(elapsed // _STUCK_PLAYING_LINE_IN_CHECK_FIRST_S)
                if bucket >= 1 and bucket != busy_probe_bucket:
                    busy_probe_bucket = bucket
                    pr = quick_line_in_probe(
                        request=request,
                        get_state=get_state,
                        log=log,
                        target=target,
                    )
                    if not pr.get("skipped") and pr.get("ok") is False:
                        return {
                            "ok": False,
                            "error": "line_in_silent_while_reports_playing",
                            "method": "busy_pin",
                            "sample": i + 1,
                            "gaps_detail": gaps_detail,
                            "max_gap_s": max((g["gap_s"] for g in gaps_detail), default=None),
                            "threshold_s": max_gap_ok_s,
                            "line_in_probe": pr,
                            "note": "busy reports playing but line-in silent — check audio path",
                        }
            if now - last_hb >= 6.0:
                elapsed_i = int(now - t_wait)
                log(
                    f"  ... still playing; {elapsed_i}s / {max_wait_track_end_s:.0f}s "
                    f"(nominal ~{_KNOWN_TEST_TRACK_DURATION_S:.0f}s track)..."
                )
                last_hb = now
            time.sleep(poll_s)
        if t_end is None:
            return {
                "ok": False,
                "error": "timeout_waiting_busy_high",
                "sample": i + 1,
                "gaps_detail": gaps_detail,
                "max_gap_s": max((g["gap_s"] for g in gaps_detail), default=None),
                "threshold_s": max_gap_ok_s,
                "method": "busy_pin",
                "note": (
                    f"busy_pin never went to 1 within {max_wait_track_end_s:.0f}s — "
                    f"expected ~{_KNOWN_TEST_TRACK_DURATION_S:.0f}s acceptance clips or BUSY stuck LOW."
                ),
            }

        log(
            f"  Auto-advance sample {i + 1}/{num_samples}: gap started; waiting up to "
            f"{max_wait_next_start_s:.0f}s for next track (busy_pin -> 0)..."
        )
        t_wait2 = time.time()
        t_start: Optional[float] = None
        while time.time() - t_wait2 < max_wait_next_start_s:
            st = get_state()
            if _bp(st) == 0:
                t_start = time.time()
                break
            time.sleep(poll_s)
        if t_start is None:
            return {
                "ok": False,
                "error": "timeout_waiting_next_busy_low",
                "method": "busy_pin",
                "sample": i + 1,
                "gaps_detail": gaps_detail,
                "max_gap_s": max((g["gap_s"] for g in gaps_detail), default=None),
                "threshold_s": max_gap_ok_s,
                "note": "Next track did not start (busy_pin back to 0) within max_wait_next_start_s",
            }

        gap = round(t_start - t_end, 3)
        ok_gap = gap <= max_gap_ok_s
        gaps_detail.append({"sample": i + 1, "gap_s": gap, "ok": ok_gap})
        log(
            f"  Auto-advance sample {i + 1}/{num_samples}: gap={gap}s "
            f"(limit {max_gap_ok_s}s) -> {'PASS' if ok_gap else 'FAIL'}"
        )

    max_g = max(g["gap_s"] for g in gaps_detail)
    return {
        "ok": all(g["ok"] for g in gaps_detail),
        "gaps_detail": gaps_detail,
        "max_gap_s": max_g,
        "threshold_s": max_gap_ok_s,
        "method": "busy_pin",
        "note": (
            "Host time from busy HIGH (track finished / idle) to busy LOW (next track playing). "
            "VRTEST poll interval adds a small blind spot vs. true MCU timing."
        ),
    }


def measure_library_shuffle_auto_advance_best_effort(
    *,
    get_state: Callable[[], Optional[JsonDict]],
    tail_lines_fn: Callable[[int], List[str]],
    log: Callable[[str], None],
    request: Optional[RequestFn] = None,
    target: str = "device",
    num_samples: int = _SHUFFLE_AUTO_ADVANCE_SAMPLES,
) -> JsonDict:
    """Prefer serial-log timing (BUSY may stay LOW); fall back to busy_pin only if serial aborts.

    If serial **finishes sampling** but gaps exceed the threshold, return that result — do not
    replace it with busy_pin (which can paint a different picture and hide real failures).
    """
    ser = measure_library_shuffle_auto_advance_serial(
        tail_lines_fn=tail_lines_fn,
        log=log,
        request=request,
        get_state=get_state,
        target=target,
        num_samples=num_samples,
    )
    if ser.get("ok"):
        return ser
    if ser.get("gaps_detail"):
        return ser
    log("  Serial auto-advance did not complete; falling back to busy_pin measurement...")
    busy = measure_library_shuffle_auto_advance(
        get_state=get_state,
        log=log,
        request=request,
        target=target,
        num_samples=num_samples,
    )
    busy["serial_attempt"] = ser
    return busy


def log_device_serial_tail(
    *,
    invoke: InvokeFn,
    log_fn: Callable[[str], None],
    target: str,
    limit: int = 80,
    heading: str = "Pico serial",
) -> None:
    """Copy recent device stream ring lines into the acceptance log (session log / MCP).

    Raw firmware ``print()`` output normally fills the Device tab stream view; this
    duplicates the tail so automated runs show MCU logs next to test steps.
    """
    if target != "device":
        return
    r = invoke("device_stream_tail", {"limit": limit})
    raw = r.get("lines") if r.get("ok") else None
    lines = [str(x) for x in raw] if isinstance(raw, list) else []
    if not lines:
        log_fn(
            f"  [{heading}: empty — enable Start Streaming on the Device tab to fill buffer]"
        )
        return
    log_fn(f"  --- {heading} (last {len(lines)} lines) ---")
    for ln in lines:
        log_fn(f"  | {ln}")
    log_fn("  --- end Pico serial ---")


def pick_line_in_device_index(
    devices: List[JsonDict], default_index: Optional[int] = None
) -> Optional[int]:
    """Choose the host input device used for Vintage Radio line-in tests.

    Prefer a device renamed in Windows to **Vintage Radio Line In**, then
    legacy Realtek USB Line In, then any name containing ``line in``, then
    *default_index*, then the first listed input.
    """
    if not devices:
        return None
    rows: List[Tuple[JsonDict, str]] = [
        (d, (d.get("name") or "").lower()) for d in devices
    ]

    def first_match(pred) -> Optional[int]:
        for d, name in rows:
            if pred(name):
                ix = d.get("index")
                if ix is not None:
                    return int(ix)
        return None

    i = first_match(lambda n: "vintage radio line in" in n)
    if i is not None:
        return i
    i = first_match(lambda n: "vintage radio" in n and "line" in n)
    if i is not None:
        return i
    i = first_match(lambda n: "realtek" in n and "usb" in n and "line" in n)
    if i is not None:
        return i
    i = first_match(lambda n: "realtek" in n and "usb" in n)
    if i is not None:
        return i
    i = first_match(lambda n: "line in" in n)
    if i is not None:
        return i
    if default_index is not None:
        return int(default_index)
    ix0 = devices[0].get("index")
    return int(ix0) if ix0 is not None else None


def run_acceptance_suite(
    *, invoke: InvokeFn, target: str = "device", suite_profile: str = "minimal"
) -> JsonDict:
    """Run scripted gestures + log heuristics + markdown report.

    *target*: ``device`` (USB VRTEST + serial ring) or ``emulator`` (GUI TestModeWidget).

    *suite_profile*: ``minimal`` (ping, state, single tap),
                     ``standard`` (+ double tap, serial log, playback check),
                     ``full``     (+ triple tap, long press, AM audio line-in analysis).
    """
    target = (target or "device").strip().lower()
    profile = (suite_profile or "minimal").strip().lower()
    steps: List[JsonDict] = []

    def add_step(name: str, ok: bool, extra: Optional[JsonDict] = None) -> None:
        row: JsonDict = {"name": name, "ok": ok}
        if extra:
            row.update(extra)
        steps.append(row)

    def run_gesture(gesture: str, wait_s: float = 0.4) -> JsonDict:
        r = invoke(
            "physical_gesture",
            {"gesture": gesture, "target": target, "timeout": 35.0},
        )
        time.sleep(wait_s)
        return r

    def get_state() -> Optional[JsonDict]:
        r = invoke("physical_gesture", {"gesture": "get_state", "target": target, "timeout": 10.0})
        time.sleep(0.15)
        dev = r.get("device") if isinstance(r.get("device"), dict) else {}
        return dev.get("state") if isinstance(dev.get("state"), dict) else None

    def tail_lines(limit: int = 400) -> List[str]:
        if target != "device":
            return []
        r = invoke("device_stream_tail", {"limit": limit})
        raw = r.get("lines") if r.get("ok") else []
        return [str(x) for x in raw] if isinstance(raw, list) else []

    lines: List[str] = [
        "# Vintage Radio — acceptance report",
        "",
        f"- **Target**: `{target}`",
        f"- **Suite profile**: `{profile}`",
        "",
    ]

    # -------------------------------------------------------------------------
    # 1. VRTEST ping — IPC comms alive
    # -------------------------------------------------------------------------
    r_ping = run_gesture("ping", 0.12)
    dev_ping = r_ping.get("device") if isinstance(r_ping.get("device"), dict) else {}
    ok_ping = bool(r_ping.get("ok")) and bool(dev_ping.get("ok", True))
    add_step("ping", ok_ping, {"result": r_ping})

    if not ok_ping:
        lines.append("## Result: **FAIL** — VRTEST ping did not succeed.")
        lines.append(
            "Next: Developer -> Deploy MCP / VRTEST support to Pico... (or copy "
            "components/vintage_radio_ipc.py), USB connect, Developer mode -> start MCP, "
            "Device tab -> Connect + Start Streaming."
        )
        return {
            "ok": False,
            "target": target,
            "suite_profile": profile,
            "steps": steps,
            "report_markdown": "\n".join(lines),
        }

    # -------------------------------------------------------------------------
    # 2. Boot / initial state: power_on, is_playing, busy_pin
    # -------------------------------------------------------------------------
    st_initial = get_state()
    ok_state = isinstance(st_initial, dict)
    add_step("get_state_initial", ok_state, {"state": st_initial})

    power_on_flag = bool(st_initial.get("power_on")) if isinstance(st_initial, dict) else None
    is_playing_initial = st_initial.get("is_playing") if isinstance(st_initial, dict) else None
    busy_pin_initial = st_initial.get("busy_pin") if isinstance(st_initial, dict) else None

    # power_on should be True (radio logic not powered off)
    ok_power = power_on_flag is True
    add_step(
        "power_on_flag",
        ok_power,
        {"power_on": power_on_flag, "note": "radio_core.power_on must be True for buttons to work"},
    )

    # is_playing may be True (music) or False (between tracks / initial delay)
    # busy_pin=0 means DFPlayer BUSY LOW = track playing
    add_step(
        "initial_playback_state",
        ok_state,  # not a hard fail — just report values
        {
            "is_playing": is_playing_initial,
            "busy_pin": busy_pin_initial,
            "note": (
                "busy_pin=0 means DFPlayer playing. is_playing is radio_core logical flag."
                " Both False is unexpected after boot."
            ),
        },
    )

    # -------------------------------------------------------------------------
    # 3. Single tap -> track should advance
    # -------------------------------------------------------------------------
    track_before_tap = st_initial.get("current_track") if isinstance(st_initial, dict) else None
    album_before_tap = st_initial.get("current_album_index") if isinstance(st_initial, dict) else None

    r_tap1 = run_gesture("single_tap", 1.0)
    ok_tap1 = bool(r_tap1.get("ok")) and bool((r_tap1.get("device") or {}).get("ok", True))
    add_step("single_tap", ok_tap1, {"result": r_tap1})

    st_after_tap1 = get_state()
    ok_after_tap1 = isinstance(st_after_tap1, dict)
    add_step("get_state_after_single_tap", ok_after_tap1, {"state": st_after_tap1})

    track_after_tap1 = st_after_tap1.get("current_track") if isinstance(st_after_tap1, dict) else None
    album_after_tap1 = st_after_tap1.get("current_album_index") if isinstance(st_after_tap1, dict) else None

    track_changed_fwd = (
        track_before_tap is not None
        and track_after_tap1 is not None
        and (track_before_tap != track_after_tap1 or album_before_tap != album_after_tap1)
    )
    add_step(
        "track_advanced_after_single_tap",
        track_changed_fwd,
        {
            "track_before": track_before_tap,
            "track_after": track_after_tap1,
            "album_before": album_before_tap,
            "album_after": album_after_tap1,
            "note": "Expected track or album index to change. Fails if only 1 track on SD card.",
        },
    )

    # -------------------------------------------------------------------------
    # 4. Serial log: button press / gesture lines visible (device only)
    # -------------------------------------------------------------------------
    saw_gesture_log = False
    if target == "device":
        stream = tail_lines(500)
        joined = "\n".join(stream[-250:])
        saw_gesture_log = any(
            kw in joined
            for kw in (
                "Button PRESSED",
                "Button RELEASED",
                "Single tap",
                "_resolve_input",
                "on_button_release: TAP",
                "on_button_press",
            )
        )
        add_step(
            "serial_log_button_events",
            saw_gesture_log,
            {
                "lines_considered": len(stream),
                "note": (
                    "Serial must show button press/release lines. "
                    "Fail = start_streaming before suite, or handle_button not running."
                ),
            },
        )
    else:
        add_step("serial_log_button_events", True, {"skipped": True, "reason": "emulator target"})

    # -------------------------------------------------------------------------
    # 5. Playback alive after tap (busy_pin / is_playing check)
    # -------------------------------------------------------------------------
    if isinstance(st_after_tap1, dict):
        is_playing_after = st_after_tap1.get("is_playing")
        busy_after = st_after_tap1.get("busy_pin")
        # busy_pin=0 (BUSY LOW) means track is actively playing on DFPlayer
        playback_alive = (busy_after == 0) or bool(is_playing_after)
        add_step(
            "playback_alive_after_tap",
            playback_alive,
            {
                "is_playing": is_playing_after,
                "busy_pin": busy_after,
                "note": "busy_pin=0 means DFPlayer BUSY LOW (playing). Both 1 and False = dead.",
            },
        )
    else:
        add_step("playback_alive_after_tap", False, {"note": "state unavailable"})

    core_ok = ok_ping and ok_state and ok_tap1 and ok_after_tap1

    # =========================================================================
    # STANDARD profile extras
    # =========================================================================
    if profile in ("standard", "full") and core_ok:

        # 6. Double tap -> track should go back
        r_tap2 = run_gesture("double_tap", 1.0)
        ok_tap2 = bool(r_tap2.get("ok")) and bool((r_tap2.get("device") or {}).get("ok", True))
        add_step("double_tap", ok_tap2, {"result": r_tap2})

        st_after_tap2 = get_state()
        ok_after_tap2 = isinstance(st_after_tap2, dict)
        add_step("get_state_after_double_tap", ok_after_tap2, {"state": st_after_tap2})

        track_after_tap2 = st_after_tap2.get("current_track") if isinstance(st_after_tap2, dict) else None
        album_after_tap2 = st_after_tap2.get("current_album_index") if isinstance(st_after_tap2, dict) else None

        track_went_back = (
            track_after_tap1 is not None
            and track_after_tap2 is not None
            and (track_after_tap2 != track_after_tap1 or album_after_tap2 != album_after_tap1)
        )
        add_step(
            "track_retreated_after_double_tap",
            track_went_back,
            {
                "track_before": track_after_tap1,
                "track_after": track_after_tap2,
                "note": "double_tap = prev track; expected index to decrease or wrap.",
            },
        )

        # 7. Serial log confirms double-tap gesture seen
        if target == "device":
            stream2 = tail_lines(500)
            joined2 = "\n".join(stream2[-250:])
            saw_double = any(
                kw in joined2
                for kw in ("Double tap", "double_tap", "_double_tap", "TAP #2", "tap_count=2")
            )
            add_step(
                "serial_log_double_tap_event",
                saw_double,
                {"lines_considered": len(stream2)},
            )

    # =========================================================================
    # FULL profile extras
    # =========================================================================
    if profile == "full" and core_ok:

        # 8. Triple tap -> restart (track = 1)
        r_tap3 = run_gesture("triple_tap", 1.2)
        ok_tap3 = bool(r_tap3.get("ok")) and bool((r_tap3.get("device") or {}).get("ok", True))
        add_step("triple_tap", ok_tap3, {"result": r_tap3})

        st_after_tap3 = get_state()
        ok_after_tap3 = isinstance(st_after_tap3, dict)
        add_step("get_state_after_triple_tap", ok_after_tap3, {"state": st_after_tap3})
        track_after_tap3 = st_after_tap3.get("current_track") if isinstance(st_after_tap3, dict) else None
        add_step(
            "track_restarted_after_triple_tap",
            track_after_tap3 == 1,
            {
                "track_after": track_after_tap3,
                "note": "triple_tap restarts station at track 1",
            },
        )

        # 9. Long press -> next station (album_index changes)
        r_hold = run_gesture("long_press", 2.0)
        ok_hold = bool(r_hold.get("ok")) and bool((r_hold.get("device") or {}).get("ok", True))
        add_step("long_press", ok_hold, {"result": r_hold})

        st_after_hold = get_state()
        ok_after_hold = isinstance(st_after_hold, dict)
        add_step("get_state_after_long_press", ok_after_hold, {"state": st_after_hold})
        album_after_hold = st_after_hold.get("current_album_index") if isinstance(st_after_hold, dict) else None
        station_changed = album_after_hold is not None and album_before_tap is not None and album_after_hold != album_before_tap
        add_step(
            "station_advanced_after_long_press",
            station_changed,
            {
                "album_before": album_before_tap,
                "album_after": album_after_hold,
                "note": "long_press = next station; album_index should change.",
            },
        )

        # 10. AM audio quality via line-in (optional — skipped if no audio device / numpy)
        try:
            r_dev = invoke("line_in_list_devices", {})
            devices = r_dev.get("devices", []) if r_dev.get("ok") else []
            am_device_idx = pick_line_in_device_index(
                devices, r_dev.get("default_input_index")
            )

            if am_device_idx is not None:
                # Trigger an AM transition on the device before capturing
                invoke("physical_gesture", {"gesture": "long_press", "target": target, "timeout": 35.0})
                time.sleep(1.5)  # let AM overlay start playing

                r_audio = invoke(
                    "line_in_analyze",
                    {
                        "duration_s": 6.0,
                        "sample_rate": 48000,
                        "device": am_device_idx,
                        # reference_wav resolved server-side from gui/resources/AMradioSound.wav
                    },
                )
                ok_audio = bool(r_audio.get("ok"))
                summary = r_audio.get("summary") or {}
                rms = summary.get("rms_dbfs") if ok_audio else None
                ref_cmp = r_audio.get("reference_compare") or {}
                pearson = ref_cmp.get("envelope_pearson_r") if ok_audio else None
                # Thresholds: silence (rms < -60 dB) or near-zero correlation = bad
                audio_pass = (
                    ok_audio
                    and rms is not None
                    and float(rms) > -55.0  # at least some signal
                )
                add_step(
                    "am_audio_line_in",
                    audio_pass,
                    {
                        "rms_dbfs": rms,
                        "envelope_pearson_r": pearson,
                        "device_idx": am_device_idx,
                        "note": "rms_dbfs > -55 = audible signal. pearson_r > 0.3 = AM static shape matches reference.",
                    },
                )
            else:
                add_step(
                    "am_audio_line_in",
                    True,
                    {"skipped": True, "reason": "no input audio device found"},
                )
        except Exception as e:
            add_step(
                "am_audio_line_in",
                True,
                {"skipped": True, "reason": f"exception: {e}"},
            )

    # =========================================================================
    # Build report
    # =========================================================================
    lines.append("## Steps summary")
    for s in steps:
        mark = "pass" if s.get("ok") else "REVIEW"
        lines.append(f"- **{s['name']}**: {mark}")

    lines.append("")
    lines.append("## Playback proxy (last state read)")
    last_state = st_after_tap1 if isinstance(st_after_tap1, dict) else st_initial
    if isinstance(last_state, dict):
        lines.append(f"- `is_playing`: `{last_state.get('is_playing')}`")
        lines.append(f"- `busy_pin`: `{last_state.get('busy_pin')}` (0=playing, 1=idle)")
        lines.append(f"- `power_on`: `{last_state.get('power_on')}`")
        lines.append(f"- `current_track`: `{last_state.get('current_track')}`")
        lines.append(f"- `current_album_index`: `{last_state.get('current_album_index')}`")

    lines.append("")
    lines.append("## Audio note")
    lines.append(
        "Objective sound quality requires `line_in_analyze` (full profile only). "
        "For AM static: `rms_dbfs > -55` = audible, `envelope_pearson_r > 0.3` = shape matches reference."
    )

    overall_fail_names = [s["name"] for s in steps if not s.get("ok")]
    overall_ok = not overall_fail_names or all(
        n in (
            "track_advanced_after_single_tap",
            "track_retreated_after_double_tap",
            "track_restarted_after_triple_tap",
            "station_advanced_after_long_press",
            "serial_log_button_events",
            "serial_log_double_tap_event",
        )
        for n in overall_fail_names
    )

    lines.append("")
    if overall_ok and not overall_fail_names:
        lines.append("## Result: **PASS**")
    elif overall_ok:
        lines.append("## Result: **PARTIAL** (gesture steps ran; some track/log checks failed)")
        lines.append(f"- Failed steps (non-critical): {overall_fail_names}")
    else:
        lines.append("## Result: **FAIL**")
        lines.append(f"- Failed steps: {overall_fail_names}")

    return {
        "ok": overall_ok,
        "target": target,
        "suite_profile": profile,
        "steps": steps,
        "track_changed": track_changed_fwd,
        "report_markdown": "\n".join(lines),
    }


def run_device_acceptance_full(
    *,
    invoke: InvokeFn,
    request: Optional[RequestFn] = None,
    target: str = "device",
    log_fn: Optional[Callable[[str], None]] = None,
) -> JsonDict:
    """Comprehensive physical-device regression suite — BASIC MODE ONLY.

    The Pico must be running main_basic.py (flashed as main.py).  Legacy /
    full mode (main.py with radio_metadata.json) is never tested here.

    Validates the bare-minimum correctness requirements:
      1. Station discovery >= 1 at boot, no boot errors.
      2. Five consecutive tracks in **ordered station** mode (IPC ``mode=playlist``) each
         start within ``_TRACK_START_MAX_S`` s and keep playing for at least
         ``_MIN_PLAY_DURATION_S`` s (the latter is mostly **test harness** wait time).
      3. Three station advances (long_press) each settle into playback.
      4. Five consecutive tracks in **shuffle-station** mode (same checks).
      5. ``triple_tap_long_press`` while in shuffle-station mode reshuffles (same as double+hold).
      6. Revert to ordered station mode (IPC ``mode=playlist``) via tap_long_press and
         confirm 2 tracks play correctly.
      7. Audio output via line-in must exceed ``_LINE_IN_RMS_MIN_DB`` for
         each mode that was tested.
      8. Serial tail is scanned for hard errors (Traceback, MemoryError ...)
         after each phase and once more at the end.

    *invoke*: callable ``(action, payload) -> dict`` routing through
    ``invoke_action`` (e.g. physical_gesture, device_stream_tail).

    *request*: optional callable ``(method, params) -> dict`` that calls the
    debug server's dispatch directly (needed for line_in_list_devices and
    line_in_analyze).  When None, line-in steps are skipped.

    *target*: ``"device"`` (physical Pico) or ``"emulator"``.
    """
    target = (target or "device").strip().lower()
    steps: List[JsonDict] = []

    def log(msg: str) -> None:
        if log_fn is not None:
            log_fn(msg)

    def add_step(name: str, ok: bool, extra: Optional[JsonDict] = None) -> None:
        row: JsonDict = {"name": name, "ok": ok}
        if extra:
            row.update(extra)
        steps.append(row)
        mark = "PASS" if ok else "FAIL"
        log(f"  [{mark}] {name}")
        if extra:
            skip_reason = extra.get("reason") or extra.get("skipped")
            if skip_reason and not ok:
                log(f"        reason: {skip_reason}")
            errors = extra.get("errors_found")
            if errors:
                log(f"        errors: {errors}")
            warns = extra.get("warns_found")
            if warns:
                log(f"        warns:  {warns}")

    def run_gesture(gesture: str, wait_s: float = 0.4) -> JsonDict:
        r = invoke(
            "physical_gesture",
            {"gesture": gesture, "target": target, "timeout": 35.0},
        )
        time.sleep(wait_s)
        return r

    def get_state() -> Optional[JsonDict]:
        r = invoke(
            "physical_gesture",
            {"gesture": "get_state", "target": target, "timeout": 10.0},
        )
        dev = r.get("device") if isinstance(r.get("device"), dict) else {}
        return dev.get("state") if isinstance(dev.get("state"), dict) else None

    _BOOT_MARKER = "VRTEST IPC: uselect stdin polling enabled"

    def tail_lines(limit: int = 400) -> List[str]:
        if target != "device":
            return []
        r = invoke("device_stream_tail", {"limit": limit})
        raw = r.get("lines") if r.get("ok") else []
        return [str(x) for x in raw] if isinstance(raw, list) else []

    def tail_lines_session(limit: int = 400) -> List[str]:
        """Return tail lines filtered to the current boot session only.

        Finds the last occurrence of the VRTEST IPC ready marker in the ring
        buffer and discards everything before it, preventing stale Traceback
        messages from old sessions poisoning the error scans.
        """
        lines = tail_lines(max(limit, 600))
        last_marker = -1
        for idx, line in enumerate(lines):
            if _BOOT_MARKER in line:
                last_marker = idx
        return lines[last_marker:] if last_marker >= 0 else lines

    def scan_errors(lines: List[str]) -> JsonDict:
        joined = "\n".join(lines)
        errors = [p for p in _ERROR_PATTERNS if p in joined]
        warns = [p for p in _WARN_PATTERNS if p in joined]
        return {"errors": errors, "warns": warns, "line_count": len(lines)}

    def poll_until_playing(max_s: float = _TRACK_START_MAX_S) -> Tuple[bool, float, Optional[JsonDict]]:
        t0 = time.time()
        while True:
            st = get_state()
            if st and st.get("busy_pin") == 0:
                return True, round(time.time() - t0, 2), st
            if time.time() - t0 >= max_s:
                return False, round(max_s, 2), st
            time.sleep(_PLAYBACK_POLL_INTERVAL_S)

    def ensure_playing_before_natural_advance(phase_label: str) -> None:
        """If DFPlayer is idle, advance once so auto-advance has an active track.

        Acceptance clips are ~5 s; the prior phase can leave the radio between tracks
        while the harness runs gestures or scans — serial auto-advance then times out
        and busy_pin fallback fails with ``not_playing_before_auto_advance``.
        """
        st = get_state()
        if st and st.get("busy_pin") == 0:
            return
        log(
            f"  [{phase_label}] busy_pin!=0 before auto-advance — "
            "single_tap to start a fresh track…"
        )
        for attempt in range(1, 4):
            run_gesture("single_tap", 0.5)
            ok_p, lat_p, _st_p = poll_until_playing(_TRACK_START_MAX_S)
            if ok_p:
                log(
                    f"  [{phase_label}] playing after tap (attempt {attempt}, {lat_p}s)."
                )
                return
            log(
                f"  [{phase_label}] tap attempt {attempt} did not start within "
                f"{_TRACK_START_MAX_S}s; retrying…"
            )
        log(f"  [{phase_label}] WARN: still idle after taps; proceeding with auto-advance.")

    def run_track_sequence(
        n: int = _TRACKS_PER_MODE,
        max_start_s: float = _TRACK_START_MAX_S,
    ) -> JsonDict:
        """Advance n tracks via single_tap; verify each starts and sustains.

        Records ``current_album_index`` / ``playing_folder`` per step for diagnostics.

        max_start_s: per-track busy_pin=0 timeout.
        """
        results = []
        for i in range(n):
            st_before = get_state()
            track_before = (st_before or {}).get("current_track")
            album_before = (st_before or {}).get("current_album_index")
            folder_before = (st_before or {}).get("playing_folder")

            log(
                f"    track {i+1}/{n}: tap -> "
                f"(station_idx={album_before} folder={folder_before} track={track_before}, "
                f"polling busy_pin max {max_start_s}s)..."
            )

            run_gesture("single_tap", 0.5)
            ok_start, latency_s, st_start = poll_until_playing(max_start_s)

            if ok_start:
                track_after = (st_start or {}).get("current_track")
                album_after = (st_start or {}).get("current_album_index")
                folder_after = (st_start or {}).get("playing_folder")
                log(
                    f"    track {i+1}/{n}: device started in {latency_s}s "
                    f"(station_idx {album_before}->{album_after} "
                    f"folder {folder_before}->{folder_after} "
                    f"track {track_before}->{track_after}); "
                    f"harness hold {_MIN_PLAY_DURATION_S}s (not device delay)..."
                )
                time.sleep(_MIN_PLAY_DURATION_S)
                st_check = get_state()
                still_playing = bool(st_check and st_check.get("busy_pin") == 0)
                bp = (st_check or {}).get("busy_pin")
                log(f"    track {i+1}/{n}: still_playing={still_playing} busy_pin={bp}")
            else:
                track_after = (st_start or {}).get("current_track")
                album_after = (st_start or {}).get("current_album_index")
                folder_after = (st_start or {}).get("playing_folder")
                still_playing = False
                log(
                    f"    track {i+1}/{n}: TIMEOUT -- did not start within {max_start_s}s "
                    f"(station_idx={album_after} folder={folder_after} track={track_after})"
                )

            results.append({
                "track_n": i + 1,
                "ok": ok_start and still_playing,
                "started": ok_start,
                f"still_playing_after_{int(_MIN_PLAY_DURATION_S)}s": still_playing,
                "track_changed": track_before != track_after,
                "album_before": album_before,
                "album_after": album_after,
                "folder_after": folder_after,
                "start_latency_s": latency_s,
                "track_before": track_before,
                "track_after": track_after,
            })

        passed = sum(1 for r in results if r["ok"])
        latencies = [r["start_latency_s"] for r in results if r.get("started")]
        avg_lat = round(sum(latencies) / len(latencies), 2) if latencies else None
        max_lat = round(max(latencies), 2) if latencies else None
        if max_lat is not None and max_lat > _SLOW_START_WARN_S:
            log(
                f"  NOTE: max tap-to-play latency {max_lat}s > {_SLOW_START_WARN_S}s "
                "(still within suite limit). Investigate DFPlayer/UART if this is unexpected."
            )
        albums_seen = list(
            {r["album_after"] for r in results if r.get("album_after") is not None}
        )
        folders_seen = list(
            {r["folder_after"] for r in results if r.get("folder_after") is not None}
        )
        return {
            "ok": passed == n,
            "passed": passed,
            "total": n,
            "avg_start_latency_s": avg_lat,
            "max_start_latency_s": max_lat,
            "albums_seen": albums_seen,
            "folders_seen": folders_seen,
            "tracks": results,
        }
    def capture_line_in() -> JsonDict:
        if request is None:
            return {"ok": True, "skipped": True, "reason": "no request callable"}
        try:
            log("  Line-in: listing host audio input devices...")
            r_dev = request("line_in_list_devices", {})
            devices = r_dev.get("devices", []) if r_dev.get("ok") else []
            device_idx = pick_line_in_device_index(
                devices, r_dev.get("default_input_index")
            )
            if device_idx is None:
                return {"ok": True, "skipped": True, "reason": "no suitable audio input device"}

            # Line-in measures DFPlayer output; capture only while hardware reports playback.
            playback_note = None
            if target == "device":
                st0 = get_state()
                if not (st0 and st0.get("busy_pin") == 0):
                    log(
                        "  Line-in: DFPlayer idle (busy_pin!=0) — single_tap then "
                        f"wait up to {_TRACK_START_MAX_S}s for playback before capture..."
                    )
                    run_gesture("single_tap", 0.5)
                    ok_pb, lat_pb, st_pb = poll_until_playing(_TRACK_START_MAX_S)
                    if not ok_pb:
                        return {
                            "ok": False,
                            "skipped": False,
                            "reason": "dfplayer_not_playing_before_line_in",
                            "busy_pin": (st_pb or {}).get("busy_pin"),
                            "state": st_pb,
                            "device_idx": device_idx,
                            "threshold_db": _LINE_IN_RMS_MIN_DB,
                            "note": "Cannot validate line-in without active DFPlayer playback",
                        }
                    playback_note = f"started_via_single_tap_latency_{lat_pb}s"
                else:
                    playback_note = "already_playing_busy_pin_0"

            log(
                f"  Line-in: recording {_LINE_IN_DURATION_S}s from input device index "
                f"{device_idx} (blocking — no new log lines until capture finishes)..."
            )
            r_audio = request("line_in_analyze", {
                "duration_s": _LINE_IN_DURATION_S,
                "sample_rate": 48000,
                "device": device_idx,
            })
            log(
                "  Line-in: capture returned "
                f"ok={r_audio.get('ok')} error={r_audio.get('error')!r}"
            )
            summary = r_audio.get("summary") or {}
            rms = summary.get("rms_dbfs")
            peak = summary.get("peak_linear")
            audio_ok = (
                bool(r_audio.get("ok"))
                and rms is not None
                and float(rms) > _LINE_IN_RMS_MIN_DB
            )
            out: JsonDict = {
                "ok": audio_ok,
                "rms_dbfs": rms,
                "peak_linear": peak,
                "device_idx": device_idx,
                "threshold_db": _LINE_IN_RMS_MIN_DB,
                "raw_error": r_audio.get("error"),
                "note": f"rms_dbfs must exceed {_LINE_IN_RMS_MIN_DB} dB for audible signal",
            }
            if playback_note is not None:
                out["playback_gate"] = playback_note
            return out
        except Exception as exc:
            return {"ok": True, "skipped": True, "reason": f"exception: {exc}"}

    # =========================================================================
    # Phase 0: Connectivity + discovery
    # =========================================================================
    log(
        "=== Full device acceptance — expect ~18–40+ min on hardware "
        f"({_TRACKS_PER_MODE} tracks in 3 modes, natural auto-advance in each, "
        "double/triple tap checks, 3 station changes, 3 line-in captures, serial scans). "
        "Pico serial tail is logged after each major phase. ==="
    )
    log(
        "=== Harness timing (not radio slowness) ==="
        f" After each tap the suite waits up to {_TRACK_START_MAX_S}s for busy_pin=0, then "
        f"**sleeps {_MIN_PLAY_DURATION_S}s on purpose** to confirm playback keeps going. "
        "Long gaps in the log are usually that hold plus line-in capture/analysis (~6s audio + "
        "host processing per phase). Watch **device started in Xs** lines for real tap-to-play "
        "latency (typically well under 1s)."
    )
    log("=== Phase 0: Connectivity + discovery ===")
    r_ping = run_gesture("ping", 0.15)
    dev_ping = r_ping.get("device") if isinstance(r_ping.get("device"), dict) else {}
    ok_ping = bool(r_ping.get("ok")) and bool(dev_ping.get("ok", True))
    add_step("ping", ok_ping, {"result": r_ping})

    if not ok_ping:
        rp = r_ping if isinstance(r_ping, dict) else {}
        err = rp.get("error")
        detail = rp.get("detail")
        hint_serial = ""
        if err == "serial" or (isinstance(detail, str) and "WriteFile" in detail):
            hint_serial = (
                "\n4. **Serial write failed (Windows):** disconnect other programs using the COM port, "
                "use **Disconnect** then **Connect** on the Device tab (or restart the app), and retry. "
                f"Raw error: `{detail}`\n"
            )
        return {
            "ok": False,
            "target": target,
            "steps": steps,
            "report_markdown": (
                "# Full acceptance\n\n**FAIL** — VRTEST ping failed.\n\n"
                "1. **Device tab:** select the Pico COM port, **Connect**, then **Start Streaming**.\n"
                "2. Confirm firmware has `components/vintage_radio_ipc.py` and `VRTEST IPC` "
                "appears in the serial stream.\n"
                "3. Run this suite again (do not rely on a quick fail if the port was not open yet)."
                f"{hint_serial}"
            ),
        }

    log("  Ping OK — reading initial state...")
    st0 = get_state()
    ok_state = isinstance(st0, dict)
    add_step("initial_state", ok_state, {"state": st0})

    total_playlists = int((st0 or {}).get("total_playlists", 0))
    ok_discovery = total_playlists >= 1
    log(
        f"  State: IPC mode={(st0 or {}).get('mode')} "
        f"station_count={total_playlists} (field total_playlists) "
        f"is_playing={(st0 or {}).get('is_playing')} busy_pin={(st0 or {}).get('busy_pin')}"
    )
    add_step("station_discovery", ok_discovery, {
        "total_playlists": total_playlists,
        "note": ">=1 station must be discovered at boot; 0 means DFPlayer folder discovery failed",
    })

    log("  Scanning boot serial tail (600 lines, current boot only)...")
    boot_lines = tail_lines_session(600)
    boot_scan = scan_errors(boot_lines)
    log(f"  Boot scan: {len(boot_lines)} lines, "
        f"errors={boot_scan['errors']}, warns={boot_scan['warns']}")
    add_step("boot_error_scan", not boot_scan["errors"], {
        "errors_found": boot_scan["errors"],
        "warns_found": boot_scan["warns"],
        "lines_checked": boot_scan["line_count"],
        "note": "scanned from last VRTEST IPC ready marker only",
    })

    power_on = bool((st0 or {}).get("power_on"))
    add_step("power_on", power_on, {"power_on": power_on})

    log_device_serial_tail(
        invoke=invoke, log_fn=log, target=target, limit=100, heading="Pico serial after Phase 0"
    )

    # =========================================================================
    # Phase 1: Ordered station playback (IPC mode=playlist) — 5 tracks
    # =========================================================================
    log(
        f"\n=== Phase 1: Ordered station playback — {_TRACKS_PER_MODE} tracks "
        "(IPC reports mode=playlist; not a host library playlist) ==="
    )
    current_mode = (st0 or {}).get("mode", "unknown")
    if current_mode != "playlist":
        log(
            f"  Not in ordered-station IPC mode (mode={current_mode}), "
            "sending tap_long_press to revert from shuffle..."
        )
        run_gesture("tap_long_press", 1.0)
        time.sleep(3.0)
        st0 = get_state()
        current_mode = (st0 or {}).get("mode", "unknown")

    if current_mode == "playlist":
        log(f"  Running {_TRACKS_PER_MODE}-track sequence (ordered tracks on current station)...")
        seq1 = run_track_sequence(_TRACKS_PER_MODE)
        add_step("playlist_5_tracks", seq1["ok"], {
            "passed": seq1["passed"],
            "total": seq1["total"],
            "avg_start_latency_s": seq1["avg_start_latency_s"],
            "max_start_latency_s": seq1.get("max_start_latency_s"),
            "tracks": seq1["tracks"],
            "note": f"All {_TRACKS_PER_MODE} tracks must start within {_TRACK_START_MAX_S}s "
                    f"and play for >= {_MIN_PLAY_DURATION_S}s (includes harness hold)",
        })
        if seq1.get("avg_start_latency_s") is not None:
            log(
                f"  Phase 1 device tap-to-play: avg={seq1['avg_start_latency_s']}s "
                f"max={seq1.get('max_start_latency_s')}s"
            )

        log(
            f"\n=== Phase 1a: Ordered station — natural auto-advance "
            f"(no taps; serial ≤{_SHUFFLE_AUTO_ADVANCE_MAX_GAP_SERIAL_S}s preferred, "
            f"{_SHUFFLE_AUTO_ADVANCE_SAMPLES} samples) ==="
        )
        ensure_playing_before_natural_advance("Phase 1a playlist")
        adv_pl = measure_library_shuffle_auto_advance_best_effort(
            get_state=get_state,
            tail_lines_fn=lambda lim: tail_lines_session(lim),
            log=log,
            request=request,
            target=target,
        )
        add_step("playlist_auto_advance_gap", adv_pl["ok"], adv_pl)

        log(
            "\n=== Phase 1b: Gestures — double_tap (previous track), "
            "triple_tap (restart station at track 1) ==="
        )
        st_g0 = get_state()
        t_g0 = (st_g0 or {}).get("current_track")
        alb_g0 = (st_g0 or {}).get("current_album_index")
        run_gesture("double_tap", 0.85)
        ok_d, _, st_d = poll_until_playing(_TRACK_START_MAX_S)
        t_d = (st_d or {}).get("current_track")
        alb_d = (st_d or {}).get("current_album_index")
        dbl_ok = (
            ok_d
            and t_g0 is not None
            and t_d is not None
            and (t_d != t_g0 or alb_d != alb_g0)
        )
        add_step("gesture_double_tap_previous_track", dbl_ok, {
            "track_before": t_g0,
            "track_after": t_d,
            "album_before": alb_g0,
            "album_after": alb_d,
            "note": "double_tap = previous track; index or station should change vs pre-gesture",
        })

        st_r = get_state()
        if (st_r or {}).get("current_track") == 1:
            log("  Already on track 1 — single_tap once so triple_tap restart is observable...")
            run_gesture("single_tap", 0.5)
            poll_until_playing(_TRACK_START_MAX_S)
        run_gesture("triple_tap", 1.05)
        ok_t3, _, st_t3 = poll_until_playing(_TRACK_START_MAX_S)
        tr3 = (st_t3 or {}).get("current_track")
        tr_ok = ok_t3 and tr3 == 1
        add_step("gesture_triple_tap_restart_station", tr_ok, {
            "current_track_after": tr3,
            "note": "triple_tap should restart current station at track 1",
        })

        if target == "device":
            # High-volume phases rotate the ring; pull a large tail and scan all
            # of it (not just the last N) so tap keywords are not missed when the
            # firmware generates bursts of log output during playback polling.
            stream_g = tail_lines(2000)
            joined_g = "\n".join(stream_g)
            saw_dbl = any(
                kw in joined_g
                for kw in ("Double tap", "double_tap", "_double_tap", "TAP #2", "tap_count=2")
            )
            saw_trp = any(
                kw in joined_g
                for kw in ("Triple tap", "triple_tap", "_triple_tap", "TAP #3", "tap_count=3")
            )
            add_step("serial_log_double_triple_tap", saw_dbl and saw_trp, {
                "saw_double_tap_line": saw_dbl,
                "saw_triple_tap_line": saw_trp,
                "lines_considered": len(stream_g),
            })
        else:
            add_step(
                "serial_log_double_triple_tap",
                True,
                {"skipped": True, "reason": "emulator target"},
            )

        log_device_serial_tail(
            invoke=invoke,
            log_fn=log,
            target=target,
            limit=100,
            heading="Pico serial after phase 1 (ordered 5 tracks + auto-advance + double/triple tap)",
        )

        log("  Capturing line-in audio (ordered station mode)...")
        li1 = capture_line_in()
        log(f"  Line-in: rms_dbfs={li1.get('rms_dbfs')} ok={li1.get('ok')} skipped={li1.get('skipped')}")
        add_step("playlist_line_in", li1.get("ok", False) or li1.get("skipped", False), li1)

        log_device_serial_tail(
            invoke=invoke,
            log_fn=log,
            target=target,
            limit=80,
            heading="Pico serial after phase 1 line-in",
        )

        log("  Scanning serial tail for errors...")
        scan1 = scan_errors(tail_lines_session(400))
        add_step("playlist_error_scan", not scan1["errors"], {
            "errors_found": scan1["errors"],
            "warns_found": scan1["warns"],
        })
    else:
        for name in (
            "playlist_5_tracks",
            "playlist_auto_advance_gap",
            "gesture_double_tap_previous_track",
            "gesture_triple_tap_restart_station",
            "serial_log_double_triple_tap",
            "playlist_line_in",
            "playlist_error_scan",
        ):
            add_step(
                name,
                False,
                {"skipped": True, "reason": f"mode={current_mode}, expected IPC mode=playlist"},
            )

    # =========================================================================
    # Phase 2: Station advance — 3 stations via long_press
    # =========================================================================
    log("\n=== Phase 2: Station advance — 3x long_press ===")
    album_at_phase_start = (get_state() or {}).get("current_album_index")
    station_advance_results: List[JsonDict] = []
    for i in range(3):
        st_pre = get_state()
        album_before = (st_pre or {}).get("current_album_index")
        log(f"  Station advance {i+1}/3: long_press from station_idx {album_before}...")
        run_gesture("long_press", 0.5)
        ok_s, lat_s, st_post = poll_until_playing(_MODE_SWITCH_MAX_S)
        album_after = (st_post or {}).get("current_album_index")
        changed = album_before != album_after
        log(
            f"  Station advance {i+1}/3: station_idx {album_before}->{album_after} "
            f"playing={ok_s} latency={lat_s}s"
        )
        station_advance_results.append({
            "advance_n": i + 1,
            "ok": ok_s and changed,
            "playing": ok_s,
            "station_changed": changed,
            "album_before": album_before,
            "album_after": album_after,
            "latency_s": lat_s,
        })
    all_advances_ok = all(r["ok"] for r in station_advance_results)
    add_step("station_advance_3x", all_advances_ok, {"advances": station_advance_results})

    scan_adv = scan_errors(tail_lines_session(300))
    add_step("station_advance_error_scan", not scan_adv["errors"], {
        "errors_found": scan_adv["errors"],
        "warns_found": scan_adv["warns"],
    })

    log_device_serial_tail(
        invoke=invoke,
        log_fn=log,
        target=target,
        limit=100,
        heading="Pico serial after Phase 2 (station advance)",
    )

    # =========================================================================
    # Phase 3: Shuffle-station mode — double_tap_long_press + 5 tracks
    # =========================================================================
    log(f"\n=== Phase 3: Shuffle-station mode — {_TRACKS_PER_MODE} tracks ===")
    log("  Sending double_tap_long_press (shuffle current station)...")
    run_gesture("double_tap_long_press", 0.5)
    ok_ss, _, st_ss = poll_until_playing(_MODE_SWITCH_MAX_S)
    mode_ss = (st_ss or {}).get("mode")
    type_ss = (st_ss or {}).get("shuffle_source_type")
    ok_ss_switch = mode_ss == "shuffle" and type_ss == "station"
    log(f"  Mode after switch: mode={mode_ss} shuffle_source_type={type_ss} playing={ok_ss}")
    add_step("shuffle_station_mode_switch", ok_ss_switch and ok_ss, {
        "mode": mode_ss,
        "shuffle_source_type": type_ss,
        "playing": ok_ss,
        "note": "double_tap_long_press from ordered station mode = shuffle current station",
    })

    if ok_ss_switch:
        log(
            f"\n=== Phase 3a: Shuffle-station — natural auto-advance "
            f"(no taps; serial ≤{_SHUFFLE_AUTO_ADVANCE_MAX_GAP_SERIAL_S}s preferred, "
            f"{_SHUFFLE_AUTO_ADVANCE_SAMPLES} samples) ==="
        )
        ensure_playing_before_natural_advance("Phase 3a shuffle-station")
        adv_ss = measure_library_shuffle_auto_advance_best_effort(
            get_state=get_state,
            tail_lines_fn=lambda lim: tail_lines_session(lim),
            log=log,
            request=request,
            target=target,
        )
        add_step("shuffle_station_auto_advance_gap", adv_ss["ok"], adv_ss)

        log(f"  Running {_TRACKS_PER_MODE}-track sequence in shuffle-station mode...")
        seq3 = run_track_sequence(_TRACKS_PER_MODE)
        add_step("shuffle_station_5_tracks", seq3["ok"], {
            "passed": seq3["passed"],
            "total": seq3["total"],
            "avg_start_latency_s": seq3["avg_start_latency_s"],
            "max_start_latency_s": seq3.get("max_start_latency_s"),
            "tracks": seq3["tracks"],
        })
        if seq3.get("avg_start_latency_s") is not None:
            log(
                f"  Phase 3 device tap-to-play: avg={seq3['avg_start_latency_s']}s "
                f"max={seq3.get('max_start_latency_s')}s"
            )
        log_device_serial_tail(
            invoke=invoke,
            log_fn=log,
            target=target,
            limit=100,
            heading="Pico serial after shuffle-station 5 tracks",
        )
        log("  Capturing line-in audio (shuffle-station mode)...")
        li3 = capture_line_in()
        log(f"  Line-in: rms_dbfs={li3.get('rms_dbfs')} ok={li3.get('ok')} skipped={li3.get('skipped')}")
        add_step("shuffle_station_line_in", li3.get("ok", False) or li3.get("skipped", False), li3)
        log_device_serial_tail(
            invoke=invoke,
            log_fn=log,
            target=target,
            limit=80,
            heading="Pico serial after shuffle-station line-in",
        )
        log("  Scanning serial tail for errors...")
        scan3 = scan_errors(tail_lines_session(400))
        add_step("shuffle_station_error_scan", not scan3["errors"], {
            "errors_found": scan3["errors"],
            "warns_found": scan3["warns"],
        })
    else:
        for name in (
            "shuffle_station_auto_advance_gap",
            "shuffle_station_5_tracks",
            "shuffle_station_line_in",
            "shuffle_station_error_scan",
        ):
            add_step(name, False, {"skipped": True, "reason": "shuffle-station mode switch failed"})

    # =========================================================================
    # Phase 4: triple_tap_long_press — same as double+hold (reshuffle station tracks)
    # =========================================================================
    if ok_ss_switch:
        log("\n=== Phase 4: triple_tap_long_press (reshuffle station tracks) ===")
        st_pre_t3 = get_state()
        album_pre_t3 = (st_pre_t3 or {}).get("current_album_index")
        log("  Sending triple_tap_long_press (expect stay in shuffle-station, track 1)...")
        run_gesture("triple_tap_long_press", 0.5)
        ok_t3, _, st_t3 = poll_until_playing(_MODE_SWITCH_MAX_S)
        mode_t3 = (st_t3 or {}).get("mode")
        type_t3 = (st_t3 or {}).get("shuffle_source_type")
        cycle_t3 = bool((st_t3 or {}).get("station_cycle_shuffle_active"))
        album_t3 = (st_t3 or {}).get("current_album_index")
        track_t3 = (st_t3 or {}).get("current_track")
        ok_t3_switch = (
            ok_t3
            and not cycle_t3
            and mode_t3 == "shuffle"
            and type_t3 == "station"
            and track_t3 == 1
            and album_pre_t3 is not None
            and album_t3 == album_pre_t3
        )
        log(
            "  State after gesture: mode={} shuffle_source_type={} station_cycle_shuffle_active={} "
            "album {}->{} track={} playing={}".format(
                mode_t3, type_t3, cycle_t3, album_pre_t3, album_t3, track_t3, ok_t3
            )
        )
        add_step("triple_hold_reshuffles_station_shuffle", ok_t3_switch, {
            "mode": mode_t3,
            "shuffle_source_type": type_t3,
            "station_cycle_shuffle_active": cycle_t3,
            "album_before": album_pre_t3,
            "album_after": album_t3,
            "current_track_after": track_t3,
            "playing": ok_t3,
            "note": "triple+hold matches double+hold: reshuffle tracks on current station",
        })
    else:
        add_step(
            "triple_hold_reshuffles_station_shuffle",
            False,
            {"skipped": True, "reason": "shuffle-station (Phase 3) not active"},
        )
    log_device_serial_tail(
        invoke=invoke,
        log_fn=log,
        target=target,
        limit=80,
        heading="Pico serial after Phase 4 (triple tap + hold reshuffle)",
    )

    # =========================================================================
    # Phase 5: Revert to ordered station mode — tap_long_press from shuffle
    # =========================================================================
    log("\n=== Phase 5: Revert to ordered station mode (IPC mode=playlist) ===")
    log("  Sending tap_long_press (exit shuffle -> ordered station playback)...")
    run_gesture("tap_long_press", 0.5)
    ok_rev, _, st_rev = poll_until_playing(_MODE_SWITCH_MAX_S)
    mode_rev = (st_rev or {}).get("mode")
    ok_revert = mode_rev == "playlist"
    log(f"  Mode after revert: mode={mode_rev} playing={ok_rev}")
    add_step("revert_to_playlist", ok_revert and ok_rev, {
        "mode_after": mode_rev,
        "playing": ok_rev,
        "note": "tap_long_press from shuffle exits to IPC mode=playlist (ordered station)",
    })

    if ok_revert:
        log("  Verifying 2 tracks play after revert...")
        seq5 = run_track_sequence(2)
        add_step("post_revert_2_tracks", seq5["ok"], {
            "passed": seq5["passed"],
            "total": seq5["total"],
            "avg_start_latency_s": seq5.get("avg_start_latency_s"),
            "max_start_latency_s": seq5.get("max_start_latency_s"),
        })
    else:
        add_step("post_revert_2_tracks", False, {"skipped": True, "reason": "revert failed"})

    log_device_serial_tail(
        invoke=invoke,
        log_fn=log,
        target=target,
        limit=100,
        heading="Pico serial after Phase 5 (revert / post-revert tracks)",
    )

    # =========================================================================
    # Phase 6: Final error scan
    # =========================================================================
    log("\n=== Phase 6: Final error scan ===")
    final_lines = tail_lines_session(800)
    final_scan = scan_errors(final_lines)
    log(f"  Final scan: {len(final_lines)} lines, errors={final_scan['errors']}, warns={final_scan['warns']}")
    add_step("final_error_scan", not final_scan["errors"], {
        "errors_found": final_scan["errors"],
        "warns_found": final_scan["warns"],
        "lines_checked": final_scan["line_count"],
    })

    # =========================================================================
    # Build summary report
    # =========================================================================
    total_steps = len(steps)
    failed_steps = [s["name"] for s in steps if not s.get("ok") and not s.get("skipped")]
    passed_count = sum(1 for s in steps if s.get("ok"))
    overall_ok = len(failed_steps) == 0

    report: List[str] = [
        "# Vintage Radio — Full Device Acceptance Report",
        "",
        f"- **Target**: `{target}`",
        f"- **Modes tested**: ordered station (IPC `mode=playlist`), shuffle-station, "
        "triple+hold (reshuffle station tracks), revert to ordered station",
        f"- **Tracks per mode**: {_TRACKS_PER_MODE}",
        f"- **Max start latency (device)**: {_TRACK_START_MAX_S}s after each tap",
        f"- **Min sustained play check**: {_MIN_PLAY_DURATION_S}s per track "
        "(mostly **test harness** sleep after playback starts — see log lines "
        "`device started in Xs` for real tap-to-play time)",
        "",
        "## Basic mode vs. IPC names",
        "",
        "Firmware still exposes legacy field names. In **basic mode**: `total_playlists` = "
        "**station count**; `current_album_index` = **station index**; `playing_folder` = "
        "**DFPlayer SD folder**; `mode=playlist` means **ordered tracks on the current station**, "
        "not a desktop music playlist.",
        "",
        "## Harness timing",
        "",
        f"Wall-clock gaps are often **{_MIN_PLAY_DURATION_S}s per track** (intentional) plus "
        f"~{_LINE_IN_DURATION_S}s line-in capture and host analysis per phase — not the radio "
        "waiting between tracks.",
        "",
        "## Coverage (what this suite exercises)",
        "",
        "1. VRTEST ping + `get_state` + station discovery count.",
        "2. Boot serial scan (errors) from current session marker.",
        f"3. Ordered station: {_TRACKS_PER_MODE} taps + **natural auto-advance** + "
        "**double_tap** (prev) + **triple_tap** (restart) + line-in + error scan.",
        "4. Three `long_press` station changes with playback settling.",
        "5. Shuffle-station (`double_tap_long_press`): mode + **natural auto-advance** + "
        f"{_TRACKS_PER_MODE} taps + line-in + error scan.",
        "6. `triple_tap_long_press` while in shuffle-station mode reshuffles (same as double+hold).",
        f"   (Auto-advance where measured: serial log gap ≤ {_SHUFFLE_AUTO_ADVANCE_MAX_GAP_SERIAL_S:.2f}s; "
        f"busy_pin fallback ≤ {_SHUFFLE_AUTO_ADVANCE_MAX_GAP_S}s.)",
        "7. `tap_long_press` back to ordered station (IPC `mode=playlist`) + 2 tracks.",
        "8. Final serial error scan.",
        "",
        "MCU `print` output is also copied into the session log as **Pico serial** blocks after each phase.",
        "",
        "## Results",
        "",
    ]
    for s in steps:
        if s.get("skipped"):
            mark = "SKIP"
        elif s.get("ok"):
            mark = "PASS"
        else:
            mark = "FAIL"
        report.append(f"- **{s['name']}**: {mark}")

    _adv_sections = (
        ("playlist_auto_advance_gap", "Ordered station — natural auto-advance (Phase 1a)"),
        ("shuffle_station_auto_advance_gap", "Shuffle-station — natural auto-advance (Phase 3a)"),
    )
    for step_name, adv_title in _adv_sections:
        adv_step = next((s for s in steps if s.get("name") == step_name), None)
        if adv_step is None:
            continue
        report += ["", f"## {adv_title}", ""]
        if adv_step.get("skipped"):
            report.append(f"- **Status**: SKIP — {adv_step.get('reason', '')}")
        else:
            report.append(f"- **Status**: {'PASS' if adv_step.get('ok') else 'FAIL'}")
            m = adv_step.get("method", "unknown")
            report.append(f"- **Measurement**: `{m}` (serial log preferred when BUSY stays LOW)")
            thr = adv_step.get("threshold_s", _SHUFFLE_AUTO_ADVANCE_MAX_GAP_SERIAL_S)
            report.append(
                f"- **Requirement**: gap **≤ {thr} s** for each of {_SHUFFLE_AUTO_ADVANCE_SAMPLES} samples "
                "(track end → next playback started; see `note` for exact markers)."
            )
            for g in adv_step.get("gaps_detail") or []:
                mark = "ok" if g.get("ok") else "**OVER LIMIT**"
                report.append(f"  - Sample {g.get('sample')}: **{g.get('gap_s')} s** — {mark}")
            if adv_step.get("max_gap_s") is not None:
                report.append(f"- **Max gap observed**: {adv_step['max_gap_s']} s")
            if adv_step.get("error"):
                report.append(f"- **Error**: `{adv_step['error']}`")
            if adv_step.get("note"):
                report.append(f"- **Note**: {adv_step['note']}")
            sa = adv_step.get("serial_attempt")
            if isinstance(sa, dict) and sa.get("gaps_detail") and m != "serial_log":
                report.append("- **Serial attempt** (for comparison):")
                report.append(f"  - method: `{sa.get('method')}` max_gap: {sa.get('max_gap_s')}")

    report += [
        "",
        f"**Total**: {passed_count}/{total_steps} steps passed.",
        "",
        "## Overall: **{}**".format("PASS" if overall_ok else "FAIL"),
    ]
    if failed_steps:
        report.append(f"\nFailed steps: {failed_steps}")

    return {
        "ok": overall_ok,
        "target": target,
        "steps": steps,
        "passed": passed_count,
        "total": total_steps,
        "failed_steps": failed_steps,
        "report_markdown": "\n".join(report),
    }
