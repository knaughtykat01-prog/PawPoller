"""Web dashboard — start when you want to view analytics.

Usage:
    python dashboard.py
    Open http://127.0.0.1:8420
"""

import logging
import sys
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse, Response

import config
from database.db import init_db
from routes.api import router
from routes.fa_api import fa_router
from routes.ws_api import ws_router
from routes.sf_api import sf_router
from routes.sqw_api import sqw_router
from routes.ao3_api import ao3_router
from routes.da_api import da_router
from routes.wp_api import wp_router
from routes.ik_api import ik_router
from routes.bsky_api import bsky_router
from routes.tw_api import tw_router
from routes.posting_api import posting_router
from routes.editor_api import editor_router
from routes.dashboard_auth import dashboard_auth_router
from routes.settings_api import settings_router, accounts_router
from routes.testing_api import testing_router

# Importing this package triggers @register_test decorators in every
# submodule, populating testing.registry.REGISTRY before the first
# request to /api/testing/tests.
import testing.tests  # noqa: F401

# Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("dashboard")


# FastAPI lifespan context manager — replaces the deprecated on_event("startup")
# and on_event("shutdown") hooks. Everything before `yield` runs at startup (DB init,
# logging the listen address). Everything after `yield` runs at shutdown. FastAPI
# holds the context open for the entire lifetime of the server.
@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    config.migrate_dashboard_auth()
    logger.info("Dashboard started at http://%s:%d", config.DASHBOARD_HOST, config.DASHBOARD_PORT)
    yield
    logger.info("Dashboard shutting down")


app = FastAPI(title="PawPoller", version="1.0.0", lifespan=lifespan)

# ── CORS — Block All Cross-Origin Requests ────────────────────
# PawPoller is a self-contained SPA where frontend and API are same-origin.
# No legitimate cross-origin requests should ever occur.  Empty allow_origins
# means all CORS preflight requests are denied, preventing external sites from
# making API calls to PawPoller even if a user has it open in another tab.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[],
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
)


# Global exception handler — catches any unhandled exception that escapes a route
# handler and returns a clean JSON 500 instead of letting uvicorn emit a bare
# traceback or HTML error page. Also logs the full stack trace (exc_info=True) so
# errors are visible in the console/log without exposing internals to the client.
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error("Unhandled error on %s %s: %s", request.method, request.url.path, exc, exc_info=True)
    return JSONResponse(status_code=500, content={"error": "Internal server error"})


# ── HTTP Security Headers ──────────────────────────────────────
# Applied to every response.  These are defence-in-depth measures:
#   X-Content-Type-Options  — prevents MIME-sniffing (IE/Edge attack vector)
#   X-Frame-Options         — blocks embedding in iframes (clickjacking)
#   Referrer-Policy         — limits referrer leakage to external sites
#   Content-Security-Policy — restricts script/style/image/connect sources
#     script-src 'self' <theme-hash>  : bundled JS + the inline no-flash theme
#                                       bootstrap script (hashed so the rest of
#                                       'unsafe-inline' stays disallowed)
#     style-src 'self' 'unsafe-inline' fonts.googleapis.com : CSS files + inline
#                                       style= attributes + Google Fonts CSS
#     font-src 'self' fonts.gstatic.com : Google Fonts woff2 binaries
#     img-src 'self' https:      : local proxy + platform CDN thumbnails
#     connect-src 'self'         : all API calls are same-origin
#     frame-ancestors 'none'     : no embedding allowed (supercedes X-Frame-Options)
#   When Turnstile is configured, script-src and frame-src include cloudflare.

_BASE_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
}


_cached_csp: str | None = None


_cached_epub_viewer_csp: str | None = None


def _build_epub_viewer_csp() -> str:
    """Relaxed CSP for the in-app EPUB viewer (/epub-viewer.html only).

    epub.js extracts CSS, images, and fonts from the EPUB archive into
    Blob URLs and references them from the rendered iframe. Without
    `blob:` in style-src/img-src/font-src those resources are CSP-blocked
    and the book renders unstyled or with broken inline images. The
    relaxation is scoped to this single page so the rest of the
    dashboard keeps the strict default.
    """
    global _cached_epub_viewer_csp
    if _cached_epub_viewer_csp is not None:
        return _cached_epub_viewer_csp
    theme_inline_hash = "'sha256-WudoxBejEmzS4SXsQBia7rsNZctlaFiey3RvF0r8SzA='"
    _cached_epub_viewer_csp = (
        "default-src 'self'; "
        f"script-src 'self' {theme_inline_hash}; "
        "style-src 'self' 'unsafe-inline' blob: https://fonts.googleapis.com; "
        "font-src 'self' blob: https://fonts.gstatic.com; "
        "img-src 'self' blob: data: https:; "
        "connect-src 'self' blob:; "
        "frame-src 'self' blob:; "
        "frame-ancestors 'none'"
    )
    return _cached_epub_viewer_csp


def _build_csp() -> str:
    """Build Content-Security-Policy, adding Turnstile origins when configured.

    Result is cached; call ``invalidate_csp_cache()`` when Turnstile config changes.
    """
    global _cached_csp
    if _cached_csp is not None:
        return _cached_csp
    settings = config.get_settings()
    has_turnstile = bool(settings.get("turnstile_site_key"))
    cf = " https://challenges.cloudflare.com" if has_turnstile else ""
    frame_src = f"frame-src 'self'{cf}; " if has_turnstile else ""
    # Hash of the inline theme-apply script in frontend/index.html.
    # Lets us keep that one no-flash bootstrap inline without opening up
    # the policy with 'unsafe-inline'. If the inline script changes, the
    # browser will print the new expected hash in the console and this
    # constant must be updated to match.
    theme_inline_hash = "'sha256-WudoxBejEmzS4SXsQBia7rsNZctlaFiey3RvF0r8SzA='"
    _cached_csp = (
        "default-src 'self'; "
        f"script-src 'self' {theme_inline_hash}{cf}; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com; "
        "img-src 'self' https:; "
        "connect-src 'self'; "
        f"{frame_src}"
        "frame-ancestors 'none'"
    )
    return _cached_csp


def invalidate_csp_cache() -> None:
    """Clear the cached CSP so it's rebuilt on the next request."""
    global _cached_csp, _cached_epub_viewer_csp
    _cached_csp = None
    _cached_epub_viewer_csp = None


@app.middleware("http")
async def security_headers_middleware(request: Request, call_next):
    response = await call_next(request)
    for header, value in _BASE_SECURITY_HEADERS.items():
        response.headers[header] = value
    # /epub-viewer.html needs a relaxed CSP for epub.js's blob: URLs.
    # Anything else gets the strict default.
    if request.url.path == "/epub-viewer.html":
        response.headers["Content-Security-Policy"] = _build_epub_viewer_csp()
    else:
        response.headers["Content-Security-Policy"] = _build_csp()
    return response


# ── Brute-Force Rate Limiting ─────────────────────────────────
# Simple in-memory tracker: after 10 failed auth attempts from the same IP
# within 5 minutes, all further requests from that IP get 429 Too Many Requests.
# Single-process server so in-memory state is sufficient.  Clears on restart.
# Used by both the session auth middleware below and the login endpoint in
# routes/dashboard_auth.py (which imports _record_auth_failure / _is_rate_limited).
_AUTH_FAIL_WINDOW = 300      # seconds (5 minutes)
_AUTH_FAIL_MAX = 10          # max failures before lockout
_auth_failures: dict[str, list[float]] = {}   # IP -> list of failure timestamps


def _record_auth_failure(ip: str) -> None:
    """Record a failed auth attempt from *ip*."""
    now = time.monotonic()
    attempts = _auth_failures.setdefault(ip, [])
    attempts.append(now)
    cutoff = now - _AUTH_FAIL_WINDOW
    _auth_failures[ip] = [t for t in attempts if t > cutoff]


def _is_rate_limited(ip: str) -> bool:
    """Return True if *ip* has exceeded the failure threshold."""
    attempts = _auth_failures.get(ip)
    if not attempts:
        return False
    cutoff = time.monotonic() - _AUTH_FAIL_WINDOW
    recent = [t for t in attempts if t > cutoff]
    if recent:
        _auth_failures[ip] = recent
    else:
        _auth_failures.pop(ip, None)  # Free memory for expired IPs
    return len(recent) >= _AUTH_FAIL_MAX


# ── Session-Based Dashboard Auth ──────────────────────────────
# Replaces the old HTTP Basic Auth popup with session cookies.  When auth is
# configured (bcrypt hash or legacy password exists), all API requests require
# either a valid pp_session cookie or a Bearer API key.  Static assets (/, /css/*,
# /js/*) are always exempt so the SPA can load and show its own login form.

_AUTH_EXEMPT_PATHS = frozenset({
    "/api/health",
    "/api/auth/dashboard-status",
    "/api/auth/dashboard-login",
    "/api/auth/dashboard-setup",
    # 2.16.8: favicon was returning 401 because the auth middleware
    # didn't exempt it. Browsers fetch /favicon.ico without auth
    # context on every page, producing console error noise.
    "/favicon.ico",
})
_AUTH_EXEMPT_PREFIXES = ("/css/", "/js/", "/vendor/")


@app.middleware("http")
async def session_auth_middleware(request: Request, call_next):
    # If no auth is configured, pass through everything
    if not config.is_dashboard_auth_required():
        return await call_next(request)

    path = request.url.path

    # Let SPA load (index.html) and static assets through unconditionally
    if path == "/" or path.startswith(_AUTH_EXEMPT_PREFIXES):
        return await call_next(request)

    # Exempt specific API paths (login, status, setup, health)
    if path in _AUTH_EXEMPT_PATHS:
        return await call_next(request)

    client_ip = request.client.host if request.client else "unknown"
    if _is_rate_limited(client_ip):
        return Response(status_code=429, content="Too many failed attempts. Try again later.")

    # Check API key (Authorization: Bearer pp_xxx)
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
        if config.validate_api_key(token):
            return await call_next(request)

    # Check session cookie (verify_session handles short/long expiry internally)
    cookie = request.cookies.get("pp_session")
    if cookie:
        payload = config.verify_session(cookie)
        if payload:
            return await call_next(request)

    # Not authenticated — return 401 JSON for API paths so the frontend
    # can detect it and redirect to the login page
    return JSONResponse(status_code=401, content={"error": "Authentication required"})



# Mount API routes BEFORE static file mounts. FastAPI/Starlette matches routes
# in registration order, so API endpoints (e.g. /api/*, /fa/*, /ws/*) must be
# registered first. If static file mounts were registered first, a request to
# /api/stats could be misrouted to the static file handler and 404.
app.include_router(dashboard_auth_router)  # Dashboard auth routes (/api/auth/dashboard-*)
app.include_router(router)       # Core REST API routes (/api/*)
app.include_router(fa_router)    # FurAffinity routes (/api/fa/*)
app.include_router(ws_router)    # Weasyl routes (/api/ws/*)
app.include_router(sf_router)    # SoFurry routes (/api/sf/*)
app.include_router(sqw_router)   # SquidgeWorld routes (/api/sqw/*)
app.include_router(ao3_router)   # AO3 routes (/api/ao3/*)
app.include_router(da_router)    # DeviantArt routes (/api/da/*)
app.include_router(wp_router)    # Wattpad routes (/api/wp/*)
app.include_router(ik_router)    # Itaku routes (/api/ik/*)
app.include_router(bsky_router)  # Bluesky routes (/api/bsky/*)
app.include_router(tw_router)    # X/Twitter routes (/api/tw/*)
app.include_router(posting_router)  # Posting module routes (/api/posting/*)
app.include_router(editor_router)   # Story editor routes (/api/editor/*)
app.include_router(settings_router)  # Settings sync routes (/api/settings/*)
app.include_router(accounts_router)  # Multi-account registry routes (/api/accounts/*)
app.include_router(testing_router)   # Diagnostics & testing routes (/api/testing/*)

# Serve frontend static files. config.resource_path() resolves differently
# depending on the build mode:
#   - Frozen (PyInstaller exe): looks inside the bundled _MEIPASS temp directory
#     where PyInstaller extracts data files at runtime.
#   - Dev (plain python): looks relative to the project root on disk.
# This abstraction lets the same code serve assets in both environments.
frontend_dir = config.resource_path("frontend")
app.mount("/css", StaticFiles(directory=str(frontend_dir / "css")), name="css")
app.mount("/js", StaticFiles(directory=str(frontend_dir / "js")), name="js")
app.mount("/vendor", StaticFiles(directory=str(frontend_dir / "vendor")), name="vendor")


# SPA (Single Page Application) serving pattern. The root route serves index.html,
# which bootstraps the JS frontend. Client-side routing is handled entirely in the
# browser by the JS app — there are no additional server-side page routes. Any
# navigation the user performs in the UI is managed by the frontend JS without
# additional HTML pages from the server.
#
# Cache-buster substitution: index.html ships with `?v=__APP_VERSION__` on every
# CSS and JS reference. We splice config.APP_VERSION in here at request time so
# every release automatically invalidates browser caches without requiring
# someone to remember to bump per-file `?v=NNN` numbers (the source of BUG-001
# in 2.14.6).
_index_html_cache: tuple[str, str] | None = None  # (version, rendered html)


def _render_index_html() -> str:
    global _index_html_cache
    version = config.APP_VERSION
    if _index_html_cache and _index_html_cache[0] == version:
        return _index_html_cache[1]
    raw = (frontend_dir / "index.html").read_text(encoding="utf-8")
    rendered = raw.replace("__APP_VERSION__", version)
    _index_html_cache = (version, rendered)
    return rendered


@app.get("/")
async def serve_index():
    return Response(content=_render_index_html(), media_type="text/html")


@app.get("/epub-viewer.html")
async def serve_epub_viewer():
    """In-app EPUB reader. Opened in a new tab from the editor's
    Downloads dropdown. Renders any EPUB served by /api/posting/file
    using vendored epub.js. Auth is the standard session-cookie middleware
    — opened from the authenticated dashboard, the cookie tags along
    same-origin so the EPUB fetch and the page itself both succeed.
    """
    raw = (frontend_dir / "epub-viewer.html").read_text(encoding="utf-8")
    rendered = raw.replace("__APP_VERSION__", config.APP_VERSION)
    return Response(content=rendered, media_type="text/html")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("dashboard:app", host=config.DASHBOARD_HOST, port=config.DASHBOARD_PORT)
