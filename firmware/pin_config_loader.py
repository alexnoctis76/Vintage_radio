"""
Pin configuration loader for Vintage Radio firmware.

Works on both MicroPython (ujson) and CPython (json).
Reads pin_config.json from the filesystem; falls back to
hardcoded defaults so existing devices keep working without
the config file.
"""

try:
    import ujson as json
except ImportError:
    import json

import os

_PICO_DEFAULTS = {
    "board": "raspberry_pi_pico",
    "audio_module": "dfplayer",
    "pins": {
        "uart_tx": 0,
        "uart_rx": 1,
        "button": 2,
        "audio_pwm": 3,
        "power_sense": 14,
        "busy": 15,
        "neopixel": 16,
    },
    "spi": {
        "bus": 1,
        "sck": 10,
        "mosi": 11,
        "miso": 12,
        "cs": 13,
    },
    "spi_alt": {
        "bus": 0,
        "sck": 18,
        "mosi": 19,
        "miso": 16,
        "cs": 17,
    },
    "dfplayer": {
        "max_volume": 28,
        "uart_baud": 9600,
    },
}

_PI_DEFAULTS = {
    "board": "raspberry_pi_linux",
    "audio_module": "vlc",
    "pins": {
        "button": 2,
        "power_sense": 14,
        "busy": 15,
    },
}

_CONFIG_FILENAME = "pin_config.json"

_SEARCH_PATHS_MICROPYTHON = [
    _CONFIG_FILENAME,
]

_cached_config = None


def _get_search_paths():
    """Return config search paths for the current platform. Avoids os.path on MicroPython import."""
    if _detect_platform() == "micropython":
        return _SEARCH_PATHS_MICROPYTHON
    return [
        _CONFIG_FILENAME,
        os.path.join(os.path.expanduser("~"), "vintage_radio", _CONFIG_FILENAME),
        "/etc/vintage_radio/" + _CONFIG_FILENAME,
    ]


def _detect_platform():
    """Return 'micropython' or 'cpython'."""
    try:
        import sys
        if hasattr(sys, "implementation") and sys.implementation.name == "micropython":
            return "micropython"
    except Exception:
        pass
    return "cpython"


def _file_exists(path):
    """Check if a file exists (works on both MicroPython and CPython)."""
    try:
        os.stat(path)
        return True
    except OSError:
        return False


def load_pin_config(force_reload=False):
    """
    Load pin configuration from pin_config.json.

    Returns a dict with the full config. Falls back to built-in
    defaults if the file is not found, ensuring backward compatibility
    with devices that don't have a config file.
    """
    global _cached_config
    if _cached_config is not None and not force_reload:
        return _cached_config

    platform = _detect_platform()
    search_paths = _get_search_paths()

    for path in search_paths:
        if _file_exists(path):
            try:
                with open(path, "r") as f:
                    cfg = json.load(f)
                print("pin_config: loaded from", path)
                _cached_config = cfg
                return cfg
            except Exception as e:
                print("pin_config: error reading", path, "-", e)

    defaults = _PICO_DEFAULTS if platform == "micropython" else _PI_DEFAULTS
    print("pin_config: no config file found, using", defaults["board"], "defaults")
    _cached_config = defaults
    return defaults


def get_pin(name, default=None):
    """Convenience: get a single pin number by function name."""
    cfg = load_pin_config()
    return cfg.get("pins", {}).get(name, default)


def get_spi_config(alt=False):
    """Get SPI bus configuration dict (or alternate SPI)."""
    cfg = load_pin_config()
    key = "spi_alt" if alt else "spi"
    return cfg.get(key, {})


def get_dfplayer_config():
    """Get DFPlayer-specific settings."""
    cfg = load_pin_config()
    return cfg.get("dfplayer", {})
