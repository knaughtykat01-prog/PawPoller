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

Cookie handling:
  httpx's cookie jar doesn't work correctly through the proxy because
  the HTTP-level request goes to the worker URL, breaking domain matching.
  The transport provides set_cookies() / get_response_cookies() to manage
  cookies at the transport level, bypassing the jar entirely.
"""

from __future__ import annotations
import logging
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)


class CloudflareProxyTransport(httpx.AsyncBaseTransport):
    """httpx transport that routes requests through a Cloudflare Worker."""

    def __init__(self, worker_url: str, proxy_key: str):
        self.worker_url = worker_url.rstrip("/")
        self.proxy_key = proxy_key
        self._worker_host = urlparse(worker_url).netloc
        self._inner = httpx.AsyncHTTPTransport(retries=2)
        self._session_cookies: str = ""  # Raw "name=val; name2=val2" string

    def set_cookies(self, cookie_str: str) -> None:
        """Store a raw cookie string to inject into every proxied request."""
        self._session_cookies = cookie_str

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        target_url = str(request.url)

        logger.debug("CF proxy: %s %s | cookies: %s",
                      request.method, target_url,
                      self._session_cookies[:120] if self._session_cookies else "(none)")

        # Build new headers: keep originals but replace Host with worker host
        # and inject session cookies (bypassing httpx's broken cookie jar).
        headers = []
        has_cookie = False
        for k, v in request.headers.raw:
            if k.lower() == b"host":
                headers.append((b"host", self._worker_host.encode()))
            elif k.lower() == b"cookie" and self._session_cookies:
                # Replace httpx's (likely empty) cookie header with our stored cookies
                headers.append((b"cookie", self._session_cookies.encode()))
                has_cookie = True
            else:
                headers.append((k, v))

        # If no cookie header existed but we have session cookies, add one
        if not has_cookie and self._session_cookies:
            headers.append((b"cookie", self._session_cookies.encode()))

        # Add proxy-specific headers
        headers.append((b"x-proxy-key", self.proxy_key.encode()))
        headers.append((b"x-target-url", target_url.encode()))

        # Rewrite request to go to the Worker instead of the real target
        proxy_request = httpx.Request(
            method=request.method,
            url=self.worker_url,
            headers=headers,
            stream=request.stream,
        )

        response = await self._inner.handle_async_request(proxy_request)

        # Log response status and Set-Cookie headers for debugging
        set_cookies = response.headers.get_list("set-cookie")
        logger.debug("CF proxy: response %d for %s | Set-Cookie count: %d",
                      response.status_code, target_url, len(set_cookies))
        if set_cookies:
            for sc in set_cookies:
                logger.debug("CF proxy:   Set-Cookie: %s", sc[:100])

        # Capture Set-Cookie headers from the response and update our
        # stored cookies so they persist across requests.
        self._update_cookies_from_response(response)

        if self._session_cookies:
            cookie_names = [p.split("=")[0] for p in self._session_cookies.split("; ") if "=" in p]
            logger.debug("CF proxy: stored cookies after response: %s", cookie_names)

        return response

    def _update_cookies_from_response(self, response: httpx.Response) -> None:
        """Parse Set-Cookie headers and merge into stored session cookies."""
        new_cookies: dict[str, str] = {}
        # Start with existing cookies
        if self._session_cookies:
            for part in self._session_cookies.split("; "):
                if "=" in part:
                    name, _, value = part.partition("=")
                    new_cookies[name.strip()] = value.strip()

        # Merge in any Set-Cookie from the response
        changed = False
        for header_value in response.headers.get_list("set-cookie"):
            cookie_part = header_value.split(";")[0].strip()
            if "=" in cookie_part:
                name, _, value = cookie_part.partition("=")
                name = name.strip()
                value = value.strip()
                if name and not name.startswith("__"):
                    if new_cookies.get(name) != value:
                        new_cookies[name] = value
                        changed = True

        if changed:
            self._session_cookies = "; ".join(
                f"{k}={v}" for k, v in new_cookies.items()
            )

    async def aclose(self) -> None:
        await self._inner.aclose()
