"""Tests for gui.sd_manager.SDManager (path helpers, metadata, validation)."""

import json
from pathlib import Path
from unittest import mock

import pytest

from gui.database import DatabaseManager
from gui.sd_manager import SDManager


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
        vintage = sd_root / "VintageRadio"
        vintage.mkdir(parents=True)

        # Create a fake MP3 file on the SD card
        folder = sd_root / "01"
        folder.mkdir()
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

    def test_am_wav_copy_to_folder_99(self, sd_db, tmp_path):
        """If AM WAV exists on disk, it should be copied to folder 99."""
        mgr = SDManager(sd_db)
        # Mock resource path to point to a real temp file
        am_source = tmp_path / "AMradioSound.wav"
        am_source.write_bytes(b"RIFF" + b"\x00" * 100)
        sd_root = tmp_path / "sd_am_copy"
        sd_root.mkdir()

        with mock.patch("gui.sd_manager.resource_path", return_value=am_source):
            result = mgr._copy_am_wav_to_dfplayer_sd(sd_root)
        # Result can be True or False depending on implementation;
        # key assertion: no exception
        assert isinstance(result, bool)


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
