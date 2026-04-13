# AGENTS.md

## Cursor Cloud specific instructions

### Project overview

Vintage Radio Music Manager is a PyQt6 desktop GUI application for managing music on a 3D-printed vintage AM radio device. It uses an embedded SQLite database (`radio_manager.db`) and has no external services or backend servers. See `README.md` for full details.

### Running the application

The app requires a display server. On headless Linux (Cloud Agent VMs), use Xvfb:

```bash
Xvfb :99 -screen 0 1280x1024x24 &
export DISPLAY=:99
source /workspace/.venv/bin/activate
python -m gui.radio_manager
```

Or for a one-off run: `xvfb-run -a python -m gui.radio_manager`

### Key caveats

- **ALSA warnings are expected** on headless VMs (no sound hardware). They do not affect functionality.
- **VLC and FFmpeg** are installed system-wide for audio format conversion. Without them, only MP3 files can be synced to SD.
- The database file `radio_manager.db` is created automatically on first run in the app data directory (see `gui/resource_paths.py` for path resolution).
- There are no automated test suites in this repo. Testing is done via the Emulator tab in the GUI.
- The entry point is `python -m gui.radio_manager` (or `python gui/radio_manager.py`).

### Lint / Build

- No linter or formatter is configured in the repo.
- For standalone builds: `pip install pyinstaller && pyinstaller vintage_radio.spec` (see `README.md` "Building standalone executables").
