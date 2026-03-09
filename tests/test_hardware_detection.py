#!/usr/bin/env python3
"""
Quick test script to verify Vintage Radio hardware detection works across platforms.
"""

import sys
import platform
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

def test_sd_detection():
    """Test SD card detection"""
    try:
        from gui.sd_manager import SDManager
        roots = SDManager.detect_sd_roots()

        print("\n✓ SD Card Detection")
        print(f"  Platform: {platform.system()}")
        print(f"  Found {len(roots)} external storage device(s)")

        if roots:
            for path, label in roots:
                print(f"    - {label} ({path})")
        else:
            print("    (None detected - normal if no USB drives are plugged in)")

        return True
    except Exception as e:
        print(f"\n✗ SD Card Detection Failed")
        print(f"  Error: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_serial_detection():
    """Test microcontroller detection via serial ports"""
    try:
        import serial
        from serial.tools import list_ports

        ports = list(list_ports.comports())

        print("\n✓ Serial Port Detection")
        print(f"  Found {len(ports)} serial port(s)")

        if ports:
            for port in ports:
                print(f"    - {port.device}: {port.description}")
        else:
            print("    (None detected - normal if Pico is not plugged in)")

        return True
    except ImportError:
        print("\n⚠ Serial Detection Skipped")
        print("  pyserial not installed. Install with: pip install pyserial")
        return True
    except Exception as e:
        print(f"\n✗ Serial Detection Failed")
        print(f"  Error: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    """Run all tests"""
    print("=" * 60)
    print("Vintage Radio Hardware Detection Test")
    print("=" * 60)

    tests = [
        test_sd_detection,
        test_serial_detection,
    ]

    results = [test() for test in tests]

    print("\n" + "=" * 60)
    if all(results):
        print("✓ All tests passed!")
        print("=" * 60)
        return 0
    else:
        print("✗ Some tests failed")
        print("=" * 60)
        return 1

if __name__ == "__main__":
    sys.exit(main())

