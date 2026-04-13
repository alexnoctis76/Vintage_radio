"""Unit tests for basic_mode_max_folder_for_station_seed (0x4F / 0x4E disambiguation)."""

import pytest

from radio_core import basic_mode_max_folder_for_station_seed


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
