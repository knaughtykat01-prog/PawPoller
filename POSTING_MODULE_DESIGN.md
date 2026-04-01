# PawPoller Posting Module — Technical Design

## Overview

Extends PawPoller with multi-platform story publishing and update capabilities. Reads
pre-formatted story files from the `m_x/Archives/Complete_Stories/` archive, uploads to
configured platforms, tracks remote submission IDs, and supports re-uploading after
revision passes.

**Supported platforms (Phase 1):** Inkbunny, Bluesky, Weasyl, FurAffinity, SoFurry

---

## 1. File Structure

```
PawPoller/
├── posting/
│   ├── __init__.py
│   ├── manager.py              # PostingManager — orchestrates multi-platform uploads
│   ├── scheduler.py            # Daemon thread — checks queue, executes scheduled posts
│   ├── story_reader.py         # Reads story archive: split_manifest, tags_upload, format files
│   └── platforms/
│       ├── __init__.py
│       ├── base.py             # Abstract base class for platform posters
│       ├── inkbunny.py         # IB: api_upload.php + api_editsubmission.php
│       ├── furaffinity.py      # FA: 3-step form scrape + edit page scrape
│       ├── weasyl.py           # WS: REST API POST /api/submissions/*
│       ├── sofurry.py          # SF: REST + CSRF (PUT create, POST content, POST finalize)
│       └── bluesky.py          # BSKY: AT Protocol createRecord + uploadBlob
├── database/
│   └── posting_schema.sql      # NEW — publication registry + queue + log tables
├── routes/
│   └── posting_api.py          # NEW — /api/posting/* endpoints
└── (existing files modified:)
    ├── database/db.py          # Add _POSTING_SCHEMA_PATH + load in init_db()
    ├── dashboard.py            # Add app.include_router(posting_router)
    ├── main.py                 # Add posting scheduler daemon thread
    ├── server.py               # Add posting queue check to orchestrator loop
    ├── polling/telegram_bot.py # Add /upload, /update, /queue, /posted commands
    ├── frontend/index.html     # Add Publishing nav-group in sidebar
    ├── frontend/js/app.js      # Add posting page routes
    └── frontend/js/api.js      # Add posting API methods
```

---

## 2. Database Schema

### `posting_schema.sql`

```sql
-- PawPoller Posting Module Schema
--
-- Three tables:
--   publications    — Registry of what's been posted where (the link between
--                     local story files and remote platform submission IDs)
--   posting_queue   — Pending/scheduled uploads and updates
--   posting_log     — Audit trail of all posting activity
--
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

-- ============================================================
-- PUBLICATIONS — tracks every story/chapter posted to every platform
-- ============================================================
-- This is the core table. One row per (story, chapter, platform) combination.
-- After uploading Chapter 1 of "Extra Credit" to Inkbunny, this table records
-- the Inkbunny submission_id so we can later edit/update/replace it.

CREATE TABLE IF NOT EXISTS publications (
    pub_id              INTEGER PRIMARY KEY AUTOINCREMENT,

    -- Story identification (maps to local archive)
    story_name          TEXT NOT NULL,           -- e.g. "Extra_Credit", "Hypnotic_Claim"
    chapter_index       INTEGER DEFAULT 0,       -- 0 = full story, 1+ = chapter number
    chapter_title       TEXT DEFAULT '',          -- e.g. "The Seduction", "Graduation"

    -- Platform identification
    platform            TEXT NOT NULL,            -- 'ib', 'fa', 'ws', 'sf', 'bsky'
    external_id         TEXT NOT NULL DEFAULT '', -- Platform's submission/post ID after upload
    external_url        TEXT DEFAULT '',          -- Direct URL to the posted submission

    -- What was posted (snapshot of file paths at time of posting)
    format_file         TEXT DEFAULT '',          -- Path to the format file used (relative to story folder)
    tags_used           TEXT DEFAULT '',          -- JSON array of tags sent to platform
    title_used          TEXT DEFAULT '',          -- Title as sent to platform
    description_used    TEXT DEFAULT '',          -- Description/summary as sent
    rating_used         TEXT DEFAULT '',          -- Rating value sent to platform

    -- State tracking
    status              TEXT NOT NULL DEFAULT 'draft',  -- draft, posted, failed, archived
    first_posted_at     TEXT,                    -- When initially uploaded
    last_updated_at     TEXT,                    -- When last edited/replaced on platform
    update_count        INTEGER DEFAULT 0,       -- How many times updated after initial post
    last_error          TEXT,                    -- Last error message if failed

    -- Metadata
    created_at          TEXT NOT NULL DEFAULT (datetime('now')),
    word_count          INTEGER DEFAULT 0,

    UNIQUE(story_name, chapter_index, platform)
);

CREATE INDEX IF NOT EXISTS idx_publications_story
    ON publications(story_name);

CREATE INDEX IF NOT EXISTS idx_publications_platform
    ON publications(platform);

CREATE INDEX IF NOT EXISTS idx_publications_status
    ON publications(status);


-- ============================================================
-- POSTING QUEUE — pending uploads, updates, and scheduled posts
-- ============================================================
-- Items are added here by the user (via dashboard, Telegram, or API).
-- The posting scheduler daemon picks them up and processes them.

CREATE TABLE IF NOT EXISTS posting_queue (
    queue_id            INTEGER PRIMARY KEY AUTOINCREMENT,

    -- What to post
    story_name          TEXT NOT NULL,
    chapter_index       INTEGER DEFAULT 0,       -- 0 = full story, 1+ = chapter
    platform            TEXT NOT NULL,            -- 'ib', 'fa', 'ws', 'sf', 'bsky'

    -- Action type
    action              TEXT NOT NULL DEFAULT 'post',  -- 'post' (new), 'update' (edit existing), 'replace' (swap file)

    -- Override fields (NULL = use defaults from tags_upload.txt / split_manifest)
    title_override      TEXT,
    description_override TEXT,
    tags_override       TEXT,                    -- JSON array, NULL = use tags_upload.txt
    rating_override     TEXT,
    file_path_override  TEXT,                    -- NULL = auto-resolve from story archive

    -- Scheduling
    scheduled_at        TEXT,                    -- NULL = post immediately when picked up
    priority            INTEGER DEFAULT 0,       -- Higher = processed first (0 = normal)

    -- State
    status              TEXT NOT NULL DEFAULT 'pending',  -- pending, processing, completed, failed, cancelled
    attempts            INTEGER DEFAULT 0,
    max_attempts        INTEGER DEFAULT 3,
    last_error          TEXT,
    pub_id              INTEGER,                 -- FK → publications.pub_id (set after successful post)

    -- Timestamps
    created_at          TEXT NOT NULL DEFAULT (datetime('now')),
    started_at          TEXT,
    completed_at        TEXT,

    FOREIGN KEY (pub_id) REFERENCES publications(pub_id)
);

CREATE INDEX IF NOT EXISTS idx_posting_queue_status
    ON posting_queue(status, scheduled_at);

CREATE INDEX IF NOT EXISTS idx_posting_queue_story
    ON posting_queue(story_name, platform);


-- ============================================================
-- POSTING LOG — immutable audit trail
-- ============================================================
-- Every posting action (success or failure) gets logged here.
-- Unlike posting_queue which tracks current state, this is append-only history.

CREATE TABLE IF NOT EXISTS posting_log (
    log_id              INTEGER PRIMARY KEY AUTOINCREMENT,
    pub_id              INTEGER,                 -- FK → publications (NULL if post failed before creating pub)
    queue_id            INTEGER,                 -- FK → posting_queue (which queue entry triggered this)
    platform            TEXT NOT NULL,
    story_name          TEXT NOT NULL,
    chapter_index       INTEGER DEFAULT 0,
    action              TEXT NOT NULL,            -- 'post', 'update', 'replace', 'delete'
    status              TEXT NOT NULL,            -- 'success', 'failed'
    external_id         TEXT,                    -- Platform submission ID (on success)
    external_url        TEXT,                    -- URL (on success)
    error_message       TEXT,                    -- Error detail (on failure)
    duration_seconds    REAL,
    created_at          TEXT NOT NULL DEFAULT (datetime('now')),

    FOREIGN KEY (pub_id) REFERENCES publications(pub_id),
    FOREIGN KEY (queue_id) REFERENCES posting_queue(queue_id)
);

CREATE INDEX IF NOT EXISTS idx_posting_log_pub
    ON posting_log(pub_id);

CREATE INDEX IF NOT EXISTS idx_posting_log_created
    ON posting_log(created_at);
```

---

## 3. Story Reader (`posting/story_reader.py`)

Reads from the `m_x/Archives/Complete_Stories/` archive structure. This module
bridges the gap between local story files and what the posting system needs.

### Responsibilities

1. **Resolve story folder** — given a story name, find its folder
2. **Read split_manifest.json** — chapter count, titles, word counts, file paths
3. **Read tags_upload.txt** — parse per-platform tags (SoFurry, Inkbunny, Wattpad sections)
4. **Select format file** — pick the right file for each platform:

| Platform | Format File Location | Fallback |
|---|---|---|
| Inkbunny | `Chapters/BBCode/Chapter_N_*.txt` or `BBCode/*_bbcode.txt` | — |
| FurAffinity | `PDF/Chapter_N_*.pdf` or generate from styled HTML | Styled HTML → PDF |
| Weasyl | `Chapters/BBCode/Chapter_N_*.txt` (Weasyl accepts BBCode-ish) | Markdown |
| SoFurry | `Chapters/SoFurry_HTML/Chapter_N_*.html` or `HTML/*_Clean.html` | — |
| Bluesky | Extract first ~280 chars from MASTER.md as announcement | — |

5. **Read description** — from tags_upload.txt DESCRIPTION or per-chapter DESCRIPTION sections
6. **Read metadata** — rating, category mappings per platform

### Key Data Structure

```python
@dataclass
class StoryUploadPackage:
    """Everything needed to post one chapter/story to one platform."""
    story_name: str
    chapter_index: int          # 0 = full story
    chapter_title: str
    platform: str               # 'ib', 'fa', 'ws', 'sf', 'bsky'
    title: str                  # Formatted title for this platform
    description: str            # Platform-appropriate description
    tags: list[str]             # Platform-formatted tag list
    rating: str                 # Platform-specific rating value
    file_path: str | None       # Absolute path to format file (None for text-only platforms)
    file_type: str              # 'bbcode', 'pdf', 'html', 'text'
    word_count: int
    thumbnail_path: str | None  # Cover image if available
    extra: dict                 # Platform-specific fields (FA: category, species, gender, etc.)
```

### Tag Parsing from tags_upload.txt

The file has distinct sections per platform. Parser extracts:

```
TAGS (97):                          → SoFurry comma-separated tags
hypnosis, mind_control, ...

INKBUNNY TAGS (Categorized):        → Inkbunny tags (flatten all categories)
Sex/Gender:
male, female, mf, ...
Species:
tiger, ...
Themes/Kinks:
hypnosis, ...

WATTPAD TAGS (25 max):              → Wattpad tags
hypnosis mindControl ...
```

For per-chapter stories, each `PART N OF M` section has its own tag lists.

---

## 4. Platform Posting Flows

### 4.1 Abstract Base (`posting/platforms/base.py`)

```python
class PlatformPoster(ABC):
    """Base class for all platform posting implementations."""

    platform_id: str            # 'ib', 'fa', 'ws', 'sf', 'bsky'
    platform_name: str          # 'Inkbunny', 'FurAffinity', etc.
    supports_edit: bool         # Can metadata be edited after posting?
    supports_file_replace: bool # Can the file be swapped after posting?
    min_post_interval: int      # Minimum seconds between consecutive posts
    max_file_size: int          # Bytes
    accepted_file_types: list[str]

    @abstractmethod
    async def post(self, package: StoryUploadPackage) -> PostResult: ...

    @abstractmethod
    async def edit(self, external_id: str, package: StoryUploadPackage) -> PostResult: ...

    @abstractmethod
    async def replace_file(self, external_id: str, file_path: str) -> PostResult: ...

    @abstractmethod
    async def validate(self, package: StoryUploadPackage) -> list[str]: ...
    # Returns list of validation errors (empty = OK)
```

```python
@dataclass
class PostResult:
    success: bool
    external_id: str            # Platform's submission ID
    external_url: str           # Direct URL
    error: str | None
    duration_seconds: float
```

### 4.2 Inkbunny (`posting/platforms/inkbunny.py`)

**Uses:** Existing `api_client/client.py` (SID auth already working)

**Post flow:**
```
1. ensure_session(sid)                              — reuse existing SID
2. POST api_upload.php                              — multipart: sid, uploadedfile[0], submission_type
   → returns submission_id
3. POST api_editsubmission.php                      — multipart: sid, submission_id, title, desc,
                                                      keywords (comma-sep), type, tag[2-5] (ratings),
                                                      visibility=yes
   → returns success
```

**Edit flow:**
```
1. POST api_editsubmission.php                      — same as step 3 above, with existing submission_id
   → can update title, description, tags, rating, visibility
```

**File replace:**
```
1. POST api_upload.php                              — with submission_id + new file
   → replaces/adds pages to existing submission
```

**Config:**
- `submission_type`: `"4"` (literary/writing)
- Rating mapping: General→tag[2]=no, Mature→tag[2]=yes, Adult→tag[4]=yes+tag[5]=yes
- Max file: 200 MB
- Max tags: no hard limit, comma-separated
- Min tags: 4
- Tag format: underscores for spaces

### 4.3 FurAffinity (`posting/platforms/furaffinity.py`)

**Uses:** Existing `fa_client/client.py` (`_fa_http` with cookies a+b)

**Post flow (3-step form scrape):**
```
1. GET /submit/                                     — scrape hidden input name="key"
   → check for CAPTCHA error (need 11+ posts)
2. POST /submit/upload                              — multipart: key, submission_type="story",
                                                      submission=[PDF file], thumbnail=[image or ""]
   → scrape new key from response form
3. POST /submit/finalize                            — urlencoded: key, title (max 60), message (BBCode),
                                                      keywords (space-sep), rating (0/1/2),
                                                      cat="13" (story), atype, species, gender
   → check for "?upload-successful" in redirect URL
```

**Edit flow (edit page scrape):**
```
1. GET /controls/submissions/changesubmission/{id}/ — scrape form with current values + key
2. POST back to same URL                            — urlencoded: key + updated fields
```

**File replace:**
```
Same as edit — the changesubmission form includes a file field for replacing the PDF.
```

**Config:**
- `submission_type`: `"story"` → auto-sets `cat="13"`
- Rating mapping: General→0, Mature→2, Adult→1 (note: Adult=1, not 2)
- Max file: 10 MB
- Accepted: pdf, doc, docx, rtf, txt, odt
- Min tags: 3, max tag string: 500 chars, space-separated
- Tag format: underscores for spaces in multi-word tags
- **70-second minimum between consecutive posts**
- Title max: 60 characters

### 4.4 Weasyl (`posting/platforms/weasyl.py`)

**Uses:** Existing `weasyl_client/client.py` (API key in header)

**Post flow:**
```
1. POST /submit/literary                            — multipart: title, rating (10/30/40),
                                                      content (HTML description),
                                                      tags (space-sep), submitfile, thumbfile,
                                                      folderid, subtype, nonotification
   → returns submission URL or manage_thumbnail redirect
2. (optional) POST /manage/thumbnail                — if step 1 indicates thumbnail processing
```

**Edit flow:**
```
Weasyl API likely supports PUT/PATCH to /api/submissions/{id} — needs confirmation.
Fallback: scrape the web edit form at /edit/{id}.
```

**Config:**
- Rating mapping: General→10, Mature→30, Adult→40
- Max file: 10 MB (text), 50 MB (images)
- Accepted: pdf, md, txt
- Min tags: 2, space-separated
- Description: HTML with <p>→<div> conversion

### 4.5 SoFurry (`posting/platforms/sofurry.py`)

**Uses:** Existing `sf_client/client.py` (session cookies + CSRF)

**Post flow (REST API, 3-step):**
```
1. PUT /ui/submission                               — JSON: {} (empty body, CSRF in header)
   → returns { id: submission_id }
2. POST /ui/submission/{id}/content                  — multipart: file upload, CSRF + origin headers
   (optional) POST /ui/submission/{id}/thumbnail     — multipart: thumbnail image
3. POST /ui/submission/{id}                          — JSON: title, description (plaintext), category,
                                                      type, rating (0/10/20), privacy, allowComments,
                                                      artistTags, contentOrder
   → publishes the submission
```

**Edit flow:**
```
POST /ui/submission/{id}                             — same as step 3, updates metadata
POST /ui/submission/{id}/content                     — replaces content file
```

**Config:**
- Category: 20 (story)
- Type: 21 (short story) or 22 (book/novel)
- Rating mapping: General→0, Mature→10, Adult→20
- Max file: 512 KB (!) — very small, text-only is fine
- Description: plaintext only
- Tags: underscores replaced with spaces, min 2
- CSRF token required on every request

### 4.6 Bluesky (`posting/platforms/bluesky.py`)

**Uses:** Existing `bsky_client/client.py` (JWT with auto-refresh)

**Post flow (announcement posts, not full stories):**
```
1. (optional) POST com.atproto.repo.uploadBlob       — upload cover image
   → returns blob ref
2. POST com.atproto.repo.createRecord                 — JSON: collection="app.bsky.feed.post",
                                                        record={ text, createdAt, facets (links),
                                                        embed: { images: [blob] }, labels }
   → returns { uri, cid }
```

**Edit flow:**
```
Bluesky has no in-place edit. Options:
- Delete + repost (loses engagement)
- Leave as-is (announcements don't need updating)
```

**Config:**
- Max text: 300 graphemes (not characters — emoji count differently)
- Max images: 4 per post, 1 MB each, resized to 2000x2000
- Labels: sexual, nudity, porn (self-labelling for NSFW)
- No title field — text only
- Use case: announcement post with link to IB/FA/SF submission, not the story itself

---

## 5. Posting Manager (`posting/manager.py`)

Orchestrates the full posting flow:

```python
class PostingManager:
    """Coordinates multi-platform posting from the story archive."""

    async def post_story(self, story_name: str, platforms: list[str],
                         chapters: list[int] | None = None) -> list[PostResult]:
        """
        Post a story to multiple platforms.

        Args:
            story_name: Story folder name (e.g. "Extra_Credit")
            platforms: List of platform IDs (e.g. ["ib", "fa", "sf"])
            chapters: Specific chapters to post (None = all chapters).
                      [0] = full story file, [1,2,3] = specific chapters.

        Flow:
        1. story_reader.load_story(story_name) → story metadata + manifest
        2. For each (chapter, platform) combination:
           a. story_reader.build_package(story, chapter, platform) → StoryUploadPackage
           b. poster.validate(package) → check file exists, size OK, tags sufficient
           c. poster.post(package) → upload to platform
           d. Record in publications table (external_id, URL, etc.)
           e. Log in posting_log
        3. Respect per-platform rate limits (FA: 70s between posts)
        4. Return results
        """

    async def update_story(self, story_name: str, platforms: list[str] | None = None,
                           chapters: list[int] | None = None) -> list[PostResult]:
        """
        Update already-posted submissions after a revision pass.

        Flow:
        1. Look up publications for this story (filter by platform/chapter if specified)
        2. For each publication with status='posted' and a valid external_id:
           a. Build fresh StoryUploadPackage from current archive files
           b. poster.edit(external_id, package) → push updated metadata
           c. If file changed: poster.replace_file(external_id, new_file)
           d. Update publications table (last_updated_at, update_count++)
           e. Log in posting_log
        """

    async def queue_post(self, story_name: str, platforms: list[str],
                         chapters: list[int] | None = None,
                         scheduled_at: str | None = None) -> list[int]:
        """Add items to the posting_queue for later processing."""

    async def queue_update(self, story_name: str, platforms: list[str] | None = None,
                           chapters: list[int] | None = None) -> list[int]:
        """Queue update operations for already-posted stories."""
```

### Rate Limiting Strategy

```python
PLATFORM_POST_INTERVALS = {
    'ib':   5,     # 5 seconds between IB API calls
    'fa':   70,    # 70 seconds — FA enforces this
    'ws':   5,     # 5 seconds
    'sf':   5,     # 5 seconds
    'bsky': 3,     # 3 seconds
}
```

For multi-chapter stories, chapters are posted sequentially per platform with the
interval between each. Cross-platform posting can be parallelised (post Ch1 to IB
while posting Ch1 to SF simultaneously).

---

## 6. Posting Scheduler (`posting/scheduler.py`)

Daemon thread that processes the posting queue.

```python
def _start_posting_scheduler():
    """Daemon thread: check posting_queue every 60 seconds."""
    import asyncio

    async def _run():
        manager = PostingManager()
        while True:
            settings = config.get_settings()
            if not settings.get("posting_enabled", False):
                await asyncio.sleep(60)
                continue

            # Pick next queue item: pending, not scheduled in future, ordered by priority then created_at
            conn = get_connection()
            try:
                row = conn.execute("""
                    SELECT * FROM posting_queue
                    WHERE status = 'pending'
                      AND (scheduled_at IS NULL OR scheduled_at <= datetime('now'))
                    ORDER BY priority DESC, created_at ASC
                    LIMIT 1
                """).fetchone()
            finally:
                conn.close()

            if row:
                await _process_queue_item(manager, row)
            else:
                await asyncio.sleep(60)  # Nothing to do, check again in 60s

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(_run())
    except Exception as e:
        logger.debug("Posting scheduler thread exiting: %s", e)
```

---

## 7. REST API Endpoints (`routes/posting_api.py`)

```
POST   /api/posting/post                    — Immediate post (story_name, platforms, chapters)
POST   /api/posting/update                  — Immediate update (story_name, platforms, chapters)
POST   /api/posting/queue                   — Add to queue (with optional scheduled_at)
GET    /api/posting/queue                   — List pending queue items
DELETE /api/posting/queue/{id}              — Cancel queued item
GET    /api/posting/publications            — List all publications (filterable by story/platform)
GET    /api/posting/publications/{pub_id}   — Single publication detail
GET    /api/posting/log                     — Posting audit log
GET    /api/posting/stories                 — List available stories from archive (reads folder names)
GET    /api/posting/stories/{name}          — Story detail (manifest + available formats + tags)
GET    /api/posting/stories/{name}/preview  — Preview what would be posted per platform
POST   /api/posting/settings                — Save posting preferences
GET    /api/posting/settings                — Get posting preferences
```

---

## 8. Telegram Bot Commands

```
/upload <story> [platforms]          — Post story to platforms (default: all configured)
                                       e.g. /upload Extra_Credit ib,fa,sf
                                       e.g. /upload Hypnotic_Claim          (all platforms)

/update <story> [platforms] [ch#]    — Push updates to already-posted submissions
                                       e.g. /update Extra_Credit            (all platforms, all chapters)
                                       e.g. /update Extra_Credit fa         (just FA)
                                       e.g. /update Extra_Credit ib ch3     (just Ch3 on IB)

/queue                               — Show pending queue items
/queue cancel <id>                   — Cancel a queued item

/posted [story]                      — Show publication registry
                                       e.g. /posted                         (summary of all)
                                       e.g. /posted Extra_Credit            (detail for one story)

/stories                             — List available stories in archive
```

### Example Telegram Interaction

```
User:  /upload Hypnotic_Claim ib,sf
Bot:   📤 Uploading Hypnotic Claim to Inkbunny, SoFurry...
       Chapters: 2 (The Seduction, The Claim)

       🐾 Inkbunny Ch1 "The Seduction" — posted ✅ (ID: 12345)
       🐾 Inkbunny Ch2 "The Claim" — posted ✅ (ID: 12346)
       🐺 SoFurry Ch1 "The Seduction" — posted ✅ (ID: 67890)
       🐺 SoFurry Ch2 "The Claim" — posted ✅ (ID: 67891)

       ✅ 4/4 uploads complete in 24s

User:  /posted Hypnotic_Claim
Bot:   📋 Hypnotic Claim — Publications
       🐾 IB  Ch1 #12345  posted 2026-04-01  0 updates
       🐾 IB  Ch2 #12346  posted 2026-04-01  0 updates
       🐺 SF  Ch1 #67890  posted 2026-04-01  0 updates
       🐺 SF  Ch2 #67891  posted 2026-04-01  0 updates

User:  /update Hypnotic_Claim
Bot:   🔄 Updating Hypnotic Claim on all platforms...
       🐾 IB Ch1 #12345 — updated ✅ (tags + description)
       🐾 IB Ch2 #12346 — updated ✅ (tags + description)
       🐺 SF Ch1 #67890 — updated ✅ (description + file replaced)
       🐺 SF Ch2 #67891 — updated ✅ (description + file replaced)
```

---

## 9. Frontend Pages

### Navigation (sidebar)

```html
<li class="nav-group">
    <div class="nav-section" data-nav-toggle>Publishing <span class="nav-chevron">&#8250;</span></div>
    <ul class="nav-group-links">
        <li><a href="#/posting" class="nav-link" data-page="posting">
            <span class="nav-icon">📤</span><span class="nav-label">Upload</span>
        </a></li>
        <li><a href="#/posting/queue" class="nav-link" data-page="posting-queue">
            <span class="nav-icon">⏳</span><span class="nav-label">Queue</span>
        </a></li>
        <li><a href="#/posting/published" class="nav-link" data-page="posting-published">
            <span class="nav-icon">📋</span><span class="nav-label">Published</span>
        </a></li>
        <li><a href="#/posting/log" class="nav-link" data-page="posting-log">
            <span class="nav-icon">📜</span><span class="nav-label">History</span>
        </a></li>
    </ul>
</li>
```

### Pages

1. **Upload** (`#/posting`) — Select story from dropdown, tick platforms, preview what will be posted (title, tags, description per platform), confirm and post
2. **Queue** (`#/posting/queue`) — Pending/scheduled items, cancel button, retry failed
3. **Published** (`#/posting/published`) — Registry of all posted stories with external links, update buttons
4. **History** (`#/posting/log`) — Audit trail table with filters

---

## 10. Configuration

### New settings.json keys

```json
{
    "posting_enabled": true,
    "posting_story_archive_path": "C:\\Users\\rhysc\\claude\\m_x\\Archives\\Complete_Stories",
    "posting_default_platforms": ["ib", "sf", "ws"],
    "posting_fa_category": "13",
    "posting_fa_species": "1",
    "posting_fa_gender": "0",
    "posting_fa_theme": "1",
    "posting_default_rating": "adult",
    "posting_schedule_enabled": false
}
```

### New config.py constants

```python
ALLOWED_POSTING_PLATFORMS = frozenset({"ib", "fa", "ws", "sf", "bsky"})
ALLOWED_POSTING_ACTIONS = frozenset({"post", "update", "replace"})
POSTING_RATE_LIMITS = {
    "ib": 5, "fa": 70, "ws": 5, "sf": 5, "bsky": 3
}
```

---

## 11. Integration with Existing Polling

After a story is posted via the posting module, PawPoller's existing pollers will
automatically pick up the new submissions on their next cycle and start tracking
stats. The `publications` table records the `external_id` which can be cross-referenced
with the platform-specific `submissions` tables (e.g., `submissions.submission_id` for IB).

Future enhancement: auto-link publications to the polling submissions table via
`submission_links` (cross-platform link groups already exist in the DB).

---

## 12. Implementation Order

### Phase 1: Core + Inkbunny + Bluesky
1. `posting_schema.sql` + register in `db.py`
2. `posting/story_reader.py` — archive reader
3. `posting/platforms/base.py` — abstract base
4. `posting/platforms/inkbunny.py` — post + edit (documented API)
5. `posting/platforms/bluesky.py` — post only (AT Protocol)
6. `posting/manager.py` — orchestrator
7. `routes/posting_api.py` — REST endpoints
8. Telegram commands: `/upload`, `/posted`, `/stories`
9. Basic frontend page

### Phase 2: Weasyl + SoFurry
10. `posting/platforms/weasyl.py` — post + edit
11. `posting/platforms/sofurry.py` — post + edit + file replace

### Phase 3: FurAffinity
12. `posting/platforms/furaffinity.py` — 3-step form scrape post + edit page scrape
13. PDF generation integration (if PDFs don't exist for a story)

### Phase 4: Queue + Scheduling
14. `posting/scheduler.py` — daemon thread
15. Queue management UI
16. Telegram `/queue` command
17. Scheduled posting support

### Phase 5: Polish
18. Auto-link publications to polling submissions
19. Revision detection (compare current files to what was posted)
20. Batch update command after `/story_revision_pipeline`
21. Publishing history dashboard with stats from polling data
