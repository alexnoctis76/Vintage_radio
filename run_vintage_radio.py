"""
Entry point for PyInstaller and for running the app as a module.
Uses absolute imports so the frozen exe has a proper package context.

Which Python runs this file depends on how you launch it (``python`` on PATH, IDE
runner, etc.), not on the file name. To use the project virtualenv explicitly
(needed for optional deps like pyfatfs / SD disk image):

  Windows:  .venv\\Scripts\\python.exe run_vintage_radio.py
  Or run:   run_vintage_radio.bat  (uses .venv when present)

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

# Developer MCP debug controls
if "--enable-mcp-debug" in sys.argv:
    os.environ["VINTAGE_RADIO_ENABLE_MCP_DEBUG"] = "1"
    while "--enable-mcp-debug" in sys.argv:
        sys.argv.remove("--enable-mcp-debug")

if "--mcp-autostart" in sys.argv:
    os.environ["VINTAGE_RADIO_MCP_AUTOSTART"] = "1"
    while "--mcp-autostart" in sys.argv:
        sys.argv.remove("--mcp-autostart")

for arg in list(sys.argv):
    if arg.startswith("--mcp-port="):
        os.environ["VINTAGE_RADIO_MCP_PORT"] = arg.split("=", 1)[1].strip()
        sys.argv.remove(arg)


def _try_sd_disk_write_cli() -> int | None:
    """If argv is --vr-write-sd-disk <img> <disk> [<log>], perform elevated write and exit."""
    if len(sys.argv) < 4:
        return None
    if sys.argv[1] != "--vr-write-sd-disk":
        return None
    import traceback
    from pathlib import Path

    from gui.sd_disk_write_helper import redirect_stdio_for_elevated_disk_child

    img = Path(sys.argv[2])
    disk = int(sys.argv[3])
    log_path = Path(sys.argv[4]) if len(sys.argv) >= 5 else None

    redirect_stdio_for_elevated_disk_child(log_path)

    from gui.sd_disk_image_flash import _write_image_to_physical_disk_impl

    try:
        ok, err = _write_image_to_physical_disk_impl(
            img,
            disk,
            progress_callback=None,
            should_cancel=None,
            try_offline_first=True,
        )
        if not ok:
            print(err, file=sys.stderr)
            return 1
        return 0
    except Exception:
        traceback.print_exc()
        return 1


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

if __name__ == "__main__":
    code = _try_sd_disk_write_cli()
    if code is not None:
        raise SystemExit(code)
    from gui.radio_manager import run_app

    run_app()
