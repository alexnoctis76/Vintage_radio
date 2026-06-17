#!/usr/bin/env python3
"""Build a shareable Vintage Radio Pico firmware release.

Creates ``dist/vintage-radio-firmware-<version>.zip`` containing:
  - Staged basic-mode firmware (same layout as Install to Pico)
  - Latest Raspberry Pi Pico MicroPython .uf2
  - Windows / Unix install scripts (mpremote)
  - INSTALL.txt with setup steps

Optional:
  ``--flash-dump`` — after ``--install``, save full flash to a single .uf2 via picotool
  (Pico must be in BOOTSEL / RPI-RP2 mode — not connected as COM serial).

  ``--install PORT`` — copy staged firmware to a connected Pico before ``--flash-dump``.

  ``--docker-uf2`` — experimental frozen MicroPython build (Docker required; still needs
  a one-time main.py on device flash unless you use ``--flash-dump`` afterward).
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
import zipfile
from pathlib import Path
from typing import List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from project_version import PROJECT_VERSION  # noqa: E402

_UF2_PATTERN = re.compile(r'href="(/resources/firmware/RPI_PICO[^"]*\.uf2)"')
_VERSION_PATTERN = re.compile(r"-(\d{8})-(v[\d.]+)\.uf2$")
MICROPYTHON_PICO_URL = "https://micropython.org/download/RPI_PICO/"


def _firmware_file_pairs(basic_mode: bool = True) -> List[Tuple[str, str]]:
    main_source = "firmware/pico/main_basic.py" if basic_mode else "firmware/pico/main.py"
    return [
        (main_source, "main.py"),
        ("firmware/radio_core.py", "radio_core.py"),
        ("firmware/pico/dfplayer_hardware.py", "components/dfplayer_hardware.py"),
        ("firmware/pico/components/vintage_radio_ipc.py", "components/vintage_radio_ipc.py"),
        ("firmware/pico/components/am_wav_loader.py", "components/am_wav_loader.py"),
        ("firmware/pin_config_loader.py", "pin_config_loader.py"),
        ("firmware/pico/sdcard.py", "sdcard.py"),
    ]


def stage_firmware(dest: Path, *, basic_mode: bool = True) -> None:
    """Copy firmware tree into *dest* (Pico root layout)."""
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)

    for local, remote in _firmware_file_pairs(basic_mode=basic_mode):
        src = REPO_ROOT / local
        if not src.is_file():
            raise FileNotFoundError(f"Missing firmware source: {src}")
        out = dest / remote
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, out)

    pin_src = REPO_ROOT / "firmware" / "pin_config.json"
    if pin_src.is_file():
        shutil.copy2(pin_src, dest / "pin_config.json")

    runtime = {"install_mode": "basic", "dfplayer_eq": "normal"}
    vintage = dest / "VintageRadio"
    vintage.mkdir(parents=True, exist_ok=True)
    (vintage / "advanced_runtime.json").write_text(
        json.dumps(runtime, indent=2) + "\n",
        encoding="utf-8",
    )

    am_candidates = [
        REPO_ROOT / "gui" / "resources" / "AMradioSound.wav",
        REPO_ROOT / "AMradioSound.wav",
    ]
    for am_src in am_candidates:
        if am_src.is_file():
            shutil.copy2(am_src, vintage / "AMradioSound.wav")
            break

    docs = REPO_ROOT / "docs" / "README_RP2040.md"
    if docs.is_file():
        shutil.copy2(docs, dest / "README_RP2040.md")


def fetch_micropython_uf2(cache_dir: Path) -> Path:
    """Download the newest RPI_PICO MicroPython UF2 from micropython.org."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    cached = sorted(cache_dir.glob("RPI_PICO-*.uf2"), reverse=True)
    if cached:
        return cached[0]

    req = urllib.request.Request(MICROPYTHON_PICO_URL, headers={"User-Agent": "VintageRadio/1.0"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        html = resp.read().decode("utf-8", errors="replace")

    links = _UF2_PATTERN.findall(html)
    if not links:
        raise RuntimeError(f"No RPI_PICO .uf2 links found on {MICROPYTHON_PICO_URL}")

    href = links[0]
    filename = href.rsplit("/", 1)[-1]
    out = cache_dir / filename
    if out.is_file():
        return out

    download_url = "https://micropython.org" + href
    print(f"Downloading MicroPython {filename} …")
    req2 = urllib.request.Request(download_url, headers={"User-Agent": "VintageRadio/1.0"})
    with urllib.request.urlopen(req2, timeout=120) as resp:
        out.write_bytes(resp.read())
    return out


def _write_install_txt(release_dir: Path, mpy_name: str) -> None:
    text = f"""Vintage Radio — Pico firmware release {PROJECT_VERSION}
============================================================

WHAT IS IN THIS PACKAGE
-----------------------
  micropython/{mpy_name}
      Official MicroPython for Raspberry Pi Pico (flash once via BOOTSEL).

  firmware/
      Vintage Radio basic-mode Python firmware (same as the desktop app's
      "Install to Pico"). Copy these files onto the Pico after MicroPython
      is installed.

QUICK INSTALL (Windows)
-----------------------
  1. Hold BOOTSEL on the Pico, plug in USB, copy micropython/*.uf2 to the
     RPI-RP2 drive. Wait for the Pico to reboot (~10 s).

  2. Install mpremote if needed:
       python -m pip install mpremote

  3. Run:
       powershell -ExecutionPolicy Bypass -File install.ps1

     Or pass a COM port:
       powershell -ExecutionPolicy Bypass -File install.ps1 -Port COM6

QUICK INSTALL (macOS / Linux)
-----------------------------
  1. Flash micropython/*.uf2 via BOOTSEL (same as above).
  2. python3 -m pip install mpremote
  3. ./install.sh

ONE-FILE .UF2 (optional, for sharing a pre-baked image)
-------------------------------------------------------
  Our firmware normally lives on the Pico filesystem (not inside the MicroPython
  UF2). To produce a single flash image like some community builds:

  1. Flash MicroPython, then run install.ps1 / install.sh on a golden device.
  2. Install picotool from Raspberry Pi Pico SDK tools.
  3. From this repo:
       python scripts/build_firmware_release.py --install COM6 --flash-dump

  That writes dist/vintage-radio-firmware-{PROJECT_VERSION}-full.uf2 which
  recipients can drag onto RPI-RP2 in BOOTSEL mode (replaces entire flash).

SD CARD
-------
  Prepare music with the Vintage Radio desktop app (Sync Library to SD).
  See firmware/README_RP2040.md for folder layout (01/, 02/, … with 001.mp3 …).

"""
    (release_dir / "INSTALL.txt").write_text(text, encoding="utf-8")


def _write_install_ps1(release_dir: Path) -> None:
    script = r'''param(
    [string]$Port = ""
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Firmware = Join-Path $Root "firmware"

function Invoke-Mpremote {
    param([string[]]$Args)
    if ($Port) {
        $all = @("connect", $Port) + $Args
    } else {
        $all = $Args
    }
    & python -m mpremote @all
    if ($LASTEXITCODE -ne 0) {
        throw "mpremote failed: mpremote $($all -join ' ')"
    }
}

Write-Host "Creating directories on Pico..."
try {
    Invoke-Mpremote @("exec", "import os`nfor d in ('components','VintageRadio'):`n try: os.mkdir(d)`n except OSError: pass")
} catch {
    Write-Warning $_
}

$files = @(
    @("main.py", "main.py"),
    @("radio_core.py", "radio_core.py"),
    @("pin_config_loader.py", "pin_config_loader.py"),
    @("sdcard.py", "sdcard.py"),
    @("pin_config.json", "pin_config.json"),
    @("components\dfplayer_hardware.py", "components/dfplayer_hardware.py"),
    @("components\vintage_radio_ipc.py", "components/vintage_radio_ipc.py"),
    @("components\am_wav_loader.py", "components/am_wav_loader.py"),
    @("VintageRadio\advanced_runtime.json", "VintageRadio/advanced_runtime.json"),
    @("VintageRadio\AMradioSound.wav", "VintageRadio/AMradioSound.wav")
)

foreach ($pair in $files) {
    $local = Join-Path $Firmware $pair[0]
    $remote = $pair[1]
    if (-not (Test-Path $local)) {
        Write-Warning "Skipping missing file: $local"
        continue
    }
    Write-Host "Copying $remote ..."
    Invoke-Mpremote @("cp", $local, ":$remote")
}

Write-Host "Done. Soft-reset the Pico (unplug/replug or mpremote reset)."
'''
    (release_dir / "install.ps1").write_text(script, encoding="utf-8")


def _write_install_sh(release_dir: Path) -> None:
    script = '''#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
FIRMWARE="$ROOT/firmware"
PORT="${1:-}"

mpremote_cmd() {
  if [[ -n "$PORT" ]]; then
    python3 -m mpremote connect "$PORT" "$@"
  else
    python3 -m mpremote "$@"
  fi
}

echo "Creating directories on Pico..."
mpremote_cmd exec "import os
for d in ('components','VintageRadio'):
 try: os.mkdir(d)
 except OSError: pass" || true

copy() {
  local src="$1" remote="$2"
  if [[ ! -f "$src" ]]; then
    echo "Skipping missing $src"
    return 0
  fi
  echo "Copying $remote ..."
  mpremote_cmd cp "$src" ":$remote"
}

copy "$FIRMWARE/main.py" main.py
copy "$FIRMWARE/radio_core.py" radio_core.py
copy "$FIRMWARE/pin_config_loader.py" pin_config_loader.py
copy "$FIRMWARE/sdcard.py" sdcard.py
copy "$FIRMWARE/pin_config.json" pin_config.json
copy "$FIRMWARE/components/dfplayer_hardware.py" components/dfplayer_hardware.py
copy "$FIRMWARE/components/vintage_radio_ipc.py" components/vintage_radio_ipc.py
copy "$FIRMWARE/components/am_wav_loader.py" components/am_wav_loader.py
copy "$FIRMWARE/VintageRadio/advanced_runtime.json" VintageRadio/advanced_runtime.json
copy "$FIRMWARE/VintageRadio/AMradioSound.wav" VintageRadio/AMradioSound.wav

echo "Done."
'''
    path = release_dir / "install.sh"
    path.write_text(script, encoding="utf-8")
    path.chmod(0o755)


def create_release_zip(release_dir: Path, zip_path: Path) -> None:
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    if zip_path.is_file():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(release_dir.rglob("*")):
            if path.is_file():
                zf.write(path, path.relative_to(release_dir.parent).as_posix())


def _resolve_mpremote() -> List[str]:
    venv_py = REPO_ROOT / ".venv" / "Scripts" / "python.exe"
    if venv_py.is_file():
        return [str(venv_py), "-m", "mpremote"]
    return [sys.executable, "-m", "mpremote"]


def install_to_pico(firmware_dir: Path, port: str) -> None:
    """Push staged *firmware_dir* to Pico (basic layout)."""
    mp = _resolve_mpremote()
    connect = ["connect", port] if port else []

    def run(args: List[str]) -> None:
        cmd = mp + connect + args
        r = subprocess.run(cmd, cwd=str(REPO_ROOT), capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError(
                f"mpremote failed ({' '.join(cmd)}):\n{r.stderr or r.stdout}"
            )

    try:
        run(["exec", "import os\nfor d in ('components','VintageRadio'):\n try: os.mkdir(d)\n except OSError: pass"])
    except RuntimeError:
        pass

    for _local, remote in _firmware_file_pairs(basic_mode=True):
        rel = remote.replace("/", "\\") if sys.platform == "win32" else remote
        src = firmware_dir / rel.replace("\\", "/")
        if not src.is_file():
            src = firmware_dir / Path(remote)
        if not src.is_file():
            raise FileNotFoundError(src)
        print(f"  cp {remote}")
        run(["cp", str(src), f":{remote}"])

    for extra in ("pin_config.json", "VintageRadio/advanced_runtime.json", "VintageRadio/AMradioSound.wav"):
        src = firmware_dir / extra
        if src.is_file():
            print(f"  cp {extra}")
            run(["cp", str(src), f":{extra}"])


def _find_picotool() -> Optional[Path]:
    for candidate in (
        REPO_ROOT / "agent_workshop" / "tools" / "picotool" / "picotool.exe",
        REPO_ROOT / "agent_workshop" / "tools" / "picotool.exe",
        Path(shutil.which("picotool") or ""),
    ):
        if candidate.is_file():
            return candidate
    return None


def _detect_rpi_rp2() -> Optional[Path]:
    try:
        from gui.sd_manager import SDManager

        for path, label in SDManager.detect_sd_roots():
            if label and label.strip().upper() == "RPI-RP2":
                return Path(path)
    except Exception:
        pass
    return None


def _wait_for_bootsel(*, timeout_s: float = 180.0) -> None:
    print(
        "\nOptional: create a full-flash .uf2 (requires picotool + a USB driver on Windows).\n"
        "The release .zip already contains firmware — you usually do not need this step.\n\n"
        "1. Close Vintage Radio (or disconnect) so nothing holds the COM port.\n"
        "2. Unplug the Pico, hold BOOTSEL, plug in while holding BOOTSEL.\n"
        "3. Confirm RPI-RP2 appears in File Explorer (COM port should be gone).\n"
    )
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        drive = _detect_rpi_rp2()
        if drive is not None:
            print(f"Found RPI-RP2 at {drive}\n")
            return
        time.sleep(2.0)
        print("  … waiting for RPI-RP2 (BOOTSEL)")
    raise TimeoutError(f"Timed out after {timeout_s:.0f}s waiting for BOOTSEL.")


def _picotool_not_bootsel(output: str) -> bool:
    text = (output or "").lower()
    return "not in bootsel mode" in text or "no accessible rp-series devices in bootsel" in text


def _picotool_zadig_needed(output: str) -> bool:
    text = (output or "").lower()
    return "zadig" in text or "unable to connect" in text


def _format_picotool_failure(combined: str) -> str:
    if _picotool_zadig_needed(combined):
        return (
            "Windows sees the Pico (RPI-RP2 drive) but picotool cannot open the USB "
            "interface it needs for a full flash read.\n\n"
            "This is a driver issue — not a missing BOOTSEL step:\n"
            "  1. Open Zadig (https://zadig.akeo.ie/) with the Pico in BOOTSEL.\n"
            "  2. Options → List All Devices; pick RP2 Boot (Interface 1) or similar.\n"
            "  3. Install WinUSB, then unplug/replug in BOOTSEL and re-run --flash-dump.\n\n"
            "You do not need a full flash dump to share firmware — the .zip release "
            "installs via mpremote or Install to Pico in the app."
        )
    if _picotool_not_bootsel(combined):
        return (
            "Picotool could not find the Pico in BOOTSEL mode.\n\n"
            "Release the COM port (close Vintage Radio / disconnect), then:\n"
            "  unplug USB → hold BOOTSEL → plug in while holding BOOTSEL.\n"
            "The RPI-RP2 drive should appear and the COM port should disappear.\n\n"
            "Re-run: python scripts/build_firmware_release.py "
            "--flash-dump --skip-micropython-download"
        )
    return combined.strip()


def _verify_picotool_bootsel(picotool: Path) -> tuple[bool, str]:
    """Give Windows a moment after RPI-RP2 mounts, then check picotool can see the device."""
    time.sleep(2.0)
    r = subprocess.run([str(picotool), "info"], capture_output=True, text=True)
    combined = (r.stderr or "") + (r.stdout or "")
    return r.returncode == 0, combined


def flash_dump_uf2(
    out_path: Path,
    *,
    wait_bootsel: bool = True,
    bootsel_timeout: float = 180.0,
) -> None:
    picotool = _find_picotool()
    if not picotool:
        raise RuntimeError(
            "picotool not found. Run once:\n"
            "  powershell -ExecutionPolicy Bypass -File agent_workshop/download_picotool.ps1\n"
            "Or install picotool from the Raspberry Pi Pico SDK and add it to PATH."
        )
    if wait_bootsel and _detect_rpi_rp2() is None:
        _wait_for_bootsel(timeout_s=bootsel_timeout)
    elif wait_bootsel and _detect_rpi_rp2() is not None:
        ok, probe = _verify_picotool_bootsel(picotool)
        if not ok and _picotool_zadig_needed(probe):
            raise RuntimeError(f"picotool cannot connect:\n{_format_picotool_failure(probe)}")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [str(picotool), "save", "-a", str(out_path)]
    print("Running:", " ".join(cmd))
    r = subprocess.run(cmd, capture_output=True, text=True)
    combined = (r.stderr or "") + (r.stdout or "")
    if r.returncode != 0 and wait_bootsel and _picotool_not_bootsel(combined):
        if _detect_rpi_rp2() is None:
            print("Pico is still running MicroPython — waiting for BOOTSEL…")
            _wait_for_bootsel(timeout_s=bootsel_timeout)
        else:
            ok, probe = _verify_picotool_bootsel(picotool)
            if not ok:
                combined = probe or combined
        r = subprocess.run(cmd, capture_output=True, text=True)
        combined = (r.stderr or "") + (r.stdout or "")

    if r.returncode != 0:
        raise RuntimeError(f"picotool save failed:\n{_format_picotool_failure(combined)}")
    print(f"Wrote full flash image: {out_path} ({out_path.stat().st_size} bytes)")


def docker_build_frozen_uf2(out_dir: Path) -> Optional[Path]:
    """Attempt a Docker-based frozen MicroPython build (experimental)."""
    if not shutil.which("docker"):
        print("Docker not available; skipping --docker-uf2")
        return None

    manifest = REPO_ROOT / "firmware" / "uf2" / "manifest.py"
    frozen_dir = REPO_ROOT / "firmware" / "uf2" / "frozen"
    frozen_dir.mkdir(parents=True, exist_ok=True)

    for local, remote in _firmware_file_pairs(basic_mode=True):
        src = REPO_ROOT / local
        dst = frozen_dir / remote
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)

    bootstrap = frozen_dir / "boot_main.py"
    bootstrap.write_text(
        "import main\nmain.main()\n",
        encoding="utf-8",
    )

    docker_script = f"""
set -e
MPY=/tmp/micropython
if [ ! -d "$MPY/.git" ]; then
  git clone --depth 1 --branch v1.27.0 https://github.com/micropython/micropython.git "$MPY"
fi
cd "$MPY"
make -C mpy-cross
make -C ports/rp2 submodules
make -C ports/rp2 BOARD=RPI_PICO FROZEN_MANIFEST={manifest.as_posix()}
cp ports/rp2/build/firmware.uf2 /out/vintage-radio-frozen-{PROJECT_VERSION}.uf2
"""
    out_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", suffix=".sh", delete=False) as tf:
        tf.write(docker_script)
        script_path = tf.name

    try:
        cmd = [
            "docker", "run", "--rm",
            "-v", f"{REPO_ROOT}:/project:ro",
            "-v", f"{out_dir}:/out",
            "-v", f"{script_path}:/build.sh:ro",
            "micropython/build-micropython-arm",
            "bash", "/build.sh",
        ]
        print("Docker build (may take 10-20 min on first run) ...")
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)
        if r.returncode != 0:
            print(r.stdout)
            print(r.stderr, file=sys.stderr)
            print("Docker frozen build failed (firmware still usable via install scripts).")
            return None
        uf2 = out_dir / f"vintage-radio-frozen-{PROJECT_VERSION}.uf2"
        if uf2.is_file():
            print(f"Frozen UF2: {uf2}")
            return uf2
    except subprocess.TimeoutExpired:
        print("Docker build timed out.")
    except Exception as exc:
        print(f"Docker build error: {exc}")
    finally:
        Path(script_path).unlink(missing_ok=True)
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=REPO_ROOT / "dist",
        help="Output directory (default: dist/)",
    )
    parser.add_argument(
        "--skip-micropython-download",
        action="store_true",
        help="Do not download MicroPython UF2 (use cache only)",
    )
    parser.add_argument(
        "--install",
        metavar="PORT",
        default="",
        help="Install staged firmware to Pico via mpremote (e.g. COM6)",
    )
    parser.add_argument(
        "--flash-dump",
        action="store_true",
        help="Save full Pico flash to a single .uf2 (Pico in BOOTSEL / RPI-RP2; uses picotool)",
    )
    parser.add_argument(
        "--bootsel-timeout",
        type=float,
        default=180.0,
        help="Seconds to wait for RPI-RP2 before flash dump (default: 180)",
    )
    parser.add_argument(
        "--no-wait-bootsel",
        action="store_true",
        help="Do not wait for BOOTSEL; fail immediately if Pico is on COM serial",
    )
    parser.add_argument(
        "--docker-uf2",
        action="store_true",
        help="Experimental: build frozen MicroPython UF2 via Docker",
    )
    args = parser.parse_args()

    version_slug = PROJECT_VERSION.lstrip("v")
    release_name = f"vintage-radio-firmware-{version_slug}"
    release_dir = args.output_dir / release_name
    zip_path = args.output_dir / f"{release_name}.zip"

    print(f"Staging firmware -> {release_dir / 'firmware'}")
    stage_firmware(release_dir / "firmware", basic_mode=True)

    mpy_cache = args.output_dir / "micropython_cache"
    if args.skip_micropython_download:
        existing = sorted(mpy_cache.glob("RPI_PICO-*.uf2"), reverse=True)
        if not existing:
            print("No cached MicroPython UF2; remove --skip-micropython-download")
            return 1
        mpy_uf2 = existing[0]
    else:
        mpy_uf2 = fetch_micropython_uf2(mpy_cache)

    mpy_dest_dir = release_dir / "micropython"
    mpy_dest_dir.mkdir(parents=True, exist_ok=True)
    mpy_dest = mpy_dest_dir / mpy_uf2.name
    if not mpy_dest.is_file():
        shutil.copy2(mpy_uf2, mpy_dest)

    _write_install_txt(release_dir, mpy_uf2.name)
    _write_install_ps1(release_dir)
    _write_install_sh(release_dir)

    print(f"Creating {zip_path}")
    create_release_zip(release_dir, zip_path)
    print(f"Release zip: {zip_path} ({zip_path.stat().st_size // 1024} KiB)")

    if args.install:
        print(f"Installing to Pico on {args.install or 'auto-detect'} …")
        install_to_pico(release_dir / "firmware", args.install)

    if args.flash_dump:
        full_uf2 = args.output_dir / f"{release_name}-full.uf2"
        flash_dump_uf2(
            full_uf2,
            wait_bootsel=not args.no_wait_bootsel,
            bootsel_timeout=args.bootsel_timeout,
        )
        print(f"Share this one-file UF2: {full_uf2}")
        release_copy = REPO_ROOT / "firmware" / "release"
        release_copy.mkdir(parents=True, exist_ok=True)
        shipped = release_copy / full_uf2.name
        shutil.copy2(full_uf2, shipped)
        print(f"Copied for app bundling: {shipped}")

    if args.docker_uf2:
        docker_build_frozen_uf2(args.output_dir)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
