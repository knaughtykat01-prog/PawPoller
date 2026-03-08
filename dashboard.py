"""Web dashboard — start when you want to view analytics.

Usage:
    python dashboard.py
    Open http://127.0.0.1:8420
"""

import logging
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse

import config
from database.db import init_db
from routes.api import router
from routes.fa_api import fa_router
from routes.ws_api import ws_router
from routes.sf_api import sf_router
from routes.sqw_api import sqw_router

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


# Mount API routes BEFORE static file mounts. FastAPI/Starlette matches routes
# in registration order, so API endpoints (e.g. /api/*, /fa/*, /ws/*) must be
# registered first. If static file mounts were registered first, a request to
# /api/stats could be misrouted to the static file handler and 404.
app.include_router(router)       # Core REST API routes (/api/*)
app.include_router(fa_router)    # FurAffinity routes (/api/fa/*)
app.include_router(ws_router)    # Weasyl routes (/api/ws/*)
app.include_router(sf_router)    # SoFurry routes (/api/sf/*)
app.include_router(sqw_router)   # SquidgeWorld routes (/api/sqw/*)

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
