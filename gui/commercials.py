"""Commercials / sweepers policy: library family, badges, catalog, sync copy."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

COMMERCIALS_FOLDER = 99
FAMILY_BASIC = "basic"
FAMILY_CONDUCTOR = "conductor"
MODE_FOLDER_99 = "folder_99"
MODE_INLINE = "inline"
MODE_BOTH = "both"
COMMERCIALS_MODES = {MODE_FOLDER_99, MODE_INLINE, MODE_BOTH}

BADGE_BASIC_COMMERCIALS = "Default | Commercials"
BADGE_CONDUCTOR = "Conductor"
BADGE_CONDUCTOR_COMMERCIALS = "Conductor | Commercials"

FIRMWARE_PRODUCT_BASIC = "Vintage Radio Default"
FIRMWARE_PRODUCT_CONDUCTOR = "Vintage Radio Conductor"

# Sync bar / help — how commercials play (not DFPlayer "folder" jargon).
COMMERCIALS_STATION_LABEL = "Commercials station"
COMMERCIALS_TAGGED_LABEL = "Tagged tracks"
COMMERCIALS_STATION_TOOLTIP = (
    "Play ads from your Commercials station every few songs "
    f"(Default firmware — {FIRMWARE_PRODUCT_BASIC}). "
    "Use Install Firmware after you change this."
)
COMMERCIALS_TAGGED_TOOLTIP = (
    "Songs you mark as commercials play inside the normal rotation "
    f"({FIRMWARE_PRODUCT_CONDUCTOR} only). "
    "Use Install Firmware after you change this."
)
COMMERCIALS_BOTH_TOOLTIP = (
    f"Use both methods together ({FIRMWARE_PRODUCT_CONDUCTOR} only). "
    "Use Install Firmware after you change this."
)

_TOOLTIP_BASIC = (
    "This library rotates commercials from the Commercials station. "
    "After you change commercials settings, use Install Firmware."
)
_TOOLTIP_CONDUCTOR_COMMERCIALS = (
    "This library plays tagged commercial tracks in the rotation (Conductor). "
    "After you change commercials or tracks, use Install Firmware."
)
_TOOLTIP_BOTH = (
    "This library uses Commercials station rotation and tagged tracks together "
    "(Conductor). After you change commercials or tracks, use Install Firmware."
)


def _mode(meta: Dict[str, Any]) -> Optional[str]:
    if not bool(meta.get("commercials_enabled")):
        return None
    mode = meta.get("commercials_mode")
    return mode if mode in COMMERCIALS_MODES else None


def _is_integrated(meta: Dict[str, Any]) -> bool:
    return _mode(meta) in {MODE_INLINE, MODE_BOTH}


def is_folder_commercials(meta: Dict[str, Any]) -> bool:
    return _mode(meta) in {MODE_FOLDER_99, MODE_BOTH}


def effective_firmware_family(meta: Dict[str, Any]) -> str:
    """Firmware family implied by commercials settings (matches library badge logic)."""
    if not bool(meta.get("commercials_enabled")):
        return FAMILY_BASIC
    mode = meta.get("commercials_mode")
    if mode in {MODE_INLINE, MODE_BOTH}:
        return FAMILY_CONDUCTOR
    if mode == MODE_FOLDER_99:
        return FAMILY_BASIC
    family = str(meta.get("firmware_family") or FAMILY_BASIC).strip().lower()
    return family if family in {FAMILY_BASIC, FAMILY_CONDUCTOR} else FAMILY_BASIC


def firmware_product_name(family: str) -> str:
    """User-facing install firmware name for a family slug."""
    slug = str(family or FAMILY_BASIC).strip().lower()
    if slug == FAMILY_CONDUCTOR:
        return FIRMWARE_PRODUCT_CONDUCTOR
    return FIRMWARE_PRODUCT_BASIC


def library_badge_text(meta: Dict[str, Any]) -> str:
    """Badge from metadata only — never parse the library name.

    Conductor is shown only for tagged-track commercials. Station rotation
    always reads as Default, even if the library used Conductor earlier.
    """
    enabled = bool(meta.get("commercials_enabled"))
    if not enabled:
        return ""
    if _is_integrated(meta):
        return BADGE_CONDUCTOR_COMMERCIALS
    return BADGE_BASIC_COMMERCIALS


def library_badge_tooltip(meta: Dict[str, Any]) -> str:
    if not bool(meta.get("commercials_enabled")):
        return ""
    if _mode(meta) == MODE_BOTH:
        return _TOOLTIP_BOTH
    if _is_integrated(meta):
        return _TOOLTIP_CONDUCTOR_COMMERCIALS
    return _TOOLTIP_BASIC


def apply_commercials_method(
    meta: Dict[str, Any],
    *,
    family: str,
    enabled: bool,
    mode: Optional[str],
    allow_switch: bool = True,
) -> Dict[str, Any]:
    """Apply a commercials method and family. Folder+Integrated together is Conductor."""
    current_family = str(meta.get("firmware_family") or FAMILY_BASIC).strip().lower()
    current_enabled = bool(meta.get("commercials_enabled"))
    family = str(family or FAMILY_BASIC).strip().lower()
    if family not in {FAMILY_BASIC, FAMILY_CONDUCTOR}:
        family = FAMILY_BASIC
    if enabled and mode not in COMMERCIALS_MODES:
        mode = MODE_FOLDER_99 if family != FAMILY_CONDUCTOR else MODE_INLINE
    if enabled and mode == MODE_BOTH:
        family = FAMILY_CONDUCTOR
    elif enabled and mode == MODE_FOLDER_99:
        family = FAMILY_BASIC
    elif enabled and mode == MODE_INLINE:
        family = FAMILY_CONDUCTOR
    else:
        family = FAMILY_BASIC
        mode = None
    if current_family != family and current_enabled and enabled and not allow_switch:
        raise ValueError("Switch firmware family on a copy of this library, or confirm the change.")
    out = dict(meta)
    out["firmware_family"] = family
    out["commercials_enabled"] = bool(enabled)
    out["commercials_mode"] = mode if enabled else None
    return out


def apply_commercials_flags(
    meta: Dict[str, Any],
    *,
    folder: bool,
    inline: bool,
    allow_switch: bool = True,
) -> Dict[str, Any]:
    """Set Folder / Integrated independently. Both together is Conductor-only."""
    if folder and inline:
        mode = MODE_BOTH
        family = FAMILY_CONDUCTOR
        enabled = True
    elif inline:
        mode = MODE_INLINE
        family = FAMILY_CONDUCTOR
        enabled = True
    elif folder:
        mode = MODE_FOLDER_99
        family = FAMILY_BASIC
        enabled = True
    else:
        mode = None
        family = FAMILY_BASIC
        enabled = False
    return apply_commercials_method(
        meta,
        family=family,
        enabled=enabled,
        mode=mode,
        allow_switch=allow_switch,
    )


def can_mark_track_commercial(meta: Dict[str, Any]) -> bool:
    return _is_integrated(meta)


def requires_pico_catalog(meta: Dict[str, Any]) -> bool:
    return _is_integrated(meta)


def sync_result_extras(meta: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "requires_pico_catalog": requires_pico_catalog(meta),
        "firmware_family": str(meta.get("firmware_family") or FAMILY_BASIC),
        "commercials_enabled": bool(meta.get("commercials_enabled")),
        "commercials_mode": meta.get("commercials_mode"),
    }


def post_sync_warning(meta: Dict[str, Any], *, settings_changed: bool = False) -> str:
    if requires_pico_catalog(meta):
        return "SD updated. Use Install Firmware so the radio gets this library."
    if bool(meta.get("commercials_enabled")) and settings_changed:
        return (
            "SD updated. Use Install Firmware if you changed commercials settings."
        )
    if bool(meta.get("commercials_enabled")):
        return "SD updated. Commercials are in the Commercials station."
    return ""


# Matches firmware reset_saved_playback_state_to_defaults() payload.
DEFAULT_ALBUM_STATE_TXT = "1,1;mode=playlist"


def catalog_changed(old: Optional[Dict[str, Any]], new: Dict[str, Any]) -> bool:
    """True if station/track/ad layout or commercials policy differs (or old is missing)."""
    if not isinstance(old, dict):
        return True
    return (old.get("commercials"), old.get("stations")) != (
        new.get("commercials"),
        new.get("stations"),
    )


def push_radio_catalog_to_pico(
    catalog_json: str,
    *,
    read_remote_catalog: Callable[[], Optional[Dict[str, Any]]],
    copy_to_pico: Callable[[Path, str], bool],
) -> Tuple[bool, str]:
    """Write catalog to Pico; reset album_state when layout changed or read failed.

    *read_remote_catalog* returns parsed JSON, or ``None`` on missing/failed read
    (treated as changed — safe default).
    *copy_to_pico* copies a local file to a Pico path (``:path``); returns success.
    """
    try:
        new_catalog = json.loads(catalog_json)
    except json.JSONDecodeError:
        return False, "Invalid catalog JSON"
    if not isinstance(new_catalog, dict):
        return False, "Invalid catalog JSON"

    old_catalog = read_remote_catalog()
    import tempfile

    tmpdir = Path(tempfile.mkdtemp())
    try:
        catalog_file = tmpdir / "radio_catalog.json"
        catalog_file.write_text(catalog_json, encoding="utf-8")
        if not copy_to_pico(catalog_file, ":VintageRadio/radio_catalog.json"):
            return False, "radio_catalog.json copy failed"

        if catalog_changed(old_catalog, new_catalog):
            state_file = tmpdir / "album_state.txt"
            state_file.write_text(DEFAULT_ALBUM_STATE_TXT, encoding="utf-8")
            if not copy_to_pico(state_file, ":VintageRadio/album_state.txt"):
                return False, "album_state.txt reset failed"
        return True, ""
    finally:
        try:
            import shutil

            shutil.rmtree(tmpdir)
        except OSError:
            pass


def build_radio_catalog(
    stations: Iterable[Dict[str, Any]],
    *,
    mode: str,
    interval: int = 5,
) -> Dict[str, Any]:
    if mode not in COMMERCIALS_MODES:
        mode = MODE_FOLDER_99
    cleaned: List[Dict[str, Any]] = []
    for station in stations:
        folder = int(station.get("folder") or 0)
        tracks = []
        for tr in station.get("tracks") or []:
            entry = {
                "t": int(tr.get("t") or tr.get("track") or 0),
                "ad": int(tr.get("ad") or 0),
            }
            if entry["ad"] and int(tr.get("link") or 0):
                entry["link"] = 1
            tracks.append(entry)
        tracks = [t for t in tracks if t["t"] > 0]
        if not tracks:
            continue
        cleaned.append({"folder": folder, "tracks": tracks})
    return {
        "version": 1,
        "commercials": {
            "enabled": mode in {MODE_FOLDER_99, MODE_BOTH},
            "mode": mode,
            "interval": max(1, min(99, int(interval or 5))),
            "folder": COMMERCIALS_FOLDER,
        },
        "stations": cleaned,
    }


def library_shuffle_slots(catalog: Dict[str, Any]) -> List[Tuple[int, int]]:
    return [unit[:2] for unit in library_shuffle_units(catalog)]


def library_shuffle_units(
    catalog: Dict[str, Any],
) -> List[Tuple[int, int, Optional[Tuple[int, int]]]]:
    """Music shuffle slots. Linked commercials attach as (folder, t) pre-roll."""
    units: List[Tuple[int, int, Optional[Tuple[int, int]]]] = []
    comm = catalog.get("commercials") or {}
    skip_reserved = comm.get("mode") in {MODE_FOLDER_99, MODE_BOTH}
    for station in catalog.get("stations") or []:
        folder = int(station.get("folder") or 0)
        if skip_reserved and folder == COMMERCIALS_FOLDER:
            continue
        units.extend(shuffle_units_from_tracks(station.get("tracks") or [], folder))
    return units


def shuffle_units_from_tracks(
    tracks: Iterable[Dict[str, Any]],
    folder: int,
) -> List[Tuple[int, int, Optional[Tuple[int, int]]]]:
    """Walk catalog order and pair linked commercials with the music below."""
    rows = list(tracks or [])
    units: List[Tuple[int, int, Optional[Tuple[int, int]]]] = []
    i = 0
    n = len(rows)
    while i < n:
        tr = rows[i]
        try:
            tnum = int(tr.get("t") or tr.get("track") or tr.get("track_number") or 0)
        except (TypeError, ValueError):
            tnum = 0
        is_ad = bool(int(tr.get("ad") or 0))
        linked = bool(int(tr.get("link") or 0))
        if is_ad:
            nxt = rows[i + 1] if i + 1 < n else None
            nxt_ad = bool(int((nxt or {}).get("ad") or 0)) if nxt is not None else True
            if linked and nxt is not None and not nxt_ad:
                try:
                    music_t = int(
                        nxt.get("t") or nxt.get("track") or nxt.get("track_number") or 0
                    )
                except (TypeError, ValueError):
                    music_t = 0
                if tnum > 0 and music_t > 0:
                    units.append((int(folder), music_t, (int(folder), tnum)))
                i += 2
                continue
            i += 1
            continue
        if tnum > 0:
            units.append((int(folder), tnum, None))
        i += 1
    return units


def expand_linked_move_rows(
    rows: Iterable[int],
    link_flags: Iterable[bool],
) -> List[int]:
    """If a commercial is linked to the next track, moving either moves both."""
    flags = [bool(x) for x in link_flags]
    extra = set(int(r) for r in rows)
    changed = True
    while changed:
        changed = False
        for i, linked in enumerate(flags):
            if not linked:
                continue
            partner = i + 1
            if i in extra or partner in extra:
                if i not in extra:
                    extra.add(i)
                    changed = True
                if partner not in extra:
                    extra.add(partner)
                    changed = True
    return sorted(extra)


def snap_insert_around_links(
    insert_at: int,
    link_flags: Iterable[bool],
    moving: Iterable[int],
) -> int:
    """Do not drop between a staying linked commercial and its music track."""
    flags = [bool(x) for x in link_flags]
    moving_set = {int(x) for x in moving}
    target = int(insert_at)
    for i, linked in enumerate(flags):
        if not linked:
            continue
        if i in moving_set or (i + 1) in moving_set:
            continue
        if target == i + 1:
            return i + 2
    return target


def can_link_commercial_to_next(
    is_commercial: bool,
    next_is_commercial: Optional[bool],
) -> bool:
    return bool(is_commercial) and next_is_commercial is False


def firmware_source_root(install_mode: str, repo_root: Path) -> Path:
    root = Path(repo_root)
    if str(install_mode or "").strip().lower() == FAMILY_CONDUCTOR:
        return root / "firmware" / "conductor"
    return root / "firmware" / "pico"


def firmware_copy_pairs(install_mode: str) -> List[Tuple[str, str]]:
    """Local repo path → Pico remote path for the selected firmware family."""
    if str(install_mode or "").strip().lower() == FAMILY_CONDUCTOR:
        return [
            ("firmware/conductor/main.py", "main.py"),
            ("firmware/conductor/radio_core.py", "radio_core.py"),
            ("firmware/conductor/dfplayer_hardware.py", "components/dfplayer_hardware.py"),
            (
                "firmware/conductor/components/vintage_radio_ipc.py",
                "components/vintage_radio_ipc.py",
            ),
            (
                "firmware/conductor/components/am_wav_loader.py",
                "components/am_wav_loader.py",
            ),
            (
                "firmware/conductor/components/radio_state.py",
                "components/radio_state.py",
            ),
            ("firmware/conductor/pin_config_loader.py", "pin_config_loader.py"),
            ("firmware/conductor/sdcard.py", "sdcard.py"),
        ]
    return [
        ("firmware/pico/main_basic.py", "main.py"),
        ("firmware/radio_core.py", "radio_core.py"),
        ("firmware/pico/dfplayer_hardware.py", "components/dfplayer_hardware.py"),
        (
            "firmware/pico/components/vintage_radio_ipc.py",
            "components/vintage_radio_ipc.py",
        ),
        (
            "firmware/pico/components/am_wav_loader.py",
            "components/am_wav_loader.py",
        ),
        (
            "firmware/pico/components/radio_state.py",
            "components/radio_state.py",
        ),
        ("firmware/pin_config_loader.py", "pin_config_loader.py"),
        ("firmware/pico/sdcard.py", "sdcard.py"),
    ]


def missing_firmware_bundle_paths(
    bundle_root: Path,
    *,
    modes: Tuple[str, ...] = (FAMILY_BASIC, FAMILY_CONDUCTOR),
) -> List[str]:
    """Return repo-relative firmware paths missing under *bundle_root* (PyInstaller root)."""
    root = Path(bundle_root)
    missing: List[str] = []
    for mode in modes:
        for local, _remote in firmware_copy_pairs(mode):
            if not (root / local).is_file():
                missing.append(local)
    return missing


def format_library_combo_label(name: str, meta: Dict[str, Any]) -> str:
    badge = library_badge_text(meta)
    if badge:
        return f"{name}  ·  {badge}"
    return name
