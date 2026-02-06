@echo off
REM Flash Vintage Radio firmware to Raspberry Pi Pico
REM Usage: flash_firmware.bat [COM_PORT]
REM Example: flash_firmware.bat COM3

set COM_PORT=%1
if "%COM_PORT%"=="" (
    echo Usage: flash_firmware.bat [COM_PORT]
    echo Example: flash_firmware.bat COM3
    echo.
    echo Please specify the COM port (check Device Manager)
    exit /b 1
)

echo ========================================
echo Flashing Vintage Radio Firmware
echo ========================================
echo.
echo COM Port: %COM_PORT%
echo.

echo [1/4] Creating firmware directory...
mpremote connect %COM_PORT% mkdir firmware
if errorlevel 1 (
    echo ERROR: Could not connect to Pico on %COM_PORT%
    echo Make sure Pico is connected and the COM port is correct
    pause
    exit /b 1
)

echo [2/4] Copying radio_core.py...
mpremote connect %COM_PORT% cp radio_core.py :

echo [3/4] Copying main.py...
mpremote connect %COM_PORT% cp main.py :

echo [4/4] Copying firmware/dfplayer_hardware.py...
mpremote connect %COM_PORT% cp firmware/dfplayer_hardware.py :firmware/dfplayer_hardware.py

echo.
echo ========================================
echo Firmware flashed successfully!
echo ========================================
echo.
echo To run the firmware, use:
echo   mpremote connect %COM_PORT% run main.py
echo.
echo Or to make it auto-run on boot:
echo   mpremote connect %COM_PORT% cp main.py :boot.py
echo.
pause

