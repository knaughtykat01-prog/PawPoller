#!/usr/bin/env python3
"""Standalone SoFurry proxy test script.

Run directly on the GCP VM (no Docker needed):
    cd ~/PawPoller
    pip install httpx python-dotenv
    python test_sf_proxy.py

Reads credentials from .env or environment variables:
    SF_USERNAME, SF_PASSWORD, SF_DISPLAY_NAME, CF_WORKER_URL, CF_WORKER_KEY

Tests multiple approaches to find what works for authenticated gallery access
through the Cloudflare Worker proxy.
"""

import asyncio
import json
import os
import re
import sys

try:
    import httpx
except ImportError:
    print("ERROR: httpx not installed. Run: pip install httpx")
    sys.exit(1)

# Try loading .env
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
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"


def check_gallery_html(html: str, label: str):
    """Analyze gallery HTML and print diagnostics."""
    ids = re.findall(r'href="(?:https://sofurry\.com)?/s/([A-Za-z0-9]+)', html)
    has_logout = "logout" in html.lower()
    has_login = 'href="/login"' in html or "href='/login'" in html
    sfw_match = re.search(r'(?i)(sfw|nsfw)[^<]{0,80}', html)
    sfw_ctx = sfw_match.group(0)[:60] if sfw_match else "not found"

    print(f"\n{'='*60}")
    print(f"  {label}")
    print(f"{'='*60}")
    print(f"  HTML length:    {len(html)} chars")
    print(f"  Submissions:    {len(ids)} found")
    if ids:
        print(f"  IDs:            {ids[:5]}{'...' if len(ids) > 5 else ''}")
    print(f"  Has logout:     {has_logout} (= authenticated)")
    print(f"  Has login link: {has_login} (= NOT authenticated)")
    print(f"  SFW/NSFW:       {sfw_ctx}")
    print(f"{'='*60}")
    return len(ids)


async def proxy_request(client: httpx.AsyncClient, method: str, url: str,
                        cookies: str = "", chain: list[str] | None = None,
                        data: dict | None = None) -> httpx.Response:
    """Send a request through the CF Worker proxy."""
    headers = {
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Referer": "https://sofurry.com/",
        "x-proxy-key": CF_KEY,
        "x-target-url": url,
    }
    if cookies:
        headers["Cookie"] = cookies
    if chain:
        headers["x-proxy-chain"] = json.dumps(chain)

    if method == "GET":
        resp = await client.get(CF_URL, headers=headers)
    else:
        # For POST, send form data
        headers["Content-Type"] = "application/x-www-form-urlencoded"
        body = "&".join(f"{k}={v}" for k, v in data.items()) if data else ""
        resp = await client.post(CF_URL, headers=headers, content=body)

    return resp


def extract_cookies(resp: httpx.Response) -> str:
    """Extract cookies from response headers."""
    cookies = {}
    # From Set-Cookie headers
    for sc in resp.headers.get_list("set-cookie"):
        eq = sc.index("=") if "=" in sc else -1
        if eq > 0:
            semi = sc.index(";") if ";" in sc else len(sc)
            name = sc[:eq].strip()
            value = sc[eq+1:semi].strip()
            if not name.startswith("__"):
                cookies[name] = value
    # From X-Session-Cookies header
    session = resp.headers.get("x-session-cookies", "")
    if session:
        for part in session.split("; "):
            if "=" in part:
                name, _, value = part.partition("=")
                cookies[name.strip()] = value.strip()
    return "; ".join(f"{k}={v}" for k, v in cookies.items())


async def test_direct():
    """Test 0: Direct connection (no proxy) — confirms IP blocking."""
    print("\n" + "="*60)
    print("  TEST 0: Direct connection (no proxy)")
    print("="*60)
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as c:
            resp = await c.get(f"{SOFURRY}/u/{SF_DISPLAY}/gallery",
                              headers={"User-Agent": UA})
            print(f"  Status: {resp.status_code}")
            print(f"  URL:    {resp.url}")
            if resp.status_code == 200:
                ids = re.findall(r'/s/([A-Za-z0-9]+)', resp.text)
                print(f"  Submissions (unauthenticated): {len(ids)}")
            else:
                print(f"  Response: {resp.text[:200]}")
    except Exception as e:
        print(f"  BLOCKED/ERROR: {e}")


async def test_separate_requests():
    """Test 1: Login and gallery as SEPARATE proxy requests."""
    print("\n" + "="*60)
    print("  TEST 1: Separate requests (login then gallery)")
    print("="*60)
    async with httpx.AsyncClient(timeout=30, follow_redirects=False) as c:
        # Step 1: GET /login for CSRF
        print("  Step 1: GET /login (CSRF token)...")
        resp = await proxy_request(c, "GET", f"{SOFURRY}/login")
        cookies = extract_cookies(resp)
        csrf = re.search(r'name="_token"\s*value="([^"]+)"', resp.text)
        if not csrf:
            print("  ERROR: No CSRF token found")
            return
        print(f"  CSRF token: {csrf.group(1)[:20]}...")
        print(f"  Cookies: {cookies[:80]}...")

        # Step 2: POST /login
        print("  Step 2: POST /login...")
        resp = await proxy_request(c, "POST", f"{SOFURRY}/login",
                                   cookies=cookies,
                                   data={"_token": csrf.group(1),
                                         "email": SF_USER,
                                         "password": SF_PASS})
        cookies = extract_cookies(resp)
        final = resp.headers.get("x-final-url", str(resp.url))
        print(f"  Status: {resp.status_code}")
        print(f"  Final URL: {final}")
        print(f"  Cookies: {cookies[:80]}...")

        if "/login" in final:
            print("  FAILED: Still on login page")
            return

        print("  Login OK!")

        # Step 3: GET gallery (separate invocation = different IP)
        print("  Step 3: GET gallery (separate request)...")
        resp = await proxy_request(c, "GET",
                                   f"{SOFURRY}/u/{SF_DISPLAY}/gallery",
                                   cookies=cookies)
        check_gallery_html(resp.text, "TEST 1: Separate requests")


async def test_chained():
    """Test 2: Login POST chained with gallery (same invocation)."""
    print("\n" + "="*60)
    print("  TEST 2: Chained (login + gallery in one invocation)")
    print("="*60)
    async with httpx.AsyncClient(timeout=30, follow_redirects=False) as c:
        # Step 1: GET /login for CSRF (separate invocation, OK)
        print("  Step 1: GET /login (CSRF token)...")
        resp = await proxy_request(c, "GET", f"{SOFURRY}/login")
        cookies = extract_cookies(resp)
        csrf = re.search(r'name="_token"\s*value="([^"]+)"', resp.text)
        if not csrf:
            print("  ERROR: No CSRF token found")
            return
        print(f"  CSRF token: {csrf.group(1)[:20]}...")
        print(f"  Cookies: {cookies[:80]}...")

        # Step 2: POST /login WITH chain to gallery
        gallery_url = f"{SOFURRY}/u/{SF_DISPLAY}/gallery"
        print(f"  Step 2: POST /login + chain [{gallery_url}]...")
        resp = await proxy_request(c, "POST", f"{SOFURRY}/login",
                                   cookies=cookies,
                                   chain=[gallery_url],
                                   data={"_token": csrf.group(1),
                                         "email": SF_USER,
                                         "password": SF_PASS})
        final = resp.headers.get("x-final-url", "")
        session_cookies = resp.headers.get("x-session-cookies", "")
        print(f"  Status: {resp.status_code}")
        print(f"  Final URL: {final}")
        print(f"  X-Session-Cookies: {session_cookies[:80]}...")
        count = check_gallery_html(resp.text, "TEST 2: Chained login+gallery")

        # Dump HTML to file for analysis
        with open("/tmp/sf_gallery.html", "w") as f:
            f.write(resp.text)
        print(f"\n  Full HTML saved to /tmp/sf_gallery.html")

        # Show key diagnostic sections
        html = resp.text
        print("\n  --- First 800 chars ---")
        print(html[:800])
        print("\n  --- Nav/header area ---")
        for m in re.finditer(r'<nav[^>]*>.*?</nav>', html, re.DOTALL):
            print(m.group(0)[:500])
        print("\n  --- Script tags mentioning gallery/submission/artwork ---")
        for m in re.finditer(r'<script[^>]*>([^<]*(?:gallery|submission|artwork|login|auth)[^<]*)</script>', html, re.IGNORECASE):
            print(m.group(0)[:400])
        print("\n  --- Links containing /u/ or /s/ ---")
        for m in re.findall(r'href="[^"]*(?:/u/|/s/)[^"]*"', html):
            print(f"    {m}")
        print("\n  --- Forms ---")
        for m in re.finditer(r'<form[^>]*>', html):
            print(f"    {m.group(0)}")
        print("\n  --- Any 'login'/'logout'/'account' text ---")
        for m in re.finditer(r'.{0,40}(?:login|logout|account|sign.?in|sign.?out).{0,40}', html, re.IGNORECASE):
            print(f"    ...{m.group(0).strip()}...")


async def test_login_sequence():
    """Test 5: Full login sequence in one Worker invocation (x-proxy-login)."""
    print("\n" + "="*60)
    print("  TEST 5: Login sequence (GET+POST+gallery, ALL same IP)")
    print("="*60)
    async with httpx.AsyncClient(timeout=30, follow_redirects=False) as c:
        login_data = {
            "url": f"{SOFURRY}/login",
            "email": SF_USER,
            "password": SF_PASS,
            "then": f"{SOFURRY}/u/{SF_DISPLAY}/gallery",
        }
        resp = await c.get(CF_URL, headers={
            "x-proxy-key": CF_KEY,
            "x-proxy-login": json.dumps(login_data),
            "User-Agent": UA,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Referer": "https://sofurry.com/",
        })
        final = resp.headers.get("x-final-url", "")
        session_cookies = resp.headers.get("x-session-cookies", "")
        print(f"  Status: {resp.status_code}")
        print(f"  Final URL: {final}")
        print(f"  X-Session-Cookies: {session_cookies[:80]}...")
        count = check_gallery_html(resp.text, "TEST 5: Login sequence (same IP)")

        # Dump HTML
        with open("/tmp/sf_gallery_t5.html", "w") as f:
            f.write(resp.text)
        print(f"\n  Full HTML saved to /tmp/sf_gallery_t5.html")

        # Key diagnostics
        html = resp.text
        print("\n  --- Links containing /s/ (submissions) ---")
        s_links = re.findall(r'href="[^"]*(/s/[^"]*)"', html)
        for link in s_links[:10]:
            print(f"    {link}")
        if not s_links:
            print("    (none)")
        print("\n  --- Any 'login'/'logout' text ---")
        for m in re.finditer(r'.{0,30}(?:login|logout|sign.?in|sign.?out).{0,30}', html, re.IGNORECASE):
            print(f"    ...{m.group(0).strip()}...")


async def test_gallery_unauthenticated():
    """Test 4: Gallery through proxy but without login."""
    print("\n" + "="*60)
    print("  TEST 4: Gallery via proxy (no login)")
    print("="*60)
    async with httpx.AsyncClient(timeout=30, follow_redirects=False) as c:
        resp = await proxy_request(c, "GET",
                                   f"{SOFURRY}/u/{SF_DISPLAY}/gallery")
        check_gallery_html(resp.text, "TEST 4: Unauthenticated gallery via proxy")


async def main():
    print("SoFurry Proxy Test Script")
    print(f"  SF User:    {SF_USER}")
    print(f"  SF Display: {SF_DISPLAY}")
    print(f"  CF Worker:  {CF_URL}")
    print(f"  CF Key:     {'*' * len(CF_KEY) if CF_KEY else '(not set)'}")

    if not all([SF_USER, SF_PASS, SF_DISPLAY, CF_URL, CF_KEY]):
        print("\nERROR: Missing required env vars.")
        print("Set: SF_USERNAME, SF_PASSWORD, SF_DISPLAY_NAME, CF_WORKER_URL, CF_WORKER_KEY")
        sys.exit(1)

    await test_direct()
    await test_gallery_unauthenticated()
    await test_login_sequence()

    print("\n" + "="*60)
    print("  ALL TESTS COMPLETE")
    print("="*60)
    print("\nIf Test 2 shows submissions but Test 1 doesn't,")
    print("the chain approach works and the current code should fix the issue.")
    print("\nIf neither shows submissions, we need a different approach")
    print("(e.g., fixed-IP proxy or Cloudflare Tunnel).")


if __name__ == "__main__":
    asyncio.run(main())
