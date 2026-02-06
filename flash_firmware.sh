#!/bin/bash
# Flash Vintage Radio firmware to Raspberry Pi Pico
# Usage: ./flash_firmware.sh [DEVICE]
# Example: ./flash_firmware.sh /dev/ttyACM0

DEVICE=${1:-/dev/ttyACM0}

echo "========================================"
echo "Flashing Vintage Radio Firmware"
echo "========================================"
echo ""
echo "Device: $DEVICE"
echo ""

# Check if device exists
if [ ! -e "$DEVICE" ]; then
    echo "ERROR: Device $DEVICE not found"
    echo "Make sure Pico is connected"
    exit 1
fi

echo "[1/4] Creating firmware directory..."
mpremote connect "$DEVICE" mkdir firmware || {
    echo "ERROR: Could not connect to Pico on $DEVICE"
    exit 1
}

echo "[2/4] Copying radio_core.py..."
mpremote connect "$DEVICE" cp radio_core.py :

echo "[3/4] Copying main.py..."
mpremote connect "$DEVICE" cp main.py :

echo "[4/4] Copying firmware/dfplayer_hardware.py..."
mpremote connect "$DEVICE" cp firmware/dfplayer_hardware.py :firmware/dfplayer_hardware.py

echo ""
echo "========================================"
echo "Firmware flashed successfully!"
echo "========================================"
echo ""
echo "To run the firmware, use:"
echo "  mpremote connect $DEVICE run main.py"
echo ""
echo "Or to make it auto-run on boot:"
echo "  mpremote connect $DEVICE cp main.py :boot.py"
echo ""

