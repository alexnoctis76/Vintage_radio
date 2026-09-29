"""Conductor playback state policy when radio_catalog.json is loaded."""

from __future__ import annotations

import importlib.util
from pathlib import Path

from tests.conftest import MockBasicHardware

ROOT = Path(__file__).resolve().parents[2]
CONDUCTOR_CORE = ROOT / "firmware" / "conductor" / "radio_core.py"


def _load_conductor_radio_core():
    spec = importlib.util.spec_from_file_location(
        "conductor_radio_core_catalog_state", CONDUCTOR_CORE
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _CatalogHardware(MockBasicHardware):
    def __init__(self, catalog):
        super().__init__(stations=[])
        self._catalog = catalog

    def get_radio_catalog(self):
        return self._catalog

    def get_commercials_config(self):
        return {"enabled": False, "interval": 5, "mode": "inline", "folder": 99}


def _sample_catalog():
    return {
        "version": 1,
        "commercials": {"enabled": False, "mode": "inline", "interval": 5, "folder": 99},
        "stations": [{"folder": 1, "tracks": [{"t": 1, "ad": 0}]}],
    }


def test_conductor_with_catalog_skips_sd_signature_helpers():
    core_mod = _load_conductor_radio_core()
    hw = _CatalogHardware(_sample_catalog())
    rc = core_mod.RadioCore(hw, basic_mode=True)

    flags = {"reset": False, "write": False, "cold": False}

    rc._basic_maybe_reset_persisted_state_if_sd_changed = lambda: flags.__setitem__(
        "reset", True
    )
    rc._basic_write_sd_signature_file = lambda: flags.__setitem__("write", True)
    rc._basic_clear_persisted_state_on_cold_boot = lambda: flags.__setitem__(
        "cold", True
    )

    rc.init(skip_initial_playback=True)

    assert getattr(rc, "_catalog_loaded", False) is True
    assert flags["reset"] is False
    assert flags["write"] is False
    assert flags["cold"] is True


def test_basic_radio_core_still_runs_sd_signature_helpers():
    from radio_core import RadioCore

    hw = MockBasicHardware()
    rc = RadioCore(hw, basic_mode=True)
    flags = {"reset": False, "write": False, "cold": False}

    rc._basic_maybe_reset_persisted_state_if_sd_changed = lambda: flags.__setitem__(
        "reset", True
    )
    rc._basic_write_sd_signature_file = lambda: flags.__setitem__("write", True)
    rc._basic_clear_persisted_state_on_cold_boot = lambda: flags.__setitem__(
        "cold", True
    )

    rc.init(skip_initial_playback=True)

    assert flags["reset"] is True
    assert flags["write"] is True
    assert flags["cold"] is True


def test_conductor_without_catalog_keeps_sd_signature_helpers():
    core_mod = _load_conductor_radio_core()
    hw = MockBasicHardware()
    rc = core_mod.RadioCore(hw, basic_mode=True)

    flags = {"reset": False, "write": False, "cold": False}

    rc._basic_maybe_reset_persisted_state_if_sd_changed = lambda: flags.__setitem__(
        "reset", True
    )
    rc._basic_write_sd_signature_file = lambda: flags.__setitem__("write", True)
    rc._basic_clear_persisted_state_on_cold_boot = lambda: flags.__setitem__(
        "cold", True
    )

    rc.init(skip_initial_playback=True)

    assert getattr(rc, "_catalog_loaded", False) is False
    assert flags["reset"] is True
    assert flags["write"] is True
    assert flags["cold"] is True
