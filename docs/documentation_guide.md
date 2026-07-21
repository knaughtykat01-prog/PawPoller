# PawPoller Documentation Guide

Comprehensive technical reference for the PawPoller codebase. Covers architecture, threading, platform clients, database, deployment, and troubleshooting.

---

## 1. Overview & Architecture

PawPoller is a multi-platform furry art/fiction **analytics + publishing** app. It has two major subsystems that share a database, dashboard, and settings surface:

1. **Polling / analytics** — periodically polls 11 art/writing platforms, stores submission stats in SQLite, and renders real-time charts in the dashboard.
2. **Publishing pipeline** — reads canonical `MASTER.md` files from the local story archive, converts to per-platform formats (BBCode, SoFurry HTML, Styled HTML, SquidgeWorld work-skin HTML, WeasyPrint/Edge-rendered PDFs, EPUB 3.0), and posts/updates stories across 9 publishing platforms. Includes a Markdown editor with anchor toolbar, metadata drawer, publish-check matrix, drift detection, retry queue, scheduling, credential vault, browser-login popups, and import from IB/SF/FA.

The tech stack is FastAPI + SQLite (WAL mode) + Vanilla JS SPA + pywebview + pystray. Desktop uses PyInstaller (`pawpoller.spec`); server runs under Docker Compose on a GCP VM. Entry points: `main.py` (desktop) or `server.py` (headless).

### Supported Platforms

| # | Platform     | Content Type         | Data Access Method |
|---|-------------|---------------------|-------------------|
| 1 | Inkbunny    | Art, stories, music  | Official JSON API |
| 2 | FurAffinity | Art, stories, music  | FAExport API + scraping |
| 3 | Weasyl      | Art, stories         | Official REST API |
| 4 | SoFurry     | Art, stories, music  | Scraping + JSON hybrid |
| 5 | SquidgeWorld| Stories (OTW Archive)| HTML scraping |
| 6 | AO3         | Stories (OTW Archive)| HTML scraping |
| 7 | DeviantArt  | Art, literature      | Official OAuth2 API (client-credentials) |
| 8 | Wattpad     | Stories              | Public REST API |
| 9 | Itaku       | Art                  | Public REST API |
| 10 | Bluesky    | Social (microblog)   | AT Protocol public API |
| 11 | X/Twitter  | Social (microblog)   | Poll via gallery-dl subprocess (GraphQL fallback); posting via GraphQL |

### Two Operating Modes

**Desktop** (`main.py`): pywebview native window + pystray system tray + all pollers. Runs on Windows and Linux; macOS is on the public roadmap. The dashboard runs at `127.0.0.1:8420` and is accessed through an embedded browser window. Desktop-only dependencies vary by OS — `winotify` on Windows, `PyQt6 + PyQt6-WebEngine` on Linux (the pywebview backend, set via `gui='qt'` in `webview.start()`); `pywebview`, `pystray`, and `Pillow` are common to both. See `requirements.txt` for env-marker syntax (`; sys_platform == "..."`).

**Headless** (`server.py`): pollers + dashboard only, no GUI dependencies. Designed for Docker / Linux server deployment. Binds `0.0.0.0:8420` by default. Uses `requirements-server.txt` which excludes all desktop dependencies.

### Cross-platform desktop matrix

| OS | Build target | Autostart mechanism | Notifications backend | pywebview backend |
|---|---|---|---|---|
| Windows | `PawPoller-Setup-{ver}.exe` (Inno Setup installer) + `PawPoller-windows-x64.zip` (portable) | `HKCU\Software\Microsoft\Windows\CurrentVersion\Run` value | `winotify` (Windows 10/11 native toast) | Edge WebView2 (default) |
| Linux | `PawPoller-{ver}-x86_64.AppImage` (single file, no install) | XDG `~/.config/autostart/PawPoller.desktop` | `notify-send` (libnotify) shell-out | Qt6 + QtWebEngine (set via `webview.start(gui='qt')`) |
| macOS | *planned* — `.app` bundle inside `.dmg` | *planned* — launch agent plist at `~/Library/LaunchAgents/` | *planned* — `pync` or `osascript` shell-out | Cocoa via PyObjC (default) |

The per-OS branching for autostart and notifications lives behind two single-entry-point helpers (`config.set_run_on_startup()` / `polling.notifications.show_toast()`) so callers stay platform-blind. See §8 (Notifications) and §9 (Configuration System) for the implementations.

### High-Level Component Map

```
                    ┌─────────────────────────────────────┐
                    │           Entry Point                │
                    │   main.py (desktop) / server.py (headless) │
                    └────────────┬────────────────────────┘
                                 │ spawns daemon threads
                    ┌────────────┴────────────────────────┐
           ┌────────┤         Thread Pool                  ├────────┐
           │        │  main.py: 11 pollers + uvicorn +     │        │
           │        │    digest + telegram + posting (15)   │        │
           │        │  server.py: orchestrator + uvicorn +  │        │
           │        │    telegram + posting (4 threads)     │        │
           │        └─────────────────────────────────────┘        │
           ▼                         ▼                              ▼
    ┌──────────┐           ┌────────────────┐              ┌──────────────┐
    │ Platform │           │   Dashboard    │              │  Telegram    │
    │ Clients  │           │   (FastAPI)    │              │  Bot + Digest│
    │ (HTTP)   │           │  port 8420     │              │  Notifications│
    └────┬─────┘           └───────┬────────┘              └──────────────┘
         │                         │
         ▼                         ▼
    ┌──────────┐           ┌──────────────┐
    │ Database │◄──────────│  REST API    │
    │ (SQLite) │           │  /api/*      │
    │  WAL     │           └──────┬───────┘
    └──────────┘                  │
                                  ▼
                           ┌──────────────┐
                           │  Frontend    │
                           │  (SPA, JS)   │
                           └──────────────┘
```

### Data Flow

```
Platform API/Website
    │
    ▼
Platform Client (clients/ib/, clients/fa/, etc.)
    │  HTTP requests via httpx.AsyncClient
    │  (optionally through CF Worker proxy)
    ▼
Poller (polling/poller.py, polling/fa_poller.py, etc.)
    │  Orchestrates: discover → fetch → upsert → snapshot → notify
    ▼
Database (database/queries.py → SQLite WAL)
    │  INSERT/UPDATE submissions, INSERT snapshots
    ▼
REST API (routes/api.py, routes/fa_api.py, etc.)
    │  FastAPI endpoints read from database
    ▼
Frontend SPA (frontend/js/app.js → api.js → components.js)
    │  Renders charts (Chart.js), tables, progress bars
    ▼
User's browser (pywebview on desktop, regular browser on server)
```

### Project File Tree

```
PawPoller/
├── main.py                  # Desktop entry point (pywebview + pystray)
├── server.py                # Headless entry point (Docker / server, unified poll orchestrator)
├── config.py                # Paths, credentials, settings.json helpers
├── dashboard.py             # FastAPI app factory, session auth middleware, rate limiting, security headers, SPA serving
├── updater.py               # Auto-update (desktop only); per-OS asset matching + apply path
├── auto_sync.py             # Settings auto-sync: debounced push + 5-min pull thread (desktop ↔ server)
│
├── clients/                 # Per-platform HTTP clients (all 17 platforms in one place — 2.14.3)
│   ├── ib/                  #   Inkbunny — InkbunnyClient with SID caching
│   ├── fa/                  #   FurAffinity — FAClient with dual HTTP transports
│   ├── weasyl/              #   Weasyl — WeasylClient with cursor pagination
│   ├── sf/                  #   SoFurry — SoFurryClient with CF proxy support
│   ├── sqw/                 #   SquidgeWorld — SqWClient with Anubis challenge solving
│   ├── ao3/                 #   AO3 — AO3Client with CSRF auth
│   ├── da/                  #   DeviantArt — DAClient, official OAuth2 API (client-credentials, no proxy)
│   ├── wp/                  #   Wattpad — WPClient (no auth, public API)
│   ├── ik/                  #   Itaku — IKClient (no auth, public API)
│   ├── bsky/                #   Bluesky — BskyClient with JWT session auth
│   └── tw/                  #   X/Twitter — TWClient with cookie auth
│   # Each subfolder has client.py (sometimes models.py for ib).
│   # Imports: `from clients.<platform>.client import <Class>`.
│
├── auth/                    # Browser-based login helpers (Phase 8a)
│   ├── __init__.py          #   Package init
│   └── browser_login.py     #   pywebview popup login for cookie-based platforms (FA, TW, SF, WS, AO3, SqW)
│
├── polling/
│   ├── poller.py            # Inkbunny poll cycle orchestration (6-step)
│   ├── fa_poller.py         # FurAffinity poll cycle (5-step + spam filter)
│   ├── ws_poller.py         # Weasyl poll cycle (3-step, simplest)
│   ├── sf_poller.py         # SoFurry poll cycle (4-step + follower scraping)
│   ├── sqw_poller.py        # SquidgeWorld poll cycle
│   ├── ao3_poller.py        # AO3 poll cycle
│   ├── da_poller.py         # DeviantArt poll cycle (no comments/watchers)
│   ├── wp_poller.py         # Wattpad poll cycle
│   ├── ik_poller.py         # Itaku poll cycle
│   ├── bsky_poller.py       # Bluesky poll cycle
│   ├── tw_poller.py         # X/Twitter poll cycle
│   ├── cf_proxy.py          # Cloudflare Worker proxy transport (httpx)
│   ├── telegram.py          # Telegram notification helpers (summaries, milestones, digests)
│   └── telegram_bot.py      # Telegram bot command listener (11 commands)
│
├── database/
│   ├── db.py                # Connection factory, schema init, 10+ migrations
│   ├── queries.py           # Inkbunny CRUD + analytics
│   ├── fa_queries.py        # FurAffinity queries (+ watcher spam management)
│   ├── ws_queries.py        # Weasyl queries
│   ├── sf_queries.py        # SoFurry queries
│   ├── sqw_queries.py       # SquidgeWorld queries
│   ├── ao3_queries.py       # AO3 queries
│   ├── da_queries.py        # DeviantArt queries
│   ├── wp_queries.py        # Wattpad queries
│   ├── ik_queries.py        # Itaku queries
│   ├── bsky_queries.py      # Bluesky queries
│   ├── tw_queries.py        # X/Twitter queries
│   ├── group_queries.py     # Cross-platform submission groups
│   ├── analytics_queries.py # Cross-platform trending, top fans, comparisons
│   ├── schema.sql           # Inkbunny tables (submissions, snapshots, faving_users, comments, poll_log, watchers, session_cache)
│   ├── fa_schema.sql        # FA tables (fa_submissions, fa_snapshots, fa_comments, fa_poll_log, fa_watchers)
│   ├── ws_schema.sql        # Weasyl tables
│   ├── sf_schema.sql        # SoFurry tables
│   ├── sqw_schema.sql       # SquidgeWorld tables
│   ├── ao3_schema.sql       # AO3 tables
│   ├── da_schema.sql        # DeviantArt tables
│   ├── wp_schema.sql        # Wattpad tables
│   ├── ik_schema.sql        # Itaku tables
│   ├── bsky_schema.sql      # Bluesky tables
│   └── tw_schema.sql        # X/Twitter tables
│
├── routes/
│   ├── api.py               # Core API (IB CRUD, settings, groups, links, health, auto-update, thumbnail proxy, Telegram setup)
│   ├── fa_api.py            # FurAffinity API endpoints (auth, submissions, watchers, poll control)
│   ├── ws_api.py            # Weasyl API endpoints
│   ├── sf_api.py            # SoFurry API endpoints
│   ├── sqw_api.py           # SquidgeWorld API endpoints
│   ├── ao3_api.py           # AO3 API endpoints
│   ├── da_api.py            # DeviantArt API endpoints
│   ├── wp_api.py            # Wattpad API endpoints
│   ├── ik_api.py            # Itaku API endpoints
│   ├── bsky_api.py          # Bluesky API endpoints
│   ├── tw_api.py            # X/Twitter API endpoints
│   ├── dashboard_auth.py    # Dashboard auth endpoints (login, 2FA, API keys, Turnstile)
│   ├── settings_api.py      # Settings sync, vault, setup wizard, browser login endpoints
│   ├── editor_api.py        # Editor endpoints (load/save MASTER.md, theme save, regenerate formats, PDF, metadata drawer, create story wizard, import)
│   └── posting_api.py       # Posting endpoints (publish-check matrix, publish, dry-run, verify, scheduling, retry queue, bulk actions)
│
├── frontend/
│   ├── index.html           # SPA shell (grouped nav: top-bar/side-rail modes, bottom nav bar, sidebar overlay)
│   ├── epub-viewer.html     # In-app EPUB reader (2.17.6+) — opened in new tab from editor Downloads dropdown
│   ├── css/
│   │   ├── tokens.css      # Design tokens (10 themes via [data-theme=...]; default "quill" = redesign palette)
│   │   ├── components.css  # UI components (cards, buttons, tables, accordions, charts)
│   │   ├── editor.css      # Editor + drawer + matrix + downloads dropdown styles
│   │   └── layout.css      # Page layout, sidebar, responsive breakpoints, bottom nav
│   ├── js/
│   │   ├── app.js           # Hash-based SPA router, accordion nav, bottom nav, auto-refresh
│   │   ├── api.js           # API client wrapper (~50 methods, get/post transport)
│   │   ├── components.js    # UI components (~25: tables with mobile card transformation, cards, charts, modals)
│   │   ├── charts.js        # Chart.js time-series and comparison chart factories
│   │   ├── editor.js        # Editor UI + anchor toolbar + format tabs + downloads dropdown
│   │   ├── epub-viewer.js   # EPUB viewer logic (2.17.6+) — extracted from epub-viewer.html for CSP compliance
│   │   ├── utils.js         # Formatting helpers (numbers, dates, relative time)
│   │   └── vendor/          # Third-party libraries (Chart.js, QRCode.js)
│   └── vendor/              # Page-level vendored libs (epub.js, jszip — used by epub-viewer.html)
│
├── posting/
│   ├── __init__.py          # Package docstring
│   ├── manager.py           # Posting orchestrator: resolve → post → record
│   ├── scheduler.py         # Daemon thread — processes posting_queue every 60s
│   ├── story_reader.py      # Reads story archives → StoryUploadPackage
│   ├── sync.py              # Retroactive claim + change detection
│   ├── generate_story_json.py # CLI: generate story.json from legacy data
│   └── platforms/
│       ├── base.py          # PlatformPoster ABC, PostResult, StoryUploadPackage
│       ├── inkbunny.py      # IB poster (official API upload)
│       ├── furaffinity.py   # FA poster (form scraping, desktop-only)
│       ├── weasyl.py        # WS poster (CSRF form + API key)
│       ├── sofurry.py       # SF poster (REST + CSRF)
│       ├── squidgeworld.py  # SqW poster (OTW Rails form + work skin)
│       ├── ao3.py           # AO3 poster (OTW Rails, CF-proxy on desktop, work skin)
│       ├── deviantart.py    # DA poster (Eclipse stash flow)
│       ├── itaku.py         # Itaku poster (REST API)
│       └── bluesky.py       # BSKY poster (AT Protocol announcements)
│
├── editor/                  # MASTER.md → multi-format conversion
│   ├── __init__.py
│   ├── converter.py         # Markdown → BBCode / SoFurry HTML / Styled HTML / SquidgeWorld work-skin HTML; anchor-aware
│   ├── pdf_generator.py     # WeasyPrint primary (Linux/server), Edge headless fallback (Windows/desktop)
│   └── slop.py              # EQ-Bench slop scoring (optional quality check)
│
├── tag_database/            # Canonical tag DB (bundled, copied to /app/tag_database/ in container — NOT under /app/data/)
│   ├── tags_fiction.json
│   ├── tags_images.json
│   ├── aliases.json
│   └── e621_lookup.tsv
│
├── scripts_utils/           # One-off maintenance scripts (story archive audits, etc.)
├── tests/                   # unittest + pytest test suite (CI discovers via `python -m unittest`)
│
├── deploy/
│   ├── cf-worker.js         # Cloudflare Worker proxy (3 modes: normal, chain, login)
│   ├── setup-gcloud.sh      # GCP VM deployment automation
│   ├── setup-oracle.sh      # Oracle Cloud Always Free deployment
│   └── pawsync.bat          # Story archive sync to GCP server automation
│
├── assets/
│   └── tray_icon.png        # System tray icon (fallback: procedurally generated)
│
├── .github/
│   └── workflows/
│       ├── build.yml        # CI build workflow
│       └── lint.yml         # CI lint workflow
│
├── Dockerfile               # Python 3.11 slim + HEALTHCHECK
├── docker-compose.yml       # Single service, 2 named volumes, .env file
├── .env.example             # 25+ environment variable template
├── requirements.txt         # Desktop dependencies. Common: pywebview, pystray, Pillow.
│                            #   Windows-only (env marker `sys_platform == "win32"`): winotify.
│                            #   Linux-only (env marker `sys_platform == "linux"`): PyQt6, PyQt6-WebEngine.
├── requirements-server.txt  # Headless/Docker dependencies (no GUI): fastapi, uvicorn, httpx, bcrypt, pyotp, itsdangerous
├── pawpoller.spec          # PyInstaller build spec
├── build.bat               # Windows build script
├── CHANGELOG.md             # Version history
├── README.md                # Public-facing project overview
├── LICENSE                  # Project licence
├── CONTRIBUTING.md          # Contribution guidelines
├── docs/                    # Internal-facing docs
│   ├── HANDOFF.md           #   Session handoff (current state, recent work)
│   ├── SETUP.md             #   New-user install guide (desktop / Docker / from source)
│   ├── ROADMAP_PUBLIC.md    #   Public release roadmap (Phases 8-15)
│   └── documentation_guide.md  # This file — full technical reference
└── qa/                      # Manual QA artefacts
    ├── TESTING_CHECKLIST_WEBAPP.html
    ├── TESTING_CHECKLIST_NATIVE.html
    └── fixtures/             # Sample upload payloads referenced by checklist file-upload tests
```

### Follower tracking (cross-platform, count + history)

Individual *watchers* are tracked per-platform for Inkbunny/FA/SoFurry (their own
`*_watchers` tables). Every other platform whose API exposes a **follower count** —
Weasyl, DeviantArt, Wattpad, Itaku, Bluesky, X, Mastodon, Pixiv — uses a lighter,
uniform layer added in 2.51.0. A follower count is one integer that means the same
thing everywhere, so — unlike the per-platform submission analytics — it lives in a
**single shared table**:

- **`database/followers.py`** — `account_follower_snapshots` (time-series keyed by the
  global `account_id`) + cached `accounts.follower_count`/`follower_count_at` for fast
  reads. `record_snapshot()` skips a `None`/negative value so a failed fetch never
  writes a bogus 0 (the zero-snapshot rule). Created by a `db.py` migration.
- **`clients/*/client.py` `get_follower_count()`** — one uniform async method per
  follower-capable client, piggybacking on the profile endpoint the client already
  hits. Bluesky/Mastodon/X/Wattpad read a documented field; Weasyl/DA/Itaku/Pixiv
  probe plausible field names and return `None` if absent (best-effort).
- **`polling/followers.py` `capture_followers()`** — each poller calls this once after
  its main `conn.commit()`. The count is fetched (network) **before** the follower
  write so no SQLite write lock is held across the await (the same rule as the poll
  snapshot loop), and any failure is swallowed so follower capture never fails a poll.
- **`routes/followers_api.py`** — `GET /api/followers/{platform}` returns the current
  count + growth series (`supported:false` for platforms with no source). The frontend
  shows a Followers stat card + Follower Growth chart per dashboard
  (`App._loadFollowerWidget`, reusing `Charts.aggregateLine`) and a per-account chip on
  the Accounts page (`follower_count` rides along on `/api/accounts`).

---

## 2. Entry Points

### `main.py` — Desktop GUI Mode

Startup sequence in detail:

**Step 1: Database initialisation**
```python
init_db()  # Creates tables/schema if the DB file does not exist yet
```

**Step 2: Launch up to 16 daemon threads (see §3 for the full table)**
All threads are `daemon=True` so they terminate automatically when the main thread (pywebview) exits. No explicit shutdown signalling is needed. Each thread is named for debugging (`threading.Thread(name="FA poller")`).

Thread launch order when `polling_owner == "local"`: Uvicorn → IB poller → FA poller → WS poller → SF poller → SqW poller → AO3 poller → DA poller → WP poller → IK poller → BSKY poller → TW poller → MAST poller → TUM poller → PIX poller → THR poller → IG poller → e621 poller → Telegram digest → Telegram bot → Posting scheduler → pystray tray. When `polling_owner == "remote"`, the 17 platform pollers are skipped.

**Step 3: System tray icon**
```python
_tray_icon = _create_tray_icon()
# pystray's default setup sets visible=True, showing the icon immediately.
# We pass a no-op lambda to override: icon starts HIDDEN.
tray_thread = threading.Thread(
    target=_tray_icon.run,
    kwargs={"setup": lambda icon: None},  # No-op: keep hidden on start
    daemon=True,
)
```

The tray icon supports a "minimize to tray" workflow:
- `_on_closing()` callback intercepts the window close event
- If `minimize_to_tray` setting is enabled: returns `False` (cancels close), hides window, shows tray icon
- If disabled: returns `True` (allows close), app exits normally
- Tray menu: "Show" (restore window + hide tray, `default=True` for double-click) and "Quit" (destroy window + stop tray)

**Step 4: Wait for server readiness**
```python
deadline = time.time() + 15  # 15-second timeout
while time.time() < deadline:
    try:
        with socket.create_connection((host, port), timeout=1.0):
            break  # TCP handshake succeeded = uvicorn is listening
    except OSError:
        time.sleep(0.2)  # 200ms between attempts
```
This prevents pywebview from opening a window to a server that hasn't finished binding its port, which would show a blank or error page.

**Step 5: Open native window**
```python
_window = webview.create_window("PawPoller", url=url, width=1200, height=800, min_size=(800, 500))
_window.events.closing += _on_closing  # Intercept close for tray minimize
webview.start()  # Blocks main thread until window is DESTROYED (not just hidden)
```

**Step 7: Cleanup** (lines ~731-735)
```python
if _tray_icon is not None:
    _tray_icon.stop()
# All daemon threads die automatically now that the main thread is exiting.
```

### `server.py` — Headless Server Mode

Startup sequence in detail:

**Step 1: Database** — Same `init_db()` call.

**Step 2: Seed credentials from environment** (lines ~78-95)
```python
_ENV_TO_SETTINGS = {
    "IB_USERNAME":      "username",
    "FA_COOKIE_A":      "fa_cookie_a",
    "SF_USERNAME":      "sf_username",
    "TELEGRAM_BOT_TOKEN": "telegram_bot_token",
    "CF_WORKER_URL":     "cf_worker_url",
    # ... 25+ mappings total
}
```
`_seed_settings_from_env()` reads each env var and writes ONLY into fields that are missing or empty in settings — never overwrites an existing UI/vault value. The UI is the source of truth for credentials once they've been set; `.env` exists purely as a first-run bootstrap so a brand-new container has something to authenticate with on its first poll. Special handling for `telegram_enabled` which is parsed as a boolean (`"true"/"1"/"yes"` → `True`). Logs which credentials were seeded. (Pre-2.18.3 behaviour was to overwrite on `existing != val` — that meant UI credential changes silently reverted to `.env` on every container restart. Fixed in 2.18.3.)

**Step 2b: Migrate legacy plaintext password** — `config.migrate_dashboard_auth()` converts any plaintext `dashboard_password` in settings.json to a bcrypt hash if not already hashed.

**Step 3: Launch 4 daemon threads** — Unlike `main.py` which spawns 15 threads (11 per-platform pollers + uvicorn + digest scheduler + telegram bot + posting scheduler), `server.py` uses a unified poll orchestrator that replaces the 11 individual poller threads and digest scheduler with a single thread:
```python
threads = [
    ("Uvicorn",             lambda: _start_server(args.host, args.port)),
    ("Poll orchestrator",   _start_poll_orchestrator),
    ("Telegram bot",        _start_telegram_bot),
    ("Posting scheduler",   start_posting_scheduler),
]
for name, target in threads:
    t = threading.Thread(target=target, daemon=True, name=name)
    t.start()
```

The **poll orchestrator** (`_start_poll_orchestrator()`) runs a single loop that each cycle:
1. **Polls all configured platforms concurrently** via `asyncio.gather()` — all 17 platform poll functions run in parallel within one async event loop
2. **Sends one consolidated Telegram summary** covering all platform results (individual per-platform notifications are suppressed via `orchestrated_poll_active` flag)
3. **Checks if the regular digest is due** — fires `send_digest_report()` when the elapsed time since `last_digest_sent_at` exceeds `telegram_digest_interval_hours`
4. **Checks if the weekly digest is due** — fires `send_weekly_digest_report()` when 7 days have elapsed since `last_weekly_digest_sent_at`
5. **Sleeps for `poll_interval_minutes`** (default 240 minutes, minimum 15), then repeats

The orchestrator uses a single `poll_interval_minutes` setting (not per-platform intervals). The poll interval is intended to be a divisor of the digest interval (e.g. poll every 4h, digest every 12h = digest fires every 3rd cycle), guaranteeing fresh data for every digest without double-polling.

First-poll notification suppression: the orchestrator tracks `_first_cycle = True` and suppresses the consolidated Telegram summary on the first cycle. Data is collected normally to establish a baseline.

The orchestrator respects `polling_paused`: when paused, polling is skipped but the sleep/schedule loop continues so that the cycle resumes immediately when unpaused. Manual `/poll` commands via the Telegram bot still work by calling individual poll functions directly.

Per-platform pause (2.103.0): distinct from the global flag, `settings.polling_paused_platforms` is a list of platform codes. `_poll_all()` reads it once per cycle and skips any platform whose code is listed (both the account-aware and legacy task-building loops), while the other platforms poll normally. Manual "Poll Now" / "Full Resync" for a paused platform still work — the skip only applies to the scheduled cycle. Toggled from Settings → Polling per-card buttons via `POST /api/poll/pause/{code}` / `/poll/resume/{code}`.

**Step 4: Block until signal** — Uses `threading.Event` + signal handler:
```python
shutdown_event = threading.Event()
signal.signal(signal.SIGINT, lambda *_: shutdown_event.set())
signal.signal(signal.SIGTERM, lambda *_: shutdown_event.set())
shutdown_event.wait()  # Blocks until SIGINT/SIGTERM
```

Key differences from `main.py`:
- **4 threads instead of 15** — unified poll orchestrator replaces 11 per-platform pollers + digest scheduler; posting scheduler is the same in both modes
- **Single poll interval** — `poll_interval_minutes` controls all platforms (not per-platform intervals)
- **Consolidated notifications** — one Telegram message per cycle instead of per-platform messages
- Binds `0.0.0.0` by default (not `127.0.0.1`) — accessible from the network
- `--port` and `--host` argparse arguments for customisation
- Signal handler for graceful shutdown (SIGINT/SIGTERM)
- CF proxy debug logging gated behind `PAWPOLLER_DEBUG_PROXY` env var
- No pywebview, pystray, Pillow, or winotify dependencies

### `cli/pawpoller_cli.py` — Menu TUI (2.22.0+)

A third entry point — a Python TUI that connects to a running
PawPoller server over HTTP (against the GCP VM remotely, or
`127.0.0.1:8420` when run on the VM itself). Not a server; just a
client. Same script works locally or on the VM with identical UX.
See §17 for full architecture, menu structure, and config resolution.

Launchers:
- `cli/pp.cmd` — Windows wrapper invoking `python pawpoller_cli.py`.
- `cli/pp.sh` — POSIX wrapper used on the VM; aliased to `pp` in
  kithetiger's `~/.bashrc`.
- `deploy/pawcli.bat` — Windows one-command launcher that SSHes into
  the VM and drops directly into the menu. With
  `PawPoller/deploy/` on the user PATH, typing `pawcli` from any cmd
  shell is enough.

---

## 3. Threading Model

`main.py` and `server.py` use different threading architectures:

### `main.py` — 16-Thread Model (Desktop, polling owner = local)

`main.py` spawns up to 16 daemon threads plus the main thread (pywebview). The 11 per-platform pollers only start when `polling_owner == "local"` (i.e. polling is not delegated to a remote server); Uvicorn / Telegram bot / Telegram digest / Posting scheduler / pystray tray icon run regardless of the polling owner.

| Thread | Purpose | Interval Source | Default | Conditional |
|--------|---------|----------------|---------|-------------|
| Uvicorn | FastAPI dashboard server | N/A (always-on) | — | always |
| IB poller | Inkbunny stat collection | `poll_interval_minutes` | 60 min | local-only |
| FA poller | FurAffinity stat collection | `fa_poll_interval_minutes` | 60 min | local-only |
| WS poller | Weasyl stat collection | `ws_poll_interval_minutes` | 60 min | local-only |
| SF poller | SoFurry stat collection | `sf_poll_interval_minutes` | 60 min | local-only |
| SqW poller | SquidgeWorld stat collection | `sqw_poll_interval_minutes` | 60 min | local-only |
| AO3 poller | AO3 stat collection | `ao3_poll_interval_minutes` | 60 min | local-only |
| DA poller | DeviantArt stat collection | `da_poll_interval_minutes` | 60 min | local-only |
| WP poller | Wattpad stat collection | `wp_poll_interval_minutes` | 60 min | local-only |
| IK poller | Itaku stat collection | `ik_poll_interval_minutes` | 60 min | local-only |
| BSKY poller | Bluesky stat collection | `bsky_poll_interval_minutes` | 60 min | local-only |
| TW poller | X/Twitter stat collection | `tw_poll_interval_minutes` | 60 min | local-only |
| Telegram digest | Cross-platform summary scheduler | `telegram_digest_interval_hours` (configurable; default 6h) | 6h | always |
| Telegram bot | Command listener (long-poll) | Continuous | — | always |
| Posting scheduler | Processes posting_queue table | Fixed 60 seconds | — | always |
| Pystray tray | System tray icon + context menu | N/A (event-driven) | — | always |

When polling is delegated to a remote server (`polling_owner == "remote"`), the 17 platform pollers stay idle and the local instance acts as a thin UI + posting + bot client; total thread count drops to 5.

### `server.py` — 4-Thread Model (Headless/Docker)

`server.py` replaces the 11 per-platform poller threads and the digest scheduler with a single unified poll orchestrator thread, and adds a posting scheduler:

| Thread | Purpose | Interval Source | Default |
|--------|---------|----------------|---------|
| Uvicorn | FastAPI dashboard server | N/A (always-on) | — |
| Poll orchestrator | Polls all platforms, sends consolidated summary, fires digests | `poll_interval_minutes` | 240 min |
| Telegram bot | Command listener (long-poll) | Continuous | — |
| Posting scheduler | Processes posting_queue table | Fixed 60 seconds | — |

### Per-Platform Thread Pattern (`main.py` only)

In the desktop 15-thread model, every poller function (`_start_poller()`, `_start_fa_poller()`, etc.) follows the exact same pattern. **As of 2.68.0** the poll step goes through the shared `_poll_platform_accounts(platform, run_cycle)` helper (module scope in `main.py`), which mirrors the server orchestrator's `_poll_accounts`: it seeds + enumerates the platform's enabled account rows and runs the cycle once per account (passing `account_id`, per-account credential check, isolated failures), falling back to a single default poll if the accounts table is empty/unreadable. So the desktop now polls **all** configured accounts per platform, not just the default. The flat credential gate (step 1) stays as a cheap "is this platform configured at all" early-out:

```python
def _start_XX_poller():
    import asyncio
    from polling.XX_poller import run_XX_poll_cycle

    async def _scheduled_XX_poll():
        # 1. Credential gating — skip if platform not configured
        settings = config.get_settings()
        if not settings.get("XX_credential"):
            logger.info("Scheduled XX poll skipped — no credentials configured")
            return
        # 2. Execute poll cycle with error catching
        try:
            await _poll_platform_accounts("XX", run_XX_poll_cycle)
        except Exception as e:
            logger.error("Scheduled XX poll failed: %s", e)

    async def _run():
        logger.info("XX poller loop started")
        if not config.get_settings().get("polling_paused"):
            await _scheduled_XX_poll()       # Immediate first poll on startup
        else:
            logger.info("XX initial poll skipped -- polling is paused")
        while True:
            # 3. Dynamic interval — re-read from settings each cycle
            settings = config.get_settings()
            interval = settings.get("XX_poll_interval_minutes", 60)
            logger.info("Next XX poll in %d minutes", interval)
            await asyncio.sleep(interval * 60)
            if config.get_settings().get("polling_paused"):
                logger.info("XX poll skipped -- polling is paused")
                continue
            await _scheduled_XX_poll()

    # 4. Isolated event loop per thread
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(_run())
    except Exception as e:
        logger.debug("XX poller thread exiting: %s", e)  # Daemon teardown
```

Key design decisions (applies to `main.py` per-platform threads):
1. **Own asyncio event loop**: asyncio loops are bound to a single thread. `new_event_loop()` + `set_event_loop()` gives each poller its own isolated async runtime. The main thread's loop (if any) cannot be reused.
2. **Immediate first poll**: So the dashboard has data right away without waiting for the first interval to elapse. Respects the `polling_paused` setting — if paused, the initial poll is skipped and every subsequent cycle also checks the flag before executing.
3. **Dynamic interval**: Users can change the polling frequency in the UI and it takes effect on the very next cycle without restarting the app.
4. **Credential gating**: If the user hasn't configured a platform yet, the cycle is silently skipped rather than erroring.

### Unified Poll Orchestrator Pattern (`server.py` only)

The poll orchestrator (`_start_poll_orchestrator()`) consolidates all polling and digest scheduling into a single thread with its own asyncio event loop. Each cycle:

1. **Credential check**: Reads `settings.json` and builds a list of configured platforms (skips unconfigured ones)
2. **Concurrent polling**: Calls all configured platform poll functions via `asyncio.gather()`, running them in parallel within a single event loop
3. **Consolidated notification**: Sends one Telegram message summarising all platform results, suppressing individual per-platform notifications via the `orchestrated_poll_active` flag on the `polling.telegram` module
4. **Digest check**: If elapsed time since `last_digest_sent_at` exceeds `telegram_digest_interval_hours`, fires `send_digest_report()`
5. **Weekly digest check**: If elapsed time since `last_weekly_digest_sent_at` exceeds 7 days, fires `send_weekly_digest_report()`
6. **Sleep**: Waits `poll_interval_minutes` (re-read from settings each cycle), then repeats

The orchestrator uses a single `poll_interval_minutes` setting for all platforms (default 240 minutes, minimum 15). Per-platform interval settings (`fa_poll_interval_minutes`, etc.) are ignored by `server.py` but still used by `main.py`.

A 5-second startup delay ensures uvicorn is ready and settings are seeded before the first poll cycle begins. Digests no longer need a separate startup delay because they are checked after each poll cycle, which inherently means poll data is available.

### First-Poll Notification Suppression

Both architectures suppress notifications on the first poll after startup to establish a baseline. Without this, every existing comment, fave, and watcher would trigger an alert on startup.

**`main.py` (per-platform threads)**: Each poller tracks a `_XX_first_poll = True` flag. On the first poll, all data is collected normally but notifications are suppressed. After the first poll completes (success or failure), the flag is set to `False` and subsequent polls notify normally.

**`server.py` (orchestrator)**: The orchestrator tracks `_first_cycle = True`. On the first cycle, all platforms are polled and data is collected, but the consolidated Telegram summary is skipped. Subsequent cycles send summaries normally.

### Daemon Thread Behaviour

All threads in both `main.py` and `server.py` are `daemon=True`, meaning they are killed automatically when the main thread exits. This avoids zombie processes but means pollers don't get a graceful shutdown signal — they simply stop mid-execution.

The `except Exception` blocks around each thread's `loop.run_until_complete()` catch the resulting teardown exceptions and log them at `logger.debug()` level. During normal shutdown, Python raises exceptions in daemon threads as the interpreter shuts down. These are harmless but would be invisible without the debug logging — if a poller or the orchestrator crashes for a real reason (import error, bug), the debug log captures it.

### Telegram Digest Scheduling

**`main.py`**: The digest runs in its own dedicated thread with a 5-minute startup delay (`await asyncio.sleep(300)`) to ensure pollers have completed their initial cycles before the first digest is generated.

**`server.py`**: There is no separate digest thread. Digests are integrated into the poll orchestrator and fire after a poll cycle completes when the configured digest interval has elapsed. Because digests are checked after every poll cycle, data is always fresh. The `poll_interval_minutes` should be a divisor of the digest interval (e.g. poll every 4h, digest every 12h) to ensure predictable timing.

---

## 4. Platform Clients

Each platform has a dedicated async HTTP client using `httpx.AsyncClient`. All support context manager protocol (`async with client:`). Below are deep technical details for each.

### Inkbunny (`clients/ib/client.py`) — `InkbunnyClient`

**Dual HTTP transport pattern**: The IB client maintains two separate httpx clients:
- `_http` — API client for JSON endpoints (`/api_login.php`, `/api_search.php`, etc.)
- `_web_http` — Browser-authenticated client for HTML scraping (comments, watchers). Uses cookies from a separate web form login (`login_process.php`) because the API SID doesn't work for web pages.

**Authentication & SID Caching**:
```
1. Check for cached SID in session_cache table (singleton row, id=1)
2. If cached SID exists, validate via lightweight search probe
3. If valid, reuse → skip login entirely
4. If invalid or no cache, full login via /api_login.php
5. On successful login, call /api_userrating.php to unlock all content ratings
6. Cache new SID in session_cache table
```

Rating unlock calls `/api_userrating.php` with `tag[2]=yes&tag[3]=yes&tag[4]=yes&tag[5]=yes` to enable: Violence (2), Sexual (3), Strong Violence (4), Strong Sexual (5). Without this, submissions with restricted ratings would be invisible in search results.

**Web login for scraping** (separate from API login):
1. GET `/login.php` to extract CSRF `token` from hidden input
2. POST `/login_process.php` with `token`, `username`, `password`
3. Session cookies stored in `_web_http` for subsequent scraping

**Key methods**:
| Method | API Endpoint | Purpose |
|--------|-------------|---------|
| `login()` | `/api_login.php` | Authenticate, return SID |
| `ensure_session(sid)` | `/api_search.php` (probe) | Validate cached SID or re-login |
| `search_user_submissions(username)` | `/api_search.php` | Paginated gallery discovery (100/page, max 1000 pages) |
| `get_submission_details(ids)` | `/api_submissions.php` | Batch-fetch metadata (configurable batch size) |
| `get_faving_users(submission_id)` | `/api_submissionfavingusers.php` | Per-submission fave user list |
| `scrape_comments(submission_id)` | `/s/{id}` (HTML) | Regex-based comment extraction from web page |
| `scrape_watchers()` | `/usersviewall.php?mode=watched_by` | Paginated watcher scraping |

**Comment scraping implementation**: Comments are stored in hidden HTML inputs on the submission page:
- Username: `id='comment_ownername_commentid_NNN'` hidden input
- Text: `id='bbcode_commentid_NNN'` hidden input
- Timestamp: `id='commentid_NNN_exact'` div
- Reply detection: CSS class `indented` on container div
- Reply-to: anchor tag with `title='In reply to'` in a 3000-character local section search

**Submission detail data structure** (returned by `to_db_dict()`):
```python
{
    "submission_id": int,       # IB's integer ID
    "title": str,
    "username": str,            # Author username
    "user_id": int,             # Author numeric ID
    "create_datetime": str,     # When posted on IB
    "type_name": str,           # "Picture/Pinup", "Writing", "Music", etc.
    "rating_id": int,           # 0=General, 1=Mature, 2=Adult
    "rating_name": str,         # Human-readable rating
    "thumb_url": str,           # Thumbnail CDN URL
    "url": str,                 # Direct file download URL
    "description": str,         # HTML body text
    "keywords": str,            # JSON-serialized array of tag strings
    "page_count": int,          # Multi-page submissions (comics)
    "views": int,
    "favorites_count": int,
    "comments_count": int,
}
```

### FurAffinity (`clients/fa/client.py`) — `FAClient`

**Dual HTTP transport pattern**:
- `_http` — Unauthenticated FAExport client (`https://faexport.spangle.org.uk`) for JSON data
- `_fa_http` — Direct FA client with session cookies; lazy-initialized. Used for cookie validation AND the direct-scrape polling fallback (`fa_direct_polling`).

**Direct-scrape fallback (refreshed 2.28.2):** `get_all_gallery_ids_direct` (`/gallery/{user}/{page}/`) + `get_submission_detail_direct` (`/view/{id}/` → `_parse_submission_html`) replace FAExport when `fa_direct_polling=true`. FA's current submission HTML: stats in `<div class="submission-page-stats"><div title="Views"><div>N</div>` (Favorites count wrapped in a `/favslist` link), title `submission-title><h2`, rating from the `twitter:label2/data2` meta, tags as `data-tag-name`. **Server-side:** when `fa_use_cf_proxy` is set, `_get_fa_http` routes the direct scrape through the CF Worker (FA blocks datacenter IPs but allows Cloudflare's egress; FA cookies authenticate through it). On the proxy path, cookies are managed at the transport level only — NOT also via the httpx jar (both accumulating Set-Cookie corrupts the session on the 2nd request).

**Cookie authentication**: FA uses two cookies (`a` and `b`) extracted from the user's browser. Validation loads the user's gallery page and checks for `<figure>` HTML elements (present only when authenticated).

**FAExport API endpoints used**:
| Endpoint | Purpose | Rate Limited |
|----------|---------|-------------|
| `/user/{username}/gallery.json?page=X&full=1` | Paginated gallery listing | Yes |
| `/submission/{id}.json` | Single submission detail | Yes |
| `/submission/{id}/comments.json` | Comment thread (JSON) | Yes |
| `/user/{username}.json` | User profile (spam detection) | Yes |
| `/user/{username}/watchers.json?page=X` | Watcher list | Yes |

**Data normalisation challenges**: FAExport has inconsistent response formats:
- Tag field: sometimes `"tags"`, sometimes `"keywords"`; sometimes a list, sometimes a comma-separated string
- Comment field: can be `int` (count only) or `list[dict]` (full comment objects)
- Some endpoints nest metadata under an `"info"` key
- Numeric values may be comma-formatted strings (`"1,234"`) — all parsed through `_safe_int()`

**Comment data structure** (FA-specific differences from IB):
```python
{
    "comment_id": str,              # TEXT, not integer (from HTML anchors)
    "submission_id": int,
    "username": str,                # "name" or "profile_name" field
    "comment_text": str,
    "commented_at": str,            # "posted_at" or "posted" field
    "reply_to": str | None,         # Parent comment ID (TEXT, not int)
    "reply_level": int,             # Nesting depth (0 = top-level)
    "is_deleted": int,              # 0/1 flag for removed comments
}
```

**Watcher spam detection**: FA has a persistent problem with bot/spam watchers. The poller (`polling/fa_poller.py`) combines three filter layers before the dashboard notifies on a new watcher:

1. **Keyword filter** — `_SPAM_KEYWORDS` regex rejects usernames containing gambling/adult-spam keywords (1xbet, casino, viagra, onlyfans, escort, etc.) immediately.
2. **Alphanumeric soup filter** — `_ALPHANUM_SOUP` regex catches bot-generated names like `2charlottec262ye0` (8+ characters, mostly digits mixed with letters, >40% digit ratio).
3. **Profile sniffing** — `sniff_watcher_profiles()` checks FAExport's user profile endpoint for activity indicators (zero submissions + zero favorites + zero watches = likely bot). Returns `{username: is_spam}` dict, capped at 10 profiles per poll. See §5 for the full 5-step watcher pipeline including the 2-cycle confirmation gate and bulk-wave threshold.

Helper utility: `_safe_int()` parses comma-formatted strings like `"1,234"` from FAExport's inconsistent count fields (sometimes int, sometimes int-shaped string).

### Weasyl (`clients/weasyl/client.py`) — `WeasylClient`

The simplest client. Clean JSON responses, no scraping needed.

**Authentication**: API key in header `X-Weasyl-API-Key`. Validated via `/api/whoami` which returns `{"login": "username", "userid": 12345}`.

**Cursor-based pagination** (unlike IB's page-number pagination):
```python
nextid = None
while True:
    params = {}
    if nextid:
        params["nextid"] = nextid
    data = await self._http.get(f"/api/users/{username}/gallery", params=params)
    # Process submissions...
    nextid = data.get("nextid")  # Exclusive lower bound for next page
    if not nextid:
        break  # No more pages
```
This is robust to insertions/deletions between page fetches — unlike offset-based pagination which can skip or duplicate entries.

**Media structure** (nested JSON):
```python
# Thumbnail and full-resolution URLs are nested under media arrays
detail["thumbnail_url"] = data.get("media", {}).get("thumbnail", [{}])[0].get("url", "")
detail["media_url"] = data.get("media", {}).get("submission", [{}])[0].get("url", "")
```

**Limitations**: No per-user comment text, no faving user lists, no watcher tracking — Weasyl's API only exposes aggregate counts.

### SoFurry (`clients/sf/client.py`) — `SoFurryClient`

**Authentication flow** (Laravel CSRF):
```
1. GET /login → extract CSRF _token from hidden form field
2. POST /login with {_token, email, password, remember: "on"}
3. If 2FA enabled → redirects to /auth/2fa → submit TOTP code
4. On success → session cookies set (including remember_web_* 30-day cookie), redirect to /
```

**Critical: Login must use email address, not display name.** The `sf_username` setting should contain the user's email. The `sf_display_name` is the public profile handle (e.g. "KnaughtyKat") used for gallery URLs.

**Two authentication modes**:

1. **Direct login** (default for local/desktop): The client authenticates directly with SoFurry using `"remember": "on"` in the login POST, which triggers a `remember_web_*` cookie lasting ~30 days. Session cookies can be persisted to `settings.json` and restored on restart, allowing the app to skip re-login for the cookie's lifetime.

2. **CF Worker proxy** (required for server/datacenter IPs): When `proxy_url` and `proxy_key` are provided, the client swaps `httpx.AsyncHTTPTransport` for `CloudflareProxyTransport`. In proxy mode, the client uses `login_and_fetch_gallery()` which performs GET/POST login + gallery fetch in a single Worker invocation. Cookie persistence is disabled in proxy mode because CF Workers rotate egress IPs between invocations and SoFurry pins sessions to the login IP.

**Session cookie persistence** (`export_cookies()` / `import_cookies()`):
- After a successful gallery fetch, the poller calls `export_cookies()` to serialize the httpx cookie jar (cookie names, values, domains, paths) plus metadata (`saved_at`, `saved_for_user`) into a dict stored as `sf_session_cookies` in `settings.json`.
- On startup, the poller calls `import_cookies()` to restore cookies from `settings.json`. Validates that `saved_for_user` matches the current username (rejects stale cookies from a different account).
- `ensure_logged_in()` handles the restored-cookies case: if cookies exist in the jar but `_logged_in` is False, it temporarily sets the flag and calls `check_session()` to test them. If valid, login is skipped entirely. If invalid (expired/corrupt), falls back to fresh login.
- Cookie persistence is only used in direct login mode (not through CF proxy).
- Cookies are automatically cleared when credentials change (`update_credentials()` returns `True`).
- The `/auth/connect` endpoint also saves cookies after successful validation.
- The `/auth/disconnect` endpoint clears `sf_session_cookies` along with credentials.

**Stored cookie structure** (in `settings.json`):
```json
"sf_session_cookies": {
  "cookies": {
    "XSRF-TOKEN": {"value": "...", "domain": ".sofurry.com", "path": "/"},
    "sofurry_session": {"value": "...", "domain": ".sofurry.com", "path": "/"},
    "remember_web_...": {"value": "...", "domain": ".sofurry.com", "path": "/"},
    "sfxlogin": {"value": "...", "domain": ".sofurry.com", "path": "/"}
  },
  "saved_at": "2026-03-10T12:00:00+00:00",
  "saved_for_user": "user@example.com"
}
```

**SoFurry "beta" (2026-06 React-Router rewrite).** SF is now a hybrid: Laravel
serves auth (`/login`); a Remix front-end serves browse + a new `/api/*`. Full
reverse-engineered map: `docs/reference/sofurry_beta_api_map.md`.

**Polling** (login-free for published works): stats come from React-Router loader
data at `GET /s/{id}.data` (turbo-stream; `views`/`likes`/comment count parsed by
`_rr_int`/`_rr_str`). Discovery reads `/u/{handle}/gallery.data` (SFW-filtered when
logged out, so new-work auto-discovery needs an authed session).

**Posting** (authenticated, 2.28.0): Laravel `/login` then the **`/fe/auth/sofurry`
OAuth2-PKCE bridge** mints an authed Remix session (`_ensure_api_session()`). Writes
send `X-CSRF-Token` (from `<meta name="csrf-token">`):
- `POST /api/upload-create` → mint an empty submission (`{id}`)
- `POST /api/upload-content` (multipart `submissionId`+`file`, HTML ≥ 1 KB) → add a content item
- `POST /api/submission-editor` (a `_endpoint`/`_method` dispatcher) → set metadata, chapter titles (`submission/{id}/content/{cid}`), order (`contentOrder[]`), delete content (`upload/{id}/content/{cid}` + `_method=DELETE`), thumbnail (`submission/{id}/thumbnail` + multipart `file`, png/jpeg/webp 1 KB–1 MB; `_method=DELETE` regenerates)
- `GET /api/submission/{id}` → read (fields nested under `submission`; category/type echo display strings)
- `DELETE /api/submission/{id}` → delete
Category/type are INT codes on write (20=Writing, 21=Short Story, 29=Book). The old
`/ui/submission*` API is gone (Remix 404s `/ui/*`).

**Followers:** count from login-free `GET /api/profile?handle=` (`user.followerCount`);
the username list from login-free `GET /api/followers?handle=&mode=followers&page=`
(20/page, `hasNextPage`) → `users[].handle`, so new-follower notifications work.
**Discovery:** `get_all_gallery_ids()` (2.28.1) extracts every id-shaped token from the
authed `gallery.data` turbo-stream (8 alnum chars with ≥1 digit/uppercase — drops
lowercase tag values), minus the profile's own user id (`/api/profile`) and folder ids
(`/api/folders`); the poller runs the auth bridge best-effort first so the gallery
includes adult works. Candidates are validated by the poller — a newly-discovered id
whose `/s/{id}.data` has no title (a folder or field-name token) is skipped, not stored
as a junk 0-view row.

### SquidgeWorld (`clients/sqw/client.py`) — `SqWClient`

**OTW Archive authentication** (same software as AO3, Rails form login):
```
1. GET /users/login → extract authenticity_token from hidden input
2. POST /users/login with {authenticity_token, user[login], user[password], user[remember_me]}
3. Check for logged-in indicators: "Hi, username", "Log Out", class="greeting"
```

**Anubis bot challenge**: SquidgeWorld deploys Anubis (SHA-256 proof-of-work challenge). When the client receives a challenge page instead of the expected content:
1. Extract `preact_info` JSON from the page
2. Compute `SHA256(challenge_string)`
3. GET `/pass-challenge?result={hex_digest}`
4. Receive auth cookie, retry original request

**Stats fields**: hits, kudos, comments, bookmarks (same as AO3 since it's the same software).

### AO3 (`clients/ao3/client.py`) — `AO3Client`

Same OTW authentication as SquidgeWorld. Key differences:

**Dual-mode auth (2.18.8+)**: AO3 throttles per-IP login attempts aggressively (5-60 min lockout after a single failed probe), and datacenter IPs typically can't log in at all. The client supports two auth paths:

1. **Username/password** — classic form login, fine from residential IPs.
2. **Session cookie** — paste your `_otwarchive_session` cookie value from a logged-in browser; the constructor accepts `session_cookie=""` and when truthy, injects it at `domain="archiveofourown.org"` and asserts `_logged_in=True` up front. `ensure_logged_in()` skips the verify fetch when a cookie is set (the verify fetch itself is rate-limited, so probing creates false negatives). When AO3 reports we're no longer logged in via a real request, the cookie is cleared and the user prompted to re-paste — there is no fallback to form login, which would just re-trip the rate limiter.

The cookie path is the recommended setup for server deployments; the `ao3_session_cookie` field is stored encrypted in the vault alongside other credentials.

**Poll-orchestrator gate (server.py:~213)**: the server's per-platform credential check uses an OR — `(ao3_username AND ao3_password) OR ao3_session_cookie`. Cookie-only deployments are valid and AO3 will be scheduled into every poll cycle. (Pre-2.22.2 this gate was AND-only and silently excluded cookie-only deployments from polling; symptoms were "AO3 dashboard tab empty + kudos counts stuck at 0" with no error in logs — the orchestrator simply skipped the platform.)

**Rate limiting**: 3-second delay between requests — the slowest of any client. AO3 is run entirely by volunteers with limited infrastructure. The delay is deliberately conservative to avoid impacting real users. The client also handles 429 (rate limited) responses with a 30-second backoff (or `Retry-After` header value when present).

**Stats extraction** (regex from HTML):
```python
# Stats are in <dd class="stat_class">1,234</dd> format
def _extract_stat(stat_class: str) -> int:
    # Primary pattern: plain text in <dd>
    pattern = rf'<dd\s+class="{stat_class}"[^>]*>\s*(\d[\d,]*)\s*</dd>'
    # Secondary pattern: text inside <a> within <dd>
    pattern2 = rf'<dd\s+class="{stat_class}"[^>]*>\s*<a[^>]*>\s*(\d[\d,]*)\s*</a>'
```

**Additional metadata**: word count, chapters current/total (e.g. "3/?"), published date, updated date, fandom, relationship tags. Full tag extraction via `class="tag"` anchors.

**Kudos user tracking**: `get_kudos_users(work_id)` extracts individual usernames from the kudos section (`id="kudos"`) — similar to IB's faving user tracking.

### DeviantArt (`clients/da/client.py`) — `DAClient`

**Official OAuth2 API (2.47.0)**: DA polling now runs on DeviantArt's official, documented OAuth2 API — the same API the DA *poster* uses (see §14 posting) — replacing the undocumented Eclipse `_napi` browser-cookie scrape. Authentication is an **app-only client-credentials** token: `da_client_id` + `da_client_secret`, with **no cookie and no user login** required. Full research write-up in `docs/research/deviantart_official_api.md`.

| Endpoint | Purpose |
|----------|---------|
| `GET /api/v1/oauth2/gallery/all?username=X&offset=Y&limit=24&mature_content=true` | Gallery enumeration (paginated: `results`, `has_more`, `next_offset`) |
| `GET /api/v1/oauth2/deviation/metadata?deviationids[]=<UUID>&ext_stats=true` | Per-deviation stats (`stats{views, views_today, favourites, comments, downloads, downloads_today}`) |

**Client-credentials auth**: `POST https://www.deviantart.com/oauth2/token` with `grant_type=client_credentials` mints an app-only bearer token — no per-user authorization, no refresh token. **Token-endpoint gotcha**: the token endpoint is `https://www.deviantart.com/oauth2/token`, **not** `/api/v1/oauth2/token` (which 404s).

**ext_stats batching**: the metadata call with `ext_stats=true` **caps at 10 deviationids per call**, so stats are fetched in chunks of ≤10 UUIDs.

**Integer-id preserved (no schema migration)**: the DB continues to key deviations by the **integer** id parsed from each deviation's `url`. The API's UUID `deviationid` is used only transiently — to make the per-deviation `metadata` call — and is not persisted. As a result the poller (`da_poller.py`), `da_queries`, `da_schema.sql`, and dashboard are **unchanged**; there is no schema migration for this switch.

**Mature content**: `mature_content=true` is passed on enumeration so adult works are included (and to avoid a 403 on mature galleries).

**No CF Worker proxy**: DeviantArt **left `PROXY_REQUIRED_PLATFORMS`** in `polling/cf_proxy.py` (now just `{"sf"}`) — the official API answers from datacenter IPs (verified 200 from the GCP VM), unlike the IP-walled Eclipse frontend. This is the same reclassification AO3 received in 2.22.11: once an auth path stops depending on the IP-walled login page, the proxy is no longer needed. See §10 / §5 CF Worker proxy gate.

**Legacy cookie/`_napi` fallback (retained)**: the old browser-cookie Eclipse scrape (`/_napi/da-user-profile/api/gallery/contents` + `/_napi/shared_api/deviation/extended_fetch`, with HTML-scrape fallback on `data-deviationid` + embedded `"stats"` JSON) is kept as a fallback. It is used **only** when no `da_client_id`/`da_client_secret` is configured but a `da_cookie` is. This legacy path still needs the CF Worker proxy on datacenter IPs.

**Unique stat**: DeviantArt is the only platform that tracks `downloads` in addition to views/favorites/comments.

### Wattpad (`clients/wp/client.py`) — `WPClient`

**No authentication required** — public REST API at `api.wattpad.com`.

**Story discovery**: `/api/v3/users/{username}/stories/published?offset=X&limit=Y`

**Story-level metrics** (not per-chapter):
```python
{
    "story_id": int,
    "title": str,
    "reads": int,           # readCount — total reads across all parts
    "votes": int,            # voteCount — reader votes
    "comments_count": int,   # commentCount
    "num_parts": int,        # Number of chapters/parts
    "num_lists": int,        # Reading lists containing this story
    "description": str,
    "cover_url": str,        # Cover image
    "completed": bool,       # Whether the story is marked complete
    "posted_at": str,        # createDate
    "updated_at": str,       # modifyDate
}
```

Rate limiting: 1s between requests, 429 handling with 30s backoff.

### Itaku (`clients/ik/client.py`) — `IKClient`

**No authentication required** — public API at `itaku.ee/api`.

**User resolution**: `/api/user_profiles/{username}/` returns the owner's numeric ID, needed for content queries.

**Two content types**: `gallery_images` and `posts`. Both are discovered via paginated API calls with cursor-based pagination (response includes `next` URL).

**Stats**: likes, comments, reshares. **No views metric** — Itaku does not expose view counts. This means the dashboard's "views" column is blank for Itaku submissions.

Rate limiting: 429 handling with 30s backoff.

### Bluesky (`clients/bsky/client.py`) — `BskyClient`

**AT Protocol API** at `bsky.social/xrpc`. Authenticated via app password → JWT session tokens.

**Session management**: `com.atproto.server.createSession` returns `accessJwt` + `refreshJwt` + DID. Access tokens are short-lived; the client auto-refreshes via `com.atproto.server.refreshSession` on 401, with full re-login as fallback. Chain: `check_session()` → `refresh_session()` → `login()`.

**Post discovery**: `app.bsky.feed.getAuthorFeed` with cursor-based pagination. Each response includes `cursor` for the next page. Returns AT URIs (`at://did:plc:xxx/app.bsky.feed.post/yyy`).

**Post detail**: `app.bsky.feed.getPosts` accepts up to 25 URIs per call. Returns likes, reposts, replies, quotes. Batched with rate limiting between calls.

**AT URI handling**: AT URIs contain slashes, so they're stored as TEXT primary keys in SQLite. The `rkey` (final path segment) is used for URL-friendly frontend routes. API resolves by suffix match (`LIKE '%/' || rkey`).

**Stats**: likes, reposts, replies, quotes. **No views metric** — Bluesky does not expose impression counts. This means the dashboard has 4 stat cards instead of the typical 5.

**Post links**: `https://bsky.app/profile/{handle}/post/{rkey}` where rkey is the last segment of the AT URI.

Rate limiting: 1s between requests, 429 handling with 30s backoff.

### X/Twitter (`clients/tw/client.py`) — `TWClient`

**Cookie-based GraphQL scraping** — uses internal GraphQL endpoints discovered from browser network inspection. (This is the same cookie-scrape style that DeviantArt polling used before it moved to the official OAuth2 API in 2.47.0; DA now only cookie-scrapes in its retained legacy fallback.)

**Cookie authentication**: `auth_token` + `ct0` cookies from the user's browser. The `ct0` value is also sent as `x-csrf-token` header. Validated by making a lightweight request and checking for non-403 response.

**Bearer token**: A hardcoded public bearer token is included in all requests. This is NOT a secret — it's embedded in X's web client JavaScript bundle, shared by all users, and required for all GraphQL requests.

**GraphQL endpoints**:

| Endpoint | Purpose |
|----------|---------|
| `UserByScreenName` | Resolve username → numeric rest_id |
| `UserTweets` | Cursor-paginated tweet listing for a user |
| `TweetResultByRestId` | Full tweet detail with all stats |

**Content type detection**: Tweets are classified by checking `in_reply_to_status_id_str` (reply), `retweeted_status_result` (retweet), `quoted_status_id_str` (quote), else "tweet".

**Stats**: views, likes, retweets, replies, quotes, bookmarks — **6 metrics**, the most of any platform. Tweet IDs are stored as TEXT because 64-bit integers exceed JS `Number.MAX_SAFE_INTEGER`.

**GraphQL query IDs**: Hardcoded known IDs that may rotate over time as X updates their frontend. Comments note this limitation.

Rate limiting: 2s between requests, 429 handling with 60s backoff (X is aggressive about rate limiting).

#### X poll backend priority (the hybrid)

`TWClient.get_all_tweets()` and `validate_cookies()` try backends in order, each returning `None` when it's not its turn / unavailable / errored, so the chain simply falls through:

1. **gallery-dl** (`clients/tw/gallerydl.py`, 2.105.0) — free, tracks X's internal API. **The primary path (2.119.0)**, so a normal poll costs nothing.
2. **Official X API v2** (`clients/tw/official_api.py`, 2.106.0) — the **paid fallback**: reached only when gallery-dl returns `None` (fails/unavailable). ToS-compliant + IP-agnostic, so it reliably rescues the cycle — and you're billed a request *only* on that fallback, not every poll.
3. **GraphQL scrape** (`_get_all_tweets_graphql`) — always-available last-ditch fallback (fragile hardcoded query IDs).

**Why gallery-dl-first (2.119.0):** the official API is reliable but billed per request; ordering the free scraper ahead of it means the paid call happens only on the rare poll gallery-dl can't serve. Previously the order was official→gallerydl→graphql (paid every cycle whenever a token was set).

`tw_polling_backend` (plain setting): `auto` (default, **gallerydl→official→graphql**), `official` (forces the paid API first — gallery-dl stands down via its `is_enabled`), `gallerydl` (gallery-dl only, drops the paid fallback), `graphql` (scrape only). **Posting is unaffected** by all of this — it always uses the GraphQL `create_tweet` path.

**Shared cross-account rate limiter (2.106.1) — `polling/rate_limit.py`.** X's timeline rate limit is **per-IP, shared across all a user's accounts**, so `_poll_accounts` polling several X accounts back-to-back can exceed it even though each account paces its own requests. `TWClient._get_json` (GraphQL) and `official_api.py` (official API) `await tw_acquire()` before every request, admitting at most `TW_RATE_LIMIT_REQUESTS` (15) per `TW_RATE_LIMIT_WINDOW_SECONDS` (30 s) as a **sliding window, globally** — FIFO, so requests are genuinely sequenced. gallery-dl (subprocess) self-paces via `--sleep-request 2.0` and isn't gated here. **Scope (measured, don't overclaim):** a sequential 3-account test on a cooled IP still throttled the 3rd account after 12+13 made only ~3-4 requests — X's per-IP budget for the datacenter is **~2 account-scrapes per window**, *below* 15/30 s, and the reset is >8 min. So this limiter is a **burst guard** that keeps PawPoller from *worsening* the throttle; it cannot manufacture budget the IP lacks, and cannot gate gallery-dl's own subprocess requests. The durable fix for 3+ accounts remains the **official API** (2.106.0, IP-agnostic) or **round-robin polling** (fewer accounts per cycle).

**Round-robin X polling (2.107.0) — `polling/roundrobin.py`.** The measured fix for the multi-account throttle: since the datacenter IP only affords ~2 X account-scrapes per window, the scheduler polls fewer accounts per cycle instead of all of them. `select_roundrobin(accts, batch_size, last_poll_by_id)` is a pure helper returning the `batch_size` **least-recently-polled** accounts — never-polled first, then oldest `started_at`, tie-broken by `account_id`. The last-poll map comes from `tw_queries.get_tw_last_poll_by_account` (`SELECT account_id, MAX(started_at) FROM tw_poll_log GROUP BY account_id`), so rotation is driven by real poll history and stays fair across redeploys/restarts (which reset the in-memory poll timer) — no cursor to persist. `server.py` narrows `accts_by_platform["tw"]` to `TW_ROUNDROBIN_BATCH` (default 2; per-user override `tw_roundrobin_batch`; 0 = poll all) *before* building the per-platform poll tasks, and logs `TW round-robin: polling N/M accounts this cycle (labels)`. **Only X is round-robined** — every other platform polls all its accounts, because only X carries the shared per-IP budget. Batch 2 keeps each cycle inside the budget; at the 12 h cadence 3 accounts each refresh ~every 18 h. This composes with the 2.106.1 limiter (burst guard on direct requests) and the 2.106.0 official API (IP-agnostic, the way to poll *all* accounts every cycle).

**Backend-aware round-robin (2.109.0, corrected 2.120.0).** Round-robin is throttle-protection for the *scraper*, but the official API has no per-IP limit, so blindly round-robining under it just caps coverage. `effective_batch(configured, *, official_primary, save_tokens)` (`polling/roundrobin.py`) encodes the policy: whenever a scraper is the primary path it gets the configured batch (round-robin ON); only when the IP-agnostic official API is the **primary** backend do we return batch 0 (poll every account each cycle) — unless `tw_roundrobin_save_tokens` is set, which round-robins to spend fewer paid reads. **2.120.0 fix:** the input was `official_active` = `official_api.is_enabled(settings)` (token present), which was right when the official API was tier 1 but became stale in 2.119.0 when gallery-dl became the primary and the official API a paid *fallback* — a present-but-fallback token wrongly returned batch 0, so all accounts polled and the tail hit the paid fallback. `server.py` now computes `official_primary = official_api.is_enabled(s) AND NOT gallerydl.is_enabled(s)`, so round-robin correctly stays ON while gallery-dl leads. **Upshot:** with the default `auto` backend (gallery-dl primary) X round-robins to `TW_ROUNDROBIN_BATCH` (2); only forcing `tw_polling_backend="official"` polls all accounts every cycle via the paid API.

**X account stagger (2.120.0) — `rate_limit.tw_account_stagger`.** The *other* way to poll all X accounts every cycle for free (vs. the paid official API): set `tw_roundrobin_batch=0` and let the stagger keep the scraper under the per-IP throttle. `tw_account_stagger(platform, polled_count, settings)` polls X accounts in **bursts of `TW_ACCOUNT_STAGGER_EVERY` (2)** — the measured per-IP budget — and sleeps `tw_account_stagger_seconds` (default `TW_ACCOUNT_STAGGER_SECONDS` = 480 = 8 min, >X's reset window) **between** bursts, so each account starts on a fresh window and stays on free gallery-dl. Called before polling each X account, passing how many X accounts were already polled this cycle; it sleeps only at a burst boundary (`polled_count` a positive multiple of 2), so the first burst — and any 1–2 account cycle or a round-robin batch of 2 — is never slowed. No-op for non-X. Wired into all three account loops (`server.py._poll_accounts`, `main.py._poll_platform_accounts`, `multi_account.poll_platform_accounts`), `sleep_fn` injectable for tests. For 3 accounts: burst {1,2} → 8-min gap → {3}.

**Manual per-account poll (2.110.0) — `polling/multi_account.py`.** Distinct from the scheduled cycle: the dashboard "Poll Now" button. It used to call `run_<code>_poll_cycle()` with no account → only the platform's *default* account was polled. `poll_platform_accounts(platform, account_id=None)` fixes that — a specific `account_id` polls that one; `None` enumerates the platform's enabled accounts and polls each in sequence (same loop shape as `server.py._poll_accounts`, falling back to a single default poll if none are seeded). `get_poll_cycles()` is the code→`run_<code>_poll_cycle` registry (all 17; keep in sync with `server.py`'s `account_aware`). Endpoint: `POST /api/poll/trigger/{code}?account_id=` (the account-less `POST /api/poll/trigger` stays IB-only for back-compat). Frontend `_dashPoll` passes `App._accountFilter[code]` (the context-bar account switcher, rendered for any platform with 2+ accounts), so "Poll Now" polls whatever account you're viewing, or all. **Manual polls are explicit and ignore the scheduled round-robin/save-tokens throttle** — a manual "poll all" always polls all accounts (but a manual "poll all X" still applies the 2.120.0 `tw_account_stagger` between X accounts, since that's per-IP protection, not a coverage cap).

#### Official X API v2 backend (2.106.0) — `clients/tw/official_api.py`

The proper fix for the **datacenter-IP rate limit** (X `429`s the scrapers' timeline requests from a server IP; see 2.105.1). The official API authenticates per-token, so it's not IP-throttled the same way.

- **Opt-in, bring-your-own-token.** A Bearer token from developer.x.com (`tw_api_bearer_token`, **vaulted secret**) enables it. `is_enabled(settings)` = token present AND `tw_polling_backend` not in (`graphql`,`gallerydl`).
- **Reads `public_metrics`** = our exact six columns (`impression_count`→views, like/retweet/reply/quote/bookmark). `_build_detail()` returns the identical detail-dict shape as the scrapers (content-type from `referenced_tweets`; photo `media_urls` from `expansions=attachments.media_keys`; Snowflake not needed — `created_at` is present). **No schema change.**
- **Endpoints:** `GET /2/users/by/username/{handle}?user.fields=public_metrics` (resolves id + follower count in one call — cached in `_LAST_FOLLOWERS` so `get_follower_count()` spends no extra billed request), then paginated `GET /2/users/{id}/tweets?exclude=retweets&tweet.fields=public_metrics,...` (≤32 pages × 100 = X's ~3,200 lookback cap).
- **Fallback contract:** `fetch_tweets()` returns `None` on a bad token (401/403 on resolve) or first-page failure → caller falls back to a scraper; a later-page failure returns the partial data. `validate()` returns True/False/None (definitive vs inconclusive).
- **Token-only, no cookies:** the poller (`tw_poller.py`) drops the `auth_token`/`ct0` requirement when `official_api.is_enabled()`; `validate_cookies()` returns True on a valid Bearer token without touching cookies.
- **Cost (pay-per-use):** owned reads ~$0.001 each (~$2–7/month typical); the poll cadence bounds spend — never `force_full` on a timer. Guardrails (recent-only reads, in-UI estimate) = Phase 2. Full design: `docs/specs/x_official_api.md`.
- **Routes:** `/api/tw/auth/status` reports `poll_backend` + `has_api_token`; `POST /api/tw/api-token/connect` (validate + vault) and `/api-token/disconnect`.

#### gallery-dl poll backend (2.105.0) — `clients/tw/gallerydl.py`

Because the GraphQL query IDs above rotate whenever X ships a new web bundle, the **poll (read) path prefers [gallery-dl](https://github.com/mikf/gallery-dl)** — a maintained downloader that tracks X's internal API for us — and only falls back to the GraphQL scrape above.

- **Hybrid, fallback-first.** `TWClient.get_all_tweets()` calls `gallerydl.fetch_tweets(...)`; the renamed `_get_all_tweets_graphql()` holds the original scrape as the fallback. `validate_cookies()` calls `gallerydl.validate(...)` first, then the `UserByScreenName` check. A gallery-dl result (even an empty list) is **authoritative**; only `None` (gallery-dl unavailable/disabled/errored) triggers the fallback. Net effect: with gallery-dl absent, X polling is byte-for-byte the old behaviour.
- **Read-only.** gallery-dl cannot post — `create_tweet`/`upload_media` (Posts module) stay on GraphQL, untouched.
- **Licence isolation (GPL-2.0).** gallery-dl is invoked **only as a subprocess** (`asyncio.create_subprocess_exec`) and **never imported** — mere aggregation, so PawPoller's MIT licence is unaffected. **Do not add `import gallery_dl` anywhere.**
- **Invocation.** `gallery-dl -j -q --cookies <temp Netscape jar> --sleep-request <TW_REQUEST_DELAY_SECONDS> -o extractor.twitter.text-tweets=true -o extractor.twitter.retweets=false -o extractor.twitter.videos=false "https://x.com/<user>/tweets"`. The temp cookie jar is written from the same `auth_token`+`ct0` and deleted in a `finally`. `-j` dumps metadata (no media download); `_parse_dump_json()` reads the JSON array (each element's **last dict** is the tweet kwdict — robust to gallery-dl's message-type ints) into the identical detail-dict shape, keying `view_count`/`favorite_count`/`retweet_count`/`reply_count`/`quote_count`/`bookmark_count`, collecting photo `media_urls`, and falling back to the Snowflake-id date. Runs are capped by `TW_GALLERYDL_TIMEOUT_SECONDS` (480s — long enough to ride out a typical X rate-limit reset, since from a datacenter IP X 429s the timeline endpoint and gallery-dl correctly waits for the reset before fetching; see 2.105.1).
- **Config / delivery.** In `requirements-server.txt` (server build → console script on PATH) and `requirements.txt` (source/dev); **not** bundled into the frozen `.exe` (never imported → PyInstaller skips it) — packaged desktop auto-detects a PATH install or falls back. Plain (non-secret) settings: `tw_gallerydl_path` (explicit binary), `tw_polling_backend` (`auto` default / `graphql` forces the legacy scrape). `/api/tw/auth/status` reports `poll_backend` + `gallerydl_available`.
- **Behavioural delta.** The gallery-dl path uses `retweets=false` (own posts), so the GraphQL path's niche "keep a repost that @-mentions me" doesn't apply on that backend; already-captured rows are never deleted (upserts only accumulate).
- **Follower count rides along for free (2.121.0).** gallery-dl's tweet metadata carries `author.followers_count`, so `fetch_tweets` extracts it (`_extract_follower_count`, preferring the author whose handle matches the tracked account) and caches it per-handle in `_LAST_FOLLOWERS`; the pure-cache-read `get_follower_count(target_user)` exposes it with **no** network/subprocess. `TWClient.get_follower_count` is ordered **gallery-dl (free) → official API (paid) → GraphQL scrape** to mirror `get_all_tweets`, so the poll's `capture_followers` step spends **zero** billed calls when gallery-dl is the active backend — closing the last paid hole from the 2.119.0 switch (before this, the follower snapshot fell through to a billed `/users/by/username` per account because the official API's own cache never warmed). Each `fetch_tweets` attempt invalidates the handle's cached count up front and re-sets only on success, so a failed cycle can't return a stale number; `get_follower_count` also returns `None` under `tw_polling_backend` `"official"`/`"graphql"` so a stale cache can't leak.

---

## 5. Polling System

### Common Poll Cycle Pattern

Every poller follows the same 4-6 step pattern, varying by platform capabilities:

```
Step 1: Authenticate (if needed)
    │  IB: restore cached SID or login
    │  FA: validate cookies
    │  SF: restore saved cookies or login via CSRF (direct or proxy)
    │  AO3/SqW: Rails form login with CSRF
    │  WS: validate API key
    │  DA: mint client-credentials token + check gallery
    │  BSKY: JWT session (login → refresh → check chain)
    │  TW: validate cookies (auth_token + ct0)
    │  WP/IK: no auth needed
    ▼
Step 2: Gallery Discovery
    │  Fetch all submission/work/deviation IDs for the user
    │  Paginated (offset or cursor based)
    ▼
Step 3: Detail Fetch
    │  Batch-fetch metadata and stats for each submission
    │  Per-submission try/except (one failure doesn't abort batch)
    ▼
Step 4: Upsert + Snapshot
    │  INSERT OR REPLACE submission metadata
    │  INSERT snapshot with current stats + timestamp
    ▼
Step 5: Comments / Faves / Watchers (platform-dependent)
    │  Only fetch when count has CHANGED since last snapshot
    │  IB: faving users + comment scraping + watcher scraping
    │  FA: comments via FAExport + watcher list + spam filter
    │  SF: follower scraping
    │  AO3: kudos user list
    │  WS/DA/WP/IK/BSKY/TW: none
    ▼
Step 6: Notifications
    │  Desktop toast (Windows: winotify; Linux: notify-send)
    │  Telegram (summaries, milestones, errors)
    │  First poll suppressed (baseline collection)
    ▼
Finalise: Update poll_log, release concurrency guard
```

### CF Worker proxy gate (2.18.6 / 2.18.7)

Only **SoFurry** now *requires* the CF Worker proxy to function from
datacenter IPs (Cloudflare TLS-fingerprint challenges, login-page rate
limits, etc). The other ten work direct by default, with the proxy as a
**fallback** that fires only when a direct call hits a block-like
failure. (AO3 left `PROXY_REQUIRED` in 2.22.11 and DeviantArt in 2.47.0
— both once their auth stopped depending on the IP-walled login/frontend
path; see the reclassification notes below.)

Two decision points in `polling/cf_proxy.py`:

```python
proxy_kwargs(settings, platform_code)
    # default-path: PROXY_REQUIRED (sf) only.
    # OPTIONAL platforms always get {} from this — they run direct.

proxy_kwargs_fallback(settings, platform_code)
    # retry-path: PROXY_REQUIRED + OPTIONAL with toggle on.
    # Used after a direct call has just failed.

is_blocking_failure(exc) -> bool
    # heuristic: 403, 429, "Shields are up", "Retry later",
    # "Cloudflare", connect/read timeouts, Anubis challenge,
    # "rate-limit", "blocked".
```

**AO3 reclassification (2.22.11):** AO3 was originally in `PROXY_REQUIRED`
because its login form throttles datacenter IPs ("Shields are up!"). Once
cookie-mode auth (2.18.8) bypassed `/users/login`, the proxy stopped being
necessary — but the classification persisted, routing every AO3 request
through the shared CF Worker egress IP pool. **All Worker tenants share
that egress IP, so AO3's per-IP throttle (300 req / 300s from
`config/initializers/rack_attack.rb` at otwarchive v0.9.475.3) saw
aggregate traffic from across all tenants** and stayed saturated even
with near-zero local activity. AO3 moved to `PROXY_OPTIONAL` in 2.22.11;
default is direct from the GCP VM IP (unique to us, our own quota), with
the proxy as a manual opt-in fallback. **Rule of thumb:** CF Worker proxy
is for bypassing IP blocks, not rate limits — sharing egress IP makes
rate-limit problems strictly worse.

**DeviantArt reclassification (2.47.0):** DA was in `PROXY_REQUIRED`
because the undocumented Eclipse `_napi` frontend hard-blocks datacenter
IP ranges. The 2.47.0 migration moved DA polling to the official OAuth2
API (app-only client-credentials token), which answers from datacenter
IPs — verified 200 from the GCP VM. Exactly as with AO3 in 2.22.11, once
the auth path no longer depends on the IP-walled path the proxy is
unnecessary, so DA left `PROXY_REQUIRED_PLATFORMS` (now just `{"sf"}`).
The retained legacy cookie/`_napi` fallback (see §4 DeviantArt) still
needs the proxy on datacenter IPs, but it only runs when app credentials
are absent.

Pattern in importers (AO3, SqW, IB, FA):

```python
direct_client = singleton(settings)         # direct path
try:
    result = await fetch(direct_client)
except Exception as e:
    if not is_blocking_failure(e):
        raise
    creds = proxy_kwargs_fallback(settings, "<platform>")
    if not creds:
        raise                               # toggle off / worker missing
    proxy_client = SomeClient(..., **creds) # one-shot
    try:
        result = await fetch(proxy_client)
    finally:
        await proxy_client.close()
```

UI: a "CF Proxy Backup" accordion in **Settings → Polling** lists the
thirteen opt-in platforms (ib, fa, ws, sqw, ao3, bsky, ik, wp, tw, mast, tum, pix, thr) with one
checkbox each. Backed by the `<platform>_use_cf_proxy` keys and a
derived `cf_worker_configured` boolean returned by
`GET /api/settings/preferences`. Toggles are disabled when worker creds
aren't configured.

**Not wrapped (yet):** poll cycles. They retry naturally on the next
scheduled cycle, so the failure mode is bounded. Adding per-cycle
fallback would mean catching errors at the orchestrator and
constructing a fresh proxy-equipped client for the retry, but that's
deferred — the bounded-failure-mode argument removes the urgency.

### Persistent client singletons (2.18.4 / 2.18.5)

Every platform with a login flow keeps a process-lifetime client
singleton inside its poller module — `polling/{ao3,sqw,bsky,da,ik,sf,tw,wp,mast,tum,pix,thr}_poller.py:_<platform>_client`.
Three callers share each singleton:

```
auth/connect (routes/<platform>_api.py)
    │  validates new credentials
    │  uses _get_or_create_client(overlay) — leaves the live session
    │  in place rather than discarding it
    ▼
import_from_<platform> (posting/importer.py)
    │  reuses the warmed singleton — no fresh login
    │  no client.close() — singleton outlives the request
    ▼
run_<platform>_poll_cycle (polling/<platform>_poller.py)
    │  uses _get_or_create_client(settings) every cycle
    │  ensure_logged_in() short-circuits when session is still alive
```

The accessor signature is identical across platforms:

```python
def _get_or_create_client(settings: dict) -> <Platform>Client:
    global _<platform>_client
    if _<platform>_client is None:
        _<platform>_client = <Platform>Client(...)
    else:
        _<platform>_client.update_credentials(...)
    return _<platform>_client
```

For `auth/connect`, callers overlay the new credentials onto a copy
of `config.get_settings()` before passing — that way `update_credentials()`
sees the to-be-validated values and applies them, but `settings.json`
is only written *after* validation succeeds.

`ensure_logged_in()` on AO3 and SqW clients is conservative: only
flips `_logged_in=False` when the verification GET returns a fetched
page that *positively lacks* the "Log Out" indicator. Transient
failures (timeouts, 429-exhausted retries, Cloudflare blips) leave
the session intact rather than triggering a doomed relogin that
would re-trip per-IP rate limiters.

**Three platforms don't follow this pattern:**

- **Inkbunny** uses DB-cached session IDs (`session_cache` table,
  populated by `client.save_session()` after each successful login).
  The IB importer reads the cached SID and calls `ensure_session()`
  rather than `login()` — same persistence outcome via a different
  mechanism. The IB poller itself does not yet use a singleton.
- **FurAffinity** is cookie-based; cookies live in settings.json and
  there is no login flow to persist. The httpx pool is the only
  thing closing/reopening the client throws away, and that's
  marginal for one-shot validation calls.
- **Weasyl** is API-key authenticated; same reasoning as FA. No
  session concept exists.

### Inkbunny Poll Cycle — Full 6-Step Detail

The IB poller (`polling/poller.py`) is the most feature-complete:

**Step 1: Authenticate**
```python
sid = await client.ensure_session(cached_sid)
# ensure_session tries cached SID first (lightweight search probe)
# Falls back to full login if cache is invalid or missing
# Unlocks all content ratings after login
```

**Step 2: Gallery Search**
```python
gallery = await client.search_user_submissions(username)
# /api_search.php with submissions_per_page=100
# Paginates through all pages (max 1000 pages safety)
# Returns list of submission_id integers
```

**Step 3: Batch Detail Fetch**
```python
details = await client.get_submission_details(submission_ids)
# /api_submissions.php with configurable batch size (SUBMISSION_BATCH_SIZE=100)
# Handles per-submission parse failures gracefully
# Returns list of SubmissionDetail objects with to_db_dict()
```

**Step 4: Upsert + Snapshot** (per-submission in a loop)
```python
for detail in details:
    prev_faves = queries.get_previous_faves_count(conn, sub_id)
    prev_comments = queries.get_previous_comments_count(conn, sub_id)
    queries.upsert_submission(conn, detail.to_db_dict())
    queries.insert_snapshot(conn, sub_id, views, faves, comments, polled_at=timestamp)
```

> **Invariant: never snapshot a failed scrape as zeros.** View/hit counts are
> cumulative and never legitimately decrease. A client whose page fetch fails
> must NOT return a fabricated all-zero stat dict — that zero flows straight into
> `upsert_submission` (clobbering the real count) and `insert_snapshot` (a bogus
> `views=0` row), and the next good poll then reads like a multi-thousand view
> spike in the digest/milestone deltas (the AO3 zero-snapshot bug, [2.27.1]). The
> OTW clients (`ao3`, `sqw`) raise on a `None` fetch or an all-zero/title-less
> parse so the work is dropped from the cycle; the pollers also skip any work that
> scrapes `views=0` while the DB already holds a non-zero count, as belt-and-braces.

**Step 5a: Conditional Fave Fetching**
```python
should_fetch = (force_full and faves > 0) or \
               (prev_faves is not None and faves > prev_faves) or \
               (prev_faves is None and faves > 0)
if should_fetch:
    fave_users = await client.get_faving_users(sub_id)
    for user in fave_users:
        is_new = queries.upsert_faving_user(conn, sub_id, user)
        if is_new:
            stats["new_faves_found"] += 1
            new_fave_details.append(...)
```

**Step 5b: Conditional Comment Scraping**
```python
# Same delta logic as faves
if should_fetch_comments:
    comments = await client.scrape_comments(sub_id)
    for comment in comments:
        is_new = queries.upsert_comment(conn, comment)
        if is_new:
            stats["new_comments_found"] += 1
            new_comment_details.append(...)
```

**Step 5c: Watcher Scraping**
```python
watchers = await client.scrape_watchers()
for username in watchers:
    is_new = queries.upsert_watcher(conn, username)
    if is_new:
        stats["new_watchers_found"] += 1
        new_watcher_names.append(username)
```

**Step 6: Notifications**
```python
if not _first_poll:
    _send_notifications(new_fave_details, new_comment_details, new_watcher_names)
    await _send_telegram(new_fave_details, new_comment_details, new_watcher_names)
    await send_poll_summary("ib", stats, duration)
    await check_milestones_batch("ib", "snapshots", "submissions")
    await check_goals()
```

### FurAffinity Poll Cycle — Watcher Spam Protection Detail

The FA poller has the most complex watcher handling. FA attracts waves of bot/spam watchers.

**Spam filter components**:

1. **Keyword filter** (`_SPAM_KEYWORDS` regex): Immediate rejection for usernames containing gambling/adult keywords (1xbet, casino, viagra, onlyfans, escort, etc.)

2. **Alphanumeric soup filter** (`_ALPHANUM_SOUP` regex): Catches bot-generated usernames like "2charlottec262ye0" — matches 8+ character strings that are mostly digits mixed with letters, with >40% digit ratio.

3. **Bulk threshold** (`_SPAM_WAVE_THRESHOLD = 20`): If more than 20 new watchers appear in one cycle, it's almost certainly a spam wave — summarise instead of listing individual names.

4. **2-cycle confirmation**: New watchers start as `confirmed=0` (pending). On the next poll, if they're still present in FAExport's watcher list, they're promoted to `confirmed=1`. This filters ephemeral bots that appear briefly then vanish without false-positiving on real users.

5. **Profile sniffing**: Confirmed watchers are checked against FAExport's user profile. Zero submissions + zero favorites + zero watches = likely bot. Flagged as `is_spam=1`. Capped at 10 profiles per poll to avoid excessive API calls.

**Watcher notification flow**:
```
New watcher discovered in FAExport → stored as pending (confirmed=0)
    ↓
Next poll cycle: still present? → confirmed=1
    ↓
Keyword filter → is_spam=1 if suspicious username
    ↓
Profile sniff → is_spam=1 if zero activity
    ↓
If confirmed=1 AND is_spam=0 AND notified=0 → send notification
    ↓
Mark notified=1 to prevent re-sending
```

**Watcher notification modes** (setting: `fa_watcher_notification_mode`):
- `"immediate"` (default): Notify per-poll as watchers confirm
- `"daily"`: Accumulate, sent via `send_fa_watcher_digest()` function
- `"off"`: Never notify about watchers

### Progress Tracking

Each poller exposes a module-level dict that the dashboard reads via the progress API:

```python
# Module-level shared dict
fa_poll_progress = {
    "active": False,         # True while poll is running
    "phase": "idle",         # Current step name
    "current": 0,            # Items processed so far
    "total": 0,              # Total items to process
    "message": "",           # Human-readable status string
}
```

**Phases** (in order): `"starting"` → `"searching"` → `"fetching_details"` → `"processing"` (per-submission loop with current/total) → `"fetching_watchers"` → `"sniffing_profiles"` → `"complete"` or `"error"`

The frontend periodically checks `GET /api/{platform}/poll/progress` and renders a loading bar with the message text. Note the terminology distinction: "polling" refers to the backend syncing data from external platforms, while "progress checks" refers to the frontend's periodic HTTP requests to check whether a backend poll is in progress and display its status in the loading bar.

### Concurrency Guard

Each poller uses a `threading.Lock` + boolean flag pattern:

```python
_fa_poll_running = False
_fa_poll_lock = threading.Lock()

async def run_fa_poll_cycle():
    global _fa_poll_running
    # Atomic check-and-set via Lock
    if not _fa_poll_lock.acquire(blocking=False):
        logger.warning("FA poll already running — skipping")
        return {}
    _fa_poll_running = True
    try:
        # ... poll cycle ...
    finally:
        _fa_poll_running = False
        _fa_poll_lock.release()
```

`blocking=False` means the lock attempt returns immediately. If another thread holds the lock, the new poll is rejected rather than queuing. This prevents overlapping polls from both the timer thread and a manual trigger.

### Conditional Fetching Logic

Comments and faving users are expensive to fetch (one API call per submission). The delta-based optimisation only fetches when the count has changed:

```python
should_fetch = False

# Case 1: Force-full resync requested AND there are items to fetch
if force_full and count > 0:
    should_fetch = True

# Case 2: Count increased since last snapshot
elif prev_count is not None and count > prev_count:
    should_fetch = True

# Case 3: First time seeing this submission and it has items
elif prev_count is None and count > 0:
    should_fetch = True
```

This dramatically reduces API calls. A gallery with 100 submissions where only 3 have new comments results in 3 comment fetches instead of 100.

### Session Expiry Recovery

Three pollers now recover from expired sessions instead of crashing the poll cycle:
- **SQW**: resets `_logged_in` flag before `validate_session()` so `ensure_logged_in()` attempts a fresh login.
- **FA**: validates cookies before gallery fetch with a clear error message on failure.
- **TW**: empty credential check + clearer expired-cookie error message.

#### Meta (Threads + Instagram): app-block ≠ expired token (2.83.0)

`polling/session_check` classifies a platform as `expired` (red, "re-enter credentials") whenever its
`validate_session()` returns falsy, and `error` (amber, "couldn't verify") when it *raises*. For the two
Meta-Graph platforms that distinction matters, because Meta returns several very different failures as an
`OAuthException` with a numeric `code`:

- **code 190** — the access token is genuinely expired/invalid. Here re-entering the token is the right
  advice, so `validate_session()` returns `None` (its historical "not alive" contract) → red "expired".
- **code 200 "API access blocked"** (an *app-level* block on the user's Meta app), other permission errors,
  rate limits, network errors — the token itself may be perfectly fine. Reporting these as "expired" sends
  the user chasing the wrong fix. So `clients/{thr,ig}/client.py::validate_session()` **raises**
  `ThrAuthError` / `IgAuthError` with the real Meta message, and `check_platform`'s existing `except` branch
  turns that into amber "couldn't verify" carrying the actual reason.

To see the `code` at all, `validate_session()` issues the `/me` probe with a raw `self._http.get(...)` rather
than `_get_json()` (which collapses every non-200 to `None`, discarding the error body). Both platforms share
one Meta app, so an app-block trips *both* at once — a useful tell in the logs (`THR/IG: non-expiry auth
failure (code 200)`). The fix only changes *classification/reporting*; a real expiry (code 190) behaves
exactly as before, and the posting path (`create_thread`/`create_post`) never calls `validate_session()`.

#### e621 (2.104.0 poll · 2.118.0 post) — official REST API, Score is the headline

e621 is the 17th platform and the first with an *official, documented* JSON API, so the client
(`clients/e621/client.py`) is unusually small. Poll-only until 2.118.0, when its OpenAPI
(https://e621.wiki/openapi.yaml) confirmed the upload endpoint takes the same creds — see **Posting** and
**Response-shape future-proofing** below. Notes that matter:

- **Auth is HTTP Basic** — `username` + **API key** (Account → Manage API Access, NOT the password).
  `E621Client._auth()` returns the `(username, api_key)` tuple httpx sends as a Basic header. Cred
  validation hits `/favorites.json` (an authenticated-only endpoint) rather than a public post endpoint,
  because e621 ignores bad Basic auth on public reads (they 200 regardless) — only an authed endpoint
  actually rejects a wrong key. `e621_api_key` is a vault secret; `e621_username` is plaintext identity.
- **User-Agent policy is enforced in code.** e621 *requires* a descriptive UA and **blocks anything that
  impersonates a browser**. `_headers()` sends `PawPoller/<ver> (e621 self-analytics; user <name>)` and the
  test suite asserts the UA contains no browser tokens (Mozilla/Chrome/…). Paging sleeps
  `config.E621_REQUEST_DELAY_SECONDS` (1.0s) between requests — e621's hard limit is 2 req/s, the docs ask
  for ~1.
- **Score, not views.** e621 exposes no view count, so the headline metric is `score` (score.total =
  up − down, **which can be negative**). The schema/queries mirror the gallery template but rename the first
  metric column `views → score`; every per-platform metric map registers e621 as
  `("score", "favorites_count", "comments_count")`. The growth-rate dict still keys the value under
  `views_per_day` (holding the score delta) so the generic `Components.growthRateCards` renders it unchanged,
  labelled "score/day".
- **No thumbnail proxy, no followers.** e621's CDN (`static1.e621.net`) is hotlinkable, so — unlike Pixiv —
  the frontend uses the thumbnail URL directly and there's no `/api/e621/thumb` relay. e621 has no per-user
  follower count, so the poller omits the `capture_followers` step and e621 is absent from
  `FOLLOWER_PLATFORMS`.
- **What it tracks.** The poller pages `/posts.json?tags=user:<username>` newest-first using the
  `page=b<id>` before-id cursor (page numbers cap at 750), and each listing already carries full engagement
  data — so there's no per-post fetch, `get_post_details_batch()` just parses the stashed raw posts.
- **Response-shape future-proofing (2.118.0).** `/posts.json` has two live formats: the LEGACY default
  (`{"posts":[…]}` with flat `file`/`score`/`fav_count`), which e621's own OpenAPI marks *deprecated*, and the
  supported **v2 extended** (`v2=true&mode=extended` → a bare array of nested `files`/`stats`). The poller now
  requests v2 extended, and `get_all_post_uris` handles both envelopes while `_parse_post`'s `_file_url` /
  `_thumb_url` / `_stats` helpers read **either** shape — so polling can't break when e621 flips or drops the
  legacy default. Both shapes are covered by `tests/test_e621_posting.py`.
- **up/down vote split trends (2.118.0).** `_stats` returns `(total, up, down, fav, comment)`; the poller writes
  `up_score`/`down_score` into each `e621_snapshots` row (new columns via a guarded db.py migration), so the
  vote split behind the net score is now trended, not just the current value on the submission row.

**Posting (2.118.0).** `E621Client.upload_post(tag_string, rating, file_path|direct_url, source, description)`
does a multipart `POST /uploads.json` with the same HTTP Basic creds, returning `{success, post_id, location}`;
a rejection raises `RuntimeError` carrying e621's own reason (duplicate → appends the existing post's URL,
missing tags, or a 403 permission note). `posting/platforms/e621.py::E621Poster` wraps it as an art-only poster
registered in `manager._get_poster`, so artwork publishes through the normal `post_artwork` path. Rating maps
general→`s`, mature→`q`, adult/explicit/**unknown**→`e` (under-rating adult content on e621 is a policy
violation, so unknown defaults to explicit). `validate()` requires an image and ≥4 tags — e621 flags
under-tagged posts. `requires_mode="any"` (the REST API isn't datacenter-IP-blocked like FA's HTML flow).
**Operational caveats:** e621 uploads enter a **janitor approval queue**, want an accurate tag set + a source
(pass one via the artwork's per-platform `source` override → `package.extra["source"]`), and **reject duplicates
by file hash**. It's the bring-your-own-creds self-host model — you upload your own art as your own account.

#### Muting a session-health alert (2.84.0)

The session problems `summarize_problems()` surfaces are merged into the notification feed
(`routes/api.py::get_notifications`, `kind:"session"`) and, for a fresh one, pop a toast. A user handling a
problem externally (a Meta app-block they're fixing in the Meta dashboard) can **mute** a specific platform's
alert so it stops nagging — without turning off notifications wholesale and without hiding a *later, different*
failure:

- **Store:** `settings.json` `muted_session_codes` (list). Mutated only via `POST /api/platforms/sessions/mute
  {code, muted}` — additive/idempotent, restricted to `session_check.CHECKABLE` codes (unknown → 400).
- **Quiet, not gone:** `get_notifications` tags each session item `muted` from that set; muted items stay in
  the feed (frontend dims them + shows an **Unmute** button) but are excluded from the unread count, and
  `notifications_center.js::maybeToast` skips their toast. The platform's health dot is untouched (still
  honest amber/red).
- **Auto-clears on recovery:** `session_check.check_platform` removes a code from `muted_session_codes` the
  moment its status returns to `valid` (re-reading settings fresh so two platforms recovering in the same
  `check_all` pass don't clobber each other's clear). So a mute means "until it's fixed", never "forever" — a
  brand-new failure after recovery re-alerts normally.

#### Quick Reconnect (2.86.0)

The counterpart to Mute: instead of silencing the alert, **fix it in place**. `frontend/js/reconnect.js`
(`window.Reconnect`, styled by `reconnect.css`) is a small modal that lets the user paste fresh credentials
straight from the alert rather than navigating to Settings → Platforms.

- **Field spec, not a per-platform form.** `SPEC[code]` maps each of the 9 session-checkable platforms to its
  reconnect fields (mirroring that platform's `/auth/connect` body): a single paste for the token/key ones
  (thr/ig `access_token`, pix `refresh_token`, mast `instance_url`+`access_token`, bsky `identifier`+
  `app_password`, tum `blog`+`api_key`) and the full set for the login ones (ao3/sf/sqw). `canReconnect(code)`
  gates the entry points. `open(code)` renders the inputs; `submit()` collects non-empty values, enforces
  required fields, and POSTs to the **same** `POST /api/{code}/auth/connect` — which validates the credential
  live (`validate_session()`/`validate_*()`) before saving, so a `200` means the session is genuinely fixed.
- **"...and sync."** On success it fires `POST /api/{code}/poll/trigger` (fresh poll) + `triggerSessionCheck()`
  (re-validate → clears the dot/banner within seconds), toasts, closes, and re-polls the notification feed.
  On failure it parses the endpoint's error (`API {status}: {json.detail}` → the raw detail) and shows it inline
  (e.g. Meta's "the access token is invalid or lacks the … scopes"), re-enabling the button so the user can retry.
- **Entry points, driven off the live session status** (`_data[code].session.status`): a **Reconnect** button
  beside Mute on every `kind:"session"` notification (`notifications_center.js`, gated on `Reconnect.
  canReconnect`), and a **Reconnect →** action on the app-wide expired banner (`platform_health.js::
  renderGlobalBanner`) when there's exactly one expired platform and it's reconnectable — otherwise the banner
  keeps its Settings link (also the multi-platform case). CSP-safe (external script/style, no inline handlers;
  reuses the `.guide-modal` shell). Registered in `index.html` after `platform_guides.js` / `guides.css`.

### N+1 Query Batching

Four pollers switched from per-item INSERT loops to `executemany` + `INSERT OR IGNORE` for fan/interaction data:
- IB faving users, FA comments, SQW kudos, AO3 kudos.
- Pre-existing set approach preserved so notification detail tracking is unaffected.

### AO3 Rate-Limit Retry

- `_parse_retry_after()` extracts the `Retry-After` header from HTTP 429 responses.
- `_get_page()` handles 429 within the retry loop with escalating backoff (was previously broken -- retried inline without checking response status).
- `_post_with_retry()` wraps all 7 non-login POST operations with automatic retry on transient failures.

---

## 6. Database Layer

### Connection Configuration

SQLite with per-connection PRAGMAs set in `database/db.py:get_connection()`:

```python
conn = sqlite3.connect(str(config.DB_PATH), timeout=30)
conn.row_factory = sqlite3.Row    # Dict-like access: row["column_name"]
conn.execute("PRAGMA journal_mode=WAL")   # Concurrent readers + single writer
conn.execute("PRAGMA busy_timeout=30000") # 30s SQLite-level busy wait
conn.execute("PRAGMA foreign_keys=ON")    # Enforce FK constraints
```

**Why WAL mode**: Without WAL, SQLite uses rollback journaling which locks the entire database during writes. The GUI thread would freeze while a poller writes snapshots. WAL (Write-Ahead Logging) allows concurrent readers and a single writer without blocking each other. This is critical for PawPoller because the dashboard reads data for display while pollers write new snapshots simultaneously.

**Why explicit FK enforcement**: SQLite does not enforce FOREIGN KEY constraints by default (for backward compatibility). Without `PRAGMA foreign_keys=ON`, you could insert a snapshot referencing a non-existent `submission_id`. This must be enabled per-connection.

**Timeout of 30 seconds**: Both the Python-level `connect(timeout=30)` and the SQLite-level `PRAGMA busy_timeout=30000` are set. If a writer is holding the WAL lock, readers wait up to 30 seconds before raising `sqlite3.OperationalError`. Generous on purpose — bulk regen and full-resync runs can hold the writer for several seconds at a time.

**Never hold an open write transaction across an `await` (2.26.3)**: Python's sqlite3 begins an implicit write transaction on the first INSERT/UPDATE and holds it until `commit()`. Four pollers (IB, FA, SqW, AO3) used to upsert a snapshot and then await rate-limited network fetches (faving users / comments / kudos) before committing — holding the single WAL write lock for 60s+ (minutes on AO3's 12s pacing), which starved every other concurrently-polling platform past the 30s busy_timeout and produced intermittent `database is locked` poll failures. Fixed in 2.26.3 by committing immediately after the snapshot upsert, before any conditional fetch awaits. When writing new poller code, commit before every `await` that follows a write.

### Inkbunny Schema (`database/schema.sql`) — Primary Platform

**Table: `submissions`** (primary key: `submission_id`)
```sql
submission_id    INTEGER PRIMARY KEY    -- IB's submission ID
title            TEXT NOT NULL DEFAULT ''
username         TEXT NOT NULL DEFAULT ''
user_id          INTEGER NOT NULL DEFAULT 0
create_datetime  TEXT                   -- When posted on IB
type_name        TEXT DEFAULT ''        -- Picture/Pinup, Writing, etc.
rating_id        INTEGER DEFAULT 0      -- 0=General, 1=Mature, 2=Adult
rating_name      TEXT DEFAULT ''
thumb_url        TEXT DEFAULT ''        -- Thumbnail CDN URL
url              TEXT DEFAULT ''        -- Direct file download URL
description      TEXT DEFAULT ''        -- HTML body text
keywords         TEXT DEFAULT '[]'      -- JSON array of tag strings
page_count       INTEGER DEFAULT 1      -- Multi-page submissions
views            INTEGER DEFAULT 0      -- Denormalized latest stats
favorites_count  INTEGER DEFAULT 0      -- (also in snapshots)
comments_count   INTEGER DEFAULT 0      -- (also in snapshots)
updated_at       TEXT                   -- Trigger-updated on snapshot insert
```

**Table: `snapshots`** (point-in-time stats)
```sql
id               INTEGER PRIMARY KEY AUTOINCREMENT
submission_id    INTEGER NOT NULL       -- FK → submissions
polled_at        TEXT NOT NULL          -- Timestamp of this snapshot
views            INTEGER DEFAULT 0
favorites_count  INTEGER DEFAULT 0
comments_count   INTEGER DEFAULT 0
-- Indices: (submission_id, polled_at), (polled_at)
```
The dashboard uses snapshots to render time-series charts showing growth over time. Each poll cycle creates one snapshot per submission.

**Table: `faving_users`** (who favorited what — IB only)
```sql
id               INTEGER PRIMARY KEY AUTOINCREMENT
submission_id    INTEGER NOT NULL       -- FK → submissions
user_id          INTEGER NOT NULL
username         TEXT NOT NULL DEFAULT ''
first_seen_at    TEXT NOT NULL DEFAULT (datetime('now'))
-- UNIQUE(submission_id, user_id) prevents duplicate entries
```

**Table: `comments`** (individual comment records)
```sql
comment_id       INTEGER PRIMARY KEY    -- From IB's HTML
submission_id    INTEGER NOT NULL       -- FK → submissions
username         TEXT NOT NULL DEFAULT ''
comment_text     TEXT NOT NULL DEFAULT ''
commented_at     TEXT                   -- When the comment was posted on IB
first_seen_at    TEXT NOT NULL DEFAULT (datetime('now'))  -- When poller found it
is_reply         INTEGER DEFAULT 0     -- 0=top-level, 1=reply
reply_to_comment_id INTEGER            -- Parent comment ID
```

**Table: `poll_log`** (audit trail)
```sql
id               INTEGER PRIMARY KEY AUTOINCREMENT
started_at       TEXT DEFAULT (datetime('now'))
finished_at      TEXT
status           TEXT DEFAULT 'running' -- running, success, error
submissions_found    INTEGER DEFAULT 0
snapshots_inserted   INTEGER DEFAULT 0
new_faves_found      INTEGER DEFAULT 0
new_comments_found   INTEGER DEFAULT 0
new_watchers_found   INTEGER DEFAULT 0
error_message    TEXT
duration_seconds REAL
```

**Table: `watchers`** (people watching the user)
```sql
id               INTEGER PRIMARY KEY AUTOINCREMENT
user_id          INTEGER NOT NULL DEFAULT 0
username         TEXT NOT NULL          -- UNIQUE constraint
first_seen_at    TEXT NOT NULL DEFAULT (datetime('now'))
```

**Table: `session_cache`** (SID caching — singleton row)
```sql
id               INTEGER PRIMARY KEY CHECK (id = 1)  -- Only one row allowed
sid              TEXT
username         TEXT
created_at       TEXT DEFAULT (datetime('now'))
```

### FurAffinity Schema — Key Differences

The FA schema mirrors IB's structure but with important differences:

- **No `fa_faving_users` table** — FA doesn't expose per-submission fave lists through FAExport or any public endpoint
- **`fa_comments.comment_id`** is `TEXT` (not INTEGER) because FA comment IDs come from HTML anchors and may not be purely numeric
- **`fa_comments.reply_to`** is `TEXT` (parent comment ID) + **`reply_level`** is `INTEGER` (nesting depth) — instead of IB's boolean `is_reply` + `reply_to_comment_id`
- **`fa_comments.is_deleted`** flag — FA allows comment deletion; the poller preserves deleted comment records
- **FA-specific metadata**: `category`, `theme`, `species`, `gender` (FA has rich content categorisation)
- **`fa_watchers`** has spam protection columns:
  ```sql
  confirmed    INTEGER DEFAULT 0    -- 0=pending, 1=survived 2+ polls
  last_seen_at TEXT                  -- Last detected in FAExport
  is_spam      INTEGER DEFAULT 0    -- Bot/spam heuristic flag
  notified     INTEGER DEFAULT 1    -- Already sent notification
  ```

### Cross-Platform Tables (via migrations)

**`submission_groups` + `submission_group_members`**: User-defined groups (e.g. "Commission batch #3"). A group has a name and description; members are `(group_id, platform, submission_id)` triples with CASCADE delete.

**`submission_links` + `submission_link_members`**: Cross-platform submission links. Links the "same" artwork posted to multiple platforms. A `link_id` groups multiple `(platform, submission_id)` pairs. Enables cross-platform analytics like comparing view/fave performance of the same piece across sites.

**`goals`**: User-defined targets (e.g. "reach 1000 views on IB"). Fields: platform, scope (account/submission), metric, target_value, created_at, completed_at. Telegram sends a notification when `current_value >= target_value`.

**`tags` + `submission_tags`**: User-defined tag categorisation. Tags have a name and colour hex code. Tag assignments link `(tag_id, platform, submission_id)`.

### Query Module Pattern

Each platform's query module (`queries.py`, `fa_queries.py`, etc.) provides:

| Function | Purpose |
|----------|---------|
| `upsert_*_submission(conn, detail_dict)` | INSERT OR REPLACE submission metadata |
| `insert_*_snapshot(conn, sub_id, views, faves, comments, polled_at)` | Record point-in-time stats |
| `get_*_submissions(conn, sort, order, limit, offset)` | Paginated list with latest stats |
| `get_*_submission(conn, sub_id)` | Single submission detail |
| `get_*_snapshots(conn, sub_id, since)` | Time-series data for charts |
| `get_*_aggregate(conn, since)` | Cross-submission totals |
| `get_*_comparison(conn, ids, since)` | Multi-submission stats for overlay charts |
| `get_previous_*_count(conn, sub_id)` | Last known count (for delta detection) |
| `upsert_*_comment(conn, comment_dict)` | Insert or ignore comment (returns is_new bool) |
| `start_*_poll_log(conn)` | Create poll_log entry with status='running' |
| `finish_*_poll_log(conn, log_id, status, **stats)` | Update poll_log with results |

Cross-platform modules:
- **`group_queries.py`**: CRUD for submission groups and members. `get_group_comparison()` joins group members with their platform-specific snapshot tables.
- **`analytics_queries.py`**: `get_top_fans()` aggregates faving users and commenters across all platforms into a unified leaderboard. Uses `user_stats` dict with `{name: {fave_count, comment_count, platforms}}`.

### Migration System

`database/db.py:_run_migrations()` runs on every startup and is idempotent:

```python
def _run_migrations(conn):
    # Get current table names
    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()}

    # Migration 1: comments table (added when comment scraping was implemented)
    if "comments" not in tables:
        conn.executescript("CREATE TABLE IF NOT EXISTS comments (...)")

    # Migration 2: submission_groups (cross-platform grouping)
    if "submission_groups" not in tables:
        conn.executescript("CREATE TABLE IF NOT EXISTS submission_groups (...)")

    # Column additions use try/except because SQLite has no
    # ALTER TABLE ADD COLUMN IF NOT EXISTS syntax.
    # The OperationalError "duplicate column" is expected and ignored;
    # any other error is re-raised to surface genuine issues.
    try:
        conn.execute("ALTER TABLE poll_log ADD COLUMN new_watchers_found INTEGER DEFAULT 0")
    except sqlite3.OperationalError as e:
        if "duplicate column" not in str(e).lower():
            raise

    # Table schema rebuild (e.g., watchers UNIQUE constraint change)
    # Uses CREATE new → INSERT from old → DROP old → RENAME new pattern
```

### Denormalisation Strategy

The `submissions` table stores **denormalised latest stats** (views, favorites_count, comments_count) in addition to the `snapshots` table which is the authoritative time-series. This avoids expensive JOINs on every dashboard page load — the submission list page can read directly from the submissions table without aggregating snapshots.

---

## 7. Dashboard (FastAPI)

### Application Setup (`dashboard.py`)

```python
app = FastAPI(title="PawPoller", version="1.0.0", lifespan=lifespan)
```

**Lifespan context manager** (replaces deprecated `on_event`):
```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()           # Startup: create tables if needed
    logger.info("Dashboard started at http://%s:%d", host, port)
    yield               # App runs here
    logger.info("Dashboard shutting down")
```

**Global exception handler**: Catches any unhandled exception from route handlers and returns clean JSON 500 with `exc_info=True` logging, instead of letting uvicorn emit bare tracebacks.

**Router registration order** (critical):
```python
# API routes BEFORE static mounts — FastAPI matches in registration order.
# If static mounts were first, /api/stats would 404 against the static handler.
app.include_router(router)       # /api/* (IB + core)
app.include_router(fa_router)    # /api/fa/*
app.include_router(ws_router)    # /api/ws/*
# ... 6 more platform routers
```

**Static file serving** uses `config.resource_path()` which resolves correctly in both dev mode (project directory) and PyInstaller frozen builds (`sys._MEIPASS` temp directory).

### SPA Architecture

The frontend is a Single Page Application with hash-based routing:

> **2.29.0 bold redesign — shell, navigation & Home.** The shell, navigation and Overview were
> redesigned in 2.29.0 (CHANGELOG [2.29.0]); the per-platform render functions, editor, posting
> and the rest of the backend are unchanged. Key changes:
> - **Type/theme** (`css/tokens.css`): adds `--font-display` (Bricolage Grotesque) and switches
>   `--font-sans` to Hanken Grotesk. The 8 `[data-theme]` blocks are unchanged.
> - **Canonical platform list** (`frontend/js/platforms.js`, loaded first): exports
>   `window.PLATFORMS` + `platformByCode()` + `platformRoute()` — the single place the platform list
>   and route scheme live. As of 2.68.0 routing is **uniform for all platforms** (Inkbunny included):
>   `#/{code}`, `#/{code}/submissions`, `#/{code}/compare`, `#/{code}/submission/{id}`. The bare
>   `#/submissions` is the cross-platform Submissions hub (`window.Submissions` / `/api/works`), NOT
>   Inkbunny — IB's legacy un-prefixed routes moved under `#/ib/…`. `command_palette.js` consumes it.
> - **Shell** (`index.html`, `css/layout.css`): a persistent **labeled sidebar** (collapse via
>   `#sidebar-collapse` → `.collapsed` + `body.sidebar-collapsed`, persisted to
>   `localStorage['pawpoller-sidebar-collapsed']`) replaces the hover-to-expand rail. `#main-col`
>   wraps `#context-bar` + `#app` and carries the sidebar-clearing left margin. Mobile keeps the
>   drawer (`.sidebar.open` + `#sidebar-overlay` + `#hamburger-btn`) and a floating `.bottom-nav`
>   (Overview · Platforms · Stories · Analytics · More; `#bottom-nav-more` opens the drawer).
> - **Context bar**: `App._renderContextBar(parts, isFullScreen)` fills `#context-bar` from the
>   parsed route — a breadcrumb always, plus a platform switcher (`#ctx-platform-switch`) and
>   Dashboard/Submissions/Compare sub-tabs when inside a platform. Empty (hidden) on full-screen
>   routes and on mobile for non-platform pages.
> - **Platforms hub**: `App.renderPlatformsHub()` at `#/platforms` (a real page, not the old
>   popover) renders `.hub-tile` colour tiles; each holds a `#pg-status-{code}` dot that
>   `platform_health.js` fills (`PlatformHealth.fetchOnce()` is fired on render).
> - **Configurable Home**: `App.renderOverview()` fetches + caches data in `this._dashCtx`, then
>   `App._renderDashboard()` builds a widget grid from `this._dashboardLayout` (a list of
>   `{id, span}`). Customize mode (`this._dashEdit`) adds drag-reorder / resize / remove / an
>   add-widget catalog. Layout is **server-saved** via the `dashboard_layout` preference
>   (`GET`/`POST /api/settings/preferences`). Catalog + default in `_dashWidgetMeta()` /
>   `_dashDefaultLayout()`; per-widget HTML in `_dashWidgetHtml()`.
> - **Platform-header accent**: `route()` sets `data-platform` + `--page-accent` on `#main-col`;
>   `redesign.css` tints the `.page-header` with the brand colour (no per-platform edits).
> - New stylesheet `frontend/css/redesign.css` holds the bold page components (hub tiles, dashboard
>   widgets, add-widget catalog, header accent), loaded after `layout.css`.
>
> The collapsible-nav-group / Platforms-popover prose further down predates this and is retained
> only as history.

**`frontend/js/app.js`** — Client-side router:
- Hash-change listener dispatches to page renderer functions
- Session-persisted state: `currentPage`, `_sortState` (field + order), `_dateRange` ('all', '7d', '30d', '90d', 'year'), `_compareIds` (Set, max 5), `_autoRefreshTimer` (60s interval)
- Initialisation: auth check → redirect to `#/login` if no credentials or `#/loading` if data not yet fetched → fire initial route → start 60s poll-status interval → wire mobile hamburger menu

**`frontend/js/api.js`** — API client wrapper:
- Core transport: `get(path, params)` builds URL, strips null/empty params, returns parsed JSON
- `post(path, body)` sends JSON payload
- ~50 convenience methods mapping to REST endpoints
- Error handling: network errors throw `"Network error: {message}"`, HTTP errors throw `"API {status}: {response_text}"`

Key API methods:
```javascript
getSubmissions(params)        // GET /api/submissions?sort=views&order=desc&...
getSubmission(id)             // GET /api/submissions/{id}
getSnapshots(id, params)      // GET /api/snapshots/{id}?since=7d
getAggregate(params)          // GET /api/aggregate?since=30d
getComparison(ids, params)    // GET /api/comparison?ids=1,2,3&since=7d
getPollProgress()             // GET /api/poll/progress
triggerPoll()                 // POST /api/poll/trigger
fullResync()                  // POST /api/poll/full-resync
getCredentials()              // GET /api/credentials
saveCredentials(data)         // POST /api/credentials
connectTelegram(data)         // POST /api/telegram/connect
testTelegram()                // POST /api/telegram/test
```

**`frontend/js/components.js`** — ~25 reusable UI components:
- Submission tables with sortable columns and mobile card transformation (via `data-mobile-cards` attribute)
- Stat cards (views, faves, comments with delta indicators)
- Progress bars (poll progress)
- Chart containers (time-series, comparison)
- Modal dialogs (settings, group management)
- Tag badges and filters

**`frontend/js/charts.js`** — Chart.js factories for:
- Time-series line charts (views/faves/comments over time per submission)
- Multi-submission comparison overlay charts (up to 5 submissions)
- Aggregate trend charts (platform-wide totals over time)

### Mobile / Responsive Design (v1.5.0)

The dashboard is fully responsive with a mobile-first overhaul targeting phone and tablet viewports.

**Viewport configuration** (`index.html`):
```html
<meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover">
```
`viewport-fit=cover` extends content into notched device areas (iPhone etc.). CSS `env(safe-area-inset-*)` values then provide padding where needed.

**Grouped navigation** — the nav groups (Publishing / Create / Insights & Tools) are wrapped in `<li class="nav-group">` elements containing a `<button class="nav-group-label" data-nav-toggle>` header and a `<ul class="nav-sub">` sub-list:
```html
<li class="nav-group">
    <button class="nav-group-label" data-nav-toggle type="button" aria-expanded="false">Publishing<span class="nav-caret" aria-hidden="true">&#9662;</span></button>
    <ul class="nav-sub">
        <li><a href="#/posts" class="nav-link" data-page="posts">💬 Posts</a></li>
        <li><a href="#/collections" class="nav-link" data-page="collections">🗃 Collections</a></li>
    </ul>
</li>
```
(Shape only — the group's real membership moves. It once held Submissions / Stories / Artwork; all
three hubs are now the top-level **Library**. See §20.11.)
The `[data-nav-toggle]` handler (bound once in `App.init()`) toggles `.expanded` on the parent `.nav-group`; `aria-expanded` tracks it. Adding/removing state is the only JS — showing/hiding is pure CSS, so the strict CSP is untouched.

**Nav mode — top bar vs side rail (2.72.0).** The shell defaults to a **horizontal top bar** (`data-navmode="top"` on `<html>`, resolved synchronously by the no-flash boot `<script>` from `localStorage['pawpoller-nav']`, default `'top'`). Settings → Appearance → Navigation (`#nav-mode-picker`) flips to the classic **left side rail** (`'side'`); `App.applyNavMode()` persists the choice and repaints without a reload. Both modes are **desktop-only** — the whole top-bar block is gated on `@media (min-width: 769px)` and `html[data-navmode="top"]:not([data-mobile="1"])`, so phones always get the bottom nav + drawer regardless.
- **Side rail** (`layout.css` base): the `.nav-sub` lists render flat (always visible, labelled) exactly like the pre-2.72.0 sidebar — no dropdowns.
- **Top bar** (`layout.css` `@media` block): the sidebar becomes a 58px horizontal row (brand · nav · search · footer), `#main-col` shifts to `margin-top:58px`, and each `.nav-sub` becomes an **absolutely-positioned dropdown** revealed on `:hover`, `:focus-within`, or `.nav-group.expanded`. An invisible `.nav-group::after` hover-bridge spans the trigger→panel gap so the panel doesn't drop while the cursor crosses it. (Note: the attribute is `data-navmode`, deliberately *not* `data-nav` — the latter would collide with the app's document-level `[data-nav]` click-delegation and hijack every click.)

The `route()` function marks the active `.nav-link` so the user always sees their current location.

**Bottom navigation bar** — A fixed `<nav class="bottom-nav">` at the bottom of the viewport (hidden on desktop via `display: none`, `display: flex` at <=768px):
```html
<nav class="bottom-nav" id="bottom-nav">
    <a href="#/overview" class="bottom-nav-item" data-page="overview">Overview</a>
    <button class="bottom-nav-item" id="bottom-nav-menu">Platforms</button>
    <a href="#/analytics" class="bottom-nav-item" data-page="analytics">Analytics</a>
    <a href="#/settings" class="bottom-nav-item" data-page="settings">Settings</a>
</nav>
```
The "Platforms" button opens the sidebar overlay. Active state is managed in `route()` by matching `data-page` against the current hash. Height is `var(--bottom-nav-h)` (56px) plus `env(safe-area-inset-bottom)` padding. The main content area has matching bottom padding to prevent content from hiding behind the bar.

**Table-to-card transformation** — All 10 submission/fan tables include the `data-mobile-cards` attribute and `data-label` on every `<td>`:
```html
<table class="data-table" data-mobile-cards>
    <thead>...</thead>
    <tbody>
        <tr>
            <td data-label="Title">My Submission</td>
            <td data-label="Views">1,234</td>
            <td data-label="Faves">56</td>
        </tr>
    </tbody>
</table>
```
At <=768px, CSS transforms these into stacked cards:
- `thead` is hidden (`display: none`)
- Each `<tr>` becomes a card (`flex-direction: column`, border, border-radius, padding)
- Each `<td>` displays as a flex row with `::before { content: attr(data-label) }` as the label
- Thumbnail cells use `td.mobile-hide` class to hide on mobile
- Tables without `data-mobile-cards` get horizontal scroll (`overflow-x: auto`) instead

Platform-specific labels are used (e.g. "Hits"/"Kudos" for SqW/AO3, "Reads"/"Votes" for WP, "Likes"/"Reshares" for IK).

**Touch optimisation**:
- `touch-action: manipulation` on interactive elements (prevents 300ms tap delay)
- `-webkit-tap-highlight-color: transparent` on body
- All buttons and nav items have 44px minimum touch targets
- `overscroll-behavior: none` on body (prevents pull-to-refresh in embedded webview)
- `-webkit-text-size-adjust: 100%` on html (prevents text zoom on orientation change)

**Responsive breakpoints** (CSS `@media`):
- **768px** (tablet/phone): sidebar as overlay (280px width), bottom nav visible, accordion nav, table-to-card, stat cards single-column layout, chart heights reduced to 220px, settings form inputs stack vertically, date range buttons flex-fill
- **480px** (small phone): stat cards 10px gap, pinned card flex-basis reduced to 140px, chart heights 200px, growth rate values smaller font (14px), top list titles truncate at 60vw

### Settings Page

The Settings page (`#/settings`) uses a tabbed layout with 7 tabs: **General**, **Platforms**, **Polling**, **Telegram**, **Data**, **Logs**, **About**.

**Tab switching** — Clicking a tab activates its panel via `data-settings-tab` / `data-settings-panel` attributes. Only one panel is visible at a time.

**Lazy loading** — The Polling and Logs tabs use deferred data fetching to reduce API calls on initial settings load:
- On first load, only General/Platforms/Telegram/Data/About tabs fetch their data (~15 API calls)
- The **Polling tab** fetches its data only when the user clicks on it. This loads IB poll status + poll log, plus each connected platform's poll status and poll log in parallel (~22 API calls), and the pause state (`/api/poll/paused`). A `_pollingTabLoaded` flag prevents re-fetching on subsequent tab switches. Cards render in a responsive **`.polling-grid`** (2.103.0, was a vertical stack) and each carries a **⏸ Pause / ▶ Resume** button (`_togglePlatformPause`) plus a "· paused" summary tag when paused.
- The **Logs tab** fetches server.log, polling.log, and app.log on demand when opened.
- **Settings search** (2.103.0): a search box above the tab strip (`#settings-search`, wired by `_wireSettingsSearch`) filters across *every* tab at once. Because all tab panels are in the DOM (inactive ones just `display:none`), a non-empty query shows all panels and hides the `.settings-section` / top-level `.settings-accordion` units whose text doesn't match; an empty query (or Esc) restores the normal single-tab view. Lazy tabs (Polling, Logs) are eager-loaded on the first search so their content is searchable.

**Collapsible accordion sections** — Within each tab, related settings are grouped in native `<details>/<summary>` HTML elements, providing expand/collapse functionality without JavaScript. Each platform's configuration section is an independent accordion.

**Platform connection status** — Each platform section in the Platforms tab shows connection status, credential fields, and a test/connect button. Connected platforms display a green indicator.

**FA profile pageviews** — The FurAffinity section includes a stat card showing the user's profile page view count, fetched from the FA API.

### REST API Endpoints — Complete Reference

The dashboard mounts ~11 routers under `/api/`. Use `grep -rEn
"^@\w+_router\.(get|post|put|delete)" routes/` for an authoritative
current inventory — versions ship rapidly and this table can drift.
The high-level groups:

| Router | Module | Prefix | Auth-exempt paths |
|---|---|---|---|
| Core API | `routes/api.py` | `/api/*` | `/api/health` |
| Dashboard auth | `routes/dashboard_auth.py` | `/api/auth/*` | `dashboard-status`, `dashboard-login`, `dashboard-setup` |
| Settings sync | `routes/settings_api.py` | `/api/settings/*` | — |
| Posting module | `routes/posting_api.py` | `/api/posting/*` | — |
| Editor / stories | `routes/editor_api.py` | `/api/editor/*` | — |
| Diagnostics | `routes/testing_api.py` | `/api/testing/*` | — |
| Per-platform × 15 | `routes/{ib,fa,ws,sf,sqw,ao3,da,wp,ik,bsky,tw,mast,tum,pix,thr}_api.py` | `/api/{p}/*` | — |

Router registration order in `dashboard.py:include_router(...)`:
dashboard auth first (so its exempt paths register before the session
middleware applies), then core, then per-platform, then posting,
editor, settings, testing.

**Core API (`routes/api.py` — `/api/*`)**:

| Method | Endpoint | Purpose |
|--------|----------|---------|
| GET | `/api/health` | Health check for Docker / liveness probe (`{"status": "ok"}`). Auth-exempt. |
| GET | `/api/status` | Polling status, last/next poll time, submission counts. |
| GET | `/api/summary` | Dashboard summary (totals, top 5, growth rates, watcher stats). |
| GET | `/api/submissions` | List IB submissions (sortable, paginated). |
| GET | `/api/submissions/{id}` | Single IB submission detail. |
| GET | `/api/snapshots/{id}` | IB submission time-series (filterable by date range). |
| GET | `/api/aggregate` | Cross-submission IB totals. |
| GET | `/api/comparison` | Multi-submission IB comparison data. |
| GET | `/api/watchers` | IB watcher list. |
| POST | `/api/poll/trigger` | Trigger manual IB poll. |
| POST | `/api/poll/full-resync` | Force full re-fetch of all data. |
| GET | `/api/poll/progress` | Real-time IB poll status. |
| GET | `/api/poll/all-progress` | Aggregate progress across every platform. |
| POST | `/api/poll/pause` | Pause the orchestrator (all platforms). |
| POST | `/api/poll/resume` | Resume polling. |
| GET | `/api/poll/paused` | `{polling_paused: bool, paused_platforms: [code…]}` state probe. |
| POST | `/api/poll/pause/{code}` | Pause scheduled polling for ONE platform (2.103.0). Adds `code` to `settings.polling_paused_platforms`; `_poll_all()` skips it each cycle. Manual poll/resync still work. |
| POST | `/api/poll/resume/{code}` | Resume scheduled polling for ONE platform (2.103.0). |
| POST | `/api/session/clear` | Clear server-side session state. |
| GET | `/api/poll_log` | IB poll audit trail. |
| GET | `/api/analytics/top-fans` | Cross-platform fan leaderboard. |
| GET | `/api/analytics/trending` | Submissions with unusual growth (spike detection). |
| GET | `/api/analytics/historical` | Historical analytics rollup. |
| GET | `/api/groups` / POST / GET `/{id}` / PUT / DELETE | Submission groups CRUD. |
| GET | `/api/groups/{id}/stats` | Per-group submission stats. |
| POST | `/api/groups/{id}/members` / DELETE `/{gid}/members/{mid}` | Group membership. |
| GET | `/api/links` / POST / DELETE `/{id}` | Cross-platform submission links. |
| GET | `/api/links/{id}/stats` | Link aggregate stats. |
| GET | `/api/links/{id}/snapshots` | Link time-series. |
| GET | `/api/links/suggestions` | Auto-detected cross-platform link candidates. |
| GET | `/api/pins` / POST / DELETE | Pinned submissions. |
| GET | `/api/update/check` / POST `/apply` | GitHub release check + auto-update. |
| GET | `/api/thumbnail` | Proxy for IB CDN thumbnails (CORS bypass). |
| GET | `/api/export/submissions` / `/api/export/snapshots` | CSV exports. |
| GET | `/api/backup/database` / POST `/api/backup/restore` | Backup / restore the SQLite DB. |
| GET | `/api/logs` | Tail of `logs/app.log`. |
| GET | `/api/goals` / POST / DELETE `/{id}` | User goals. |
| GET | `/api/tags` / POST / DELETE `/{id}` / POST `/{id}/assign` / DELETE `/{tid}/submissions/{platform}/{sid}` | User-defined tag CRUD + assignment. |
| GET | `/api/settings/credentials` / POST | IB credential status (username + has_password flag). |
| GET | `/api/settings/preferences` / POST | Preferences (see below for accepted keys). |
| GET | `/api/settings/telegram` / POST / DELETE / `/test` / `/disconnect` / `/features` / `/digest` | Telegram bot + digest controls. |

**Dashboard auth (`routes/dashboard_auth.py` — `/api/auth/*`)**:

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/api/auth/dashboard-status` | Auth state probe. Auth-exempt. |
| POST | `/api/auth/dashboard-login` | Username + password (+ TOTP if enabled). Auth-exempt. |
| POST | `/api/auth/dashboard-setup` | First-time admin creation. Auth-exempt. |
| POST | `/api/auth/dashboard-logout` | Clear cookie session. |
| POST | `/api/auth/dashboard-change-password` | Rotate password. |
| POST | `/api/auth/totp-setup` / `/totp-enable` / `/totp-disable` | TOTP 2FA flow. |
| GET | `/api/auth/api-keys` / POST / DELETE `/{prefix}` | API key CRUD — Bearer `pp_xxx` keys. |
| POST | `/api/auth/turnstile-config` | Save Turnstile site/secret keys. |

The historical `/api/auth/login` / `/api/auth/logout` / `/api/auth/status`
endpoints documented in earlier versions of this guide were renamed to
`dashboard-login` / `dashboard-logout` / `dashboard-status` when the
multi-platform auth refactor landed (the per-platform `/auth/*` paths
still exist under each platform router).

**Settings sync (`routes/settings_api.py` — `/api/settings/*`)**:

| Method | Endpoint | Purpose |
|---|---|---|
| POST | `/api/settings/sync` | Push local settings.json → remote (desktop↔server pairing). |
| GET | `/api/settings/sync/status` | Last sync metadata. |
| GET | `/api/settings/vault/status` | Credential vault status (always-on; reports key_source). |
| GET | `/api/settings/setup-status` / POST `/setup-reset` / `/setup-complete` / `/setup-mode` | First-run wizard. |
| POST | `/api/settings/pair-test` | Verify remote pairing works. |
| GET | `/api/settings/browser-login/platforms` / POST `/browser-login/{platform}` | Embedded pywebview login. |

**Posting module (`routes/posting_api.py` — `/api/posting/*`)**: 20+
endpoints covering story listing, file/image/archive proxies, post and
update entry points, publications list + stats + detail, queue CRUD,
posting log, posting settings, retroactive sync (claim, changes,
sync/upload, sync/push, sync/status). Full surface visible via
`grep "@posting_router"` in `routes/posting_api.py`.

**Editor / stories (`routes/editor_api.py` — `/api/editor/*`)**: 40+
endpoints — story CRUD, content read/write, preview, regenerate one,
regenerate-all + SSE stream + cancel + active probe, publish-check,
verify posted, probe-drafts, publish action, schedule, scheduled list
+ per-row cancel + bulk cancel (2.21.0), publication forget +
URL-anchor PUT/DELETE (2.21.0), theme save, metadata, chapter
thumbnail upload, cover upload, import endpoints + manual ID/URL
import. See §15 for the editor flows; the testing-tab and diagnostics
endpoints live under `/api/testing/` (§16).

**Diagnostics (`routes/testing_api.py` — `/api/testing/*`)**: see §16
for full coverage. Endpoints: `tests`, `last-results`, `active`,
`run/{test_id}`, `run-category/{category}`, `run-suite`,
`stream/{run_id}` (SSE), `stop/{run_id}`.

**Per-platform API pattern** (each platform router provides):

| Method | Endpoint | Purpose |
|--------|----------|---------|
| GET | `/api/{p}/auth/status` | Check platform auth status |
| POST | `/api/{p}/auth/connect` | Validate and save credentials |
| POST | `/api/{p}/auth/disconnect` | Remove platform credentials |
| GET | `/api/{p}/submissions` | List platform submissions |
| GET | `/api/{p}/submissions/{id}` | Single submission detail |
| GET | `/api/{p}/submissions/{id}/snapshots` | Time-series data |
| GET | `/api/{p}/aggregate` | Platform aggregate stats |
| GET | `/api/{p}/comparison` | Multi-submission comparison |
| POST | `/api/{p}/poll/trigger` | Trigger manual poll |
| GET | `/api/{p}/poll/progress` | Real-time poll status |
| GET | `/api/{p}/poll_log` | Poll audit trail |
| GET | `/api/{p}/export/csv` | CSV export |

Platform-specific extras:
- `/api/fa/watchers` — FA watcher list with spam status
- `/api/fa/watchers/{username}` — Individual watcher detail
- `/api/sf/followers` — SF follower list

### Preferences Endpoint — Accepted Keys

`GET /api/settings/preferences` returns all keys below with their defaults.
`POST /api/settings/preferences` accepts any subset — only provided keys are updated.

| Key | Type | Default | Validation | Effect |
|-----|------|---------|------------|--------|
| `minimize_to_tray` | bool | false | — | Hide to tray on close (desktop) |
| `run_on_startup` | bool | false | — | Windows registry entry (desktop) |
| `display_timezone` | string | "UTC" | — | Timezone for Telegram messages |
| `theme` | string | "dark" | one of {dark, light, ink_copper, parchment, midnight_press, forest, velvet, high_contrast} | UI theme; persists to settings.json so it syncs cross-device |
| `auto_sync_enabled` | bool | true | — | Master toggle for the desktop ↔ server settings auto-sync (see "Settings auto-sync") |
| `notifications_enabled` | bool | true | — | IB master notification toggle |
| `fa_notifications_enabled` | bool | true | — | FA master notification toggle |
| `ws_notifications_enabled` | bool | true | — | WS master notification toggle |
| `sf_notifications_enabled` | bool | true | — | SF master notification toggle |
| `sqw_notifications_enabled` | bool | true | — | SqW master notification toggle |
| `ao3_notifications_enabled` | bool | true | — | AO3 master notification toggle |
| `da_notifications_enabled` | bool | true | — | DA master notification toggle |
| `wp_notifications_enabled` | bool | true | — | WP master notification toggle |
| `ik_notifications_enabled` | bool | true | — | IK master notification toggle |
| `bsky_notifications_enabled` | bool | true | — | BSKY master notification toggle |
| `tw_notifications_enabled` | bool | true | — | TW master notification toggle |
| `watcher_notifications_enabled` | bool | true | — | IB watcher alerts |
| `fa_watcher_notifications_enabled` | bool | true | — | FA watcher alerts |
| `poll_interval_minutes` | int | 60 (main.py) / 240 (server.py) | {15,30,60,120,240} | IB poll frequency (main.py); unified poll interval for all platforms (server.py) |
| `fa_poll_interval_minutes` | int | 60 | {15,30,60,120,240} | FA poll frequency (main.py only; ignored by server.py orchestrator) |
| `ws_poll_interval_minutes` | int | 60 | {15,30,60,120,240} | WS poll frequency (main.py only) |
| `sf_poll_interval_minutes` | int | 60 | {15,30,60,120,240} | SF poll frequency (main.py only) |
| `sqw_poll_interval_minutes` | int | 60 | {15,30,60,120,240} | SqW poll frequency (main.py only) |
| `ao3_poll_interval_minutes` | int | 60 | {15,30,60,120,240} | AO3 poll frequency (main.py only) |
| `da_poll_interval_minutes` | int | 60 | {15,30,60,120,240} | DA poll frequency (main.py only) |
| `wp_poll_interval_minutes` | int | 60 | {15,30,60,120,240} | WP poll frequency (main.py only) |
| `ik_poll_interval_minutes` | int | 60 | {15,30,60,120,240} | IK poll frequency (main.py only) |
| `bsky_poll_interval_minutes` | int | 60 | {15,30,60,120,240} | BSKY poll frequency (main.py only) |
| `tw_poll_interval_minutes` | int | 60 | {15,30,60,120,240} | TW poll frequency (main.py only) |
| `notification_comments_only` | bool | false | — | IB: suppress fave alerts |
| `fa_notification_comments_only` | bool | false | — | FA: stored, no-op (FA only alerts on comments) |
| `ws_notification_comments_only` | bool | false | — | WS: suppress fave-triggered activity alerts |
| `sf_notification_comments_only` | bool | false | — | SF: suppress generic activity alerts |
| `notification_min_faves_delta` | int | 0 | ≥ 0 | IB: min new-fave count to notify (0 = off) |
| `notification_min_views_delta` | int | 0 | ≥ 0 | Stored, not yet consumed |
| `telegram_enabled` | bool | false | — | Telegram notification master toggle |
| `milestone_views` | int[] | [100..100000] | sorted, >0 | View milestone thresholds |
| `milestone_faves` | int[] | [10..5000] | sorted, >0 | Fave milestone thresholds |
| `milestone_comments` | int[] | [10..1000] | sorted, >0 | Comment milestone thresholds |

Poll interval values outside the allowed set {15, 30, 60, 120, 240} are silently rejected. All other fields are individually optional — only keys present in the request body are updated.

### Dashboard Authentication

Self-hosted session-based auth system (`dashboard.py` + `routes/dashboard_auth.py`). Replaces the old HTTP Basic Auth popup with proper login forms, session cookies, optional 2FA, API keys, and bot protection.

**Two separate auth systems** — do not confuse:
- **Dashboard auth** (this section): Controls who can access PawPoller itself. Session cookies + API keys.
- **Platform auth** (`routes/api.py` `/api/auth/*`): Validates Inkbunny credentials for polling. Unchanged.

**Auth flow**:
1. SPA loads (/, /css/*, /js/* exempt from auth)
2. `App.init()` calls `GET /api/auth/dashboard-status` (exempt)
3. If `auth_required && !authenticated` → show `#/dashboard-login`
4. User submits credentials → `POST /api/auth/dashboard-login`
5. Server validates bcrypt hash + optional TOTP + optional Turnstile
6. Success → `pp_session` cookie set → app re-initializes

**Session cookies**:
- Signed with `itsdangerous.URLSafeTimedSerializer` using a server-side secret
- Payload: `{"u": username}` (minimal — single user, no roles)
- Cookie: `pp_session`, httponly, samesite=Strict, secure when HTTPS
- Max age: 24h default, 30 days with "remember me"
- Secret auto-generated (32-byte hex) on first use, stored in settings.json

**API keys** for programmatic access (scripts, Claude, curl):
- Format: `pp_` + 48 hex chars = 51 chars total
- Storage: SHA-256 hash in settings.json (fast lookup, secure for random tokens)
- Usage: `Authorization: Bearer pp_xxx` header
- Managed via Settings > Security > API Keys

**Optional TOTP 2FA** (`pyotp`):
- Standard TOTP with 30-second windows, ±1 window tolerance
- QR code generated client-side via `qrcode.min.js` vendor lib
- Enable flow: `/totp-setup` → show QR → `/totp-enable` with verification code
- Disable requires both password and valid TOTP code

**Optional Cloudflare Turnstile** bot protection:
- Site key + secret key configured in Settings > Security > Turnstile
- Widget loaded on login form when configured
- Server-side token verification via Cloudflare API
- CSP automatically updated to allow `challenges.cloudflare.com`

**Middleware** (`session_auth_middleware`):
```
1. If no auth configured (no hash + no legacy password) → pass through
2. If path is / or /css/* or /js/* → pass through (let SPA load)
3. If path in exempt set (health, dashboard-status, login, setup) → pass through
4. If rate limited → 429
5. If Authorization: Bearer pp_xxx → validate API key hash
6. If pp_session cookie → validate signed cookie + max_age
7. Otherwise → 401 JSON
```

**Migration**: On first startup after upgrade, `_migrate_dashboard_auth()` runs:
- If `auth_password_hash` exists → skip (already migrated)
- If `dashboard_password` in settings or `DASHBOARD_PASSWORD` env → hash with bcrypt → save as `auth_password_hash` → delete plaintext
- Same migration in both `server.py` (headless) and `dashboard.py` (desktop)

**Dashboard auth API endpoints** (`routes/dashboard_auth.py`):
| Method | Path | Auth Exempt | Purpose |
|--------|------|:-----------:|---------|
| GET | `/api/auth/dashboard-status` | Yes | Auth state (required, authenticated, totp, turnstile key) |
| POST | `/api/auth/dashboard-login` | Yes | Validate creds, set session cookie |
| POST | `/api/auth/dashboard-setup` | Yes* | First-time password setup (*only when no hash exists) |
| POST | `/api/auth/dashboard-logout` | No | Clear session cookie |
| POST | `/api/auth/dashboard-change-password` | No | Current + new password |
| POST | `/api/auth/totp-setup` | No | Generate TOTP secret + otpauth URI |
| POST | `/api/auth/totp-enable` | No | Verify code, activate 2FA |
| POST | `/api/auth/totp-disable` | No | Requires password + TOTP code |
| GET | `/api/auth/api-keys` | No | List keys (prefix + name only) |
| POST | `/api/auth/api-keys` | No | Generate new key (returns full key once) |
| DELETE | `/api/auth/api-keys/{prefix}` | No | Revoke a key |
| POST | `/api/auth/turnstile-config` | No | Save Turnstile site key + secret key |

**Brute-force protection**: In-memory rate limiter tracks failed attempts per client IP. After 10 failures within a 5-minute window, all further requests from that IP receive HTTP 429. Clears on successful auth. Resets on container restart. Shared between middleware and login endpoint.

**Programmatic access with API keys** (replaces old Basic Auth curl commands):
```bash
# Generate a key in Settings > Security > API Keys, then:
curl -H "Authorization: Bearer pp_xxxx..." http://localhost:8420/api/status
```

### Security Hardening

The following security measures are applied in `dashboard.py` and across the codebase:

**HTTP Security Headers** — Applied to every response via middleware:
| Header | Value | Purpose |
|--------|-------|---------|
| `X-Content-Type-Options` | `nosniff` | Prevent MIME-sniffing |
| `X-Frame-Options` | `DENY` | Block iframe embedding (clickjacking) |
| `Referrer-Policy` | `strict-origin-when-cross-origin` | Limit referrer leakage |
| `Content-Security-Policy` | `default-src 'self'; script-src 'self' 'sha256-<computed>'; style-src 'self' 'unsafe-inline' fonts.googleapis.com; font-src 'self' fonts.gstatic.com; img-src 'self' https:; connect-src 'self'; frame-ancestors 'none'` | Restrict resource loading |

CSP rationale: All JS loaded via `<script src=...>` *except* one tiny inline boot script in `index.html` (and byte-identical in `epub-viewer.html`) that sets `data-theme` + `data-mobile` + `data-navmode` synchronously to avoid a flash of default-dark / wrong-shell. That script's SHA-256 hash is allowlisted; everything else inline is dropped. **The hash is computed at runtime from the HTML files** (`_theme_inline_hash()`, cached) rather than hardcoded — 2.70.0 shipped a regression where the boot script was edited but a hardcoded hash wasn't, silently blocking the script and breaking theme + mobile-mode boot; deriving it from the file self-heals. The helper hashes both `index.html` and `epub-viewer.html` (deduped), so editing one without the other can't block it. Inline `style=` attributes require `'unsafe-inline'`. Google Fonts CSS + woff2 binaries get explicit allowlist origins. Platform CDN thumbnails need `https:`. All API calls are same-origin. When Cloudflare Turnstile is configured, `script-src` and `frame-src` automatically include `https://challenges.cloudflare.com`.

**Path-scoped CSP relaxation for `/epub-viewer.html`** — `_build_epub_viewer_csp()` returns a separate policy that allows `blob:` in `style-src`, `img-src`, `font-src`, `connect-src`, and `frame-src`. epub.js extracts the EPUB's stylesheets, fonts, and inline images into Blob URLs and references them from the rendered iframe; under the strict default the iframe loads chapter HTML with no styling. The middleware swaps to the relaxed CSP only when `request.url.path == "/epub-viewer.html"` so every other route keeps the strict default. Both CSPs get the inline-boot-script hash from the same `_theme_inline_hash()`, so editing that script in either HTML file no longer needs a manual hash update — the value is recomputed from the files.

**CORS** — Configured via FastAPI `CORSMiddleware` with `allow_origins=[]` (no cross-origin requests). The SPA and API are same-origin, so no legitimate cross-origin requests should occur.

**Docker Container Security**:
- Container runs as non-root user `pawpoller` (UID 1001) — not as root
- Data/log directories are pre-created and owned by the `pawpoller` user
- Port 8420 is above 1024 (no root needed to bind)

**Settings.json Protection**:
- File permissions set to `0600` (owner read/write only) on Unix/Linux after every write
- Atomic writes via temp file + `os.replace()` prevent corruption

**SQL Injection Prevention**:
- All user-supplied values use parameterised queries (`?` placeholders)
- Goal metrics validated against `config.ALLOWED_GOAL_METRICS` frozenset before SQL interpolation — single source of truth shared by `routes/api.py` and `polling/telegram.py`

**CSV Export Security**:
- All string values sanitised against formula injection before CSV write
- Cells starting with `=`, `+`, `-`, `@`, `\t`, `\r` are prefixed with `'` (OWASP recommendation)

**Dependency Pinning**:
- `requirements-server.txt` uses compatible release (`~=`) specifiers to pin dependencies
- Allows patch updates but blocks minor/major version bumps that could introduce breaking changes

**Frontend XSS Prevention**:
- `Utils.escapeHtml()` used for all user-supplied data rendered as HTML
- No `eval()` or dynamic code execution
- Error messages escaped before innerHTML insertion

---

## 8. Notifications

### Desktop Toast Notifications (per-OS shim)

`polling/notifications.py:show_toast()` is a single-entry-point helper
that branches on `sys.platform`. Callers (the 11 pollers) just call it
with a title + line list and don't care which backend fires.

**Windows** — `winotify` (Windows 10/11 native toast). Lazy-imported so
the module loads cleanly on non-Windows builds:

```python
if sys.platform == "win32":
    from winotify import Notification
    Notification(app_id="PawPoller", title=title, msg=msg).show()
    return True
```

**Linux** — shell-out to `notify-send` (libnotify CLI). Present by
default on every major desktop environment (GNOME, KDE, XFCE, MATE,
Cinnamon, LXQt). `--app-name=PawPoller` groups our toasts together in
DE notification centres; `--expire-time=8000` (8s) matches the
Windows toast dwell:

```python
if sys.platform.startswith("linux"):
    subprocess.run([
        "notify-send", "--app-name=PawPoller", "--expire-time=8000",
        title, msg,
    ], check=False, timeout=3.0)
    return True
```

Silently no-ops (returns False + debug log) when `notify-send` isn't on
PATH — headless servers, minimal containers, AppImage runs on hosts
that haven't installed libnotify. PawPoller still works; the user just
doesn't get desktop toasts.

**macOS / other** — no-op + debug log for now. The launch-agent plist
work plus a `pync`/`osascript` notifications branch will land when the
macOS native app ships.

The server/Docker deployment silently skips toasts on all platforms
because all three branches gracefully degrade when their backend is
missing (no winotify, no notify-send, no `sys.platform == "darwin"`).

**Notification types per platform**:
- New comments: "IB: 3 New Comments" with up to 3 lines of "User commented on Title"
- New favorites: "IB: 5 New Favorites" with up to 3 lines of "User favorited Title"
- New watchers: "FA: 2 New Watchers" with up to 3 lines of "User started watching you"
- Truncation: if >3 items, last line says "...and N more"
- Platform prefix (IB:/FA:/WS:/SF: etc.) for visual distinction at a glance

**Settings filters**:

*Per-platform notification master toggles* — each platform has a `{prefix}_notifications_enabled` key that acts as a master on/off switch for all toast + Telegram alerts from that platform:
- `notifications_enabled` (IB), `fa_notifications_enabled`, `ws_notifications_enabled`, `sf_notifications_enabled`, `sqw_notifications_enabled`, `ao3_notifications_enabled`, `da_notifications_enabled`, `wp_notifications_enabled`, `ik_notifications_enabled`, `bsky_notifications_enabled`, `tw_notifications_enabled`

*Watcher / follower notification toggles* — separate from the master toggle so users can receive submission alerts without watcher alerts (or vice versa):
- `watcher_notifications_enabled` (IB) — toggles IB watcher toast + Telegram alerts
- `fa_watcher_notifications_enabled` — toggles FA watcher toast + Telegram alerts

*Comments-only filters* — when enabled, suppress fave/activity notifications and only alert on new comments:
- `notification_comments_only` (IB) — suppresses fave notifications in both toast and Telegram
- `fa_notification_comments_only` — stored but currently a no-op (FA only notifies on comments/watchers, no fave notifications to suppress)
- `ws_notification_comments_only` — suppresses WS activity notifications (which are triggered by fave-count increases)
- `sf_notification_comments_only` — suppresses SF activity notifications (generic stat-change alerts); follower notifications are unaffected

*Minimum delta thresholds* (IB only):
- `notification_min_faves_delta` — suppress fave notifications unless the number of new faves in a cycle meets or exceeds this value (0 = no minimum, notify on any new fave)
- `notification_min_views_delta` — stored for future use; no platform currently generates view-change-based notifications

### Telegram Notifications (`polling/telegram.py`)

Requires `telegram_bot_token` and `telegram_chat_id` in settings.

**Poll summary format** (sent after each poll cycle):
```
<b>{emoji} {Platform} Poll Complete</b>
  {submissions} submissions, {snapshots} snapshots in {duration}s
  New: +{faves} faves, +{comments} comments, +{watchers} watchers
```

Platform emojis: IB=🐾, FA=🦊, WS=🦎, SF=🐺, SqW=🦑, AO3=📖, DA=🎨, WP=📙, IK=🎯

**Error alert format**:
```
<b>{emoji} {Platform} Poll Failed</b>
  {error_message[:200]}
```

**Milestone thresholds** (configurable via settings):
```python
VIEWS_MILESTONES     = [100, 250, 500, 1000, 2500, 5000, 10000, 25000, 50000, 100000]
FAVORITES_MILESTONES = [10, 25, 50, 100, 250, 500, 1000, 2500, 5000]
COMMENTS_MILESTONES  = [10, 25, 50, 100, 250, 500, 1000]
```

Milestone detection logic:
```python
def _crossed_milestone(current, previous, thresholds):
    """Returns highest milestone crossed, or None."""
    for m in reversed(thresholds):  # Check highest first
        if previous < m <= current:
            return m
    return None
```

Milestone alert format:
```
<b>🎉 Milestone: "Submission Title" hit {milestone} {metric}!</b>
  {platform} — currently at {current}
```

**Platform-aware column mapping** (`PLATFORM_METRICS` dict):
Different platforms call their stats different things:
- IB/FA/WS/SF/SqW/AO3/DA: `views`, `favorites_count`, `comments_count`
- Wattpad: `reads` (not views), `votes` (not favorites), `comments_count`, `num_lists`
- Itaku: `likes` (not views/favorites), `comments_count`, `reshares` (no views metric at all)
- Bluesky: `likes`, `replies`, `reposts`, `quotes` (no views metric)
- X/Twitter: `views`, `likes`, `replies`, `retweets`, `quotes`, `bookmarks` (6 metrics — most of any platform)

**6-Hour Digest Report** (sent by digest scheduler thread in `main.py`, or by poll orchestrator in `server.py`):
```
<b>📊 PawPoller 6-Hour Digest</b>

🐾 <b>Inkbunny</b>
  Views: 12,345 (+234)
  Favorites: 678 (+12)
  Comments: 45 (+3)
  Top gainer: "My Art" +120 views

🦊 <b>FurAffinity</b>
  Views: 8,901 (+156)
  ...

<b>Grand Totals</b>
  Views: 45,678 (+890)
  Favorites: 2,345 (+67)
```

The digest aggregates stats deltas from 6 hours ago to now using snapshot data. Shows top 3 gainers per platform. Skips platforms with no data.

**Goal completion checking** (`check_goals()`):
- Queries `goals` table for incomplete goals (`completed_at IS NULL`)
- Supports scopes: `"submission"` (specific submission), `"platform"` (all submissions on one platform), `"all"` (cross-platform total)
- Uses `UPDATE ... SET completed_at = datetime('now') WHERE completed_at IS NULL` with `rowcount` check to prevent duplicate notifications from concurrent pollers reaching the goal simultaneously

### Telegram Error Classification

`_classify_error()` in `polling/telegram.py` maps raw exception strings to user-friendly `(label, hint)` pairs. 13 patterns cover: login blocks, rate limits, Cloudflare challenges, 403/404, timeouts, connection errors, SSL issues, and dropped connections. `send_poll_error()` now shows a bold label, italic hint explaining the likely cause, and the raw error in monospace for debugging. `send_consolidated_poll_summary()` uses the same classifier for failed platform lines.

Before: `AO3: AO3 login failed -- check credentials`
After: `AO3: Login blocked` / `Likely Cloudflare/rate-limit, not bad creds`

### Telegram Bot Commands (`polling/telegram_bot.py`)

**Long-polling loop**:
```python
async def run_bot():
    _last_update_id = 0
    # Flush stale updates on startup
    updates = await _get_updates(offset=-1, timeout=0)
    if updates:
        _last_update_id = updates[-1]["update_id"]

    while True:
        settings = config.get_settings()  # Hot-reload config each loop
        if not settings.get("telegram_enabled"):
            await asyncio.sleep(30)
            continue
        updates = await _get_updates(offset=_last_update_id + 1, timeout=30)
        for update in updates:
            _last_update_id = update["update_id"]
            # Only respond to configured chat_id (security)
            if update_chat_id != expected_chat_id:
                continue
            await _dispatch_command(text, chat_id)
```

**Command handlers detail**:

| Command | Handler | What it does |
|---------|---------|-------------|
| `/help`, `/start` | `_cmd_help` | Returns formatted list of all commands with descriptions |
| `/stats` | `_cmd_stats` | Queries each platform's submission table for COUNT, SUM(views), SUM(favorites). Formats as multi-platform summary with emoji prefixes. |
| `/top [platform]` | `_cmd_top` | Queries top 5 submissions by views (or platform-specific metric like reads for WP). Shows title, views, faves, comments for each. Default: IB. |
| `/trending` | `_cmd_trending` | Z-score based spike detection. Compares recent snapshot deltas against historical mean/stddev. Lists submissions with unusual growth. |
| `/digest` | `_cmd_digest` | Triggers `send_digest_report()` immediately instead of waiting for 6-hour timer. |
| `/fans` | `_cmd_fans` | Calls `analytics_queries.get_top_fans()` for cross-platform top 10 fan leaderboard with fave + comment counts. |
| `/poll [platform]` | `_cmd_poll` | Force-triggers a poll cycle. Supports: ib, fa, ws, sf, sqw, ao3, da, wp, ik, all. Uses `asyncio.create_task()` so the poll runs in the background and the bot responds immediately. |
| `/status` | `_cmd_status` | Shows last poll time (timezone-adjusted), current interval, and thread status for each platform. |
| `/interval [platform] [minutes]` | `_cmd_interval` | Changes poll interval via `config.save_settings()`. Minimum 15 minutes. Takes effect on next cycle. |
| `/notify` (no args) | `_cmd_notify` | Shows current state of all notification toggles. |
| `/notify [type] [on\|off]` | `_cmd_notify` | Toggles specific notification types (e.g. `/notify fa_watchers off`). |

---

## 9. Configuration System

### Path Resolution (`config.py`)

```python
def resource_path(relative: str) -> Path:
    if getattr(sys, "frozen", False):
        base = Path(sys._MEIPASS)    # PyInstaller temp extraction directory
    else:
        base = Path(__file__).resolve().parent  # Project root in dev mode
    return base / relative
```

**Directory layout by mode**:
```
Frozen (.exe):
  sys._MEIPASS/          # Read-only bundled assets (code, templates, static files)
    ├── frontend/
    ├── database/*.sql
    └── assets/
  %APPDATA%/PawPoller/   # Persistent user data
    ├── data/pawpoller.db
    ├── data/settings.vault.json  # Encrypted credentials (vault always-on since 2.101.0)
    ├── logs/app.log
    └── settings.json

Dev mode (python main.py):
  project_root/          # Everything in one place
    ├── frontend/
    ├── database/*.sql
    ├── data/pawpoller.db
    ├── data/settings.vault.json  # Encrypted credentials (vault always-on since 2.101.0)
    ├── logs/app.log
    └── settings.json
```

### settings.json — Thread-Safe Atomic Read-Modify-Write

```python
_settings_lock = threading.Lock()

def save_settings(data: dict) -> None:
    """Merge data into settings.json atomically."""
    import tempfile
    with _settings_lock:
        current = _load_settings()           # Read current file
        current.update(data)                  # Overlay new keys
        # Atomic write: temp file → os.replace()
        fd, tmp_path = tempfile.mkstemp(dir=SETTINGS_PATH.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(current, f, indent=2)
            os.replace(tmp_path, SETTINGS_PATH)  # Atomic on same filesystem
        except BaseException:
            try:
                os.unlink(tmp_path)           # Clean up temp on failure
            except OSError:
                pass
            raise
```

The temp file is created in the same directory as settings.json to ensure `os.replace()` is atomic (same filesystem). This prevents a crash mid-write from leaving a truncated/corrupt settings.json.

### Credential Vault (Phase 7b; ALWAYS ON since 2.101.0)

Credential fields listed in `CREDENTIAL_FIELDS` (plus account-namespaced `acct_<id>_<field>` secrets, via `is_credential_key()`) are **always** stored encrypted in `settings.vault.json` — there is no plaintext mode and no enable/disable toggle. The vault uses Fernet symmetric encryption with a key sourced from (in order): an operator-supplied `PAWPOLLER_VAULT_KEY`/`PAWPOLLER_VAULT_KEY_FILE` (servers — keeps the key off the data volume), the system keyring (desktop — Windows Credential Manager / macOS Keychain; `keyring` is a desktop requirement), or a `.vault_key` dotfile with 0600 permissions (last-resort fallback).

```
settings.json   → non-credential settings only (+ credential_mode:"local" stamp for downgrade compat)
settings.vault.json → Fernet-encrypted JSON blob containing all credential fields
```

The integration is transparent: `_load_settings()` merges decrypted vault data into the returned dict, and `save_settings()`/`delete_settings_keys()` split credential fields into the vault on every write — the vault is rewritten even when empty, so deleting the last secret can't be resurrected by stale ciphertext. `ensure_vault()` runs at startup (dashboard lifespan + server main) and sweeps any plaintext credential values (pre-2.101.0 file, hand edit, old-backup restore) into the vault. All consumers see a unified view without needing vault awareness.

**Key functions**: `_get_vault_key()`, `vault_key_source()`, `_encrypt_vault()`, `_decrypt_vault()`, `ensure_vault()`, `migrate_to_local_vault()`; `migrate_to_cloud()` is a console-only break-glass decrypt (no API/UI path).

**API endpoints**: `GET /api/settings/vault/status` (reports `key_source`); the old `POST …/vault/enable` + `/vault/disable` endpoints were removed in 2.101.0.

### Security assessment & cross-cutting controls (ASVS 5.0 L2, 2.102.0)

The app is assessed against **OWASP ASVS 5.0 Level 2** — the full requirement-by-requirement
walk-through with evidence and a Known-Gaps register lives at
`docs/security/ASVS_ASSESSMENT.md` (ships in the public copy). Re-run/refresh it when touching
auth, session, crypto, file handling, or the CSP/headers. Cross-cutting controls added in 2.102.0:

- **Frontend URL safety** — `Utils.safeUrl()` allowlists URL schemes (http(s)/relative/blob/
  `data:image`) so a scraped `javascript:` URL can't reach an `href`; `Utils.cssUrl()` does the
  same then percent-encodes the CSS/HTML breakout set for `url()` contexts (both in `utils.js`).
  All external-URL `href`/`background-image` sinks route through them.
- **5xx error scrubber** — an `@app.exception_handler(StarletteHTTPException)` in `dashboard.py`
  replaces the `detail` of any 5xx with `"Internal server error"` (logging the real detail),
  while leaving 4xx validation messages intact. This neutralizes the ~200 `HTTPException(500,
  detail=str(e))` sites without editing each one.
- **Auth logging** — `routes/dashboard_auth.py` logs every auth outcome with client IP +
  `_sanitize_for_log(username)` (CR/LF-stripped); the middleware logs API-key rejections and
  rate-limit trips.
- **Session invalidation** — `config.rotate_session_secret()` (called on password change)
  regenerates the signing secret, invalidating all stateless session cookies at once.
- **Reduced surface** — FastAPI docs (`/docs`,`/redoc`,`/openapi.json`) are off unless
  `PAWPOLLER_ENABLE_DOCS=1`; log files rotate (`RotatingFileHandler`, 10 MB × 5).

### Settings Sync (Phase 7a)

Desktop and server instances can share credentials via `POST /api/settings/sync`. Supports `mode: "pull"` (fetch server settings) and `mode: "push"` (send local settings to server). Auth enforced by existing dashboard middleware.

- `CREDENTIAL_FIELDS` — 35+ sensitive field names (passwords, cookies, API keys, tokens) eligible for sync.
- `SYNC_EXCLUDE` — per-machine keys that must not sync (`credential_mode`, `auth_session_secret`, `minimize_to_tray`).
- `get_settings_for_sync()` / `merge_synced_settings()` — filter and merge with SYNC_EXCLUDE enforcement.
- `GET /api/settings/sync/status` — returns server version, settings timestamp, credential_mode, total key count.
- Desktop startup pull (`main.py`): `_sync_settings_on_startup()` pulls from the server on launch if `credential_mode != "local"` and server URL is configured. Failures are non-fatal.
- Dashboard UI: Settings > Data tab > "Settings Sync" section with Pull / Push / Status buttons.

### Settings Auto-Sync (2.14.2+)

Built on top of the Phase 7a sync endpoint, but runs automatically without manual button presses. Lives in `auto_sync.py`. Activates only when `posting_server_url` + `posting_server_api_key` are set AND `auto_sync_enabled` is true (default).

**Three moving parts:**

1. **Push side (desktop → server).** `config.save_settings()` calls `auto_sync.schedule_push()` after every successful write. The push is debounced ~2s on a daemon `threading.Timer` so bursts (wizard steps, multi-toggle saves) collapse into one HTTP request. Fire-and-forget — failures log at debug level only.
2. **Pull side (desktop ← server).** `auto_sync.start_pull_thread()` is launched once from `main.py` after the existing one-shot startup pull. Loop interval: `AUTO_SYNC_PULL_INTERVAL_SECONDS = 300` (5 min). Each iteration calls `pull_once()`, which compares server `mtime` against local `mtime` (last-writer-wins) and only merges when the server is newer.
3. **Browser focus refresh.** `App.init()` registers a `visibilitychange` listener (throttled to once per 3s) that pulls `/api/settings/preferences` and reapplies the theme if it changed. So a desktop theme switch repaints any open browser tab on next focus.

**Loop protection.** Because `merge_synced_settings()` calls `save_settings()`, and `save_settings()` triggers a push, a pulled merge would echo every key right back to the server. The `_in_pull_merge` thread-local flag is set inside `pull_once()` for the duration of the merge, and `schedule_push()` skips when the flag is active.

**Loopback skip.** `_sync_target()` returns `None` when the configured `posting_server_url` resolves to `localhost` or `127.0.0.1`, so the cloud server can't try to sync to itself.

**Excluded from auto-sync** (same `SYNC_EXCLUDE` set as manual sync): `credential_mode`, `auth_session_secret`, `minimize_to_tray`.

**Toggle.** `auto_sync_enabled` (default `true`) is exposed in **Settings → Appearance**. Setting `false` disables both push scheduling and the pull loop's effective work (the thread keeps running but no-ops).

**Server side is unchanged.** The cloud server has no `posting_server_url` set, so `_sync_target()` returns `None` for it — the auto-sync hooks become quiet no-ops. All sync traffic still goes through `POST /api/settings/sync`.

### Three-Tier Credential Cascade

```
Priority 1: settings.json    ← Written by UI settings page at runtime
Priority 2: .env file        ← Developer convenience for local testing
Priority 3: Empty string     ← Safe default; pollers skip when blank
```

```python
load_dotenv(_BASE_DIR / ".env")  # Load .env as fallback

_settings = _load_settings()
# `or` short-circuits: if settings.json has the value, .env is never read
INKBUNNY_USERNAME = _settings.get("username") or os.getenv("INKBUNNY_USERNAME", "")
```

**Important caveat**: These module-level reads happen once at import time. They exist for backward compatibility with code that imports `config.INKBUNNY_USERNAME` directly. Pollers should call `config.get_settings()` for fresh reads each cycle — the module-level values are stale snapshots that won't reflect runtime changes made through the UI.

### Environment Variable Seeding (`server.py`)

The `_ENV_TO_SETTINGS` mapping bridges 25+ environment variables into settings.json:

```python
_ENV_TO_SETTINGS = {
    # Inkbunny
    "IB_USERNAME":        "username",
    "IB_PASSWORD":        "password",
    # FurAffinity
    "FA_USERNAME":        "fa_username",
    "FA_COOKIE_A":        "fa_cookie_a",
    "FA_COOKIE_B":        "fa_cookie_b",
    # Weasyl
    "WS_API_KEY":         "ws_api_key",
    # SoFurry
    "SF_USERNAME":        "sf_username",
    "SF_PASSWORD":        "sf_password",
    "SF_DISPLAY_NAME":    "sf_display_name",
    # SquidgeWorld
    "SQW_USERNAME":       "sqw_username",
    "SQW_PASSWORD":       "sqw_password",
    "SQW_TARGET_USER":    "sqw_target_user",
    # AO3
    "AO3_USERNAME":       "ao3_username",
    "AO3_PASSWORD":       "ao3_password",
    "AO3_TARGET_USER":    "ao3_target_user",
    # DeviantArt
    "DA_COOKIE":          "da_cookie",
    "DA_TARGET_USER":     "da_target_user",
    # Wattpad / Itaku (no auth, just target user)
    "WP_TARGET_USER":     "wp_target_user",
    "IK_TARGET_USER":     "ik_target_user",
    # Bluesky
    "BSKY_IDENTIFIER":    "bsky_identifier",
    "BSKY_APP_PASSWORD":  "bsky_app_password",
    # X/Twitter
    "TW_AUTH_TOKEN":      "tw_auth_token",
    "TW_CT0":             "tw_ct0",
    "TW_TARGET_USER":     "tw_target_user",
    # Telegram
    "TELEGRAM_BOT_TOKEN": "telegram_bot_token",
    "TELEGRAM_CHAT_ID":   "telegram_chat_id",
    "TELEGRAM_ENABLED":   "telegram_enabled",   # Parsed as boolean
    # Dashboard
    "DASHBOARD_PASSWORD":  "dashboard_password",
    "DASHBOARD_USER":      "dashboard_user",
    # CF Worker Proxy
    "CF_WORKER_URL":       "cf_worker_url",
    "CF_WORKER_KEY":       "cf_worker_key",
}
```

### Platform Rate Limit Constants

```python
# config.py — inter-request delays (seconds)
REQUEST_DELAY_SECONDS          = 1.0    # IB general API calls
FAVE_REQUEST_DELAY_SECONDS     = 0.5    # IB fave lookups (lighter endpoint)
COMMENT_REQUEST_DELAY_SECONDS  = 1.0    # IB comment scraping
FA_REQUEST_DELAY_SECONDS       = 1.0    # FAExport API calls
WS_REQUEST_DELAY_SECONDS       = 1.0    # Weasyl API calls
SF_REQUEST_DELAY_SECONDS       = 1.5    # SoFurry scraping (higher for scraping)
SQW_REQUEST_DELAY_SECONDS      = 2.0    # SquidgeWorld (anti-bot measures)
AO3_REQUEST_DELAY_SECONDS      = 3.0    # AO3 (volunteer-run, courtesy delay)
DA_REQUEST_DELAY_SECONDS       = 2.0    # DeviantArt (paces official-API pages/ext_stats chunks)
WP_REQUEST_DELAY_SECONDS       = 1.0    # Wattpad public API
IK_REQUEST_DELAY_SECONDS       = 1.0    # Itaku public API
BSKY_REQUEST_DELAY_SECONDS     = 1.0    # Bluesky AT Protocol (generous rate limits)
TW_REQUEST_DELAY_SECONDS       = 2.0    # X/Twitter GraphQL + gallery-dl --sleep-request (aggressive rate limiting)
TW_GALLERYDL_TIMEOUT_SECONDS   = 480    # kill a stuck gallery-dl poll subprocess after 8 min (rides out a typical X rate-limit reset)
```

### Run-on-startup (per-OS shim)

`config.get_run_on_startup()` and `config.set_run_on_startup(enabled)`
are the single entry points used by the Settings → General toggle in
the dashboard. Both branch on `sys.platform`. The exec-string
construction is shared (`_exec_command_for_autostart()`) — frozen
builds register the bundled binary; dev mode registers `python main.py`.

**Windows** — per-user Run registry key. No admin privileges needed:

```python
_STARTUP_REG_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
_STARTUP_REG_NAME = "PawPoller"
# HKCU (not HKLM) — runs only for the current user, no admin needed.
```

**Linux** — XDG autostart `.desktop` file at
`~/.config/autostart/PawPoller.desktop`. Honoured by every major
desktop environment automatically (no user action beyond the toggle
itself). Honours `$XDG_CONFIG_HOME` if set. File contents:

```ini
[Desktop Entry]
Type=Application
Name=PawPoller
Comment=Multi-platform story publishing + analytics
Exec=/path/to/PawPoller.AppImage
Terminal=false
X-GNOME-Autostart-enabled=true
```

`X-GNOME-Autostart-enabled` is GNOME-specific but harmless on other DEs;
`OnlyShowIn=` is intentionally omitted so every DE picks it up.

**macOS** — not implemented yet. Would use a launch agent plist at
`~/Library/LaunchAgents/com.knaughtykat.pawpoller.plist`. Currently
`set_run_on_startup` logs a warning and returns; `get_run_on_startup`
returns False. The Settings toggle still renders for UI parity.

### Other App Constants

```python
APP_VERSION = "2.25.0"  # check config.py for current — bumped on every ship
INKBUNNY_API_BASE = "https://inkbunny.net"
FA_BASE = "https://www.furaffinity.net"
FAEXPORT_BASE = "https://faexport.spangle.org.uk"
DASHBOARD_HOST = "127.0.0.1"      # Localhost only (desktop)
DASHBOARD_PORT = 8420              # Arbitrary high port
SUBMISSION_BATCH_SIZE = 100        # IB API batch size

# Stat offsets for private/deleted submissions
VIEWS_OFFSET = 301                 # Added to API totals to match IB dashboard
FAVORITES_OFFSET = 0
COMMENTS_OFFSET = 0
```

---

## 10. Cloudflare Worker Proxy

### Why It Exists

SoFurry blocks requests from datacenter IP ranges (cloud VMs, Docker containers). Residential IPs (desktop mode) typically work fine. The Cloudflare Worker acts as a reverse proxy, routing requests through Cloudflare's IP range which these sites allow.

Without the proxy, server deployments would get 403 Forbidden responses from SoFurry. Since 2.47.0 DeviantArt polling uses the official OAuth2 API, which is **not** IP-walled (verified 200 from the GCP VM), so DA no longer needs the proxy — only the retained legacy DA cookie/`_napi` fallback (used only when no app credentials are configured) still does. The proxy is otherwise only needed for SoFurry — all other platforms work from any IP.

**SoFurry dual-mode**: SF supports both direct login (with cookie persistence) and CF proxy. The poller auto-selects based on whether `cf_worker_url` is configured in settings. Desktop/local deployments use direct login with 30-day cookie persistence. Server/GCP deployments use the CF proxy (cookie persistence disabled since CF Workers rotate IPs). All proxy code in `client.py` is preserved as fallback — re-enabling is a one-line change in `sf_poller.py`.

### Architecture

```
PawPoller (server.py in Docker)
    │
    │  httpx request to https://sofurry.com/s/12345
    │  intercepted by CloudflareProxyTransport
    ▼
CloudflareProxyTransport (polling/cf_proxy.py)
    │  Rewrites request:
    │    URL: → https://your-worker.workers.dev
    │    Headers: + x-proxy-key, + x-target-url, + Cookie (raw string)
    ▼
Cloudflare Worker (deploy/cf-worker.js)
    │  Validates x-proxy-key against PROXY_SECRET env var
    │  Strips proxy headers, rebuilds request
    │  Forwards to x-target-url with cookie jar
    │  Follows redirects internally (same egress IP)
    ▼
Target Site (sofurry.com / deviantart.com)
    │  Sees request from Cloudflare IP range (allowed)
    │  Returns response
    ▼
Worker → Transport → PawPoller
    Response headers include:
    - X-Final-URL: actual URL after redirects
    - X-Session-Cookies: all cookies as "name=val; name2=val2" string
    - Set-Cookie: forwarded from target site
```

### Python Transport (`polling/cf_proxy.py`)

`CloudflareProxyTransport` extends `httpx.AsyncBaseTransport`:

```python
class CloudflareProxyTransport(httpx.AsyncBaseTransport):
    def __init__(self, worker_url, proxy_key):
        self.worker_url = worker_url.rstrip("/")
        self.proxy_key = proxy_key
        self._worker_host = urlparse(worker_url).netloc
        self._inner = httpx.AsyncHTTPTransport(retries=2)
        self._session_cookies: str = ""    # Raw cookie string

    async def handle_async_request(self, request):
        target_url = str(request.url)
        # Rewrite headers: replace Host, inject cookies bypassing httpx jar
        headers = []
        for k, v in request.headers.raw:
            if k.lower() == b"host":
                headers.append((b"host", self._worker_host.encode()))
            elif k.lower() == b"cookie" and self._session_cookies:
                headers.append((b"cookie", self._session_cookies.encode()))
            else:
                headers.append((k, v))
        # Add proxy-specific headers
        headers.append((b"x-proxy-key", self.proxy_key.encode()))
        headers.append((b"x-target-url", target_url.encode()))
        # Send to worker instead of real target
        proxy_request = httpx.Request(method=request.method, url=self.worker_url, headers=headers)
        response = await self._inner.handle_async_request(proxy_request)
        self._update_cookies_from_response(response)
        return response
```

**Cookie management at the transport layer**: httpx's cookie jar uses domain matching to decide which cookies to send. When proxying through a CF Worker, the HTTP-level request goes to the worker URL (e.g. `workers.dev`), not the real target domain (e.g. `sofurry.com`). This breaks httpx's domain matching — cookies set for sofurry.com won't be sent to a workers.dev URL. So the transport bypasses the cookie jar entirely and manages cookies as raw strings.

**`login_and_fetch` method** (for SoFurry):
```python
async def login_and_fetch(self, login_url, email, password, then_url):
    """Single Worker invocation: GET login → CSRF → POST login → GET gallery"""
    login_data = json.dumps({"url": login_url, "email": email, "password": password, "then": then_url})
    headers = [..., (b"x-proxy-login", login_data.encode())]
    # One request to the Worker handles the entire login + gallery fetch
    response = await self._inner.handle_async_request(proxy_request)
    # Worker returns: X-Session-Cookies header with all session cookies
    self._session_cookies = response.headers.get("x-session-cookies", "")
    return response
```

### Worker Implementation (`deploy/cf-worker.js`)

The Worker handles three modes based on which header is present:

**1. Login mode** (`x-proxy-login` header) — Most complex:
```javascript
// Step 1: GET login page
const loginPageResp = await fetchWithRedirects(login.url, 'GET', null);
const loginHtml = await loginPageResp.text();
const csrfToken = loginHtml.match(/name="_token"\s*value="([^"]+)"/)[1];

// Step 2: POST login with credentials
const formBody = `_token=${csrfToken}&email=${login.email}&password=${login.password}`;
const postResp = await fetchWithRedirects(login.url, 'POST', formBody, {
    'Content-Type': 'application/x-www-form-urlencoded',
});

// Step 3: GET target URL (e.g. gallery)
if (login.then) {
    const thenResp = await fetchWithRedirects(login.then, 'GET', null);
    return buildResponse(thenResp, thenUrl);
}
```

All three steps execute within a single Worker invocation, sharing the same egress IP and cookie jar. This is critical for SoFurry which pins sessions to the login IP.

**2. Normal mode** (`x-target-url` header):
```javascript
const { resp, finalUrl } = await fetchWithRedirects(targetUrl, request.method, request.body);
return buildResponse(resp, finalUrl);
```

**3. Chain mode** (`x-proxy-chain` header):
Executes a sequence of URLs after the main request, all within one invocation (same IP). Used for multi-step operations.

**Internal redirect following** (`fetchWithRedirects`):
The Worker follows redirects internally (up to 10) with `redirect: 'manual'`, forwarding cookies at each hop. This ensures all redirects go through the same egress IP — critical because some sites change behaviour based on whether redirects come from the same IP.

**Cookie forwarding**: All Set-Cookie headers from target site responses are captured in a shared `cookies` object. Each subsequent request within the same invocation includes all accumulated cookies.

**Response metadata**: Every response includes:
- `X-Final-URL` — the URL after all redirects
- `X-Session-Cookies` — all cookies as `"name=val; name2=val2"` string
- Original `Set-Cookie` headers forwarded through

**Hostname allowlist** (added 2026-04-17): The Worker enforces an
`ALLOWED_HOSTS` set covering only the platforms PawPoller actually
routes through — `sofurry.com`, `deviantart.com`, `archiveofourown.org`,
`squidgeworld.org`, `furaffinity.net` and their `www.` variants.
Requests to anything else return `403 Target host not on allowlist: <host>`.
Chain URLs (`x-proxy-chain`) are validated against the same list so they
can't bypass it. This closes the open-proxy risk if `PROXY_SECRET` ever
leaks: an attacker with the secret can only hit platforms we already
talk to, not arbitrary SSRF targets.

When you add a new platform that uses the CF proxy (FA is the likely
next candidate), extend the allowlist in `deploy/cf-worker.js` and
redeploy via wrangler or the CF dashboard.

### Deployment Instructions

1. Log into [Cloudflare Dashboard](https://dash.cloudflare.com/)
2. Navigate to Workers & Pages → Create Worker
3. Replace the default code with the contents of `deploy/cf-worker.js`
4. Go to Settings → Variables → Add: `PROXY_SECRET` = a strong random string
5. Deploy the Worker and copy its URL (e.g. `https://pawpoller-proxy.your-account.workers.dev`)
6. In PawPoller's `.env` file (or settings UI):
   ```
   CF_WORKER_URL=https://pawpoller-proxy.your-account.workers.dev
   CF_WORKER_KEY=same-strong-random-string
   ```

**Debug logging**: Set `PAWPOLLER_DEBUG_PROXY=1` environment variable to enable verbose logging of every proxy request/response/cookie operation. This is extremely noisy — only use when actively debugging proxy issues.

---

## 11. Deployment

### Docker

**Files**:
- `Dockerfile` — Python 3.11 slim base, installs `requirements-server.txt`, copies project, exposes port 8420, runs `server.py`
- `docker-compose.yml` — single service, two named volumes, `.env` file
- `.env.example` — template with all 25+ environment variables

**Dockerfile detail**:
```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements-server.txt .
RUN pip install --no-cache-dir -r requirements-server.txt
COPY . .
EXPOSE 8420
HEALTHCHECK --interval=60s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8420/api/health')" || exit 1
CMD ["python", "server.py"]
```

The HEALTHCHECK uses Python's built-in `urllib` (no curl/wget needed) to ping the health endpoint every 60 seconds. The 30-second start period gives the server time to initialise. After 3 consecutive failures, Docker marks the container as unhealthy.

**docker-compose.yml**:
```yaml
services:
  pawpoller:
    build: .
    ports:
      - "8420:8420"
    volumes:
      - pawpoller-data:/app/data    # SQLite database
      - pawpoller-logs:/app/logs    # Log files
    restart: unless-stopped
    env_file: .env

volumes:
  pawpoller-data:
  pawpoller-logs:
```

Named volumes persist across container rebuilds. The database lives in `pawpoller-data` and log files in `pawpoller-logs`.

**Quick start**:
```bash
cp .env.example .env
# Edit .env with your credentials
docker compose up -d --build
# Verify
curl http://localhost:8420/api/health
# View logs
docker compose logs -f pawpoller
```

### GCP (Google Cloud Platform)

**Initial setup** — `deploy/setup-gcloud.sh` automates:
1. Create a Compute Engine instance (e2-micro or similar)
2. Install Docker + Docker Compose
3. Clone PawPoller repository
4. Copy `.env.example` to `.env` (user must edit with credentials)
5. Run `docker compose up -d --build`
6. Print the dashboard URL: `http://{PUBLIC_IP}:8420`

**Current GCP instance**:
- Instance name: `pawpoller`
- Zone: `us-east1-c`
- Machine type: `e2-micro`
- Repo location on VM: `/home/kithetiger/PawPoller`
- Git user on VM: `kithetiger` (owns the repo clone; `sudo -u kithetiger git pull` required)

**Updating the server (pawupdate workflow)**:

After making code changes locally, the deployment cycle is:

```bash
# 1. Commit and push from local machine
cd PawPoller
git add <changed files>
git commit -m "description of changes"
git push origin master

# 2. SSH into GCP VM, pull changes, rebuild Docker container
gcloud compute ssh pawpoller --zone=us-east1-c --command="cd /home/kithetiger/PawPoller && sudo -u kithetiger git pull && sudo docker compose up -d --build"

# 3. Verify deployment (check logs)
gcloud compute ssh pawpoller --zone=us-east1-c --command="sudo docker compose -f /home/kithetiger/PawPoller/docker-compose.yml logs --tail=30"
```

**Important notes**:
- `git pull` must run as `kithetiger` (repo owner): `sudo -u kithetiger git pull`. Running `git pull` as root fails with permission errors on `.git/FETCH_HEAD`. Running `sudo git pull` fails because root has no GitHub credentials.
- `docker compose` commands require `sudo` because Docker runs as root on the VM.
- The `--build` flag ensures the Docker image is rebuilt with the new code. Without it, Docker would restart the old image.
- The VM's external IP may change on restart (ephemeral IP). Use `gcloud compute instances list` to find the current IP.
- The `gcloud compute ssh` command uses the SSH key at `~/.ssh/google_compute_engine` (managed by gcloud).
- Build is fast (usually <5s) because Docker layer caching means only the `COPY . .` layer is rebuilt when only Python code changes.

**Checking instance status**:
```bash
# List instances with IPs
gcloud compute instances list

# Check container health
gcloud compute ssh pawpoller --zone=us-east1-c --command="sudo docker compose -f /home/kithetiger/PawPoller/docker-compose.yml ps"

# Check specific platform logs
gcloud compute ssh pawpoller --zone=us-east1-c --command="sudo docker compose -f /home/kithetiger/PawPoller/docker-compose.yml logs 2>&1 | grep -i 'SF\|sofurry' | tail -15"
```

### Oracle Cloud

`deploy/setup-oracle.sh` automates the same process for Oracle Cloud Always Free tier, with additional steps:
- Opens port 8420 in iptables (Oracle's internal firewall blocks non-SSH by default)
- Uses `sudo` for docker commands
- Handles ARM architecture compatibility (Oracle's free instances are ARM-based)

### Desktop Installer / Bundles (Windows + Linux)

Native desktop builds are produced by `.github/workflows/build.yml` on
every `v*` tag push. Three artefacts ship with each release:

| Artefact | Platform | Built by | Purpose |
|---|---|---|---|
| `PawPoller-windows-x64.zip` | Windows | PyInstaller `--onedir` + `Compress-Archive` | Portable install — extract anywhere, run `PawPoller.exe` |
| `PawPoller-Setup-{ver}.exe` | Windows | Inno Setup 6 (`installer/PawPoller.iss`) | Single-file installer with proper uninstaller in Add/Remove Programs. Per-user install by default (no UAC); optional Start Menu / desktop shortcuts / autostart task |
| `PawPoller-{ver}-x86_64.AppImage` | Linux | PyInstaller + `installer/build-appimage.sh` (appimagetool) | Single-file distro-independent build. Runs on Ubuntu 22.04+ / Fedora 37+ / Debian 12+ / Arch. GLIBC 2.35 floor for forward-compat. |

**Windows installer** (`installer/PawPoller.iss`): Inno Setup 6 script.
Fixed AppId GUID so reinstalls upgrade in place. AppVersion injected
at build time via `iscc /DMyAppVersion="..."` so there's no
duplicated version string. Per-user install model writes a HKCU
`Run` value when "Run on Windows startup" task is ticked; uninstaller
offers (default No) to delete `%APPDATA%\PawPoller\` so most uninstalls
preserve user data. Best-effort `taskkill /F /IM PawPoller.exe` runs
before file deletes to avoid "in use" errors.

**Linux AppImage** (`installer/build-appimage.sh`): builds an `AppDir`
from PyInstaller's `dist/PawPoller/` tree (the `--onedir` output, with
PyInstaller's bundled `_internal/` libs):

```
PawPoller.AppDir/
├── AppRun                       # launcher script; exec's usr/bin/PawPoller/PawPoller
├── PawPoller.desktop            # required by AppImage spec
├── PawPoller.png                # icon (sourced from assets/tray_icon.png)
├── .DirIcon -> PawPoller.png    # AppImage runtime reads this for previews
└── usr/bin/PawPoller/           # entire dist/PawPoller/ tree
    ├── PawPoller                # the bundled binary
    └── _internal/               # PyInstaller's bundled libs (Qt6, WebEngine, WeasyPrint, …)
```

`appimagetool` then packages the AppDir into a single executable
AppImage with the AppImage runtime prepended. Script auto-downloads
appimagetool from AppImageKit's continuous build if not on PATH, and
falls back to `--appimage-extract-and-run` when libfuse2 is missing
(rare on dev machines, but happens on minimal CI runners — see the
"libfuse2" line in `build.yml`).

**CI structure** (`.github/workflows/build.yml`):

- `build-windows` job on `windows-latest`: PyInstaller → zip →
  Inno Setup → uploads zip + installer + attaches both to the release.
- `build-linux` job on `ubuntu-22.04`: apt-installs WeasyPrint deps,
  libnotify-bin, Qt6 platform plugin deps (libgl1, libegl1, libxcb-*,
  libxkbcommon-x11-0, libdbus-1-3), QtWebEngine deps (libnss3,
  libxcomposite1, libxdamage1, libxrandr2, libasound2), and libfuse2.
  Runs PyInstaller, then `build-appimage.sh`, then uploads + attaches
  the AppImage.
- `test` job on `ubuntu-latest`: runs the pytest suite (91 tests) +
  py_compile sanity check.

All three jobs run in parallel on tag push; the release ends up with
all three artefacts attached. Marketing site (`site/`) is deployed
separately by Cloudflare Pages on every push to master that touches
`site/**` (no CI step needed — CF Pages auto-builds).

### In-app Uninstall (`uninstall.py`)

Settings → General → Danger zone → "Uninstall PawPoller" button. Closes
the cleanup gap for portable-zip and AppImage installs (Inno Setup
already had a proper uninstaller via Add/Remove Programs).

**Install-type detection** (`uninstall.detect()`):

```python
class InstallType(Enum):
    WINDOWS_INSTALLER = "windows_installer"  # Inno — has unins000.exe
    WINDOWS_PORTABLE  = "windows_portable"   # zip extract
    LINUX_APPIMAGE    = "linux_appimage"     # APPIMAGE env var set
    DEV               = "dev"                # `python main.py`
    UNKNOWN           = "unknown"
```

Detection rules:
- `unins000.exe` next to `sys.executable` → `WINDOWS_INSTALLER`
- frozen but no `unins000.exe` and `sys.platform == "win32"` → `WINDOWS_PORTABLE`
- `os.environ.get("APPIMAGE")` set → `LINUX_APPIMAGE`
- not frozen → `DEV`

`detect()` is pure (no side effects), used by the
`GET /api/settings/uninstall/plan` endpoint to populate the confirm
dialog with the paths the cleanup would touch.

**Cleanup flow** (`execute()`):

1. Synchronous: `config.set_run_on_startup(False)` removes the
   per-OS autostart entry (HKCU registry / XDG `.desktop`).
2. Synchronous: `keyring.delete_password("PawPoller", "vault_key")`
   removes the vault encryption key from Windows Credential Manager /
   Secret Service. Best-effort — swallows exceptions.
3. Async: builds and spawns a detached cleanup script per install type.

**Per-OS scripts**:

| Install type | Script | Notes |
|---|---|---|
| `WINDOWS_INSTALLER` | `.bat` that runs `unins000.exe /SILENT` | Delegates to Inno's uninstaller — same code path as Windows Search → Uninstall. Inno's own `[UninstallRun]` taskkill + `[Code] CurUninstallStepChanged` data-dir prompt still fires |
| `WINDOWS_PORTABLE` | `.bat` with `taskkill /F /IM PawPoller.exe` + `rmdir /S /Q` on install dir + data dir | Defensive `if exist "{install}\PawPoller.exe"` guard to prevent a misconfiguration from `rmdir`ing C:\ |
| `LINUX_APPIMAGE` | `.sh` with `pkill -f PawPoller` + `rm -f "$APPIMAGE"` + `rm -rf` data dir + autostart `.desktop` | Reads the AppImage path from the `APPIMAGE` env var (set by the AppImage runtime) |
| `DEV` | Cleans data + autostart only | Refuses to delete the source tree |

Scripts all wait 3s before touching files so the parent PawPoller
process can release file locks. Self-delete on completion via
`del "%~f0"` / `rm -f -- "$0"`.

**Detached spawn**:
- Windows: `os.startfile(script_path)` — runs detached from our process.
- Linux: `subprocess.Popen(["bash", script], stdin/out/err=DEVNULL,
  start_new_session=True)` — same idea.

**Server shutdown**: after the script is spawned, the endpoint
schedules `os._exit(0)` via `asyncio.get_event_loop().call_later(2.0,
…)` so the JSON response flushes cleanly before the process dies.

**Windows Search / Apps & features integration**: this is automatic
once a user installs via `PawPoller-Setup-*.exe`. Inno Setup writes
`HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\{AppId}_is1`
with `UninstallString` = `unins000.exe`. All three Windows uninstall
surfaces (Start Menu search context, Settings → Apps & features,
Control Panel → Programs and Features) read this key. The in-app
Uninstall button delegates to the same `unins000.exe` so behaviour is
consistent regardless of where the user triggers it.

**Known limitations**:
- Users uninstalling via Windows Search → Uninstall (not the in-app
  button) bypass the keyring cleanup — leaves a stray 64-char hex
  value in Windows Credential Manager. Tiny, no security impact
  (the encrypted vault file is gone too). Same gap on Linux for
  users who just `rm` the AppImage.
- macOS uninstall raises `RuntimeError("Uninstall not yet supported
  on darwin")` — lands with the macOS native app.

### Auto-Update (`updater.py` — Desktop Only)

Version checking against GitHub Releases:
```python
GITHUB_REPO = "knaughtykat01-prog/PawPoller"

async def check_for_update():
    resp = await http.get(f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest")
    latest = resp.json()["tag_name"].lstrip("v")
    if _version_newer(latest, config.APP_VERSION):
        return {"available": True, "version": latest, "download_url": asset["browser_download_url"]}
```

Download uses streaming (8KB chunks) to avoid memory bloat. 120-second
timeout for slow connections. Supports authenticated requests via
`github_pat` token for private repos.

**Per-OS asset matching** (`_pick_update_asset`): the in-app updater
is for incremental upgrades of an already-installed app, so it picks:

- **Linux** → `*-x86_64.AppImage` (in-place replace via `$APPIMAGE`).
- **Windows** → `*.zip` (extract + robocopy mirror into the install
  dir). The `*-Setup.exe` installer is intentionally NOT chosen —
  that's for fresh installs from the website / Releases page.

**Per-OS apply path**:

- **Windows** (`apply_update`): extracts the zip to a temp dir,
  resolves the mirror source via `_resolve_source_dir`, then writes a
  `_update.bat` that sleeps 2s, runs `robocopy <source> <install-dir>
  /MIR /XD data logs /R:2 /W:2`, restarts the .exe, and self-deletes.
  `os.startfile` launches the .bat detached.

  > **PACKAGING INVARIANT (learned the hard way, 2.162.1).** `robocopy
  > /MIR` makes the install dir *identical* to its source — it also
  > **deletes** install-dir entries absent from the source. So the
  > source MUST be the tree that directly holds `PawPoller.exe` +
  > `_internal/`. The CI zip is built **flat** (`ZipFile.
  > CreateFromDirectory` → contents at the root, NOT wrapped in a
  > `PawPoller/` folder); `Compress-Archive -Path PawPoller` produced
  > that wrapper, and mirroring the extract-root then **nested** the new
  > build under `install\PawPoller\` while **purging** the real
  > `install\_internal\` → a launch-time `schema.sql` FileNotFound.
  > `_resolve_source_dir` is the belt-and-braces: it descends into a
  > lone top-level wrapper dir, uses a flat payload as-is, and **raises
  > before `/MIR`** if the resolved source has no `.exe` — never purge a
  > working install from a malformed payload. `/R:2 /W:2` bounds
  > robocopy's retries (default `/R:1000000 /W:30` would hang the whole
  > update on one locked file). Keep the zip flat **and** the resolver;
  > either alone is a single point of failure.
- **Linux** (`_apply_update_linux`): reads the current AppImage path
  from the `APPIMAGE` env var (standard, set by the AppImage runtime),
  writes a `_update.sh` that sleeps 2s, `mv -f`'s the new file over
  the current path, chmod +x, exec's the new AppImage. Spawned
  detached via `subprocess.Popen(stdin/stdout/stderr=DEVNULL,
  start_new_session=True)`.

Both paths refuse to run in dev mode (`getattr(sys, "frozen", False)
== False`) — auto-updating a venv would clobber the developer's
working tree.

---

## 12. Credential Flow

### Desktop Mode

```
User opens Settings page in dashboard
    │
    ▼
Fills in platform credentials (e.g. FA cookies, SF email/password)
    │
    ▼
Frontend calls POST /api/credentials with credential data
    │
    ▼
Route handler calls config.save_settings(data)
    │  Acquires _settings_lock
    │  Reads current settings.json
    │  Overlays new credential keys
    │  Writes to temp file → os.replace() (atomic)
    ▼
settings.json updated on disk
    │
    ▼
Next poll cycle: poller calls config.get_settings()
    │  Acquires _settings_lock
    │  Reads fresh settings.json
    │  Gets updated credentials
    ▼
Platform client uses new credentials for HTTP requests
```

**"Don't remember me" mode**: If the user logs in without checking "remember me", credentials are stored in `_session_credentials` (in-memory dict in `routes/api.py`) rather than written to settings.json. They survive for the lifetime of the process but are lost on restart.

### Server/Docker Mode

```
.env file on host
    │
    ▼
docker-compose.yml: env_file: .env
    │
    ▼
Container environment variables
    │
    ▼
server.py startup: _seed_settings_from_env()
    │  Reads each _ENV_TO_SETTINGS mapping
    │  Only writes if the corresponding settings field
    │  is missing/empty — never overwrites existing values
    │  Special handling: telegram_enabled parsed as boolean
    ▼
settings.json written to /app volume (persistent)
    │
    ▼
Pollers read via config.get_settings() each cycle
```

### Per-Platform Auth Matrix

| Platform | Auth Method | Settings Keys | How to Obtain |
|----------|-----------|--------------|---------------|
| Inkbunny | Username/password → SID | `username`, `password` | IB account credentials |
| FurAffinity | Browser cookies | `fa_username`, `fa_cookie_a`, `fa_cookie_b` | Export cookies 'a' and 'b' from browser DevTools |
| Weasyl | API key | `ws_api_key` | Generate at weasyl.com/control/apikeys |
| SoFurry | Email/password → session | `sf_username` (email!), `sf_password`, `sf_display_name` | SF account email + profile handle |
| SquidgeWorld | User/pass + CSRF | `sqw_username`, `sqw_password`, `sqw_target_user` | Login account + tracked user's username |
| AO3 | User/pass + CSRF **or** session cookie | `ao3_username`, `ao3_password`, `ao3_target_user`, `ao3_session_cookie` (optional, takes precedence) | Login account + tracked user. **Cookie mode** (2.18.8+): paste `_otwarchive_session` from your browser to bypass the per-IP login throttle — recommended on datacenter/server deployments |
| DeviantArt | App client-credentials (OAuth2) | `da_client_id`, `da_client_secret`, `da_target_user` | Register a DA app (Confidential) at the developer portal; use its client_id/secret. (Legacy `da_cookie` still works as a fallback when no app credentials are set.) |
| Wattpad | None (public) | `wp_target_user` | Just the username to track |
| Itaku | None (public) | `ik_target_user` | Just the username to track |
| Bluesky | App password → JWT | `bsky_identifier`, `bsky_app_password` | Settings → App Passwords on bsky.app |
| X/Twitter | Browser cookies | `tw_auth_token`, `tw_ct0`, `tw_target_user` | F12 → Application → Cookies on x.com |

**Note on separated login vs target user**: For AO3 and SquidgeWorld, the login credentials (username/password) are for authenticating with the site, while `target_user` is the profile being tracked. These can be different accounts — you might log in with your own account but track stats for a different user.

---

## 13. Troubleshooting & Known Issues

### Diagnostic Tools

**`test_sf_proxy.py`** — SoFurry proxy diagnostic script. Tests the CF Worker proxy by performing a full login + gallery fetch sequence. Useful for debugging SF proxy issues in isolation. Requires environment variables:
```
SF_USERNAME=your@email.com
SF_PASSWORD=your_password
SF_DISPLAY_NAME=YourProfileHandle
CF_WORKER_URL=https://your-worker.workers.dev
CF_WORKER_KEY=your-secret-key
```
Run: `python test_sf_proxy.py`

**`test_sf_direct.py`** — SoFurry direct login + cookie persistence test. Tests direct login (no proxy) and validates that session cookies can be exported, persisted, and restored. Confirms the `remember_web_*` cookie is set with `"remember": "on"`. Reads credentials from `settings.json`. Run: `python test_sf_direct.py`

**Debug proxy logging** — Set `PAWPOLLER_DEBUG_PROXY=1` to enable verbose logging in `polling.cf_proxy` logger:
```bash
# Docker
docker compose exec pawpoller env PAWPOLLER_DEBUG_PROXY=1 python server.py

# Development
PAWPOLLER_DEBUG_PROXY=1 python server.py
```
Logs every request URL, response status, Set-Cookie headers, stored cookie names, and session cookie contents. Extremely noisy.

**Poll log audit trail** — Every poll cycle is recorded in the `{platform}_poll_log` table:
```sql
SELECT started_at, status, duration_seconds, error_message,
       submissions_found, snapshots_inserted, new_comments_found
FROM poll_log ORDER BY started_at DESC LIMIT 10;
```
Also viewable via `GET /api/poll_log` or the Telegram `/status` command.

### Common Problems & Solutions

| Problem | Cause | Solution |
|---------|-------|----------|
| SF login fails | Using username instead of email | SoFurry login requires the **email address**, not the display name. Set `sf_username` to your email. |
| SF login works locally but fails on server | Datacenter IP blocked | Configure CF Worker proxy (`CF_WORKER_URL`, `CF_WORKER_KEY`). SF blocks non-residential IPs. The poller auto-detects: if `cf_worker_url` is set, it uses the proxy; otherwise it uses direct login with cookie persistence. |
| SF "restored session is valid" then fails | Saved cookies expired | The `remember_web_*` cookie lasts ~30 days. After expiry, `check_session()` fails and the app does a fresh login automatically. No manual action needed. |
| FA polls return no data | Cookies expired | FA cookies (`cookie_a`, `cookie_b`) expire periodically. Re-export them from browser DevTools → Application → Cookies. |
| FA polls return 403 | Cookies incomplete | Both `cookie_a` AND `cookie_b` are required. Check both are set. |
| DA polls fail / no data | Bad or missing app credentials | Check `da_client_id` / `da_client_secret` (register a Confidential DA app) and that `da_target_user` is the correct tracked username. The official OAuth2 API works from any IP (2.47.0), so the datacenter-IP/CF-proxy fix no longer applies to DA polling. |
| DA token request 404 | Wrong token endpoint | The token endpoint is `https://www.deviantart.com/oauth2/token`, **not** `/api/v1/oauth2/token` (which 404s). Applies to the client-credentials fetch. |
| AO3 rate limited (429) | Polling too fast | Increase poll interval. In `main.py`, increase `ao3_poll_interval_minutes`. In `server.py`, increase `poll_interval_minutes` (applies to all platforms). AO3 is volunteer-run with limited infrastructure. Default 60 minutes is usually fine. |
| WS API returns 401 | Invalid API key | Generate a new key at weasyl.com/control/apikeys. Keys don't expire but can be revoked. |
| Settings file corrupt/empty | Previously: crash during write | **Fixed**: atomic writes (temp file + `os.replace()`) now prevent this. If corrupt, delete `settings.json` to reset — it will be recreated with empty defaults on next startup. |
| Poller thread silently stops | Previously: swallowed exception | **Fixed**: exceptions now logged at `logger.debug()` level. Run with `logging.basicConfig(level=logging.DEBUG)` or check the log file to see the actual error. |
| Dashboard shows no data after setup | First poll still running | Check poll progress: `GET /api/poll/progress`. The first poll may take several minutes for platforms with many submissions. |
| Docker container unhealthy | Uvicorn crashed or hung | Check `docker compose logs pawpoller` for errors. The HEALTHCHECK pings `/api/health` every 60s; 3 failures = unhealthy. |
| SqW login fails with challenge | Anubis bot protection | The client automatically solves Anubis SHA-256 challenges. If it fails, the challenge format may have changed — check logs for details. |
| Telegram bot not responding | Bot not polling updates | Verify `telegram_enabled=true`, `telegram_bot_token`, and `telegram_chat_id` are set. Check bot thread is alive in logs. Send `/start` to your bot. |
| Proxy returns 403 | Mismatched proxy key | Ensure `CF_WORKER_KEY` in PawPoller matches `PROXY_SECRET` in Cloudflare Worker settings exactly. |
| BSKY login fails | Wrong credential type | Use an **App Password** (Settings → App Passwords on bsky.app), not your main account password. |
| BSKY no posts found | Wrong identifier | `bsky_identifier` should be your handle (e.g. `user.bsky.social`) or DID (`did:plc:...`). |
| TW polls return 403 | Cookies expired/invalid | Re-export `auth_token` and `ct0` cookies from browser DevTools → Application → Cookies on x.com. |
| TW rate limited (429) | Polling too fast | X is aggressive about rate limiting. In `main.py`, increase `tw_poll_interval_minutes`. In `server.py`, increase `poll_interval_minutes`. Default 2s inter-request delay + 60s backoff. |
| TW GraphQL fails | Query IDs rotated | As of 2.105.0 the poll path prefers **gallery-dl** (`clients/tw/gallerydl.py`), which tracks X's API for us — `pip install -U gallery-dl` usually fixes a broken scrape. Only the GraphQL **fallback** (and posting) still uses hardcoded query IDs; if gallery-dl is unavailable and logs show 404s, update the IDs in `clients/tw/client.py`. Check `/api/tw/auth/status` → `poll_backend` to see which path is live. |

### Known Limitations (Not Fixed)

**Architectural**:
- **No connection pooling**: Each poll cycle creates new HTTP client instances rather than reusing connections. This adds TLS handshake overhead but simplifies credential rotation.
- **No dashboard request rate limiting**: The REST API has brute-force protection on auth (10 attempts/5min lockout) but no per-endpoint request throttling. A denial-of-service against the dashboard is possible on exposed servers.
- **Daemon threads don't await shutdown**: Pollers are killed mid-execution when the app exits. WAL mode mitigates database corruption risk, but in-progress API calls are abandoned without cleanup.
- **No websocket push for dashboard**: The frontend polls `GET /api/poll/progress` on a timer. Real-time updates would require WebSocket support.

**Code quality**:
- **Module-level credential caching**: `config.py` reads some credentials at import time (`INKBUNNY_USERNAME`, `FA_COOKIE_A`, etc.). If credentials change at runtime, a restart is needed for these cached values. Pollers use `get_settings()` fresh each cycle, so this mainly affects the initial IB client setup.
- **Hardcoded spam filter**: FA watcher spam patterns (`_SPAM_KEYWORDS`, `_ALPHANUM_SOUP`) are hardcoded regexes rather than configurable via settings.
- **Notification code duplication**: Each platform's poller has its own notification-sending code (Windows toast + Telegram). A shared notification dispatcher would reduce ~200 lines of near-identical code.
- **No retry/backoff for transient failures**: If a platform API returns a 500 or times out, the entire poll cycle fails. A retry with exponential backoff would improve resilience.

### External API Endpoints Called

| Service | Endpoint | Client | Purpose |
|---------|----------|--------|---------|
| Inkbunny API | `/api_login.php` | `clients/ib/client.py` | Authentication |
| | `/api_userrating.php` | | Unlock content ratings |
| | `/api_search.php` | | Gallery discovery |
| | `/api_submissions.php` | | Batch detail fetch |
| | `/api_submissionfavingusers.php` | | Faving user lists |
| Inkbunny Web | `/login.php`, `/login_process.php` | | Web auth for scraping |
| | `/s/{id}` | | Comment HTML scraping |
| | `/usersviewall.php?mode=watched_by` | | Watcher list scraping |
| FAExport | `/user/{u}/gallery.json` | `clients/fa/client.py` | Gallery listing |
| | `/submission/{id}.json` | | Submission detail |
| | `/submission/{id}/comments.json` | | Comment thread |
| | `/user/{u}.json` | | Profile (spam check) |
| | `/user/{u}/watchers.json` | | Watcher list |
| Weasyl API | `/api/whoami` | `clients/weasyl/client.py` | Validate API key |
| | `/api/users/{u}/gallery` | | Gallery (cursor pagination) |
| | `/api/submissions/{id}/view` | | Submission detail |
| SoFurry | `/login` (GET/POST) | `clients/sf/client.py` | CSRF auth flow |
| | `/u/{u}/gallery` | | Gallery HTML scraping |
| | `/ui/submission/{id}` | | JSON metadata |
| | `/s/{id}` | | Stats HTML scraping |
| | `/u/{u}/followers` | | Follower list |
| AO3 | `/users/login` (GET/POST) | `clients/ao3/client.py` | CSRF auth flow |
| | `/users/{u}/works` | | Works listing |
| | `/works/{id}?view_adult=true` | | Work detail + stats |
| DeviantArt | `https://www.deviantart.com/oauth2/token` | `clients/da/client.py` | Client-credentials token (NOT `/api/v1/oauth2/token`) |
| | `/api/v1/oauth2/gallery/all` | | Gallery enumeration (official API) |
| | `/api/v1/oauth2/deviation/metadata?ext_stats=true` | | Per-deviation stats (≤10 ids/call) |
| | `/_napi/da-user-profile/api/gallery/contents` | | Legacy cookie fallback — gallery listing |
| | `/_napi/shared_api/deviation/extended_fetch` | | Legacy cookie fallback — deviation detail |
| | `/{u}/gallery` | | Legacy cookie fallback — HTML scrape |
| Wattpad API | `/api/v3/users/{u}/stories/published` | `clients/wp/client.py` | Story listing |
| Itaku API | `/api/user_profiles/{u}/` | `clients/ik/client.py` | User resolution |
| | `/api/gallery_images/` | | Content discovery |
| Bluesky AT Proto | `com.atproto.server.createSession` | `clients/bsky/client.py` | JWT authentication |
| | `com.atproto.server.refreshSession` | | Token refresh |
| | `app.bsky.feed.getAuthorFeed` | | Post discovery |
| | `app.bsky.feed.getPosts` | | Batch post details |
| | `app.bsky.actor.getProfile` | | Session validation |
| X/Twitter GraphQL | `/i/api/graphql/.../UserByScreenName` | `clients/tw/client.py` | User ID resolution |
| | `/i/api/graphql/.../UserTweets` | | Tweet listing |
| | `/i/api/graphql/.../TweetResultByRestId` | | Tweet detail |
| Telegram | `/bot{token}/getUpdates` | `polling/telegram_bot.py` | Long-poll commands |
| | `/bot{token}/sendMessage` | `polling/telegram.py` | Send notifications |
| GitHub | `/repos/{owner}/{repo}/releases/latest` | `updater.py` | Version check |
| CF Worker | `/{worker-url}` | `polling/cf_proxy.py` | Proxy transport |
| **Posting Module — Upload/Edit Endpoints** | | | |
| Inkbunny API | `/api_upload.php` | `posting/platforms/inkbunny.py` | File upload (multipart) |
| | `/api_editsubmission.php` | | Edit metadata, tags, ratings, visibility |
| FurAffinity | `/submit/` | `posting/platforms/furaffinity.py` | Step 1: scrape hidden key |
| | `/submit/upload` | | Step 2: multipart file + key upload |
| | `/submit/finalize` | | Step 3: title, desc, tags, rating |
| | `/controls/submissions/changeinfo/{id}/` | | Edit metadata |
| | `/controls/submissions/changestory/{id}/` | | Replace file |
| Weasyl | `/submit/literary` | `posting/platforms/weasyl.py` | Literary submission (multipart) |
| | `/edit/submission/{id}` | | Edit existing submission |
| SoFurry | `/ui/submission` (PUT) | `posting/platforms/sofurry.py` | Create empty submission |
| | `/ui/submission/{id}/content` (POST) | | Upload file content |
| | `/ui/submission/{id}` (POST) | | Set metadata + publish |
| SquidgeWorld | `/works` (POST) | `posting/platforms/squidgeworld.py` | Create new work |
| | `/works/{id}` (PATCH) | | Edit work metadata |
| | `/works/{id}/chapters/{ch}` (PATCH) | | Edit chapter content |
| AO3 (OTW posting) | `/works` (POST) | `posting/platforms/ao3.py` | Create new work |
| | `/works/{id}` (PATCH) | | Edit work metadata |
| | `/works/{id}/chapters/{ch}` (PATCH) | | Edit chapter content |
| | `/works/{id}/navigate` (GET) | | Get chapter IDs |
| Bluesky AT Proto | `com.repo.createRecord` | `posting/platforms/bluesky.py` | Create post record |
| | `com.repo.uploadBlob` | | Upload image blob |

---

## 14. Posting Module

### Overview

The posting module enables PawPoller to upload stories to 9 platforms, edit existing submissions (where the platform supports it), track what has been posted where, and detect when local story files have changed since the last upload. It is the reverse complement to the polling system: polling reads stats *from* platforms, posting pushes content *to* them.

Supported platforms for posting:

| Platform | Poster | Auth Method | Post | Edit | File Replace | Requires |
|----------|--------|------------|:----:|:----:|:------------:|----------|
| Inkbunny | `InkbunnyPoster` | Username/password → SID | Yes | Yes | Yes | any |
| FurAffinity | `FurAffinityPoster` | Cookie a + Cookie b | Yes | Yes | Yes | desktop |
| Weasyl | `WeasylPoster` | API key | Yes | Yes | No | any |
| SoFurry | `SoFurryPoster` | Email/password + CSRF | Yes | Yes | Yes | any |
| SquidgeWorld | `SquidgeWorldPoster` | Author user/pass + CSRF | Yes | Yes | Yes | any |
| AO3 | `AO3Poster` | Username/password OR session cookie | Yes | Yes | Yes | any |
| DeviantArt | `DAPoster` | OAuth2 access token | Yes | Yes (limited) | No | any |
| Itaku | `ItakuPoster` | API token | Yes | No | No | any |
| Bluesky | `BlueskyPoster` | App password → JWT | Yes | No* | No | any |

*Bluesky / Itaku do not support in-place editing — delete + repost loses engagement so the matrix treats them as post-only platforms.

**Wattpad note**: `wp` appears in tag-parsing paths (`story_reader.py`) but
has no poster implementation; the `wp` column never appears in the
publish matrix. Treat as a planned-but-unbuilt path.

FurAffinity requires `desktop` mode because FA blocks datacenter IP ranges. When a server-mode post to FA fails, the scheduler automatically queues it for desktop pickup.

**Cross-reference**: §15 documents the v2.21.0 Per-Cell Publish
Controls (Set URL manually, Forget publication, Cancel scheduled bulk)
which act directly on rows in this module's `publications` registry
via `database/posting_queries.py:delete_publication`,
`update_publication_url`, and `cancel_all_for(chapter_index=...)`.

### Architecture

The posting module lives in the `posting/` directory alongside the existing `polling/`, `database/`, and `routes/` directories. It reuses the existing platform API clients (e.g. `InkbunnyClient`, `FAClient`) by adding upload/edit methods.

```
posting/
├── manager.py              Orchestrator: story_reader → poster → publications DB
├── scheduler.py            Daemon thread: checks posting_queue every 60s
├── story_reader.py         Reads archive → builds StoryUploadPackage objects
├── sync.py                 Retroactive claim + change detection
├── importer.py             Pulls submissions from platforms into local archive
├── generate_story_json.py  CLI: generates story.json from legacy data
└── platforms/
    ├── base.py             PlatformPoster ABC + data classes
    ├── inkbunny.py         InkbunnyPoster
    ├── furaffinity.py      FurAffinityPoster
    ├── weasyl.py           WeasylPoster
    ├── sofurry.py          SoFurryPoster
    ├── squidgeworld.py     SquidgeWorldPoster
    ├── ao3.py              AO3Poster — chapter-aware OTW Archive flow
    ├── deviantart.py       DAPoster — OAuth2 + plain text
    ├── itaku.py            ItakuPoster — art-gallery primary use
    └── bluesky.py          BlueskyPoster
```

**Data flow**:
```
User (Dashboard/Telegram/API)
    │  "Upload Extra_Credit to IB + SF"
    ▼
PostingManager (manager.py)
    │  1. story_reader.load_story("Extra_Credit")
    │  2. story_reader.build_package(story, chapter, platform)
    │  3. poster.validate(package)
    │  4. poster.post(package)
    ▼
Platform Poster (platforms/inkbunny.py, etc.)
    │  HTTP upload to platform API
    ▼
PostingManager
    │  5. posting_queries.upsert_publication(...)
    │  6. posting_queries.log_posting_action(...)
    ▼
Publications table (database)
```

**Thread model**: The posting scheduler runs as Thread 15 in `main.py` (desktop) and as the 4th thread in `server.py` (headless). It creates its own asyncio event loop following the same pattern as the pollers. On startup it detects the runtime mode (desktop/server) by checking whether `pywebview` is importable — this determines which queue items it can process.

### Story Archive

Stories are read from the `m_x/Archives/Complete_Stories/` directory (configurable via `posting_story_archive_path` setting). Each story folder has this structure:

```
Extra_Credit/
├── story.json                    # Story metadata (preferred source)
├── Markdown/MASTER.md            # Canonical source text
├── Tags/tags_upload.txt          # Per-platform tag lists
├── Chapters/
│   ├── split_manifest.json       # Chapter structure + file map
│   ├── BBCode/                   # Chapter files for IB/WS
│   ├── SoFurry_HTML/             # Chapter files for SF
│   └── PDF/                      # Chapter files for FA
├── BBCode/                       # Full-story BBCode
├── HTML/                         # Full-story HTML variants
├── PDF/                          # Full-story PDF
├── SquidgeWorld/                  # SqW-specific HTML
└── Images/                       # Cover art, thumbnails
```

**story.json schema**: The preferred metadata source (generated by `generate_story_json.py`). Contains:
```json
{
    "title": "Hypnotic Claim",
    "author": "KnaughtyKat",
    "description": "Short blurb for IB/SF listings (1-2 sentences).",
    "summary": "Detailed summary for AO3/SqW (max 1250 chars, 3-5 sentences).",
    "rating": "explicit",
    "category": "F/M",
    "fandom": "Original Work",
    "warnings": ["Rape/Non-Con"],
    "characters": ["Maya (Original Female Character)", "Dmitri (Original Male Character)"],
    "relationships": ["Dmitri/Maya (Original Characters)"],
    "word_count": 9809,
    "chapters": 2,
    "tags": {
        "default": ["hypnosis", "mind_control", "tiger", "deer", ...],
        "sofurry": ["hypnosis", "mind_control", ...],       // max 97
        "inkbunny": ["hypnosis", "mind_control", ...],      // unlimited
        "weasyl": ["hypnosis", "mind_control", ...],        // unlimited
        "wattpad": ["hypnosis", "mindControl", ...]         // max 24, camelCase
    },
    "chapter_info": [
        {
            "index": 1,
            "title": "Part 1: The Seduction",
            "words": 6123,
            "description": "Chapter-specific description for per-chapter uploads.",
            "tags": {
                "default": ["hypnosis", "gym", "seduction", ...],   // subset of story tags
                "sofurry": ["hypnosis", "gym", "seduction", ...],   // max 97
                "wattpad": ["hypnosis", "gym", "seduction", ...]    // max 24
            }
        }
    ],
    "formats": { "bbcode": true, "html": true, "markdown": true, "squidgeworld": true },
    "platforms": {
        "inkbunny": { "format": "bbcode", "description_field": "story" },
        "sofurry": { "format": "sofurry_html", "category": 20 },
        "squidgeworld": { "format": "squidgeworld_html", "work_skin": "Skin Name" }
    },
    "images": { "cover": "Images/cover.png", "chapter_thumbnails": { "1": "Images/ch1.png" } }
}
```

**Per-chapter tags**: When `chapter_info[].tags` is present, `story_reader.build_package()` uses the chapter-specific tag list instead of the story-level tags. The fallback chain is: chapter tags → story tags → empty. This is essential for per-chapter platform uploads (FA posts each chapter separately with its own tags).

**Platform tag limits** (documented in `posting/references/platform_tag_limits.md`):
| Platform | Max Tags | Notes |
|---|---|---|
| Inkbunny | Unlimited | Comma-separated, underscores for spaces |
| FurAffinity | Unlimited | Space-separated |
| SoFurry | 97 | Comma-separated |
| Wattpad | 24 | camelCase, no underscores |
| DeviantArt | 30 | Array |
| SQW/AO3 | Unlimited | Freeform, comma-separated |

**SQW/AO3 archive warnings**: Choose Not To Use Archive Warnings, No Archive Warnings Apply, Graphic Depictions Of Violence, Major Character Death, Rape/Non-Con, Incest and/or Incestuous Relationship(s), Suicide/Suicidal Ideation, Underage.

**SQW/AO3 categories**: F/F, F/M, Gen, M/M, Multi, NB/F, NB/M, NB/NB, QPR, Vs./Antagonistic, Other. Relationship notation: `/` = romantic, `&` = platonic, `~` = queerplatonic, `vs` = antagonistic.

**Format file resolution** (`PLATFORM_FORMAT_MAP` in `story_reader.py`): Each platform has a priority-ordered list of format directories and glob patterns. The reader checks each in order and uses the first match:

| Platform | Priority 1 | Priority 2 | Priority 3 |
|----------|-----------|-----------|-----------|
| Inkbunny | `Chapters/BBCode/*.txt` | `BBCode/*_bbcode.txt` | — |
| FurAffinity | `PDF/*.pdf` | `Chapters/PDF/*.pdf` | — |
| Weasyl | `Chapters/BBCode/*.txt` | `BBCode/*_bbcode.txt` | `Markdown/MASTER.md` |
| SoFurry | `Chapters/SoFurry_HTML/*.html` | `HTML/*_Clean.html` | `HTML/*_sofurry.html` |
| SquidgeWorld | `SquidgeWorld/*.html` | `Chapters/SoFurry_HTML/*.html` | — |
| Bluesky | *(no file upload — uses description text)* | — | — |

> **Important (fixed 2026-04-08):** When `chapter_index == 0` (full-story request), `_resolve_format_file()` now skips any subdir whose path contains `Chapters/`. Without this guard, the loose `*.txt` glob on `Chapters/BBCode/` would match `Chapter_1_*_bbcode.txt` first and silently return chapter 1 instead of the full bulk file. The bug masqueraded as a successful upload because page-count verification still reported `pages=1`. See CHANGELOG 2.3.4.

**tags_upload.txt** (legacy fallback when story.json is missing): Multi-platform tag file parsed by `story_reader.py`. Format:
```
=== INKBUNNY ===
furry, wolf, college, romance

=== SOFURRY ===
furry, wolf, college, romance

=== PER-CHAPTER TAGS ===
Chapter 1: meeting, classroom
Chapter 2: tension, library
```

### Platform Posters

All posters extend the `PlatformPoster` abstract base class, which enforces a consistent interface: `post()`, `edit()`, `replace_file()`, `validate()`. The manager treats all platforms identically.

**Cover image upload**: All 4 platforms that support cover/thumbnail images are wired: IB (via `upload_submission(thumbnail_path=...)`), FA (via `changethumbnail` endpoint), SF (via `submission/{id}/content` cover slot), and WS (via `coverfile` multipart field). `story.json`'s `images.cover` path is resolved by `build_package()` with auto-detection fallback.

**`PostResult` dataclass**: Every operation returns:
```python
@dataclass
class PostResult:
    success: bool
    external_id: str = ""       # Platform's submission/post ID
    external_url: str = ""      # Direct URL to the submission
    error: str | None = None
    duration_seconds: float = 0.0
```

**`StoryUploadPackage` dataclass**: Everything needed to post one chapter to one platform:
```python
@dataclass
class StoryUploadPackage:
    story_name: str             # "Extra_Credit"
    chapter_index: int          # 0 = full story, 1+ = chapter number
    chapter_title: str          # "Chapter 1: First Day"
    platform: str               # "ib", "fa", "ws", "sf", "sqw", "bsky"
    title: str                  # Submission title
    description: str            # Body text / description
    tags: list[str]             # Platform-specific tag list
    rating: str                 # Platform-specific rating value
    file_path: str | None       # Absolute path to format file
    file_type: str              # "bbcode", "pdf", "html", "text"
    word_count: int
    thumbnail_path: str | None  # Cover image path (auto-detected from story root if story.json.images.cover empty)
    extra: dict                 # Platform-specific overrides
```

**`extra` dict conventions** (per-platform overrides set by callers, read by posters):
- `extra["draft"] = True` — Inkbunny: omit visibility on `edit_submission`, leaving the submission hidden. SquidgeWorld: equivalent to leaving the work in `/works/drafts`.
- `extra["visibility"]` — Inkbunny: explicit override (e.g. `"yes_nowatch"` for visible-without-notify-watchers). Wins over `draft`.
- `extra["categories"]`, `extra["warnings"]`, `extra["fandoms"]`, `extra["characters"]`, `extra["relationships"]` — SquidgeWorld/AO3 OTW Archive metadata fields.
- `extra["work_skin_title"]` — SquidgeWorld: title of the Work Skin to apply (auto-resolved by `SquidgeWorldPoster._ensure_work_skin()` from `story.work_skin_path`).

#### Inkbunny (`posting/platforms/inkbunny.py`)

**Auth**: Reuses `InkbunnyClient` with SID session caching (same as polling).

**Post flow**:
1. `ensure_session(cached_sid)` — restore or re-login
2. `upload_submission(file)` via `/api_upload.php` — multipart file upload, returns `submission_id`
3. `edit_submission(submission_id, title, desc, tags, ratings, visibility=yes)` via `/api_editsubmission.php` — sets metadata and makes visible

**Edit flow**: `edit_submission(existing_id, updated_fields)` — same endpoint, just updates.

**File replace**: Re-upload via `api_upload.php` targeting the existing submission.

**Rating mapping**: General → all rating tags "no"; Mature → `tag[2]="yes"` (Nudity - Nonsexual); Adult → `tag[4]="yes"` (Sexual Situations - Strong) + `tag[5]="yes"`.

**File type**: `story` field for the IB reading panel (BBCode text displayed in-browser).

**Rate limit**: 5 seconds minimum between consecutive posts.

**Draft mode**: Set `package.extra["draft"] = True` to omit the `visibility` parameter on `edit_submission`. IB defaults newly created submissions to hidden, so omitting visibility leaves them as drafts. You can flip later via the IB UI or another `edit_submission(visibility="yes")` call. `extra["visibility"]` overrides both modes (e.g. `"yes_nowatch"` for visible-without-notify).

**Single-bulk-file convention for chaptered stories**: For prose with multiple chapters, post **one submission with one BBCode file** (the full-story bulk file at `BBCode/<Story>_bbcode.txt`), not one page per chapter. Reasons:
1. IB's `story` field (the inline reading panel) is a single text blob — it can't show different content per page anyway
2. Page navigation on IB is for multi-image art, not chaptered prose
3. Per-page splits cause UI confusion — page 2 still shows chapter 1 in the reading panel

`build_package(story, chapter_index=0, platform="ib")` resolves to the full-story BBCode file automatically (after the 2026-04-08 fix to `_resolve_format_file` — see CHANGELOG 2.3.4).

**Tag limit (empirical, 2026-04-08)**: IB accepts at least **108 keywords** on a single submission. The historical 75-tag fear was wrong — no truncation needed. NSE Studying did see one duplicate silently dropped server-side (58 sent → 57 returned), so don't depend on exact counts being preserved.

**Thumbnail auto-detection**: `story_reader._load_from_story_json()` auto-detects thumbnails by globbing the story root for common patterns when `images.cover` is empty:
- `*_thumbnail_full_series.*`
- `*_thumbnail.*`
- `*_cover.*`
- `thumbnail.*` / `cover.*`

First match wins, restricted to png/jpg/jpeg/gif. The IB poster forwards `package.thumbnail_path` to `upload_submission(thumbnail_path=...)`, which uses IB's `replace=<file_id>` mechanism to attach the thumbnail to the uploaded file.

**Bulk-draft script**: `tests/bulk_inkbunny_drafts.py` shows the canonical pattern:
1. Cross-check `client.search_user_submissions()` against local story names — abort on overlap
2. For each missing story, `build_package(story, 0, "ib")` + `extra["draft"] = True`
3. `poster.post(package)` then verify via `get_submission_details()`
4. Record via `upsert_publication(status="draft")`

#### FurAffinity (`posting/platforms/furaffinity.py`)

**Auth**: Reuses `FAClient` with cookie a + cookie b. Validates cookies before every upload.

**Post flow** (3-step form scrape, same approach as PostyBirb):
1. `GET /submit/` — scrape hidden `key` input from form
2. `POST /submit/upload` — multipart: key + `submission_type` + file
3. `POST /submit/finalize` — urlencoded: key + title + description + tags + rating

**Edit flow** (`changeinfo` endpoint): `GET /controls/submissions/changeinfo/{id}/` — scrape form + key, scrape current values, merge in caller's overrides, POST back. Editable fields: title, description (`message` field), keywords, rating. Category/atype/species are scraped and preserved. **No CSRF key required for the POST** — only the `update=yes` hidden field.

**File replace flow** (`changestory` endpoint): `POST /controls/submissions/changestory/{id}/` with `data={"update":"yes"}` and `files={"newfile": <file>}`. **No CSRF key required.** Optional `MAX_FILE_SIZE` field is browser hint only. Form accepts: `.txt, .doc, .docx, .odt, .rtf, .pdf`. After POST, FA changes the download URL's internal version timestamp (e.g. `/stories/1775693326/...` → `/stories/1775693986/...`) — the filename slug stays the same, but the underlying file is the new one. Use this to confirm the replacement actually happened.

**Other edit endpoints** (not currently wired up but documented for future use):
- `POST /controls/submissions/changethumbnail/{id}/` — replace the thumbnail/cover image
- The metadata edit endpoint above (`changeinfo`) does NOT touch the source file or thumbnail — those are separate

**Rating mapping**: General → `"0"`, Adult → `"1"`, Mature → `"2"` (note: Adult=1, not 2 — counterintuitive).

**Constraints**: 10 MB max file size. 60-character title limit. 3 tag minimum, 500-character max tag string. Accounts need 11+ posts or CAPTCHA blocks.

**Rate limit (empirically confirmed 2026-04-09)**: The 70-second minimum applies to **new submissions only** (the upload endpoint), NOT to metadata edits or file replacements. Bulk-editing 7 existing submissions in this session at 3-second pacing produced no rate-limit errors. The `min_post_interval = 70` constant on `FurAffinityPoster` is correct as named — it applies to the post flow, not the edit/replace flows. The bulk edit script `tests/verify_fa_edit_existing.py` uses `FA_RATE_LIMIT_SECONDS = 3` for inter-edit pauses.

**Requires `desktop` mode**: FA blocks datacenter IPs. When a server-mode post fails, the manager auto-queues for desktop pickup.

**Bulk edit + file replacement helper** (`tests/verify_fa_edit_existing.py`): supports verify-only diffing (default) and `--apply` mode for actually performing edits. Optional `--update-file` flag also pushes the regenerated PDF via the changestory endpoint. `--skip-tags` and `--skip-rating` flags preserve existing values (path A — keep working SEO tags rather than overwriting with the build_package's atmospheric/character set). Hardcoded fallback list of known FA submissions so it works locally without needing the server's publications DB.

**Single-submission canary** (`tests/fa_changestory_canary.py`): minimal isolated test of the changestory endpoint flow. Reads current state, calls `replace_file()`, re-reads to confirm the download URL changed. Used to validate the `replace_file()` code path before wiring it into the bulk edit script.

#### SoFurry (`posting/platforms/sofurry.py`)

**Auth**: Reuses `SoFurryClient` with email/password + CSRF token.

**Network mode** — `SoFurryClient` is dual-mode:
- **Local desktop / residential IP**: direct httpx, with cookie persistence (`sf_session_cookies` saved across runs, ~30 day lifetime via `remember_web_*` cookie). Auto-detects: if `cf_worker_url` is empty in settings, uses direct mode.
- **GCP server / datacenter IP**: routed through the CloudflareProxyTransport because SF blocks datacenter IPs at the edge. Set `cf_worker_url` + `cf_worker_key` in settings to enable. Cookie persistence is disabled in proxy mode because CF Workers rotate egress IPs and SF pins sessions to the IP that performed login.

**Post flow** (3-step REST, very fast — typically 2-3 seconds end-to-end):
1. `PUT /ui/submission` — create empty submission, returns `submission_id`
2. `POST /ui/submission/{id}/content` — upload file content (multipart)
3. `POST /ui/submission/{id}` — set metadata (title, tags, rating, **privacy**)

**Privacy levels** (SF supports a real first-class draft state):
- `privacy=1` **Private** — owner-only, hidden from feeds and search, only the logged-in author can see it. Used for draft mode.
- `privacy=2` **Unlisted** — accessible by direct link but not in feeds or search.
- `privacy=3` **Public** — listed in feeds and search (default).

**Draft mode**:
- `package.extra["draft"] = True` → posts as `privacy=1` (Private). Same convention as IB / SQW / AO3.
- `package.extra["privacy"] = 1|2|3` (or `"private"/"unlisted"/"public"`) → explicit override (wins over draft).
- Default: `privacy=3` (Public). Preserves prior behaviour for callers that don't set anything.
- Post-flight verification: hits `/ui/submission/{id}` raw and confirms `privacy=1` server-side after a Private draft. Logs a warning on mismatch.

**Edit flow**: `POST /ui/submission/{id}` — update metadata. SF requires the **complete payload** on every edit (partial sends return 422), so the client fetches the **raw current JSON** first and overlays the caller's changes.

> **Critical bug history (fixed 2026-04-08):** an earlier version of `edit_submission` used `get_submission_detail()` to fetch current state. That helper strips `privacy`, `category`, `type`, and other write-only fields, so `current.get("privacy", 1)` always fell back to the default — and the default was **`1` (Private)**. Every edit silently downgraded the work to Private. Caught and rolled back during the SF retry session. The current code fetches raw JSON via `/ui/submission/{id}` directly and defaults to `privacy=3` if the field is somehow missing. Don't substitute `get_submission_detail()` back in.

**`SoFurryPoster.edit()` privacy semantics**:
- By default `privacy=None` is passed through to the client → preserves whatever the server currently has
- `extra["draft"] = True` → forces `privacy=1` on edit
- `extra["privacy"] = 1|2|3` → explicit override
- Use this to flip a draft to public later: `package.extra["privacy"] = 3` then `poster.edit(submission_id, package)`

**File replace**: `POST /ui/submission/{id}/content` — re-upload content.

**Rating mapping**: General → 0 (Clean), Mature → 10, Adult → 20.

**Max file size**: 512 KB for text content. The full-story `HTML/<Story>_Clean.html` files for all 13 local stories fit comfortably (largest is Velvet & Vice at 444 KB).

**Format files** (`PLATFORM_FORMAT_MAP["sf"]`, in priority order):
1. `Chapters/SoFurry_HTML/*.html` (per-chapter)
2. `HTML/*_Clean.html` (full-story body HTML — used for full-story posts after the `Chapters/` skip in `_resolve_format_file`)
3. `HTML/*_sofurry.html` (legacy)

#### Weasyl (`posting/platforms/weasyl.py`)

**Auth**: Reuses `WeasylClient` with API key in `X-Weasyl-API-Key` header.

**Post flow**: `POST /submit/literary` — multipart with file + metadata (title, description, tags, rating).

**Edit flow**: `GET /edit/submission/{id}` to scrape form, then `POST` with updated fields.

**File replace**: Not supported — Weasyl has no file-replace endpoint.

**Rating mapping**: General → 10, Mature → 30, Adult → 40.

**Max file size**: 10 MB.

#### SquidgeWorld (`posting/platforms/squidgeworld.py`)

**Auth**: Uses `SquidgeWorldClient` with **author credentials** (`sqw_author_username`/`sqw_author_password`), falling back to `sqw_username`/`sqw_password` if author credentials are not set. The posting module needs to log in as the work author (who has edit permissions), not the polling account.

**Post flow** (OTW Rails form):
1. Login + extract CSRF `authenticity_token`
2. `POST /works` with form data (title, fandom, tags, rating, content as HTML)
3. For multi-chapter works: POST additional chapters

**Edit flow**: `PATCH /works/{id}` for metadata; `PATCH /works/{id}/chapters/{ch_id}` for chapter content.

**HTML whitespace collapse**: SquidgeWorld (OTW software) collapses multiple blank lines into single spacing. Content must be pre-processed to preserve intentional formatting.

**Work Skin preservation**: If a story uses a custom AO3/SqW Work Skin for styled HTML, the poster preserves the `work_skin_id` field during edits.

**No file upload**: Content is pasted as HTML in the form field, not uploaded as a file.

#### Bluesky (`posting/platforms/bluesky.py`)

**Auth**: Reuses `BskyClient` with AT Protocol JWT session.

**Post flow**:
1. `ensure_logged_in()` — JWT session (login → refresh → check chain)
2. (Optional) `upload_blob(cover_image)` — upload image, max 1 MB
3. `create_post(text, embed=image, labels=nsfw)` via `com.repo.createRecord`

**NSFW labels**: Adult/Explicit → `["sexual"]`; Mature/Questionable → `["nudity"]`. Labels are AT Protocol self-labels that trigger content warnings in Bluesky clients.

**Edit flow**: Not supported. Bluesky does not allow in-place editing. The only option is delete + repost (loses all engagement). For story announcements this is acceptable.

**Post limit**: 300 graphemes max per post. Descriptions are truncated with `...` if needed.

**Bluesky is used for announcement posts**, not full story uploads. The poster generates a brief announcement text from the story description and optionally attaches a cover image.

#### AO3 (`posting/platforms/ao3.py`)

**Auth**: Reuses `AO3Client` with Rails CSRF form login. Same account for polling and posting (`ao3_username`/`ao3_password` = KnaughtyKat).

**Same OTW Archive software as SquidgeWorld** — identical form structure, HTML handling, and chapter editing. The `AO3Poster` is a near-mirror of `SquidgeWorldPoster` after the 2026-04-08 refactor.

**Post flow**:
1. **Resume detection** (2.22.9): look up publication for `(story_name, 0, "ao3")`. If `external_id` is set and `status != "posted"`, a previous run created the work but didn't finish — `existing_work_id` becomes the resume target. `probe_exists(work_id)` confirms the work still lives on AO3; if confirmed 404, clear the resume target and fall through to fresh create.
2. Read full StoryInfo from `story.json` (fandom, warnings, categories, characters, relationships)
3. Trim freeform tags to fit OTW's 75-tag total budget (`fandom + relationships + characters + freeform <= 75`)
4. `_ensure_work_skin(client, story)` — find or create the per-story Work Skin on AO3 from `SquidgeWorld/Work_Skin.css`, auto-refresh CSS on every post. Returns skin_id or `""` (no skin applied if no CSS file).
5. Chaptered detection (`story.total_chapters > 1`):
   - **Multi-chapter**: read chapter 1 body from `SquidgeWorld/Chapter_1_*.html`, create_work with ch1 content, then iterate ch2..N via `create_chapter(work_id, title=, content=, position=, publish=…)`. Chapter titles are stripped of `Chapter N:` / `Part N:` / `Prelude:` / `Epilogue:` prefixes via `_strip_chapter_prefix()` since AO3 auto-prefixes on display.
   - **Single-chapter / unsplit**: read `HTML/<Story>_Clean.html` (full-story body) and upload as one chapter.
6. **Resume branch**: if `existing_work_id` was set in step 1, skip `create_work`, call `get_chapter_ids(work_id)` to learn which chapters are already on AO3, build `already_created_chapter_indices`, and skip those in the chapter loop. Otherwise call `client.create_work(...)` normally.
7. **Checkpoint after create_work** (2.22.9): immediately `upsert_publication(status="partial", external_id=work_id)` so a chapter failure preserves the work_id handle for the next retry. Without this, the manager's `upsert_publication(external_id="")` on bubble-up would erase the only handle on the partial work, and the retry would create a duplicate draft.
8. **Publish-live wiring** (2.22.8): `publish_live = not bool(package.extra.get("draft", True))` reflects the user's "live" toggle from dashboard. Single-chapter: pass `publish=publish_live` directly to `create_work` (uses `post_without_preview_button=Post` when True). Multi-chapter: keep work as draft on `create_work` and pass `publish=publish_live` only on the LAST chapter — AO3's "Post Without Preview" on a chapter publishes the whole work. The `_verify_still_draft` safety check is bypassed when `publish_live=True`.
9. SAFETY: post-flight `is_work_published` check on create — only aborts on POSITIVE confirmation of publish (handles AO3 timeouts gracefully). Each `create_chapter` call is also safety-checked. On any chapter-loop exception, re-checkpoint before re-raising.
10. **Failure path** carries `external_id=work_id` in the returned `PostResult` so the manager's `upsert` preserves the resume handle.

**Edit flow** (metadata + per-chapter content):
1. `_ensure_work_skin` — refresh skin CSS before the metadata write so skin changes propagate.
2. `client.edit_work(id, title=, summary=, additional_tags=, warnings=, categories=, relationship=, characters=, fandom=, rating=, work_skin_id=, save_as_draft=True)` — **safe fetch-form overlay pattern**: GET `/works/{id}/edit`, extract every current `work[*]` field via `_extract_work_form_fields()`, overlay only the caller-supplied overrides, POST back with `save_button=Save As Draft`. Earlier versions sent only a handful of fields with `_method=patch` alone — AO3 returned 302 but silently dropped the update; the overlay pattern fixed this. `_append_if_missing()` fallback ensures fields are sent even when OTW renders the edit form differently than new-work.
3. `get_chapter_ids()` — scrape `/works/{id}/navigate`.
4. Multi-chapter edit: iterate AO3's existing chapters, pair with local by index, call `edit_chapter(title=stripped_title, content=local_ch_html)`. Appends any local chapters missing upstream via `create_chapter`. Single-chapter fallback pushes the Clean HTML blob to chapter 1.
5. `edit_chapter` also uses the safe fetch-form overlay — `content=None` preserves the existing body on AO3 so **title-only retitles don't re-upload content** (used by Metadata only flow).

**Metadata-only mode** (`package.extra["skip_content_refresh"] = True`):
Short-circuits chapter body re-upload but still iterates chapters to push title changes via `edit_chapter(title=, content=None)`. ~N extra GET+POST roundtrips for N chapters but no HTML body transfer. Triggered by the Publish Check "Metadata only" button or by passing `extras` through `manager.update_story()`.

**Critical OTW form fields** (any of these missing → silent validation failure):
- `work[author_attributes][ids][]` — pseud_id, REQUIRED, extracted from `/works/new` HTML on every post
- `work[archive_warning_strings][]` — plural array, hidden empty value first, then each warning. Default: `"No Archive Warnings Apply"`. Other valid: `"Choose Not To Use Archive Warnings"`, `"Graphic Depictions Of Violence"`, `"Major Character Death"`, `"Rape/Non-Con"`, `"Underage"`, `"Suicide/Suicidal Ideation"`, `"Incest and/or Incestuous Relationship(s)"`
- `work[category_strings][]` — plural array. Valid: `F/F`, `F/M`, `Gen`, `M/M`, `Multi`, `NB/F`, `NB/M`, `NB/NB`, `Other`, `QPR`
- `work[language_id]` — **numeric** ID; `1` = English. The previous code passed `"en"` (ISO code) which AO3 silently treated as blank → `"Language cannot be blank."` validation error.
- `work[wip_length]` — `"1"` for completed works (no WIP)
- `preview_button` / `post_without_preview_button` — `preview_button=Preview` lands the work in drafts (default); `post_without_preview_button=Post` publishes the work live. `create_work` and `create_chapter` both accept a `publish: bool` parameter (added 2.22.8) that swaps which button is sent. Multi-chapter posts keep the work draft on `create_work` and pass `publish=publish_live` only on the LAST `create_chapter` — AO3's "Post Without Preview" on a chapter publishes the entire work.

**Rating mapping**: General → "General Audiences"; Mature → "Mature"; Teen → "Teen And Up Audiences"; Adult/Explicit → "Explicit".

**HTML whitespace collapse**: `_collapse_html_whitespace()` joins multi-line `<p>` and `<div>` tags onto single lines to prevent OTW's auto-formatter from inserting `<br />` tags.

**Rate limiting**: 12 seconds between requests (`config.AO3_REQUEST_DELAY_SECONDS`, bumped 3 → 6 → 12 across 2.22.4/2.22.5 in response to AO3's post-AI-scraper tightening). Comfortably under the 1 req/sec sustained limit derived from AO3's Rack::Attack throttle (300 req / 300 s per IP). Bulk runs use a 10-second inter-post sleep on top of that — AO3 is volunteer-run with limited infrastructure.

**Throttle handling** (2.22.6 / 2.22.10):
- **Module-level backoff cache** — `_ao3_backoff_until_ts: float` in `clients/ao3/client.py`. Updated on every observed 429 (both GET via `_get_page` and POST via `_post_with_retry`). Process-local; resets on container restart.
- **Pre-flight gate** — `__init__` monkey-patches `self._http.get` and `self._http.post` so every raw call (chapter-form GET, work-skin POST, edit-page GET, etc.) checks the cache first. If `_ao3_backoff_until_ts > time.time()`, return a synthetic `429` response with `Retry-After` headers — no HTTP fired. This prevents the "request inside an active window counts toward the NEXT window's quota" failure mode that kept us perpetually throttled.
- **No in-method retries on 429** — `_get_page` returns `None` on 429 after recording; `_post_with_retry` raises `AO3ThrottledError(retry_after, url)`. Each failed post bubbles up to `manager.post_story`, which `_schedule_retry`s the work for after the window expires. The retry hits the pre-flight gate and short-circuits cleanly until the window drains.
- **Why no sleep-and-retry?** AO3's Rack::Attack throttle is a fixed-window counter (`Time.now.to_i / period`). Retry-After reports time until the current 300s window rolls over, but **requests inside the window count toward the NEXT window's quota**. Sleeping Retry-After then re-firing the same request at window rollover immediately eats the new window's budget — that's how we got stuck in 2.22.10 before this fix.
- **Poll orchestrator gate** — `run_ao3_poll_cycle` calls `get_backoff_until_ts()` and returns a stub `{skipped_reason: "throttled, Ns remaining"}` if a window is active, instead of enqueuing requests that will inevitably 429.

**Network reliability** (the one really painful difference from SQW):
- **AO3 from datacenter IPs** sees frequent `ReadTimeout` and `525 origin SSL handshake fail` responses — about 1 in 5 requests. The drafts page (`/users/<user>/works/drafts`) is particularly slow and times out the most.
- `_get_page()` retries 3 times with backoff on timeout/525. Hard 403/404 are not retried.
- **AO3 from residential IPs** is currently shielded with the "Shields are up!" CF JavaScript challenge — vanilla httpx cannot pass it. All AO3 testing must run from the GCP container.
- **AO3 routes direct from the GCP VM IP, not through the CF Worker proxy** (2.22.11). Cookie-mode auth (2.18.8) bypasses the login form, and routing through the shared CF Worker egress pool shares AO3's per-IP quota with every other Worker tenant. AO3 was reclassified `PROXY_OPTIONAL` — direct is the default; `ao3_use_cf_proxy: true` enables fallback through the Worker on block-like failure.
- The post-flight safety check uses **tri-state** state checks (`True | False | None`). When `is_work_in_drafts` returns `None` (fetch failed), the check trusts `preview_button` and logs a warning instead of triggering a destructive auto-delete. Without this, AO3 timeouts caused spurious aborts that tried (and failed) to delete healthy drafts.

**Format files** (`FORMAT_SPECS["ao3"]`, in priority order — flipped in v2.20.6):
| Priority | Path | Pattern |
|---|---|---|
| 1 | `SquidgeWorld/` | `*.html` (per-chapter, body-only — OTW Archive shape) |
| 2 | `HTML/` | `*_Clean.html` (full-story Clean HTML — legacy fallback for pre-SqW archives) |
| 3 | `Chapters/SoFurry_HTML/` | `*.html` (per-chapter SoFurry shape — last resort) |

v2.20.6 inverted the priority because AO3 is an OTW Archive site like
SquidgeWorld: the SqW per-chapter HTML carries the OTW chapter
markers, warning-icon glyph, and semantic anchors AO3 expects, while
Clean HTML is the generic shape for Inkbunny/Weasyl. Both the read
path (`_read_full_story_html`) and the publish-matrix package builder
(`FORMAT_SPECS["ao3"]`) now prefer SqW so the matrix's `file_path`
matches the actual POST body. For full-story posts (`chapter_index=0`)
the `Chapters/` skip in `_resolve_format_file` removes priority 3.

**Chapter-creation recovery (v2.20.7)**: `clients/ao3/client.py:create_chapter`
no longer crashes when AO3's POST response lands on the bare
`/works/{id}/chapters` URL with no chapter ID. Body fallback scans the
response for `/works/{work_id}/chapters/(\d+)` references and picks
the highest numeric ID (AO3 chapter IDs are monotonically increasing);
a `/works/{id}/navigate` fetch is the last-resort. Both fallbacks
include diagnostic body dumps to `{tempdir}/ao3_chapter_debug_*.html`
when they fail.

**Safety helpers** (`AO3Client`):
- `delete_work(work_id)` — confirm_delete flow (`_method=delete`, `commit=Yes, Delete Work`). Use with care.
- `is_work_in_drafts(work_id)` — tri-state check against `/users/{user}/works/drafts`
- `is_work_published(work_id)` — tri-state check against `/users/{user}/works`

**Deletion detection** (`probe_exists`):
- `AO3Poster.probe_exists(external_id)` — GET `/works/{id}/edit`, returns False on 404 (deleted), True on 2xx (live), None on transient errors (don't misflag). Called by `/api/editor/stories/{name}/verify` endpoint during matrix Verify action. Also triggered automatically by `_looks_like_deletion()` in `manager.update_story()` when an edit fails with a deletion-ish error — flips the publications registry row to `status='deleted'` so the cell flips to ⊘ Re-post in the Publish Check matrix.

**Login-with-email resolution**:
AO3 lets you log in with either username OR email. If you log in with email, the account-name URLs (`/users/{name}/works/drafts`, `/users/{name}/skins`) won't resolve. `AO3Client.login()` post-authentication parses the redirect URL and replaces `self.username` with the actual account name, so every subsequent URL hits the right page.

**Known limitations**:
- None of the earlier posting limits remain; AO3 has full SQW parity (chaptered, work skins, safe-overlay edits, deletion probe).

#### DeviantArt (`posting/platforms/deviantart.py`)

**Auth**: Official OAuth2 API — **not** the undocumented `_napi`/`_puppy` endpoints. Requires registering a DA application at the developer portal to get `client_id` and `client_secret`, then doing a one-time Authorization Code flow in the browser to obtain a refresh token. (Since 2.47.0 DA *polling* also runs on this same official OAuth2 API — via an app-only client-credentials token rather than the poster's user refresh token; see §4 DeviantArt.)

**Settings**: `da_client_id`, `da_client_secret`, `da_refresh_token`. Access tokens expire hourly and are auto-refreshed. Refresh tokens last 3 months.

**Post flow**:
```
POST /api/v1/oauth2/deviation/literature/create
```
Parameters: `title` (max 50 chars), `body` (plain text), `tags[]` (max 30), `is_mature`, `mature_level` ("strict"/"moderate"), `mature_classification[]` ("sexual"/"nudity"/"gore"), `allow_comments`, `galleryids[]`.

**Edit flow**:
```
POST /api/v1/oauth2/deviation/literature/update/{deviationid}
```
Same parameters — only provided fields are updated. Body replacement replaces the full literature text.

**Rating mapping**: General → `is_mature=false`; Mature → `is_mature=true, mature_level="moderate"`; Adult → `is_mature=true, mature_level="strict", mature_classification=["sexual"]`.

**Format files**: Reads from `Markdown/MASTER.md` or `Chapters/Markdown/*.md`. The OAuth API accepts plain text (not HTML/BBCode).

**IP independence**: Unlike the cookie-based `_napi` endpoints which need residential IPs, the OAuth2 API works from any IP since authentication is token-based.

**Stability**: Official, documented, versioned API — low fragility compared to the `_napi`/`_puppy` approach that PostyBirb uses.

#### Itaku (`posting/platforms/itaku.py`)

**Auth**: Django REST Framework token extracted from browser session. Stored as `ik_auth_token` in settings. No OAuth or API key registration — must be manually obtained from browser DevTools (Network tab → any API call → Authorization header).

**Image upload**:
POST `/api/galleries/images/` with multipart form data: `image` (binary), `title`, `description`, `tags` (JSON array of `{name: tag}`), `maturity_rating`, `visibility`, `share_on_feed`.

**Text post** (for announcements, not full stories):
POST `/api/posts/` with JSON: `title`, `content` (plaintext, max ~5000 chars), `tags`, `maturity_rating`, `gallery_images` (optional image IDs).

**Rating mapping**: General → `"SFW"`, Mature → `"Questionable"`, Adult → `"NSFW"`.

**Limitations**: No edit API, no file replacement, no chapter system, no rich text formatting. Min 5 tags, max 59 chars per tag, max 10MB per image. Text posts are ~5000 chars max (~800 words). Itaku is an art gallery — literature is a second-class citizen.

**Use case**: Image/thumbnail uploads and short announcement posts, not full story publishing.

### Publications Registry

The `publications` table is the central record of what has been posted where. One row per `(story_name, chapter_index, platform)` combination.

**Schema** (from `posting_schema.sql`):
```sql
CREATE TABLE publications (
    pub_id              INTEGER PRIMARY KEY AUTOINCREMENT,
    story_name          TEXT NOT NULL,       -- "Extra_Credit"
    chapter_index       INTEGER DEFAULT 0,   -- 0 = full story, 1+ = chapter
    chapter_title       TEXT DEFAULT '',
    platform            TEXT NOT NULL,       -- "ib", "fa", "ws", "sf", "sqw", "ao3", "da", "ik", "bsky"
    external_id         TEXT NOT NULL DEFAULT '',  -- Platform's submission ID
    external_url        TEXT DEFAULT '',
    format_file         TEXT DEFAULT '',     -- Path to file that was uploaded
    file_hash           TEXT DEFAULT '',     -- SHA256 hash at time of upload
    tags_used           TEXT DEFAULT '[]',   -- JSON array of tags used
    title_used          TEXT DEFAULT '',
    description_used    TEXT DEFAULT '',
    rating_used         TEXT DEFAULT '',
    status              TEXT NOT NULL DEFAULT 'draft',  -- draft, posted, failed
    first_posted_at     TEXT,
    last_updated_at     TEXT,
    update_count        INTEGER DEFAULT 0,
    word_count          INTEGER DEFAULT 0,
    UNIQUE(story_name, chapter_index, platform)
);
```

Publications are enriched with live stats by `get_publications_with_stats()`, which joins each publication's `external_id` against the platform-specific submission table (e.g. `submissions` for IB, `fa_submissions` for FA) to pull current views, faves, and comments.

**Manual-repair helpers (v2.21.0+)**: three helpers in
`database/posting_queries.py` back the publish-check drawer's per-cell
repair controls (see §15 → Per-Cell Publish Controls):

| Function | Purpose |
|---|---|
| `delete_publication(conn, story_name, chapter_index, platform)` | Drops the local row only — never touches the upstream submission. Used by `DELETE /api/editor/stories/{story}/publication`. |
| `update_publication_url(conn, story_name, chapter_index, platform, *, external_url, external_id)` | Overwrites both URL + ID after the user pastes a known-good submission link. Used by `PUT /api/editor/stories/{story}/publication`. |
| `cancel_all_for(conn, *, platform=None, story_name=None, chapter_index=None)` | Bulk-cancel queue items matching any combination of filters. The `chapter_index` filter was added in 2.21.0 so a single cell's stuck/processing rows can be nuked in one call. |

### Posting Queue

The `posting_queue` table holds pending uploads and updates. Items can be:
- **Immediate**: `scheduled_at` is NULL — processed on the next scheduler check
- **Scheduled**: `scheduled_at` is a future datetime — processed when due
- **Retryable**: Failed items with `attempts < max_attempts` (default 3)

**Status enum** (`posting_queue.status`): `pending` → `processing` →
{`completed` | `failed` | `cancelled`}. The `cancelled` terminal state
was hardened in v2.20.3: `cancel_queue_item` accepts rows in
pending/processing/failed (not just pending), and every
`UPDATE` in `update_queue_status` carries `AND status != 'cancelled'`
so the scheduler's failure path can no longer overwrite a cancellation
back to pending mid-flight.

**`requires` field**: Each queue item carries a `requires` value indicating the runtime mode needed:
- `"any"` — processable by both desktop and server (default for most platforms)
- `"desktop"` — only processable by the desktop app (used for FA, which blocks datacenter IPs)
- `"server"` — only processable by the server instance

The scheduler auto-detects its runtime mode on startup and only processes matching items. Items requiring `"desktop"` are skipped by the server scheduler and vice versa.

**Auto-queue fallback**: When a post fails on the server (e.g. FA rejects the datacenter IP), the manager automatically queues the item with `requires="desktop"` so the desktop app picks it up on its next scheduler check.

### Retroactive Sync

The `/claim` command scans each platform's existing submissions table in PawPoller's database and matches them to stories in the local archive by title. This populates the publications table so that `/update` commands can push revisions to already-live submissions.

**Matching strategy** (`sync.py`):
1. Normalize both story folder names and submission titles (lowercase, strip punctuation, collapse whitespace)
2. Full-story match: `"Extra Credit"` matches `Extra_Credit`
3. Chapter match: `"Hypnotic Claim - Chapter 1: The Seduction"` matches `Hypnotic_Claim` chapter 1
4. Multi-part match: `"Velvet and Vice (Part One)"` matches `Velvet_And_Vice` chapters 1-4
5. Skip test submissions (titles starting with `[TEST]`)

**Platform submission table configs** (`PLATFORM_TABLES` dict):

| Platform | Table | URL Template |
|----------|-------|-------------|
| IB | `submissions` | `https://inkbunny.net/s/{id}` |
| FA | `fa_submissions` | `https://www.furaffinity.net/view/{id}/` |
| WS | `ws_submissions` | `https://www.weasyl.com/submission/{id}` |
| SF | `sf_submissions` | `https://sofurry.com/s/{id}` |
| SqW | `sqw_submissions` | `https://squidgeworld.org/works/{id}` |

_(abbreviated — the dict covers **all 17 platforms**, each `{code}_submissions` with `submission_id`/`title` and, for the newer ones, a `link` permalink preferred over the template. Adding a platform here is what makes its polled submissions discoverable + importable as artwork.)_

### Change Detection

After initial posting, stories are often revised. The change detection system compares the current state of local files against what was recorded in the publications table at the time of posting.

**`file_hash`**: When a story is posted or updated, the SHA256 hash of the uploaded file is stored in `publications.file_hash`. The `/changes` endpoint (`detect_changes()` in `sync.py`) recomputes hashes for all published stories and compares against stored values.

**Telegram `/changes` command**: Shows which stories have changed since last update, with per-platform breakdown. Users can then run `/update all` to push all changes, or `/update <story>` for a specific story.

**`/update all` command**: Iterates all stories with detected changes and pushes updates to every platform where they are published.

### Retry Queue

Failed posts and updates are automatically re-queued for retry with exponential backoff via `_schedule_retry()` in `manager.py`. Backoff schedule: 1 minute, 5 minutes, 30 minutes; maximum 3 attempts. Uses the existing `posting_queue` infrastructure. Desktop-requiring platforms (FA) still queue for desktop pickup. Deletion errors (`_looks_like_deletion()`) skip retry entirely to avoid re-posting to a platform that rejected the content. The Publish Check frontend shows "Will retry automatically" for queued retries.

### Post Scheduling

Three endpoints under `/api/editor/stories/{name}/` enable scheduling future publish/update actions:
- `POST /schedule` -- validates story/platform/chapter, checks the scheduled time is in the future, runs poster validation, then inserts into `posting_queue` with `scheduled_at`. Returns queue_id and confirmed schedule time.
- `GET /scheduled` -- returns all pending/processing queue items for the story.
- `DELETE /scheduled/{queue_id}` -- cancels a pending scheduled item (verifies ownership by story name).

The Publish Check action panel shows a "Schedule" button next to Post/Update with an inline `datetime-local` picker (defaults to 1 hour from now, rounded to next 5 minutes). No scheduler daemon changes were needed -- `posting/scheduler.py` already checks `scheduled_at` against `datetime('now')` each cycle.

### Desktop Queue Mode

Some platforms (currently FA) require residential IPs and cannot be posted to from a server/datacenter. The posting module handles this through the `requires` field:

1. User requests upload from any interface (dashboard, Telegram, API)
2. Manager checks `poster.requires_mode` for each target platform
3. If the platform requires `"desktop"` and the current runtime is `"server"`, the item is queued with `requires="desktop"` instead of attempting a direct upload
4. Scheduler on the desktop instance picks up desktop-only items on its next 60-second check
5. If a post fails on the server with an IP-related error, the manager auto-queues for desktop

**Runtime detection**: `scheduler.detect_runtime_mode()` checks whether `pywebview` is importable. Desktop mode = pywebview available (installed via `requirements.txt`). Server mode = pywebview not available (excluded from `requirements-server.txt`).

### REST API Endpoints

Complete list of `/api/posting/*` endpoints (`routes/posting_api.py`):

| Method | Endpoint | Purpose |
|--------|----------|---------|
| GET | `/api/posting/stories` | List all stories with publication status per platform |
| GET | `/api/posting/stories/{name}` | Full story detail: metadata, chapters, publications, formats, stats |
| POST | `/api/posting/post` | Post story to platforms immediately |
| POST | `/api/posting/update` | Push updates to already-posted submissions |
| GET | `/api/posting/publications` | List publications (filterable by story/platform) |
| GET | `/api/posting/publications/stats` | Publications enriched with live polling stats |
| GET | `/api/posting/publications/{pub_id}` | Single publication by ID |
| POST | `/api/posting/queue` | Add items to posting queue (with scheduling) |
| GET | `/api/posting/queue` | List pending/processing queue items |
| DELETE | `/api/posting/queue/{queue_id}` | Cancel a pending queue item |
| GET | `/api/posting/log` | Posting audit log (filterable by story, with limit) |
| GET | `/api/posting/settings` | Get posting-related settings |
| POST | `/api/posting/settings` | Save posting-related settings |
| POST | `/api/posting/claim` | Retroactive sync: match submissions to stories |
| GET | `/api/posting/changes` | Detect publications with changed files |
| GET | `/api/posting/sync/status` | Per-story sync status summary (for dashboard) |
| POST | `/api/posting/sync/upload` | Receive .tar.gz archive from desktop instance |
| POST | `/api/posting/sync/push` | Push local archive to remote server |

**POST `/api/posting/post`** body:
```json
{
    "story_name": "Extra_Credit",
    "platforms": ["ib", "sf"],
    "chapters": [1, 2, 3],
    "confirm_live": true
}
```
`chapters` is optional — `null` or omitted means all chapters. `confirm_live`
is **required** (must be `true`): a live-publish safety guard mirroring the
editor's publish endpoint, so a UI regression can't fire a public post without
an explicit acknowledgement. `/api/posting/update` requires it identically.

**POST `/api/posting/queue`** body:
```json
{
    "story_name": "Extra_Credit",
    "platforms": ["ib", "sf"],
    "chapters": [1, 2],
    "action": "post",
    "scheduled_at": "2026-04-10T18:00:00Z"
}
```
`scheduled_at` is optional — `null` means process immediately on next scheduler check.

**POST `/api/posting/claim`** body:
```json
{
    "platforms": ["ib", "fa"],
    "dry_run": true
}
```
Both fields are optional. `platforms` defaults to all platforms with data. `dry_run` previews matches without writing.

### Telegram Commands

The Telegram bot (`polling/telegram_bot.py`) includes 6 posting-related commands:

| Command | Purpose |
|---------|---------|
| `/stories` | List available stories in the archive with chapter counts and format availability |
| `/upload <story> [platforms]` | Post a story to platforms (e.g. `/upload Extra_Credit ib,sf`) |
| `/update <story> [platforms]` | Push updates to already-posted submissions |
| `/update all [platforms]` | Update all stories with changed files |
| `/posted [story]` | Show the publication registry (what is posted where) |
| `/claim [platforms]` | Claim existing submissions into the publications registry |
| `/changes` | Show which stories have changed since last update |

### Dashboard UI

The posting module is implemented in `frontend/js/posting.js`. It no longer has its own sidebar section — see §"One works hub" below.

**1. Stories Hub** (`#/posting`) — **RETIRED 2.155.0 (backlog L).** It was a card grid of every story in the archive, with no search or sort. That made it `/api/works` filtered to `content_type == "story"` — a strict subset of the Library's Stories segment, linking to the same detail page. The route now **redirects to `#/library/type/story`**, and `Posting.renderUpload()` is unreachable (kept for now as a port source; tracked as backlog L2). Cards live in `bookshelf.js` `_book()`.

**2. Story Detail** (`#/posting/story/{name}`) — Full metadata view with:
- Story info: title, author, description, word count, rating, warnings
- Chapter list with per-chapter descriptions
- Per-platform publication status (posted/not posted) with external links
- Upload controls: select platforms and chapters, post or queue
- Publication history with live stats from polling tables

**3. Queue** (`#/posting/queue`) — Table of pending, processing, and completed queue items. Shows story, platform, action, status, scheduled time, and error messages. Cancel button for pending items.

**4. History/Log** (`#/posting/log`) — Audit trail of all posting actions (uploads, edits, failures) with timestamps, durations, and error details.

### Story Sync

**`deploy/pawsync.bat`**: Batch script that syncs the local story archive to the GCP server:
1. `tar -czf` the `Complete_Stories/` directory (excluding `Backups/`, `Drafts/`, `Styled_HTML/`)
2. `gcloud compute scp` the tarball to the server (`/tmp/story-archive.tar.gz`)
3. `gcloud compute ssh` to extract on server + set permissions + clean up temp file

**API-based sync** (`/api/posting/sync/push` + `/api/posting/sync/upload`): The dashboard also supports sync via HTTP:
- Desktop calls `POST /api/posting/sync/push` with an optional `server_url` and `api_key`
- The endpoint tars the local archive in-memory and POSTs it to the remote server's `POST /api/posting/sync/upload`
- The upload endpoint extracts the tarball into the server's story archive directory
- Security: path traversal protection rejects any archive members starting with `/` or containing `..`

**SquidgeWorld exclusion fix**: The `pawsync.bat` script now excludes `Styled_HTML/` directories from the sync. Styled HTML files are large and not needed by any platform poster — they are only used for local rendering. SqW uses `SquidgeWorld/*.html` or `Chapters/SoFurry_HTML/*.html` instead.

### Configuration

The posting module uses these settings in `settings.json`:

| Key | Type | Default | Purpose |
|-----|------|---------|---------|
| `posting_enabled` | bool | false | Master toggle — scheduler skips all processing when false |
| `posting_story_archive_path` | string | "" | Custom archive path (overrides default resolution) |
| `posting_default_platforms` | list | [] | Default platforms for new uploads |
| `posting_default_rating` | string | "adult" | Default rating for new uploads |
| `posting_server_url` | string | "" | Remote server URL for sync push |
| `posting_server_api_key` | string | "" | API key for authenticating with remote server |
| `sqw_author_username` | string | "" | SquidgeWorld author account (for posting, distinct from polling account) |
| `sqw_author_password` | string | "" | SquidgeWorld author password |

**Archive path resolution order** (in `story_reader.get_archive_path()`):
1. `posting_story_archive_path` setting (explicit override)
2. `/app/story-archive` (Docker bind mount on GCP server)
3. `../m_x/Archives/Complete_Stories/` (relative to PawPoller, for desktop)

---

## 15. Story Editor

The Story Editor is a browser-based authoring environment for stories
under `m_x/Archives/Complete_Stories/`. Its job is to take `MASTER.md`
(the canonical source for every completed story) and produce all of the
derivative formats — Clean HTML, SoFurry HTML, BBCode, SquidgeWorld,
Styled HTML, and PDFs — that the posting module then uploads to each
platform.

### Architecture

```
frontend/                                        backend
├── editor.html             ◄─────────────────►  routes/editor_api.py
├── js/editor.js                  HTTP / JSON      ├── /api/editor/stories
├── js/metadata_editor.js                          ├── /api/editor/stories/{name}/master
├── css/editor.css                                 ├── /api/editor/stories/{name}/preview
                                                   ├── /api/editor/stories/{name}/regenerate
                                                   ├── /api/editor/stories/{name}/theme
                                                   ├── /api/editor/stories/{name}/chapters
                                                   ├── /api/editor/stories/{name}/cover
                                                   ├── /api/editor/tags
                                                   ├── /api/editor/tags/lookup
                                                   └── /api/editor/tags/add
                                                       │
                                                       ▼
                                                  editor/converter.py
                                                  editor/pdf_generator.py
                                                  editor/epub_generator.py
                                                  editor/slop.py
```

The editor never modifies derivative files directly — it edits
`MASTER.md`, then `/regenerate` rebuilds every other format from it.
This guarantees the formats can never drift from the source.

### Anchor System

`MASTER.md` uses HTML-comment anchors to mark structural elements that
plain Markdown can't express. The converter parses them and emits
appropriate per-format markup.

| Anchor | Meaning | Used by |
|--------|---------|---------|
| `<!-- @title -->` | Story / chapter title block | All formats (style hooks) |
| `<!-- @subtitle -->` | Subtitle line | Styled HTML, SoFurry HTML |
| `<!-- @byline -->` | "by Author" line | Styled HTML, SQW |
| `<!-- @warning -->` | Content warning panel | Styled HTML, SQW |
| `<!-- @disclaimer -->` | Disclaimer block | Styled HTML, SQW |
| `<!-- @body -->` | Main story prose starts here | Splits front matter from content |
| `<!-- @text-sent --> ... <!-- @text-end -->` | Outgoing text-message bubble | Styled HTML (CSS bubble), SQW (`.text-sent` class), SoFurry HTML (italic block) |
| `<!-- @text-received --> ... <!-- @text-end -->` | Incoming text-message bubble | Same as above |
| `<!-- @phone --> ... <!-- @phone-end -->` | Phone screen container | Styled HTML (frame/border), SQW |
| `<!-- @story-end -->` | "~ End ~" centered marker | Styled HTML, SQW |
| `# Chapter N: Title` | Chapter break (after `---`) | Per-chapter splitting |

The converter (`editor/converter.py`) walks the markdown line-by-line,
maintaining anchor state. Inline markdown (`*italic*`, `**bold**`,
`---` section breaks, POV markers like `**⟨ Callum ⟩**`) is converted
per-format using the `convert(content, format)` entry point.

### Anchor Toolbar

The WYSIWYG toolbar includes 8 anchor insertion buttons: Title, Sub, Body, Warning, Text Sent, Text Received, Phone, and End. Each calls `_insertAnchor(type)` which inserts the corresponding HTML-comment anchor at the CodeMirror cursor position. This replaces the need to manually type anchor comments.

### Format Converters

`editor/converter.py` exposes these format keys:

| Format | Output | Used by |
|--------|--------|---------|
| `clean_html` | Body-only HTML, no `<head>` | AO3, generic uploaders |
| `sofurry_html` | SF-specific HTML (`<h2>`, `<h3>`, `text-center`) | SoFurry |
| `bbcode` | Inkbunny BBCode | Inkbunny, Weasyl |
| `sqw` | SquidgeWorld OTW-Archive HTML (per-chapter) | SquidgeWorld |
| `styled_html` | Self-contained Styled HTML with theme CSS | Local rendering, PDF source |

Each returns a `ConvertResult` dataclass: `output`, `stats` (chapter
counts, word counts), `warnings` (non-fatal issues like missing
anchors). `convert_to_styled_html_external_css()` emits a variant
that links to an external `style.css` rather than inlining — used for
the editor's preview pane and the per-chapter Styled HTML files.

### EPUB Output

`editor/epub_generator.py` builds an EPUB 3.0 archive in a Vellum-style
novel layout. It reuses the same anchor parser as the other formats
(`parse_front_matter`, `parse_markdown_formatting`, `is_pov_marker`,
`is_text_message`) so phone-screen blocks, text-message bubbles, and
italic-narration body all carry through identically.

Layout choices that mirror the Vellum 4.1.2 reference (Apple Books):
- Word-form chapter numbers — `# Chapter 2: Title` becomes a
  "Chapter Two" line above the title, drop cap on the first paragraph
  rendered roman regardless of italic body context.
- `mimetype` first and uncompressed; `META-INF/container.xml` points at
  `OEBPS/content.opf`; manifest + spine + nav `toc.xhtml` per spec.
- `_strip_trailing_separators()` drops the source `---` between
  chapters so no empty `<hr/>` page slips in between chapter files.

Output lives in `EPUB/{stem}.epub` (one file per story). Auto-discovered
by `posting/story_reader.py` via `_FORMAT_KEY_PATTERNS["epub"]` and
flagged in `story.json` by `posting/generate_story_json.py`. The
regenerate route accepts an `epub_warning_position` field
(`"front"` | `"after-title"`) for placement of the content-warning
block. Validates cleanly against epubcheck 5.1.0 / EPUB 3.3.

### EPUB Viewer (2.17.6+)

Served at `GET /epub-viewer.html?story=X&file=EPUB/Y.epub` for
in-dashboard previews of generated EPUBs. Wired from the editor's
Downloads dropdown via a `.downloads-row-sub` "↗ Preview in browser"
sub-row inserted directly under the EPUB row in
`frontend/js/editor.js:_populateDownloadsMenu`. Opens in a new tab
(`target="_blank"`).

Files:
- `frontend/vendor/epub.min.js` — epub.js 0.3.93, BSD-2
- `frontend/vendor/jszip.min.js` — jszip 3.10.1, MIT
- `frontend/vendor/README.md` — version/license tracking
- `frontend/epub-viewer.html` — minimal page: 48px toolbar
  (close × / title / ‹ prev / N% / next › / ↓ EPUB download),
  full-bleed reader area, two invisible 18%-wide tap zones for
  mobile prev/next. Loads `tokens.css` for theme-token resolution.
  The inline `<head>` script is byte-identical to `index.html`'s
  theme/mobile bootstrap so the existing CSP SHA-256 hash covers
  it (`WudoxBejEmzS4SXsQBia7rsNZctlaFiey3RvF0r8SzA=`).
- `frontend/js/epub-viewer.js` — viewer logic. Reads `?story=` /
  `?file=` from URL, fetches the EPUB via `/api/posting/file`
  (cookie carries same-origin), wires keyboard arrows + tap zones
  + toolbar buttons, generates location index for the percent
  indicator.

`dashboard.py` plumbing:
- `app.mount("/vendor", StaticFiles(...))` next to `/css` and `/js`
  (and `/img` since 2.32.0, serving the brand assets: `logo-quill.png`,
  `favicon.png`/`.ico`, `apple-touch-icon.png`)
- `_AUTH_EXEMPT_PREFIXES = ("/css/", "/js/", "/vendor/", "/img/")` so vendored
  libs + brand assets load without auth (parity with the rest of the SPA assets)
- `@app.get("/favicon.ico")` (2.32.0) serves the nib-badge `.ico` for the bare
  browser request (path is also in `_AUTH_EXEMPT_PATHS`)
- `app.include_router(works_router)` (2.33.0) — the unified **Submissions hub** at
  `/api/works` (`routes/submissions_api.py`): a per-work list merging the story +
  artwork archives with the publications registry (posted platforms + persona),
  built by the pure, unit-tested `assemble_works()` helper. Frontend:
  `frontend/js/submissions.js`, route `#/submissions`, sidebar item above
  Stories/Artwork. Phase 1 of `docs/specs/submissions-hub.md`.
  - **2.73.0 — the Bookshelf / Library** (reskin concept Slice A, `docs/RESKIN_BUILD_PLAN.md`):
    a second, editorial view of the same works over the SAME endpoints — no backend added.
    `frontend/js/bookshelf.js` (`window.Bookshelf`) + `frontend/css/bookshelf.css`, a new
    **top-level** route `#/library` (peer to Overview, distinct from the Publishing-group
    Submissions hub). `render()` is a cover-forward shelf over `/api/works` (gilt "N live" /
    "published" ribbon from `platforms`/`publication_count`; quiet Draft otherwise; serif-initial
    placeholder for coverless works). `renderWork(name)` (`#/library/work/{name}`) fetches
    `/api/posting/stories/{name}` and renders the "Atelier" detail: marginalia stats, a per-platform
    **Published to** list (views summed, faves/comments maxed across a platform's `publications[]`
    rows), and a **chapter × platform reach** card (lights each chapter's platforms from
    `publications[].chapter_index`; flags **incomplete** where a multi-chapter platform is missing a
    chapter). Stories open here; artwork keeps `#/artwork/image/{name}`. Router branches +
    active-nav keep-lit + breadcrumb are in `app.js`.
  - **2.74.0 — Modes pane + Brut display mode** (reskin concept Slice B, `docs/RESKIN_BUILD_PLAN.md`):
    a **Display mode** picker joins Theme + Navigation in **Settings → Appearance** as the
    look-and-feel controls. Two skins: **Default** and **Brut**. Brut is a *character* layer
    (`html[data-mode="brut"]`), NOT a theme — it keeps the active theme's colours and only changes
    the "hand": thick ink borders, hard `4px 4px 0` offset shadows, **squared corners via an
    app-wide `--radius*` token override**, bold-sans headings (overrides the Vibe-Pack serif rule in
    `tokens.css` by specificity + load order), press-down buttons. It's **theme-aware** because the
    border/shadow colour is the active theme's ink (`--text-primary`) — dark on paper, light on the
    dark themes; both read brutalist. Mechanism mirrors nav mode exactly: single source of truth is
    the `data-mode` attribute on `<html>` (ABSENT = Default), set pre-paint by the no-flash boot
    `<script>` (index.html + epub-viewer.html, both kept byte-identical) from localStorage
    `pawpoller-mode`; `App.applyMode()` / `getModeOverride()` / `DISPLAY_MODES` in `app.js`; the CSP
    boot hash self-computes (`_theme_inline_hash`) so no hash edit. Styles live in a new
    `frontend/css/brut.css` (linked after `bookshelf.css`), targeting the real primitives (`.card`,
    `.stat-card`, `.settings-section`, `.btn*`, `.form-control`, `.sidebar`, `.nav-link.active`,
    `.nav-sub`, `.book-cover`, `.work-card`, `.chip`, headings). Brut swaps borders/shadows/type but
    **not layout**, so charts don't re-measure and there's no re-route (no lost editor state).
    **Design decision — Terminal/Console is intentionally not a dashboard skin.** The green-on-black
    operator/CLI aesthetic (the "Console" concept) belongs to the **headless / Docker operator
    surface** (where you shell in for `docker`/logs), not the end-user dashboard — so only Default +
    Brut are offered as display modes. If a terminal skin is ever built, it attaches to the headless
    context, keyed the same way (`data-mode="term"`), never surfaced as a dashboard option here.
  - **2.75.0 — Laurels** (reskin concept Slice C, `docs/RESKIN_BUILD_PLAN.md`): a motivational
    achievements view at top-level route `#/laurels` (Insights & Tools group). `frontend/js/laurels.js`
    (`window.Laurels`) + `frontend/css/laurels.css`; **no backend added** (Path A). `render()` fans out
    `getPersonas` + `getPreferences` + `getWorks` + `getSummary` + `getAggregate` + `getPostingLog` in
    one `Promise.all` (each `.catch`-guarded), then aggregates client-side. Grand totals come from the
    **normalized** persona stats (`personas[].stats.combined.{views,favorites,comments,submissions}` +
    any `unassigned[].stats`) — this sidesteps the per-platform summary-key divergence (views vs
    likes/notes/reads). The **medal rungs reuse the app's own milestone ladders**
    (`/api/settings/preferences` `milestone_views/faves/comments`, falling back to hardcoded defaults
    that mirror `routes/api.py`), so a Laurels medal == a Telegram milestone alert. Medals are all
    derived (metric-tier at the highest rung reached + next rung in-progress; catalogue medals from
    `getWorks` counts + platform-spread; Breakout from `summary.top_viewed[0].views`; watchers from
    `summary.total_watchers`). Per-persona **trophy cards** show a metal tier (Bronze→Diamond by views)
    + level (rungs cleared). **Rhythm** buckets posting-log `created_at` into ISO weeks (last 12) for a
    weeks-with-a-publish streak, plus distinct `aggregate.snapshots[].polled_at` days for "days
    tracked". **Design decision (the deferred open question):** milestones read each platform's CURRENT
    cumulative totals — i.e. **all-time**, credit for everything earned — stated in a page footnote (a
    "from-now-on" mode was considered and rejected as less motivating and harder to explain). Router
    branch + breadcrumb label in `app.js`; nav item in the Insights group; Brut mode covers `.lr-*`
    cards.
  - **2.76.0 — Ledger / dated timelines** (reskin concept Slice D, `docs/RESKIN_BUILD_PLAN.md`): a
    reusable `window.Ledger` (in `frontend/js/ledger.js` + `frontend/css/ledger.css`) rendering a dated
    spine (day-grouped, newest-first, typed node dots with status colours), used in two places, **no
    backend added**. (1) **Work timeline** — a "Timeline" tab on the Bookshelf work-detail; `bookshelf.js`
    `_paintWork` now wraps the existing cards in a `.work-pane[data-pane="overview"]` and adds a
    `.work-pane[data-pane="timeline"]` that `Ledger.renderWorkTimeline(pane, name, d)` fills **lazily on
    first open, reusing the already-fetched `d`** (no extra request). `Ledger.workEvents` derives nodes
    from `d.publications[]`: `first_posted_at` → "Posted to {platform}" (chapter-labelled when
    `chapter_index > 0`), `last_updated_at` (when `update_count > 0` and ≠ first_posted) → "Updated on
    {platform}". NOTE: managed works that were never *posted through PawPoller's posting module* have
    empty `publications` (their `/api/works` count comes from linked discovered submissions), so their
    timeline is empty — expected. (2) **Activity ledger** — route `#/ledger` (nav "Activity", Insights
    group) over `GET /api/activity/recent` (`API.getRecentActivity`), the unified poll+post event feed
    (`{events:[{timestamp,platform,kind,status,summary,detail}]}`). `Ledger.render()` maps those to nodes
    (kind→type, status→colour: `err/fail`→red, `partial/warn`→amber), then `_paint()` applies **client-side
    filters** — segments All/Posts/Polls/Issues + a platform `<select>` (filtering to one platform reads
    as that account's history). **Design note:** the Ledger is only ever a **tab / destination, never the
    home** — a time-ordered list buries "is everything OK right now", which is Overview's job. Router
    branch + breadcrumb in `app.js`; Brut squares the node dots + rail (`.led-dot`/`.led-day-nodes`).
  - **2.77.0 — Health strip + Workbench** (reskin concept Slice E, final; `docs/RESKIN_BUILD_PLAN.md`):
    extends the **existing** Overview widget board (the "Workbench" — `_renderDashboard` at ~app.js:2770,
    edit mode with drag `_wireDashDrag` / resize `[data-wsz]` / remove `[data-wrm]` / add `_openDashCatalog`,
    persisted to the `dashboard_layout` preference via `_saveDashLayout`; this all predates the slice). Two
    additions: **(1) Observatory** — a new `health` widget (`_dashWidgetMeta`/`_dashDefaultLayout`; rendered by
    `_healthStripHtml`, mounted by `_mountHealthStrip`): a compact 16-platform status strip that reads the
    shared `window.PlatformHealth` cache and `subscribe()`s for live updates (**no new fetch** — PlatformHealth
    already polls `/api/platforms/health`), colouring a dot per platform by `PlatformHealth.classify(code)`
    (`healthy/running/stale/throttled/error/unconfigured/unknown`) with a summary count. The subscriber
    self-unsubscribes when the strip leaves the DOM and is re-bound cleanly each render (`this._healthUnsub`).
    **(2) Bento** — the `charts` widget gains a **Line/Bar toggle** persisted **per-widget**: layout entries
    now carry an optional `cfg` object (`{id, span, cfg:{chartType}}`), the loader (~app.js:2679) preserves
    `cfg` through validation, `_dashWidgetHtml`/`_dashWidgetMount` take the entry `w` as a 3rd arg and read
    `w.cfg.chartType`, and `Charts.aggregateLine` gained a backward-compatible `type` param (`'bar'` = solid
    fill, no trendlines). Styles in new `frontend/css/workbench.css` (health strip states via semantic tokens
    `--success/--info/--warning/--danger`; Brut coverage). To add another configurable widget, follow the same
    pattern: register it, render/mount with the `w` entry, store settings on `w.cfg` (the loader keeps it).
    **This completes the 5-slice reskin concept-layer plan.**
  - **2.78.0 — Gamification expansion** (builds on Slice-C Laurels; Path A, **no backend added**). Four
    threads, all in existing files (`laurels.js`, `bookshelf.js`, `laurels.css`, `bookshelf.css` — no new
    files, no new routes): **(1) Account medals 9 → 23** — `Laurels._buildMedals(d)` now emits a **stable
    `id`** on every medal (the celebration engine diffs on it), and `render()` computes `rhythm`/`trackingDays`
    **before** calling `_buildMedals` so streak (`On a Roll`, `id:on-a-roll`) and days-tracked (`Dedicated`,
    `id:dedicated`) medals can exist. New medals: `first-words`/`first-canvas`, `storyteller` (5 stories),
    `gallery` (5 artworks), `shelf-of-ten`/`prolific` (25)/`century` (100 works), `cross-poster`/`wide-reach`
    (8+ platforms on one work)/`full-spread` (all 16), `breakout` (5k on one work)/`viral-hit` (10k),
    `following-100`/`following-500` (👑, only if watchers≥100), and `decorated` (🎖 earn 15 — computed from an
    `earnedSoFar` count of the others). Tier + per-work-derived medals carry a **source** field (the work title,
    e.g. Breakout ← "Chosen") shown as a sub-badge. **(2) Per-work achievements** — a **pure** engine
    `Laurels.workMedals(w)` (input `{views,faves,comments,platforms:[],chapters,words,incompleteChapters}`,
    returns `[{id,icon,name,sub,earned}]`): `w-published`, `w-crossposted` (3+ platforms), `w-wide` (8+), a
    single view tier (highest of 1K/5K/10K), `w-beloved` (100 faves), `w-discussed` (25 comments), `w-epic`
    (10 ch), `w-wordsmith` (40k words), `w-complete` (no chapter gaps — only when chapters>1 && published≥1).
    `bookshelf.js` `_paintWork` calls it with the **same per-work stats it already aggregates** (views summed,
    faves/comments max-across-a-platform's-rows via the existing `byPlat` logic; `incompleteChapters` from the
    chapter-gap reduce) and renders an **"Achievements — N of M earned"** `.work-card` (via `_wMedal(x)` →
    `.wm.is-earned`/`.is-locked` chips) between "Published to" and the chapter card. NOTE: managed/imported works
    with empty `publications` still get view/fave stats from linked discovered submissions, so their per-work
    medals populate even though their *timeline* (2.76.0) is empty. **(3) Library → Laurels button** — `_paintWork`'s
    library header is wrapped in a `.shelf-topbar` (flex space-between) with a `🏅 Laurels` `<a href="#/laurels">`
    (`.shelf-laurels`); the view is now reachable from the Library, not only the Insights nav group. **(4) Animated
    celebration** — `render()` ends with `_animateIn(totals.views)` + `_celebrateNew(earned)`. `_animateIn` drives
    the **hero count-up** (ease-out cubic ~1.1s, only if target≥50) and fills `.lr-hero-fill`/`.lr-mini-fill`
    `[data-pct]` bars from `width:0` (CSS transition). `_celebrateNew(earned)` diffs the earned-medal `id`s against
    `localStorage['pp_laurels_seen']`: **first run with no key records a silent baseline** (no popups — existing
    users aren't spammed with their whole medal history), otherwise any id not in the seen set is `_enqueueCeleb`'d
    and the set is updated. `_drainCeleb` builds a fixed **`.lr-celebrate`** overlay (z-9999 backdrop) with a
    scale-in **`.lr-celebrate-card`** (🏆 icon / "Achievement unlocked" eyebrow / medal name+desc / "tap to dismiss")
    and **28 `.lr-conf` confetti** (randomised left/delay/duration via `Math.random`), auto-closing after 4600ms or
    on click, one-at-a-time via a `_celebBusy` queue. **Reduced-motion:** a `@media (prefers-reduced-motion: reduce)`
    block disables the count-up/bar-fill/confetti/card-pop. **Brut:** squares the popup card + `.wm` chips (hard
    border/offset shadow). The count-up/bars use `requestAnimationFrame` + `performance.now()` (both available in the
    browser; only unavailable in the Workflow sandbox).
  - **2.79.0 — App-wide milestone celebrations.** The 2.78.0 celebration only fired when the Laurels page was
    open (`render()` → `_celebrateNew`). 2.79.0 makes it fire on **any** screen the moment a poll crosses a
    milestone, via a background watcher — still Path A, **no backend / new files / new endpoints**. Two parts, both
    in `frontend/js/laurels.js` plus a one-line start in `app.js`: **(1) `_load()` extraction** — the
    fetch(6 endpoints)+aggregate+`_buildMedals` block that was inline in `render()` is pulled into a shared
    `async _load()` returning the full model `{personas, totals, ladderV, rhythm, trackingDays, pV, pF, pC, medals,
    empty}`. `render()` now calls `_load()` then paints (behaviour identical). The watcher calls the SAME `_load()`,
    so both compute identical medal ids and share the one `pp_laurels_seen` baseline → each crossing is celebrated
    exactly once regardless of which path detects it. **(2) `startAchievementWatch()`** — called once from
    `App.init()` right after `PlatformHealth.start()` / `NotificationCenter.start()` (same auth gate; guarded by
    `this._watching`). It schedules a silent catch-up `_achCheck()` ~4s after login (covers milestones crossed while
    the app was closed — first-ever run just baselines silently) and `PlatformHealth.subscribe()`s to detect poll
    completion: `_newestPoll(data)` returns the max `Date.parse(last_poll_at)` across platforms; when it advances past
    the last-seen value, `_achCheck()` runs. `_achCheck()` (guarded by `this._achBusy`, try/caught so a transient
    fetch failure just waits for the next poll) does `_load()` → `_celebrateNew(earned)`, reusing the 2.78.0 overlay /
    queue / reduced-motion / Brut untouched. **Why PlatformHealth for the trigger:** it already polls
    `/api/platforms/health` every 60s and exposes `last_poll_at` + `subscribe()`, so the watcher needs **no trigger
    fetch of its own** and only does the 6-endpoint `_load()` when a poll actually landed (~hourly), not every tick.
    NOTE: milestone crossings are otherwise invisible in-app (the server-side `check_milestones` in
    `polling/telegram.py` only sends Telegram, persists nothing), so this celebration is the only in-dashboard
    surfacing of a crossing.
  - **2.85.0 — Laurels 100+ achievements, grouped & filterable.** Expands `_buildMedals(d)` from ~23 medals to
    a **104-medal catalogue**, still Path A (frontend-only, same `_load()` model + endpoints, no backend). The
    core shift: each engagement metric is a **full ladder** — a `ladder({group,key,icon,unit,verb,total,rungs,
    names,desc?})` helper pushes one medal per rung (`id:` `${key}-${rung}`, `earned: total>=rung`, `sub:`
    `${total}/${rung}` while locked), replacing the old "top-crossed + next" pair. Ladders: Views (13 rungs →
    1M), Favourites (12), Comments (9), Library works/stories/art, Reach breadth, Following watchers, Breakouts
    (best single work by views, themed names), Momentum streak + tracking-days; hand-authored `badge()`s cover
    Reach cross-post depth, Personas (best persona view-tier + count — `_load` now also computes `personaViews`
    = max persona `stats.combined.views` and passes `personaCount`), and Milestones (all-rounder + collection
    meta `decorated-{15,30,50,75,100}` counting earned-so-far). Every medal carries a `group`; **`_medalsSection
    (medals)`** buckets them by `_GROUP_ORDER` and renders one `.lr-mgroup` per group (serif `.lr-mg-title` +
    `data-earned` count) with an **All/Earned** `.lr-mfilter` toggle wired in `render()` (adds `filt-earned` to
    the section; CSS hides `.lr-medal.is-locked` and any `.lr-mgroup[data-earned="0"]`). `workMedals(w)` similarly
    expanded to ~20/work (full view/fave/comment tiers + Epic/Saga chapters + Novel/Epic-Length words). **Confetti-
    flood guard (important):** the new per-rung ids would all read as "new" to a returning user, so `_SEEN_KEY` is
    bumped to **`pp_laurels_seen_v2`** (everyone re-baselines silently once) AND `_celebrateNew` gains a
    `_CELEB_BURST_CAP` (3): it always advances the baseline but if `>3` medals are freshly earned at once (an
    upgrade, or a bulk poll catch-up) it returns without celebrating — single/small crossings still pop. The hero
    view-tracker still uses the prefs/alert ladder (`ladderV`), so the medal ladder (which climbs past the alert
    rungs) is a deliberate superset. Verified live-in-browser: 104 medals, 10 groups, 0 duplicate ids, filter
    104→10, silent re-baseline, 0 console errors.
  - **2.80.0 — Mobile polish + iOS safe-area fixes** for the reskin/gamification pages (CSS-only, no
    logic/DOM change). Context: mobile mode is width-driven — the boot script sets `data-mobile="1"` at
    `≤768px` (index.html), the sidebar becomes a slide-in drawer, and a **fixed hamburger** (`.hamburger-btn`,
    top-left) + **fixed bell** (`.pp-notif-bell`, top-right) + **fixed `.bottom-nav`** float over the content.
    The core mobile chrome was already `env(safe-area-inset-*)`-aware (index.html has `viewport-fit=cover`; the
    hamburger uses `env(top/left)+12px`, `.main-content` reserves `bottom-nav-h + env(bottom)`), but the **new
    reskin pages weren't**. Five fixes: **(1)** the top-left page header on Bookshelf/Laurels/work-detail
    (`.shelf-topbar`/`.lr-head`/`.work-back`) started at `left:16` and hid under the hamburger → added mobile
    `padding-top: calc(env(safe-area-inset-top,0px)+44px)`. **(2)** `.lr-medals` used `minmax(180px,1fr)`+gap,
    which fits only ONE column at ~360px (22 medals stacked) → mobile override `repeat(2,1fr)`. **(3)** the bell
    was a flat `top:8px` (loading_indicator.css `@media(max-width:560px)`) with no top inset, so it sat under the
    iPhone status bar / Dynamic Island → `top: calc(env(safe-area-inset-top,0px)+8px)` (matches the hamburger).
    **(4)** the work-hero kept `120px 1fr` on mobile, cramming a long summary into the narrow column beside an
    empty gap under the cover → mobile single-column (`grid-template-columns:1fr`) with a capped `.work-cover{
    width:128px}`. **(5)** `.bottom-nav` padded `env(safe-area-inset-bottom)` but with `box-sizing:border-box`
    + fixed `height:var(--bottom-nav-h)` the 34px inset squeezed the 50px items into the home-indicator zone →
    `height: calc(var(--bottom-nav-h) + env(safe-area-inset-bottom,0px))` so the nav grows and the item row
    lifts clear of the swipe-up bar. Touched `frontend/css/{bookshelf,laurels,loading_indicator,layout}.css`.
    **Chrome caveat:** `env(safe-area-inset-*)` resolves to 0 in desktop Chrome / device emulation, so #3/#5
    are verified by asserting the CSS rule is present + a manual inset simulation (override with iPhone 15 Pro
    values 59px/34px), not by real env resolution — a real-device pass is the final confirmation.
    **Native-app reach:** the native **desktop** app (`main.py` → pywebview `create_window(url=http://127.0.0.1:
    8420)`) loads these exact `frontend/` files, so the fix is shared in source — but it runs at desktop window
    width (`data-mobile="0"`), so these `@media(max-width:768px)` rules don't apply at normal size, and the
    shipped PyInstaller EXE only picks up the CSS on a `build.bat` rebuild (the server git-pull+docker deploy
    doesn't touch it). There is **no native iOS/Android app**, and the web app is **not yet a PWA** (no
    `manifest` / `apple-mobile-web-app-capable` meta — only `apple-touch-icon`), so "Add to Home Screen" opens
    normal Safari, not a standalone app; the `env()` safe-area work would pay off most if a PWA/standalone mode
    is added later.
  - **2.81.0 — PWA (installable, standalone).** Turns the app into an installable home-screen PWA (the
    follow-up the 2.80.0 note foreshadowed). Pieces: **manifest** `frontend/manifest.webmanifest` served at
    `/manifest.webmanifest` (`application/manifest+json`) — `display:standalone`, `orientation:portrait`,
    `start_url`/`scope` `/`, `background_color`/`theme_color` `#f4f0e8`, icons 192/512/512-maskable
    (`frontend/img/pwa-*.png`, the sienna quill on paper). **iOS metas** in `index.html`
    (`apple-mobile-web-app-capable=yes`, `-status-bar-style=default`, `-title=PawPoller`,
    `mobile-web-app-capable`, `theme-color`) + `<link rel="manifest">` + `<script defer src="/js/pwa.js">` —
    added after the `apple-touch-icon` link, NOT touching the inline theme-boot `<script>`, so its CSP hash is
    unchanged. iOS keeps using `apple-touch-icon` (the paw badge) as the icon; `-status-bar-style=default` means
    the standalone content sits BELOW an opaque status bar, so `env(safe-area-inset-top)` is ~0 there and the
    2.80.0 bell/header insets resolve to their base offsets (no double gap); the bottom `env(safe-area-inset-
    bottom)` still applies for the home indicator. **Service worker** `frontend/sw.js` served ROOT-scoped at
    `/sw.js` (a worker under `/js/` could only control `/js/`) with `Cache-Control: no-cache` and
    `__APP_VERSION__` spliced into `CACHE = 'pawpoller-shell-<version>'` — so each deploy changes the worker's
    bytes → browser installs the new worker → `activate()` purges older caches (Cache API only; it never touches
    `localStorage`). **SW safety invariants (critical for a live auth'd dashboard):** early-returns (no
    `respondWith`) for non-GET, cross-origin, and **any `/api/*`** so live polling data + auth ALWAYS hit the
    network and are never cached; navigations are network-first (server decides login vs app) with the cached
    shell only as an offline fallback; static assets are cache-first ONLY because the `?v=APP_VERSION` query
    guarantees a new release requests new URLs (stale impossible). **Registration** `frontend/js/pwa.js`
    (external → `script-src 'self'`, no inline hash) registers `/sw.js` on `load` (guarded/silent on failure)
    and keeps `<meta name=theme-color>` synced to the resolved theme's `--bg-primary` via a `data-theme`
    MutationObserver. **`dashboard.py`:** `serve_manifest` + `serve_service_worker` routes (the latter does the
    same `__APP_VERSION__` substitution as `_render_index_html`); both paths added to `_AUTH_EXEMPT_PATHS`
    (the browser fetches them outside the page auth context; neither leaks private data); `_build_csp()` gains
    `worker-src 'self'` + `manifest-src 'self'` (explicit, not fallback). The PyInstaller spec already bundles
    `frontend/` (`('frontend','frontend')`), so the desktop build ships manifest + sw.js + icons with no spec
    change. Verified: manifest parses, SW registers + controls at root scope, **0 `/api` entries in the cache**
    (58 static assets), theme-color syncs, zero console/CSP errors. Requires a secure context (HTTPS or
    localhost). **iOS storage caveat:** a home-screen web app gets storage separate from Safari, so first launch
    of the installed app can re-show the getting-started tour once (tour-seen is `localStorage`-local, see the
    tour note) — the planned fix is to persist tour-seen in server preferences.
  - Phase 2 (2.34.0) adds `GET /api/works/discovered` (poller-found submissions
    with no publication link, normalized via `build_discovered` over
    `posting.sync.PLATFORM_TABLES`) and `POST /api/works/link` (links one to a
    work via `upsert_publication`). Frontend: the **Discovered** view at
    `#/submissions/discovered` with a per-row work-picker.
  - Phase 3 (2.35.0) adds `POST /api/artwork/import/{platform}/{submission_id}`
    (`posting/artwork_importer.py`): a generic importer that reuses the pollers'
    stored submission metadata + image URL → `create_artwork(source=…)` + links
    it. Frontend: an **Import** button on discovered rows. FA full-res needs a
    residential IP (desktop).
  - Phase 4 (2.36.0): `POST /api/artwork/import/bulk/{platform}` (import all
    discovered for a platform, per-item errors collected) + a per-platform
    "Import all" bar; DeviantArt/Itaku added to `PLATFORM_TABLES`; and an import
    guard — `image_url()` drops the page `url` (adds `thumb_url`) and
    `import_artwork` validates Content-Type/magic bytes so non-images are
    rejected, not turned into broken artworks.
  - **2.90.0 — route-order fix.** `/import/bulk/{platform}` was registered
    *after* the generic `/import/{platform}/{submission_id}`, so Starlette (first
    match wins) captured `/import/bulk/bsky` as `platform="bulk"` → every "Import
    all" hit `Unknown platform: bulk` and the bulk route was unreachable. The
    specific `bulk`/`discovered-art` routes now precede the generic two-segment
    route (with an inline comment guarding the order).
  - **2.91.0 — multi-image import (Bluesky).** A multi-image post now imports as
    **one artwork per image** (titled `… (i/N)`), not just the first. Data flow:
    the Bluesky client collects every embed image's `fullsize` into a
    `media_urls` list (`clients/bsky/client.py`); it's persisted as a JSON array
    in the new `bsky_submissions.media_urls` column (schema + a `db.py` migration;
    existing rows stay `''` until a **Full Resync** re-polls them); the importer's
    `media_url_list(row)` returns that list (falling back to the single
    `image_url()` for older/single-image rows), and `import_artwork` loops it —
    each image → its own `create_artwork` (source `image_index`), the FIRST piece
    carries the publication (`external_id = submission_id`) that clears the
    Discovered bucket, and per-image download failures are collected, not fatal.
    `create_artwork` is still single-image, so this is N artworks, not a gallery.
  - **2.93.0 — multi-image for X + Instagram.** Same `media_urls` pattern extended
    to two more platforms (the importer is platform-agnostic — it just reads the
    column — so only capture + storage changed). **X** (`clients/tw/client.py`):
    collect every `type=="photo"` `media_url_https` from `extended_entities.media`
    (videos/GIFs skipped; quoted-tweet photos used as the fallback, mirroring the
    thumbnail). **Instagram** (`clients/ig/client.py`): `_MEDIA_FIELDS` now requests
    `children{media_url,media_type}`, and a `CAROUSEL_ALBUM` collects each IMAGE
    child's `media_url` (single-media posts have no `children`, so they fall back to
    the one `media_url`/thumbnail unchanged). New `media_urls` column on
    `tw_submissions` + `ig_submissions` (schemas + the shared `db.py` migration loop;
    `tw_queries`/`ig_queries` upserts persist it). Backfill via **Full Resync** as
    with Bluesky. That's Bluesky + X + Instagram covered.
  - 2.37.0: Inkbunny imports now re-fetch the **original** file via the API
    (`_resolve_ib_full_url` → `files[].file_url_full`, reusing the poller's cached
    SID) instead of the thumbnail. SoFurry full-res isn't feasible (the `.data`
    reader exposes no image URL); DA/Itaku remain thumbnail-only.
  - **2.69.0 — discovery/import for all 16 platforms + one-click "import all art".**
    `posting.sync.PLATFORM_TABLES` previously listed only 10 platforms, so the six
    newest (`mast, tum, pix, thr, ig, tw` — **incl. image-first Pixiv & Instagram**)
    were invisible to both discovery and import. All six are now registered (each
    stores a `link` permalink + `thumbnail_url`), so `PLATFORM_TABLES` covers all 16.
    `classify_kind(platform, type_str, has_image=None)` gained an image-presence
    tie-breaker — an inconclusive post that carries an image is classified **art**
    (importable), catching discovered art from any platform instead of leaving it
    "unknown"; pix/ig join the image-first `_ART_ONLY_PLATFORMS`. `build_discovered`
    passes image presence and prefers each row's stored `link` for the external URL
    (the `url_template` is a fallback — wrong for instance-scoped mast/tum URLs);
    `import_artwork` uses `link` for the linked publication too. New
    `POST /api/artwork/import/discovered-art` imports every discovered art item with
    a downloadable image across all platforms (per-item failures collected — FA's
    datacenter-IP block lands FA art in `failed`). Frontend (`submissions.js`): a
    suggestion banner (**Import all art** / **Review →**), a count on the Discovered
    link, and a smart Artwork-segment empty state. New platforms import at the stored
    thumbnail resolution (like DA/Itaku).
- `@app.get("/epub-viewer.html")` route reads the file and substitutes
  `__APP_VERSION__` for cache busting on `tokens.css` + the viewer JS
- Path-scoped `_build_epub_viewer_csp()` relaxation (see Security
  Hardening section above) — without this the iframe renders chapter
  HTML but with no styles or images, since epub.js uses blob: URLs
  for everything it extracts from the EPUB archive

Two non-obvious gotchas:
1. **`ePub(url, { openAs: 'epub' })` is mandatory.** epub.js sniffs
   the URL's *path* extension to pick archive vs. directory mode.
   Our URL is `/api/posting/file?story=...&file=...epub` — the path
   ends in `/file`, not `.epub` (the extension is in the query
   string), so the sniff fails and the loader hangs trying to read
   `META-INF/container.xml` as if the URL were an unzipped directory.
   Forcing `openAs: 'epub'` skips the sniff.
2. **Theme tokens don't cross the iframe boundary.** epub.js renders
   the EPUB into a sandboxed iframe that doesn't inherit CSS custom
   properties from the parent. `epub-viewer.js` resolves
   `--bg-primary`, `--text-primary`, `--accent` from the parent's
   computed style and passes the *concrete colour values* into
   `rendition.themes.default()` — passing `var(--…)` would resolve
   to the iframe's defaults (white / black) regardless of the
   selected dashboard theme.

### Theme System (Styled HTML / PDF)

Each story owns a `CHAPTER_STYLING.md` file declaring its visual
theme — currently 14 colour variables plus the section-break symbol
and warning icon. The canonical template lives at
`m_x/Archives/Complete_Stories/Reference_Guides/Styling/HTML_CSS/STYLING_REFERENCE.md`.

Theme keys (all optional — defaults applied for missing ones):
`BACKGROUND`, `TEXT_COLOUR`, `TITLE_COLOUR`, `BYLINE_COLOUR`,
`ACCENT_COLOUR`, `WARNING_HEADING_COLOUR`, `WARNING_BODY_COLOUR`,
`DISCLAIMER_HEADING_COLOUR`, `STORY_END_COLOUR`, `SIGNATURE_COLOUR`,
`TEXT_SENT_COLOUR`, `TEXT_RECEIVED_COLOUR`, `TITLE_TEXT_SHADOW`,
`SECTION_BREAK_SYMBOL`, `WARNING_ICON`, `PRINT_APPROACH`.

Theme save flow:
1. User edits colour pickers in the editor's Theme panel.
2. `POST /api/editor/stories/{name}/theme` writes the new
   `CHAPTER_STYLING.md` (with `.bak.{ts}` snapshot) and regenerates
   `style.css` next to both `HTML/` and `Chapters/Styled_HTML/`.
3. User clicks Regenerate — Styled HTML files (and PDFs) pick up the
   new CSS automatically.

**Server permission gotcha:** `pawsync.bat` chmod's archive files
`o+rwX` (not just `o+rX`) so the Docker container (uid 1001) can
write theme updates to files owned by `kithetiger` (uid 1000).

### Metadata Editor (Drawer)

A right-side drawer (50vw, slides from right, portal-mounted to
`document.body`) edits `story.json` — the per-story metadata file
that drives platform packages.

Sections (each collapsible, state persisted in `localStorage`):
1. **Basics** — title, author, summary, description
2. **Cover** — drag-drop full-series + per-chapter thumbnails
3. **Classification** — rating, fandom, categories, warnings
4. **Characters & Relationships**
5. **Tags** — per-platform tag lists with autocomplete
6. **Chapter Tags** — per-chapter tag editing (Phase 4b)
7. **Chapters** — title + description per chapter
8. **Advanced** — raw `story.json` JSON view (read-only)

Each save: write to `.tmp` → atomic rename → `.bak.{ts}` snapshot.

### Tag System (Bundled Database + e621 Lookup)

The editor ships a curated tag database at `tag_database/` (NOT under
`data/` — that's a Docker volume that would shadow bundled files):

| File | Tags | Purpose |
|------|------|---------|
| `tag_database_physical.txt` | 1,337 | Body / species / form |
| `tag_database_acts.txt` | 1,270 | Sexual / romantic acts |
| `tag_database_kink.txt` | 788 | Kink / BDSM / fetish |
| `tag_database_meta.txt` | 1,216 | Genre / mood / structure |
| `tag_database_image.txt` | ~3,000 | Visual descriptors (for image tags) |
| `tag_database_user.txt` | grows | User-added tags via "+ Library" |
| `tag_aliases.json` | 23,159 | Synonym → canonical mapping |
| `e621_lookup.tsv` | 26,829 | Fallback lookup when local DB has no match |

**Autocomplete flow** (in `frontend/js/metadata_editor.js`):
1. User types in the per-platform tag input.
2. Local fuzzy match against tag database + aliases. Top results
   shown in a portal-mounted dropdown.
3. If local matches < 5 AND query >= 3 chars, fire debounced (300ms)
   `GET /api/editor/tags/lookup?q=<str>` for e621 results.
4. e621 results show with violet "e621" category chip + post count.
   Three actions per row: **+ Library** (default target by
   category), caret menu (explicit target), **Use once** (apply to
   current platform without persisting).

**Cross-platform sync** (story-level only, not per-chapter):
Adding a tag to **Default** cascades to SF/IB/Wattpad with
platform-specific transforms (underscores → spaces for SF, camelCase
for Wattpad, etc.). Adding directly to a specific platform's tab
applies to that platform only.

**Per-chapter tag platforms**: `_CHAPTER_TAG_PLATFORMS` now includes
`inkbunny` alongside `default`, `sofurry`, and `wattpad`, matching the
story-level tag editor.

**Tag format correction**: `_transformTagForPlatform()` fixed so FA
and Weasyl correctly keep underscores (were wrongly converting to
spaces). Space-to-underscore auto-conversion fires in real-time on
Default/FA/Weasyl/Itaku tag inputs.

**Tag management buttons**: "Fix spaces" bulk-replaces spaces with
underscores in all underscore-platform tags (story + chapter level).
"Sort A-Z" sorts tags alphabetically across all platforms.

**Tag browser enhancements**: "Selected" filter chip shows only
currently-selected tags with descriptions. Platform badges (DEF, SF,
IB, AO3, etc.) appear on each tag card showing which platforms have
that tag.

### Regenerate Endpoint

`POST /api/editor/stories/{name}/regenerate` rebuilds every derivative
file from `MASTER.md`. Sequence:

1. Full-story Clean HTML → `HTML/{stem}_Clean.html`
2. Full-story SoFurry HTML → `HTML/{stem}_SoFurry.html`
3. Full-story BBCode → `BBCode/{stem}_bbcode.txt`
4. SquidgeWorld per-chapter HTML → `SquidgeWorld/Chapter_*.html`
5. Styled HTML — generates `style.css` + full + per-chapter into
   `HTML/` and `Chapters/Styled_HTML/`
6. **PDFs** (if `skip_pdf=False`, default) — full + per-chapter via
   `editor.pdf_generator.html_to_pdf()`
7. Chapter splits — Markdown, Clean HTML, BBCode → `Chapters/{Markdown,SoFurry_HTML,BBCode}/`

Returns `{ok, results: [...], errors: [...], word_count}`.

### Selective Format Regeneration

The Regenerate button includes a dropdown with options for All formats, HTML, BBCode, Styled HTML + CSS, SquidgeWorld, PDF, EPUB, and Chapter splits. The backend `RegenerateRequest.formats` field accepts a list of format keys and filters which conversion steps run, avoiding unnecessary rebuilds when only one format has changed. The toolbar also has a separate Downloads ▾ menu that lists every output format with its file size plus a "Download all (zip)" footer that streams the entire story folder via `/api/posting/archive` — convenient for grabbing an EPUB or PDF onto a phone for proofreading.

### Regenerate All Stories (2.20.0+)

Bulk rebuild of every story's derived formats from each `MASTER.md`,
exposed as a single editor button and a diagnostics test. Two surfaces
backed by one orchestrator:

- **Editor button.** `↻ Regenerate All` in the story-list header (next
  to "+ Create New Story" / "Import"). Opens an overlay with a "Skip
  PDF" checkbox (default on). Start kicks off the run and the overlay
  flips to a live log: per-story stamps, pass/partial/fail counts,
  progress bar, elapsed timer.
- **Diagnostics test.** `archive.regenerate.all_stories` in
  Settings → Diagnostics → Archive. Destructive (opt-in per-test
  confirm), `skip_pdf=True` always so the suite stays inside the
  15-min per-test timeout. Reports per-story pass/partial/failed
  counts + failures list.

**Endpoints** in `routes/editor_api.py`:

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/editor/regenerate-all` | Start a bulk run. Body: `{skip_pdf: bool}`. Returns `{run_id}`. |
| GET | `/api/editor/regenerate-all/active` | Reattach probe — returns `{active: bool, run_id?}`. |
| GET | `/api/editor/regenerate-all/stream/{run_id}` | SSE: `story_start`, `story_end`, `log`, `complete` events. 15s heartbeats + event-buffer backfill so reconnects don't lose history. |
| POST | `/api/editor/regenerate-all/cancel/{run_id}` | Graceful stop — current story finishes, loop exits. |

**Architecture.** Thin orchestrator calls the existing per-story
`regenerate()` endpoint in-process for each story, so single-story
behaviour stays the single source of truth and bug fixes don't have to
land twice. A module-level `threading.Lock` prevents two bulk runs at
once (returns 409 with the active `run_id` so the frontend can attach
to the existing stream).

**PDF safety net (2.20.5).** Each `html_to_pdf()` call is wrapped in
`asyncio.to_thread(...)` so WeasyPrint's CPU-bound render runs on the
threadpool executor instead of blocking the event loop. Before this
fix, the dashboard froze for the ~30-80s/story PDF render and polling
ticks were skipped for the entire 20+ min bulk run.

**Single-chapter EPUB fallback (2.20.4).** Stories whose `MASTER.md`
has chapter boundaries only in `chapters.json` (legacy from before the
editor existed) used to fail with "No chapters found in MASTER.md
after body anchor". Defensive fallback in
`editor/epub_generator.py:_split_into_chapters`: when no `# Chapter X`
headings exist but `<!-- @body -->` content does, treat the whole body
as one synthetic chapter using the story title. Multi-chapter stories
with proper headings are unaffected. Companion rescue tool at
`scripts/inject_chapter_markers.py` reads `chapters.json` +
`Chapters/Markdown/Chapter_*.md` to anchor each chapter in MASTER.md
and inject `# Chapter N: Title` headings at the right positions.
Idempotent; backs up MASTER.md → .bak; sorts by extracted numeric N
so chapter 10 lands after 9 not between 1 and 2.

### Phone Display / Text Message Styling (2.21.1+)

Stories with phone-call caller IDs (`**ETHAN ❤**`) and SMS-style text
messages (`**Name:** message`) get rendered as styled phone-bubble UI
in SquidgeWorld and Styled HTML. Two paths produce this:

- **Semantic anchors** (explicit). MASTER.md uses
  `<!-- @phone-incoming -->`, `<!-- @text-sent -->`,
  `<!-- @text-received -->` on the line before the content. The
  anchor branch in `editor/converter.py:_convert_body_clean_html`
  emits `<div class="phone-display-wrap"><div class="phone-display">…</div></div>`
  and `<div class="text-message {sent|received}">…</div>`.
- **Heuristic fallback** (no anchors required). Same converter
  detects `**NAME ❤**` and `**Name:** message` patterns via
  `is_phone_display` and `is_text_message`. Before 2.21.1 the
  heuristic emitted plain `<p><strong>…</strong></p>` and stories
  without explicit anchors silently lost their Work Skin styling.
  2.21.1 made the heuristic emit the same div structure as the
  anchor branch. Without explicit anchors we can't tell sent from
  received, so heuristic text-messages get no modifier and inherit
  the Work Skin's base `.text-message` rule.

Companion fix in `m_x/Scripts_Utils/regenerate_story.py`
(`apply_phone_text_styling()`) — that script builds SqW + Styled HTML
output from the SoFurry HTML body, not from PawPoller's converter, so
the same post-process pass had to land in both code paths.

### Format Tab Bar

The output format selector in the editor preview pane was changed from a `<select>` dropdown to an inline tab bar (`<div class="format-tabs">` with four `<button class="format-tab">` elements). All four formats (Clean HTML, SoFurry, BBCode, Styled HTML) are now visible at a glance as clickable buttons with an active highlight.

### PDF Generation

`editor/pdf_generator.py` provides `html_to_pdf(html_path, pdf_path)`
returning `(success, backend_used)`. Two backends, picked
automatically:

| Backend | Where it works | Notes |
|---------|----------------|-------|
| **WeasyPrint** | Linux/Docker (and Windows with GTK runtime) | Pure Python. Resolves `style.css` and images via `base_url=html_path.parent`. Server-side rendering — no desktop required. |
| **Edge headless** | Windows (auto-probed at standard install paths) | Subprocess: `msedge --headless --no-margins --print-to-pdf=...`. Used when WeasyPrint can't import its native libs. |

Server (Docker) installs WeasyPrint's deps via `apt-get`:
`libpango-1.0-0`, `libpangoft2-1.0-0`, `libharfbuzz0b`, `libcairo2`,
`libgdk-pixbuf-2.0-0`, `libffi8`, `fonts-dejavu-core`. ~50 MB image
growth.

`get_backend()` reports the active backend for diagnostics —
`weasyprint` / `edge` / `none`.

### Slop Scoring (Optional)

`editor/slop.py` exposes the EQ-Bench slop scorer used by the writing
guide pipeline. The editor surfaces this for any open story but it's
not required for regeneration — it's a quality signal, not a gate.

### Publish Check Matrix

`GET /api/editor/stories/{name}/publish-check` returns a chapter × platform
matrix showing where a story can be published. The matrix UI (Publish
button on the editor toolbar → modal) renders:

- **Rows**: always starts with a **Full story** row; chaptered stories
  append per-chapter rows.
- **Columns**: 9 platforms (IB, FA, WS, SF, SQW, AO3, DA, IK, BSky).
- **Cells**: each is one of these states, each colour-coded:
  - `ready` (green ✓) — validation passes, no prior publication
  - `posted` (blue ✓) — already posted to this platform, external URL known
  - `posted_drifted` (violet ↑) — posted but local file hash differs from
    what was uploaded; hit Update to push fresh content
  - `posted_stale` (orange !) — posted but package no longer validates
  - `deleted_upstream` (red ⊘) — publication was detected deleted on the
    platform; hit Re-post to create a fresh submission
  - `ready_retry` (orange ↻) — previous attempt failed, current package is valid
  - `failed_prev` (red ✗) — blocked + prior attempt failed
  - `not_supported` (grey –) — work-oriented platforms (AO3, SQW) show
    grey dashes on per-chapter rows because they post whole works
  - `no_credentials` (grey 🔒) — platform has no credentials configured;
    action panel shows "Set up in Settings" message. The `PLATFORM_CREDS` map
    in `editor_api.py` (`publish_check`) declares each platform's required
    settings keys and is checked before the matrix loop. **Keep it in step with
    what the poster actually reads** — e.g. SqW is an OR-of-ANDs
    `(sqw_author_username, sqw_author_password)` OR `(sqw_username, sqw_password)`
    because `squidgeworld.py` resolves `sqw_author_* OR sqw_*`; requiring only
    the author keys (which the standard connect flow doesn't set) wrongly locked
    a working SqW config (fixed 2.122.0).
  - `error` (red ⚠) — poster init / package build threw
  - `blocked` (red ✗) — fresh cell with validation errors

**Work-oriented vs per-chapter** (`WORK_ORIENTED = {"ao3", "sqw"}`):
OTW-Archive-family platforms post a whole work containing N chapters;
per-chapter rows show `not_supported` with the hint to use the Full story
row. For IB/FA/WS/SF/DA/IK/BSky each chapter is a separate submission so
every row is actionable.

**Drift detection**: cells that were `posted` are cross-checked against
the current file hash via `posting.sync.hash_file()`. Mismatch flips to
`posted_drifted`. Stored hash comes from `publications.file_hash` recorded
at post time. Tag-only platforms (IK, BSky) skip the drift check.

### Per-Cell Publish Controls (2.21.0+)

The expanded-cell drawer carries three repair affordances for when
PawPoller's stored state diverges from upstream reality. All three sit
under the "Existing publication" block when one exists; they target the
single (story, chapter, platform) row, never the upstream.

- **Set URL manually.** Paste a live submission URL; the backend regex
  in `routes/editor_api.py:_URL_ID_PATTERNS` (covers all 11 platforms)
  extracts the external ID. Both `publications.external_url` and
  `publications.external_id` are overwritten via
  `PUT /api/editor/stories/{story}/publication`. Use when PawPoller's
  stored URL is wrong but the submission exists — drift detection and
  Edit calls then target the correct submission.
- **Forget this publication.** Deletes the local `publications` row
  for the cell; does NOT touch the upstream. Reverts the cell to
  `ready` so the next post creates a fresh submission instead of
  editing a phantom one. Confirmed via `prompt()` requiring the user
  to type the platform code; backend also requires
  `confirm_platform=<platform>` query param.
  `DELETE /api/editor/stories/{story}/publication`.
- **Cancel scheduled (per-row + bulk).** The scheduled-items list
  under the action panel got two fixes in 2.21.0:
  - Per-row Cancel button was hidden client-side for non-`pending`
    rows; backend `cancel_queue_item` has handled
    pending/processing/failed since 2.20.3, so the gate was
    widened.
  - When the cell has >1 scheduled item, the header gets a
    "Cancel all (N)" button calling
    `DELETE /api/editor/stories/{story}/scheduled?platform=&chapter=`
    backed by `posting_queries.cancel_all_for(..., chapter_index=...)`.

### Activity Spinner + Toasts (2.22.1+)

Universal UI feedback for every fetch in the dashboard. Lives in
`frontend/js/loading_indicator.js` + `frontend/css/loading_indicator.css`;
no markup changes required at call sites.

- **Top-right dot-ring spinner.** Module wraps `window.fetch` once
  (idempotent against hot reload) and tracks an in-flight counter.
  When the counter is >0, a subtle 18px purple ring appears after a
  250ms delay (so trivially-fast requests don't flash). A badge shows
  the count when >1 request is live. SSE via `EventSource` bypasses
  the wrap, so long-lived regen/diagnostics streams don't pin the
  spinner on.
- **Bottom-right toast stack.** `window.toast.{success,error,warn,info}`.
  Auto-dismiss 4s success/info or 6s error/warn; click ✕ to dismiss
  earlier; newest on top; slide-in/out transitions. Wired into the
  highest-traffic publish handlers in `publish_check.js` —
  `_executeAction`, `_submitSchedule`, the URL-anchor handler, the
  forget-publication handler — each toast carries
  action + platform + chapter context.
- **`window.withLoading(btn, asyncFn)`.** Opt-in per-button helper:
  disables the button, swaps its label for a 12px spinner, preserves
  the button's width so layout doesn't jump. Not auto-applied — some
  buttons already have their own progress patterns.

The JS loads BEFORE `utils.js` in `index.html` so the `fetch` wrap is
in place before any other module fires a request.

### Publish Action Panel

Clicking any matrix cell opens the detail panel with the package summary
(title, tag count, file path + size, mode requirement, edit support,
existing publication URL) and action buttons per cell state:

- **Dry Run** — always available. Fires `POST /api/editor/stories/{name}/publish`
  with `action="dry_run"`. Rebuilds the `StoryUploadPackage` and returns
  it as JSON so you can inspect the exact payload that would be posted.
  No external HTTP.
- **Post** — visible on `ready` / `deleted_upstream` cells. Calls
  `manager.post_story()`. Confirmation dialog spells out platform + draft
  state; backend requires `confirm_live=True` in the request body.
- **Update all** — visible on `posted` / `posted_drifted` cells.
  Calls `manager.update_story()` with no extras — pushes metadata AND
  content via the platform's `edit()` path. Primary-styled when drifted.
- **Metadata only** — visible on `posted` / `posted_drifted` cells.
  Same path but `extras={"skip_content_refresh": True}`. IB / SF / FA
  skip the file re-upload; AO3 / SQW iterate chapters to push title
  changes via `edit_chapter(content=None)` which preserves bodies. WS
  ignores the flag (API can't replace file anyway) but returns a soft
  warning in the result.
- **Re-post** — visible on `deleted_upstream` cells. Goes through
  `post_story()` (not edit), creating a fresh submission.
- **Open** — external link to the live URL when one exists.

Verify posted button at the modal footer walks every `posted` publication
for the story and calls `poster.probe_exists()` to detect upstream
deletions. Confirmed deletions are flipped to `status='deleted'` in the
registry; the matrix reloads and deleted cells flip to ⊘.

**Live-publish warning**: Unchecking "Save as draft" reveals a yellow warning banner: "LIVE PUBLISH -- This will be immediately visible to the public." The `confirm()` dialog includes an extra warning paragraph.

**Action result log**: Every post/update/dry-run action is recorded in a session-scoped log array (max 20 entries) rendered below the detail panel. Compact timestamped list with success/fail icons, platform names, and external links. Survives cell clicks and matrix reloads; clears on page refresh.

**Relative timestamps**: The "Posted" and "Last updated" fields show a relative suffix (e.g. "2026-04-17 14:30 (2d ago)") via `_relativeTime()`.

**Readable dry-run results**: Dry-run output is now a structured summary (title, rating, word count, file info, tag list) instead of raw JSON. Raw JSON still available under a collapsible.

### Regen Staleness Warning

The Publish Check compares `MASTER.md` mtime against the newest generated file's mtime. When the source is newer than the derived formats, an amber banner appears at the top of the matrix with an inline "Regenerate now" button. This prevents publishing stale formats that don't reflect the latest edits.

### Per-Platform Descriptions

The Metadata Drawer's Basics section includes a collapsible "Per-platform descriptions" panel with two textareas:
- `descriptions.short` — for IB/SF listings (1-2 sentences).
- `descriptions.announcement` — for Bluesky announcements (300-character limit).

Stored in `story.json`. `build_package()` uses a fallback chain: platform-specific description > short description > main description.

### Per-Chapter Thumbnails

`POST /api/editor/stories/{name}/chapter-thumbnail` accepts a per-chapter cover image upload. Stored in `story.json` at `images.chapter_thumbnails.{index}`. The Metadata Drawer's Cover section supports drag-drop for both the full-series cover and per-chapter thumbnails.

### Create New Story Wizard

`POST /api/editor/stories/create` scaffolds a new story with the full folder structure (Markdown, BBCode, HTML, PDF, SquidgeWorld, Chapters/*, Images). Generates a template `MASTER.md` showing all anchor types, writes `story.json` with default metadata, and copies `STYLING_REFERENCE.md` as `CHAPTER_STYLING.md` when available. The editor's story list shows a "+ Create New Story" button that opens an overlay dialog with title, folder name (auto-generated), author, chapter count, and rating fields.

**Genre templates**: Optional genre dropdown pre-fills tags, rating, warnings, and category from 9 presets (romance, erotica, adventure, comedy, drama, fantasy, sci_fi, slice_of_life, horror). `GET /api/editor/genre-templates` returns the full preset dict. User-supplied rating always overrides the template default.

**File upload**: Optional file input accepts `.md`, `.txt`, `.html`, `.bbcode`, `.rtf`. Uploaded content replaces the template `MASTER.md` with proper anchor wrapping. Format converters: `_convert_html_to_md()` (strips tags, preserves headings/bold/italic/hr), `_convert_bbcode_to_md()` (strips BBCode tags), `_strip_rtf()` (strips RTF control codes). Markdown and plain text are used as-is.

### Import from Platforms

`posting/importer.py` downloads submissions (published *and* unposted drafts) from platforms and creates local story folders. The editor's story list shows an "Import from Platform" button; the dialog also has an "Import by URL or ID" row at the top so draft IDs can be pasted directly (the auto-list only surfaces what the pollers have seen, which is published-only).

**Supported platforms:**
- **Inkbunny**: `import_from_inkbunny()` — fetches submission details via API with `show_writing=yes`, downloads BBCode text file (follows CDN redirects), converts BBCode→Markdown via `_bbcode_to_markdown()`. Drafts are reached transparently — `api_submissions.php` returns owner drafts the same shape as published works; the importer flags `is_draft = (public == "no")`.
- **SoFurry**: `import_from_sofurry()` — fetches metadata from `/ui/submission/{id}` JSON API, scrapes story content from the `/s/{id}` page (extracted after the chapter divider in `story-content-holder`), converts HTML→Markdown via `_html_to_markdown()`. Draft state inferred from `publishedAt` (null / empty / `0000-…` / future ISO date); a non-200 `/s/{id}` page-scrape on a draft falls back to the JSON description rather than failing the import.
- **FurAffinity**: `import_from_furaffinity()` — fetches submission details from FAExport API, downloads story file via `download_url` (TXT files get full text; PDF files get description fallback since PDF parsing is not included). FA exposes no draft API surface, so this path is published-only.
- **AO3 / SquidgeWorld** (shared OTW Rails markup): `import_from_ao3()` and `import_from_squidgeworld()` use the shared `_parse_otw_work_page()` helper to extract title / author / summary / rating / tags / chapters from a single `?view_full_work=true` round trip. Both try `/works/{id}?view_full_work=true&view_adult=true` first and fall through to `/works/{id}/preview?view_full_work=true&view_adult=true` for unposted drafts (AO3 detects via 404; SqW detects via missing title-heading + userstuff markers because `_get_page` swallows status through the Anubis solver). SqW additionally routes through `client._get_page()` to transparently solve the Anubis PoW bot challenge.

**Endpoints:**
- `GET /api/editor/import/available` — cross-references polled submissions against local archive `import_source` metadata to find importable published submissions.
- `POST /api/editor/import/{platform}/{submission_id}` — triggers download + folder creation, returns `{story_name, title, is_draft}`.

**Folder creation** (`_create_story_folder()`): creates full archive structure, generates `story.json` with `import_source` provenance (platform, submission_id, url), saves original format file alongside `MASTER.md`. Name collisions handled by appending `_2`, `_3` suffix.

**UI affordances**: the import overlay's manual-entry input accepts platform-prefixed (`ao3:12345`, `ib:12345`) and full URLs (`https://archiveofourown.org/works/12345`, `https://inkbunny.net/s/...`, etc.). Imported drafts get an amber row tint plus a "Done (draft)" button label so they're distinguishable from published imports at a glance.

### Setup Wizard (Phase 9a)

First-run detection: when no `setup_complete` flag exists in `settings.json`, the dashboard redirects to a 4-step guided wizard (Welcome, Story Archive location, Platform Connections, Done). Existing users are unaffected.

- `GET /api/settings/setup-status` — returns setup completion state, archive path presence, and count of connected platforms.
- `POST /api/settings/setup-complete` — marks setup as done so the wizard is not shown again.
- `renderSetupWizard()` in `app.js` drives the step UI with platform card grid and connecting-line step indicators.

### Embedded Browser Login (Phase 8a)

`auth/browser_login.py` provides pywebview-powered browser login for cookie-based platforms. In desktop mode, users click "Login via Browser" and a native popup opens the platform's real login page; after logging in, cookies are detected and saved automatically. Server mode falls back to helpful login-page links.

- `PLATFORM_LOGIN` configs for these platforms (IB, FA, SF, TW, WS, AO3, SqW) with URL, success conditions, and cookie-to-setting mappings. FA / SF / TW capture real auth cookies; IB / WS / AO3 / SqW are verification-only because their APIs need username+password (or API keys) rather than session cookies. (DeviantArt polling moved to app client-credentials in 2.47.0, so DA no longer uses browser-login for polling — the DA poster uses OAuth2 and a legacy cookie fallback exists, but neither is wired through this popup.)
- `login_via_browser()` calls `webview.create_window()` against the dashboard's already-running pywebview GUI loop — it MUST NOT call `webview.start()` itself (only one `start()` per process is allowed, and on Windows it must be the main thread, both of which `main.py:924` already owns). A top-of-function guard returns `RuntimeError` if `webview.windows` is empty (i.e. no GUI loop). The cookie poller runs in a daemon thread; the cancel path is driven by the window's `closed` event; a 5-minute timeout fires `window.destroy()` if the user walks away. Credentials are saved via `config.save_settings()` once the success_check passes. (Pre-2.18.13 the function called `webview.start()` from a daemon thread, which fails with `pywebview must be run on a main thread` on first attempt — the old wrapper-thread + second-`start()` pattern is the bug 2.18.13 fixes.)
- `GET /api/settings/browser-login/platforms` — lists supported platforms with availability flag (True in desktop mode only).
- `POST /api/settings/browser-login/{platform}` — launches the popup and blocks until login completes or window closes. Runs in `run_in_executor` to avoid stalling the event loop.
- Dashboard: FA and TW platform connect forms show "Login via Browser" as primary action in desktop mode, with a "Enter cookies manually" toggle for the existing cookie input form. (DeviantArt's connect form is now client_id/secret since 2.47.0 — it no longer offers browser-login/cookies for polling.)

### Theme-Save Trailing Content

`POST /api/editor/stories/{name}/theme` writes `CHAPTER_STYLING.md` with
the new variables table between `<!-- THEME_VARIABLES_START -->` and
`<!-- THEME_VARIABLES_END -->` markers. Any user-authored content AFTER
the end marker (notes, credits, extra sections) is preserved by a
`after = existing[existing.index(marker_end) + len(marker_end):]` split;
earlier versions silently wiped this content on every save.

---

## 16. Diagnostics & Testing Tab (2.19.0+)

A unified in-app testing suite that catalogues ~82 bespoke live-system
tests plus the existing pytest suite (parsed as ~91 child results), all
runnable from a single tab in Settings → Diagnostics with per-test /
per-category / full-suite run buttons and live SSE-streamed progress.

The motivation: every subsystem of PawPoller has its own way of being
exercised (one of 11 `/auth/connect` endpoints, one of 11
`/poll/trigger` endpoints, the Telegram test endpoint, pytest CI, etc.),
and there was no top-level "is everything healthy?" view. Diagnostics
gives that view in one place.

### Architecture

```
testing/
├── __init__.py
├── registry.py         # @register_test decorator, TestResult, REGISTRY dict
├── runner.py           # async run_one / run_category / run_suite
├── streamer.py         # Per-run in-memory event buffer + SSE generator
├── store.py            # data/diagnostics_results.json (last 10 runs)
└── tests/
    ├── __init__.py     # Imports every test module so @register_test fires
    ├── infra.py        # 12 tests: DB / settings / vault / disk / tag DB
    ├── platforms.py    # 22 tests: 11 auth + 11 poll-discovery
    ├── editor.py       # 10 tests: converter / EPUB / PDF / theme / anchors
    ├── story_reader.py # 6 tests: archive / build_package / resolution
    ├── posting.py      # 9 tests: dry-run validate per posting platform
    ├── auth.py         # 6 tests: bcrypt / TOTP / API key / session / rate-limit
    ├── external.py     # 5 tests: CF proxy / Telegram / GitHub / Turnstile
    ├── scheduling.py   # 5 tests: scheduler threads / queue filters
    ├── notifications.py # 3 tests: telegram_send (destructive) / toast / digest
    ├── archive.py      # 3 tests: readable / story.json valid / pawsync dry-run
    └── pytest_runner.py # 1 test that runs pytest and expands to ~91 children
```

### Registry pattern

```python
# testing/registry.py
@dataclass
class TestResult:
    test_id: str
    name: str
    category: str
    status: Literal["passed", "failed", "skipped", "errored", "running", "pending"]
    duration_ms: float
    message: str = ""
    details: dict | None = None
    logs: list[str] = field(default_factory=list)
    destructive: bool = False
    requires_creds: list[str] = field(default_factory=list)

REGISTRY: dict[str, TestSpec] = {}

def register_test(id, name, category, *, description="",
                  destructive=False, requires_creds=None):
    """Decorator. Async function returning TestResult or raising on error."""
    ...
```

### Event streaming (SSE)

`testing/streamer.py` exposes a per-run async event queue. The runner
emits events; the SSE endpoint pumps them to the client. Event types:

- `{event: "suite_start", run_id, total, started_at}`
- `{event: "test_start", test_id, name, category, idx, total}`
- `{event: "log", test_id, level, message, timestamp}`
- `{event: "test_end", test_id, status, duration_ms, message, details}`
- `{event: "suite_complete", summary: {passed, failed, skipped, total, duration_ms}}`

15s heartbeat ping so reverse-proxy intermediates don't close the stream.
A per-run event buffer means late-joiners (refresh, second tab) get the
full history backfilled before live events start arriving.

### API (`routes/testing_api.py`)

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/testing/tests` | Full registry — id, name, category, description, destructive flag, last result. |
| GET | `/api/testing/last-results` | Last persisted run summary + per-test results. |
| GET | `/api/testing/active` | `{active: bool, run_id?}` — for reattach. |
| POST | `/api/testing/run/{test_id}` | Run one test. Returns `{run_id}`. |
| POST | `/api/testing/run-category/{category}` | Run all tests in a category. Body: `{include_destructive: [...]}`. |
| POST | `/api/testing/run-suite` | Run full suite. Body: `{include_destructive: [...], skip_categories: [...]}`. |
| GET | `/api/testing/stream/{run_id}` | SSE event stream. |
| POST | `/api/testing/stop/{run_id}` | Request graceful cancellation. |

All endpoints sit behind the existing dashboard session auth.

### UI

Settings → Diagnostics tab (`frontend/js/diagnostics.js` +
`frontend/css/diagnostics.css`). Two-pane layout:

- **Left — test catalog.** Sticky search box + status filter chips
  (All / Passed / Failed / Skipped / Destructive). Category accordions
  for the 12 categories. Each row: status icon, name, last duration,
  Run button, expand for details/logs.
- **Right — live log + summary.** Sticky run-summary card (X of Y, Z
  passed, W failed, progress bar, elapsed time). Action bar: Run All,
  Run Failed, Stop, Clear Log, Download Log, Copy Results. Log line
  filter chips. `<pre>` with auto-scroll-on-new (toggleable), 5000-line
  in-memory cap.

### Concurrency + safety

- **One run at a time** — module-level `threading.Lock` in the runner;
  a second run request returns 409 with the active `run_id` and the
  frontend switches to spectator mode on the existing stream.
- **Per-test timeout** — default 30s; tests that need longer (e.g.
  AO3 auth at 3s + probe) declare their own.
- **Cleanup hooks** — tests that mutate state (queue insert, settings
  marker) wrap in try/finally so cleanup runs on failure.
- **Destructive gating** — route layer refuses to run a destructive
  test unless `confirm_destructive: true` is in the request body. The
  frontend asks for per-test confirmation. Run-all auto-skips
  destructive tests unless the user explicitly opts in.
- **Run history** — last 10 runs kept in `data/diagnostics_results.json`;
  older entries rotated out. Persists across container rebuilds (same
  volume as `pawpoller.db`).
- **Rate-limit pacing** — platform-auth tests sleep
  `{P}_REQUEST_DELAY_SECONDS` between platforms when run as a category
  or suite, so we don't burst into AO3's 429 wall.

### Test inventory (categories)

| Category | Count | What it exercises |
|---|---|---|
| Infrastructure | 12 | DB integrity, WAL mode, foreign keys, settings round-trip, vault crypto, disk space, log writes, tag DB files. |
| Dashboard Auth | 6 | Bcrypt, TOTP, API key SHA-256, session cookie sign/unsign, escape_html, rate-limiter (isolated instance). |
| Platforms · Auth | 11 | One per platform — validate `/auth/connect` logic without UI side effects; skipped if creds missing. |
| Platforms · Polling | 11 | One per platform — call the gallery-discovery method, report submission count. |
| Editor / Converter | 10 | MD→Clean HTML, MD→SoFurry HTML, MD→BBCode, SqW chapter split, Styled HTML chapter end-marker (regression for 2.18.20), EPUB spine, PDF backend availability, theme parser, anchor parser. |
| Story Reader | 6 | Archive path resolves, has_stories≥1, load_story, build_packages_all_platforms, format resolution chapter≠full-story (regression for 2.18.19), manifest parsing `number` key. |
| Posting Dry-Run | 9 | One per posting platform — build package, `poster.validate(package)`. No network upload. |
| External Services | 5 | CF Worker proxy ping, Telegram getMe, GitHub latest_release (PAT-aware), Turnstile reachable. |
| Scheduling & Queue | 5 | Poll orchestrator + posting scheduler + Telegram bot thread alive; queue `requires` filter regression (2.18.16); `scheduled_at` gate. |
| Notifications | 3 (all destructive) | Telegram test message, Windows toast (desktop only), digest builder data-fetch. |
| Archive | 3 | Local archive readable, story.json valid across every story, pawsync dry-run subprocess. (2.20.0 added `archive.regenerate.all_stories` here too.) |
| Pytest Suite | 1 → ~91 children | Subprocess `pytest tests/ -v` parsed via regex; child outcomes expand under a "Pytest Suite" accordion. |

Grand total: **~82 bespoke + ~91 pytest = ~170 test rows** visible in
the UI.

### Out of scope (explicitly)

- Scheduled / cron-triggered diagnostic runs. Doable as follow-up.
- Email / Slack alerts on failures.
- Per-test trend graphs across runs.
- "Run on every PR" CI integration — the existing GitHub Actions
  `pytest` already covers static code; Diagnostics is a runtime tool,
  not a CI gate.

---

## 17. PawPoller CLI (2.22.0+)

A menu-driven Python TUI under `cli/pawpoller_cli.py` that talks to a
PawPoller server over the same HTTP API as the dashboard. Same script
runs locally (against the GCP VM) or on the VM itself (against
127.0.0.1) with identical UX.

### Goals

- Anything you can do without rendering a story body should be doable
  from the CLI — polling control, queue ops, publishing, diagnostics,
  story regen.
- Drop-in for SSH workflows where opening a browser is overkill.
- No new auth surface — uses the existing `pp_…` API keys.
- Single file, two deps (`rich`, `httpx`), runs on any Python 3.10+.

### Files

```
cli/
├── pawpoller_cli.py     # ~1100 LOC single-file TUI
├── requirements.txt     # rich >= 13, httpx >= 0.27
├── pp.cmd               # Windows launcher (calls python pawpoller_cli.py)
└── pp.sh                # Unix launcher (used on the VM)

deploy/
└── pawcli.bat           # One-command Windows wrapper: SSHes into the
                         # VM with -t and launches pp.sh as kithetiger.
```

### Config resolution

In order:

1. Env vars `PAWPOLLER_URL` + `PAWPOLLER_KEY`.
2. `~/.pawpoller-cli.json` — created on first run via the setup prompt.
3. VM fallback hint: the SQLite `api_keys` table stores only hashes,
   not plaintext keys, so the CLI prints a message asking the user to
   run `python pawpoller_cli.py setup` and paste the key manually.

### Top-level menu

```
PawPoller CLI                                  [○ Healthy]
─────────────────────────────────────────────────────────
Polling: live · Queue: 3 pending · Diagnostics: idle

  1. Polling
  2. Publishing & Queue
  3. Diagnostics
  4. Stories
  5. Settings & Status
  q. Quit
```

Each section is a numbered submenu. Pickers (story / platform / chapter
/ test) display as numbered tables and accept `1-N` or `q` to go back.
Long-running operations (regen, diagnostics suite) attach to the SSE
stream and render live with per-event colour coding; Ctrl-C detaches
without cancelling the server-side run.

### Submenu coverage

| Section | Actions |
|---|---|
| Polling | Status (per-platform progress table), pause/resume toggle, trigger one platform, full resync. |
| Publishing & Queue | View queue, cancel queue item, publish matrix grid, post / update / update_metadata / dry-run with draft + live-publish confirmation, schedule, forget publication, set URL manually. |
| Diagnostics | Last results summary + failures, run one test, run category, run full suite, attach to active run. SSE-streamed with per-test status colours. |
| Stories | List with chapter/word counts, regen one (with PDF toggle), regen all (SSE-streamed bulk progress + Ctrl-C detach), publish matrix, probe drafts. |
| Settings & Status | Ping (latency), view posting settings, list API key prefixes, show current CLI config, re-run setup. |

### Tech

- **`rich`** — `Table`, `Panel`, `Prompt`, `Confirm` for menus + tables
  + colours.
- **`httpx`** — sync client for normal requests; `client.stream("GET", path)`
  for SSE. Hand-parses `data: …` lines as JSON; ignores comments and
  empty events.
- **Idempotent helpers** — `pick_from(label, options)`,
  `numbered_menu(title, items)`, `withLoading` button helper.
- **Error display** — `show_error()` unwraps `HTTPStatusError` to print
  the API's `detail` field instead of a stack trace.

### Deployment

**Local**:
```cmd
pip install -r PawPoller\cli\requirements.txt
python PawPoller\cli\pawpoller_cli.py
```

**On the VM** (already installed via `git pull` in the v2.22.0 deploy):
```bash
sudo -u kithetiger python3 -m pip install --user --break-system-packages \
    -r /home/kithetiger/PawPoller/cli/requirements.txt
chmod +x /home/kithetiger/PawPoller/cli/pp.sh
echo 'alias pp=/home/kithetiger/PawPoller/cli/pp.sh' >> ~/.bashrc
```

**One-command launch from Windows** (`deploy/pawcli.bat`):
```cmd
gcloud compute ssh pawpoller --zone=us-east1-c --ssh-flag="-t" \
    --command="sudo -u kithetiger -i /home/kithetiger/PawPoller/cli/pp.sh"
```

With `C:\Users\rhysc\claude\PawPoller\deploy` on the user PATH, typing
`pawcli` from any cmd window SSHes in and drops straight into the menu.

### Out of scope (v1)

- Story body editing — the menu intentionally has no rich-text editor;
  use the web editor.
- Auto-launch on SSH login — one-line `.bashrc` follow-up if wanted.
- API key / TOTP setup — stays in the web UI for the security flow.
- Real-time `app.log` tailing — would need a streaming log endpoint
  the dashboard doesn't expose yet. *(Done in 2.23.0 — see section 18.)*

---

## 18. Dashboard UX Layer (2.23.0+)

The 2.23.0 release added a dedicated UX surface on top of the existing
SPA. Nothing in `polling/`, `database/`, or `*_client/` changed —
this is a frontend + thin-API addition that makes existing state
visible. If you're chasing a "why didn't anything happen when I
clicked?" bug, this section is where it lives.

### 18.1 Architecture

```
+-----------------------------------------------------------+
|                      Browser SPA                          |
|                                                           |
|  app.js (page renderers)                                  |
|     |                                                     |
|     +-- toast() ------------ loading_indicator.js         |
|     +-- [data-tooltip] ----- loading_indicator.js (delegated)
|     +-- PlatformHealth ----- platform_health.js          |
|     +-- CommandPalette ----- command_palette.js (Cmd+K)  |
|     +-- LogsPanel ---------- logs_panel.js (bottom-left) |
|     +-- Components.* ------- components.js                |
|                                                           |
+--------------------|--------------------------------------+
                     |
                     v
+-----------------------------------------------------------+
|                      FastAPI                              |
|                                                           |
|  routes/api.py                                            |
|    GET /api/platforms/health                              |
|    GET /api/activity/recent?limit=N                       |
|    GET /api/logs/stream                  (SSE)            |
|                                                           |
|  routes/posting_api.py                                    |
|    GET /api/posting/preview-file                          |
|                                                           |
|  routes/editor_api.py                                     |
|    /editor/slop  (now includes "available" flag)          |
+-----------------------------------------------------------+
```

The UX modules subscribe to existing data — none of them mutate
polling state. They reuse `API.*` helpers from `js/api.js`.

### 18.2 Backend endpoints

#### `GET /api/platforms/health` (`routes/api.py`)

Returns a single snapshot of every platform's recent poll log:

```json
{
  "ts": 1715722800,
  "platforms": {
    "ib": {
      "last_poll_ts": 1715722500,
      "last_status": "ok",
      "last_error": null,
      "next_poll_ts": 1715722800,
      "throttled_until_ts": null
    },
    "ao3": {
      "last_poll_ts": 1715720100,
      "last_status": "throttled",
      "last_error": "AO3 backoff active",
      "next_poll_ts": 1715723700,
      "throttled_until_ts": 1715723700
    }
  }
}
```

- Driven by `_PLATFORM_HEALTH_CONFIG` — one entry per platform with
  `(queries_module, table_name, throttle_attr)`.
- Uses each platform's own `*_queries.get_recent_poll_summary()` if
  available; falls back to a generic `SELECT … FROM <platform>_poll_log
  ORDER BY started_at DESC LIMIT 1`.
- AO3 picks up `_ao3_backoff_until_ts` from the global state cache so
  the dashboard can show "throttled until …" without a separate poll.
- Polled by `platform_health.js` every 60s; cheap because every query
  is `LIMIT 1` against a covering index.

#### `GET /api/activity/recent?limit=N` (`routes/api.py`)

Unified feed of the last N events across polls and posts:

```json
{
  "events": [
    {
      "ts": 1715722500,
      "kind": "poll",
      "platform": "sf",
      "level": "ok",
      "summary": "SoFurry: 3 new submissions (12 watchers)"
    },
    {
      "ts": 1715722200,
      "kind": "post",
      "platform": "ib",
      "level": "error",
      "summary": "Inkbunny: post failed — ratelimit"
    }
  ]
}
```

- `_format_poll_summary` and `_format_post_summary` keep the wording
  consistent so the renderer doesn't need per-platform templates.
- `level` is `ok` / `warn` / `error` for the sidebar dot mapping.
- Used by overview's "Recent activity" feed (`Components.systemEventsFeed`).

#### `GET /api/logs/stream` (SSE)

Streaming log tail. `app.log`, `server.log`, and per-platform polling
logs each have their own SSE source:

```
data: {"file":"app","ts":1715722500,"level":"INFO","line":"…"}
data: {"file":"app","ts":1715722501,"level":"WARN","line":"…"}
```

- Tracks **byte offset** (not line count) per file. Detects log rotation
  when `os.stat(path).st_size` shrinks below the cursor — resets to 0
  and re-emits.
- Honours `?file=app|server|polling` query param (defaults to `app`).
- Sends `: keepalive\n\n` every 15s so reverse proxies don't kill it.
- Closes cleanly on client disconnect (`asyncio.CancelledError`).

#### `GET /api/posting/preview-file` (`routes/posting_api.py`)

Compares a story's local file with what was last sent for posting:

```json
{
  "story_uid": "velvet_and_vice",
  "platform": "ib",
  "file_exists": true,
  "head": "[b]Velvet and Vice[/b]\n\n…",   // first 4096 chars
  "local_hash": "sha256:abcd…",
  "posted_hash": "sha256:wxyz…",
  "drift": true
}
```

Used by `publish_check.js` "Preview file" button in the cell drawer
to surface drift before a republish.

### 18.3 Frontend modules

All three new modules are auto-registered globals; you don't need to
`import` them — including the `<script>` tag is enough.

#### `frontend/js/platform_health.js`

```js
window.PlatformHealth = {
  start(),         // Begins polling /api/platforms/health every 60s
  stop(),          // Stops polling and tears down observers
  fetchOnce(),     // Manual refresh; resolves to the snapshot
  get(code),       // Returns cached state for one platform
  getAll(),        // Returns the full map
  classify(state), // -> "ok" | "warn" | "error" | "throttled" | "unknown"
  relativePast(ts),    // "3 min ago"
  relativeFuture(ts),  // "in 2 min"
  subscribe(fn),   // Call fn(snapshot) on every refresh
  LABELS,          // { ib: "Inkbunny", … }
}
```

- `start()` is called once after the auth check in `app.js`.
- A `MutationObserver` on `#app` re-applies sidebar dots, page subtitle,
  and throttle banners after every SPA route change. Throttled with
  `requestAnimationFrame` so route changes don't trigger render floods.
- Tick interval is 30s for relative-time refresh; full fetch is 60s.
  These are independent so the UI feels live without doubling network
  traffic.

#### `frontend/js/command_palette.js`

```js
// Cmd+K (mac) or Ctrl+K (everything else) opens it.
// Esc, click-outside, or Enter closes it.
```

- 22 platform pages (Polling/Stories/Posting per platform) + 9
  top-level sections + 3 actions ("Pause polling", "Resume polling",
  "Open logs panel") are registered at module load.
- Fuzzy ranking: prefix match > substring > subsequence. Ties broken
  by command type (page > action) then alpha.
- Up/Down arrows navigate; Enter executes; selection wraps at edges.
- Renders into a `<div class="cmdk-overlay">` portal at body root;
  doesn't depend on the page being mounted.

#### `frontend/js/logs_panel.js`

The bottom-left toggle pill + 520x360 floating panel.

```js
// Persisted to localStorage as `pp_logs_panel_state`:
{
  visible: false,
  file: "app",       // app | server | polling
  level: "INFO",     // INFO | WARN | ERROR
  paused: false,
  height: 360,
}
```

- SSE `EventSource` to `/api/logs/stream?file=…` opens **only** when
  the panel is visible AND the tab is focused. Closes on tab blur or
  panel hide. Avoids the "logs piled up while I was on Slack" memory
  bloat.
- Sticky-bottom auto-scroll: if the user scrolls up, new lines append
  silently; scroll back to bottom resumes auto-scroll.
- 1500-line memory cap; oldest lines drop off when the cap is hit.
- Pause button freezes the view but keeps the SSE connection open so
  history doesn't gap.
- File picker re-opens the SSE stream on change.
- **Visibility gate (2.108.0):** the whole widget is gated by the
  `logs_panel_enabled` preference (Settings → App Preferences →
  "Floating logs button", default on, whitelisted in
  `routes/api.py` `get_preferences`/`save_preferences`). `init()` reads
  it via `API.getPreferences()` and only renders the toggle when
  enabled — on any fetch failure it defaults to **shown** so the widget
  never silently disappears. `window.LogsPanel.setEnabled(bool)` flips
  it live (hides the button + collapses/disconnects the panel, or
  restores the persisted open state), so the settings toggle takes
  effect with no reload.

#### `frontend/js/loading_indicator.js` (extension)

The `[data-tooltip]` event delegation system was added here to keep
all hover/popup behaviour in one module:

```html
<button data-tooltip="Re-fetch all watchlists">Poll all</button>
```

- 1.2s show delay (no jitter on quick pointer movement).
- Clamps to viewport edges so tooltips on right-most buttons don't
  clip.
- Hides on scroll, Esc, or `mousedown` anywhere.
- Single delegated `mouseover`/`mouseout` listener at `document.body`,
  so dynamically rendered SPA content gets tooltips for free.

#### `frontend/js/tour.js` (guided tours)

Interactive coach-mark onboarding — `window.Tour`
(`{ start(name,opts), startHere(opts), maybeAuto(hash), end(completed), isDone(name), hydrate(), tourForHash(hash) }`),
styled by `frontend/css/tour.css`. Introduced 2.56.0 (single getting-started tour); generalised to a
**registry of named tours** in 2.57.0 (getting-started + one tour per page); "seen" state moved
**server-side** in 2.82.0 (see the persistence bullet).

- **Registry.** `TOURS` maps a tour name → an array of `{ target, title, body }` steps. `getting-started`
  walks the shell chrome; 13 page tours (`platforms`, `submissions`, `stories`, `queue`, `history`,
  `editor`, `artwork`, `posts`, `analytics`, `groups`, `cross-platform`, `accounts`, `settings`) each walk
  one page. `tourForHash()` maps a location hash to a tour name (or null for full-screen / deep / platform
  sub-routes). Each tour has its own seen-flag: `pp_tour_done` for getting-started, `pp_tour_done__<name>`
  for pages (`doneKey()`).
- **Seen state is server-backed (2.82.0).** Before 2.82.0 "seen" lived only in per-browser `localStorage`,
  so a dismissal didn't follow the user — a different browser, a cleared/Private store, or the installed PWA
  (iOS gives a home-screen web app storage separate from Safari) all re-offered the tours. Now the source of
  truth is `settings.json` `tours_seen` (a list of tour names), exposed on `GET /api/settings/preferences`
  and appended via the **additive** `POST /api/settings/tour-seen {name}` (never removes — race-safe across
  tabs, un-wipeable by a partial client; rejects empty/>64-char names 400). `localStorage` stays a
  synchronous cache + offline fallback. `hydrate()` (memoised; called once past the auth gate in `App.init`,
  alongside the health/achievement watchers) GETs the seen set, mirrors it into `localStorage`, and
  **reconciles** any tour dismissed only on this browser *up* to the server (a one-time migration for existing
  users). It clears its own memo on a 401/403 or network error, so a pre-login attempt can't cache an empty
  set forever. `isDone(name)` = server set ∪ localStorage.
- **Spotlight without canvas/SVG.** `.pp-tour-spot` is a small box over the target; its spread shadow
  `box-shadow: 0 0 0 9999px rgba(0,0,0,.62)` paints everything *outside* it dark, and a
  `0 0 0 3px var(--accent)` ring highlights it. A transparent `.pp-tour-blocker` swallows background clicks
  so only the popover's Next/Back/Skip drive it. Centered (no-target) steps hide the spot and dim the blocker.
- **Empty-state-safe + auto-skip.** Page steps target durable chrome and containers, never a data row. Where
  a step targets a state-exclusive element (`.empty-state` exists only when empty; `.data-table` /
  `.story-card-grid` only when populated), `findTarget()` resolves it to a *visible* element (non-zero rect)
  and `show()` **skips a missing/hidden step in the current direction** — so each tour reads correctly on both
  empty and populated accounts. `maybeAuto()` also waits for the first *targeted* element before committing,
  so it never fires over a half-rendered page.
- **Sidebar is force-expanded** for the run (`forceSidebarOpen()` / `restoreSidebar()`), so the spotlight
  lands on a legible rail; `html.pp-tour-active .sidebar { transform:none }` backs this up on mobile.
- **Trigger model.** `App.route()` schedules `Tour.maybeAuto(hash)` after each dispatch. It self-gates:
  getting-started auto-fires once on the overview; a page tour auto-fires once on first visit **but only after
  getting-started is done**, and not within ~1.2s of another tour ending (debounce, so tours don't chain).
  The sidebar-footer **"?"** (`#help-tour-btn`) calls `Tour.startHere()` — the tour for the current route —
  replayable regardless of the flags. Since 2.82.0 `maybeAuto()` `await hydrate()`s before deciding, so a tour
  the user already dismissed on another browser/the PWA never flashes before the server set has loaded. `end()`
  persists the current tour's "seen" on both completion and dismissal — it writes the `localStorage` flag **and**
  fire-and-forget POSTs to `/api/settings/tour-seen` (a lost request just retries via `hydrate()`'s reconcile
  next login).

#### `frontend/js/error_popup.js` + `routes/report_api.py` (achievement-style error cards, 2.159.0)

Every failed **mutating** API call pops a card in the Laurels celebration's visual language (same
rays/ico/label/name/desc anatomy, restyled on `--danger` in `frontend/css/error_popup.css`), with
**📋 Copy report** and **📨 Send to dev** actions. `window.ErrorPopup = { show, onApiError }`.

- **Wiring lives in api.js, not per screen.** `_popError(method, path, status, text)` is called from the
  POST error path (including its network-error catch — status 0), PATCH, and DELETE. GETs are deliberately
  NOT hooked: screens poll and prefetch constantly, and a flaky read shouldn't pop a card.
  `_maybeAuthModal()` now returns a bool; when the session-expired modal takes the error, the card is
  suppressed (one surface per failure).
- **Guards** (in `onApiError`): `/api/report-error` itself (a failing report must never recurse),
  `/api/auth/*` and connect/validate paths (login + credential flows have their own inline messaging),
  8-second same-`method+path+status` dedup, and one open card at a time (first error wins — it's usually
  the root cause). Inline per-screen error messages still render where they exist; the card adds the
  copy/report affordance on top.
- **Card content.** Title maps from status (0 → "Server unreachable", 401/403 → "Not authorised",
  404 → "Not found", 5xx → "Server error", else "That didn't work"); the message is the FastAPI `detail`
  (parsed like api.js `_cleanErr`); a collapsed `<details>` holds the full plain-text report (route,
  status, screen hash, version, ISO time, raw body). The app version is parsed from api.js's own
  `?v=X.Y.Z` cache-buster — free, and always matches the serving backend. Esc / tap-outside dismisses.
- **`POST /api/report-error`** (`routes/report_api.py`, registered in `dashboard.py`): accepts
  `{context, message, detail, url, version, ua}`, **always** writes the report to the server log, then
  HTML-escapes + clips every field (context 200 / message 500 / detail 1200 / url+ua 200 — keeps the
  message under Telegram's 4096-char cap) and forwards via `polling/telegram.py` `send_telegram`.
  Returns `{sent: bool}` so the button can show "Sent to dev ✓" vs "Telegram not set up". Self-host
  model: **"the dev" = the instance owner** — the report rides the instance's own Telegram bot; no
  third-party telemetry, nothing leaves the box unless Telegram is configured. The Send button uses a
  raw `fetch`, not `API.post` — a report about a failing API must not route back through it.
  Tests: `tests/test_report_error.py` (forwarding, sent:false, HTML escaping, clipping, version stamp).
- **Submissions caveat.** The `submissions` tour is keyed to `#/submissions`, which the router resolves to the
  legacy IB analytics view (`renderSubmissions` in app.js) — its un-prefixed route shadows the unified hub
  (`Submissions.render`). The tour therefore targets the IB view's controls (`#search-input`, `#filter-rating`,
  `#filter-type`, `.view-toggle`, `#grid-container`), not the hub's. Revisit if route-unification lands.

### 18.4 Components

`frontend/js/components.js` gained two helpers that the page renderers
in `app.js` use directly:

```js
Components.platformEmptyState("sf", {
  hasStories: false,        // Affects copy and CTA
  primaryAction: {label: "Add story", onclick: "App.addStory('sf')"},
})
// -> Renders the "No SoFurry stories yet" card with a CTA button.

Components.systemEventsFeed(events)
// -> <ul class="sys-evt-list"> with one <li class="sys-evt-row sys-evt-{level}">
//    per event, time-relative timestamp, platform tag, summary.
```

Both helpers degrade gracefully — `systemEventsFeed([])` renders
"No recent activity yet." instead of an empty `<ul>`.

### 18.5 Drift preview UI (`publish_check.js`)

The Publish Check cell drawer gained a **Preview file** button that:

1. Calls `GET /api/posting/preview-file?story_uid=…&platform=…`
2. Renders the first 4096 chars in a monospace panel
3. Shows the local-vs-posted hash comparison
4. Highlights "drift" when local hash != last posted hash

Implemented in `_toggleDriftPreview` and `_renderDriftPreview` —
the panel is collapsible so the cell drawer stays compact when not
needed.

### 18.6 Token aliases (CSS hygiene)

`frontend/css/tokens.css` gained a "legacy alias" block at `:root`:

```css
--surface-elevated: var(--bg-card);
--border-primary: var(--border);
--color-success: var(--success);
--color-warning: var(--warn);
--color-error: var(--error);
--color-text: var(--text);
--color-text-muted: var(--muted);
```

These existed in the SCSS-style names that several components were
already calling but were **never defined** — falling silently through
to browser defaults (white-on-white dropdowns being the most visible
symptom). Aliasing them keeps the call sites unchanged while the
canonical tokens stay in `--bg-card` etc.

### 18.7 Slop scorer bundling

`scripts_utils/slop_words.json` (1,648 entries) and
`scripts_utils/slop_trigrams.json` (430 entries) are now bundled
**inside** the PawPoller tree. Previously the editor's slop scorer
read them from `m_x/Scripts_Utils/` — fine on the dev machine, but
non-existent on the GCP VM, where `/editor/slop` silently returned
0.0 for every story.

`editor/slop.py` now exposes `is_available()`; `routes/editor_api.py`
adds an `available: bool` field to the response so the editor can
render "Slop: -" instead of a misleading 0.0 if the data ever goes
missing again.

### 18.8 Out of scope

- Persistent log retention beyond what `app.log` already does — the
  panel is a live tail, not a search UI.
- Per-user dashboard layouts — the empty states, command palette, and
  logs panel are fixed-position. Re-themable via tokens, but not
  draggable.
- Throttle banners for non-AO3 platforms — only AO3 and Bsky surface
  enough throttle metadata to be worth showing. Other platforms fall
  through to the generic error banner.

---

## 19. Multi-account model (multiple accounts per platform)

> **Status:** in progress. Landed: Phase 0 foundation, the Inkbunny and
> FurAffinity analytics verticals, and orchestrator account enumeration — so
> multi-account **polling works end-to-end for IB + FA** on the server. Pending:
> posting "post as account" selection, per-account dashboard, cross-cutting
> concerns, and the other 9 platforms. See `docs/HANDOFF.md` for the live checklist.

PawPoller historically assumed **one account per platform**: credentials lived
under flat settings keys and no table carried an account discriminator. The
multi-account work lets more than one account run per platform (e.g. two
FurAffinity accounts), all active at once, for both polling and posting.

### 19.1 The `accounts` registry

`database/accounts.py` owns a single `accounts` table shared across all
platforms:

```
account_id INTEGER PK AUTOINCREMENT   -- global surrogate; threads through every per-platform table
platform   TEXT                       -- 'ib','fa',…
label      TEXT                        -- user-facing name
handle     TEXT                        -- denormalized username/identifier for display
enabled    INTEGER                     -- polled/posted only when 1
is_default INTEGER                     -- the legacy/first account per platform
sort_order, created_at
```

A **partial unique index** (`WHERE is_default = 1`) guarantees at most one
default account per platform. The default account is special: it owns the legacy
flat credentials and the pre-multi-account data history.

**Critical invariant:** `account_id` is AUTOINCREMENT and therefore *not*
uniformly 1 per platform (Inkbunny might be 1, FurAffinity 2, …). Any backfill of
existing rows must target *that platform's* default account_id — resolve via
`accounts.get_default_account_id(conn, platform)`, never a literal 1.

### 19.2 Credentials — namespaced flat keys

The default account keeps the existing flat keys verbatim (`username`,
`fa_cookie_a`…) so existing installs need **zero credential migration**.
Additional accounts store the same canonical fields under `acct_<id>_<field>`.
`config.py` provides:

- `PLATFORM_CREDENTIAL_FIELDS` — canonical field list per platform.
- `account_setting_key(account_id, field, is_default)` — bare key for the
  default account, namespaced for the rest.
- `resolve_account_credentials(platform, account_id, is_default, settings)` /
  `get_account_credentials(account_id)` — return `{canonical_field: value}` so
  clients/posters don't care which account they are.
- `is_credential_key(key)` — used at the three vault-split sites; matches both
  the legacy `CREDENTIAL_FIELDS` set and namespaced secrets
  (`acct_<id>_<secret>`), so extra-account secrets are encrypted like the
  default's while non-secret identity fields stay in plaintext.

### 19.3 Schema migration (`database/db.py`)

Two categories, both idempotent:

1. **Additive** (`_run_migrations`, "Migration 0/0b") — `accounts` table is
   created and seeded first; then `account_id` columns are added to the Inkbunny
   analytics tables and `posting_queue`/`posting_log`, and existing rows are
   backfilled to the platform default. `account_id = 0` is the "unset" sentinel
   (real ids start at 1); after backfill no row is 0.
2. **Constraint rebuilds** (`_run_table_rebuilds`) — run on a dedicated
   **foreign-keys-off, autocommit** connection because SQLite can only toggle FK
   enforcement outside a transaction, and dropping the FK-referenced
   `publications` table with FK on would trigger an implicit DELETE that violates
   `posting_queue`/`posting_log`. Rebuilds: `session_cache` singleton
   (`CHECK id=1`) → `PK account_id`; `watchers` `UNIQUE(username)` →
   `UNIQUE(account_id, username)`; `publications`
   `UNIQUE(story_name, chapter_index, platform)` → `+ account_id`. Each guards on
   the presence of the `account_id` column and cleans up any leftover `*_new`
   table, so re-runs are safe.

Fresh installs run the same path: the `.sql` schema files still create the
old shape, then the migration immediately upgrades it (cheap on empty tables).

### 19.4 Runtime

- **Polling** — `polling/poller.py` `run_poll_cycle(account_id=None, …)`. When
  `account_id` is None it resolves the platform's default account (back-compat).
  Per-account credentials, per-account cached session, and per-account first-poll
  suppression (`_first_poll_done` set). A single module lock still serialises IB
  polls — accounts on one platform poll sequentially by design (rate limits).
- **Posting** — `posting_queries.upsert_publication` / `get_publication_by_story`
  take an optional `account_id` (None → platform default). The Inkbunny poster
  holds an `account_id` and reads `session_cache WHERE account_id = ?` — the old
  singleton `WHERE id = 1` read is gone (it would have shared one auth token
  across accounts; this is the single most important posting fix).

### 19.5 API + sync

- `routes/settings_api.py` exposes `accounts_router` (`/api/accounts` CRUD).
  Deleting a default account is refused; extra accounts' namespaced credentials
  are removed on delete.
- Settings sync (`config.get_settings_for_sync` / `merge_synced_settings`)
  carries an `_accounts_manifest` (serialized `accounts` table) so desktop and
  server agree on which accounts exist. `accounts.apply_manifest` is an additive
  upsert (never deletes) keyed on `account_id` to keep the surrogate stable.

### 19.6 Pending / known gaps

- **Polling** is account-aware for **all 17 platforms** — the orchestrator
  enumerates each platform's enabled accounts; there is no legacy single-account
  path left.
- **Posting** data layer is account-aware end to end (`/api/posting/post`
  `account_ids`, `/api/posting/update` `account_id`; `manager._get_poster` keyed by
  `(platform, account_id)`; scheduler + desktop auto-queue carry `account_id`).
  Only the **IB and FA posters** authenticate per account in `_ensure_client`; the
  other posters (ws, sf, sqw, ao3, da, bsky, ik) still read flat creds and post as
  the default account. The frontend publish-check matrix also doesn't expose a
  "post as account" selector yet.
- The **Accounts page** shows per-account stat rollups (`accounts.account_stats`).
  The per-account dashboard picker is now **done** (2.30.0 — see §19.7); the
  frontend "post as account" selector in the publish-check matrix is still pending.
- Cross-cutting done: the consolidated Telegram summary labels accounts when a
  platform has more than one; drift records (`posting/sync.py`) carry `account_id`.
  Pending: the diagnostics tab per account; desktop `main.py` polls only default
  accounts (polling is server-side, so low priority).

### 19.7 Personas + per-account scoping (2.30.0)

The identity layer that makes multi-account usable. CHANGELOG [2.30.0].

**Personas** (`database/personas.py`) — a `personas` table (`persona_id`, `name`,
`color`, `sort_order`) + a nullable `accounts.persona_id` (NULL = Unassigned).
The link is a **soft reference** (no SQL FK): `delete_persona` nulls its accounts'
`persona_id` first. The module mirrors `accounts.py` — CRUD,
`assign_account_persona` (dedicated, because `update_account` skips `None` and so
can't unassign), `list_accounts_by_persona` (the `None` key is Unassigned),
`persona_stats` (sums `accounts.account_stats` over the persona's accounts +
per-platform breakdown — reuses, no new SQL), and `get_manifest`/`apply_manifest`.
Migration is an idempotent `ADD COLUMN persona_id` + index at the **end** of
`_run_migrations` (no rebuild — additive only). Sync adds a `_personas_manifest`
applied **before** the accounts manifest (so account→persona refs resolve), and
the accounts manifest gained a `persona_id` field (old-client absence never
clobbers a local assignment). API: `personas_router` (`/api/personas` CRUD +
`GET /{id}` detail) + `POST /api/accounts/{id}/persona`.

**Per-account read scoping** (`database/scope.py`) — `account_clause(account_id,
alias="") -> (sql, params)` is the single optional `account_id = ?` predicate
(`None` ⇒ `("", [])` ⇒ All accounts, byte-identical to pre-scoping). Every
platform's `get_*_summary` / `get_all_*_submissions` / `get_*_aggregate_snapshots`
(+ recent faves/comments where present) take an optional `account_id` and splice
the clause in; the snapshot subquery in the fastest-growing / delta joins stays
unscoped because submission_ids are account-unique. The `/summary`, `/submissions`,
`/aggregate` endpoints on all 11 platforms gained `account_id: int | None =
Query(None)`. **Growth-rate + watcher-count helpers stay aggregate** (deliberate
follow-up). Frontend: `app.js` `_populateAccountSwitch` adds an account `<select>`
to the context bar **only when a platform has 2+ enabled accounts**; `_acctId(code)`
holds the per-platform filter and is threaded into each platform's dashboard /
submissions / compare fetches. The cross-platform Overview + Platforms hub stay
aggregate by design.

**Per-persona notifications** (`polling/telegram.py`) — digests reuse
`account_clause` via the now account-aware `_get_platform_totals` /
`_get_digest_deltas` / `_get_watcher_stats`, and the per-function platform lists
collapsed into one `PLATFORM_TABLES`. `send_digest_report` +
`send_weekly_digest_report` iterate `list_accounts_by_persona` and emit **one
message per persona** (+ an Unassigned digest) — per-account breakdown +
persona-combined totals + top gainers; **no-personas installs still get the single
combined digest** (`_ordered_digest_units` decides). `send_consolidated_poll_summary`
groups the cycle's results into a 👤 sub-section per persona. `check_milestones_batch`
takes an `account_id` — scoping the scan both labels the alert and **fixes a latent
double-fire** (each account's poll previously rescanned every account's submissions).
Instant new-fave/comment alerts lead with a persona/account line: IB/FA thread
`account_id` into `_send_telegram`/`_send_fa_telegram` directly; the other 9 read an
async-safe `notifications.current_alert_account` ContextVar that the orchestrator
(`server.py _poll_accounts`) sets once per account. `_should_label_account` suppresses
every prefix on single-unassigned-account installs.

**Persona overview** (`frontend/js/accounts.js` `renderPersonaDetail`, route
`#/persona/:id` in `app.js`) — combined stat cards (`Components.statCard`) +
per-platform breakdown + member accounts; each account's "View →" sets
`App._accountFilter[platform]` and navigates to that platform's dashboard
pre-scoped. Persona names on the Accounts page link through.

## 20. Artwork (PostyBirb-style image posting, 2.31.0)

> **The `#/artwork` HUB is retired (2.155.0, backlog L)** — it redirects to
> `#/library/type/artwork`. Its grid was `/api/works` filtered to
> `content_type == "artwork"`, and its discovered tiles are now the Library's
> Discovered segment. `Artwork.render()` and ~400 lines of hub-only helpers are
> unreachable but still present (port source for backlog L1/L2). Everything else
> in this section — the **uploader** (`#/artwork/new`), **detail**
> (`#/artwork/image/{name}`), **log**, **ignored** and the whole posting path —
> is LIVE and unchanged. Merging the hubs did not merge the pages behind them.

A standalone image uploader parallel to the story flow: drop in an image, set
per-platform metadata, publish to multiple art sites at once. It **reuses the
posting engine** rather than forking it — the same posters, manager, registry,
scheduler, and retry/desktop-queue fallbacks carry both stories and artwork.

**Why it's cheap.** Two facts shrank the build: (1) **analytics are free** —
every poller auto-discovers the user's whole gallery with no content-type
filter, so posted art is tracked (views/faves/comments, charts, milestones) on
the next poll with zero poller changes; (2) `StoryUploadPackage` (in
`posting/platforms/base.py`) already carries `file_path`/`file_type`/
`thumbnail_path`/tags/rating, so an image is just a package whose `file_path`
is the image.

### 20.1 Registry — the `content_type` discriminator

`publications` / `posting_queue` / `posting_log` gained an additive
`content_type TEXT NOT NULL DEFAULT 'story'` column (idempotent ADD COLUMN in
`_run_migrations`, mirroring the account_id rollout). `_rebuild_publications_content_type`
(in `_run_table_rebuilds`, right after `_rebuild_publications`) folds it into the
publications UNIQUE → `UNIQUE(content_type, story_name, chapter_index, platform,
account_id)`, so an artwork named like a story can't UPSERT onto the story's row.
The rebuild is defensive about whether the account_id rebuild already dropped the
freshly-added column (reads the live column set).

In `database/posting_queries.py` the write/keyed functions (`upsert_publication`,
`get_publication_by_story`, `add_to_queue`, `log_posting_action`,
`delete_publication`, `update_publication_url`) take a `content_type="story"`
param; the cross-story **list** reads (`get_publications`, `get_queue`,
`get_posting_log`) filter to `content_type='story'` so artwork never leaks into
the Stories views. **`get_pending_queue` is deliberately unfiltered** — the
scheduler must see both content types and routes on each row's `content_type`.
Every default is `"story"`, so the existing story flow is byte-for-byte unchanged.

### 20.2 Engine — `artwork_reader` + `post_artwork`

`posting/artwork_reader.py` (mirrors `story_reader.py`): one folder per artwork
under `get_artwork_archive_path()` (setting `artwork_archive_path` → Docker
`/app/data/artwork` on the existing persistent volume → desktop
`…/m_x/Archives/Artwork`). Each folder has the image + a **`masterpiece.json`**
(`title/description/author/rating/characters/image/thumbnail` + per-platform
`tags/titles/descriptions/categories` maps). **Back-compat (Masterpieces Phase 0,
2.124.0):** the reader accepts BOTH `masterpiece.json` and the legacy
`artwork.json` via `_meta_path` (prefers the new; the new file is a strict
superset), writers emit `masterpiece.json`, and `save_artwork_metadata` migrates
a folder to it on first edit. `create_artwork` (used by both upload paths),
`load_artwork` (traversal-guarded), and `build_artwork_package`
→ a `StoryUploadPackage` (chapter 0, image `file_path`, per-platform cascade,
`extra` = the platform's category map). A folder is the on-disk half of a
**Masterpiece** (the master record for one image; see
`docs/specs/masterpieces.md`); the name-keyed `masterpieces` index table +
`masterpiece_members` (Phase 1, 2.125.0) are the relational half — see §20.10.

`manager.post_artwork(artwork_name, platforms, account_ids, extras)` is the
parallel of `post_story`: per platform it builds the image package, validates,
posts via the **same** `_get_poster`/`poster.post`, records
`content_type='artwork'`, and reuses the desktop-queue + `_schedule_retry` + log
fallbacks. `scheduler._process_queue_item` branches on the queued row's
`content_type` → `post_artwork` vs `post_story`/`update_story`.

### 20.3 API + frontend

`routes/artwork_api.py` (`/api/artwork/*`, registered in `dashboard.py`):
`images` (list) / `images/{name}` (detail + live stats / delete / PATCH) /
**upload** (browser `UploadFile` → `create_artwork`) / **create-from-path**
(desktop local file copied in) / **publish** (→ `post_artwork`) / **image**
(query-param + traversal-guarded serving) / artwork-scoped `publications` + `log`
/ `settings` / `sync/{upload,push}` (tar.gz desktop⇄server media).

`frontend/js/artwork.js` (`window.Artwork`): a card-grid hub, a create flow
(drag-drop / `<input type=file>` / desktop native picker, live preview, default
metadata + collapsible per-platform tag overrides, platform checkboxes +
per-platform account `<select>`s), a detail page (cover + per-platform
publications with stats + "publish to more"), and a history view. `#/artwork`
routes + an **Artwork** nav entry sit beside Stories.

**Full gallery — discovered art merged in (2.48.0).** The hub grid is no longer
library-only. `render()` fetches `/api/artwork/images` (library) **and**
`/api/works/discovered` in parallel and merges both into one grid, newest-first,
"like Stories". Discovered items are filtered client-side to art via
`_isArt(d)` = art-capable platform (`this._PLATFORMS`) **and** `d.kind !== 'text'`
**and** a thumbnail. That `kind` comes from the backend: `routes/submissions_api.py`
`classify_kind(platform, type_str)` (pure/unit-tested) tags each discovered
submission `art`/`text`/`unknown` — image-only `da`/`ik` and text-only
`ao3`/`sqw`/`wp` short-circuit; mixed `fa`/`sf`/`ib`/`ws`/`bsky` read the stored
type string (`category`/`content_type`/`subtype`), text hints winning over art
hints — and `build_discovered` stamps it on every item. Library cards link to
their per-work detail; **discovered cards** (`_discoveredCard`) render the
source-platform badge over the cover + a view count, with **View ↗** (external)
and **Import** (delegated click → `_importDiscovered` → existing
`/api/artwork/import/{platform}/{id}` → re-render). Discovered is additive: a
discovered-fetch error is swallowed so the library grid still shows. No schema
change, no new endpoint. Styling: `frontend/css/artwork.css` `.artwork-card--disc`
+ `.artwork-disc-*` (reuses the global `.btn-sm`).

**Masters — unify the same piece across sites (2.59.0).** The gallery folds the
same artwork posted to several sites into **one master tile with pooled stats**.
The key realisation: a master *is* a generic **cross-platform link** — the
`submission_links` / `submission_link_members` tables (see §"Cross-Platform
Tables") key on `(platform, submission_id)`, which is exactly the identity a
discovered art tile already carries (both come from the same `*_submissions`
poller tables). So the feature is **frontend-only** and reuses the existing link
endpoints — `GET /api/links` (read), `POST /api/links` (unify), `DELETE
/api/links/{id}` (split); **no schema change, no new endpoint.**
- *Read path* — `render()` also fetches `/api/links`; `_foldMasters(discovered,
  links)` groups discovered tiles sharing a link into masters and returns the
  still-standalone tiles. A link becomes a master **only when 2+ of its members
  are art tiles present in this gallery**, so story links (and links whose art
  members were imported to the library and thus left the discovered set) fall
  through untouched — no server-side art-vs-story classification needed.
  `_masterCard` renders a "N sites" badge, the members' platform emojis, summed
  views, and a click-to-expand (`.art-master-toggle` → `_toggleMaster` toggles
  `.expanded`) panel of per-member rows (each still opens its own post) with a
  **Split** button (`_splitMaster` → `DELETE /api/links/{id}` → re-render).
- *Write path* — a **Select** toggle in the header (`_enterSelect`/`_exitSelect`)
  adds `.selecting` to the grid, revealing a checkbox overlay on each
  `.artwork-card--selectable` (discovered) tile and swallowing its normal
  navigation/import; `_toggleSelect` tracks ticked keys; **Unify selected**
  (`_unifySelected`) posts the ticked `(platform, submission_id)` members to
  `POST /api/links` and re-renders so they collapse into a master.
- *Action bar (2.89.0)* — `#art-select-bar` is a **floating** card fixed to the
  bottom-centre of the viewport (`position:fixed`), so the count + Unify + Cancel
  stay in reach while you scroll a long gallery ticking pieces. Visibility is
  driven by an **`.is-active` class**, not the `[hidden]` attribute: the bar's own
  `display` value (and the toggle's `.btn` display) override a bare `[hidden]`, so
  before 2.89.0 the bar leaked visible on the Artwork page at all times.
  `_enterSelect` adds `.is-active` to the bar + `.is-hidden` to the toggle;
  `_exitSelect` removes both. `.artwork-grid.selecting` gets bottom padding so the
  last row clears the floating bar.
- *Suggestions banner (2.60.0)* — a dismissible **Possible matches** banner
  nudges the obvious merges, reusing the title-similarity engine
  (`GET /api/links/suggestions` → `auto_suggest_links`). `_loadSuggestions` fetches
  it **lazily after the grid paints** (into `#art-suggest-slot`, whose click
  handler is delegated once in `render()`), so the O(N·M) scan never delays first
  paint. `_artSuggestions(suggestions, standalone)` keeps only pairs whose members
  are **both standalone art tiles present here** (via the `standalone` set → no
  story matches, no already-mastered pieces) minus `localStorage`-dismissed pairs
  (`pp_artunify_dismissed`, keyed by the sorted member pair). Each card offers
  one-click **Unify** (`_unifySuggestion` → same `POST /api/links`) and **✕**
  (`_dismissSuggestion`). Caveat: `auto_suggest_links` scans the fiction-ish set
  (ib/fa/ws/sf/sqw/ao3/da/wp/ik), so bsky/pixiv art isn't proposed (still unifies
  manually).
- *Scope* — unify operates on the orphan **discovered** tiles (library uploads
  are already "one work → N publications"; cross-type merges are out). Deferred
  (see `prototype/docs/ARTWORK_UNIFY.md` §6.4): per-master cover/title management
  (would want the optional `title`/`cover_*` columns from the spec's §3). Styling:
  `.artwork-card--master`, `.artwork-master-*`, `.artwork-select-*`,
  `.artwork-suggest-*` in `artwork.css`.

### 20.4 Per-platform image posting

The 7 image-capable platforms (the 4 fiction-only sites — ao3, sqw, wp — plus tw,
which has no poster, are excluded):

| Platform | How an image posts | State |
|---|---|---|
| Inkbunny | `upload_submission(submission_type="1")` (picture) | verified |
| Itaku | `upload_image` (already image-native) | verified |
| Bluesky | image embed (Pillow downscale for the ~1 MB blob cap) | verified |
| FurAffinity | `submit_visual` — `submission_type="submission"` + visual category | **needs live test** |
| SoFurry | image as Artwork (category 10) via MIME-aware `upload_content` | **needs live test** |
| Weasyl | `submit_visual` → `/submit/visual` (image as `submitfile`) | **needs live test** |
| DeviantArt | Sta.sh `oauth_stash_submit` → `oauth_stash_publish` | **needs live test + scope re-auth** |

The READY three were verified end-to-end in-browser. FA/SF/Weasyl/DA were built
from the existing client patterns + each site's form/API but can't be verified
without posting live; **DeviantArt also needs the DA app re-authorized with
`stash`+`publish` OAuth scopes** (the literature-only token will 401/403). The
per-platform submission categories for FA/SF/Weasyl come from `artwork_*`
settings: `artwork_fa_category/species/gender`, `artwork_sf_sub_type`,
`artwork_ws_subtype`, `artwork_da_catpath` (plus `artwork_enabled`,
`artwork_archive_path`, `artwork_default_platforms/rating`).

### 20.5 Desktop bridge

`main.py` passes a `js_api` object to `webview.create_window`; its
`open_image_dialog()` opens a native file dialog and returns the chosen path, so
the desktop app posts a local image by path (copied into the archive) instead of
re-uploading bytes. The browser upload path is the universal fallback (works on
desktop and the server).


## 20.9 Collections — one master container per piece (2.97.0)

A **Collection** is a user-curated master folder for a single *piece* across every place it lives — gallery works
+ microblog submissions + an optional companion story — with pooled analytics, all locations/links and merged
tags. Full design + rationale: `docs/specs/collections.md`. (Phase 0 — the account-attribution fix that makes the
persona/analytics rollup correct — shipped in 2.96.0; see that changelog entry.)

- **Model** — `collections` + `collection_members` (`database/collections_schema.sql`, loaded in `db.py` via
  `CREATE TABLE IF NOT EXISTS`). Members are **polymorphic references**, not copies: `member_type` ∈
  `work` (`artwork:Name` / `story:Name`) | `submission` (`platform:submission_id`) | `post`, resolved live so
  analytics stay current. `ON DELETE CASCADE` on the FK; `INSERT OR IGNORE` makes add-member idempotent.
- **Rollup** — `database/collections_queries.py::rollup_collection(conn, cid)` resolves each member into
  per-platform **locations** `{platform, account_id, url, title, stats:{views,favorites,comments}, keywords}`.
  A `submission` member → its `{platform}_submissions` row; a `work` member → its publications (via
  `get_publications`), each publication resolved to its submission. Stats are normalised with the SAME
  `_TABLE_MAP`/`_METRICS` per-platform column mapping as `analytics_queries.get_link_combined_stats` (the unify
  master pooling), so Collections and Masters pool identically. Output pools totals, merges the tag set, collects
  the persona(s) spanned (each location's `account_id` → persona), and surfaces the first `story` work member as
  `story`. `list_collections_with_summary()` gives the hub grid a light rollup.
- **API** — `routes/collections_api.py` (`/api/collections`, registered in `dashboard.py`): `GET` (list) /
  `POST` (create, optional `members[]`) / `GET /{id}` (detail rollup) / `PATCH /{id}` / `DELETE /{id}` /
  `POST /{id}/members` / `DELETE /{id}/members?member_type=&member_ref=`.
- **Frontend** — `frontend/js/collections.js` (`window.Collections`) + `collections.css`, a **Collections** nav
  entry, routes `#/collections` (`render()` grid) and `#/collections/:id` (`renderDetail()`). CSP-safe: one
  delegated click listener keyed on `data-coll-*` / `data-add-collection`, no inline handlers; modals reuse the
  `.guide-modal` shell. **Curation:** `Collections.pickAndAdd(memberType, memberRef, label)` powers a "＋ Collection"
  `role="button"` span on every Submissions-hub work card (`submissions.js`), and the detail page has a
  browse-to-add member picker (`_addMemberBrowser`).
- **Member picker (2.111.0) — `frontend/js/work_picker.js` (`window.WorkPicker`).** `_addMemberBrowser` now
  opens **WorkPicker**, a reusable *visual* picker modeled on the story-editor tag browser: it reuses the
  `.tag-browser-*` modal chrome (backdrop, sticky header with search + filter chips, selected strip, footer)
  but fills the grid with **image cards** (thumbnail + title + badge) instead of tag chips. `WorkPicker.open({
  title, confirmLabel, multi, onConfirm })` returns selected items as `{member_type, member_ref, title, badge,
  thumb}`. It **scales to thousands** via server-side search (`/api/works?search=&type=` + the discovered
  bucket) — the old `_addMemberBrowser` text list was capped at 200 rows. `.wp-*` card CSS lives in
  `editor.css`. Reusable anywhere a work/submission is chosen (will replace the Cross-Platform `prompt()`).
- **Cross-Platform Links folded in (2.113.0, Phase 3).** Cross-Platform Links were the same idea as a Collection
  (one piece across platforms + pooled analytics), so the screen was retired and its two unique features moved in:
  - **Combined growth chart** — `analytics_queries.get_combined_snapshots(conn, pairs)` is the reusable core
    (merges per-platform snapshots by `polled_at`, summing overlapping timestamps). `get_link_combined_snapshots`
    is now a thin wrapper; `collections_queries.collection_member_pairs(cid)` resolves a collection's submission +
    work members to `(platform, submission_id)` pairs (posts excluded). Served by `GET /api/collections/{cid}/snapshots`
    and charted on the Collections detail page (`Charts.aggregateLine`, shown only when a real series exists).
  - **Suggestions** — shared engine `analytics_queries._auto_suggest(conn, existing)` (title-Jaccard ≥ 0.6).
    `auto_suggest_links` excludes already-linked pairs; `collections_queries.auto_suggest_collections` excludes
    already-**collected** pairs (`_collected_pairs`). Served by `GET /api/collections/suggestions` (declared BEFORE
    `/{cid}` so the static path wins over the int converter) and surfaced as the hub's "Suggested collections" card
    with a one-click "Make collection".
  - **Migration** `collections_queries.migrate_links_to_collections(conn)` (called from `db.py._run_migrations`):
    one-time, **idempotent**, **reversible**. Adds a `collections.source_link_id` provenance column, then creates a
    Collection per not-yet-migrated `submission_links` row (submission members, named from the first resolvable
    title). The link rows are **not deleted** — undo = delete the migrated collections. `/api/links*` endpoints stay
    dormant. Frontend: nav entry removed, `#/cross-platform`→`#/collections` redirect, command-palette + page-tour
    re-pointed to Collections.
- **Image similarity (2.114.0, Phase 4) — `database/image_hash.py`.** The suggestion engine now unions a second,
  native (no-AI) signal: perceptual **dHash**. Shrink an image to a 9×8 greyscale grid and record, per pixel,
  whether it is brighter than its right neighbour → a 64-bit fingerprint; resize-invariant, so a full-res upload
  and a platform thumbnail of the same art sit a small **Hamming distance** apart. Hashes live in `image_hashes`
  keyed by `(platform, submission_id)`. Two populators behind `POST /api/collections/hash-scan`:
  `hash_local_artworks` (zero-network — hashes each local artwork image, stores the hash against every platform
  copy it was posted to) and `hash_scan(conn, fetch, limit)` (fetches un-hashed thumbnails, injected fetcher).
  **SSRF posture:** `is_allowed_thumb_url` permits https **only** on a hardcoded public-CDN host-suffix allowlist
  (`CDN_ALLOWLIST` — Inkbunny/FA/Weasyl/Bluesky/Tumblr/X/DeviantArt); the endpoint's fetcher is redirect-disabled
  and size-capped — same posture as `/thumb`, can't reach an internal host. pixiv (referer-gated), e621 (UA
  policy) and per-instance Mastodon are excluded on purpose. `collections_queries.auto_suggest_collections` unions
  `_auto_suggest` (title) with `image_hash.image_suggestions` (Hamming ≤ `HAMMING_THRESHOLD` = 8), deduping on the
  unordered member pair so a pair found by both is tagged `reason: 'both'`. The hub's "Suggested collections" card
  renders a 📝/🖼/✓ chip per row and a **🔍 Scan images** button.
- **Art shown in Collections (2.115.0, Phase 5).** `_location_from_submission` returns each location's
  `thumbnail_url`; the detail Locations table renders a per-posting thumbnail and `list_collections_with_summary`
  exposes `cover_thumb`/`cover_platform` (first location with an image) so a hub card auto-covers from the art.
  `collections.js._thumbSrc` routes FA/IB/Pixiv through the thumbnail relays (mirrors `artwork.js`).
- **Two art-grouping systems — the flagged "mess" (for §7 scoping).** The **Artwork hub** groups cross-posted art
  into "**masters**" via `artwork.js._foldMasters` + Unify/Split, which call `create_link`/`delete_link` on the
  **same `submission_links` tables** that Phase 3 folded into Collections. So `#/artwork` masters and
  `#/collections` are two overlapping grouping models. This is why `/api/links*` was kept **dormant, not deleted**
  in 2.113.0 — the Artwork hub still depends on it. Consolidating masters → Collections is the intended end-state
  but a structural change deferred to the removals scoping (`docs/specs/linking_picker_overhaul.md` §5/§7).

**Tag picker (2.112.0, Phase 2) — `frontend/js/tag_picker.js` (`window.TagPicker`).**
The sibling of WorkPicker for **tags** instead of works. `TagPicker.open({ title, selected, onConfirm })`
reuses the same `.tag-browser-*` modal chrome but fills the body with selectable **tag chips** (`.tp-chip`:
name + category badge) filtered by the six categories (`physical/acts/kink/meta/image/user`) plus a live
substring search. It loads the canonical tag database from `/api/editor/tags` and caches it in `sessionStorage`
under **the same `pawpoller_tag_db_v1` key the story editor uses**, so it's free after the editor (or the
picker) has opened once. `onConfirm(names)` receives the final selected tag names.
- **Why standalone and not a refactor of the editor's browser:** the story-editor tag browser
  (`metadata_editor.js`) is welded to `this.metadata.tags` — it reads every platform's tag set to show "also
  on" indicators and applies via `_addTagToPlatform` / `_addTagToChapter`, with no automated tests. TagPicker
  copies WorkPicker's pure-in/pure-out contract instead, so the editor is untouched.
- **Art module wiring (`frontend/js/artwork.js`):** a `🏷️ Browse tag library` button (`#art-tag-browse`,
  `_openTagLibrary`) under the default-tags box opens the picker seeded with the current tags and writes the
  confirmed selection back as a comma list. **Lossless** — free-typed tags that aren't in the library are
  pre-selected (via the picker's `preserve` map) and returned unchanged, so browsing never drops a tag.
- `.tp-*` chip CSS lives in `editor.css` (after the `.wp-*` block); script registered in `index.html` after
  `work_picker.js`. Reusable anywhere library-backed tag selection is needed outside the story editor.

## 20.10 Masterpieces — the master record for ONE image (2.124.0 Phase 0, 2.125.0 Phase 1)

A **Masterpiece** is the image analog of a story's `MASTER.md`: the canonical record for a single artwork
(title/desc/rating/tags/characters + the source image) that every site-upload of that image points back to. Spec:
`docs/specs/masterpieces.md` (§0 Amendments are binding). Two halves:

- **On-disk (Phase 0, §20.2)** — one artwork folder + `masterpiece.json` (back-compat superset of legacy
  `artwork.json`). This is the source of truth for the canonical metadata.
- **Relational (Phase 1)** — a name-keyed index + a membership table recording which platform uploads ARE this image:
  - **`masterpieces`** (`database/db.py`) — thin index `(id, name UNIQUE, source_link_id, timestamps)`; a Masterpiece
    is keyed by its folder **name**, NOT a numeric id (spec §0-A2), so the disk folder stays the identity.
  - **`masterpiece_members`** — `(masterpiece_name, platform, submission_id)` PK (idempotent re-link) + `account_id`,
    `role` (`primary`/`crosspost`), `linked_via` (`manual`/`phash`/`title`/`publish`). No stats stored — the pair
    resolves live against the per-platform `*_submissions` tables at rollup time, exactly like a Collection's
    submission members.
- **Rollup — `database/masterpiece_queries.py`.** Membership CRUD (`ensure_indexed`, `add_member`, `remove_member`,
  `get_members`, `member_pairs`) + `rollup_members(conn, name)` (resolves members → locations, pools non-None totals,
  unions tags, collects personas + platforms) + `summarize` (light grid rollup: totals, member count, platforms,
  auto-cover = first member with a thumbnail). It **imports `_location_from_submission` + `_acct_to_persona` from
  `collections_queries`**, so a Masterpiece and a Collection pool stats through the identical per-platform
  normalisation (`_METRICS`) — one source of truth. In Phase 1 members start empty (no promote flow until Phase 3),
  so a fresh Masterpiece rolls up to zeroed totals — expected.
- **Read API — `routes/masterpieces_api.py`** (`/api/masterpieces`, registered in `dashboard.py`): `GET ""` (every
  artwork folder + a light pooled `summary`, adopting each name into the `masterpieces` index on the way past),
  `GET /{name}` (canonical `masterpiece.json` **merged** with the live member rollup — `canonical_tags` = the master
  record's per-platform map, `tags` = the union observed on live member uploads), `GET /{name}/snapshots` (combined
  time-series across every site the image lives on, via `analytics_queries.get_combined_snapshots(conn, member_pairs)`).
  Read-only in Phase 1; the promote/link + edit-and-Sync write flows land in Phases 3–5.
- **Frontend (Phase 2, 2.126.0) — `frontend/js/masterpieces.js` (`window.Masterpieces`) + `masterpieces.css`.** The
  managed grid lives **inside Library** (`bookshelf.js`), not its own nav item (spec §0-A3): the shelf's type
  segment gains a fourth option **Masterpieces**, and `_paint()` delegates that segment to
  `Masterpieces.renderGrid(gridEl, {persona, search, sort})` — a `.mp-card` per Masterpiece (canonical-image cover ·
  title · N sites · pooled stats · persona dots) from `API.getMasterpieces()`. The list is cached per Library session
  (`resetCache()` called by `bookshelf.render()`). Cards link to the read-only **detail** `renderDetail(name)` at
  `#/masterpieces/{name}`: image hero + rating + persona dots + pooled headline; a read-only **Canonical record**
  panel (desc/characters/tags — editing is Phase 5); a **Published to** Locations table over `m.locations`
  (thumbnail via `_thumbSrc` FA/IB/Pixiv relays · platform · `primary`/`crosspost` role · per-platform stats ·
  open↗); and a combined chart (`Charts.aggregateLine` over `API.getMasterpieceSnapshots`, ≥2 points). `app.js` routes
  bare `#/masterpieces` → Library with the segment preset (`Bookshelf._type='masterpiece'`) and keeps the Library nav
  lit for both routes. Additive: the existing All/Stories/Artwork segments are unchanged; folding Artwork into
  Masterpieces (the spec's 3-way target) waits until members auto-populate on publish (Phase 4).
- **Promote + linking (Phase 3, 2.127.0) — the first write surface.** `masterpiece_queries.promote_from_submission`
  wraps `posting.artwork_importer.import_artwork` (idempotent full-res import → folder + `masterpiece.json` +
  publication), then seeds the source as the `role='primary'` member (account carried from the submission row) and
  stores the canonical image's dHash (`image_hash.dhash_from_path`) in `image_hashes` + on `masterpiece.json`.
  `masterpiece_queries.suggestions(conn, name)` is the anchored, no-AI same-image finder: seed pHashes = the members'
  stored hashes ∪ a fresh hash of the canonical image, then scan `image_hash.all_hashes` for rows within
  `HAMMING_THRESHOLD` (8) that aren't already members, resolved to `{platform, submission_id, similarity, title,
  thumbnail_url, account_id}` via `_location_from_submission`. Write API on `routes/masterpieces_api.py`:
  `POST /api/masterpieces {from:{platform,submission_id}}` (promote — 422 on an un-importable submission),
  `GET /{name}/suggestions`, `POST /{name}/members` (attach — account defaulted from the source row for persona
  correctness), `DELETE /{name}/members?platform=&submission_id=` (detach). Frontend: **"★ Master"** on Gallery
  discovered tiles (`artwork.js._makeMasterpiece` → `API.promoteMasterpiece` → open the detail); the detail view
  (`masterpieces.js`) gains a document-level click delegate driving a **"Link the same image elsewhere"** suggestions
  strip (`＋ Link` = `API.addMasterpieceMember`, `↻ Scan` = `API.scanImageHashes` then reload) and an **✕ unlink** per
  location (`API.removeMasterpieceMember`); both re-render the detail to re-pool stats. Editing the canonical metadata
  + Sync-all remain Phase 5.
- **Publishing IS mastering (Phase 4, 2.128.0).** `posting/manager.post_artwork` upserts a `masterpiece_member` on
  **each successful post** (`role='crosspost'`, `linked_via='publication'`, `account_id` from the post) right after
  it records the publication — idempotent + best-effort (wrapped so a link failure never breaks a recorded post). So
  every artwork publish (the existing hub AND a fresh Masterpiece) auto-accumulates members; a fresh "＋ New
  Masterpiece" (button on the Masterpieces grid → the `#/artwork/new` uploader, which writes a `masterpiece.json`
  folder) becomes a mastered record with live members purely by publishing. **e621** is in
  `artwork_reader._ALL_POSTER_IDS` (a valid art target, wired in `_get_poster`); **Instagram is not** — IG posting
  lives only in the Posts module (`post_publisher`), not `post_artwork`/`_get_poster`, so an art-target IG needs a
  net-new `IGPoster` adapter (deferred).
- **Canonical edit + Sync-all (Phase 5, 2.129.0) — "edit once, push everywhere".** The per-platform `edit(external_id,
  package)` methods turned out already metadata-oriented + content-type-agnostic (Weasyl metadata-only; IB reads
  content only when `file_type=='bbcode'`; FA's file refresh is gated on `extra['skip_content_refresh']`), so Phase 5
  is a new orchestration, not new posting code. **Edit:** `PATCH /api/masterpieces/{name}` whitelists title /
  description / rating (general|mature|adult) / characters / tags → `artwork_reader.save_artwork_metadata`. Editing the
  canonical **default** tags preserves real per-platform overrides — the route reads the un-cascaded file via new
  `artwork_reader.read_raw_metadata(name)` (since `load_artwork` cascades `tags.default` onto every poster id). **Sync:**
  `posting/manager.update_artwork(name, platforms=None, account_filter=None, extras=None)` mirrors `update_story` but is
  driven off `masterpiece_members` (reaches promote/pHash-linked members, not just publications) and **metadata-only**
  (`package.extra['skip_content_refresh']=True` — never re-uploads the image); it resolves each member's account
  (`_resolve_account_id`), calls `poster.edit` for `supports_edit` platforms, and returns non-editable ones
  (Bluesky/e621/Itaku) as `{skipped:True, reason:'post-only'}` — never touched (§0-A1). Async
  `POST /api/masterpieces/{name}/sync` aggregates `{synced, skipped, failed, results}`. Frontend (`masterpieces.js`):
  the Canonical record panel is an editable form (`_saveCanonical` → PATCH; `_openTagBrowse` → `window.TagPicker`); **↑
  Sync to sites** (`_syncAll`) saves then pushes behind a `window.confirm`, reports a per-member summary, and the
  Locations table badges non-editable platforms `post-only` (JS `_POST_ONLY` set mirrors the backend `supports_edit`).
- **Collections interop (Phase 6, 2.130.0).** A Masterpiece can be a Collection member — the two grouping axes connect
  without duplicating (per-image mastering vs cross-type bundling; §1.2 boundary). `collection_members` gains
  `member_type='masterpiece'` with `member_ref` = the **bare** Masterpiece name (the type disambiguates, unlike works'
  `content_type:name`). `collections_queries.rollup_collection` resolves it by lazy-importing `masterpiece_queries`
  (avoids the import cycle — `masterpiece_queries` imports this module at load) and folding every
  `masterpiece_members` location into the Collection's pooled totals/tags/personas (tagged with `masterpiece_name`);
  `collection_member_pairs` (snapshot chart) and `_collected_pairs` (suggestion exclusion) include them too;
  `collections_api._MEMBER_TYPES` gains `masterpiece`. Frontend: **"＋ Add to Collection"** on the detail header is a
  `data-add-collection data-mtype="masterpiece"` button caught by the existing document-level `collections.js`
  delegate (no new wiring); `work_picker.js` gains a **Masterpieces** filter chip (`FILTERS.masterpiece`, `mp:true`,
  fetching `GET /api/masterpieces` — kept out of "All" to avoid double-listing artwork folders) so the Collections
  "＋ Add member" browser can pick Masterpieces, whose `member_type`/`member_ref` pass straight into
  `addCollectionMember`.
- **Retire old masters + migration (Phase 7, 2.131.0) — the build's final slice.** The Gallery (`artwork.js`) no
  longer **mints** `submission_link` "art masters": the "Select → Unify selected" flow and the "Possible matches"
  suggestion strip (both called `API.createLink`) were removed along with their methods/state; the read-only
  **display** of any existing masters (`_foldMasters`/`_masterCard`/`_splitMaster`) is deliberately kept **dormant**
  (honours §7's "keep `/api/links` dormant until the fold is proven" — nothing is orphaned; on live there are zero
  links anyway). `collections_queries.auto_suggest_collections` now stamps each suggestion with `target`:
  `masterpiece` for a same-image (pHash) match, `collection` for a same-piece (title) match — so the one engine feeds
  both. `masterpiece_queries.migrate_links_to_masterpieces` mirrors `migrate_links_to_collections` (idempotent,
  reversible via `masterpieces.source_link_id`, account carried for persona correctness). **It is a callable, NOT
  wired to startup:** a migrated Masterpiece is index-only (no canonical image), so it would be invisible in the
  folder-based Library grid until "materialised" — auto-running it could silently mint grid-invisible Masterpieces
  (known limitation, spec §9). This completes the Masterpiece build (phases 0–7): a single image now has the full
  master lifecycle a story always had.

- **Junk bin (2.149.0) — kept-but-hidden status.** `masterpieces.status` (`''` active / `'junk'`, guarded ADD-COLUMN
  migration) marks pulled art the user doesn't want in the grid — memes, other people's commission ads, retired
  pieces — **without deleting** the folder, metadata or members (softer than the 2.144 merge, which deletes the
  duplicate). `masterpiece_queries.set_status/get_status/statuses`; **`POST /api/masterpieces/{name}/status`**
  `{status:'junk'|''}` — deliberately accepts **index-only names** (a Masterpiece with no folder, e.g. the swept-in
  tweets from `migrate_links_to_masterpieces`) since those can't be junked any other way. `GET /api/masterpieces`
  rows + `GET /{name}` carry `status`; the grid (`masterpieces.js renderGrid`) filters junked out by default and
  offers a **🗑 Junk (N)** toggle view with per-card ♻ Restore; the detail page has the Junk/Restore button + badge.
  The discovered-tile counterpart is the Ignore list (2.140, `ignored_submissions`) — Ignore is for *unpromoted*
  discovered art, Junk is for *Masterpiece records*.

- **Variants (2.158.0) — one piece, several renders, per-variant stats.** Spec
  `docs/specs/masterpiece_variants.md`. Definitions in `masterpiece.json` `"variants": [{key,label,image,
  rating}]` (images share the folder — declared 2.152 alts, effectively); attribution on
  `masterpiece_members.variant_key` (''=primary, guarded migration). Per-variant stats are the ordinary
  member rollup filtered by key — `rollup_members(conn, name, variant_key)` — so the cohort totals (no
  filter) are untouched by construction. Ways in: `POST /api/masterpieces/merge-as-variant` (fold a whole
  Masterpiece in as a labeled variant: image copied to the keeper's folder, members re-keyed KEEPING their
  stats, record deleted — `mq.merge_as_variant`; the dup-finder's third button "🖇 Variants of one piece"),
  `POST /{name}/variants` (declare an existing folder image), `DELETE /{name}/variants/{key}` (demote;
  members re-key to ''), `PATCH /{name}/members/variant` (attribute one upload). The hero stays the ONLY
  posting/pHash image. UI: the detail head is a stage (giant blurred `.mp-stage-bg` backdrop following the
  focused variant) and the gallery strip renders labeled chips + a per-variant stats line.

- **By-TITLE variant suggester (2.160.0) — the complement to the hash de-dup finder.** The dedup finder groups by
  perceptual hash = the same *image* on several sites. But a rough vs final, or SFW vs NSFW, are *different images*,
  so it can't group them — the tie is the **title**. `database/variant_suggest.py` (pure, tested): `base_title()`
  peels a conservative allow-list of stage/edit qualifiers off a title's end (`Midnight Snack (Rough)` → `midnight
  snack`) and `suggest_families()` groups folders sharing a base, deriving a hero (unqualified member, else
  most-viewed) + a per-member `key`/`label` from the suffix. **Conservative on purpose:** a word not on the list
  (`…for the Night`) stays part of the title, so distinct pieces don't merge on a coincidental suffix. `GET
  /api/masterpieces/variant-suggestions` feeds a **"Same piece, different renders" section on `#/masterpieces/
  duplicates`** ("Tidy up Masterpieces"); one button folds a family via the existing `POST /merge-as-variant` with
  labels pre-filled (no per-item prompt, unlike the dup screen's "🖇 Variants of one piece"). Dismiss = `POST
  /not-variant` → **`masterpiece_not_variant`, a SEPARATE lazily-created table** from `masterpiece_not_duplicate`:
  an SFW/NSFW pair are different images (dismissable there) yet ARE variants, so one dismissal must not imply the
  other. Review-only, never automatic — a title heuristic is fuzzy and it's the user's art (same rationale as the
  2.151 on-import prompt).

- **Per-piece "fold into another" (2.161.0) — dup/variant from the detail page, not just the bulk screen.** The merge
  actions used to live only on `#/masterpieces/duplicates`. `Masterpieces._paintDetail` now renders a **"Same piece
  as another?"** section: a `<datalist>` title picker of every OTHER Masterpiece (`_loadFoldPicker` → `getMasterpieces`,
  title→folder-name map, self excluded) + a duplicate/variant radio (variant reveals a label field). `_foldIntoAnother`
  folds **this** piece into the picked one — duplicate via `POST /merge` (keep=picked, drop=this; this folder removed,
  same image), variant via `POST /merge-as-variant` (this image copied into the target as a labeled alternate). Always
  "fold this into that", then navigates to the target. **Frontend-only** — both endpoints already existed.

- **Showcase (2.158.0) — the Library's OPT-IN XMB view.** `frontend/js/showcase.js` (`window.Showcase`): two
  animated shelves (Stories / Artwork-Masterpieces) with PS3-XMB navigation and an ambient art backdrop.
  **Never forced**: bare `#/library` opens in the last-chosen view — `localStorage['pp_library_view']`
  (`classic` default / `shelves`); classic's ▤ Shelf view and the Showcase's ✕ Classic view (or Esc) switch
  AND persist the choice. `#/library/browse` is the always-classic route (`switchType('all')` writes it;
  every `type/sort/work/discovered` deep-link still lands classic). Listeners are epoch-guarded so stale
  key/wheel handlers self-remove after navigation. Reduced-motion respected (`.sc-*` in `masterpieces.css`).

- **Detail gallery (2.152.0) — multi-image sets.** A Masterpiece folder can hold more than one image (multi-image
  tweet sets recovered from `tw_submissions.media_urls`, SFW/NSFW variants preserved by dupe merges) as
  `image_N.ext` beside the hero. `GET /api/masterpieces/{name}` returns `images: [...]` (every
  `IMAGE_EXTENSIONS` file in the folder, hero first); the detail view renders a `.mp-alts` thumbnail strip under
  the hero when there are 2+ and clicking swaps the hero image in place (served, as ever, by
  `GET /api/artwork/image?name=&file=` — already path-traversal-guarded for arbitrary folder files). The hero
  (`masterpiece.json`'s `image` key) remains the ONLY image used for posting and pHash duplicate detection.

- **Replace the canonical image (2.153.0).** "The artist sent the full-res / a fixed version." `PATCH
  /artwork/images/{name}` is metadata-only, so swapping the file used to mean delete + re-import — which threw away the
  record, its `masterpiece_members` links and all pooled stats. **`POST /api/masterpieces/{name}/image`** (multipart,
  `⇪ Replace image` under the detail hero) writes the new file into the existing folder and repoints
  `masterpiece.json`'s `image` at it. Everything else is deliberately preserved:
  - **Metadata + members untouched** — only the hero pointer moves, so links/stats carry straight over.
  - **Non-destructive** — the old file STAYS in the folder and therefore surfaces as a gallery alternate (above). A
    filename collision is suffixed `_v1`, `_v2`… so the current hero can never be clobbered.
  - **Only the hero moves** — sibling `image_N.*` (tweet sets, SFW/NSFW variants) are never touched.
  - **The cached `__mp__` hero hash is DELETED** so `image_hash.hash_masterpieces()` recomputes it. Skipping this would
    leave the de-dup finder (§ Masterpiece de-duplication) comparing the OLD pixels forever.
  - Guarded by the same 50 MB cap + `IMAGE_EXTENSIONS` allowlist as the artwork uploader; 404 on an unknown name.


## 20.12 Discovered posts → the Posts module (2.157.0)

**`posting/post_importer.py`** — the text-side mirror of `artwork_importer`. The discovered queue only ever
offered **import-as-artwork** (download an image → mint an artwork folder), but the live queue was **62 items,
60 with no image, 54 of them tweets**: for ~90% of it there was nothing to download and no workable action but
Ignore. A tweet is a **post**, and the Posts module already has the shape for one (`posts.body` +
a `post_publications` row per platform), so this imports the poller's own stored row into it.

- `POST /api/posts/import/{platform}/{submission_id}` (one) and `POST /api/posts/import/discovered` (bulk).
  Declared **before** the generic `/{post_id}` routes so their literal segments aren't shadowed.
- **No network call** — reuses stored poller metadata. `description` holds the full post text while `title` is
  usually a truncated display copy, so it prefers `description` and falls back to `title`.
- **`account_id` is carried through.** Every poller row records the account it was found under; the tweets span
  three (KnaughtyKat / KiiKinar / NaughtyKiiKinar). Dropping it is what made every import land on the platform
  default and lump the personas together until 2.96.0 — see `artwork_importer`, which carries it for the same reason.
- **Idempotent.** `already_imported()` looks up `post_publications` by `(platform, external_id)` and returns the
  existing `post_id` instead of minting a duplicate.

**The exclusion set is the load-bearing part.** `get_discovered_unlinked` excluded `publications`, Masterpiece
members and ignores. `post_publications` is a **separate registry** (`posts_schema.sql` is deliberately not the
story/artwork `publications` model — a post has no title/chapters/file), so an imported post matches none of those
and would sit in the queue forever. It's now a fourth exclusion set. `tests/test_post_importer.py` asserts the item
is in the queue before the import and gone after.

**Text-only, deliberately.** Image-bearing items already have a home (Import → artwork, ★ Master → Masterpiece);
importing them here would mean either downloading media into `posts_media/` or silently dropping the image. The gate
(`is_importable_post`, mirrored client-side by `Submissions._canImportPost`) is *microblog platform*
(`MICROBLOG_PLATFORMS = tw/bsky/mast/thr/tum`) **and** no image. The platform check matters: a SquidgeWorld text
work or a thumbnail-less DeviantArt piece is a story/artwork that happens to lack an image, **not** a post.

**The gate must NOT consult `kind` (2.157.1).** `classify_kind` lists `"post"` among its `_ART_TYPE_HINTS` — on
purpose, so an image-bearing Bluesky/Mastodon post is catchable by the artwork import — which means **every**
Bluesky post is tagged `kind: "art"` regardless of content. 2.157.0 gated on `kind != "art"` and so hid the button
from exactly the imageless microblog posts it exists for (found by checking the live queue: a bsky and a mast item
fell through to "neither"). No image ⇒ nothing for the artwork path to download (`import_all_discovered_art`
filters on `thumbnail_url` for the same reason) ⇒ on a microblog it's a text post. The image routes it, not `kind`.


## 20.11 One works hub — the Library (2.155.0, backlog L)

**The Library (`#/library`, `frontend/js/bookshelf.js`) is the single hub for your works.** It had
grown alongside two others that listed the same records, because **`/api/works` has always returned
both kinds behind a `content_type` discriminator** (`"story"` / `"artwork"`, set in
`routes/submissions_api.py` `assemble_works`). That made:

- **Stories** (`#/posting`) = `/api/works` filtered to stories, with no search and no sort — a strict
  subset of the Library's Stories segment, linking to the same detail page;
- **Artwork** (`#/artwork`) = `/api/works` filtered to artwork, plus a discovered-tile surface.

Both hub routes now **redirect** (`#/posting` → `#/library/type/story`, `#/artwork` →
`#/library/type/artwork`), as does **`#/submissions`** → `#/library` — that hub lost its nav entry
in 2.117.0 but never stopped rendering, leaving a *fourth* works hub reachable by URL. Their
*sub-pages* are untouched and still live — **merging the hubs did not merge the pages behind
them.** `#/submissions/discovered` still serves the standalone discovered page.

### Segments

`Bookshelf._type` ∈ `Bookshelf.TYPES` = `all | story | artwork | masterpiece | discovered`.

| Segment | Rendered by | Notes |
|---|---|---|
| all / story / artwork | `_paint()` → `_book()` over `_works` | client-side filter of the cached `/api/works` list |
| masterpiece | `Masterpieces.renderGrid(grid, {persona, search, sort})` | its own managed surface (`/api/masterpieces`) |
| discovered | `Submissions.renderDiscoveredInto(grid)` | the review queue — see below |

**`#/library/type/{t}`** deep-links a segment (router validates against `TYPES`, falling back to
`all`). Clicking a segment goes through **`Bookshelf.switchType()`**, which switches **in place** and
writes the URL with **`history.replaceState`** — assigning `location.hash` would fire `hashchange` →
`route()` → a full `render()` and a second `/api/works` call just to filter data already in memory.
Bare `#/library` **explicitly resets `_type = 'all'`**: it's module state that survives navigation, so
without the reset, arriving from `#/masterpieces` or a `type/` deep-link would show that segment while
the URL claimed the full shelf.

**Discovered** is a *review queue*, not a shelf of your works, so `switchType` hides the
persona/search/sort controls there (they'd be dead inputs) and the segment carries a count badge fed
by `_loadDiscovered()`. `renderDiscoveredInto(target)` is a thin entry point beside the standalone
`Submissions.renderDiscovered()` page (`#/library/discovered`, still routed): both set `_discItems` /
`_workOptions` then call `_paintDiscovered()`, which targets `#disc-list` — so the rows and **their
actions (link · import · 🚫 Ignore · the per-platform bulk bar) are the same code**, not a
reimplementation. The page is just this plus a header.

**`_masterOne()` / `_canMaster()` are a PORT, not a move.** ★ Master (promote-to-Masterpiece, 2.151.0
backlog M) existed *only* on the Artwork hub's discovered tiles — these rows never had it — so
retiring that hub without porting would have silently removed the feature. Same flow, same duplicate-
check prompt. `_canMaster` gates on **image-bearing and not-text**, deliberately NOT on the old hub's
`_PLATFORMS` allowlist: that list omits X/Threads, which is exactly what hid the Ignore buttons until
2.143.0 — this is the surface where discovered items get reviewed, and tweet art is a real source of
Masterpieces.

### What the merge had to carry

`assemble_works` now projects **`description` / `category` / `warnings`** for stories — the retired
Stories hub showed a blurb, a category chip and a ⚠ tooltip that weren't in the payload, so folding it
in would have silently dropped them (`tests/test_works.py`). The Ignored + History links moved to the
Library header (`.shelf-topbar-actions`).

Everything pointing at the dead hubs was repointed rather than left to double-hop through the
redirect: sidebar (`index.html` — Publish → Stories/Artwork removed; Library is already top-level),
**bottom nav** (its Stories slot → Library), breadcrumbs + nav-active rules (`app.js` — story detail
and artwork detail/log/ignored light **Library** now), `command_palette.js`, and Artwork's back-links.

**Tours** (`tour.js`): `#/library` had **no tour at all** despite being the main hub, while three
toured DOM that no longer renders — `submissions` (hub retired 2.117.0), `stories` and `artwork`. All
three are replaced by one `library` tour, and `tourForHash` maps `#/library` + `#/library/type/*` to
it. The registry is consistent both ways (nothing defined-but-unreachable or returned-but-undefined).

### Known gaps (deliberate — backlog L1/L2)

- **Masters-folding of discovered art** went with the Artwork hub. It grouped one piece cross-posted
  to several sites into a single tile via `submission_links` (`_foldMasters`/`_masterCard`/
  `_splitMaster`); the Discovered segment lists them as separate rows. Not ported on purpose: it is
  the older of the **two art-grouping systems** flagged as a "mess" in §20.9 — **Masterpieces
  supersedes it**, and cross-platform links are slated to merge into Collections.
- **🗑 delete off an artwork card** is gone; artwork **detail** has always had Delete (one extra click).
- `Posting.renderUpload` + `Artwork.render` and ~400 lines of hub-only helpers are **unreachable but
  present** — the port source for the above. Verified reachable only from the dead hub block, so
  removal is safe once L1 is settled.


## 21. Posts hub (microblog / "tweet-like" publishing, 2.49.0)

The third publishing hub beside Stories and Artwork, for short-form posts to
microblog platforms. Compose once → publish to **Bluesky, Mastodon, Threads,
Tumblr, X and Instagram** (`post_publisher.SUPPORTED`). Bluesky/Mastodon/X carry
images (up to 4); Threads/Tumblr are text-only (`_TEXT_ONLY`); **Instagram is the
inverse — it REQUIRES a photo** (`_IMAGE_REQUIRED`; no text-only IG post) and,
uniquely, needs the image at a public URL because Meta cURLs it rather than
accepting an upload. That public-image mechanism lives in `posting/ig_media.py`:
a JPEG copy is stashed on the data volume and served unauthenticated at
`GET /api/ig/pubmedia/{token}` (auth-exempt prefix in `dashboard.py`; uuid4 token
+ path-traversal guard + 15-min TTL, deleted after publish), so on the server IG
posting needs `ig_public_base_url` (`IG_PUBLIC_BASE_URL` in `.env`) set to the
server's public address. `IgClient.create_post` does the two-step
container→`media_publish` flow (with 2–10 photo carousels). IG posting needs the
`instagram_business_content_publish` scope + a Business/Creator account.

**Desktop posting via image relay (2.67.0).** The desktop app binds to
`localhost`, which Meta can't reach — so a **paired desktop** instead borrows its
server as the image host. New authenticated endpoint **`POST /api/ig/pubmedia`**
(`routes/ig_api.py`) accepts an uploaded image, stashes it via
`ig_media.stash_bytes` (the raw-bytes sibling of `stash_image`), and returns
`{token, url}`. It shares the path prefix with the open GET but **requires auth**:
the POST has no trailing slash, so it falls outside the `/api/ig/pubmedia/`
auth-exempt prefix, and the desktop authenticates with the same Bearer API key it
already uses for story/artwork sync. `post_publisher`'s `ig` branch chooses its
host at publish time — `ig_public_base_url` set → stash locally (server); else
`posting_server_url` + `posting_server_api_key` set → relay each image to the
server (`_relay_stash_image`, multipart httpx upload); else a clear error naming
both options. No new settings — it reuses the existing desktop↔server pairing.

### 21.1 Why a separate store (not the publications registry)

A microblog post has no title, chapters, or source file — forcing it onto the
story/artwork `Package`/`publications` model buys nothing. So Posts gets its own
pair of tables (`database/posts_schema.sql`):

- **`posts`** — `post_id`, `body`, `rating` (general|mature|adult), `image_path`
  (optional local media under `DATA_DIR/posts_media/`), `image_alt`, timestamps.
  `image_path`/`image_alt` now mirror the **first** attached image (backward compat).
- **`post_media`** (2.58.0) — `ordinal, path, alt` per attached image; a post can
  carry up to 4 (the X/Bluesky/Mastodon cap). `get_post`/`list_posts` attach a
  `media` list (synthesised from the legacy `image_path` for old posts).
- **`post_publications`** — one row per `(post_id, platform, account_id)` publish
  attempt: `status` (pending|posted|failed), `external_id`, `external_url`,
  `error`. `UNIQUE(post_id, platform, account_id)` so a re-publish upserts over a
  prior failure.

Wired into `database/db.py` `init_db()` after the posting schema. Analytics for
what these posts *earn* still flows through the normal per-platform pollers
(`bsky_submissions`, etc.) — this pair only tracks the compose→publish side.
Thin CRUD in `database/posts_queries.py` (caller supplies timestamps so the
helpers stay pure/testable).

### 21.2 Engine — `posting/post_publisher.py`

`publish_post(post_id, platforms, account_ids, settings)` loads the post and, per
platform, calls `_publish_one`, then upserts the publication row. `_publish_one`
resolves the account's credentials the same way the pollers do
(`config.resolve_account_credentials`, default account via
`accounts_db.get_default_account_id`, legacy single-account fallback) and
constructs a **fresh** client — never the poller singleton — so posting can't
mutate a client mid-poll (same lesson as the 2.47.0 DA throwaway-client fix).
Rating maps to Bluesky self-labels (`_BSKY_LABELS`: mature→`sexual`,
adult→`porn`) and Mastodon `sensitive`. `SUPPORTED = ("bsky", "mast", "thr", "tw",
"tum")`; any other platform returns `success=False, error="… isn't wired yet"`. Never
raises — every failure comes back as a result dict + a recorded `failed` row.

### 21.3 Client posting methods

Image support (2.58.0): **Bluesky, Mastodon and X carry images — up to 4 each**;
**Threads and Tumblr stay text-only** (`post_publisher._TEXT_ONLY`) because each
needs distinct image work — Threads pulls from a public `image_url` (no upload),
Tumblr needs NPF. The publisher refuses an attached image on those two *before*
any network call, and builds `image_paths`/`image_alts` from the post's `media`
list (legacy `image_path` synthesised when absent).

X image posting is **unverified in CI** — it needs a live cookie session and
fires a real public tweet. `TWClient.upload_media()` does the simple v1.1 upload
on `upload.x.com` (reusing the client's cookie/CSRF/bearer session) and
`create_tweet(text, media_ids)` attaches the ids. If X moves the endpoint off
`upload.x.com` it 401s → a failed (not wrong) tweet, fixable in one line.

- **Bluesky**: reuses `clients/bsky/client.py` `create_post(text, *, image_path,
  image_alt, image_paths, image_alts, labels)` → `{uri, cid, url}`. Up to 4 blobs.
- **Mastodon**: `clients/mast/client.py` `create_status(text, *, image_path,
  image_alt, image_paths, image_alts, sensitive, visibility, idempotency_key)` →
  `{id, uri, url}`. Up to 4 media. Images
  via `_upload_media` (`POST /api/v2/media`, id usable even on the 202 reply);
  status posts to `POST /api/v1/statuses` with an `Idempotency-Key`. **Needs a
  write-scope token** — the poll-only `read` token 403s.
- **Threads** (2.50.0): `clients/thr/client.py` `create_thread(text)` → `{id,
  url}`. The Graph API 2-step: `POST /{user_id}/threads` (media_type=TEXT) →
  `POST /{user_id}/threads_publish` (creation_id) → `GET /{media_id}?fields=
  permalink`. Reuses `thr_access_token`/`thr_user_id`; the token must carry
  **`threads_content_publish`** or publish 400s.
- **X/Twitter** (2.50.0): `clients/tw/client.py` `create_tweet(text)` → `{id,
  url}` via the internal **CreateTweet GraphQL mutation** over the same cookie
  session as polling (`tw_auth_token`/`tw_ct0`, `_BEARER`, `x-csrf-token=ct0`) —
  **no new creds**. `_GRAPHQL_CREATE_TWEET` + `_CREATE_TWEET_FEATURES` rotate
  with X's web client; refresh from x.com's `main.*.js` if it 404s / errors on
  missing features. X actively fights automation, so treat this as best-effort.
- **Tumblr** (2.50.0): `clients/tum/client.py` `create_text_post(body, title,
  tags)` → `{id, url}` via the OAuth1-signed legacy `POST /blog/{blog}/post`
  (`type=text`). The read-only `api_key` can't post, so this needs the full
  OAuth1 user token: NEW creds `tum_consumer_secret` / `tum_oauth_token` /
  `tum_oauth_token_secret` (in `PLATFORM_CREDENTIAL_FIELDS["tum"]` + the
  vault-encrypted `CREDENTIAL_FIELDS`). No oauth lib is installed, so the
  **HMAC-SHA1 signer is hand-rolled** (`_oauth1_header` + `_pe`, RFC 5849 §3.4)
  — unit-tested against the canonical Twitter OAuth1 example and cross-validated
  with `openssl` (`tests/test_oauth1.py`).

### 21.4 API + frontend

`routes/posts_api.py` (`/api/posts/*`): `GET ""` (feed, newest-first with
publications) / `POST ""` (create — multipart so an optional image rides along;
magic-extension + 25 MB guarded; row created first, image saved as
`posts_media/{post_id}{ext}`) / `POST /{id}/publish` / `DELETE /{id}` (+ media
cleanup) / `GET /image?post_id=` (traversal-safe: path derived from the id,
resolved-parent check). Registered in `dashboard.py`.

`frontend/js/posts.js` (`window.Posts`) + `frontend/css/posts.css`: a single
page with a compose card (textarea, optional image + preview, rating select,
per-platform checkboxes with account `<select>`s, a 300-grapheme Bluesky soft
counter that reddens when Bluesky is checked and over) over a feed of composed
posts. Each feed card shows the body/image/rating, per-platform status badges
(posted → external link, failed → hover-title error), and delete. `#/posts`
route + a **Posts** nav entry (💬) sit beside Artwork. `_PLATFORMS = ['bsky',
'mast', 'thr', 'tum', 'tw']`; `_DEFAULT_CHECKED = ['bsky', 'mast']` — the three
text-only platforms are badged **text** and start unticked (they need their
posting creds set up first).

### 21.5 What's verified

Unit tests (`tests/test_posts.py`, 8): queries CRUD + publication upsert,
`update_post` allowed-field filtering, the rating→label map, the unsupported-
platform short-circuit (Pixiv), the not-connected credential path for all five
targets, the text-only image guard for thr/tw/tum, and an end-to-end
`publish_post` that records a `failed` row. OAuth1 (`tests/test_oauth1.py`, 2):
`_pe` RFC-3986 encoding + the HMAC-SHA1 signature against the canonical Twitter
example, cross-validated with `openssl`. HTTP-smoke-verified through a Starlette
`TestClient`: create→list→publish (all five resolve with correct per-platform
errors)→get→delete. **Not** verifiable without live creds/posting: an actual
toot/skeet/tweet/thread/tumbl landing — those are user-side dashboard tests (and
would create real posts). Fragility to watch: X's CreateTweet query id/features
rotate; Threads needs the publish permission; Tumblr/Mastodon need the right
token scope.

### 21.6 @mentions across platforms — the handle-book (2.61.0)

The problem: the same person's handle **differs per network**
(`@name.bsky.social` vs `@xname` vs `@user@instance` vs `@threadsname`), so
"compose once, publish to all" can't share a literal `@handle`. And Bluesky —
unlike X/Mastodon/Threads, which auto-link server-side — needs explicit
**rich-text facets** or a `#tag`/`@handle` is dead plain text.

Model: you tag with a short **alias** (`@luna`) and bind it once to a
**contact** carrying that person's per-platform handles; the publisher expands
the alias into the right handle per network at send time.

- **Store** — `post_contacts` (name + `handle_bsky/tw/mast/thr/tum`, handles
  saved without a leading `@`) is the reusable handle-book; `post_mentions`
  (`post_id, token, contact_id`, `UNIQUE(post_id, token)`) binds a post's alias
  tokens to contacts. Both auto-create via `posts_schema.sql`. Queries in
  `posts_queries.py` (`add/list/get/update/delete_contact`, `set_post_mentions`,
  `get_post_mentions` — a LEFT JOIN so a deleted contact leaves the alias as
  plain text). `get_post` attaches `post["mentions"]`; `delete_post` clears them.
- **API** — `posts_api.py`: `GET/POST /api/posts/contacts`,
  `PATCH/DELETE /api/posts/contacts/{id}` (defined **before** the `/{post_id}`
  routes so `/contacts` isn't parsed as a post id). `POST /api/posts` gained a
  `mentions` form field (JSON `[{token, contact_id}]`; malformed → skipped, never
  fails the post).
- **Render + facets** — `post_publisher._render_body(body, mentions, platform)`
  substitutes each bound `@alias` for that platform's handle (whole-token, so
  `@luna` ≠ `@lunar`; no handle for the platform → left as plain text). For
  Bluesky the publisher passes the bound contacts' Bluesky handles as
  `mention_handles` to `BskyClient.create_post`, which now builds facets via
  `_build_facets` = links (`_extract_link_facets`) + **`#hashtags`**
  (`_extract_tag_facets`, applies to *every* Bluesky post — fixes the long-
  standing dead-tag bug) + **`@mentions`** (`_build_mention_facets` →
  `resolve_handle` per handle → DID). Overlapping ranges are dropped (a `#anchor`
  inside a URL) and facets are byte-sorted. X/Mastodon/Threads just receive the
  substituted text and auto-link it.
- **Composer** — `posts.js` scans the body for `@\w+` aliases and shows a
  **Tag** panel: a `<select>` per alias binds it to a contact (auto-selected when
  a contact's name equals the alias) or opens an inline **add-contact** form
  (name + the five handle fields). Bindings ride along in the `mentions` form
  field. Contacts load once per render (`API.getContacts`); tagging is additive —
  if the contacts fetch fails the composer still works, aliases just stay plain.
- **Contacts manager (2.62.0)** — `#/posts/contacts` (a **Tag contacts** button
  on the Posts header, route in `app.js`): each contact as a card (name + handle
  chips) with **Edit** (inline prefilled form → `PATCH /api/posts/contacts/{id}`)
  / **Delete** (→ `DELETE`, cascades to `post_mentions`) + **New contact**.
  `Posts.renderContacts`/`_loadContactList`/`_contactCard`/`_openManagerForm`/
  `_saveManagerContact`/`_deleteContact`; the composer's inline add-form and the
  manager share the `_MENTION_FIELDS` layout + `.post-cf-*` styles.
- **Directly-typed handles auto-facet on Bluesky (2.62.0)** — you don't have to
  bind an alias for a mention Bluesky can already resolve: `_build_facets` merges
  the bound `mention_handles` with `_detect_handle_mentions(text)` (domain-shaped
  `@x.y` only — a bare `@alias` still needs a binding, an email's `@domain` is
  skipped via a lookbehind), so a typed `@name.bsky.social` is resolved+faceted.
  The rework also drops any mention/hashtag facet overlapping a URL facet (AT
  Protocol rejects overlapping ranges).
- **Tests** (`tests/test_posts.py`): `_render_body` per-platform expansion +
  whole-token/unbound safety, `_extract_tag_facets` (byte offsets, `#1` rejected,
  trailing-punct trim), `_detect_handle_mentions` (dotted-handle vs bare-alias vs
  email), the contacts↔mentions round-trip + cascade deletes. **Not** unit-tested
  (network): live DID resolution / a real faceted skeet — a user-side test.


## 22. Platform setup guides ("How to get started", 2.65.0)

Every platform ships an in-app **setup guide** — how to go from nothing to a
connected credential, plus how to renew it when a cookie/token expires. Pure
frontend, no backend.

- **Content** — `frontend/js/platform_guides.js` exposes `window.PlatformGuides`
  with a `GUIDES` object keyed by platform code. Each entry: `kind`
  (Analytics | Analytics + posting), `difficulty`, `summary`, `need[]`
  (prerequisites), `steps[]` (`{t, b, link?}` — ordered, `b` may hold simple HTML,
  `link` is an external `{label, url}`), `paste` (where the credential goes in
  PawPoller), `renew` (`{when, how}` — the "keeping it alive" story), `notes[]`
  (gotchas). `renderBody(code)` turns one entry into the guide HTML shared by both
  surfaces below.
- **Controller** — the same file exposes `window.Guides`: `openModal(code)` (builds
  a self-contained `.guide-modal` overlay with backdrop-click + Escape close),
  `renderHub()` (the Getting Started page), and `injectSettingsButtons()`. A single
  delegated `document` click handler on `[data-guide]` powers every trigger, so
  nothing needs re-binding after a re-render.
- **Surface 1 — connect cards.** `injectSettingsButtons()` runs at the end of
  `App.renderSettings()`. It scans the `data-tab-content="platforms"` pane for
  `[id$="-connect-btn"], [id$="-disconnect-btn"], #save-creds-btn` (the Inkbunny
  save button → `ib`; `telegram` skipped), derives the platform code, and inserts a
  `.guide-trigger` ("📖 Setup guide") after each. Idempotent — safe on every
  settings re-render (and there are many, after each connect/disconnect).
- **Surface 2 — Getting Started hub.** Sidebar entry → `#/getting-started` →
  router branch calls `Guides.renderHub()`, which iterates `window.PLATFORMS` into
  a card grid (emoji/name/kind/summary/difficulty); a card's `data-guide` opens the
  same modal.
- **Surface 3 — Platforms hub tiles (2.66.0).** `App.renderPlatformsHub()` fetches
  `/api/platforms/health` in parallel with the per-platform summaries and reads each
  platform's `configured` flag. A configured tile is unchanged (stat + "N works"); an
  un-configured tile shows **"Not set up yet"** plus a `.hub-tile-guide`
  `<span role="button" tabindex="0" data-guide="{code}">` (only when
  `PlatformGuides.has(code)`). The span sits inside the tile's `<a>`, so the delegated
  `[data-guide]` click handler's `preventDefault()` opens the modal instead of
  following the tile link; a sibling Enter/Space `keydown` delegate covers keyboard
  (the hub cards in Surface 2 are real `<button>`s and need no keydown).
- **Styling** — `frontend/css/guides.css`, entirely design-token based, so it
  retones across all 8 themes. Loaded in `index.html` after `posts.css`;
  `platform_guides.js` loads after `platforms.js`/`components.js` and before
  `app.js` (it needs `window.PLATFORMS`/`window.platformByCode`).

### Settings → Platforms accordion polish (2.87.0)

The Settings → Platforms pane is a hand-written stack of `<details class="settings-accordion">`
blocks (one per platform), emitted inline by `App.renderSettings()`. Three cosmetic issues were
fixed without touching that markup wholesale — a **post-render enhancement pass** re-orders and
decorates the already-rendered accordions:

- **Inkbunny auto-open bug.** The Inkbunny `<details>` carried a stray hardcoded `open` attribute,
  so it was expanded on every visit. Removed in `app.js` — it now starts collapsed like the rest.
- **`App._enhancePlatformSettings()`** — called once after the platforms lazy-tab finishes loading
  (idempotent; the whole body is `try`-wrapped so a DOM change can never break Settings). It selects
  `:scope > details.settings-accordion` in the platforms pane (skipping the `#session-health-dot`
  block, which stays pinned first), matches each accordion to `window.PLATFORMS` by its visible name
  (`_accordionName()` clones the summary and strips the status dot / meta / logo / emoji before
  reading `textContent`), sorts by `localeCompare(…, {sensitivity:'base'})`, and re-`appendChild`s
  them in order. Because it moves the existing nodes (no innerHTML rewrite), every connect/disconnect
  handler already bound inside stays intact.
- **`_decoratePlatformSummary(summary, p)`** — adds the `.pset-summary` class and inserts an
  `<img class="pset-logo" src="${p.logo}">` (from `window.PLATFORMS[].logo`,
  `/img/platforms/{code}.{png,svg}`) right after the status dot, with an `error`-listener fallback
  that swaps in the platform emoji (`.pset-emoji`) if the logo 404s.
- **Centring** — `.pset-summary` CSS (`components.css`) centres the logo + name row; the status dot
  is `position:absolute; left` and the expand caret `::after` is `position:absolute; right`, so the
  title reads centred regardless of dot/caret width.

Refinements in **2.88.0**:

- **Uniform logo size.** One source asset (`img/platforms/tw.png`, the X mark) had ~50% transparent
  padding, so it rendered at half the size of the others. It was trimmed to its alpha bounding box and
  re-padded to a ~89% fill so it matches. `.pset-logo` is now 20×20 (was 18). If you add a new platform
  logo, trim its transparent border so the mark fills ~85-95% of the canvas, or it'll look tiny next to
  the rest.
- **True-centred titles.** The connected-account meta (`.summary-meta`, e.g. "— KnaughtyKat") used to sit
  inside the centred flex group, so a row *with* an account had its title pushed off-centre relative to
  account-less rows. `.pset-summary .summary-meta` is now `position:absolute; right:46px` (muted,
  ellipsised) — out of the centring flow — so every title lands on the same centre. (The Session-health
  header row is excluded from `.pset-summary`, so its inline meta is unaffected.)
- **Footer — `App._appendPlatformsFooter(pane)`** (called at the end of `_enhancePlatformSettings`,
  idempotent, re-appended last each paint so it stays below the re-ordered accordions). Emits
  `#pset-platforms-footer` with two blocks: (1) a `.pset-accounts-note` pointing multi-account users at
  the Accounts page — the creds set here are the *primary* account per platform — with a
  `<a class="btn btn-secondary" href="#/accounts">Manage accounts →</a>` (plain hash link, no JS handler);
  (2) a `.pset-trademark` line stating the platform names/logos are trademarks of their owners, shown for
  identification only, PawPoller unaffiliated. Styles in `components.css` under the `.pset-footer` block.
