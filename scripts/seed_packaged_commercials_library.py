#!/usr/bin/env python3
"""Copy the Commercials Test - Folder 99 library into the packaged app's data dir.

The frozen .exe uses platformdirs (not the dev checkout's data/ folder). This script
seeds the MCP acceptance library from the dev workspace so the packaged app can sync
and install firmware with folder_99 / interval 3 settings.

Usage:
    python scripts/seed_packaged_commercials_library.py
    python scripts/seed_packaged_commercials_library.py --all-test-libraries
    python scripts/seed_packaged_commercials_library.py --target-dir "C:/Users/.../Vintage Radio"
"""

from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

DEFAULT_SLUG = "commercials-test-folder-99"
COMMERCIALS_TEST_SLUGS = (
    "commercials-test-folder-99",
    "commercials-test-inline",
    "commercials-test-both",
)
EXPECTED_STATIONS = 3
EXPECTED_AD_FOLDER = 99


def _packaged_data_dir(explicit: Path | None) -> Path:
    if explicit is not None:
        return explicit
    import platformdirs

    return Path(platformdirs.user_data_dir(appname="Vintage Radio", roaming=False))


def _checkpoint_sqlite(db_path: Path) -> None:
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        conn.commit()
    finally:
        conn.close()


def _dev_registry_path() -> Path:
    dev_registry = PROJECT_ROOT / "data" / "libraries" / "libraries.json"
    if not dev_registry.is_file():
        raise FileNotFoundError(f"Dev registry missing: {dev_registry}")
    return dev_registry


def _dev_db_path(slug: str, lib_info: dict) -> Path:
    """Resolve dev SQLite path (matches LibraryRegistry.db_path_for under data/)."""
    dev_root = PROJECT_ROOT / "data"
    rel = str(lib_info.get("filename") or f"libraries/{slug}.db")
    dev_db = dev_root / rel
    if not dev_db.is_file():
        flat = PROJECT_ROOT / "data" / "libraries" / f"{slug}.db"
        if flat.is_file():
            return flat
        raise FileNotFoundError(f"Dev library DB missing: {dev_db}")
    return dev_db


def _verify_library(db_path: Path) -> None:
    from gui.database import DatabaseManager

    db = DatabaseManager(db_path=db_path)
    try:
        stations = [s for s in db.list_basic_stations() if int(s["folder_number"] or 0) != EXPECTED_AD_FOLDER]
        if len(stations) != EXPECTED_STATIONS:
            raise RuntimeError(
                f"Expected {EXPECTED_STATIONS} music stations, found {len(stations)} in {db_path}"
            )
        interval = int(db.get_setting("commercials_interval") or 0)
        if interval != 3:
            db.set_setting("commercials_interval", "3")
        db.set_setting("commercials_enabled", "1")
        db.conn.commit()
    finally:
        db.close()


def seed(*, slug: str, target_dir: Path, set_active: bool = True) -> Path:
    dev_registry_path = _dev_registry_path()
    with dev_registry_path.open("r", encoding="utf-8") as f:
        dev_registry = json.load(f)
    lib_info = dev_registry.get("libraries", {}).get(slug)
    if not lib_info:
        raise KeyError(f"Slug {slug!r} not found in {dev_registry_path}")

    dev_db_path = _dev_db_path(slug, lib_info)

    target_lib_dir = target_dir / "libraries"
    target_lib_dir.mkdir(parents=True, exist_ok=True)
    rel = str(lib_info.get("filename") or f"libraries/{slug}.db")
    if rel.startswith("libraries/"):
        target_db = target_dir / rel
    else:
        target_db = target_lib_dir / f"{slug}.db"
    target_db.parent.mkdir(parents=True, exist_ok=True)

    _checkpoint_sqlite(dev_db_path)
    shutil.copy2(dev_db_path, target_db)
    for suffix in ("-wal", "-shm"):
        sidecar = dev_db_path.with_name(dev_db_path.name + suffix)
        if sidecar.is_file():
            try:
                sidecar.unlink()
            except OSError:
                pass

    _verify_library(target_db)

    registry_path = target_lib_dir / "libraries.json"
    if registry_path.is_file():
        with registry_path.open("r", encoding="utf-8") as f:
            packaged = json.load(f)
    else:
        packaged = {"active": "default", "libraries": {}}

    packaged.setdefault("libraries", {})[slug] = dict(lib_info)
    if set_active:
        packaged["active"] = slug
    tmp = registry_path.with_suffix(".json.tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(packaged, f, indent=2)
    tmp.replace(registry_path)
    return target_db


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Seed commercials MCP library into packaged app data")
    parser.add_argument("--slug", default=DEFAULT_SLUG)
    parser.add_argument(
        "--all-test-libraries",
        action="store_true",
        help="seed folder_99, inline, and both layouts (from build_test_libraries.py)",
    )
    parser.add_argument(
        "--target-dir",
        type=Path,
        default=None,
        help="Packaged app data dir (default: platformdirs user_data_dir)",
    )
    args = parser.parse_args(argv)

    audio_root = PROJECT_ROOT / "agent_workshop" / "test_library_audio" / "folder"
    if not audio_root.is_dir():
        print(
            "Error: test audio missing. Run: python agent_workshop/build_test_libraries.py",
            file=sys.stderr,
        )
        return 1

    slugs = list(COMMERCIALS_TEST_SLUGS) if args.all_test_libraries else [args.slug]
    target = _packaged_data_dir(args.target_dir)
    print(f"Target data dir: {target}")
    seeded: list[str] = []
    try:
        for i, slug in enumerate(slugs):
            db_path = seed(slug=slug, target_dir=target, set_active=(i == len(slugs) - 1))
            seeded.append(slug)
            print(f"Seeded {slug!r} -> {db_path}")
    except (FileNotFoundError, KeyError, RuntimeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print(f"Registry: {target / 'libraries' / 'libraries.json'}")
    if len(seeded) == 1:
        print("Restart the packaged app and confirm the library picker shows Commercials Test - Folder 99.")
    else:
        print(
            "Restart the packaged app — you should see Commercials Test - Folder 99, "
            "Inline, and Both in the library picker."
        )
    print("Then sync to SD and Install Firmware from that library before running MCP acceptance.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
