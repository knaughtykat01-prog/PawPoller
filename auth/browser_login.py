"""Embedded browser login -- opens a pywebview popup for platform authentication.

The user logs in through the actual platform website inside a native desktop
window. On success, cookies/tokens are detected via URL changes and cookie
inspection, then extracted and saved to settings.json via config.save_settings().

pywebview's get_cookies() returns a list of http.cookies.SimpleCookie objects.
Each SimpleCookie is a dict mapping a single cookie name to a Morsel with a
.value attribute.  We flatten these into a {name: value} dict for easy lookup.

Threading constraints:
    pywebview.start() MUST run on the main thread on macOS.  On Windows (our
    primary target) it can run on any thread, but webview.start() blocks until
    ALL windows created in that call are destroyed.  We therefore create a
    fresh webview.start() call per login window inside a daemon thread so the
    main window keeps responding.

    IMPORTANT: Each call to webview.start() creates an independent GUI event
    loop.  Only one webview.start() can be active per thread, so the login
    window runs in its own thread.  On Windows with EdgeChromium this works
    reliably.
"""

from __future__ import annotations

import logging
import queue
import threading
from http.cookies import SimpleCookie

import config

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Cookie helpers
# ---------------------------------------------------------------------------

def _flatten_cookies(cookie_list: list[SimpleCookie]) -> dict[str, str]:
    """Convert pywebview's list-of-SimpleCookie into a flat {name: value} dict.

    pywebview.Window.get_cookies() returns a list where each element is a
    SimpleCookie containing exactly one key.  We iterate all of them and
    merge into a single dict for easy lookup by cookie name.
    """
    flat: dict[str, str] = {}
    for sc in cookie_list:
        for name, morsel in sc.items():
            flat[name] = morsel.value
    return flat


# ---------------------------------------------------------------------------
# Per-platform login configuration
# ---------------------------------------------------------------------------
# Each entry defines:
#   name          -- Human-readable platform name (shown in window title)
#   url           -- Login page URL to load initially
#   success_check -- Callable(cookies_dict, current_url) -> bool
#                    Returns True when the user has successfully logged in.
#   extract       -- Callable(cookies_dict, current_url) -> dict
#                    Returns the credential keys to save into settings.json.
#   fields        -- Optional list of extra fields the user must provide
#                    before launching the browser (e.g. username to track).
#                    Each is {id, label, placeholder, required}.

PLATFORM_LOGIN: dict[str, dict] = {
    "fa": {
        "name": "FurAffinity",
        "url": "https://www.furaffinity.net/login/",
        "success_check": lambda cookies, url: (
            "a" in cookies and "b" in cookies
        ),
        "extract": lambda cookies, url: {
            "fa_cookie_a": cookies.get("a", ""),
            "fa_cookie_b": cookies.get("b", ""),
        },
        "fields": [
            {"id": "fa_username", "label": "FA username", "placeholder": "Your FurAffinity username", "required": True},
        ],
    },
    "da": {
        "name": "DeviantArt",
        "url": "https://www.deviantart.com/users/login",
        "success_check": lambda cookies, url: "auth_secure" in cookies or "auth" in cookies,
        "extract": lambda cookies, url: {
            # DA uses full cookie string -- rebuild it from all cookies
            "da_cookie": "; ".join(f"{k}={v}" for k, v in cookies.items()),
        },
        "fields": [
            {"id": "da_username", "label": "DA username to track", "placeholder": "DeviantArt username", "required": True},
        ],
    },
    "sf": {
        "name": "SoFurry",
        "url": "https://www.sofurry.com/user/login",
        "success_check": lambda cookies, url: (
            "/user/login" not in (url or "") and
            "sofurry.com" in (url or "")
        ),
        "extract": lambda cookies, url: {
            # SF uses session cookies -- capture them all for the session
            "sf_session_cookies": "; ".join(f"{k}={v}" for k, v in cookies.items()),
        },
        "fields": [
            {"id": "sf_display_name", "label": "SF display name", "placeholder": "Your SoFurry profile name", "required": True},
        ],
    },
    "tw": {
        "name": "X / Twitter",
        "url": "https://x.com/i/flow/login",
        "success_check": lambda cookies, url: (
            "auth_token" in cookies
        ),
        "extract": lambda cookies, url: {
            "tw_auth_token": cookies.get("auth_token", ""),
            "tw_ct0": cookies.get("ct0", ""),
        },
        "fields": [
            {"id": "tw_username", "label": "X username to track", "placeholder": "Username (without @)", "required": True},
        ],
    },
    "ws": {
        "name": "Weasyl",
        "url": "https://www.weasyl.com/signin",
        "success_check": lambda cookies, url: "WZL" in cookies,
        "extract": lambda cookies, url: {},
        # Weasyl uses API keys, not cookies -- browser login captures nothing useful
        # but we include it so users can verify their account works.
        "fields": [],
    },
    "ao3": {
        "name": "Archive of Our Own",
        "url": "https://archiveofourown.org/users/login",
        "success_check": lambda cookies, url: (
            "user_credentials" in cookies or
            ("/users/login" not in (url or "") and "archiveofourown.org" in (url or ""))
        ),
        "extract": lambda cookies, url: {},
        # AO3 uses username/password stored in settings, not browser cookies
        "fields": [],
    },
    "sqw": {
        "name": "SquidgeWorld",
        "url": "https://squidgeworld.org/users/login",
        "success_check": lambda cookies, url: (
            "/users/login" not in (url or "") and
            "squidgeworld.org" in (url or "")
        ),
        "extract": lambda cookies, url: {},
        "fields": [],
    },
}


def get_supported_platforms() -> list[dict]:
    """Return list of platforms that support browser login.

    Each entry has {code, name, has_cookie_extraction, fields}.
    Used by the API to tell the frontend which platforms have browser login.
    """
    result = []
    for code, cfg in PLATFORM_LOGIN.items():
        # Only include platforms where browser login captures useful cookies
        extract_test = cfg["extract"]({}, "")
        result.append({
            "code": code,
            "name": cfg["name"],
            "has_cookie_extraction": bool(extract_test is not None),
            "fields": cfg.get("fields", []),
        })
    return result


# ---------------------------------------------------------------------------
# Core browser login function
# ---------------------------------------------------------------------------

def login_via_browser(
    platform: str,
    extra_fields: dict[str, str] | None = None,
    timeout: int = 300,
) -> dict | None:
    """Open a pywebview popup for the given platform's login page.

    The user logs in through the real platform website.  Once the
    success_check detects a successful login (via cookies or URL change),
    credentials are extracted and the window closes automatically.

    Args:
        platform: Platform code (e.g. "fa", "da", "tw").
        extra_fields: Additional field values from the UI (e.g. username).
        timeout: Max seconds to wait for login (default 300 = 5 minutes).

    Returns:
        Dict of extracted credentials on success, None on cancel/timeout.
        The credentials are also saved to settings.json automatically.

    Raises:
        ValueError: If platform code is not in PLATFORM_LOGIN.
        RuntimeError: If pywebview is not available (server mode).
    """
    plat_cfg = PLATFORM_LOGIN.get(platform)
    if not plat_cfg:
        raise ValueError(f"No browser login config for platform: {platform}")

    try:
        import webview
    except ImportError:
        raise RuntimeError(
            "pywebview is not available. Browser login only works in desktop mode."
        )

    result_queue: queue.Queue[dict | None] = queue.Queue()

    def _run_login_window():
        """Thread target: creates and runs the login window."""
        try:
            window = webview.create_window(
                f"Login to {plat_cfg['name']} — PawPoller",
                plat_cfg["url"],
                width=900,
                height=700,
            )

            poll_active = True

            def _check_login():
                """Periodically check cookies/URL for successful login."""
                import time
                while poll_active:
                    time.sleep(2)
                    try:
                        cookies_raw = window.get_cookies()
                        url = window.get_current_url() or ""
                        cookies = _flatten_cookies(cookies_raw)

                        if plat_cfg["success_check"](cookies, url):
                            creds = plat_cfg["extract"](cookies, url)
                            logger.info(
                                "Browser login success for %s (%d cookie keys extracted)",
                                platform, len(creds),
                            )
                            result_queue.put(creds)
                            # Close the window from a timer to avoid deadlock
                            window.destroy()
                            return
                    except Exception as e:
                        # Window might be closing or not yet loaded
                        logger.debug("Cookie check for %s: %s", platform, e)

            # Start the cookie-polling thread
            checker = threading.Thread(target=_check_login, daemon=True)
            checker.start()

            # webview.start() blocks until the window is destroyed
            webview.start()

            # If we get here without a result, user closed the window
            poll_active = False
            if result_queue.empty():
                result_queue.put(None)

        except Exception as e:
            logger.error("Browser login window error for %s: %s", platform, e)
            result_queue.put(None)

    # Run in a thread so we don't block the caller
    login_thread = threading.Thread(target=_run_login_window, daemon=True)
    login_thread.start()

    # Wait for the result (blocks until window closes or timeout)
    try:
        creds = result_queue.get(timeout=timeout)
    except queue.Empty:
        logger.warning("Browser login timed out for %s after %ds", platform, timeout)
        return None

    if creds is None:
        logger.info("Browser login cancelled for %s", platform)
        return None

    # Merge extra fields (username, etc.) provided by the caller
    if extra_fields:
        creds.update(extra_fields)

    # Save to settings.json
    if creds:
        config.save_settings(creds)
        logger.info("Saved browser login credentials for %s: %s", platform, list(creds.keys()))

    return creds


# ---------------------------------------------------------------------------
# Convenience: check if browser login is available
# ---------------------------------------------------------------------------

def is_browser_login_available() -> bool:
    """Return True if pywebview is importable (desktop mode)."""
    try:
        import webview  # noqa: F401
        return True
    except ImportError:
        return False
