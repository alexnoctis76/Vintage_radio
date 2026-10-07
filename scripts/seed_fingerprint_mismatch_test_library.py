#!/usr/bin/env python3
"""Seed the fingerprint mismatch test library into an app data directory.

Use this so the **packaged** Vintage Radio.app (or dev) can run manual sync /
fingerprint QA without MCP or ``agent_workshop/``.

Creates:
  - Library **Fingerprint mismatch test** (slug ``fingerprint-mismatch-test``)
  - Station folder **87**, two MP3 tracks
  - Audio under ``<data>/fingerprint_mismatch_test_audio/``

Examples:
  # Same data dir as installed Vintage Radio.app on macOS:
  python scripts/seed_fingerprint_mismatch_test_library.py --packaged

  # Cursor / VS Code: Run and Debug (Cmd+Shift+D) → "Seed fingerprint test (packaged)"
  # Or top-right Run ▷ with the Python interpreter set to .venv (see .vscode/settings.json).

  # Explicit path:
  python scripts/seed_fingerprint_mismatch_test_library.py \\
      --data-dir \"$HOME/Library/Application Support/Vintage Radio\"

  # Also simulate on-disk edits (stale DB hashes) for sync testing:
  python scripts/seed_fingerprint_mismatch_test_library.py --packaged --apply-mismatch
"""

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
    parser.add_argument(
        "--data-dir",
        default="",
        help="Override app data root (sets VINTAGE_RADIO_DATA_DIR for this run)",
    )
    parser.add_argument(
        "--no-set-active",
        action="store_true",
        help="Do not switch the active library to the test library",
    )
    parser.add_argument(
        "--apply-mismatch",
        action="store_true",
        help="Append test bytes to MP3s on disk; DB hashes stay stale (sync QA)",
    )
    parser.add_argument(
        "--only-first-track",
        action="store_true",
        help="With --apply-mismatch, edit only track A (skip-track QA)",
    )
    args = parser.parse_args()

    data_dir = _resolve_data_dir(packaged=args.packaged, explicit=args.data_dir or None)
    data_dir.mkdir(parents=True, exist_ok=True)
    os.environ["VINTAGE_RADIO_DATA_DIR"] = str(data_dir)

    from gui.fingerprint_mismatch_test_fixture import (
        AUDIO_SUBDIR,
        LIBRARY_NAME,
        LIBRARY_SLUG,
        STATION_FOLDER,
        STATION_NAME,
        apply_mismatch,
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
    print(f"Tracks:       {', '.join(t for _f, t in specs)}")
    print(f"Audio folder: {data_dir / AUDIO_SUBDIR}")

    if args.apply_mismatch:
        report = apply_mismatch(
            library_slug=slug,
            stale_db_only=True,
            only_first_track=args.only_first_track,
        )
        print(f"Mismatch sim: edited {report.get('edited')!r} (DB hashes unchanged)")

    print(
        "\nIn Vintage Radio: pick library "
        f"\"{LIBRARY_NAME}\", sync to SD, then use Abort, Update Track, or Skip Track.\n"
        "Apply to all remaining mismatches covers later hash mismatches only.\n"
        "For a conversion failure that must still prompt, seed the mixed library:\n"
        "  python scripts/seed_sync_failure_paths_test_library.py --packaged --prepare-mixed"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
