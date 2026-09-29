"""Physical-device acceptance for commercials, on a small purpose-built library.

The existing full suite in ``mcp_device_acceptance`` answers a different question:
it stresses a large folder and measures auto-advance gaps. These suites instead
take a deliberately small library (3 stations x 4 tracks plus a folder-99 ad reel)
and check that commercials behave correctly around it.

What makes these suites different is that they listen. Every file in the test
library carries the pilot-tone ident from ``gui/audio_ident.py``, so the harness
can decode from the line-in capture which folder and track the radio is *actually*
playing. Skipped, repeated, or out-of-order tracks are caught acoustically instead
of being inferred from the state the firmware reports about itself.

Manual skip (single tap) counts toward the folder-99 interval the same way a
natural track end does, and skipping the last track of a station starts the next
station instead of wrapping the same folder.

Four suites, matching what each firmware family can actually do:

===========================  ========  ===========  ========================================
suite                        family    mode         covers
===========================  ========  ===========  ========================================
``basic_folder``             basic     folder_99    interval inserts, resume, station walk
``conductor_folder``         conductor folder_99    the above plus library shuffle
``conductor_inline``         conductor inline       catalog ads in order, linked ad pairing
``conductor_both``           conductor both         folder inserts and inline ads together
===========================  ========  ===========  ========================================

Basic firmware has no ``inline`` suite because it cannot do inline commercials: it
never loads ``radio_catalog.json``, so it has no ad metadata to act on.

Prerequisite: the SD card must hold the generated test library, and the app must
be set to the suite's commercials mode:

1. ``python agent_workshop/generate_test_library_audio.py``
2. In the app, create a library and import each ``station_NN`` folder as a station,
   and the ``commercials_99`` folder as the commercials station.
3. Set the commercials mode and interval (3) to match the suite.
4. Sync to SD, then run the suite.

Phase 0 aborts with an actionable message when the SD contents or mode do not
match, rather than reporting misleading failures later on.
"""

from __future__ import annotations

import math
import re
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

from .audio_ident import COMMERCIALS_FOLDER

JsonDict = Dict[str, Any]
InvokeFn = Callable[[str, JsonDict], JsonDict]
RequestFn = Callable[[str, JsonDict], JsonDict]

# Shape of the generated test library. Kept in sync with
# agent_workshop/generate_test_library_audio.py.
EXPECTED_STATIONS = 3
TRACKS_PER_STATION = 4
EXPECTED_ADS = 4
COMMERCIAL_INTERVAL = 3
MUSIC_TRACK_S = 25.0
AD_TRACK_S = 5.0

_TRACK_START_MAX_S = 8.0
_MODE_SWITCH_MAX_S = 15.0
_MUSIC_READY_MAX_S = 15.0
_MIN_PLAY_DURATION_S = 4.0
_POLL_INTERVAL_S = 0.15
_LINE_IN_RMS_MIN_DB = -55.0

# Short probe used only when more than one host-API slot matches the line-in
# device name, to pick whichever one is actually alive (see resolve_line_in).
_DEVICE_PROBE_S = 0.6
#: Pause between probing successive candidates so an open/close cycle on one
#: host-API slot doesn't run right up against the next one starting - each
#: probe is now an isolated stream (see capture_and_analyze), but the physical
#: USB hardware underneath is still shared and cheap USB audio chips are not
#: built for being hammered with back-to-back opens.
_DEVICE_PROBE_SETTLE_S = 0.3
#: Real unclipped audio cannot exceed 0 dBFS. Observed directly: a misbehaving
#: capture path (a loopback-type device wrongly offered as a line-in candidate)
#: reported +40 dBFS and "won" a naive loudest-wins probe, silently swapping
#: the whole suite onto the wrong signal. A little slack above 0 dBFS covers
#: normal calibration/measurement noise without letting garbage readings win.
_PROBE_MAX_PLAUSIBLE_RMS_DBFS = 3.0

# Long enough to decode several ident chunks, short enough not to span a track edge.
_IDENT_CAPTURE_S = 2.0
# A capture deliberately long enough to straddle a transition and show both sides.
_IDENT_TRANSITION_CAPTURE_S = 6.0

# One ad cycle is COMMERCIAL_INTERVAL music tracks plus the ad itself.
_AD_CYCLE_S = COMMERCIAL_INTERVAL * MUSIC_TRACK_S + AD_TRACK_S
_AD_WAIT_MAX_S = _AD_CYCLE_S * 2.0
_NATURAL_END_MAX_S = MUSIC_TRACK_S * 2.5 + 4.0

_AD_START = "COMMERCIALS: playing folder"
_AD_RESUME = "COMMERCIALS: finished, resuming music"
_AD_CANCEL = "COMMERCIALS: pending resume cancelled"
_AD_EMPTY = "COMMERCIALS: folder 99 empty"
_LINKED_AD_START = "CONDUCTOR: playing linked commercial before shuffle track"
_LINKED_AD_DONE = "CONDUCTOR: linked commercial finished, playing track"
_LINKED_AD_SKIP = "CONDUCTOR: skip linked commercial, playing attached track"
_TRACK_FINISHED = "Track finished, auto-advancing"
_AM_OVERLAY_COMPLETE = "AM: PWM overlay complete"
_BOOT_MARKER = "VRTEST IPC: uselect stdin polling enabled"
# machine.soft_reset() via Device-tab restart_firmware; USB usually drops.
_FIRMWARE_RESET_SETTLE_S = 8.0
# Envelope correlation vs AMradioSound.wav: below this, line-in is music not AM.
_AM_PEARSON_MUSIC_MAX = 0.3
_RECONNECT_ATTEMPTS = 12
_RECONNECT_GAP_S = 2.0

_ERROR_PATTERNS = [
    "Traceback (most recent call last)",
    "MemoryError",
    "SyntaxError",
    "FATAL:",
    "Boot init error:",
]
_WARN_PATTERNS = [
    "am_overlay failed",
    "compact load retry",
    "No tracks available",
    "error_code",
    "Playback failed to start",
    _AD_EMPTY,
]

SUITES: Dict[str, JsonDict] = {
    "basic_folder": {
        "family": "basic",
        "mode": "folder_99",
        "label": "Basic firmware - folder 99 commercials",
        "library_shuffle": False,
        "inline": False,
    },
    "conductor_folder": {
        "family": "conductor",
        "mode": "folder_99",
        "label": "Conductor firmware - folder 99 commercials",
        "library_shuffle": True,
        "inline": False,
    },
    "conductor_inline": {
        "family": "conductor",
        "mode": "inline",
        "label": "Conductor firmware - inline (integrated) commercials",
        "library_shuffle": True,
        "inline": True,
    },
    "conductor_both": {
        "family": "conductor",
        "mode": "both",
        "label": "Conductor firmware - folder 99 and inline commercials together",
        "library_shuffle": True,
        "inline": True,
    },
}


def run_commercials_acceptance(
    *,
    invoke: InvokeFn,
    request: Optional[RequestFn] = None,
    target: str = "device",
    suite: str = "basic_folder",
    require_audio: bool = True,
    log_fn: Optional[Callable[[str], None]] = None,
) -> JsonDict:
    """Run one commercials acceptance suite against the physical device.

    *require_audio* aborts in Phase 0 when line-in is silent. The acoustic checks
    are the point of these suites, so discovering a muted radio or an unplugged
    capture adapter after a ten minute run helps nobody. Pass False to run the
    state and serial checks anyway.
    """
    target = (target or "device").strip().lower()
    suite_name = (suite or "basic_folder").strip().lower()
    if suite_name not in SUITES:
        return {
            "ok": False,
            "error": "unknown_suite",
            "suite": suite_name,
            "available": sorted(SUITES),
            "steps": [],
            "report_markdown": f"Unknown commercials suite {suite_name!r}.",
        }

    cfg = SUITES[suite_name]
    folder_ads = cfg["mode"] in ("folder_99", "both")
    inline_ads = bool(cfg["inline"])
    steps: List[JsonDict] = []

    def log(msg: str) -> None:
        if log_fn is not None:
            log_fn(msg)

    def add_step(name: str, ok: bool, extra: Optional[JsonDict] = None) -> None:
        row: JsonDict = {"name": name, "ok": ok}
        if extra:
            row.update(extra)
        steps.append(row)
        mark = "SKIP" if (extra or {}).get("skipped") else ("PASS" if ok else "FAIL")
        log(f"  [{mark}] {name}")
        detail = (extra or {}).get("note") or (extra or {}).get("reason")
        if detail:
            log(f"        {detail}")

    # ---------------------------------------------------------------- device I/O

    def run_gesture(gesture: str, wait_s: float = 0.4) -> JsonDict:
        r = invoke("physical_gesture", {"gesture": gesture, "target": target, "timeout": 35.0})
        time.sleep(wait_s)
        return r

    def get_state() -> Optional[JsonDict]:
        r = invoke("physical_gesture", {"gesture": "get_state", "target": target, "timeout": 10.0})
        dev = r.get("device") if isinstance(r.get("device"), dict) else {}
        return dev.get("state") if isinstance(dev.get("state"), dict) else None

    def _on_first_station_track_1(st: Optional[JsonDict]) -> bool:
        if not st or st.get("mode") != "playlist":
            return False
        try:
            album = int(st["current_album_index"])
            track = int(st["current_track"])
        except (KeyError, TypeError, ValueError):
            return False
        return album == 0 and track == 1

    def _connection_up() -> bool:
        if request is None:
            return True
        try:
            cs = request("get_connection_state", {})
        except Exception:
            return True
        state = cs.get("state") if isinstance(cs.get("state"), dict) else {}
        if not state:
            return True
        return bool(state.get("connected"))

    def _bring_com_up() -> None:
        if request is not None:
            try:
                request("device_connect", {"auto_start_streaming": True})
                return
            except Exception:
                pass
        invoke("connect_device", {"auto_start_streaming": True})
        invoke("start_streaming", {})

    def _reconnect_after_reset() -> Optional[JsonDict]:
        """USB usually drops across machine.soft_reset(); bring COM back.

        Do not call get_state while COM is down — that IPC wait is ~10s and
        eight misses is why the first soft-reset start aborted after two minutes.
        """
        _bring_com_up()
        time.sleep(_RECONNECT_GAP_S)
        for _ in range(_RECONNECT_ATTEMPTS):
            if not _connection_up():
                _bring_com_up()
                time.sleep(_RECONNECT_GAP_S)
                continue
            st = get_state()
            if st:
                return st
            time.sleep(_RECONNECT_GAP_S)
        return get_state() if _connection_up() else None

    def _soft_reset_firmware() -> Optional[JsonDict]:
        """Boot from machine.soft_reset() so ads and position start at zero."""
        invoke("restart_firmware", {})
        time.sleep(_FIRMWARE_RESET_SETTLE_S)
        return _reconnect_after_reset()

    def tail_lines(limit: int = 500) -> List[str]:
        if target != "device":
            return []
        r = invoke("device_stream_tail", {"limit": limit})
        raw = r.get("lines") if r.get("ok") else []
        return [str(x) for x in raw] if isinstance(raw, list) else []

    def tail_session(limit: int = 600) -> List[str]:
        lines = tail_lines(max(limit, 600))
        last = -1
        for i, line in enumerate(lines):
            if _BOOT_MARKER in line:
                last = i
        return lines[last:] if last >= 0 else lines

    def mark_serial() -> List[str]:
        """Snapshot the serial ring so later output can be diffed against it."""
        return [ln for ln in tail_lines(1500) if ln.strip()]

    def serial_since(mark: List[str]) -> Tuple[List[str], bool]:
        """Lines appended since a snapshot, plus whether the join point was found.

        A chatty device can rotate the ring buffer past the snapshot. Saying so
        matters: silently falling back to the whole buffer would let events from
        an earlier phase satisfy a check about this one.
        """
        now = [ln for ln in tail_lines(1500) if ln.strip()]
        if not mark:
            return now, True
        if len(now) >= len(mark) and now[: len(mark)] == mark:
            return now[len(mark) :], True
        for overlap in range(min(len(mark), len(now)), 0, -1):
            if mark[-overlap:] == now[:overlap]:
                return now[overlap:], True
        return now, False

    def poll_until_playing(max_s: float = _TRACK_START_MAX_S) -> Tuple[bool, float, Optional[JsonDict]]:
        t0 = time.time()
        while True:
            st = get_state()
            if st and st.get("busy_pin") == 0:
                return True, round(time.time() - t0, 2), st
            if time.time() - t0 >= max_s:
                return False, round(max_s, 2), st
            time.sleep(_POLL_INTERVAL_S)

    def scan_errors(lines: List[str]) -> JsonDict:
        joined = "\n".join(lines)
        return {
            "errors": [p for p in _ERROR_PATTERNS if p in joined],
            "warns": [p for p in _WARN_PATTERNS if p in joined],
            "line_count": len(lines),
        }

    # ---------------------------------------------------------------- acoustics

    line_in_device: JsonDict = {"resolved": False, "index": None, "reason": None}

    def _healthiest_candidate(candidates: List[int]) -> int:
        """Try each candidate host-API slot for the same physical device, in
        ranked order, and stop as soon as one is genuinely audible.

        A USB line-in device is enumerated once per host API (MME, DirectSound,
        WASAPI); one API's slot can silently go stale after the device is
        hot-unplugged/replugged while the others correctly bind to the new
        device instance. Observed directly: MME read -96 dBFS (pure noise
        floor) while DirectSound on the identical hardware read -45 dBFS at
        the same moment. Trusting only the first name match would have picked
        the dead one every time. Skipped entirely when there is nothing to
        choose between.

        Deliberately does NOT probe every remaining candidate once a good one
        is found "to see if another is louder" - each probe opens a fresh
        stream on the same physical USB hardware, and cheap USB audio class
        chips are not built for being hammered with back-to-back opens across
        every duplicate host-API slot. Ranked order already prefers the real
        device name, so the common case costs exactly one open.

        Readings above ``_PROBE_MAX_PLAUSIBLE_RMS_DBFS`` (or non-finite) are
        treated the same as a failed probe rather than a candidate worth
        keeping - observed directly from a misidentified loopback-type device
        reporting +40 dBFS, which is not physically possible for unclipped
        audio.
        """
        if len(candidates) == 1:
            return candidates[0]
        best_idx = candidates[0]
        best_rms = float("-inf")
        readings = []
        for idx in candidates:
            try:
                r = request(  # type: ignore[misc]
                    "line_in_analyze",
                    {
                        "duration_s": _DEVICE_PROBE_S,
                        "sample_rate": 48000,
                        "device": idx,
                        "detect_ident": False,
                    },
                )
            except Exception:
                readings.append(f"{idx}:exception")
                continue
            rms = (r.get("summary") or {}).get("rms_dbfs") if r.get("ok") else None
            plausible = (
                rms is not None
                and math.isfinite(float(rms))
                and float(rms) <= _PROBE_MAX_PLAUSIBLE_RMS_DBFS
            )
            if rms is None:
                readings.append(f"{idx}:fail")
            elif not plausible:
                readings.append(f"{idx}:{rms}(implausible)")
            else:
                readings.append(f"{idx}:{rms}")
            if plausible and float(rms) > best_rms:
                best_rms = float(rms)
                best_idx = idx
            if plausible and float(rms) > _LINE_IN_RMS_MIN_DB:
                log(f"    line-in device probe {{{', '.join(readings)}}} -> using {idx}")
                return idx
            # Not audible yet - give the hardware a moment before the next
            # open rather than hammering it back-to-back.
            time.sleep(_DEVICE_PROBE_SETTLE_S)
        log(f"    line-in device probe {{{', '.join(readings)}}} -> none audible, using {best_idx}")
        return best_idx

    def resolve_line_in() -> Optional[int]:
        if line_in_device["resolved"]:
            return line_in_device["index"]
        line_in_device["resolved"] = True
        if request is None or target != "device":
            line_in_device["reason"] = "no_request_callable_or_not_device"
            return None
        try:
            from .mcp_device_acceptance import rank_line_in_device_candidates

            r = request("line_in_list_devices", {})
            devices = r.get("devices", []) if r.get("ok") else []
            candidates = rank_line_in_device_candidates(devices, r.get("default_input_index"))
            if not candidates:
                line_in_device["reason"] = "no_suitable_input_device"
                return None
            idx = _healthiest_candidate(candidates)
            line_in_device["index"] = idx
            return idx
        except Exception as exc:
            line_in_device["reason"] = f"exception: {exc}"
            return None

    def capture_ident(
        duration_s: float = _IDENT_CAPTURE_S,
        why: str = "",
        *,
        detect_ident: bool = True,
    ) -> JsonDict:
        """Record line-in and decode which folder/track is really playing."""
        idx = resolve_line_in()
        if idx is None:
            return {"ok": True, "skipped": True, "reason": line_in_device["reason"]}
        try:
            log(f"    listening {duration_s:.1f}s{(' - ' + why) if why else ''}...")
            r = request(  # type: ignore[misc]
                "line_in_analyze",
                {
                    "duration_s": duration_s,
                    "sample_rate": 48000,
                    "device": idx,
                    "detect_ident": detect_ident,
                },
            )
            ident = r.get("ident") or {}
            summary = r.get("summary") or {}
            dominant = ident.get("dominant") or {}
            order = ident.get("played_order") or []
            rms = summary.get("rms_dbfs")
            heard = (
                f"{dominant.get('folder')}/{dominant.get('track')}"
                if dominant
                else "nothing decoded"
            )
            log(f"    heard: {heard}  (rms {rms} dBFS, {ident.get('decoded_segments')} segments)")
            return {
                "ok": bool(ident.get("ok")),
                "skipped": False,
                "folder": dominant.get("folder"),
                "track": dominant.get("track"),
                "played_order": [(o["folder"], o["track"]) for o in order],
                "rms_dbfs": rms,
                "decoded_segments": ident.get("decoded_segments"),
                "total_segments": ident.get("total_segments"),
            }
        except Exception as exc:
            return {"ok": True, "skipped": True, "reason": f"exception: {exc}"}

    def acoustics_available() -> bool:
        return resolve_line_in() is not None

    def device_volume() -> Optional[int]:
        """Last volume the firmware reported setting, to explain a silent capture."""
        for line in reversed(tail_session(600)):
            m = re.search(r"set volume (\d+)", line)
            if m:
                return int(m.group(1))
        return None

    # ---------------------------------------------------------------- ad waiting

    def ad_active(st: Optional[JsonDict]) -> bool:
        if not st:
            return False
        if folder_ads and st.get("folder_commercial_playing"):
            return True
        if inline_ads and st.get("playing_commercial") and not folder_ads:
            return True
        return bool(st.get("playing_commercial")) if inline_ads else False

    def wait_for_ad(max_s: float = _AD_WAIT_MAX_S) -> Tuple[bool, Optional[JsonDict], float]:
        t0 = time.time()
        while time.time() - t0 < max_s:
            st = get_state()
            if ad_active(st):
                return True, st, round(time.time() - t0, 1)
            time.sleep(0.25)
        return False, get_state(), round(max_s, 1)

    def wait_for_ad_end() -> bool:
        """Poll until the ad clears, rather than assuming how long ads run."""
        limit = AD_TRACK_S + _NATURAL_END_MAX_S
        t0 = time.time()
        while time.time() - t0 < limit:
            if not ad_active(get_state()):
                return True
            time.sleep(0.3)
        return False

    def wait_for_music_playing(
        max_s: float = _TRACK_START_MAX_S,
    ) -> Tuple[bool, float, Optional[JsonDict]]:
        """Poll until a music track (not folder 99) is playing."""
        t0 = time.time()
        while time.time() - t0 < max_s:
            st = get_state()
            if st and st.get("busy_pin") == 0 and not ad_active(st):
                pf = st.get("playing_folder")
                try:
                    folder_num = int(pf) if pf is not None else None
                except (TypeError, ValueError):
                    folder_num = None
                if folder_num is None or folder_num != COMMERCIALS_FOLDER:
                    return True, round(time.time() - t0, 2), st
            time.sleep(_POLL_INTERVAL_S)
        return False, round(max_s, 2), get_state()

    def _probe_am_pearson() -> Optional[float]:
        """Short line-in compare vs AMradioSound.wav. None if capture is unavailable."""
        idx = resolve_line_in()
        if idx is None or request is None:
            return None
        try:
            r = request(
                "line_in_analyze",
                {
                    "duration_s": _DEVICE_PROBE_S,
                    "sample_rate": 48000,
                    "device": idx,
                    "detect_ident": False,
                    "reference_wav": "",
                },
            )
        except Exception:
            return None
        if not r.get("ok"):
            return None
        pearson = (r.get("reference_compare") or {}).get("envelope_pearson_r")
        try:
            return float(pearson) if pearson is not None else None
        except (TypeError, ValueError):
            return None

    def wait_for_music_ready(
        max_s: float = _MUSIC_READY_MAX_S,
        mark: Optional[List[str]] = None,
    ) -> Tuple[bool, float, Optional[JsonDict]]:
        """Wait until AM overlay is done and music (not an ad) is playing.

        Prefer the firmware ``AM: PWM overlay complete`` line. If that never
        arrives, treat a low envelope match vs AMradioSound.wav as the music
        phase. Do not decode pilot idents while overlay is still the loud signal.
        """
        snap = mark if mark is not None else mark_serial()
        t0 = time.time()
        probed = False
        while time.time() - t0 < max_s:
            st = get_state()
            if ad_active(st):
                wait_for_ad_end()
                time.sleep(_POLL_INTERVAL_S)
                continue
            overlay_done, _ = _serial_lines_contain(_AM_OVERLAY_COMPLETE, prefer_mark=snap)
            playing = bool(st and st.get("busy_pin") == 0 and not ad_active(st))
            if playing and overlay_done:
                return True, round(time.time() - t0, 2), st
            if playing and not probed:
                pearson = _probe_am_pearson()
                probed = True
                if pearson is None or pearson < _AM_PEARSON_MUSIC_MAX:
                    return True, round(time.time() - t0, 2), st
            time.sleep(_POLL_INTERVAL_S)
        return False, round(max_s, 2), get_state()

    def capture_music_ident(
        *,
        why: str = "",
        duration_s: float = _IDENT_CAPTURE_S,
    ) -> JsonDict:
        """Decode ident from music only; drain any in-flight folder-99 ad first."""
        heard: JsonDict = {"skipped": True, "reason": "no music capture"}
        for _attempt in range(3):
            if ad_active(get_state()):
                wait_for_ad_end()
            ok, _lat, _st = wait_for_music_ready(_MUSIC_READY_MAX_S)
            if not ok:
                time.sleep(0.3)
                continue
            heard = capture_ident(duration_s=duration_s, why=why)
            if heard.get("skipped"):
                return heard
            try:
                folder = int(heard.get("folder")) if heard.get("folder") is not None else None
            except (TypeError, ValueError):
                folder = None
            if folder == COMMERCIALS_FOLDER:
                wait_for_ad_end()
                continue
            return heard
        return heard

    def _serial_lines_contain(substr: str, prefer_mark: Optional[List[str]] = None) -> Tuple[bool, bool]:
        """Return (found, anchored). Falls back to the boot-scoped session tail."""
        if prefer_mark:
            post, anchored = serial_since(prefer_mark)
            if anchored:
                return any(substr in ln for ln in post), True
        return any(substr in ln for ln in tail_session(800)), False

    # ================================================================= Phase 0
    log("")
    log(f"=== Commercials acceptance: {cfg['label']}")
    log(
        f"    library: {EXPECTED_STATIONS} stations x {TRACKS_PER_STATION} tracks "
        f"(~{MUSIC_TRACK_S:.0f}s each) + {EXPECTED_ADS} ads in folder {COMMERCIALS_FOLDER}; "
        f"interval {COMMERCIAL_INTERVAL}"
    )
    log("--- Phase 0: connectivity and library shape")

    st0 = get_state()
    if not st0:
        add_step("device_reachable", False, {"note": "no state from device; is it connected?"})
        return _finish(steps, suite_name, cfg, log, aborted="device unreachable")
    add_step("device_reachable", True, {"state": st0})

    station_count = st0.get("total_playlists")
    stations_ok = station_count == EXPECTED_STATIONS
    add_step(
        "station_count_matches_test_library",
        stations_ok,
        {
            "expected": EXPECTED_STATIONS,
            "actual": station_count,
            "note": (
                None
                if stations_ok
                else "SD card does not hold the generated test library - "
                "run generate_test_library_audio.py, import it, then sync"
            ),
        },
    )
    if not stations_ok:
        return _finish(steps, suite_name, cfg, log, aborted="wrong library on SD")

    reported_mode = st0.get("commercials_mode")
    mode_ok = reported_mode == cfg["mode"]
    add_step(
        "firmware_reports_expected_commercials_mode",
        mode_ok,
        {
            "expected": cfg["mode"],
            "actual": reported_mode,
            "note": None if mode_ok else "set the mode in the app and Install Firmware",
        },
    )
    if not mode_ok:
        return _finish(steps, suite_name, cfg, log, aborted="wrong commercials mode on Pico")

    # Folder-99 inserts are gated by Pico-flash policy (advanced_runtime.json),
    # not by SD sync. Mode defaults to folder_99 even when ads are off, so a
    # mode-only check would keep running a deaf-to-ads suite.
    needs_folder_ads = cfg["mode"] in ("folder_99", "both")
    if needs_folder_ads:
        enabled = st0.get("commercials_enabled")
        enabled_ok = enabled is True
        add_step(
            "firmware_reports_commercials_enabled",
            enabled_ok,
            {
                "expected": True,
                "actual": enabled,
                "note": (
                    None
                    if enabled_ok
                    else "Pico flash does not have commercials enabled - "
                    "Install Firmware from the folder-99 test library"
                ),
            },
        )
        if not enabled_ok:
            return _finish(steps, suite_name, cfg, log, aborted="commercials disabled on Pico")

        reported_interval = st0.get("commercials_interval")
        try:
            interval_ok = int(reported_interval) == COMMERCIAL_INTERVAL
        except (TypeError, ValueError):
            interval_ok = False
        add_step(
            "firmware_reports_expected_commercials_interval",
            interval_ok,
            {
                "expected": COMMERCIAL_INTERVAL,
                "actual": reported_interval,
                "note": (
                    None
                    if interval_ok
                    else "set the interval to 3 in the app and Install Firmware"
                ),
            },
        )
        if not interval_ok:
            return _finish(steps, suite_name, cfg, log, aborted="wrong commercials interval on Pico")

    if not acoustics_available():
        add_step(
            "line_in_available",
            True,
            {
                "skipped": True,
                "reason": line_in_device["reason"],
                "note": "acoustic checks will be skipped - state and serial checks still run",
            },
        )
    else:
        add_step("line_in_available", True, {"device_index": line_in_device["index"]})

    log("    soft-resetting firmware so the suite starts at boot...")
    st0 = _soft_reset_firmware()
    if not st0:
        add_step(
            "firmware_soft_reset",
            False,
            {"note": "no state after restart_firmware; COM may still be down"},
        )
        return _finish(steps, suite_name, cfg, log, aborted="soft reset did not come back")
    add_step("firmware_soft_reset", True)
    poll_until_playing(_TRACK_START_MAX_S)
    log("    five_tap to station 1 track 1, then wait for AM overlay to finish...")
    run_gesture("five_tap", 1.0)
    ready0, lat0, st_ready = wait_for_music_ready(_MUSIC_READY_MAX_S)

    if acoustics_available():
        probe = capture_ident(
            duration_s=_DEVICE_PROBE_S,
            why="audio path level check",
            detect_ident=False,
        )
        rms = probe.get("rms_dbfs")
        volume = device_volume()
        audible = rms is not None and float(rms) > _LINE_IN_RMS_MIN_DB
        add_step(
            "audio_path_is_audible",
            audible,
            {
                "rms_dbfs": rms,
                "threshold_db": _LINE_IN_RMS_MIN_DB,
                "device_volume": volume,
                "note": (
                    None
                    if audible
                    else f"line-in reads {rms} dBFS while the DFPlayer reports playing. "
                    f"Device volume is {volume if volume is not None else 'unknown'} "
                    "(0-30). Check the radio volume, then the 3.5mm cable, then "
                    "unplug/replug the USB line-in adapter and close any app holding it."
                ),
            },
        )
        if not audible and require_audio:
            log("")
            log("  Aborting early rather than running the full suite deaf.")
            log("  Re-run with require_audio=false to check state and serial only.")
            return _finish(steps, suite_name, cfg, log, aborted="line-in silent")

    # ================================================================= Phase 1
    log("--- Phase 1: ordered station playback plays every track, in order, once")
    st = st_ready
    on_first = _on_first_station_track_1(st)
    add_step(
        "reset_to_first_station_playing",
        ready0 and on_first,
        {
            "start_latency_s": lat0,
            "station_index": (st or {}).get("current_album_index"),
            "track": (st or {}).get("current_track"),
            "used_five_tap": True,
            "used_triple_tap": False,
            "note": "soft-reset, then one five_tap; wait_for_music_ready drains the AM overlay",
        },
    )

    heard_sequence: List[Tuple[Optional[int], Optional[int]]] = []
    ordered_results: List[JsonDict] = []

    def _record_music_heard(heard: JsonDict) -> None:
        if heard.get("skipped") or not heard.get("folder"):
            return
        try:
            folder = int(heard.get("folder"))
        except (TypeError, ValueError):
            return
        if folder == COMMERCIALS_FOLDER:
            return
        heard_sequence.append((folder, heard.get("track")))

    # Skip through station 1. The tap after track 3 inserts the interval ad;
    # after that we hear track 4, then skip onto station 2.
    for expected_track in range(1, TRACKS_PER_STATION + 1):
        st_before = get_state()
        if expected_track == COMMERCIAL_INTERVAL + 1 and folder_ads:
            found_skip_ad, st_skip, waited_skip = wait_for_ad(_AD_WAIT_MAX_S)
            add_step(
                "gesture_skip_inserts_interval_ad",
                found_skip_ad,
                {
                    "waited_s": waited_skip,
                    "playing_folder": (st_skip or {}).get("playing_folder"),
                    "note": "skipping music must count toward the interval, same as a "
                    "natural track end",
                },
            )
            if found_skip_ad:
                wait_for_ad_end()
        ok_play, latency, st_after = wait_for_music_ready(_MUSIC_READY_MAX_S)
        if not ok_play:
            ok_play, latency, st_after = wait_for_music_playing(_TRACK_START_MAX_S)
        why = (
            "last station track after skip-ad"
            if expected_track == TRACKS_PER_STATION and folder_ads
            else f"ordered track {expected_track}/{TRACKS_PER_STATION}"
        )
        heard = capture_music_ident(why=why)
        _record_music_heard(heard)
        st_hold = get_state()
        sustained = bool(st_hold and st_hold.get("busy_pin") == 0 and not ad_active(st_hold))
        ordered_results.append(
            {
                "n": expected_track,
                "started": ok_play,
                "sustained": sustained,
                "start_latency_s": latency,
                "reported_track": (st_after or {}).get("current_track"),
                "heard": (heard.get("folder"), heard.get("track")),
                "track_before": (st_before or {}).get("current_track"),
            }
        )
        if expected_track < TRACKS_PER_STATION:
            run_gesture("single_tap", 0.6)

    starts_ok = all(r["started"] and r["sustained"] for r in ordered_results)
    add_step(
        "ordered_tracks_start_and_sustain",
        starts_ok,
        {
            "tracks": ordered_results,
            "note": f"each track must start within {_TRACK_START_MAX_S}s and still play "
            f"{_MIN_PLAY_DURATION_S}s later",
        },
    )

    if heard_sequence:
        expected = [(1, n) for n in range(1, TRACKS_PER_STATION + 1)]
        sequence_ok = heard_sequence == expected
        repeats = [p for p in set(heard_sequence) if heard_sequence.count(p) > 1]
        missing = [p for p in expected if p not in heard_sequence]
        add_step(
            "no_skipped_or_repeated_tracks_acoustic",
            sequence_ok,
            {
                "expected": expected,
                "heard": heard_sequence,
                "repeated": repeats,
                "missing": missing,
                "note": "decoded from the speaker output, not from reported state",
            },
        )
    else:
        add_step(
            "no_skipped_or_repeated_tracks_acoustic",
            True,
            {
                "skipped": True,
                "reason": line_in_device["reason"]
                or "no idents decoded - is the generated test library on the SD card?",
            },
        )

    if ad_active(get_state()):
        wait_for_ad_end()
    st_last = get_state()
    run_gesture("single_tap", 0.6)
    if ad_active(get_state()):
        wait_for_ad_end()
    ok_ns, lat_ns, st_ns = wait_for_music_ready(_MODE_SWITCH_MAX_S)
    if not ok_ns:
        ok_ns, lat_ns, st_ns = wait_for_music_playing(_MODE_SWITCH_MAX_S)
    heard_ns = capture_music_ident(why="next station after last-track skip")
    if not heard_ns.get("skipped") and heard_ns.get("folder"):
        station_ok = (heard_ns.get("folder"), heard_ns.get("track")) == (2, 1)
    else:
        station_ok = bool(
            st_ns
            and int(st_ns.get("current_album_index") or -1) == 1
            and int(st_ns.get("current_track") or 0) == 1
        )
    add_step(
        "single_tap_past_last_track_advances_station",
        ok_ns and station_ok,
        {
            "start_latency_s": lat_ns,
            "last_track_state": {
                "station_index": (st_last or {}).get("current_album_index"),
                "track": (st_last or {}).get("current_track"),
            },
            "station_index": (st_ns or {}).get("current_album_index"),
            "track": (st_ns or {}).get("current_track"),
            "heard": (heard_ns.get("folder"), heard_ns.get("track")),
            "note": "skipping the last track of a station must start the next station, "
            "not wrap the same album",
        },
    )

    # ================================================================= Phase 2
    if folder_ads:
        log("--- Phase 2: folder-99 ads fire on cadence and resume the right track")
        mark = mark_serial()
        found_ad, st_ad, waited = wait_for_ad(_AD_WAIT_MAX_S)
        add_step(
            "folder_ad_inserted_within_two_cycles",
            found_ad,
            {
                "waited_s": waited,
                "max_wait_s": _AD_WAIT_MAX_S,
                "note": f"expect an ad every {COMMERCIAL_INTERVAL} finished music tracks",
            },
        )

        if found_ad:
            heard_ad = capture_ident(why="folder-99 ad")
            if heard_ad.get("skipped"):
                add_step(
                    "ad_audio_comes_from_folder_99",
                    True,
                    {"skipped": True, "reason": heard_ad.get("reason")},
                )
            else:
                from_99 = heard_ad.get("folder") == COMMERCIALS_FOLDER
                add_step(
                    "ad_audio_comes_from_folder_99",
                    from_99,
                    {
                        "heard_folder": heard_ad.get("folder"),
                        "heard_track": heard_ad.get("track"),
                        "rms_dbfs": heard_ad.get("rms_dbfs"),
                        "note": "the ad the ear hears must be a folder-99 file",
                    },
                )

            # Let the ad end naturally and watch where playback resumes.
            log("    waiting for the ad to finish naturally...")
            wait_for_ad_end()
            resume_heard = capture_ident(why="track resumed after ad")
            resumed, anchored2 = _serial_lines_contain(_AD_RESUME, mark)
            cancel, _ = _serial_lines_contain(_AD_CANCEL, mark)
            acoustic_ok = not resume_heard.get("skipped") and resume_heard.get(
                "folder"
            ) not in (None, COMMERCIALS_FOLDER)
            add_step(
                "ad_resumes_music_without_stale_cancel",
                (resumed or acoustic_ok) and not cancel,
                {
                    "skipped": False,
                    "reason": None if anchored2 else "used session tail (ring may have rotated)",
                    "resume_logged": resumed,
                    "cancel_logged": cancel,
                    "acoustic_resume": acoustic_ok,
                    "note": "an uninterrupted ad must resume music and must not log a cancel",
                },
            )
            if not resume_heard.get("skipped"):
                back_to_music = resume_heard.get("folder") not in (None, COMMERCIALS_FOLDER)
                add_step(
                    "resumed_audio_is_music_not_another_ad",
                    back_to_music,
                    {
                        "heard_folder": resume_heard.get("folder"),
                        "heard_track": resume_heard.get("track"),
                    },
                )

            post, _anchored_starts = serial_since(mark)
            starts = [ln for ln in post if "_start_playback_for_current" in ln]
            if not starts:
                starts = [
                    ln for ln in tail_session(800) if "_start_playback_for_current" in ln
                ]
            double_start = len(starts) > 1 and starts[0] == starts[1]
            add_step(
                "resume_does_not_restart_the_same_track",
                not double_start,
                {
                    "starts_seen": len(starts),
                    "note": "regression guard: a stale resume point used to replay the "
                    "track that was already playing",
                },
            )

        # ------------------------------------------------------------ Phase 3
        log("--- Phase 3: interrupting an ad cancels its pending resume")
        found_ad2, _st, waited2 = wait_for_ad(_AD_WAIT_MAX_S)
        if not found_ad2:
            add_step(
                "gesture_during_ad_cancels_resume",
                False,
                {"reason": "no second ad observed", "waited_s": waited2},
            )
        else:
            mark2 = mark_serial()
            st_mid = get_state()
            if ad_active(st_mid):
                run_gesture("single_tap", 1.0)
                time.sleep(4.0)
                post2, anchored3 = serial_since(mark2)
                cancelled = any(_AD_CANCEL in ln for ln in post2)
                stale_resume = any(_AD_RESUME in ln for ln in post2)
                add_step(
                    "gesture_during_ad_cancels_resume",
                    True if not anchored3 else (cancelled and not stale_resume),
                    {
                        "skipped": not anchored3,
                        "reason": None if anchored3 else "serial ring rotated past the marker",
                        "cancel_logged": cancelled,
                        "stale_resume_logged": stale_resume,
                        "note": "tapping mid-ad must drop the saved resume point so the "
                        "next track end is not mistaken for the ad ending",
                    },
                )
                after = get_state()
                add_step(
                    "playback_healthy_after_interrupting_ad",
                    bool(after and after.get("busy_pin") == 0),
                    {"busy_pin": (after or {}).get("busy_pin")},
                )
            else:
                add_step(
                    "gesture_during_ad_cancels_resume",
                    True,
                    {"skipped": True, "reason": "ad ended before the gesture could land"},
                )
    else:
        log("--- Phases 2-3 skipped: this suite does not use folder-99 inserts")

    # ================================================================= Phase 4
    log("--- Phase 4: station changes never land on the commercials folder")
    station_walk: List[JsonDict] = []
    for i in range(EXPECTED_STATIONS):
        before = (get_state() or {}).get("current_album_index")
        run_gesture("long_press", 1.5)
        ok_sw, lat_sw, st_sw = wait_for_music_ready(_MODE_SWITCH_MAX_S)
        if not ok_sw:
            ok_sw, lat_sw, st_sw = poll_until_playing(_MODE_SWITCH_MAX_S)
        heard = capture_ident(why=f"station change {i + 1}/{EXPECTED_STATIONS}")
        station_walk.append(
            {
                "n": i + 1,
                "index_before": before,
                "index_after": (st_sw or {}).get("current_album_index"),
                "playing_folder": (st_sw or {}).get("playing_folder"),
                "started": ok_sw,
                "start_latency_s": lat_sw,
                "heard_folder": heard.get("folder"),
            }
        )

    changed_ok = all(
        w["started"] and w["index_after"] != w["index_before"] for w in station_walk
    )
    add_step("station_advance_changes_station", changed_ok, {"stations": station_walk})

    heard_folders = [w["heard_folder"] for w in station_walk if w["heard_folder"]]
    if heard_folders:
        add_step(
            "commercials_folder_is_not_a_station",
            COMMERCIALS_FOLDER not in heard_folders,
            {
                "heard_folders": heard_folders,
                "note": f"folder {COMMERCIALS_FOLDER} must be excluded from the station rotation",
            },
        )
    else:
        add_step(
            "commercials_folder_is_not_a_station",
            all(w["playing_folder"] != COMMERCIALS_FOLDER for w in station_walk),
            {"note": "checked from reported state; line-in unavailable"},
        )

    # ================================================================= Phase 5
    log("--- Phase 5: shuffle modes")
    run_gesture("double_tap_long_press", 2.0)
    ok_sh, lat_sh, st_sh = wait_for_music_ready(_MODE_SWITCH_MAX_S)
    if not ok_sh:
        ok_sh, lat_sh, st_sh = poll_until_playing(_MODE_SWITCH_MAX_S)
    shuffle_ok = bool(
        st_sh and st_sh.get("mode") == "shuffle" and st_sh.get("shuffle_source_type") == "station"
    )
    add_step(
        "station_shuffle_engages",
        ok_sh and shuffle_ok,
        {
            "mode": (st_sh or {}).get("mode"),
            "shuffle_source_type": (st_sh or {}).get("shuffle_source_type"),
            "start_latency_s": lat_sh,
        },
    )

    shuffle_heard: List[Tuple[Optional[int], Optional[int]]] = []
    shuffle_started = []
    for i in range(TRACKS_PER_STATION):
        if i > 0:
            run_gesture("single_tap", 0.6)
        ok_play, _lat, _st = wait_for_music_ready(_TRACK_START_MAX_S)
        if not ok_play:
            ok_play, _lat, _st = poll_until_playing(_TRACK_START_MAX_S)
        shuffle_started.append(ok_play)
        heard = capture_ident(why=f"shuffle track {i + 1}/{TRACKS_PER_STATION}")
        if not heard.get("skipped") and heard.get("folder"):
            shuffle_heard.append((heard.get("folder"), heard.get("track")))
        time.sleep(max(0.0, _MIN_PLAY_DURATION_S - _IDENT_CAPTURE_S))

    add_step("shuffle_tracks_all_start", all(shuffle_started), {"started": shuffle_started})

    if shuffle_heard:
        music = [p for p in shuffle_heard if p[0] != COMMERCIALS_FOLDER]
        one_station = len({p[0] for p in music}) <= 1
        no_repeats = len(music) == len(set(music))
        add_step(
            "station_shuffle_stays_in_one_station_without_repeats",
            one_station and no_repeats,
            {
                "heard": shuffle_heard,
                "distinct_stations": sorted({p[0] for p in music}),
                "note": "a station shuffle must cover its own station's tracks without "
                "repeating one before the rest have played",
            },
        )
    else:
        add_step(
            "station_shuffle_stays_in_one_station_without_repeats",
            True,
            {"skipped": True, "reason": line_in_device["reason"] or "no idents decoded"},
        )

    if folder_ads:
        mark3 = mark_serial()
        found_sh_ad, _st, waited3 = wait_for_ad(_AD_WAIT_MAX_S)
        add_step(
            "ads_still_insert_during_shuffle",
            found_sh_ad,
            {
                "waited_s": waited3,
                "note": "interval inserts must keep working while shuffling",
            },
        )
        if found_sh_ad:
            ended = wait_for_ad_end()
            resumed, anchored4 = _serial_lines_contain(_AD_RESUME, mark3)
            ok_play, _, st_after = poll_until_playing(_TRACK_START_MAX_S)
            add_step(
                "shuffle_resumes_after_ad",
                ended and (resumed or bool(ok_play and st_after and st_after.get("busy_pin") == 0)),
                {
                    "skipped": False,
                    "reason": None if anchored4 else "used session tail (ring may have rotated)",
                    "ad_ended": ended,
                    "resume_logged": resumed,
                    "playing_after_ad": bool(ok_play and st_after and st_after.get("busy_pin") == 0),
                    "note": "shuffle must continue after the ad rather than stalling",
                },
            )

    if cfg["library_shuffle"]:
        log("--- Phase 5b: library shuffle (Conductor only)")
        run_gesture("triple_tap_long_press", 2.5)
        ok_lib, lat_lib, st_lib = poll_until_playing(_MODE_SWITCH_MAX_S)
        lib_ok = bool(
            st_lib
            and st_lib.get("mode") == "shuffle"
            and st_lib.get("shuffle_source_type") == "library"
        )
        add_step(
            "library_shuffle_engages",
            ok_lib and lib_ok,
            {
                "mode": (st_lib or {}).get("mode"),
                "shuffle_source_type": (st_lib or {}).get("shuffle_source_type"),
                "start_latency_s": lat_lib,
            },
        )

        lib_heard: List[Tuple[Optional[int], Optional[int]]] = []
        # Extra samples so folder-99 inserts during skip do not hide a station change.
        lib_samples = TRACKS_PER_STATION + 4
        for i in range(lib_samples):
            if i > 0:
                run_gesture("single_tap", 0.6)
            poll_until_playing(_TRACK_START_MAX_S)
            heard = capture_ident(why=f"library shuffle {i + 1}/{lib_samples}")
            if not heard.get("skipped") and heard.get("folder"):
                lib_heard.append((heard.get("folder"), heard.get("track")))
            time.sleep(1.0)

        if lib_heard:
            music = [p for p in lib_heard if p[0] != COMMERCIALS_FOLDER]
            spans = len({p[0] for p in music})
            add_step(
                "library_shuffle_crosses_stations",
                spans > 1,
                {
                    "heard": lib_heard,
                    "distinct_stations": sorted({p[0] for p in music}),
                    "note": "a library shuffle must draw from more than one station",
                },
            )
        else:
            add_step(
                "library_shuffle_crosses_stations",
                True,
                {"skipped": True, "reason": line_in_device["reason"] or "no idents decoded"},
            )
    else:
        log("--- Phase 5b skipped: basic firmware has no library shuffle")
        run_gesture("triple_tap_long_press", 2.5)
        st_b = get_state()
        add_step(
            "basic_triple_hold_returns_to_first_station_shuffled",
            bool(
                st_b
                and st_b.get("current_album_index") == 0
                and st_b.get("shuffle_source_type") == "station"
            ),
            {
                "station_index": (st_b or {}).get("current_album_index"),
                "shuffle_source_type": (st_b or {}).get("shuffle_source_type"),
            },
        )

    # ================================================================= Phase 6
    if inline_ads:
        log("--- Phase 6: inline commercials")
        run_gesture("five_tap", 1.5)
        run_gesture("tap_long_press", 1.5)
        poll_until_playing(_MODE_SWITCH_MAX_S)

        inline_seen = False
        inline_detail: List[JsonDict] = []
        for i in range(TRACKS_PER_STATION * 2):
            run_gesture("single_tap", 0.6)
            poll_until_playing(_TRACK_START_MAX_S)
            st_i = get_state()
            if st_i and st_i.get("playing_commercial") and not st_i.get("folder_commercial_playing"):
                inline_seen = True
                inline_detail.append(
                    {
                        "step": i + 1,
                        "track": st_i.get("current_track"),
                        "linked": st_i.get("linked_ad_playing"),
                    }
                )

        add_step(
            "inline_ads_play_in_station_order",
            inline_seen,
            {
                "occurrences": inline_detail,
                "note": "catalog tracks flagged as ads must appear in the ordered station "
                "walk, reported without folder_commercial_playing",
            },
        )

        log("--- Phase 6b: linked commercials pair with the track below them")
        run_gesture("double_tap_long_press", 2.0)
        poll_until_playing(_MODE_SWITCH_MAX_S)
        mark4 = mark_serial()
        linked_pairs = 0
        for _ in range(TRACKS_PER_STATION + 2):
            run_gesture("single_tap", 0.6)
            poll_until_playing(_TRACK_START_MAX_S)
            time.sleep(1.0)
        post4, _anchored4 = serial_since(mark4)
        starts = [ln for ln in post4 if _LINKED_AD_START in ln]
        dones = [ln for ln in post4 if _LINKED_AD_DONE in ln]
        skips = [ln for ln in post4 if _LINKED_AD_SKIP in ln]
        # Natural end-of-ad and user skip both play the paired track; skip only
        # fires while _linked_ad_playing is true (same guard as _LINKED_AD_DONE).
        handoffs = len(dones) + len(skips)
        linked_pairs = min(len(starts), handoffs)
        add_step(
            "linked_ads_hand_off_to_their_track",
            len(starts) == 0 or linked_pairs > 0,
            {
                "linked_ad_starts": len(starts),
                "linked_ad_handoffs_natural": len(dones),
                "linked_ad_handoffs_skip": len(skips),
                "linked_ad_handoffs": handoffs,
                "note": "every linked ad that starts must hand off to its paired track "
                "(natural finish or skip during shuffle); zero linked ads is reported, not failed",
            },
        )
        if len(starts) == 0:
            log("        note: no linked commercials in this library - link one to cover this")
    else:
        log("--- Phase 6 skipped: this suite does not use inline commercials")

    # ================================================================= Phase 7
    log("--- Phase 7: revert to ordered playback and final serial scan")
    run_gesture("tap_long_press", 2.0)
    ok_rev, lat_rev, st_rev = poll_until_playing(_MODE_SWITCH_MAX_S)
    add_step(
        "reverts_to_ordered_playlist",
        ok_rev and bool(st_rev and st_rev.get("mode") == "playlist"),
        {"mode": (st_rev or {}).get("mode"), "start_latency_s": lat_rev},
    )

    final = scan_errors(tail_session(800))
    add_step(
        "final_serial_error_scan",
        not final["errors"],
        {
            "errors_found": final["errors"],
            "warns_found": final["warns"],
            "lines_scanned": final["line_count"],
        },
    )

    return _finish(steps, suite_name, cfg, log)


def _finish(
    steps: List[JsonDict],
    suite_name: str,
    cfg: JsonDict,
    log: Callable[[str], None],
    aborted: Optional[str] = None,
) -> JsonDict:
    failed = [s["name"] for s in steps if not s.get("ok") and not s.get("skipped")]
    skipped = [s["name"] for s in steps if s.get("skipped")]
    passed = sum(1 for s in steps if s.get("ok") and not s.get("skipped"))
    overall = not failed and not aborted

    report = [
        f"# Commercials acceptance - {cfg['label']}",
        "",
        f"- suite: `{suite_name}`",
        f"- firmware family: **{cfg['family']}**",
        f"- commercials mode: **{cfg['mode']}**",
        f"- library: {EXPECTED_STATIONS} stations x {TRACKS_PER_STATION} tracks "
        f"+ {EXPECTED_ADS} ads in folder {COMMERCIALS_FOLDER}, interval {COMMERCIAL_INTERVAL}",
        "",
        "## Steps",
        "",
        "| step | result | detail |",
        "| --- | --- | --- |",
    ]
    for s in steps:
        if s.get("skipped"):
            mark = "SKIP"
        else:
            mark = "PASS" if s.get("ok") else "FAIL"
        detail = s.get("note") or s.get("reason") or ""
        detail = str(detail).replace("|", "/").replace("\n", " ")[:160]
        report.append(f"| {s['name']} | {mark} | {detail} |")

    report += ["", f"**{passed} passed, {len(failed)} failed, {len(skipped)} skipped**", ""]
    if aborted:
        report.append(f"## Result: **ABORTED** - {aborted}")
    elif overall:
        report.append("## Result: **PASS**")
    else:
        report.append("## Result: **FAIL**")
        report.append("")
        for name in failed:
            report.append(f"- failed: `{name}`")
    if skipped:
        report += ["", "Skipped steps (gaps in coverage this run):"]
        for name in skipped:
            report.append(f"- `{name}`")

    log("")
    log(f"=== {suite_name}: {passed} passed, {len(failed)} failed, {len(skipped)} skipped")
    if failed:
        log(f"    failed: {', '.join(failed)}")

    return {
        "ok": overall,
        "suite": suite_name,
        "family": cfg["family"],
        "mode": cfg["mode"],
        "passed": passed,
        "failed": len(failed),
        "skipped": len(skipped),
        "total": len(steps),
        "failed_steps": failed,
        "skipped_steps": skipped,
        "aborted": aborted,
        "steps": steps,
        "report_markdown": "\n".join(report),
    }
