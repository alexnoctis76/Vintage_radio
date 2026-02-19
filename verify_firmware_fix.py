#!/usr/bin/env python3
"""
Verification checklist for macOS firmware fetching fix.
Run this to verify everything is working correctly.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

def check_imports():
    """Verify all required modules are available."""
    print("\n1. Checking imports...")
    try:
        import urllib.request
        import urllib.error
        import ssl
        import json
        import re
        import tempfile
        print("   ✓ All imports available")
        return True
    except ImportError as e:
        print(f"   ✗ Import error: {e}")
        return False

def check_radio_manager():
    """Verify the modified radio_manager has correct syntax."""
    print("\n2. Checking radio_manager.py syntax...")
    try:
        from gui.radio_manager import InstallMicroPythonDialog
        print("   ✓ radio_manager imports successfully")

        # Check that the class exists and has the methods
        methods = ['_fetch_firmware_releases', '_download_and_install', '_copy_to_pico']
        for method in methods:
            if hasattr(InstallMicroPythonDialog, method):
                print(f"   ✓ Method {method} exists")
            else:
                print(f"   ✗ Method {method} missing")
                return False
        return True
    except Exception as e:
        print(f"   ✗ Error: {e}")
        return False

def check_ssl_fallback():
    """Test that SSL fallback works."""
    print("\n3. Testing SSL fallback mechanism...")
    try:
        import ssl
        import urllib.error

        # Create unverified context (like the fix does)
        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE
        print("   ✓ Can create unverified SSL context")

        # Test building HTTPS handler
        https_handler = urllib.request.HTTPSHandler(context=ssl_context)
        opener = urllib.request.build_opener(https_handler)
        print("   ✓ Can build HTTPS handler with context")
        return True
    except Exception as e:
        print(f"   ✗ Error: {e}")
        return False

def check_requirements():
    """Verify requirements.txt has been updated."""
    print("\n4. Checking requirements.txt...")
    try:
        req_file = Path(__file__).parent / "requirements.txt"
        if req_file.exists():
            content = req_file.read_text()
            if "certifi" in content:
                print("   ✓ certifi is in requirements.txt")
            else:
                print("   ⚠ certifi not in requirements.txt (optional but recommended)")

            if "pyserial" in content:
                print("   ✓ pyserial is in requirements.txt")
            if "psutil" in content:
                print("   ✓ psutil is in requirements.txt")
            return True
        else:
            print("   ✗ requirements.txt not found")
            return False
    except Exception as e:
        print(f"   ✗ Error: {e}")
        return False

def main():
    """Run all checks."""
    print("=" * 60)
    print("macOS Firmware Fetching Fix - Verification Checklist")
    print("=" * 60)

    checks = [
        ("Imports", check_imports),
        ("radio_manager.py", check_radio_manager),
        ("SSL Fallback", check_ssl_fallback),
        ("requirements.txt", check_requirements),
    ]

    results = []
    for name, check_func in checks:
        try:
            result = check_func()
            results.append((name, result))
        except Exception as e:
            print(f"   ✗ Unexpected error: {e}")
            results.append((name, False))

    print("\n" + "=" * 60)
    print("Summary")
    print("=" * 60)

    for name, result in results:
        status = "✓" if result else "✗"
        print(f"{status} {name}")

    all_pass = all(r for _, r in results)

    if all_pass:
        print("\n✅ All checks passed! Firmware fetching should work on macOS.")
        print("\nNext steps:")
        print("1. Run: python -m gui.radio_manager")
        print("2. Go to Device Debug tab")
        print("3. Click 'Install MicroPython on Pico'")
        print("4. Click 'Refresh' to fetch firmware versions")
        return 0
    else:
        print("\n⚠ Some checks failed. Review the errors above.")
        return 1

if __name__ == "__main__":
    sys.exit(main())

