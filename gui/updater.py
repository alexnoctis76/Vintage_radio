"""GitHub release updater helpers for packaged app builds."""

from __future__ import annotations

import json
import logging
import os
import platform
import re
import shlex
import shutil
import ssl
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Literal, Optional
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

_LOG = logging.getLogger(__name__)


def _log_updater(message: str) -> None:
    """Append to session log when available; always emit at INFO for loggers."""
    _LOG.info("[UPDATER] %s", message)
    try:
        from gui.session_log import write_session_line

        write_session_line(message, prefix="UPDATER")
    except Exception:
        pass


# Must match filenames produced by release packaging (see .github/workflows/build-release.yml).
PREFERRED_WINDOWS_ASSET = "Vintage-Radio-Windows.zip"
PREFERRED_MACOS_ASSET = "Vintage.Radio.dmg"
# Optional small JSON attached to each release; per-OS shipped semver may differ from tag_name.
RELEASE_VERSIONS_MANIFEST = "release-versions.json"

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
    # Semver string shown to the user and used for update checks; from release-versions.json
    # when present, otherwise equal to tag_name.
    platform_version: str = ""

    def advertised_version(self) -> str:
        v = (self.platform_version or "").strip()
        return v if v else self.tag_name


UpdateStatus = Literal["update_available", "up_to_date", "unavailable"]


@dataclass
class UpdateCheckResult:
    """Outcome of a GitHub release check (includes up-to-date vs fetch failure)."""

    status: UpdateStatus
    release: Optional[ReleaseInfo] = None
    error: Optional[str] = None
    latest_published: Optional[str] = None


def _https_ssl_context() -> ssl.SSLContext:
    """Build TLS context for GitHub / HTTPS in frozen apps.

    PyInstaller includes the ``certifi`` module but not ``cacert.pem`` unless the
    spec bundles certifi data (``collect_all('certifi')``). Without the PEM,
    ``certifi.where()`` can point at a missing path and verification fails.
    """
    try:
        import certifi

        cafile = certifi.where()
        if cafile and os.path.isfile(cafile):
            return ssl.create_default_context(cafile=cafile)
    except Exception:
        pass
    return ssl.create_default_context()


def _urlopen_with_certs(req: Request, timeout: int):
    ctx = _https_ssl_context()
    return urlopen(req, timeout=timeout, context=ctx)


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


def _fetch_release_assets_for_tag(tag: str) -> list[dict]:
    """GET ``/releases/tags/{tag}`` so we have the full ``assets`` list and URLs.

    The releases *list* payload can omit or slim assets in some cases; the tag
    endpoint matches what the GitHub UI uses for download links.
    """
    t = quote((tag or "").strip(), safe="")
    if not t:
        return []
    url = f"https://api.github.com/repos/{GITHUB_REPO_SLUG}/releases/tags/{t}"
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "VintageRadio-Updater",
    }
    try:
        req = Request(url, headers=headers)
        with _urlopen_with_certs(req, timeout=25) as resp:
            raw = resp.read()
        data = json.loads(raw.decode("utf-8", errors="replace"))
        if isinstance(data, dict):
            assets = list(data.get("assets") or [])
            _log_updater(f"GET {url} -> {len(assets)} asset(s)")
            return assets
    except HTTPError as e:
        _log_updater(f"GET releases/tags/{t}: HTTP {e.code} {e.reason!r}")
    except Exception as e:
        _log_updater(f"GET releases/tags/{t}: {type(e).__name__}: {e}")
    return []


def _merge_release_assets(primary: list[dict], extra: list[dict]) -> list[dict]:
    """Union by GitHub asset ``id`` when present; else append unknowns."""
    seen: set[int] = set()
    out: list[dict] = []
    for a in primary:
        aid = a.get("id")
        if isinstance(aid, int):
            seen.add(aid)
        out.append(a)
    for a in extra:
        aid = a.get("id")
        if isinstance(aid, int):
            if aid in seen:
                continue
            seen.add(aid)
        out.append(a)
    return out


def _version_equal(a: str, b: str) -> bool:
    return not is_newer(a, b) and not is_newer(b, a)


def _manifest_versions_asset(assets: list[dict]) -> Optional[dict]:
    want = RELEASE_VERSIONS_MANIFEST.lower()
    for asset in assets:
        name = str(asset.get("name") or "").strip().lower()
        if name == want:
            return asset
    return None


def _fetch_release_versions_manifest_dict(browser_download_url: str) -> Optional[dict]:
    url = (browser_download_url or "").strip()
    if not url:
        return None
    try:
        req = Request(url, headers={"User-Agent": "VintageRadio-Updater"})
        with _urlopen_with_certs(req, timeout=15) as resp:
            raw = resp.read()
        data = json.loads(raw.decode("utf-8", errors="replace"))
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def _manifest_value_for_platform(data: dict) -> Optional[str]:
    pm = _platform_matcher()
    keys: list[str]
    if pm == "windows":
        keys = ["windows"]
    elif pm == "macos":
        keys = ["macos", "mac", "darwin"]
    else:
        return None
    for ck in keys:
        raw = data.get(ck)
        if raw is None:
            lk = ck.lower()
            for dk, dv in data.items():
                if str(dk).strip().lower() == lk:
                    raw = dv
                    break
        if raw is not None:
            s = str(raw).strip()
            if s:
                return s
    return None


def _effective_platform_version(info: ReleaseInfo) -> str:
    """Shipped semver for this OS (from release-versions.json when present, else tag_name)."""
    man = _manifest_versions_asset(list(info.assets or []))
    if man is not None:
        parsed = _fetch_release_versions_manifest_dict(
            str(man.get("browser_download_url") or "")
        )
        if parsed is not None:
            v = _manifest_value_for_platform(parsed)
            if v:
                return v
    return str(info.tag_name or "").strip()


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
    if best is None:
        return None
    eff = _effective_platform_version(best)
    return ReleaseInfo(
        tag_name=best.tag_name,
        html_url=best.html_url,
        body=best.body,
        assets=best.assets,
        platform_version=eff,
    )


def _newest_installable_release(items: list) -> Optional[ReleaseInfo]:
    """Newest published release that ships an installer for this platform."""
    best_info: Optional[ReleaseInfo] = None
    best_eff: Optional[str] = None
    best_tag: Optional[str] = None
    for item in items:
        if not isinstance(item, dict) or item.get("draft"):
            continue
        info = _release_info_from_api_dict(item)
        if info is None or get_platform_asset(info.assets) is None:
            continue
        eff = _effective_platform_version(info)
        candidate = ReleaseInfo(
            tag_name=info.tag_name,
            html_url=info.html_url,
            body=info.body,
            assets=info.assets,
            platform_version=eff,
        )
        if best_info is None:
            best_info = candidate
            best_eff = eff
            best_tag = info.tag_name
            continue
        assert best_eff is not None and best_tag is not None
        replace = False
        if is_newer(eff, best_eff):
            replace = True
        elif _version_equal(eff, best_eff) and is_newer(info.tag_name, best_tag):
            replace = True
        if replace:
            best_info = candidate
            best_eff = eff
            best_tag = info.tag_name
    return best_info


def _fetch_release_list(user_agent: str) -> list:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": user_agent,
    }
    req = Request(GITHUB_RELEASES_LIST_URL, headers=headers)
    with _urlopen_with_certs(req, timeout=20) as resp:
        raw = resp.read()
    items = json.loads(raw.decode("utf-8", errors="replace"))
    return items if isinstance(items, list) else []


def run_update_check(
    *,
    current_version: str,
    user_agent: str = "VintageRadio",
) -> UpdateCheckResult:
    """Check GitHub for updates; distinguish up-to-date from API / asset failures."""
    cur = (current_version or "").strip()
    try:
        items = _fetch_release_list(user_agent)
    except HTTPError as e:
        msg = f"GitHub API HTTP {e.code}"
        if e.reason:
            msg = f"{msg}: {e.reason}"
        return UpdateCheckResult(status="unavailable", error=msg)
    except Exception as e:
        return UpdateCheckResult(status="unavailable", error=str(e))

    if items:
        if cur:
            update = _best_release_newer_than_for_platform(items, cur)
            if update is not None:
                return UpdateCheckResult(status="update_available", release=update)
        else:
            update = _newest_installable_release(items) or _newest_release_from_list(items)
            if update is not None:
                return UpdateCheckResult(status="update_available", release=update)

        newest = _newest_installable_release(items)
        if newest is not None:
            return UpdateCheckResult(
                status="up_to_date",
                release=newest,
                latest_published=newest.advertised_version(),
            )
        return UpdateCheckResult(
            status="unavailable",
            error="No installer asset found on GitHub for this platform.",
        )

    try:
        req = Request(
            GITHUB_RELEASES_LATEST_URL,
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": user_agent,
            },
        )
        with _urlopen_with_certs(req, timeout=20) as resp:
            raw = resp.read()
        data = json.loads(raw.decode("utf-8", errors="replace"))
        if isinstance(data, dict):
            info = _release_info_from_api_dict(data)
            if info is not None and get_platform_asset(info.assets) is not None:
                eff = _effective_platform_version(info)
                full = ReleaseInfo(
                    tag_name=info.tag_name,
                    html_url=info.html_url,
                    body=info.body,
                    assets=info.assets,
                    platform_version=eff,
                )
                if cur and is_newer(eff, cur):
                    return UpdateCheckResult(status="update_available", release=full)
                return UpdateCheckResult(
                    status="up_to_date",
                    release=full,
                    latest_published=full.advertised_version(),
                )
    except HTTPError as e:
        if e.code != 404:
            msg = f"GitHub API HTTP {e.code}"
            if e.reason:
                msg = f"{msg}: {e.reason}"
            return UpdateCheckResult(status="unavailable", error=msg)
    except Exception as e:
        return UpdateCheckResult(status="unavailable", error=str(e))

    return UpdateCheckResult(
        status="unavailable",
        error="No published releases found on GitHub.",
    )


def check_latest_release(
    user_agent: str = "VintageRadio",
    *,
    current_version: Optional[str] = None,
) -> Optional[ReleaseInfo]:
    """Fetch a published GitHub release to offer as an update.

    Uses the **releases list** (``per_page=100``) and semver. When
    *current_version* is set (recommended), returns the best release for this OS
    whose **platform version** (from optional ``release-versions.json`` on the release,
    else the GitHub tag) is strictly greater than *current_version*, and that has
    an installer asset for the current platform.

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
            cur_ver = (current_version or "").strip()
            if cur_ver:
                info = _best_release_newer_than_for_platform(items, cur_ver)
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
                if get_platform_asset(info.assets) is None:
                    return None
                eff = _effective_platform_version(info)
                cur = (current_version or "").strip()
                if cur and not is_newer(eff, cur):
                    return None
                return ReleaseInfo(
                    tag_name=info.tag_name,
                    html_url=info.html_url,
                    body=info.body,
                    assets=info.assets,
                    platform_version=eff,
                )
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


def _releases_download_url(tag_name: str, basename: str) -> Optional[str]:
    """``/releases/download/{tag}/{basename}`` (basename must match upload exactly)."""
    tag = (tag_name or "").strip()
    base = (basename or "").strip()
    if not tag or not base:
        return None
    t = quote(tag, safe="")
    f = quote(base, safe="")
    return f"https://github.com/{GITHUB_REPO_SLUG}/releases/download/{t}/{f}"


def _best_release_newer_than_for_platform(
    items: list, current_version: str
) -> Optional[ReleaseInfo]:
    """Newest updatable release for this OS: semver(platform deliverable) > current."""
    cur = (current_version or "").strip()
    if not cur:
        return None
    best_info: Optional[ReleaseInfo] = None
    best_eff: Optional[str] = None
    best_tag: Optional[str] = None
    for item in items:
        if not isinstance(item, dict) or item.get("draft"):
            continue
        info = _release_info_from_api_dict(item)
        if info is None:
            continue
        if get_platform_asset(info.assets) is None:
            continue
        eff = _effective_platform_version(info)
        if not is_newer(eff, cur):
            continue
        if best_info is None:
            best_info = info
            best_eff = eff
            best_tag = info.tag_name
            continue
        assert best_eff is not None and best_tag is not None
        replace = False
        if is_newer(eff, best_eff):
            replace = True
        elif _version_equal(eff, best_eff) and is_newer(info.tag_name, best_tag):
            replace = True
        if replace:
            best_info = info
            best_eff = eff
            best_tag = info.tag_name
    if best_info is None or best_eff is None:
        return None
    return ReleaseInfo(
        tag_name=best_info.tag_name,
        html_url=best_info.html_url,
        body=best_info.body,
        assets=best_info.assets,
        platform_version=best_eff,
    )


def direct_download_url_for_release(tag_name: str) -> Optional[str]:
    """URL for the official installer **for this exact release tag** only.

    Uses ``/releases/download/{tag}/{filename}``. Filename must match the file
    attached to that tag; if it differs (e.g. ``Vintage Radio.dmg`` vs
    ``Vintage.Radio.dmg``), use :func:`installer_download_urls_for_release` which
    tries several sources.
    """
    preferred = official_installer_zip_basename()
    if not preferred:
        return None
    return _releases_download_url(tag_name, preferred)


def installer_download_url_for_release(release: ReleaseInfo) -> Optional[str]:
    """Direct installer download URL tied to *release.tag_name* (Windows / macOS)."""
    return direct_download_url_for_release(release.tag_name)


def official_installer_zip_basename() -> Optional[str]:
    """Basename of the official installer for this OS (zip on Windows, DMG on macOS)."""
    return _preferred_asset_name_for_platform()


def installer_download_urls_for_release(release: ReleaseInfo) -> list[str]:
    """Ordered HTTPS URLs to try for the packaged installer (handles filename mismatches)."""
    tag = (release.tag_name or "").strip()
    if not tag:
        _log_updater("installer_download_urls: empty tag_name, no URLs")
        return []

    out: list[str] = []
    seen: set[str] = set()

    def add(u: Optional[str]) -> None:
        u = (u or "").strip()
        if u and u not in seen:
            seen.add(u)
            out.append(u)

    sys_name = platform.system().lower()
    assets = list(release.assets or [])
    tag_assets = _fetch_release_assets_for_tag(tag)
    if tag_assets:
        before = len(assets)
        assets = _merge_release_assets(assets, tag_assets)
        _log_updater(
            f"release {tag!r}: merged API tag assets ({before} -> {len(assets)} rows)"
        )

    if "windows" in sys_name:
        a = get_platform_asset(assets)
        if a:
            add(str(a.get("browser_download_url") or ""))
        for asset in assets:
            name = str(asset.get("name") or "").lower()
            if name.endswith(".zip") and "windows" in name:
                add(str(asset.get("browser_download_url") or ""))
        add(direct_download_url_for_release(tag))
        return out

    if "darwin" in sys_name:
        a = get_platform_asset(assets)
        if a:
            add(str(a.get("browser_download_url") or ""))
        for asset in assets:
            name = str(asset.get("name") or "").lower()
            if not name.endswith(".dmg"):
                continue
            if _VINTAGE_RADIO_DMG_RE.search(name):
                add(str(asset.get("browser_download_url") or ""))
                continue
            if "vintage" in name and "radio" in name:
                add(str(asset.get("browser_download_url") or ""))
                continue
            if "macos" in name:
                add(str(asset.get("browser_download_url") or ""))
        add(direct_download_url_for_release(tag))
        add(_releases_download_url(tag, "Vintage Radio.dmg"))
        add(_releases_download_url(tag, "Vintage-Radio-macOS.zip"))
        _log_updater(
            f"release {tag!r}: {len(assets)} API asset(s), built {len(out)} download URL(s)"
        )
        for i, u in enumerate(out, 1):
            _log_updater(f"  URL[{i}/{len(out)}]: {u}")
        return out

    _log_updater(f"release {tag!r}: non-macOS/Windows, no installer URLs")
    return out


def download_update_try_urls(
    urls: list[str],
    dest_dir: Path,
    progress_cb: Optional[Callable[[int, int], None]] = None,
    *,
    dest_filename: Optional[str] = None,
) -> Path:
    """Try each URL in order; on HTTP 404 only, try the next. Re-raises last error."""
    last_err: Optional[BaseException] = None
    seen: set[str] = set()
    attempted: list[str] = []
    _log_updater(
        f"download_try_urls: cache_dir={dest_dir!s} dest_filename={dest_filename!r} "
        f"candidates={len(urls)}"
    )
    for url in urls:
        u = (url or "").strip()
        if not u or u in seen:
            continue
        seen.add(u)
        attempted.append(u)
        _log_updater(f"GET {u}")
        try:
            path = download_update(u, dest_dir, progress_cb, dest_filename=dest_filename)
            _log_updater(f"download OK -> {path}")
            return path
        except HTTPError as e:
            last_err = e
            _log_updater(f"HTTP {e.code} {e.reason!r} for {u}")
            if e.code != 404:
                raise
            parsed = urlparse(u)
            stale = dest_dir / (
                dest_filename or Path(parsed.path).name or "vintage-radio-update.zip"
            )
            if stale.exists():
                try:
                    stale.unlink()
                except OSError:
                    pass
            continue
    if last_err is not None:
        summary = "\n".join(f"  - {a}" for a in attempted) if attempted else "  (none)"
        if isinstance(last_err, HTTPError):
            raise RuntimeError(
                f"{last_err}\nTried {len(attempted)} URL(s):\n{summary}"
            ) from last_err
        raise last_err
    raise RuntimeError("No download URLs to try.")


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
    _log_updater(f"download_update: writing {target!s} (from URL path {file_name!r})")
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
    _log_updater(f"DMG stage: dmg={dmg_path!s} work_dir={work_dir!s}")
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
        _log_updater(f"hdiutil attach failed rc={attach.returncode}: {msg[:500]}")
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
        _log_updater(f"DMG stage OK: copied {source!s} -> {dest!s}")
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


def _macos_bundle_main_executable(bundle: Path) -> Path:
    """PyInstaller one-folder bundle: ``Name.app/Contents/MacOS/Name``."""
    return bundle / "Contents" / "MacOS" / bundle.stem


def _launch_macos_apply_script(source_app: Path, target_app: Path, pid: int) -> None:
    script = source_app.parent / "apply_update.sh"
    log = source_app.parent / "apply_update.log"
    src_q = shlex.quote(str(source_app))
    tgt_q = shlex.quote(str(target_app))
    inner_q = shlex.quote(str(_macos_bundle_main_executable(target_app)))
    log_q = shlex.quote(str(log))
    content = f"""#!/bin/bash
# Not using set -e: launch failures must not abort the script.
PID={int(pid)}
SOURCE={src_q}
TARGET={tgt_q}
INNER={inner_q}
LOG={log_q}
exec >>"$LOG" 2>&1
echo "apply_update start $(date -u +%Y-%m-%dT%H:%M:%SZ) pid=$PID"

# Wait for old process to exit
while kill -0 "$PID" 2>/dev/null; do
  sleep 1
done
echo "installer: old process exited; replacing bundle"

# Replace the bundle (abort on copy failure — nothing to launch if this breaks)
rm -rf "$TARGET"
if command -v ditto >/dev/null 2>&1; then
  ditto "$SOURCE" "$TARGET" || {{ echo "installer: ditto failed, exit $?"; exit 1; }}
else
  cp -R "$SOURCE" "$TARGET" || {{ echo "installer: cp failed, exit $?"; exit 1; }}
fi

# Clear quarantine flags — required for unsigned apps; open silently fails otherwise
xattr -cr "$TARGET" 2>/dev/null || true
xattr -dr com.apple.quarantine "$TARGET" 2>/dev/null || true

# Ensure inner executable is runnable
chmod u+x "$INNER" 2>/dev/null || true

sleep 1
echo "installer: launching updated app TARGET=$TARGET INNER=$INNER"

# Try open -n (new instance) first
if open -n "$TARGET" 2>/dev/null; then
  echo "installer: launched via open -n"
else
  echo "installer: open -n failed (exit $?), trying open"
  if open "$TARGET" 2>/dev/null; then
    echo "installer: launched via open"
  else
    echo "installer: open failed, trying direct exec via nohup"
    if [[ -x "$INNER" ]]; then
      nohup "$INNER" >/dev/null 2>&1 &
      echo "installer: launched via nohup pid $!"
    else
      echo "installer: ERROR: $INNER is not executable or missing"
    fi
  fi
fi

echo "apply_update done $(date -u +%Y-%m-%dT%H:%M:%SZ)"
"""
    script.write_text(content, encoding="utf-8")
    script.chmod(0o755)
    subprocess.Popen(["/bin/bash", str(script)], start_new_session=True)
    _log_updater(f"scheduled apply_update.sh log={log!s} target={target_app!s}")


def apply_update(archive_path: Path) -> None:
    """Extract or mount download, then launch an update script that replaces app files after exit."""
    if not getattr(sys, "frozen", False):
        raise RuntimeError("Automatic updates are only supported for packaged builds.")

    _log_updater(
        f"apply_update: path={archive_path!s} suffix={archive_path.suffix!r} "
        f"exists={archive_path.is_file()}"
    )
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
