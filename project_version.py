"""Canonical Vintage Radio release label (GUI About, updater, logs).

Updated by ``python scripts/set_app_version.py <tag>`` or ``build_* --set-version``.
"""

PROJECT_VERSION = "v1.1.0"

# Bundled Basic UF2 semver at or above this is "current"; older shipped images are legacy.
CURRENT_FIRMWARE_GENERATION = "1.1.0"

__all__ = ["PROJECT_VERSION", "CURRENT_FIRMWARE_GENERATION"]
