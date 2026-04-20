# PawPoller Public Release Roadmap

**Status:** Planning  
**Date:** 2026-04-20  
**Current version:** 2.11.0  
**Target:** GitHub public release with desktop installer

---

## Vision

PawPoller is a **story-first multi-platform publishing pipeline** for
furry fiction writers. Write in Markdown, generate every format
(BBCode, HTML, PDF, SquidgeWorld, Styled HTML), publish to 9+
platforms, and track analytics — all from one app.

Two modes:
- **Desktop-only** — local app, no server needed. Stories live in a
  folder the user picks. Polls platforms, tracks stats, publishes.
- **Server + Desktop** — current architecture. Server handles
  polling/analytics 24/7, desktop syncs and handles platforms that
  block datacenter IPs.

What makes PawPoller different from PostyBirb: PawPoller is built for
**writers**, not visual artists. Chaptered posting, per-chapter tags,
format conversion, story analytics, drift detection, work skins.
PostyBirb posts images with descriptions; PawPoller publishes novels.

---

## Phase 8: Authentication UX

*Goal: Users log into platforms without copy-pasting cookies or
editing JSON files.*

### 8a — Embedded browser login

Open a pywebview popup showing the platform's actual login page. User
logs in normally. On success, PawPoller captures cookies/tokens from
the webview session and stores them.

**Per-platform flow:**

| Platform | Login URL | What to capture | Session indicator |
|----------|-----------|-----------------|-------------------|
| Inkbunny | `/login.php` | SID cookie from redirect | `/` shows username |
| FurAffinity | `/login/` | `a` + `b` cookies | `/` shows username |
| SoFurry | `/login` | Session cookies (CSRF + remember) | Profile link visible |
| Weasyl | `/signin` | `WZL` session cookie | Profile menu visible |
| AO3 | `/users/login` | `_otwarchive_session` + `user_credentials` | "Log Out" link present |
| SquidgeWorld | `/users/login` | Same as AO3 (OTW software) | "Log Out" link present |
| DeviantArt | `/users/login` | `auth_secure` + `userinfo` cookies | User menu visible |
| Bluesky | AT Protocol `createSession` | JWT tokens | Return `did` + `handle` |

**Implementation:**
- `auth/browser_login.py` — shared webview launcher + cookie extractor
- Each platform module gets `login_via_browser()` method
- Webview monitors URL changes + cookie jar; closes on success
- Timeout after 5 minutes with "Still working?" prompt
- On success: store credentials via existing `config.save_settings()`

**Desktop-only:** pywebview popup (already a dependency).  
**Server mode:** not applicable (server uses stored creds from sync).

### 8b — Manual credential fallback

Keep the current manual entry UI as a fallback, but add:
- Platform-specific guide panels ("How to find your FA cookies")
- Screenshots showing browser dev tools → cookie extraction
- "Test credentials" button that validates without posting
- Clear success/failure feedback with retry

### 8c — Credential encryption at rest

Implement Phase 7b (already designed in `PHASE_7_DESIGN.md`):
- Desktop: DPAPI (Windows) / keyring (macOS/Linux) encryption
- `settings.vault.json` for credential fields
- Server: encrypt credential fields in Docker volume
- Migration: plaintext → encrypted on first run, transparent to user

---

## Phase 9: First-Run Experience

*Goal: New users go from download to first publish in under 10
minutes.*

### 9a — Setup wizard

On first launch (no `settings.json` or missing `setup_complete` flag):

1. **Welcome** — "PawPoller helps you publish stories to multiple
   platforms. Let's get set up."
2. **Mode selection** — Desktop-only or Server+Desktop
3. **Story folder** — file picker for the story archive directory.
   Creates the folder structure if empty.
4. **Platform login** — card grid of supported platforms. Click to
   open embedded browser login (8a). Skip any. Green checkmark on
   success.
5. **Done** — "You're ready to publish! Here's a quick tour..."
   Links to the editor, publish check, and analytics.

### 9b — New story wizard

"Create New Story" button on the story list:

1. **Title + author** — pre-fills author from settings
2. **Genre/template** — optional preset that pre-fills tags and
   rating. Templates: Romance, Adventure, Erotica, Comedy, Drama,
   Sci-Fi, Fantasy, Slice of Life. Each preset includes ~20 common
   tags + appropriate rating + warnings.
3. **Chapter count** — "How many chapters?" (can add more later)
4. **Platform selection** — which platforms to target (determines
   format generation)
5. **Creates:**
   - `story.json` with metadata pre-filled
   - `Markdown/MASTER.md` from template with example content showing
     all anchor types, section breaks, POV markers, text message
     formatting
   - `CHAPTER_STYLING.md` from default theme
   - Folder structure (`BBCode/`, `HTML/`, `PDF/`, `SquidgeWorld/`,
     `Chapters/`, `Images/`)

### 9c — In-editor guide

The template MASTER.md serves as a living tutorial:

```markdown
<!-- @title -->
# Your Story Title

<!-- @subtitle -->
*A subtitle goes here*

<!-- @byline -->
by Your Name

<!-- @warning -->
Content warnings go here

<!-- @body -->

This is where your story begins. Everything above this
anchor is "front matter" — it appears in styled formats
but not in plain BBCode uploads.

## How to use anchors

Click the anchor toolbar buttons above to insert these
automatically. [rest of guide...]
```

---

## Phase 10: Editor Enhancements

*Goal: The editor is a complete writing environment, not just a text
box with a preview pane.*

### 10a — Anchor insertion toolbar

Row of buttons above the editor that insert anchors at cursor:

| Button | Inserts | Icon |
|--------|---------|------|
| Title | `<!-- @title -->` | T |
| Subtitle | `<!-- @subtitle -->` | S |
| Body | `<!-- @body -->` | B |
| Warning | `<!-- @warning -->` | ! |
| Text Sent | `<!-- @text-sent -->...<!-- @text-end -->` | -> |
| Text Received | `<!-- @text-received -->...<!-- @text-end -->` | <- |
| Phone | `<!-- @phone -->...<!-- @phone-end -->` | phone |
| Story End | `<!-- @story-end -->` | end |
| Section Break | `---` | --- |
| Chapter | `# Chapter N: Title` | # |

### 10b — Selective format regeneration

The Regenerate button gets a dropdown:
- **All formats** (current behaviour)
- **BBCode only** (IB/WS)
- **HTML only** (SF/AO3/SQW)
- **PDF only**
- **Styled HTML only**
- **SquidgeWorld only**

Useful when you've only changed CSS and don't need to rebuild
BBCode, or when you want a quick PDF check without waiting for all
formats.

### 10c — Work skin auto-generation from CSS

When `CHAPTER_STYLING.md` is saved or theme colours change:
- Auto-generate `SquidgeWorld/Work_Skin.css` from the theme variables
- The existing `_ensure_work_skin()` on AO3/SQW already uploads this
  CSS on post — this just keeps it in sync with theme edits

### 10d — Per-platform description editor

Metadata drawer gains a "Descriptions" section with tabs:
- **Default** — used everywhere unless overridden
- **Short** (IB/SF) — 1-2 sentence blurb for listing pages
- **Summary** (AO3/SQW) — 3-5 sentences, max 1250 chars
- **Announcement** (Bluesky) — 300 chars max, hashtag style

Stored in `story.json` as `descriptions: {default, short, summary,
announcement}`. `build_package()` picks the right one per platform.

### 10e — Format preview carousel

Story detail page gets a tabbed preview:
- **Styled HTML** — rendered in iframe (current preview)
- **Clean HTML** — body HTML as AO3/SQW would show it
- **BBCode** — rendered BBCode as IB would display it
- **SoFurry HTML** — SF-specific rendering
- **PDF** — embedded PDF viewer
- **Source** — raw markdown

Each tab loads the corresponding generated file. "Not yet generated"
placeholder if the file doesn't exist.

---

## Phase 11: Image & Thumbnail Support

*Goal: Cover art and chapter thumbnails upload alongside story content.*

### 11a — Cover image upload wiring

Currently `story.json` has `images.cover` and `build_package()` sets
`package.thumbnail_path`, but only IB's poster uses it. Wire through:

| Platform | Cover upload method | Max size |
|----------|-------------------|----------|
| Inkbunny | `thumbnail_path` on `upload_submission` | 100 MB |
| FurAffinity | Separate `changethumbnail` endpoint | 10 MB |
| SoFurry | `thumbnail` field on submission create | 5 MB |
| Weasyl | `coverfile` on `submit/literary` | 50 MB |
| AO3 | Not supported (no image upload API) | — |
| SquidgeWorld | Not supported | — |
| Bluesky | `embed.images` on post | 1 MB |

### 11b — Per-chapter thumbnails

`story.json` already has `images.chapter_thumbnails`. For platforms
that post per-chapter (IB, FA):
- Each chapter gets its own thumbnail in the metadata drawer
- Drag-drop upload in the Chapter section
- Falls back to story cover if no chapter thumbnail set

### 11c — Thumbnail guide & tools

- **Spec display** — "Recommended: 400x400px, PNG or JPG, <5 MB"
- **Canva link** — "Create a cover in Canva" button opens Canva with
  a 400x400 template (deep link if possible, otherwise generic link)
- **Auto-resize** — if uploaded image exceeds platform limits, offer
  to resize automatically (Pillow is already a dependency)
- **Preview** — show the thumbnail at actual upload size in the
  metadata drawer

---

## Phase 12: Publishing UX

*Goal: Publishing is foolproof — warnings prevent mistakes, actions
link back to the editor.*

### 12a — Regeneration staleness warning

Before any publish action, check:
```
MASTER.md mtime > newest generated file mtime?
```
If yes, show a warning banner: "Story source has changed since files
were last generated. Regenerate before publishing to avoid posting
stale content." With a "Regenerate now" button inline.

### 12b — Edit button from published stories

The analytics/submissions page for each story gets an "Edit in
Editor" button that opens the story editor with that story loaded.
Simple route: `/editor?story=Extra_Credit`.

### 12c — Post scheduling

"Schedule" button alongside Post in the action panel:
- Date/time picker (defaults to user's timezone from settings)
- Creates a `scheduled_posts` entry in the DB
- Posting scheduler checks for due items each cycle
- Telegram notification when scheduled post fires
- Cancel/reschedule from the publish check matrix

### 12d — Retry queue

Failed posts go into a retry queue instead of disappearing:
- Automatic retry with exponential backoff (1min, 5min, 30min, 2hr)
- Max 3 retries before marking as "failed — manual retry required"
- Retry queue visible in the publish check detail panel
- Manual "Retry now" button

---

## Phase 13: Analytics for Desktop-Only Mode

*Goal: Desktop-only users get the same analytics as server users.*

The polling system already works in `main.py` (desktop). The only
gap is that desktop-only users currently need the server running for
the dashboard.

**Already solved:** The dashboard runs on `localhost:8420` in desktop
mode too. Desktop-only users already have analytics — they just need
the setup wizard (Phase 9a) to configure platforms.

**Nice-to-haves:**
- Offline analytics (cache last-known stats when platform is
  unreachable)
- Export analytics as charts/reports (PNG, CSV)
- Story performance comparison dashboard
- Goal tracking with visual progress bars

---

## Phase 14: Import Existing Work

*Goal: Users with existing stories on platforms can pull them into
PawPoller without manual re-entry.*

### 14a — Import from platform

"Import" button on the story list:
1. Pick platform (IB, SF, AO3, etc.)
2. PawPoller lists the user's submissions (already scraped by pollers)
3. User selects which to import
4. For each: download content, extract tags, build `story.json`,
   create folder structure
5. User reviews and edits metadata in the editor

### 14b — Import from files

"Import from folder" for users with existing `.md` / `.txt` / `.html`
files:
1. Pick folder
2. PawPoller detects chapter structure
3. Generates `story.json` template
4. User fills in metadata

---

## Phase 15: GitHub Release Packaging

*Goal: Anyone can download and run PawPoller without Python knowledge.*

### 15a — Repository cleanup

- [ ] Audit all committed files for hardcoded credentials
- [ ] `.gitignore` for `data/`, `dist/`, `build/`, `*.pyc`, `.env`
- [ ] `.env.example` with placeholder values
- [ ] `LICENSE` (MIT recommended — permissive, matches PostyBirb)
- [ ] `CONTRIBUTING.md` — how to add a new platform module

### 15b — README

- Banner image / logo
- Feature list with screenshots
- Installation: download `.exe` (Windows), `pip install` (dev)
- Quick start: 5-step guide matching the setup wizard
- Platform support matrix (which platforms, what features)
- Architecture overview for contributors
- Comparison with PostyBirb (why PawPoller for writers)

### 15c — GitHub Actions CI/CD

- **Build:** PyInstaller → Windows `.exe` on every release tag
- **Test:** Run `tests/test_posting_helpers.py` on every push
- **Release:** Auto-create GitHub Release with `.exe` + changelog
- **Linting:** pyflakes / ruff on PR

### 15d — Auto-update

- On startup, check GitHub API for latest release tag
- Compare with `APP_VERSION`
- If newer: show notification in sidebar (already partially built)
- "Download update" opens the GitHub releases page
- Future: in-place update (download `.exe`, replace, restart)

---

## Implementation Priority

### Must-have for public beta

1. **Setup wizard** (9a) — first impression
2. **Embedded browser login** (8a) — replaces the hardest step
3. **Manual login fallback** (8b) — safety net
4. **Credential encryption** (8c) — non-negotiable for public release
5. **New story wizard** (9b) — empty app is intimidating
6. **Cover image upload** (11a) — expected feature
7. **Regen staleness warning** (12a) — prevents silent mistakes
8. **GitHub packaging** (15a-c) — distribution mechanism

### Should-have for v1.0

9. Anchor toolbar (10a)
10. Per-chapter thumbnails (11b)
11. Edit from published stories (12b)
12. Format preview carousel (10e)
13. Retry queue (12d)
14. Session expiry recovery
15. Auto-update (15d)

### Nice-to-have for v1.x

16. Post scheduling (12c)
17. Per-platform descriptions (10d)
18. Import from platforms (14a)
19. Selective regen (10b)
20. Story templates (9b genre presets)
21. Thumbnail auto-resize (11c)
22. Work skin auto-gen (10c)
23. Analytics export

---

## Technical Decisions Needed

1. **Electron vs pywebview** — pywebview is lighter and already a
   dependency, but Electron gives better cross-platform webview
   consistency. PostyBirb uses Electron. Recommendation: stay with
   pywebview unless browser login requires Chromium-level cookie access.

2. **Plugin system** — should platforms be pluggable (add new platform
   without touching core)? PostyBirb does this. Current PawPoller has
   a consistent pattern per platform but it's not a formal plugin API.
   Recommendation: formalize the pattern (base class + registry) but
   don't build a dynamic plugin loader yet.

3. **Story format** — MASTER.md with anchors works well but is
   PawPoller-specific. Should we support import from other formats
   (Google Docs, Scrivener, .docx)? Recommendation: Markdown-first,
   add .docx import later via `python-docx`.

4. **Database** — SQLite works great for single-user. For server mode
   with multiple users (future?), would need PostgreSQL or similar.
   Recommendation: keep SQLite, don't over-architect for multi-tenant
   yet.

5. **Naming** — "PawPoller" emphasizes polling/analytics. For a
   publishing tool, something like "PawPress" or "FurPublish" might
   communicate the value better. Or keep PawPoller — it's already
   established.
