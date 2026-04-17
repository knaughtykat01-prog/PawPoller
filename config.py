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

    NOTE: Callers must hold _settings_lock before calling this function.
    """
    if SETTINGS_PATH.exists():
        try:
            return json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}  # Corrupt file -- treat as empty and let next save fix it
    return {}


def save_settings(data: dict) -> None:
    """Merge *data* into settings.json and write.

    Uses read-merge-write so that keys not present in *data* are preserved.
    Thread-safe: acquires _settings_lock for the entire read-modify-write cycle.

    Write is atomic: data goes to a temp file first, then os.replace() swaps it
    in.  os.replace() is atomic on the same filesystem, so a crash mid-write
    cannot leave a truncated/corrupt settings.json.
    """
    import tempfile
    with _settings_lock:
        current = _load_settings()
        current.update(data)  # Overlay new values on top of existing ones
        # Write to a temp file in the same directory, then atomically replace.
        # Same-directory ensures same filesystem so os.replace() is atomic.
        fd, tmp_path = tempfile.mkstemp(dir=SETTINGS_PATH.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(current, f, indent=2)
            os.replace(tmp_path, SETTINGS_PATH)
            _secure_file_permissions(SETTINGS_PATH)
        except BaseException:
            # Clean up temp file on any failure (including KeyboardInterrupt)
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise


def delete_settings_keys(keys: list[str]) -> None:
    """Remove *keys* from settings.json and write.

    Thread-safe: acquires _settings_lock for the entire read-modify-write cycle.
    Keys that do not exist are silently ignored.
    Uses the same atomic write pattern as save_settings().
    """
    import tempfile
    with _settings_lock:
        current = _load_settings()
        for key in keys:
            current.pop(key, None)
        fd, tmp_path = tempfile.mkstemp(dir=SETTINGS_PATH.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(current, f, indent=2)
            os.replace(tmp_path, SETTINGS_PATH)
            _secure_file_permissions(SETTINGS_PATH)
        except BaseException:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise


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
FA_REQUEST_DELAY_SECONDS = 1.0   # Delay between consecutive FA API requests (rate limiting)
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
# Why 3 seconds: AO3 is run entirely by volunteers with limited infrastructure.
# Aggressive scraping can degrade the site for real users.  This is a courtesy
# rate limit — significantly slower than what the site technically requires —
# to be a good citizen.
AO3_REQUEST_DELAY_SECONDS = 3.0

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

# ── App metadata ──
APP_VERSION = "2.10.3"

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
        return  # Already migrated

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


# ── Run-on-startup (Windows registry) ────────────────────────
# Windows auto-start is implemented by writing a value to the per-user
# "Run" registry key at HKCU\Software\Microsoft\Windows\CurrentVersion\Run.
# Each value in that key is a program path that Windows launches at logon.
# We use HKCU (not HKLM) so no admin privileges are needed.
#
# The value stored differs by mode:
#   Frozen:  the .exe path directly (e.g. "C:\...\PawPoller.exe")
#   Dev:     a quoted python + script path (e.g. "python" "main.py")

_STARTUP_REG_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
_STARTUP_REG_NAME = "PawPoller"  # Registry value name -- identifies our entry


def get_run_on_startup() -> bool:
    """Check whether the app is registered to start with Windows.

    Returns True if our named value exists under the Run key, regardless of
    whether the path it points to is still valid.
    """
    if sys.platform != "win32":
        return False  # No-op on non-Windows platforms
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _STARTUP_REG_KEY, 0, winreg.KEY_READ) as key:
            winreg.QueryValueEx(key, _STARTUP_REG_NAME)  # Throws if not found
            return True
    except FileNotFoundError:
        return False  # Value does not exist -- not registered
    except OSError:
        return False  # Registry access error -- treat as not registered


def set_run_on_startup(enabled: bool) -> None:
    """Add or remove the app from Windows startup via the registry.

    When enabling, the registry value is set to the executable path so
    Windows will launch PawPoller automatically at user logon.  When
    disabling, the value is deleted (silently succeeds if already absent).
    """
    if sys.platform != "win32":
        logger.warning("set_run_on_startup is only supported on Windows")
        return
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _STARTUP_REG_KEY, 0, winreg.KEY_SET_VALUE) as key:
            if enabled:
                exe_path = sys.executable
                if getattr(sys, "frozen", False):
                    # Frozen: sys.executable is already the .exe path
                    exe_path = sys.executable
                else:
                    # Dev mode: need to invoke the Python interpreter with main.py
                    script = str(Path(__file__).resolve().parent / "main.py")
                    exe_path = f'"{sys.executable}" "{script}"'
                winreg.SetValueEx(key, _STARTUP_REG_NAME, 0, winreg.REG_SZ, exe_path)
                logger.info("Added to Windows startup: %s", exe_path)
            else:
                try:
                    winreg.DeleteValue(key, _STARTUP_REG_NAME)
                    logger.info("Removed from Windows startup")
                except FileNotFoundError:
                    pass  # Already absent -- nothing to remove
    except OSError as e:
        logger.error("Failed to modify startup registry: %s", e)
