"""Fire-and-forget scheduling for manual poll / resync triggers.

Manual trigger endpoints used to ``await run_X_poll_cycle()`` *inside* the HTTP
request, so the response didn't return until the whole scrape finished. Behind
Cloudflare (which caps a request at ~100 s) a slow platform — AO3, X — blew
past that and the browser got a **524 timeout**, even though the poll itself was
running fine.

``spawn()`` runs the cycle as a detached background task on the running event
loop and lets the endpoint return immediately. The frontend only cares that the
trigger was accepted (it shows "Done!" then reloads), not about the poll's
return value, so returning before the scrape completes is exactly right.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Awaitable

logger = logging.getLogger(__name__)

# Hold strong references to in-flight tasks. asyncio only keeps a weak reference
# to a bare create_task() result, so without this the task can be garbage
# collected mid-flight and cancelled. Discarded in the done-callback.
_background_tasks: set[asyncio.Task] = set()


def spawn(coro: Awaitable, label: str) -> None:
    """Schedule ``coro`` fire-and-forget, logging any exception it raises.

    Must be called from within a running event loop (i.e. an async route
    handler), which is always the case for the poll/resync endpoints.
    """
    task = asyncio.ensure_future(coro)
    _background_tasks.add(task)

    def _done(t: asyncio.Task) -> None:
        _background_tasks.discard(t)
        if t.cancelled():
            return
        exc = t.exception()
        if exc is not None:
            logger.error("Background task %r failed: %s", label, exc, exc_info=exc)

    task.add_done_callback(_done)
