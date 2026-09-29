"""Acoustic track identification for physical-device tests.

Test-library audio carries two continuous pilot tones mixed under the music: one
encodes the DFPlayer folder, the other the track number. Any half-second of a
capture is therefore enough to answer "which file is the radio actually playing",
which is what turns "no skipped tracks" from a guess based on reported state into
something proven from the speaker output.

The scheme is deliberately constrained so the tones survive MP3 encoding and the
DFPlayer analogue path:

* Music content is synthesised below ``MUSIC_MAX_HZ`` so no musical energy sits
  near the pilots. Without a loud neighbour to hide behind, the LAME
  psychoacoustic model keeps them instead of discarding them as masked.
* The whole pilot band lives above ``BAND_LOW_HZ`` and below ``2 * BAND_LOW_HZ``,
  so the second harmonic of any pilot lands outside the band and cannot be
  mistaken for another slot when the amplifier adds distortion.
* Slot spacing is far wider than the FFT bin size used for detection, leaving
  room for DFPlayer clock drift.
"""

from __future__ import annotations

from typing import Optional, Tuple

# Folder pilots occupy the lower half of the band, track pilots the upper half.
FOLDER_BASE_HZ = 3100.0
FOLDER_STEP_HZ = 180.0
TRACK_BASE_HZ = 4600.0
TRACK_STEP_HZ = 160.0
SLOTS = 8

# Reserved DFPlayer folder for commercials; it gets the last folder slot so ads
# are acoustically distinguishable from any music station.
COMMERCIALS_FOLDER = 99
COMMERCIALS_SLOT = SLOTS - 1

#: Peak amplitude of each pilot tone, relative to full scale.
PILOT_AMPLITUDE = 0.085

#: Synthesised music must stay below this so it never masks the pilots.
MUSIC_MAX_HZ = 2500.0

BAND_LOW_HZ = FOLDER_BASE_HZ - FOLDER_STEP_HZ / 2.0
FOLDER_BAND_HIGH_HZ = FOLDER_BASE_HZ + (SLOTS - 0.5) * FOLDER_STEP_HZ
TRACK_BAND_LOW_HZ = TRACK_BASE_HZ - TRACK_STEP_HZ / 2.0
BAND_HIGH_HZ = TRACK_BASE_HZ + (SLOTS - 0.5) * TRACK_STEP_HZ

#: How far a measured peak may sit from a slot centre and still decode.
MATCH_TOLERANCE_HZ = 45.0


class IdentError(ValueError):
    """Raised when a folder/track cannot be represented as pilot tones."""


def folder_slot(folder: int) -> int:
    """Map a DFPlayer folder number to a pilot slot index."""
    f = int(folder)
    if f == COMMERCIALS_FOLDER:
        return COMMERCIALS_SLOT
    if 1 <= f <= COMMERCIALS_SLOT:
        return f - 1
    raise IdentError(
        f"folder {f} has no pilot slot (use 1-{COMMERCIALS_SLOT} or {COMMERCIALS_FOLDER})"
    )


def track_slot(track: int) -> int:
    """Map a DFPlayer track number to a pilot slot index."""
    t = int(track)
    if 1 <= t <= SLOTS:
        return t - 1
    raise IdentError(f"track {t} has no pilot slot (use 1-{SLOTS})")


def slot_to_folder(slot: int) -> int:
    if slot == COMMERCIALS_SLOT:
        return COMMERCIALS_FOLDER
    return int(slot) + 1


def slot_to_track(slot: int) -> int:
    return int(slot) + 1


def ident_tones(folder: int, track: int) -> Tuple[float, float]:
    """Return the (folder_hz, track_hz) pilot pair identifying folder/track."""
    f_hz = FOLDER_BASE_HZ + FOLDER_STEP_HZ * folder_slot(folder)
    t_hz = TRACK_BASE_HZ + TRACK_STEP_HZ * track_slot(track)
    return f_hz, t_hz


def _nearest_slot(freq_hz: float, base_hz: float, step_hz: float) -> Optional[int]:
    if freq_hz <= 0:
        return None
    slot = int(round((float(freq_hz) - base_hz) / step_hz))
    if not 0 <= slot < SLOTS:
        return None
    if abs(base_hz + step_hz * slot - float(freq_hz)) > MATCH_TOLERANCE_HZ:
        return None
    return slot


def decode_tones(
    folder_hz: Optional[float], track_hz: Optional[float]
) -> Tuple[Optional[int], Optional[int]]:
    """Turn a measured pilot pair back into (folder, track); None where unmatched."""
    f_slot = _nearest_slot(folder_hz, FOLDER_BASE_HZ, FOLDER_STEP_HZ) if folder_hz else None
    t_slot = _nearest_slot(track_hz, TRACK_BASE_HZ, TRACK_STEP_HZ) if track_hz else None
    folder = slot_to_folder(f_slot) if f_slot is not None else None
    track = slot_to_track(t_slot) if t_slot is not None else None
    return folder, track


def describe_plan() -> str:
    """Human-readable frequency plan, used in generated docs and reports."""
    rows = ["folder pilots:"]
    for slot in range(SLOTS):
        label = (
            f"folder {COMMERCIALS_FOLDER} (commercials)"
            if slot == COMMERCIALS_SLOT
            else f"folder {slot_to_folder(slot)}"
        )
        rows.append(f"  {FOLDER_BASE_HZ + FOLDER_STEP_HZ * slot:7.1f} Hz  {label}")
    rows.append("track pilots:")
    for slot in range(SLOTS):
        rows.append(f"  {TRACK_BASE_HZ + TRACK_STEP_HZ * slot:7.1f} Hz  track {slot_to_track(slot)}")
    return "\n".join(rows)
