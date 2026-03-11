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
import json
import logging
import os
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
APP_VERSION = "1.5.0"

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
