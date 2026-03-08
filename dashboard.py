"""Web dashboard — start when you want to view analytics.

Usage:
    python dashboard.py
    Open http://127.0.0.1:8420
"""

import base64
import logging
import os
import secrets
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
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


# Global exception handler — catches any unhandled exception that escapes a route
# handler and returns a clean JSON 500 instead of letting uvicorn emit a bare
# traceback or HTML error page. Also logs the full stack trace (exc_info=True) so
# errors are visible in the console/log without exposing internals to the client.
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error("Unhandled error on %s %s: %s", request.method, request.url.path, exc, exc_info=True)
    return JSONResponse(status_code=500, content={"error": str(exc)})


# ── Optional Basic Auth for Server Deployments ─────────────────
# When DASHBOARD_PASSWORD is set (via environment variable or settings.json),
# all requests require HTTP Basic Auth. This protects server/Docker deployments
# where the dashboard is exposed on 0.0.0.0. Desktop mode (127.0.0.1) typically
# doesn't need this, so it's opt-in.

_dashboard_password = os.environ.get("DASHBOARD_PASSWORD") or config.get_settings().get("dashboard_password")

if _dashboard_password:
    _dashboard_user = os.environ.get("DASHBOARD_USER", "admin")
    logger.info("Dashboard authentication enabled (user: %s)", _dashboard_user)

    @app.middleware("http")
    async def basic_auth_middleware(request: Request, call_next):
        auth = request.headers.get("Authorization")
        if auth and auth.startswith("Basic "):
            try:
                decoded = base64.b64decode(auth[6:]).decode("utf-8")
                user, passwd = decoded.split(":", 1)
                if secrets.compare_digest(user, _dashboard_user) and secrets.compare_digest(passwd, _dashboard_password):
                    return await call_next(request)
            except Exception:
                pass
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
