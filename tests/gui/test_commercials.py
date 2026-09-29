"""Fail-first tests for commercials policy, badges, catalog, and sync warnings."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from gui.commercials import (
    COMMERCIALS_FOLDER,
    DEFAULT_ALBUM_STATE_TXT,
    FAMILY_BASIC,
    FAMILY_CONDUCTOR,
    FIRMWARE_PRODUCT_BASIC,
    FIRMWARE_PRODUCT_CONDUCTOR,
    MODE_BOTH,
    MODE_FOLDER_99,
    MODE_INLINE,
    apply_commercials_flags,
    apply_commercials_method,
    build_radio_catalog,
    can_mark_track_commercial,
    catalog_changed,
    effective_firmware_family,
    firmware_product_name,
    is_folder_commercials,
    firmware_copy_pairs,
    firmware_source_root,
    missing_firmware_bundle_paths,
    library_badge_text,
    library_badge_tooltip,
    library_shuffle_slots,
    library_shuffle_units,
    expand_linked_move_rows,
    push_radio_catalog_to_pico,
    snap_insert_around_links,
    can_link_commercial_to_next,
    post_sync_warning,
    requires_pico_catalog,
    shuffle_units_from_tracks,
    sync_result_extras,
)
from gui.widgets.common.delegates import (
    TRACK_COMMERCIAL_ROLE,
    configure_track_title_item,
    track_is_commercial,
)


def _meta(**kwargs):
    base = {
        "firmware_family": FAMILY_BASIC,
        "commercials_enabled": False,
        "commercials_mode": None,
    }
    base.update(kwargs)
    return base


class TestEffectiveFirmwareFamily:
    def test_stale_conductor_with_folder_commercials_is_basic(self):
        meta = _meta(
            firmware_family=FAMILY_CONDUCTOR,
            commercials_enabled=True,
            commercials_mode=MODE_FOLDER_99,
        )
        assert effective_firmware_family(meta) == FAMILY_BASIC
        assert library_badge_text(meta) == "Default | Commercials"

    def test_integrated_commercials_is_conductor(self):
        meta = _meta(
            commercials_enabled=True,
            commercials_mode=MODE_INLINE,
        )
        assert effective_firmware_family(meta) == FAMILY_CONDUCTOR

    def test_firmware_product_names_match_install_labels(self):
        assert firmware_product_name(FAMILY_BASIC) == FIRMWARE_PRODUCT_BASIC
        assert firmware_product_name(FAMILY_CONDUCTOR) == FIRMWARE_PRODUCT_CONDUCTOR


class TestLibraryBadges:
    def test_basic_without_commercials_has_no_badge(self):
        assert library_badge_text(_meta()) == ""

    def test_basic_with_commercials_badge(self):
        assert library_badge_text(_meta(commercials_enabled=True, commercials_mode=MODE_FOLDER_99)) == (
            "Default | Commercials"
        )

    def test_conductor_without_integrated_has_no_badge(self):
        assert library_badge_text(_meta(firmware_family=FAMILY_CONDUCTOR)) == ""

    def test_stale_conductor_folder_mode_reads_as_basic(self):
        assert library_badge_text(
            _meta(
                firmware_family=FAMILY_CONDUCTOR,
                commercials_enabled=True,
                commercials_mode=MODE_FOLDER_99,
            )
        ) == "Default | Commercials"

    def test_conductor_with_integrated_commercials_badge(self):
        assert (
            library_badge_text(
                _meta(
                    firmware_family=FAMILY_CONDUCTOR,
                    commercials_enabled=True,
                    commercials_mode=MODE_INLINE,
                )
            )
            == "Conductor | Commercials"
        )

    def test_badge_does_not_parse_library_name(self):
        assert library_badge_text(_meta(name="Jazz [Conductor]")) == ""

    def test_basic_commercials_tooltip_mentions_install_firmware(self):
        tip = library_badge_tooltip(
            _meta(commercials_enabled=True, commercials_mode=MODE_FOLDER_99)
        )
        assert "install firmware" in tip.lower()
        assert "ads" not in tip.lower()
        assert "inline" not in tip.lower()
        assert "conductor" not in tip.lower()

    def test_integrated_tooltip_mentions_install_firmware(self):
        tip = library_badge_tooltip(
            _meta(
                firmware_family=FAMILY_CONDUCTOR,
                commercials_enabled=True,
                commercials_mode=MODE_INLINE,
            )
        )
        assert "conductor" in tip.lower()
        assert "tagged" in tip.lower()
        assert "install firmware" in tip.lower()
        assert "ads" not in tip.lower()
        assert "inline" not in tip.lower()


class TestFamilyGating:
    def test_enabling_basic_commercials_keeps_basic_family(self):
        out = apply_commercials_method(
            _meta(),
            family=FAMILY_BASIC,
            enabled=True,
            mode=MODE_FOLDER_99,
        )
        assert out["firmware_family"] == FAMILY_BASIC
        assert out["commercials_enabled"] is True
        assert out["commercials_mode"] == MODE_FOLDER_99

    def test_first_integrated_action_sets_conductor_family(self):
        out = apply_commercials_method(
            _meta(),
            family=FAMILY_CONDUCTOR,
            enabled=True,
            mode=MODE_INLINE,
        )
        assert out["firmware_family"] == FAMILY_CONDUCTOR
        assert out["commercials_mode"] == MODE_INLINE

    def test_folder_mode_forces_basic_family(self):
        out = apply_commercials_method(
            _meta(
                firmware_family=FAMILY_CONDUCTOR,
                commercials_enabled=True,
                commercials_mode=MODE_INLINE,
            ),
            family=FAMILY_CONDUCTOR,
            enabled=True,
            mode=MODE_FOLDER_99,
        )
        assert out["firmware_family"] == FAMILY_BASIC
        assert out["commercials_mode"] == MODE_FOLDER_99
        assert library_badge_text(out) == "Default | Commercials"

    def test_family_switch_still_requires_allow(self):
        with pytest.raises(ValueError):
            apply_commercials_method(
                _meta(commercials_enabled=True, commercials_mode=MODE_FOLDER_99),
                family=FAMILY_CONDUCTOR,
                enabled=True,
                mode=MODE_INLINE,
                allow_switch=False,
            )

    def test_folder_and_integrated_together_use_conductor(self):
        out = apply_commercials_flags(_meta(), folder=True, inline=True)
        assert out["firmware_family"] == FAMILY_CONDUCTOR
        assert out["commercials_mode"] == MODE_BOTH
        assert is_folder_commercials(out) is True
        assert can_mark_track_commercial(out) is True
        assert library_badge_text(out) == "Conductor | Commercials"

    def test_cannot_mark_track_on_basic_library(self):
        assert can_mark_track_commercial(_meta(commercials_enabled=True, commercials_mode=MODE_FOLDER_99)) is False

    def test_can_mark_track_on_conductor_inline(self):
        assert (
            can_mark_track_commercial(
                _meta(
                    firmware_family=FAMILY_CONDUCTOR,
                    commercials_enabled=True,
                    commercials_mode=MODE_INLINE,
                )
            )
            is True
        )


class TestSyncWarnings:
    def test_integrated_requires_pico_catalog(self):
        assert requires_pico_catalog(
            _meta(
                firmware_family=FAMILY_CONDUCTOR,
                commercials_enabled=True,
                commercials_mode=MODE_INLINE,
            )
        ) is True

    def test_stale_conductor_without_integrated_does_not_require_catalog(self):
        assert requires_pico_catalog(_meta(firmware_family=FAMILY_CONDUCTOR)) is False

    def test_basic_does_not_require_pico_catalog(self):
        assert requires_pico_catalog(_meta(commercials_enabled=True, commercials_mode=MODE_FOLDER_99)) is False

    def test_sync_extras_flag_for_integrated(self):
        extras = sync_result_extras(
            _meta(
                firmware_family=FAMILY_CONDUCTOR,
                commercials_enabled=True,
                commercials_mode=MODE_INLINE,
            )
        )
        assert extras["requires_pico_catalog"] is True

    def test_post_sync_warning_integrated_mentions_install_firmware(self):
        text = post_sync_warning(
            _meta(
                firmware_family=FAMILY_CONDUCTOR,
                commercials_enabled=True,
                commercials_mode=MODE_INLINE,
            )
        )
        assert "install firmware" in text.lower()

    def test_post_sync_warning_basic_commercials_mentions_install_firmware(self):
        text = post_sync_warning(
            _meta(commercials_enabled=True, commercials_mode=MODE_FOLDER_99),
            settings_changed=True,
        )
        assert "install firmware" in text.lower()


class TestRadioCatalog:
    def test_folder_99_mode_puts_ads_in_folder_99(self):
        stations = [
            {"folder": 1, "tracks": [{"t": 1, "ad": 0}, {"t": 2, "ad": 0}]},
            {"folder": COMMERCIALS_FOLDER, "tracks": [{"t": 1, "ad": 0}, {"t": 2, "ad": 0}]},
        ]
        catalog = build_radio_catalog(stations, mode=MODE_FOLDER_99, interval=5)
        assert catalog["commercials"]["mode"] == MODE_FOLDER_99
        assert catalog["commercials"]["folder"] == COMMERCIALS_FOLDER
        music = [s for s in catalog["stations"] if s["folder"] != COMMERCIALS_FOLDER]
        ads = [s for s in catalog["stations"] if s["folder"] == COMMERCIALS_FOLDER]
        assert len(music) == 1
        assert ads[0]["tracks"]

    def test_inline_flags_preserved(self):
        stations = [
            {"folder": 1, "tracks": [{"t": 1, "ad": 0}, {"t": 2, "ad": 1}, {"t": 3, "ad": 0}]},
        ]
        catalog = build_radio_catalog(stations, mode=MODE_INLINE, interval=5)
        assert catalog["stations"][0]["tracks"][1]["ad"] == 1

    def test_inline_link_flag_preserved_on_commercials(self):
        stations = [
            {
                "folder": 1,
                "tracks": [
                    {"t": 1, "ad": 1, "link": 1},
                    {"t": 2, "ad": 0},
                    {"t": 3, "ad": 1, "link": 0},
                ],
            },
        ]
        catalog = build_radio_catalog(stations, mode=MODE_INLINE, interval=5)
        tracks = catalog["stations"][0]["tracks"]
        assert tracks[0]["ad"] == 1
        assert tracks[0]["link"] == 1
        assert "link" not in tracks[1]
        assert "link" not in tracks[2]

    def test_integrated_keeps_user_folder_99(self):
        stations = [
            {"folder": 1, "tracks": [{"t": 1, "ad": 0}]},
            {"folder": COMMERCIALS_FOLDER, "tracks": [{"t": 1, "ad": 0}]},
        ]
        catalog = build_radio_catalog(stations, mode=MODE_INLINE, interval=5)
        folders = {s["folder"] for s in catalog["stations"]}
        assert COMMERCIALS_FOLDER in folders
        assert catalog["commercials"]["enabled"] is False

    def test_both_mode_enables_folder_inserts_and_keeps_inline_flags(self):
        stations = [
            {"folder": 1, "tracks": [{"t": 1, "ad": 0}, {"t": 2, "ad": 1}]},
            {"folder": COMMERCIALS_FOLDER, "tracks": [{"t": 1, "ad": 0}]},
        ]
        catalog = build_radio_catalog(stations, mode=MODE_BOTH, interval=4)
        assert catalog["commercials"]["mode"] == MODE_BOTH
        assert catalog["commercials"]["enabled"] is True
        assert catalog["stations"][0]["tracks"][1]["ad"] == 1
        slots = library_shuffle_slots(catalog)
        assert (COMMERCIALS_FOLDER, 1) not in slots
        assert (1, 2) not in slots

    def test_library_shuffle_excludes_ads(self):
        catalog = {
            "stations": [
                {"folder": 1, "tracks": [{"t": 1, "ad": 0}, {"t": 2, "ad": 1}]},
                {"folder": 2, "tracks": [{"t": 1, "ad": 0}]},
            ]
        }
        slots = library_shuffle_slots(catalog)
        assert (1, 2) not in slots
        assert set(slots) == {(1, 1), (2, 1)}

    def test_library_shuffle_keeps_linked_commercial_with_next_track(self):
        catalog = {
            "stations": [
                {
                    "folder": 1,
                    "tracks": [
                        {"t": 1, "ad": 1, "link": 1},
                        {"t": 2, "ad": 0},
                        {"t": 3, "ad": 1},
                        {"t": 4, "ad": 0},
                    ],
                },
            ]
        }
        units = library_shuffle_units(catalog)
        assert units == [(1, 2, (1, 1)), (1, 4, None)]
        assert library_shuffle_slots(catalog) == [(1, 2), (1, 4)]

    def test_expand_linked_move_rows_includes_partner(self):
        flags = [False, True, False, False]
        assert expand_linked_move_rows([1], flags) == [1, 2]
        assert expand_linked_move_rows([2], flags) == [1, 2]
        assert expand_linked_move_rows([0], flags) == [0]

    def test_snap_insert_skips_staying_pair(self):
        flags = [True, False, False]
        assert snap_insert_around_links(1, flags, moving=[]) == 2
        assert snap_insert_around_links(1, flags, moving=[0, 1]) == 1

    def test_can_link_only_when_next_is_music(self):
        assert can_link_commercial_to_next(True, False) is True
        assert can_link_commercial_to_next(True, True) is False
        assert can_link_commercial_to_next(True, None) is False
        assert can_link_commercial_to_next(False, False) is False

    def test_shuffle_units_from_tracks_skips_unlinked_ads(self):
        units = shuffle_units_from_tracks(
            [{"t": 1, "ad": 1}, {"t": 2, "ad": 0}, {"t": 3, "ad": 0}],
            folder=4,
        )
        assert units == [(4, 2, None), (4, 3, None)]


class TestTrackCommercialRole:
    def test_configure_item_sets_commercial_role(self, qapp=None):
        from PyQt6 import QtWidgets

        app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        _ = app
        item = QtWidgets.QTableWidgetItem()
        configure_track_title_item(item, "Jingle", artist="Ad", is_commercial=True)
        assert item.data(TRACK_COMMERCIAL_ROLE) is True
        assert track_is_commercial(item) is True

    def test_configure_item_sets_toggle_role(self, qapp=None):
        from PyQt6 import QtWidgets
        from gui.widgets.common.delegates import TRACK_COMMERCIAL_TOGGLE_ROLE

        app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        _ = app
        item = QtWidgets.QTableWidgetItem()
        configure_track_title_item(
            item, "Jingle", is_commercial=True, show_commercial_toggle=True
        )
        assert item.data(TRACK_COMMERCIAL_TOGGLE_ROLE) is True

    def test_right_cluster_keeps_badge_left_of_actions(self, qapp=None):
        from PyQt6 import QtCore, QtGui, QtWidgets
        from gui.widgets.common.delegates import (
            track_commercial_badge_rect,
            track_commercial_hit_rect,
            track_pencil_hit_rect,
        )

        app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        _ = app
        row = QtCore.QRect(0, 0, 640, 72)
        font = QtGui.QFont()
        pencil = track_pencil_hit_rect(row, show_ad_toggle=True)
        ad_btn = track_commercial_hit_rect(row)
        badge = track_commercial_badge_rect(row, font)
        assert not pencil.isEmpty()
        assert not ad_btn.isEmpty()
        assert not badge.isEmpty()
        assert not pencil.intersects(ad_btn)
        assert ad_btn.right() <= pencil.left()
        assert badge.right() <= ad_btn.left()
        assert abs(badge.center().y() - pencil.center().y()) <= 2
        assert ad_btn.width() > pencil.width()

    def test_link_button_sits_left_of_ad_toggle(self, qapp=None):
        from PyQt6 import QtCore, QtWidgets
        from gui.widgets.common.delegates import (
            track_commercial_badge_rect,
            track_commercial_hit_rect,
            track_link_hit_rect,
        )

        app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        _ = app
        row = QtCore.QRect(0, 0, 640, 72)
        ad_btn = track_commercial_hit_rect(row, show_link_toggle=True)
        link_btn = track_link_hit_rect(row, show_ad_toggle=True)
        badge = track_commercial_badge_rect(row, show_ad_toggle=True, show_link_toggle=True)
        assert not link_btn.intersects(ad_btn)
        assert link_btn.right() <= ad_btn.left()
        assert badge.right() <= link_btn.left()


class TestCatalogChanged:
    def _sample_catalog(self, **commercials_kw):
        return build_radio_catalog(
            [{"folder": 1, "tracks": [{"t": 1, "ad": 0}]}],
            mode=MODE_FOLDER_99,
            interval=5,
        )

    def test_identical_catalogs_unchanged(self):
        cat = self._sample_catalog()
        assert catalog_changed(cat, dict(cat)) is False

    def test_missing_old_is_changed(self):
        cat = self._sample_catalog()
        assert catalog_changed(None, cat) is True

    def test_track_change_is_changed(self):
        old = self._sample_catalog()
        new = build_radio_catalog(
            [{"folder": 1, "tracks": [{"t": 1, "ad": 0}, {"t": 2, "ad": 0}]}],
            mode=MODE_FOLDER_99,
        )
        assert catalog_changed(old, new) is True

    def test_commercials_interval_change_is_changed(self):
        old = self._sample_catalog()
        new = build_radio_catalog(
            [{"folder": 1, "tracks": [{"t": 1, "ad": 0}]}],
            mode=MODE_FOLDER_99,
            interval=3,
        )
        assert catalog_changed(old, new) is True


class TestPushRadioCatalogToPico:
    def test_resets_album_state_when_catalog_changed(self, tmp_path):
        cat = build_radio_catalog(
            [{"folder": 1, "tracks": [{"t": 1, "ad": 0}]}],
            mode=MODE_FOLDER_99,
        )
        copied: list[tuple[str, str]] = []

        def copy_to_pico(local: Path, remote: str) -> bool:
            copied.append((local.name, remote))
            return True

        ok, err = push_radio_catalog_to_pico(
            json.dumps(cat),
            read_remote_catalog=lambda: None,
            copy_to_pico=copy_to_pico,
        )
        assert ok is True
        assert err == ""
        assert ("radio_catalog.json", ":VintageRadio/radio_catalog.json") in copied
        assert ("album_state.txt", ":VintageRadio/album_state.txt") in copied

    def test_skips_album_state_when_unchanged(self):
        cat = build_radio_catalog(
            [{"folder": 1, "tracks": [{"t": 1, "ad": 0}]}],
            mode=MODE_FOLDER_99,
        )
        copied: list[tuple[str, str]] = []

        def copy_to_pico(local: Path, remote: str) -> bool:
            copied.append((local.name, remote))
            return True

        ok, _ = push_radio_catalog_to_pico(
            json.dumps(cat),
            read_remote_catalog=lambda: dict(cat),
            copy_to_pico=copy_to_pico,
        )
        assert ok is True
        assert copied == [("radio_catalog.json", ":VintageRadio/radio_catalog.json")]

    def test_read_failure_triggers_reset(self):
        cat = build_radio_catalog(
            [{"folder": 1, "tracks": [{"t": 1, "ad": 0}]}],
            mode=MODE_FOLDER_99,
        )
        copied: list[str] = []

        def copy_to_pico(local: Path, remote: str) -> bool:
            copied.append(remote)
            return True

        push_radio_catalog_to_pico(
            json.dumps(cat),
            read_remote_catalog=lambda: None,
            copy_to_pico=copy_to_pico,
        )
        assert ":VintageRadio/album_state.txt" in copied


class TestFirmwareRoot:
    def test_conductor_install_uses_conductor_tree(self, tmp_path):
        (tmp_path / "firmware" / "pico").mkdir(parents=True)
        (tmp_path / "firmware" / "conductor").mkdir(parents=True)
        assert firmware_source_root("conductor", tmp_path).name == "conductor"
        assert firmware_source_root("basic", tmp_path).name == "pico"

    def test_conductor_copy_pairs_stay_in_conductor_tree(self):
        pairs = firmware_copy_pairs("conductor")
        assert pairs
        assert all(src.startswith("firmware/conductor/") for src, _dst in pairs)
        assert any(dst == "main.py" for _src, dst in pairs)
        assert any(src.endswith("radio_core.py") for src, _dst in pairs)

    def test_basic_copy_pairs_use_pico_tree(self):
        pairs = firmware_copy_pairs("basic")
        assert any(src == "firmware/pico/main_basic.py" for src, _dst in pairs)
        assert all(not src.startswith("firmware/conductor/") for src, _dst in pairs)


class TestAdIcon:
    def test_ad_png_keeps_original_aspect(self):
        from PyQt6.QtGui import QImage
        from gui.widgets.common.delegates import _AD_ASPECT, _resource_path

        path = _resource_path("Ad.png")
        assert path.is_file()
        image = QImage(str(path))
        assert not image.isNull()
        assert abs((image.width() / image.height()) - _AD_ASPECT) < 0.01

    def test_ad_svg_keeps_plate_and_glyph(self):
        from gui.widgets.common.delegates import _ad_svg_path

        path = _ad_svg_path()
        assert path.is_file()
        text = path.read_text(encoding="utf-8")
        assert "AD" in text
        assert 'viewBox="0 0 669 301"' in text
        assert 'fill="black"' in text
        assert 'fill="white"' in text

    def test_link_and_chain_icons_exist(self):
        from gui.widgets.common.delegates import _resource_path

        assert _resource_path("Link.png").is_file()
        assert _resource_path("Chain.png").is_file()

    def test_integrated_tooltip_mentions_conductor(self):
        from gui.commercials import (
            COMMERCIALS_STATION_TOOLTIP,
            COMMERCIALS_TAGGED_TOOLTIP,
        )

        assert "Vintage Radio Conductor" in COMMERCIALS_TAGGED_TOOLTIP
        assert "Vintage Radio Default" in COMMERCIALS_STATION_TOOLTIP


def test_source_tree_has_all_firmware_copy_paths():
    root = Path(__file__).resolve().parents[2]
    missing = missing_firmware_bundle_paths(root)
    assert missing == [], missing
