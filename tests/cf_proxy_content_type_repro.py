"""Reproduce the CF Worker Content-Type stripping bug.

Sends a POST through the proxy to httpbin.org/post (which echoes back the
headers it received). If the worker is forwarding Content-Type correctly,
the response will show "Content-Type": "application/json" in the headers.
If the bug is present, Content-Type will be missing or "text/plain".
"""
from __future__ import annotations
import asyncio
import sys
sys.path.insert(0, "/app")

import config
import httpx
from polling.cf_proxy import CloudflareProxyTransport


async def main() -> int:
    s = config.get_settings()
    proxy_url = s.get("cf_worker_url", "")
    proxy_key = s.get("cf_worker_key", "")
    if not (proxy_url and proxy_key):
        print("[FAIL] no cf_worker_url/key configured")
        return 1

    transport = CloudflareProxyTransport(proxy_url, proxy_key)
    async with httpx.AsyncClient(timeout=30, follow_redirects=False, transport=transport) as c:
        r = await c.post(
            "https://httpbin.org/post",
            json={"test": "content-type-repro", "value": 42},
        )
        print(f"status: {r.status_code}")
        if r.status_code == 200:
            data = r.json()
            received_headers = data.get("headers", {})
            ct = received_headers.get("Content-Type") or received_headers.get("content-type")
            received_data = data.get("data") or data.get("json")
            print(f"target received Content-Type: {ct!r}")
            print(f"target received body data:    {received_data!r}")
            if ct == "application/json":
                print("[OK] Content-Type forwarded correctly — worker is FIXED")
                return 0
            else:
                print("[BUG] Content-Type missing/wrong — worker still has the bug")
                return 1
        else:
            print(f"non-200 response: {r.text[:200]}")
            return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
