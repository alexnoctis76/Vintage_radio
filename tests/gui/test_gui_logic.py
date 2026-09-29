"""Tests for GUI module helper logic.

These tests focus on pure logic that can be validated without rendering actual
Qt widgets. We test _volume_name_key normalization, undo/redo stack mechanics,
and other helper functions. For dialog tests requiring Qt we use
QT_QPA_PLATFORM=offscreen (set via pytest.ini or environment).
"""

from __future__ import annotations

import unicodedata
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# _volume_name_key normalization (pure Python, no Qt)
# ---------------------------------------------------------------------------

def _volume_name_key(name):
    """Mirror of gui.radio_manager._volume_name_key."""
    if not name:
        return ""
    return unicodedata.normalize("NFC", str(name).strip()).upper()


class TestVolumeNameKey:
    def test_empty_string_returns_empty(self):
        assert _volume_name_key("") == ""

    def test_none_returns_empty(self):
        assert _volume_name_key(None) == ""

    def test_basic_string_uppercased(self):
        assert _volume_name_key("hello") == "HELLO"

    def test_strips_leading_and_trailing_spaces(self):
        assert _volume_name_key("  hello  ") == "HELLO"

    def test_unicode_nfd_to_nfc_normalized(self):
        """NFD-encoded 'ü' should normalize to NFC 'Ü'."""
        nfd_u = "u\u0308"  # u + combining diaeresis = ü in NFD
        result = _volume_name_key(nfd_u)
        nfc_u = unicodedata.normalize("NFC", "ü").upper()
        assert result == nfc_u

    def test_mixed_case_uppercased(self):
        assert _volume_name_key("MyAlbum") == "MYALBUM"

    def test_numbers_unchanged(self):
        assert _volume_name_key("album123") == "ALBUM123"

    def test_same_name_different_encoding_equal(self):
        """Two strings that differ only in Unicode normalization compare equal after key."""
        nfc = unicodedata.normalize("NFC", "Ára bátur")
        nfd = unicodedata.normalize("NFD", "Ára bátur")
        assert _volume_name_key(nfc) == _volume_name_key(nfd)


# ---------------------------------------------------------------------------
# Undo/redo stack mechanics (pure Python, mirrors MainWindow behaviour)
# ---------------------------------------------------------------------------

class UndoRedoStack:
    """Minimal replication of MainWindow undo/redo stack logic for unit testing."""

    def __init__(self):
        self._undo_stack = []
        self._redo_stack = []

    def push_undo(self, action: dict) -> None:
        self._undo_stack.append(action)
        self._redo_stack.clear()

    def undo(self):
        if not self._undo_stack:
            return None
        action = self._undo_stack.pop()
        self._redo_stack.append(action)
        return action

    def redo(self):
        if not self._redo_stack:
            return None
        action = self._redo_stack.pop()
        self._undo_stack.append(action)
        return action


class TestUndoRedoStack:
    def test_push_then_undo_returns_action(self):
        stack = UndoRedoStack()
        action = {"type": "test", "data": 42}
        stack.push_undo(action)
        result = stack.undo()
        assert result == action

    def test_undo_puts_action_on_redo_stack(self):
        stack = UndoRedoStack()
        action = {"type": "test", "data": 1}
        stack.push_undo(action)
        stack.undo()
        result = stack.redo()
        assert result == action

    def test_undo_empty_stack_returns_none(self):
        stack = UndoRedoStack()
        assert stack.undo() is None

    def test_redo_empty_stack_returns_none(self):
        stack = UndoRedoStack()
        assert stack.redo() is None

    def test_push_new_action_clears_redo_stack(self):
        stack = UndoRedoStack()
        stack.push_undo({"type": "a"})
        stack.undo()
        # There should be something on redo now
        assert len(stack._redo_stack) == 1
        # Pushing a NEW action must clear redo
        stack.push_undo({"type": "b"})
        assert len(stack._redo_stack) == 0

    def test_multiple_undos_in_sequence(self):
        stack = UndoRedoStack()
        for i in range(3):
            stack.push_undo({"type": f"action_{i}"})
        # Undo three times - should get them in LIFO order
        assert stack.undo()["type"] == "action_2"
        assert stack.undo()["type"] == "action_1"
        assert stack.undo()["type"] == "action_0"
        assert stack.undo() is None

    def test_undo_redo_undo_cycle(self):
        stack = UndoRedoStack()
        action = {"type": "cycle"}
        stack.push_undo(action)
        stack.undo()   # -> redo
        stack.redo()   # -> undo
        result = stack.undo()  # pop from undo again
        assert result == action


class TestBootselDetection:
    def test_sd_manager_detects_rpi_rp2_label(self, monkeypatch):
        from gui.sd_manager import SDManager

        monkeypatch.setattr(
            SDManager,
            "detect_sd_roots",
            staticmethod(lambda: [(Path("/Volumes/RPI-RP2"), "RPI-RP2")]),
        )
        assert SDManager.is_rp2040_bootsel_present() is True

    def test_sd_manager_absent_when_no_bootsel_volume(self, monkeypatch):
        from gui.sd_manager import SDManager

        monkeypatch.setattr(
            SDManager,
            "detect_sd_roots",
            staticmethod(lambda: [(Path("/Volumes/USB"), "USB")]),
        )
        assert SDManager.is_rp2040_bootsel_present() is False


# ---------------------------------------------------------------------------
# _volume_name_key imported from actual module (integration check)
# ---------------------------------------------------------------------------

class TestVolumeNameKeyImport:
    def test_module_function_matches_reference_impl(self):
        from gui.radio_manager import _volume_name_key as real_fn
        test_cases = [
            "",
            "hello",
            "  spacey  ",
            "Ára bátur",
            "Album 123",
        ]
        for case in test_cases:
            assert real_fn(case) == _volume_name_key(case), f"Mismatch for: {case!r}"
