"""Settings sync API routes (Phase 7a).

Provides a single sync endpoint for desktop ↔ server credential sharing.
Auth is handled by the dashboard middleware (session cookie or API key).
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

import config

logger = logging.getLogger(__name__)

settings_router = APIRouter(prefix="/api/settings", tags=["settings"])


class SyncRequest(BaseModel):
    settings: dict = {}
    timestamp: float | None = None
    mode: str = "pull"  # "pull" | "push"


class SyncResponse(BaseModel):
    ok: bool
    settings: dict
    timestamp: float
    mode: str
    keys_merged: int = 0


@settings_router.post("/sync")
async def sync_settings(req: SyncRequest) -> SyncResponse:
    """Sync settings between desktop and server.

    - **pull**: Returns current server settings + timestamp.
    - **push**: Merges incoming settings into server, returns merged result.

    Auth: Requires valid session cookie or API key (enforced by middleware).
    SYNC_EXCLUDE keys are filtered on both directions.
    """
    if req.mode not in ("pull", "push"):
        raise HTTPException(status_code=400, detail=f"Unknown mode: {req.mode}")

    if req.mode == "pull":
        data, mtime = config.get_settings_for_sync()
        logger.info("Settings sync pull: %d keys", len(data))
        return SyncResponse(
            ok=True,
            settings=data,
            timestamp=mtime,
            mode="pull",
        )

    # Push mode
    if not req.settings:
        raise HTTPException(status_code=400, detail="Push requires non-empty settings")

    incoming_keys = set(req.settings.keys()) - config.SYNC_EXCLUDE
    merged = config.merge_synced_settings(req.settings, req.timestamp)
    data, mtime = config.get_settings_for_sync()
    logger.info("Settings sync push: %d keys merged", len(incoming_keys))

    return SyncResponse(
        ok=True,
        settings=data,
        timestamp=mtime,
        mode="push",
        keys_merged=len(incoming_keys),
    )


@settings_router.get("/sync/status")
async def sync_status():
    """Check sync readiness — returns server version and settings timestamp."""
    mtime = config.SETTINGS_PATH.stat().st_mtime if config.SETTINGS_PATH.exists() else 0
    return {
        "ok": True,
        "version": config.APP_VERSION,
        "timestamp": mtime,
        "credential_mode": config.get_settings().get("credential_mode", "cloud"),
        "total_keys": len(config.get_settings()),
    }


# ── Credential vault (Phase 7b) ────────────────────────────────

@settings_router.post("/vault/enable")
async def enable_vault():
    """Switch to local-only encrypted credential mode."""
    try:
        count = config.migrate_to_local_vault()
    except Exception as e:
        logger.error("Vault enable failed: %s", e, exc_info=True)
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}
    logger.info("Vault enabled: %d credential fields migrated to vault", count)
    return {"ok": True, "mode": "local", "fields_migrated": count}


@settings_router.post("/vault/disable")
async def disable_vault():
    """Switch back to cloud/plaintext credential mode."""
    try:
        count = config.migrate_to_cloud()
    except Exception as e:
        logger.error("Vault disable failed: %s", e, exc_info=True)
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}
    logger.info("Vault disabled: %d credential fields migrated to plaintext", count)
    return {"ok": True, "mode": "cloud", "fields_migrated": count}


@settings_router.get("/vault/status")
async def vault_status():
    """Check vault status."""
    mode = config.get_credential_mode()
    vault_exists = config.VAULT_PATH.exists()
    return {"mode": mode, "vault_exists": vault_exists}


# ── Setup wizard status (first-run detection) ────────────────

@settings_router.get("/setup-status")
async def setup_status():
    """Check first-run setup wizard state.

    Returns whether initial setup has been completed, plus a summary of
    what has been configured so the wizard can pre-populate or skip steps.
    """
    settings = config.get_settings()
    return {
        "setup_complete": settings.get("setup_complete", False),
        "has_archive_path": bool(settings.get("posting_story_archive_path")),
        "platforms_connected": sum(
            1 for key in (
                "username", "fa_cookie_a", "sf_username", "ws_api_key",
                "ao3_username", "sqw_username", "bsky_identifier",
                "da_refresh_token", "wp_username", "ik_token", "tw_api_key",
            )
            if settings.get(key)
        ),
    }


@settings_router.post("/setup-complete")
async def mark_setup_complete():
    """Mark the first-run setup wizard as completed.

    Writes setup_complete=true into settings.json so the wizard is not
    shown again on subsequent launches.
    """
    config.save_settings({"setup_complete": True})
    return {"ok": True}


# ── Browser login (embedded pywebview popup) ──────────────────

class BrowserLoginRequest(BaseModel):
    extra_fields: dict = {}


@settings_router.get("/browser-login/platforms")
async def browser_login_platforms():
    """List platforms that support embedded browser login.

    Returns availability status (True only in desktop mode where pywebview
    is installed) and the per-platform config including any extra fields
    the user needs to fill in before launching the login window.
    """
    from auth.browser_login import get_supported_platforms, is_browser_login_available
    return {
        "available": is_browser_login_available(),
        "platforms": get_supported_platforms(),
    }


@settings_router.post("/browser-login/{platform}")
async def browser_login(platform: str, req: BrowserLoginRequest | None = None):
    """Launch an embedded browser window for platform authentication.

    Only works in desktop mode (pywebview must be installed).  Opens the
    platform's login page in a native popup window.  The user logs in
    normally, and cookies/tokens are captured automatically on success.

    The endpoint runs the login in a background thread and blocks until
    the user completes login or closes the window (up to 5 minutes).

    NOTE: This is a long-running request -- the response arrives only
    after the login window closes.  The frontend should show a spinner.
    """
    from auth.browser_login import login_via_browser, is_browser_login_available, PLATFORM_LOGIN

    if not is_browser_login_available():
        raise HTTPException(
            status_code=400,
            detail="Browser login is only available in desktop mode (pywebview required).",
        )

    if platform not in PLATFORM_LOGIN:
        raise HTTPException(
            status_code=404,
            detail=f"Platform '{platform}' does not support browser login. "
                   f"Supported: {', '.join(PLATFORM_LOGIN.keys())}",
        )

    extra_fields = req.extra_fields if req else {}

    # Run the blocking login in a thread so we don't block the event loop
    import asyncio
    loop = asyncio.get_event_loop()
    try:
        creds = await loop.run_in_executor(
            None, lambda: login_via_browser(platform, extra_fields)
        )
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    if creds is None:
        return {"ok": False, "message": "Login cancelled or timed out."}

    return {
        "ok": True,
        "message": f"Successfully logged in to {PLATFORM_LOGIN[platform]['name']}.",
        "keys_saved": list(creds.keys()),
    }
