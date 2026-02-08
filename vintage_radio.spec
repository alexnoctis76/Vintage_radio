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

# Application icon (radio icon). Windows exe requires .ico; pass only .ico to avoid build failure without Pillow.
# To create .ico: pip install Pillow && python -c "from PIL import Image; Image.open('gui/resources/vintage_radio.png').save('gui/resources/vintage_radio.ico', format='ICO', sizes=[(256,256),(48,48),(32,32),(16,16)])"
icon_ico = project_dir / 'gui' / 'resources' / 'vintage_radio.ico'
icon_path = str(icon_ico) if icon_ico.exists() else None

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
    strip=False,
    upx=True,
    console=False,
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
    strip=False,
    upx=True,
    upx_exclude=[],
    name='Vintage Radio',
)
