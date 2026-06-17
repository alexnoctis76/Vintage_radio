#!/usr/bin/env python3
"""Set :data:`project_version.PROJECT_VERSION` (only semver source; ``gui.__version__`` aliases it).

Usage:
  python scripts/set_app_version.py v0.2.5-beta
  python scripts/set_app_version.py --dry-run v0.2.5-beta
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


_PROJECT_VERSION_RE = re.compile(
    r"^(PROJECT_VERSION\s*=\s*)([\"'])([^\"']+)(\2)",
    re.MULTILINE,
)


def _project_version_path() -> Path:
    return Path(__file__).resolve().parent.parent / "project_version.py"


def set_version(new_version: str, *, dry_run: bool = False) -> str:
    raw = new_version.strip()
    if not raw:
        raise ValueError("version string is empty")
    path = _project_version_path()
    text = path.read_text(encoding="utf-8")
    m = _PROJECT_VERSION_RE.search(text)
    if not m:
        raise RuntimeError(
            f"Could not find PROJECT_VERSION assignment in {path} "
            '(expected a line like PROJECT_VERSION = "v0.1.0").'
        )
    old = m.group(3)
    new_text = _PROJECT_VERSION_RE.sub(rf"\1\2{raw}\2", text, count=1)
    if new_text == text:
        return old
    if not dry_run:
        path.write_text(new_text, encoding="utf-8", newline="\n")
    return old


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "version",
        help="New release tag, e.g. v0.2.5-beta (written to project_version.py)",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Print old and new values without writing the file",
    )
    args = p.parse_args()
    try:
        old = set_version(args.version, dry_run=args.dry_run)
    except (ValueError, RuntimeError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    action = "would set" if args.dry_run else "set"
    print(
        f"{action} PROJECT_VERSION: {old!r} -> {args.version.strip()!r} ({_project_version_path()})"
    )
    print("  (gui.__version__ re-exports it via __getattr__.)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
