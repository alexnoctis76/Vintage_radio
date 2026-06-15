# PyInstaller spec for Vintage Radio Music Manager
# Build: pyinstaller vintage_radio.spec   (or pyinstaller --noconfirm vintage_radio.spec to skip prompt)
#
# Platform-specific output:
#   Windows: dist/Vintage Radio/Vintage Radio.exe  (one-folder)
#   macOS:   dist/Vintage Radio.app                (.app bundle)
#   Linux:   dist/Vintage Radio/Vintage Radio      (one-folder)
#
# Windows: COLLECT writes to dist/_pyi_staging first, then promote to dist/Vintage Radio (avoids cleaning a locked folder).
# macOS/Linux: unchanged. You can still close the running app if promotion (copy) hits locks.
# The SyntaxWarnings during build come from the pydub dependency; they are harmless and the build still succeeds.
# If the exe icon looks wrong in Explorer (e.g. small icons), try renaming the exe so Windows refreshes its icon cache.

import sys
import platform
import subprocess
import time
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules, collect_all

block_cipher = None

# Project root (parent of build/ which contains this spec)
project_dir = Path(SPECPATH).parent


# Windows: try to stop running instances; COLLECT uses staging (see CONF['distpath'] below).
if platform.system() == "Windows":
    _kill_helper = project_dir / "build" / "kill_vintage_radio_build_locks.py"
    if _kill_helper.is_file():
        try:
            subprocess.run(
                [sys.executable, str(_kill_helper)],
                cwd=str(project_dir),
                timeout=120,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            pass
    else:
        for _ in range(5):
            try:
                subprocess.run(
                    ["taskkill", "/IM", "Vintage Radio.exe", "/F", "/T"],
                    capture_output=True,
                    timeout=45,
                )
            except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
                pass
            time.sleep(0.6)

    # COLLECT reads PyInstaller CONF['distpath'], not the spec DISTPATH variable.
    from PyInstaller.config import CONF

    _win_staging = (project_dir / "dist" / "_pyi_staging").resolve()
    _win_staging.mkdir(parents=True, exist_ok=True)
    CONF["distpath"] = str(_win_staging)

# Data files: gui/resources, firmware files, and mpremote (for bundled Pico flashing)
gui_resources = project_dir / 'gui' / 'resources'
datas = [
    (str(gui_resources), 'gui/resources'),
    # Mirror source tree so project_root() / "firmware/..." works when frozen.
    (str(project_dir / 'firmware' / 'pico' / 'main.py'), 'firmware/pico'),
    (str(project_dir / 'firmware' / 'pico' / 'main_basic.py'), 'firmware/pico'),
    (str(project_dir / 'firmware' / 'radio_core.py'), 'firmware'),
    (str(project_dir / 'firmware' / 'pico' / 'dfplayer_hardware.py'), 'firmware/pico'),
    (str(project_dir / 'firmware' / 'pico' / 'sdcard.py'), 'firmware/pico'),
    (str(project_dir / 'firmware' / 'custom_driver_template.py'), 'firmware'),
    (str(project_dir / 'firmware' / 'pin_config_loader.py'), 'firmware'),
    (str(project_dir / 'docs' / 'CUSTOM_DRIVER.md'), 'docs'),
]
_release_cfg = project_dir / 'release_config.json'
if _release_cfg.is_file():
    datas.append((str(_release_cfg), '.'))
# main_basic.py / main.py import these from components/; without them mpremote install silently skipped
# missing sources (see radio_manager._install_to_pico_worker) and firmware dies at ImportError.
_pico_components = project_dir / 'firmware' / 'pico' / 'components'
for _fn in ('am_wav_loader.py', 'vintage_radio_ipc.py'):
    _comp = _pico_components / _fn
    if _comp.exists():
        datas.append((str(_comp), 'firmware/pico/components'))
_vs1053 = project_dir / 'firmware' / 'pico' / 'vs1053_hardware.py'
if _vs1053.exists():
    datas.append((str(_vs1053), 'firmware/pico'))
# Bundle mpremote fully (modules + any data files)
try:
    mpremote_datas, mpremote_binaries, mpremote_hidden = collect_all('mpremote')
    datas += mpremote_datas
except Exception:
    mpremote_datas = []
    mpremote_binaries = []
    mpremote_hidden = []

# Bundle imageio-ffmpeg so ffmpeg executable is available in packaged app.
# collect_all puts the static ffmpeg binary under imageio_ffmpeg/binaries/ in datas.
# A runtime hook (pyi_rthook_fix_ffmpeg.py) sets the executable bit at launch.
ffmpeg_hidden = []
try:
    ffmpeg_datas, ffmpeg_binaries, ffmpeg_hidden = collect_all('imageio_ffmpeg')
    datas += ffmpeg_datas
    mpremote_binaries += ffmpeg_binaries
except Exception:
    pass

# certifi: hiddenimport alone does not ship cacert.pem — HTTPS (GitHub updater) fails on macOS frozen builds.
try:
    _certifi_datas, _certifi_bins, _certifi_ch = collect_all('certifi')
    datas += _certifi_datas
    mpremote_binaries += _certifi_bins
    mpremote_hidden += _certifi_ch
except Exception:
    pass

# pyfatfs: SD image export feature. fs (pyfilesystem2) dependency uses pkg_resources
# which setuptools 82+ removed; a runtime hook provides the stub.
try:
    _pyfatfs_datas, _pyfatfs_bins, _pyfatfs_hidden = collect_all('pyfatfs')
    datas += _pyfatfs_datas
    mpremote_binaries += _pyfatfs_bins
    mpremote_hidden += _pyfatfs_hidden
    _fs_datas, _fs_bins, _fs_hidden = collect_all('fs')
    datas += _fs_datas
    mpremote_binaries += _fs_bins
    mpremote_hidden += _fs_hidden
except Exception:
    pass

# Force-include stdlib packages needed by mpremote.mip (urllib -> email, http)
def _collect_stdlib(pkg):
    try:
        d, b, h = collect_all(pkg)
        return d, b, h
    except Exception:
        return [], [], []
_email_d, _email_b, _email_h = _collect_stdlib('email')
_http_d, _http_b, _http_h = _collect_stdlib('http')
datas += _email_d + _http_d
mpremote_binaries += _email_b + _http_b
mpremote_hidden += _email_h + _http_h

# Application icon
# Windows: .ico    macOS: .icns (fall back to .png)    Linux: .png
icon_ico = project_dir / 'gui' / 'resources' / 'vintage_radio.ico'
icon_icns = project_dir / 'gui' / 'resources' / 'vintage_radio.icns'
icon_png = project_dir / 'gui' / 'resources' / 'vintage_radio.png'
icon_path = None

if platform.system() == "Windows":
    icon_path = str(icon_ico) if icon_ico.exists() else None
elif platform.system() == "Darwin":
    if icon_icns.exists():
        icon_path = str(icon_icns)
    elif icon_png.exists():
        icon_path = str(icon_png)
else:
    icon_path = str(icon_png) if icon_png.exists() else None

# macOS entitlements (for code signing)
entitlements_file = str(project_dir / 'build' / 'macos_entitlements.plist') if (project_dir / 'build' / 'macos_entitlements.plist').exists() else None

a = Analysis(
    # Absolute path: PyInstaller resolves scripts relative to the spec dir (build/).
    [str(project_dir / 'run_vintage_radio.py')],
    pathex=[str(project_dir)],
    binaries=mpremote_binaries,
    datas=datas,
    hiddenimports=[
        'project_version',
        'PyQt6.QtCore',
        'PyQt6.QtGui',
        'PyQt6.QtWidgets',
        'mutagen',
        'mutagen.mp3',
        'mutagen.flac',
        'mutagen.id3',
        'pygame',
        'psutil',
        'pydub',
        'imageio_ffmpeg',
        'mpremote',
        'mpremote.commands',
        'mpremote.main',
        'mpremote.mip',
        'serial',
        'serial.tools.list_ports',
        'serial.tools.list_ports_osx',
        'platformdirs',
        'importlib_metadata',
        'certifi',
        'pyfatfs',
        'pyfatfs.PyFatFS',
        'fs',
        'fs.base',
        'fs.errors',
        'fs.info',
        'fs.path',
        # urllib.request and its full dependency chain (required by mpremote.mip)
        'urllib',
        'urllib.request',
        'urllib.error',
        'urllib.parse',
        'email',
        'email.utils',
        'email.header',
        'email.parser',
        'email.errors',
        'http',
        'http.client',
        'http.server',
        'ssl',
    ] + mpremote_hidden + ffmpeg_hidden + collect_submodules('mpremote'),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[
        str(project_dir / 'build' / 'pyi_rthook_pkg_resources_stub.py'),
        str(project_dir / 'build' / 'pyi_rthook_fix_ffmpeg.py'),
    ],
    excludes=[],  # Do not exclude stdlib - mpremote/urllib need email, http, etc.
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='Vintage Radio',
    debug=False,
    bootloader_ignore_signals=False,
    # Stripping macOS onedir payloads can break bundled Mach-O (imageio-ffmpeg).
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=entitlements_file if platform.system() == "Darwin" else None,
    icon=icon_path,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[
        "ffmpeg-macos-aarch64-v7.1",
        "ffmpeg-macos-x86_64-v7.1",
        "ffmpeg-linux-aarch64-v7.0.2",
        "ffmpeg-linux-x86_64-v7.0.2",
        "ffmpeg-win-x86_64-v7.1.exe",
        "ffmpeg-win32-v4.2.2.exe",
    ],
    name='Vintage Radio',
)

if platform.system() == "Windows":
    _promote = project_dir / "build" / "pyi_windows_promote_dist.py"
    if _promote.is_file():
        subprocess.run(
            [sys.executable, str(_promote), str(project_dir)],
            cwd=str(project_dir),
            timeout=900,
        )

# macOS: wrap the COLLECT folder into a proper .app bundle
if platform.system() == "Darwin":
    app = BUNDLE(
        coll,
        name='Vintage Radio.app',
        icon=icon_path,
        bundle_identifier='com.zionbrock.vintage-radio',
        info_plist={
            'CFBundleDisplayName': 'Vintage Radio',
            'CFBundleShortVersionString': '1.0.0',
            'NSHighResolutionCapable': True,
            'LSMinimumSystemVersion': '15.0',
        },
    )
