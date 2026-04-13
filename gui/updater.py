"""GitHub release updater helpers for packaged app builds."""

from __future__ import annotations

import json
import os
import platform
import re
import shutil
import ssl
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import urlparse
from urllib.error import HTTPError
from urllib.request import Request, urlopen
import zipfile


# NOTE: GitHub's /releases/latest is the latest *non-prerelease* only. If every
# release is a GitHub "Pre-release", that endpoint returns 404. Use the list
# endpoint (newest first) so beta/prerelease tags still resolve.
GITHUB_RELEASES_LATEST_URL = (
    "https://api.github.com/repos/alexnoctis76/Vintage_radio/releases/latest"
)
GITHUB_RELEASES_LIST_URL = (
    "https://api.github.com/repos/alexnoctis76/Vintage_radio/releases?per_page=30"
)
GITHUB_RELEASES_URL = "https://github.com/alexnoctis76/Vintage_radio/releases"


@dataclass
class ReleaseInfo:
    tag_name: str
    html_url: str
    body: str
    assets: list[dict]


def _urlopen_with_certs(req: Request, timeout: int):
    try:
        import certifi

        ctx = ssl.create_default_context(cafile=certifi.where())
        return urlopen(req, timeout=timeout, context=ctx)
    except Exception:
        return urlopen(req, timeout=timeout)


def _parse_version_tag(tag: str) -> tuple[int, int, int, Optional[str]]:
    value = (tag or "").strip()
    if value.lower().startswith("v"):
        value = value[1:]
    m = re.match(r"^(\d+)\.(\d+)\.(\d+)(?:[-+](.+))?$", value)
    if not m:
        return (0, 0, 0, value or None)
    major, minor, patch, suffix = m.groups()
    return (int(major), int(minor), int(patch), suffix)


def is_newer(latest_tag: str, current_tag: str) -> bool:
    """Return True when latest_tag should be considered newer."""
    latest = _parse_version_tag(latest_tag)
    current = _parse_version_tag(current_tag)
    latest_nums = latest[:3]
    current_nums = current[:3]
    if latest_nums != current_nums:
        return latest_nums > current_nums
    latest_suffix = latest[3]
    current_suffix = current[3]
    if latest_suffix is None and current_suffix is not None:
        return True
    if latest_suffix is not None and current_suffix is None:
        return False
    if latest_suffix == current_suffix:
        return False
    if latest_suffix is None:
        return False
    if current_suffix is None:
        return True
    return latest_suffix > current_suffix


def _release_info_from_api_dict(data: dict) -> Optional[ReleaseInfo]:
    tag = str(data.get("tag_name") or "").strip()
    if not tag:
        return None
    return ReleaseInfo(
        tag_name=tag,
        html_url=str(data.get("html_url") or GITHUB_RELEASES_URL),
        body=str(data.get("body") or "").strip(),
        assets=list(data.get("assets") or []),
    )


def _newest_release_from_list(items: list) -> Optional[ReleaseInfo]:
    """Pick the semantically newest tag; GitHub order is by publish date, not semver."""
    candidates: list[ReleaseInfo] = []
    for item in items:
        if not isinstance(item, dict) or item.get("draft"):
            continue
        info = _release_info_from_api_dict(item)
        if info is not None:
            candidates.append(info)
    best: Optional[ReleaseInfo] = None
    for c in candidates:
        if best is None or is_newer(c.tag_name, best.tag_name):
            best = c
    return best


def check_latest_release(user_agent: str = "VintageRadio") -> Optional[ReleaseInfo]:
    """Fetch newest published release from GitHub (includes prereleases)."""
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": user_agent,
    }
    try:
        req = Request(GITHUB_RELEASES_LATEST_URL, headers=headers)
        with _urlopen_with_certs(req, timeout=20) as resp:
            raw = resp.read()
        data = json.loads(raw.decode("utf-8", errors="replace"))
        if isinstance(data, dict):
            info = _release_info_from_api_dict(data)
            if info is not None:
                return info
    except HTTPError as e:
        if e.code != 404:
            return None
    except Exception:
        return None

    try:
        req = Request(GITHUB_RELEASES_LIST_URL, headers=headers)
        with _urlopen_with_certs(req, timeout=20) as resp:
            raw = resp.read()
        items = json.loads(raw.decode("utf-8", errors="replace"))
        if not isinstance(items, list):
            return None
        return _newest_release_from_list(items)
    except Exception:
        return None


def get_platform_asset(assets: list[dict]) -> Optional[dict]:
    """Pick the expected release asset for this platform."""
    sys_name = platform.system().lower()
    if "windows" in sys_name:
        matcher = "windows"
    elif "darwin" in sys_name:
        matcher = "macos"
    else:
        return None
    for asset in assets:
        name = str(asset.get("name") or "").lower()
        if matcher in name and name.endswith(".zip"):
            return asset
    return None


def download_update(
    url: str,
    dest_dir: Path,
    progress_cb: Optional[Callable[[int, int], None]] = None,
) -> Path:
    """Download update zip with optional progress callback."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    parsed = urlparse(url)
    file_name = Path(parsed.path).name or "vintage-radio-update.zip"
    target = dest_dir / file_name
    req = Request(url, headers={"User-Agent": "VintageRadio-Updater"})
    with _urlopen_with_certs(req, timeout=60) as resp:
        total = int(resp.headers.get("Content-Length", "0") or "0")
        done = 0
        with target.open("wb") as out:
            while True:
                chunk = resp.read(64 * 1024)
                if not chunk:
                    break
                out.write(chunk)
                done += len(chunk)
                if progress_cb is not None:
                    progress_cb(done, total)
    return target


def _extract_zip(zip_path: Path, extract_dir: Path) -> None:
    if extract_dir.exists():
        shutil.rmtree(extract_dir, ignore_errors=True)
    extract_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "r") as zf:
        zf.extractall(extract_dir)


def _find_windows_source_dir(extract_dir: Path) -> Optional[Path]:
    for p in extract_dir.rglob("Vintage Radio.exe"):
        if p.is_file():
            return p.parent
    return None


def _find_macos_source_app(extract_dir: Path) -> Optional[Path]:
    for p in extract_dir.rglob("*.app"):
        if p.is_dir():
            return p
    return None


def _launch_windows_apply_script(source_dir: Path, target_dir: Path, work_dir: Path, pid: int) -> None:
    script = work_dir / "apply_update.bat"
    restart_exe = target_dir / "Vintage Radio.exe"
    content = f"""@echo off
setlocal
set PID={pid}
:waitloop
tasklist /FI "PID eq %PID%" | find /I "%PID%" >nul
if not errorlevel 1 (
  timeout /t 1 /nobreak >nul
  goto waitloop
)
robocopy "{source_dir}" "{target_dir}" /MIR /R:2 /W:1 >nul
start "" "{restart_exe}"
endlocal
"""
    script.write_text(content, encoding="utf-8")
    subprocess.Popen(["cmd", "/c", str(script)], start_new_session=True)


def _launch_macos_apply_script(source_app: Path, target_app: Path, pid: int) -> None:
    script = source_app.parent / "apply_update.sh"
    content = f"""#!/bin/bash
set -e
PID={pid}
while kill -0 "$PID" 2>/dev/null; do
  sleep 1
done
rm -rf "{target_app}"
cp -R "{source_app}" "{target_app}"
open "{target_app}"
"""
    script.write_text(content, encoding="utf-8")
    script.chmod(0o755)
    subprocess.Popen(["/bin/bash", str(script)], start_new_session=True)


def apply_update(zip_path: Path) -> None:
    """Extract and launch an update script that replaces app files after exit."""
    if not getattr(sys, "frozen", False):
        raise RuntimeError("Automatic updates are only supported for packaged builds.")

    platform_name = platform.system()
    extract_dir = zip_path.parent / "extracted"
    _extract_zip(zip_path, extract_dir)

    pid = int(getattr(os, "getpid", lambda: 0)())
    if platform_name == "Windows":
        source_dir = _find_windows_source_dir(extract_dir)
        if source_dir is None:
            raise RuntimeError("Could not locate 'Vintage Radio.exe' in downloaded update.")
        target_dir = Path(sys.executable).resolve().parent
        _launch_windows_apply_script(source_dir, target_dir, zip_path.parent, pid)
        return

    if platform_name == "Darwin":
        source_app = _find_macos_source_app(extract_dir)
        if source_app is None:
            raise RuntimeError("Could not locate .app bundle in downloaded update.")
        target_app = Path(sys.executable).resolve().parents[2]
        _launch_macos_apply_script(source_app, target_app, pid)
        return

    raise RuntimeError("Automatic updates are not supported on this platform.")
