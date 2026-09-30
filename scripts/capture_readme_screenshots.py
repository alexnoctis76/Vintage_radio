#!/usr/bin/env python3
"""Capture main-window screenshots for README.md (run from repo root).

Usage:
    python scripts/capture_readme_screenshots.py
    python scripts/capture_readme_screenshots.py --exe "dist/Vintage Radio/Vintage Radio.exe"
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "images" / "readme"


def _capture_from_python(*, hero_only: bool = False) -> int:
    sys.path.insert(0, str(ROOT))
    from PyQt6 import QtCore, QtWidgets

    from gui.radio_manager import MainWindow, configure_vintage_app_rendering
    from gui.session_log import init_session_logging, install_messagebox_session_logging
    from gui.widgets.dialogs.vintage_message import VintageMessageBox

    # Block modal dialogs during capture (conversion tools missing, etc.).
    VintageMessageBox.information = staticmethod(lambda *a, **k: None)  # type: ignore[method-assign]
    VintageMessageBox.warning = staticmethod(lambda *a, **k: None)  # type: ignore[method-assign]
    VintageMessageBox.critical = staticmethod(lambda *a, **k: None)  # type: ignore[method-assign]

    init_session_logging(app_version="screenshot")
    install_messagebox_session_logging()

    app = QtWidgets.QApplication(sys.argv)
    configure_vintage_app_rendering(app)

    window = MainWindow(dev_mode=False)
    window._check_for_updates_on_startup = lambda: None  # type: ignore[method-assign]
    window.resize(1440, 920)
    window.show()
    app.processEvents()

    def _assign_physical_sd_card() -> None:
        """Point storage at the real SD/USB volume, not cloud drives like Google Drive."""
        from gui.sd_manager import SDManager, SYNC_TARGET_VOLUME_LABEL

        candidates = SDManager.detect_sd_roots()
        if not candidates:
            window.detect_basic_sd_root()
            app.processEvents()
            window._refresh_basic_sd_capacity()
            return

        def _score(path_label: tuple) -> tuple:
            path, label = path_label
            lab = (label or "").upper()
            name = str(path).upper()
            skip = 0
            if "GOOGLE DRIVE" in lab or "ONEDRIVE" in lab or "DROPBOX" in lab:
                skip = 1
            vintage = 0
            if SYNC_TARGET_VOLUME_LABEL in lab or lab.startswith("VINTAGER"):
                vintage = 2
            try:
                import psutil

                gb = psutil.disk_usage(str(path)).total / (1024**3)
            except OSError:
                gb = 9999.0
            # Prefer small removable volumes (typical SD) over huge HDDs/cloud.
            return (skip, -vintage, gb)

        candidates.sort(key=_score)
        path, label = candidates[0]
        if _score(candidates[0])[0] == 1 and len(candidates) > 1:
            path, label = candidates[1]
        window.sd_root = str(path)
        window.sd_label = (label or "").strip() or path.name
        window.db.set_setting("sd_root", window.sd_root)
        window.db.set_setting("sd_label", window.sd_label)
        window._update_sd_root_label()
        if hasattr(window, "_check_basic_sd_sync"):
            window._check_basic_sd_sync()
        window._refresh_basic_sd_capacity()
        app.processEvents()
        QtCore.QThread.msleep(500)

    def _prepare_hero_load_music() -> None:
        """Real library + station with visible tracks (README hero shot)."""
        slug = "actual-music"
        if getattr(window, "_lib_registry", None) is not None:
            if window._lib_registry.active_library() != slug:
                window._switch_library(slug)
                app.processEvents()
        window._on_sidebar_nav(0)
        sidebar = getattr(window, "_sidebar", None)
        if sidebar is not None:
            sidebar.set_active(0)
        _assign_physical_sd_card()
        app.processEvents()
        station_list = getattr(window, "_basic_station_list", None)
        if station_list is None:
            return
        needle = "avenged"
        for row in range(station_list.count()):
            item = station_list.item(row)
            if item is None:
                continue
            label = (item.text() or "").lower()
            if needle in label:
                station_list.setCurrentRow(row)
                window._sync_basic_station_tracks_from_selection()
                app.processEvents()
                QtCore.QThread.msleep(600)
                return
        # Fallback: first music station with tracks
        for row in range(station_list.count()):
            item = station_list.item(row)
            if item and "0 tracks" not in (item.text() or ""):
                station_list.setCurrentRow(row)
                window._sync_basic_station_tracks_from_selection()
                app.processEvents()
                QtCore.QThread.msleep(600)
                return

    shots: list[tuple[int, str]] = [(0, "01-load-music.png")]
    if not hero_only:
        shots.extend(
            [
                (1, "02-install-firmware.png"),
                (2, "03-tools.png"),
                (3, "04-settings.png"),
                (4, "05-help.png"),
            ]
        )

    def grab_all() -> None:
        OUT.mkdir(parents=True, exist_ok=True)
        sidebar = getattr(window, "_sidebar", None)
        for idx, name in shots:
            window._on_sidebar_nav(idx)
            if sidebar is not None:
                sidebar.set_active(idx)
            if idx == 0:
                _prepare_hero_load_music()
            else:
                app.processEvents()
                QtCore.QThread.msleep(400)
            pix = window.grab()
            path = OUT / name
            if not pix.save(str(path)):
                print(f"Failed to save {path}", file=sys.stderr)
            else:
                print(f"Wrote {path}")
        # pygame teardown can segfault on exit; screenshots are already on disk.
        os._exit(0)

    QtCore.QTimer.singleShot(1200, grab_all)
    return app.exec()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--exe",
        type=Path,
        default=None,
        help="Optional packaged exe path (not used yet; python capture only)",
    )
    parser.add_argument(
        "--hero-only",
        action="store_true",
        help="Only recapture 01-load-music.png",
    )
    args = parser.parse_args()
    if args.exe and args.exe.is_file():
        print("Note: --exe ignored; using in-process MainWindow for consistent sizing.")
    return _capture_from_python(hero_only=args.hero_only)


if __name__ == "__main__":
    raise SystemExit(main())
