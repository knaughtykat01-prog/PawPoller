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
    settings = config.get_settings()
    return {
        "ok": True,
        "version": config.APP_VERSION,
        "timestamp": mtime,
        "credential_mode": settings.get("credential_mode", "cloud"),
        "total_keys": len(settings),
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
    Also reports ``runtime_mode`` (desktop vs server) so the frontend can
    skip the local-vs-server question on the headless container — there
    the answer is always "server".
    """
    settings = config.get_settings()
    from auth.browser_login import is_browser_login_available
    runtime_mode = "desktop" if is_browser_login_available() else "server"
    return {
        "setup_complete": settings.get("setup_complete", False),
        "setup_mode": settings.get("setup_mode"),
        "runtime_mode": runtime_mode,
        "polling_owner": config.get_polling_owner(runtime_mode),
        "has_archive_path": bool(settings.get("posting_story_archive_path")),
        "platforms_connected": sum(
            1 for key in (
                "username", "fa_cookie_a", "sf_username", "ws_api_key",
                "ao3_username", "sqw_username", "bsky_identifier",
                "da_refresh_token", "wp_username", "ik_token", "tw_api_key",
                "mast_access_token", "tum_api_key", "pix_refresh_token", "thr_access_token",
                "ig_access_token",
            )
            if settings.get(key)
        ),
    }


@settings_router.post("/setup-reset")
async def reset_setup():
    """Clear ``setup_complete`` so the user goes back through the wizard.

    Doesn't touch credentials, the chosen mode, or pairing config — just
    flips the "first-run done" flag. Used by the Settings page's
    "Re-run setup wizard" button.
    """
    config.save_settings({"setup_complete": False})
    return {"ok": True}


@settings_router.post("/setup-complete")
async def mark_setup_complete():
    """Mark the first-run setup wizard as completed.

    Writes setup_complete=true into settings.json so the wizard is not
    shown again on subsequent launches.
    """
    config.save_settings({"setup_complete": True})
    return {"ok": True}


class SetupModeRequest(BaseModel):
    mode: str  # standalone | paired_desktop | server
    posting_server_url: str | None = None
    posting_server_api_key: str | None = None


@settings_router.post("/setup-mode")
async def set_setup_mode(req: SetupModeRequest):
    """Persist the chosen setup mode (and pairing creds, if paired_desktop).

    Validates the mode is one of the known values. For ``paired_desktop``,
    requires ``posting_server_url`` + ``posting_server_api_key``. The
    polling-owner gate in main.py reads ``setup_mode`` on startup, so the
    user must restart for the gate to take effect — but auto-sync picks
    up the new server URL immediately.
    """
    if req.mode not in config.VALID_SETUP_MODES:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown setup_mode: {req.mode}. "
                   f"Valid: {', '.join(sorted(config.VALID_SETUP_MODES))}",
        )

    update: dict = {"setup_mode": req.mode}
    if req.mode == config.SETUP_MODE_PAIRED:
        url = (req.posting_server_url or "").strip().rstrip("/")
        api_key = (req.posting_server_api_key or "").strip()
        if not url or not api_key:
            raise HTTPException(
                status_code=400,
                detail="paired_desktop mode requires posting_server_url and posting_server_api_key",
            )
        update["posting_server_url"] = url
        update["posting_server_api_key"] = api_key
        update["auto_sync_enabled"] = True
    elif req.mode == config.SETUP_MODE_STANDALONE:
        # Pure standalone — explicitly clear any stale pairing config so
        # auto-sync stops trying to talk to a server the user no longer
        # wants paired. We deliberately leave the API key alone (the user
        # may have minted it for another purpose).
        update["posting_server_url"] = ""
        update["auto_sync_enabled"] = False

    config.save_settings(update)
    logger.info("setup_mode set to %r (paired_url=%r)",
                req.mode, update.get("posting_server_url"))

    # Immediate first-pull on paired-desktop so the user sees the server's
    # settings right away instead of waiting for the 5-minute pull cadence.
    pulled_keys = 0
    if req.mode == config.SETUP_MODE_PAIRED:
        try:
            import auto_sync
            if auto_sync.pull_once():
                # pull_once doesn't surface a count, so re-read settings to
                # tell the user how much actually arrived. Approximate but
                # informative.
                pulled_keys = len(config.get_settings())
        except Exception as e:
            logger.warning("Initial pairing pull failed: %s", e)

    return {
        "ok": True,
        "setup_mode": req.mode,
        "pulled_keys": pulled_keys,
    }


class PairingTestRequest(BaseModel):
    posting_server_url: str
    posting_server_api_key: str


@settings_router.post("/pair-test")
async def pair_test(req: PairingTestRequest):
    """Validate pairing credentials by probing the remote server.

    Calls ``GET /api/settings/sync/status`` on the target. Used by the
    setup wizard to give immediate feedback before the user commits to
    the pairing. Returns the remote ``version`` and ``timestamp`` on
    success so the wizard can warn about version mismatches.

    Requires HTTPS for non-localhost targets — same rule as auto_sync's
    push path, since this endpoint asks the user to send their bearer
    token to a URL we're about to validate.
    """
    import httpx

    url = req.posting_server_url.strip().rstrip("/")
    api_key = req.posting_server_api_key.strip()
    if not url or not api_key:
        return {"ok": False, "error": "URL and API key are required"}

    is_loopback = "localhost" in url or "127.0.0.1" in url
    if not is_loopback and not url.lower().startswith("https://"):
        return {
            "ok": False,
            "error": "Server URL must use https:// (the API key is sent as a bearer token).",
        }

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{url}/api/settings/sync/status",
                headers={"Authorization": f"Bearer {api_key}"},
            )
    except Exception as e:
        return {"ok": False, "error": f"Could not reach server: {e}"}

    if resp.status_code == 401:
        return {"ok": False, "error": "API key rejected (HTTP 401). Check the key on the server."}
    if resp.status_code != 200:
        return {"ok": False, "error": f"Server returned HTTP {resp.status_code}"}

    try:
        body = resp.json()
    except Exception:
        return {"ok": False, "error": "Server returned non-JSON response"}

    return {
        "ok": True,
        "remote_version": body.get("version"),
        "remote_timestamp": body.get("timestamp"),
        "local_version": config.APP_VERSION,
        "version_match": body.get("version") == config.APP_VERSION,
    }


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


# ── Uninstall ────────────────────────────────────────────────────────
# In-app uninstall flow (Settings → General → Danger zone). See
# uninstall.py for the per-OS detection + cleanup scripts.

class UninstallRequest(BaseModel):
    remove_data: bool = True
    remove_autostart: bool = True
    remove_app: bool = True
    confirm: str = ""   # must equal "UNINSTALL" to proceed — typed by user


@settings_router.get("/uninstall/plan")
async def get_uninstall_plan() -> dict:
    """Return what an uninstall would touch — for the confirm dialog.

    Pure / no side effects. Frontend renders the resulting paths +
    install-type so the user can sanity-check before confirming.
    """
    import uninstall  # lazy import — keeps server.py startup snappy
    plan = uninstall.detect()
    return {
        "install_type": plan.install_type.value,
        "app_path": plan.app_path,
        "data_dir": plan.data_dir,
        "autostart_target": plan.autostart_target,
        "has_keyring_key": plan.has_keyring_key,
    }


@settings_router.post("/uninstall")
async def do_uninstall(req: UninstallRequest) -> dict:
    """Kick off the uninstall.

    Requires `confirm: "UNINSTALL"` in the body — typed by the user in the
    dialog to prevent accidental fires (and to make scripted/curl calls
    explicit about intent).

    Spawns a detached cleanup script and returns immediately. The frontend
    is responsible for showing a "goodbye" screen; the server shuts itself
    down via os._exit shortly after.
    """
    if req.confirm != "UNINSTALL":
        raise HTTPException(
            status_code=400,
            detail='Set "confirm": "UNINSTALL" in the request body to proceed.',
        )

    import uninstall
    result = uninstall.execute(
        remove_data=req.remove_data,
        remove_autostart=req.remove_autostart,
        remove_app=req.remove_app,
    )

    # Schedule app shutdown after the response is sent. asyncio.get_event_loop
    # + call_later gives the response time to flush before we yank the process.
    import asyncio
    import os as _os
    asyncio.get_event_loop().call_later(2.0, lambda: _os._exit(0))

    result["shutdown_in_seconds"] = 2
    return result


# ── Accounts CRUD (multi-account) ─────────────────────────────────────
# Manages the per-platform account registry. The default account keeps the
# legacy flat credential keys; extra accounts store credentials under
# acct_<id>_<field> keys (config.account_setting_key / get_account_credentials).

accounts_router = APIRouter(prefix="/api/accounts", tags=["accounts"])


class AccountCreate(BaseModel):
    platform: str
    label: str = ""
    handle: str = ""
    enabled: bool = True
    credentials: dict = {}   # {canonical_field: value}


class AccountUpdate(BaseModel):
    label: str | None = None
    handle: str | None = None
    enabled: bool | None = None
    credentials: dict | None = None


def _accounts_conn():
    from database import db
    return db.get_connection()


def _platform_fields_meta() -> dict:
    """Per-platform credential field list + secret flags, for the UI form."""
    return {
        plat: [{"field": f, "secret": config.is_credential_key(f)} for f in fields]
        for plat, fields in config.PLATFORM_CREDENTIAL_FIELDS.items()
    }


def _save_account_credentials(account: dict, creds: dict | None) -> None:
    """Persist provided credential fields under the account's settings keys."""
    if not creds:
        return
    platform = account["platform"]
    is_default = bool(account["is_default"])
    allowed = set(config.PLATFORM_CREDENTIAL_FIELDS.get(platform, []))
    payload = {}
    for field, value in creds.items():
        if field in allowed:
            payload[config.account_setting_key(account["account_id"], field, is_default)] = value
    if payload:
        config.save_settings(payload)


@accounts_router.get("")
async def list_accounts_endpoint(platform: str | None = None):
    """List accounts (optionally for one platform) + field metadata for forms."""
    from database import accounts as adb
    conn = _accounts_conn()
    try:
        # Ensure any platform that has credentials but no account row yet gets
        # its default account before we list — so freshly connected platforms
        # (e.g. X / Bluesky) show up immediately instead of after the next poll
        # cycle or restart. Idempotent; get_default_account_id self-commits.
        adb.seed_default_accounts(conn, config.get_settings())
        rows = adb.list_accounts(conn, platform=platform)
        # Attach per-account stat rollups so the UI can show numbers side by side.
        for r in rows:
            r["stats"] = adb.account_stats(conn, r["account_id"], r["platform"])
    finally:
        conn.close()
    return {
        "accounts": rows,
        "platform_names": adb.PLATFORM_NAMES,
        "platform_fields": _platform_fields_meta(),
    }


@accounts_router.post("")
async def create_account_endpoint(req: AccountCreate):
    """Create a new account on a platform and store its credentials."""
    from database import accounts as adb
    if req.platform not in adb.PLATFORMS:
        raise HTTPException(status_code=400, detail=f"Unknown platform: {req.platform}")
    conn = _accounts_conn()
    try:
        handle = req.handle or adb.derive_handle(req.platform, req.credentials or {})
        aid = adb.create_account(conn, req.platform, req.label,
                                 handle=handle, enabled=req.enabled)
        account = adb.get_account(conn, aid)
    finally:
        conn.close()
    _save_account_credentials(account, req.credentials)
    logger.info("Created %s account #%s (%s)", req.platform, aid, account.get("label"))
    return {"ok": True, "account": account}


@accounts_router.patch("/{account_id}")
async def update_account_endpoint(account_id: int, req: AccountUpdate):
    """Rename / enable / disable an account and optionally update credentials."""
    from database import accounts as adb
    conn = _accounts_conn()
    try:
        account = adb.get_account(conn, account_id)
        if not account:
            raise HTTPException(status_code=404, detail="Account not found")
        adb.update_account(conn, account_id, label=req.label,
                           handle=req.handle, enabled=req.enabled)
        account = adb.get_account(conn, account_id)
    finally:
        conn.close()
    if req.credentials:
        _save_account_credentials(account, req.credentials)
    return {"ok": True, "account": account}


@accounts_router.delete("/{account_id}")
async def delete_account_endpoint(account_id: int):
    """Delete a non-default account and its namespaced credentials.

    Refuses to delete a platform's default account — that account owns the
    legacy flat credential keys and the pre-multi-account data history.
    """
    from database import accounts as adb
    conn = _accounts_conn()
    try:
        account = adb.get_account(conn, account_id)
        if not account:
            raise HTTPException(status_code=404, detail="Account not found")
        if account["is_default"]:
            raise HTTPException(
                status_code=400,
                detail="Cannot delete the default account for a platform.",
            )
        adb.delete_account(conn, account_id)
    finally:
        conn.close()
    # Remove the account's namespaced credential keys.
    keys = [config.account_setting_key(account_id, f, False)
            for f in config.PLATFORM_CREDENTIAL_FIELDS.get(account["platform"], [])]
    if keys:
        config.delete_settings_keys(keys)
    logger.info("Deleted %s account #%s", account["platform"], account_id)
    return {"ok": True}


class PersonaAssign(BaseModel):
    persona_id: int | None = None


@accounts_router.post("/{account_id}/persona")
async def assign_account_persona_endpoint(account_id: int, req: PersonaAssign):
    """Assign an account to a persona (or clear it with persona_id=null)."""
    from database import accounts as adb, personas as pdb
    conn = _accounts_conn()
    try:
        if not adb.get_account(conn, account_id):
            raise HTTPException(status_code=404, detail="Account not found")
        if req.persona_id is not None and not pdb.get_persona(conn, req.persona_id):
            raise HTTPException(status_code=404, detail="Persona not found")
        pdb.assign_account_persona(conn, account_id, req.persona_id)
    finally:
        conn.close()
    return {"ok": True}


# ── Personas CRUD (cross-platform account grouping) ───────────────────
# A persona bundles accounts across platforms into one logical identity. The
# account→persona link lives on accounts.persona_id (the assign endpoint above);
# this router manages the persona rows + per-persona combined stats.

personas_router = APIRouter(prefix="/api/personas", tags=["personas"])


class PersonaCreate(BaseModel):
    name: str
    color: str = "#6c8cff"


class PersonaUpdate(BaseModel):
    name: str | None = None
    color: str | None = None
    sort_order: int | None = None


@personas_router.get("")
async def list_personas_endpoint():
    """All personas (each with combined stats + its accounts) + the Unassigned bucket."""
    from database import accounts as adb, personas as pdb
    conn = _accounts_conn()
    try:
        groups = pdb.list_accounts_by_persona(conn)
        out = []
        for p in pdb.list_personas(conn):
            pid = p["persona_id"]
            p["accounts"] = groups.get(pid, [])
            p["stats"] = pdb.persona_stats(conn, pid)
            out.append(p)
        unassigned = groups.get(None, [])
    finally:
        conn.close()
    return {"personas": out, "unassigned": unassigned, "platform_names": adb.PLATFORM_NAMES}


@personas_router.get("/{persona_id}")
async def get_persona_endpoint(persona_id: int):
    """One persona + its accounts (each with per-account stats) + combined stats."""
    from database import accounts as adb, personas as pdb
    conn = _accounts_conn()
    try:
        p = pdb.get_persona(conn, persona_id)
        if not p:
            raise HTTPException(status_code=404, detail="Persona not found")
        accts = [a for a in adb.list_accounts(conn) if a.get("persona_id") == persona_id]
        for a in accts:
            a["stats"] = adb.account_stats(conn, a["account_id"], a["platform"])
        p["accounts"] = accts
        p["stats"] = pdb.persona_stats(conn, persona_id)
    finally:
        conn.close()
    return {"persona": p, "platform_names": adb.PLATFORM_NAMES}


@personas_router.post("")
async def create_persona_endpoint(req: PersonaCreate):
    from database import personas as pdb
    conn = _accounts_conn()
    try:
        pid = pdb.create_persona(conn, req.name, color=req.color)
        persona = pdb.get_persona(conn, pid)
    finally:
        conn.close()
    logger.info("Created persona #%s (%s)", pid, req.name)
    return {"ok": True, "persona": persona}


@personas_router.patch("/{persona_id}")
async def update_persona_endpoint(persona_id: int, req: PersonaUpdate):
    from database import personas as pdb
    conn = _accounts_conn()
    try:
        if not pdb.get_persona(conn, persona_id):
            raise HTTPException(status_code=404, detail="Persona not found")
        pdb.update_persona(conn, persona_id, name=req.name, color=req.color,
                           sort_order=req.sort_order)
        persona = pdb.get_persona(conn, persona_id)
    finally:
        conn.close()
    return {"ok": True, "persona": persona}


@personas_router.delete("/{persona_id}")
async def delete_persona_endpoint(persona_id: int):
    """Delete a persona; its accounts fall back to Unassigned (persona_id NULL)."""
    from database import personas as pdb
    conn = _accounts_conn()
    try:
        if not pdb.get_persona(conn, persona_id):
            raise HTTPException(status_code=404, detail="Persona not found")
        pdb.delete_persona(conn, persona_id)
    finally:
        conn.close()
    logger.info("Deleted persona #%s", persona_id)
    return {"ok": True}
