"""Mixed sync failure scenarios for manual QA and automated tests.

Station folder **88**, three tracks in sync order:

1. **Hash A** — MP3 with stale library fingerprint (hash mismatch prompt)
2. **Bad convert** — corrupt WAV (conversion failure prompt; DB hash matches file)
3. **Hash B** — MP3 with stale fingerprint (second hash mismatch)

Use this to confirm **Apply to all remaining mismatches** on a hash dialog only
auto-handles later ``hash_mismatch`` events, not ``conversion_failure`` (or
``copy_failure``).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Tuple

from gui.audio_metadata import compute_file_hash
from gui.database import DatabaseManager
from gui.fingerprint_mismatch_test_fixture import (
    MISMATCH_MARKER,
    _try_ffmpeg_mp3,
    _write_minimal_mp3,
)
from gui.library_manager import LibraryRegistry
from gui.resource_paths import app_data_dir

LIBRARY_SLUG = "sync-failure-paths-test"
LIBRARY_NAME = "Sync failure paths test"
STATION_NAME = "Failure paths"
STATION_FOLDER = 88
AUDIO_SUBDIR = "sync_failure_paths_test_audio"

TRACK_SPECS: Tuple[Tuple[str, str, str], ...] = (
    ("hash_a.mp3", "Hash A", "mp3"),
    ("bad_convert.wav", "Bad convert", "wav"),
    ("hash_b.mp3", "Hash B", "mp3"),
)


def _write_corrupt_wav(path: Path) -> None:
    """WAV-shaped bytes ffmpeg/lib cannot decode (conversion failure, not hash mismatch)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(
        b"RIFF$\x00\x00\x00WAVEfmt \x10\x00\x00\x00\x01\x00\x01\x00"
        b"\x44\xac\x00\x00\x88X\x01\x00\x02\x00\x10\x00data\x00\x00\x00\x00"
    )


def _ensure_mp3(path: Path, *, frequency_hz: float, minimal_repeat: int) -> None:
    if path.is_file() and path.stat().st_size > 500:
        return
    if not _try_ffmpeg_mp3(path, frequency_hz=frequency_hz, duration_s=1.2):
        # Distinct payloads so add_song hash dedup does not collapse two tracks.
        _write_minimal_mp3(path, repeat=minimal_repeat)


def _ensure_audio_files(audio_root: Path) -> None:
    _ensure_mp3(audio_root / "hash_a.mp3", frequency_hz=523.0, minimal_repeat=22)
    _write_corrupt_wav(audio_root / "bad_convert.wav")
    _ensure_mp3(audio_root / "hash_b.mp3", frequency_hz=659.0, minimal_repeat=31)


def _upsert_station_db(db: DatabaseManager, audio_root: Path) -> int:
    row = db.conn.execute(
        "SELECT id FROM basic_stations WHERE folder_number = ? LIMIT 1;",
        (STATION_FOLDER,),
    ).fetchone()
    if row is None:
        st_id = db.create_basic_station(STATION_NAME, STATION_FOLDER)
    else:
        st_id = int(row[0])
        db.conn.execute(
            "UPDATE basic_stations SET name = ? WHERE id = ?;",
            (STATION_NAME, st_id),
        )
        db.conn.commit()
        track_rows = db.list_basic_station_tracks(st_id)
        song_ids = {int(tr["song_id"]) for tr in track_rows}
        for tr in track_rows:
            db.remove_basic_station_track(int(tr["id"]))
        for sid in song_ids:
            db.conn.execute("DELETE FROM songs WHERE id = ?;", (sid,))
        db.conn.commit()

    for order, (filename, title, fmt) in enumerate(TRACK_SPECS, start=1):
        fp = audio_root / filename
        if not fp.is_file():
            raise FileNotFoundError(fp)
        file_hash = compute_file_hash(fp)
        size = fp.stat().st_size
        sid = db.add_song(
            original_filename=filename,
            file_path=str(fp.resolve()),
            title=title,
            file_hash=file_hash,
            file_size=size,
            format=fmt,
        )
        db.add_song_to_basic_station(st_id, sid, order)
    db.conn.commit()
    return st_id


def upsert_station(
    *,
    new_library: bool = False,
    library_slug: str = LIBRARY_SLUG,
    set_active: bool = False,
) -> Tuple[Path, str, int, List[Tuple[str, str, str]]]:
    root = app_data_dir()
    registry = LibraryRegistry(root)
    if new_library:
        _ensure_library_slug(registry, library_slug, LIBRARY_NAME)
    db_path = registry.db_path_for(library_slug)
    audio_root = root / AUDIO_SUBDIR
    _ensure_audio_files(audio_root)

    db = DatabaseManager(db_path=db_path, backups_dir=root / "backups")
    try:
        st_id = _upsert_station_db(db, audio_root)
    finally:
        db.close()

    if set_active:
        registry.set_active(library_slug)
    return db_path, library_slug, st_id, list(TRACK_SPECS)


def _stale_hash_song_ids(db: DatabaseManager, st_id: int) -> List[int]:
    ids: List[int] = []
    for song in db.list_basic_station_songs(st_id):
        name = Path(str(song["file_path"] or "")).name.lower()
        if name.endswith(".mp3"):
            ids.append(int(song["id"]))
    return ids


def prepare_mixed_failure_state(
    *,
    library_slug: str = LIBRARY_SLUG,
) -> Dict[str, Any]:
    """Refresh audio, sync DB hashes for WAV, stale fingerprints on both MP3s."""
    root = app_data_dir()
    registry = LibraryRegistry(root)
    db_path = registry.db_path_for(library_slug)
    audio_root = root / AUDIO_SUBDIR
    _ensure_audio_files(audio_root)

    db = DatabaseManager(db_path=db_path, backups_dir=root / "backups")
    edited_mp3: List[str] = []
    try:
        row = db.conn.execute(
            "SELECT id FROM basic_stations WHERE folder_number = ? LIMIT 1;",
            (STATION_FOLDER,),
        ).fetchone()
        if row is None:
            raise RuntimeError(
                f"Station folder {STATION_FOLDER} missing; run upsert_station first"
            )
        st_id = int(row[0])

        wav_path = audio_root / "bad_convert.wav"
        _write_corrupt_wav(wav_path)
        for song in db.list_basic_station_songs(st_id):
            fp = Path(str(song["file_path"] or ""))
            if fp.name.lower() == "bad_convert.wav":
                db.update_song(
                    int(song["id"]),
                    {
                        "file_hash": compute_file_hash(wav_path),
                        "file_size": wav_path.stat().st_size,
                    },
                )
                break

        for song in db.list_basic_station_songs(st_id):
            fp = Path(str(song["file_path"] or ""))
            if not fp.name.lower().endswith(".mp3"):
                continue
            if fp.is_file():
                fp.write_bytes(fp.read_bytes() + MISMATCH_MARKER)
                edited_mp3.append(fp.name)

        db.conn.commit()
        stale_ids = _stale_hash_song_ids(db, st_id)
    finally:
        db.close()

    return {
        "library_slug": library_slug,
        "station_folder": STATION_FOLDER,
        "edited_mp3": edited_mp3,
        "stale_mp3_count": len(stale_ids),
        "audio_root": str(audio_root),
        "manual_qa": (
            "Sync station 88: on first hash mismatch choose Update Track with "
            "'Apply to all remaining mismatches'. Expect a conversion prompt on "
            "'Bad convert', then Hash B should update without a second hash dialog."
        ),
    }


def _ensure_library_slug(registry: LibraryRegistry, slug: str, name: str) -> None:
    try:
        registry.db_path_for(slug)
        return
    except KeyError:
        pass
    created = registry.create_library(name)
    if created != slug:
        raise RuntimeError(f"Expected library slug {slug!r}, registry created {created!r}")
