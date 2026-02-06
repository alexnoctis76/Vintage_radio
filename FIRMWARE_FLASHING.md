# Firmware Flashing Guide

## Overview
This guide explains how to flash the Vintage Radio firmware to a Raspberry Pi Pico (RP2040).

## Prerequisites
1. **Raspberry Pi Pico** (or Pico W) with MicroPython firmware installed
2. **USB cable** to connect Pico to your computer
3. **Choose your method:**
   - **Option A**: Use Cursor/VS Code terminal with `mpremote` (recommended if you're already using Cursor)
   - **Option B**: Use Thonny IDE (easiest for beginners)
   - **Option C**: Use `rshell` (alternative command-line tool)

## Method 1: Using Cursor/VS Code Terminal with mpremote (Recommended)

### Step 1: Install mpremote
Open a terminal in Cursor and run:
```bash
pip install mpremote
```

### Step 2: Connect Pico
1. Hold the **BOOTSEL** button on your Pico
2. Connect Pico to your computer via USB
3. Release BOOTSEL button
4. Wait a few seconds for Windows to recognize the device

### Step 3: Find COM Port (Windows)
- Open Device Manager (Win+X → Device Manager)
- Look under "Ports (COM & LPT)" for "USB Serial Device" or "Raspberry Pi Pico"
- Note the COM port number (e.g., COM3, COM4)

### Step 4: Flash Firmware Files
In Cursor's terminal, run these commands:

```bash
# Create firmware directory on Pico
mpremote connect COM3 mkdir firmware

# Copy files (replace COM3 with your actual port)
mpremote connect COM3 cp radio_core.py :
mpremote connect COM3 cp main.py :
mpremote connect COM3 cp firmware/dfplayer_hardware.py :firmware/dfplayer_hardware.py

# Run firmware
mpremote connect COM3 run main.py
```

**Note**: On Linux/Mac, use `/dev/ttyACM0` instead of `COM3`:
```bash
mpremote connect /dev/ttyACM0 cp radio_core.py :
# etc...
```

### Step 5: Auto-Run on Boot (Optional)
To make firmware run automatically when Pico boots:
```bash
mpremote connect COM3 cp main.py :boot.py
```

### Quick Script for Cursor
You can create a simple script to automate this. Create `flash_firmware.bat` (Windows) or `flash_firmware.sh` (Linux/Mac):

**Windows (`flash_firmware.bat`):**
```batch
@echo off
echo Flashing firmware to Pico...
mpremote connect COM3 mkdir firmware
mpremote connect COM3 cp radio_core.py :
mpremote connect COM3 cp main.py :
mpremote connect COM3 cp firmware/dfplayer_hardware.py :firmware/dfplayer_hardware.py
echo Done! Firmware flashed.
pause
```

**Linux/Mac (`flash_firmware.sh`):**
```bash
#!/bin/bash
echo "Flashing firmware to Pico..."
mpremote connect /dev/ttyACM0 mkdir firmware
mpremote connect /dev/ttyACM0 cp radio_core.py :
mpremote connect /dev/ttyACM0 cp main.py :
mpremote connect /dev/ttyACM0 cp firmware/dfplayer_hardware.py :firmware/dfplayer_hardware.py
echo "Done! Firmware flashed."
```

## Method 2: Using Thonny IDE (Easiest for Beginners)

### Step 1: Install Thonny
1. Download Thonny from https://thonny.org/
2. Install and open Thonny

### Step 2: Connect Pico
1. Hold the **BOOTSEL** button on your Pico
2. Connect Pico to your computer via USB
3. Release BOOTSEL button
4. In Thonny: **Tools → Options → Interpreter**
5. Select **MicroPython (Raspberry Pi Pico)**
6. Select the correct COM port (Windows) or `/dev/ttyACM0` (Linux/Mac)

### Step 3: Flash Firmware Files
1. In Thonny, open the **Files** panel** (View → Files)
2. Navigate to your project directory
3. Upload these files to the Pico (right-click → Upload to /):
   - `radio_core.py` → `/radio_core.py`
   - `main.py` → `/main.py`
   - `firmware/dfplayer_hardware.py` → `/firmware/dfplayer_hardware.py`

### Step 4: Verify
1. In Thonny, click **Run** (F5) or type in REPL:
   ```python
   import main
   main.main()
   ```
2. Check the console for boot messages

## Method 3: Using rshell (Alternative Command-Line Tool)

### Step 1: Install mpremote
```bash
pip install mpremote
```

### Step 2: Connect Pico
1. Hold **BOOTSEL** button
2. Connect Pico via USB
3. Release BOOTSEL

### Step 3: Flash Files
```bash
# Create firmware directory on Pico
mpremote mkdir firmware

# Copy files
mpremote cp radio_core.py :
mpremote cp main.py :
mpremote cp firmware/dfplayer_hardware.py :firmware/dfplayer_hardware.py

# Run firmware
mpremote run main.py
```

## Method 3: Using rshell (Alternative)

```bash
pip install rshell
rshell -p COM3  # Windows: use COM port, Linux/Mac: use /dev/ttyACM0
cp radio_core.py /pyboard/
cp main.py /pyboard/
mkdir /pyboard/firmware
cp firmware/dfplayer_hardware.py /pyboard/firmware/
```

## File Structure on Pico
```
/
├── main.py                    # Main firmware entry point
├── radio_core.py              # Shared core logic
├── firmware/
│   └── dfplayer_hardware.py   # Hardware interface
└── VintageRadio/              # SD card mount point (if using SD)
    ├── AMradioSound.wav
    ├── album_state.txt
    └── radio_metadata.json
```

## Troubleshooting

### Pico Not Detected
- Try a different USB cable (data cable, not charge-only)
- Press BOOTSEL and reconnect
- Check Device Manager (Windows) for COM port

### Import Errors
- Ensure all files are uploaded to correct locations
- Check file names match exactly (case-sensitive)
- Verify `firmware/` directory exists on Pico

### DFPlayer Not Responding
- Check UART connections (TX/RX pins)
- Verify DFPlayer power and connections
- Check baud rate (9600)

## Auto-Run on Boot
To make the firmware run automatically when Pico boots:
1. Rename `main.py` to `boot.py` on the Pico
2. Or add to `boot.py`:
   ```python
   import main
   main.main()
   ```

## Updating Firmware
1. Connect Pico
2. Upload new files (overwrite old ones)
3. Soft reset: Press Ctrl+D in Thonny REPL, or reset button on Pico

