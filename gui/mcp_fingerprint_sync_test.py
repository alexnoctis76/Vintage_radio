"""Automated fingerprint / hash-mismatch sync checks for MCP debug.

Scenarios cover every sync-failure dialog choice:

* Hash mismatch modal — Update Track, Skip Track, Abort, and both with
  **Apply to all remaining mismatches**.
* Conversion modal — Ignore, Skip rest, Abort.
* Apply-all on a hash mismatch must still prompt for a later conversion
  failure (and the reverse: Ignore on a conversion failure must not answer
  later hash mismatches).
"""

from __future__ import annotations

import sys
import tempfile
import traceback
from collections import Counter
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

# on_mismatch values from older callers map onto a single scenario.
_ON_MISMATCH_TO_SCENARIO = {
    "accept_file": "update",
    "accept_all": "update_remaining",
    "skip": "skip",
    "skip_all": "skip_remaining",
    "stop": "abort",
}

# answers: kind -> dialog action returned the first time that kind is prompted.
# Later hash mismatches are auto-handled only when the action was accept_all
# or skip_all. Other kinds always prompt.
FINGERPRINT_SCENARIOS: Dict[str, Dict[str, Any]] = {
    "update": {
        "label": "Update Track",
        "library": "fingerprint",
        "answers": {"hash_mismatch": "accept_file"},
        "expect_kinds": {"hash_mismatch": 2},
        "slots": {"001.mp3": True, "002.mp3": True},
        "mismatch_after": 0,
    },
    "skip": {
        "label": "Skip Track",
        "library": "fingerprint",
        "only_first_track": True,
        "answers": {"hash_mismatch": "skip"},
        "expect_kinds": {"hash_mismatch": 1},
        "slots": {"001.mp3": False, "002.mp3": True},
        "mismatch_after_min": 1,
    },
    "abort": {
        "label": "Abort",
        "library": "fingerprint",
        "answers": {"hash_mismatch": "stop"},
        "expect_kinds": {"hash_mismatch": 1},
        "stopped": True,
        "slots": {"001.mp3": False},
    },
    "update_remaining": {
        "label": "Update Track + apply remaining mismatches",
        "library": "fingerprint",
        "answers": {"hash_mismatch": "accept_all"},
        "expect_kinds": {"hash_mismatch": 1},
        "slots": {"001.mp3": True, "002.mp3": True},
        "mismatch_after": 0,
    },
    "skip_remaining": {
        "label": "Skip Track + apply remaining mismatches",
        "library": "fingerprint",
        "answers": {"hash_mismatch": "skip_all"},
        "expect_kinds": {"hash_mismatch": 1},
        "slots": {"001.mp3": False, "002.mp3": False},
        "mismatch_after_min": 2,
    },
    "update_remaining_keeps_conversion": {
        "label": "Apply-all update does not cover a conversion failure",
        "library": "mixed",
        "answers": {
            "hash_mismatch": "accept_all",
            "conversion_failure": "skip",
            "copy_failure": "skip",
        },
        "expect_kinds": {"hash_mismatch": 1, "conversion_failure": 1},
        "slots": {"001.mp3": True, "002.mp3": False, "003.mp3": True},
    },
    "skip_remaining_keeps_conversion": {
        "label": "Apply-all skip does not cover a conversion failure",
        "library": "mixed",
        "answers": {
            "hash_mismatch": "skip_all",
            "conversion_failure": "skip",
            "copy_failure": "skip",
        },
        "expect_kinds": {"hash_mismatch": 1, "conversion_failure": 1},
        "slots": {"001.mp3": False, "002.mp3": False, "003.mp3": False},
    },
    "conversion_ignore": {
        "label": "Ignore on a conversion failure does not answer hash mismatches",
        "library": "mixed",
        "answers": {
            "hash_mismatch": "accept_file",
            "conversion_failure": "skip",
            "copy_failure": "skip",
        },
        "expect_kinds": {"hash_mismatch": 2, "conversion_failure": 1},
        "slots": {"001.mp3": True, "002.mp3": False, "003.mp3": True},
    },
    "conversion_skip_rest": {
        "label": "Skip rest on a conversion failure",
        "library": "mixed",
        "answers": {
            "hash_mismatch": "accept_file",
            "conversion_failure": "skip_all",
            "copy_failure": "skip",
        },
        "expect_kinds_at_least": {"conversion_failure": 1, "hash_mismatch": 1},
        "slots": {"002.mp3": False},
    },
    "conversion_abort": {
        "label": "Abort on a conversion failure",
        "library": "mixed",
        "answers": {
            "hash_mismatch": "accept_file",
            "conversion_failure": "stop",
            "copy_failure": "stop",
        },
        "expect_kinds_at_least": {"conversion_failure": 1},
        "stopped": True,
        "slots": {"002.mp3": False},
    },
}


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


def _mismatch_count_in_folder(db: DatabaseManager, folder: int) -> int:
    row = db.conn.execute(
        "SELECT id FROM basic_stations WHERE folder_number = ? LIMIT 1;",
        (folder,),
    ).fetchone()
    if row is None:
        return 0
    n = 0
    seen: set[int] = set()
    for song in db.list_basic_station_songs(int(row["id"])):
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


def _mismatch_count(db: DatabaseManager) -> int:
    return _mismatch_count_in_folder(db, STATION_FOLDER)


def list_fingerprint_scenarios() -> Dict[str, str]:
    """Scenario id -> short label for MCP ``scenario=list``."""
    return {name: str(spec["label"]) for name, spec in FINGERPRINT_SCENARIOS.items()}


def resolve_fingerprint_scenario(scenario: str, on_mismatch: str = "accept_file") -> str:
    """Map a scenario name or legacy ``on_mismatch`` policy onto a scenario id."""
    name = (scenario or "").strip().lower()
    if name in ("", "sync"):
        policy = (on_mismatch or "accept_file").strip().lower()
        return _ON_MISMATCH_TO_SCENARIO.get(policy, "update")
    return name


def _station_folder_for(library: str) -> int:
    if library == "mixed":
        from gui.sync_failure_paths_test_fixture import STATION_FOLDER as mixed_folder

        return int(mixed_folder)
    return STATION_FOLDER


def _prepare_scenario_library(
    spec: Dict[str, Any],
    *,
    setup: bool,
    apply_mismatch: bool,
    switch_library: bool,
) -> str:
    """Create the library for ``spec`` and return its slug."""
    if spec["library"] == "mixed":
        from gui.sync_failure_paths_test_fixture import (
            LIBRARY_SLUG as mixed_slug,
            prepare_mixed_failure_state,
            upsert_station,
        )

        if setup:
            _db_path, slug, _st_id, _specs = upsert_station(
                new_library=True,
                library_slug=mixed_slug,
                set_active=switch_library,
            )
        else:
            slug = mixed_slug
        if apply_mismatch:
            prepare_mixed_failure_state(library_slug=slug)
        return slug

    _station_name, apply_mismatch_fn, upsert_station_fn = _import_station_builder()
    if setup:
        _db_path, slug, _st_id, _specs = upsert_station_fn(
            new_library=True,
            library_slug=LIBRARY_SLUG,
            set_active=switch_library,
        )
    else:
        slug = LIBRARY_SLUG
    if apply_mismatch:
        apply_mismatch_fn(
            library_slug=slug,
            stale_db_only=True,
            only_first_track=bool(spec.get("only_first_track")),
        )
    return slug


def _sync_with_answers(
    sd_mgr: SDManager,
    sd_root: Path,
    answers: Dict[str, str],
    prompts: List[Dict[str, str]],
) -> Dict[str, Any]:
    """Run sync. Each failure kind uses its own answer — hash apply-all is not reused."""

    def _on_failure(info: Dict[str, str]) -> str:
        kind = str(info.get("kind") or "")
        prompts.append(
            {
                "kind": kind,
                "name": str(info.get("name") or ""),
            }
        )
        action = answers.get(kind)
        if action is None:
            return "skip"
        return action

    return sd_mgr.sync_library_basic(
        sd_root,
        force_clean=True,
        on_sync_failure=_on_failure,
    )


def _kinds_match(prompts: List[Dict[str, str]], spec: Dict[str, Any]) -> bool:
    counts = Counter(p.get("kind") for p in prompts)
    expected = spec.get("expect_kinds")
    if expected is not None and dict(counts) != dict(expected):
        return False
    at_least = spec.get("expect_kinds_at_least") or {}
    for kind, minimum in at_least.items():
        if counts.get(kind, 0) < int(minimum):
            return False
    return True


def _slot_presence(sd_root: Path, folder: int, slots: Dict[str, bool]) -> Dict[str, bool]:
    """Which expected slot files exist. Callers compare this to the wanted map."""
    return {name: (sd_root / f"{folder:02d}" / name).is_file() for name in slots}


def run_fingerprint_sync_test(
    *,
    setup: bool = True,
    apply_mismatch: bool = True,
    stale_db_only: bool = True,
    on_mismatch: str = "accept_file",
    scenario: str = "",
    switch_library: bool = True,
    switch_library_fn: Optional[Callable[[str], None]] = None,
    sd_root: Optional[Path] = None,
    log: Optional[Callable[[str], None]] = None,
) -> Dict[str, Any]:
    """Headless sync exercise for one fingerprint scenario, or every scenario.

    ``scenario="all"`` runs the full dialog matrix. ``scenario="list"`` returns
    the catalog. A legacy ``on_mismatch`` policy selects one scenario when
    ``scenario`` is empty or ``"sync"``.

    ``stale_db_only`` is accepted so older callers still parse. Named scenarios
    always leave library hashes stale; passing False does not refresh them.
    """
    _log = log or (lambda _m: None)
    requested = (scenario or "").strip().lower()
    if requested == "list":
        return {"ok": True, "scenarios": list_fingerprint_scenarios()}
    if requested == "all":
        results: List[Dict[str, Any]] = []
        for name in FINGERPRINT_SCENARIOS:
            child_root = None if sd_root is None else sd_root / name
            one = run_fingerprint_sync_test(
                setup=setup,
                apply_mismatch=apply_mismatch,
                scenario=name,
                switch_library=switch_library,
                switch_library_fn=switch_library_fn,
                sd_root=child_root,
                log=log,
            )
            results.append({"scenario": name, "ok": bool(one.get("ok")), "report": one})
        return {
            "ok": all(item["ok"] for item in results),
            "scenario": "all",
            "results": results,
        }

    scenario_id = resolve_fingerprint_scenario(requested, on_mismatch)
    spec = FINGERPRINT_SCENARIOS.get(scenario_id)
    report: Dict[str, Any] = {
        "ok": False,
        "scenario": scenario_id,
        "on_mismatch": on_mismatch,
        "steps": [],
        "prompts": [],
    }
    if spec is None:
        report["error"] = "unknown_scenario"
        report["known"] = list_fingerprint_scenarios()
        return report

    if not stale_db_only:
        _log(
            "stale_db_only=False is ignored; scenarios always leave library hashes stale"
        )
    folder = _station_folder_for(str(spec["library"]))
    prompts: List[Dict[str, str]] = []

    try:
        _log(f"Fingerprint scenario {scenario_id}: {spec['label']}")
        slug = _prepare_scenario_library(
            spec,
            setup=setup,
            apply_mismatch=apply_mismatch,
            switch_library=switch_library,
        )
        report["library_slug"] = slug
        report["steps"].append({"step": "setup", "ok": True, "library": slug})

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

        reg = LibraryRegistry()
        db_path = reg.db_path_for(slug)
        db = DatabaseManager(db_path=db_path, backups_dir=db_path.parent / "backups")
        try:
            before_mismatch = _mismatch_count_in_folder(db, folder)
            report["mismatch_before_sync"] = before_mismatch
            if apply_mismatch and before_mismatch <= 0:
                report["error"] = "expected_hash_mismatch_before_sync"
                report["steps"].append({"step": "precheck", "ok": False})
                return report
            report["steps"].append(
                {"step": "precheck", "ok": True, "count": before_mismatch}
            )

            sd_target = sd_root
            temp_dir: Optional[tempfile.TemporaryDirectory[str]] = None
            if sd_target is None:
                temp_dir = tempfile.TemporaryDirectory(prefix="vr_fp_sync_")
                sd_target = Path(temp_dir.name)
            sd_target.mkdir(parents=True, exist_ok=True)

            sd_mgr = SDManager(db)
            stopped = False
            sync_result: Dict[str, Any] = {}
            try:
                sync_result = _sync_with_answers(
                    sd_mgr,
                    sd_target,
                    dict(spec["answers"]),
                    prompts,
                )
            except RuntimeError as exc:
                if "stopped by user" not in str(exc).lower():
                    raise
                stopped = True

            report["prompts"] = list(prompts)
            report["stopped"] = stopped
            copied = int(sync_result.get("copied", 0)) if sync_result else 0
            skipped = int(sync_result.get("skipped", 0)) if sync_result else 0
            report["sync"] = {"copied": copied, "skipped": skipped, "stopped": stopped}
            report["steps"].append(
                {"step": "sync", "ok": True, "copied": copied, "skipped": skipped}
            )

            after_mismatch = _mismatch_count_in_folder(db, folder)
            report["mismatch_after_sync"] = after_mismatch
            slot_spec = dict(spec.get("slots") or {})
            present = _slot_presence(sd_target, folder, slot_spec)
            report["sd_files"] = present

            kinds_ok = _kinds_match(prompts, spec)
            slots_ok = all(present[name] is want for name, want in slot_spec.items())
            stopped_ok = bool(spec.get("stopped")) == stopped
            after_ok = True
            if "mismatch_after" in spec:
                after_ok = after_mismatch == int(spec["mismatch_after"])
            if "mismatch_after_min" in spec:
                after_ok = after_mismatch >= int(spec["mismatch_after_min"])

            report["ok"] = bool(kinds_ok and slots_ok and stopped_ok and after_ok)
            if not report["ok"]:
                report["error"] = "scenario_expectation_failed"
                report["checks"] = {
                    "kinds": kinds_ok,
                    "slots": slots_ok,
                    "stopped": stopped_ok,
                    "mismatch_after": after_ok,
                }
            if temp_dir is not None:
                report["sd_root"] = str(sd_target)
        finally:
            db.close()

        _log(f"Fingerprint scenario {scenario_id} finished ok={report['ok']}")
    except Exception as exc:
        report["ok"] = False
        report["error"] = "exception"
        report["detail"] = str(exc)
        report["prompts"] = list(prompts)
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
