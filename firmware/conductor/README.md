# Vintage Radio Conductor

Isolated firmware tree. **Do not** import from `firmware/pico` or `firmware/radio_core.py`.
Host install copies this folder only when the Install Firmware card **Vintage Radio Conductor**
is selected (`install_mode=conductor`).

## Shared-origin files

These started as copies of Basic. Bugfixes must be ported deliberately.

| Conductor file | Originated from |
| --- | --- |
| `main.py` | `firmware/pico/main_basic.py` |
| `radio_core.py` | `firmware/radio_core.py` |
| `dfplayer_hardware.py` | `firmware/pico/dfplayer_hardware.py` |
| `pin_config_loader.py` | `firmware/pin_config_loader.py` |
| `sdcard.py` | `firmware/pico/sdcard.py` |
| `components/vintage_radio_ipc.py` | `firmware/pico/components/vintage_radio_ipc.py` |
| `components/am_wav_loader.py` | `firmware/pico/components/am_wav_loader.py` |
| `components/radio_state.py` | `firmware/pico/components/radio_state.py` |

## Playback state policy

| Event | Behavior |
| --- | --- |
| Pot off → pot on (Pico stays powered) | RAM `resume_state` only — no flash write |
| Full Pico power loss (`PWRON_RESET`) | Playback state cleared on cold boot |
| Host pushes changed `radio_catalog.json` | Host also writes default `album_state.txt` (`1,1;mode=playlist`) |
| Boot with catalog loaded | Skip flaky DFPlayer SD-signature reset/write; cold-boot clear still runs |
| Boot without catalog (discovery fallback) | Same SD-signature behavior as Basic |

## Playback

Boots from `VintageRadio/radio_catalog.json` on Pico flash.

- `commercials.mode = folder_99` — same interval insert as Basic (random track in folder 99).
- `commercials.mode = inline` — play catalog order; `ad=1` stays in place; shuffle skips unlinked ads.
- `link=1` on an `ad=1` track — that commercial stays attached to the music track below it in both station shuffle and library shuffle.

Every library change needs **SD sync and a Pico catalog write**. Full firmware copy is only
required when these files change.

## Gestures (vs Basic)

| Gesture | Conductor |
| --- | --- |
| Double tap + hold | Shuffle **current station** (music only; linked commercials travel with the track below) |
| Triple tap + hold | Shuffle the **whole library** (same pairing; unlinked `ad=1` is skipped) |

Station change (long press / four tap) uses catalog station count, not DFPlayer `0x4F`.
