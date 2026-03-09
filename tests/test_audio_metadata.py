"""Tests for gui.audio_metadata (hashing, extraction, matching)."""

import hashlib
from pathlib import Path

import pytest

from gui.audio_metadata import compute_file_hash, extract_metadata, file_matches_metadata


class TestComputeFileHash:
    def test_known_content(self, tmp_path):
        f = tmp_path / "known.bin"
        data = b"vintage radio test data"
        f.write_bytes(data)
        expected = hashlib.sha256(data).hexdigest()
        assert compute_file_hash(f) == expected

    def test_empty_file(self, tmp_path):
        f = tmp_path / "empty.bin"
        f.write_bytes(b"")
        expected = hashlib.sha256(b"").hexdigest()
        assert compute_file_hash(f) == expected

    def test_larger_file(self, tmp_path):
        f = tmp_path / "big.bin"
        data = b"x" * (2 * 1024 * 1024)
        f.write_bytes(data)
        expected = hashlib.sha256(data).hexdigest()
        assert compute_file_hash(f) == expected


class TestExtractMetadata:
    def test_plain_file_fallback(self, tmp_path):
        """File with no tags: title falls back to stem."""
        f = tmp_path / "not_audio.xyz"
        f.write_bytes(b"\x00" * 100)
        meta = extract_metadata(f)
        assert meta["title"] == "not_audio"
        assert meta["original_filename"] == "not_audio.xyz"
        assert meta["file_path"] == str(f)
        assert meta["file_size"] == 100
        assert meta["format"] == "xyz"

    def test_valid_mp3_with_mutagen(self, sample_audio_file):
        """A minimal MP3: mutagen should recognise the format."""
        meta = extract_metadata(sample_audio_file)
        assert meta["original_filename"] == sample_audio_file.name
        assert meta["file_size"] > 0
        assert meta["format"] == "mp3"


class TestFileMatchesMetadata:
    def test_matching_file(self, tmp_path):
        f = tmp_path / "match.bin"
        data = b"hello world"
        f.write_bytes(data)
        h = hashlib.sha256(data).hexdigest()
        assert file_matches_metadata(f, len(data), h) is True

    def test_wrong_size(self, tmp_path):
        f = tmp_path / "size.bin"
        f.write_bytes(b"data")
        assert file_matches_metadata(f, 999, None) is False

    def test_wrong_hash(self, tmp_path):
        f = tmp_path / "hash.bin"
        f.write_bytes(b"data")
        assert file_matches_metadata(f, 4, "badhash") is False

    def test_missing_file(self, tmp_path):
        f = tmp_path / "nope.bin"
        assert file_matches_metadata(f, 10, "x") is False

    def test_no_expected_constraints(self, tmp_path):
        f = tmp_path / "any.bin"
        f.write_bytes(b"anything")
        assert file_matches_metadata(f, None, None) is True
