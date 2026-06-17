"""
Hardware playback / mode coverage matrix for Vintage Radio (Pico + DFPlayer).

Use this as the checklist when validating firmware before a release. The automated
``physical_device_full_check.py`` suite does *not* run these scenarios today — it
only exercises VRTEST gestures, connect/stream, reboot, list_files, and boot logs.

How to run cases:
  - Manually on the bench (preferred for audio quality).
  - Or extend VRTEST in ``firmware/pico/components/vintage_radio_ipc.py`` with
    scripted commands that call into ``radio_core`` / firmware wrappers (future).

Line-in objective metrics (host):
  - MCP ``line_in_analyze`` vs ``gui/resources/AMradioSound.wav`` (needs numpy +
    sounddevice + Line In wired from the amp/DFPlayer output).
"""

from __future__ import annotations

from typing import Any, Dict, List

JsonDict = Dict[str, Any]

# Each case: id, description, steps (human-readable), notes for pass criteria.
PLAYBACK_CASES: List[JsonDict] = [
    {
        "id": "normal_station_multi_album",
        "description": "Normal (non-shuffle) station order: play at least 10 tracks across 5+ album folders.",
        "steps": [
            "Boot from clean state or known saved state in normal/playlist order.",
            "Single-tap through tracks; note folder/track on serial or UI.",
            "Cover at least 5 distinct folders and 10 track advances.",
        ],
        "pass": "No UART errors, BUSY behaves, audio continuous, state file consistent.",
    },
    {
        "id": "station_shuffle",
        "description": "Station shuffle: enter shuffle, play several tracks, verify non-sequential behavior vs folder order.",
        "steps": [
            "Enter station shuffle per basic-mode gesture map (double-tap + hold, etc.).",
            "Advance 8+ tracks; log folder/track indices from serial or get_state.",
        ],
        "pass": "Shuffle advances without stuck BUSY; no MemoryError in serial tail.",
    },
    {
        "id": "library_shuffle",
        "description": "Library shuffle (virtual permutation across many folders).",
        "steps": [
            "Triple-tap + hold (basic map) or equivalent to enter library shuffle.",
            "Play 15+ advances spanning multiple folders when card has data.",
        ],
        "pass": "No repeated hang on bad folder; recovery logs if any; audio plays.",
    },
    {
        "id": "shuffle_to_normal",
        "description": "Exit shuffle back to normal ordered playback.",
        "steps": [
            "From shuffle, use tap + hold (basic map) to exit to normal station order.",
            "Single-tap a few tracks; verify order matches station list expectations.",
        ],
        "pass": "Mode transition clean; next/prev track matches non-shuffle semantics.",
    },
    {
        "id": "am_overlay_each_power_track_change",
        "description": "AM static overlay + DFPlayer fade on boot and major transitions.",
        "steps": [
            "Cold boot: listen to AM static vs music blend; compare to reference WAV on PC.",
            "Change station/album modes that trigger overlay (as implemented in main_basic).",
        ],
        "pass": "Overlay not grossly muffled vs reference; no runaway PWM after overlay (GPIO high-Z).",
    },
    {
        "id": "long_press_station_change",
        "description": "Hold: next station (and variants in shuffle).",
        "steps": ["Long-press from playing state; verify station index and first track."],
        "pass": "BUSY and UART end detection still advance tracks afterward.",
    },
    {
        "id": "triple_tap_restart_station",
        "description": "Triple-tap restart current station.",
        "steps": ["Mid-station triple-tap; confirm track resets per map."],
        "pass": "Playback restarts without deadlock.",
    },
]


def print_matrix() -> None:
    for c in PLAYBACK_CASES:
        print(c["id"] + " - " + c["description"])
        for s in c.get("steps", []):
            print("  - " + s)
        print("  pass:", c.get("pass", ""))
        print()


if __name__ == "__main__":
    print_matrix()
