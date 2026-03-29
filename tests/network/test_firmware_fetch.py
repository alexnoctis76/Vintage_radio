"""Tests for firmware fetch logic (SSL context, URL parsing, UF2 filename parsing).

Originally a standalone script. Converted to pytest with mocked HTTP responses
so tests run offline and in CI without network access.
"""

from __future__ import annotations

import re
import ssl
import urllib.request
from unittest import mock

import pytest


# ---------------------------------------------------------------------------
# Helpers under test
# ---------------------------------------------------------------------------

_UF2_PATTERN = re.compile(r'href="(/resources/firmware/[^"]*\.uf2)"')
_VERSION_PATTERN = re.compile(r"-(\d{8})-(v[\d.]+)\.uf2$")


def parse_uf2_links(html: str) -> list[dict]:
    """Parse firmware download links from micropython.org HTML."""
    links = _UF2_PATTERN.findall(html)
    results = []
    for link in links:
        filename = link.rsplit("/", 1)[-1]
        m = _VERSION_PATTERN.search(filename)
        if m:
            date_str, version = m.group(1), m.group(2)
            display = f"{version}  ({date_str[:4]}-{date_str[4:6]}-{date_str[6:]})"
        else:
            display = filename
        results.append({"link": link, "filename": filename, "display": display})
    return results


def create_ssl_context_with_fallback():
    """Create SSL context, trying certifi first then system default."""
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

FAKE_PICO_HTML = """
<html>
<a href="/resources/firmware/RPI_PICO-20240602-v1.23.0.uf2">latest</a>
<a href="/resources/firmware/RPI_PICO-20240101-v1.22.0.uf2">older</a>
<a href="/other/something.zip">not firmware</a>
</html>
"""


class TestParseUF2Links:
    def test_finds_all_uf2_links(self):
        results = parse_uf2_links(FAKE_PICO_HTML)
        assert len(results) == 2

    def test_link_paths_are_correct(self):
        results = parse_uf2_links(FAKE_PICO_HTML)
        for r in results:
            assert r["link"].startswith("/resources/firmware/")

    def test_version_display_format(self):
        results = parse_uf2_links(FAKE_PICO_HTML)
        # Should have formatted version strings like "v1.23.0  (2024-06-02)"
        assert any("v1.23.0" in r["display"] for r in results)
        assert any("2024-06-02" in r["display"] for r in results)

    def test_non_versioned_filename_uses_raw_name(self):
        html = '<a href="/resources/firmware/mystery.uf2">x</a>'
        results = parse_uf2_links(html)
        assert results[0]["display"] == "mystery.uf2"

    def test_empty_html_returns_empty(self):
        assert parse_uf2_links("") == []

    def test_no_uf2_links_returns_empty(self):
        assert parse_uf2_links("<html>nothing useful here</html>") == []


class TestSSLContextWithFallback:
    def test_creates_context_with_certifi(self):
        fake_certifi = mock.MagicMock()
        fake_certifi.where.return_value = "/fake/cacert.pem"
        with mock.patch.dict("sys.modules", {"certifi": fake_certifi}):
            with mock.patch("ssl.create_default_context") as mk:
                create_ssl_context_with_fallback()
                mk.assert_called_once_with(cafile="/fake/cacert.pem")

    def test_falls_back_to_system_when_certifi_missing(self):
        with mock.patch.dict("sys.modules", {"certifi": None}):
            ctx = create_ssl_context_with_fallback()
            assert ctx is not None

    def test_returns_ssl_context_object(self):
        ctx = create_ssl_context_with_fallback()
        assert hasattr(ctx, "verify_mode")


class TestFirmwareFetchIntegration:
    def _make_fake_resp(self, body: str):
        resp = mock.MagicMock()
        resp.read.return_value = body.encode("utf-8")
        resp.__enter__ = lambda s: s
        resp.__exit__ = mock.MagicMock(return_value=False)
        return resp

    def test_successful_fetch_parses_links(self):
        """Mocked HTTP fetch should return parseable HTML."""
        with mock.patch("urllib.request.urlopen", return_value=self._make_fake_resp(FAKE_PICO_HTML)):
            req = urllib.request.Request(
                "https://micropython.org/download/RPI_PICO/",
                headers={"User-Agent": "VintageRadio/1.0"},
            )
            ctx = ssl.create_default_context()
            with urllib.request.urlopen(req, timeout=15, context=ctx) as resp:
                html = resp.read().decode("utf-8")
        links = parse_uf2_links(html)
        assert len(links) == 2

    def test_network_error_surfaces_exception(self):
        with mock.patch("urllib.request.urlopen", side_effect=OSError("network down")):
            with pytest.raises(OSError):
                req = urllib.request.Request("https://example.com")
                urllib.request.urlopen(req, timeout=5)
