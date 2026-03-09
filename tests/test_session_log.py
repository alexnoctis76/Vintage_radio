"""Tests for gui.session_log (log directory, init, cleanup)."""

import sys
import tempfile
from pathlib import Path
from unittest import mock

import pytest

from gui import session_log


class TestGetLogDir:
    def test_returns_path(self):
        d = session_log.get_log_dir()
        assert isinstance(d, Path)
        assert d.name == "VintageRadio"
        assert d.exists()

    def test_creates_dir(self, tmp_path, monkeypatch):
        target = tmp_path / "custom_tmp" / "VintageRadio"
        monkeypatch.setattr(tempfile, "gettempdir", lambda: str(tmp_path / "custom_tmp"))
        d = session_log.get_log_dir()
        assert d.exists()
        assert d == target


class TestCleanupOldLogs:
    def test_keeps_recent(self, tmp_path):
        for i in range(15):
            (tmp_path / f"vintage_radio_{i:04d}.log").write_text(f"log {i}")
        session_log._cleanup_old_logs(tmp_path, keep=10)
        remaining = list(tmp_path.glob("vintage_radio_*.log"))
        assert len(remaining) == 10

    def test_noop_when_under_limit(self, tmp_path):
        for i in range(3):
            (tmp_path / f"vintage_radio_{i:04d}.log").write_text(f"log {i}")
        session_log._cleanup_old_logs(tmp_path, keep=10)
        remaining = list(tmp_path.glob("vintage_radio_*.log"))
        assert len(remaining) == 3


class TestInitSessionLogging:
    def test_creates_log_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr(tempfile, "gettempdir", lambda: str(tmp_path))
        saved_stdout = sys.stdout
        saved_stderr = sys.stderr
        try:
            path = session_log.init_session_logging(app_version="test-1.0")
            assert path.exists()
            assert "vintage_radio_" in path.name
            content = path.read_text()
            assert "test-1.0" in content
        finally:
            sys.stdout = saved_stdout
            sys.stderr = saved_stderr
            session_log._session_log_path = None
