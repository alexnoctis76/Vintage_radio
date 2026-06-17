# Install default Vintage Radio firmware on a Raspberry Pi Pico (Windows).
#
# Use when drag-and-drop to RPI-RP2 fails (broken BOOTSEL mass-storage driver).
#
# Usage (from repo root):
#   powershell -ExecutionPolicy Bypass -File scripts\install_pico_windows.ps1
#   powershell -ExecutionPolicy Bypass -File scripts\install_pico_windows.ps1 -Port COM6
#   powershell -ExecutionPolicy Bypass -File scripts\install_pico_windows.ps1 -FixDrivers   # run as Admin
#
param(
    [string]$Port = "",
    [switch]$FixDrivers,
    [switch]$SkipMicroPythonFlash
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$ReleaseDir = Join-Path $RepoRoot "dist\vintage-radio-firmware-1.0.0"
$FirmwareDir = Join-Path $ReleaseDir "firmware"
$VenvPython = Join-Path $RepoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $VenvPython)) { $VenvPython = "python" }

function Write-Step([string]$Msg) {
    Write-Host ""
    Write-Host "==> $Msg" -ForegroundColor Cyan
}

function Get-Rp2040BootselDevices {
    Get-PnpDevice -PresentOnly -ErrorAction SilentlyContinue |
        Where-Object { $_.InstanceId -match 'VID_2E8A&PID_0003' }
}

function Get-RpiRp2Drive {
    Get-Volume -ErrorAction SilentlyContinue |
        Where-Object { $_.FileSystemLabel -eq 'RPI-RP2' -and $_.DriveLetter } |
        Select-Object -First 1
}

function Find-MicroPythonUf2 {
    $candidates = @(
        (Get-ChildItem -Path (Join-Path $ReleaseDir "micropython") -Filter "RPI_PICO*.uf2" -ErrorAction SilentlyContinue),
        (Get-ChildItem -Path (Join-Path $RepoRoot "dist") -Filter "RPI_PICO*.uf2" -ErrorAction SilentlyContinue),
        (Get-ChildItem -Path (Join-Path $RepoRoot "dist\micropython_cache") -Filter "RPI_PICO*.uf2" -ErrorAction SilentlyContinue),
        (Get-ChildItem -Path (Join-Path $RepoRoot "data\firmware_cache\micropython") -Filter "RPI_PICO*.uf2" -ErrorAction SilentlyContinue)
    ) | ForEach-Object { $_ } | Where-Object { $_ } | Sort-Object LastWriteTime -Descending
    return $candidates | Select-Object -First 1
}

function Ensure-ReleaseStaged {
    if ((Test-Path $FirmwareDir) -and (Test-Path (Join-Path $FirmwareDir "main.py"))) {
        return
    }
    Write-Step "Staging firmware release (one-time)..."
    & $VenvPython (Join-Path $RepoRoot "scripts\build_firmware_release.py") --skip-micropython-download
    if (-not (Test-Path (Join-Path $FirmwareDir "main.py"))) {
        throw "Firmware staging failed - missing $(Join-Path $FirmwareDir 'main.py')"
    }
}

function Invoke-Mpremote {
    param([string[]]$Args)
    $base = @("-m", "mpremote")
    if ($Port) {
        $all = $base + @("connect", $Port) + $Args
    } else {
        $all = $base + $Args
    }
    & $VenvPython @all
    if ($LASTEXITCODE -ne 0) {
        throw "mpremote failed: $($all -join ' ')"
    }
}

function Wait-ForMicroPythonPort {
    param([int]$TimeoutSec = 90)
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $deadline) {
        $list = & $VenvPython -m mpremote connect list 2>&1
        foreach ($line in ($list -split "`n")) {
            if ($line -match '2e8a:0005' -or $line -match '5303') {
                $p = ($line -split '\s+')[0]
                if ($p -match '^COM\d+$') { return $p }
            }
        }
        Start-Sleep -Seconds 3
        Write-Host "  ... waiting for MicroPython serial port"
    }
    return $null
}

function Copy-FirmwareFiles {
    Write-Step "Copying Vintage Radio firmware via mpremote..."
    try {
        Invoke-Mpremote @("exec", "import os`nfor d in ('components','VintageRadio'):`n try: os.mkdir(d)`n except OSError: pass")
    } catch {
        Write-Warning $_
    }
    $pairs = @(
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
    foreach ($pair in $pairs) {
        $local = Join-Path $FirmwareDir $pair[0]
        $remote = $pair[1]
        if (-not (Test-Path $local)) {
            Write-Warning "Skipping missing: $local"
            continue
        }
        Write-Host "  cp $remote"
        Invoke-Mpremote @("cp", $local, ":$remote")
    }
}

# ── Driver repair (Admin) ────────────────────────────────────────────────────
if ($FixDrivers) {
    $isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
        [Security.Principal.WindowsBuiltInRole]::Administrator)
    if (-not $isAdmin) {
        Write-Host "Re-launching as Administrator for driver repair..."
        Start-Process powershell -Verb RunAs -ArgumentList @(
            "-ExecutionPolicy", "Bypass",
            "-File", $MyInvocation.MyCommand.Path,
            "-FixDrivers"
        )
        exit 0
    }
    Write-Step "Removing broken RP2 Boot USB entries (unplug Pico first if this hangs)..."
    Get-PnpDevice -PresentOnly -ErrorAction SilentlyContinue |
        Where-Object { $_.InstanceId -match 'VID_2E8A&PID_0003' } |
        ForEach-Object {
            Write-Host "  removing $($_.FriendlyName) [$($_.InstanceId)]"
            pnputil /remove-device $_.InstanceId 2>&1 | Out-Host
        }
    Write-Host ""
    Write-Host "Unplug the Pico, hold BOOTSEL, plug in while holding BOOTSEL."
    Write-Host "RPI-RP2 should appear in File Explorer within a few seconds."
    exit 0
}

Write-Step "Vintage Radio Pico install (Windows)"
Ensure-ReleaseStaged

# ── Diagnose USB state ───────────────────────────────────────────────────────
$bootsel = Get-Rp2040BootselDevices
$broken = $bootsel | Where-Object { $_.Problem -eq 'CM_PROB_FAILED_INSTALL' }
$rp2 = Get-RpiRp2Drive

if ($broken -and -not $rp2) {
    Write-Host ""
    Write-Host "PROBLEM: Pico is in BOOTSEL but the RPI-RP2 drive did not mount." -ForegroundColor Yellow
    Write-Host "Windows failed to install the mass-storage driver (often after Zadig/picotool)."
    Write-Host ""
    Write-Host "Fix (pick one):"
    Write-Host "  A) Run this script as Admin to reset USB drivers:"
    Write-Host "       powershell -ExecutionPolicy Bypass -File scripts\install_pico_windows.ps1 -FixDrivers"
    Write-Host "  B) Device Manager -> RP2 Boot (warning) -> Uninstall -> replug in BOOTSEL"
    Write-Host "  C) Use Raspberry Pi Imager -> choose MicroPython -> write to Pico"
    Write-Host "     (works even when RPI-RP2 drive is missing)"
    Write-Host ""
    if (-not $SkipMicroPythonFlash) {
        throw "Cannot flash MicroPython until RPI-RP2 is visible or you use Raspberry Pi Imager."
    }
}

# ── Already on MicroPython serial? ───────────────────────────────────────────
if (-not $Port) {
    $Port = Wait-ForMicroPythonPort -TimeoutSec 5
}

if ($Port -and $SkipMicroPythonFlash) {
    Write-Step "Pico already on $Port - skipping MicroPython flash"
} elseif ($Port -and -not $SkipMicroPythonFlash) {
    Write-Step "Found Pico on $Port - testing MicroPython..."
    $probe = & $VenvPython -m mpremote connect $Port exec "print('VR_OK')" 2>&1
    if ($probe -match 'VR_OK') {
        Write-Host "MicroPython is already installed on $Port."
    } else {
        Write-Host "Serial port found but MicroPython not responding - flash MicroPython first."
        $Port = ""
    }
}

# ── Flash MicroPython via RPI-RP2 ───────────────────────────────────────────
if (-not $Port -and -not $SkipMicroPythonFlash) {
    $uf2 = Find-MicroPythonUf2
    if (-not $uf2) {
        Write-Step "Downloading MicroPython UF2..."
        & $VenvPython (Join-Path $RepoRoot "scripts\build_firmware_release.py")
        $uf2 = Find-MicroPythonUf2
    }
    if (-not $uf2) {
        throw "MicroPython UF2 not found. Run: python scripts\build_firmware_release.py"
    }

    if (-not $rp2) {
        Write-Step "Waiting for RPI-RP2 drive (put Pico in BOOTSEL: hold BOOTSEL, plug USB)..."
        $deadline = (Get-Date).AddSeconds(180)
        while ((Get-Date) -lt $deadline) {
            $rp2 = Get-RpiRp2Drive
            if ($rp2) { break }
            Start-Sleep -Seconds 2
            Write-Host "  ... waiting for RPI-RP2"
        }
    }

    if (-not $rp2) {
        throw @"
RPI-RP2 drive never appeared.

Try:
  1. scripts\install_pico_windows.ps1 -FixDrivers   (as Administrator)
  2. Raspberry Pi Imager -> MicroPython -> your Pico
  3. Then re-run this script (MicroPython will be detected on COM)
"@
    }

    $dest = "{0}:\$($uf2.Name)" -f $rp2.DriveLetter
    Write-Step "Flashing MicroPython: $($uf2.Name) -> $dest"
    Copy-Item -LiteralPath $uf2.FullName -Destination $dest -Force
    Write-Host "UF2 copied. Pico rebooting..."
    Start-Sleep -Seconds 12
    $Port = Wait-ForMicroPythonPort -TimeoutSec 90
    if (-not $Port) {
        throw "MicroPython did not appear on USB serial after UF2 flash."
    }
    Write-Host "MicroPython ready on $Port"
}

if (-not $Port) {
    $Port = Wait-ForMicroPythonPort -TimeoutSec 30
}
if (-not $Port) {
    throw "No Pico COM port found. Connect the Pico (not BOOTSEL) and retry with -Port COMx"
}

$Port = $Port.Trim()
Copy-FirmwareFiles
Write-Step "Done. Firmware installed on $Port."
Write-Host "Unplug/replug the Pico or run: $VenvPython -m mpremote connect $Port reset"
