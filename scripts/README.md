# Scripts Directory

Operational scripts live here so ad-hoc tooling does not leak into core modules.

## Current entrypoints

- `physical_device_full_check.py` - host + device health checks for a connected Pico.
- `vintage_radio_debug_mcp_bridge.py` - bridge helper for MCP debug transport.
- `hardware_playback_matrix.py` - targeted playback matrix diagnostics.

## Rules

- Keep scripts task-oriented and runnable from repo root.
- Prefer read-only diagnostics unless the script name clearly indicates mutation.
- Keep temporary experiment scripts in `agent_workshop/`, not in this folder.
