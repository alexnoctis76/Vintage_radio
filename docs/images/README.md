# README screenshots

Current README images live in **`readme/`** (captured from the v1.1 sidebar UI):

| File | Page |
|------|------|
| `readme/01-load-music.png` | Load Music — library bar, storage, stations, tracks, sync |
| `readme/02-install-firmware.png` | Install Firmware |
| `readme/03-tools.png` | Tools — device console |
| `readme/04-settings.png` | Settings |
| `readme/05-help.png` | Help |
| `readme/06-commercials.png` | Load Music — Conductor commercials + link-to-track |

Regenerate after UI changes:

```bash
python scripts/capture_readme_screenshots.py
python scripts/capture_readme_screenshots.py --commercials-only
```

Legacy filenames (`library.png`, `emulator-*.png`, etc.) referred to an older tabbed UI and are no longer used by the root README.
