# PawPoller Documentation Guide

Comprehensive technical reference for the PawPoller codebase. Covers architecture, threading, platform clients, database, deployment, and troubleshooting.

---

## 1. Overview & Architecture

PawPoller is a multi-platform furry art analytics dashboard. It periodically polls 11 art/writing platforms, stores submission statistics in SQLite, and serves a real-time analytics dashboard. The tech stack is FastAPI + SQLite (WAL mode) + Vanilla JS SPA + pywebview + pystray.

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
           │        │  11 pollers + uvicorn + telegram(2)  │        │
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
Platform Client (api_client/, fa_client/, etc.)
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
├── server.py                # Headless entry point (Docker / server)
├── poll_service.py          # Legacy/alternative (APScheduler, --once, --status)
├── config.py                # Paths, credentials, settings.json helpers
├── dashboard.py             # FastAPI app factory, auth middleware, SPA serving
├── updater.py               # Auto-update (desktop only)
├── test_sf_proxy.py         # SoFurry proxy diagnostic tool
├── test_sf_direct.py        # SoFurry direct login + cookie persistence test
│
├── api_client/              # Inkbunny API client
│   └── client.py            #   InkbunnyClient class with SID caching
├── fa_client/               # FurAffinity client (FAExport + scraping)
│   └── client.py            #   FAClient class with dual HTTP transports
├── weasyl_client/           # Weasyl REST API client
│   └── client.py            #   WeasylClient class with cursor pagination
├── sf_client/               # SoFurry client (scraping + JSON hybrid)
│   └── client.py            #   SoFurryClient class with CF proxy support
├── sqw_client/              # SquidgeWorld client (OTW scraping)
│   └── client.py            #   SqWClient class with Anubis challenge solving
├── ao3_client/              # AO3 client (OTW scraping)
│   └── client.py            #   AO3Client class with CSRF auth
├── da_client/               # DeviantArt client (Eclipse _napi)
│   └── client.py            #   DAClient class with cookie auth + proxy
├── wp_client/               # Wattpad client (REST API)
│   └── client.py            #   WPClient class (no auth, public API)
├── ik_client/               # Itaku client (REST API)
│   └── client.py            #   IKClient class (no auth, public API)
├── bsky_client/             # Bluesky client (AT Protocol)
│   └── client.py            #   BskyClient class with JWT session auth
├── tw_client/               # X/Twitter client (GraphQL scraping)
│   └── client.py            #   TWClient class with cookie auth
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
│   └── tw_api.py            # X/Twitter API endpoints
│
├── frontend/
│   ├── index.html           # SPA shell (collapsible nav groups, bottom nav bar, sidebar overlay)
│   ├── css/
│   │   ├── tokens.css      # Design tokens (dark + light theme custom properties)
│   │   ├── components.css  # UI components (cards, buttons, tables, accordions, charts)
│   │   └── layout.css      # Page layout, sidebar, responsive breakpoints, bottom nav
│   └── js/
│       ├── app.js           # Hash-based SPA router, accordion nav, bottom nav, auto-refresh
│       ├── api.js           # API client wrapper (~50 methods, get/post transport)
│       ├── components.js    # UI components (~25: tables with mobile card transformation, cards, charts, modals)
│       ├── charts.js        # Chart.js time-series and comparison chart factories
│       ├── utils.js         # Formatting helpers (numbers, dates, relative time)
│       └── vendor/          # Third-party libraries (Chart.js)
│
├── deploy/
│   ├── cf-worker.js         # Cloudflare Worker proxy (3 modes: normal, chain, login)
│   ├── setup-gcloud.sh      # GCP VM deployment automation
│   └── setup-oracle.sh      # Oracle Cloud Always Free deployment automation
│
├── assets/
│   └── tray_icon.png        # System tray icon (fallback: procedurally generated)
│
├── Dockerfile               # Python 3.11 slim + HEALTHCHECK
├── docker-compose.yml       # Single service, 2 named volumes, .env file
├── .env.example             # 25+ environment variable template
├── requirements.txt         # Desktop dependencies (pywebview, pystray, Pillow, winotify, etc.)
├── requirements-server.txt  # Headless/Docker dependencies (no GUI)
├── inkbunny_analytics.spec  # PyInstaller build spec
├── build.bat                # Windows build script
├── settings.json            # Runtime user settings (gitignored)
├── CHANGELOG.md             # Version history
└── INDEX.md                 # Detailed codebase index (~35KB)
```

---

## 2. Entry Points

### `main.py` — Desktop GUI Mode

Startup sequence in detail:

**Step 1: Database initialisation**
```python
init_db()  # Creates tables/schema if the DB file does not exist yet
```

**Step 2: Launch 14 daemon threads**
All threads are `daemon=True` so they terminate automatically when the main thread (pywebview) exits. No explicit shutdown signalling is needed. Each thread is named for debugging (`threading.Thread(name="FA poller")`).

Thread launch order: Uvicorn → IB poller → FA poller → WS poller → SF poller → SqW poller → AO3 poller → DA poller → WP poller → IK poller → BSKY poller → TW poller → Telegram digest → Telegram bot.

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
`_seed_settings_from_env()` reads each env var, compares with existing settings.json values, and only writes if the value is new or different. Special handling for `telegram_enabled` which is parsed as a boolean (`"true"/"1"/"yes"` → `True`). Logs which credentials were seeded.

**Step 3: Launch daemon threads** — Same 14 threads as desktop (11 pollers + uvicorn + telegram digest + telegram bot), but launched from a list of `(name, target)` tuples and iterated:
```python
threads = [
    ("Uvicorn",         lambda: _start_server(args.host, args.port)),
    ("IB poller",       _start_poller),
    ("FA poller",       _start_fa_poller),
    # ...
]
for name, target in threads:
    t = threading.Thread(target=target, daemon=True, name=name)
    t.start()
```

**Step 4: Block until signal** — Uses `threading.Event` + signal handler:
```python
shutdown_event = threading.Event()
signal.signal(signal.SIGINT, lambda *_: shutdown_event.set())
signal.signal(signal.SIGTERM, lambda *_: shutdown_event.set())
shutdown_event.wait()  # Blocks until SIGINT/SIGTERM
```

Key differences from `main.py`:
- Binds `0.0.0.0` by default (not `127.0.0.1`) — accessible from the network
- `--port` and `--host` argparse arguments for customisation
- Signal handler for graceful shutdown (SIGINT/SIGTERM)
- CF proxy debug logging gated behind `PAWPOLLER_DEBUG_PROXY` env var
- No pywebview, pystray, Pillow, or winotify dependencies

### `poll_service.py` — Legacy/Alternative

Three modes via argparse:

**Continuous mode** (default): APScheduler `AsyncIOScheduler` with `IntervalTrigger(hours=1)`. Forces an immediate first poll via `next_run_time=datetime.now()`. Main loop is `while True: await asyncio.sleep(1)` to keep the event loop alive for APScheduler. Only polls Inkbunny.

**Once mode** (`--once`): `asyncio.run(do_poll_once())` — single poll cycle then exit. Designed for Windows Task Scheduler or cron where the OS handles scheduling. Exit code 1 on failure so the scheduler can detect errors.

**Status mode** (`--status`): Synchronous SQLite reads (no event loop needed). Prints: database path, submission count, total views/favorites, snapshot count, faving user count, last poll time/status/duration/error.

---

## 3. Threading Model

Both `main.py` and `server.py` spawn 14 daemon threads plus the main thread:

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

### Per-Thread Design Pattern

Every poller function (`_start_poller()`, `_start_fa_poller()`, etc.) follows the exact same pattern:

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

Key design decisions:
1. **Own asyncio event loop**: asyncio loops are bound to a single thread. `new_event_loop()` + `set_event_loop()` gives each poller its own isolated async runtime. The main thread's loop (if any) cannot be reused.
2. **Immediate first poll**: So the dashboard has data right away without waiting for the first interval to elapse. Respects the `polling_paused` setting — if paused, the initial poll is skipped and every subsequent cycle also checks the flag before executing.
3. **Dynamic interval**: Users can change the polling frequency in the UI and it takes effect on the very next cycle without restarting the app.
4. **Credential gating**: If the user hasn't configured a platform yet, the cycle is silently skipped rather than erroring.

### First-Poll Notification Suppression

Each poller tracks a `_XX_first_poll = True` flag. On the first poll after startup:
- All data is collected normally (gallery discovery, detail fetch, upsert + snapshot)
- But notifications are suppressed — no Windows toasts, no Telegram messages
- This establishes a baseline. Without it, every existing comment, fave, and watcher would trigger an alert on startup.

After the first poll completes (success or failure), the flag is set to `False` and subsequent polls notify normally.

### Daemon Thread Behaviour

All threads are `daemon=True`, meaning they are killed automatically when the main thread exits. This avoids zombie processes but means pollers don't get a graceful shutdown signal — they simply stop mid-execution.

The `except Exception` blocks around each thread's `loop.run_until_complete()` catch the resulting teardown exceptions and log them at `logger.debug()` level. During normal shutdown, Python raises exceptions in daemon threads as the interpreter shuts down. These are harmless but would be invisible without the debug logging — if a poller crashes for a real reason (import error, bug), the debug log captures it.

### Telegram Digest Scheduler

The digest thread has a unique startup delay:
```python
await asyncio.sleep(300)  # Wait 5 minutes for pollers to populate data
```
This ensures pollers have completed their initial cycles before the first digest is generated. Otherwise the digest would report empty or incomplete data.

---

## 4. Platform Clients

Each platform has a dedicated async HTTP client using `httpx.AsyncClient`. All support context manager protocol (`async with client:`). Below are deep technical details for each.

### Inkbunny (`api_client/client.py`) — `InkbunnyClient`

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

### FurAffinity (`fa_client/client.py`) — `FAClient`

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

### Weasyl (`weasyl_client/client.py`) — `WeasylClient`

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

### SoFurry (`sf_client/client.py`) — `SoFurryClient`

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

### SquidgeWorld (`sqw_client/client.py`) — `SqWClient`

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

### AO3 (`ao3_client/client.py`) — `AO3Client`

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

### DeviantArt (`da_client/client.py`) — `DAClient`

**Eclipse _napi endpoints**: DeviantArt's public frontend (Eclipse) uses internal JSON API endpoints that are undocumented. These were discovered by inspecting browser network traffic. There is no public gallery stats API.

| Endpoint | Purpose |
|----------|---------|
| `/_napi/da-user-profile/api/gallery/contents?username=X&offset=Y&limit=24&all_folder=true&mode=newest` | Gallery listing |
| `/_napi/shared_api/deviation/extended_fetch?deviationid=X&username=Y&type=art` | Full deviation detail with stats |

**Cookie authentication**: The full cookie string from the user's browser (all cookies for deviantart.com) is parsed and set on the httpx client. Validated by loading the gallery page and checking for `data-userid` or `deviantart.com/notifications` in the HTML.

**CF Worker proxy**: Required for server deployments because DA aggressively blocks datacenter IP ranges. Desktop mode with a residential IP typically works without the proxy.

**HTML scraping fallback**: If `_napi` endpoints fail (e.g., DA changes the internal API), the client falls back to scraping gallery HTML pages using regex patterns on `data-deviationid` attributes and embedded JSON `"stats"` objects.

**Unique stat**: DeviantArt is the only platform that tracks `downloads` in addition to views/favorites/comments.

### Wattpad (`wp_client/client.py`) — `WPClient`

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

### Itaku (`ik_client/client.py`) — `IKClient`

**No authentication required** — public API at `itaku.ee/api`.

**User resolution**: `/api/user_profiles/{username}/` returns the owner's numeric ID, needed for content queries.

**Two content types**: `gallery_images` and `posts`. Both are discovered via paginated API calls with cursor-based pagination (response includes `next` URL).

**Stats**: likes, comments, reshares. **No views metric** — Itaku does not expose view counts. This means the dashboard's "views" column is blank for Itaku submissions.

Rate limiting: 429 handling with 30s backoff.

### Bluesky (`bsky_client/client.py`) — `BskyClient`

**AT Protocol API** at `bsky.social/xrpc`. Authenticated via app password → JWT session tokens.

**Session management**: `com.atproto.server.createSession` returns `accessJwt` + `refreshJwt` + DID. Access tokens are short-lived; the client auto-refreshes via `com.atproto.server.refreshSession` on 401, with full re-login as fallback. Chain: `check_session()` → `refresh_session()` → `login()`.

**Post discovery**: `app.bsky.feed.getAuthorFeed` with cursor-based pagination. Each response includes `cursor` for the next page. Returns AT URIs (`at://did:plc:xxx/app.bsky.feed.post/yyy`).

**Post detail**: `app.bsky.feed.getPosts` accepts up to 25 URIs per call. Returns likes, reposts, replies, quotes. Batched with rate limiting between calls.

**AT URI handling**: AT URIs contain slashes, so they're stored as TEXT primary keys in SQLite. The `rkey` (final path segment) is used for URL-friendly frontend routes. API resolves by suffix match (`LIKE '%/' || rkey`).

**Stats**: likes, reposts, replies, quotes. **No views metric** — Bluesky does not expose impression counts. This means the dashboard has 4 stat cards instead of the typical 5.

**Post links**: `https://bsky.app/profile/{handle}/post/{rkey}` where rkey is the last segment of the AT URI.

Rate limiting: 1s between requests, 429 handling with 30s backoff.

### X/Twitter (`tw_client/client.py`) — `TWClient`

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
| `poll_interval_minutes` | int | 60 | {15,30,60,120,240} | IB poll frequency |
| `fa_poll_interval_minutes` | int | 60 | {15,30,60,120,240} | FA poll frequency |
| `ws_poll_interval_minutes` | int | 60 | {15,30,60,120,240} | WS poll frequency |
| `sf_poll_interval_minutes` | int | 60 | {15,30,60,120,240} | SF poll frequency |
| `sqw_poll_interval_minutes` | int | 60 | {15,30,60,120,240} | SqW poll frequency |
| `ao3_poll_interval_minutes` | int | 60 | {15,30,60,120,240} | AO3 poll frequency |
| `da_poll_interval_minutes` | int | 60 | {15,30,60,120,240} | DA poll frequency |
| `wp_poll_interval_minutes` | int | 60 | {15,30,60,120,240} | WP poll frequency |
| `ik_poll_interval_minutes` | int | 60 | {15,30,60,120,240} | IK poll frequency |
| `bsky_poll_interval_minutes` | int | 60 | {15,30,60,120,240} | BSKY poll frequency |
| `tw_poll_interval_minutes` | int | 60 | {15,30,60,120,240} | TW poll frequency |
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

### Authentication Middleware

Optional HTTP Basic Auth for server deployments (`dashboard.py` lines ~70-99):

```python
@app.middleware("http")
async def basic_auth_middleware(request, call_next):
    password = _get_dashboard_password()  # From env or settings.json
    if not password:
        return await call_next(request)   # No password = no auth required
    # Decode Basic auth header, compare with secrets.compare_digest()
    # Return 401 with WWW-Authenticate header on failure
```

Uses `secrets.compare_digest()` for constant-time comparison (prevents timing attacks). Dashboard user defaults to `"admin"` but is configurable via `DASHBOARD_USER` env var.

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

**6-Hour Digest Report** (sent by digest scheduler thread):
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
    ├── logs/app.log
    └── settings.json

Dev mode (python main.py):
  project_root/          # Everything in one place
    ├── frontend/
    ├── database/*.sql
    ├── data/pawpoller.db
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
APP_VERSION = "1.5.0"
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
    │  Compares with existing settings.json values
    │  Only writes if value is new or different
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
| AO3 rate limited (429) | Polling too fast | Increase `ao3_poll_interval_minutes`. AO3 is volunteer-run with limited infrastructure. Default 60 minutes is usually fine. |
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
| TW rate limited (429) | Polling too fast | X is aggressive about rate limiting. Increase `tw_poll_interval_minutes`. Default 2s inter-request delay + 60s backoff. |
| TW GraphQL fails | Query IDs rotated | X may update GraphQL query IDs when they deploy new frontend code. Check logs for 404s and update hardcoded IDs in `tw_client/client.py`. |

### Known Limitations (Not Fixed)

**Architectural**:
- **No connection pooling**: Each poll cycle creates new HTTP client instances rather than reusing connections. This adds TLS handshake overhead but simplifies credential rotation.
- **No dashboard rate limiting**: The REST API has no request throttling beyond the optional Basic Auth. A denial-of-service against the dashboard is possible on exposed servers.
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
| Inkbunny API | `/api_login.php` | `api_client/client.py` | Authentication |
| | `/api_userrating.php` | | Unlock content ratings |
| | `/api_search.php` | | Gallery discovery |
| | `/api_submissions.php` | | Batch detail fetch |
| | `/api_submissionfavingusers.php` | | Faving user lists |
| Inkbunny Web | `/login.php`, `/login_process.php` | | Web auth for scraping |
| | `/s/{id}` | | Comment HTML scraping |
| | `/usersviewall.php?mode=watched_by` | | Watcher list scraping |
| FAExport | `/user/{u}/gallery.json` | `fa_client/client.py` | Gallery listing |
| | `/submission/{id}.json` | | Submission detail |
| | `/submission/{id}/comments.json` | | Comment thread |
| | `/user/{u}.json` | | Profile (spam check) |
| | `/user/{u}/watchers.json` | | Watcher list |
| Weasyl API | `/api/whoami` | `weasyl_client/client.py` | Validate API key |
| | `/api/users/{u}/gallery` | | Gallery (cursor pagination) |
| | `/api/submissions/{id}/view` | | Submission detail |
| SoFurry | `/login` (GET/POST) | `sf_client/client.py` | CSRF auth flow |
| | `/u/{u}/gallery` | | Gallery HTML scraping |
| | `/ui/submission/{id}` | | JSON metadata |
| | `/s/{id}` | | Stats HTML scraping |
| | `/u/{u}/followers` | | Follower list |
| AO3 | `/users/login` (GET/POST) | `ao3_client/client.py` | CSRF auth flow |
| | `/users/{u}/works` | | Works listing |
| | `/works/{id}?view_adult=true` | | Work detail + stats |
| DeviantArt | `/_napi/da-user-profile/api/gallery/contents` | `da_client/client.py` | Gallery listing |
| | `/_napi/shared_api/deviation/extended_fetch` | | Deviation detail |
| | `/{u}/gallery` | | HTML fallback |
| Wattpad API | `/api/v3/users/{u}/stories/published` | `wp_client/client.py` | Story listing |
| Itaku API | `/api/user_profiles/{u}/` | `ik_client/client.py` | User resolution |
| | `/api/gallery_images/` | | Content discovery |
| Bluesky AT Proto | `com.atproto.server.createSession` | `bsky_client/client.py` | JWT authentication |
| | `com.atproto.server.refreshSession` | | Token refresh |
| | `app.bsky.feed.getAuthorFeed` | | Post discovery |
| | `app.bsky.feed.getPosts` | | Batch post details |
| | `app.bsky.actor.getProfile` | | Session validation |
| X/Twitter GraphQL | `/i/api/graphql/.../UserByScreenName` | `tw_client/client.py` | User ID resolution |
| | `/i/api/graphql/.../UserTweets` | | Tweet listing |
| | `/i/api/graphql/.../TweetResultByRestId` | | Tweet detail |
| Telegram | `/bot{token}/getUpdates` | `polling/telegram_bot.py` | Long-poll commands |
| | `/bot{token}/sendMessage` | `polling/telegram.py` | Send notifications |
| GitHub | `/repos/{owner}/{repo}/releases/latest` | `updater.py` | Version check |
| CF Worker | `/{worker-url}` | `polling/cf_proxy.py` | Proxy transport |
