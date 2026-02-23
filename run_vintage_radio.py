"""
Entry point for PyInstaller and for running the app as a module.
Uses absolute imports so the frozen exe has a proper package context.

Run with verbose debug logs in the console:
  python run_vintage_radio.py --verbose
  # or set env before starting:
  set VINTAGE_RADIO_VERBOSE=1   (Windows)
  export VINTAGE_RADIO_VERBOSE=1   (Linux/macOS)
"""
import os
import sys

# Support --verbose / -v for debug logs to console (must set before gui imports)
if "--verbose" in sys.argv or "-v" in sys.argv:
    os.environ["VINTAGE_RADIO_VERBOSE"] = "1"
    while "--verbose" in sys.argv:
        sys.argv.remove("--verbose")
    while "-v" in sys.argv:
        sys.argv.remove("-v")

# When packaged on macOS, Finder often launches with a minimal PATH.
# Extend it so ffmpeg/VLC (e.g. from Homebrew) are found for SD sync / conversion.
if getattr(sys, "frozen", False):
    try:
        import platform
        if platform.system() == "Darwin":
            extra = os.pathsep.join(["/usr/local/bin", "/opt/homebrew/bin"])
            path = os.environ.get("PATH", "")
            if extra not in path:
                os.environ["PATH"] = extra + os.pathsep + path
    except Exception:
        pass

from gui.radio_manager import run_app

if __name__ == "__main__":
    run_app()
