"""Network-marked integration smoke for fetch_micropython_uf2 (opt-in)."""

from __future__ import annotations

import pytest

from gui.services.firmware_bundle import list_micropython_uf2_hrefs


@pytest.mark.network
def test_micropython_download_page_lists_rpi_pico_uf2():
    import urllib.request

    req = urllib.request.Request(
        "https://micropython.org/download/RPI_PICO/",
        headers={"User-Agent": "VintageRadio/1.0"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        html = resp.read().decode("utf-8", errors="replace")
    links = list_micropython_uf2_hrefs(html)
    assert links
    assert all("/resources/firmware/RPI_PICO" in link for link in links)
