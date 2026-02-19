"""
Entry point for PyInstaller and for running the app as a module.
Uses absolute imports so the frozen exe has a proper package context.
"""
import os
import sys

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
