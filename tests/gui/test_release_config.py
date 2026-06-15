"""Tests for release_config.json visibility flags."""

from __future__ import annotations

import json

from gui.release_config import (
    ZBVR_FIRMWARE_ENTRY_ID,
    is_official_firmware_visible,
    reload_release_config,
)


def test_zbvr_hidden_when_config_false(tmp_path, monkeypatch):
    cfg = tmp_path / "release_config.json"
    cfg.write_text(
        json.dumps({"official_firmware": {ZBVR_FIRMWARE_ENTRY_ID: False}}),
        encoding="utf-8",
    )
    monkeypatch.setattr("gui.release_config.project_root", lambda: tmp_path)
    reload_release_config()

    assert is_official_firmware_visible(ZBVR_FIRMWARE_ENTRY_ID) is False
    assert is_official_firmware_visible("v1.1_stable") is True


def test_zbvr_visible_when_config_true(tmp_path, monkeypatch):
    cfg = tmp_path / "release_config.json"
    cfg.write_text(
        json.dumps({"official_firmware": {ZBVR_FIRMWARE_ENTRY_ID: True}}),
        encoding="utf-8",
    )
    monkeypatch.setattr("gui.release_config.project_root", lambda: tmp_path)
    reload_release_config()

    assert is_official_firmware_visible(ZBVR_FIRMWARE_ENTRY_ID) is True


def test_missing_key_uses_default(tmp_path, monkeypatch):
    cfg = tmp_path / "release_config.json"
    cfg.write_text(json.dumps({"official_firmware": {}}), encoding="utf-8")
    monkeypatch.setattr("gui.release_config.project_root", lambda: tmp_path)
    reload_release_config()

    assert is_official_firmware_visible(ZBVR_FIRMWARE_ENTRY_ID) is True
