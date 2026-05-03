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
| 7 | DeviantArt  | Art, literature      | Undocumented Eclipse _napi |
| 8 | Wattpad     | Stories              | Public REST API |
| 9 | Itaku       | Art                  | Public REST API |
| 10 | Bluesky    | Social (microblog)   | AT Protocol public API |
| 11 | X/Twitter  | Social (microblog)   | Cookie-based GraphQL scraping |

### Two Operating Modes

**Desktop** (`main.py`): pywebview native window + pystray system tray + all pollers. Designed for Windows. The dashboard runs at `127.0.0.1:8420` and is accessed through an embedded browser window. Requires desktop-only dependencies: pywebview, pystray, Pillow, winotify.

**Headless** (`server.py`): pollers + dashboard only, no GUI dependencies. Designed for Docker / Linux server deployment. Binds `0.0.0.0:8420` by default. Uses `requirements-server.txt` which excludes all desktop dependencies.

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
├── updater.py               # Auto-update (desktop only)
├── auto_sync.py             # Settings auto-sync: debounced push + 5-min pull thread (desktop ↔ server)
│
├── clients/                 # Per-platform HTTP clients (all 11 platforms in one place — 2.14.3)
│   ├── ib/                  #   Inkbunny — InkbunnyClient with SID caching
│   ├── fa/                  #   FurAffinity — FAClient with dual HTTP transports
│   ├── weasyl/              #   Weasyl — WeasylClient with cursor pagination
│   ├── sf/                  #   SoFurry — SoFurryClient with CF proxy support
│   ├── sqw/                 #   SquidgeWorld — SqWClient with Anubis challenge solving
│   ├── ao3/                 #   AO3 — AO3Client with CSRF auth
│   ├── da/                  #   DeviantArt — DAClient with cookie auth + proxy
│   ├── wp/                  #   Wattpad — WPClient (no auth, public API)
│   ├── ik/                  #   Itaku — IKClient (no auth, public API)
│   ├── bsky/                #   Bluesky — BskyClient with JWT session auth
│   └── tw/                  #   X/Twitter — TWClient with cookie auth
│   # Each subfolder has client.py (sometimes models.py for ib).
│   # Imports: `from clients.<platform>.client import <Class>`.
│
├── auth/                    # Browser-based login helpers (Phase 8a)
│   ├── __init__.py          #   Package init
│   └── browser_login.py     #   pywebview popup login for cookie-based platforms (FA, DA, TW, SF, WS, AO3, SqW)
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
│   ├── index.html           # SPA shell (collapsible nav groups, bottom nav bar, sidebar overlay)
│   ├── epub-viewer.html     # In-app EPUB reader (2.17.6+) — opened in new tab from editor Downloads dropdown
│   ├── css/
│   │   ├── tokens.css      # Design tokens (8 themes via [data-theme=...] custom properties)
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
├── requirements.txt         # Desktop dependencies (pywebview, pystray, Pillow, winotify, etc.)
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

---

## 2. Entry Points

### `main.py` — Desktop GUI Mode

Startup sequence in detail:

**Step 1: Database initialisation**
```python
init_db()  # Creates tables/schema if the DB file does not exist yet
```

**Step 2: Launch 15 daemon threads**
All threads are `daemon=True` so they terminate automatically when the main thread (pywebview) exits. No explicit shutdown signalling is needed. Each thread is named for debugging (`threading.Thread(name="FA poller")`).

Thread launch order: Uvicorn → IB poller → FA poller → WS poller → SF poller → SqW poller → AO3 poller → DA poller → WP poller → IK poller → BSKY poller → TW poller → Telegram digest → Telegram bot → Posting scheduler.

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
1. **Polls all configured platforms concurrently** via `asyncio.gather()` — all 11 platform poll functions run in parallel within one async event loop
2. **Sends one consolidated Telegram summary** covering all platform results (individual per-platform notifications are suppressed via `orchestrated_poll_active` flag)
3. **Checks if the regular digest is due** — fires `send_digest_report()` when the elapsed time since `last_digest_sent_at` exceeds `telegram_digest_interval_hours`
4. **Checks if the weekly digest is due** — fires `send_weekly_digest_report()` when 7 days have elapsed since `last_weekly_digest_sent_at`
5. **Sleeps for `poll_interval_minutes`** (default 240 minutes, minimum 15), then repeats

The orchestrator uses a single `poll_interval_minutes` setting (not per-platform intervals). The poll interval is intended to be a divisor of the digest interval (e.g. poll every 4h, digest every 12h = digest fires every 3rd cycle), guaranteeing fresh data for every digest without double-polling.

First-poll notification suppression: the orchestrator tracks `_first_cycle = True` and suppresses the consolidated Telegram summary on the first cycle. Data is collected normally to establish a baseline.

The orchestrator respects `polling_paused`: when paused, polling is skipped but the sleep/schedule loop continues so that the cycle resumes immediately when unpaused. Manual `/poll` commands via the Telegram bot still work by calling individual poll functions directly.

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

---

## 3. Threading Model

`main.py` and `server.py` use different threading architectures:

### `main.py` — 15-Thread Model (Desktop)

`main.py` spawns 15 daemon threads plus the main thread (pywebview). Each platform gets its own poller thread with an independent poll interval:

| Thread | Purpose | Interval Source | Default |
|--------|---------|----------------|---------|
| Uvicorn | FastAPI dashboard server | N/A (always-on) | — |
| IB poller | Inkbunny stat collection | `poll_interval_minutes` | 60 min |
| FA poller | FurAffinity stat collection | `fa_poll_interval_minutes` | 60 min |
| WS poller | Weasyl stat collection | `ws_poll_interval_minutes` | 60 min |
| SF poller | SoFurry stat collection | `sf_poll_interval_minutes` | 60 min |
| SqW poller | SquidgeWorld stat collection | `sqw_poll_interval_minutes` | 60 min |
| AO3 poller | AO3 stat collection | `ao3_poll_interval_minutes` | 60 min |
| DA poller | DeviantArt stat collection | `da_poll_interval_minutes` | 60 min |
| WP poller | Wattpad stat collection | `wp_poll_interval_minutes` | 60 min |
| IK poller | Itaku stat collection | `ik_poll_interval_minutes` | 60 min |
| BSKY poller | Bluesky stat collection | `bsky_poll_interval_minutes` | 60 min |
| TW poller | X/Twitter stat collection | `tw_poll_interval_minutes` | 60 min |
| Telegram digest | 6-hourly cross-platform summary | Fixed 6 hours | — |
| Telegram bot | Command listener (long-poll) | Continuous | — |
| Posting scheduler | Processes posting_queue table | Fixed 60 seconds | — |

### `server.py` — 4-Thread Model (Headless/Docker)

`server.py` replaces the 11 per-platform poller threads and the digest scheduler with a single unified poll orchestrator thread, and adds a posting scheduler:

| Thread | Purpose | Interval Source | Default |
|--------|---------|----------------|---------|
| Uvicorn | FastAPI dashboard server | N/A (always-on) | — |
| Poll orchestrator | Polls all platforms, sends consolidated summary, fires digests | `poll_interval_minutes` | 240 min |
| Telegram bot | Command listener (long-poll) | Continuous | — |
| Posting scheduler | Processes posting_queue table | Fixed 60 seconds | — |

### Per-Platform Thread Pattern (`main.py` only)

In the desktop 15-thread model, every poller function (`_start_poller()`, `_start_fa_poller()`, etc.) follows the exact same pattern:

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
            await run_XX_poll_cycle()
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
- `_fa_http` — Direct FA client with session cookies for validation; lazy-initialized only when needed

**Cookie authentication**: FA uses two cookies (`a` and `b`) extracted from the user's browser. These are set on the `_fa_http` client's cookie jar. Validation is done by loading the user's gallery page and checking for `<figure>` HTML elements (present only when authenticated).

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

**Watcher spam detection**: FA has a persistent problem with bot/spam watchers. The client includes `sniff_watcher_profiles()` which checks FAExport's user profile endpoint for activity indicators:
- Zero submissions + zero favorites + zero watches = likely bot
- Returns `{username: is_spam}` dict, capped at 10 profiles per poll to avoid excessive API calls

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

**Data collection** (hybrid approach):
- Gallery listing: scrape `/u/{display_name}/gallery` HTML for submission IDs (regex: `href="/s/{id}?ref=glr"`)
- Submission metadata: GET `/ui/submission/{id}` (undocumented JSON API) for title, author, rating, publishedAt, thumbnail, description
- Submission stats: scrape `/s/{id}` HTML for views/likes/comments (regex: `(\d[\d,]*)\s*[Vv]iews?`, etc.)
- Category codes: 20=story, 30=art, 40=music, 50=photo

**Follower scraping**: Paginates `/u/{display_name}/followers`, extracting usernames from `user-card` div blocks. Public page (no login required).

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

**Rate limiting**: 3-second delay between requests — the slowest of any client. AO3 is run entirely by volunteers with limited infrastructure. The delay is deliberately conservative to avoid impacting real users. The client also handles 429 (rate limited) responses with a 30-second backoff.

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

**Eclipse _napi endpoints**: DeviantArt's public frontend (Eclipse) uses internal JSON API endpoints that are undocumented. These were discovered by inspecting browser network traffic. There is no public gallery stats API.

| Endpoint | Purpose |
|----------|---------|
| `/_napi/da-user-profile/api/gallery/contents?username=X&offset=Y&limit=24&all_folder=true&mode=newest` | Gallery listing |
| `/_napi/shared_api/deviation/extended_fetch?deviationid=X&username=Y&type=art` | Full deviation detail with stats |

**Cookie authentication**: The full cookie string from the user's browser (all cookies for deviantart.com) is parsed and set on the httpx client. Validated by loading the gallery page and checking for `data-userid` or `deviantart.com/notifications` in the HTML.

**CF Worker proxy**: Required for server deployments because DA aggressively blocks datacenter IP ranges. Desktop mode with a residential IP typically works without the proxy.

**HTML scraping fallback**: If `_napi` endpoints fail (e.g., DA changes the internal API), the client falls back to scraping gallery HTML pages using regex patterns on `data-deviationid` attributes and embedded JSON `"stats"` objects.

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

**Cookie-based GraphQL scraping** — same approach as DeviantArt. Uses internal GraphQL endpoints discovered from browser network inspection.

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
    │  DA: validate cookie string
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
    │  Windows toast (desktop only, winotify)
    │  Telegram (summaries, milestones, errors)
    │  First poll suppressed (baseline collection)
    ▼
Finalise: Update poll_log, release concurrency guard
```

### Persistent client singletons (2.18.4 / 2.18.5)

Every platform with a login flow keeps a process-lifetime client
singleton inside its poller module — `polling/{ao3,sqw,bsky,da,ik,sf,tw,wp}_poller.py:_<platform>_client`.
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
conn = sqlite3.connect(str(config.DB_PATH), timeout=10)
conn.row_factory = sqlite3.Row    # Dict-like access: row["column_name"]
conn.execute("PRAGMA journal_mode=WAL")   # Concurrent readers + single writer
conn.execute("PRAGMA foreign_keys=ON")    # Enforce FK constraints
```

**Why WAL mode**: Without WAL, SQLite uses rollback journaling which locks the entire database during writes. The GUI thread would freeze while a poller writes snapshots. WAL (Write-Ahead Logging) allows concurrent readers and a single writer without blocking each other. This is critical for PawPoller because the dashboard reads data for display while pollers write new snapshots simultaneously.

**Why explicit FK enforcement**: SQLite does not enforce FOREIGN KEY constraints by default (for backward compatibility). Without `PRAGMA foreign_keys=ON`, you could insert a snapshot referencing a non-existent `submission_id`. This must be enabled per-connection.

**Timeout of 10 seconds**: If a writer is holding the WAL lock, readers wait up to 10 seconds before raising `sqlite3.OperationalError`. This is generous enough for normal operation but prevents indefinite hangs.

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

**Collapsible sidebar navigation** — Platform sections are wrapped in `<li class="nav-group">` elements containing a `<div class="nav-section" data-nav-toggle>` header and a `<ul class="nav-group-links">` sub-list:
```html
<li class="nav-group">
    <div class="nav-section" data-nav-toggle>Inkbunny <span class="nav-chevron">&#8250;</span></div>
    <ul class="nav-group-links">
        <li><a href="#/" class="nav-link" data-page="dashboard">Dashboard</a></li>
        <li><a href="#/submissions" class="nav-link" data-page="submissions">Submissions</a></li>
        <li><a href="#/compare" class="nav-link" data-page="compare">Compare</a></li>
    </ul>
</li>
```
On mobile (<=768px), `.nav-group-links` uses `max-height: 0` with `overflow: hidden` and transitions to `max-height: 200px` when the parent has `.expanded`. On desktop, groups are always expanded. The accordion toggle is CSS-only with JS adding/removing `.expanded` on the parent `.nav-group`.

The `route()` function auto-expands the nav-group containing the active link so the user always sees their current location in the sidebar.

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
- The **Polling tab** fetches its data only when the user clicks on it. This loads IB poll status + poll log, plus each connected platform's poll status and poll log in parallel (~22 API calls). A `_pollingTabLoaded` flag prevents re-fetching on subsequent tab switches.
- The **Logs tab** fetches server.log, polling.log, and app.log on demand when opened.

**Collapsible accordion sections** — Within each tab, related settings are grouped in native `<details>/<summary>` HTML elements, providing expand/collapse functionality without JavaScript. Each platform's configuration section is an independent accordion.

**Platform connection status** — Each platform section in the Platforms tab shows connection status, credential fields, and a test/connect button. Connected platforms display a green indicator.

**FA profile pageviews** — The FurAffinity section includes a stat card showing the user's profile page view count, fetched from the FA API.

### REST API Endpoints — Complete Reference

**Core API (`routes/api.py` — `/api/*`)**:

| Method | Endpoint | Purpose |
|--------|----------|---------|
| GET | `/api/health` | Health check for Docker (`{"status": "ok"}`) |
| GET | `/api/auth/status` | Check if credentials are configured |
| POST | `/api/auth/login` | Login with username/password |
| POST | `/api/auth/logout` | Clear session credentials |
| GET | `/api/submissions` | List IB submissions (sortable, paginated) |
| GET | `/api/submissions/{id}` | Single IB submission detail |
| GET | `/api/snapshots/{id}` | IB submission time-series (filterable by date range) |
| GET | `/api/aggregate` | Cross-submission IB totals |
| GET | `/api/comparison` | Multi-submission IB comparison data |
| GET | `/api/comments/{id}` | Comments for an IB submission |
| GET | `/api/faving-users/{id}` | Faving users for an IB submission |
| GET | `/api/watchers` | IB watcher list |
| POST | `/api/poll/trigger` | Trigger manual IB poll |
| POST | `/api/poll/full-resync` | Force full re-fetch of all data |
| GET | `/api/poll/progress` | Real-time IB poll status |
| GET | `/api/poll_log` | IB poll audit trail |
| GET | `/api/top-fans` | Cross-platform fan leaderboard |
| GET | `/api/trending` | Submissions with unusual growth (spike detection) |
| GET | `/api/settings/credentials` | Get IB credential status (username + has_password flag) |
| POST | `/api/settings/credentials` | Save IB credentials (partial updates OK) |
| GET | `/api/settings/preferences` | Get all preferences with defaults (see below) |
| POST | `/api/settings/preferences` | Save preferences (see below) |
| GET | `/api/settings/telegram` | Telegram connection status |
| POST | `/api/settings/telegram` | Connect Telegram bot (validates via getUpdates) |
| POST | `/api/settings/telegram/test` | Send test Telegram message |
| POST | `/api/settings/telegram/disconnect` | Remove Telegram configuration |
| GET | `/api/settings/telegram/features` | Telegram feature toggles |
| POST | `/api/settings/telegram/features` | Update Telegram feature toggles |
| POST | `/api/settings/telegram/digest` | Manually trigger Telegram digest |
| GET | `/api/groups` | List submission groups |
| POST | `/api/groups` | Create a new group |
| GET | `/api/groups/{id}` | Group detail with members |
| PUT | `/api/groups/{id}` | Update group name/description |
| DELETE | `/api/groups/{id}` | Delete group (CASCADE removes members) |
| POST | `/api/groups/{id}/members` | Add submission to group |
| DELETE | `/api/groups/{gid}/members/{mid}` | Remove submission from group |
| GET | `/api/links` | List cross-platform submission links |
| POST | `/api/links` | Create cross-platform link |
| DELETE | `/api/links/{id}` | Delete link |
| GET | `/api/update/check` | Check for new version on GitHub |
| POST | `/api/update/apply` | Download and apply update |
| GET | `/api/thumbnail` | Proxy for IB CDN thumbnails (CORS bypass) |
| GET | `/api/export/csv` | Export submissions as CSV |
| GET | `/api/goals` | List user goals |
| POST | `/api/goals` | Create a new goal |
| DELETE | `/api/goals/{id}` | Delete a goal |
| GET | `/api/tags` | List user tags |
| POST | `/api/tags` | Create a new tag |
| DELETE | `/api/tags/{id}` | Delete a tag |
| POST | `/api/tags/{id}/assign` | Assign tag to submission |
| DELETE | `/api/tags/{tid}/submissions/{platform}/{sid}` | Remove tag assignment |

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
| `Content-Security-Policy` | `default-src 'self'; script-src 'self' 'sha256-Wudo…SzA='; style-src 'self' 'unsafe-inline' fonts.googleapis.com; font-src 'self' fonts.gstatic.com; img-src 'self' https:; connect-src 'self'; frame-ancestors 'none'` | Restrict resource loading |

CSP rationale: All JS loaded via `<script src=...>` *except* one tiny inline boot script in `index.html` (and byte-identical in `epub-viewer.html`) that sets `data-theme` + `data-mobile` synchronously to avoid a flash of default-dark. That script's SHA-256 hash is allowlisted; everything else inline is dropped. Inline `style=` attributes require `'unsafe-inline'`. Google Fonts CSS + woff2 binaries get explicit allowlist origins. Platform CDN thumbnails need `https:`. All API calls are same-origin. When Cloudflare Turnstile is configured, `script-src` and `frame-src` automatically include `https://challenges.cloudflare.com`.

**Path-scoped CSP relaxation for `/epub-viewer.html`** — `_build_epub_viewer_csp()` returns a separate policy that allows `blob:` in `style-src`, `img-src`, `font-src`, `connect-src`, and `frame-src`. epub.js extracts the EPUB's stylesheets, fonts, and inline images into Blob URLs and references them from the rendered iframe; under the strict default the iframe loads chapter HTML with no styling. The middleware swaps to the relaxed CSP only when `request.url.path == "/epub-viewer.html"` so every other route keeps the strict default. Updating the inline-boot-script body in either `index.html` or `epub-viewer.html` requires recomputing both files' SHA-256 hashes (the browser prints the expected hash in console on a CSP violation).

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

### Windows Toast Notifications (Desktop Only)

Uses `winotify` library. Every notification call is wrapped in try/except with an ImportError guard:
```python
try:
    from winotify import Notification
except ImportError:
    logger.debug("winotify not installed — skipping notifications")
    return
```
This means the server/Docker deployment silently skips toasts without any error.

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
    ├── data/settings.vault.json  # Encrypted credentials (Phase 7b, local mode only)
    ├── logs/app.log
    └── settings.json

Dev mode (python main.py):
  project_root/          # Everything in one place
    ├── frontend/
    ├── database/*.sql
    ├── data/pawpoller.db
    ├── data/settings.vault.json  # Encrypted credentials (Phase 7b, local mode only)
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

### Credential Vault (Phase 7b)

When `credential_mode` is `"local"`, credential fields listed in `CREDENTIAL_FIELDS` are stored encrypted in `settings.vault.json` instead of plaintext in `settings.json`. The vault uses Fernet symmetric encryption with a key sourced from the system keyring (preferred) or a `.vault_key` dotfile with 0600 permissions.

```
settings.json   → non-credential settings only (credential_mode, poll intervals, etc.)
settings.vault.json → Fernet-encrypted JSON blob containing all credential fields
```

The integration is transparent: `_load_settings()` merges decrypted vault data into the returned dict, and `save_settings()` splits credential fields into the vault on write. All consumers see a unified view without needing vault awareness.

**Key functions**: `_get_vault_key()`, `_encrypt_vault()`, `_decrypt_vault()`, `get_credential_mode()`, `migrate_to_local_vault()`, `migrate_to_cloud()`.

**API endpoints**: `POST /api/settings/vault/enable`, `POST /api/settings/vault/disable`, `GET /api/settings/vault/status`.

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
DA_REQUEST_DELAY_SECONDS       = 2.0    # DeviantArt (aggressive rate limiting)
WP_REQUEST_DELAY_SECONDS       = 1.0    # Wattpad public API
IK_REQUEST_DELAY_SECONDS       = 1.0    # Itaku public API
BSKY_REQUEST_DELAY_SECONDS     = 1.0    # Bluesky AT Protocol (generous rate limits)
TW_REQUEST_DELAY_SECONDS       = 2.0    # X/Twitter GraphQL (aggressive rate limiting)
```

### Windows Auto-Start (Registry)

PawPoller can register itself to start with Windows via the per-user Run registry key:

```python
_STARTUP_REG_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
_STARTUP_REG_NAME = "PawPoller"

# Frozen: writes exe path directly ("C:\...\PawPoller.exe")
# Dev: writes python + script path ("python" "main.py")
```

Uses `HKCU` (not `HKLM`) so no admin privileges are needed.

### Other App Constants

```python
APP_VERSION = "2.13.8"  # check config.py for current — bumped on every ship
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

DeviantArt and SoFurry block requests from datacenter IP ranges (cloud VMs, Docker containers). Residential IPs (desktop mode) typically work fine. The Cloudflare Worker acts as a reverse proxy, routing requests through Cloudflare's IP range which these sites allow.

Without the proxy, server deployments would get 403 Forbidden responses from DA and SF. The proxy is only needed for these two platforms — all others work from any IP.

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

Download uses streaming (8KB chunks) to avoid memory bloat. Extraction to a temp directory. 120-second timeout for slow connections. Supports authenticated requests via `github_pat` token for private repos.

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
| AO3 | User/pass + CSRF | `ao3_username`, `ao3_password`, `ao3_target_user` | Login account + tracked user's username |
| DeviantArt | Browser cookie string | `da_cookie`, `da_target_user` | Full cookie string from browser DevTools |
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
| DA polls fail on server | Datacenter IP blocked | Configure CF Worker proxy. DA aggressively blocks cloud/datacenter IP ranges. |
| DA cookie format wrong | Partial cookie string | Export the **full** cookie string from DevTools (Network tab → copy as cURL → extract Cookie header), not individual cookie values. |
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
| TW GraphQL fails | Query IDs rotated | X may update GraphQL query IDs when they deploy new frontend code. Check logs for 404s and update hardcoded IDs in `clients/tw/client.py`. |

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
| DeviantArt | `/_napi/da-user-profile/api/gallery/contents` | `clients/da/client.py` | Gallery listing |
| | `/_napi/shared_api/deviation/extended_fetch` | | Deviation detail |
| | `/{u}/gallery` | | HTML fallback |
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

The posting module enables PawPoller to upload stories to 6 platforms, edit existing submissions, track what has been posted where, and detect when local story files have changed since the last upload. It is the reverse complement to the polling system: polling reads stats *from* platforms, posting pushes content *to* them.

Supported platforms for posting:

| Platform | Poster | Auth Method | Post | Edit | File Replace | Requires |
|----------|--------|------------|:----:|:----:|:------------:|----------|
| Inkbunny | `InkbunnyPoster` | Username/password → SID | Yes | Yes | Yes | any |
| FurAffinity | `FurAffinityPoster` | Cookie a + Cookie b | Yes | Yes | Yes | desktop |
| Weasyl | `WeasylPoster` | API key | Yes | Yes | No | any |
| SoFurry | `SoFurryPoster` | Email/password + CSRF | Yes | Yes | Yes | any |
| SquidgeWorld | `SquidgeWorldPoster` | Author user/pass + CSRF | Yes | Yes | Yes | any |
| Bluesky | `BlueskyPoster` | App password → JWT | Yes | No* | No | any |

*Bluesky does not support in-place editing. The only option is delete + repost, which loses engagement.

FurAffinity requires `desktop` mode because FA blocks datacenter IP ranges. When a server-mode post to FA fails, the scheduler automatically queues it for desktop pickup.

### Architecture

The posting module lives in the `posting/` directory alongside the existing `polling/`, `database/`, and `routes/` directories. It reuses the existing platform API clients (e.g. `InkbunnyClient`, `FAClient`) by adding upload/edit methods.

```
posting/
├── manager.py              Orchestrator: story_reader → poster → publications DB
├── scheduler.py            Daemon thread: checks posting_queue every 60s
├── story_reader.py         Reads archive → builds StoryUploadPackage objects
├── sync.py                 Retroactive claim + change detection
├── generate_story_json.py  CLI: generates story.json from legacy data
└── platforms/
    ├── base.py             PlatformPoster ABC + data classes
    ├── inkbunny.py         InkbunnyPoster
    ├── furaffinity.py      FurAffinityPoster
    ├── weasyl.py           WeasylPoster
    ├── sofurry.py          SoFurryPoster
    ├── squidgeworld.py     SquidgeWorldPoster
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
1. Read full StoryInfo from `story.json` (fandom, warnings, categories, characters, relationships)
2. Trim freeform tags to fit OTW's 75-tag total budget (`fandom + relationships + characters + freeform <= 75`)
3. `_ensure_work_skin(client, story)` — find or create the per-story Work Skin on AO3 from `SquidgeWorld/Work_Skin.css`, auto-refresh CSS on every post. Returns skin_id or `""` (no skin applied if no CSS file).
4. Chaptered detection (`story.total_chapters > 1`):
   - **Multi-chapter**: read chapter 1 body from `SquidgeWorld/Chapter_1_*.html`, create_work with ch1 content, then iterate ch2..N via `create_chapter(work_id, title=, content=, position=, publish=False)`. Chapter titles are stripped of `Chapter N:` / `Part N:` / `Prelude:` / `Epilogue:` prefixes via `_strip_chapter_prefix()` since AO3 auto-prefixes on display.
   - **Single-chapter / unsplit**: read `HTML/<Story>_Clean.html` (full-story body) and upload as one chapter.
5. `client.create_work(...)` with `preview_button` — work lands in `/works/{id}/preview` (drafts), NOT published.
6. SAFETY: post-flight `is_work_published` check — only aborts on POSITIVE confirmation of publish (handles AO3 timeouts gracefully). Each `create_chapter` call is also safety-checked.

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
- `preview_button` — `"Preview"` lands in drafts; `post_button` would publish (we never use it)

**Rating mapping**: General → "General Audiences"; Mature → "Mature"; Teen → "Teen And Up Audiences"; Adult/Explicit → "Explicit".

**HTML whitespace collapse**: `_collapse_html_whitespace()` joins multi-line `<p>` and `<div>` tags onto single lines to prevent OTW's auto-formatter from inserting `<br />` tags.

**Rate limiting**: 3 seconds between requests (`config.AO3_REQUEST_DELAY_SECONDS`). Bulk runs use a 10-second inter-post sleep on top of that — AO3 is volunteer-run with limited infrastructure.

**Network reliability** (the one really painful difference from SQW):
- **AO3 from datacenter IPs** sees frequent `ReadTimeout` and `525 origin SSL handshake fail` responses — about 1 in 5 requests. The drafts page (`/users/<user>/works/drafts`) is particularly slow and times out the most.
- `_get_page()` retries 3 times with backoff on timeout/525. Hard 403/404 are not retried.
- **AO3 from residential IPs** is currently shielded with the "Shields are up!" CF JavaScript challenge — vanilla httpx cannot pass it. All AO3 testing must run from the GCP container.
- The post-flight safety check uses **tri-state** state checks (`True | False | None`). When `is_work_in_drafts` returns `None` (fetch failed), the check trusts `preview_button` and logs a warning instead of triggering a destructive auto-delete. Without this, AO3 timeouts caused spurious aborts that tried (and failed) to delete healthy drafts.

**Format files** (`PLATFORM_FORMAT_MAP["ao3"]`, in priority order):
| Priority | Path | Pattern |
|---|---|---|
| 1 | `HTML/` | `*_Clean.html` (full-story body HTML, single bulk) |
| 2 | `SquidgeWorld/` | `*.html` (per-chapter, body-only) |
| 3 | `Chapters/SoFurry_HTML/` | `*.html` (per-chapter) |

For full-story posting (`chapter_index=0`) priority 3 is skipped automatically because of the `Chapters/` skip in `_resolve_format_file`. Priority 1 wins for any story with a `Clean.html` full-story file (which is all of them after the 2026-04-07 converter regen).

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

**Auth**: Official OAuth2 API — **not** the undocumented `_napi`/`_puppy` endpoints. Requires registering a DA application at the developer portal to get `client_id` and `client_secret`, then doing a one-time Authorization Code flow in the browser to obtain a refresh token.

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
    platform            TEXT NOT NULL,       -- "ib", "fa", "ws", "sf", "sqw", "bsky"
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

### Posting Queue

The `posting_queue` table holds pending uploads and updates. Items can be:
- **Immediate**: `scheduled_at` is NULL — processed on the next scheduler check
- **Scheduled**: `scheduled_at` is a future datetime — processed when due
- **Retryable**: Failed items with `attempts < max_attempts` (default 3)

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
    "chapters": [1, 2, 3]
}
```
`chapters` is optional — `null` or omitted means all chapters.

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

The posting module adds a "Stories" section to the dashboard sidebar, implemented in `frontend/js/posting.js` with 4 pages:

**1. Stories Hub** (`#/posting`) — Card grid showing all stories in the archive. Each card displays title, author, word count, chapter count, and platform badges for published platforms. Clicking a card navigates to the story detail page.

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
- `_AUTH_EXEMPT_PREFIXES = ("/css/", "/js/", "/vendor/")` so vendored
  libs load without auth (parity with the rest of the SPA assets)
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
    action panel shows "Set up in Settings" message. `PLATFORM_CREDS` map
    in `publish_check.js` checks per-platform credential requirements
    before the matrix loop.
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

- `PLATFORM_LOGIN` configs for 7 platforms (FA, DA, SF, TW, WS, AO3, SqW) with URL, success conditions, and cookie-to-setting mappings.
- `login_via_browser()` opens a pywebview window in a daemon thread with a 5-minute timeout, captures cookies via `get_cookies()`, and saves credentials via `config.save_settings()`.
- `GET /api/settings/browser-login/platforms` — lists supported platforms with availability flag (True in desktop mode only).
- `POST /api/settings/browser-login/{platform}` — launches the popup and blocks until login completes or window closes. Runs in `run_in_executor` to avoid stalling the event loop.
- Dashboard: FA, DA, and TW platform connect forms show "Login via Browser" as primary action in desktop mode, with a "Enter cookies manually" toggle for the existing cookie input form.

### Theme-Save Trailing Content

`POST /api/editor/stories/{name}/theme` writes `CHAPTER_STYLING.md` with
the new variables table between `<!-- THEME_VARIABLES_START -->` and
`<!-- THEME_VARIABLES_END -->` markers. Any user-authored content AFTER
the end marker (notes, credits, extra sections) is preserved by a
`after = existing[existing.index(marker_end) + len(marker_end):]` split;
earlier versions silently wiped this content on every save.
