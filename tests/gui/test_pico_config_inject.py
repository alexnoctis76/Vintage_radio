"""Tests for post-flash Pico config injection helpers."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from gui.pico_config_inject import (
    build_injections_from_entry,
    inject_pico_config_files,
    local_file_fingerprint,
    needs_config_inject_confirm,
    validate_config_local_file,
)


def test_build_injections_skips_when_config_not_supported(tmp_path):
    cfg = tmp_path / "config.py"
    cfg.write_text("App = object()\n", encoding="utf-8")
    entry = {
        "kind": "uf2",
        "config_path": str(cfg),
        "inject_config": True,
        "supports_config": False,
    }
    assert build_injections_from_entry(entry) == []


def test_build_injections_single_file(tmp_path):
    cfg = tmp_path / "config.py"
    cfg.write_text("App = object()\n", encoding="utf-8")
    entry = {
        "kind": "micropython",
        "config_path": str(cfg),
        "config_remote": "config.py",
        "inject_config": True,
    }
    pairs = build_injections_from_entry(entry)
    assert len(pairs) == 1
    assert pairs[0][0] == cfg
    assert pairs[0][1] == "config.py"


def test_build_injections_folder_with_manifest(tmp_path):
    folder = tmp_path / "bundle"
    folder.mkdir()
    (folder / "settings.json").write_text("{}", encoding="utf-8")
    (folder / "pico_inject_manifest.json").write_text(
        json.dumps(
            {
                "files": [
                    {"local": "settings.json", "remote": "VintageRadio/settings.json"},
                ]
            }
        ),
        encoding="utf-8",
    )
    entry = {"kind": "folder", "config_path": str(folder), "inject_config": True}
    pairs = build_injections_from_entry(entry)
    assert len(pairs) == 1
    assert pairs[0][1] == "VintageRadio/settings.json"


def test_validate_blocks_same_file_as_uf2(tmp_path):
    uf2 = tmp_path / "fw.uf2"
    uf2.write_bytes(b"uf2")
    err = validate_config_local_file(uf2, uf2_path=uf2)
    assert err is not None
    assert "same" in err.lower()


def test_validate_python_syntax_error(tmp_path):
    bad = tmp_path / "config.py"
    bad.write_text("def oops(\n", encoding="utf-8")
    err = validate_config_local_file(bad)
    assert err is not None
    assert "syntax" in err.lower()


def test_needs_confirm_for_exe(tmp_path):
    exe = tmp_path / "tool.exe"
    exe.write_bytes(b"MZ")
    need, reason = needs_config_inject_confirm(exe)
    assert need is True
    assert reason


def test_inject_pico_config_files_calls_mpremote(tmp_path):
    cfg = tmp_path / "config.py"
    cfg.write_text("X = 1\n", encoding="utf-8")
    copied: list[tuple[str, str]] = []

    def run_cp(local_fp: Path, remote: str) -> bool:
        copied.append((local_fp.name, remote))
        return True

    inject_pico_config_files(
        ["mpremote"],
        [(cfg, "config.py")],
        wait_serial_ready=lambda *_a, **_k: None,
        run_mpremote_cp=run_cp,
    )
    assert copied == [("config.py", ":config.py")]


def test_inject_passes_mpremote_cmd_positionally_to_wait(tmp_path):
    cfg = tmp_path / "config.py"
    cfg.write_text("X = 1\n", encoding="utf-8")
    seen: list = []

    def wait_serial_ready(mpremote_cmd, **kwargs):
        seen.append((list(mpremote_cmd), kwargs.get("after_uf2_flash")))
        return None

    inject_pico_config_files(
        ["python", "-m", "mpremote"],
        [(cfg, "config.py")],
        wait_serial_ready=wait_serial_ready,
        run_mpremote_cp=lambda *_a, **_k: True,
    )
    assert seen == [(["python", "-m", "mpremote"], True)]


def test_local_file_fingerprint_stable(tmp_path):
    fp = tmp_path / "config.py"
    fp.write_text("EQUALIZER = 5\n", encoding="utf-8")
    size, digest = local_file_fingerprint(fp)
    assert size == fp.stat().st_size
    assert len(digest) == 64


def test_inject_fails_on_invalid_python(tmp_path):
    bad = tmp_path / "config.py"
    bad.write_text("syntax (\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="syntax"):
        inject_pico_config_files(
            ["mpremote"],
            [(bad, "config.py")],
            wait_serial_ready=lambda *_a, **_k: None,
            run_mpremote_cp=lambda *_a, **_k: True,
        )
