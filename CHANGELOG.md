# PawPoller Changelog

All notable changes to PawPoller are documented here.

---

## [2.2.0] - 2026-04-06

### Added
- **Per-chapter tag support** — story_reader.py now reads `chapter_info[].tags` from story.json and populates `chapter_tags_by_platform`. Per-chapter uploads (FA, SQW) use chapter-specific tags when available, falling back to story-level tags.
- **Platform tag limits reference** — `posting/references/platform_tag_limits.md` documenting tag limits (SF≤97, WP≤24, DA≤30), SQW/AO3 archive warnings, categories, ratings, and relationship notation.
- **Complete story.json metadata** for all 11 stories — descriptions, summaries, categories, warnings, characters, relationships, per-platform tags (from Tag_Database), per-chapter tags and descriptions for all 67 chapters.
- **Itaku posting support** (platform 8) — image gallery uploads and text posts via Django REST Framework token auth.
- **DeviantArt posting support** (platform 9) — via official OAuth2 literature API with auto-refreshing tokens.
- **AO3 posting support** (platform 7) — same OTW Archive form structure as SquidgeWorld.

### Changed
- `posting/story_reader.py` — `_load_from_story_json()` now reads per-chapter tags and populates `chapter_tags_by_platform` dict. `build_package()` tag selection chain: chapter tags → story tags → empty.
- `posting/generate_story_json.py` — generates AO3 and DeviantArt platform configs in story.json.
- `database/db.py` — SQLite timeout increased from 10s to 30s + `PRAGMA busy_timeout=30000` for concurrent poll cycle contention.

### Fixed
- **SQLite "database is locked" errors** during concurrent poll cycles — busy_timeout pragma makes writers queue instead of erroring.
- **Styled HTML title font-size** standardised to 2.8rem across all stories (was 3rem in Hypnotic Claim and NSES).

---

## [2.1.0] - 2026-04-05

### Added
- **DeviantArt posting support** (platform 9) — via official OAuth2 literature API
  - `da_client/client.py` — `oauth_create_literature()`, `oauth_update_literature()`, `oauth_refresh_token()`
  - `posting/platforms/deviantart.py` — DeviantArtPoster with post, edit, replace_file (body content)
  - Uses official OAuth2 API (not undocumented _napi) — stable, works from any IP
  - Requires app registration: `da_client_id`, `da_client_secret`, `da_refresh_token` in settings
  - Auto-refreshes access tokens (1-hour expiry, 3-month refresh tokens)
  - Title max 50 chars, max 30 tags, mature level/classification support
  - Format: reads from Markdown (MASTER.md or chapter files)

- **Itaku posting support** (platform 8) — image gallery uploads and text posts
  - `ik_client/client.py` — `upload_image()` (multipart gallery), `create_post()` (JSON text post)
  - `posting/platforms/itaku.py` — ItakuPoster with image upload and text post support
  - Auth: Django REST Framework token from browser session (`ik_auth_token` setting)
  - Min 5 tags, max 10MB images, ratings: SFW/Questionable/NSFW
  - No edit or file replacement support (Itaku API limitation)
  - Note: Itaku is primarily for art, not literature. Text posts limited to ~5000 chars.

- **AO3 posting support** (platform 7) — same OTW Archive software as SquidgeWorld
  - `ao3_client/client.py` — `create_work()`, `edit_work()`, `edit_chapter()`, `get_chapter_ids()`, HTML whitespace collapse
  - `posting/platforms/ao3.py` — AO3Poster with post, edit (metadata + chapters), replace_file
  - Uses existing `ao3_username`/`ao3_password` credentials (same account for polling and posting)
  - 3-second rate limit between requests (AO3 is volunteer-run)
  - Registered in manager, story_reader, frontend, story.json generator

### Fixed
- **SQLite "database is locked" errors** — increased timeout from 10s to 30s + added `PRAGMA busy_timeout=30000` for concurrent poll cycle contention

---

## [2.0.0] - 2026-04-04

### Added — Multi-Platform Posting Module
Complete story publishing system — upload, edit, and manage stories across 7 platforms from PawPoller.

**Core Infrastructure:**
- `posting/` module — manager, scheduler, story reader, sync, platform posters
- `database/posting_schema.sql` — 3 tables: publications, posting_queue, posting_log
- `database/posting_queries.py` — Full CRUD for all posting tables
- `routes/posting_api.py` — 12+ REST endpoints for posting operations
- `posting/scheduler.py` — Background daemon thread processing the posting queue
- Desktop/server queue mode — FA items auto-queue for desktop when server can't process

**Platform Posters (6 platforms):**
- **Inkbunny** (`posting/platforms/inkbunny.py`) — API upload + edit via `api_upload.php` / `api_editsubmission.php`. Story text uses `story` field (reading panel), `desc` for summary. BBCode text message styling (coloured, aligned sent/received).
- **FurAffinity** (`posting/platforms/furaffinity.py`) — 3-step form scrape (GET key → POST upload → POST finalize). Edit via `/controls/submissions/changeinfo/`. File replace via `/controls/submissions/changestory/`. 70s rate limit.
- **SoFurry** (`posting/platforms/sofurry.py`) — REST + CSRF (PUT create → POST content chapter → POST metadata). Chapter-based story content. Author credentials for editing.
- **Weasyl** (`posting/platforms/weasyl.py`) — CSRF + form POST to `/submit/literary`. API key auth.
- **SquidgeWorld** (`posting/platforms/squidgeworld.py`) — OTW Archive form scraping. Author credentials (separate from polling account). HTML whitespace collapse to prevent `<br />` injection. Work Skin CSS classes preserved.
- **Bluesky** (`posting/platforms/bluesky.py`) — AT Protocol `createRecord` + `uploadBlob`. Announcement posts with NSFW labels. Link facet extraction.

**Story Archive System:**
- `story.json` per story — standardised metadata (title, author, rating, warnings, tags, chapters, platforms, images)
- `posting/generate_story_json.py` — generates story.json from existing tags_upload.txt + split_manifest.json
- `posting/story_reader.py` — reads story.json (preferred) or falls back to legacy tag/manifest parsing
- Platform-specific description selection (summary for SQW/AO3, short blurb for IB/SF)
- Format file resolution per platform (BBCode→IB, PDF→FA, SoFurry HTML→SF, SquidgeWorld HTML→SQW)

**Retroactive Sync:**
- `posting/sync.py` — claim existing submissions into publications registry by title matching
- 25 publications claimed across IB, FA, SF, SQW, WP
- Fuzzy matching: full stories, per-chapter (FA), sub-stories (Abstinent Bet), part words
- `/claim` Telegram command and `/api/posting/claim` endpoint

**Change Detection:**
- `file_hash` column on publications — SHA-256 of format file at time of posting
- `detect_changes()` / `get_changed_stories()` / `get_sync_status_summary()`
- `/changes` Telegram command and `/api/posting/changes` endpoint
- After `/update`, hashes are refreshed so `/changes` shows stories as up-to-date

**Desktop Queue Mode:**
- `requires` column on posting_queue: `any`, `desktop`, `server`
- FA flagged as `requires_mode = "desktop"` (needs residential IP)
- Scheduler auto-detects runtime mode (pywebview importable = desktop)
- Failed server posts auto-queue for desktop with `requires=desktop`

**Batch Operations:**
- `/update all [platforms]` — pushes all changed stories to all platforms
- `/update all fa` — batch update on single platform
- Auto-queue fallback: failed server edits queued for desktop processing

**Dashboard UI:**
- Story card hub (`#/posting`) — grid of cards with title, words, chapters, rating, platform badges
- Story detail page (`#/posting/story/{name}`) — full metadata, publications with live stats, upload/update buttons, chapter list, format inventory
- Queue page (`#/posting/queue`) — pending items with cancel
- History page (`#/posting/log`) — audit trail
- Published page redirects to Stories hub
- Mobile responsive: single-column cards, full-width buttons, 44px touch targets
- Bottom nav: Stories link added

**Telegram Commands:**
- `/stories` — list archive stories
- `/upload <story> [platforms]` — post story to platforms
- `/update <story> [platforms]` — push updates to posted submissions
- `/update all [platforms]` — batch update all changed stories
- `/posted [story]` — show publication registry
- `/claim [platforms]` — claim existing submissions
- `/changes` — show which stories have changed since last update

**BBCode Converter Fixes:**
- Title uses `[t]` tag (IB title style) instead of `[b]`
- Subtitle detection: only `*by Author*` or `*A Something Story*` patterns, window closes on first non-subtitle content
- Text messages styled: sent (MAYA) right-aligned blue `#4a9eff`, received left-aligned grey `#aab0bc`
- Phone calls: centred with `📱` emoji and decorative lines
- No longer centres first italic body paragraph after chapter headings

**Story Sync:**
- `deploy/pawsync.bat` — syncs story archive to GCP server
- Fixed: was excluding `*/SquidgeWorld/*` — now includes all format folders
- PyInstaller spec updated with `posting_schema.sql`

### Changed
- `api_client/client.py` — added `upload_submission()`, `edit_submission()` with `story` field
- `bsky_client/client.py` — added `_post_json()`, `upload_blob()`, `create_post()`, `delete_post()`
- `weasyl_client/client.py` — added `submit_literary()`, `edit_submission()` with CSRF
- `sf_client/client.py` — added `_get_csrf_meta()`, `create_submission()` (chapter-based), `edit_submission()`
- `fa_client/client.py` — added `submit_story()` (3-step), `edit_submission()` via `changeinfo`, file replace via `changestory`
- `sqw_client/client.py` — added `create_work()`, `edit_work()`, `edit_chapter()`, `get_chapter_ids()`, `_collapse_html_whitespace()`
- `dashboard.py` — registered `posting_router`
- `database/db.py` — loads `posting_schema.sql`, migrations for `file_hash` and `requires` columns
- `main.py` + `server.py` — posting scheduler daemon thread added
- `polling/telegram_bot.py` — 7 new commands + help text updated
- `inkbunny_analytics.spec` — added `posting_schema.sql` to PyInstaller data files

---

## [1.6.0] - 2026-03-10

### Added
- **Bluesky platform support** (platform 10) — AT Protocol integration with JWT session auth via app passwords
  - `bsky_client/client.py` — `BskyClient` with login/refresh/check session chain, batch post fetching (25 URIs per call), cursor-paginated feed discovery
  - `database/bsky_schema.sql` — `bsky_submissions` (TEXT PK for AT URIs), `bsky_snapshots`, `bsky_poll_log`
  - `database/bsky_queries.py` — Full CRUD with `get_bsky_submission_by_rkey()` suffix match for AT URI resolution
  - `polling/bsky_poller.py` — Poll cycle with 🦋 emoji notifications, activity trigger on likes/reposts changes
  - `routes/bsky_api.py` — `/api/bsky/*` endpoints with `{submission_id:path}` for AT URI path params
  - Frontend: Dashboard (4 stat cards: likes, reposts, replies, quotes — no views), posts table, detail view, comparison charts
  - Metrics: likes, reposts, replies, quotes (4 metrics, no view counts)

- **X/Twitter platform support** (platform 11) — Cookie-based GraphQL scraping of internal endpoints
  - `tw_client/client.py` — `TWClient` with auth_token + ct0 cookie auth, GraphQL query endpoints (UserByScreenName, UserTweets, TweetResultByRestId), content type detection (tweet/reply/retweet/quote)
  - `database/tw_schema.sql` — `tw_submissions` (TEXT PK for tweet IDs), `tw_snapshots`, `tw_poll_log`
  - `database/tw_queries.py` — Full CRUD with 6 metrics, default sort by views DESC
  - `polling/tw_poller.py` — Poll cycle with 🐦 emoji notifications, 2s inter-request delay (aggressive rate limiting)
  - `routes/tw_api.py` — `/api/tw/*` endpoints with content_type filtering
  - Frontend: Dashboard (7 stat cards: views, likes, retweets, replies, quotes, bookmarks), tweets table with type column, detail view, comparison charts
  - Metrics: views, likes, retweets, replies, quotes, bookmarks (6 metrics — most of any platform)

- **Cross-platform integration** for both platforms:
  - Overview page: BSKY/TW included in totals, top lists, recent activity, aggregate charts, export buttons
  - Settings page: BSKY (identifier + app_password) and TW (auth_token + ct0 + target_user) credential sections with connect/disconnect/poll/resync controls
  - Telegram notifications: digest reports, milestone alerts, `/stats`, `/top`, `/poll`, `/interval`, `/notifications` bot commands
  - Analytics: trending detection, cross-platform links, group stats
  - Platform badges: `.platform-badge.bsky` (blue #0085ff) and `.platform-badge.tw` (blue #1d9bf0)
  - Navigation: Bluesky and X/Twitter sidebar groups with Dashboard/Posts/Compare links

### Changed
- Thread count increased from 12 to 14 daemon threads (added BSKY + TW pollers)
- `config.py` — Added `BSKY_REQUEST_DELAY_SECONDS = 1.0` and `TW_REQUEST_DELAY_SECONDS = 2.0`
- `database/db.py` — Schema init loads `bsky_schema.sql` and `tw_schema.sql`
- `dashboard.py` — Registers `bsky_router` and `tw_router`
- `server.py` — Added env-to-settings mappings for BSKY/TW credentials
- `polling/telegram.py` — Added BSKY/TW to platform metrics, emoji, name maps, digest reports, goal checking
- `polling/telegram_bot.py` — Added BSKY/TW to all 10+ platform maps (stats, poll, interval, notify commands)
- `database/analytics_queries.py` — Added BSKY/TW to trending and cross-platform metrics
- `database/group_queries.py` — Added BSKY/TW to group stats metrics
- `routes/api.py` — Added BSKY/TW to table maps and allowed metrics (reposts, retweets, bookmarks, quotes)
- `inkbunny_analytics.spec` — Added BSKY/TW schema files to PyInstaller datas

---

## [1.5.0] - 2026-03-09

### Added
- **Mobile-first UI overhaul** — comprehensive responsive redesign for phone and tablet use
- **Collapsible sidebar navigation** — platform sections collapse into accordion groups on mobile (<=768px), reducing 30+ links to manageable groups that expand on tap
- **Bottom navigation bar** — fixed bottom bar on mobile with quick access to Overview, Platforms (opens sidebar), Analytics, and Settings
- **Table-to-card transformation** — all 9 platform submission tables transform into stacked card layouts on mobile using `data-label` attributes for inline column headers
- **Safe area support** — `viewport-fit=cover` and `env(safe-area-inset-*)` CSS for notched devices (iPhone etc.)
- **Touch optimisation** — `touch-action: manipulation` on all interactive elements, `-webkit-tap-highlight-color: transparent`, 44px minimum touch targets
- **Responsive chart sizing** — chart heights reduce from 280px to 220px/200px at tablet/phone breakpoints
- **Mobile-friendly settings** — form inputs stack vertically with full-width fields and 44px min-height on mobile
- **Wider sidebar on mobile** — sidebar expands to 280px (up from 220px) when opened as overlay for easier tap targets
- **Date range buttons** — range buttons flex-fill and centre-align on mobile for even spacing

### Changed
- Sidebar overlay element moved from JS-created to HTML for better bottom-nav integration
- Stat cards use 10px gap on mobile (down from 16px) and single-column at 480px
- Pinned cards use smaller flex-basis (160px/140px) for better mobile scrolling
- Top list titles truncate at 55vw/60vw on mobile for consistent layout
- Comment cards reduce padding on mobile for space efficiency
- Growth rate values use smaller font (14px) at 480px

---

## [1.4.2] - 2026-03-09

### Security
- **Zip Slip prevention** — auto-updater now validates all ZIP entry paths before extraction to prevent path traversal attacks
- **XSS fix** — `escapeHtml()` now escapes single quotes (`'` -> `&#39;`) preventing attribute injection via submission titles
- **Timing attack fix** — HTTP Basic Auth now evaluates both username and password in constant time (no short-circuit)
- **Error response hardening** — global exception handler no longer leaks internal error details to clients

### Fixed
- **SqW Anubis solver** — proof-of-work implementation now correctly finds a nonce with leading zeros matching difficulty, instead of computing a single hash (which always failed)
- **WP/IK detail charts broken** — `Charts.submissionLine()` now accepts a custom metrics array; Wattpad charts correctly plot reads/votes/lists and Itaku charts plot likes/reshares
- **WP/IK missing from 5 UI components** — added Wattpad and Itaku entries to `overviewTopList`, `overviewRecentActivity`, `trendingCards`, `linkCards`, and `linkSuggestions` badge/route maps; items no longer misidentified as Inkbunny
- **Poll error logs lost** — all 9 pollers now `conn.commit()` after writing error status to poll_log; failed cycles are no longer silently rolled back
- **IB web session lock-in** — CSRF token failure no longer permanently locks the web client in a failed state; session now properly detects expiry and re-authenticates
- **IB comment truncation** — added double-quote fallback for BBCode extraction regex; comments containing apostrophes are no longer silently truncated
- **5 batch methods crash on single failure** — SqW, AO3, WP, IK, and DA `get_*_details_batch()` methods now catch per-item exceptions instead of crashing the entire batch
- **Server startup fallthrough** — main.py now exits with error code if the server fails to start within 15 seconds, instead of opening a blank native window
- **Poll interval zero spin** — poll intervals are now clamped to minimum 1 minute, preventing infinite CPU spin or crashes from zero/negative/non-numeric values
- **Telegram /notify comments** — command now toggles comment-specific setting instead of the IB master notification switch
- **Telegram /notify missing platforms** — added sqw, ao3, da, wp, ik to the notification toggle map
- **DB restore corruption** — backup restore now removes stale WAL/SHM journal files to prevent replaying old transactions against the restored database
- **SF schema incomplete** — added missing `new_watchers_found` column to `sf_poll_log` table definition
- **Update temp cleanup** — failed update downloads now clean up their temp directory instead of leaving orphaned files

---

## [1.4.1] - 2026-03-09

### Security
- **Dashboard authentication** — optional HTTP Basic Auth for server/Docker deployments (set `DASHBOARD_PASSWORD` env var)
- **Update endpoint hardened** — `/api/update/apply` now restricted to GitHub URLs only (prevents SSRF)
- **SQL injection fix** — parameterized weeks value in historical analytics query
- **Thumbnail proxy domain whitelist** — fixed substring matching bypass on IB and FA proxies (e.g. `evil-metapix.net` no longer passes)
- **Thread-safe credentials** — added mutex lock protecting credential reads/writes between web and poller threads

### Fixed
- **Poller deadlock** — all 9 pollers could permanently lock up if database connection failed at startup; restructured try/finally to guarantee lock release
- **WP/IK column name crashes** — milestones, digest, goals, and analytics now use platform-aware column mapping (Wattpad: reads/votes, Itaku: likes/reshares)
- **10 database connection leaks** — all `auth_status` endpoints now close connections in `finally` blocks
- **HTML injection in Telegram** — all titles and usernames are now HTML-escaped in notification messages across all 9 pollers
- **Poll log not committed** — "no submissions found" cycles now persist their poll log entries
- **WS/DA/WP/IK missing notifications** — notification functions were defined but never called; now wired into poll cycles
- **Telegram bot incomplete** — `/stats`, `/top`, `/poll`, `/status`, `/interval` commands now support all 9 platforms
- **table_map incomplete** — pins, goals, tags, historical analytics, groups, and links now include all 9 platforms
- **AO3 work discovery** — narrowed regex to only match works in the listing section, not sidebar/related works
- **DA cookie validation** — now checks for authenticated indicators instead of generic page words
- **IB login check** — removed overly permissive `status_code == 200` fallback
- **IB rating unlock** — response now checked for errors (prevents silent adult content filtering)
- **AO3 login detection** — changed fragile "greeting" text match to `class="greeting"` attribute check
- **SF empty CSRF** — login now fails early with clear error instead of proceeding with empty token
- **SF poll log** — `new_watchers_found` was accepted but silently dropped from SQL UPDATE
- **Rate limit constants** — AO3/DA/WP/IK/SqW clients now use config.py values instead of hardcoded local copies
- **SqW dead code** — removed unused `guest_match` variable
- **IK unused import** — removed `from urllib.parse import urlencode`
- **Frontend: compare chip IDs** — SF/SqW/AO3 now use `parseInt()` matching other platforms
- **Frontend: overview activity** — recent activity timeline now merges all 9 platforms
- **Frontend: groups dropdown** — all 9 platforms available for adding group members
- **Frontend: metric labels** — pinned submissions, growth rates, and analytics use correct platform-specific labels (reads/votes for WP, likes for IK)
- **Frontend: poll interval settings** — added UI controls for SqW/AO3/DA/WP/IK
- **Frontend: interval stacking** — auto-refresh and poll progress intervals now cleared before recreation

### Added
- **FA watcher spam protection** — 3-layer system: keyword filter, confirmation delay (must survive 2 poll cycles), profile sniff (zero-activity detection)
- **FA watcher digest mode** — `fa_watcher_notification_mode` setting: immediate, daily, or off
- **Pagination safety limits** — all client pagination loops capped at 1000 pages to prevent infinite loops
- **Async context managers** — all 9 client classes support `async with` for safe resource cleanup
- **Transport-level retries** — all HTTP clients retry on connection errors (2 retries via httpx transport)
- **Client shutdown cleanup** — atexit handlers close persistent HTTP clients on app termination
- Bullet character consistency — SF/SqW/AO3 Telegram messages now use `•` matching other platforms

---

## [1.4.0] - 2026-03-09

### Added
- **AO3 (Archive of Our Own)** platform support — dashboard, submissions, detail, compare, settings, polling, Telegram notifications
- **DeviantArt** platform support — cookie-based auth, gallery tracking, deviation stats (views, favorites, comments, downloads)
- **Wattpad** platform support — public API, story stats (reads, votes, comments, reading lists), no auth required
- **Itaku** platform support — public API, image/post tracking (likes, comments, reshares), no auth required
- Changelog file

---

## [1.3.1] - 2026-03-08

### Added
- **SquidgeWorld** platform support (full stack)
  - OTW Archive scraper with Anubis bot challenge solver
  - Login via username/password with CSRF token extraction
  - Works discovery and detail scraping (hits, kudos, comments, bookmarks, word count, chapters)
  - Individual kudos user tracking
  - Database schema, queries, poller, REST API (16 endpoints)
  - Frontend: dashboard, submissions table, detail view, compare tool, settings section
  - Overview page integration (totals, platform card, charts)
  - Poll progress bar integration
  - Telegram notifications with platform emoji
- **Headless server mode** (`server.py`) for 24/7 deployment without GUI
  - Runs pollers + dashboard on `0.0.0.0:8420`
  - Docker support with `Dockerfile` and `docker-compose.yml`
  - Environment variable credential injection
  - Graceful SIGTERM/SIGINT handling
- Docker deployment files (`.dockerignore`, `docker-compose.yml`, `Dockerfile`)
- `requirements-server.txt` for server-only dependencies
- Oracle Cloud deployment script (`deploy/setup-oracle.sh`)

---

## [1.3.0] - 2026-03-07

### Added
- **Light/dark theme toggle** with localStorage persistence
- **User-defined tags** — create colour-coded labels and assign them to submissions across platforms
- **Goals** — set metric targets (views, faves, comments) per platform or per submission, track progress with visual cards
- **Pinned submissions** — pin favourites to the top of any platform dashboard
- **Analytics page** — top fans, trending submissions, historical best periods
- **Database backup/restore** — download `.db` file or restore from upload
- **Poll progress bar** — real-time progress indicator during poll cycles
- **SoFurry** platform support (full stack)
  - Email/password + 2FA authentication
  - Gallery scraping with content type detection
  - Stats: views, likes, comments
  - Dashboard, submissions, detail, compare, settings
- `python-multipart` dependency for backup restore endpoint

---

## [1.2.0] - 2026-03-07

### Added
- **Telegram bot command handler** — two-way interaction via `/status`, `/poll`, `/stats` commands
- **Weasyl** platform support (full stack)
  - API key authentication
  - Gallery and submission stats via Weasyl REST API
  - Dashboard, submissions, detail, compare, settings
- **FurAffinity** platform support (full stack)
  - Cookie-based authentication (cookie_a, cookie_b)
  - Scraping via FAExport proxy API
  - Dashboard, submissions, detail, compare, settings
- **Cross-platform overview page** — aggregated stats, merged top lists, per-platform cards and charts
- **Submission groups** — organise submissions from any platform into named groups
- **Cross-platform links** — link the same work across platforms for combined stats
- Watcher tracking for Inkbunny and FurAffinity

---

## [1.1.1] - 2026-03-06

### Added
- Version display and update check in sidebar footer
- "Check for Updates" button in Settings page

---

## [1.1.0] - 2026-03-06

### Added
- **Comprehensive Telegram notifications**
  - Poll summaries after each cycle
  - Milestone alerts (configurable thresholds for views, faves, comments)
  - New fave/comment/watcher alerts
  - Digest reports (daily/weekly)
  - Error notifications for failed polls
- Telegram bot token and chat ID configuration in Settings

---

## [1.0.0] - 2026-03-06

### Added
- Initial release
- **Inkbunny** platform support
  - Username/password API authentication
  - Submission discovery and stats polling (views, favorites, comments)
  - Individual fave user tracking
  - Comment scraping with reply threading
- SQLite database with WAL mode for concurrent access
- FastAPI web dashboard (SPA with hash routing)
  - Dashboard with stat cards, aggregate charts, top lists, growth rates
  - Submissions table with sorting, search, and rating filters
  - Submission detail with time-series charts and date range selection
  - Compare tool (2-5 submissions side by side)
  - Settings page with credential management and preferences
- Background polling with configurable intervals
- Windows system tray integration (pystray)
- Windows toast notifications (winotify)
- PyInstaller packaging for standalone `.exe` distribution
- CSV export for submissions and snapshots
- Run-on-startup via Windows registry
- Minimize-to-tray on close
