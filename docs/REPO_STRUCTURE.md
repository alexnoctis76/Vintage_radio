# Repository Structure and Source Policy

This file defines what belongs in source control and where new code should go.

## Directory Taxonomy

- `gui/`: Desktop UI orchestration and user-facing workflows.
- `gui/services/`: Reusable service logic used by UI modules.
- `gui/widgets/`: Reusable widget classes and dialog components.
- `firmware/`: Device/core playback logic and firmware-side adapters.
- `scripts/`: Operational tooling and one-off automation entrypoints.
- `tests/`: Regression tests by domain (`core`, `gui`, `storage`, `network`).
- `docs/`: Canonical documentation only (overview, packaging, hardware, releases).
- `agent_workshop/`: Temporary harness outputs and ad-hoc test artifacts.

## Source of Truth vs Generated Artifacts

Track in git:

- Python source (`.py`) and tests
- Documentation under `docs/`
- Build specs/scripts (`build/vintage_radio.spec`, `build_macos.sh`)
- Configuration (`pytest.ini`, `pyrightconfig.json`, `.cursor/rules/*`)

Do not track in git:

- Cache and compiled files (`__pycache__`, `.pytest_cache`, `.pyc`)
- Runtime logs (`*.log`)
- Local acceptance artifacts (`agent_workshop/*`, backup bundles/patches)
- Runtime data stores (`data/`, `*.db*`)

## Clean Folder Rules

- Avoid catch-all names (`misc`, `temp`, `new`, `helper2`).
- Keep helpers near their domain owner (UI helper in `gui/`, firmware helper in `firmware/`).
- Prefer adding focused subfolders over growing mega-files.
- If a file starts mixing UI, device transport, and persistence logic, split it.
