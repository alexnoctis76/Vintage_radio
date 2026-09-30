#!/usr/bin/env python3
"""Create/update the private upgrade-test GitHub repo and publish a pre-release.

Requires ``GITHUB_TOKEN`` or ``GH_TOKEN`` with ``repo`` scope.

Example:
  set GITHUB_TOKEN=ghp_...
  python scripts/publish_upgrade_test_release.py ^
    --tag v1.1.0-upgrade-test ^
    --asset agent_workshop/Vintage-Radio-Windows-v1.1.0-upgrade-test.zip
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import sys
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPO = "alexnoctis76/Vintage_radio-upgrade-test"


def _token() -> str:
    tok = (os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or "").strip()
    if not tok:
        raise SystemExit(
            "Set GITHUB_TOKEN or GH_TOKEN (classic PAT with repo scope) and retry."
        )
    return tok


def _api(method: str, url: str, token: str, body: dict | None = None) -> dict | list:
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = Request(
        url,
        data=data,
        method=method,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "User-Agent": "VintageRadio-upgrade-test",
            **({"Content-Type": "application/json"} if body is not None else {}),
        },
    )
    try:
        with urlopen(req, timeout=120) as resp:
            raw = resp.read()
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise SystemExit(f"GitHub API {method} {url} -> HTTP {exc.code}: {detail}") from exc
    if not raw:
        return {}
    parsed = json.loads(raw.decode("utf-8", errors="replace"))
    return parsed if isinstance(parsed, (dict, list)) else {}


def _ensure_private_repo(owner: str, repo: str, token: str) -> None:
    url = f"https://api.github.com/repos/{owner}/{repo}"
    try:
        _api("GET", url, token)
        print(f"Repo exists: {owner}/{repo}")
        return
    except SystemExit as exc:
        if "HTTP 404" not in str(exc):
            raise
    print(f"Creating private repo {owner}/{repo} ...")
    _api(
        "POST",
        "https://api.github.com/user/repos",
        token,
        {
            "name": repo,
            "private": True,
            "description": "Private Vintage Radio upgrade-path QA (pre-releases only)",
            "has_issues": False,
            "has_projects": False,
            "has_wiki": False,
            "auto_init": True,
        },
    )
    print("Private repo created.")


def _upload_asset(upload_url: str, asset_path: Path, token: str) -> None:
    ctype = mimetypes.guess_type(asset_path.name)[0] or "application/octet-stream"
    data = asset_path.read_bytes()
    req = Request(
        upload_url,
        data=data,
        method="POST",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "Content-Type": ctype,
            "Content-Length": str(len(data)),
            "User-Agent": "VintageRadio-upgrade-test",
        },
    )
    try:
        with urlopen(req, timeout=600) as resp:
            resp.read()
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise SystemExit(f"Asset upload failed HTTP {exc.code}: {detail}") from exc
    print(f"Uploaded asset: {asset_path.name} ({len(data)} bytes)")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=DEFAULT_REPO, help="owner/repo private test fork")
    parser.add_argument("--tag", required=True, help="e.g. v1.1.0-upgrade-test")
    parser.add_argument("--asset", type=Path, required=True, help="Windows zip to attach")
    parser.add_argument("--title", default="", help="Release title (defaults to tag)")
    parser.add_argument(
        "--body",
        default="Private upgrade-path test release. Not offered to stable-channel apps.",
    )
    args = parser.parse_args()

    if "/" not in args.repo:
        raise SystemExit("--repo must be owner/repo")
    owner, repo = args.repo.split("/", 1)
    asset = args.asset.resolve()
    if not asset.is_file():
        raise SystemExit(f"Asset not found: {asset}")

    token = _token()
    _ensure_private_repo(owner, repo, token)

    tag = args.tag.strip()
    title = (args.title or tag).strip()
    release = _api(
        "POST",
        f"https://api.github.com/repos/{owner}/{repo}/releases",
        token,
        {
            "tag_name": tag,
            "name": title,
            "body": args.body,
            "draft": False,
            "prerelease": True,
            "target_commitish": "main",
        },
    )
    if not isinstance(release, dict):
        raise SystemExit("Unexpected GitHub response creating release")
    upload_url = str(release.get("upload_url") or "").split("{", 1)[0]
    if not upload_url:
        raise SystemExit("Release created but upload_url missing")
    upload_name = asset.name
    if upload_name.startswith("Vintage-Radio-Windows") and upload_name != "Vintage-Radio-Windows.zip":
        upload_name = "Vintage-Radio-Windows.zip"
    _upload_asset(f"{upload_url}?name={upload_name}", asset, token)
    html = release.get("html_url") or f"https://github.com/{owner}/{repo}/releases/tag/{tag}"
    print(f"Pre-release published: {html}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
