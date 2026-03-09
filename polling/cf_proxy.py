"""Cloudflare Worker proxy transport for httpx.

Routes HTTP requests through a Cloudflare Worker to bypass datacenter IP
blocking on sites like DeviantArt and SoFurry.  Works at the httpx transport
layer so the rest of the code (cookies, redirects, etc.) behaves normally.

The Worker expects two headers:
  - x-proxy-key:  shared secret for authentication
  - x-target-url: the real URL to fetch

The Worker forwards the request, strips proxy headers, and returns the
response with redirect: 'manual' so httpx can handle redirects itself
(each redirect also goes through the proxy transport).
"""

from __future__ import annotations
import logging

import httpx

logger = logging.getLogger(__name__)


class CloudflareProxyTransport(httpx.AsyncBaseTransport):
    """httpx transport that routes requests through a Cloudflare Worker."""

    def __init__(self, worker_url: str, proxy_key: str):
        self.worker_url = worker_url.rstrip("/")
        self.proxy_key = proxy_key
        self._inner = httpx.AsyncHTTPTransport(retries=2)

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        target_url = str(request.url)

        # Build new headers: keep originals, add proxy headers
        headers = [(k, v) for k, v in request.headers.raw]
        headers.append((b"x-proxy-key", self.proxy_key.encode()))
        headers.append((b"x-target-url", target_url.encode()))

        # Rewrite request to go to the Worker instead of the real target
        proxy_request = httpx.Request(
            method=request.method,
            url=self.worker_url,
            headers=headers,
            stream=request.stream,
        )

        return await self._inner.handle_async_request(proxy_request)

    async def aclose(self) -> None:
        await self._inner.aclose()
