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
from urllib.parse import quote, urlparse
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
    "https://api.github.com/repos/alexnoctis76/Vintage_radio/releases?per_page=100"
)
GITHUB_RELEASES_URL = "https://github.com/alexnoctis76/Vintage_radio/releases"
GITHUB_REPO_SLUG = "alexnoctis76/Vintage_radio"
# Must match filenames produced by release packaging (see .github/workflows/build-release.yml).
PREFERRED_WINDOWS_ASSET = "Vintage-Radio-Windows.zip"
PREFERRED_MACOS_ASSET = "Vintage.Radio.dmg"

# GitHub may show the volume name with a dot instead of a space, e.g. "Vintage.Radio.dmg".
_VINTAGE_RADIO_DMG_RE = re.compile(
    r"vintage[\s._-]*radio\.dmg\Z",
    re.IGNORECASE,
)


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


def _newest_release_newer_than(items: list, current_version: str) -> Optional[ReleaseInfo]:
    """Semantically newest release whose tag is strictly newer than *current_version*."""
    best: Optional[ReleaseInfo] = None
    cur = (current_version or "").strip()
    if not cur:
        return _newest_release_from_list(items)
    for item in items:
        if not isinstance(item, dict) or item.get("draft"):
            continue
        info = _release_info_from_api_dict(item)
        if info is None:
            continue
        if not is_newer(info.tag_name, cur):
            continue
        if best is None or is_newer(info.tag_name, best.tag_name):
            best = info
    return best


def check_latest_release(
    user_agent: str = "VintageRadio",
    *,
    current_version: Optional[str] = None,
) -> Optional[ReleaseInfo]:
    """Fetch a published GitHub release to offer as an update.

    Uses the **releases list** (``per_page=100``) and semver. When
    *current_version* is set (recommended), returns only the newest release whose
    tag is **strictly greater** than that version — not merely the newest tag on
    the repo (which could equal the running build).

    GitHub's ``/releases/latest`` is used only as a fallback if the list call fails.
    """
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": user_agent,
    }
    try:
        req = Request(GITHUB_RELEASES_LIST_URL, headers=headers)
        with _urlopen_with_certs(req, timeout=20) as resp:
            raw = resp.read()
        items = json.loads(raw.decode("utf-8", errors="replace"))
        if isinstance(items, list) and items:
            if (current_version or "").strip():
                info = _newest_release_newer_than(items, current_version.strip())
            else:
                info = _newest_release_from_list(items)
            if info is not None:
                return info
    except HTTPError:
        pass
    except Exception:
        pass

    try:
        req = Request(GITHUB_RELEASES_LATEST_URL, headers=headers)
        with _urlopen_with_certs(req, timeout=20) as resp:
            raw = resp.read()
        data = json.loads(raw.decode("utf-8", errors="replace"))
        if isinstance(data, dict):
            info = _release_info_from_api_dict(data)
            if info is not None:
                cur = (current_version or "").strip()
                if cur and not is_newer(info.tag_name, cur):
                    return None
                return info
    except HTTPError as e:
        if e.code != 404:
            return None
    except Exception:
        return None

    return None


def _platform_matcher() -> Optional[str]:
    sys_name = platform.system().lower()
    if "windows" in sys_name:
        return "windows"
    if "darwin" in sys_name:
        return "macos"
    return None


def _preferred_asset_name_for_platform() -> Optional[str]:
    m = _platform_matcher()
    if m == "windows":
        return PREFERRED_WINDOWS_ASSET
    if m == "macos":
        return PREFERRED_MACOS_ASSET
    return None


def get_platform_asset(assets: list[dict]) -> Optional[dict]:
    """Pick the expected release asset for this platform.

    Windows: prefer ``Vintage-Radio-Windows.zip`` among zips whose name contains
    ``windows`` (avoids picking an auxiliary zip).

    macOS: prefer ``Vintage.Radio.dmg`` when present, else DMG/zip heuristics from
    :func:`_get_macos_release_asset`.
    """
    matcher = _platform_matcher()
    if matcher is None:
        return None

    if matcher == "windows":
        preferred = (PREFERRED_WINDOWS_ASSET or "").lower()
        candidates: list[dict] = []
        for asset in assets:
            name = str(asset.get("name") or "").lower()
            if not name.endswith(".zip"):
                continue
            if matcher not in name:
                continue
            candidates.append(asset)

        if not candidates:
            return None

        by_lower = {str(a.get("name") or "").lower(): a for a in candidates}
        if preferred and preferred in by_lower:
            return by_lower[preferred]

        vintage = [
            a
            for a in candidates
            if str(a.get("name") or "").lower().startswith("vintage-radio-")
        ]
        if vintage:
            vintage.sort(key=lambda a: len(str(a.get("name") or "")))
            return vintage[0]

        candidates.sort(key=lambda a: len(str(a.get("name") or "")))
        return candidates[0]

    preferred_mac = (PREFERRED_MACOS_ASSET or "").lower()
    by_lower_all = {str(a.get("name") or "").lower(): a for a in assets}
    if preferred_mac and preferred_mac in by_lower_all:
        return by_lower_all[preferred_mac]

    return _get_macos_release_asset(assets)


def direct_download_url_for_release(tag_name: str) -> Optional[str]:
    """URL for the official installer **for this exact release tag** only.

    Always uses ``/releases/download/{tag}/{filename}``. Do not use release
    ``assets`` ``browser_download_url`` for installers — those blobs can be
    mis-ordered or duplicated across releases; the tag in the path is the single
    source of truth.
    """
    preferred = official_installer_zip_basename()
    if not (preferred and tag_name.strip()):
        return None
    t = quote(tag_name.strip(), safe="")
    f = quote(preferred, safe="")
    return f"https://github.com/{GITHUB_REPO_SLUG}/releases/download/{t}/{f}"


def installer_download_url_for_release(release: ReleaseInfo) -> Optional[str]:
    """Direct installer download URL tied to *release.tag_name* (Windows / macOS)."""
    return direct_download_url_for_release(release.tag_name)


def official_installer_zip_basename() -> Optional[str]:
    """Basename of the official installer for this OS (zip on Windows, DMG on macOS)."""
    return _preferred_asset_name_for_platform()


def _get_macos_release_asset(assets: list[dict]) -> Optional[dict]:
    """Pick macOS update asset: raw DMG (e.g. Vintage.Radio.dmg) preferred, else macOS .zip."""
    dmg_scored: list[tuple[int, dict]] = []
    zip_candidates: list[dict] = []
    for asset in assets:
        name = str(asset.get("name") or "").lower()
        if name.endswith(".dmg"):
            score = 0
            if _VINTAGE_RADIO_DMG_RE.search(name):
                score += 100
            elif "vintage" in name and "radio" in name:
                score += 80
            if "macos" in name:
                score += 50
            if score == 0:
                continue
            dmg_scored.append((score, asset))
        elif "macos" in name and name.endswith(".zip"):
            zip_candidates.append(asset)
    if dmg_scored:
        dmg_scored.sort(key=lambda t: t[0], reverse=True)
        return dmg_scored[0][1]
    if zip_candidates:
        return zip_candidates[0]
    return None


def download_update(
    url: str,
    dest_dir: Path,
    progress_cb: Optional[Callable[[int, int], None]] = None,
    *,
    dest_filename: Optional[str] = None,
) -> Path:
    """Download release archive (.zip / .dmg) with optional progress callback.

    *dest_filename* — optional local filename (avoids stale collisions when the URL
    path is the same across releases, e.g. ``Vintage-Radio-Windows.zip``).
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    parsed = urlparse(url)
    file_name = dest_filename or Path(parsed.path).name or "vintage-radio-update.zip"
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
    """Return the folder that contains the *shallowest* ``Vintage Radio.exe``.

    ``rglob`` order is not guaranteed; a malformed zip could contain nested
    duplicates — the real bundle keeps the exe near the extract root.
    """
    hits = [p for p in extract_dir.rglob("Vintage Radio.exe") if p.is_file()]
    if not hits:
        return None
    hits.sort(key=lambda p: (len(p.parts), str(p)))
    return hits[0].parent


def _macos_app_has_bundle_layout(app_path: Path) -> bool:
    if not app_path.is_dir():
        return False
    if app_path.name.startswith("._"):
        return False
    if not app_path.name.lower().endswith(".app"):
        return False
    return (app_path / "Contents" / "MacOS").is_dir()


def _pick_macos_app_bundle_from_root(root: Path) -> Optional[Path]:
    """Find a real .app bundle under root (skips __MACOSX / AppleDouble junk)."""
    candidates: list[Path] = []
    for dirpath, dirnames, _filenames in os.walk(root, topdown=True):
        dirnames[:] = [
            d for d in dirnames if d != "__MACOSX" and not d.startswith("._")
        ]
        for d in dirnames:
            p = Path(dirpath) / d
            if _macos_app_has_bundle_layout(p):
                candidates.append(p)
    if not candidates:
        return None

    def sort_key(p: Path) -> tuple[int, int]:
        preferred = 0 if p.name.lower() == "vintage radio.app" else 1
        return (preferred, len(p.parts))

    candidates.sort(key=sort_key)
    return candidates[0]


def _stage_macos_app_from_dmg(dmg_path: Path, work_dir: Path) -> Path:
    """Mount DMG, copy the app bundle to work_dir, detach. Returns path to copied .app."""
    work_dir.mkdir(parents=True, exist_ok=True)
    mount = work_dir / "_dmg_mount"
    if mount.exists():
        shutil.rmtree(mount, ignore_errors=True)
    mount.mkdir(parents=True, exist_ok=True)
    attach = subprocess.run(
        [
            "hdiutil",
            "attach",
            "-readonly",
            "-nobrowse",
            "-mountpoint",
            str(mount),
            str(dmg_path),
        ],
        capture_output=True,
        text=True,
    )
    if attach.returncode != 0:
        msg = (attach.stderr or attach.stdout or "").strip()
        raise RuntimeError(
            "Could not mount the downloaded disk image.\n"
            + (msg or "hdiutil attach failed.")
        )
    try:
        source = _pick_macos_app_bundle_from_root(mount)
        if source is None:
            raise RuntimeError(
                "Could not find a .app bundle inside the DMG (expected Vintage Radio.app)."
            )
        dest = work_dir / source.name
        if dest.exists():
            shutil.rmtree(dest, ignore_errors=True)
        shutil.copytree(source, dest, symlinks=True)
        return dest
    finally:
        subprocess.run(
            ["hdiutil", "detach", str(mount)],
            capture_output=True,
            text=True,
        )
        shutil.rmtree(mount, ignore_errors=True)


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


def apply_update(archive_path: Path) -> None:
    """Extract or mount download, then launch an update script that replaces app files after exit."""
    if not getattr(sys, "frozen", False):
        raise RuntimeError("Automatic updates are only supported for packaged builds.")

    platform_name = platform.system()
    work_dir = archive_path.parent
    extract_dir = work_dir / "extracted"

    pid = int(getattr(os, "getpid", lambda: 0)())
    if platform_name == "Windows":
        _extract_zip(archive_path, extract_dir)
        source_dir = _find_windows_source_dir(extract_dir)
        if source_dir is None:
            raise RuntimeError("Could not locate 'Vintage Radio.exe' in downloaded update.")
        target_dir = Path(sys.executable).resolve().parent
        _launch_windows_apply_script(source_dir, target_dir, work_dir, pid)
        return

    if platform_name == "Darwin":
        shutil.rmtree(extract_dir, ignore_errors=True)
        extract_dir.mkdir(parents=True, exist_ok=True)
        suffix = archive_path.suffix.lower()
        if suffix == ".dmg":
            source_app = _stage_macos_app_from_dmg(archive_path, extract_dir)
        elif suffix == ".zip":
            _extract_zip(archive_path, extract_dir)
            source_app = _pick_macos_app_bundle_from_root(extract_dir)
        else:
            raise RuntimeError(
                f"Unsupported macOS update format ({archive_path.suffix!r}); "
                "expected .dmg or .zip."
            )
        if source_app is None:
            raise RuntimeError(
                "Could not locate Vintage Radio.app in the downloaded update."
            )
        target_app = Path(sys.executable).resolve().parents[2]
        _launch_macos_apply_script(source_app, target_app, pid)
        return

    raise RuntimeError("Automatic updates are not supported on this platform.")
