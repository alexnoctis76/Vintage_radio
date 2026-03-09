"""Tests for gui.resource_paths."""

import sys
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


class TestAppDataDir:
    def test_source_mode_returns_data_dir(self):
        d = resource_paths.app_data_dir()
        assert d.name == "data"

    def test_creates_dir(self, tmp_path, monkeypatch):
        monkeypatch.setattr(resource_paths, "project_root", lambda: tmp_path)
        monkeypatch.delattr(sys, "frozen", raising=False)
        d = resource_paths.app_data_dir()
        assert d == tmp_path / "data"
