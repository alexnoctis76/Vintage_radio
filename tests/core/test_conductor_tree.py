"""Conductor firmware tree is isolated and catalog-aware."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONDUCTOR = ROOT / "firmware" / "conductor"


def test_conductor_tree_has_required_files():
    for rel in (
        "README.md",
        "main.py",
        "radio_core.py",
        "dfplayer_hardware.py",
        "pin_config_loader.py",
        "sdcard.py",
        "components/vintage_radio_ipc.py",
        "components/am_wav_loader.py",
        "components/radio_state.py",
    ):
        assert (CONDUCTOR / rel).is_file(), rel


def test_radio_state_module_matches_between_trees():
    pico = ROOT / "firmware" / "pico" / "components" / "radio_state.py"
    conductor = CONDUCTOR / "components" / "radio_state.py"
    assert pico.read_bytes() == conductor.read_bytes()


def test_conductor_radio_core_does_not_import_basic_tree():
    text = (CONDUCTOR / "radio_core.py").read_text(encoding="utf-8")
    assert "from firmware.radio_core" not in text
    assert "from firmware.pico.main" not in text
    assert "from firmware.pico.dfplayer" not in text
    assert "_apply_radio_catalog" in text
    assert "_init_library_shuffle" in text
    assert "_shuffle_units_from_tracks" in text


def test_conductor_readme_documents_library_shuffle_gesture():
    text = (CONDUCTOR / "README.md").read_text(encoding="utf-8")
    assert "Triple tap + hold" in text
    assert "library" in text.lower()
    assert "link=1" in text
