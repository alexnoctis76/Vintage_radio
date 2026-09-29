# Vintage Radio — agent context

PyQt6 desktop app for managing music libraries, syncing to SD, and flashing/controlling RP2040 “Basic” and “Conductor” firmware on a vintage AM radio build with DFPlayer.

## Architecture

| Layer | Path | Notes |
|-------|------|-------|
| Entry | `run_vintage_radio.py` | PyInstaller entry; supports `--enable-mcp-debug`, `--mcp-autostart`, `--mcp-port=` |
| Main window | `gui/radio_manager.py` | Large orchestrator (~16k lines); sidebar pages: Load Music, Install Firmware, Tools, Settings, Help |
| Widgets | `gui/widgets/` | Extracted UI; use vintage modal/scrollbar helpers per `.cursor/rules/vintage-ui-chrome.mdc` |
| Library DB | `gui/database.py` | SQLite per library; basic stations = DFPlayer folders |
| Library registry | `gui/library_manager.py` | `data/libraries/libraries.json` (source) or packaged `platformdirs` data dir |
| Commercials policy | `gui/commercials.py` | folder_99 / inline / both; catalog for Conductor |
| MCP debug server | `gui/debug_mcp_server.py` | TCP `127.0.0.1:8765`, newline JSON |
| MCP bridge | `scripts/vintage_radio_debug_mcp_bridge.py` | Cursor stdio → TCP |

## Firmware families

| Family | Pico entry | Library source | Commercials |
|--------|------------|----------------|-------------|
| **Basic** | `firmware/pico/main_basic.py` → flash as `main.py` | DFPlayer SD folder discovery | folder_99 only (folder 99 on SD) |
| **Conductor** | `firmware/conductor/main.py` | `radio_catalog.json` on Pico flash | folder_99, inline, or both |
| **Legacy** | `firmware/pico/main.py` | `radio_metadata.json` | frozen — do not test in acceptance |

Shared logic: `firmware/radio_core.py`, `firmware/pico/components/radio_state.py`.

**Hardware acceptance is Basic mode only** (`main_basic.py`). See `.cursor/rules/physical-device-testing.mdc`.

## Install Firmware UX

- **Default RP2040:** copies bundled Python (`main_basic.py`, `radio_core.py`, components) via USB/mpremote — **not** UF2-only.
- **Legacy cards / BOOTSEL:** full UF2 flash when appropriate.
- After firmware changes: `restart_firmware` via MCP, wait ~8 s, reconnect, run acceptance.

## RP2040 status LED (profile v5)

Serial boot line: `Status LED profile v5 (white=standby blue=idle orange=warning purple=playing)`

| State | Behavior |
|-------|----------|
| Standby | Dim white pulse (pot off / boot wait) |
| Idle | Solid dim blue (pot on, not playing) |
| Playing | Violet breathe |
| Warning | Deep orange pulse |
| Fatal | Solid red |

Help tab legend: `gui/widgets/help/page.py`.

## Commercials MCP acceptance

Engine: `gui/mcp_commercials_acceptance.py`

| Suite | Firmware | Mode |
|-------|----------|------|
| `basic_folder` | basic | folder_99 |
| `conductor_folder` | conductor | folder_99 |
| `conductor_inline` | conductor | inline |
| `conductor_both` | conductor | both |

**Test library shape:** 3 music stations × 4 tracks (~25 s) + folder 99 ad reel (4 ads, ~5 s), interval **3**, pilot-tone idents in `agent_workshop/test_library_audio/`.

**Setup packaged app for MCP:**

```powershell
python scripts/seed_packaged_commercials_library.py
# Restart packaged .exe, sync SD, Install Firmware from Commercials Test - Folder 99
python agent_workshop/run_commercials_acceptance.py
```

Dev library slug: `commercials-test-folder-99-3` in `data/libraries/`.

## MCP workflow (low token use)

1. `ping` → `get_connection_state` → `device_connect` (COM port)
2. `restart_firmware` if firmware changed; wait ~8 s
3. Long suites: **one** blocking `run_commercials_acceptance` or `run_full_acceptance` call — watch app session log; do not poll serial in a loop
4. End: `stop_streaming`, `disconnect`

Start app with MCP:

```text
Vintage Radio.exe --enable-mcp-debug --mcp-autostart
```

## Packaged app testing

- **Frozen data dir (Windows):** `%LOCALAPPDATA%\Vintage Radio\Vintage Radio` — separate from dev `data/`
- **Post-build smoke:** `scripts/packaged_app_smoke.py` (auto-run at end of `build/build_windows.bat` unless `--skip-smoke`)
- **Pre-build pytest (optional):** `build_windows.bat --with-pytest`
- **Visual checklist:** manual ~15 min per OS (sidebar, themes, modals, Help LED legend) — not automated

Build:

```powershell
python scripts/apply_release_config.py dev
build\build_windows.bat
```

## Physical device prerequisites

- Power **pot ON** (firmware waits for power sense HIGH)
- Line-in USB adapter; rename input **Vintage Radio Line In** when possible
- If line-in silent (~−85 dBFS): replug adapter, close apps holding capture device
- COM conflicts: disconnect MCP/app before mpremote; kill only agent harness processes

## Agent workshop

Temporary scripts/reports under `agent_workshop/` — clean up when done. Keep reusable runners (`run_commercials_acceptance.py`, `packaged_smoke_report.json`).

## Mandatory Cursor rules

Read and follow `.cursor/rules/`:

- `physical-device-testing.mdc` — full device acceptance before firmware sign-off
- `firmware-issues-self-test.mdc` — MCP + serial evidence
- `verify-changes-via-mcp.mdc` — MCP checks for device-affecting changes
- `vintage-ui-chrome.mdc` — modals and scrollbars
- `report-problems-reproduce.mdc` — reproduce before explaining

## Cross-OS notes

| OS | Build | Packaged smoke |
|----|-------|----------------|
| Windows | `build\build_windows.bat` | `--exe "dist/Vintage Radio/Vintage Radio.exe"` |
| macOS arm64 | `bash build/build_macos.sh --no-dmg --arch arm64 --channel dev` | `--mac-app "dist/Vintage Radio.app"` |
| Linux | `bash build/build_linux.sh --channel dev` | `--exe "dist/Vintage Radio/Vintage Radio"` |

Mac: Gatekeeper on first `.app` open; brew SDL deps per `docs/BUILD_AND_PACKAGE.md`.

No GitHub test CI by default — tests run locally.
