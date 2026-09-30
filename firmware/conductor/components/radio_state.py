"""Shared Basic-mode SD signature and cold-boot helpers (Pico + host tests).

Duplicated verbatim in ``firmware/conductor/components/radio_state.py``.
"""

try:
    import sys as _sys

    _IS_MICROPYTHON = getattr(getattr(_sys, "implementation", None), "name", "") == "micropython"
except Exception:
    _IS_MICROPYTHON = False

BASIC_SD_SIG_FILE = "VintageRadio/basic_sd_sig.txt"


def parse_basic_sd_sig_line(text):
    """Parse basic_sd_sig.txt; return (folder_count, n_stations, tf_files|None)."""
    line = (text or "").strip()
    if not line:
        return None
    parts = line.split(",")
    if len(parts) == 2:
        try:
            return (int(parts[0].strip()), int(parts[1].strip()), None)
        except (TypeError, ValueError):
            return None
    if len(parts) == 3:
        try:
            return (int(parts[0].strip()), int(parts[1].strip()), int(parts[2].strip()))
        except (TypeError, ValueError):
            return None
    return None


def format_basic_sd_sig(sig):
    """Serialize signature for basic_sd_sig.txt."""
    if sig is None:
        return ""
    fc = int(sig[0])
    n = int(sig[1])
    if len(sig) >= 3 and sig[2] is not None:
        return "{},{},{}".format(fc, n, int(sig[2]))
    return "{},{}".format(fc, n)


def basic_sd_sig_tf_count(sig):
    if sig is None or len(sig) < 3:
        return None
    try:
        tf = int(sig[2])
    except (TypeError, ValueError):
        return None
    return tf if tf >= 0 else None


def basic_sd_signatures_equivalent(prev, new):
    """Return True when two SD fingerprints describe the same card."""
    if prev is None or new is None:
        return True
    if prev == new:
        return True
    try:
        prev_fc = int(prev[0])
        new_fc = int(new[0])
    except (TypeError, ValueError, IndexError):
        prev_fc = -1
        new_fc = -1
    prev_tf = basic_sd_sig_tf_count(prev)
    new_tf = basic_sd_sig_tf_count(new)
    if prev_tf is not None and new_tf is not None and prev_tf != new_tf:
        return False
    if prev_fc >= 0 and new_fc >= 0 and prev_fc != new_fc:
        return False
    return True


def basic_is_cold_power_on_reset():
    """True after Pico power was removed (not soft_reset / USB reboot while powered)."""
    if not _IS_MICROPYTHON:
        return False
    try:
        import machine

        return machine.reset_cause() == machine.PWRON_RESET
    except Exception:
        return False
