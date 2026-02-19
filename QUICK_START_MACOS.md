# Quick Start: Building Vintage Radio for macOS

This is a quick reference guide for packaging your Vintage Radio app for macOS 11+.

## Prerequisites (One-Time Setup)

```bash
# Install Xcode Command Line Tools (for code signing)
xcode-select --install

# Install PyInstaller
pip install pyinstaller

# Verify your environment
python --version           # Should be 3.8+
pip list | grep PyQt6     # Should see PyQt6
pip list | grep psutil    # Should see psutil
```

## Building the App

### Option 1: Unsigned (for personal use on your Mac)

```bash
bash build_macos.sh
open dist/"Vintage Radio.app"
```

**Result**: A working `.app` bundle you can move to Applications folder

**Time**: ~5-10 minutes

### Option 2: Signed (to remove Gatekeeper warnings)

```bash
bash build_macos.sh --sign
open dist/"Vintage Radio.app"
```

**Requirements**: Developer ID in Keychain (optional for personal use)

**Result**: Code-signed app that bypasses Gatekeeper

**Time**: ~5-10 minutes (+ signing)

### Option 3: Full Distribution (DMG + notarized)

```bash
bash build_macos.sh --notarize
# Wait for notarization to complete (5-10 minutes)
# Result: dist/Vintage Radio.dmg
```

**Requirements**: 
- Apple Developer account
- Apple ID with app-specific password
- Developer ID certificate

**Result**: Fully notarized `.dmg` for distributing to other users

**Time**: ~15-20 minutes (including notarization wait)

## Testing the Packaged App

After building, test that hardware detection works:

```bash
# Test on the packaged app
./dist/"Vintage Radio.app"/Contents/MacOS/"Vintage Radio"

# You should see:
# ✓ SD Card Detection (finds external drives)
# ✓ Serial Port Detection (finds your Pico)
```

Or run the test script directly:

```bash
python test_hardware_detection.py
```

## Building on Older macOS (11.x)

The app should work fine on macOS 11. If you encounter issues:

1. **Check Python version**:
   ```bash
   python --version  # Must be 3.8+
   ```

2. **Update PyQt6**:
   ```bash
   pip install --upgrade PyQt6
   ```

3. **Rebuild with verbose output**:
   ```bash
   pyinstaller vintage_radio.spec --verbose
   ```

## Troubleshooting

### "PyInstaller not found"
```bash
pip install pyinstaller
```

### "Permission denied" on build script
```bash
chmod +x build_macos.sh
bash build_macos.sh
```

### App won't start on your Mac
If you get "App is damaged":
```bash
xattr -d com.apple.quarantine dist/"Vintage Radio.app"
```

### Serial port (Pico) not detected
1. Plug in your Pico via USB
2. Check System Report > USB to see the device
3. Verify `pyserial` installed: `pip install pyserial`

### SD card not detected
1. Plug in your SD card reader/USB drive
2. Check Finder > Devices to see if it appears
3. It should show up in the app's "Select Drive" dialog

## What Each Build Produces

| Command | Output | For | Time |
|---------|--------|-----|------|
| `bash build_macos.sh` | `dist/Vintage Radio.app` | Personal use | 5-10 min |
| `bash build_macos.sh --sign` | `dist/Vintage Radio.app` (signed) | Remove warnings | 5-10 min |
| `bash build_macos.sh --no-dmg` | `dist/Vintage Radio.app` | Quick test | 5-10 min |
| `bash build_macos.sh --notarize` | `dist/Vintage Radio.dmg` | Distribution | 15-20 min |

## Next Steps

1. **Build the app**:
   ```bash
   bash build_macos.sh
   ```

2. **Test hardware detection**:
   ```bash
   python test_hardware_detection.py
   ```

3. **Try the packaged app**:
   ```bash
   open dist/"Vintage Radio.app"
   ```

4. **Move to Applications** (optional):
   ```bash
   cp -r dist/"Vintage Radio.app" /Applications/
   ```

5. **Test with your hardware**:
   - Plug in SD card → Should appear in "Select Drive"
   - Plug in Pico → Should appear in "Device Debug" > port list
   - Import music and sync to verify it works

## Support

See these files for more details:
- `BUILD_AND_PACKAGE.md` - Comprehensive guide for all platforms
- `IMPLEMENTATION_SUMMARY.md` - Technical overview of changes
- `WINDOWS_COMPATIBILITY.md` - Verify Windows still works

---

**Happy building!** 🎉

After successfully testing, you can:
- Keep using the packaged `.app`
- Share it with friends (just the `.app` folder)
- Create a `.dmg` installer for distribution

