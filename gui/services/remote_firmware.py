"""Download community firmware release assets (GitHub) into a local cache."""

from __future__ import annotations

import json
import ssl
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from gui.resource_paths import app_data_dir, project_root


def _project_root() -> Path:
    return project_root()


def firmware_cache_dir() -> Path:
    cache = app_data_dir() / "firmware_cache"
    cache.mkdir(parents=True, exist_ok=True)
    return cache


def _fetch_url(url: str, *, timeout: int = 60) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "VintageRadio/1.0"})
    try:
        import certifi

        ctx = ssl.create_default_context(cafile=certifi.where())
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            return resp.read()
    except Exception:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read()


def _extract_uf2_from_zip(zip_path: Path, dest_dir: Path) -> Path:
    with zipfile.ZipFile(zip_path, "r") as zf:
        names = [n for n in zf.namelist() if n.lower().endswith(".uf2")]
        if not names:
            raise FileNotFoundError(f"No .uf2 file in {zip_path.name}")
        member = names[0]
        dest_dir.mkdir(parents=True, exist_ok=True)
        out = dest_dir / Path(member).name
        with zf.open(member) as src, open(out, "wb") as dst:
            dst.write(src.read())
        return out


def ensure_cached_uf2(
    *,
    cache_key: str,
    download_url: str,
    zip_name: Optional[str] = None,
) -> Path:
    """Return path to a cached .uf2, downloading and extracting the zip if needed."""
    cache_key = cache_key.strip() or "remote"
    entry_dir = firmware_cache_dir() / cache_key
    entry_dir.mkdir(parents=True, exist_ok=True)

    existing = sorted(entry_dir.glob("*.uf2"))
    if existing:
        return existing[0]

    zip_label = zip_name or download_url.rsplit("/", 1)[-1] or "firmware.zip"
    zip_path = entry_dir / zip_label
    if not zip_path.is_file():
        data = _fetch_url(download_url)
        zip_path.write_bytes(data)

    uf2_path = _extract_uf2_from_zip(zip_path, entry_dir)
    if not uf2_path.is_file():
        raise FileNotFoundError(f"Extract failed for {zip_path}")
    return uf2_path


def resolve_github_release_asset(
    repo: str,
    tag: str,
    *,
    asset_suffix: str = ".uf2.zip",
) -> Tuple[str, str]:
    """Return (download_url, asset_filename) for the latest matching release asset."""
    api = f"https://api.github.com/repos/{repo}/releases/tags/{tag}"
    req = urllib.request.Request(api, headers={"User-Agent": "VintageRadio/1.0"})
    try:
        import certifi

        ctx = ssl.create_default_context(cafile=certifi.where())
        with urllib.request.urlopen(req, timeout=30, context=ctx) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except Exception:
        with urllib.request.urlopen(req, timeout=30) as resp:
            payload = json.loads(resp.read().decode("utf-8"))

    assets = payload.get("assets") or []
    for asset in assets:
        name = str(asset.get("name") or "")
        if name.lower().endswith(asset_suffix.lower()):
            url = str(asset.get("browser_download_url") or "")
            if url:
                return url, name
    raise FileNotFoundError(
        f"No {asset_suffix} asset on {repo} release {tag}"
    )


def ensure_entry_uf2(entry: Dict[str, Any]) -> Path:
    """Resolve a built-in firmware entry dict to a local .uf2 path."""
    cache_key = str(entry.get("cacheKey") or entry.get("id") or "remote")
    download_url = str(entry.get("downloadUrl") or "").strip()
    if not download_url:
        repo = str(entry.get("githubRepo") or "").strip()
        tag = str(entry.get("githubTag") or entry.get("version") or "").strip().lstrip("v")
        if repo and tag:
            download_url, zip_name = resolve_github_release_asset(repo, tag)
            return ensure_cached_uf2(
                cache_key=cache_key,
                download_url=download_url,
                zip_name=zip_name,
            )
        raise ValueError("Firmware entry has no downloadUrl or githubRepo/githubTag")

    return ensure_cached_uf2(
        cache_key=cache_key,
        download_url=download_url,
    )
