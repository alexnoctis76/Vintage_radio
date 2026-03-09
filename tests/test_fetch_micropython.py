#!/usr/bin/env python3
"""Test fetching MicroPython UF2 links with SSL fallbacks (certifi or unverified)"""
import urllib.request
import ssl
import re

try:
    import certifi
except Exception:
    certifi = None


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "VintageRadio/1.0"})
    # 1) default
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.read().decode('utf-8')
    except Exception as e:
        print('Default fetch failed:', type(e).__name__, e)
    # 2) certifi if available
    if certifi:
        try:
            ctx = ssl.create_default_context(cafile=certifi.where())
            with urllib.request.urlopen(req, timeout=15, context=ctx) as resp:
                return resp.read().decode('utf-8')
        except Exception as e:
            print('Certifi fetch failed:', type(e).__name__, e)
    # 3) unverified (last resort)
    try:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        with urllib.request.urlopen(req, timeout=15, context=ctx) as resp:
            return resp.read().decode('utf-8')
    except Exception as e:
        print('Unverified fetch failed:', type(e).__name__, e)
    raise RuntimeError('All fetch attempts failed')


def find_uf2_links(html):
    return re.findall(r'href="(/resources/firmware/[^"]*\.uf2)"', html)


def main():
    urls = [
        'https://micropython.org/download/RPI_PICO/',
        'https://micropython.org/download/RPI_PICO_W/',
    ]
    for url in urls:
        print('\n===', url)
        try:
            html = fetch(url)
            links = find_uf2_links(html)
            print('Found', len(links), 'uf2 links')
            for l in links[:5]:
                print(' ', 'https://micropython.org' + l)
        except Exception as e:
            print('ERROR:', type(e).__name__, e)

if __name__ == '__main__':
    main()

