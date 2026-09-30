# Apple Silicon Mac — build & QA handoff

Handoff from **Intel Mac (x86_64) QA on 2026-09-29**. Use this on your **Apple Silicon** machine to finish macOS packaging, in-app updates, and (optionally) MCP commercials acceptance.

**QA release fork (public):** [alexnoctis76/Vintage_radio-upgrade-test](https://github.com/alexnoctis76/Vintage_radio-upgrade-test)  
**Application source:** [alexnoctis76/Vintage_radio](https://github.com/alexnoctis76/Vintage_radio) — branch **`f-ui-cleanup`** (Mac packaging + updater fixes from this session)

General upgrade-path steps (tags, pytest gate, publishing): see **`docs/MAC_UPGRADE_TEST_AGENT.md`** on the upgrade-test fork (same content as the agent brief for update QA).

---

## What Intel Mac already validated

| Area | Result | Notes |
|------|--------|--------|
| Host pytest (MCP modules ignored) | **PASS** (~983 tests) | `DYLD_LIBRARY_PATH` for VLC required on macOS |
| `build_macos.sh --arch x86_64 --channel dev` | **PASS** | PyInstaller + mpremote_helper + bundled firmware |
| `scripts/packaged_app_smoke.py` | **16/16 PASS** | Includes `bundled_firmware_paths_present`, updater zip roundtrip |
| `dfplayer_protocol.py` in app bundle | **Fixed** | Was missing from spec + install copy list; Conductor/Basic flash was crashing with `ImportError` |
| Install to Pico (Basic) | **Copied + verified** | `dfplayer_protocol.py` on device before reset |
| QA pre-release on fork | **`v1.1.0-upgrade-test`** | Asset: `Vintage-Radio-macOS-x86_64.zip` uploaded |
| In-app update (Intel old → new) | **Partial** | Use **`Vintage Radio-x86_64.app`** in `/Applications`, not the stable `Vintage Radio.app` |
| MCP commercials test libraries | **Generated in dev** | Seeded into packaged data dir via `seed_packaged_commercials_library.py --all-test-libraries` |

**Still open on any Mac with hardware:** Pico boot re-check after USB replug, `run_full_acceptance`, MCP `run_commercials_acceptance` (needs line-in + SD sync).

---

## Apple Silicon — goals (remaining)

1. **Native arm64 test build** @ `v1.0.0-upgrade-test` → Help → Check for updates → downloads **`Vintage-Radio-macOS-arm64.zip`** → install succeeds → version **`v1.1.0-upgrade-test`**.
2. **Rosetta scenario (optional but important):** Install **x86_64** old test app on Silicon → updater must still offer **arm64** zip (not x86_64). After update, Activity Monitor → **Kind: Apple** (native).
3. **Rebuild and upload arm64 zip** to the same pre-release if the Silicon build includes newer fixes than the Intel-only upload.
4. **Packaged smoke on arm64** before uploading (do not use `--skip-smoke` for sign-off).

---

## One-time setup (Apple Silicon)

```bash
xcode-select --install   # if needed
brew install sdl2 sdl2_image sdl2_mixer sdl2_ttf
brew install --cask vlc  # pytest + pydub/vlc

cd /path/to/Vintage_radio
git fetch origin
git checkout f-ui-cleanup   # or merge commit that contains Mac fixes

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt pyinstaller

# pytest on macOS (VLC dylibs)
export QT_QPA_PLATFORM=offscreen
export DYLD_LIBRARY_PATH="/Applications/VLC.app/Contents/MacOS/lib"
```

---

## Step 0 — Host pytest (required before packaging)

```bash
source .venv/bin/activate
export QT_QPA_PLATFORM=offscreen
export DYLD_LIBRARY_PATH="/Applications/VLC.app/Contents/MacOS/lib"

python -m pytest -q \
  --ignore=tests/gui/test_mcp_device_acceptance.py \
  --ignore=tests/gui/test_mcp_gui_queue.py \
  --ignore=tests/gui/test_mcp_line_in_analysis.py \
  --ignore=tests/gui/test_debug_mcp_server.py \
  --ignore=tests/gui/test_commercials_acceptance.py
```

**Pass criteria:** exit code 0, **0 failed**.

Optional packaging-focused tests:

```bash
python -m pytest tests/scripts/test_packaged_bundle_checks.py tests/gui/test_updater.py -q
```

---

## Step 1 — Build NEW release (arm64) for the QA fork

```bash
source .venv/bin/activate
python scripts/apply_release_config.py test
python scripts/set_app_version.py v1.1.0-upgrade-test

bash build/build_macos.sh --no-dmg --arch arm64 --channel test
# Do NOT pass --skip-smoke for sign-off.

ditto -c -k --sequesterRsrc --keepParent \
  "dist/Vintage Radio-arm64.app" \
  "agent_workshop/Vintage-Radio-macOS-arm64.zip"
```

**Sanity checks before upload:**

```bash
test -f "dist/Vintage Radio-arm64.app/Contents/Frameworks/firmware/dfplayer_protocol.py" && echo OK
"/dist/Vintage Radio-arm64.app/Contents/MacOS/Vintage Radio" --version 2>/dev/null || true
/usr/libexec/PlistBuddy -c 'Print :CFBundleShortVersionString' \
  "dist/Vintage Radio-arm64.app/Contents/Info.plist"
```

Expect plist version aligned with `project_version.py` (not hardcoded `1.0.0`).

---

## Step 2 — Publish / refresh GitHub pre-release

Existing tag: **`v1.1.0-upgrade-test`** on the upgrade-test fork.

Replace or add the **arm64** asset (keep x86_64 zip for Intel testers):

```bash
export GITHUB_TOKEN=$(gh auth token)

gh release upload v1.1.0-upgrade-test \
  --repo alexnoctis76/Vintage_radio-upgrade-test \
  --clobber \
  agent_workshop/Vintage-Radio-macOS-arm64.zip
```

Verify API (no auth):

```bash
curl -s "https://api.github.com/repos/alexnoctis76/Vintage_radio-upgrade-test/releases/latest" \
  | python3 -c "import sys,json; r=json.load(sys.stdin); print(r['tag_name'], [a['name'] for a in r['assets']])"
```

Expect both **`Vintage-Radio-macOS-arm64.zip`** and **`Vintage-Radio-macOS-x86_64.zip`** when both arches are published.

---

## Step 3 — Build OLD test app on Apple Silicon (arm64)

```bash
python scripts/set_app_version.py v1.0.0-upgrade-test
bash build/build_macos.sh --no-dmg --arch arm64 --channel test --skip-smoke

cp -R "dist/Vintage Radio-arm64.app" "/Applications/Vintage Radio-arm64.app"
xattr -cr "/Applications/Vintage Radio-arm64.app"   # if Gatekeeper blocks
```

Confirm bundled test config:

```bash
/usr/libexec/PlistBuddy -c 'Print :CFBundleShortVersionString' \
  "/Applications/Vintage Radio-arm64.app/Contents/Info.plist"

python3 -c "
import json
from pathlib import Path
for p in [
  Path('/Applications/Vintage Radio-arm64.app/Contents/Frameworks/release_config.json'),
  Path('/Applications/Vintage Radio-arm64.app/Contents/Resources/release_config.json'),
]:
  if p.is_file():
    print(p, json.loads(p.read_text())['update'])
"
```

Expect **`channel: test`**, repo **`alexnoctis76/Vintage_radio-upgrade-test`**.

---

## Step 4 — Run the update test (GUI)

1. Open **`/Applications/Vintage Radio-arm64.app`** (not a dev `python run_vintage_radio.py` build).
2. **Help → Check for updates** → should offer **`v1.1.0-upgrade-test`**.
3. **Download & Install** → app quits → relaunch → About shows new version.

CLI pre-check:

```bash
source .venv/bin/activate
python3 -c "
from gui import updater
r = updater.run_update_check(current_version='v1.0.0-upgrade-test')
print('status', r.status)
print('tag', r.release.tag_name if r.release else None)
a = updater.get_platform_asset(r.release.assets) if r.release else None
print('asset', a.get('name') if a else None)
print('arch pick', updater.preferred_macos_asset_basename())
"
```

On Apple Silicon expect **`Vintage-Radio-macOS-arm64.zip`**.

If install fails: `tail -50 ~/Library/Caches/VintageRadio/update/apply_update.log`

---

## Step 5 — Rosetta scenario (Apple Silicon only)

1. Build or copy **x86_64** old app @ `v1.0.0-upgrade-test` to `/Applications/Vintage Radio-x86_64.app`.
2. Run under Rosetta → Check for updates → must download **arm64** zip.
3. After update, confirm native arm64 in Activity Monitor.

---

## MCP commercials libraries (packaged app)

Dev checkout **`build_test_libraries.py`** creates libraries under **`data/libraries/`**. The **`.app` uses a different data directory**:

`~/Library/Application Support/Vintage Radio/libraries/`

After generating audio on any machine:

```bash
python agent_workshop/build_test_libraries.py
python scripts/seed_packaged_commercials_library.py --all-test-libraries
```

Restart the packaged app (full quit). Libraries:

- **Commercials Test - Folder 99** (`basic` / folder_99) — suites `basic_folder`, `conductor_folder`
- **Commercials Test - Inline** — `conductor_inline`
- **Commercials Test - Both** — `conductor_both`

Track files reference absolute paths under `agent_workshop/test_library_audio/` in the repo; keep the repo path stable on that Mac or regenerate.

**Firmware:** Folder 99 library → install **Vintage Radio Default (Basic)** unless Conductor options are enabled; Conductor install now warns on library mismatch. Flash must include **`dfplayer_protocol.py`**.

**Device MCP:** Start app with `--enable-mcp-debug --mcp-autostart`, connect Pico, sync SD, then run commercials acceptance (Developer menu or `agent_workshop/run_commercials_acceptance.py` when present).

---

## Sign-off checklist (Apple Silicon)

- [ ] Step 0 pytest PASS with VLC `DYLD_LIBRARY_PATH`
- [ ] arm64 build + packaged smoke 16/16 PASS
- [ ] `dfplayer_protocol.py` present in `Contents/Frameworks/firmware/`
- [ ] arm64 zip uploaded to `v1.1.0-upgrade-test`
- [ ] Native arm64 old app → update → **v1.1.0-upgrade-test** OK
- [ ] (Optional) x86_64 old app under Rosetta → arm64 zip → native app OK
- [ ] (Optional) Seed commercials libraries → visible in packaged app after restart
- [ ] (Optional) Pico Basic flash boots without `ImportError: dfplayer_protocol`

---

## Key code changes in this session (for reviewers)

| Topic | Files |
|-------|--------|
| Bundle + flash `dfplayer_protocol` | `build/vintage_radio.spec`, `gui/commercials.py`, `gui/radio_manager.py` |
| macOS updater extract + launch | `gui/updater.py` (`ditto` for zip; CFBundleExecutable) |
| Wedged BOOTSEL volume probe | `gui/sd_manager.py`, `gui/radio_manager.py` |
| SSL for MicroPython download | `gui/services/firmware_bundle.py` |
| mpremote_helper without mpy_cross | `build/mpremote_helper.spec` |
| Packaged smoke / bundle checks | `scripts/packaged_app_smoke.py`, `scripts/packaged_bundle_checks.py` |
| Seed all commercials test libs | `scripts/seed_packaged_commercials_library.py` |
| Conductor vs Basic install warning | `gui/radio_manager.py` |

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| pytest: `FileNotFoundError: libvlccore` | Install VLC.app; set `DYLD_LIBRARY_PATH` as above |
| Libraries missing in `.app` | Run seed script; **quit and reopen** app |
| Update 404 | Upgrade-test repo must stay **public** |
| Wrong zip on Silicon | Rebuild with latest `gui/updater.py`; confirm `preferred_macos_asset_basename()` |
| Pico `ImportError: dfplayer_protocol` | Rebuild/reinstall app; re-flash **Default** firmware |
| Install hangs on SD browse | Pico stuck in BOOTSEL — eject volume or restart `fskit` / replug USB |

---

## After Silicon sign-off

1. Merge **`f-ui-cleanup`** (or equivalent) into main via PR on **Vintage_radio**.
2. Keep **`v1.1.0-upgrade-test`** pre-release on the fork until both Mac arches are confirmed.
3. Restore **`release_config.json`** / version for stable builds before production release (`apply_release_config.py stable`).
