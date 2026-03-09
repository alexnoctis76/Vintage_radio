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
