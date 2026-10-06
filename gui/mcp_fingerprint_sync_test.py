"""Automated fingerprint / hash-mismatch sync checks for MCP debug."""

from __future__ import annotations

import sys
import tempfile
import traceback
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from gui.audio_metadata import compute_file_hash, file_matches_metadata
from gui.database import DatabaseManager
from gui.library_manager import LibraryRegistry
from gui.sd_manager import SDManager

LIBRARY_SLUG = "fingerprint-mismatch-test"
STATION_FOLDER = 87


def _import_station_builder():
    from gui.fingerprint_mismatch_test_fixture import (
        STATION_NAME,
        apply_mismatch,
        upsert_station,
    )

    return STATION_NAME, apply_mismatch, upsert_station


def _station_songs(db: DatabaseManager) -> List[Any]:
    row = db.conn.execute(
        "SELECT id FROM basic_stations WHERE folder_number = ? LIMIT 1;",
        (STATION_FOLDER,),
    ).fetchone()
    if row is None:
        return []
    return db.list_basic_station_songs(int(row["id"]))


def _mismatch_count(db: DatabaseManager) -> int:
    n = 0
    seen: set[int] = set()
    for song in _station_songs(db):
        song_id = int(song["id"])
        if song_id in seen:
            continue
        seen.add(song_id)
        fp = Path(str(song["file_path"] or ""))
        if not fp.is_file():
            n += 1
            continue
        stored = str(song["file_hash"] or "").strip()
        if stored and not file_matches_metadata(fp, song["file_size"], stored):
            n += 1
    return n


def _sync_with_policy(
    sd_mgr: SDManager,
    sd_root: Path,
    on_mismatch: str,
) -> Dict[str, Any]:
    policy = on_mismatch.strip().lower()
    if policy not in ("accept_file", "accept_all", "skip", "skip_all", "stop"):
        policy = "accept_file"

    def _on_failure(info: Dict[str, str]) -> str:
        if str(info.get("kind") or "") != "hash_mismatch":
            return "skip"
        if policy == "skip_all":
            return "skip_all"
        if policy == "stop":
            return "stop"
        return policy

    return sd_mgr.sync_library_basic(
        sd_root,
        force_clean=True,
        on_sync_failure=_on_failure,
    )


def run_fingerprint_sync_test(
    *,
    setup: bool = True,
    apply_mismatch: bool = True,
    stale_db_only: bool = False,
    on_mismatch: str = "accept_file",
    switch_library: bool = True,
    switch_library_fn: Optional[Callable[[str], None]] = None,
    sd_root: Optional[Path] = None,
    log: Optional[Callable[[str], None]] = None,
) -> Dict[str, Any]:
    """Headless sync exercise against the fingerprint mismatch test station."""
    _log = log or (lambda _m: None)
    report: Dict[str, Any] = {
        "ok": False,
        "library_slug": LIBRARY_SLUG,
        "on_mismatch": on_mismatch,
        "steps": [],
    }

    try:
        station_name, apply_mismatch_fn, upsert_station_fn = _import_station_builder()

        if setup:
            _log("Creating / refreshing fingerprint mismatch test library…")
            db_path, slug, _station_id, _specs = upsert_station_fn(
                new_library=True,
                library_slug=LIBRARY_SLUG,
                set_active=switch_library,
            )
            report["steps"].append({"step": "setup", "ok": True, "db_path": str(db_path)})
        else:
            slug = LIBRARY_SLUG

        if switch_library:
            reg = LibraryRegistry()
            try:
                reg.db_path_for(slug)
            except KeyError:
                report["error"] = "library_missing"
                return report
            if switch_library_fn is not None:
                switch_library_fn(slug)
            else:
                reg.set_active(slug)
            report["steps"].append({"step": "switch_library", "ok": True, "active": slug})

        if apply_mismatch:
            _log("Applying on-disk edit simulation (library fingerprints unchanged)…")
            policy = on_mismatch.strip().lower()
            only_first = policy == "skip"
            use_stale_db = stale_db_only or only_first
            mismatch_report = apply_mismatch_fn(
                library_slug=slug,
                stale_db_only=use_stale_db,
                only_first_track=only_first,
            )
            report["steps"].append(
                {"step": "apply_mismatch", "ok": True, "detail": mismatch_report}
            )

        reg = LibraryRegistry()
        db_path = reg.db_path_for(slug)
        db = DatabaseManager(db_path=db_path, backups_dir=db_path.parent / "backups")
        try:
            before_mismatch = _mismatch_count(db)
            report["mismatch_before_sync"] = before_mismatch
            if before_mismatch <= 0:
                report["error"] = "expected_hash_mismatch_before_sync"
                report["steps"].append({"step": "precheck", "ok": False})
                return report
            report["steps"].append({"step": "precheck", "ok": True, "count": before_mismatch})

            sd_target = sd_root
            temp_dir: Optional[tempfile.TemporaryDirectory[str]] = None
            if sd_target is None:
                temp_dir = tempfile.TemporaryDirectory(prefix="vr_fp_sync_")
                sd_target = Path(temp_dir.name)
            sd_target.mkdir(parents=True, exist_ok=True)

            sd_mgr = SDManager(db)
            _log(f"Running basic sync (on_mismatch={on_mismatch!r})…")
            try:
                sync_result = _sync_with_policy(sd_mgr, sd_target, on_mismatch)
            except RuntimeError as exc:
                if "stopped by user" in str(exc).lower():
                    report["steps"].append({"step": "sync", "ok": True, "stopped_by_user": True})
                    report["ok"] = on_mismatch.strip().lower() == "stop"
                    return report
                raise

            copied = int(sync_result.get("copied", 0))
            skipped = int(sync_result.get("skipped", 0))
            report["sync"] = {"copied": copied, "skipped": skipped}
            report["steps"].append({"step": "sync", "ok": True, "copied": copied, "skipped": skipped})

            after_mismatch = _mismatch_count(db)
            report["mismatch_after_sync"] = after_mismatch

            slot_a = sd_target / f"{STATION_FOLDER:02d}" / "001.mp3"
            slot_b = sd_target / f"{STATION_FOLDER:02d}" / "002.mp3"
            report["sd_files"] = {
                "001.mp3": slot_a.is_file(),
                "002.mp3": slot_b.is_file(),
            }

            policy = on_mismatch.strip().lower()
            if policy == "accept_file":
                report["ok"] = (
                    copied >= 2
                    and slot_a.is_file()
                    and slot_b.is_file()
                    and after_mismatch == 0
                )
                if not report["ok"]:
                    report["error"] = "accept_file_expectation_failed"
            elif policy in ("skip", "skip_all"):
                report["ok"] = (
                    copied >= 1
                    and not slot_a.is_file()
                    and slot_b.is_file()
                    and after_mismatch >= 1
                )
                if not report["ok"]:
                    report["error"] = "skip_expectation_failed"
            elif policy == "stop":
                report["ok"] = copied == 0 and not slot_a.is_file()
            else:
                report["ok"] = False
                report["error"] = "unknown_policy"

            if temp_dir is not None and not sd_root:
                report["sd_root"] = str(sd_target)
        finally:
            db.close()

        _log(f"Fingerprint sync test finished ok={report['ok']}")
    except Exception as exc:
        report["ok"] = False
        report["error"] = "exception"
        report["detail"] = str(exc)
        report["traceback"] = traceback.format_exc()
        _log(f"Fingerprint sync test failed: {exc}")

    return report


def run_fingerprint_reimport_check(
    *,
    log: Optional[Callable[[str], None]] = None,
) -> Dict[str, Any]:
    """After mismatch: re-add same paths via add_song should refresh fingerprints."""
    from gui.audio_metadata import extract_metadata
    from gui.fingerprint_mismatch_test_fixture import apply_mismatch, upsert_station

    upsert_station_fn = upsert_station
    _log = log or (lambda _m: None)
    out: Dict[str, Any] = {"ok": False, "steps": []}
    reg = LibraryRegistry()
    slug = LIBRARY_SLUG
    db_path = reg.db_path_for(slug)
    db = DatabaseManager(db_path=db_path, backups_dir=db_path.parent / "backups")
    try:
        upsert_station_fn(new_library=False, library_slug=slug, set_active=False)
        apply_mismatch(library_slug=slug, stale_db_only=True)
        before = _mismatch_count(db)
        out["mismatch_before"] = before
        if before <= 0:
            out["error"] = "expected_mismatch"
            return out

        refreshed = 0
        for song in _station_songs(db):
            fp = Path(str(song["file_path"] or ""))
            meta = extract_metadata(fp)
            new_id = db.add_song(
                original_filename=fp.name,
                file_path=str(fp.resolve()),
                title=meta.get("title") or fp.stem,
                artist=meta.get("artist"),
                duration=meta.get("duration"),
                file_hash=compute_file_hash(fp),
                file_size=fp.stat().st_size,
                format=meta.get("format"),
            )
            if new_id == int(song["id"]):
                refreshed += 1
        after = _mismatch_count(db)
        out["mismatch_after"] = after
        out["reused_same_ids"] = refreshed
        out["ok"] = refreshed >= 1 and after == 0
        out["steps"].append({"step": "reimport_refresh", "ok": out["ok"]})
        _log(f"Re-import check ok={out['ok']} (refreshed={refreshed}, after={after})")
    except Exception as exc:
        out["error"] = str(exc)
        out["traceback"] = traceback.format_exc()
    finally:
        db.close()
    return out
