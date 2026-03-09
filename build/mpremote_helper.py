#!/usr/bin/env python3
"""Minimal mpremote launcher - no Qt, no GUI. Used as subprocess by packaged macOS app.

Invocation: mpremote_helper [mpremote args...]
E.g.: mpremote_helper connect auto exec "print(1)"
"""
import sys

def main():
    # mpremote.main expects argv[0] == "mpremote"
    orig = sys.argv
    sys.argv = ["mpremote"] + sys.argv[1:]
    try:
        from mpremote.main import main as mpremote_main
        return mpremote_main()
    finally:
        sys.argv = orig

if __name__ == "__main__":
    sys.exit(main() or 0)
