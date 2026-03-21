"""
Tests for pin configuration loader, board profiles, pin validation,
database profile CRUD, and config generation.
"""

from __future__ import annotations

import json
import os
import sqlite3
import tempfile
from pathlib import Path
from typing import Any, Dict

import pytest


# ---------------------------------------------------------------------------
#  pin_config_loader tests
# ---------------------------------------------------------------------------


class TestPinConfigLoader:
    """Tests for firmware/pin_config_loader.py."""

    def test_load_defaults_when_no_file(self, tmp_path, monkeypatch):
        """When pin_config.json is missing, loader returns hardcoded defaults."""
        import importlib
        import firmware.pin_config_loader as loader_mod

        monkeypatch.setattr(loader_mod, "_cached_config", None)
        monkeypatch.setattr(
            loader_mod, "_SEARCH_PATHS_CPYTHON", [str(tmp_path / "nonexistent.json")]
        )
        cfg = loader_mod.load_pin_config(force_reload=True)
        assert cfg["board"] == "raspberry_pi_linux"
        assert "pins" in cfg

    def test_load_from_file(self, tmp_path, monkeypatch):
        """Loader reads pin_config.json when it exists."""
        import firmware.pin_config_loader as loader_mod

        monkeypatch.setattr(loader_mod, "_cached_config", None)

        cfg_data = {
            "board": "test_board",
            "audio_module": "dfplayer",
            "pins": {"uart_tx": 99, "uart_rx": 98},
        }
        cfg_path = tmp_path / "pin_config.json"
        cfg_path.write_text(json.dumps(cfg_data))

        monkeypatch.setattr(loader_mod, "_SEARCH_PATHS_CPYTHON", [str(cfg_path)])
        result = loader_mod.load_pin_config(force_reload=True)
        assert result["board"] == "test_board"
        assert result["pins"]["uart_tx"] == 99

    def test_caching(self, tmp_path, monkeypatch):
        """Second call returns cached config without re-reading file."""
        import firmware.pin_config_loader as loader_mod

        monkeypatch.setattr(loader_mod, "_cached_config", None)
        monkeypatch.setattr(
            loader_mod, "_SEARCH_PATHS_CPYTHON", [str(tmp_path / "nonexistent.json")]
        )

        cfg1 = loader_mod.load_pin_config(force_reload=True)
        cfg1["_test_marker"] = True
        cfg2 = loader_mod.load_pin_config()
        assert cfg2.get("_test_marker") is True

    def test_force_reload_bypasses_cache(self, tmp_path, monkeypatch):
        """force_reload=True re-reads from disk."""
        import firmware.pin_config_loader as loader_mod

        monkeypatch.setattr(loader_mod, "_cached_config", {"old": True})
        monkeypatch.setattr(
            loader_mod, "_SEARCH_PATHS_CPYTHON", [str(tmp_path / "nonexistent.json")]
        )

        cfg = loader_mod.load_pin_config(force_reload=True)
        assert "old" not in cfg

    def test_get_pin_helper(self, monkeypatch):
        import firmware.pin_config_loader as loader_mod

        monkeypatch.setattr(
            loader_mod, "_cached_config", {"pins": {"button": 42}}
        )
        assert loader_mod.get_pin("button") == 42
        assert loader_mod.get_pin("nonexistent", 99) == 99

    def test_get_spi_config(self, monkeypatch):
        import firmware.pin_config_loader as loader_mod

        monkeypatch.setattr(
            loader_mod,
            "_cached_config",
            {
                "spi": {"bus": 1, "sck": 10},
                "spi_alt": {"bus": 0, "sck": 18},
            },
        )
        assert loader_mod.get_spi_config()["sck"] == 10
        assert loader_mod.get_spi_config(alt=True)["sck"] == 18

    def test_get_dfplayer_config(self, monkeypatch):
        import firmware.pin_config_loader as loader_mod

        monkeypatch.setattr(
            loader_mod,
            "_cached_config",
            {"dfplayer": {"max_volume": 28, "uart_baud": 9600}},
        )
        df = loader_mod.get_dfplayer_config()
        assert df["max_volume"] == 28
        assert df["uart_baud"] == 9600

    def test_malformed_json_falls_back(self, tmp_path, monkeypatch):
        """If file contains invalid JSON, loader falls back to defaults."""
        import firmware.pin_config_loader as loader_mod

        monkeypatch.setattr(loader_mod, "_cached_config", None)
        bad_file = tmp_path / "pin_config.json"
        bad_file.write_text("{not valid json}")
        monkeypatch.setattr(loader_mod, "_SEARCH_PATHS_CPYTHON", [str(bad_file)])

        cfg = loader_mod.load_pin_config(force_reload=True)
        assert "board" in cfg


# ---------------------------------------------------------------------------
#  board_profiles tests
# ---------------------------------------------------------------------------


class TestBoardProfiles:
    """Tests for gui/board_profiles.py."""

    def test_all_profiles_have_required_fields(self):
        from gui.board_profiles import BOARD_PROFILES

        for bp in BOARD_PROFILES:
            assert bp.id, f"Profile missing id: {bp}"
            assert bp.name, f"Profile missing name: {bp.id}"
            assert bp.mcu, f"Profile missing mcu: {bp.id}"
            assert bp.platform in ("micropython", "cpython"), f"Invalid platform: {bp.id}"
            lo, hi = bp.gpio_range
            assert lo <= hi, f"Invalid gpio_range: {bp.id}"
            assert isinstance(bp.default_pin_config, dict), f"default_pin_config not dict: {bp.id}"

    def test_profile_lookup_by_id(self):
        from gui.board_profiles import get_board_profile, BOARD_PROFILES

        for bp in BOARD_PROFILES:
            found = get_board_profile(bp.id)
            assert found is bp

    def test_unknown_id_returns_none(self):
        from gui.board_profiles import get_board_profile

        assert get_board_profile("nonexistent_board_xyz") is None

    def test_default_config_json_is_valid(self):
        from gui.board_profiles import BOARD_PROFILES

        for bp in BOARD_PROFILES:
            cfg_json = bp.default_config_json()
            parsed = json.loads(cfg_json)
            assert isinstance(parsed, dict)
            assert "board" in parsed

    def test_valid_gpio_pins_excludes_restricted(self):
        from gui.board_profiles import PICO

        valid = PICO.valid_gpio_pins()
        for restricted_pin in PICO.restricted_pins:
            assert restricted_pin not in valid

    def test_pico_defaults_match_original_firmware(self):
        from gui.board_profiles import PICO

        pins = PICO.default_pin_config["pins"]
        assert pins["uart_tx"] == 0
        assert pins["uart_rx"] == 1
        assert pins["button"] == 2
        assert pins["audio_pwm"] == 3
        assert pins["neopixel"] == 16

    def test_pi_linux_has_no_spi(self):
        from gui.board_profiles import PI_LINUX

        assert not PI_LINUX.supports_sd_spi
        assert not PI_LINUX.supports_neopixel

    def test_esp32_restricted_pins_include_flash(self):
        from gui.board_profiles import ESP32

        for pin in (6, 7, 8, 9, 10, 11):
            assert pin in ESP32.restricted_pins


# ---------------------------------------------------------------------------
#  Database profile CRUD tests
# ---------------------------------------------------------------------------


@pytest.fixture
def db_with_profiles(tmp_path):
    """Create a DatabaseManager with the profiles table initialized."""
    from gui.database import DatabaseManager

    db_path = tmp_path / "test.db"
    db = DatabaseManager(db_path)
    return db


class TestDatabaseProfileCRUD:
    """Tests for device_profiles table CRUD operations."""

    def test_default_profile_created_on_init(self, db_with_profiles):
        db = db_with_profiles
        profiles = db.list_device_profiles()
        assert len(profiles) >= 1
        default = [p for p in profiles if p["is_default"]]
        assert len(default) == 1
        assert default[0]["name"] == "Default (Pico)"

    def test_active_profile_set_on_init(self, db_with_profiles):
        db = db_with_profiles
        active = db.get_active_profile()
        assert active is not None
        assert active["is_default"] == 1

    def test_create_profile(self, db_with_profiles):
        db = db_with_profiles
        pid = db.create_device_profile(
            name="Test Profile",
            board_id="esp32",
            pin_config_json='{"board": "esp32"}',
            notes="My test notes",
        )
        assert pid is not None
        p = db.get_device_profile(pid)
        assert p["name"] == "Test Profile"
        assert p["board_id"] == "esp32"
        assert p["notes"] == "My test notes"

    def test_update_profile(self, db_with_profiles):
        db = db_with_profiles
        pid = db.create_device_profile("Edit Me", "raspberry_pi_pico", "{}")
        db.update_device_profile(pid, name="Edited", notes="Updated notes")
        p = db.get_device_profile(pid)
        assert p["name"] == "Edited"
        assert p["notes"] == "Updated notes"

    def test_update_ignores_invalid_fields(self, db_with_profiles):
        db = db_with_profiles
        active = db.get_active_profile()
        db.update_device_profile(active["id"], invalid_field="should be ignored")
        p = db.get_device_profile(active["id"])
        assert p is not None

    def test_delete_profile(self, db_with_profiles):
        db = db_with_profiles
        pid = db.create_device_profile("Delete Me", "esp32", "{}")
        assert db.delete_device_profile(pid) is True
        assert db.get_device_profile(pid) is None

    def test_cannot_delete_default_profile(self, db_with_profiles):
        db = db_with_profiles
        active = db.get_active_profile()
        assert active["is_default"] == 1
        assert db.delete_device_profile(active["id"]) is False
        assert db.get_device_profile(active["id"]) is not None

    def test_cannot_delete_last_profile(self, db_with_profiles):
        """Even non-default profiles can't be deleted if they're the only one."""
        db = db_with_profiles
        profiles = db.list_device_profiles()
        if len(profiles) == 1:
            assert db.delete_device_profile(profiles[0]["id"]) is False

    def test_duplicate_profile(self, db_with_profiles):
        db = db_with_profiles
        active = db.get_active_profile()
        new_id = db.duplicate_device_profile(active["id"], "Copy of Default")
        copy = db.get_device_profile(new_id)
        assert copy["name"] == "Copy of Default"
        assert copy["board_id"] == active["board_id"]
        assert copy["pin_config_json"] == active["pin_config_json"]
        assert copy["is_default"] == 0

    def test_set_active_profile(self, db_with_profiles):
        db = db_with_profiles
        pid = db.create_device_profile("New Active", "esp32", "{}")
        db.set_active_profile(pid)
        active = db.get_active_profile()
        assert active["id"] == pid

    def test_delete_active_switches_to_first(self, db_with_profiles):
        db = db_with_profiles
        pid1 = db.create_device_profile("P1", "esp32", "{}")
        pid2 = db.create_device_profile("P2", "esp32", "{}")
        db.set_active_profile(pid2)
        db.delete_device_profile(pid2)
        active = db.get_active_profile()
        assert active is not None
        assert active["id"] != pid2

    def test_list_profiles_ordered(self, db_with_profiles):
        db = db_with_profiles
        db.create_device_profile("Zebra", "esp32", "{}")
        db.create_device_profile("Alpha", "esp32", "{}")
        profiles = db.list_device_profiles()
        assert profiles[0]["is_default"] == 1
        names = [p["name"] for p in profiles[1:]]
        assert names == sorted(names, key=str.lower)


# ---------------------------------------------------------------------------
#  Pin validation logic tests
# ---------------------------------------------------------------------------


class TestPinValidation:
    """Tests for pin conflict detection and range validation logic.

    Uses a lightweight mock of PinConfigWidget to avoid needing a QApplication.
    """

    class _FakeEditor:
        """Minimal stand-in that exercises the validation methods from PinConfigDialog."""

        def __init__(self, board_profile, config):
            self._board_profile = board_profile
            self._config = config

        def _get_pin_description(self, section, key, pin):
            from gui.pin_config_editor import PinConfigDialog
            return PinConfigDialog._get_pin_description(self, section, key, pin)

        def _check_pin_conflict(self, section, key, pin):
            from gui.pin_config_editor import PinConfigDialog
            return PinConfigDialog._check_pin_conflict(self, section, key, pin)

    @pytest.fixture
    def editor(self):
        from gui.board_profiles import get_board_profile
        bp = get_board_profile("raspberry_pi_pico")
        return self._FakeEditor(bp, {})

    def test_no_conflict_with_unique_pins(self, editor):
        editor._config = {"pins": {"uart_tx": 0, "uart_rx": 1, "button": 2}}
        result = editor._check_pin_conflict("pins", "uart_tx", 0)
        assert result == ""

    def test_conflict_detected_duplicate_pin(self, editor):
        editor._config = {"pins": {"uart_tx": 0, "uart_rx": 0}}
        result = editor._check_pin_conflict("pins", "uart_tx", 0)
        assert "CONFLICT" in result

    def test_conflict_across_sections(self, editor):
        editor._config = {"pins": {"uart_tx": 10}, "spi": {"sck": 10}}
        result = editor._check_pin_conflict("pins", "uart_tx", 10)
        assert "CONFLICT" in result

    def test_restricted_pin_warning(self, editor):
        desc = editor._get_pin_description("pins", "button", 25)
        assert "WARNING" in desc

    def test_out_of_range_warning(self, editor):
        desc = editor._get_pin_description("pins", "button", 50)
        assert "WARNING" in desc
        assert "range" in desc.lower()

    def test_valid_pin_no_warning(self, editor):
        desc = editor._get_pin_description("pins", "button", 2)
        assert desc == ""

    def test_bus_field_skipped_in_conflict_check(self, editor):
        editor._config = {"spi": {"bus": 1, "sck": 10}, "spi_alt": {"bus": 1, "sck": 18}}
        result = editor._check_pin_conflict("spi", "bus", 1)
        assert result == ""

    def test_spi_and_spi_alt_do_not_conflict(self, editor):
        """spi and spi_alt are mutually exclusive alternatives."""
        editor._config = {"spi": {"sck": 10}, "spi_alt": {"miso": 10}}
        result = editor._check_pin_conflict("spi", "sck", 10)
        assert result == ""

    def test_spi_alt_does_not_conflict_with_pins(self, editor):
        """spi_alt is a fallback bus, so it doesn't conflict with the pins section."""
        editor._config = {"pins": {"neopixel": 18}, "spi_alt": {"sck": 18}}
        result = editor._check_pin_conflict("spi_alt", "sck", 18)
        assert result == ""

    def test_spi_alt_internal_conflict(self, editor):
        """Duplicate pins within spi_alt itself should still be flagged."""
        editor._config = {"spi_alt": {"sck": 18, "mosi": 18}}
        result = editor._check_pin_conflict("spi_alt", "sck", 18)
        assert "CONFLICT" in result

    def test_default_pico_config_no_false_conflicts(self, editor):
        """The default Pico config should have no conflicts (neopixel=16, spi_alt.miso=16 are OK)."""
        from gui.board_profiles import PICO
        import copy
        editor._config = copy.deepcopy(PICO.default_pin_config)
        for section in ("pins", "spi", "spi_alt"):
            sub = editor._config.get(section, {})
            for key, val in sub.items():
                if key == "bus":
                    continue
                conflict = editor._check_pin_conflict(section, key, val)
                assert conflict == "", f"False conflict for {section}.{key}={val}: {conflict}"

    def test_dfplayer_fields_skip_pin_validation(self, editor):
        """DFPlayer settings like max_volume and uart_baud should not get GPIO warnings."""
        desc = editor._get_pin_description("dfplayer", "uart_baud", 9600)
        assert desc == ""
        desc = editor._get_pin_description("dfplayer", "max_volume", 28)
        assert desc == ""

    def test_dfplayer_fields_skip_conflict_check(self, editor):
        """DFPlayer settings should not trigger pin conflict warnings."""
        editor._config = {"pins": {"neopixel": 28}, "dfplayer": {"max_volume": 28}}
        result = editor._check_pin_conflict("dfplayer", "max_volume", 28)
        assert result == ""


# ---------------------------------------------------------------------------
#  Config generation tests
# ---------------------------------------------------------------------------


class TestConfigGeneration:
    """Test that config JSON round-trips correctly."""

    def test_default_config_roundtrips(self):
        from gui.board_profiles import PICO

        json_str = PICO.default_config_json()
        parsed = json.loads(json_str)
        assert parsed["board"] == "raspberry_pi_pico"
        assert parsed["pins"]["uart_tx"] == 0
        assert parsed["spi"]["bus"] == 1

    def test_profile_pin_config_matches_loader_format(self):
        """Ensure the profile's pin_config_json matches what pin_config_loader expects."""
        from gui.board_profiles import PICO

        cfg = json.loads(PICO.default_config_json())
        required_pin_keys = {"uart_tx", "uart_rx", "button", "audio_pwm", "power_sense", "busy", "neopixel"}
        assert required_pin_keys.issubset(set(cfg["pins"].keys()))

    def test_all_boards_produce_valid_json(self):
        from gui.board_profiles import BOARD_PROFILES

        for bp in BOARD_PROFILES:
            cfg = json.loads(bp.default_config_json())
            assert "board" in cfg
            assert "pins" in cfg
