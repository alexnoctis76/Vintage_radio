#!/bin/bash
# Build script for Vintage Radio application on macOS
# Usage: bash build_macos.sh [--sign] [--notarize]
#
# Options:
#   --sign         Code sign the app with entitlements (requires Apple Developer ID)
#   --notarize     Notarize the .dmg for distribution (requires Developer ID)
#   --no-dmg       Skip creating .dmg and just build the .app
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

# Clean previous build
echo "Cleaning previous build..."
rm -rf "$BUILD_DIR"
mkdir -p "$BUILD_DIR"

# Run PyInstaller
echo "Building application with PyInstaller..."
pyinstaller "$SPEC_FILE" --noconfirm --distpath "$BUILD_DIR" --buildpath "$SCRIPT_DIR/build" --specpath "$SCRIPT_DIR"

if [ ! -d "$APP_BUNDLE" ]; then
    echo "Error: Failed to build app bundle at $APP_BUNDLE"
    exit 1
fi

echo "✓ App bundle created at $APP_BUNDLE"

# Code sign if requested
if [ "$SIGN" = true ]; then
    echo ""
    echo "Code signing application..."

    # Find Developer ID (first one found)
    IDENTITY=$(security find-identity -v -p codesigning | grep "Developer ID Application" | head -1 | awk '{print $2}')

    if [ -z "$IDENTITY" ]; then
        echo "Error: No Developer ID found in keychain"
        echo "To create one, visit https://developer.apple.com and set up a Developer ID"
        exit 1
    fi

    echo "Using identity: $IDENTITY"

    # Sign the app with entitlements
    if [ -f "$ENTITLEMENTS_FILE" ]; then
        codesign --force --deep --sign "$IDENTITY" --entitlements "$ENTITLEMENTS_FILE" "$APP_BUNDLE"
        echo "✓ App signed with entitlements"
    else
        codesign --force --deep --sign "$IDENTITY" "$APP_BUNDLE"
        echo "✓ App signed (no entitlements file found)"
    fi

    # Verify signature
    codesign --verify --verbose "$APP_BUNDLE"
    echo "✓ Signature verified"
fi

# Create DMG if requested
if [ "$BUILD_DMG" = true ]; then
    echo ""
    echo "Creating DMG installer..."

    # Remove old DMG
    rm -f "$DMG_OUTPUT"

    # Create DMG
    hdiutil create -volname "$APP_NAME" \
        -srcfolder "$BUILD_DIR" \
        -ov -format UDZO "$DMG_OUTPUT"

    if [ -f "$DMG_OUTPUT" ]; then
        echo "✓ DMG created at $DMG_OUTPUT"

        # Code sign DMG if requested
        if [ "$SIGN" = true ]; then
            echo "Signing DMG..."
            codesign --force --sign "$IDENTITY" "$DMG_OUTPUT"
            echo "✓ DMG signed"
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

    # Submit for notarization
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

    # Poll for notarization status
    while true; do
        STATUS=$(xcrun altool --notarization-info "$NOTARIZE_UUID" \
            --output-format json 2>/dev/null | grep -o '"Status" : "[^"]*' | cut -d'"' -f4)

        if [ "$STATUS" = "invalid" ]; then
            echo "Error: Notarization failed"
            exit 1
        elif [ "$STATUS" = "success" ]; then
            echo "✓ Notarization successful"

            # Staple the ticket
            xcrun stapler staple "$DMG_OUTPUT"
            echo "✓ Notarization ticket stapled"
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
if [ "$BUILD_DMG" = true ]; then
    echo "DMG: $DMG_OUTPUT"
    if [ "$NOTARIZE" = true ]; then
        echo "Status: Signed and notarized ✓"
    elif [ "$SIGN" = true ]; then
        echo "Status: Signed ✓"
    else
        echo "Status: Unsigned (for distribution, run: bash build_macos.sh --sign)"
    fi
else
    echo "App Bundle: $APP_BUNDLE"
    if [ "$SIGN" = true ]; then
        echo "Status: Signed ✓"
    else
        echo "Status: Unsigned"
    fi
fi
echo "=========================================="

