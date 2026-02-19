# PyInstaller spec for Vintage Radio Music Manager
# Build: pyinstaller vintage_radio.spec   (or pyinstaller --noconfirm vintage_radio.spec to skip prompt)
#
# Platform-specific output:
#   Windows: dist/Vintage Radio/Vintage Radio.exe  (one-folder)
#   macOS:   dist/Vintage Radio.app                (.app bundle)
#   Linux:   dist/Vintage Radio/Vintage Radio      (one-folder)
#
# Note: Close any running Vintage Radio app before rebuilding, or you may get "Access is denied" when PyInstaller cleans the output dir.
# The SyntaxWarnings during build come from the pydub dependency; they are harmless and the build still succeeds.
# If the exe icon looks wrong in Explorer (e.g. small icons), try renaming the exe so Windows refreshes its icon cache.

import sys
import platform
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

block_cipher = None

# Project root (directory containing this spec)
project_dir = Path(SPECPATH)

# Data files: gui/resources, and firmware files for Export (main.py, radio_core.py, components)
gui_resources = project_dir / 'gui' / 'resources'
datas = [
    (str(gui_resources), 'gui/resources'),
    (str(project_dir / 'main.py'), '.'),
    (str(project_dir / 'radio_core.py'), '.'),
    (str(project_dir / 'components'), 'components'),
]

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
entitlements_file = str(project_dir / 'macos_entitlements.plist') if (project_dir / 'macos_entitlements.plist').exists() else None

a = Analysis(
    ['run_vintage_radio.py'],
    pathex=[str(project_dir)],
    binaries=[],
    datas=datas,
    hiddenimports=[
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
        'mpremote',
        'mpremote.commands',
        'mpremote.main',
        'platformdirs',
    ] + collect_submodules('mpremote'),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
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
    upx_exclude=[],
    name='Vintage Radio',
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
            'LSMinimumSystemVersion': '10.13',
        },
    )
