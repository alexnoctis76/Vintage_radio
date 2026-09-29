#!/usr/bin/env python3
"""Copy a release_config template into release_config.json before packaging."""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path


def apply_release_channel(root: Path, channel: str) -> None:
    """Write ``release_config.json`` under *root* for *channel* (``stable`` or ``dev``)."""
    dest = root / "release_config.json"
    if channel == "stable":
        src = root / "release_config.example.json"
        if not src.is_file():
            raise FileNotFoundError(f"Missing template: {src}")
        shutil.copy2(src, dest)
        return
    src = root / "release_config.dev.json"
    if not src.is_file():
        raise FileNotFoundError(f"Missing template: {src}")
    shutil.copy2(src, dest)


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "channel",
        choices=("stable", "dev"),
        help="dev copies release_config.dev.json; stable copies release_config.example.json",
    )
    args = parser.parse_args()
    try:
        apply_release_channel(root, args.channel)
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    label = " (stable channel)" if args.channel == "stable" else ""
    print(f"Applied release config for {args.channel}{label}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
