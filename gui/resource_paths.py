"""Path helpers for resources and project root. Works from source and when frozen (PyInstaller)."""

import os
import platform
import shutil
import stat
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


def _migrate_legacy_frozen_data(new_dir: Path) -> None:
    """One-time migration from legacy frozen location (next to executable).

    Older Windows/Linux packaged builds stored DBs/libraries next to the exe.
    New builds use a per-user app data directory; copy once if destination is empty.
    """
    old_dir = Path(sys.executable).resolve().parent
    old_db = old_dir / "radio_manager.db"
    new_db = new_dir / "radio_manager.db"
    if not old_db.exists() or new_db.exists():
        return
    try:
        shutil.copy2(old_db, new_db)
        for suffix in ("-wal", "-shm"):
            src = old_dir / f"radio_manager.db{suffix}"
            if src.exists():
                shutil.copy2(src, new_dir / f"radio_manager.db{suffix}")
        old_libraries_dir = old_dir / "libraries"
        if old_libraries_dir.is_dir():
            new_libraries_dir = new_dir / "libraries"
            new_libraries_dir.mkdir(parents=True, exist_ok=True)
            for f in old_libraries_dir.iterdir():
                if f.is_file() and not (new_libraries_dir / f.name).exists():
                    shutil.copy2(f, new_libraries_dir / f.name)
    except OSError:
        # Best-effort migration; app should still start with a fresh database.
        pass


def app_data_dir() -> Path:
    """Writable directory for db, backups, libraries.

    When running from source: project_root() / "data" so all DBs live in one
    directory that can be gitignored. Migrates existing DBs from project root
    into data/ once.
    When frozen (packaged): use platformdirs user_data_dir() so user data survives
    app replacement/build cleanup and never writes inside the app bundle/install dir.
    """
    if not getattr(sys, "frozen", False):
        root = project_root()
        data_dir = root / _DATA_DIR_NAME
        # One-time migration: if DBs or libraries exist at project root, copy into data/
        root_has_db = (root / "radio_manager.db").exists()
        lib_src = root / "libraries"
        root_has_libraries = lib_src.exists() and lib_src.is_dir() and any(lib_src.iterdir())
        data_lib = data_dir / "libraries"
        data_has_library_json = (data_lib / "libraries.json").exists()
        data_has_library_dbs = data_lib.exists() and any(data_lib.glob("*.db"))
        # The default library still uses data/radio_manager.db, so data/libraries/
        # may contain only libraries.json (no *.db) until a second library is
        # opened. Treat an existing registry as "already seeded" so we never
        # copy project_root/libraries/* on top of it (that overwrote libraries.json
        # and effectively wiped the default library when creating a new library).
        data_libraries_seeded = data_has_library_json or data_has_library_dbs
        data_needs_migration = (
            (not data_has_library_json and not (data_dir / "radio_manager.db").exists())
            or (root_has_libraries and not data_libraries_seeded)
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
        import platformdirs

        path = Path(platformdirs.user_data_dir(appname="Vintage Radio", roaming=False))
        path.mkdir(parents=True, exist_ok=True)
        _migrate_legacy_frozen_data(path)
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


def _bundle_imageio_ffmpeg_binary() -> Path | None:
    """Find imageio-ffmpeg static build under PyInstaller ``_MEIPASS``.

    ``imageio_ffmpeg.get_ffmpeg_exe()`` uses ``importlib.resources`` paths that do
    not reliably match where PyInstaller extracts ``collect_all('imageio_ffmpeg')``
    data (especially inside a macOS ``.app``).
    """
    root = _frozen_base()
    if root is None or not root.is_dir():
        return None

    ordered_names: list[str] = []
    try:
        import imageio_ffmpeg._definitions as defs

        plat = defs.get_platform()
        primary = defs.FNAME_PER_PLATFORM.get(plat)
        if primary:
            ordered_names.append(primary)
        for n in dict.fromkeys(defs.FNAME_PER_PLATFORM.values()):
            if n and n not in ordered_names:
                ordered_names.append(n)
    except Exception:
        if platform.system() == "Darwin":
            ordered_names = [
                "ffmpeg-macos-aarch64-v7.1",
                "ffmpeg-macos-x86_64-v7.1",
            ]
        elif platform.system() == "Windows":
            ordered_names = [
                "ffmpeg-win-x86_64-v7.1.exe",
                "ffmpeg-win32-v4.2.2.exe",
            ]
        else:
            ordered_names = [
                "ffmpeg-linux-x86_64-v7.0.2",
                "ffmpeg-linux-aarch64-v7.0.2",
            ]

    def _platform_ffmpeg_ok(p: Path) -> bool:
        n = p.name.lower()
        if platform.system() == "Darwin":
            return "macos" in n
        if platform.system() == "Windows":
            return p.suffix.lower() == ".exe" or "win" in n
        if platform.system() == "Linux":
            return "linux" in n
        return True

    for name in ordered_names:
        direct = root / "imageio_ffmpeg" / "binaries" / name
        if direct.is_file() and _platform_ffmpeg_ok(direct):
            return direct
        for p in root.rglob(name):
            if p.is_file() and _platform_ffmpeg_ok(p):
                return p
    return None


def _ensure_executable(p: Path) -> None:
    try:
        mode = p.stat().st_mode
        if mode & stat.S_IXUSR == 0:
            p.chmod(mode | stat.S_IRWXU)
    except OSError:
        pass


def resolve_ffmpeg_executable() -> str | None:
    """Return an ffmpeg executable path if available.

    Priority:
    1) Explicit env override: VINTAGE_RADIO_FFMPEG_EXE
    2) Bundled executable from imageio-ffmpeg package (``get_ffmpeg_exe()``)
    3) When **frozen**: search ``_MEIPASS`` for the static binary shipped with imageio-ffmpeg
    4) System PATH lookup (``ffmpeg``)
    """
    override = os.environ.get("VINTAGE_RADIO_FFMPEG_EXE", "").strip()
    if override and Path(override).exists():
        return override

    try:
        import imageio_ffmpeg

        exe = imageio_ffmpeg.get_ffmpeg_exe()
        if exe and Path(exe).exists():
            return exe
    except Exception:
        pass

    bundled = _bundle_imageio_ffmpeg_binary()
    if bundled is not None:
        _ensure_executable(bundled)
        if bundled.is_file():
            return str(bundled)

    system_ffmpeg = shutil.which("ffmpeg")
    if system_ffmpeg:
        return system_ffmpeg
    return None
