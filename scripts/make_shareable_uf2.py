#!/usr/bin/env python3
"""Build a single shareable Vintage Radio .uf2 (full flash image).

Requires a Pico on USB. You will be prompted twice to hold BOOTSEL:
  1. Flash stock MicroPython (replaces any existing firmware)
  2. Read back full flash after Vintage Radio files are copied

Output:
  dist/vintage-radio-firmware-<version>-full.uf2
  firmware/release/  (copy for the desktop app)
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from project_version import PROJECT_VERSION  # noqa: E402
from scripts.build_firmware_release import (  # noqa: E402
    REPO_ROOT as _ROOT,
    fetch_micropython_uf2,
    flash_dump_uf2,
    install_to_pico,
    stage_firmware,
)


def _find_picotool() -> Path:
    for candidate in (
        REPO_ROOT / "agent_workshop" / "tools" / "picotool" / "picotool.exe",
        Path(shutil.which("picotool") or ""),
    ):
        if candidate.is_file():
            return candidate
    raise RuntimeError(
        "picotool not found. Run once:\n"
        "  powershell -File agent_workshop/download_picotool.ps1"
    )


def _detect_rpi_rp2() -> Path | None:
    from gui.sd_manager import SDManager

    try:
        for path, label in SDManager.detect_sd_roots():
            if label and label.strip().upper() == "RPI-RP2":
                return Path(path)
    except Exception:
        pass
    return None


def _wait_for_bootsel(*, prompt: str, timeout_s: float = 180.0) -> Path:
    print(prompt)
    print("(Hold BOOTSEL while plugging in USB, or tap RESET while holding BOOTSEL.)\n")
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        drive = _detect_rpi_rp2()
        if drive is not None:
            print(f"Found RPI-RP2 at {drive}")
            return drive
        time.sleep(2.0)
        print("  … waiting for RPI-RP2 drive")
    raise TimeoutError(f"Timed out after {timeout_s:.0f}s waiting for BOOTSEL.")


def _copy_uf2_to_bootsel(uf2: Path, drive: Path) -> None:
    dest = drive / uf2.name
    print(f"Copying {uf2.name} -> {dest}")
    shutil.copy2(uf2, dest)
    print("Copy complete. Pico should reboot in a few seconds.")


def _wait_for_mp_port(timeout_s: float = 45.0) -> None:
    mp = [sys.executable, "-m", "mpremote"]
    if (REPO_ROOT / ".venv" / "Scripts" / "python.exe").is_file():
        mp = [str(REPO_ROOT / ".venv" / "Scripts" / "python.exe"), "-m", "mpremote"]
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        r = subprocess.run(
            mp + ["connect", "auto", "exec", "print('VR_MP_OK')"],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=15,
        )
        out = (r.stdout or "") + (r.stderr or "")
        if "VR_MP_OK" in out or "micropython" in out.lower():
            print("MicroPython responded on USB serial.")
            return
        time.sleep(3.0)
    raise TimeoutError("MicroPython did not appear on USB serial after flashing.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", default="", help="COM port after MicroPython boots (optional)")
    parser.add_argument("--bootsel-timeout", type=float, default=180.0)
    args = parser.parse_args()

    version_slug = PROJECT_VERSION.lstrip("v")
    release_name = f"vintage-radio-firmware-{version_slug}"
    staging = REPO_ROOT / "dist" / f"{release_name}" / "firmware"
    out_uf2 = REPO_ROOT / "dist" / f"{release_name}-full.uf2"
    release_dir = REPO_ROOT / "firmware" / "release"
    release_dir.mkdir(parents=True, exist_ok=True)

    _find_picotool()  # fail early

    print(f"=== Vintage Radio shareable UF2 builder ({PROJECT_VERSION}) ===\n")

    stage_firmware(staging, basic_mode=True)
    mp_uf2 = fetch_micropython_uf2(REPO_ROOT / "dist" / "micropython_cache")

    drive = _wait_for_bootsel(
        prompt="STEP 1/2 — Flash MicroPython: put the Pico in BOOTSEL mode.",
        timeout_s=args.bootsel_timeout,
    )
    _copy_uf2_to_bootsel(mp_uf2, drive)
    time.sleep(12.0)
    _wait_for_mp_port()

    port = args.port.strip()
    if not port:
        r = subprocess.run(
            [sys.executable, "-m", "mpremote", "connect", "list"],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )
        for line in (r.stdout or "").splitlines():
            if "2e8a:0005" in line.lower() or "5303" in line:
                port = line.split()[0]
                break
    if not port:
        port = "auto"
    print(f"Installing Vintage Radio firmware via mpremote ({port}) …")
    install_to_pico(staging, port if port != "auto" else "")

    print("\nWaiting 5 s before readback …")
    time.sleep(5.0)

    drive2 = _wait_for_bootsel(
        prompt="STEP 2/2 — Capture full flash: put the SAME Pico in BOOTSEL mode again.",
        timeout_s=args.bootsel_timeout,
    )
    print(f"RPI-RP2 at {drive2} — reading flash (picotool) …")
    flash_dump_uf2(out_uf2)
    shipped = release_dir / out_uf2.name
    shutil.copy2(out_uf2, shipped)

    print(f"\nDone. Share this file:\n  {out_uf2}\n")
    print(f"App bundle path:\n  {shipped}\n")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except TimeoutError as exc:
        print(f"\nERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
