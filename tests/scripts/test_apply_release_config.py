from __future__ import annotations

import json
from pathlib import Path

from scripts.apply_release_config import apply_release_channel


def test_stable_channel_restores_example_template(tmp_path: Path):
    (tmp_path / "release_config.example.json").write_text(
        json.dumps({"update": {"enabled": True, "channel": "stable"}}),
        encoding="utf-8",
    )
    (tmp_path / "release_config.dev.json").write_text(
        json.dumps({"update": {"enabled": False, "channel": "dev"}}),
        encoding="utf-8",
    )
    dest = tmp_path / "release_config.json"
    dest.write_text(json.dumps({"update": {"enabled": False, "channel": "dev"}}), encoding="utf-8")

    apply_release_channel(tmp_path, "stable")

    data = json.loads(dest.read_text(encoding="utf-8"))
    assert data["update"]["channel"] == "stable"
    assert data["update"]["enabled"] is True


def test_dev_channel_copies_dev_template(tmp_path: Path):
    (tmp_path / "release_config.example.json").write_text("{}", encoding="utf-8")
    (tmp_path / "release_config.dev.json").write_text(
        json.dumps({"update": {"enabled": False, "channel": "dev"}}),
        encoding="utf-8",
    )
    dest = tmp_path / "release_config.json"
    dest.write_text("{}", encoding="utf-8")

    apply_release_channel(tmp_path, "dev")

    data = json.loads(dest.read_text(encoding="utf-8"))
    assert data["update"]["channel"] == "dev"


def test_test_channel_copies_test_template(tmp_path: Path):
    (tmp_path / "release_config.test.json").write_text(
        json.dumps(
            {
                "update": {
                    "enabled": True,
                    "channel": "test",
                    "tag_suffix": "-upgrade-test",
                }
            }
        ),
        encoding="utf-8",
    )
    dest = tmp_path / "release_config.json"
    dest.write_text("{}", encoding="utf-8")

    apply_release_channel(tmp_path, "test")

    data = json.loads(dest.read_text(encoding="utf-8"))
    assert data["update"]["channel"] == "test"
    assert data["update"]["tag_suffix"] == "-upgrade-test"


def test_invalid_channel_falls_back_to_dev_template(tmp_path: Path):
    (tmp_path / "release_config.example.json").write_text(
        json.dumps({"update": {"enabled": True, "channel": "stable"}}),
        encoding="utf-8",
    )
    (tmp_path / "release_config.dev.json").write_text(
        json.dumps({"update": {"enabled": False, "channel": "dev"}}),
        encoding="utf-8",
    )
    dest = tmp_path / "release_config.json"
    dest.write_text(json.dumps({"update": {"enabled": True, "channel": "stable"}}), encoding="utf-8")

    apply_release_channel(tmp_path, "nightly")

    data = json.loads(dest.read_text(encoding="utf-8"))
    assert data["update"]["channel"] == "dev"
    assert data["update"]["enabled"] is False
