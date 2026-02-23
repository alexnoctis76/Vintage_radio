"""Path helpers for resources and project root. Works from source and when frozen (PyInstaller)."""

import os
from pathlib import Path
import sys


def _frozen_base() -> Path | None:
    """Return base path when running as PyInstaller bundle, else None."""
    if getattr(sys, "frozen", False) and getattr(sys, "_MEIPASS", None):
        return Path(sys._MEIPASS)
    return None


def gui_dir() -> Path:
    """Base path for the gui package (use for gui/resources, etc.)."""
    base = _frozen_base()
    if base is not None:
        return base / "gui"
    return Path(__file__).resolve().parent


def project_root() -> Path:
    """Project root (parent of gui when not frozen; bundle root when frozen)."""
    base = _frozen_base()
    if base is not None:
        return base
    return Path(__file__).resolve().parents[1]


_DATA_DIR_NAME = "data"


def app_data_dir() -> Path:
    """Writable directory for db, backups, libraries.

    When running from source: project_root() / "data" so all DBs live in one
    directory that can be gitignored. Migrates existing DBs from project root
    into data/ once.
    When frozen (packaged): on macOS uses ~/Library/Application Support/Vintage Radio/
    so the app bundle is not written to. On Windows/Linux uses the directory
    containing the executable.
    """
    if not getattr(sys, "frozen", False):
        root = project_root()
        data_dir = root / _DATA_DIR_NAME
        # One-time migration: if DBs or libraries exist at project root, copy into data/
        root_has_db = (root / "radio_manager.db").exists()
        lib_src = root / "libraries"
        root_has_libraries = lib_src.exists() and lib_src.is_dir() and any(lib_src.iterdir())
        data_lib = data_dir / "libraries"
        data_has_library_dbs = data_lib.exists() and any(data_lib.glob("*.db"))
        data_needs_migration = (
            (not (data_lib / "libraries.json").exists() and not (data_dir / "radio_manager.db").exists())
            or (root_has_libraries and not data_has_library_dbs)
        )
        if data_needs_migration and (root_has_db or root_has_libraries):
            data_dir.mkdir(parents=True, exist_ok=True)
            try:
                import shutil
                if (root / "radio_manager.db").exists():
                    shutil.copy2(root / "radio_manager.db", data_dir / "radio_manager.db")
                for walshm in ("radio_manager.db-wal", "radio_manager.db-shm"):
                    p = root / walshm
                    if p.exists():
                        shutil.copy2(p, data_dir / walshm)
                if lib_src.exists() and lib_src.is_dir():
                    (data_dir / "libraries").mkdir(parents=True, exist_ok=True)
                    for f in lib_src.iterdir():
                        if f.is_file():
                            shutil.copy2(f, data_dir / "libraries" / f.name)
            except OSError:
                pass
        return data_dir
    try:
        import platform
        if platform.system() == "Darwin":
            import platformdirs
            path = Path(platformdirs.user_data_dir(appname="Vintage Radio", roaming=False))
            path.mkdir(parents=True, exist_ok=True)
            return path
    except Exception:
        pass
    return Path(sys.executable).resolve().parent


def subprocess_env() -> dict:
    """Environment for subprocess calls. When frozen on macOS, PATH is extended
    so tools like ffmpeg (e.g. from Homebrew) are found when the app is launched
    from Finder (which often has a minimal PATH).
    """
    if not getattr(sys, "frozen", False):
        return os.environ
    try:
        import platform
        if platform.system() == "Darwin":
            extra = os.pathsep.join(["/usr/local/bin", "/opt/homebrew/bin"])
            path = os.environ.get("PATH", "")
            if extra not in path:
                return {**os.environ, "PATH": extra + os.pathsep + path}
    except Exception:
        pass
    return os.environ


def resource_path(*parts: str) -> Path:
    """Path to a file under gui/resources."""
    return gui_dir() / "resources" / "/".join(parts)
