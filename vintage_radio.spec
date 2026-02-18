# PyInstaller spec for Vintage Radio Music Manager
# Build: pyinstaller vintage_radio.spec   (or pyinstaller --noconfirm vintage_radio.spec to skip prompt)
# Output: dist/Vintage Radio/ (one-folder; run the exe or .app inside)
# Note: Close any running Vintage Radio app before rebuilding, or you may get "Access is denied" when PyInstaller cleans the output dir.
# The SyntaxWarnings during build come from the pydub dependency; they are harmless and the build still succeeds.
# If the exe icon looks wrong in Explorer (e.g. small icons), try renaming the exe so Windows refreshes its icon cache.

import sys
from pathlib import Path

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
# Windows: .ico  (created by workflow or manually with Pillow)
# macOS:   .icns (created by workflow using sips + iconutil)
icon_ico = project_dir / 'gui' / 'resources' / 'vintage_radio.ico'
icon_icns = project_dir / 'gui' / 'resources' / 'vintage_radio.icns'

if sys.platform == 'darwin' and icon_icns.exists():
    icon_path = str(icon_icns)
elif icon_ico.exists():
    icon_path = str(icon_ico)
else:
    icon_path = None

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
        'mpremote.pyboard',
        'mpremote.commands',
    ],
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
    strip=True if sys.platform == 'darwin' else False,  # Strip symbols on macOS to reduce size
    upx=True,
    console=True if sys.platform == 'darwin' else False,  # Enable console on macOS to see crash errors
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=icon_path,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=True if sys.platform == 'darwin' else False,  # Strip symbols on macOS to reduce size
    upx=True,
    upx_exclude=[],
    name='Vintage Radio',
)

# macOS: create a .app bundle so the app integrates properly with Finder/Dock
if sys.platform == 'darwin':
    app = BUNDLE(
        coll,
        name='Vintage Radio.app',
        icon=icon_path,
        bundle_identifier='com.vintageradio.musicmanager',
        info_plist={
            'CFBundleShortVersionString': '0.1.0',
            'NSHighResolutionCapable': True,
            'LSMinimumSystemVersion': '11.0',  # Support macOS 11+ (Big Sur)
        },
    )
