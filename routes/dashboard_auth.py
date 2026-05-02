"""Dashboard authentication API endpoints.

Self-hosted auth system for PawPoller: session cookies, bcrypt password
hashing, optional TOTP 2FA, API keys for programmatic access, and optional
Cloudflare Turnstile bot protection.

This is SEPARATE from the Inkbunny platform auth (routes/api.py /api/auth/*).
Dashboard auth controls who can access the PawPoller dashboard itself.
Inkbunny auth validates credentials against the live Inkbunny API for polling.
"""

from __future__ import annotations
import hashlib
import logging
import secrets
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import JSONResponse

import config

logger = logging.getLogger(__name__)
dashboard_auth_router = APIRouter(prefix="/api/auth")


# -- Dashboard Status --------------------------------------------------------

@dashboard_auth_router.get("/dashboard-status")
def dashboard_status(request: Request):
    """Return current dashboard auth state for the frontend.

    Always exempt from auth so the SPA can decide which login form to show.
    Returns whether auth is required, whether the current request is
    authenticated (valid session cookie), and optional feature flags.
    """
    auth_required = config.is_dashboard_auth_required()
    authenticated = False

    if auth_required:
        cookie = request.cookies.get("pp_session")
        if cookie:
            payload = config.verify_session(cookie)
            authenticated = payload is not None

    settings = config.get_settings()
    totp_enabled = bool(settings.get("auth_totp_secret") and settings.get("auth_totp_enabled"))
    turnstile_site_key = settings.get("turnstile_site_key", "")

    return {
        "auth_required": auth_required,
        "authenticated": authenticated,
        "totp_enabled": totp_enabled,
        "turnstile_site_key": turnstile_site_key if auth_required else "",
    }


# -- Dashboard Login ---------------------------------------------------------

@dashboard_auth_router.post("/dashboard-login")
async def dashboard_login(request: Request, body: dict):
    """Validate credentials and set a session cookie.

    Accepts username, password, optional totp_code, optional turnstile_token.
    On success, sets a signed pp_session cookie.  The "remember" field
    controls cookie max_age: True = 30 days, False = 24 hours (session).
    """
    # Import rate limiting helpers from dashboard.py (same process)
    from dashboard import _record_auth_failure, _is_rate_limited

    client_ip = request.client.host if request.client else "unknown"
    if _is_rate_limited(client_ip):
        raise HTTPException(429, "Too many failed attempts. Try again later.")

    username = body.get("username", "").strip()
    password = body.get("password", "")
    totp_code = body.get("totp_code", "").strip()
    remember = body.get("remember", False)
    turnstile_token = body.get("turnstile_token", "")

    settings = config.get_settings()

    # Validate Turnstile if configured
    turnstile_secret = settings.get("turnstile_secret_key", "")
    if turnstile_secret:
        if not await _verify_turnstile(turnstile_token, turnstile_secret, client_ip):
            _record_auth_failure(client_ip)
            raise HTTPException(403, "Bot verification failed. Please try again.")

    # Check credentials
    stored_hash = settings.get("auth_password_hash", "")
    stored_user = settings.get("auth_username", "admin")

    if not stored_hash:
        # Legacy plaintext password (pre-migration)
        legacy_pw = settings.get("dashboard_password") or ""
        if not legacy_pw:
            raise HTTPException(400, "Dashboard auth is not configured.")
        if username != stored_user or password != legacy_pw:
            _record_auth_failure(client_ip)
            raise HTTPException(401, "Invalid username or password.")
    else:
        if username != stored_user or not config.verify_password(password, stored_hash):
            _record_auth_failure(client_ip)
            raise HTTPException(401, "Invalid username or password.")

    # Check TOTP if enabled
    if settings.get("auth_totp_secret") and settings.get("auth_totp_enabled"):
        import pyotp
        totp = pyotp.TOTP(settings["auth_totp_secret"])
        if not totp_code or not totp.verify(totp_code, valid_window=1):
            _record_auth_failure(client_ip)
            raise HTTPException(401, "Invalid or missing 2FA code.")

    # Success — clear rate limit history and create session
    from dashboard import _auth_failures
    _auth_failures.pop(client_ip, None)

    max_age = 30 * 86400 if remember else 86400
    payload = {"u": username}
    if remember:
        payload["r"] = True
    cookie_value = config.sign_session(payload)

    response = JSONResponse({"status": "success", "message": f"Welcome, {username}!"})
    response.set_cookie(
        key="pp_session",
        value=cookie_value,
        max_age=max_age,
        httponly=True,
        # 2.16.8: lax instead of strict — prod live-monitor caught a
        # recurring pattern where the browser dropped the cookie under
        # specific idle/refresh conditions, producing periodic 401
        # bursts (9× polling progress + the next SPA fetch all 401),
        # then immediately recovering on the next tick. Strict was
        # never necessary anyway: dashboard is HttpOnly + JSON-only
        # state-change endpoints, so CSRF surface is already closed.
        samesite="lax",
        secure=request.url.scheme == "https",
        path="/",
    )
    return response


# -- Dashboard Setup (first-time) -------------------------------------------

@dashboard_auth_router.post("/dashboard-setup")
def dashboard_setup(body: dict):
    """First-time password setup.  Only works when no auth is configured.

    This endpoint is exempt from auth (obviously — there's no password yet).
    Once a password hash is stored, this endpoint returns 403.
    """
    settings = config.get_settings()
    if settings.get("auth_password_hash") or settings.get("dashboard_password"):
        raise HTTPException(403, "Dashboard auth is already configured. Use change-password instead.")

    username = body.get("username", "admin").strip() or "admin"
    password = body.get("password", "")
    confirm = body.get("confirm", "")

    if not password:
        raise HTTPException(400, "Password is required.")
    if len(password) < 8:
        raise HTTPException(400, "Password must be at least 8 characters.")
    if password != confirm:
        raise HTTPException(400, "Passwords do not match.")

    config.save_settings({
        "auth_username": username,
        "auth_password_hash": config.hash_password(password),
    })
    config.invalidate_auth_required_cache()
    logger.info("Dashboard auth configured for user '%s'", username)
    return {"status": "success", "message": f"Dashboard auth configured for {username}."}


# -- Dashboard Logout --------------------------------------------------------

@dashboard_auth_router.post("/dashboard-logout")
def dashboard_logout(request: Request):
    """Clear the session cookie."""
    response = JSONResponse({"status": "success", "message": "Logged out."})
    response.delete_cookie("pp_session", path="/")
    return response


# -- Change Password ---------------------------------------------------------

@dashboard_auth_router.post("/dashboard-change-password")
def dashboard_change_password(body: dict):
    """Change the dashboard password.  Requires current password."""
    current = body.get("current_password", "")
    new_password = body.get("new_password", "")
    confirm = body.get("confirm", "")

    if not new_password:
        raise HTTPException(400, "New password is required.")
    if len(new_password) < 8:
        raise HTTPException(400, "Password must be at least 8 characters.")
    if new_password != confirm:
        raise HTTPException(400, "Passwords do not match.")

    settings = config.get_settings()
    stored_hash = settings.get("auth_password_hash", "")
    if not stored_hash:
        raise HTTPException(400, "No password configured.")
    if not config.verify_password(current, stored_hash):
        raise HTTPException(401, "Current password is incorrect.")

    config.save_settings({"auth_password_hash": config.hash_password(new_password)})
    logger.info("Dashboard password changed")
    return {"status": "success", "message": "Password updated."}


# -- TOTP 2FA ---------------------------------------------------------------

@dashboard_auth_router.post("/totp-setup")
def totp_setup():
    """Generate a TOTP secret and return the otpauth URI for QR rendering.

    Does NOT enable 2FA yet — the user must verify a code first via
    /totp-enable.  The secret is stored as a pending value until verified.
    """
    import pyotp
    secret = pyotp.random_base32()
    settings = config.get_settings()
    username = settings.get("auth_username", "admin")
    totp = pyotp.TOTP(secret)
    uri = totp.provisioning_uri(name=username, issuer_name="PawPoller")

    # Store pending secret (not yet active)
    config.save_settings({"auth_totp_pending_secret": secret})
    return {"secret": secret, "uri": uri}


@dashboard_auth_router.post("/totp-enable")
def totp_enable(body: dict):
    """Verify a TOTP code and activate 2FA.

    The user must provide a valid code generated from the pending secret
    to prove they've configured their authenticator app correctly.
    """
    import pyotp
    code = body.get("code", "").strip()
    if not code:
        raise HTTPException(400, "Verification code is required.")

    settings = config.get_settings()
    pending = settings.get("auth_totp_pending_secret")
    if not pending:
        raise HTTPException(400, "No pending TOTP setup. Call /totp-setup first.")

    totp = pyotp.TOTP(pending)
    if not totp.verify(code, valid_window=1):
        raise HTTPException(400, "Invalid code. Check your authenticator app and try again.")

    # Activate: move pending secret to active
    config.save_settings({
        "auth_totp_secret": pending,
        "auth_totp_enabled": True,
    })
    config.delete_settings_keys(["auth_totp_pending_secret"])
    logger.info("TOTP 2FA enabled")
    return {"status": "success", "message": "Two-factor authentication enabled."}


@dashboard_auth_router.post("/totp-disable")
def totp_disable(body: dict):
    """Disable 2FA.  Requires password and a valid TOTP code for safety."""
    import pyotp
    password = body.get("password", "")
    code = body.get("code", "").strip()

    settings = config.get_settings()
    stored_hash = settings.get("auth_password_hash", "")
    if not stored_hash or not config.verify_password(password, stored_hash):
        raise HTTPException(401, "Password is incorrect.")

    totp_secret = settings.get("auth_totp_secret")
    if not totp_secret:
        raise HTTPException(400, "2FA is not enabled.")

    totp = pyotp.TOTP(totp_secret)
    if not totp.verify(code, valid_window=1):
        raise HTTPException(400, "Invalid 2FA code.")

    config.delete_settings_keys(["auth_totp_secret", "auth_totp_enabled", "auth_totp_pending_secret"])
    logger.info("TOTP 2FA disabled")
    return {"status": "success", "message": "Two-factor authentication disabled."}


# -- API Keys ----------------------------------------------------------------

@dashboard_auth_router.get("/api-keys")
def list_api_keys():
    """List API keys (prefix + name only, never the full key)."""
    settings = config.get_settings()
    keys = settings.get("auth_api_keys", [])
    return {"keys": [{"name": k["name"], "prefix": k["prefix"], "created": k["created"]} for k in keys]}


@dashboard_auth_router.post("/api-keys")
def create_api_key(body: dict):
    """Generate a new API key.  Returns the full key ONCE.

    The full key is ``pp_`` + 48 hex chars.  Only the SHA-256 hash is
    stored in settings.json.  If the user loses the key, they must
    generate a new one.
    """
    name = body.get("name", "").strip()
    if not name:
        raise HTTPException(400, "Key name is required.")
    if len(name) > 64:
        raise HTTPException(400, "Key name must be 64 characters or less.")

    # Generate key: pp_ prefix + 48 hex chars = 51 chars total
    raw = secrets.token_hex(24)  # 24 bytes = 48 hex chars
    full_key = f"pp_{raw}"
    prefix = f"pp_{raw[:8]}"
    key_hash = hashlib.sha256(full_key.encode("utf-8")).hexdigest()

    settings = config.get_settings()
    api_keys = settings.get("auth_api_keys", [])
    api_keys.append({
        "name": name,
        "prefix": prefix,
        "hash": key_hash,
        "created": datetime.now(timezone.utc).isoformat(),
    })
    config.save_settings({"auth_api_keys": api_keys})
    logger.info("API key created: %s (%s)", name, prefix)

    return {
        "status": "success",
        "key": full_key,
        "prefix": prefix,
        "name": name,
        "message": "Save this key now — it won't be shown again.",
    }


@dashboard_auth_router.delete("/api-keys/{prefix}")
def revoke_api_key(prefix: str):
    """Revoke an API key by its prefix."""
    settings = config.get_settings()
    api_keys = settings.get("auth_api_keys", [])
    original_len = len(api_keys)
    api_keys = [k for k in api_keys if k["prefix"] != prefix]
    if len(api_keys) == original_len:
        raise HTTPException(404, "API key not found.")
    config.save_settings({"auth_api_keys": api_keys})
    logger.info("API key revoked: %s", prefix)
    return {"status": "success", "message": f"API key {prefix}... revoked."}


# -- Cloudflare Turnstile Config ---------------------------------------------

@dashboard_auth_router.post("/turnstile-config")
def save_turnstile_config(body: dict):
    """Save Cloudflare Turnstile site key and secret key."""
    site_key = body.get("site_key", "").strip()
    secret_key = body.get("secret_key", "").strip()

    # Allow clearing by sending empty strings
    config.save_settings({
        "turnstile_site_key": site_key,
        "turnstile_secret_key": secret_key,
    })
    # Invalidate cached CSP so the Turnstile origins are added/removed
    from dashboard import invalidate_csp_cache
    invalidate_csp_cache()

    status = "enabled" if site_key and secret_key else "disabled"
    logger.info("Turnstile %s", status)
    return {"status": "success", "message": f"Turnstile {status}."}


# -- Turnstile Verification Helper -------------------------------------------

async def _verify_turnstile(token: str, secret_key: str, remote_ip: str) -> bool:
    """Verify a Cloudflare Turnstile token server-side.

    Returns True if the token is valid, False otherwise.  Network errors
    are treated as failure (deny access rather than bypass verification).
    """
    if not token:
        return False
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                "https://challenges.cloudflare.com/turnstile/v0/siteverify",
                data={
                    "secret": secret_key,
                    "response": token,
                    "remoteip": remote_ip,
                },
            )
            result = resp.json()
            return result.get("success", False)
    except Exception as e:
        logger.error("Turnstile verification failed: %s", e)
        return False
