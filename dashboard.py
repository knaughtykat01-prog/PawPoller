"""Web dashboard — start when you want to view analytics.

Usage:
    python dashboard.py
    Open http://127.0.0.1:8420
"""

import base64
import binascii
import logging
import os
import secrets
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
#     script-src 'self'          : all JS loaded via <script src=...>, zero inline
#     style-src 'self' 'unsafe-inline' : CSS files + inline style= attributes
#     img-src 'self' https:      : local proxy + platform CDN thumbnails
#     connect-src 'self'         : all API calls are same-origin
#     frame-ancestors 'none'     : no embedding allowed (supercedes X-Frame-Options)

_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Content-Security-Policy": (
        "default-src 'self'; "
        "script-src 'self'; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' https:; "
        "connect-src 'self'; "
        "frame-ancestors 'none'"
    ),
}


@app.middleware("http")
async def security_headers_middleware(request: Request, call_next):
    response = await call_next(request)
    for header, value in _SECURITY_HEADERS.items():
        response.headers[header] = value
    return response


# ── Optional Basic Auth for Server Deployments ─────────────────
# When DASHBOARD_PASSWORD is set (via environment variable or settings.json),
# all requests require HTTP Basic Auth. This protects server/Docker deployments
# where the dashboard is exposed on 0.0.0.0. Desktop mode (127.0.0.1) typically
# doesn't need this, so it's opt-in.

def _get_dashboard_password() -> str:
    """Resolve dashboard password from env or settings (checked on every request)."""
    return os.environ.get("DASHBOARD_PASSWORD") or config.get_settings().get("dashboard_password") or ""


def _get_dashboard_user() -> str:
    return os.environ.get("DASHBOARD_USER", "admin")


# ── Brute-Force Rate Limiting ─────────────────────────────────
# Simple in-memory tracker: after 10 failed auth attempts from the same IP
# within 5 minutes, all further requests from that IP get 429 Too Many Requests.
# Single-process server so in-memory state is sufficient.  Clears on restart.
_AUTH_FAIL_WINDOW = 300      # seconds (5 minutes)
_AUTH_FAIL_MAX = 10          # max failures before lockout
_auth_failures: dict[str, list[float]] = {}   # IP -> list of failure timestamps


def _record_auth_failure(ip: str) -> None:
    """Record a failed auth attempt from *ip*."""
    now = time.monotonic()
    attempts = _auth_failures.setdefault(ip, [])
    attempts.append(now)
    # Prune entries older than the window
    cutoff = now - _AUTH_FAIL_WINDOW
    _auth_failures[ip] = [t for t in attempts if t > cutoff]


def _is_rate_limited(ip: str) -> bool:
    """Return True if *ip* has exceeded the failure threshold."""
    attempts = _auth_failures.get(ip)
    if not attempts:
        return False
    cutoff = time.monotonic() - _AUTH_FAIL_WINDOW
    recent = [t for t in attempts if t > cutoff]
    _auth_failures[ip] = recent  # Lazy prune
    return len(recent) >= _AUTH_FAIL_MAX


@app.middleware("http")
async def basic_auth_middleware(request: Request, call_next):
    password = _get_dashboard_password()
    if not password:
        return await call_next(request)

    client_ip = request.client.host if request.client else "unknown"

    # Rate-limit check before processing credentials
    if _is_rate_limited(client_ip):
        return Response(status_code=429, content="Too many failed attempts. Try again later.")

    user_expected = _get_dashboard_user()
    auth = request.headers.get("Authorization")
    if auth and auth.startswith("Basic "):
        try:
            decoded = base64.b64decode(auth[6:]).decode("utf-8")
            user, passwd = decoded.split(":", 1)
            user_ok = secrets.compare_digest(user, user_expected)
            pass_ok = secrets.compare_digest(passwd, password)
            if user_ok and pass_ok:
                # Successful auth — clear any failure history for this IP
                _auth_failures.pop(client_ip, None)
                return await call_next(request)
        except (ValueError, UnicodeDecodeError, binascii.Error):
            pass  # Malformed auth header

    _record_auth_failure(client_ip)
    return Response(
        status_code=401,
        content="Authentication required",
        headers={"WWW-Authenticate": 'Basic realm="PawPoller"'},
    )


# Mount API routes BEFORE static file mounts. FastAPI/Starlette matches routes
# in registration order, so API endpoints (e.g. /api/*, /fa/*, /ws/*) must be
# registered first. If static file mounts were registered first, a request to
# /api/stats could be misrouted to the static file handler and 404.
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

# Serve frontend static files. config.resource_path() resolves differently
# depending on the build mode:
#   - Frozen (PyInstaller exe): looks inside the bundled _MEIPASS temp directory
#     where PyInstaller extracts data files at runtime.
#   - Dev (plain python): looks relative to the project root on disk.
# This abstraction lets the same code serve assets in both environments.
frontend_dir = config.resource_path("frontend")
app.mount("/css", StaticFiles(directory=str(frontend_dir / "css")), name="css")
app.mount("/js", StaticFiles(directory=str(frontend_dir / "js")), name="js")


# SPA (Single Page Application) serving pattern. The root route serves index.html,
# which bootstraps the JS frontend. Client-side routing is handled entirely in the
# browser by the JS app — there are no additional server-side page routes. Any
# navigation the user performs in the UI is managed by the frontend JS without
# additional HTML pages from the server.
@app.get("/")
async def serve_index():
    return FileResponse(str(frontend_dir / "index.html"))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("dashboard:app", host=config.DASHBOARD_HOST, port=config.DASHBOARD_PORT)
