"""Install Firmware — release UF2 policy for official entries."""

from gui.radio_manager import MainWindow


def test_current_default_never_uses_release_uf2():
    entry = {
        "kind": "vintage_radio",
        "generation": "current",
        "uf2Path": "/tmp/vintage-radio-firmware-1.1.0-full.uf2",
    }
    assert MainWindow._firmware_entry_allows_release_uf2(entry) is False


def test_legacy_default_allows_release_uf2():
    entry = {
        "kind": "vintage_radio",
        "generation": "legacy",
        "uf2Path": "/tmp/vintage-radio-firmware-1.0.0-full.uf2",
    }
    assert MainWindow._firmware_entry_allows_release_uf2(entry) is True


def test_conductor_never_uses_release_uf2():
    entry = {"kind": "vintage_radio_conductor", "generation": "current"}
    assert MainWindow._firmware_entry_allows_release_uf2(entry) is False
