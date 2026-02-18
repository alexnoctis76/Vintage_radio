#!/bin/bash
# Build script for macOS - builds Vintage Radio.app locally
# This ensures PyQt6 libraries are compatible with your macOS version

set -e  # Exit on error

echo "=========================================="
echo "Building Vintage Radio for macOS"
echo "=========================================="

# Check Python version
echo ""
echo "Checking Python version..."
python3 --version

# Upgrade pip
echo ""
echo "Upgrading pip..."
python3 -m pip install --upgrade pip

# Install dependencies
echo ""
echo "Installing dependencies..."
python3 -m pip install -r requirements.txt
python3 -m pip install pyinstaller

# Create .icns icon from PNG (if it doesn't exist)
if [ ! -f "gui/resources/vintage_radio.icns" ]; then
    echo ""
    echo "Creating .icns icon..."
    mkdir -p vintage_radio.iconset
    sips -z 16 16     gui/resources/vintage_radio.png --out vintage_radio.iconset/icon_16x16.png
    sips -z 32 32     gui/resources/vintage_radio.png --out vintage_radio.iconset/icon_16x16@2x.png
    sips -z 32 32     gui/resources/vintage_radio.png --out vintage_radio.iconset/icon_32x32.png
    sips -z 64 64     gui/resources/vintage_radio.png --out vintage_radio.iconset/icon_32x32@2x.png
    sips -z 128 128   gui/resources/vintage_radio.png --out vintage_radio.iconset/icon_128x128.png
    sips -z 256 256   gui/resources/vintage_radio.png --out vintage_radio.iconset/icon_128x128@2x.png
    sips -z 256 256   gui/resources/vintage_radio.png --out vintage_radio.iconset/icon_256x256.png
    sips -z 512 512   gui/resources/vintage_radio.png --out vintage_radio.iconset/icon_256x256@2x.png
    sips -z 512 512   gui/resources/vintage_radio.png --out vintage_radio.iconset/icon_512x512.png
    sips -z 1024 1024 gui/resources/vintage_radio.png --out vintage_radio.iconset/icon_512x512@2x.png
    iconutil -c icns vintage_radio.iconset -o gui/resources/vintage_radio.icns
    rm -rf vintage_radio.iconset
    echo "Icon created!"
else
    echo ""
    echo "Icon already exists, skipping..."
fi

# Set deployment target to match your macOS version (or 11.0 for compatibility)
export MACOSX_DEPLOYMENT_TARGET=11.0

# Build with PyInstaller
echo ""
echo "Building with PyInstaller..."
echo "This may take a few minutes..."
python3 -m PyInstaller vintage_radio.spec

# Check if build succeeded
if [ -d "dist/Vintage Radio.app" ]; then
    echo ""
    echo "=========================================="
    echo "✅ Build successful!"
    echo "=========================================="
    echo ""
    echo "Your app is located at:"
    echo "  dist/Vintage Radio.app"
    echo ""
    echo "To run it:"
    echo "  open 'dist/Vintage Radio.app'"
    echo ""
    echo "Or from Terminal:"
    echo "  ./dist/Vintage\\ Radio.app/Contents/MacOS/Vintage\\ Radio"
    echo ""
else
    echo ""
    echo "=========================================="
    echo "❌ Build failed!"
    echo "=========================================="
    echo "Check the error messages above."
    exit 1
fi

