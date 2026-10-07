"""Each fingerprint sync scenario matches one dialog choice.

Apply-all on a hash mismatch must not answer a later conversion failure, and
Ignore on a conversion failure must not answer later hash mismatches.
"""

from __future__ import annotations

import pytest

from gui.mcp_fingerprint_sync_test import (
    FINGERPRINT_SCENARIOS,
    resolve_fingerprint_scenario,
    run_fingerprint_sync_test,
)


def test_legacy_on_mismatch_maps_onto_scenarios():
    assert resolve_fingerprint_scenario("", "accept_file") == "update"
    assert resolve_fingerprint_scenario("sync", "accept_all") == "update_remaining"
    assert resolve_fingerprint_scenario("", "skip") == "skip"
    assert resolve_fingerprint_scenario("", "skip_all") == "skip_remaining"
    assert resolve_fingerprint_scenario("", "stop") == "abort"
    assert resolve_fingerprint_scenario("conversion_ignore", "accept_file") == (
        "conversion_ignore"
    )


@pytest.mark.parametrize("scenario", list(FINGERPRINT_SCENARIOS))
def test_fingerprint_scenario(scenario, tmp_path, monkeypatch):
    monkeypatch.setenv("VINTAGE_RADIO_DATA_DIR", str(tmp_path))
    report = run_fingerprint_sync_test(
        scenario=scenario,
        switch_library=False,
        sd_root=tmp_path / "sd",
    )
    assert report.get("ok"), report
