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
APP_NAME="Vintage Radio"
BUILD_DIR="$SCRIPT_DIR/dist"
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

# Check for PyInstaller
if ! command -v pyinstaller &> /dev/null; then
    echo "Error: PyInstaller not found. Install with: pip install pyinstaller"
    exit 1
fi

# --- Generate .icns icon from SVG ---
SVG_ICON="$SCRIPT_DIR/gui/resources/vintage_radio.svg"
ICNS_ICON="$SCRIPT_DIR/gui/resources/vintage_radio.icns"
PNG_ICON="$SCRIPT_DIR/gui/resources/vintage_radio.png"

if [ -f "$SVG_ICON" ]; then
    echo "Generating .icns icon from SVG..."

    ICONSET_DIR="$SCRIPT_DIR/gui/resources/vintage_radio.iconset"
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
rm -rf "$SCRIPT_DIR/build"
mkdir -p "$BUILD_DIR"

# Run PyInstaller (spec now produces a .app bundle on macOS via BUNDLE step)
echo "Building application with PyInstaller..."
pyinstaller "$SPEC_FILE" --noconfirm --distpath "$BUILD_DIR" --workpath "$SCRIPT_DIR/build"

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

# Code sign if requested
if [ "$SIGN" = true ]; then
    echo ""
    echo "Code signing application..."

    IDENTITY=$(security find-identity -v -p codesigning | grep "Developer ID Application" | head -1 | awk '{print $2}')

    if [ -z "$IDENTITY" ]; then
        echo "Warning: No Developer ID found in keychain"
        echo "Attempting ad-hoc signing (good for local use)..."
        IDENTITY="-"
    fi

    echo "Using identity: $IDENTITY"

    if [ -f "$ENTITLEMENTS_FILE" ] && [ "$IDENTITY" != "-" ]; then
        codesign --deep --force --sign "$IDENTITY" --entitlements "$ENTITLEMENTS_FILE" "$APP_BUNDLE"
    else
        codesign --deep --force --sign "$IDENTITY" "$APP_BUNDLE"
    fi

    echo "Application signed"

    if codesign --verify --verbose "$APP_BUNDLE" 2>/dev/null; then
        echo "Signature verified"
    else
        echo "Warning: Signature verification returned non-zero (may be fine for ad-hoc)"
    fi
fi

# Create DMG if requested
if [ "$BUILD_DMG" = true ]; then
    echo ""
    echo "Creating DMG installer..."

    rm -f "$DMG_OUTPUT"

    DMG_STAGING="$SCRIPT_DIR/build/dmg_staging"
    rm -rf "$DMG_STAGING"
    mkdir -p "$DMG_STAGING"
    cp -R "$APP_BUNDLE" "$DMG_STAGING/"

    hdiutil create -volname "$APP_NAME" \
        -srcfolder "$DMG_STAGING" \
        -ov -format UDZO "$DMG_OUTPUT"

    rm -rf "$DMG_STAGING"

    if [ -f "$DMG_OUTPUT" ]; then
        echo "DMG created at $DMG_OUTPUT"

        if [ "$SIGN" = true ] && [ "$IDENTITY" != "-" ]; then
            echo "Signing DMG..."
            codesign --force --sign "$IDENTITY" "$DMG_OUTPUT"
            echo "DMG signed"
        fi
    else
        echo "Warning: Failed to create DMG"
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
echo "Output: $APP_BUNDLE"
echo "Run:    open \"$APP_BUNDLE\""
if [ "$BUILD_DMG" = true ] && [ -f "$DMG_OUTPUT" ]; then
    echo "DMG:    $DMG_OUTPUT"
fi
if [ "$SIGN" = true ]; then
    echo "Signed: yes"
fi
echo "=========================================="
