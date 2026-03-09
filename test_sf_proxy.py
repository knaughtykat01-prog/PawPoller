#!/usr/bin/env python3
"""SoFurry proxy + API exploration script.

Run directly on the GCP VM (no Docker needed):
    cd ~/PawPoller
    python3 test_sf_proxy.py

Reads credentials from .env or environment variables:
    SF_USERNAME, SF_PASSWORD, SF_DISPLAY_NAME, CF_WORKER_URL, CF_WORKER_KEY
"""

import asyncio
import json
import os
import re
import sys

try:
    import httpx
except ImportError:
    print("ERROR: httpx not installed. Run: pip3 install --break-system-packages httpx")
    sys.exit(1)

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

SF_USER = os.environ.get("SF_USERNAME", "")
SF_PASS = os.environ.get("SF_PASSWORD", "")
SF_DISPLAY = os.environ.get("SF_DISPLAY_NAME", "")
CF_URL = os.environ.get("CF_WORKER_URL", "")
CF_KEY = os.environ.get("CF_WORKER_KEY", "")

SOFURRY = "https://sofurry.com"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"


async def proxy_get(client, url, extra_headers=None):
    """GET a URL through the CF Worker proxy."""
    headers = {
        "x-proxy-key": CF_KEY,
        "x-target-url": url,
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    if extra_headers:
        headers.update(extra_headers)
    return await client.get(CF_URL, headers=headers)


async def proxy_login_and_get(client, then_url):
    """Full login sequence + fetch a URL, all in one Worker invocation."""
    login_data = {
        "url": f"{SOFURRY}/login",
        "email": SF_USER,
        "password": SF_PASS,
        "then": then_url,
    }
    return await client.get(CF_URL, headers={
        "x-proxy-key": CF_KEY,
        "x-proxy-login": json.dumps(login_data),
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    })


def section(title):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


async def main():
    print("SoFurry Exploration Script")
    print(f"  SF User:    {SF_USER}")
    print(f"  SF Display: {SF_DISPLAY}")
    print(f"  CF Worker:  {CF_URL}")

    if not all([SF_USER, SF_PASS, SF_DISPLAY, CF_URL, CF_KEY]):
        print("\nERROR: Missing required env vars.")
        sys.exit(1)

    async with httpx.AsyncClient(timeout=30, follow_redirects=False) as c:

        # ── PART 1: Analyze gallery page structure ──────────────
        section("PART 1: Gallery page structure analysis")

        resp = await proxy_get(c, f"{SOFURRY}/u/{SF_DISPLAY}/gallery")
        html = resp.text
        print(f"  Page size: {len(html)} chars")

        # Check for Turbo Frames (lazy-loaded content)
        frames = re.findall(r'<turbo-frame[^>]*>', html)
        if frames:
            print(f"\n  TURBO FRAMES FOUND ({len(frames)}):")
            for f in frames:
                print(f"    {f}")
        else:
            print("\n  No <turbo-frame> tags found")

        # Check for data-turbo-frame attributes
        turbo_attrs = re.findall(r'data-turbo-frame="([^"]*)"', html)
        if turbo_attrs:
            print(f"\n  data-turbo-frame attributes: {turbo_attrs}")

        # Check for any AJAX/fetch patterns in inline scripts
        print("\n  Inline scripts mentioning fetch/ajax/load/turbo:")
        for m in re.finditer(r'<script[^>]*>(.*?)</script>', html, re.DOTALL):
            script = m.group(1)
            if any(kw in script.lower() for kw in ['fetch(', 'ajax', 'xmlhttp', 'turbo', 'gallery', 'submission', 'browse']):
                print(f"    {script[:200].strip()}")

        # Check for external JS files
        js_files = re.findall(r'<script[^>]*src="([^"]*)"[^>]*>', html)
        print(f"\n  External JS files ({len(js_files)}):")
        for f in js_files[:10]:
            print(f"    {f}")

        # Look for the main content area
        print("\n  Looking for content/gallery area...")
        # Find the section between gallery link and footer
        content_patterns = [
            r'class="[^"]*gallery[^"]*"',
            r'class="[^"]*submissions?[^"]*"',
            r'class="[^"]*artworks?[^"]*"',
            r'class="[^"]*grid[^"]*"',
            r'class="[^"]*content[^"]*"',
            r'id="[^"]*gallery[^"]*"',
            r'id="[^"]*content[^"]*"',
            r'data-controller="[^"]*gallery[^"]*"',
            r'data-controller="[^"]*browse[^"]*"',
        ]
        for pat in content_patterns:
            matches = re.findall(pat, html, re.IGNORECASE)
            if matches:
                print(f"    Found: {matches}")

        # Dump the middle section of the page (where content would be)
        mid = len(html) // 2
        print(f"\n  Middle of page (chars {mid-500} to {mid+500}):")
        print(html[mid-500:mid+500])

        # ── PART 2: Try API endpoints ──────────────────────────
        section("PART 2: API endpoint exploration")

        api_endpoints = [
            # JSON API patterns
            (f"{SOFURRY}/ui/user/{SF_DISPLAY}", "application/json"),
            (f"{SOFURRY}/ui/browse?by={SF_DISPLAY}", "application/json"),
            (f"{SOFURRY}/ui/browse?user={SF_DISPLAY}", "application/json"),
            (f"{SOFURRY}/ui/gallery/{SF_DISPLAY}", "application/json"),
            (f"{SOFURRY}/api/browse?by={SF_DISPLAY}", "application/json"),
            # Gallery with JSON accept
            (f"{SOFURRY}/u/{SF_DISPLAY}/gallery", "application/json"),
            # Turbo stream format
            (f"{SOFURRY}/u/{SF_DISPLAY}/gallery", "text/vnd.turbo-stream.html"),
            # Old API
            ("https://api2.sofurry.com/browse/all?by={}&count=30".format(SF_DISPLAY), "application/json"),
            # Other possible patterns
            (f"{SOFURRY}/browse?by={SF_DISPLAY}", None),
            (f"{SOFURRY}/browse/user/{SF_DISPLAY}", None),
            (f"{SOFURRY}/browse?filter=user:{SF_DISPLAY}", None),
        ]

        for url, accept in api_endpoints:
            try:
                extra = {}
                if accept:
                    extra["Accept"] = accept
                resp = await proxy_get(c, url, extra)
                body = resp.text[:300]
                content_type = resp.headers.get("content-type", "")

                # Check if it looks like JSON
                is_json = False
                try:
                    data = resp.json()
                    is_json = True
                except Exception:
                    pass

                # Check if it has submission links
                has_subs = bool(re.search(r'/s/[A-Za-z0-9]', body))

                status_icon = "✓" if resp.status_code == 200 else "✗"
                detail = ""
                if is_json:
                    detail = f" [JSON: {list(data.keys()) if isinstance(data, dict) else f'array[{len(data)}]'}]"
                elif has_subs:
                    detail = " [HAS /s/ LINKS!]"

                print(f"  {status_icon} {resp.status_code} {url}")
                if accept:
                    print(f"         Accept: {accept}")
                print(f"         Type: {content_type} | Size: {len(resp.text)}{detail}")
                if is_json:
                    print(f"         Data: {resp.text[:300]}")
                elif has_subs:
                    print(f"         Content: {body}")
                elif resp.status_code == 200 and len(resp.text) < 5000:
                    print(f"         Content: {body}")

            except Exception as e:
                print(f"  ✗ ERROR {url}: {e}")

        # ── PART 3: Login then try API endpoints ───────────────
        section("PART 3: Authenticated API exploration")
        print("  (Login + fetch in one Worker invocation)")

        auth_endpoints = [
            f"{SOFURRY}/u/{SF_DISPLAY}/gallery",
            f"{SOFURRY}/u/{SF_DISPLAY}",
            f"{SOFURRY}/",  # Homepage after login
        ]

        for url in auth_endpoints:
            try:
                resp = await proxy_login_and_get(c, url)
                html = resp.text
                final = resp.headers.get("x-final-url", "")
                s_links = re.findall(r'/s/([A-Za-z0-9]+)', html)

                print(f"\n  URL: {url}")
                print(f"  Final: {final}")
                print(f"  Size: {len(html)} | /s/ links: {len(s_links)}")
                if s_links:
                    print(f"  SUBMISSIONS FOUND: {s_links[:10]}")

                # Check for auth indicators
                has_logout = bool(re.search(r'logout|sign.?out', html, re.IGNORECASE))
                has_login = bool(re.search(r'href="[^"]*login"', html))
                has_account = bool(re.search(r'href="[^"]*account|href="[^"]*settings|href="[^"]*profile/edit', html, re.IGNORECASE))
                print(f"  Auth: logout={has_logout}, login_link={has_login}, account={has_account}")

                # Check for username in nav/header
                username_in_nav = bool(re.search(rf'>{re.escape(SF_DISPLAY)}<', html))
                print(f"  Username in HTML: {username_in_nav}")

                # Dump page structure for homepage (shows if auth worked)
                if url.endswith("/"):
                    print(f"  First 1000 chars:")
                    print(html[:1000])

            except Exception as e:
                print(f"  ERROR {url}: {e}")

        # ── PART 4: Check if SF_USERNAME is email ──────────────
        section("PART 4: Credential check")
        print(f"  SF_USERNAME value: {SF_USER}")
        if "@" in SF_USER:
            print(f"  Looks like an email ✓")
        else:
            print(f"  WARNING: Does NOT look like an email!")
            print(f"  SoFurry login form expects 'email', not username.")
            print(f"  If this is your display name, login will fail silently.")
            print(f"  Set SF_USERNAME to your SoFurry email address.")

    print(f"\n{'='*60}")
    print(f"  EXPLORATION COMPLETE")
    print(f"{'='*60}")


if __name__ == "__main__":
    asyncio.run(main())
