"""Sync failure paths test library builder."""

from __future__ import annotations

from gui.sync_failure_paths_test_fixture import (
    LIBRARY_SLUG,
    prepare_mixed_failure_state,
    upsert_station,
)


def test_upsert_and_prepare_mixed_state(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "gui.sync_failure_paths_test_fixture.app_data_dir",
        lambda: tmp_path,
    )
    db_path, slug, _st_id, specs = upsert_station(
        new_library=True,
        library_slug=LIBRARY_SLUG,
        set_active=False,
    )
    assert slug == LIBRARY_SLUG
    assert len(specs) == 3
    report = prepare_mixed_failure_state(library_slug=slug)
    assert report["stale_mp3_count"] == 2
    assert len(report["edited_mp3"]) == 2
