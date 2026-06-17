# Building and Packaging Vintage Radio

This guide covers building the Vintage Radio application from source on Windows, macOS, and Linux, and packaging it for distribution.

## Packaging locally (summary)

1. **One-time setup**: Python 3.8+ (3.11–3.12 recommended if a dependency lacks wheels), venv, `pip install -r requirements.txt pyinstaller`. The project uses **pygame-ce** (drop-in for pygame); prebuilt wheels usually avoid compiling SDL. If you ever build pygame from source on macOS, install SDL: `brew install sdl2 sdl2_image sdl2_mixer sdl2_ttf`.
2. **macOS**: From repo root run `bash build_macos.sh` (unsigned app) or `bash build_macos.sh --no-dmg` for app only. Optional: `--sign` for code signing, `--notarize` for notarized DMG. **Note:** CI only produces an Apple Silicon build; Intel Mac users must build locally.
3. **Windows**: Run `build_windows.bat` (or `pyinstaller vintage_radio.spec`). Run `dist\Vintage Radio\Vintage Radio.exe`.
4. **Linux**: Run `bash build_linux.sh` (or `pyinstaller vintage_radio.spec`). Run `dist/Vintage Radio/Vintage Radio`.
5. **Without scripts**: `pyinstaller vintage_radio.spec --noconfirm` on any OS; output is in `dist/Vintage Radio/` (run the executable inside).

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Building from Source](#building-from-source)
3. [Packaging for Distribution](#packaging-for-distribution)
4. [Troubleshooting](#troubleshooting)

## Prerequisites

### All Platforms

1. **Python 3.8 or higher** – [Download from python.org](https://www.python.org/)
2. **Virtual Environment** (recommended):
   ```bash
   python -m venv venv
   # Windows
   venv\Scripts\activate
   # macOS/Linux
   source venv/bin/activate
   ```
3. **Install Dependencies**:
   ```bash
   pip install -r requirements.txt
   pip install pyinstaller  # For packaging
   ```
4. **External Dependency** – VLC or FFmpeg (for audio conversion):
   - **macOS**: `brew install vlc` or `brew install ffmpeg`
   - **Windows**: [Download VLC](https://www.videolan.org/vlc/) or [FFmpeg](https://ffmpeg.org/download.html)
   - **Linux**: `sudo apt install vlc` or `sudo apt install ffmpeg`

### macOS-Specific

- **Xcode Command Line Tools** (for code signing and notarization):
  ```bash
  xcode-select --install
  ```
- **Apple Developer ID** (for signing and distribution):
  - Register at [developer.apple.com](https://developer.apple.com)
  - Add your certificate to Keychain (optional but needed for `--sign` flag)

### Linux-Specific

- **Development Headers**:
  ```bash
  # Ubuntu/Debian
  sudo apt install libpython3-dev libgl1-mesa-dev libxkbcommon-x11-0 libxkbcommon-x11-dev
  ```

## Building from Source

Simply run the application directly without packaging:

### macOS
```bash
python -m gui.radio_manager
```

### Windows
```bash
python -m gui.radio_manager
```

### Linux
```bash
python -m gui.radio_manager
```

## Packaging for Distribution

Packaging creates a standalone executable or app bundle that doesn't require Python to be installed.

### macOS – Create distribution locally

From the project root (with venv activated and dependencies installed):

| Goal | Command | Output |
|------|---------|--------|
| **App + DMG (default)** | `bash build_macos.sh` | `dist/Vintage Radio.app` and `dist/Vintage Radio.dmg` |
| App only (no DMG) | `bash build_macos.sh --no-dmg` | `dist/Vintage Radio.app` only |
| Signed app + DMG | `bash build_macos.sh --sign` | Same, with code signing (needs Developer ID) |
| Signed + notarized DMG | `bash build_macos.sh --notarize` | Same, DMG notarized for distribution (needs Apple ID) |

**Typical local distribution (no Apple Developer account):**

```bash
cd /path/to/Vintage_radio
source venv/bin/activate   # if you use a venv
bash build_macos.sh
```

You get:
- **`dist/Vintage Radio.app`** – double-click to run
- **`dist/Vintage Radio.dmg`** – share this; recipients open it and drag the app to Applications (or run from the DMG). Requires macOS 13+.

Recipients who get "damaged" or Library Validation errors should run once:  
`xattr -cr "/path/to/Vintage Radio.app"` (see [App won't launch](#app-wont-launch-on-macos--damaged-after-downloading)).

#### Build as App Bundle (Signed)

For distribution or to remove Gatekeeper warnings:

```bash
bash build_macos.sh --sign
```

Requirements:
- Apple Developer ID installed in Keychain
- The script will automatically find it

Output: `dist/Vintage Radio.app` (signed)

#### Build as DMG (Signed and Notarized)

For public distribution (macOS 11+):

```bash
bash build_macos.sh --notarize
```

Requirements:
- Apple Developer ID with notarization entitlement
- Apple ID and app-specific password in Keychain
- `xcrun` and `altool` (from Xcode)

Output: `dist/Vintage Radio.dmg` (signed, notarized, and stapled)

#### Build Without DMG

If you only want the app bundle:

```bash
bash build_macos.sh --no-dmg
```

Output: `dist/Vintage Radio.app` (unsigned)

### Windows

Build as Executable:

```bash
build_windows.bat
```

Or with bash (Git Bash, WSL):

```bash
bash build_windows.bat
```

Output: `dist\Vintage Radio\Vintage Radio.exe`

To run:
```bash
dist\Vintage Radio\Vintage Radio.exe
```

Or double-click the `.exe` in File Explorer.

### Linux

Build as Executable:

```bash
bash build_linux.sh
```

Output: `dist/Vintage Radio/Vintage Radio`

To run:
```bash
./dist/"Vintage Radio"/Vintage Radio
```

Or install desktop shortcut:
```bash
mkdir -p ~/.local/share/applications
cp dist/"Vintage Radio.desktop" ~/.local/share/applications/
```

## Cross-Platform Hardware Detection

The application now detects external storage (SD cards, USB drives) and microcontroller serial ports across all platforms:

### macOS
- **SD Cards/USB Drives**: Detected from `/Volumes`
- **Microcontroller (Pico)**: Detected via USB serial port (e.g., `/dev/cu.usbmodem*`)
- **Permissions**: The app requires no special permissions for local use; the entitlements plist grants USB access if code-signed.

### Windows
- **SD Cards/USB Drives**: Detected by "removable" flag and filesystem type (FAT, FAT32, ExFAT)
- **Microcontroller (Pico)**: Detected as COM port (e.g., `COM3`)

### Linux
- **SD Cards/USB Drives**: Detected from `/mnt` and `/media`
- **Microcontroller (Pico)**: Detected as `/dev/ttyUSB*` or `/dev/ttyACM*`

## Building on Older macOS (11.x)

The build process and resulting app should work on macOS 11+. The PyInstaller-built app uses standard Python and PyQt6, which are compatible with macOS 11.

If you encounter library compatibility issues:
1. Ensure your virtual environment uses Python 3.8+ (compatible with macOS 11)
2. Check that PyQt6 is installed: `pip install PyQt6>=6.8.0`
3. Test on your target macOS version before distributing

## Troubleshooting

### PyInstaller Not Found
```bash
pip install pyinstaller
```

### "Permission denied" on macOS/Linux build scripts
```bash
chmod +x build_macos.sh build_linux.sh
```

### Code signing fails on macOS
```bash
# List installed certificates
security find-identity -v -p codesigning

# If no Developer ID found, sign with self-signed cert (for personal use):
bash build_macos.sh --sign
# (Script will prompt for certificate)
```

### App won't launch on macOS / "damaged" after downloading
If you get **"Vintage Radio is damaged and can't be opened"** (common when the app was downloaded from the web, e.g. a GitHub Actions artifact), macOS Gatekeeper is blocking it because the app is not notarized. Fix:

```bash
# Remove quarantine attributes from the app bundle (use your actual path)
xattr -cr "/path/to/Vintage Radio.app"
```

Then open the app as usual. Alternatively: right-click the app → **Open** → confirm "Open" once; macOS may allow it without the command.

### "Not supported on this Mac" / "bad CPU type in executable"
**GitHub Actions only builds for Apple Silicon (M1/M2/M3).** If you have an **Intel Mac**, the CI macOS artifact will not run on your machine. Build locally instead:

```bash
# Intel Mac: build on your machine (produces native Intel .app)
bash build_macos.sh
# Output: dist/Vintage Radio.app
```

If you have an Apple Silicon Mac and see this error, make sure you are running **Vintage Radio.app** (double-click or `open "Vintage Radio.app"`), not the raw `Vintage Radio` executable inside a folder.

### Serial Port Not Detected (macOS/Linux)
- Ensure the Pico is connected via USB
- On macOS, check System Report > USB for the device
- On Linux, check `ls /dev/ttyUSB*` or `ls /dev/ttyACM*`
- Verify `pyserial` is installed: `pip install pyserial>=3.5`

### External Storage Not Detected
- Verify the drive is mounted: `df` (Linux), `mount` (macOS), or File Explorer (Windows)
- On macOS, check `/Volumes` for your drive
- On Linux, check `/mnt` and `/media`
- On Windows, the drive should appear in File Explorer

### Clean install / SD sync fails on packaged macOS app
The packaged app on macOS stores the library database and backups in **~/Library/Application Support/Vintage Radio/** (not inside the app bundle). This avoids writing into a read-only or replaced bundle. If you had an older build that wrote next to the executable, copy `radio_manager.db` and `backups/` from inside the app’s `Contents/MacOS/` folder into `~/Library/Application Support/Vintage Radio/` if you want to keep that data. The app also extends `PATH` at launch so tools like ffmpeg (e.g. from Homebrew) are found when running SD sync or conversions.

## Building on Windows from Previous Source

If you've previously built this on Windows and want to ensure compatibility:

1. Update the source code:
   ```bash
   git pull
   ```
2. Reinstall dependencies:
   ```bash
   pip install -r requirements.txt --upgrade
   ```
3. Run the build script:
   ```bash
   build_windows.bat
   ```

The updated `detect_sd_roots()` function is fully backward-compatible with Windows while adding support for macOS and Linux.

## Next Steps

- **For Users**: Download pre-built releases from the repository or build using the scripts above
- **For Developers**: Modify `gui/sd_manager.py` to customize hardware detection, or `vintage_radio.spec` to change bundled dependencies
- **For Distribution**: Use `build_macos.sh --notarize` or sign manually for macOS; Windows builds can be distributed as-is (users may see Gatekeeper warnings unless code-signed with a valid certificate)

