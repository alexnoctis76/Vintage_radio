"""Tests for gui.resource_paths."""

import sys
import types
from pathlib import Path
from unittest import mock

import pytest

from gui import resource_paths


class TestProjectRoot:
    def test_returns_parent_of_gui(self):
        root = resource_paths.project_root()
        assert (root / "gui").is_dir()
        assert (root / "firmware" / "radio_core.py").exists()

    def test_frozen_mode(self, tmp_path):
        with mock.patch.object(sys, "frozen", True, create=True), \
             mock.patch.object(sys, "_MEIPASS", str(tmp_path), create=True):
            assert resource_paths.project_root() == tmp_path


class TestGuiDir:
    def test_source_mode(self):
        gui = resource_paths.gui_dir()
        assert gui.name == "gui"
        assert gui.is_dir()

    def test_frozen_mode(self, tmp_path):
        with mock.patch.object(sys, "frozen", True, create=True), \
             mock.patch.object(sys, "_MEIPASS", str(tmp_path), create=True):
            assert resource_paths.gui_dir() == tmp_path / "gui"


class TestResourcePath:
    def test_returns_path_under_gui_resources(self):
        p = resource_paths.resource_path("AMradioSound.wav")
        assert p.parent.name == "resources"


class TestResolveFfmpegFrozen:
    def test_finds_imageio_ffmpeg_binary_under_meipass(self, tmp_path, monkeypatch):
        fake = types.ModuleType("imageio_ffmpeg")
        fake.get_ffmpeg_exe = lambda: (_ for _ in ()).throw(RuntimeError("no bundled exe"))
        monkeypatch.setitem(sys.modules, "imageio_ffmpeg", fake)

        ff = tmp_path / "nested" / "ffmpeg-macos-aarch64-v7.1"
        ff.parent.mkdir(parents=True)
        ff.write_text("# mock\n", encoding="utf-8")
        ff.chmod(0o755)
        monkeypatch.setattr(resource_paths.platform, "system", lambda: "Darwin")
        monkeypatch.setattr(resource_paths.shutil, "which", lambda *_a, **_k: None)
        monkeypatch.delenv("VINTAGE_RADIO_FFMPEG_EXE", raising=False)
        with mock.patch.object(sys, "frozen", True, create=True), mock.patch.object(
            sys, "_MEIPASS", str(tmp_path), create=True
        ):
            got = resource_paths.resolve_ffmpeg_executable()
        assert got == str(ff)

    def test_env_override_wins(self, tmp_path, monkeypatch):
        override = tmp_path / "my-ffmpeg"
        override.write_text("", encoding="utf-8")
        monkeypatch.setenv("VINTAGE_RADIO_FFMPEG_EXE", str(override))
        with mock.patch.object(sys, "frozen", True, create=True), mock.patch.object(
            sys, "_MEIPASS", str(tmp_path), create=True
        ):
            assert resource_paths.resolve_ffmpeg_executable() == str(override)


class TestAppDataDir:
    def test_source_mode_returns_data_dir(self):
        d = resource_paths.app_data_dir()
        assert d.name == "data"

    def test_creates_dir(self, tmp_path, monkeypatch):
        monkeypatch.setattr(resource_paths, "project_root", lambda: tmp_path)
        monkeypatch.delattr(sys, "frozen", raising=False)
        d = resource_paths.app_data_dir()
        assert d == tmp_path / "data"
