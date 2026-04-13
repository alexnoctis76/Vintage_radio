"""Tests for mpremote-related logic in gui.radio_manager.

Covers:
- _run_mpremote: in-process execution path and subprocess path (with cwd override)
- _install_to_pico_worker: the Install to Pico file-copy workflow
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import List, Optional
from unittest import mock

import pytest


# ---------------------------------------------------------------------------
# _run_mpremote tests
# ---------------------------------------------------------------------------

class TestRunMpremoteInProcess:
    """Test the __INPROCESS__ execution path of _run_mpremote."""

    def _import_run_mpremote(self):
        from gui.radio_manager import _run_mpremote
        return _run_mpremote

    def test_captures_stdout(self):
        """In-process mpremote captures stdout from the callable."""
        _run_mpremote = self._import_run_mpremote()

        def fake_main():
            sys.stdout.write("hello from mpremote")
            return 0

        result = _run_mpremote(
            ["__INPROCESS__", fake_main],
            ["connect", "auto"],
        )
        assert result.returncode == 0
        assert "hello from mpremote" in result.stdout

    def test_captures_stderr(self):
        _run_mpremote = self._import_run_mpremote()

        def fake_main():
            sys.stderr.write("error output")
            return 1

        result = _run_mpremote(
            ["__INPROCESS__", fake_main],
            ["connect", "auto"],
        )
        assert result.returncode == 1
        assert "error output" in result.stderr

    def test_sets_sys_argv(self):
        """sys.argv should be ['mpremote', ...args] during execution."""
        _run_mpremote = self._import_run_mpremote()
        captured_argv = []

        def fake_main():
            captured_argv.extend(sys.argv)
            return 0

        _run_mpremote(
            ["__INPROCESS__", fake_main],
            ["connect", "auto", "exec", "print(1)"],
        )
        assert captured_argv == ["mpremote", "connect", "auto", "exec", "print(1)"]

    def test_restores_sys_argv(self):
        _run_mpremote = self._import_run_mpremote()
        original_argv = sys.argv[:]

        def fake_main():
            return 0

        _run_mpremote(["__INPROCESS__", fake_main], ["test"])
        assert sys.argv == original_argv

    def test_restores_stdout_stderr(self):
        _run_mpremote = self._import_run_mpremote()
        original_stdout = sys.stdout
        original_stderr = sys.stderr

        def fake_main():
            return 0

        _run_mpremote(["__INPROCESS__", fake_main], ["test"])
        assert sys.stdout is original_stdout
        assert sys.stderr is original_stderr

    def test_changes_and_restores_cwd(self, tmp_path):
        _run_mpremote = self._import_run_mpremote()
        original_cwd = os.getcwd()
        target_dir = str(tmp_path)
        captured_cwd = []

        def fake_main():
            captured_cwd.append(os.getcwd())
            return 0

        _run_mpremote(
            ["__INPROCESS__", fake_main],
            ["test"],
            cwd=target_dir,
        )
        assert captured_cwd[0] == target_dir
        assert os.getcwd() == original_cwd

    def test_no_cwd_change_when_none(self):
        _run_mpremote = self._import_run_mpremote()
        original_cwd = os.getcwd()

        def fake_main():
            return 0

        _run_mpremote(["__INPROCESS__", fake_main], ["test"], cwd=None)
        assert os.getcwd() == original_cwd

    def test_encoded_string_io_has_encoding(self):
        """The _EncodedStringIO used for stdout must report encoding='utf-8'."""
        _run_mpremote = self._import_run_mpremote()
        captured_encoding = []

        def fake_main():
            captured_encoding.append(sys.stdout.encoding)
            return 0

        _run_mpremote(["__INPROCESS__", fake_main], ["test"])
        assert captured_encoding[0] == "utf-8"


class TestRunMpremoteSubprocess:
    """Test the subprocess execution path of _run_mpremote."""

    def _import_run_mpremote(self):
        from gui.radio_manager import _run_mpremote
        return _run_mpremote

    @mock.patch("subprocess.run")
    def test_passes_args_to_subprocess(self, mock_run):
        _run_mpremote = self._import_run_mpremote()
        mock_run.return_value = mock.Mock(returncode=0, stdout="ok", stderr="")

        result = _run_mpremote(
            ["/usr/bin/python3", "-m", "mpremote"],
            ["connect", "auto", "exec", "print(1)"],
            cwd="/some/path",
            capture_output=True,
            text=True,
            timeout=10,
        )
        mock_run.assert_called_once()
        call_args = mock_run.call_args
        assert call_args[0][0] == ["/usr/bin/python3", "-m", "mpremote", "connect", "auto", "exec", "print(1)"]
        assert result.returncode == 0

    @mock.patch("subprocess.run")
    def test_cwd_override_when_frozen_and_system_python(self, mock_run):
        """When frozen and using system python -m mpremote, cwd should be redirected to ~."""
        _run_mpremote = self._import_run_mpremote()
        mock_run.return_value = mock.Mock(returncode=0)
        home = os.path.expanduser("~")

        with mock.patch.object(sys, "frozen", True, create=True):
            _run_mpremote(
                ["/usr/bin/python3", "-m", "mpremote"],
                ["connect", "auto"],
                cwd="/Applications/VintageRadio.app/Contents/MacOS",
            )
        call_args = mock_run.call_args
        assert call_args[1]["cwd"] == home

    @mock.patch("subprocess.run")
    def test_cwd_not_overridden_when_not_frozen(self, mock_run):
        """When NOT frozen, cwd should not be overridden."""
        _run_mpremote = self._import_run_mpremote()
        mock_run.return_value = mock.Mock(returncode=0)

        with mock.patch.object(sys, "frozen", False, create=True):
            _run_mpremote(
                ["/usr/bin/python3", "-m", "mpremote"],
                ["connect", "auto"],
                cwd="/home/user/project",
            )
        call_args = mock_run.call_args
        assert call_args[1]["cwd"] == "/home/user/project"

    @mock.patch("subprocess.run")
    def test_cwd_not_overridden_for_standalone_mpremote(self, mock_run):
        """When using standalone mpremote (not python -m mpremote), cwd should not be overridden."""
        _run_mpremote = self._import_run_mpremote()
        mock_run.return_value = mock.Mock(returncode=0)

        with mock.patch.object(sys, "frozen", True, create=True):
            _run_mpremote(
                ["/usr/local/bin/mpremote"],
                ["connect", "auto"],
                cwd="/Applications/VintageRadio.app/Contents/MacOS",
            )
        call_args = mock_run.call_args
        assert call_args[1]["cwd"] == "/Applications/VintageRadio.app/Contents/MacOS"

    @mock.patch("subprocess.run")
    def test_cwd_not_overridden_when_none(self, mock_run):
        """When cwd is None, no override should happen even when frozen."""
        _run_mpremote = self._import_run_mpremote()
        mock_run.return_value = mock.Mock(returncode=0)

        with mock.patch.object(sys, "frozen", True, create=True):
            _run_mpremote(
                ["/usr/bin/python3", "-m", "mpremote"],
                ["connect", "auto"],
                cwd=None,
            )
        call_args = mock_run.call_args
        assert call_args[1]["cwd"] is None


# ---------------------------------------------------------------------------
# _install_to_pico_worker tests
# ---------------------------------------------------------------------------

class TestInstallToPicoWorker:
    """Test the _install_to_pico_worker static method.

    We mock _run_mpremote so no real hardware/subprocess calls are made.
    """

    @pytest.fixture
    def project_root(self, tmp_path):
        """Create a fake project root with required firmware files."""
        root = tmp_path / "project"
        root.mkdir()
        fw = root / "firmware"
        fw.mkdir()
        pico = fw / "pico"
        pico.mkdir()
        (pico / "main.py").write_text("# main firmware")
        (fw / "radio_core.py").write_text("# radio core")
        (pico / "dfplayer_hardware.py").write_text("# dfplayer")
        (root / "AMradioSound.wav").write_bytes(b"\x00" * 100)
        return root

    @pytest.fixture
    def mock_sd_manager(self, tmp_path):
        """Minimal mock SDManager that writes a dummy metadata file."""
        class FakeSDManager:
            def __init__(self):
                self.db = None

            def _write_metadata(self, target_dir: Path):
                meta = target_dir / "radio_metadata.json"
                meta.write_text('{"albums":[],"playlists":[]}')

        return FakeSDManager()

    def _get_worker(self):
        from gui.radio_manager import MainWindow
        return MainWindow._install_to_pico_worker

    def _make_mock_run_mpremote(self, *, failures=None):
        """Build a mock _run_mpremote that records calls and optionally fails specific ones.

        failures: dict mapping arg substrings to (returncode, stderr) to simulate errors.
        """
        failures = failures or {}
        calls = []

        def mock_run(mpremote_cmd, args, **kwargs):
            calls.append(args)
            for pattern, (rc, err) in failures.items():
                if pattern in " ".join(args):
                    return mock.Mock(returncode=rc, stdout="", stderr=err)
            return mock.Mock(returncode=0, stdout="ok", stderr="")

        return mock_run, calls

    @mock.patch("gui.radio_manager._run_mpremote")
    def test_copies_all_firmware_files(self, mock_mpremote, project_root, mock_sd_manager):
        worker = self._get_worker()
        mock_mpremote.return_value = mock.Mock(returncode=0, stdout="", stderr="")
        progress = []

        result = worker(
            mpremote_cmd=["/usr/bin/mpremote"],
            root=project_root,
            sd_root=None,
            sd_manager=mock_sd_manager,
            progress_callback=lambda c, t, m: progress.append((c, t, m)),
        )
        assert "successfully" in result.lower()
        assert len(progress) >= 3

        all_args = [call[0][1] for call in mock_mpremote.call_args_list]
        cp_calls = [a for a in all_args if isinstance(a, list) and a and a[0] == "cp"]
        assert len(cp_calls) >= 3

    @mock.patch("gui.radio_manager._run_mpremote")
    def test_raises_on_firmware_copy_failure(self, mock_mpremote, project_root, mock_sd_manager):
        worker = self._get_worker()

        call_count = 0
        def side_effect(cmd, args, **kwargs):
            nonlocal call_count
            call_count += 1
            if isinstance(args, list) and args and args[0] == "cp":
                return mock.Mock(returncode=1, stdout="", stderr="copy failed")
            return mock.Mock(returncode=0, stdout="", stderr="")

        mock_mpremote.side_effect = side_effect

        with pytest.raises(RuntimeError, match="Failed to copy firmware"):
            worker(
                mpremote_cmd=["/usr/bin/mpremote"],
                root=project_root,
                sd_root=None,
                sd_manager=mock_sd_manager,
            )

    @mock.patch("gui.radio_manager._run_mpremote")
    def test_copies_am_wav(self, mock_mpremote, project_root, mock_sd_manager):
        worker = self._get_worker()
        mock_mpremote.return_value = mock.Mock(returncode=0, stdout="", stderr="")

        worker(
            mpremote_cmd=["/usr/bin/mpremote"],
            root=project_root,
            sd_root=None,
            sd_manager=mock_sd_manager,
            install_mode="legacy",
        )
        all_args = [call[0][1] for call in mock_mpremote.call_args_list]
        am_wav_copies = [
            a for a in all_args
            if isinstance(a, list) and any("AMradioSound" in str(x) for x in a)
        ]
        assert len(am_wav_copies) >= 1

    @mock.patch("gui.radio_manager._run_mpremote")
    def test_writes_and_copies_metadata(self, mock_mpremote, project_root, mock_sd_manager):
        worker = self._get_worker()
        mock_mpremote.return_value = mock.Mock(returncode=0, stdout="", stderr="")

        worker(
            mpremote_cmd=["/usr/bin/mpremote"],
            root=project_root,
            sd_root=None,
            sd_manager=mock_sd_manager,
            install_mode="legacy",
        )
        all_args = [call[0][1] for call in mock_mpremote.call_args_list]
        metadata_copies = [
            a for a in all_args
            if isinstance(a, list) and any("radio_metadata" in str(x) for x in a)
        ]
        assert len(metadata_copies) >= 1

    @mock.patch("gui.radio_manager._run_mpremote")
    def test_creates_directories(self, mock_mpremote, project_root, mock_sd_manager):
        worker = self._get_worker()
        mock_mpremote.return_value = mock.Mock(returncode=0, stdout="", stderr="")

        worker(
            mpremote_cmd=["/usr/bin/mpremote"],
            root=project_root,
            sd_root=None,
            sd_manager=mock_sd_manager,
        )
        first_call_args = mock_mpremote.call_args_list[0][0][1]
        assert "exec" in first_call_args
        mkdir_cmd = first_call_args[first_call_args.index("exec") + 1]
        assert "mkdir" in mkdir_cmd

    @mock.patch("gui.radio_manager._run_mpremote")
    def test_reboots_pico(self, mock_mpremote, project_root, mock_sd_manager):
        worker = self._get_worker()
        mock_mpremote.return_value = mock.Mock(returncode=0, stdout="", stderr="")

        worker(
            mpremote_cmd=["/usr/bin/mpremote"],
            root=project_root,
            sd_root=None,
            sd_manager=mock_sd_manager,
        )
        all_args = [call[0][1] for call in mock_mpremote.call_args_list]
        reboot_calls = [
            a for a in all_args
            if isinstance(a, list) and any("machine.reset" in str(x) for x in a)
        ]
        assert len(reboot_calls) >= 1

    @mock.patch("gui.radio_manager._run_mpremote")
    def test_progress_callback_reports_all_steps(self, mock_mpremote, project_root, mock_sd_manager):
        worker = self._get_worker()
        mock_mpremote.return_value = mock.Mock(returncode=0, stdout="", stderr="")
        progress = []

        worker(
            mpremote_cmd=["/usr/bin/mpremote"],
            root=project_root,
            sd_root=None,
            sd_manager=mock_sd_manager,
            progress_callback=lambda c, t, m: progress.append((c, t, m)),
        )
        assert len(progress) >= 5
        assert progress[-1][2] == "Done!"

    @mock.patch("gui.radio_manager._run_mpremote")
    def test_worker_thread_fallback_for_inprocess(self, mock_mpremote, project_root, mock_sd_manager):
        """In a worker thread, __INPROCESS__ should fall back to system mpremote."""
        worker = self._get_worker()
        mock_mpremote.return_value = mock.Mock(returncode=0, stdout="", stderr="")
        import threading

        error_raised = []

        def fake_main():
            return 0

        with mock.patch("gui.radio_manager._resolve_system_mpremote_for_worker", return_value=None):
            def run_worker():
                try:
                    worker(
                        mpremote_cmd=["__INPROCESS__", fake_main],
                        root=project_root,
                        sd_root=None,
                        sd_manager=mock_sd_manager,
                    )
                except RuntimeError as e:
                    error_raised.append(str(e))

            t = threading.Thread(target=run_worker)
            t.start()
            t.join(timeout=10)

        assert len(error_raised) == 1
        assert "background thread" in error_raised[0].lower()


class TestRunMpremoteWithRetry:
    """Test the retry logic inside _install_to_pico_worker."""

    @mock.patch("gui.radio_manager._run_mpremote")
    def test_retries_on_no_device_found(self, mock_mpremote, tmp_path):
        """When first attempt returns 'no device found', it should retry once after a delay."""
        from gui.radio_manager import MainWindow

        root = tmp_path / "project"
        root.mkdir()
        fw = root / "firmware"
        fw.mkdir()
        pico = fw / "pico"
        pico.mkdir()
        (pico / "main.py").write_text("# main")
        (fw / "radio_core.py").write_text("# core")
        (pico / "dfplayer_hardware.py").write_text("# dfplayer")

        call_count = 0
        def side_effect(cmd, args, **kwargs):
            nonlocal call_count
            call_count += 1
            if isinstance(args, list) and "exec" in args and "mkdir" in " ".join(args):
                if call_count <= 1:
                    return mock.Mock(returncode=1, stdout="", stderr="no device found")
            return mock.Mock(returncode=0, stdout="", stderr="")

        mock_mpremote.side_effect = side_effect

        class FakeSDManager:
            def _write_metadata(self, target_dir):
                (target_dir / "radio_metadata.json").write_text("{}")

        with mock.patch("time.sleep"):
            result = MainWindow._install_to_pico_worker(
                mpremote_cmd=["/usr/bin/mpremote"],
                root=root,
                sd_root=None,
                sd_manager=FakeSDManager(),
            )
        assert "successfully" in result.lower()
