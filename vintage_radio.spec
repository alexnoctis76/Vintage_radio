# PyInstaller spec for Vintage Radio Music Manager
# Build: pyinstaller vintage_radio.spec
# Output: dist/Vintage Radio/ (one-folder; run the exe or .app inside)

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

# Application icon (radio icon). Use .ico on Windows for exe icon; .png may work on some versions.
# If Windows build fails on icon, create .ico: python -c "from PIL import Image; Image.open('gui/resources/vintage_radio.png').save('gui/resources/vintage_radio.ico', format='ICO', sizes=[(256,256),(48,48),(32,32),(16,16)])"
icon_path = project_dir / 'gui' / 'resources' / 'vintage_radio.png'
if (project_dir / 'gui' / 'resources' / 'vintage_radio.ico').exists():
    icon_path = project_dir / 'gui' / 'resources' / 'vintage_radio.ico'

a = Analysis(
    ['gui/radio_manager.py'],
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
    icon=str(icon_path) if icon_path.exists() else None,
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
