# PyInstaller spec for mpremote helper (no Qt) - used by packaged macOS app for Setup Pico.
# Build: pyinstaller mpremote_helper.spec
# Output: dist/mpremote_helper (or mpremote_helper.exe on Windows)

import platform
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules

block_cipher = None
project_dir = Path(SPECPATH).parent

# Collect mpremote and deps (no Qt)
try:
    mpremote_datas, mpremote_binaries, mpremote_hidden = collect_all('mpremote')
except Exception:
    mpremote_datas, mpremote_binaries, mpremote_hidden = [], [], []

def _collect_stdlib(pkg):
    try:
        d, b, h = collect_all(pkg)
        return d, b, h
    except Exception:
        return [], [], []
_email_d, _email_b, _email_h = _collect_stdlib('email')
_http_d, _http_b, _http_h = _collect_stdlib('http')

a = Analysis(
    [str(project_dir / 'build' / 'mpremote_helper.py')],
    pathex=[str(project_dir)],
    binaries=mpremote_binaries + _email_b + _http_b,
    datas=mpremote_datas + _email_d + _http_d,
    hiddenimports=[
        'mpremote', 'mpremote.main', 'mpremote.commands', 'mpremote.mip',
        'serial', 'serial.tools.list_ports', 'serial.tools.list_ports_osx',
        'urllib', 'urllib.request', 'email', 'http', 'http.client',
    ] + mpremote_hidden + _email_h + _http_h + collect_submodules('mpremote'),
    hookspath=[],
    excludes=['PyQt6', 'PyQt5', 'PySide6', 'PySide2', 'tkinter'],
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# One-folder mode: no extraction per run = much faster when spawned repeatedly
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='mpremote_helper',
    debug=False,
    strip=(platform.system() == "Darwin"),
    upx=True,
    console=True,
    disable_windowed_traceback=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=(platform.system() == "Darwin"),
    upx=True,
    name='mpremote_helper',
)
