"""Vintage Radio Music Manager GUI Package."""

__version__ = "1.0.0"

from .audio_metadata import compute_file_hash, extract_metadata, file_matches_metadata
from .database import DatabaseManager
from .sd_manager import SDManager

__all__ = [
    "DatabaseManager",
    "compute_file_hash",
    "extract_metadata",
    "file_matches_metadata",
    "SDManager",
]


def __getattr__(name: str):
    if name in {"MainWindow", "run_app"}:
        from . import radio_manager

        return getattr(radio_manager, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

