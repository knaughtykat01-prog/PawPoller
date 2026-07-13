"""Shared async request rate limiter for X/Twitter polling.

X applies its timeline rate limit **per IP**, shared across ALL of a user's
accounts. Polling several accounts back-to-back in one cycle (server.py
`_poll_accounts` runs them sequentially with no spacing) blew straight through
it — and a per-request `sleep` only paces requests *within* one account.

This module enforces a global cap *across* every account and backend: no more
than ``N`` requests per rolling ``W``-second window. The default (15 / 30 s) is
1 request every 2 s averaged, but as a **sliding window** — a burst can never
exceed 15 in any 30 s, no matter how the accounts interleave.

Scope: the requests PawPoller makes **directly** — the GraphQL scrape
(`clients/tw/client.py`) and the official API (`clients/tw/official_api.py`).
gallery-dl runs as a subprocess and self-paces via ``--sleep-request``, so its
internal requests aren't (and can't cleanly be) gated here.
"""

from __future__ import annotations

import asyncio
import collections
import logging
import time

import config

logger = logging.getLogger(__name__)


class AsyncSlidingWindowLimiter:
    """Admit at most ``max_requests`` acquisitions per ``window_seconds``.

    Admission is FIFO and serialized (the lock is held across the wait), so
    requests fire in order — that ordering *is* the "sequencing". ``time_fn`` /
    ``sleep_fn`` are injectable for deterministic tests.
    """

    def __init__(self, max_requests: int, window_seconds: float, *,
                 time_fn=time.monotonic, sleep_fn=asyncio.sleep):
        self.max_requests = max(1, int(max_requests))
        self.window_seconds = max(0.0, float(window_seconds))
        self._stamps: collections.deque = collections.deque()
        self._lock = asyncio.Lock()
        self._time = time_fn
        self._sleep = sleep_fn

    async def acquire(self) -> None:
        """Block until firing now keeps us within the cap, then record the hit."""
        if self.window_seconds <= 0:
            return
        async with self._lock:
            while True:
                now = self._time()
                cutoff = now - self.window_seconds
                while self._stamps and self._stamps[0] <= cutoff:
                    self._stamps.popleft()
                if len(self._stamps) < self.max_requests:
                    self._stamps.append(now)
                    return
                wait = self._stamps[0] + self.window_seconds - now
                if wait <= 0:
                    # Oldest is exactly at the edge — pop it next loop.
                    self._stamps.popleft()
                    continue
                logger.debug("TW rate limit: waiting %.2fs (%d/%d in %.0fs window)",
                             wait, len(self._stamps), self.max_requests, self.window_seconds)
                await self._sleep(wait)


_tw_limiter: AsyncSlidingWindowLimiter | None = None


def get_tw_limiter() -> AsyncSlidingWindowLimiter:
    """Process-wide singleton limiter for X requests, built from config
    (``TW_RATE_LIMIT_REQUESTS`` / ``TW_RATE_LIMIT_WINDOW_SECONDS``)."""
    global _tw_limiter
    if _tw_limiter is None:
        _tw_limiter = AsyncSlidingWindowLimiter(
            getattr(config, "TW_RATE_LIMIT_REQUESTS", 15),
            getattr(config, "TW_RATE_LIMIT_WINDOW_SECONDS", 30),
        )
    return _tw_limiter


async def tw_acquire() -> None:
    """Await a slot in the shared X request budget before making a request."""
    await get_tw_limiter().acquire()
