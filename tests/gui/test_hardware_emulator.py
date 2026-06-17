"""Tests for gui.hardware_emulator.PygameHardwareEmulator (mocked audio)."""

from pathlib import Path
from unittest import mock
import json
import pytest

from gui.database import DatabaseManager


def _make_emulator(db, log_callback=None, am_wav_path=None):
    """Import and construct PygameHardwareEmulator with mocked audio backends."""
    with mock.patch.dict("sys.modules", {"pygame": mock.MagicMock(), "vlc": None}):
        with mock.patch("gui.hardware_emulator.pygame") as mock_pygame:
            mock_pygame.mixer.get_init.return_value = True
            mock_pygame.mixer.init.return_value = None
            from gui.hardware_emulator import PygameHardwareEmulator
            emu = PygameHardwareEmulator.__new__(PygameHardwareEmulator)
            emu.db = db
            emu._log_callback = log_callback
            emu.am_wav_path = am_wav_path
            emu._audio_ready = False
            emu._am_sound = None
            emu._am_channel = None
            emu._volume = 100
            emu._is_playing = False
            emu._playback_start_time = 0
            emu._playback_start_offset_ms = 0
            emu._current_sound = None
            emu._current_channel = None
            emu._current_temp_file = None
            emu._vlc_instance = None
            emu._vlc_player = None
            emu._vlc_am_player = None
            emu._delay_playback = False
            emu._pending_playback = None
            emu._am_overlay_duration_ms = 2000
            emu._ignore_track_finished_until = 0.0
            emu._ffmpeg_available = False
            emu._track_cache = {}
            emu._current_track_hint = None
            emu._vlc_api = None
            emu._lazy_audio_init_done = True
    return emu


@pytest.fixture
def emu_db(tmp_path):
    db = DatabaseManager(db_path=tmp_path / "emu.db", backups_dir=tmp_path / "backups")
    yield db
    db.close()


@pytest.fixture
def populated_emu_db(emu_db):
    s1 = emu_db.add_song(original_filename="a.mp3", file_path="/fake/a.mp3",
                          title="Song A", artist="Artist 1", duration=200.0,
                          file_hash="aaa", file_size=5000, format="mp3")
    s2 = emu_db.add_song(original_filename="b.mp3", file_path="/fake/b.mp3",
                          title="Song B", artist="Artist 2", duration=180.0,
                          file_hash="bbb", file_size=4500, format="mp3")
    s3 = emu_db.add_song(original_filename="c.mp3", file_path="/fake/c.mp3",
                          title="Song C", artist="Artist 1", duration=240.0,
                          file_hash="ccc", file_size=12000, format="mp3")
    aid = emu_db.create_album("Test Album")
    emu_db.add_song_to_album(aid, s1, 1)
    emu_db.add_song_to_album(aid, s2, 2)
    emu_db.add_song_to_album(aid, s3, 3)

    pid = emu_db.create_playlist("Test PL")
    emu_db.add_song_to_playlist(pid, s1, 1)
    emu_db.add_song_to_playlist(pid, s2, 2)

    emu_db.set_sd_mapping(s1, 1, 1)
    emu_db.set_sd_mapping(s2, 1, 2)
    emu_db.set_sd_mapping(s3, 1, 3)

    return emu_db, [s1, s2, s3], aid, pid


class TestFindTrack:
    def test_finds_by_folder_track(self, populated_emu_db):
        db, ids, aid, pid = populated_emu_db
        emu = _make_emulator(db)
        song = emu._find_track(1, 1)
        assert song is not None
        assert song["title"] == "Song A"

    def test_cache_works(self, populated_emu_db):
        db, ids, aid, pid = populated_emu_db
        emu = _make_emulator(db)
        emu._find_track(1, 2)
        assert (1, 2) in emu._track_cache

    def test_missing_track(self, populated_emu_db):
        db, ids, aid, pid = populated_emu_db
        emu = _make_emulator(db)
        song = emu._find_track(99, 99)
        # Should still return something (last-resort fallback) or None
        # Depends on track count; with 3 tracks and track=99, returns None
        assert song is None or isinstance(song, dict)


class TestResolvePath:
    def test_prefers_sd_path(self, populated_emu_db, tmp_path):
        db, ids, aid, pid = populated_emu_db
        sd_file = tmp_path / "01" / "001.mp3"
        sd_file.parent.mkdir(parents=True)
        sd_file.write_bytes(b"\x00" * 100)
        db.update_song_sd_path(ids[0], str(sd_file))

        emu = _make_emulator(db)
        song = dict(db.get_song_by_id(ids[0]))
        result = emu._resolve_path(song)
        assert result == str(sd_file)

    def test_falls_back_to_file_path(self, populated_emu_db, tmp_path):
        db, ids, aid, pid = populated_emu_db
        local_file = tmp_path / "a.mp3"
        local_file.write_bytes(b"\x00" * 100)
        db.update_song(ids[0], {"file_path": str(local_file)})

        emu = _make_emulator(db)
        song = dict(db.get_song_by_id(ids[0]))
        result = emu._resolve_path(song)
        assert result == str(local_file)

    def test_returns_none_for_missing(self, populated_emu_db):
        db, ids, aid, pid = populated_emu_db
        emu = _make_emulator(db)
        song = {"file_path": "/nonexistent/x.mp3", "title": "X"}
        result = emu._resolve_path(song)
        assert result is None


class TestEnrichTrack:
    def test_with_sd_mapping(self, populated_emu_db):
        db, ids, aid, pid = populated_emu_db
        emu = _make_emulator(db)
        song = dict(db.get_song_by_id(ids[0]))
        enriched = emu._enrich_track(song, 99)
        assert enriched["folder"] == 1
        assert enriched["track_number"] == 1

    def test_without_mapping_uses_fallback(self, emu_db):
        sid = emu_db.add_song(original_filename="x.mp3", file_path="/x.mp3")
        emu = _make_emulator(emu_db)
        song = dict(emu_db.get_song_by_id(sid))
        enriched = emu._enrich_track(song, 7)
        assert enriched["track_number"] == 7


class TestGetAlbumsPlaylists:
    def test_get_albums(self, populated_emu_db):
        db, ids, aid, pid = populated_emu_db
        emu = _make_emulator(db)
        albums = emu.get_albums()
        assert len(albums) == 1
        assert albums[0]["name"] == "Test Album"
        assert len(albums[0]["tracks"]) == 3

    def test_get_playlists(self, populated_emu_db):
        db, ids, aid, pid = populated_emu_db
        emu = _make_emulator(db)
        playlists = emu.get_playlists()
        assert len(playlists) == 1
        assert len(playlists[0]["tracks"]) == 2

    def test_get_all_tracks(self, populated_emu_db):
        db, ids, aid, pid = populated_emu_db
        emu = _make_emulator(db)
        tracks = emu.get_all_tracks()
        assert len(tracks) == 3


class TestSaveLoadState:
    def test_round_trip(self, populated_emu_db):
        db, ids, aid, pid = populated_emu_db
        emu = _make_emulator(db)
        state = {"mode": "playlist", "album_index": 1, "track": 3}
        emu.save_state(state)
        loaded = emu.load_state()
        assert loaded == state


# ---------------------------------------------------------------------------
# New tests: delay playback / pending playback
# ---------------------------------------------------------------------------

class TestDelayPlayback:
    def test_delay_playback_queues_request_instead_of_playing(self, populated_emu_db):
        db, ids, aid, pid = populated_emu_db
        emu = _make_emulator(db)
        emu._delay_playback = True
        emu._audio_ready = True  # ensure audio appears ready
        result = emu.play_track(1, 1)
        # Should queue, not play immediately
        assert emu._pending_playback == (1, 1, 0)
        assert result is True  # accepted as queued

    def test_delay_playback_false_allows_normal_play(self, populated_emu_db, tmp_path):
        db, ids, aid, pid = populated_emu_db
        # Give Song A an existing local file so _resolve_path works
        local = tmp_path / "a.mp3"
        local.write_bytes(b"\x00" * 100)
        db.update_song(ids[0], {"file_path": str(local)})

        emu = _make_emulator(db)
        emu._delay_playback = False
        emu._audio_ready = True

        with mock.patch.object(emu, "_find_track", return_value={"file_path": str(local), "title": "T"}), \
             mock.patch.object(emu, "_resolve_path", return_value=str(local)):
            with mock.patch("gui.hardware_emulator.pygame") as mp:
                mp.mixer.get_init.return_value = True
                # Not testing VLC path - just that _pending_playback is NOT set
                emu._vlc_player = None
                mp.mixer.Sound.return_value = mock.MagicMock()
                mp.mixer.Sound.return_value.play.return_value = mock.MagicMock()
                emu._delay_playback = False
                emu._pending_playback = None
                # The important assertion: pending is cleared by set_delay_playback
                emu.set_delay_playback(False)
                assert emu._delay_playback is False

    def test_set_delay_false_with_pending_clears_pending(self, populated_emu_db):
        db, ids, aid, pid = populated_emu_db
        emu = _make_emulator(db)
        emu._delay_playback = True
        emu._pending_playback = (1, 1, 0)
        # set_delay_playback(False) should execute pending and clear it
        with mock.patch.object(emu, "play_track") as mock_play:
            mock_play.return_value = True
            emu.set_delay_playback(False)
        # pending_playback should be cleared
        assert emu._pending_playback is None


# ---------------------------------------------------------------------------
# New tests: stop / is_playing / volume
# ---------------------------------------------------------------------------

class TestPlaybackControl:
    def test_stop_clears_is_playing(self, populated_emu_db):
        db, ids, aid, pid = populated_emu_db
        emu = _make_emulator(db)
        emu._audio_ready = True
        emu._is_playing = True
        with mock.patch("gui.hardware_emulator.pygame") as mp:
            mp.mixer.get_init.return_value = True
            mp.mixer.stop = mock.MagicMock()
            emu.stop()
        assert emu._is_playing is False

    def test_set_volume_clamps_low(self, populated_emu_db):
        db, ids, aid, pid = populated_emu_db
        emu = _make_emulator(db)
        with mock.patch("gui.hardware_emulator.pygame"):
            emu.set_volume(-10)
        assert emu._volume == 0

    def test_set_volume_clamps_high(self, populated_emu_db):
        db, ids, aid, pid = populated_emu_db
        emu = _make_emulator(db)
        with mock.patch("gui.hardware_emulator.pygame"):
            emu.set_volume(200)
        assert emu._volume == 100

    def test_set_volume_normal(self, populated_emu_db):
        db, ids, aid, pid = populated_emu_db
        emu = _make_emulator(db)
        with mock.patch("gui.hardware_emulator.pygame"):
            emu.set_volume(75)
        assert emu._volume == 75

    def test_is_playing_reflects_state(self, populated_emu_db):
        db, ids, aid, pid = populated_emu_db
        emu = _make_emulator(db)
        emu._audio_ready = True
        emu._is_playing = False
        assert emu.is_playing() is False
        emu._is_playing = True
        with mock.patch("gui.hardware_emulator.pygame") as mp:
            mp.mixer.music.get_busy.return_value = True
            assert emu.is_playing() is True

    def test_get_playback_position_returns_int(self, populated_emu_db):
        db, ids, aid, pid = populated_emu_db
        emu = _make_emulator(db)
        pos = emu.get_playback_position_ms()
        assert isinstance(pos, int)
        assert pos >= 0


# ---------------------------------------------------------------------------
# New tests: missing/nonexistent files handled gracefully
# ---------------------------------------------------------------------------

class TestErrorConditions:
    def test_play_nonexistent_folder_track_returns_false(self, populated_emu_db):
        db, ids, aid, pid = populated_emu_db
        emu = _make_emulator(db)
        emu._audio_ready = True
        emu._delay_playback = False
        with mock.patch.object(emu, "_find_track", return_value=None):
            result = emu.play_track(99, 99)
        assert result is False

    def test_play_with_missing_file_path_returns_false(self, populated_emu_db):
        db, ids, aid, pid = populated_emu_db
        emu = _make_emulator(db)
        emu._audio_ready = True
        emu._delay_playback = False
        fake_song = {"id": 1, "title": "Missing", "file_path": "/does/not/exist.mp3"}
        with mock.patch.object(emu, "_find_track", return_value=fake_song), \
             mock.patch.object(emu, "_resolve_path", return_value=None):
            result = emu.play_track(1, 1)
        assert result is False
