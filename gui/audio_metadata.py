"""Audio metadata extraction and hashing utilities."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Dict, Optional

from mutagen import File as MutagenFile


def compute_file_hash(file_path: Path, chunk_size: int = 1024 * 1024) -> str:
    hasher = hashlib.sha256()
    with file_path.open("rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            hasher.update(chunk)
    return hasher.hexdigest()


def extract_metadata(file_path: Path) -> Dict[str, Any]:
    title = None
    artist = None
    duration = None
    format_name = file_path.suffix.lower().lstrip(".") or None

    audio = MutagenFile(file_path, easy=True)
    if audio is not None:
        tags = audio.tags or {}
        title = _first_tag_value(tags, "title")
        artist = _first_tag_value(tags, "artist")
        if audio.info is not None and hasattr(audio.info, "length"):
            try:
                duration = float(audio.info.length)
            except (TypeError, ValueError):
                duration = None
        if not format_name and hasattr(audio, "mime"):
            mime = audio.mime[0] if audio.mime else None
            if mime:
                format_name = mime.split("/")[-1]

    if not title:
        title = file_path.stem

    return {
        "original_filename": file_path.name,
        "file_path": str(file_path),
        "title": title,
        "artist": artist,
        "duration": duration,
        "file_size": file_path.stat().st_size,
        "format": format_name,
    }


def file_matches_metadata(
    file_path: Path, expected_size: Optional[int], expected_hash: Optional[str]
) -> bool:
    if not file_path.exists():
        return False
    if expected_size is not None:
        try:
            if file_path.stat().st_size != expected_size:
                return False
        except OSError:
            return False
    if expected_hash:
        actual_hash = compute_file_hash(file_path)
        if actual_hash != expected_hash:
            return False
    return True


def _first_tag_value(tags: Dict[str, Any], key: str) -> Optional[str]:
    value = tags.get(key)
    if isinstance(value, (list, tuple)) and value:
        return _normalize_str(value[0])
    if isinstance(value, str):
        return _normalize_str(value)
    return None


def _normalize_str(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


