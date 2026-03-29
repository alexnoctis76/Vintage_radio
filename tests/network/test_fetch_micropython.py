"""Tests for MicroPython UF2 link fetching with SSL fallback logic.

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
# Core functions extracted from the original script (under test)
# ---------------------------------------------------------------------------

def fetch_with_fallback(url: str) -> str:
    """Try default, then certifi, then unverified SSL to fetch a URL."""
    req = urllib.request.Request(url, headers={"User-Agent": "VintageRadio/1.0"})
    # 1) default
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.read().decode("utf-8")
    except Exception:
        pass
    # 2) certifi if available
    try:
        import certifi
        ctx = ssl.create_default_context(cafile=certifi.where())
        with urllib.request.urlopen(req, timeout=15, context=ctx) as resp:
            return resp.read().decode("utf-8")
    except Exception:
        pass
    # 3) unverified (last resort)
    ctx2 = ssl.create_default_context()
    ctx2.check_hostname = False
    ctx2.verify_mode = ssl.CERT_NONE
    with urllib.request.urlopen(req, timeout=15, context=ctx2) as resp:
        return resp.read().decode("utf-8")


def find_uf2_links(html: str) -> list:
    return re.findall(r'href="(/resources/firmware/[^"]*\.uf2)"', html)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

FAKE_HTML = """
<html><body>
<a href="/resources/firmware/RPI_PICO-20240602-v1.23.0.uf2">v1.23.0</a>
<a href="/resources/firmware/RPI_PICO-20240101-v1.22.0.uf2">v1.22.0</a>
<a href="/not-uf2/somefile.zip">not a uf2</a>
</body></html>
"""


class TestFindUF2Links:
    def test_finds_uf2_href_links(self):
        links = find_uf2_links(FAKE_HTML)
        assert len(links) == 2

    def test_link_paths_start_with_resources_firmware(self):
        links = find_uf2_links(FAKE_HTML)
        for link in links:
            assert link.startswith("/resources/firmware/")

    def test_non_uf2_not_included(self):
        links = find_uf2_links(FAKE_HTML)
        assert not any(".zip" in link for link in links)

    def test_empty_html_returns_empty(self):
        assert find_uf2_links("") == []

    def test_html_with_no_uf2_links_returns_empty(self):
        assert find_uf2_links("<html><body>nothing here</body></html>") == []


class TestFetchWithFallback:
    def _fake_response(self, content: str):
        resp = mock.MagicMock()
        resp.read.return_value = content.encode("utf-8")
        resp.__enter__ = lambda s: s
        resp.__exit__ = mock.MagicMock(return_value=False)
        return resp

    def test_default_fetch_succeeds(self):
        with mock.patch("urllib.request.urlopen", return_value=self._fake_response(FAKE_HTML)):
            result = fetch_with_fallback("https://example.com")
        assert "uf2" in result

    def test_fallback_path_works_when_default_fails(self):
        """If default SSL fails, a later fallback attempt should succeed."""
        call_count = [0]

        def side_effect(req, **kwargs):
            call_count[0] += 1
            if call_count[0] < 2:
                raise ssl.SSLError("cert verify failed")
            return self._fake_response(FAKE_HTML)

        with mock.patch("urllib.request.urlopen", side_effect=side_effect):
            with mock.patch.dict("sys.modules", {"certifi": mock.MagicMock(where=lambda: "/fake/cert")}):
                result = fetch_with_fallback("https://example.com")
        assert "uf2" in result

    def test_raises_when_all_fetches_fail(self):
        with mock.patch("urllib.request.urlopen", side_effect=Exception("connection refused")):
            with pytest.raises(Exception):
                fetch_with_fallback("https://example.com")


class TestSSLContextCreation:
    def test_ssl_context_can_be_created(self):
        """Verify that a default SSL context is creatable in this environment."""
        ctx = ssl.create_default_context()
        assert ctx is not None

    def test_unverified_context_can_be_created(self):
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        assert ctx.verify_mode == ssl.CERT_NONE
