#!/usr/bin/env python3
"""Seed the MP3 Sync Test library into the packaged app's data dir.

The frozen app uses platformdirs (not the dev checkout ``data/`` folder). This
copies the dev ``mp3-sync-test`` library, copies audio fixtures beside it, and
rewrites song paths so sync works without the repo checkout path.

Usage:
    python scripts/seed_packaged_mp3_sync_test_library.py
    python scripts/seed_packaged_mp3_sync_test_library.py --no-set-active
    python scripts/seed_packaged_mp3_sync_test_library.py --target-dir "%LOCALAPPDATA%/Vintage Radio/Vintage Radio"
"""

from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

SLUG = "mp3-sync-test"
STATION_NAME = "MP3 Sync Test"
STATION_FOLDER = 88
EXPECTED_TRACKS = 9
AUDIO_DIRNAME = "mp3_sync_test_audio"


def _packaged_data_dir(explicit: Path | None) -> Path:
    if explicit is not None:
        return explicit.expanduser()
    import platformdirs

    return Path(platformdirs.user_data_dir(appname="Vintage Radio", roaming=False))


def _checkpoint_sqlite(db_path: Path) -> None:
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        conn.commit()
    finally:
        conn.close()


def _ensure_dev_library() -> None:
    script = PROJECT_ROOT / "agent_workshop" / "create_mp3_sync_test_station.py"
    if not script.is_file():
        raise FileNotFoundError(f"Missing station builder: {script}")
    proc = subprocess.run(
        [sys.executable, str(script), "--new-library"],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        raise RuntimeError(f"create_mp3_sync_test_station failed: {detail[:500]}")


def _dev_source_paths() -> tuple[Path, Path]:
    dev_lib_dir = PROJECT_ROOT / "data" / "libraries"
    dev_registry = dev_lib_dir / "libraries.json"
    dev_db = dev_lib_dir / f"{SLUG}.db"
    if not dev_registry.is_file():
        raise FileNotFoundError(f"Dev registry missing: {dev_registry}")
    if not dev_db.is_file():
        raise FileNotFoundError(f"Dev library DB missing: {dev_db}")
    return dev_registry, dev_db


def _copy_audio_fixtures(target_dir: Path) -> Path:
    src = PROJECT_ROOT / "agent_workshop" / AUDIO_DIRNAME
    if not src.is_dir():
        raise FileNotFoundError(
            f"Test audio missing at {src}. Run agent_workshop/create_mp3_sync_test_station.py"
        )
    dst = target_dir / AUDIO_DIRNAME
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)
    return dst


def _rewrite_song_paths(db_path: Path, audio_dir: Path) -> None:
    from gui.audio_metadata import compute_file_hash
    from gui.database import DatabaseManager

    db = DatabaseManager(db_path=db_path, backups_dir=db_path.parent / "backups")
    try:
        rows = db.conn.execute(
            "SELECT id, original_filename, file_path FROM songs ORDER BY id;"
        ).fetchall()
        for row in rows:
            name = str(row["original_filename"] or "").strip()
            if not name:
                continue
            new_path = (audio_dir / name).resolve()
            if not new_path.is_file():
                raise FileNotFoundError(f"Fixture missing after copy: {new_path}")
            db.update_song(
                int(row["id"]),
                {
                    "file_path": str(new_path),
                    "file_hash": compute_file_hash(new_path),
                    "file_size": new_path.stat().st_size,
                },
            )
        stations = db.list_basic_stations()
        test = [
            s for s in stations if int(s["folder_number"]) == STATION_FOLDER
        ]
        if len(test) != 1:
            raise RuntimeError(
                f"Expected one station at folder {STATION_FOLDER}, found {len(test)}"
            )
        tracks = db.list_basic_station_songs(int(test[0]["id"]))
        if len(tracks) != EXPECTED_TRACKS:
            raise RuntimeError(
                f"Expected {EXPECTED_TRACKS} tracks on {STATION_NAME!r}, found {len(tracks)}"
            )
        db.conn.commit()
    finally:
        db.close()


def seed(*, target_dir: Path, set_active: bool) -> Path:
    _ensure_dev_library()
    dev_registry_path, dev_db_path = _dev_source_paths()
    with dev_registry_path.open("r", encoding="utf-8") as f:
        dev_registry = json.load(f)
    lib_info = dev_registry.get("libraries", {}).get(SLUG)
    if not lib_info:
        raise KeyError(f"Slug {SLUG!r} not found in {dev_registry_path}")

    target_dir.mkdir(parents=True, exist_ok=True)
    target_lib_dir = target_dir / "libraries"
    target_lib_dir.mkdir(parents=True, exist_ok=True)
    target_db = target_lib_dir / f"{SLUG}.db"

    _checkpoint_sqlite(dev_db_path)
    shutil.copy2(dev_db_path, target_db)
    for suffix in ("-wal", "-shm"):
        sidecar = dev_db_path.with_name(dev_db_path.name + suffix)
        if sidecar.is_file():
            try:
                sidecar.unlink()
            except OSError:
                pass

    audio_dir = _copy_audio_fixtures(target_dir)
    _rewrite_song_paths(target_db, audio_dir)

    registry_path = target_lib_dir / "libraries.json"
    if registry_path.is_file():
        with registry_path.open("r", encoding="utf-8") as f:
            packaged = json.load(f)
    else:
        packaged = {"active": "default", "libraries": {}}

    packaged.setdefault("libraries", {})[SLUG] = dict(lib_info)
    if set_active:
        packaged["active"] = SLUG
    tmp = registry_path.with_suffix(".json.tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(packaged, f, indent=2)
    tmp.replace(registry_path)
    return target_db


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Seed MP3 Sync Test library into packaged app data"
    )
    parser.add_argument(
        "--target-dir",
        type=Path,
        default=None,
        help="Packaged app data dir (default: platformdirs user_data_dir)",
    )
    parser.add_argument(
        "--no-set-active",
        action="store_true",
        help="Register library without switching the active library",
    )
    args = parser.parse_args(argv)

    target = _packaged_data_dir(args.target_dir)
    print(f"Target data dir: {target}")
    try:
        db_path = seed(target_dir=target, set_active=not args.no_set_active)
    except (FileNotFoundError, KeyError, RuntimeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print(f"Seeded library {SLUG!r} ({STATION_NAME}, folder {STATION_FOLDER:02d})")
    print(f"  DB: {db_path}")
    print(f"  Audio: {target / AUDIO_DIRNAME}")
    print(f"  Registry: {target / 'libraries' / 'libraries.json'}")
    if not args.no_set_active:
        print("  Active library set to MP3 Sync Test")
    print("Restart the packaged app, pick MP3 Sync Test, and sync to SD to exercise all cases.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
