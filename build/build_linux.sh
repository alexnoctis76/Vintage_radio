#!/bin/bash
# Build script for Vintage Radio application on Linux
# Usage: bash build_linux.sh [--no-clean]
#
# Prerequisites:
#   - Python 3.8+ with venv
#   - PyInstaller: pip install pyinstaller
#   - Development headers: libpython3-dev, libgl1-mesa-dev, libxkbcommon-x11-0
#
# Output: dist/Vintage Radio/ (app folder with executable)

set -e  # Exit on error

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$( cd "$SCRIPT_DIR/.." && pwd )"
APP_NAME="Vintage Radio"
BUILD_DIR="$PROJECT_ROOT/dist"
APP_DIR="$BUILD_DIR/Vintage Radio"
SPEC_FILE="$SCRIPT_DIR/vintage_radio.spec"

CLEAN=true

# Parse command-line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --no-clean)
            CLEAN=false
            shift
            ;;
        *)
            echo "Unknown option: $1"
            echo "Usage: bash build_linux.sh [--no-clean]"
            exit 1
            ;;
    esac
done

echo "=========================================="
echo "Vintage Radio Linux Build Script"
echo "=========================================="
echo "App Name: $APP_NAME"
echo "Build Directory: $BUILD_DIR"
echo "Clean: $CLEAN"
echo "=========================================="

# Check for PyInstaller
if ! command -v pyinstaller &> /dev/null; then
    echo "Error: PyInstaller not found. Install with: pip install pyinstaller"
    exit 1
fi

# Clean previous build
if [ "$CLEAN" = true ]; then
    echo "Cleaning previous build..."
    rm -rf "$BUILD_DIR"
    mkdir -p "$BUILD_DIR"
fi

# Run PyInstaller
echo "Building application with PyInstaller..."
pyinstaller "$SPEC_FILE" --noconfirm --distpath "$BUILD_DIR" --workpath "$PROJECT_ROOT/build/pyinstaller_temp" --specpath "$SCRIPT_DIR"

if [ ! -d "$APP_DIR" ]; then
    echo "Error: Failed to build app directory at $APP_DIR"
    exit 1
fi

echo "✓ App directory created at $APP_DIR"

# Make the main executable executable
EXECUTABLE="$APP_DIR/Vintage Radio"
if [ -f "$EXECUTABLE" ]; then
    chmod +x "$EXECUTABLE"
    echo "✓ Executable permissions set"
else
    echo "Warning: Executable not found at $EXECUTABLE"
fi

# Create a desktop shortcut (optional)
DESKTOP_FILE="$BUILD_DIR/Vintage Radio.desktop"
cat > "$DESKTOP_FILE" << 'EOF'
[Desktop Entry]
Version=1.0
Type=Application
Name=Vintage Radio
Comment=Music Manager for Vintage AM Radio
Icon=vintage_radio
Exec=$APP_EXECUTABLE
Categories=Utility;
Terminal=false
EOF

# Replace $APP_EXECUTABLE with actual path
sed -i "s|\$APP_EXECUTABLE|$EXECUTABLE|g" "$DESKTOP_FILE"
chmod +x "$DESKTOP_FILE"
echo "✓ Desktop shortcut created"

echo ""
echo "=========================================="
echo "Build Complete!"
echo "=========================================="
echo "App Directory: $APP_DIR"
echo ""
echo "To run the app:"
echo "  $EXECUTABLE"
echo ""
echo "To create a system shortcut, copy $DESKTOP_FILE to ~/.local/share/applications/"
echo "=========================================="

