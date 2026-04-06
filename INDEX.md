# PawPoller Codebase Index

> **Quick reference** for finding anything in the codebase.
> Every file, every function, every route, every table — indexed.

---

## Architecture Overview

PawPoller is a **desktop analytics dashboard** for tracking submission stats across 11 platforms: **Inkbunny (IB)**, **FurAffinity (FA)**, **Weasyl (WS)**, **SoFurry (SF)**, **SquidgeWorld (SqW)**, **AO3**, **DeviantArt (DA)**, **Wattpad (WP)**, **Itaku (IK)**, **Bluesky (BSKY)**, and **X/Twitter (TW)**. Also includes a **posting module** that uploads/edits stories on 6 platforms (IB, FA, WS, SF, SqW, BSKY) with publication tracking and change detection.

**Stack**: FastAPI + SQLite (WAL) + Vanilla JS SPA + pywebview + pystray

**Runtime model**: Single process with 15 daemon threads + main thread:
- Threads 1-11: Platform pollers (IB, FA, WS, SF, SqW, AO3, DA, WP, IK, BSKY, TW)
- Thread 12: Uvicorn web server (FastAPI dashboard)
- Thread 13: Telegram digest scheduler
- Thread 14: Telegram bot command listener
- Thread 15: Posting scheduler (processes posting_queue every 60s)
- Main thread: pywebview native desktop window + pystray system tray

**Data flow**: Platform API → Poller → SQLite → REST API → Frontend SPA
**Posting flow**: Story Archive → story_reader → Platform Poster → Platform API → publications table

---

## Directory Structure

```
PawPoller/
├── main.py                    # Entry point — threads, server, GUI
├── config.py                  # Paths, settings, credentials, constants
├── dashboard.py               # FastAPI app factory + router mounting
├── poll_service.py            # Standalone polling service (CLI)
├── updater.py                 # GitHub releases auto-update
│
├── api_client/                # Inkbunny API client
│   ├── __init__.py
│   ├── client.py              # InkbunnyClient (API + web scraping)
│   └── models.py              # Pydantic models for IB API responses
│
├── fa_client/                 # FurAffinity API client
│   ├── __init__.py
│   └── client.py              # FAClient (FAExport + cookie validation)
│
├── weasyl_client/             # Weasyl API client
│   ├── __init__.py
│   └── client.py              # WeasylClient (REST API + API key auth)
│
├── bsky_client/               # Bluesky API client
│   ├── __init__.py
│   └── client.py              # BskyClient (AT Protocol + JWT auth)
│
├── tw_client/                 # X/Twitter API client
│   ├── __init__.py
│   └── client.py              # TWClient (GraphQL + cookie auth)
│
├── database/                  # SQLite schema, queries, migrations
│   ├── __init__.py
│   ├── db.py                  # Connection factory, schema init, migrations
│   ├── schema.sql             # Inkbunny tables
│   ├── fa_schema.sql          # FurAffinity tables
│   ├── ws_schema.sql          # Weasyl tables
│   ├── sf_schema.sql          # SoFurry tables
│   ├── sqw_schema.sql         # SquidgeWorld tables
│   ├── ao3_schema.sql         # AO3 tables
│   ├── da_schema.sql          # DeviantArt tables
│   ├── wp_schema.sql          # Wattpad tables
│   ├── ik_schema.sql          # Itaku tables
│   ├── bsky_schema.sql        # Bluesky tables
│   ├── tw_schema.sql          # X/Twitter tables
│   ├── posting_schema.sql     # Posting module tables (publications, posting_queue, posting_log)
│   ├── queries.py             # Inkbunny CRUD + analytics
│   ├── fa_queries.py          # FurAffinity CRUD + analytics
│   ├── ws_queries.py          # Weasyl CRUD + analytics
│   ├── sf_queries.py          # SoFurry CRUD + analytics
│   ├── sqw_queries.py         # SquidgeWorld CRUD + analytics
│   ├── ao3_queries.py         # AO3 CRUD + analytics
│   ├── da_queries.py          # DeviantArt CRUD + analytics
│   ├── wp_queries.py          # Wattpad CRUD + analytics
│   ├── ik_queries.py          # Itaku CRUD + analytics
│   ├── bsky_queries.py        # Bluesky CRUD + analytics
│   ├── tw_queries.py          # X/Twitter CRUD + analytics
│   ├── posting_queries.py     # Posting module CRUD (publications, queue, log)
│   ├── group_queries.py       # Cross-platform submission groups
│   └── analytics_queries.py   # Top fans, trending, cross-platform links
│
├── polling/                   # Background poll cycle orchestration
│   ├── __init__.py
│   ├── poller.py              # Inkbunny poll cycle
│   ├── fa_poller.py           # FurAffinity poll cycle
│   ├── ws_poller.py           # Weasyl poll cycle
│   ├── bsky_poller.py         # Bluesky poll cycle
│   └── tw_poller.py           # X/Twitter poll cycle
│
├── routes/                    # FastAPI REST API routers
│   ├── __init__.py
│   ├── api.py                 # /api/* — IB + cross-platform endpoints
│   ├── fa_api.py              # /api/fa/* — FA endpoints
│   ├── sf_api.py              # /api/sf/* — SF endpoints
│   ├── sqw_api.py             # /api/sqw/* — SqW endpoints
│   ├── ao3_api.py             # /api/ao3/* — AO3 endpoints
│   ├── da_api.py              # /api/da/* — DA endpoints
│   ├── wp_api.py              # /api/wp/* — WP endpoints
│   ├── ik_api.py              # /api/ik/* — IK endpoints
│   ├── bsky_api.py            # /api/bsky/* — Bluesky endpoints
│   ├── tw_api.py              # /api/tw/* — X/Twitter endpoints
│   ├── ws_api.py              # /api/ws/* — WS endpoints
│   ├── posting_api.py         # /api/posting/* — Posting module (stories, post, queue, sync)
│   └── dashboard_auth.py      # Dashboard auth (login, 2FA, API keys, Turnstile)
│
├── frontend/                  # Vanilla JS SPA
│   ├── index.html             # SPA shell (sidebar + #app container)
│   ├── css/
│   │   └── styles.css         # Dark theme, responsive, all components
│   └── js/
│       ├── utils.js           # Formatting, dates, escaping, helpers
│       ├── api.js             # API fetch wrapper (~50 methods)
│       ├── components.js      # HTML template functions (~25 components)
│       ├── charts.js          # Chart.js factories (4 chart types)
│       ├── app.js             # SPA router + page renderers
│       ├── posting.js         # Posting module pages (stories, detail, queue, log)
│       └── vendor/            # Chart.js + plugins (not indexed)
│
├── posting/                   # Multi-platform story upload module
│   ├── __init__.py            # Package docstring
│   ├── manager.py             # Orchestrates uploads: resolve → post → record
│   ├── scheduler.py           # Daemon thread — processes posting_queue every 60s
│   ├── story_reader.py        # Reads story archives, builds StoryUploadPackage
│   ├── sync.py                # Retroactive claim + change detection
│   ├── generate_story_json.py # CLI: generate story.json from legacy data
│   ├── platforms/             # Per-platform poster implementations
│   │   ├── __init__.py
│   │   ├── base.py            # PlatformPoster ABC, PostResult, StoryUploadPackage
│   │   ├── inkbunny.py        # IB poster (official API upload)
│   │   ├── furaffinity.py     # FA poster (form scraping, desktop-only)
│   │   ├── weasyl.py          # WS poster (CSRF form + API key)
│   │   ├── sofurry.py         # SF poster (REST + CSRF chapters)
│   │   ├── squidgeworld.py    # SqW poster (OTW Rails form)
│   │   └── bluesky.py         # BSKY poster (AT Protocol announcements)
│   └── references/
│       └── inkbunny_bbcode_guide.md  # IB BBCode formatting reference
│
├── deploy/
│   ├── cf-worker.js           # Cloudflare Worker proxy
│   ├── setup-gcloud.sh        # GCP VM deployment automation
│   ├── setup-oracle.sh        # Oracle Cloud Always Free deployment
│   └── pawsync.bat            # Story archive sync (tar + gcloud scp to GCP)
│
├── inkbunny_analytics.spec    # PyInstaller build spec
├── build.bat                  # Build script
├── start_all.bat              # Dev: start dashboard + poller
├── start_dashboard.bat        # Dev: start dashboard only
├── start_poller.bat           # Dev: start poller only
├── requirements.txt           # Python dependencies
├── settings.json              # User settings (runtime)
└── .env                       # API keys (fallback)
```

---

## File-by-File Reference

### Entry Points

| File | Lines | Purpose |
|------|-------|---------|
| `main.py` | ~850 | App entry point — spawns 15 daemon threads + pywebview window |
| `poll_service.py` | 178 | Standalone CLI poller: `--once`, `--status`, or continuous (APScheduler) |
| `dashboard.py` | 87 | FastAPI app factory with lifespan, router mounting, static file serving |
| `config.py` | 236 | All paths, settings.json CRUD, credentials cascade, constants |
| `updater.py` | 159 | GitHub releases version check + self-update via batch script |

### API Clients

| File | Lines | Class | Auth Method |
|------|-------|-------|-------------|
| `api_client/client.py` | 394 | `InkbunnyClient` | Username/password → SID session token |
| `api_client/models.py` | 149 | Pydantic models | — |
| `fa_client/client.py` | 338 | `FAClient` | Cookie a + cookie b |
| `weasyl_client/client.py` | 245 | `WeasylClient` | API key via `X-Weasyl-API-Key` header |
| `bsky_client/client.py` | ~350 | `BskyClient` | App password → JWT (AT Protocol) |
| `tw_client/client.py` | ~400 | `TWClient` | Browser cookies (auth_token + ct0) |

### Database

| File | Lines | Purpose |
|------|-------|---------|
| `database/db.py` | 160 | Connection factory (WAL, Row, FK), schema loading, migrations |
| `database/schema.sql` | 156 | IB tables: submissions, snapshots, faving_users, comments, poll_log, session_cache |
| `database/fa_schema.sql` | 130 | FA tables: fa_submissions, fa_snapshots, fa_comments, fa_poll_log |
| `database/ws_schema.sql` | 100 | WS tables: ws_submissions, ws_snapshots, ws_poll_log |
| `database/queries.py` | 576 | IB CRUD: session cache, upsert, snapshots, faves, comments, summary, growth |
| `database/fa_queries.py` | 416 | FA CRUD: upsert, snapshots, comments, summary, growth |
| `database/ws_queries.py` | 297 | WS CRUD: upsert, snapshots, summary, growth |
| `database/bsky_schema.sql` | ~60 | BSKY tables: bsky_submissions (TEXT PK), bsky_snapshots, bsky_poll_log |
| `database/tw_schema.sql` | ~60 | TW tables: tw_submissions (TEXT PK), tw_snapshots, tw_poll_log |
| `database/bsky_queries.py` | ~400 | BSKY CRUD: upsert, snapshots, summary, growth (4 metrics) |
| `database/tw_queries.py` | ~450 | TW CRUD: upsert, snapshots, summary, growth (6 metrics) |
| `database/group_queries.py` | 114 | Cross-platform groups: CRUD, member management, aggregate stats |
| `database/analytics_queries.py` | 355 | Top fans, trending/spikes, cross-platform links, auto-suggest |
| `database/posting_schema.sql` | ~145 | Posting tables: publications, posting_queue, posting_log |
| `database/posting_queries.py` | ~300 | Posting CRUD: upsert publication, queue management, log entries |

### Posting Module

| File | Lines | Purpose |
|------|-------|---------|
| `posting/__init__.py` | ~25 | Package docstring — module overview |
| `posting/manager.py` | ~200 | Orchestrates uploads: resolve files → dispatch to posters → record results |
| `posting/scheduler.py` | ~120 | Daemon thread — checks posting_queue every 60s, respects requires field |
| `posting/story_reader.py` | ~350 | Reads story archives (story.json with per-chapter tags, split_manifest, tags_upload) → StoryUploadPackage. Tag chain: chapter → story → empty |
| `posting/sync.py` | ~200 | Retroactive claim (title matching) + change detection (file hash comparison) |
| `posting/generate_story_json.py` | ~200 | CLI tool: generate story.json from legacy tags_upload.txt + split_manifest |
| `posting/platforms/base.py` | ~100 | PlatformPoster ABC, PostResult dataclass, StoryUploadPackage dataclass |
| `posting/platforms/inkbunny.py` | ~130 | IB poster — api_upload.php + api_editsubmission.php |
| `posting/platforms/furaffinity.py` | ~150 | FA poster — 3-step form scrape, desktop-only (70s rate limit) |
| `posting/platforms/weasyl.py` | ~120 | WS poster — CSRF form submit + API key |
| `posting/platforms/sofurry.py` | ~130 | SF poster — REST PUT/POST with CSRF token |
| `posting/platforms/squidgeworld.py` | ~140 | SqW poster — OTW Rails form, author credentials |
| `posting/platforms/bluesky.py` | ~120 | BSKY poster — AT Protocol createRecord + uploadBlob |
| `posting/references/inkbunny_bbcode_guide.md` | — | IB BBCode formatting reference for story uploads |

### Polling

| File | Lines | Purpose |
|------|-------|---------|
| `polling/poller.py` | 397 | IB poll: auth → search → details → upsert → faves → comments → notify |
| `polling/fa_poller.py` | 294 | FA poll: gallery → details → upsert → comments → notify |
| `polling/ws_poller.py` | 253 | WS poll: validate → gallery → details → upsert |
| `polling/bsky_poller.py` | ~250 | BSKY poll: login → feed → details → upsert → notify |
| `polling/tw_poller.py` | ~250 | TW poll: cookies → tweets → details → upsert → notify |

### Routes

| File | Lines | Prefix | Purpose |
|------|-------|--------|---------|
| `routes/api.py` | 1083 | `/api` | IB endpoints + groups + analytics + links + update + settings |
| `routes/fa_api.py` | 469 | `/api/fa` | FA endpoints |
| `routes/ws_api.py` | 417 | `/api/ws` | WS endpoints |
| `routes/bsky_api.py` | ~350 | `/api/bsky` | Bluesky endpoints |
| `routes/tw_api.py` | ~350 | `/api/tw` | X/Twitter endpoints |
| `routes/posting_api.py` | ~650 | `/api/posting` | Posting: stories, post, update, queue, publications, claim, changes, sync |
| `routes/dashboard_auth.py` | ~350 | `/api/auth/dashboard-*` | Dashboard auth: login, 2FA, API keys, Turnstile |

### Frontend

| File | Lines | Purpose |
|------|-------|---------|
| `frontend/index.html` | 80 | SPA shell — sidebar nav + `<main id="app">` |
| `frontend/css/styles.css` | 925 | Dark theme CSS — responsive breakpoints at 900/768/480px |
| `frontend/js/utils.js` | 218 | Formatting, date parsing, escaping, thumbnail proxy URLs |
| `frontend/js/api.js` | 195 | API singleton — get/post wrappers + ~50 convenience methods |
| `frontend/js/components.js` | 697 | ~25 HTML template functions (tables, cards, lists, comments) |
| `frontend/js/charts.js` | 436 | Chart.js wrappers — aggregate, submission, top bar, comparison |
| `frontend/js/app.js` | 2524 | SPA router + all page renderers + state management |
| `frontend/js/posting.js` | ~650 | Posting module pages: stories hub, story detail, queue, log |

### Deploy

| File | Purpose |
|------|---------|
| `deploy/cf-worker.js` | Cloudflare Worker proxy (3 modes: normal, chain, login) |
| `deploy/setup-gcloud.sh` | GCP VM deployment automation |
| `deploy/setup-oracle.sh` | Oracle Cloud Always Free deployment |
| `deploy/pawsync.bat` | Story archive sync — tars Complete_Stories, gcloud scp to GCP, extracts on server |

---

## Database Tables

### Inkbunny (schema.sql)

| Table | Primary Key | Purpose |
|-------|-------------|---------|
| `submissions` | `submission_id` | Submission metadata + denormalized latest stats |
| `snapshots` | `id` (auto) | Time-series: views, faves, comments per poll |
| `faving_users` | `id` (auto) | Users who faved each submission (UNIQUE sub+user) |
| `comments` | `comment_id` | Scraped comment text with threading |
| `poll_log` | `id` (auto) | Poll audit trail: timing, status, counts |
| `session_cache` | `id` (CHECK=1) | Singleton: cached API session ID |

### FurAffinity (fa_schema.sql)

| Table | Primary Key | Purpose |
|-------|-------------|---------|
| `fa_submissions` | `submission_id` | FA submissions with category/theme/species/gender |
| `fa_snapshots` | `id` (auto) | Time-series per poll |
| `fa_comments` | `comment_id` (TEXT) | Comments via FAExport with reply threading |
| `fa_poll_log` | `id` (auto) | Poll audit trail |

### Weasyl (ws_schema.sql)

| Table | Primary Key | Purpose |
|-------|-------------|---------|
| `ws_submissions` | `submission_id` | WS submissions with subtype/media_url |
| `ws_snapshots` | `id` (auto) | Time-series per poll |
| `ws_poll_log` | `id` (auto) | Poll audit trail |

### Bluesky (bsky_schema.sql)

| Table | Primary Key | Purpose |
|-------|-------------|---------|
| `bsky_submissions` | `submission_id` (TEXT) | Post metadata + AT URI as ID + denormalized stats |
| `bsky_snapshots` | `id` (auto) | Time-series: likes, reposts, replies, quotes per poll |
| `bsky_poll_log` | `id` (auto) | Poll audit trail |

### X/Twitter (tw_schema.sql)

| Table | Primary Key | Purpose |
|-------|-------------|---------|
| `tw_submissions` | `submission_id` (TEXT) | Tweet metadata + stats (6 metrics) |
| `tw_snapshots` | `id` (auto) | Time-series: views, likes, retweets, replies, quotes, bookmarks |
| `tw_poll_log` | `id` (auto) | Poll audit trail |

### Cross-Platform (created by migrations in db.py)

| Table | Primary Key | Purpose |
|-------|-------------|---------|
| `submission_groups` | `group_id` (auto) | Named groups for organizing submissions |
| `submission_group_members` | `id` (auto) | Group membership (platform + submission_id) |
| `submission_links` | `link_id` (auto) | Links between same work on different platforms |
| `submission_link_members` | `id` (auto) | Link membership (platform + submission_id) |

### Posting Module (posting_schema.sql)

| Table | Primary Key | Purpose |
|-------|-------------|---------|
| `publications` | `pub_id` (auto) | Registry of what is posted where — UNIQUE(story_name, chapter_index, platform) |
| `posting_queue` | `queue_id` (auto) | Pending/scheduled uploads and updates with `requires` field (desktop/server/any) |
| `posting_log` | `log_id` (auto) | Immutable audit trail of every posting action (success or failure) |

---

## REST API Endpoints

### Inkbunny — `/api/*` (routes/api.py)

**Auth:**
| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/auth/status` | Check if credentials exist + has data |
| POST | `/api/auth/login` | Login with username/password/remember |
| POST | `/api/auth/logout` | Clear session + optionally clear saved creds |

**Polling:**
| Method | Path | Purpose |
|--------|------|---------|
| POST | `/api/poll/trigger` | Start a background poll cycle |
| POST | `/api/poll/full-resync` | Re-fetch all faves + comments (force_full=True) |
| GET | `/api/poll/progress` | Current poll phase/progress/message |

**Data:**
| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/status` | Last poll info |
| GET | `/api/summary` | Dashboard stats: totals, top lists, growth rates, recent activity |
| GET | `/api/submissions` | All submissions (sortable) with 24h deltas |
| GET | `/api/submissions/{id}` | Single submission detail + snapshots + faves + comments + growth |
| GET | `/api/submissions/{id}/snapshots` | Time-series snapshots (filterable by date range) |
| GET | `/api/aggregate` | Aggregate snapshots across all submissions |
| GET | `/api/comparison` | Multi-submission snapshot series (ids param) |
| GET | `/api/poll_log` | Poll history |
| POST | `/api/session/clear` | Clear cached IB session token |

**Settings:**
| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/settings/credentials` | Get saved username (not password) |
| POST | `/api/settings/credentials` | Save username + password |
| GET | `/api/settings/preferences` | Get all preferences |
| POST | `/api/settings/preferences` | Save preferences (merge) |
| GET | `/api/settings/telegram` | Get Telegram connection status |
| POST | `/api/settings/telegram` | Connect Telegram (token + chat_id) |
| POST | `/api/settings/telegram/test` | Send test notification |
| POST | `/api/settings/telegram/disconnect` | Remove Telegram config |

**Export:**
| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/export/submissions` | CSV download of all IB submissions |
| GET | `/api/export/snapshots` | CSV download of snapshots (optional id filter) |

**Groups:**
| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/groups` | List all groups with member counts |
| POST | `/api/groups` | Create group |
| POST | `/api/groups/{id}` | Update group name/description |
| DELETE | `/api/groups/{id}` | Delete group |
| POST | `/api/groups/{id}/members` | Add submission to group |
| DELETE | `/api/groups/{id}/members` | Remove submission from group |
| GET | `/api/groups/{id}/stats` | Aggregate stats for group members |

**Analytics:**
| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/analytics/top-fans` | Leaderboard (faves*2 + comments) |
| GET | `/api/analytics/trending` | Spike detection via z-score analysis |

**Cross-Platform Links:**
| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/links` | List all links with members |
| POST | `/api/links` | Create link (members: [{platform, submission_id}]) |
| DELETE | `/api/links/{id}` | Delete link |
| GET | `/api/links/{id}/stats` | Combined stats across linked submissions |
| GET | `/api/links/{id}/snapshots` | Merged time-series |
| GET | `/api/links/suggestions` | Auto-suggest by title similarity (Jaccard) |

**Auto-Update:**
| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/update/check` | Check GitHub releases for new version |
| POST | `/api/update/apply` | Download + apply update via batch script |

**Proxy:**
| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/thumb` | Proxy IB thumbnails (metapix.net whitelist) |

### FurAffinity — `/api/fa/*` (routes/fa_api.py)

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/fa/auth/status` | Check if FA cookies are configured |
| POST | `/api/fa/auth/connect` | Save FA cookies (cookie_a + cookie_b) |
| POST | `/api/fa/auth/disconnect` | Clear FA cookies + delete all FA data |
| GET | `/api/fa/status` | Last FA poll info |
| GET | `/api/fa/summary` | FA dashboard stats |
| GET | `/api/fa/submissions` | All FA submissions with deltas |
| GET | `/api/fa/submissions/{id}` | FA submission detail + snapshots + comments + growth |
| GET | `/api/fa/submissions/{id}/snapshots` | FA time-series |
| GET | `/api/fa/aggregate` | FA aggregate snapshots |
| GET | `/api/fa/comparison` | FA multi-submission comparison |
| GET | `/api/fa/poll_log` | FA poll history |
| POST | `/api/fa/poll/trigger` | Trigger FA poll |
| POST | `/api/fa/poll/full-resync` | FA full resync |
| GET | `/api/fa/poll/progress` | FA poll progress |
| GET | `/api/fa/export/submissions` | FA CSV export |
| GET | `/api/fa/export/snapshots` | FA snapshots CSV |
| GET | `/api/fa/thumb` | Proxy FA thumbnails (furaffinity.net/facdn.net whitelist) |

### Weasyl — `/api/ws/*` (routes/ws_api.py)

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/ws/auth/status` | Check if WS API key is configured |
| POST | `/api/ws/auth/connect` | Save WS API key (validates first) |
| POST | `/api/ws/auth/disconnect` | Clear WS key + delete all WS data |
| GET | `/api/ws/status` | Last WS poll info |
| GET | `/api/ws/summary` | WS dashboard stats |
| GET | `/api/ws/submissions` | All WS submissions with deltas |
| GET | `/api/ws/submissions/{id}` | WS submission detail + snapshots + growth |
| GET | `/api/ws/submissions/{id}/snapshots` | WS time-series |
| GET | `/api/ws/aggregate` | WS aggregate snapshots |
| GET | `/api/ws/comparison` | WS multi-submission comparison |
| GET | `/api/ws/poll_log` | WS poll history |
| POST | `/api/ws/poll/trigger` | Trigger WS poll |
| POST | `/api/ws/poll/full-resync` | WS full resync |
| GET | `/api/ws/poll/progress` | WS poll progress |
| GET | `/api/ws/export/submissions` | WS CSV export |
| GET | `/api/ws/export/snapshots` | WS snapshots CSV |

### Bluesky — `/api/bsky/*` (routes/bsky_api.py)

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/bsky/auth/status` | Check if BSKY credentials are configured |
| POST | `/api/bsky/auth/connect` | Save BSKY identifier + app_password |
| POST | `/api/bsky/auth/disconnect` | Clear BSKY creds + delete all BSKY data |
| GET | `/api/bsky/status` | Last BSKY poll info |
| GET | `/api/bsky/summary` | BSKY dashboard stats |
| GET | `/api/bsky/submissions` | All BSKY posts with deltas |
| GET | `/api/bsky/submissions/{submission_id:path}` | BSKY post detail (AT URI path param) |
| GET | `/api/bsky/submissions/{submission_id:path}/snapshots` | BSKY time-series |
| GET | `/api/bsky/aggregate` | BSKY aggregate snapshots |
| GET | `/api/bsky/comparison` | BSKY multi-post comparison |
| GET | `/api/bsky/poll_log` | BSKY poll history |
| POST | `/api/bsky/poll/trigger` | Trigger BSKY poll |
| POST | `/api/bsky/poll/full-resync` | BSKY full resync |
| GET | `/api/bsky/poll/progress` | BSKY poll progress |
| GET | `/api/bsky/export/submissions` | BSKY CSV export |
| GET | `/api/bsky/export/snapshots` | BSKY snapshots CSV |

### X/Twitter — `/api/tw/*` (routes/tw_api.py)

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/tw/auth/status` | Check if TW cookies are configured |
| POST | `/api/tw/auth/connect` | Save TW auth_token + ct0 + target_user |
| POST | `/api/tw/auth/disconnect` | Clear TW creds + delete all TW data |
| GET | `/api/tw/status` | Last TW poll info |
| GET | `/api/tw/summary` | TW dashboard stats |
| GET | `/api/tw/submissions` | All tweets with deltas |
| GET | `/api/tw/submissions/{submission_id}` | Tweet detail + snapshots + growth |
| GET | `/api/tw/submissions/{submission_id}/snapshots` | TW time-series |
| GET | `/api/tw/aggregate` | TW aggregate snapshots |
| GET | `/api/tw/comparison` | TW multi-tweet comparison |
| GET | `/api/tw/poll_log` | TW poll history |
| POST | `/api/tw/poll/trigger` | Trigger TW poll |
| POST | `/api/tw/poll/full-resync` | TW full resync |
| GET | `/api/tw/poll/progress` | TW poll progress |
| GET | `/api/tw/export/submissions` | TW CSV export |
| GET | `/api/tw/export/snapshots` | TW snapshots CSV |

### Posting Module — `/api/posting/*` (routes/posting_api.py)

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/posting/stories` | List all stories with publication status per platform |
| GET | `/api/posting/stories/{name}` | Full story detail: metadata, chapters, publications, stats |
| POST | `/api/posting/post` | Post story to platforms immediately (body: story_name, platforms, chapters) |
| POST | `/api/posting/update` | Push updates to already-posted submissions |
| GET | `/api/posting/publications` | List all publications (filterable by story/platform) |
| GET | `/api/posting/publications/stats` | Publications enriched with live stats from polling tables |
| GET | `/api/posting/publications/{pub_id}` | Single publication by ID |
| POST | `/api/posting/queue` | Add items to posting queue (with scheduling) |
| GET | `/api/posting/queue` | List pending/processing queue items |
| DELETE | `/api/posting/queue/{queue_id}` | Cancel a pending queue item |
| GET | `/api/posting/log` | Posting audit log (filterable by story, limit) |
| GET | `/api/posting/settings` | Get posting-related settings |
| POST | `/api/posting/settings` | Save posting-related settings |
| POST | `/api/posting/claim` | Retroactive sync: match submissions to stories |
| GET | `/api/posting/changes` | Detect publications with changed files |
| GET | `/api/posting/sync/status` | Per-story sync status summary |
| POST | `/api/posting/sync/upload` | Receive .tar.gz archive from desktop (server endpoint) |
| POST | `/api/posting/sync/push` | Push local archive to remote server (desktop endpoint) |

---

## Frontend SPA Routes

| Hash Route | Renderer | Page |
|------------|----------|------|
| `#/login` | `renderLogin()` | Full-screen login form |
| `#/loading` | `renderLoading()` | First-run progress screen |
| `#/overview` | `renderOverview()` | Cross-platform combined overview |
| `#/` | `renderDashboard()` | IB dashboard |
| `#/submissions` | `renderSubmissions()` | IB submissions table |
| `#/submission/:id` | `renderDetail(id)` | IB submission detail |
| `#/compare` | `renderCompare()` | IB multi-submission comparison |
| `#/fa` | `renderFADashboard()` | FA dashboard |
| `#/fa/submissions` | `renderFASubmissions()` | FA submissions table |
| `#/fa/submission/:id` | `renderFADetail(id)` | FA submission detail |
| `#/fa/compare` | `renderFACompare()` | FA comparison |
| `#/ws` | `renderWSDashboard()` | WS dashboard |
| `#/ws/submissions` | `renderWSSubmissions()` | WS submissions table |
| `#/ws/submission/:id` | `renderWSDetail(id)` | WS submission detail |
| `#/ws/compare` | `renderWSCompare()` | WS comparison |
| `#/bsky` | `renderBSKYDashboard()` | BSKY dashboard |
| `#/bsky/submissions` | `renderBSKYSubmissions()` | BSKY posts table |
| `#/bsky/submission/:rkey` | `renderBSKYDetail(rkey)` | BSKY post detail |
| `#/bsky/compare` | `renderBSKYCompare()` | BSKY comparison |
| `#/tw` | `renderTWDashboard()` | TW dashboard |
| `#/tw/submissions` | `renderTWSubmissions()` | TW tweets table |
| `#/tw/submission/:id` | `renderTWDetail(id)` | TW tweet detail |
| `#/tw/compare` | `renderTWCompare()` | TW comparison |
| `#/groups` | `renderGroups()` | Submission groups list |
| `#/group/:id` | `renderGroupDetail(id)` | Group detail + members |
| `#/cross-platform` | `renderCrossPlatform()` | Cross-platform links management |
| `#/posting` | `Posting.renderUpload()` | Story card hub (browse all stories) |
| `#/posting/story/:name` | `Posting.renderStoryDetail(name)` | Single story detail with platform controls |
| `#/posting/queue` | `Posting.renderQueue()` | Posting queue (pending/scheduled items) |
| `#/posting/log` | `Posting.renderLog()` | Posting audit log |
| `#/settings` | `renderSettings()` | All settings + poll logs |

---

## Function Index

### config.py — Configuration

| Function | Line | Purpose |
|----------|------|---------|
| `resource_path(relative)` | ~40 | Resolve asset path (frozen _MEIPASS or dev) |
| `_load_settings()` | ~90 | Read settings.json, return {} on failure |
| `save_settings(updates)` | ~100 | Merge updates into settings.json |
| `get_settings()` | ~110 | Public getter for full settings dict |
| `get_run_on_startup()` | ~185 | Check HKCU Run registry key |
| `set_run_on_startup(enable)` | ~200 | Set/clear HKCU Run registry key |

### main.py — Application Entry

| Function | Line | Purpose |
|----------|------|---------|
| `_start_poller()` | ~80 | IB poller thread: asyncio loop + interval polling |
| `_start_fa_poller()` | ~115 | FA poller thread |
| `_start_ws_poller()` | ~150 | WS poller thread |
| `_start_server()` | ~190 | Uvicorn server thread |
| `_load_tray_image()` | ~235 | Load .ico or generate fallback |
| `_show_window()` | ~250 | Restore pywebview from tray |
| `_quit_app()` | ~265 | Stop tray + destroy window → exit |
| `_create_tray_icon()` | ~280 | Create pystray icon with Show/Quit menu |
| `_minimize_to_tray_enabled()` | ~300 | Check minimize_to_tray setting |
| `_on_closing()` | ~310 | pywebview close handler: hide or destroy |
| `main()` | ~330 | Boot sequence: init DB → threads → wait for server → pywebview |

### dashboard.py — FastAPI App

| Function | Line | Purpose |
|----------|------|---------|
| `lifespan(app)` | ~30 | Startup/shutdown lifecycle (init_db) |
| `create_app()` | ~50 | Build FastAPI app, mount routers + static files |

### updater.py — Auto-Update

| Function | Line | Purpose |
|----------|------|---------|
| `check_for_update()` | ~28 | Check GitHub releases, compare versions |
| `download_update(url, dest)` | ~70 | Stream download ZIP to temp dir |
| `apply_update(zip_path)` | ~100 | Extract + write self-update batch script |

### api_client/client.py — InkbunnyClient

| Method | Line | Purpose |
|--------|------|---------|
| `login()` | ~50 | Authenticate, set ratings mask |
| `ensure_session()` | ~80 | Restore cached SID or re-login |
| `search_user_submissions()` | ~110 | Paginated search for user's submissions |
| `get_submission_details(ids)` | ~150 | Batch fetch full submission details |
| `get_faving_users(id)` | ~190 | Fetch users who faved a submission |
| `_ensure_web_session()` | ~210 | Browser login for web scraping (CSRF + cookies) |
| `scrape_comments(id)` | ~260 | Regex-based HTML comment extraction |
| `close()` | ~380 | Close HTTP clients |

### api_client/models.py — Pydantic Models

| Class | Purpose |
|-------|---------|
| `LoginResponse` | SID + ratingsmask from login |
| `SearchSubmission` | Lightweight submission from search results |
| `SearchResponse` | Paginated search response |
| `Keyword` | Single keyword entry |
| `SubmissionDetail` | Full submission with `to_db_dict()` normalization |
| `FavingUser` | Single faving user |
| `FavingUsersResponse` | List of faving users |

### fa_client/client.py — FAClient

| Method | Line | Purpose |
|--------|------|---------|
| `validate_cookies()` | ~50 | Check FA cookies via gallery page |
| `get_gallery_page(user, page)` | ~80 | Single gallery page from FAExport |
| `get_all_gallery_ids()` | ~95 | Paginate all gallery submissions |
| `get_submission_detail(id)` | ~120 | Single submission from FAExport |
| `get_submission_details_batch(ids)` | ~135 | Sequential detail fetch |
| `get_submission_comments(id)` | ~155 | Comments from FAExport API |
| `_normalize_submission(data)` | ~175 | FAExport → internal DB format |
| `_normalize_comment(data, sub_id)` | ~240 | FAExport comment → DB format |
| `_safe_int(val)` | ~270 | Parse ints from various formats |
| `close()` | ~330 | Close HTTP clients |

### weasyl_client/client.py — WeasylClient

| Method | Line | Purpose |
|--------|------|---------|
| `validate_key()` | ~50 | Validate API key via /api/whoami |
| `get_all_gallery_ids()` | ~75 | Cursor-paginated gallery fetch (nextid) |
| `get_submission_detail(id)` | ~110 | Single submission from /api/submissions/{id}/view |
| `get_submission_details_batch(ids)` | ~130 | Sequential detail fetch |
| `_normalize_submission(data)` | ~150 | Weasyl API → internal DB format |
| `_safe_int(val)` | ~220 | Parse ints |
| `close()` | ~240 | Close HTTP client |

### database/db.py — Connection & Schema

| Function | Line | Purpose |
|----------|------|---------|
| `get_connection()` | ~40 | Create SQLite connection (WAL + Row + FK) |
| `init_db()` | ~65 | Execute all 3 schema files + run migrations |
| `_run_migrations(conn)` | ~90 | Add comments, groups, links tables if missing |

### database/queries.py — Inkbunny Queries

| Function | Purpose |
|----------|---------|
| `get_cached_session(conn)` | Get singleton session cache |
| `save_session(conn, sid, username)` | Save/replace cached session |
| `clear_session(conn)` | Delete cached session |
| `upsert_submission(conn, data)` | INSERT OR REPLACE submission |
| `insert_snapshot(conn, id, views, faves, comments, polled_at)` | Record time-series data point |
| `get_submissions(conn, sort_by, order)` | All submissions sorted, with 24h deltas |
| `get_submission(conn, id)` | Single submission by ID |
| `get_snapshots(conn, id, start, end)` | Time-series for one submission |
| `get_aggregate_snapshots(conn, start, end)` | Summed time-series across all submissions |
| `get_comparison_snapshots(conn, ids, start, end)` | Per-submission time-series for comparison |
| `upsert_faving_user(conn, sub_id, user_id, username)` | Track faving user (returns is_new) |
| `get_faving_users(conn, sub_id)` | All faving users for a submission |
| `upsert_comment(conn, data)` | Insert comment if new (returns is_new) |
| `get_comments(conn, sub_id)` | All comments for a submission |
| `get_previous_fave_count(conn, sub_id)` | Last known fave count (for delta detection) |
| `get_previous_comments_count(conn, sub_id)` | Last known comment count |
| `start_poll_log(conn)` | Create poll_log row (status=running) |
| `finish_poll_log(conn, id, status, **stats)` | Update poll_log with results |
| `get_last_poll(conn)` | Most recent poll_log entry |
| `get_poll_log(conn, limit)` | Recent poll history |
| `get_summary(conn)` | Dashboard stats: totals, top lists, recent activity, growth |
| `get_growth_rates(conn, sub_id)` | 24h/7d/30d growth rates for one submission |
| `get_submission_deltas(conn)` | 24h view/fave/comment changes per submission |

### database/fa_queries.py — FA Queries

Same pattern as queries.py with `fa_` prefix. Key differences:
- `upsert_fa_comment()` instead of `upsert_comment()` — uses TEXT comment_id
- No `upsert_faving_user()` or `get_faving_users()` (FA doesn't provide this)
- `new_comments_found` in poll log instead of `new_faves_found`

### database/ws_queries.py — WS Queries

Same pattern as queries.py with `ws_` prefix. Key differences:
- No comment functions at all (WS API doesn't expose comment text)
- No faving user functions
- Simpler poll log (no fave or comment counts)

### database/group_queries.py — Groups

| Function | Purpose |
|----------|---------|
| `create_group(conn, name, description)` | Create submission group |
| `get_groups(conn)` | All groups with member counts |
| `get_group(conn, id)` | Single group |
| `update_group(conn, id, name, description)` | Update group metadata |
| `delete_group(conn, id)` | Delete group (CASCADE deletes members) |
| `add_group_member(conn, group_id, platform, sub_id)` | Add submission to group |
| `remove_group_member(conn, group_id, platform, sub_id)` | Remove from group |
| `get_group_stats(conn, id)` | Aggregate stats across group members (cross-platform) |

### database/analytics_queries.py — Analytics

| Function | Purpose |
|----------|---------|
| `get_top_fans(conn, limit)` | Leaderboard: faves*2 + comments across IB+FA |
| `get_trending_submissions(conn, hours, z_threshold)` | Z-score spike detection on snapshot deltas |
| `create_link(conn, members)` | Create cross-platform link |
| `delete_link(conn, link_id)` | Delete link |
| `get_links(conn)` | All links with member details |
| `get_link_combined_stats(conn, link_id)` | Summed stats across linked submissions |
| `get_link_combined_snapshots(conn, link_id)` | Merged time-series |
| `auto_suggest_links(conn)` | Find matches by Jaccard title similarity (threshold 0.6) |

### polling/poller.py — IB Poll Cycle

| Function | Purpose |
|----------|---------|
| `poll_progress` | Dict: {active, phase, current, total, message} — read by API |
| `run_poll_cycle(force_full)` | Full IB poll: auth → search → details → upsert → faves → comments |
| `_update_progress(phase, ...)` | Update progress dict |
| `_send_notifications(fave_details, comment_details)` | Windows toast notifications |
| `_send_telegram(fave_details, comment_details)` | Telegram notifications |

### polling/fa_poller.py — FA Poll Cycle

| Function | Purpose |
|----------|---------|
| `fa_poll_progress` | Dict: same pattern, `fa_` prefix |
| `run_fa_poll_cycle(force_full)` | Full FA poll: gallery → details → upsert → comments |
| `_send_fa_notifications(comment_details)` | Toast notifications (comments only) |
| `_send_fa_telegram(comment_details)` | Telegram notifications |

### polling/ws_poller.py — WS Poll Cycle

| Function | Purpose |
|----------|---------|
| `ws_poll_progress` | Dict: same pattern, `ws_` prefix |
| `run_ws_poll_cycle(force_full)` | WS poll: validate → gallery → details → upsert |
| `_send_ws_notifications(details)` | Toast notifications (generic "gained activity") |
| `_send_ws_telegram(details)` | Telegram notifications |

---

## Frontend JavaScript

### utils.js — Utility Functions

| Function | Purpose |
|----------|---------|
| `formatNumber(n)` | Locale-formatted number (1,234) |
| `formatCompact(n)` | Abbreviated (1.2K, 3.4M) |
| `formatDelta(n)` | Colored +/- HTML span for 24h changes |
| `_parseDate(str)` | Normalize date strings (IB "+00", bare, ISO) |
| `formatDate(str)` | Smart date (omit year if current), en-AU locale |
| `formatDateTime(str)` | Relative date+time (Today/Yesterday/date) |
| `timeAgo(str)` | Relative time (5m ago, 3h ago, 2d ago) |
| `escapeHtml(str)` | XSS prevention for innerHTML |
| `truncate(str, len)` | Ellipsis truncation |
| `thumbUrl(url)` | IB thumbnail proxy URL (/api/thumb) |
| `faThumbUrl(url)` | FA thumbnail proxy URL (/api/fa/thumb) |
| `getDateRange(preset)` | Preset → {start, end} ISO strings |

### api.js — API Wrapper

| Section | Methods |
|---------|---------|
| Core | `get(path, params)`, `post(path, body)` |
| IB | `getStatus`, `getSummary`, `getSubmissions`, `getSubmission`, `getSnapshots`, `getAggregate`, `getComparison`, `getPollLog`, `triggerPoll`, `fullResync`, `clearSession`, `getAuthStatus`, `authLogin`, `authLogout`, `getPollProgress`, `getCredentials`, `saveCredentials`, `getPreferences`, `savePreferences`, `getTelegram`, `connectTelegram`, `testTelegram`, `disconnectTelegram` |
| FA | `getFAAuthStatus`, `faConnect`, `faDisconnect`, `getFAStatus`, `getFASummary`, `getFASubmissions`, `getFASubmission`, `getFASnapshots`, `getFAAggregate`, `getFAComparison`, `getFAPollLog`, `triggerFAPoll`, `fullFAResync`, `getFAPollProgress` |
| WS | `getWSAuthStatus`, `wsConnect`, `wsDisconnect`, `getWSStatus`, `getWSSummary`, `getWSSubmissions`, `getWSSubmission`, `getWSSnapshots`, `getWSAggregate`, `getWSComparison`, `getWSPollLog`, `triggerWSPoll`, `fullWSResync`, `getWSPollProgress` |
| Export | `exportSubmissions(platform)`, `exportSnapshots(platform, id)` |
| Groups | `getGroups`, `createGroup`, `updateGroup`, `deleteGroup`, `addGroupMember`, `removeGroupMember`, `getGroupStats` |
| Analytics | `getTopFans`, `getTrending` |
| Links | `getLinks`, `createLink`, `deleteLink`, `getLinkStats`, `getLinkSnapshots`, `getLinkSuggestions` |
| Update | `checkUpdate`, `applyUpdate` |

### charts.js — Chart.js Factories

| Function | Type | Purpose |
|----------|------|---------|
| `aggregateLine(canvasId, snapshots, metrics)` | Line | Multi-metric time-series (dashboard) |
| `submissionLine(canvasId, snapshots)` | Line | Dual Y-axis (views left, faves/comments right) |
| `topBar(canvasId, items, valueKey)` | Bar | Horizontal bar chart (top rankings) |
| `comparisonLine(canvasId, series, titles, metric)` | Line | Multi-submission overlay with milestones |

### components.js — HTML Templates

| Component | Platform | Purpose |
|-----------|----------|---------|
| `statCard(label, value, delta)` | All | Metric card with optional 24h delta |
| `topList(items, valueKey)` | IB | Clickable ranked list |
| `recentFaves(items)` | IB | Fave activity feed |
| `dateRangeBar(active)` | All | Time filter buttons (24h/7d/30d/90d/All) |
| `submissionsTable(subs)` | IB | Sortable submissions table with thumbnails |
| `pollLogTable(polls)` | IB | Poll history with colored status |
| `favingUsersTable(users)` | IB | Users who faved a submission |
| `commentsSection(comments)` | IB | Threaded comments display |
| `recentComments(items)` | IB | Recent comments feed |
| `growthRateCards(rates)` | All | 24h/7d/30d growth metrics |
| `keywords(jsonStr)` | All | Tag badges from JSON array |
| `overviewTopList(items)` | Cross | Cross-platform ranked list with badges |
| `overviewRecentActivity(items)` | Cross | Cross-platform activity feed |
| `faTopList(items)` | FA | FA ranked list |
| `faRecentComments(items)` | FA | FA recent comments |
| `faSubmissionsTable(subs)` | FA | FA submissions table |
| `faPollLogTable(polls)` | FA | FA poll log |
| `wsTopList(items)` | WS | WS ranked list |
| `wsSubmissionsTable(subs)` | WS | WS submissions table |
| `wsPollLogTable(polls)` | WS | WS poll log |
| `groupsList(groups)` | Cross | Group cards |
| `topFansTable(fans)` | Cross | Fan leaderboard |
| `trendingCards(items)` | Cross | Spike detection cards |
| `linkCards(links)` | Cross | Cross-platform link cards |
| `linkSuggestions(suggestions)` | Cross | Auto-suggested links |
| `faCommentsSection(comments)` | FA | FA threaded comments |

### app.js — SPA Router & State

**State:**
| Property | Purpose |
|----------|---------|
| `_sortState` | IB table sort: {field, order} |
| `_faSortState` | FA table sort |
| `_wsSortState` | WS table sort |
| `_dateRange` | Active time filter preset |
| `_compareIds` | IB selected submission IDs for comparison (Set) |
| `_faCompareIds` | FA comparison selections |
| `_wsCompareIds` | WS comparison selections |
| `_compareMetric` | IB comparison metric (views/favorites_count/comments_count) |
| `_faCompareMetric` | FA comparison metric |
| `_wsCompareMetric` | WS comparison metric |
| `_autoRefreshTimer` | 60s auto-refresh interval ID |

**Key Methods:**
| Method | Purpose |
|--------|---------|
| `init()` | Boot: auth check, router, hamburger, logout |
| `route()` | Hash parser → renderer dispatch |
| `_bindDateRange(callback)` | Wire date range button clicks |
| `_bindTableSort()` / `_bindFATableSort()` / `_bindWSTableSort()` | Column header sort handlers |
| `_bindSearch(subs)` / `_bindFASearch(subs)` / `_bindWSSearch(subs)` | Client-side text/filter search |
| `_startAutoRefresh(renderFn)` | 60s page refresh (skips when tab hidden) |
| `_updatePollStatus()` | Sidebar "Last poll: Xm ago" update |

---

## Platform Comparison

| Feature | Inkbunny | FurAffinity | Weasyl |
|---------|----------|-------------|--------|
| **Auth** | Username/password → SID | Cookie a + Cookie b | API key header |
| **API** | Official JSON API | FAExport (3rd party) | Official REST API |
| **Pagination** | Page-based | Page-based | Cursor-based (nextid) |
| **Faving Users** | Yes (API endpoint) | No | No |
| **Comment Text** | Yes (web scraping) | Yes (FAExport JSON) | No (count only) |
| **Comment Threading** | is_reply + reply_to_comment_id | reply_to + reply_level | N/A |
| **Submission Metadata** | type_name, rating_id/name | category, theme, species, gender | subtype, rating |
| **Thumbnail Proxy** | Yes (metapix.net) | Yes (furaffinity.net/facdn.net) | No (direct URL) |
| **Notification Type** | Faves + Comments | Comments only | Generic "activity" |
| **DB Tables** | 6 (submissions, snapshots, faving_users, comments, poll_log, session_cache) | 4 (submissions, snapshots, comments, poll_log) | 3 (submissions, snapshots, poll_log) |

### Bluesky vs X/Twitter

| Feature | Bluesky | X/Twitter |
|---------|---------|-----------|
| **Auth** | App password → JWT (AT Protocol) | Browser cookies (auth_token + ct0) |
| **API** | AT Protocol public API | Internal GraphQL (cookie-based scraping) |
| **Pagination** | Cursor-based | Cursor-based (GraphQL) |
| **Metrics** | likes, reposts, replies, quotes (4) | views, likes, retweets, replies, quotes, bookmarks (6) |
| **ID Format** | AT URI (TEXT, contains slashes) | Numeric string (TEXT, exceeds JS safe int) |
| **Views** | No | Yes |
| **Notification Type** | Generic "activity" | Generic "activity" |
| **DB Tables** | 3 (bsky_submissions, bsky_snapshots, bsky_poll_log) | 3 (tw_submissions, tw_snapshots, tw_poll_log) |

---

## Settings Keys (settings.json)

| Key | Type | Default | Purpose |
|-----|------|---------|---------|
| `username` | string | "" | IB username |
| `password` | string | "" | IB password |
| `minimize_to_tray` | bool | false | Hide to tray instead of quit |
| `run_on_startup` | bool | false | Launch with Windows |
| `notifications_enabled` | bool | true | IB desktop toast notifications |
| `poll_interval_minutes` | int | 60 | IB poll frequency |
| `fa_cookie_a` | string | "" | FA auth cookie a |
| `fa_cookie_b` | string | "" | FA auth cookie b |
| `fa_username` | string | "" | FA username |
| `fa_notifications_enabled` | bool | true | FA desktop notifications |
| `fa_poll_interval_minutes` | int | 60 | FA poll frequency |
| `ws_api_key` | string | "" | Weasyl API key |
| `ws_notifications_enabled` | bool | true | WS desktop notifications |
| `ws_poll_interval_minutes` | int | 60 | WS poll frequency |
| `telegram_enabled` | bool | false | Telegram notifications on/off |
| `telegram_bot_token` | string | "" | Telegram bot token |
| `telegram_chat_id` | string | "" | Telegram chat/user ID |
| `notification_comments_only` | bool | false | IB: only notify on comments |
| `fa_notification_comments_only` | bool | false | FA: only notify on comments |
| `ws_notification_comments_only` | bool | false | WS: suppress fave-triggered activity alerts |
| `watcher_notifications_enabled` | bool | true | IB watcher toast + Telegram alerts |
| `fa_watcher_notifications_enabled` | bool | true | FA watcher toast + Telegram alerts |
| `sf_username` | string | "" | SF login email |
| `sf_password` | string | "" | SF password |
| `sf_display_name` | string | "" | SF display name |
| `sf_notifications_enabled` | bool | true | SF desktop notifications |
| `sf_poll_interval_minutes` | int | 60 | SF poll frequency |
| `sf_notification_comments_only` | bool | false | SF: suppress generic activity alerts |
| `sqw_username` | string | "" | SqW login username |
| `sqw_password` | string | "" | SqW password |
| `sqw_target_user` | string | "" | SqW target username to track |
| `sqw_notifications_enabled` | bool | true | SqW desktop notifications |
| `sqw_poll_interval_minutes` | int | 60 | SqW poll frequency |
| `ao3_username` | string | "" | AO3 login username |
| `ao3_password` | string | "" | AO3 password |
| `ao3_target_user` | string | "" | AO3 target username to track |
| `ao3_notifications_enabled` | bool | true | AO3 desktop notifications |
| `ao3_poll_interval_minutes` | int | 60 | AO3 poll frequency |
| `da_cookie` | string | "" | DA auth cookie string |
| `da_target_user` | string | "" | DA username to track |
| `da_notifications_enabled` | bool | true | DA desktop notifications |
| `da_poll_interval_minutes` | int | 60 | DA poll frequency |
| `wp_target_user` | string | "" | WP username/story URL to track |
| `wp_notifications_enabled` | bool | true | WP desktop notifications |
| `wp_poll_interval_minutes` | int | 60 | WP poll frequency |
| `ik_target_user` | string | "" | IK username to track |
| `ik_notifications_enabled` | bool | true | IK desktop notifications |
| `ik_poll_interval_minutes` | int | 60 | IK poll frequency |
| `display_timezone` | string | "UTC" | Timezone for Telegram messages and timestamps |
| `milestone_views` | int[] | [100,250,...,100000] | View milestone thresholds for Telegram alerts |
| `milestone_faves` | int[] | [10,25,...,5000] | Fave milestone thresholds for Telegram alerts |
| `milestone_comments` | int[] | [10,25,...,1000] | Comment milestone thresholds for Telegram alerts |
| `bsky_identifier` | string | "" | Bluesky handle or DID |
| `bsky_app_password` | string | "" | Bluesky app password |
| `bsky_notifications_enabled` | bool | true | BSKY desktop notifications |
| `bsky_poll_interval_minutes` | int | 60 | BSKY poll frequency |
| `tw_auth_token` | string | "" | X/Twitter auth_token cookie |
| `tw_ct0` | string | "" | X/Twitter ct0 CSRF cookie |
| `tw_target_user` | string | "" | X/Twitter username to track |
| `tw_notifications_enabled` | bool | true | TW desktop notifications |
| `tw_poll_interval_minutes` | int | 60 | TW poll frequency |
| `notification_min_views_delta` | int | 0 | Stored for future use (no view-based notifications yet) |
| `notification_min_faves_delta` | int | 0 | Min new-fave count per cycle to trigger IB fave notifications |
| `views_offset` | int | 0 | IB stat correction offset |
| `faves_offset` | int | 0 | IB stat correction offset |
| `comments_offset` | int | 0 | IB stat correction offset |

---

## CSS Responsive Breakpoints

| Breakpoint | Changes |
|------------|---------|
| 900px | Chart rows → single column, stats grid → 2 columns, growth grid → 1 column |
| 768px | Sidebar → slide-in overlay, hamburger shown, main content full-width, touch-friendly 44px buttons |
| 480px | Stats grid → single column, detail header stacked, table columns 3-4 hidden |

---

## Build & Deployment

**PyInstaller**: `inkbunny_analytics.spec` bundles into single-directory exe
- Bundled assets: frontend/, schema SQL files, icon
- User data: `%APPDATA%/PawPoller/` (DB, settings, logs)
- Auto-update: GitHub releases → streaming ZIP download → robocopy batch script → restart

**Dev scripts**:
- `start_all.bat` — Start dashboard + poller
- `start_dashboard.bat` — Dashboard only
- `start_poller.bat` — Poller only
- `build.bat` — PyInstaller build
