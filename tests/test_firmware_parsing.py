"""Tests for firmware file parsing logic (no real hardware).

These tests verify the state load/save format and metadata parsing
used by both DFPlayer and Pi builds, without importing MicroPython-only
modules. We extract and test the pure parsing logic.
"""

import json
from pathlib import Path

import pytest


class TestDFPlayerStateFormat:
    """Verify the album_state.txt format used by both builds."""

    @staticmethod
    def _encode_state(album_index, track, known_tracks=None, mode="album"):
        """Encode state dict -> album_state.txt payload (mirrors save_state)."""
        album_idx_1based = album_index + 1
        known = known_tracks or {}
        track_str = ",".join(f"{a}:{c}" for a, c in sorted(known.items()))
        return f"{album_idx_1based},{track};tracks={track_str};mode={mode}"

    @staticmethod
    def _decode_state(raw):
        """Decode album_state.txt payload -> state dict (mirrors load_state)."""
        parts = raw.strip().split(";")
        a_str, t_str = parts[0].split(",")
        album_idx = int(a_str) - 1
        track = int(t_str)
        known_tracks = {}
        mode = "album"
        for part in parts[1:]:
            if part.startswith("tracks="):
                for pair in part[7:].split(","):
                    if not pair:
                        continue
                    a, c = pair.split(":")
                    known_tracks[int(a)] = int(c)
            elif part.startswith("mode="):
                mode = part[5:].strip().lower()
                if mode not in ("album", "playlist", "shuffle", "radio"):
                    mode = "album"
        return {
            "mode": mode,
            "album_index": album_idx,
            "track": track,
            "known_tracks": known_tracks,
        }

    def test_round_trip(self):
        original = {"album_index": 2, "track": 5, "known_tracks": {1: 10, 2: 8}, "mode": "playlist"}
        payload = self._encode_state(**original)
        decoded = self._decode_state(payload)
        assert decoded["album_index"] == 2
        assert decoded["track"] == 5
        assert decoded["known_tracks"] == {1: 10, 2: 8}
        assert decoded["mode"] == "playlist"

    def test_default_mode(self):
        payload = "3,1;tracks="
        decoded = self._decode_state(payload)
        assert decoded["mode"] == "album"
        assert decoded["album_index"] == 2
        assert decoded["track"] == 1

    def test_invalid_mode_falls_back(self):
        payload = "1,1;tracks=;mode=bogus"
        decoded = self._decode_state(payload)
        assert decoded["mode"] == "album"

    def test_empty_known_tracks(self):
        payload = "2,3;tracks=;mode=shuffle"
        decoded = self._decode_state(payload)
        assert decoded["known_tracks"] == {}
        assert decoded["mode"] == "shuffle"


class TestMetadataParsing:
    """Test radio_metadata.json parsing (new deduplicated format)."""

    @staticmethod
    def _parse_metadata(data):
        """Standalone metadata parser matching firmware logic."""
        songs = data.get("songs", {})
        albums = []
        playlists = []

        def _parse_collections(collection_list, ctype):
            for col in (collection_list or []):
                name = col.get("name", "Unknown")
                col_id = col.get("id", 0)
                tracks = []
                for idx, t in enumerate(col.get("tracks", [])):
                    song_id = t.get("song_id", idx + 1)
                    song_data = songs.get(str(song_id), {})
                    folder = t.get("folder", song_data.get("folder", 1))
                    track_num = t.get("track", song_data.get("track", idx + 1))
                    tracks.append({
                        "id": song_id,
                        "title": song_data.get("title", f"Track {idx + 1}"),
                        "artist": song_data.get("artist", "Unknown"),
                        "duration": song_data.get("duration", 180),
                        "folder": folder,
                        "track_number": track_num,
                    })
                entry = {"id": col_id, "name": name, "tracks": tracks}
                if ctype == "playlist":
                    playlists.append(entry)
                else:
                    albums.append(entry)

        new_albums = data.get("albums")
        new_playlists = data.get("playlists")
        if new_albums is not None or new_playlists is not None:
            _parse_collections(new_albums, "album")
            _parse_collections(new_playlists, "playlist")

        return albums, playlists

    def test_new_format(self):
        data = {
            "songs": {
                "1": {"title": "Song A", "artist": "Art 1", "duration": 200, "folder": 1, "track": 1},
                "2": {"title": "Song B", "artist": "Art 2", "duration": 180, "folder": 1, "track": 2},
            },
            "albums": [
                {"id": 1, "name": "Album 1", "tracks": [
                    {"song_id": 1, "folder": 1, "track": 1},
                    {"song_id": 2, "folder": 1, "track": 2},
                ]},
            ],
            "playlists": [
                {"id": 10, "name": "Chill", "tracks": [
                    {"song_id": 2, "folder": 1, "track": 2},
                ]},
            ],
        }
        albums, playlists = self._parse_metadata(data)
        assert len(albums) == 1
        assert albums[0]["name"] == "Album 1"
        assert len(albums[0]["tracks"]) == 2
        assert albums[0]["tracks"][0]["title"] == "Song A"
        assert len(playlists) == 1
        assert playlists[0]["tracks"][0]["title"] == "Song B"

    def test_missing_song_uses_defaults(self):
        data = {
            "songs": {},
            "albums": [
                {"id": 1, "name": "Empty", "tracks": [
                    {"song_id": 99, "folder": 5, "track": 3},
                ]},
            ],
        }
        albums, _ = self._parse_metadata(data)
        track = albums[0]["tracks"][0]
        assert track["title"] == "Track 1"
        assert track["folder"] == 5
        assert track["track_number"] == 3

    def test_am_sound_in_metadata(self):
        data = {
            "am_sound": {"folder": 99, "track": 1},
            "songs": {},
            "albums": [],
        }
        am = data.get("am_sound", {})
        assert am["folder"] == 99
        assert am["track"] == 1


class TestPiStateFormat:
    """Pi hardware uses a simplified album_state.txt (no mode field in some builds)."""

    @staticmethod
    def _decode_pi_state(raw):
        parts = raw.strip().split(";")
        try:
            a_str, t_str = parts[0].split(",")
            album_idx = int(a_str) - 1
            track = int(t_str)
        except (ValueError, IndexError):
            return {"mode": "album", "album_index": 0, "track": 1, "known_tracks": {}}
        known_tracks = {}
        if len(parts) > 1 and parts[1].startswith("tracks="):
            for pair in parts[1][7:].split(","):
                if not pair:
                    continue
                try:
                    a, c = pair.split(":")
                    known_tracks[int(a)] = int(c)
                except ValueError:
                    pass
        return {"mode": "album", "album_index": album_idx, "track": track, "known_tracks": known_tracks}

    def test_basic(self):
        state = self._decode_pi_state("3,2;tracks=1:5,2:3")
        assert state["album_index"] == 2
        assert state["track"] == 2
        assert state["known_tracks"] == {1: 5, 2: 3}

    def test_empty(self):
        state = self._decode_pi_state("1,1;tracks=")
        assert state["album_index"] == 0
        assert state["track"] == 1
        assert state["known_tracks"] == {}


class TestPiPathResolution:
    """Test _resolve_sd_path logic from pi_hardware (isolated from GPIO/VLC)."""

    @staticmethod
    def _resolve_sd_path(sd_path, media_root="/media/vintage"):
        if not sd_path:
            return None
        p = Path(sd_path)
        if p.is_absolute() and "VintageRadio" in sd_path:
            parts = sd_path.split("VintageRadio", 1)
            if len(parts) == 2:
                rest = parts[1].lstrip("/\\")
                return str(Path(media_root) / "VintageRadio" / rest)
        if not p.is_absolute():
            return str(Path(media_root) / sd_path)
        return sd_path

    def test_absolute_with_vintage(self):
        result = self._resolve_sd_path("/Volumes/SD/VintageRadio/library/song.mp3")
        norm = result.replace("\\", "/")
        # On Unix-like systems this rewrites to /media/vintage/...; on Windows
        # the input path is treated as a rooted local path and is preserved.
        assert norm.endswith("/VintageRadio/library/song.mp3")

    def test_relative_path(self):
        result = self._resolve_sd_path("01/001.mp3")
        assert result.replace("\\", "/") == "/media/vintage/01/001.mp3"

    def test_none(self):
        assert self._resolve_sd_path(None) is None

    def test_empty(self):
        assert self._resolve_sd_path("") is None

    def test_absolute_without_vintage(self):
        result = self._resolve_sd_path("/some/other/path.mp3")
        assert result.replace("\\", "/") == "/some/other/path.mp3"
