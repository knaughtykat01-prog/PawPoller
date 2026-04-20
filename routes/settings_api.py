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
    count = config.migrate_to_local_vault()
    logger.info("Vault enabled: %d credential fields migrated to vault", count)
    return {"ok": True, "mode": "local", "fields_migrated": count}


@settings_router.post("/vault/disable")
async def disable_vault():
    """Switch back to cloud/plaintext credential mode."""
    count = config.migrate_to_cloud()
    logger.info("Vault disabled: %d credential fields migrated to plaintext", count)
    return {"ok": True, "mode": "cloud", "fields_migrated": count}


@settings_router.get("/vault/status")
async def vault_status():
    """Check vault status."""
    mode = config.get_credential_mode()
    vault_exists = config.VAULT_PATH.exists()
    return {"mode": mode, "vault_exists": vault_exists}
