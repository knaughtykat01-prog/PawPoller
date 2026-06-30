"""Configuration — loads .env / settings.json and defines paths.

This module is imported early by every other module, so it establishes all
paths, credentials, and tunables in one place.  Two runtime modes are
supported:
  - **Dev mode**: run via `python main.py`, paths are relative to this file.
  - **Frozen mode**: packaged with PyInstaller into a single .exe; bundled
    assets live in a temp directory (sys._MEIPASS) while user data goes
    to %APPDATA%/PawPoller so it persists across updates.
"""

from pathlib import Path
from dotenv import load_dotenv
import hashlib
import json
import logging
import os
import re
import secrets
import stat
import sys
import threading

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Path resolution: frozen (PyInstaller) vs dev mode
# ---------------------------------------------------------------------------
# PyInstaller bundles assets into a temporary directory exposed via
# sys._MEIPASS.  The `frozen` attribute is set to True by PyInstaller.
# In dev mode neither attribute exists, so we fall back to the directory
# that contains this source file.  This dual-path pattern lets the same
# code locate icons, templates, and static files regardless of how the
# app was launched.
# ---------------------------------------------------------------------------

def resource_path(relative: str) -> Path:
    """Resolve a path relative to the application root.

    When frozen by PyInstaller, bundled data files live under sys._MEIPASS.
    In normal dev mode this is just the directory containing this file.
    """
    if getattr(sys, "frozen", False):
        base = Path(sys._MEIPASS)  # PyInstaller temp extraction directory
    else:
        base = Path(__file__).resolve().parent  # project root in dev mode
    return base / relative


# ── Source directory (code / bundled assets) ──────────────────
# Points to the root of bundled assets (frozen) or the project folder (dev).
SRC_DIR = resource_path(".")

# ── Persistent data directory ─────────────────────────────────
# The APPDATA_DIR split separates *mutable* user data from *immutable*
# bundled code.  In a frozen build the .exe unpacks read-only assets to a
# temp folder that is deleted on exit, so databases, logs, and settings
# must live somewhere persistent -- %APPDATA%/PawPoller is the standard
# Windows location for per-user application data.
# In dev mode everything stays in the project directory for convenience.
#
# Frozen exe  -> %APPDATA%/PawPoller/
# Dev mode    -> ./data, ./logs  (project-local)

if getattr(sys, "frozen", False):
    # Persistent roaming AppData folder survives app updates / reinstalls
    APPDATA_DIR = Path(os.environ.get("APPDATA", "")) / "PawPoller"
else:
    # Dev mode: keep data alongside source for easy inspection
    APPDATA_DIR = Path(__file__).resolve().parent

DATA_DIR = APPDATA_DIR / "data"         # SQLite database and JSON caches
LOGS_DIR = APPDATA_DIR / "logs"         # Rotating log files
DB_PATH = DATA_DIR / "pawpoller.db"     # Main SQLite database
SETTINGS_PATH = DATA_DIR / "settings.json"      # User preferences and credentials

# Create data/log directories on first run (no-op if they already exist)
DATA_DIR.mkdir(parents=True, exist_ok=True)
LOGS_DIR.mkdir(parents=True, exist_ok=True)

# Migrate settings.json from old location (APPDATA_DIR) to new (DATA_DIR)
# so it lives on the persistent Docker volume and survives container rebuilds.
_old_settings = APPDATA_DIR / "settings.json"
if _old_settings.exists() and not SETTINGS_PATH.exists():
    import shutil
    shutil.copy2(_old_settings, SETTINGS_PATH)


# ── Goal Metrics Whitelist ─────────────────────────────────────
# Single source of truth for valid metric column names used in SQL queries
# for goal tracking.  Referenced by routes/api.py (create + read) and
# polling/telegram.py (goal completion notifications).  Any metric name
# interpolated into SQL MUST be validated against this set first.
ALLOWED_GOAL_METRICS = frozenset({
    "views", "favorites_count", "comments_count", "watchers",
    "reads", "votes", "likes", "reshares", "downloads", "num_lists",
    "reposts", "retweets", "bookmarks", "quotes", "replies",
})


def _secure_file_permissions(path) -> None:
    """Set file to owner-read/write only (0600) on Unix/Linux.

    No-op on Windows where POSIX permissions don't apply.
    Protects settings.json (which contains credentials) from being
    readable by other users/processes in the Docker container.
    """
    if sys.platform != "win32":
        try:
            os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
        except OSError:
            pass  # Best-effort — don't crash if permissions can't be set


# ── Credential vault (Phase 7b) ────────────────────────────────
# Must be declared BEFORE _load_settings because the module-level
# `_settings = _load_settings()` at import time calls _decrypt_vault()
# when settings.json has credential_mode="local". If these live below
# that init line Python raises NameError at import on vault-mode servers.

VAULT_PATH = DATA_DIR / "settings.vault.json"


def _get_vault_key() -> bytes:
    """Derive or retrieve the encryption key for the credential vault.

    Uses the system keyring if available, otherwise falls back to a
    machine-derived key stored in a dotfile.
    """
    try:
        import keyring
        key = keyring.get_password("PawPoller", "vault_key")
        if key:
            return key.encode()
        # Generate and store a new key
        from cryptography.fernet import Fernet
        new_key = Fernet.generate_key()
        keyring.set_password("PawPoller", "vault_key", new_key.decode())
        return new_key
    except Exception:
        # Fallback: store key in a dotfile in DATA_DIR
        key_file = DATA_DIR / ".vault_key"
        if key_file.exists():
            return key_file.read_bytes().strip()
        from cryptography.fernet import Fernet
        new_key = Fernet.generate_key()
        key_file.write_bytes(new_key)
        _secure_file_permissions(key_file)
        return new_key


def _encrypt_vault(creds: dict) -> None:
    """Encrypt credential fields to settings.vault.json.

    NOTE: Callers must hold _settings_lock before calling this function.
    """
    from cryptography.fernet import Fernet
    import tempfile
    key = _get_vault_key()
    f = Fernet(key)
    payload = json.dumps(creds).encode("utf-8")
    encrypted = f.encrypt(payload)
    vault_data = {"version": 1, "encrypted": encrypted.decode("ascii")}

    fd, tmp = tempfile.mkstemp(dir=VAULT_PATH.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fp:
            json.dump(vault_data, fp, indent=2)
        os.replace(tmp, str(VAULT_PATH))
        _secure_file_permissions(VAULT_PATH)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _decrypt_vault() -> dict:
    """Decrypt credential fields from settings.vault.json.

    NOTE: Callers must hold _settings_lock before calling this function.
    """
    if not VAULT_PATH.exists():
        return {}
    try:
        from cryptography.fernet import Fernet
        vault = json.loads(VAULT_PATH.read_text(encoding="utf-8"))
        key = _get_vault_key()
        f = Fernet(key)
        decrypted = f.decrypt(vault["encrypted"].encode("ascii"))
        return json.loads(decrypted)
    except Exception as e:
        logger.error("Failed to decrypt vault: %s", e)
        return {}


# ── Settings.json helpers ─────────────────────────────────────
# settings.json is the single source of truth for user preferences and
# credentials once the app has been configured through the UI.  It uses a
# simple merge-on-write strategy: save_settings() reads the current file,
# overlays the new keys, and writes back, so callers only need to pass the
# keys they want to change.  A threading lock serialises all reads and writes
# to prevent race conditions when multiple routes access settings concurrently.

_settings_lock = threading.Lock()


def _load_settings() -> dict:
    """Load settings.json if it exists, else return empty dict.

    Returns an empty dict (rather than raising) on corrupt/missing files so
    the app can always start with sensible defaults.

    When credential_mode is "local", credential fields are stored in an
    encrypted vault file rather than plaintext settings.json.  This method
    transparently merges decrypted vault contents into the returned dict so
    the rest of the app sees a unified view.

    NOTE: Callers must hold _settings_lock before calling this function.
    """
    if SETTINGS_PATH.exists():
        try:
            settings = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}  # Corrupt file -- treat as empty and let next save fix it
    else:
        settings = {}
    # Merge vault credentials when in local mode
    if settings.get("credential_mode") == "local":
        vault_creds = _decrypt_vault()
        if vault_creds:
            settings.update(vault_creds)
    return settings


def save_settings(data: dict) -> None:
    """Merge *data* into settings.json and write.

    Uses read-merge-write so that keys not present in *data* are preserved.
    Thread-safe: acquires _settings_lock for the entire read-modify-write cycle.

    When credential_mode is "local", credential fields are routed to the
    encrypted vault instead of being stored in plaintext settings.json.

    Write is atomic: data goes to a temp file first, then os.replace() swaps it
    in.  os.replace() is atomic on the same filesystem, so a crash mid-write
    cannot leave a truncated/corrupt settings.json.
    """
    import tempfile
    with _settings_lock:
        current = _load_settings()
        current.update(data)  # Overlay new values on top of existing ones

        # In local mode, split credentials into vault vs plaintext.
        # is_credential_key() also catches account-namespaced secrets
        # (acct_<id>_<field>), so extra accounts are encrypted like the default.
        if current.get("credential_mode") == "local":
            vault_creds = {k: v for k, v in current.items()
                           if is_credential_key(k) and v}
            if vault_creds:
                _encrypt_vault(vault_creds)
            plaintext = {k: v for k, v in current.items()
                         if not is_credential_key(k)}
        else:
            plaintext = current

        # Write to a temp file in the same directory, then atomically replace.
        # Same-directory ensures same filesystem so os.replace() is atomic.
        fd, tmp_path = tempfile.mkstemp(dir=SETTINGS_PATH.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(plaintext, f, indent=2)
            os.replace(tmp_path, SETTINGS_PATH)
            _secure_file_permissions(SETTINGS_PATH)
        except BaseException:
            # Clean up temp file on any failure (including KeyboardInterrupt)
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    # Fire a debounced push to the cloud server (no-op when not configured
    # or when this save originated from a pull merge — auto_sync handles both).
    _schedule_auto_sync_push()


def delete_settings_keys(keys: list[str]) -> None:
    """Remove *keys* from settings.json (and vault if in local mode) and write.

    Thread-safe: acquires _settings_lock for the entire read-modify-write cycle.
    Keys that do not exist are silently ignored.
    Uses the same atomic write pattern as save_settings().
    """
    import tempfile
    with _settings_lock:
        current = _load_settings()
        for key in keys:
            current.pop(key, None)

        # In local mode, re-split credentials into vault vs plaintext
        if current.get("credential_mode") == "local":
            vault_creds = {k: v for k, v in current.items()
                           if is_credential_key(k) and v}
            if vault_creds:
                _encrypt_vault(vault_creds)
            plaintext = {k: v for k, v in current.items()
                         if not is_credential_key(k)}
        else:
            plaintext = current

        fd, tmp_path = tempfile.mkstemp(dir=SETTINGS_PATH.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(plaintext, f, indent=2)
            os.replace(tmp_path, SETTINGS_PATH)
            _secure_file_permissions(SETTINGS_PATH)
        except BaseException:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    _schedule_auto_sync_push()


def _schedule_auto_sync_push() -> None:
    """Trigger a debounced auto-sync push if available.

    Imported lazily and exception-swallowed so config.py stays usable when
    auto_sync isn't importable (e.g. unit tests that stub modules).
    """
    try:
        import auto_sync
        auto_sync.schedule_push()
    except Exception:
        pass


def get_settings() -> dict:
    """Public read accessor -- thin wrapper kept separate from the private
    _load_settings() so callers have a clean API and internal helpers can
    evolve independently.  Thread-safe: acquires _settings_lock."""
    with _settings_lock:
        return _load_settings()


# ── Credentials (cascading: settings.json > .env > empty) ────
# Credentials are resolved with a three-tier fallback:
#   1. settings.json  -- written by the UI's settings page at runtime
#   2. .env file      -- developer convenience for local testing
#   3. empty string   -- safe default; pollers skip when creds are blank
# This lets users configure everything through the GUI while still
# allowing developers to drop in a .env for quick local runs.

_BASE_DIR = Path(__file__).resolve().parent
load_dotenv(_BASE_DIR / ".env")  # Load .env as fallback for dev environments

# Why these module-level reads exist alongside get_settings():
# These reads happen once at import time and provide backward compatibility
# for code that imports config.INKBUNNY_USERNAME directly.  Pollers that run
# later should call get_settings() for fresh reads — these module-level values
# are stale snapshots that won't reflect runtime changes made through the UI.
_settings = _load_settings()
# `or` short-circuits: if settings.json has the value, .env is never read
INKBUNNY_USERNAME = _settings.get("username") or os.getenv("INKBUNNY_USERNAME", "")
INKBUNNY_PASSWORD = _settings.get("password") or os.getenv("INKBUNNY_PASSWORD", "")

# ── FurAffinity settings ──
FA_BASE = "https://www.furaffinity.net"          # Main FA website for scraping
FAEXPORT_BASE = "https://faexport.spangle.org.uk"  # Third-party FA API proxy
FA_POLL_INTERVAL_HOURS = 1       # Default hours between FA poll cycles
FA_REQUEST_DELAY_SECONDS = 1.5   # Delay between consecutive FA API requests (rate limiting)
FA_USERNAME = _settings.get("fa_username", "")
# FA uses session cookies (cookie_a and cookie_b) instead of username/password auth
FA_COOKIE_A = _settings.get("fa_cookie_a", "")
FA_COOKIE_B = _settings.get("fa_cookie_b", "")

# ── Weasyl settings ──
WS_REQUEST_DELAY_SECONDS = 1.0  # Rate-limit delay between Weasyl API calls

# ── SoFurry settings ──
SF_REQUEST_DELAY_SECONDS = 1.5  # Rate-limit delay between SoFurry page scrapes (slightly higher for scraping)

# ── SquidgeWorld settings ──
SQW_REQUEST_DELAY_SECONDS = 2.0  # Rate-limit delay between SquidgeWorld page scrapes (higher due to anti-bot)

# ── AO3 settings ──
# Why 12 seconds: 2.22.4 bumped 3s → 6s based on kenalba/ao3-scraper's
# baseline. First live test still hit `Retry-After: 349s` because we'd
# already cooked the per-IP bucket with earlier cycles that day. AO3's
# throttle escalates the longer you're inside the punishment window.
# 12s is "be aggressively generous" — double the external-tool baseline,
# which makes us slower than every comparable scraper and gives the
# bucket comfortable headroom to drain between requests.
# Cost: ~60s extra wall time per ten-work cycle. Still invisible at the
# 240-min polling cadence.
# Bumped 6.0 → 12.0 in 2.22.5 after observing 349s throttle escalation
# on a 6s-pacing cycle.
AO3_REQUEST_DELAY_SECONDS = 12.0

# ── DeviantArt settings ──
DA_REQUEST_DELAY_SECONDS = 2.0  # Rate-limit delay between DeviantArt API requests

# ── Wattpad settings ──
WP_REQUEST_DELAY_SECONDS = 1.0  # Rate-limit delay between Wattpad API requests

# ── Itaku settings ──
IK_REQUEST_DELAY_SECONDS = 1.0  # Rate-limit delay between Itaku API requests

# ── Bluesky settings ──
BSKY_REQUEST_DELAY_SECONDS = 1.0  # Bluesky AT Protocol — generous rate limits

# ── X/Twitter settings ──
TW_REQUEST_DELAY_SECONDS = 2.0  # X GraphQL — aggressive rate limiting, needs higher delay

# ── Mastodon settings ──
MAST_REQUEST_DELAY_SECONDS = 0.5  # Mastodon REST — per-instance limits are generous

# ── Tumblr settings ──
TUM_REQUEST_DELAY_SECONDS = 0.5  # Tumblr v2 API — generous rate limits for read

# ── Settings sync (Phase 7a) ────────────────────────────────

CREDENTIAL_FIELDS = frozenset({
    # Inkbunny
    "username", "password",
    # FurAffinity
    "fa_cookie_a", "fa_cookie_b",
    # Weasyl
    "ws_api_key",
    # SoFurry
    "sf_username", "sf_password", "sf_session_cookies",
    # SquidgeWorld
    "sqw_username", "sqw_password",
    "sqw_author_username", "sqw_author_password",
    # AO3
    "ao3_username", "ao3_password", "ao3_session_cookie",
    # DeviantArt
    "da_cookie", "da_client_secret", "da_refresh_token",
    # Itaku
    "ik_auth_token",
    # Bluesky
    "bsky_identifier", "bsky_app_password",
    # X/Twitter
    "tw_auth_token", "tw_ct0",
    # Mastodon
    "mast_access_token",
    # Tumblr
    "tum_api_key",
    # CF proxy
    "cf_worker_url", "cf_worker_key",
    # Dashboard auth
    "auth_password_hash", "auth_api_keys",
    "auth_session_secret", "auth_totp_secret",
    "auth_totp_enabled", "auth_totp_pending_secret",
    "dashboard_password", "dashboard_user",
    # Integrations
    "telegram_bot_token", "telegram_chat_id",
    "github_pat",
    "turnstile_site_key", "turnstile_secret_key",
    # Server ↔ desktop
    "posting_server_url", "posting_server_api_key",
})

SYNC_EXCLUDE = frozenset({
    "credential_mode",
    "auth_session_secret",
    "minimize_to_tray",
    # Desktop-only — never leak to the server settings dump
    "run_on_startup",
    # Setup mode is decided per-device (server is always "server"; desktop
    # is "standalone" or "paired_desktop"). Syncing it would let one side
    # overwrite the other's mode, which is exactly what we don't want.
    "setup_mode",
})


# ── Multi-account credential resolution ───────────────────────
# Each platform's *default* account keeps using the legacy flat settings keys
# (``username``/``password``, ``fa_username``/``fa_cookie_a``…) so existing
# installs need zero credential migration. Additional accounts store the SAME
# canonical fields under an ``acct_<account_id>_<field>`` prefix. The resolver
# below hands callers a creds dict keyed by the canonical field names regardless
# of which account it is, so clients/posters don't care whether they're the
# default account or the fifth one.
#
# PLATFORM_CREDENTIAL_FIELDS lists, per platform, the canonical settings keys
# that make up an account's identity + secrets. Secret-ness (vault routing) is
# still decided by membership in CREDENTIAL_FIELDS above — non-secret identity
# fields like ``fa_username`` stay in plaintext exactly as they do today.
PLATFORM_CREDENTIAL_FIELDS = {
    "ib": ["username", "password"],
    "fa": ["fa_username", "fa_cookie_a", "fa_cookie_b"],
    "ws": ["ws_username", "ws_api_key"],
    "sf": ["sf_username", "sf_password", "sf_session_cookies", "sf_display_name"],
    "sqw": ["sqw_username", "sqw_password", "sqw_target_user",
            "sqw_author_username", "sqw_author_password"],
    "ao3": ["ao3_username", "ao3_password", "ao3_target_user", "ao3_session_cookie"],
    "da": ["da_cookie", "da_target_user",
           "da_client_id", "da_client_secret", "da_refresh_token"],
    "wp": ["wp_target_user"],
    "ik": ["ik_target_user", "ik_auth_token"],
    "bsky": ["bsky_identifier", "bsky_app_password"],
    "tw": ["tw_auth_token", "tw_ct0", "tw_target_user"],
    "mast": ["mast_instance_url", "mast_access_token"],
    "tum": ["tum_api_key", "tum_blog"],
}

# Matches an account-namespaced settings key: acct_<id>_<canonical_field>.
_ACCT_KEY_RE = re.compile(r"^acct_(\d+)_(.+)$")


def is_credential_key(key: str) -> bool:
    """True if *key* names a secret that belongs in the encrypted vault.

    Covers both the legacy flat keys (membership in CREDENTIAL_FIELDS) and the
    account-namespaced form ``acct_<id>_<field>`` whose underlying canonical
    field is itself a secret. This keeps extra-account secrets encrypted exactly
    like the default account's, while leaving non-secret identity fields (and
    their namespaced variants, e.g. ``acct_5_fa_username``) in plaintext.
    """
    if key in CREDENTIAL_FIELDS:
        return True
    m = _ACCT_KEY_RE.match(key)
    return bool(m and m.group(2) in CREDENTIAL_FIELDS)


def account_setting_key(account_id: int, field: str, is_default: bool) -> str:
    """Return the settings key holding *field* for the given account.

    The default account uses the bare canonical field; others are namespaced.
    """
    return field if is_default else f"acct_{account_id}_{field}"


def resolve_account_credentials(platform: str, account_id: int,
                                is_default: bool, settings: dict | None = None) -> dict:
    """Return {canonical_field: value} for one account, no DB access.

    Pollers/posters that already hold the account row should call this directly.
    """
    fields = PLATFORM_CREDENTIAL_FIELDS.get(platform, [])
    if settings is None:
        settings = get_settings()
    return {f: settings.get(account_setting_key(account_id, f, is_default), "")
            for f in fields}


def get_account_credentials(account_id: int) -> dict:
    """Return {canonical_field: value} for *account_id*, looking up its row.

    Convenience wrapper around :func:`resolve_account_credentials` for callers
    that have only an account_id. Returns {} for an unknown account.
    """
    try:
        from database import db as _db, accounts as _accts
        conn = _db.get_connection()
        try:
            acct = _accts.get_account(conn, account_id)
        finally:
            conn.close()
    except Exception as e:
        logger.warning("get_account_credentials(%s) lookup failed: %s", account_id, e)
        return {}
    if not acct:
        return {}
    return resolve_account_credentials(
        acct["platform"], account_id, bool(acct["is_default"]))


# ── Setup mode + polling ownership ────────────────────────────
# `setup_mode` tells each instance what role it plays. Three values:
#
#   "standalone"     — Desktop only; no server. Polls locally.
#   "paired_desktop" — Desktop running alongside a remote server; pulls
#                      settings from the server, defers polling to it,
#                      but can still post stories from the local archive.
#   "server"         — Headless container. Always polls.
#
# When `setup_mode` is unset (existing installs upgraded from < 2.14.6),
# we infer from runtime + presence of `posting_server_url` so behaviour
# matches what the user already had.

SETUP_MODE_STANDALONE = "standalone"
SETUP_MODE_PAIRED = "paired_desktop"
SETUP_MODE_SERVER = "server"
VALID_SETUP_MODES = frozenset({SETUP_MODE_STANDALONE, SETUP_MODE_PAIRED, SETUP_MODE_SERVER})


def get_polling_owner(runtime: str) -> str:
    """Return ``"local"`` if this process should run the poll loop, else ``"server"``.

    ``runtime`` is the entry point: ``"desktop"`` (main.py) or
    ``"server"`` (server.py). The server is always the polling owner on
    its own box — there's no other PawPoller that could run there. The
    desktop is the polling owner only when it knows it's standalone.

    Inference rules for unset ``setup_mode`` (back-compat with installs
    that predate the mode setting):

    * Desktop with ``posting_server_url`` set → assume paired; server polls.
    * Desktop with no server URL → assume standalone; desktop polls.
    """
    if runtime == "server":
        return "local"  # this process *is* the server, it polls
    settings = get_settings()
    mode = settings.get("setup_mode")
    if mode == SETUP_MODE_PAIRED:
        return "server"
    if mode == SETUP_MODE_STANDALONE:
        return "local"
    if mode == SETUP_MODE_SERVER:
        # Defensive: a desktop install shouldn't have mode=server, but if
        # it somehow does we don't want it polling and racing the real one.
        return "server"
    # No mode set — fall back to the implicit pairing signal.
    if settings.get("posting_server_url") and settings.get("posting_server_api_key"):
        return "server"
    return "local"


def get_credential_mode() -> str:
    """Return 'cloud' or 'local'.

    Reads directly from settings.json (not the merged view) so we can
    determine mode before deciding whether to merge the vault.
    """
    with _settings_lock:
        raw = {}
        if SETTINGS_PATH.exists():
            try:
                raw = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                pass
        return raw.get("credential_mode", "cloud")


def migrate_to_local_vault() -> int:
    """Migrate credentials from plaintext settings.json to encrypted vault.

    Returns count of fields migrated.
    """
    with _settings_lock:
        settings = _load_settings()
        creds = {k: v for k, v in settings.items() if is_credential_key(k) and v}
        if not creds:
            # Still switch mode even if no creds to migrate
            settings["credential_mode"] = "local"
            import tempfile
            fd, tmp = tempfile.mkstemp(dir=SETTINGS_PATH.parent, suffix=".tmp")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as fp:
                    json.dump(settings, fp, indent=2)
                os.replace(tmp, str(SETTINGS_PATH))
                _secure_file_permissions(SETTINGS_PATH)
            except BaseException:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
                raise
            return 0
        _encrypt_vault(creds)
        # Remove credential fields from plaintext settings
        for k in creds:
            settings.pop(k, None)
        settings["credential_mode"] = "local"
        # Write cleaned settings
        import tempfile
        fd, tmp = tempfile.mkstemp(dir=SETTINGS_PATH.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fp:
                json.dump(settings, fp, indent=2)
            os.replace(tmp, str(SETTINGS_PATH))
            _secure_file_permissions(SETTINGS_PATH)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
        return len(creds)


def migrate_to_cloud() -> int:
    """Migrate credentials from encrypted vault back to plaintext settings.json.

    Returns count of fields migrated.
    """
    with _settings_lock:
        creds = _decrypt_vault()
        settings = _load_settings()
        if creds:
            settings.update(creds)
        settings["credential_mode"] = "cloud"
        import tempfile
        fd, tmp = tempfile.mkstemp(dir=SETTINGS_PATH.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fp:
                json.dump(settings, fp, indent=2)
            os.replace(tmp, str(SETTINGS_PATH))
            _secure_file_permissions(SETTINGS_PATH)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
    # Remove vault file
    if VAULT_PATH.exists():
        VAULT_PATH.unlink()
    return len(creds) if creds else 0


def get_settings_for_sync() -> tuple[dict, float]:
    """Return (settings_dict, mtime) for the sync endpoint.

    Excludes keys in SYNC_EXCLUDE.
    """
    with _settings_lock:
        data = _load_settings()
    mtime = SETTINGS_PATH.stat().st_mtime if SETTINGS_PATH.exists() else 0
    out = {k: v for k, v in data.items() if k not in SYNC_EXCLUDE}
    # Carry the account registry (DB state, not a setting) so desktop↔server
    # agree on which accounts exist. Guarded — never break sync over this.
    try:
        from database import db as _db, accounts as _accts, personas as _personas
        conn = _db.get_connection()
        try:
            out["_accounts_manifest"] = _accts.get_manifest(conn)
            out["_personas_manifest"] = _personas.get_manifest(conn)
        finally:
            conn.close()
    except Exception as e:
        logger.debug("accounts/personas manifest export skipped: %s", e)
    return out, mtime


def merge_synced_settings(incoming: dict, client_timestamp: float | None = None) -> dict:
    """Merge incoming settings from a sync push.

    Applies SYNC_EXCLUDE filtering, then merges into current settings.
    Returns the merged result.
    """
    filtered = {k: v for k, v in incoming.items() if k not in SYNC_EXCLUDE}
    # The account registry rides the sync channel but is DB state, not a
    # setting — apply it to the accounts table (additive, never deletes) and
    # strip it so it isn't persisted into settings.json.
    personas_manifest = filtered.pop("_personas_manifest", None)
    accounts_manifest = filtered.pop("_accounts_manifest", None)
    if personas_manifest is not None or accounts_manifest is not None:
        try:
            from database import db as _db, accounts as _accts, personas as _personas
            conn = _db.get_connection()
            try:
                # Personas BEFORE accounts so account→persona references land
                # after the persona rows exist. Both additive, never delete.
                if personas_manifest is not None:
                    _personas.apply_manifest(conn, personas_manifest)
                if accounts_manifest is not None:
                    _accts.apply_manifest(conn, accounts_manifest)
            finally:
                conn.close()
        except Exception as e:
            logger.warning("accounts/personas manifest import skipped: %s", e)
    if not filtered:
        return get_settings()
    save_settings(filtered)
    return get_settings()


# ── App metadata ──
APP_VERSION = "2.42.0"

# ── Inkbunny API settings ──
INKBUNNY_API_BASE = "https://inkbunny.net"     # Inkbunny API root URL
POLL_INTERVAL_HOURS = 1                        # Default hours between IB poll cycles
REQUEST_DELAY_SECONDS = 1.0                    # Delay between general IB API requests
FAVE_REQUEST_DELAY_SECONDS = 0.5               # Shorter delay for fave lookups (lighter endpoint)
COMMENT_REQUEST_DELAY_SECONDS = 1.0            # Delay between comment-fetching requests
SUBMISSION_BATCH_SIZE = 100                    # Max submissions fetched per API page request

# ── Dashboard (local web server) ──
DASHBOARD_HOST = "127.0.0.1"  # Localhost only -- not exposed to the network
DASHBOARD_PORT = 8420          # Arbitrary high port unlikely to conflict

# ── Stat offsets ──
# The Inkbunny API only returns data for *public* submissions.  If you have
# deleted or private submissions, API-reported totals for views/faves/comments
# will be lower than the numbers shown on your Inkbunny dashboard.  These
# offsets are added to the API totals so the dashboard displays numbers that
# match the real Inkbunny totals.  Adjust them manually if the gap changes.
VIEWS_OFFSET = 301
FAVORITES_OFFSET = 0
COMMENTS_OFFSET = 0


# ── Dashboard Auth Helpers ────────────────────────────────────
# Bcrypt password hashing, session cookie signing, and API key validation
# for the self-hosted dashboard authentication system.  These are used by
# routes/dashboard_auth.py and the session middleware in dashboard.py.

def hash_password(password: str) -> str:
    """Hash a password with bcrypt.  Returns the hash as a UTF-8 string."""
    import bcrypt
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    """Check a plaintext password against a bcrypt hash."""
    import bcrypt
    try:
        return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


_session_secret_cache: str | None = None


def get_or_create_session_secret() -> str:
    """Return the session signing secret, creating one on first call.

    The secret is a 32-byte hex string stored in settings.json.  It is
    generated once and reused across restarts so that existing session
    cookies remain valid.  Regenerating it would log out all users.
    Cached in memory since it never changes after creation.
    """
    global _session_secret_cache
    if _session_secret_cache is not None:
        return _session_secret_cache
    settings = get_settings()
    secret = settings.get("auth_session_secret")
    if not secret:
        secret = secrets.token_hex(32)
        save_settings({"auth_session_secret": secret})
    _session_secret_cache = secret
    return secret


_SESSION_MAX_AGE_SHORT = 86400        # 24 hours (default)
_SESSION_MAX_AGE_LONG = 30 * 86400   # 30 days ("remember me")


def sign_session(payload: dict) -> str:
    """Sign a session payload and return the cookie value.

    The payload should include a ``"r": True`` flag for "remember me"
    sessions so verify_session() can apply the correct max_age.
    """
    from itsdangerous import URLSafeTimedSerializer
    s = URLSafeTimedSerializer(get_or_create_session_secret())
    return s.dumps(payload)


def verify_session(cookie: str) -> dict | None:
    """Verify a signed session cookie.  Returns the payload dict or None.

    Tries the short max_age first, then the long max_age.  The ``"r"``
    (remember) flag in the payload determines which expiry applies:
    sessions without ``"r": True`` expire after 24 hours; sessions with
    it expire after 30 days.
    """
    from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
    s = URLSafeTimedSerializer(get_or_create_session_secret())
    # First try with the long max_age (universal upper bound)
    try:
        payload = s.loads(cookie, max_age=_SESSION_MAX_AGE_LONG)
    except (BadSignature, SignatureExpired):
        return None
    # If not a "remember me" session, enforce the short max_age
    if not payload.get("r"):
        try:
            s.loads(cookie, max_age=_SESSION_MAX_AGE_SHORT)
        except SignatureExpired:
            return None
        except BadSignature:
            return None
    return payload


_auth_required_cache: bool | None = None


def is_dashboard_auth_required() -> bool:
    """Return True if dashboard authentication is configured.

    Auth is required when either:
      - A bcrypt password hash exists (new system), or
      - A legacy plaintext dashboard_password is set (pre-migration)

    Result is cached; call ``invalidate_auth_required_cache()`` after
    dashboard-setup or migration changes the auth state.
    """
    global _auth_required_cache
    if _auth_required_cache is not None:
        return _auth_required_cache
    settings = get_settings()
    if settings.get("auth_password_hash"):
        _auth_required_cache = True
        return True
    if settings.get("dashboard_password"):
        _auth_required_cache = True
        return True
    if os.environ.get("DASHBOARD_PASSWORD"):
        _auth_required_cache = True
        return True
    _auth_required_cache = False
    return False


def invalidate_auth_required_cache() -> None:
    """Clear the cached auth-required flag so it's re-evaluated."""
    global _auth_required_cache
    _auth_required_cache = None


def validate_api_key(key: str) -> bool:
    """Check an API key against stored SHA-256 hashes in settings.json.

    API keys are stored as a list of {hash, name, prefix, created} dicts.
    The key format is ``pp_`` + 48 hex chars.  We hash the full key with
    SHA-256 and compare against stored hashes.  SHA-256 is sufficient here
    because API keys are high-entropy random tokens (not user passwords).
    """
    if not key or not key.startswith("pp_"):
        return False
    key_hash = hashlib.sha256(key.encode("utf-8")).hexdigest()
    settings = get_settings()
    api_keys = settings.get("auth_api_keys", [])
    return any(k.get("hash") == key_hash for k in api_keys)


def migrate_dashboard_auth() -> None:
    """Hash legacy plaintext dashboard_password to bcrypt if not already migrated.

    Called on startup from both server.py (headless) and dashboard.py (desktop).
    Safe to call multiple times — no-ops if already migrated or no auth configured.
    """
    settings = get_settings()
    if settings.get("auth_password_hash"):
        # Already migrated. _seed_settings_from_env can re-write the legacy
        # plaintext keys back into settings.json on every restart from the
        # DASHBOARD_PASSWORD/USER env vars (Docker compose), so scrub them
        # here too — otherwise the plaintext sits next to the bcrypt hash and
        # defeats the migration. (BUG-004 in 2.14.6.)
        if settings.get("dashboard_password") or settings.get("dashboard_user"):
            delete_settings_keys(["dashboard_password", "dashboard_user"])
        return

    legacy_pw = settings.get("dashboard_password") or os.environ.get("DASHBOARD_PASSWORD", "")
    if not legacy_pw:
        return  # No auth configured

    legacy_user = settings.get("dashboard_user") or os.environ.get("DASHBOARD_USER", "admin")
    hashed = hash_password(legacy_pw)
    save_settings({
        "auth_username": legacy_user,
        "auth_password_hash": hashed,
    })
    # Remove plaintext password from settings (env var remains but is ignored
    # once the hash exists)
    delete_settings_keys(["dashboard_password", "dashboard_user"])
    invalidate_auth_required_cache()
    logger.info("Migrated dashboard password to bcrypt hash for user '%s'", legacy_user)


# ── Run-on-startup ────────────────────────────────────────────
# Per-OS implementation behind a single get/set pair:
#
#   Windows: HKCU\Software\Microsoft\Windows\CurrentVersion\Run value.
#            Per-user, no admin needed.
#   Linux:   ~/.config/autostart/PawPoller.desktop (XDG autostart spec).
#            Per-user, no root needed. Honoured by GNOME, KDE, XFCE,
#            Cinnamon, MATE, LXQt — every major desktop environment.
#   macOS:   Not implemented yet — would use a launch agent plist at
#            ~/Library/LaunchAgents/com.knaughtykat.pawpoller.plist.
#
# The value/exec string differs by mode:
#   Frozen:  the executable path directly (e.g. "C:\...\PawPoller.exe"
#            on Windows, or the AppImage path on Linux)
#   Dev:     python interpreter + main.py path

_STARTUP_REG_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
_STARTUP_REG_NAME = "PawPoller"  # Windows registry value name


def _linux_autostart_path() -> Path:
    """Return the XDG autostart .desktop path for the current user.

    Honours $XDG_CONFIG_HOME if set (rare), else ~/.config/autostart.
    """
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg) if xdg else Path.home() / ".config"
    return base / "autostart" / "PawPoller.desktop"


def _exec_command_for_autostart() -> str:
    """Build the Exec= / registry value pointing at this PawPoller install.

    Same logic for both OSes — only the quoting style differs and the
    callers handle that.
    """
    if getattr(sys, "frozen", False):
        # Frozen: sys.executable is the bundled binary (PawPoller.exe or
        # the Linux PyInstaller binary inside the AppImage)
        return sys.executable
    # Dev mode: invoke the interpreter against main.py
    script = str(Path(__file__).resolve().parent / "main.py")
    return f'"{sys.executable}" "{script}"'


def get_run_on_startup() -> bool:
    """Check whether the app is registered to start on user login.

    Returns True iff the per-OS registration exists. Path/exec validity
    is NOT checked — a stale registration still returns True so the UI
    can show the toggle state honestly.
    """
    if sys.platform == "win32":
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _STARTUP_REG_KEY, 0, winreg.KEY_READ) as key:
                winreg.QueryValueEx(key, _STARTUP_REG_NAME)  # Throws if not found
                return True
        except FileNotFoundError:
            return False
        except OSError:
            return False
    if sys.platform.startswith("linux"):
        return _linux_autostart_path().exists()
    # macOS and others: not implemented
    return False


def set_run_on_startup(enabled: bool) -> None:
    """Add or remove the app from per-user startup.

    Windows: writes/deletes the HKCU Run registry value.
    Linux: writes/removes the XDG autostart .desktop file.
    Other platforms: logs a warning and returns.
    """
    if sys.platform == "win32":
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _STARTUP_REG_KEY, 0, winreg.KEY_SET_VALUE) as key:
                if enabled:
                    exe_path = _exec_command_for_autostart()
                    winreg.SetValueEx(key, _STARTUP_REG_NAME, 0, winreg.REG_SZ, exe_path)
                    logger.info("Added to Windows startup: %s", exe_path)
                else:
                    try:
                        winreg.DeleteValue(key, _STARTUP_REG_NAME)
                        logger.info("Removed from Windows startup")
                    except FileNotFoundError:
                        pass  # Already absent
        except OSError as e:
            logger.error("Failed to modify startup registry: %s", e)
        return

    if sys.platform.startswith("linux"):
        desktop_path = _linux_autostart_path()
        if enabled:
            exec_cmd = _exec_command_for_autostart()
            desktop_path.parent.mkdir(parents=True, exist_ok=True)
            # Standard XDG autostart .desktop format. X-GNOME-Autostart-enabled
            # is honoured by GNOME but harmless elsewhere; OnlyShowIn omitted
            # so every DE picks it up.
            content = (
                "[Desktop Entry]\n"
                "Type=Application\n"
                "Name=PawPoller\n"
                "Comment=Multi-platform story publishing + analytics\n"
                f"Exec={exec_cmd}\n"
                "Terminal=false\n"
                "X-GNOME-Autostart-enabled=true\n"
            )
            try:
                desktop_path.write_text(content, encoding="utf-8")
                logger.info("Added to Linux autostart: %s", desktop_path)
            except OSError as e:
                logger.error("Failed to write Linux autostart file %s: %s", desktop_path, e)
        else:
            try:
                desktop_path.unlink()
                logger.info("Removed from Linux autostart: %s", desktop_path)
            except FileNotFoundError:
                pass  # Already absent
            except OSError as e:
                logger.error("Failed to remove Linux autostart file %s: %s", desktop_path, e)
        return

    logger.warning("set_run_on_startup is not supported on this platform (%s)", sys.platform)
