"""Tracked fingerprint mismatch test library builder."""

from __future__ import annotations

from pathlib import Path

from gui.audio_metadata import file_matches_metadata
from gui.database import DatabaseManager
from gui.fingerprint_mismatch_test_fixture import (
    LIBRARY_SLUG,
    STATION_FOLDER,
    apply_mismatch,
    upsert_station,
)


def test_upsert_and_apply_mismatch_stale_db(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "gui.fingerprint_mismatch_test_fixture.app_data_dir",
        lambda: tmp_path,
    )
    db_path, slug, _st_id, _specs = upsert_station(
        new_library=True,
        library_slug=LIBRARY_SLUG,
        set_active=False,
    )
    assert slug == LIBRARY_SLUG
    assert db_path.is_file()

    report = apply_mismatch(library_slug=slug, stale_db_only=True)
    assert len(report["edited"]) >= 1

    db = DatabaseManager(db_path=db_path, backups_dir=tmp_path / "backups")
    try:
        row = db.conn.execute(
            "SELECT id FROM basic_stations WHERE folder_number = ?;",
            (STATION_FOLDER,),
        ).fetchone()
        assert row is not None
        songs = db.list_basic_station_songs(int(row[0]))
        stale = 0
        for song in songs:
            fp = Path(str(song["file_path"]))
            stored = str(song["file_hash"] or "")
            if stored and not file_matches_metadata(
                fp, song["file_size"], stored
            ):
                stale += 1
        assert stale >= 1
    finally:
        db.close()


def test_mcp_module_imports_fixture():
    from gui.mcp_fingerprint_sync_test import _import_station_builder

    _import_station_builder()
