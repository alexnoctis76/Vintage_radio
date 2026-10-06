"""Build the fingerprint-mismatch test library (MCP + local dev).

Creates library slug ``fingerprint-mismatch-test``, station folder **87**, two MP3
tracks. ``apply_mismatch`` can edit files on disk while leaving DB hashes stale.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Tuple

from gui.audio_metadata import compute_file_hash
from gui.database import DatabaseManager
from gui.library_manager import LibraryRegistry
from gui.resource_paths import app_data_dir

LIBRARY_SLUG = "fingerprint-mismatch-test"
LIBRARY_NAME = "Fingerprint mismatch test"
STATION_NAME = "Mismatch test"
STATION_FOLDER = 87
AUDIO_SUBDIR = "fingerprint_mismatch_test_audio"
MISMATCH_MARKER = b"_FP_MISMATCH_TEST_"

TRACK_SPECS: Tuple[Tuple[str, str], ...] = (
    ("track_a.mp3", "Track A"),
    ("track_b.mp3", "Track B"),
)


def _ensure_library_slug(registry: LibraryRegistry, slug: str) -> None:
    try:
        registry.db_path_for(slug)
        return
    except KeyError:
        pass
    created = registry.create_library(LIBRARY_NAME)
    if created != slug:
        raise RuntimeError(
            f"Expected library slug {slug!r}, registry created {created!r}"
        )


def _write_minimal_mp3(path: Path, *, repeat: int = 20) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame = b"\xff\xfb\x90\x00" + b"\x00" * 413
    path.write_bytes(frame * repeat)


def _try_ffmpeg_mp3(path: Path, *, frequency_hz: float, duration_s: float) -> bool:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        ffmpeg,
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"sine=frequency={frequency_hz}:duration={duration_s}",
        "-ac",
        "1",
        "-ar",
        "44100",
        "-b:a",
        "128k",
        str(path),
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True, timeout=30)
        return path.is_file() and path.stat().st_size > 500
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError):
        return False


def _ensure_audio_files(audio_root: Path) -> None:
    for index, (filename, _title) in enumerate(TRACK_SPECS):
        dest = audio_root / filename
        if dest.is_file() and dest.stat().st_size > 200:
            continue
        freq = 440.0 + (index + 1) * 61.0
        duration = 1.5 + index * 0.35
        if not _try_ffmpeg_mp3(dest, frequency_hz=freq, duration_s=duration):
            _write_minimal_mp3(dest, repeat=20 + index * 6)


def _upsert_station_db(
    db: DatabaseManager, audio_root: Path,
) -> int:
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
        for tr in db.list_basic_station_tracks(st_id):
            db.remove_basic_station_track(int(tr["id"]))

    for order, (filename, title) in enumerate(TRACK_SPECS, start=1):
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
            format="mp3",
        )
        db.add_song_to_basic_station(st_id, sid, order)
    db.conn.commit()
    return st_id


def upsert_station(
    *,
    new_library: bool = False,
    library_slug: str = LIBRARY_SLUG,
    set_active: bool = False,
) -> Tuple[Path, str, int, List[Tuple[str, str]]]:
    """Create or refresh the test library and station. Returns (db_path, slug, st_id, specs)."""
    root = app_data_dir()
    registry = LibraryRegistry(root)
    if new_library:
        _ensure_library_slug(registry, library_slug)
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


def apply_mismatch(
    *,
    library_slug: str = LIBRARY_SLUG,
    stale_db_only: bool = True,
    only_first_track: bool = False,
) -> Dict[str, Any]:
    """Append bytes on disk; by default leave library fingerprints unchanged."""
    root = app_data_dir()
    registry = LibraryRegistry(root)
    db_path = registry.db_path_for(library_slug)
    audio_root = root / AUDIO_SUBDIR
    db = DatabaseManager(db_path=db_path, backups_dir=root / "backups")
    edited: List[str] = []
    try:
        row = db.conn.execute(
            "SELECT id FROM basic_stations WHERE folder_number = ? LIMIT 1;",
            (STATION_FOLDER,),
        ).fetchone()
        if row is None:
            raise RuntimeError(f"Station folder {STATION_FOLDER} missing in {library_slug}")
        st_id = int(row[0])
        tracks = db.list_basic_station_songs(st_id)
        for order, song in enumerate(tracks, start=1):
            if only_first_track and order > 1:
                break
            fp = Path(str(song["file_path"] or ""))
            if not fp.is_file():
                continue
            fp.write_bytes(fp.read_bytes() + MISMATCH_MARKER)
            edited.append(fp.name)
            if not stale_db_only:
                new_hash = compute_file_hash(fp)
                new_size = fp.stat().st_size
                db.update_song(
                    int(song["id"]),
                    {
                        "file_hash": new_hash,
                        "file_size": new_size,
                    },
                )
        db.conn.commit()
    finally:
        db.close()
    return {
        "edited": edited,
        "stale_db_only": stale_db_only,
        "only_first_track": only_first_track,
        "audio_root": str(audio_root),
    }
