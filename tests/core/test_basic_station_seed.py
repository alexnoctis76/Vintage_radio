"""Unit tests for basic_mode_max_folder_for_station_seed (0x4F / 0x4E disambiguation)."""

import pytest

from radio_core import (
    _format_basic_sd_sig,
    _parse_basic_sd_sig_line,
    basic_mode_max_folder_for_station_seed,
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
    "line,expected",
    [
        ("20,10", (20, 10)),
        ("-1,3", (-1, 3)),
        ("", None),
        ("20", None),
        ("a,3", None),
    ],
)
def test_parse_basic_sd_sig_line(line, expected):
    assert _parse_basic_sd_sig_line(line) == expected


def test_format_basic_sd_sig_roundtrip():
    sig = (15, 8)
    assert _parse_basic_sd_sig_line(_format_basic_sd_sig(sig)) == sig
