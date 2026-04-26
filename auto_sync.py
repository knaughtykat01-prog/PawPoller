"""Background settings sync between desktop and cloud server.

Two halves to this module:

  - **Push side**: when the desktop saves settings, we fire-and-forget a
    debounced push to the cloud server so the change propagates within
    a couple of seconds. Debouncing collapses bursts (e.g. five
    save_settings() calls in 100ms during a wizard step) into one HTTP
    request. Runs on a daemon thread.

  - **Pull side**: a separate daemon thread polls the cloud server every
    AUTO_SYNC_PULL_INTERVAL seconds and merges anything new. Conflict
    resolution is last-writer-wins via mtime — if the server's snapshot
    is older than ours we skip the merge (otherwise we'd undo our own
    in-flight push).

Loop-protection: merge_synced_settings() ultimately calls save_settings()
which would normally trigger a push, which the server would then echo
back to us, ad infinitum. The `_in_pull_merge` thread-local flag is set
during pull-driven saves and skipped by schedule_push().

Activation: nothing happens unless settings.json has both
`posting_server_url` and `posting_server_api_key` set AND
`auto_sync_enabled` is true (the default). Servers themselves leave
posting_server_url empty so they never sync to themselves.
"""
from __future__ import annotations

import logging
import threading
import time

logger = logging.getLogger(__name__)


AUTO_SYNC_PUSH_DEBOUNCE_SECONDS = 2.0
AUTO_SYNC_PULL_INTERVAL_SECONDS = 300  # 5 minutes
AUTO_SYNC_HTTP_TIMEOUT = 10

_push_lock = threading.Lock()
_push_timer: threading.Timer | None = None

# Set on the thread that's currently applying a server pull, so save_settings
# inside merge_synced_settings doesn't trigger another push.
_in_pull_merge = threading.local()


def _is_pull_merge() -> bool:
    return getattr(_in_pull_merge, "active", False)


def _sync_target():
    """Return (server_url, api_key) if auto-sync is configured, else None."""
    import config
    settings = config.get_settings()
    if not settings.get("auto_sync_enabled", True):
        return None
    server_url = (settings.get("posting_server_url") or "").rstrip("/")
    api_key = settings.get("posting_server_api_key") or ""
    if not server_url or not api_key:
        return None
    # A server pointing at itself would create a loopback storm. Cheap guard:
    # treat anything resolving to localhost as "we are the server, don't sync".
    if "localhost" in server_url or "127.0.0.1" in server_url:
        return None
    return server_url, api_key


def _do_push():
    """Push current settings to the server. Runs on the debounce timer thread."""
    import httpx
    import config

    target = _sync_target()
    if target is None:
        return
    server_url, api_key = target

    try:
        data, _mtime = config.get_settings_for_sync()
        resp = httpx.post(
            f"{server_url}/api/settings/sync",
            json={"mode": "push", "settings": data},
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=AUTO_SYNC_HTTP_TIMEOUT,
        )
        if resp.status_code == 200:
            body = resp.json()
            logger.info("Auto-sync push: %d keys merged on server",
                        body.get("keys_merged", 0))
        else:
            logger.warning("Auto-sync push failed: HTTP %d", resp.status_code)
    except Exception as e:
        logger.debug("Auto-sync push: server unreachable (%s)", e)


def schedule_push() -> None:
    """Fire a debounced push to the server. Safe to call from any thread.

    Multiple calls within AUTO_SYNC_PUSH_DEBOUNCE_SECONDS collapse into one
    HTTP request, so wizards/bulk saves don't generate a push per field.
    No-op when the save originated from a pull merge.
    """
    if _is_pull_merge():
        return
    if _sync_target() is None:
        return

    global _push_timer
    with _push_lock:
        if _push_timer is not None:
            _push_timer.cancel()
        _push_timer = threading.Timer(AUTO_SYNC_PUSH_DEBOUNCE_SECONDS, _do_push)
        _push_timer.daemon = True
        _push_timer.start()


def pull_once() -> bool:
    """One-shot pull from the cloud server. Returns True on success."""
    import httpx
    import config

    target = _sync_target()
    if target is None:
        return False
    server_url, api_key = target

    try:
        resp = httpx.post(
            f"{server_url}/api/settings/sync",
            json={"mode": "pull"},
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=AUTO_SYNC_HTTP_TIMEOUT,
        )
        if resp.status_code != 200:
            logger.warning("Auto-sync pull failed: HTTP %d", resp.status_code)
            return False
        body = resp.json()
        if not body.get("ok") or not body.get("settings"):
            return False
        pulled = body["settings"]
        server_mtime = body.get("timestamp", 0)
        local_mtime = (config.SETTINGS_PATH.stat().st_mtime
                       if config.SETTINGS_PATH.exists() else 0)
        # Last-writer-wins: only apply if the server is newer than us.
        # Skipping when server is older avoids stomping a push we just sent
        # that the server hasn't fully echoed back yet.
        if server_mtime <= local_mtime:
            return False
        _in_pull_merge.active = True
        try:
            config.merge_synced_settings(pulled, client_timestamp=server_mtime)
        finally:
            _in_pull_merge.active = False
        logger.info("Auto-sync pull: applied %d keys from server", len(pulled))
        return True
    except Exception as e:
        logger.debug("Auto-sync pull: server unreachable (%s)", e)
        return False


def _pull_loop():
    """Background loop: pull from server every AUTO_SYNC_PULL_INTERVAL_SECONDS."""
    while True:
        try:
            pull_once()
        except Exception:
            logger.exception("Auto-sync pull loop iteration failed")
        time.sleep(AUTO_SYNC_PULL_INTERVAL_SECONDS)


def start_pull_thread() -> threading.Thread:
    """Start the periodic pull daemon. Idempotent — call once at startup."""
    t = threading.Thread(target=_pull_loop, name="auto_sync_pull", daemon=True)
    t.start()
    return t
