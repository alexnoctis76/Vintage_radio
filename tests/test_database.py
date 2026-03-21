"""Tests for gui.database.DatabaseManager."""

from pathlib import Path

import pytest

from gui.database import DatabaseManager


class TestSchemaInit:
    def test_fresh_db_reaches_schema_v6(self, tmp_db):
        version = tmp_db.get_setting("schema_version")
        assert version == "6"

    def test_tables_exist(self, tmp_db):
        tables = {
            row[0]
            for row in tmp_db.conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table';"
            ).fetchall()
        }
        for expected in ("songs", "albums", "playlists", "album_songs",
                         "playlist_songs", "sd_mapping", "settings",
                         "basic_stations", "basic_station_tracks"):
            assert expected in tables

    def test_sort_order_columns_exist(self, tmp_db):
        for table in ("albums", "playlists"):
            cols = [
                row["name"]
                for row in tmp_db.conn.execute(f"PRAGMA table_info({table});").fetchall()
            ]
            assert "sort_order" in cols


class TestSongsCRUD:
    def test_add_and_retrieve(self, tmp_db):
        sid = tmp_db.add_song(
            original_filename="test.mp3",
            file_path="/tmp/test.mp3",
            title="Test Song",
            artist="Test Artist",
            duration=120.5,
            file_hash="abc123",
            file_size=9999,
            format="mp3",
        )
        assert sid > 0

        row = tmp_db.get_song_by_id(sid)
        assert row is not None
        assert row["title"] == "Test Song"
        assert row["artist"] == "Test Artist"
        assert row["duration"] == pytest.approx(120.5)
        assert row["file_hash"] == "abc123"
        assert row["file_size"] == 9999
        assert row["format"] == "mp3"

    def test_get_song_by_path(self, tmp_db):
        tmp_db.add_song(original_filename="a.mp3", file_path="/x/a.mp3", title="A")
        row = tmp_db.get_song_by_path("/x/a.mp3")
        assert row is not None
        assert row["title"] == "A"

    def test_get_song_by_hash_size(self, tmp_db):
        tmp_db.add_song(
            original_filename="b.mp3", file_path="/x/b.mp3",
            file_hash="h1", file_size=100,
        )
        row = tmp_db.get_song_by_hash_size("h1", 100)
        assert row is not None

    def test_update_song(self, tmp_db):
        sid = tmp_db.add_song(original_filename="c.mp3", file_path="/x/c.mp3", title="C")
        tmp_db.update_song(sid, {"title": "C Updated"})
        assert tmp_db.get_song_by_id(sid)["title"] == "C Updated"

    def test_delete_song(self, tmp_db):
        sid = tmp_db.add_song(original_filename="d.mp3", file_path="/x/d.mp3")
        tmp_db.delete_song(sid)
        assert tmp_db.get_song_by_id(sid) is None

    def test_list_songs(self, tmp_db):
        tmp_db.add_song(original_filename="e.mp3", file_path="/x/e.mp3", title="E")
        tmp_db.add_song(original_filename="f.mp3", file_path="/x/f.mp3", title="F")
        songs = tmp_db.list_songs()
        assert len(songs) == 2

    def test_get_songs_by_ids(self, tmp_db):
        s1 = tmp_db.add_song(original_filename="g.mp3", file_path="/x/g.mp3")
        s2 = tmp_db.add_song(original_filename="h.mp3", file_path="/x/h.mp3")
        rows = tmp_db.get_songs_by_ids([s1, s2])
        assert len(rows) == 2

    def test_get_songs_by_ids_empty(self, tmp_db):
        assert tmp_db.get_songs_by_ids([]) == []


class TestDeduplication:
    def test_same_hash_size_returns_existing_id(self, tmp_db):
        s1 = tmp_db.add_song(
            original_filename="dup.mp3", file_path="/x/dup.mp3",
            file_hash="samehash", file_size=500,
        )
        s2 = tmp_db.add_song(
            original_filename="dup2.mp3", file_path="/x/dup2.mp3",
            file_hash="samehash", file_size=500,
        )
        assert s1 == s2

    def test_same_path_returns_existing_id(self, tmp_db):
        s1 = tmp_db.add_song(original_filename="p.mp3", file_path="/x/p.mp3")
        s2 = tmp_db.add_song(original_filename="p.mp3", file_path="/x/p.mp3")
        assert s1 == s2


class TestAlbumsCRUD:
    def test_create_album(self, tmp_db):
        aid = tmp_db.create_album("My Album", "Desc")
        assert aid > 0

    def test_list_albums(self, tmp_db):
        tmp_db.create_album("Album A")
        tmp_db.create_album("Album B")
        assert len(tmp_db.list_albums()) == 2

    def test_get_album_by_id(self, tmp_db):
        aid = tmp_db.create_album("Find Me")
        row = tmp_db.get_album_by_id(aid)
        assert row is not None
        assert row["name"] == "Find Me"

    def test_update_album(self, tmp_db):
        aid = tmp_db.create_album("Old Name")
        tmp_db.update_album(aid, {"name": "New Name"})
        assert tmp_db.get_album_by_id(aid)["name"] == "New Name"

    def test_delete_album(self, tmp_db):
        aid = tmp_db.create_album("Del Me")
        tmp_db.delete_album(aid)
        assert tmp_db.get_album_by_id(aid) is None

    def test_update_album_order(self, tmp_db):
        a1 = tmp_db.create_album("First")
        a2 = tmp_db.create_album("Second")
        tmp_db.update_album_order([a2, a1])
        albums = tmp_db.list_albums()
        assert albums[0]["name"] == "Second"
        assert albums[1]["name"] == "First"


class TestPlaylistsCRUD:
    def test_create_playlist(self, tmp_db):
        pid = tmp_db.create_playlist("My Playlist")
        assert pid > 0

    def test_update_playlist(self, tmp_db):
        pid = tmp_db.create_playlist("Old PL")
        tmp_db.update_playlist(pid, {"name": "New PL"})
        assert tmp_db.get_playlist_by_id(pid)["name"] == "New PL"

    def test_delete_playlist(self, tmp_db):
        pid = tmp_db.create_playlist("Del PL")
        tmp_db.delete_playlist(pid)
        assert tmp_db.get_playlist_by_id(pid) is None

    def test_update_playlist_order(self, tmp_db):
        p1 = tmp_db.create_playlist("PL 1")
        p2 = tmp_db.create_playlist("PL 2")
        tmp_db.update_playlist_order([p2, p1])
        playlists = tmp_db.list_playlists()
        assert playlists[0]["name"] == "PL 2"


class TestAlbumTracks:
    def test_add_and_list_album_songs(self, tmp_db):
        aid = tmp_db.create_album("A")
        s1 = tmp_db.add_song(original_filename="s1.mp3", file_path="/s1.mp3")
        s2 = tmp_db.add_song(original_filename="s2.mp3", file_path="/s2.mp3")
        tmp_db.add_song_to_album(aid, s1, 1)
        tmp_db.add_song_to_album(aid, s2, 2)
        songs = tmp_db.list_album_songs(aid)
        assert len(songs) == 2
        assert songs[0]["id"] == s1
        assert songs[1]["id"] == s2

    def test_remove_song_from_album(self, tmp_db):
        aid = tmp_db.create_album("A")
        sid = tmp_db.add_song(original_filename="r.mp3", file_path="/r.mp3")
        tmp_db.add_song_to_album(aid, sid, 1)
        tmp_db.remove_song_from_album(aid, sid)
        assert len(tmp_db.list_album_songs(aid)) == 0

    def test_list_album_tracks(self, tmp_db):
        aid = tmp_db.create_album("A")
        sid = tmp_db.add_song(original_filename="t.mp3", file_path="/t.mp3")
        tmp_db.add_song_to_album(aid, sid, 5)
        tracks = tmp_db.list_album_tracks(aid)
        assert len(tracks) == 1
        assert tracks[0]["track_order"] == 5

    def test_replace_album_tracks(self, tmp_db):
        aid = tmp_db.create_album("A")
        s1 = tmp_db.add_song(original_filename="ra.mp3", file_path="/ra.mp3")
        s2 = tmp_db.add_song(original_filename="rb.mp3", file_path="/rb.mp3")
        s3 = tmp_db.add_song(original_filename="rc.mp3", file_path="/rc.mp3")
        tmp_db.add_song_to_album(aid, s1, 1)
        tmp_db.replace_album_tracks(aid, [s3, s2])
        songs = tmp_db.list_album_songs(aid)
        assert len(songs) == 2
        assert songs[0]["id"] == s3

    def test_next_album_track_order(self, tmp_db):
        aid = tmp_db.create_album("A")
        assert tmp_db.next_album_track_order(aid) == 1
        sid = tmp_db.add_song(original_filename="n.mp3", file_path="/n.mp3")
        tmp_db.add_song_to_album(aid, sid, 3)
        assert tmp_db.next_album_track_order(aid) == 4


class TestPlaylistTracks:
    def test_add_and_list_playlist_songs(self, tmp_db):
        pid = tmp_db.create_playlist("P")
        s1 = tmp_db.add_song(original_filename="ps1.mp3", file_path="/ps1.mp3")
        tmp_db.add_song_to_playlist(pid, s1, 1)
        songs = tmp_db.list_playlist_songs(pid)
        assert len(songs) == 1

    def test_remove_song_from_playlist(self, tmp_db):
        pid = tmp_db.create_playlist("P")
        sid = tmp_db.add_song(original_filename="pr.mp3", file_path="/pr.mp3")
        tmp_db.add_song_to_playlist(pid, sid, 1)
        tmp_db.remove_song_from_playlist(pid, sid)
        assert len(tmp_db.list_playlist_songs(pid)) == 0

    def test_replace_playlist_tracks(self, tmp_db):
        pid = tmp_db.create_playlist("P")
        s1 = tmp_db.add_song(original_filename="pr1.mp3", file_path="/pr1.mp3")
        s2 = tmp_db.add_song(original_filename="pr2.mp3", file_path="/pr2.mp3")
        tmp_db.replace_playlist_tracks(pid, [s2, s1])
        songs = tmp_db.list_playlist_songs(pid)
        assert songs[0]["id"] == s2

    def test_next_playlist_track_order(self, tmp_db):
        pid = tmp_db.create_playlist("P")
        assert tmp_db.next_playlist_track_order(pid) == 1


class TestSDMapping:
    def test_set_and_get(self, tmp_db):
        sid = tmp_db.add_song(original_filename="m.mp3", file_path="/m.mp3")
        tmp_db.set_sd_mapping(sid, 2, 5)
        mapping = tmp_db.get_sd_mapping(sid)
        assert mapping is not None
        assert mapping["folder_number"] == 2
        assert mapping["track_number"] == 5

    def test_no_mapping(self, tmp_db):
        sid = tmp_db.add_song(original_filename="nm.mp3", file_path="/nm.mp3")
        assert tmp_db.get_sd_mapping(sid) is None

    def test_set_sd_mappings_batch(self, tmp_db):
        s1 = tmp_db.add_song(original_filename="b1.mp3", file_path="/b1.mp3")
        s2 = tmp_db.add_song(original_filename="b2.mp3", file_path="/b2.mp3")
        tmp_db.set_sd_mappings_batch([(s1, 1, 1), (s2, 1, 2)])
        assert tmp_db.get_sd_mapping(s1)["folder_number"] == 1
        assert tmp_db.get_sd_mapping(s2)["track_number"] == 2


class TestSettings:
    def test_round_trip(self, tmp_db):
        tmp_db.set_setting("volume", "80")
        assert tmp_db.get_setting("volume") == "80"

    def test_default(self, tmp_db):
        assert tmp_db.get_setting("missing") is None
        assert tmp_db.get_setting("missing", "fallback") == "fallback"

    def test_overwrite(self, tmp_db):
        tmp_db.set_setting("key", "a")
        tmp_db.set_setting("key", "b")
        assert tmp_db.get_setting("key") == "b"


class TestBackupRestore:
    def test_backup_creates_file(self, tmp_db):
        backup = tmp_db.backup_now()
        assert backup is not None
        assert backup.exists()

    def test_restore_from_backup(self, tmp_path):
        import sqlite3
        db = DatabaseManager(db_path=tmp_path / "bk.db", backups_dir=tmp_path / "backups")
        sid = db.add_song(original_filename="bk.mp3", file_path="/bk.mp3", title="Backup")
        # Checkpoint WAL so backup_now (which copies the file) captures all data
        db.conn.execute("PRAGMA wal_checkpoint(FULL);")
        backup = db.backup_now()

        db.delete_song(sid)
        assert db.get_song_by_id(sid) is None
        db.close()

        db.restore_from_backup(backup)
        conn = sqlite3.connect(db.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM songs WHERE id = ?;", (sid,)).fetchone()
        conn.close()
        assert row is not None
        assert row["title"] == "Backup"

    def test_backup_retention(self, tmp_path):
        db = DatabaseManager(
            db_path=tmp_path / "ret.db",
            backups_dir=tmp_path / "backups",
            backup_retention=2,
        )
        db.backup_now()
        db.backup_now()
        db.backup_now()
        backups = list((tmp_path / "backups").glob("*.db"))
        assert len(backups) <= 2
        db.close()


class TestSdPathBatch:
    def test_update_song_sd_paths_batch(self, tmp_db):
        s1 = tmp_db.add_song(original_filename="sp1.mp3", file_path="/sp1.mp3")
        s2 = tmp_db.add_song(original_filename="sp2.mp3", file_path="/sp2.mp3")
        tmp_db.update_song_sd_paths_batch([(s1, "/sd/01/001.mp3"), (s2, "/sd/01/002.mp3")])
        assert tmp_db.get_song_by_id(s1)["sd_path"] == "/sd/01/001.mp3"
        assert tmp_db.get_song_by_id(s2)["sd_path"] == "/sd/01/002.mp3"


class TestBasicStationsCRUD:
    def test_create_and_get(self, tmp_db):
        sid = tmp_db.create_basic_station("Station 1", 1)
        assert sid > 0
        station = tmp_db.get_basic_station(sid)
        assert station is not None
        assert station["name"] == "Station 1"
        assert station["folder_number"] == 1

    def test_list_stations(self, tmp_db):
        tmp_db.create_basic_station("Station A", 1)
        tmp_db.create_basic_station("Station B", 2)
        stations = tmp_db.list_basic_stations()
        assert len(stations) == 2

    def test_update_station(self, tmp_db):
        sid = tmp_db.create_basic_station("Old Name", 1)
        tmp_db.update_basic_station(sid, name="New Name")
        assert tmp_db.get_basic_station(sid)["name"] == "New Name"

    def test_delete_station(self, tmp_db):
        sid = tmp_db.create_basic_station("To Delete", 1)
        tmp_db.delete_basic_station(sid)
        assert tmp_db.get_basic_station(sid) is None

    def test_next_folder_number(self, tmp_db):
        assert tmp_db.next_basic_station_folder() == 1
        tmp_db.create_basic_station("S1", 1)
        assert tmp_db.next_basic_station_folder() == 2
        tmp_db.create_basic_station("S3", 3)
        assert tmp_db.next_basic_station_folder() == 2

    def test_update_station_order(self, tmp_db):
        s1 = tmp_db.create_basic_station("First", 1)
        s2 = tmp_db.create_basic_station("Second", 2)
        tmp_db.update_basic_station_order([s2, s1])
        stations = tmp_db.list_basic_stations()
        assert stations[0]["name"] == "Second"
        assert stations[1]["name"] == "First"

    def test_update_station_order_reassigns_folders(self, tmp_db):
        s1 = tmp_db.create_basic_station("A", 1)
        s2 = tmp_db.create_basic_station("B", 2)
        s3 = tmp_db.create_basic_station("C", 3)
        tmp_db.update_basic_station_order([s3, s1, s2])
        stations = tmp_db.list_basic_stations()
        assert stations[0]["folder_number"] == 1
        assert stations[0]["name"] == "C"
        assert stations[1]["folder_number"] == 2
        assert stations[1]["name"] == "A"
        assert stations[2]["folder_number"] == 3
        assert stations[2]["name"] == "B"

    def test_clear_all(self, tmp_db):
        s1 = tmp_db.create_basic_station("S1", 1)
        song = tmp_db.add_song(original_filename="x.mp3", file_path="/x.mp3")
        tmp_db.add_song_to_basic_station(s1, song, 1)
        tmp_db.clear_all_basic_stations()
        assert len(tmp_db.list_basic_stations()) == 0


class TestBasicStationTracks:
    def test_add_and_list(self, tmp_db):
        sid = tmp_db.create_basic_station("S", 1)
        s1 = tmp_db.add_song(original_filename="a.mp3", file_path="/a.mp3")
        s2 = tmp_db.add_song(original_filename="b.mp3", file_path="/b.mp3")
        tmp_db.add_song_to_basic_station(sid, s1, 1)
        tmp_db.add_song_to_basic_station(sid, s2, 2)
        songs = tmp_db.list_basic_station_songs(sid)
        assert len(songs) == 2
        assert songs[0]["id"] == s1
        assert "bst_id" in songs[0].keys()

    def test_remove_song(self, tmp_db):
        sid = tmp_db.create_basic_station("S", 1)
        song = tmp_db.add_song(original_filename="r.mp3", file_path="/r.mp3")
        tmp_db.add_song_to_basic_station(sid, song, 1)
        tmp_db.remove_song_from_basic_station(sid, song)
        assert len(tmp_db.list_basic_station_songs(sid)) == 0

    def test_remove_single_track_by_id(self, tmp_db):
        sid = tmp_db.create_basic_station("S", 1)
        song = tmp_db.add_song(original_filename="dup.mp3", file_path="/dup.mp3")
        tmp_db.add_song_to_basic_station(sid, song, 1)
        tmp_db.add_song_to_basic_station(sid, song, 2)
        songs = tmp_db.list_basic_station_songs(sid)
        assert len(songs) == 2
        tmp_db.remove_basic_station_track(songs[0]["bst_id"])
        songs_after = tmp_db.list_basic_station_songs(sid)
        assert len(songs_after) == 1

    def test_duplicate_songs_in_station(self, tmp_db):
        sid = tmp_db.create_basic_station("S", 1)
        song = tmp_db.add_song(original_filename="song.mp3", file_path="/song.mp3")
        tmp_db.add_song_to_basic_station(sid, song, 1)
        tmp_db.add_song_to_basic_station(sid, song, 2)
        tmp_db.add_song_to_basic_station(sid, song, 3)
        songs = tmp_db.list_basic_station_songs(sid)
        assert len(songs) == 3
        assert all(s["id"] == song for s in songs)
        assert songs[0]["bst_id"] != songs[1]["bst_id"]

    def test_replace_tracks(self, tmp_db):
        sid = tmp_db.create_basic_station("S", 1)
        s1 = tmp_db.add_song(original_filename="t1.mp3", file_path="/t1.mp3")
        s2 = tmp_db.add_song(original_filename="t2.mp3", file_path="/t2.mp3")
        s3 = tmp_db.add_song(original_filename="t3.mp3", file_path="/t3.mp3")
        tmp_db.add_song_to_basic_station(sid, s1, 1)
        tmp_db.replace_basic_station_tracks(sid, [s3, s2])
        songs = tmp_db.list_basic_station_songs(sid)
        assert len(songs) == 2
        assert songs[0]["id"] == s3

    def test_replace_tracks_with_duplicates(self, tmp_db):
        sid = tmp_db.create_basic_station("S", 1)
        song = tmp_db.add_song(original_filename="x.mp3", file_path="/x.mp3")
        tmp_db.replace_basic_station_tracks(sid, [song, song, song])
        songs = tmp_db.list_basic_station_songs(sid)
        assert len(songs) == 3

    def test_next_track_order(self, tmp_db):
        sid = tmp_db.create_basic_station("S", 1)
        assert tmp_db.next_basic_station_track_order(sid) == 1
        song = tmp_db.add_song(original_filename="n.mp3", file_path="/n.mp3")
        tmp_db.add_song_to_basic_station(sid, song, 3)
        assert tmp_db.next_basic_station_track_order(sid) == 4

    def test_song_in_multiple_stations(self, tmp_db):
        s1 = tmp_db.create_basic_station("S1", 1)
        s2 = tmp_db.create_basic_station("S2", 2)
        song = tmp_db.add_song(original_filename="shared.mp3", file_path="/shared.mp3")
        tmp_db.add_song_to_basic_station(s1, song, 1)
        tmp_db.add_song_to_basic_station(s2, song, 1)
        assert len(tmp_db.list_basic_station_songs(s1)) == 1
        assert len(tmp_db.list_basic_station_songs(s2)) == 1

    def test_cascade_delete_station(self, tmp_db):
        sid = tmp_db.create_basic_station("S", 1)
        song = tmp_db.add_song(original_filename="c.mp3", file_path="/c.mp3")
        tmp_db.add_song_to_basic_station(sid, song, 1)
        tmp_db.delete_basic_station(sid)
        tracks = tmp_db.conn.execute(
            "SELECT * FROM basic_station_tracks WHERE station_id = ?;", (sid,)
        ).fetchall()
        assert len(tracks) == 0
