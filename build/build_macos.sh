#!/bin/bash
# Build script for Vintage Radio application on macOS
# Usage: bash build_macos.sh [--sign] [--notarize]
#
# Options:
#   --sign         Code sign the app with entitlements (requires Apple Developer ID)
#   --notarize     Notarize the .dmg for distribution (requires Developer ID)
#   --no-dmg       Skip creating .dmg and just build the app
#
# Prerequisites:
#   - Python 3.8+ with venv
#   - PyInstaller: pip install pyinstaller
#   - For signing: Apple Developer ID and codesign utility
#   - For notarization: altool configured with developer credentials


set -e  # Exit on error

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$( cd "$SCRIPT_DIR/.." && pwd )"
cd "$PROJECT_ROOT"

# Use project venv if it exists (ensures same Python/packages as when running from terminal)
if [ -d "$PROJECT_ROOT/venv" ]; then
    source "$PROJECT_ROOT/venv/bin/activate"
    echo "Using venv Python: $(which python3)"
elif [ -d "$PROJECT_ROOT/.venv" ]; then
    source "$PROJECT_ROOT/.venv/bin/activate"
    echo "Using .venv Python: $(which python3)"
fi

APP_NAME="Vintage Radio"
BUILD_DIR="$PROJECT_ROOT/dist"
APP_BUNDLE="$BUILD_DIR/Vintage Radio.app"
DMG_OUTPUT="$BUILD_DIR/Vintage Radio.dmg"
SPEC_FILE="$SCRIPT_DIR/vintage_radio.spec"
ENTITLEMENTS_FILE="$SCRIPT_DIR/macos_entitlements.plist"
SIGN=false
NOTARIZE=false
BUILD_DMG=true

# Parse command-line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --sign)
            SIGN=true
            shift
            ;;
        --notarize)
            NOTARIZE=true
            SIGN=true  # Notarization requires signing
            shift
            ;;
        --no-dmg)
            BUILD_DMG=false
            shift
            ;;
        *)
            echo "Unknown option: $1"
            echo "Usage: bash build_macos.sh [--sign] [--notarize] [--no-dmg]"
            exit 1
            ;;
    esac
done

echo "=========================================="
echo "Vintage Radio macOS Build Script"
echo "=========================================="
echo "App Name: $APP_NAME"
echo "Build Directory: $BUILD_DIR"
echo "Code Sign: $SIGN"
echo "Notarize: $NOTARIZE"
echo "Create DMG: $BUILD_DMG"
echo "=========================================="

# Check for PyInstaller (use same Python as venv for consistent build)
if ! python3 -c "import PyInstaller" 2>/dev/null; then
    echo "Error: PyInstaller not found. Install with: pip install pyinstaller"
    exit 1
fi

# Check for mpremote (required for bundled Pico flashing; must be in same env as pyinstaller)
echo "Python: $(which python3) ($(python3 --version 2>&1))"
if ! python3 -c "from mpremote.main import main" 2>/dev/null; then
    echo "Error: mpremote not found. The packaged app needs it for 'Setup Pico' / 'Install to Pico'."
    echo "  With venv activated, run: pip install mpremote"
    echo "  Then run this build script again."
    echo ""
    echo "If you don't see 'Using venv Python' above, create a venv first:"
    echo "  python3 -m venv venv && source venv/bin/activate && pip install mpremote"
    exit 1
fi
echo "mpremote: OK (will be bundled)"

# --- Generate .icns icon from SVG ---
SVG_ICON="$PROJECT_ROOT/gui/resources/vintage_radio.svg"
ICNS_ICON="$PROJECT_ROOT/gui/resources/vintage_radio.icns"
PNG_ICON="$PROJECT_ROOT/gui/resources/vintage_radio.png"

if [ -f "$SVG_ICON" ]; then
    echo "Generating .icns icon from SVG..."

    ICONSET_DIR="$PROJECT_ROOT/gui/resources/vintage_radio.iconset"
    rm -rf "$ICONSET_DIR"
    mkdir -p "$ICONSET_DIR"

    # Render SVG to a high-res PNG using Python + PyQt6
    python3 -c "
from PyQt6.QtSvg import QSvgRenderer
from PyQt6.QtGui import QImage, QPainter
from PyQt6.QtCore import QSize, Qt
renderer = QSvgRenderer('$SVG_ICON')
for size in [16, 32, 64, 128, 256, 512, 1024]:
    img = QImage(QSize(size, size), QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    renderer.render(p)
    p.end()
    if size <= 512:
        img.save('$ICONSET_DIR/icon_{}x{}.png'.format(size, size))
    if size >= 32:
        half = size // 2
        img.save('$ICONSET_DIR/icon_{}x{}@2x.png'.format(half, half))
"

    # Also save a 512px PNG for fallback use
    if [ ! -f "$PNG_ICON" ]; then
        cp "$ICONSET_DIR/icon_512x512.png" "$PNG_ICON"
    fi

    iconutil -c icns "$ICONSET_DIR" -o "$ICNS_ICON"
    rm -rf "$ICONSET_DIR"

    if [ -f "$ICNS_ICON" ]; then
        echo "Icon generated: $ICNS_ICON"
    else
        echo "Warning: iconutil failed to create .icns; build will continue without custom icon"
    fi
else
    echo "Warning: SVG icon not found at $SVG_ICON; skipping .icns generation"
fi

# Clean previous build
echo "Cleaning previous build..."
rm -rf "$BUILD_DIR"
rm -rf "$PROJECT_ROOT/build/pyinstaller_temp"
mkdir -p "$BUILD_DIR"

# Run PyInstaller (spec now produces a .app bundle on macOS via BUNDLE step)
echo "Building application with PyInstaller..."
python3 -m PyInstaller "$SPEC_FILE" --noconfirm --distpath "$BUILD_DIR" --workpath "$PROJECT_ROOT/build/pyinstaller_temp"

# Verify the .app bundle was created
if [ ! -d "$APP_BUNDLE" ]; then
    echo "Error: PyInstaller build failed - expected .app bundle at: $APP_BUNDLE"
    echo "Check the PyInstaller output above for errors."
    exit 1
fi

APP_EXE="$APP_BUNDLE/Contents/MacOS/Vintage Radio"
if [ ! -f "$APP_EXE" ]; then
    echo "Error: Executable not found at $APP_EXE"
    exit 1
fi

echo "Build successful: $APP_BUNDLE"
echo "  Executable: $APP_EXE"

# Build mpremote helper (standalone exe, no Qt) for macOS - avoids pyserial+Qt crash in main app
echo ""
echo "Building mpremote helper (for Setup Pico on packaged macOS)..."
HELPER_SPEC="$SCRIPT_DIR/mpremote_helper.spec"
HELPER_DIR="$BUILD_DIR/mpremote_helper"
HELPER_EXE="$HELPER_DIR/mpremote_helper"
mkdir -p "$PROJECT_ROOT/build/pyinstaller_temp/mpremote_helper"
if python3 -m PyInstaller "$HELPER_SPEC" --noconfirm --distpath "$BUILD_DIR" --workpath "$PROJECT_ROOT/build/pyinstaller_temp/mpremote_helper"; then
    if [ -d "$HELPER_DIR" ] && [ -f "$HELPER_EXE" ]; then
        cp -R "$HELPER_DIR" "$APP_BUNDLE/Contents/MacOS/"
        chmod +x "$APP_BUNDLE/Contents/MacOS/mpremote_helper/mpremote_helper"
        # Remove .dist-info (metadata) - codesign rejects it; not needed at runtime
        find "$APP_BUNDLE/Contents/MacOS/mpremote_helper" -type d -name "*.dist-info" -print0 | xargs -0 rm -rf 2>/dev/null || true
        echo "  mpremote_helper installed in app bundle (one-folder, no extraction delay)"
    fi
else
    echo "  Warning: mpremote_helper build failed; Setup Pico will require system Python (python3 -m pip install mpremote)"
fi

# Remove PyInstaller's ad-hoc signatures so shared DMG gets "unidentified developer" + Open Anyway, not "damaged"
if [ "$SIGN" = false ]; then
    echo ""
    echo "Removing ad-hoc signatures (for Open Anyway when shared)..."
    _strip_count=0
    while IFS= read -r -d '' f; do
        if codesign --remove --all-architectures "$f" 2>/dev/null; then
            _strip_count=$((_strip_count + 1))
        fi
    done < <(find "$APP_BUNDLE" -type f \( -perm +111 -o -name "*.dylib" -o -name "*.so" \) -print0 2>/dev/null)
    rm -rf "$APP_BUNDLE/Contents/_CodeSignature" 2>/dev/null || true
    [ "$_strip_count" -gt 0 ] && echo "  Removed signature from $_strip_count binary(ies)"
fi

# Code sign only with Developer ID. Ad-hoc signing (-) causes "damaged" when the app
# is shared/downloaded; unsigned apps get "unidentified developer" which allows Open Anyway in Settings.
IDENTITY=""
if [ "$SIGN" = true ]; then
    echo ""
    echo "Code signing application..."

    IDENTITY=$(security find-identity -v -p codesigning | grep "Developer ID Application" | head -1 | awk '{print $2}')

    if [ -z "$IDENTITY" ]; then
        echo "Skipping signing: No Developer ID found."
        echo "  (Ad-hoc signing would cause 'damaged' when shared. Unsigned app allows Open Anyway in Settings.)"
        SIGN=false
    else
        echo "Using identity: $IDENTITY"
        if [ -f "$ENTITLEMENTS_FILE" ]; then
            if codesign --deep --force --sign "$IDENTITY" --entitlements "$ENTITLEMENTS_FILE" "$APP_BUNDLE"; then
                echo "Application signed"
            else
                echo "Warning: App signing failed. DMG will contain unsigned app."
                SIGN=false
            fi
        else
            if codesign --deep --force --sign "$IDENTITY" "$APP_BUNDLE"; then
                echo "Application signed"
            else
                echo "Warning: App signing failed. DMG will contain unsigned app."
                SIGN=false
            fi
        fi
    fi
fi

# Create DMG (signed app if signing succeeded)
if [ "$BUILD_DMG" = true ]; then
    echo ""
    echo "Creating DMG installer..."

    rm -f "$DMG_OUTPUT"

    DMG_STAGING="$PROJECT_ROOT/build/pyinstaller_temp/dmg_staging"
    rm -rf "$DMG_STAGING"
    mkdir -p "$DMG_STAGING"
    cp -R "$APP_BUNDLE" "$DMG_STAGING/"
    ln -s /Applications "$DMG_STAGING/Applications"

    # Clear quarantine/extended attributes so app runs without xattr workaround when DMG is used locally
    xattr -cr "$DMG_STAGING/$APP_NAME.app" 2>/dev/null || true

    # README with Open Anyway instructions (works for unsigned/unidentified apps; no Terminal needed)
    cat > "$DMG_STAGING/README - START HERE.txt" << 'README_EOF'
FIRST TIME: Allow the app in System Settings

1. Double-click "Vintage Radio" (you'll see a security message - that's expected)
2. Open System Settings (Apple menu > System Settings)
3. Go to Privacy & Security
4. Scroll to Security
5. Click "Open Anyway" next to the Vintage Radio message
6. Enter your password if asked

After that, double-click Vintage Radio anytime - or drag it to Applications first.

The "Open Anyway" button is available for about an hour after step 1.
README_EOF

    hdiutil create -volname "$APP_NAME" \
        -srcfolder "$DMG_STAGING" \
        -ov -format UDZO \
        -imagekey zlib-level=9 \
        "$DMG_OUTPUT"

    rm -rf "$DMG_STAGING"

    if [ -f "$DMG_OUTPUT" ]; then
        echo "DMG created at $DMG_OUTPUT"
    else
        echo "Warning: Failed to create DMG"
    fi

    if [ "$SIGN" = true ] && [ -n "$IDENTITY" ] && [ "$IDENTITY" != "-" ]; then
        echo "Signing DMG..."
        if codesign --force --sign "$IDENTITY" "$DMG_OUTPUT"; then
            echo "DMG signed"
        fi
    fi
fi

# Notarize if requested (requires Developer ID and Apple ID configured)
if [ "$NOTARIZE" = true ]; then
    echo ""
    echo "Notarizing DMG (this may take several minutes)..."

    if [ ! -f "$DMG_OUTPUT" ]; then
        echo "Error: DMG not found. Cannot notarize without DMG."
        exit 1
    fi

    NOTARIZE_UUID=$(xcrun altool --notarize-app \
        --file "$DMG_OUTPUT" \
        --primary-bundle-id "com.zionbrock.vintage-radio" \
        --output-format json 2>/dev/null | grep -o '"id" : "[^"]*' | cut -d'"' -f4)

    if [ -z "$NOTARIZE_UUID" ]; then
        echo "Error: Failed to submit for notarization"
        echo "Ensure your Apple ID credentials are configured in Keychain"
        exit 1
    fi

    echo "Notarization submitted (UUID: $NOTARIZE_UUID)"
    echo "Waiting for notarization to complete..."

    while true; do
        STATUS=$(xcrun altool --notarization-info "$NOTARIZE_UUID" \
            --output-format json 2>/dev/null | grep -o '"Status" : "[^"]*' | cut -d'"' -f4)

        if [ "$STATUS" = "invalid" ]; then
            echo "Error: Notarization failed"
            exit 1
        elif [ "$STATUS" = "success" ]; then
            echo "Notarization successful"
            xcrun stapler staple "$DMG_OUTPUT"
            echo "Notarization ticket stapled"
            break
        else
            echo "Status: $STATUS... waiting (check back in 30 seconds)"
            sleep 30
        fi
    done
fi

echo ""
echo "=========================================="
echo "Build Complete!"
echo "=========================================="
if [ "$SIGN" = false ] && [ -f "$ENTITLEMENTS_FILE" ]; then
    echo ""
    echo "Note: For serial/USB (Setup Pico) to work, sign the app so entitlements apply:"
    echo "  bash build/build_macos.sh --sign"
fi
if [ "$SIGN" = true ] && [ "$NOTARIZE" = false ]; then
    echo ""
    echo "Note: For distribution (avoid 'damaged' when downloaded), notarize the DMG:"
    echo "  bash build/build_macos.sh --sign --notarize"
fi
echo "Output: $APP_BUNDLE"
echo "Run:    open \"$APP_BUNDLE\""
if [ "$BUILD_DMG" = true ] && [ -f "$DMG_OUTPUT" ]; then
    echo "DMG:    $DMG_OUTPUT"
fi
if [ "$SIGN" = true ]; then
    echo "Signed: yes"
fi
echo "=========================================="
