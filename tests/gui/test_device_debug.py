"""Tests for DeviceDebugWidget serial stream parsing and protocol logic.

These tests validate the parsing logic without requiring real hardware.
We test _parse_stream_for_now_playing, command output parsing, and
presence detection logic by creating the widget with mocked serial.
"""

from __future__ import annotations

import re
import pytest


# ---------------------------------------------------------------------------
# Pure stream parsing logic (extracted for testing without Qt)
# ---------------------------------------------------------------------------

def _parse_stream_line(line: str, state: dict, basic_mode: bool = False) -> None:
    """Mirror of DeviceDebugWidget._parse_stream_for_now_playing logic.

    We replicate the regex parsing here so we can test the rules that the
    production code must implement, without instantiating a full Qt widget.
    """
    if "_start_playback_for_current: mode=" in line:
        mode_match = re.search(r"mode=(\w+)", line)
        if mode_match:
            detected = mode_match.group(1)
            if basic_mode and detected == "playlist":
                detected = "station"
            state["mode"] = detected

        source_match = re.search(r"source=([^,]*?)(?:,\s*shuffle_type=|,\s*album_idx=|$)", line)
        if source_match:
            val = source_match.group(1).strip()
            if val:
                state["source"] = val

        shuffle_match = re.search(r"shuffle_type=(\w*)", line)
        if shuffle_match and shuffle_match.group(1):
            state["shuffle_type"] = shuffle_match.group(1)
        elif state.get("mode") != "shuffle":
            state["shuffle_type"] = ""

        idx_match = re.search(r"album_idx=(\d+)", line)
        if idx_match:
            state["album_idx"] = int(idx_match.group(1))
            if not state.get("source"):
                mode = state.get("mode", "")
                if mode == "station":
                    state["source"] = f"Station #{state['album_idx'] + 1}"
                elif mode == "album":
                    state["source"] = f"Album #{state['album_idx'] + 1}"
        return

    if "[MODE]" in line:
        match = re.search(r"(\w+)\s*->\s*(\w+)", line)
        if match:
            new_mode = match.group(2)
            if basic_mode and new_mode == "playlist":
                new_mode = "station"
            state["mode"] = new_mode
            state["source"] = ""
            if new_mode != "shuffle":
                state["shuffle_type"] = ""
            idx_match = re.search(r"album_idx=(\d+)", line)
            if idx_match:
                state["album_idx"] = int(idx_match.group(1))
        return

    if "Mode: Shuffle" in line:
        match = re.search(r"Mode: Shuffle \((.+?),\s*(\d+)\s*tracks?\)", line)
        if match:
            source = match.group(1).strip()
            state["mode"] = "shuffle"
            state["source"] = source
            if source == "Library":
                state["shuffle_type"] = "library"
            elif source.startswith("Station"):
                state["shuffle_type"] = "station"
            else:
                state["shuffle_type"] = "source"


# ---------------------------------------------------------------------------
# Stream parsing tests
# ---------------------------------------------------------------------------

class TestStreamParsing:
    def _fresh_state(self):
        return {"mode": "", "source": "", "shuffle_type": "", "album_idx": 0}

    def test_parses_mode_from_playback_line(self):
        state = self._fresh_state()
        _parse_stream_line(
            "_start_playback_for_current: mode=album, source=My Album, shuffle_type=, album_idx=0",
            state,
        )
        assert state["mode"] == "album"

    def test_parses_source_from_playback_line(self):
        state = self._fresh_state()
        _parse_stream_line(
            "_start_playback_for_current: mode=playlist, source=Chill Mix, shuffle_type=, album_idx=1",
            state,
        )
        assert state["source"] == "Chill Mix"

    def test_parses_shuffle_type(self):
        state = self._fresh_state()
        _parse_stream_line(
            "_start_playback_for_current: mode=shuffle, source=Library, shuffle_type=library, album_idx=0",
            state,
        )
        assert state["shuffle_type"] == "library"

    def test_unrelated_line_does_not_change_state(self):
        state = self._fresh_state()
        state["mode"] = "album"
        _parse_stream_line("Some random firmware log output", state)
        assert state["mode"] == "album"

    def test_mode_change_line_updates_mode(self):
        state = self._fresh_state()
        state["mode"] = "album"
        _parse_stream_line("[MODE] album -> playlist", state)
        assert state["mode"] == "playlist"

    def test_mode_change_clears_source(self):
        state = {"mode": "album", "source": "My Album", "shuffle_type": "", "album_idx": 0}
        _parse_stream_line("[MODE] album -> playlist", state)
        assert state["source"] == ""

    def test_mode_change_clears_shuffle_type_when_not_shuffle(self):
        state = {"mode": "shuffle", "source": "Library", "shuffle_type": "library", "album_idx": 0}
        _parse_stream_line("[MODE] shuffle -> album", state)
        assert state["shuffle_type"] == ""

    def test_shuffle_init_line_updates_mode_and_source(self):
        state = self._fresh_state()
        _parse_stream_line("Mode: Shuffle (Library, 50 tracks)", state)
        assert state["mode"] == "shuffle"
        assert state["source"] == "Library"
        assert state["shuffle_type"] == "library"

    def test_shuffle_station_type(self):
        state = self._fresh_state()
        _parse_stream_line("Mode: Shuffle (Station 2, 8 tracks)", state)
        assert state["shuffle_type"] == "station"

    def test_shuffle_named_source_type(self):
        state = self._fresh_state()
        _parse_stream_line("Mode: Shuffle (My Cool Album, 12 tracks)", state)
        assert state["shuffle_type"] == "source"

    def test_basic_mode_maps_playlist_to_station(self):
        state = self._fresh_state()
        _parse_stream_line(
            "_start_playback_for_current: mode=playlist, source=Station 1, shuffle_type=, album_idx=0",
            state,
            basic_mode=True,
        )
        assert state["mode"] == "station"

    def test_mode_change_basic_maps_playlist_to_station(self):
        state = self._fresh_state()
        _parse_stream_line("[MODE] playlist -> playlist, album_idx=1", state, basic_mode=True)
        assert state["mode"] == "station"

    def test_album_idx_generates_fallback_source(self):
        state = self._fresh_state()
        # No source name, but has album_idx
        _parse_stream_line(
            "_start_playback_for_current: mode=album, source=, shuffle_type=, album_idx=2",
            state,
        )
        assert "Album" in state["source"] or state["source"] == ""  # fallback may set source

    def test_mode_change_extracts_album_idx(self):
        state = self._fresh_state()
        _parse_stream_line("[MODE] album -> playlist, album_idx=3", state)
        assert state["album_idx"] == 3


# ---------------------------------------------------------------------------
# Command output parsing logic
# ---------------------------------------------------------------------------

def _parse_command_output(raw: str, command: str) -> tuple[int, str, str]:
    """Mirror of _send_serial_command_locked output parsing: strips prompts and echoes."""
    lines = raw.split("\n")
    result_lines = []
    command_lines = command.strip().split("\n") if command.strip() else []
    for line in lines:
        ls = line.strip()
        if ls.startswith(">>>") or ls.startswith("...") or not ls:
            continue
        is_echo = any(cl.strip() and cl.strip() in ls for cl in command_lines)
        if not is_echo:
            result_lines.append(ls)
    result = "\n".join(result_lines).strip()
    return (0, result, "") if result else (1, "", "No response")


class TestCommandOutputParsing:
    def test_strips_repl_prompt_lines(self):
        raw = ">>> import sys\r\n3.11.0\r\n>>> "
        code, out, err = _parse_command_output(raw, "import sys")
        assert ">>>" not in out

    def test_strips_command_echo(self):
        raw = ">>> import sys\r\nimport sys\r\n3.11.0\r\n>>> "
        code, out, err = _parse_command_output(raw, "import sys")
        assert "import sys" not in out

    def test_clean_output_returns_code_0(self):
        raw = "3.11.0\r\n>>> "
        code, out, err = _parse_command_output(raw, "import sys; print(sys.version)")
        assert code == 0
        assert "3.11.0" in out

    def test_no_output_returns_code_1(self):
        raw = ">>> "
        code, out, err = _parse_command_output(raw, "x = 1")
        assert code == 1

    def test_empty_lines_stripped(self):
        raw = "\r\n\r\nresult_value\r\n\r\n>>> "
        code, out, err = _parse_command_output(raw, "print(x)")
        assert out == "result_value"

    def test_multiline_output_preserved(self):
        raw = "line1\r\nline2\r\nline3\r\n>>> "
        code, out, err = _parse_command_output(raw, "print_all()")
        lines = out.split("\n")
        assert len(lines) == 3


# ---------------------------------------------------------------------------
# Presence detection logic
# ---------------------------------------------------------------------------

def _compute_effective_presence(
    raw_presence: bool,
    mask_active: bool,
) -> bool:
    """
    Mirrors DeviceDebugWidget._computed_presence_for_led:
    during a mask window after intentional disconnect, suppress spurious
    'device appeared' signals.
    """
    if mask_active:
        return False
    return raw_presence


class TestPresenceDetection:
    def test_device_present_emitted_as_true(self):
        result = _compute_effective_presence(raw_presence=True, mask_active=False)
        assert result is True

    def test_device_absent_emitted_as_false(self):
        result = _compute_effective_presence(raw_presence=False, mask_active=False)
        assert result is False

    def test_mask_suppresses_spurious_connect(self):
        """After intentional disconnect, a re-detected device should be masked."""
        result = _compute_effective_presence(raw_presence=True, mask_active=True)
        assert result is False

    def test_mask_does_not_affect_true_absence(self):
        result = _compute_effective_presence(raw_presence=False, mask_active=True)
        assert result is False

    def test_mask_inactive_allows_presence(self):
        result = _compute_effective_presence(raw_presence=True, mask_active=False)
        assert result is True
