"""Unit tests for basic_mode_max_folder_for_station_seed (0x4F / 0x4E disambiguation)."""

import pytest

from radio_core import (
    _basic_sd_signatures_equivalent,
    _format_basic_sd_sig,
    _parse_basic_sd_sig_line,
    basic_mode_effective_folder_count,
    basic_mode_max_folder_for_station_seed,
    basic_mode_music_folder_count,
)


@pytest.mark.parametrize(
    "fc,hi,expected",
    [
        (None, None, 99),
        (0, None, 99),
        (-1, None, 99),
        (1, None, 1),
        (2, 7, 2),
        (2, 1, 2),
        (2, 0, 1),
        (3, 5, 3),
        (3, 0, 2),
        (100, None, 99),
    ],
)
def test_basic_mode_max_folder_for_station_seed(fc, hi, expected):
    assert basic_mode_max_folder_for_station_seed(fc, hi) == expected


def test_invalid_fc_string_treated_as_fallback():
    assert basic_mode_max_folder_for_station_seed("x", None) == 99


@pytest.mark.parametrize(
    "fc,ads_present,expected",
    [
        (5, True, 4),
        (5, False, 5),
        (1, True, 0),
        (0, True, 0),
        (None, True, None),
        (None, False, None),
    ],
)
def test_basic_mode_effective_folder_count(fc, ads_present, expected):
    assert basic_mode_effective_folder_count(fc, ads_present) == expected


@pytest.mark.parametrize(
    "fc,hi_probe_result,ads_present,expected",
    [
        # Real-world regression: card has folders 01,02,03,99 (3 music stations
        # plus the ads reel). 0x4F reports 5 (the +1 root-counting quirk plus the
        # ads folder); probing folder 4 (the gap between 03 and 99) reads empty.
        # Without the ads-folder adjustment this used to seed a phantom station 04.
        (5, 0, True, 3),
        # Same raw count, but no ads folder present -- falls through to the
        # unmodified seeding heuristic unchanged.
        (5, 0, False, 4),
        # Three real stations (01,02,03) plus ads in 99; 0x4F reports 4 exactly
        # (no root-counting quirk this time). Adjusted fc=3, probing folder 3
        # confirms it is real (hi_probe>0), so all folders up to it are kept.
        (4, 3, True, 3),
        # Exactly one music station plus ads: fc=2 (1 music + 1 ads, no root
        # quirk) adjusts to fc_effective=1, short-circuiting the probe entirely.
        (2, None, True, 1),
        # No ads folder detected: identical to the original function.
        (3, 5, False, 3),
    ],
)
def test_basic_mode_music_folder_count(fc, hi_probe_result, ads_present, expected):
    assert basic_mode_music_folder_count(fc, hi_probe_result, ads_present) == expected


@pytest.mark.parametrize(
    "line,expected",
    [
        ("20,10", (20, 10, None)),
        ("-1,3", (-1, 3, None)),
        ("20,10,500", (20, 10, 500)),
        ("-1,3,-1", (-1, 3, -1)),
        ("", None),
        ("20", None),
        ("a,3", None),
        ("20,10,x", None),
    ],
)
def test_parse_basic_sd_sig_line(line, expected):
    assert _parse_basic_sd_sig_line(line) == expected


def test_format_basic_sd_sig_roundtrip_legacy_2tuple():
    """A 2-tuple (no TF file count) formats without a third field, and parses
    back with the third field as None -- old and new signature files must
    both round-trip cleanly."""
    sig = (15, 8)
    assert _parse_basic_sd_sig_line(_format_basic_sd_sig(sig)) == (15, 8, None)


def test_format_basic_sd_sig_roundtrip_3tuple():
    sig = (15, 8, 2048)
    assert _parse_basic_sd_sig_line(_format_basic_sd_sig(sig)) == sig


def test_sd_signatures_equivalent_ignores_seed_count_when_tf_matches():
    """0x4F timeout (99 slots) vs later success (6 slots) on the same card."""
    prev = (-1, 99, 210)
    new = (6, 6, 210)
    assert _basic_sd_signatures_equivalent(prev, new) is True


def test_sd_signatures_not_equivalent_when_tf_file_count_changes():
    prev = (6, 6, 210)
    new = (6, 6, 400)
    assert _basic_sd_signatures_equivalent(prev, new) is False


def test_sd_signatures_not_equivalent_when_folder_count_both_known_and_differ():
    prev = (6, 6, 210)
    new = (8, 8, 210)
    assert _basic_sd_signatures_equivalent(prev, new) is False
