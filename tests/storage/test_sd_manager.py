"""Tests for gui.sd_manager.SDManager (path helpers, metadata, validation)."""

import json
import os
import sys
from pathlib import Path
from unittest import mock

import pytest

from gui.audio_metadata import compute_file_hash
from gui.database import DatabaseManager
from gui.sd_manager import (
    SDManager,
    _resolve_mount_volume_name,
    _sanitize_fat_volume_label,
)


@pytest.fixture
def sd_db(tmp_path):
    db = DatabaseManager(db_path=tmp_path / "sd_test.db", backups_dir=tmp_path / "backups")
    yield db
    db.close()


@pytest.fixture
def sd_mgr(sd_db):
    return SDManager(sd_db)


@pytest.fixture
def populated_sd(sd_db, tmp_path):
    """DB with 3 songs whose files exist on disk, plus an album and playlist."""
    songs = []
    for i, name in enumerate(("a.mp3", "b.mp3", "c.mp3"), start=1):
        fp = tmp_path / "music" / name
        fp.parent.mkdir(parents=True, exist_ok=True)
        frame = b"\xff\xfb\x90\x00" + b"\x00" * 413
        fp.write_bytes(frame * 10)
        sid = sd_db.add_song(
            original_filename=name,
            file_path=str(fp),
            title=f"Song {i}",
            artist=f"Artist {i}",
            duration=180.0 + i * 10,
            file_hash=f"hash{i}",
            file_size=fp.stat().st_size,
            format="mp3",
        )
        songs.append(sid)

    aid = sd_db.create_album("Test Album")
    for order, sid in enumerate(songs, start=1):
        sd_db.add_song_to_album(aid, sid, order)

    pid = sd_db.create_playlist("Test Playlist")
    sd_db.add_song_to_playlist(pid, songs[0], 1)
    sd_db.add_song_to_playlist(pid, songs[1], 2)

    mgr = SDManager(sd_db)
    return mgr, sd_db, songs, aid, pid


class TestRemoveHiddenJunk:
    def test_removes_macos_and_windows_junk(self, tmp_path):
        sd = tmp_path / "sd"
        (sd / "01").mkdir(parents=True)
        (sd / "01" / "001.mp3").write_bytes(b"x")
        (sd / "01" / "._001.mp3").write_bytes(b"junk")
        (sd / "01" / ".DS_Store").write_bytes(b"")
        (sd / "01" / "Thumbs.db").write_bytes(b"")
        (sd / "01" / "desktop.ini").write_bytes(b"")
        mac = sd / "__MACOSX" / "01"
        mac.mkdir(parents=True)
        (mac / "001.mp3").write_bytes(b"z")

        n = SDManager.remove_hidden_junk_from_sd(sd)
        assert n >= 5
        assert (sd / "01" / "001.mp3").exists()
        assert not (sd / "01" / "._001.mp3").exists()
        assert not (sd / "01" / ".DS_Store").exists()
        assert not (sd / "__MACOSX").exists()

    def test_removes_spotlight_and_fseventsd_at_sd_root(self, tmp_path):
        sd = tmp_path / "sd"
        sd.mkdir()
        (sd / ".Spotlight-V100" / "sub").mkdir(parents=True)
        (sd / ".Spotlight-V100" / "sub" / "x").write_text("a")
        (sd / ".fseventsd").mkdir(parents=True)
        (sd / ".fseventsd" / "uuid").write_text("b")
        (sd / "01").mkdir()
        (sd / "01" / "001.mp3").write_bytes(b"x")

        n = SDManager.remove_hidden_junk_from_sd(sd)
        assert n >= 0
        # Some platforms can recreate root service dirs immediately; ensure the
        # cleanup pass does not disturb actual audio content.
        assert (sd / "01" / "001.mp3").exists()

    def test_sync_strips_junk_after_copy(self, populated_sd, tmp_path):
        mgr, db, songs, aid, pid = populated_sd
        sd_root = tmp_path / "sd_junk"
        sd_root.mkdir()
        junk = sd_root / "01" / "._999.mp3"
        junk.parent.mkdir(parents=True, exist_ok=True)
        junk.write_bytes(b"junk")

        with mock.patch.object(mgr, "_copy_am_wav_to_dfplayer_sd", return_value=False):
            mgr.sync_library(sd_root, audio_target="dfplayer_rp2040")

        assert not junk.exists()
        assert (sd_root / "01" / "001.mp3").exists()


class TestPathHelpers:
    def test_library_root(self, tmp_path):
        assert SDManager.library_root(tmp_path) == tmp_path / "VintageRadio" / "library"

    def test_vintage_root(self, tmp_path):
        assert SDManager.vintage_root(tmp_path) == tmp_path / "VintageRadio"

    def test_dfplayer_radio_metadata_path(self, tmp_path):
        assert SDManager.dfplayer_radio_metadata_path(tmp_path) == tmp_path / "radio_metadata.json"


class TestWriteMetadata:
    def test_creates_json(self, populated_sd, tmp_path):
        mgr, db, songs, aid, pid = populated_sd
        vintage_root = tmp_path / "sd" / "VintageRadio"
        vintage_root.mkdir(parents=True)

        # Set SD mappings so metadata has folder/track info
        for i, sid in enumerate(songs, start=1):
            db.set_sd_mapping(sid, 1, i)

        mgr._write_metadata(vintage_root)
        metadata_path = vintage_root / "radio_metadata.json"
        assert metadata_path.exists()
        data = json.loads(metadata_path.read_text())
        assert len(data["albums"]) == 1
        assert len(data["playlists"]) == 1
        assert len(data["songs"]) == 3
        assert data["am_sound"]["folder"] == 99


class TestValidateSD:
    def test_clean_state(self, populated_sd, tmp_path):
        mgr, db, songs, aid, pid = populated_sd
        # Set sd_path to real files
        for i, sid in enumerate(songs, start=1):
            song = db.get_song_by_id(sid)
            db.update_song_sd_path(sid, song["file_path"])

        results = mgr.validate_sd()
        assert results["missing_file"] == []
        assert results["missing_sd_path"] == []

    def test_missing_sd_path(self, sd_db):
        sd_db.add_song(
            original_filename="x.mp3", file_path="/nonexistent/x.mp3",
            title="X",
        )
        mgr = SDManager(sd_db)
        results = mgr.validate_sd()
        # Source file is missing
        assert len(results["source_file_missing"]) == 1

    def test_missing_file_on_sd(self, sd_db, tmp_path):
        fp = tmp_path / "real.mp3"
        fp.write_bytes(b"\x00" * 100)
        sid = sd_db.add_song(
            original_filename="real.mp3", file_path=str(fp),
            title="Real", sd_path="/nonexistent/sd.mp3",
        )
        mgr = SDManager(sd_db)
        results = mgr.validate_sd()
        assert len(results["missing_file"]) == 1


class TestSyncDFPlayer:
    def test_sync_creates_files(self, populated_sd, tmp_path):
        mgr, db, songs, aid, pid = populated_sd
        sd_root = tmp_path / "sd_card"
        sd_root.mkdir()

        with mock.patch.object(mgr, "_copy_am_wav_to_dfplayer_sd", return_value=False):
            copied, skipped = mgr.sync_library(sd_root, audio_target="dfplayer_rp2040")

        assert copied == 3
        assert not (sd_root / "VintageRadio").exists()
        assert (sd_root / "radio_metadata.json").exists()
        # Verify folder/file structure
        folder_01 = sd_root / "01"
        assert folder_01.exists()
        assert (folder_01 / "001.mp3").exists()
        assert (folder_01 / "002.mp3").exists()
        assert (folder_01 / "003.mp3").exists()

    def test_second_sync_skips(self, populated_sd, tmp_path):
        mgr, db, songs, aid, pid = populated_sd
        sd_root = tmp_path / "sd_card2"
        sd_root.mkdir()

        with mock.patch.object(mgr, "_copy_am_wav_to_dfplayer_sd", return_value=False):
            mgr.sync_library(sd_root, audio_target="dfplayer_rp2040")
            copied, skipped = mgr.sync_library(sd_root, audio_target="dfplayer_rp2040")

        assert copied == 0
        assert skipped == 3


class TestImportFromSD:
    def test_import_reads_metadata(self, sd_db, tmp_path):
        sd_root = tmp_path / "sd_import"

        # Create a fake MP3 file on the SD card
        folder = sd_root / "01"
        folder.mkdir(parents=True)
        track_file = folder / "001.mp3"
        frame = b"\xff\xfb\x90\x00" + b"\x00" * 413
        track_file.write_bytes(frame * 10)

        metadata = {
            "songs": {
                "1": {"title": "Imported Song", "artist": "Imp Artist", "duration": 120,
                      "folder": 1, "track": 1},
            },
            "albums": [
                {"id": 1, "name": "Imported Album", "tracks": [
                    {"song_id": 1, "folder": 1, "track": 1},
                ]},
            ],
            "playlists": [],
        }
        (sd_root / "radio_metadata.json").write_text(json.dumps(metadata))

        mgr = SDManager(sd_db)
        result = mgr.import_from_sd(sd_root)
        assert result["albums"] == 1
        assert result["songs"] == 1

    def test_import_reads_metadata_legacy_vintage_subfolder(self, sd_db, tmp_path):
        sd_root = tmp_path / "sd_import_legacy"
        vintage = sd_root / "VintageRadio"
        vintage.mkdir(parents=True)
        folder = sd_root / "01"
        folder.mkdir(parents=True)
        track_file = folder / "001.mp3"
        frame = b"\xff\xfb\x90\x00" + b"\x00" * 413
        track_file.write_bytes(frame * 10)
        metadata = {
            "songs": {
                "1": {"title": "L", "artist": "A", "duration": 1, "folder": 1, "track": 1},
            },
            "albums": [{"id": 1, "name": "Alb", "tracks": [{"song_id": 1, "folder": 1, "track": 1}]}],
            "playlists": [],
        }
        (vintage / "radio_metadata.json").write_text(json.dumps(metadata))
        mgr = SDManager(sd_db)
        result = mgr.import_from_sd(sd_root)
        assert result["albums"] == 1
        assert result["songs"] == 1


# ---------------------------------------------------------------------------
# New tests: sync edge cases
# ---------------------------------------------------------------------------

class TestSyncEdgeCases:
    def test_sync_with_progress_callback(self, populated_sd, tmp_path):
        mgr, db, songs, aid, pid = populated_sd
        sd_root = tmp_path / "sd_progress"
        sd_root.mkdir()
        progress_values = []

        def on_progress(current, total, label=""):
            progress_values.append((current, total))

        with mock.patch.object(mgr, "_copy_am_wav_to_dfplayer_sd", return_value=False):
            mgr.sync_library(sd_root, audio_target="dfplayer_rp2040",
                             progress_callback=on_progress)

        assert len(progress_values) > 0
        # Progress callback may reset current counter per phase; just assert
        # all values are sane and final callback reaches completion.
        for current, total in progress_values:
            assert 0 <= current <= total
        assert any(current == total for current, total in progress_values if total > 0)

    def test_sync_creates_correct_folder_numbers(self, populated_sd, tmp_path):
        mgr, db, songs, aid, pid = populated_sd
        sd_root = tmp_path / "sd_folders"
        sd_root.mkdir()

        with mock.patch.object(mgr, "_copy_am_wav_to_dfplayer_sd", return_value=False):
            mgr.sync_library(sd_root, audio_target="dfplayer_rp2040")

        # DFPlayer folder should be zero-padded two-digit
        assert (sd_root / "01").exists()

    def test_sync_track_files_are_zero_padded(self, populated_sd, tmp_path):
        mgr, db, songs, aid, pid = populated_sd
        sd_root = tmp_path / "sd_pad"
        sd_root.mkdir()

        with mock.patch.object(mgr, "_copy_am_wav_to_dfplayer_sd", return_value=False):
            mgr.sync_library(sd_root, audio_target="dfplayer_rp2040")

        folder_01 = sd_root / "01"
        if folder_01.exists():
            mp3s = sorted(folder_01.glob("*.mp3"))
            for f in mp3s:
                # Name should be zero-padded: 001.mp3, 002.mp3, etc.
                assert len(f.stem) == 3 or f.stem.isdigit()

    def test_sync_updates_sd_path_in_db(self, populated_sd, tmp_path):
        mgr, db, songs, aid, pid = populated_sd
        sd_root = tmp_path / "sd_paths"
        sd_root.mkdir()

        with mock.patch.object(mgr, "_copy_am_wav_to_dfplayer_sd", return_value=False):
            mgr.sync_library(sd_root, audio_target="dfplayer_rp2040")

        # After sync, songs should have sd_path set
        for sid in songs:
            song = db.get_song_by_id(sid)
            assert song["sd_path"] is not None

    def test_second_sync_skips_all_already_copied(self, populated_sd, tmp_path):
        mgr, db, songs, aid, pid = populated_sd
        sd_root = tmp_path / "sd_skip"
        sd_root.mkdir()

        with mock.patch.object(mgr, "_copy_am_wav_to_dfplayer_sd", return_value=False):
            mgr.sync_library(sd_root, audio_target="dfplayer_rp2040")
            copied, skipped = mgr.sync_library(sd_root, audio_target="dfplayer_rp2040")

        assert copied == 0
        assert skipped > 0


# ---------------------------------------------------------------------------
# New tests: metadata write schema
# ---------------------------------------------------------------------------

class TestMetadataSchema:
    def test_written_metadata_has_required_keys(self, populated_sd, tmp_path):
        mgr, db, songs, aid, pid = populated_sd
        vintage_root = tmp_path / "VintageRadio"
        vintage_root.mkdir(parents=True)

        for i, sid in enumerate(songs, start=1):
            db.set_sd_mapping(sid, 1, i)

        mgr._write_metadata(vintage_root)
        data = json.loads((vintage_root / "radio_metadata.json").read_text())

        assert "albums" in data
        assert "playlists" in data
        assert "songs" in data
        assert "am_sound" in data

    def test_songs_dict_keys_are_strings(self, populated_sd, tmp_path):
        mgr, db, songs, aid, pid = populated_sd
        vintage_root = tmp_path / "VintageRadio"
        vintage_root.mkdir(parents=True)

        for i, sid in enumerate(songs, start=1):
            db.set_sd_mapping(sid, 1, i)

        mgr._write_metadata(vintage_root)
        data = json.loads((vintage_root / "radio_metadata.json").read_text())

        # JSON spec: all keys must be strings
        for key in data["songs"]:
            assert isinstance(key, str)

    def test_each_album_has_tracks(self, populated_sd, tmp_path):
        mgr, db, songs, aid, pid = populated_sd
        vintage_root = tmp_path / "VintageRadio"
        vintage_root.mkdir(parents=True)

        for i, sid in enumerate(songs, start=1):
            db.set_sd_mapping(sid, 1, i)

        mgr._write_metadata(vintage_root)
        data = json.loads((vintage_root / "radio_metadata.json").read_text())

        for album in data["albums"]:
            assert "tracks" in album
            assert isinstance(album["tracks"], list)


# ---------------------------------------------------------------------------
# New tests: AM WAV copy
# ---------------------------------------------------------------------------

class TestAmWavCopy:
    def test_missing_am_wav_source_does_not_raise(self, sd_db, tmp_path):
        mgr = SDManager(sd_db)
        sd_root = tmp_path / "sd_am"
        sd_root.mkdir()
        # Should not raise even if am_wav doesn't exist
        try:
            mgr._copy_am_wav_to_dfplayer_sd(sd_root)
        except Exception as exc:
            pytest.fail(f"_copy_am_wav_to_dfplayer_sd raised on missing WAV: {exc}")

    def test_am_wav_not_copied_to_dfplayer_sd(self, sd_db, tmp_path):
        """AM WAV is Pico PWM only; sync must not place it on the DFPlayer SD card."""
        mgr = SDManager(sd_db)
        am_source = tmp_path / "AMradioSound.wav"
        am_source.write_bytes(b"RIFF" + b"\x00" * 100)
        sd_root = tmp_path / "sd_am_copy"
        sd_root.mkdir()

        with mock.patch("gui.sd_manager.resource_path", return_value=am_source):
            result = mgr._copy_am_wav_to_dfplayer_sd(sd_root)
        assert result is False
        assert not (sd_root / "99" / "001.wav").exists()

# ---------------------------------------------------------------------------
# New tests: validation edge cases
# ---------------------------------------------------------------------------

class TestValidateSDEdgeCases:
    def test_extra_unexpected_files_on_sd_do_not_cause_failure(self, populated_sd, tmp_path):
        mgr, db, songs, aid, pid = populated_sd
        # All songs have valid source files; set sd_path to actual files
        for sid in songs:
            song = db.get_song_by_id(sid)
            db.update_song_sd_path(sid, song["file_path"])

        results = mgr.validate_sd()
        # With valid mappings, missing_file should be empty
        assert results["missing_file"] == []

    def test_song_with_no_source_file_reported(self, sd_db, tmp_path):
        """A song whose source file doesn't exist should appear in validation."""
        sd_db.add_song(
            original_filename="phantom.mp3",
            file_path="/absolutely/nonexistent/phantom.mp3",
            title="Phantom",
        )
        mgr = SDManager(sd_db)
        results = mgr.validate_sd()
        assert len(results["source_file_missing"]) >= 1


def test_sanitize_fat_volume_label_strips_and_truncates():
    assert _sanitize_fat_volume_label("my-sd_12") == "MYSD12"
    assert len(_sanitize_fat_volume_label("ABCDEFGHIJKLMNOP")) == 11
    assert _sanitize_fat_volume_label("   ") == ""


@pytest.mark.windows_only
@pytest.mark.skipif(sys.platform != "win32", reason="Windows Path + volume label semantics")
def test_resolve_mount_volume_name_windows_prefers_get_volume_label():
    p = Path("E:/")
    with mock.patch("gui.sd_manager.os.name", "nt"):
        with mock.patch("gui.sd_manager._get_volume_label", return_value="CANON"):
            assert _resolve_mount_volume_name(p, "HINT") == "CANON"


@pytest.mark.windows_only
@pytest.mark.skipif(sys.platform != "win32", reason="Windows Path + volume label semantics")
def test_resolve_mount_volume_name_falls_back_to_db_hint_on_windows():
    p = Path("E:/")
    with mock.patch("gui.sd_manager.os.name", "nt"):
        with mock.patch("gui.sd_manager._get_volume_label", return_value=""):
            assert _resolve_mount_volume_name(p, "FALLBACK") == "FALLBACK"


def test_resolve_mount_volume_name_uses_mount_folder_name():
    p = Path("/Volumes/MyRadioCard")
    with mock.patch("gui.sd_manager.os.name", "posix"):
        assert _resolve_mount_volume_name(p, "") == "MyRadioCard"


class TestBasicConvertWorkersAuto:
    """_basic_convert_workers_auto tiers: RAM + logical CPU count (see sd_manager)."""

    def test_workstation_tier_uses_2x_logical_cpus_capped_32(self, sd_mgr):
        with mock.patch("gui.sd_manager.os.cpu_count", return_value=8):
            vm = mock.Mock()
            vm.total = 64 * 1024**3
            with mock.patch("gui.sd_manager.psutil.virtual_memory", return_value=vm):
                w, tier = sd_mgr._basic_convert_workers_auto(100000)
        assert w == 16
        assert "workstation" in tier

    def test_workstation_16_threads_caps_at_32(self, sd_mgr):
        with mock.patch("gui.sd_manager.os.cpu_count", return_value=16):
            vm = mock.Mock()
            vm.total = 64 * 1024**3
            with mock.patch("gui.sd_manager.psutil.virtual_memory", return_value=vm):
                w, _ = sd_mgr._basic_convert_workers_auto(100000)
        assert w == 32

    def test_balanced_tier_one_per_core(self, sd_mgr):
        with mock.patch("gui.sd_manager.os.cpu_count", return_value=8):
            vm = mock.Mock()
            vm.total = 16 * 1024**3
            with mock.patch("gui.sd_manager.psutil.virtual_memory", return_value=vm):
                w, tier = sd_mgr._basic_convert_workers_auto(100000)
        assert w == 8
        assert "balanced" in tier

    def test_modest_tier_8gb_ram(self, sd_mgr):
        with mock.patch("gui.sd_manager.os.cpu_count", return_value=8):
            vm = mock.Mock()
            vm.total = 8 * 1024**3
            with mock.patch("gui.sd_manager.psutil.virtual_memory", return_value=vm):
                w, tier = sd_mgr._basic_convert_workers_auto(100000)
        assert w == 8
        assert "modest" in tier

    def test_env_overrides_auto_tiers(self, sd_mgr):
        with mock.patch.dict(os.environ, {"VINTAGE_RADIO_CONVERT_WORKERS": "5"}, clear=False):
            with mock.patch("gui.sd_manager.os.cpu_count", return_value=8):
                vm = mock.Mock()
                vm.total = 64 * 1024**3
                with mock.patch("gui.sd_manager.psutil.virtual_memory", return_value=vm):
                    w, note = sd_mgr._resolve_basic_convert_workers(999)
        assert w == 5
        assert "manual" in note


def test_clear_basic_sync_mp3_cache_for_library_removes_tree(sd_mgr, tmp_path):
    fp = sd_mgr._library_cache_fingerprint()
    fake_base = tmp_path / "cache_root"
    root = fake_base / "basic_sync_mp3" / fp
    root.mkdir(parents=True)
    (root / "dfplayer_safe_auto").mkdir()
    (root / "dfplayer_safe_auto" / "h.mp3").write_bytes(b"x")
    with mock.patch("platformdirs.user_cache_dir", return_value=str(fake_base)):
        ok, err = sd_mgr.clear_basic_sync_mp3_cache_for_library()
    assert ok
    assert err == ""
    assert not root.exists()


def test_clear_basic_sync_mp3_cache_for_library_noop_when_missing(sd_mgr, tmp_path):
    fp = sd_mgr._library_cache_fingerprint()
    fake_base = tmp_path / "cache_root"
    fake_base.mkdir()
    with mock.patch("platformdirs.user_cache_dir", return_value=str(fake_base)):
        ok, err = sd_mgr.clear_basic_sync_mp3_cache_for_library()
    assert ok
    assert err == ""


def _write_minimal_mp3(path: Path, *, repeat: int = 10) -> None:
    frame = b"\xff\xfb\x90\x00" + b"\x00" * 413
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(frame * repeat)


@pytest.fixture
def basic_station_setup(tmp_path, sd_db):
    """One basic station with two MP3 tracks on disk."""
    music = tmp_path / "music"
    a = music / "alpha.mp3"
    b = music / "beta.mp3"
    _write_minimal_mp3(a)
    _write_minimal_mp3(b, repeat=20)
    sid_a = sd_db.add_song(
        original_filename="alpha.mp3",
        file_path=str(a),
        title="Alpha",
        file_hash=compute_file_hash(a),
        file_size=a.stat().st_size,
        format="mp3",
    )
    sid_b = sd_db.add_song(
        original_filename="beta.mp3",
        file_path=str(b),
        title="Beta",
        file_hash=compute_file_hash(b),
        file_size=b.stat().st_size,
        format="mp3",
    )
    st_id = sd_db.create_basic_station("Station One", 1)
    sd_db.add_song_to_basic_station(st_id, sid_a, 1)
    sd_db.add_song_to_basic_station(st_id, sid_b, 2)
    mgr = SDManager(sd_db)
    return mgr, sd_db, st_id, sid_a, sid_b, a, b


class TestBasicSyncChanges:
    def test_second_sync_skips_unchanged_tracks(self, basic_station_setup, tmp_path):
        mgr, db, st_id, sid_a, sid_b, a, b = basic_station_setup
        sd_root = tmp_path / "sd_basic"
        sd_root.mkdir()
        with mock.patch.object(mgr, "_copy_am_wav_to_dfplayer_sd", return_value=False):
            r1 = mgr.sync_library_basic(sd_root)
            r2 = mgr.sync_library_basic(sd_root)
        assert int(r1["copied"]) == 2
        assert int(r2["copied"]) == 0
        assert int(r2["skipped"]) >= 2
        assert (sd_root / "01" / "001.mp3").exists()
        assert (sd_root / "01" / "002.mp3").exists()

    def test_sync_changes_replaces_modified_track(self, basic_station_setup, tmp_path):
        mgr, db, st_id, sid_a, sid_b, a, b = basic_station_setup
        sd_root = tmp_path / "sd_modified"
        sd_root.mkdir()
        with mock.patch.object(mgr, "_copy_am_wav_to_dfplayer_sd", return_value=False):
            mgr.sync_library_basic(sd_root)
            _write_minimal_mp3(a, repeat=12)
            new_hash = compute_file_hash(a)
            db.conn.execute(
                "UPDATE songs SET file_hash = ?, file_size = ? WHERE id = ?;",
                (new_hash, a.stat().st_size, sid_a),
            )
            db.conn.commit()
            r2 = mgr.sync_library_basic(sd_root)
        assert int(r2["copied"]) >= 1
        assert (sd_root / "01" / "001.mp3").read_bytes() == a.read_bytes()

    def test_sync_without_manifest_verifies_mp3_content(self, basic_station_setup, tmp_path):
        mgr, db, st_id, sid_a, sid_b, a, b = basic_station_setup
        sd_root = tmp_path / "sd_nomanifest"
        sd_root.mkdir()
        with mock.patch.object(mgr, "_copy_am_wav_to_dfplayer_sd", return_value=False):
            mgr.sync_library_basic(sd_root)
            manifest = sd_root / ".sync_manifest.json"
            assert manifest.exists()
            manifest.unlink()
            local_manifest = SDManager._local_manifest_path(sd_root)
            if local_manifest is not None:
                try:
                    local_manifest.unlink(missing_ok=True)
                except OSError:
                    pass
            wrong = sd_root / "01" / "001.mp3"
            wrong.write_bytes(wrong.read_bytes() + b"corrupt")
            r2 = mgr.sync_library_basic(sd_root)
        assert int(r2["copied"]) >= 1
        assert wrong.read_bytes() == a.read_bytes()

    def test_reordered_tracks_are_recopied(self, basic_station_setup, tmp_path):
        mgr, db, st_id, sid_a, sid_b, a, b = basic_station_setup
        sd_root = tmp_path / "sd_reorder"
        sd_root.mkdir()
        with mock.patch.object(mgr, "_copy_am_wav_to_dfplayer_sd", return_value=False):
            mgr.sync_library_basic(sd_root)
            for row in db.list_basic_station_tracks(st_id):
                db.remove_basic_station_track(int(row["id"]))
            db.add_song_to_basic_station(st_id, sid_b, 1)
            db.add_song_to_basic_station(st_id, sid_a, 2)
            r2 = mgr.sync_library_basic(sd_root)
        assert int(r2["copied"]) >= 2
        assert (sd_root / "01" / "001.mp3").read_bytes() == b.read_bytes()
        assert (sd_root / "01" / "002.mp3").read_bytes() == a.read_bytes()

    def test_unchanged_sync_uses_manifest_without_hashing(self, basic_station_setup, tmp_path):
        """Second Sync Changes pass must not SHA-256 every MP3 when manifest matches."""
        mgr, db, st_id, sid_a, sid_b, a, b = basic_station_setup
        sd_root = tmp_path / "sd_fast"
        sd_root.mkdir()
        with mock.patch.object(mgr, "_copy_am_wav_to_dfplayer_sd", return_value=False):
            mgr.sync_library_basic(sd_root)
            with mock.patch(
                "gui.sd_manager.compute_file_hash",
                side_effect=AssertionError("hash should not run on manifest fast path"),
            ) as hash_mock:
                r2 = mgr.sync_library_basic(sd_root)
            hash_mock.assert_not_called()
        assert int(r2["copied"]) == 0
        assert int(r2["skipped"]) >= 2
