#!/usr/bin/env python3
"""
Test script to verify firmware fetching works on macOS.
"""

import sys
import platform
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

def test_ssl_context():
    """Test that SSL context can be created properly."""
    import ssl
    print(f"Platform: {platform.system()}")

    try:
        # Try with certifi
        try:
            import certifi
            ssl_context = ssl.create_default_context(cafile=certifi.where())
            print("✓ Created SSL context with certifi")
            return True
        except ImportError:
            print("⚠ certifi not installed, trying system default...")
            ssl_context = ssl.create_default_context()
            print("✓ Created SSL context with system defaults")
            return True
    except Exception as e:
        print(f"✗ Failed to create SSL context: {e}")
        return False

def test_firmware_fetch():
    """Test fetching firmware list from micropython.org."""
    import urllib.request
    import ssl
    import re

    url = "https://micropython.org/download/RPI_PICO/"

    try:
        # Create SSL context
        try:
            import certifi
            ssl_context = ssl.create_default_context(cafile=certifi.where())
        except ImportError:
            ssl_context = ssl.create_default_context()

        print(f"\nFetching firmware list from {url}...")
        req = urllib.request.Request(url, headers={"User-Agent": "VintageRadio/1.0"})

        with urllib.request.urlopen(req, timeout=15, context=ssl_context) as resp:
            html = resp.read().decode("utf-8")

        # Find .uf2 links
        uf2_links = re.findall(r'href="(/resources/firmware/[^"]*\.uf2)"', html)

        if uf2_links:
            print(f"✓ Found {len(uf2_links)} firmware versions")
            for i, link in enumerate(uf2_links[:2], 1):
                filename = link.rsplit("/", 1)[-1]
                m = re.search(r"-(\d{8})-(v[\d.]+)\.uf2$", filename)
                if m:
                    date_str, version = m.group(1), m.group(2)
                    display = f"{version}  ({date_str[:4]}-{date_str[4:6]}-{date_str[6:]})"
                else:
                    display = filename
                print(f"  {i}. {display}")
            return True
        else:
            print("✗ No firmware found on page")
            return False
    except Exception as e:
        print(f"✗ Fetch failed: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    """Run all tests."""
    print("=" * 60)
    print("Firmware Fetching Tests")
    print("=" * 60)

    tests = [
        ("SSL Context Creation", test_ssl_context),
        ("Firmware Fetch", test_firmware_fetch),
    ]

    results = []
    for name, test_func in tests:
        print(f"\n{name}...")
        try:
            result = test_func()
            results.append((name, result))
        except Exception as e:
            print(f"✗ Test crashed: {e}")
            import traceback
            traceback.print_exc()
            results.append((name, False))

    print("\n" + "=" * 60)
    print("Summary")
    print("=" * 60)
    for name, result in results:
        status = "✓ PASS" if result else "✗ FAIL"
        print(f"{status}: {name}")

    all_pass = all(r for _, r in results)
    print("\n" + ("=" * 60))
    if all_pass:
        print("✅ All tests passed!")
        return 0
    else:
        print("❌ Some tests failed")
        return 1

if __name__ == "__main__":
    sys.exit(main())

