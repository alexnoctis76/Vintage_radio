"""Tests for MicroPython UF2 discovery via production firmware_bundle helpers."""

from __future__ import annotations

from pathlib import Path
from unittest import mock

import pytest

from gui.services import firmware_bundle as fb

FAKE_HTML = """
<html><body>
<a href="/resources/firmware/RPI_PICO-20240602-v1.23.0.uf2">v1.23.0</a>
<a href="/resources/firmware/RPI_PICO-20240101-v1.22.0.uf2">v1.22.0</a>
<a href="/resources/firmware/OTHER_BOARD-20240101-v1.0.0.uf2">other board</a>
<a href="/not-uf2/somefile.zip">not a uf2</a>
</body></html>
"""


class TestListMicroPythonUF2Hrefs:
    def test_finds_only_rpi_pico_links(self):
        links = fb.list_micropython_uf2_hrefs(FAKE_HTML)
        assert len(links) == 2
        assert all("RPI_PICO" in link for link in links)
        assert not any("OTHER_BOARD" in link for link in links)

    def test_empty_html_returns_empty(self):
        assert fb.list_micropython_uf2_hrefs("") == []


class TestFetchMicroPythonUF2:
    def _fake_resp(self, body: str | bytes):
        resp = mock.MagicMock()
        resp.read.return_value = body if isinstance(body, bytes) else body.encode("utf-8")
        resp.__enter__ = lambda s: s
        resp.__exit__ = mock.MagicMock(return_value=False)
        return resp

    def test_fetch_downloads_newest_link(self, tmp_path, monkeypatch):
        cache = tmp_path / "mp"
        cache.mkdir()
        monkeypatch.setattr(fb, "_micropython_cache_dir", lambda: cache)

        calls: list[str] = []

        def urlopen(req, timeout=60):
            url = req.full_url if hasattr(req, "full_url") else str(req)
            calls.append(url)
            if url.endswith("/download/RPI_PICO/"):
                return self._fake_resp(FAKE_HTML)
            return self._fake_resp(b"UF2" + b"\x00" * 2000)

        monkeypatch.setattr(fb.urllib.request, "urlopen", urlopen)
        path = fb.fetch_micropython_uf2(force=True)
        assert path.name == "RPI_PICO-20240602-v1.23.0.uf2"
        assert path.is_file()
        assert path.stat().st_size > 1000

    def test_fetch_raises_when_no_rpi_pico_links(self, tmp_path, monkeypatch):
        cache = tmp_path / "mp"
        cache.mkdir()
        monkeypatch.setattr(fb, "_micropython_cache_dir", lambda: cache)
        monkeypatch.setattr(
            fb.urllib.request,
            "urlopen",
            lambda *a, **k: self._fake_resp("<html>no firmware</html>"),
        )
        with pytest.raises(RuntimeError, match="No RPI_PICO"):
            fb.fetch_micropython_uf2(force=True)
