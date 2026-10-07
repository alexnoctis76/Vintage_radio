#!/usr/bin/env python3
"""Seed mixed hash + conversion failure test library for packaged app QA."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _resolve_data_dir(*, packaged: bool, explicit: str | None) -> Path:
    if explicit:
        return Path(explicit).expanduser().resolve()
    if packaged:
        import platformdirs

        return Path(platformdirs.user_data_dir(appname="Vintage Radio", roaming=False))
    return Path(os.environ.get("VINTAGE_RADIO_DATA_DIR", "") or ROOT / "data").expanduser()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--packaged",
        action="store_true",
        help="Write to platformdirs user data (same as frozen Vintage Radio.app)",
    )
    parser.add_argument("--data-dir", default="", help="Override app data root")
    parser.add_argument(
        "--no-set-active",
        action="store_true",
        help="Do not switch active library to the sync failure paths library",
    )
    parser.add_argument(
        "--prepare-mixed",
        action="store_true",
        help="After upsert, stale MP3 hashes + corrupt WAV (ready to sync)",
    )
    args = parser.parse_args()

    data_dir = _resolve_data_dir(packaged=args.packaged, explicit=args.data_dir or None)
    data_dir.mkdir(parents=True, exist_ok=True)
    os.environ["VINTAGE_RADIO_DATA_DIR"] = str(data_dir)

    from gui.sync_failure_paths_test_fixture import (
        AUDIO_SUBDIR,
        LIBRARY_NAME,
        LIBRARY_SLUG,
        STATION_FOLDER,
        STATION_NAME,
        prepare_mixed_failure_state,
        upsert_station,
    )

    db_path, slug, st_id, specs = upsert_station(
        new_library=True,
        library_slug=LIBRARY_SLUG,
        set_active=not args.no_set_active,
    )
    print(f"Data dir:     {data_dir}")
    print(f"Library:      {LIBRARY_NAME!r} ({slug})")
    print(f"Database:     {db_path}")
    print(f"Station:      {STATION_NAME!r} folder {STATION_FOLDER} (id={st_id})")
    print(f"Tracks:       {', '.join(t for _f, t, _fmt in specs)}")
    print(f"Audio folder: {data_dir / AUDIO_SUBDIR}")

    if args.prepare_mixed:
        report = prepare_mixed_failure_state(library_slug=slug)
        print(f"Prepared:     {report.get('edited_mp3')} stale MP3s, WAV corrupt")
        print(report.get("manual_qa", ""))

    print(
        "\nSync station "
        f"{STATION_FOLDER}: Hash A, then a corrupt WAV, then Hash B.\n"
        "On the hash dialog, Apply to all remaining mismatches must not answer\n"
        "the conversion dialog (Abort / Ignore / Skip rest) for Bad convert.\n"
        "Ignore on that conversion dialog must still ask about Hash B."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
