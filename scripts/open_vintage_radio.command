#!/bin/bash
# ============================================================
# Vintage Radio - macOS Launcher
# ============================================================
# IMPORTANT: If macOS says "cannot be opened because it is from
# an unidentified developer", you need to RIGHT-CLICK this file
# and select "Open" → "Open" in the dialog (first time only).
#
# This script removes the macOS quarantine flag and launches
# Vintage Radio. After the first run, you can just double-click
# Vintage Radio.app directly.
#
# Why is this needed?
# macOS Gatekeeper blocks unsigned apps downloaded from the
# internet. This script removes the quarantine attribute so
# the app can run without the "cannot be verified" warning.
# ============================================================

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
APP_NAME="Vintage Radio"

# Look for the executable in the same directory
if [ -f "$SCRIPT_DIR/$APP_NAME" ]; then
    APP_PATH="$SCRIPT_DIR/$APP_NAME"
elif [ -d "$SCRIPT_DIR/$APP_NAME.app" ]; then
    APP_PATH="$SCRIPT_DIR/$APP_NAME.app"
else
    echo "Error: Could not find '$APP_NAME' in: $SCRIPT_DIR"
    echo "Make sure this script is in the same folder as the Vintage Radio app."
    echo ""
    echo "Press any key to close..."
    read -n 1
    exit 1
fi

echo "Removing macOS quarantine flag..."
xattr -dr com.apple.quarantine "$SCRIPT_DIR" 2>/dev/null

echo "Launching $APP_NAME..."
if [ -d "$APP_PATH" ]; then
    # .app bundle
    open "$APP_PATH"
else
    # Direct executable
    "$APP_PATH" &
fi

echo "Done!"

