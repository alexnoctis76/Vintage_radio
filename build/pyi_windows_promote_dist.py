"""
After PyInstaller COLLECT into dist/_pyi_staging/Vintage Radio, move/copy to dist/Vintage Radio.

Builds there so _make_clean_directory never has to wipe the folder users run the exe from
(Windows locks: WinError 32/5).
"""
from __future__ import annotations

import os
import shutil
import stat
import subprocess
import sys
import time
from pathlib import Path


def _project_root() -> Path:
    if len(sys.argv) > 1:
        return Path(sys.argv[1]).resolve()
    return Path(__file__).resolve().parent.parent


def _run_kill(project_dir: Path) -> None:
    helper = project_dir / "build" / "kill_vintage_radio_build_locks.py"
    if helper.is_file():
        try:
            subprocess.run(
                [sys.executable, str(helper)],
                cwd=str(project_dir),
                timeout=120,
            )
        except (OSError, subprocess.TimeoutExpired):
            pass
    for _ in range(3):
        subprocess.run(
            ["taskkill", "/IM", "Vintage Radio.exe", "/F", "/T"],
            capture_output=True,
            timeout=45,
        )
        time.sleep(0.35)


def _chmod_rw(func, path, _):
    try:
        os.chmod(path, stat.S_IWRITE)
    except OSError:
        pass
    try:
        func(path)
    except OSError:
        pass


def _rmtree_retry(path: Path, attempts: int = 8) -> bool:
    if not path.exists():
        return True
    for _ in range(attempts):
        try:
            shutil.rmtree(path, onexc=_chmod_rw)
            return not path.exists()
        except OSError:
            time.sleep(0.45)
    try:
        shutil.rmtree(path, ignore_errors=True)
    except OSError:
        pass
    return not path.exists()


def _robocopy_mirror(src: Path, dst: Path) -> int:
    # Exit codes 0–8: success / partial success per robocopy docs
    return subprocess.run(
        [
            "robocopy",
            str(src),
            str(dst),
            "/MIR",
            "/R:2",
            "/W:1",
            "/NFL",
            "/NDL",
            "/NJH",
            "/NJS",
            "/NP",
        ],
        timeout=600,
    ).returncode


def main() -> int:
    if sys.platform != "win32":
        return 0
    project_dir = _project_root()
    src = project_dir / "dist" / "_pyi_staging" / "Vintage Radio"
    dst = project_dir / "dist" / "Vintage Radio"
    if not src.is_dir():
        return 0

    dst.parent.mkdir(parents=True, exist_ok=True)
    _run_kill(project_dir)

    if dst.exists():
        if not _rmtree_retry(dst):
            rc = _robocopy_mirror(src, dst)
            if rc > 8:
                print(
                    f"pyi_windows_promote_dist: robocopy failed (code {rc}). "
                    f"Fresh build is at: {src}",
                    file=sys.stderr,
                )
                return 1
            _rmtree_retry(src)
            print(f"Promoted build via robocopy -> {dst}")
            return 0

    try:
        shutil.move(str(src), str(dst))
    except OSError as e:
        print(f"pyi_windows_promote_dist: move failed ({e}); trying robocopy...", file=sys.stderr)
        dst.mkdir(parents=True, exist_ok=True)
        rc = _robocopy_mirror(src, dst)
        if rc > 8:
            print(f"Fresh build remains at: {src}", file=sys.stderr)
            return 1
        _rmtree_retry(src)

    staging = project_dir / "dist" / "_pyi_staging"
    try:
        if staging.is_dir() and not any(staging.iterdir()):
            staging.rmdir()
    except OSError:
        pass

    print(f"PyInstaller output: {dst}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
