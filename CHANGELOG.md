# PawPoller Changelog

All notable changes to PawPoller are documented here.

---

## [2.10.2] - 2026-04-17

### Added — Unit tests, CF Worker hostname allowlist, docs refresh

Low-risk polish pass while the user was away from keyboard. No
runtime behaviour changes to the posting paths themselves — this
release locks in the 2.10.x helpers with tests, hardens the CF
proxy, and brings the reference docs back in sync with the code.

**Unit tests (`tests/test_posting_helpers.py`)**
- 30 tests, all passing, runnable via
  `python -m unittest tests.test_posting_helpers` from the PawPoller
  root. Plain stdlib `unittest`, no pytest dependency.
- Covers `posting.manager._looks_like_deletion` — deletion pattern
  matcher with explicit false-positive guards (`File not found on
  disk`, `model not found in cache`, etc. that the old `not found`
  catch-all would have matched).
- Covers `_strip_chapter_prefix` on both AO3 and SQW posters, with
  a divergence-check test that asserts the two verbatim-copied
  helpers produce identical output for identical input.
- Covers `_extract_work_form_fields` on both AO3 and SQW clients,
  with a hand-built OTW-style form fixture exercising text inputs,
  checkboxes (checked vs unchecked), selects (selected option),
  textareas, submit skipping, auth_token skipping, and HTML entity
  decoding. Also asserts AO3 and SQW helpers produce identical
  output for identical input.

**CF Worker hostname allowlist (`deploy/cf-worker.js`)**
- New `ALLOWED_HOSTS` set — only `sofurry.com`, `deviantart.com`,
  `archiveofourown.org`, `squidgeworld.org`, `furaffinity.net` (+ `www.`
  variants). Requests to anything else return
  `403 Target host not on allowlist: <host>`. Chain URLs validated
  against the same list so they can't bypass.
- Closes the open-proxy risk if `PROXY_SECRET` ever leaks: an
  attacker with the secret can only hit platforms we already route
  through, not arbitrary SSRF targets.
- **Requires manual redeploy via wrangler or the CF dashboard** —
  the Worker doesn't auto-deploy from git.

**`documentation_guide.md` refresh**
- Section 14 (AO3 poster) rewritten to reflect reality: chaptered
  posting via `create_work + create_chapter` loop, work skin
  CRUD, safe fetch-form overlay edit pattern, `content=None`
  preservation in `edit_chapter`, `skip_content_refresh` mode,
  `probe_exists` deletion detection, email-login account-name
  resolution. Removed the "Known limitations" block that falsely
  claimed AO3 had no chaptered / no work skin / chapter-1-only-edit.
- Section 15 (Story Editor) extended with three new subsections:
  Publish Check Matrix, Publish Action Panel, Theme-Save Trailing
  Content. Cell states documented, work-oriented vs per-chapter
  distinction explained, confirm_live guard noted.
- Section 10 (CF Worker) gained the hostname allowlist description.

**`PHASE_6D_PLAN.md` added**
- Design doc for bulk publish actions (Publish row, Publish all new,
  Update all drifted). Recommended path: frontend-orchestrated loop
  over existing `/publish` endpoint, no backend changes, no
  server-side state. AbortController-based cancellation. ~1 day
  complexity, all changes within `publish_check.js` + `editor.css`.

**Pyflakes-flagged dead imports removed**
- `asyncio`, `PostResult`, `StoryUploadPackage` from
  `posting/manager.py`.
- `pathlib.Path` from `posting/platforms/ao3.py` and
  `posting/platforms/squidgeworld.py`.
- No behaviour change; verified all tests still pass after removal.

### Not changed this release
- 13 polling module audit findings deferred — low-risk fixes there
  require careful testing that the user will do when back at a machine.
- Weasyl / FurAffinity / DeviantArt / Itaku / Bluesky still untested
  end-to-end. FA is blocked on desktop queue flush; Weasyl is blocked
  on account verification; DA / IK / BSky are user's choice to skip.

---

## [2.10.1] - 2026-04-16

### Fixed — Bug hunt round + edit_chapter overlay + AO3 shields

After Test Story posting was verified end-to-end on IB, SF, AO3, and
SQW, ran two rounds of automated audits against the posting module,
routes, editor, and frontend JS. Plus a few things that surfaced during
testing.

**Bug hunt finds:**
- `DELETION_ERROR_PATTERNS` no longer has a generic `"not found"`
  catch-all. Scoped to phrasings that specifically refer to the
  submission/work/URL (`submission has been deleted`, `work does not
  exist`, `page does not exist`, `client error 404`). Prevents
  false-positives on unrelated `"File not found on disk"` errors.
- `/verify` endpoint: `probe_exists()` is supposed to swallow its own
  errors, but now wrapped in try/except so one bad platform can't crash
  the whole verify loop. Rate-limited to 400ms between probes.
- `routes/posting_api.py` had a duplicate `get_sync_status` function
  both registered at `GET /sync/status`. FastAPI resolves last-one-wins;
  the earlier (simpler) one became dead code. Removed.
- **Silent data loss fix**: theme-save in `routes/editor_api.py`
  computed `after_idx` (position after `<!-- THEME_VARIABLES_END -->`)
  but never used it. Any content below the end marker — user notes,
  credits, extra CSS sections — got wiped on every theme save. Now
  properly re-attaches.
- `publish_check.js` v8: `_executeAction` captures `_currentStory` into
  a local at start; success-reload guards with `_currentStory ===
  storyName`. Prevents wrong-story matrix reload if user opens Publish
  Check for Story A → clicks Post → closes → opens for Story B.
- Re-check button disables itself immediately on click to prevent
  double-fire on rapid double-click.

**edit_chapter overlay pattern (AO3):**
- Ported from sqw_client — GET edit form, extract every chapter[*]
  field, overlay only caller overrides, POST with save_button.
- `content: str | None = None` — passing None preserves body on AO3.
- Metadata-only button on AO3 now pushes chapter title changes without
  re-uploading the chapter body.

**AO3 "Shields are up!" workaround:**
- Residential IPs were getting 403 on `/users/login` even though
  GCP/datacenter IPs worked fine. Expanded `_HEADERS` to match a real
  Chrome 131: added Sec-Fetch-Dest/Mode/Site/User, Sec-Ch-Ua/Mobile/
  Platform, Upgrade-Insecure-Requests, Priority.
- Login now warms up the session by GETting the homepage first, then
  navigates to `/users/login` with Referer + Sec-Fetch-Site:
  same-origin — mimics a real browser navigation instead of a cold
  direct-hit.

**Version bump:**
- `config.py APP_VERSION` bumped from `1.5.0` to `2.10.0`. Had been
  stale for months — every release was tracked in CHANGELOG.md but
  the in-app constant stayed behind. This is what the desktop tray
  tooltip shows, so the desktop was silently advertising year-old
  vintage even with current code.

---

## [2.10.0] - 2026-04-16

### Added — AO3 parity pass (chaptered posting, work skins, edit fidelity)

Large bundle of AO3 improvements driven by end-to-end testing of
chaptered story publishing on AO3 drafts. Chaptered stories now post
to AO3 the same way they post to SquidgeWorld: one work with N chapters
via `create_work` + `create_chapter` loop. Metadata edits push every
field instead of silently dropping the submission.

**Work skins on AO3 (mirroring SQW, same OTW Archive software):**
- `ao3_client.find_work_skin_by_title`, `create_work_skin`,
  `get_or_create_work_skin`, `edit_work_skin` — full CRUD on
  `/skins/{id}` via `skin_type=WorkSkin`.
- `edit_work` gains a `work_skin_id` kwarg so the assigned skin can
  be updated alongside other metadata.
- `AO3Poster._ensure_work_skin()` — finds or creates the per-story
  "<Story> Skin" on every post/edit, auto-refreshing the CSS from
  `SquidgeWorld/Work_Skin.css` so local edits propagate. Leading
  underscores on story folder names (`_Test_Story`) are stripped so
  the skin title is `Test Story Skin` rather than `_Test Story Skin`.

**Chaptered posting:**
- `ao3_client.create_chapter` — ported from SqW. POST to
  `/works/{id}/chapters/new` with `preview_button=Preview` so a
  draft work stays a draft while the chapter is added.
- `AO3Poster.post()` detects multi-chapter stories via
  `story.total_chapters > 1`. Multi-chapter → `create_work` with
  ch1 content, then iterate ch2..N via `create_chapter`. Single
  chapter → previous behaviour (full-story Clean HTML as one chapter).
- `AO3Poster.edit()` iterates AO3's existing chapters via
  `get_chapter_ids()`, edits each from the matching SquidgeWorld
  chapter HTML, appends any local chapters missing upstream.
- `_read_chapter_content(story, idx)` resolves
  `SquidgeWorld/Chapter_<idx>_*.html` with a prefer-exact-match
  glob (avoids picking up debris files).

**`edit_work` safe-overlay pattern (critical bug fix):**
Earlier builds sent `_method=patch` with only 5 `work[*]` fields
and no commit button. AO3 returned 302 but never persisted the
changes — a silent no-op. `edit_work` now:
1. GETs `/works/{id}/edit` and extracts every current `work[*]`
   field via `_extract_work_form_fields`.
2. Overlays only the caller-supplied overrides (title, summary,
   additional_tags, warnings, categories, relationship, characters,
   fandom, rating, work_skin_id).
3. `_append_if_missing()` any scalar override whose field name isn't
   in the form (defensive net against OTW rendering fields differently
   between new-work and edit forms).
4. POSTs the full form back with `save_button=Save As Draft`
   (or `post_button=Post` when `save_as_draft=False`).
5. Parses flash messages and logs notice/error/caution/warning
   classes at INFO so canonicalisation notices and validation errors
   surface in logs.

**Safety fixes:**
- Login with email instead of account name resolves via the login
  redirect URL so every `/users/{name}/...` call hits the right
  page. Fixes SQW SAFETY ABORT after `create_work` (draft-state
  check was hitting `/users/<email>/works/drafts` → 404 → treated
  as missing → work deleted). Same fix in AO3 client.
- `probe_exists()` added for AO3 + SQW. `/works/{id}/edit` 404 means
  deleted, 2xx means live, transient errors return None so we don't
  misflag live works.

**Matrix work-oriented flip:**
- Removed `PER_CHAPTER_ONLY = {"sqw"}` (had semantics inverted).
  Replaced with `WORK_ORIENTED = {"ao3", "sqw"}`. For chaptered
  stories on these platforms, per-chapter rows show grey `–` N/A
  with the hint to use the Full story row. The full-story row is
  the actionable one — internally handles multi-chapter creation.

**`Metadata only` update action:**
- New cell button next to `Update all`. Sends `skip_content_refresh`
  through `package.extra`. Short-circuits the chapter-refresh / file
  re-upload loop on IB, SF, FA, AO3, SQW (WS was metadata-only by
  API constraint). Faster edits when only tags/title/summary changed.
- `manager.update_story()` gains an `extras: dict` kwarg (mirrors
  `post_story`).
- Existing action renamed `Update existing` → `Update all` for
  clarity.

**Upstream deletion detection:**
- `PlatformPoster.probe_exists(external_id) -> bool | None` — new
  abstract method. SF / IB / AO3 / SQW implemented; others return
  None (not probed).
- `POST /api/editor/stories/{name}/verify` endpoint — walks every
  `posted` publication, probes each poster, flips confirmed deletions
  to `status='deleted'` in the registry. Matrix then renders those
  cells as red ⊘ with a `Re-post to <platform>` primary button.
- `manager.update_story()` catches deletion error strings (IB, FA,
  AO3) and flips the registry row to `deleted` instead of auto-queuing
  for desktop (which would hit the same wall).

**Content-refresh parity:**
- SF `edit()` now calls `replace_file()` alongside `edit_submission()`
  — previously metadata-only. FA `edit()` likewise calls
  `replace_file()` (changestory endpoint). WS explicitly documents
  the API limitation + returns a soft warning so the UI can surface
  `delete + repost required`.
- IB `edit()` skips BBCode read when `skip_content_refresh` is set.

**Tag cascade fix (editor UI):**
- `TAG_CASCADE_PLATFORMS` replaces the old `TAG_PLATFORMS` cascade
  target. Default tab now propagates added/removed tags to SF, IB,
  WP, **plus** AO3, SQW, WS, FA, DA, IK (everyone with a poster
  except Bluesky, which uses hashtag-style tags). Previously only
  the first three were synced, so AO3/SQW/etc. would keep stale
  tag lists and silently ignore updates.
- `_transformTagForPlatform` branch added for Itaku (underscores
  like default).

**Chapter title de-duplication (OTW display):**
- AO3 and SQW both render chapters as `Chapter N: <title>`. Passing
  `chapter_title="Chapter 1: The Counter"` ended up rendering as
  `Chapter 1: Chapter 1: The Counter`. Both posters now strip the
  leading `Chapter N:` / `Part N:` / `Prelude:` / `Epilogue:`
  prefix from chapter titles before `create_work` / `create_chapter`
  / `edit_chapter` calls.

**Cache busters:** `metadata_editor.js?v=14`, `publish_check.js?v=7`.

---

## [2.9.4] - 2026-04-15

### Added — Content drift detection in the Publish Check matrix

When you regenerate a story after posting, the matrix now flags
any (chapter × platform) cell whose local file has changed since the
last successful upload. The cell flips to a violet `↑` "Drifted"
state, and the detail panel shows a banner: *"Local content has
changed since this was posted. Hit Update existing to push the fresh
file."* — with the Update button promoted to primary so it's hard to
miss.

This fixes the silent failure mode where you edit MASTER.md, post
without regenerating, then later regenerate and forget the platform
copies are now out of date.

**Backend (`routes/editor_api.py`):**
- `/publish-check` now imports `posting.sync.hash_file`. For each
  cell whose `existing.status == 'posted'` and which has a file
  path, it hashes the current local file and compares to the
  `publications.file_hash` recorded at post time. Mismatch →
  `posted_drifted` cell status; the existing.drifted flag and
  the stored hash are surfaced to the UI.
- Tag-only platforms (Bsky, Itaku) store an empty file_hash on
  post and are skipped by the drift check.

**Frontend (`frontend/js/publish_check.js`):**
- New `posted_drifted` cell state — icon `↑`, violet colour.
- Stats line gains a "X drifted" counter (only shown when > 0).
- Action panel detects drift and:
  - Renders a violet banner explaining the drift.
  - Promotes Update to btn-primary with an extra "(push fresh
    content)" hint, so the right action is the obvious one.
- Footer legend updated.

**Frontend (`frontend/css/editor.css`):**
- `.cell-posted-drifted`, `.publish-action-drift-banner`,
  `.stat-drifted` styles.

**Cache buster:** `publish_check.js?v=4`.

---

## [2.9.3] - 2026-04-15

### Added — Full-story row in the Publish Check matrix

For chaptered stories the matrix previously only showed per-chapter
rows. You now get a "Full story" row at the top so you can choose to
post the whole work as one submission OR split into per-chapter
submissions. Some platforms suit one mode (FA chaptered for size,
SQW per-chapter only); others (SF, IB, AO3, WS) work either way.

The full row gets a heavier border + bold label so it's visually
distinct from chapter rows.

**Backend (`routes/editor_api.py`):**
- `chapters` array now always starts with `{"index": 0, "kind": "full"}`
  followed by per-chapter rows (if any). Single-chapter stories still
  show only the full-story row.
- New `PER_CHAPTER_ONLY = {"sqw"}` set — these platforms get a
  dedicated `not_supported` cell on the full-story row with a clear
  "use a chapter row" hint.
- New cell status `not_supported` (icon `–`, label "N/A —
  per-chapter only").

**Backend (`posting/story_reader.py`):**
- `_parse_story_json()` now cascades `default` tags to every poster
  ID that wasn't given an explicit list — at both the story level and
  the per-chapter level. Fixes the bug where DA / IK / BSky returned
  0 tags for the full-story package even when `default` had plenty.
- Platform name map extended with `deviantart→da`, `itaku→ik`,
  `bluesky→bsky` so editor-written story.json keys translate to the
  short IDs the package builder uses.

**Frontend (`frontend/js/publish_check.js`):**
- Full-story row gets `class="row-full"` + a "(<title>)" hint after
  the bold "Full story" label.
- New `cell-na` colour-block (subtle grey) for `not_supported` cells.

**Cache buster:** `publish_check.js?v=3`.

---

## [2.9.2] - 2026-04-15

### Added — Phase 6b: Publish actions (POC, all platforms via single endpoint)

The Publish Check matrix gains real action buttons. Click any cell, and
the detail panel now shows: **Dry Run** (always available — rebuilds
package + validates, returns full payload as JSON), **Post** (for
`ready` cells), **Update** (for `posted` cells where the platform
supports edit), and **Open** (for posted cells with an external URL).

Two safety layers:
- **Frontend**: `confirm()` dialog with the title, platform, and draft
  state spelled out. User must explicitly approve before any external
  HTTP fires.
- **Backend**: `confirm_live=true` is required in the request body for
  any non-dry-run action. The endpoint 400s without it — server-side
  guard if the UI is bypassed.

A "Save as draft" checkbox (default ON) sets `package.extra["draft"] =
True`, which on supported platforms (SF, SQW, AO3, etc.) creates the
submission as a draft instead of going public. Platforms that don't
support drafts ignore the flag.

**Backend (`routes/editor_api.py`):**
- `POST /api/editor/stories/{name}/publish` — body
  `{platform, chapter, action, draft, confirm_live}`. Routes to
  `manager.post_story()` or `manager.update_story()` for a single
  (platform, chapter) pair. Dry-run path skips manager entirely and
  returns the rebuilt package as JSON for inspection.

**Backend (`posting/manager.py`):**
- `post_story()` gains an `extras: dict | None` parameter. Values are
  merged into `package.extra` before posting. Update path inherits
  existing behaviour (no extras yet).

**Frontend (`frontend/js/publish_check.js`):**
- `_renderActionPanel()` produces the action buttons inside the detail
  panel based on cell state.
- `_executeAction()` handles dry-run / post / update calls, shows
  loading state, and refreshes the matrix on success.
- Result panel renders dry-run package as a `<details><pre>` JSON
  block, real posts as success/failure with external URL link.
- Matrix rows now carry `data-ch-idx` + `data-ch-title` for cell
  click → detail-panel context.

**Cache buster:** `publish_check.js?v=2`.

**Next (Phase 6c):** broaden testing to the other 8 platforms, then
6d adds bulk "Publish to all" and "Update all changed" actions.

---

## [2.9.1] - 2026-04-15

### Added — Phase 6a: Publish Check (read-only validation matrix)

Pre-flight check before the actual publish flow lands in 6b. Opens a
chapter × platform grid showing which combinations are ready, blocked,
or already posted — without making a single HTTP request to any
external platform.

**Backend (`routes/editor_api.py`):**
- `GET /api/editor/stories/{name}/publish-check` — returns
  `{ok, story_name, story_title, total_chapters, platforms[], chapters[], matrix[]}`.
- For each chapter × platform: builds the `StoryUploadPackage` via
  `story_reader.build_package()`, runs `poster.validate(package)`,
  cross-references the publications registry. No external HTTP.
- Cell statuses: `ready`, `blocked`, `posted`, `posted_stale`
  (already posted but file/tags now invalid), `ready_retry` (previous
  attempt failed, package now valid), `failed_prev` (previous attempt
  failed and still blocked), `error` (poster init or package build threw).
- `PUBLISH_PLATFORMS` constant defines display order: IB, FA, WS, SF,
  SQW, AO3, DA, IK, BSky.

**Frontend (`frontend/js/publish_check.js` — new):**
- `PublishCheck.open(storyName)` opens a full-screen modal (5vw inset,
  z-index 10010) with the matrix.
- Each cell shows a status icon (✓ / ✗ / ! / ↻ / ⚠) colour-coded by
  status. Click a cell → detail panel with package title, tag count,
  file path + size + max-size, mode requirement, edit support,
  existing publication link.
- Sticky header row (platform names) and sticky first column (chapter
  titles) so the matrix scales for stories with many chapters.
- Stats line: total combinations / posted / ready / blocked.
- "Re-check" button re-fires the endpoint without closing the modal.
- ESC and backdrop click both close.

**Frontend (`frontend/js/editor.js`):**
- New "Publish" button between Regenerate and Format, opens
  `PublishCheck.open(storyName)`.

**Frontend (`frontend/css/editor.css`):**
- Full modal styling: `.publish-check-modal`, `.publish-check-dialog`,
  `.publish-check-table`, status colour cells (`.cell-ready`,
  `.cell-posted`, `.cell-posted-stale`, `.cell-retry`,
  `.cell-blocked`, `.cell-error`), detail panel.

**Cache busters:** `editor.js?v=276`, `publish_check.js?v=1`.

---

## [2.9.0] - 2026-04-15

### Added — Native PDF generation in the editor (WeasyPrint primary, Edge fallback)

The editor's `/regenerate` endpoint previously skipped PDF generation entirely
(the `skip_pdf` flag on `RegenerateRequest` was dead — nothing read it).
PDFs only existed if a user manually ran `m_x/Scripts_Utils/regenerate_story.py`
locally with Edge installed. This blocked Phase 6 (publish buttons) for FA,
which requires per-chapter PDFs because of the 10 MB upload limit.

**New module — `editor/pdf_generator.py`:**
- `html_to_pdf(html_path, pdf_path) -> (ok, backend)` — picks the best
  available backend automatically.
- **WeasyPrint** is primary. Pure-Python HTML→PDF, no browser required.
  Renders styled HTML using the existing `style.css` next to it
  (resolved via `base_url=html_path.parent`). Works server-side in the
  GCP container, so PDFs regenerate without needing desktop mode.
- **Edge headless** is the fallback. Probes the two standard install
  paths on Windows; renders via `--print-to-pdf=...`. Used when
  WeasyPrint can't import its native libs (typical on bare Windows
  without GTK runtime).
- `get_backend()` reports which backend is currently usable
  (`weasyprint` / `edge` / `none`).

**Backend (`routes/editor_api.py`):**
- `RegenerateRequest.skip_pdf` default flipped from `True` to `False`
  (PDFs now generated by default — WeasyPrint is fast enough that the
  opt-in pattern is no longer warranted).
- New PDF block runs after the Styled HTML pass:
  - Full story → `PDF/{stem}.pdf` from `HTML/{stem}_Styled.html`.
  - Each `Chapters/Styled_HTML/Chapter_*.html` → `Chapters/PDF/Chapter_*.pdf`.
  - Tracks per-file failures in `errors[]`, total count in `results[]`.

**Dockerfile:**
- Added `apt-get install` for WeasyPrint's native deps:
  `libpango-1.0-0`, `libpangoft2-1.0-0`, `libharfbuzz0b`, `libcairo2`,
  `libgdk-pixbuf-2.0-0`, `libffi8`, `fonts-dejavu-core`. ~50 MB image growth.
  Fonts pkg ensures consistent rendering on the headless container.

**Dependencies:**
- `weasyprint>=68.0` added to `requirements.txt`.
- `weasyprint~=68.1` added to `requirements-server.txt`.

**Why not Playwright?** Bundling Chromium is ~150 MB and pixel-perfect
rendering isn't needed for these PDFs (clean text + headings + page
breaks). WeasyPrint is the right shape for the job.

**Verification:** `_Test_Story` regenerated locally — full PDF (200 KB)
+ 4 chapter PDFs (96–164 KB). On Windows it routed through the Edge
fallback (WeasyPrint missing GTK), but the server will use WeasyPrint
natively after deploy.

---

## [2.8.2] - 2026-04-15

### Added — Metadata Editor Phases 4 + 5 + 4b: Tag Browser + Per-Chapter Tags

**Phase 4 — Tag Browser modal:**
- Full-screen browser opened from "Browse all matches" button in the
  autocomplete dropdown. Shows ALL tags from the local DB filtered by
  category chips (`physical`, `acts`, `kink`, `meta`, `image`, `user`).
- Search box filters in real time. Click a tag to add it to the active
  platform with normal cross-platform propagation rules.
- Portal-mounted to `document.body` to escape `.metadata-section-body`'s
  `overflow: hidden` clipping (same fix as the autocomplete dropdown).

**Phase 5 — Section toggles + collapse memory:**
- Each metadata section header has a chevron — click to collapse.
- Expanded/collapsed state persists per-section in `localStorage`
  (`pawpoller_metadata_section_state_v1`).
- Smooth height transition; respects `prefers-reduced-motion`.

**Phase 4b — Per-chapter tag editing:**
- New `Chapter Tags` section in the metadata drawer. One sub-panel per
  chapter, each with the same tab strip + autocomplete UI as the
  story-level Tags section.
- Backend (`routes/editor_api.py`):
  - `chapter_info[i].tags[platform]` shape added to `story.json`.
  - `GET /api/editor/stories/{name}/chapters` returns the per-chapter
    tag map alongside titles/descriptions/thumbnails.
  - `PUT /api/editor/stories/{name}/chapters` upserts per-chapter tags
    atomically (write to `.tmp` → rename, with `.bak.{ts}` snapshot).
- Frontend (`frontend/js/metadata_editor.js`):
  - **NO cross-platform sync** for chapter tags (unlike story-level
    Default → SF/IB/WP cascade). Reasoning: per-chapter tags are
    typically platform-specific edits (e.g. SF "Chapter 3 of 5" vs IB
    "story-arc"), not universal labels.
  - Same e621 lookup + "+ Library" workflow available per chapter.

**Cache buster:** `metadata_editor.js?v=13`

---

## [2.8.1] - 2026-04-15

### Added — Metadata Editor Phase 3b: e621 lookup fallback + "+ Library" workflow

**Bundled e621 lookup TSV:**
- `tag_database/e621_lookup.tsv` — 26,829 tags, ~500KB. Filtered from the raw
  e621 dump (drop cat 1/2/4 + low-post + IMAGE_NOISE regex + bad-name chars).
- Generator lives at `m_x/Scripts_Utils/generate_e621_lookup.py` (not shipped —
  only the output TSV ships with the repo).

**Backend (`routes/editor_api.py`):**
- New lazy loader `_load_e621_lookup()` — parses TSV once on first lookup call.
- `GET /api/editor/tags/lookup?q=<str>&limit=<N>` — substring search against
  the e621 lookup, excluding tags already in the local DB. Ranking:
  exact > prefix > substring, post_count desc. Returns `{matches: [{name, category, post_count}]}`.
- `POST /api/editor/tags/add` — appends a tag to one of the local DB files.
  Body: `{name, target, description}`. `target` is one of
  `physical|acts|kink|meta|image|user`. Validates against
  `^[a-z0-9_/-]+$`, rejects dupes (409), invalidates the in-memory
  `_TAG_DB_CACHE` on success.
- `tag_database_user.txt` added to `_TAG_DB_FILES` with category label
  `user`. Auto-created with a header on first write.
- Curated DBs get a new `USER ADDITIONS` section appended on first
  per-file user-add, then appended-to on subsequent adds.

**Frontend (`frontend/js/metadata_editor.js`):**
- Autocomplete dropdown now appends an "e621 suggestions" block below local
  matches whenever local hits < 5 and query length >= 3.
- Debounced (300ms) fetch; session-scoped `Map` cache keyed by lowercased query.
- Each e621 row shows: name, category chip (`e621 general/species/copyright/meta/lore`),
  post count, and three actions:
  - **+ {Target}** primary button — target is derived from the e621 category
    (species → physical, general → user, copyright → meta, etc.).
  - **Caret dropdown** — choose any of the 6 library buckets explicitly.
  - **Use once** — adds the tag to the current platform without mutating
    the library (same as pressing Enter on the raw query).
- `_addTagToLibrary(name, target)` — POST to `/api/editor/tags/add`, then
  clears `sessionStorage['pawpoller_tag_db_v1']`, reloads the local tag DB,
  clears the e621 cache, and routes through `_addTagFromDropdown` so the
  tag is immediately applied with normal cross-platform propagation.
- Status toast: "Added '<name>' to <Target> library".
- Tag browser categories now include `user` (so user-added tags show up
  in the expanded browse modal's filter chips).

**Frontend (`frontend/css/editor.css`):**
- `.metadata-tag-result-divider` — section header above e621 block.
- `.metadata-tag-result-e621` — subtle violet wash to distinguish from local rows.
- `.metadata-tag-cat-e621` — violet category chip for e621 rows.
- `.metadata-tag-cat-user` — warm beige chip for user-added tags.
- `.metadata-tag-add-library-btn` — primary "+ Library" button.
- `.metadata-tag-use-once-btn` — subtle "Use once" link-style button.
- `.metadata-tag-target-menu*` — caret + dropdown for explicit target choice.

**Cache buster:** `metadata_editor.js?v=12`

---

## [2.8.0] - 2026-04-15

### Added — Metadata Editor Phase 3a: Tag Autocomplete

**Bundled tag database:**
- `data/tag_database/` shipped with the repo (5 tag files + `tag_aliases.json`, ~2MB raw / ~400KB gzipped)
- Sourced from `C:\Users\rhysc\claude\Tag_Database\`: physical, acts, kink, meta, image categories + 23K aliases
- `.gitignore` + `.dockerignore` carve-outs so `data/` stays ignored but `data/tag_database/` ships
- Loads + parses once per process (version-hashed cache); served from memory

**Backend (`routes/editor_api.py`):**
- `GET /api/editor/tags` — returns `{tags: [...], aliases: {...}, version: sha256}`
- Section-aware parser for `name | description` tag files
- SHA256 version hash over all files → cache self-invalidates if files change on disk

**Frontend (`frontend/js/metadata_editor.js`):**
- Per-platform tag section now renders a tab strip (Default / SoFurry / Wattpad / Inkbunny) with separate pill lists per platform
- Lazy tag DB load on first autocomplete interaction (cached in `sessionStorage` by version hash, background refresh)
- Autocomplete dropdown: exact → alias → prefix → substring match ranking, capped at 30 results
- Alias matching: typing "boobs" surfaces `breasts` with alias badge; selection adds the canonical tag
- Keyboard nav: ArrowUp/Down, Enter to add, Esc to close, Backspace-on-empty to remove last pill
- Unknown-tag handling: "No matches — Press Enter to add anyway" with yellow-bordered pill flag
- Tag count footer with per-platform limits (SoFurry 97, Wattpad 24, Inkbunny/Default ∞), turns red over limit

**Frontend (`frontend/css/editor.css`):**
- Tab strip + dropdown + pill styles matching dark theme tokens
- Per-category chips with colour coding (physical/acts/kink/meta/image)

**Cache busters:** `metadata_editor.js?v=3`, `editor.css?v=241`

---

## [2.7.0] - 2026-04-13

### Added — WYSIWYG Editor, Semantic Anchors, Format Tools, Theme Persistence

**Theme Save persistence + Regenerate integration:**
- Theme Save now persists variables to `CHAPTER_STYLING.md` (survives Regenerate)
- Regenerate now includes Styled HTML (full + chapters + `style.css`)
- `pawpull.py` reverse sync script (server → local)
- Text message colour pickers in theme GUI (`TEXT_SENT_COLOUR`, `TEXT_RECEIVED_COLOUR`)
- Warning icon + section break mega dropdown selectors (55 icons, 47 breaks, custom option)
- `GET /theme` endpoint fills defaults for missing variables
- `PUT /format-file` endpoint for saving formatted output

**WYSIWYG Rich Editor (panel 2):**
- Contenteditable panel with formatting toolbar (Bold, Italic, Heading, Section Break, Undo, Redo)
- Bidirectional sync with CM source via Turndown (HTML→markdown) library
- Front matter locked as non-editable; body edits sync to all panels
- Source-flag pattern prevents infinite sync loops
- Paste handler sanitises to plain text

**Semantic anchors for text messages + phone displays:**
- New body-level anchors: `<!-- @text-sent -->`, `<!-- @text-received -->`, `<!-- @phone-incoming -->`
- All 4 body converters (Clean HTML, SoFurry, BBCode, Styled HTML) handle anchors
- Clean/Styled HTML: `<div class="text-message sent/received">` with CSS styling
- BBCode: colour-coded `[right]` (sent) / `[left]` (received) alignment
- SoFurry: `text-right` / `text-left` class alignment
- Text-message + phone-display CSS added to STYLING_REFERENCE.md template
- `is_text_message()` regex fixed to match `**Name:** message` format (was broken)

**Format Document button:**
- js-beautify library (141KB) for HTML/CSS prettification
- Format button + Shift+Alt+F keyboard shortcut
- Formats + saves the prettified content to disk via `PUT /format-file` endpoint

**Editor improvements:**
- Bidirectional scroll sync across all 4 panels (60ms lock prevents wobble)
- Cross-panel selection sync (highlight text in any panel → shows in others)
- Selection highlights skip contenteditable panel to prevent DOM corruption
- Preview truncation limit raised from 100K to 500K chars
- Print-container added to STYLING_REFERENCE.md template (print margins)
- Ruins of Breeding: fixed 44 bogus `<strong>` tags from parser bug
- 8 stories: added print-container wrapper to styled HTML files
- Converter: `---` separator no longer leaks into disclaimer text

**Bug fixes (comprehensive audit — 12 issues):**
- Auto-save timer properly cleared on re-render
- CM instances destroyed on re-render (prevents orphaned listeners)
- beforeunload listener cleaned up between stories
- Scroll sync flag in try/finally (prevents stuck state)
- Toolbar overflow handled with nowrap + overflow-x
- Front matter re-extracted from CM on every WYSIWYG sync (prevents stale cache)

---

## [2.6.0] - 2026-04-12

### Added — Visual Theme Editor with live preview sync

**Theme GUI (editor.js / editor_api.py):**
- Visual colour picker interface for all 14 styled HTML theme variables
- Live preview: changing any colour immediately updates the Styled HTML preview iframe (~300ms debounce)
- CSS source view stays in sync with GUI changes (returned from preview endpoint)
- Undo button — steps back one change at a time (50-entry stack, debounced for colour picker drags)
- Revert button — resets to last-saved values (the revert itself is undoable)
- Save writes `style.css` to `HTML/` and `Chapters/Styled_HTML/`, clears undo history
- Source/GUI toggle switches between visual editor and raw CSS CodeMirror view

**Backend (editor_api.py):**
- `PreviewRequest` accepts optional `theme` dict for live GUI → preview pipeline
- Preview response includes generated `css` field for styled_html format
- `PUT /theme` endpoint: better error handling (PermissionError, template-not-found, CSS generation failures)
- `PUT /theme` and `PUT /css`: proper HTTP error detail parsing in frontend

**External CSS migration (all 13 stories):**
- Generated `style.css` for all 13 stories (28 files: `HTML/` + `Chapters/Styled_HTML/`)
- Converted 89 Styled HTML files from embedded `<style>` to external `<link rel="stylesheet" href="style.css">`
- ~600 KB total size reduction across all styled HTML files

**Infrastructure:**
- `deploy/pawsync.py`: changed `chmod o+rX` to `o+rwX` so Docker container can write to story archive
- Cache-busting on `editor.js` (v250 → v253)

---

## [2.5.1] - 2026-04-10

### Fixed — Full code audit cleanup

4-domain audit across editor code, standalone scripts, MASTER.md files, format files, and documentation. 66 findings addressed.

**Code fixes:**
- converter.py: removed unreachable `else` block (dead code from subtitle iteration)
- editor_api.py: removed duplicate path resolution (copy-paste error)
- editor.js: removed dead `_setupDivider()` method (19 lines, old split pane)
- editor.css: removed dead `.preview-source-header` style

**Portability fixes (14 scripts):**
- Eliminated all hardcoded `C:/Users/rhysc/claude/...` absolute paths across 14 Scripts_Utils files
- All now use `Path(__file__).resolve().parent.parent / "Archives" / "Complete_Stories"` (relative to script location)
- Scripts work on any machine, any OS, any user account

**Data fixes:**
- AB Nice + Naughty: added missing `#workskin em` CSS rule to Work_Skin.css
- Velvet story.json: title "Velvet And Vice" → "Velvet and Vice" (lowercase "and")
- 7 MASTER.md files: added `---` separator after `<!-- @body -->` for cross-story consistency
- slop_scorer.py: fixed formula docstring to match actual implementation

**Documentation fixes:**
- EDITOR_PLAN.md: updated all phase statuses (Phases 1-4 marked DONE, Phase 5 TODO list updated)
- FILE_FORMAT_STANDARDS.md: added external CSS architecture section for Styled HTML

---

## [2.5.0] - 2026-04-10

### Added — Story Editor: all formats complete + anchor system + slop scoring

The story editor is now a full pipeline — every format automated from MASTER.md.

**Anchor-based MASTER.md parsing (Phases 1-2):**
- 7 HTML comment anchors mark structural sections: `@title`, `@subtitle`, `@byline`, `@warning`, `@disclaimer`, `@fanfiction`, `@body`
- `parse_front_matter()` extracts structured `FrontMatter` dataclass from anchored files
- 4 format-specific front matter renderers (Clean HTML, SoFurry HTML, BBCode, SQW)
- Heuristic fallback for non-anchored files (backwards compatible)
- Migration script `add_anchors_to_master.py` processed all 13 stories — warning/disclaimer text sourced from canonical SQW Chapter 1 files
- `@fanfiction` anchor for IP attribution (Chosen = DreamWorks, Silk = Bethesda)

**Standalone converter unification (Phase 3):**
- `convert_md_to_sofurry_html.py` and `convert_md_to_bbcode.py` replaced with 80-line wrappers that import from `editor/converter.py`
- ~1,000 lines of duplicate parser code eliminated

**SQW auto-generation (Phase 4):**
- `convert_to_sqw_chapters()` generates per-chapter SquidgeWorld body HTML from anchored source
- Chapter 1: full warning-page div; Chapter 2+: bare title block
- Warning icon read from CHAPTER_STYLING.md per story
- Wired into editor regenerate endpoint

**Styled HTML generator (the last manual format):**
- `convert_to_styled_html()` generates complete HTML documents with embedded CSS
- `parse_chapter_styling()` reads 14 colour variables from CHAPTER_STYLING.md
- 3 modes: full story, per-chapter, single chapter
- Template from STYLING_REFERENCE.md with `{{PLACEHOLDER}}` variable filling
- Print CSS generation (colour-preserve + grayscale modes)
- Editor renders Styled HTML in sandboxed iframe

**Slop scoring:**
- `editor/slop.py` — ported EQ-Bench scorer for in-memory use
- `POST /api/editor/{story}/slop` endpoint
- Colour-coded badge in editor toolbar (green CLEAN < 15, yellow BORDERLINE 15-25, red SLOP > 25)
- Refreshes on load + after save

**SF replace_file() fix:**
- Upload-first-then-delete order (SF won't delete the last content item)
- 32 duplicate content items cleaned across 12 stories

**SoFurry HTML converter:**
- New `convert_to_sofurry_html()` using SF's actual HTML capabilities (`<h2>`, `<h3>`, `text-center`)
- `story_reader.py` updated to prefer `*_SoFurry.html` over `*_Clean.html` for SF uploads
- SoFurry HTML capabilities reference documented from `sofurry_html_capabilities.html`

**Content warning standardisation:**
- 7 MASTER.md files received Content Warning + DISCLAIMER blocks (were missing)
- Centering rules enforced: title, subtitle, CW, disclaimer, chapter headings, POV markers, section breaks, end marker — all centred in every format
- `_is_warning_line()` detector + `in_warning_block` state tracking (heuristic, replaced by anchors)

**Editor format dropdown:** Clean HTML (AO3), SoFurry HTML, BBCode (IB), Styled HTML (PDF) — 4 formats, all live-converting from the textarea

**converter.py:** 1,722 lines (from 457 at session start)

---

## [2.4.0] - 2026-04-09

### Added — Story Editor (Phase 1: Edit + Preview + Regenerate)

New in-app story editor accessible at `#/editor`. Edit MASTER.md directly in the PawPoller web UI with a live format preview and one-click format regeneration.

**Backend** (`editor/` package + `routes/editor_api.py`):
- `editor/converter.py` — core markdown parser (`parse_markdown_formatting()`) + HTML/BBCode renderers. Same parser used by the standalone CLI converters. Handles `*italic*`, `**bold**`, `***both***`, nested italics, POV markers, text messages, chapter headings, section breaks.
- `routes/editor_api.py` — 5 endpoints:
  - `GET /api/editor/stories` — lists all stories in the archive (13 found)
  - `GET /api/editor/stories/{name}/content` — reads MASTER.md, detects chapters
  - `PUT /api/editor/stories/{name}/content` — saves with backup + optimistic concurrency
  - `POST /api/editor/stories/{name}/preview` — live format conversion (clean_html, bbcode)
  - `POST /api/editor/stories/{name}/regenerate` — writes BBCode + Clean HTML + chapter splits

**Frontend** (`editor.js` + `editor.css`):
- Story list page (`#/editor`) — card grid of all stories with word counts
- Split-pane editor (`#/editor/{story}`) — textarea left, live preview right
- Draggable divider between panes
- Format switcher (Clean HTML / BBCode dropdown)
- Ctrl+S keyboard shortcut for save
- Debounced live preview (400ms after typing stops)
- Dirty-state tracking with beforeunload warning
- Word count in toolbar (live)
- Regenerate button (saves first if dirty, then writes BBCode + HTML + chapter files)
- Sidebar nav link under new "Editor" section

**File management:**
- Editor reads/writes directly to the story archive (resolved via `story_reader.get_archive_path()` — works for both desktop and Docker)
- Save creates a timestamped backup (`MASTER.md.bak.{timestamp}`), keeps last 10
- Atomic write via temp file + `os.replace()` to prevent corruption
- Regenerate creates folder structure if missing (`BBCode/`, `HTML/`, `Chapters/`)

**Architecture docs:** `docs/EDITOR_PLAN.md` — full implementation plan covering all 5 phases, file sync model, API design, frontend design, risk assessment.

**What's next (Phases 2-5):**
- Phase 2: SQW + Styled HTML preview tabs, chapter outline sidebar
- Phase 3: Live slop score + validation panel
- Phase 4: CSS theme editor (colour pickers → live styled preview)
- Phase 5: PDF generation + one-click platform push

---

## [2.3.19] - 2026-04-09

### Fixed — Platform push of regenerated files (SF + IB + AO3 attempt)

Pushed the converter-rewrite output to all accessible platforms:

- **SoFurry**: 13/13 submissions updated via `SoFurryPoster.replace_file()` (Clean HTML body content replaced). Both published and draft works updated. Total time ~16s.
- **Inkbunny**: 7/7 submissions updated via `InkbunnyPoster.replace_file()` (BBCode story text replaced via `api_editsubmission.php`). All published works updated. Total time ~9s.
- **AO3**: 0/13 — "Shields are up!" (AO3 rate-limit wall). Script `tests/edit_ao3_after_converter_rewrite.py` ready for retry.

### Changed — Inkbunny `replace_file()` implemented

`posting/platforms/inkbunny.py`: Replaced the "not implemented" stub with a working implementation that reads the BBCode file and pushes via `client.edit_submission(story=text)`. The IB API's `api_editsubmission.php` accepts a `story` field for the reading-panel body text — only that field is sent, so title/description/tags/visibility are preserved.

### New test scripts
- `tests/edit_sf_after_converter_rewrite.py` — bulk SoFurry content push
- `tests/edit_ao3_after_converter_rewrite.py` — bulk AO3 content push (ready for retry)

---

## [2.3.18] - 2026-04-09

### Fixed — Converter rewrite: proper `*`/`**` italic/bold parser

**Root cause fix** for the `<em><strong>` / `[i][b]` nested-italic bug class that affected Clean HTML (SoFurry/AO3), BBCode (Inkbunny), and SquidgeWorld body files across the entire catalogue.

Both `convert_md_to_sofurry_html.py` and `convert_md_to_bbcode.py` rewritten with a new `parse_markdown_formatting()` function that scans left-to-right, toggling italic state on `*` and bold state on `**`. Replaces the old pipeline (`split_dialogue_narration` → `apply_narration_italic` → `convert_emphasis` → outer wrapper stripping) which had these bugs:
- Inner `*word*` inside italic context rendered as `<strong>` (bold) instead of toggling italic OFF (roman)
- Outer wrapper stripping heuristic was fragile (counted asterisks, broke on mixed-italic lines)
- Default-italic mode wrapped un-marked paragraphs in italic
- POV marker regex didn't support Unicode `⟨⟩`
- HTML converter lacked text message detection (BBCode had it)

**Files regenerated:**
- 22 full-story files (11 Clean HTML + 11 BBCode)
- 118 per-chapter files (SoFurry HTML + BBCode per chapter)
- All from current MASTER.md source

**Verification:** `grep -rl "<em><strong>"` on all Clean HTML returns only legitimate `***bold+italic***` constructions (Extra Credit epilogue title, Velvet story-name references). Zero converter bugs.

---

## [2.3.17] - 2026-04-09

### Fixed — Section break styling + inline emphasis + PDF regen (final clean-up pass)

Continuation of the [2.3.16] standardisation sweep. Targets the remaining validator warnings.

**Fixes:**
- **67 SQW section breaks styled** — `<p>* * *</p>` → `<p class="section-break">* * *</p>` across 23 files / 8 stories. The CSS accent colour + centering now applies.
- **108 styled HTML section breaks styled** — same fix applied to per-chapter and full-story styled HTML across 21 files / 6 stories. PDFs now render section breaks with proper spacing.
- **32 inline `*word*` emphasis converted** — bare markdown emphasis in dialogue that the old converter never processed (e.g. `*looking*`, `*Kristoff*`, `*me*`) → `<em>word</em>` across 9 styled HTML files / 3 stories (Extra Credit, Ruins, Velvet).
- **1 Ruins ch1 styled HTML fix** — leading literal `*` + `<em><strong>` converter artefact on the "His hooves" paragraph (same bug class as the SQW bolding fix, but in the styled source).
- **87 PDFs regenerated** from updated styled HTML.
- **Validator false-positive fix** — `validate_story.py` no longer flags `* * *` inside `<p class="section-break">` as stray asterisks.

**New script:** `fix_sqw_plain_section_breaks.py` — converts standalone `<p>* * *</p>` → `<p class="section-break">* * *</p>` across all SQW chapters.

**Final validator result:** 11 of 12 stories at 0 fails, 0 warnings. Only NSES remains (incomplete folder build — separate scope).

---

## [2.3.16] - 2026-04-09

### Fixed — Full SQW standardisation pass (11 stories) + NSES species fix

Catalogue-wide standardisation sweep against `Reference_Guides/FILE_FORMAT_STANDARDS.md`, then bulk re-push of all 11 SQW drafts. Reduced validator fails from 67 → 9 (the 9 are all structural gaps in Not So Efficient Studying's incomplete folder build).

**Fixes applied (in order of severity):**

| Fix | Files | Stories |
|---|---|---|
| Subtitle separator `—` → `:` to match story.json | 58 | 10 |
| Duplicate section breaks removed (`<p>* * *</p>` + `<p><strong>~ End ~</strong></p>`) | 18 | 9 |
| Duplicate plain front matter deleted after warning-page div | 6 | 6 |
| em-strong narrative bolding fixed (Hypnotic text messages + Extra Credit labels) | 14 | 2 |
| Missing `#workskin em` CSS rule added | 2 | 2 (Chosen + Silk) |
| **Not So Efficient Studying species fix** — Mack was described as "bull terrier" in story.json description + summary; he's a **rat** (confirmed from MASTER.md) | 1 | 1 |

**New helper scripts** (under `m_x/Scripts_Utils/`):
- `fix_sqw_subtitle_separator.py` — reads story.json chapter_info titles and replaces mismatched h2 text in SQW chapter files
- `fix_sqw_duplicate_front_matter.py` — detects and deletes plain-paragraph title/byline/warning blocks that appear after the warning-page div
- `fix_sqw_duplicate_section_breaks.py` — removes plain `<p>* * *</p>` lines that duplicate a styled `<p class="section-break">`, and plain `<p><strong>~ End ~</strong></p>` that duplicate a styled `<div class="story-end">`
- `validate_story.py` — validates any story folder against FILE_FORMAT_STANDARDS.md rules (folder structure, MASTER.md asterisk balance, story.json fields, SQW body anti-patterns, CSS selectors, styled HTML chapter headings, div balance). Run `python validate_story.py --all` for a full sweep.

**Standards document**: `Reference_Guides/FILE_FORMAT_STANDARDS.md` — comprehensive rules for all 13 file types with required structure, anti-patterns, cross-story consistency rules, and a validation checklist.

**SQW push**: All 11 stories re-pushed via `tests/edit_sqw_after_fixes.py --apply --yes`. Total edit time ~330s. All draft states preserved (verified by poster safety checks).

---

## [2.3.15] - 2026-04-09

### Fixed — SquidgeWorld bulk re-edit after body normalisation pass (5 stories)

Pushed local SquidgeWorld body fixes live to 5 existing draft works. The fixes covered five distinct bug categories the user surfaced after browsing the drafts:

1. **Velvet and Vice** — chapter labels in all 9 SQW chapter HTML files were `Chapter X — Title` matching the file index, but the canonical labels (per the styled HTML) are `Prelude: Threads Unraveling` then `Chapter 1: Callum`, `Chapter 2: Sierra`, ..., `Chapter 8: Communion` (offset by 1). Plus Velvet's `Work_Skin.css` had no `.chapter-subtitle` selector, so every h2 fell back to default browser styling (left-aligned, plain bold) instead of the canonical centred small-caps Georgia. Plus chapter 1's warning page was missing the `warning-heading`/`warning-body` paragraphs and had a duplicate plain front matter block below the div. Fixed all three.

2. **Drumheller Detour** — chapter 1 warning page had only the disclaimer (no actual content warning text), with the real warning content dumped as plain `<p><em>...</em></p>` paragraphs immediately below the div. Restored the canonical warning-heading/warning-body inside the div, deleted the duplicate plain block.

3. **Ruins of Breeding** — 46 narrative paragraphs across 6 chapters had `<em><strong>X</strong> Y <strong>Z</strong></em>` artefacts from an old converter mishandling nested italics. The script `m_x/Scripts_Utils/fix_sqw_em_strong_bolding.py` parses MASTER.md as ground truth and re-renders each affected line as alternating italic/roman segments using a small Python parser (`parse_italic_alternation` + `md_line_to_html`). Plus deleted Ruins ch1's duplicate plain front matter block.

4. **Overtime** — already fixed locally yesterday (print-container strip + `chapter-heading` → `chapter-subtitle` rename via `normalize_sqw_print_container.py`). Pushed via this pass. Chapter headings now render centred italic in the work skin (the rename made the existing `.chapter-subtitle` rule apply).

5. **Tombstone** — same as Overtime, fixed locally yesterday, pushed in this pass.

### New helper scripts (under `m_x/Scripts_Utils/`)

- **`normalize_sqw_print_container.py`** — strips vestigial `<div class="print-container">` outer wrapper from Overtime + Tombstone SQW chapters and renames `<h2 class="chapter-heading">` → `<h2 class="chapter-subtitle">`. Verifies div balance pre/post. Idempotent. Backups at `*.sqw-bak`.
- **`fix_sqw_em_strong_bolding.py`** — Ruins-only narrative bolding fix. Reads MASTER.md, finds each `<p>` paragraph in the SQW chapter HTML containing `<em><strong>` patterns, looks up the corresponding MASTER.md line by text signature (HTML tags + `*` markers stripped, whitespace collapsed), then re-renders the line as alternating italic/roman segments. 46 paragraphs fixed across 6 Ruins chapters with 0 no-match. Restricted to Ruins because other stories use `<em><strong>` legitimately for chat-message styling (Drumheller, Hypnotic), POV markers (Velvet `⟨ Sierra ⟩`), and story-title references.

### New test script

- **`tests/edit_sqw_after_fixes.py`** — drives `SquidgeWorldPoster.edit()` for the 5 affected stories. Looks up each work_id by matching the local title against the user's SQW drafts + published lists, then runs `edit()` per story (which auto-detects draft state, preserves it, refreshes the work skin, edits metadata, iterates all chapters, and verifies state didn't flip). Single-story mode via `--story <folder>`, batch via no flag. Dry run by default; `--apply` to push.

### SquidgeWorld results

| Story | work_id | Edit time | Notes |
|---|---|---|---|
| Velvet and Vice | [91397](https://squidgeworld.org/works/91397) | 45.5s | CSS rule + 9 chapter labels + ch1 warning rebuild |
| Drumheller Detour | [91391](https://squidgeworld.org/works/91391) | 39.1s | ch1 warning page rebuilt, duplicate plain block deleted |
| Ruins of Breeding | [91395](https://squidgeworld.org/works/91395) | 33.0s | 46 narrative paragraphs cleaned, ch1 dup deleted |
| Overtime | [91394](https://squidgeworld.org/works/91394) | 26.4s | print-container strip + class rename, headings now centred |
| Tombstone | [91390](https://squidgeworld.org/works/91390) | 22.4s | same as Overtime |

All 5 still in draft state post-edit (verified by `SquidgeWorldPoster.edit()`'s built-in safety check). Total edit time across all 5: 166.4s.

---

## [2.3.14] - 2026-04-09

### Added — Story detail page enrichment (Batch 3 of 3): sparklines, comparison chart, timeline, format downloads

Final batch of the story detail page overhaul. Adds the analytics tier: per-pub sparklines, a Chart.js comparison overlay, a publication timeline, format file metadata + direct downloads, and a best-performer badge. Completes the brainstorm from the Drumheller Detour screenshot session.

**Backend:**

- **Per-pub snapshots in `get_story_detail`.** New `_SNAP_TABLES` mapping in the route handler keys each platform to its snapshot table + primary metric (`snapshots.views`, `fa_snapshots.views`, `sqw_snapshots.hits`, `wp_snapshots.reads`, `ik_snapshots.likes`, etc.). For each pub we query the last 30 days of snapshots (capped at 60 points) and attach them as `pub.snapshots = [{t, v}]` in chronological order. Wrapped in try/except for `OperationalError` (table missing on fresh installs) and `ValueError` (TEXT vs INT id mismatch on BSKY/TW). The frontend renders these via inline SVG sparklines + a Chart.js comparison overlay.
- **`story_reader.get_format_files()` helper.** New function + new `_FORMAT_KEY_PATTERNS` dict that maps each `formats` key in `story.json` (`bbcode`, `chapter_bbcode`, `html`, `sofurry_html`, `squidgeworld`, `markdown`, `pdf`, `styled_html`) to its directory + glob pattern. For each declared format, resolves all matching files, stats them, and returns `{available, files: [{path, size, modified}]}`. The relative `path` is exactly what the new `/api/posting/file` endpoint expects in its `file` query param. `_iso_mtime()` helper converts the float mtime into a UTC ISO timestamp string.
- **`get_story_detail` now returns `formats` as the enriched dict** instead of the raw `{key: bool}` flag dict from `story.json`. The frontend uses the file metadata to render badge tooltips and download links.
- **`GET /api/posting/file?story=&file=`** — new download endpoint. Same security model as `/api/posting/image`: query params, `Path.resolve().relative_to()` traversal guard, extension allowlist. The download allowlist is wider than the image one — `.txt, .html, .htm, .md, .pdf, .json` — covering all the format files the badges link to. Sends `Content-Disposition: attachment; filename="..."` so browsers download rather than render. `Cache-Control: no-cache` because format files change frequently and a cached BBCode would be misleading.

**Frontend (`frontend/js/posting.js`):**

- **`buildSparkline(snapshots, w, h)` helper.** Pure inline SVG line chart, no Chart.js per row. SVG was chosen over Chart.js for the per-row sparklines because Chart.js per row means N canvases × N resize observers × N animation loops on the page — too much for what should be a tiny visual cue. SVG is one DOM tree per chart, no JS lifecycle. Renders polyline + a small dot on the most recent point so flat series still have a visual anchor.
- **`formatFileSize(bytes)` helper.** Bytes → "1.2 KB" / "3.4 MB" for the format download badges.
- **`PUB_CHART_COLORS`** palette — 11 colours picked to be distinct on a dark background (one per platform, modulo cycling).
- **Pub row gains a sparkline column** rendered from `p.snapshots`. Empty for fresh pubs with <2 data points (sparkline helper early-returns).
- **👑 Best-performer badge.** Computed client-side: find the pub with the highest views (or views-equivalent), tag its row. Only renders when there are 2+ pubs — best-of-one is meaningless.
- **`Posting._renderComparisonChart(pubsWithData)`** — new method that builds a Chart.js line chart in the new `#story-comparison-chart` canvas with one dataset per pub. Reads CSS custom properties (`--text-muted`, `--border`) so the chart matches the active theme. Manages its own canvas lifecycle via `canvas._ppChart` (route() doesn't clean up posting.js charts the way it does for the main app's charts, so the destroy-before-recreate pattern is local). Only renders when there are 2+ pubs with at least 2 snapshot points each.
- **Publication Timeline card.** Chronological list of post + update events, derived from the existing `first_posted_at` / `last_updated_at` columns on each pub. No new backend data needed — pure client-side aggregation. Sorted newest-first. Update events use a green dot, post events a purple one.
- **Formats card rebuilt for the enriched dict.** Each format becomes a clickable `<a class="format-link" download>` pointing at `/api/posting/file?story=&file=` with the size shown inline ("bbcode 24 KB") and full file path + modified timestamp on hover. Multi-file formats (chapter_bbcode, squidgeworld) link the first file's download and show "(N files)" instead of a single size. Formats declared in story.json but with no files on disk get rendered as a muted, non-clickable `format-empty` badge.

**CSS (`frontend/css/components.css`):**

- New: `.pub-spark` (sparkline column on pub rows, accent-colored), `.best-badge`, `.timeline-list` + `.timeline-event` + `.timeline-dot` (with `.timeline-update` variant), `.timeline-when`, `.timeline-label`. Format badges revamped: `.format-link` (clickable download with hover state), `.format-empty` (muted no-files-on-disk variant), `.format-meta` (the size span).
- Mobile breakpoint extended: sparkline scales to row width, timeline collapses the time + label into stacked rows.

**Verified:**
- `python -m py_compile routes/posting_api.py posting/story_reader.py` clean
- `node --check frontend/js/posting.js` clean
- Single round-trip preserved: still one request to `/api/posting/stories/{name}`. The detail page now carries cover, summary, chips, totals, change-detection, top fans, recent log, queue, snapshots, format metadata — all in one response. The format download endpoint is hit only on click.
- Chart.js lifecycle: `_renderComparisonChart` destroys any existing chart on the canvas before recreating, so navigating away and back doesn't leak.
- Path traversal: `/api/posting/file` rejects `../etc/passwd` style paths via the same `relative_to()` guard the image endpoint uses, plus the wider extension allowlist still excludes `.py`, `.sh`, `.exe`, etc. — no arbitrary file exfiltration from the story folder.

**Not done in this version:**
- Did NOT add zoom/pan to the comparison chart. Chart.js zoom is a separate plugin and the 30-day window is small enough that fixed scale is fine.
- Did NOT add metric selector (views vs faves vs comments) to the comparison chart. Hardcoded to views (or views-equivalent per platform). Adding a metric switch would require either re-querying snapshots with a different value column or fetching all metrics up-front; out of scope for this batch.
- Did NOT add a "regenerate format files" button next to the download links. The format files are regenerated externally via the `m_x/Scripts_Utils/regenerate_story.py` workflow on the desktop, not by the dashboard. Adding a regen button would require shell-out to that script and runtime mode awareness.
- BSKY/IK/DA/TW publications: snapshots queries should work for these now since we added them to `_SNAP_TABLES`, but they still don't have stats populated by `get_publications_with_stats` (separate `stat_tables` dict in `posting_queries.py` doesn't have entries for them). Worth aligning the two dicts in a future change.

### Wraps up the story detail page enrichment series

This is the third and final batch of the detail page overhaul started in 2.3.12 and continued in 2.3.13. The Drumheller Detour screenshot from the brainstorm session — a sparse page showing just title/words/chapters/2 pubs/8 chapters/6 format badges — now renders with cover image, summary, characters, relationships, cross-platform totals, sparklines per pub, change-detection badges, top fans, a comparison overlay chart, the publication timeline, recent activity log, per-platform tags accordion, and clickable format downloads. All driven by data the backend was already storing — most of the work was just surfacing it.

---

## [2.3.13] - 2026-04-09

### Added — Story detail page enrichment (Batch 2 of 3): change detection, history, queue, top fans

Continues the story detail page enrichment from 2.3.12. Adds the four cross-cutting items that needed backend work: per-publication change-detection badges, recent posting log card, pending queue callout, and IB top-fans inline. Everything still served in a single `/api/posting/stories/{name}` round-trip — the alternative would have been four separate fetches and a noticeably slower page render.

**Backend:**

- **`posting/sync.py:detect_changes()`** now accepts an optional `story_name` parameter. Without it the function still walks every publication (existing behaviour for the dashboard's `/api/posting/changes` endpoint); with it, only that story's pubs are hashed. Story-scoped detection is what `get_story_detail` actually wants — paying the cost of hashing every other story's files just to render one detail page is wasteful and would scale badly as the archive grows.
- **`database/posting_queries.py:get_queue()`** now accepts an optional `story_name` parameter. Backwards-compatible default (`None` = all queue items). Used by `get_story_detail` to surface only this story's pending items.
- **`routes/posting_api.py:get_story_detail`** is now the single round-trip backend for the detail page. It now returns:
  - `recent_log`: last 5 entries from `posting_log` filtered to this story (already supported by `get_posting_log(story_name=...)`).
  - `pending_queue`: in-flight or scheduled queue items for this story.
  - `publications[].top_fans`: for IB pubs, the 5 most recent rows from `faving_users` for that submission_id, as `[{username, first_seen_at}]`. Other platforms get an empty list. Wrapped in try/except for `OperationalError` so a fresh install without an IB poll yet doesn't crash the endpoint.
  - `publications[].change_status` and `publications[].change_detected`: per-pub output of the new story-scoped `detect_changes()`. Status is one of `changed`/`unchanged`/`file_missing`/`no_hash`. Merged onto each publication by `(chapter_index, platform)` — the unique key. Wrapped in try/except so a transient `story_reader` failure doesn't break the page.

**Frontend (`frontend/js/posting.js:renderStoryDetail`):**

- **Pending queue callout** at the top of the page (below the info card) when there are in-flight or scheduled items. Per-item lines show action / chapter / platform / status / scheduled time. Visually styled as an accented card so it can't be missed.
- **Per-pub change badges:** `⚠ stale` (yellow) when the local file hash differs from `publications.file_hash`, `? missing` (red) when the format file can't be resolved, `? no hash` (grey) when the publication was claimed retroactively without a stored hash. The "unchanged" case stays silent — no green badge — since silence is the desired default.
- **Smarter "Update All" button.** When change detection knows N pubs are stale, the button label becomes `Update Stale (N)` and switches to primary styling; otherwise it stays `Update All` in secondary styling. Communicates intent at a glance.
- **Top fans inline** on IB publication rows: a small strip below the row showing up to 5 fan-name chips drawn from `faving_users`. Empty for non-IB pubs. The full list is still available via the IB submission detail page.
- **Recent activity card** showing the last 5 posting log entries for this story. Each row displays relative time (with raw timestamp on hover), action emoji, success/failure colour, duration, and an inline link if available. Failed entries also show a truncated error message tooltip.

**CSS (`frontend/css/components.css`):**

- New: `.pending-queue-card` (accented left border), `.pending-queue-list`, `.change-badge` + `.change-stale` / `.change-missing` / `.change-unknown`, `.pub-row-wrapper` (containing div so the fan strip can sit under the row without breaking the existing border-bottom pattern), `.pub-fans` + `.fan-chip`, `.log-row` (3-column grid: time / action / status, with full-width error subline), `.log-success` / `.log-failed`, `.log-when` / `.log-action` / `.log-status` / `.log-error`.
- Mobile breakpoint extended: `.log-row` collapses to a single column and `.pub-fans` un-indents.

**Verified:**
- `python -m py_compile routes/posting_api.py database/posting_queries.py posting/sync.py` clean
- `node --check frontend/js/posting.js` clean
- Backwards compatibility: `detect_changes()` and `get_queue()` both keep their no-arg signatures working — existing callers (`/api/posting/changes`, `/api/posting/queue`) are unchanged.
- Defensive: every new field early-returns to empty when its source data is absent. Stories with no change history, no queue items, no IB pub, and no recent log render exactly as before this change.
- Single round-trip: the detail page still makes one request to `/api/posting/stories/{name}`. No extra fetches added.

**Not done in this version:**
- Did NOT add a "claim history" view to surface publications that came in via `claim_existing_submissions` (status `no_hash`) — the badge tells the user the state but there's no UI to convert them to "tracked from now on" by re-uploading. Reasonable follow-up.
- Did NOT add per-platform comment/reply user lists (FA has comments + reply users via `fa_comments`, AO3/SqW have kudos users in their own tables). Top-fans is IB-only for now because faving_users is the cleanest source. Multi-platform top-fans goes in batch 3 alongside the comparison overlay chart.
- Did NOT add a "stale chip count" badge to the listing-page story cards. Worth doing in a separate change so the listing can show "3 stories have stale publications" at a glance, but out of scope for the detail page.

---

## [2.3.12] - 2026-04-09

### Added — Story detail page enrichment (Batch 1 of 3)

The Publishing → Stories detail page (`#/posting/story/{name}`) was rendering only a fraction of what the backend already returns. `get_story_detail` was sending `summary`, `characters`, `relationships`, `tags_by_platform`, per-chapter `description` fields, and full `update_count` / `tags_used` / file-hash columns from the publications table — all dropped on the floor by the frontend. This batch wires them up.

**Frontend (`frontend/js/posting.js:renderStoryDetail`):**

1. **Cover image** at the top of the info card. Same `/api/posting/image` route + `encodeURIComponent` shape as the listing cards. Backed by the same `detect_cover_relative()` auto-detect, so stories with a thumbnail file in the folder root but no `images.cover` entry in `story.json` finally render the cover on the detail page too.
2. **Summary block.** OTW-style longer blurb (`data.summary`) rendered as a callout card below the description, but only when it differs from `data.description` — many stories duplicate the two and we don't want side-by-side identical paragraphs.
3. **Characters & relationships chips.** Two-tone pill chips (purple-bordered for characters, green for relationships) below the warnings line.
4. **Per-chapter descriptions** rendered as italic muted text under each chapter row. The data was already returned per `data.chapters[].description` — the JS just had a 3-field render loop that ignored it.
5. **Per-platform tags accordion.** Native `<details>` blocks (one per platform that has tags), sorted by tag count desc so the densest list opens first. Each platform's full tag list shown as small pills inside the `<details>` body. Collapsed by default — IB carries 100+ tags on some stories and would otherwise dominate the page.
6. **Update count badge** on each pub row. Renders `↻ N` next to the date when `p.update_count > 0`, hover shows "N updates since first post". Drawn from the existing `update_count` column on `publications` (already on the wire — `get_publications_with_stats` does `SELECT *`).
7. **Cross-platform totals strip.** New card under the info section: total views, faves, comments summed across all publications, plus a platform count. Computed client-side from `data.publications[]` with platform-aware metric resolution (views/hits/reads, favorites_count/kudos/votes) so SqW kudos and Wattpad reads roll up correctly into the same totals.
8. **Days-since timestamps.** Pub-row dates now show `Utils.timeAgo()` output ("5d ago") with the raw `last_updated_at` on hover via `title=`. Reads better than `2026-04-04 00:52:59` and survives timezone confusion since timeAgo is relative.

**Backend (`routes/posting_api.py:get_story_detail`):**

- Enriched the `images` dict in the response with `detect_cover_relative()` fallback when `story.json` doesn't declare an `images.cover`. Mirrors the fix from 2.3.11 that added the same fallback to `_story_entry()` for the listing endpoint, so the listing and detail page can never disagree about which file is the cover. Without this, the detail page would have shown no cover for stories like Drumheller Detour where the thumbnail sits in the folder root but isn't recorded in `story.json`.

**CSS (`frontend/css/components.css`):**

- New: `.story-detail-cover` (200px desktop / 140px mobile, edge-to-edge above the info body), `.story-detail-info-body` (16px padding wrapper since `.story-detail-info` is now `padding: 0` for the cover bleed), `.story-detail-summary` (callout block with accent left-border), `.story-detail-chips` + `.chip` / `.chip-character` / `.chip-relationship`, `.totals-strip` + `.totals-stat` / `.totals-value` / `.totals-label`, `.chapter-entry` (wraps the existing `.chapter-row` so the description can sit under it), `.chapter-desc`, `.update-count-badge`, `.tags-platform` + `.tag-count` + `.tag-pill`.
- Mobile breakpoint extended: detail cover scales to 140px, totals-strip switches to a 2-up grid, pub-row stacks vertically.

**Verified:**
- `python -m py_compile routes/posting_api.py` clean
- `node --check frontend/js/posting.js` clean
- All new fields render conditionally — empty data is never shown as an empty block (covers, summary, chips, tags, totals, update badges all early-return when their source data is absent).

**Not done in this version:**
- Did NOT add per-pub change-detection badges (item 7 in the original brainstorm) — that lands in batch 2 because it needs an enriched API response or a separate fetch. Same for recent posting log card, pending queue card, and IB top-fans (batch 2). Per-pub sparklines, comparison overlay, and posting cadence timeline are batch 3.
- Did NOT add an "About" accordion that combines summary + characters + relationships into a single collapsible — opted for inline rendering since the data is short and screen real estate is fine. Reconsider if it gets noisy.
- BSKY/IK/DA/TW publications still won't have `stats` populated because `get_publications_with_stats` doesn't have entries for those platforms in its `stat_tables` dict — they fall through to `pub_dict["stats"] = None` and contribute 0 to the totals strip. Worth fixing in a separate change but out of scope for this batch.

---

## [2.3.11] - 2026-04-09

### Fixed — Story cover images never rendered in the Publishing → Stories hub

The card grid in `frontend/js/posting.js:renderUpload` had cover-image markup since the page was first written, but covers never appeared. Two combining bugs:

1. **No backend route.** `posting.js:56` built `/api/posting/image/{name}/{cover}` URLs but no FastAPI handler matched — every cover request 404'd silently (the card just rendered with no `.story-card-cover` div).
2. **Listing endpoint never auto-detected covers.** `routes/posting_api.py:list_stories` calls `story_reader.list_stories()` → `_story_entry()`, which only surfaced `images.cover` when `story.json` declared one explicitly. The richer auto-detect glob (`*_thumbnail_full_series.*`, `*_thumbnail.*`, `cover.*`, `thumbnail.*`) lived inside `_load_from_story_json` and only ran on the per-story detail endpoint. So stories with a thumbnail file in the folder root but no `images.cover` entry — which is the common case in this archive — silently rendered cover-less in the listing even though the detail page would have found the same file.

**Fix:**
- New route `GET /api/posting/image?story=&file=` in `routes/posting_api.py:134-185`. Query params (not path segments) so sub-stories like `The_Abstinent_Bet/Nice_Version` and nested files like `Images/cover.png` round-trip cleanly through `encodeURIComponent` without path/segment ambiguity. Hardened with `Path.resolve().relative_to()` traversal guard, image extension allowlist, and a 1-hour `Cache-Control` header.
- Extracted `detect_cover_relative()` + `COVER_EXTENSIONS` tuple in `posting/story_reader.py:229-262`, and pointed both `_story_entry()` and `_load_from_story_json()` at it. Listing and detail can no longer drift.
- `frontend/js/posting.js:55-63` now uses the query-param URL with `encodeURIComponent` for both `story` and `file`.

**Verified:**
- `python -m py_compile posting/story_reader.py routes/posting_api.py` clean
- Route registration check: `posting_router.routes` shows `/api/posting/image` registered (20 total routes)
- Path traversal: `(story_root / "../../../etc/passwd").resolve().relative_to(story_root)` raises `ValueError` → caught and returned as HTTP 403
- Extension allowlist: rejects anything outside `{.png, .jpg, .jpeg, .gif, .webp}` with HTTP 415

**Not done in this version:**
- Did not add a frontend fallback placeholder image for stories that genuinely have no cover (the card just renders without the `.story-card-cover` div, which is the existing graceful-degradation path).
- Did not update `documentation_guide.md` to mention the new route — the route is implementation detail rather than architecture, and the existing "Posting Module → Story Detail" section already documents the listing behaviour at the right level.

### Process note (for future me)

This session also surfaced that I'd been merging code changes without a CHANGELOG entry. The CHANGELOG is load-bearing here — `documentation_guide.md` cross-references entries by version (e.g. "see CHANGELOG 2.3.4") to explain *why* code looks the way it does. Going forward: every PawPoller code change ships with a versioned CHANGELOG entry plus the full deploy workflow (build → commit → push → `pawupdate`).

---

## [2.3.10] - 2026-04-09

### Fixed — stray markdown asterisks in styled HTML files (47 across 4 stories)

While verifying the FA Hypnotic + Silk submissions after the metadata + PDF replacement work in [2.3.9], spotted that Silk Chapter 2 was rendering literal `*` characters in the body text on FA. Investigation showed:

- **Bug pattern in styled HTML**: `<em>*Text...</em>` (leading `*` inside an italic opener), `<em>*</em>` (orphan italic with just an asterisk), `*</em>` (trailing `*` before closer). All three are leftover markdown italic markers from an old converter mishandling unmatched `*` in the source.
- **Root cause in MASTER.md**: 46 lines in Silk Threaded Bonds alone have unmatched asterisk counts — opening `*italic narration*` markers that were never closed (forgotten end-of-paragraph `*`) or stray closing markers left from edits. Other stories have a handful too: Hypnotic (4), Extra Credit (4), Ruins of Breeding (5).
- **Why this didn't affect BBCode/SoFurry HTML**: those were regenerated using the converter fix from [2.2.1] which correctly handles nested asterisk emphasis. The styled HTML files are manually maintained per workflow rule, so they never got the converter fix re-applied.

**Total bug count fixed**: 47 stray markers across 11 styled HTML files (5 Silk per-chapter + 1 Silk full + 2 Hypnotic + 2 Extra Credit + 2 Ruins = correct on close inspection — Silk full was already clean from yesterday's chapter-heading fix pass).

**Tooling added**: `m_x/Scripts_Utils/strip_stray_em_asterisks.py` — applies the 3-pattern cleanup to a list of styled HTML files. Idempotent. Returns 0 if all files end up clean. Used in this session against all 9 affected files in one batch.

**Plus one manual fix**: Ruins of Breeding `Chapter_2_The_Temple.html` had a standalone `*read*` markdown emphasis in dialogue that the original converter missed entirely (different bug class — bare `*word*` standalone emphasis not wrapped in narration italic). Manually replaced with `<em>read</em>`.

**FA submissions re-pushed after the fix** (5 of the 7 — Silk ch2 was already done in the session's first push, Hypnotic Part 2 wasn't affected):
- Hypnotic Part 1 (64274343)
- Silk Ch 1 (64284286)
- Silk Ch 3 (64284355)
- Silk Ch 4 (64284453)
- Silk Ch 5 (64284497)

**Verified live on FA** by downloading each PDF, extracting text via pypdf, counting literal `*` characters across all pages. Result: **0 asterisks across all 7 submissions, 74 pages of story text total.**

### Local-only fixes (not pushed because not on FA yet)
- Extra Credit: 4 stray asterisks fixed
- Ruins of Breeding: 4 stray asterisks + 1 standalone `*read*` fixed

These will be uploaded with clean PDFs whenever the stories get drip-posted to FA via the upcoming `bulk_fa_posts.py` flow.

### Documentation
- Per-story changelog updates for Silk, Hypnotic, Extra Credit, Ruins
- Note about MASTER.md authoring inconsistency (46 unmatched asterisk lines in Silk alone). The styled HTML files are now in their canonical clean state — the bug only re-emerges if you run the OLD converter against the still-broken MASTER.md. Future Layer 2 fix: clean up MASTER.md so any future regeneration is also clean.

### Not done in this version
- MASTER.md asterisk cleanup (Layer 2 — author-facing fix). Currently planned as a manual pass requiring careful per-line judgement (italic intent vs stray markers vs nested italic vs bold conventions like `**Dev:**` chat names that are intentional).

---

## [2.3.9] - 2026-04-09

### Added — FurAffinity edit-existing flow + per-chapter description prefix

Two new test scripts and one library improvement, in service of bringing the existing FA submissions for Hypnotic Claim and The Silk-Threaded Bonds in line with the regenerated PDFs and refreshed `story.json` metadata.

**`tests/verify_fa_edit_existing.py`** — verify (and optionally apply) metadata edits + PDF file replacements on existing FA submissions.

- **Default mode is read-only**: fetches the current FA state via FAExport, builds a fresh package via `build_package`, and prints a diff (title, description, tags, rating). Exits without writing anything.
- **`--apply`** flag: actually performs edits via `FurAffinityPoster.edit()` (changeinfo endpoint).
- **`--update-file`** flag: ALSO replaces the source PDF via `FurAffinityPoster.replace_file()` (changestory endpoint), 2-second pause between metadata edit and file replacement.
- **`--skip-tags`** flag: preserve existing FA tags (path A: SEO/act-focused tags work better for FA discovery than the new atmospheric/character set the build_package would produce).
- **`--skip-rating`** flag: preserve existing rating.
- **`--story <name>`** filter: substring-match by story name.
- **`--yes`** flag: skip the typed confirmation prompt (for scripted runs).
- **Hard typed confirmation prompt** before any write: must type exactly `EDIT N LIVE FA SUBMISSIONS` (with the right N) — no other input proceeds.
- **Hardcoded fallback list of 7 known FA submissions** (Hypnotic 2 + Silk 5) so the script works locally without needing the server's publications DB.
- **Inter-edit delay: 3 seconds** (NOT 70). Empirically confirmed FA's 70-second rate limit applies to *new submissions only*, not edits — see "FA edit rate limit" finding below.

**`tests/fa_changestory_canary.py`** — single-submission canary test of the changestory endpoint flow. Reads the current submission state, calls `replace_file()`, re-reads to confirm the download URL changed. Used to validate the existing `FurAffinityPoster.replace_file()` code path before extending the bulk script. Confirmed working end-to-end on Hypnotic Part 1 (FA 64274343).

**`posting/story_reader.py`** — `build_package()` now prepends a `Chapter X of N. ` or `Part X of N. ` navigation prefix to per-chapter FA descriptions. Auto-detects "Part" vs "Chapter" from the chapter title in `story.json` so Hypnotic Claim (which uses "Part 1" / "Part 2") gets `Part 1 of 2. <description>` while normal stories get `Chapter X of N. <description>`. The prefix is only added for FA platform packages with `chapter_index > 0`.

### Empirically confirmed — FA's 70-second rate limit is for new submissions, not edits

The FA poster's `min_post_interval = 70` constant is correctly named — it applies to new uploads (changeinfo endpoints don't have the same throttle). Two batches of edits performed in this session:

- **Hypnotic Claim batch**: 2 metadata edits + 2 file replacements, ~10s total wallclock
- **Silk Threaded Bonds batch**: 5 metadata edits + 5 file replacements, ~25s total wallclock with 3-second pauses

No 429s, no rate-limit errors. The previous 70s sleeps in `verify_fa_edit_existing.py` were a precautionary copy from the upload constraint and have been removed. New constant: `FA_RATE_LIMIT_SECONDS = 3`.

### FA submissions updated this session (live writes)

| Submission | Story | What changed |
|---|---|---|
| 64274343 | Hypnotic Claim Part 1 | title (em-dash + Part), description (rewritten + prefix), PDF (regenerated with proper warning page) |
| 64274371 | Hypnotic Claim Part 2 | same |
| 64284286 | Silk Threaded Bonds Ch 1 | same (Chapter prefix) |
| 64284325 | Silk Threaded Bonds Ch 2 | same |
| 64284355 | Silk Threaded Bonds Ch 3 | same |
| 64284453 | Silk Threaded Bonds Ch 4 | same |
| 64284497 | Silk Threaded Bonds Ch 5 | same |

**Tags + rating preserved on all 7** (path A — kept the existing SEO/act-focused tag sets that work for FA's tag-search). **Thumbnails not touched.**

For Silk specifically, the per-chapter PDFs were regenerated TWICE this session — first as part of the bulk regeneration that landed yesterday, then a second time after a follow-up fix to the per-chapter Styled HTML files (see story-side changelog for The Silk-Threaded Bonds). The second regeneration was triggered by spotting that Silk's per-chapter chapter-heading rendered as default browser h2 instead of the canonical centred Cormorant Garamond small-caps form. The per-chapter Silk Styled HTML files had `<h2 class="chapter-heading">` markup but no CSS rule for it.

### Documentation updates
- `m_x/Archives/Complete_Stories/Hypnotic_Claim/CHANGELOG.md` — full FA sync entry
- `m_x/Archives/Complete_Stories/The_Silk_Threaded_Bonds/CHANGELOG.md` — full FA sync entry + the per-chapter Styled HTML follow-up fix
- `m_x/Archives/Complete_Stories/The_Silk_Threaded_Bonds/CHAPTER_STYLING.md` — addendum documenting the per-chapter `.chapter-heading` rule fix
- `m_x/Archives/Complete_Stories/Hypnotic_Claim/story.json` — `chapter_info[].title` confirmed as `"Part 1: ..."` / `"Part 2: ..."` (briefly flipped to "Chapter" then reverted — Part is canonical)
- `m_x/Archives/Complete_Stories/The_Silk_Threaded_Bonds/story.json` — `title` field hyphen restored (`"The Silk Threaded Bonds"` → `"The Silk-Threaded Bonds"`); all 5 `chapter_info[].description` fields rewritten to ~half length

### Not done (intentionally)
- The 11 stories not yet on FA still need bulk-posting via a `bulk_fa_posts.py` script (not written yet — drip-feed strategy preferred over bulk-and-done)
- Tags on the 7 existing FA submissions are deliberately stale relative to what `build_package` would produce — the new tag set is more atmospheric/character-driven and would hurt FA discoverability

---

## [2.3.8] - 2026-04-08

### Fixed — CF Worker proxy was stripping Content-Type, silently breaking every body-bearing request

The Cloudflare Worker at `pawproxy.knaughtykat01.workers.dev` had a long-standing bug in `buildHeaders()` that stripped both `Content-Type` and `Content-Length` from every forwarded request. The bug was discovered while wiring up server-side SF posting:

- **Polling never noticed** because polling is GET-only — no request body, no Content-Type to forward, no boundary= parameter to lose.
- **Posting from local always worked** because the proxy is bypassed when `cf_worker_url` is empty in settings — and PawPoller's local dev settings.json has it empty.
- **Posting from the GCP server** was the first scenario where the proxy actually had to forward POST/PUT bodies. Every body-bearing request would arrive at the target site with no `Content-Type`, causing JSON / form-urlencoded / multipart bodies to be unparseable. SF/AO3/SQW posting via proxy would have been silently broken.

**Reproduced before fixing** with `tests/cf_proxy_content_type_repro.py` — sent a JSON POST through the proxy to `httpbin.org/post` (which echoes back the headers it received) and confirmed `target received Content-Type: None`.

**Fix in `deploy/cf-worker.js:buildHeaders()`:**
- Strip ONLY `host` (we set our own per-target) and `cookie` (we manage cookies in our own jar so domain-matching works through the workers.dev → real-target hop)
- **Preserve `Content-Type`** — it's a property of the request body, not the connection. Multipart bodies in particular MUST keep their `boundary=` parameter or the body is unparseable
- **Strip `Content-Length`** — Cloudflare Workers' inner `fetch()` recomputes the length from the body itself (or uses chunked encoding for streams). Forwarding the original Content-Length from the outer client→worker request would set a stale value that may not match what the worker actually streams to the target
- Long history-note comment in the source warning the next person not to add Content-Type back to the strip list
- Login flow's `extraHeaders: {'Content-Type': 'application/x-www-form-urlencoded'}` override still works because `Headers.set()` replaces existing values

**Also fixed: redirect path stale headers.** When the worker follows a redirect, it converts to GET method. The original Content-Type and Content-Length from a POST/PUT would still be in the headers built by `buildHeaders` and would be misleading (or rejected by strict servers) on a body-less GET. Added an explicit `redirHeaders.delete('content-type'); redirHeaders.delete('content-length')` in the redirect loop.

**Verified end-to-end:**
1. `tests/cf_proxy_content_type_repro.py` flipped from `[BUG]` to `[OK]` — `Content-Type: application/json` now forwarded correctly
2. `tests/sf_proxy_post_smoke.py` posted Tombstone as Private through the proxy from inside the GCP container (multipart upload, JSON metadata, full 3-step REST flow). Submission `myw0PxW1` created with `privacy=1 (Private)`, 75 tags, 2.1s end-to-end (basically as fast as direct local posting). Cleaned up afterwards.

**This unblocks server-side posting on every platform that uses bodies:**
- **SoFurry** — JSON + multipart, both confirmed working through proxy
- **SquidgeWorld** — form-urlencoded, OTW Archive (uses the same Rails form pattern as AO3, will work through proxy if needed; SQW doesn't strictly need the proxy from GCP but the path is now available)
- **AO3** — form-urlencoded, currently runs from GCP without the proxy and works most days; the proxy is now a viable fallback if AO3 starts blocking GCP IPs
- **DeviantArt** — JSON over OAuth2, currently the only platform that NEEDS the proxy from GCP. Bug was definitely affecting any DA POST attempts.

### Deployment

- `deploy/cf-worker.js` — patched `buildHeaders()` (preserve Content-Type, strip Content-Length) + redirect-path Content-Type/Length cleanup + long history-note comment
- `deploy/wrangler.toml` — added minimal wrangler config so future deploys can use `npx wrangler deploy` from `PawPoller/deploy/`
- Deployed via `npx wrangler deploy` to the `knaughtykat01@gmail.com` Cloudflare account (the one that owns the `knaughtykat01.workers.dev` subdomain). Initial deploy attempt landed on the wrong account because `wrangler login` had logged into a different identity — fixed by `wrangler logout` + `wrangler login` and picking the right account in the OAuth flow.

### Test files
- `tests/check_cf_proxy_state.py` — audit `cf_worker_url`/`cf_worker_key` settings and report which mode the SF poster would pick
- `tests/cf_proxy_content_type_repro.py` — reproduces the bug against `httpbin.org/post` (read-only deterministic regression test)
- `tests/sf_proxy_post_smoke.py` — server-side SF posting smoke test that exercises multipart upload through the proxy
- `tests/sf_delete_proxy_test_dup.py` — cleans up the duplicate Tombstone draft created by the smoke test

---

## [2.3.7] - 2026-04-08

### Added — SoFurry draft mode + bulk drafting

SoFurry now supports the same draft pattern as IB / SQW / AO3. SF has built-in privacy levels (1=Private, 2=Unlisted, 3=Public) so this is a real first-class draft state — owner-only visibility — not a workaround.

**6 SF drafts** (single-bulk-file convention via `HTML/<Story>_Clean.html`, all Private/owner-only):

| Story | Submission | Words |
|---|---|---|
| Tombstone | [nLrR4PBe](https://sofurry.com/s/nLrR4PBe) | 8,414 |
| Chosen | [m0KjxlKe](https://sofurry.com/s/m0KjxlKe) | 15,958 |
| Not_So_Efficient_Studying | [ePdyAZ5e](https://sofurry.com/s/ePdyAZ5e) | 13,602 |
| Overtime | [1xJGPWZm](https://sofurry.com/s/1xJGPWZm) | 11,513 |
| Ruins_of_Breeding | [nd4Pol7n](https://sofurry.com/s/nd4Pol7n) | 24,457 |
| The_Haunting_Desires | [mXB73JG1](https://sofurry.com/s/mXB73JG1) | 30,480 |

After this run, every local story is now on SF — 7 live published works + 6 new private drafts. Drafts are recorded in the publications table on the server with `status=draft`.

**SF posting was *fast*** — 2-3 seconds per submission, vs AO3's 20-150 seconds with retries. SoFurry's 3-step REST API (PUT empty → POST file → POST metadata) is much cleaner than OTW Archive's CSRF form scraping.

**`SoFurryPoster.post()` refactor:**
- New `_normalize_privacy()` helper that accepts ints (1/2/3) or strings ("private"/"unlisted"/"public") and maps to SF's numeric codes
- `package.extra["draft"] = True` → `privacy=1` (Private, owner-only) — same convention as IB/AO3
- `package.extra["privacy"] = 1|2|3` for explicit override (wins over draft)
- Default: `privacy=3` (Public) — preserves the existing behaviour for callers who don't set anything
- Post-flight verification: hits `/ui/submission/{id}` raw and confirms `privacy=1` server-side after a Private draft. Logs a warning if the server returns something else (defensive — `create_submission` has the privacy parameter wired correctly so this should never fire, but better to know).

### Fixed — `sf_client.edit_submission` was silently downgrading every edited work to Private

A pair of cascading bugs in `sf_client/client.py:edit_submission`:

1. **It used `get_submission_detail()` to fetch current state.** That helper strips the response down to public-facing fields (title, description, rating, etc) and **does not return `privacy`, `category`, `type`, or any of the other write-only metadata fields**. So `current.get("privacy")` always returned `None`.

2. **The fallback default was wrong.** When `current.get("privacy", 1)` returned the fallback, it returned **`1` (Private)** — the *least permissive* option. So every single edit silently overwrote whatever the work's actual privacy was with Private.

**Caught this the hard way:** while retrying the 4-day-old failed `Hypnotic_Claim` edit, the edit went through and reported success — then a follow-up fetch showed `privacy: 1` (Private). Hypnotic Claim had been a public live work for weeks. The script then ran an emergency restoration script that fetched the raw JSON, set `privacy=3` explicitly, and posted back, restoring the live state within 60 seconds of the regression.

**Why no other live works were affected:** the `failed` row in `publications` for Hypnotic_Claim shows the original 2026-04-04 edit failed with `"SoFurry login failed"` — i.e. it errored out at the *auth* step before reaching the metadata POST. So the buggy code path never actually fired in production, and the 7 live works on SF stayed Public. My retry today was the **first time the bug actually executed end-to-end**, and it was caught and rolled back inside the same script run.

**The fix:**
- `edit_submission` now fetches the **raw** `/ui/submission/{id}` JSON directly (not the stripped helper), so the merge sees every field on the server
- The fallback for `privacy` is now `current.get("privacy", 3)` — defaulting to Public is the safer choice when the field is somehow missing
- Added an explicit `privacy: int | None = None` parameter to `edit_submission` so callers can override (used by `SoFurryPoster.edit()` when `extra["draft"]` or `extra["privacy"]` is set)
- A long docstring on the method warns the next person not to substitute `get_submission_detail()` back in

**Audit confirmed all 13 SF works are in correct state:**
| 7 live works | privacy=3 (Public) ✓ |
| 6 new drafts | privacy=1 (Private) ✓ |

### Test files
- `tests/sf_smoke.py` — login + CSRF read-only check
- `tests/verify_sf_draft.py` — Tombstone canary draft with raw-JSON privacy verification
- `tests/bulk_sf_drafts.py` — bulk draft 5 missing stories (Tombstone already drafted)
- `tests/sf_retry_hypnotic_edit.py` — retry the 4-day-old failed edit
- `tests/sf_emergency_restore_hypnotic.py` — emergency restoration script (used once to undo the privacy regression)
- `tests/sf_audit_all_privacy.py` — full audit of expected vs actual privacy state for every known SF submission
- `tests/sf_mark_hypnotic_posted.py` — mark the publications row from `failed` back to `posted`

---

## [2.3.6] - 2026-04-08

### Fixed — `pawsync.bat` rewritten in Python after intermittent batch hang

The original `pawsync.bat` had two intermittent gotchas that survived three rounds of patching:

1. **Windows tar's `Cannot connect to C:` silent failure.** Windows tar (libarchive port) interprets `C:\\...` paths as remote SSH hosts unless given `--force-local`. Without it the pack would silently fail and the script would still upload whatever stale tarball was left in `%TEMP%` from the previous run — which we caught the hard way when [2.3.4]'s pawsync uploaded an Apr-6 archive 2 days after the fact.

2. **gcloud-from-batch hang.** When `gcloud compute scp` was invoked from inside a `.bat` file (vs interactively or via `cmd /c "..."`), it would silently hang somewhere after the upload reached 100% — never reaching the next command, never returning control to cmd.exe, no visible processes left running. The same gcloud command worked fine in every isolated test (interactive cmd, inline `cmd /c`, with or without `--quiet`, with or without `< nul` stdin redirect, with `--quiet` as top-level flag vs subcommand flag — none of those workarounds dislodged the hang in `.bat` context).

**Resolution: rewrote `deploy/pawsync.bat` in Python** as `deploy/pawsync.py` with a 3-line `.bat` wrapper that just calls `python pawsync.py %*`. Python sidesteps both bugs:

- **Pack via `tarfile` module** instead of Windows tar — cross-platform, no `--force-local` gotcha, no path interpretation surprises, and cleanly skips `Backups/`, `Drafts/`, `Styled_HTML/` via a name filter.
- **scp + ssh via `subprocess.run`** with `stdin=subprocess.DEVNULL`, `capture_output=True`, `shell=True` (needed on Windows so the OS resolves `gcloud.cmd`), explicit `timeout=600` for upload and `timeout=300` for extract. Zero ambiguity about stdio inheritance, deterministic exit code propagation, no batch context to confuse the wrapper.
- Uses `kithetiger@pawpoller` consistently for both scp and ssh (was previously mismatched — scp uploaded as `kithetiger`, default `gcloud ssh` ran as your Google identity user, which couldn't `rm` the kithetiger-owned file in `/tmp` due to the sticky bit).
- Aborts on any failure with a non-zero exit code (no silent stale uploads).

**One-time server cleanup applied during the rewrite:**
The server's `/home/kithetiger/story-archive/` files were owned by `rhysc` (my Google account user from previous extracts). After switching the new pawsync to extract as `kithetiger`, the first run hit `tar: Cannot open: File exists` because tar can't overwrite files owned by another user. Fixed with a one-shot `sudo chown -R kithetiger:kithetiger /home/kithetiger/story-archive`. All subsequent syncs work cleanly.

### File changes
- `deploy/pawsync.py` — new Python script (185 lines) that does the full pack-upload-extract-cleanup pipeline
- `deploy/pawsync.bat` — replaced 30-line batch script with 3-line wrapper that calls `python pawsync.py %*`

---

## [2.3.5] - 2026-04-08

### Added — AO3 Refactor + Bulk Drafting

Brought the Archive of Our Own client and poster up to par with the SquidgeWorld stack and bulk-drafted the entire local catalogue (13 drafts) on AO3.

**13 AO3 drafts** (every local story, all in preview/draft state, none published):

| Story | Work ID | Words |
|---|---|---|
| Tombstone | [82711601](https://archiveofourown.org/works/82711601/preview) | 8,414 |
| Chosen | [82712456](https://archiveofourown.org/works/82712456/preview) | 15,958 |
| Drumheller_Detour | [82712566](https://archiveofourown.org/works/82712566/preview) | 10,062 |
| Hypnotic_Claim | [82712801](https://archiveofourown.org/works/82712801/preview) | 9,809 |
| Not_So_Efficient_Studying | [82712821](https://archiveofourown.org/works/82712821/preview) | 13,602 |
| Overtime | [82712896](https://archiveofourown.org/works/82712896/preview) | 11,513 |
| Ruins_of_Breeding | [82712911](https://archiveofourown.org/works/82712911/preview) | 24,457 |
| The_Haunting_Desires | [82713001](https://archiveofourown.org/works/82713001/preview) | 30,480 |
| The_Silk_Threaded_Bonds | [82713066](https://archiveofourown.org/works/82713066/preview) | 13,904 |
| Velvet_And_Vice | [82713131](https://archiveofourown.org/works/82713131/preview) | 73,068 |
| Extra_Credit | [82713211](https://archiveofourown.org/works/82713211/preview) | 24,433 |
| The_Abstinent_Bet — Nice Version | [82713236](https://archiveofourown.org/works/82713236/preview) | 15,767 |
| The_Abstinent_Bet — Naughty Version | [82713271](https://archiveofourown.org/works/82713271/preview) | 9,704 |

All 13 are recorded in the publications table on the server with `status=draft`. Each is the canonical single-bulk-file shape (full story body HTML in one chapter, matching the IB convention) sourced from `HTML/<Story>_Clean.html`.

### Fixed — `ao3_client/client.py` was a pre-SQW codebase with multiple critical bugs

Before this session, the AO3 client was missing every refinement that landed on `sqw_client/client.py` over the past month. `create_work` was effectively broken — it would have failed validation if anyone tried to use it. The full list of fixes:

**1. `_get_page` retries on timeout/525.** AO3 from datacenter IPs sees frequent `ReadTimeout` and `525 origin SSL handshake fail` responses (about 1 in 5 requests). The previous implementation caught the exception, logged with an empty `str(e)` (the user saw `"AO3: Failed to fetch ...: "` with nothing after the colon), and gave up. Now retries 3 times with backoff, distinguishes 525s from timeouts in the logs, and still preserves a clean error path for hard failures (403/404/etc).

**2. `create_work` rewritten to mirror SQW's pattern.** The previous version sent:
```python
"work[archive_warning_string]": warning,    # SINGULAR — wrong field name
"work[category_string]": category,          # SINGULAR — wrong field name
# missing: work[author_attributes][ids][]   # REQUIRED — pseud_id
# missing: work[work_skin_id]
# missing: work[wip_length]
```
Now uses the correct OTW Archive form fields:
```python
"work[author_attributes][ids][]": pseud_id,            # extracted from /works/new HTML
"work[archive_warning_strings][]": warnings_array,     # plural with hidden empty value
"work[category_strings][]": categories_array,          # plural
"work[work_skin_id]": skin_id,
"work[wip_length]": "1",
"preview_button": "Preview",
```

The pseud_id extraction is critical — every OTW work must be linked to at least one author pseud via `work[author_attributes][ids][]`. Without it the form silently rejects with "Sorry! We couldn't save this work because: ...". The pseud is unique per user and is embedded in the `/works/new` HTML.

**3. `language_id="en"` was wrong.** AO3's form expects the numeric language ID (1 = English), not the ISO code "en". The previous code's "en" produced a server-side validation error: `"Language cannot be blank."` which was the first thing the new client hit even after the form-fields fix. Default is now `"1"`.

**4. Added `delete_work`, `is_work_in_drafts`, `is_work_published`.** Direct ports of the SQW versions. Critical for safety — without `delete_work` we can't auto-clean if a draft test goes wrong. Mirror the SQW confirm_delete flow (`_method=delete` + `commit=Yes, Delete Work`).

**5. State checks return tri-state (`True | False | None`).** AO3's `/users/<user>/works/drafts` page is **slow and times out frequently**. The SQW versions return `False` on fetch failure, which would cause the post-flight safety check to spuriously fire `not in_drafts` and try to delete healthy drafts. The AO3 versions distinguish:
- `True`  — fetched and present
- `False` — fetched and not present
- `None`  — fetch failed (network/timeout/CF) — caller cannot conclude

### Added — Smart safety logic in `AO3Poster.post()`

The post-flight verifier in `_verify_still_draft` was rewritten to handle AO3's flakiness:

```python
in_published = await client.is_work_published(work_id)
if in_published is True:
    # Confirmed published — abort + delete
elif in_published is None:
    # Fetch failed — trust preview_button (which guarantees draft state)
    logger.warning(...)
# in_published is False -> definitely safe
```

Before this fix, the first bulk-draft test ran into a real disaster:
1. `create_work` actually succeeded (work `82710971` created in preview state)
2. Post-flight `is_work_in_drafts` timed out 3 times → returned `None` (wrongly interpreted as `False`)
3. `is_work_published` also timed out → returned `False`
4. Safety check: `not in_drafts == True` → triggered abort
5. Auto-delete `delete_work(82710971)` was called
6. `delete_work` ALSO timed out and threw an exception with empty `str()`
7. The script reported `"DELETE FAILED: ."` and exited

The new logic only aborts on **positive** confirmation that the work is published. Since `create_work` exclusively uses `preview_button` (no `post_button` path exists in our client), publication is impossible by construction. Fetch failures are now logged-and-trusted.

### Added — `posting/platforms/ao3.py` rewritten as a SquidgeWorldPoster mirror

The previous `AO3Poster` was 187 lines of legacy minimal-viable code: no draft mode, no fandom passthrough, no warnings/categories/characters/relationships, no tag truncation, no safety checks, no publications tracking. Replaced with a 350-line implementation that mirrors `SquidgeWorldPoster`:

- Loads full StoryInfo from `story.json`
- Builds the OTW metadata bundle (fandom, warnings, categories, characters, relationships)
- Trims freeform tags to fit OTW's 75-tag total budget (`fandom + relationships + characters + freeform <= 75`)
- Reads single-bulk-file body HTML from `HTML/<story>_Clean.html` (with `SquidgeWorld/Chapter_*.html` concatenation as fallback)
- Posts via the new `create_work` with `preview_button`
- Smart post-flight safety check (see above)
- Returns standard `PostResult`

**Difference from SQW**: AO3 client doesn't yet have multi-chapter `create_chapter` or Work Skin support. For chaptered prose we use the IB-style **single bulk file** convention (`HTML/<Story>_Clean.html` is body-only HTML with all chapters as `<p>` elements in one big body). Multi-chapter `create_chapter` is the next deferred refactor if needed.

### Fixed — `_resolve_format_file` for AO3

Added `("HTML", "*_Clean.html", "html")` as the highest-priority entry in `PLATFORM_FORMAT_MAP["ao3"]`. The previous map only listed `Chapters/SoFurry_HTML/*.html` and `SquidgeWorld/*.html` — both per-chapter dirs. With the earlier `Chapters/` skip fix from 2.3.4, full-story AO3 requests now correctly resolve to `HTML/<story>_Clean.html`.

### Fixed — `StoryInfo.title` field for human display titles

`StoryInfo` was missing the `title` field from `story.json` (only `name` = folder name). `build_package` therefore derived titles via `story.name.replace("_", " ")`, which produced `"The Abstinent Bet/Nice Version"` (with a slash) when the story was loaded from a subfolder path like `The_Abstinent_Bet/Nice_Version`.

Added `title: str = ""` to `StoryInfo` and made `build_package` prefer `story.title` over the folder-name fallback. The two Abstinent Bet AO3 drafts that were posted with the slashy titles were retroactively fixed via `client.edit_work(work_id, title=...)`.

### Test files
- `tests/ao3_smoke.py` — login + list works (read-only smoke test)
- `tests/ao3_diagnose.py` — `_get_page` retry-vs-direct timing diagnostic (helped find the timeout-as-empty-error bug)
- `tests/verify_ao3_draft.py` — single-story draft test (Tombstone) with full safety verification
- `tests/bulk_ao3_drafts.py` — bulk-draft 11 missing stories (Extra_Credit + Abstinent_Bet versions failed and were retried)
- `tests/ao3_retry_failed.py` — retry script for the 3 stories that failed in bulk
- `tests/ao3_fix_abstinent_titles.py` — `edit_work` retroactive title fix for the 2 Abstinent Bet drafts
- `tests/check_ao3_pubs.py` — quick query helper

### Important: deployment status

**The refactor lives only in the running container's filesystem right now** — files were `docker cp`'d in for fast iteration, NOT pulled from a deployed git repo. The local repo has the same files. To make the refactor permanent across container rebuilds:

1. Commit the refactor (`ao3_client/client.py`, `posting/platforms/ao3.py`, `posting/story_reader.py`, the test files)
2. Push to GitHub
3. Run `pawupdate` (`gcloud ... git pull && docker compose up -d --build`)

Without that, the next `docker compose up` will pull the legacy AO3 code back from the image.

### AO3 access notes

- **Local desktop access**: shielded ("Shields are up!" CF JS challenge). No bypass via header tweaks. All AO3 testing must run from the GCP container.
- **GCP container access**: works most of the time but with frequent `ReadTimeout` and `525 origin SSL` errors. AO3's infrastructure is volunteer-run and intermittent. The new retry logic in `_get_page` handles this transparently.
- **AO3 throughput observations**: bulk-drafting 11 stories over 12 minutes hit ~1 in 6 form fetches that needed 2-3 retries to get through. One story (`Extra_Credit`) needed a full retry after exhausting all 3 attempts on the same form fetch.

---

## [2.3.4] - 2026-04-08

### Added — Inkbunny Bulk Drafting + `story_reader` Fixes

**Bulk Inkbunny upload** — Posted 5 missing stories as HIDDEN DRAFTS to KnaughtyKat's IB account in a single run via `tests/bulk_inkbunny_drafts.py`:

| Story | Submission | Words | Tags |
|---|---|---|---|
| Chosen | [3847118](https://inkbunny.net/s/3847118) | 15,958 | 105 |
| Not_So_Efficient_Studying | [3847119](https://inkbunny.net/s/3847119) | 13,602 | 57 |
| Overtime | [3847120](https://inkbunny.net/s/3847120) | 11,513 | 88 |
| Ruins_of_Breeding | [3847121](https://inkbunny.net/s/3847121) | 24,457 | 92 |
| The_Haunting_Desires | [3847122](https://inkbunny.net/s/3847122) | 30,480 | 108 |

Plus the previously-rebuilt **Tombstone** ([3847083](https://inkbunny.net/s/3847083), 8,414 words, 75 tags) which was registered into the publications table during this run.

After this run, the `publications` table holds 6 IB rows — every Tombstone, Chosen, NSE Studying, Overtime, Ruins, and Haunting record knows its IB submission_id and can be edited or replaced from the dashboard.

**Bulk-draft script safety:**
- Pulls every published submission via `client.search_user_submissions()` and aborts if any local target's display title overlaps with a live work — protects the 9 already-published stories from accidental overwrite.
- Sets `extra["draft"] = True` on every package so visibility is omitted (IB defaults hidden).
- Verifies each post via `get_submission_details()` (title, page count, keyword count) before recording.
- Records each result via `upsert_publication()` so the registry is the single source of truth.

**Empirical finding:** Inkbunny accepts at least 108 keywords on a single submission. The previously-assumed 75-keyword cap is wrong — no truncation needed. (NSE Studying sent 58 tags and IB returned 57; one duplicate or empty was silently dropped server-side, not a hard limit.)

### Fixed — `story_reader` resolved chapter file instead of full-story file

`posting/story_reader.py:_resolve_format_file()` was returning the wrong file when called with `chapter_index=0`. The IB format spec is:

```python
"ib": [
    ("Chapters/BBCode", "*.txt", "bbcode"),   # per-chapter
    ("BBCode", "*_bbcode.txt", "bbcode"),     # full story
],
```

For full-story requests, the loop iterated specs in order, hit `Chapters/BBCode` first, found that `*.txt` matched any chapter file, and returned `Chapter_1_*_bbcode.txt`. The full-story spec was never reached.

**Fix:** when `chapter_index == 0`, skip any subdir whose path contains `Chapters/`. Per-chapter directories are inherently chapter-only and should never serve full-story requests.

```python
else:
    # Full-story file — skip per-chapter subdirs (Chapters/...)
    if "Chapters" in subdir.split("/"):
        continue
    ...
```

This bug masqueraded as a successful upload — IB submission 3847080 was created from chapter 1 only and verification reported `pages=1` correctly. Caught only by inspecting `file_path` in the script output. The user-visible result: posting any story via `build_package(story, 0, "ib")` would silently upload chapter 1 instead of the full bulk file. Now fixed for IB and — by extension — every other platform with the same `Chapters/...` + `BBCode/...` spec ordering (FA, Weasyl).

### Fixed — `story_reader` thumbnail auto-detection when `images.cover` empty

Stories with thumbnails sitting at the story root but no `images.cover` entry in `story.json` (the common case — `<story>_thumbnail_full_series.png` is the convention) returned `thumbnail_path = None`. The IB poster then uploaded with no thumbnail.

**Fix:** when `images.cover` is empty, glob the story root for common thumbnail naming patterns:
- `*_thumbnail_full_series.*`
- `*_thumbnail.*`
- `*_cover.*`
- `thumbnail.*`
- `cover.*`

First match wins, restricted to `.png/.jpg/.jpeg/.gif`. Verified end-to-end: Tombstone's `tombstone_thumbnail_full_series.png` was auto-detected and attached to submission 3847083, and IB returned a populated `thumbnail_url_huge` after the post.

The 5 newly drafted stories don't have thumbnail files yet, so they posted thumbnail-less — they can be added via the IB UI later.

### Inkbunny Tombstone single-bulk-file rebuild

Replaced the experimental two-page Tombstone test (3847063 → deleted) with a clean single-file submission:
- Submission **3847083** = full Tombstone bulk file (`BBCode/Tombstone_bbcode.txt`, 49,200 bytes, all 3 chapters in one BBCode)
- Title `Tombstone`
- Description: 30-word version from `story.json`
- 75 IB keywords
- Auto-detected thumbnail attached
- Stays HIDDEN — ready for live submission whenever

This is the canonical IB shape for chaptered stories: one submission, one bulk file with chapter dividers, one thumbnail. IB's per-page navigation is for multi-image art, not for chaptered prose where the story field is a single blob anyway.

### Test files
- `tests/verify_inkbunny_bulk_rebuild.py` — Tombstone single-file rebuild verification
- `tests/bulk_inkbunny_drafts.py` — bulk-draft 5 missing stories with safety guards

---

## [2.3.3] - 2026-04-08

### Added — Work Skin CSS Auto-Refresh

`SquidgeWorldPoster._ensure_work_skin()` now **always pushes the current local CSS to SquidgeWorld** on every `post()` and `edit()` call, not just when creating a new skin. Previously, if a Work Skin already existed by title, the poster would return its skin_id and skip the update — meaning local CSS edits would never propagate.

**New behavior:**
1. If no `Work_Skin.css` for the story → return `''` (no skin applied)
2. If skin doesn't exist by title → create new with current CSS
3. **If skin exists → call `client.edit_work_skin()` to push the current CSS and description** (auto-refresh, best-effort — if the edit fails, log a warning but still return the skin_id so the work can use the existing skin)

**Verified end-to-end** with a sentinel-color test:
- Modified Tombstone's `Work_Skin.css` locally (replaced `#5a7a52` with `#abcdef`)
- Called `SquidgeWorldPoster.edit("91390", package)`
- Confirmed `#abcdef` was present in the live SQW skin CSS
- Auto-restored original

**Note:** SquidgeWorld (OTW Archive) **strips CSS comments server-side** as part of its sanitization. This is intentional on their end and doesn't affect functionality. Don't rely on string-equality comparisons between local CSS files and the live skin CSS — strip comments from local before comparing.

---

## [2.3.2] - 2026-04-08

### Added — Work Skins for the 3 Stories That Were Missing Them

Created `Work_Skin.css` for Drumheller_Detour, The_Haunting_Desires, and Velvet_And_Vice, then uploaded them as Work Skins on SquidgeWorld and applied them to the live drafts via `SquidgeWorldPoster.edit()`:

- **Drumheller_Detour Skin** (id 2827) — Badlands Dust theme: dark brown background (#1c1510), warm cream text (#e0d5c8), badlands orange accents (#c17817). Includes `.comic-panel` / `.comic-caption` rules for the story's embedded illustration images.
- **The Haunting Desires Skin** (id 2828) — Haunted Dark theme: near-black background (#08090e), warm grey text (#d0ccc8), antique gold accents (#c8a050).
- **Velvet And Vice Skin** (id 2829) — Velvet Noir theme: dark wine background (#100808), warm off-white text (#e2dad0), deep burgundy primary (#8b1a1a), copper secondary (#b87040). Handles both `<p class="chapter-heading">` and `.chapter-heading` since V&V uses the `<p>` variant.

All 3 skins were uploaded via `client.create_work_skin()` and applied through the existing `SquidgeWorldPoster.edit()` flow which auto-detects draft/published state. All 3 stories stayed in draft state throughout.

After this change, every SquidgeWorld work has a custom Work Skin matching its story's theme.

---

## [2.3.1] - 2026-04-08

### Added — SquidgeWorld Bulk Upload + Description Cleanup + Safety Hardening

**Bulk SquidgeWorld upload** — Posted 7 missing stories as DRAFTS to SquidgeWorld in a single run:
- Tombstone (91390, 3 chapters)
- Drumheller_Detour (91391, 8 chapters)
- Not_So_Efficient_Studying (91393, 3 chapters)
- Overtime (91394, 4 chapters)
- Ruins_of_Breeding (91395, 6 chapters)
- The_Haunting_Desires (91396, 8 chapters)
- Velvet_And_Vice (91397, 9 chapters)
- Total: **41 new chapters added**. All verified to stay in draft state throughout.

**Safety infrastructure** added to prevent accidental publishing:
- `SquidgeWorldClient.delete_work(work_id)` — emergency cleanup mechanism via the `/works/{id}/confirm_delete` form (POST `_method=delete` + `commit=Yes, Delete Work`).
- `SquidgeWorldClient.is_work_in_drafts(work_id)` / `is_work_published(work_id)` — state check helpers that query `/users/{user}/works/drafts` and `/users/{user}/works`.
- `SquidgeWorldPoster.post()` now has post-flight draft-state verification after `create_work` AND after every `create_chapter`. If the work ever leaves draft state, it's **automatically deleted** and the call fails. Opt out with `package.extra["allow_publish"] = True`.
- `SquidgeWorldPoster.edit()` now **auto-detects** whether the work is draft or published and uses the matching submit button (`save_button=Save As Draft` for drafts, `post_button=Post` for published), then verifies the state didn't change after the edit. Opt out with `package.extra["allow_state_change"] = True`.

**`SquidgeWorldClient.create_chapter` simplified and fixed:**
- The previous `publish=False` path was broken (tried a two-step preview→save flow that returned 400 because it didn't resend the chapter fields).
- **Verified empirically** that a single `preview_button=Preview` POST creates the chapter fully AND leaves the work in its current state. No follow-up `save_button` click is needed. Confirmed via `tests/test_chapter_after_preview_only.py` — the new chapter is present in `get_chapter_ids()` after the preview POST with no state change.
- `publish=True` still uses `post_without_preview_button=Post` which DOES publish the work (never call this on drafts).

**Description cleanup** — Updated 9 story.json `description` fields to be ≤30 words and ≤2 sentences for cleaner platform listings:
- Chosen: 40w → 30w
- Drumheller_Detour: 39w → 28w
- Not_So_Efficient_Studying: 29w → 28w (merged to 2 sentences)
- Overtime: 64w → 26w
- Ruins_of_Breeding: 31w → 23w
- The_Haunting_Desires: 31w → 29w
- The_Silk_Threaded_Bonds: 35w → 29w
- Tombstone: 56w → 30w (4 sentences → 2)
- Velvet_And_Vice: 35w → 29w (3 sentences → 2)
- Extra_Credit and Hypnotic_Claim already fit the target (28w and 27w respectively)
- All changes pushed live to SquidgeWorld via the refactored `SquidgeWorldPoster.edit()` (drafts stayed drafts, Chosen stayed published)

**Bulk upload test infrastructure (`tests/`):**
- `verify_draft_chapter_safety.py` — creates a throwaway draft, verifies draft state, adds a chapter via `publish=False`, verifies still draft, deletes. Always cleans up.
- `test_chapter_after_preview_only.py` — proved the preview POST alone is sufficient (the fix that made `create_chapter(publish=False)` actually work)
- `inspect_draft_chapter_form.py` — dumps the fields OTW Archive expects on the chapter preview page
- `post_missing_stories_to_sqw_drafts.py` — bulk-upload script with fuzzy title matching, dry-run, per-story confirmation, and post-flight safety checks
- `verify_all_drafts.py` — sequential read-only audit of all draft works, comparing each against its `story.json`
- `update_descriptions_and_push.py` — updates story.json descriptions and pushes them to SquidgeWorld

### Fixed
- **`edit_chapter`** had a silent-failure bug — the original partial-fields approach sent `_method=patch` + a few fields + a generic `commit=Update` button. This matched nothing the OTW form expected and sometimes returned 200 with no actual save. Fully refactored to the safe form-fetch pattern: GET `/works/{id}/chapters/{ch_id}/edit`, extract every `chapter[*]` field with its current value (inputs, selects, textareas), override only the requested fields, POST with the appropriate submit button (auto-detected: `save_button` for drafts, `post_without_preview_button` for published), strict success check for "successfully updated" flash.

### Known Issues / Follow-ups
- **Chosen work_skin fandom drift**: OTW Archive's tag wrangler auto-canonicalises `Kung Fu Panda` → `Kung Fu Panda - Fandom`. The story.json stays as `Kung Fu Panda` and SQW adds the suffix server-side. Not a bug, just informational.
- **Character/relationship tag canonicalisation**: OTW converts `(Original Character)` to `[Original Character]` or appends `[OC]`. Same — server-side transformation, not a client bug.
- **Missing Work_Skin.css for 3 stories**: Drumheller_Detour, The_Haunting_Desires, Velvet_And_Vice have no `Work_Skin.css` in their `SquidgeWorld/` folder. These stories were uploaded without a custom work skin (they use the default OTW styling). Create work skins for them as a follow-up if desired.
- **Tag curation** — current behavior dumbly truncates to first N tags to fit the 75-tag OTW limit. Smart prioritisation or dedicated `tags.sqw` lists in `story.json` would be better, but deferred.

### Verification
- All 8 stories on SquidgeWorld verified sequentially via `verify_all_drafts.py` — correct title, fandom, rating, warnings, categories, characters, relationships, tag counts, chapter counts, and draft/published state.
- `The Silk-Threaded Bonds` correctly matched as pre-existing via fuzzy matching (`The Silk Threaded Bonds` in story.json vs `The Silk-Threaded Bonds` on SQW — hyphen difference).
- Description updates pushed live, auto-detected draft state for each work, preserved existing state.

---

## [2.3.0] - 2026-04-07

### Added — SquidgeWorld Posting: Full Refactor + Live Verification

**SquidgeWorldClient (`sqw_client/client.py`):**
- `find_work_skin_by_title(title)` — looks up an existing Work Skin by title from `/users/<user>/skins?skin_type=WorkSkin`, returns skin_id or None
- `create_work_skin(title, css, description, public, role)` — POSTs to `/skins` to create a new Work Skin. Handles `skin_type=WorkSkin` field and the multipart form structure.
- `get_or_create_work_skin(title, css, description)` — find-or-create wrapper. Idempotent.
- `edit_work_skin(skin_id, title, description, css, public)` — safe form-fetch pattern. Extracts every `skin[*]` field from `/skins/{id}/edit`, overrides only the requested fields, POSTs back with `_method=patch` and `commit=Update`. Includes the strict success check.
- `create_work` — added `warnings: list[str]`, `categories: list[str]`, `work_skin_id`, `chapter_title` parameters. Defaults to `warnings=["No Archive Warnings Apply"]`. Now extracts the author pseud ID from the form (required field that was missing). Sends form data via `urlencode(doseq=True)` + `content=` because httpx 0.28.1 has an `AsyncClient` bug with list-of-tuples in `data=`. Backwards compat shims for old `warning`/`category` single-string parameters.
- `edit_work` — full refactor. Uses safe form-fetch pattern: GET `/works/{id}/edit`, extract every `work[*]` field with current value (handles inputs, selects, textareas, radios, checkboxes), override only the requested fields, POST back with `_method=patch` and `save_button=Save As Draft` (or `post_button=Post` if `save_as_draft=False`). Strict success check looks for explicit "successfully updated" flash and raises with the OTW error block if not present. **This was the silent-fail bug** — previous version only checked for "have not been saved" but missed cases where the form was rejected for other validation reasons.
- `edit_chapter` — full refactor. Same safe form-fetch pattern as `edit_work`. Auto-detects whether the form has `save_button=Save As Draft` (draft work) or `post_without_preview_button=Post` (published work) and uses the right one. Strict success check.
- `create_chapter` — **new**. POSTs to `/works/{id}/chapters/new`. **Safe by default**: uses `preview_button=Preview` then submits the preview's `save_button=Save As Draft` so adding a chapter to a draft work does NOT publish the work. Set `publish=True` explicitly to use `post_without_preview_button=Post` (which publishes the work for chapters added to a draft). This safety default was added after a session-mistake accidentally published Chosen.
- `_extract_work_form_fields(html)` — module-level helper that parses every `work[*]` field from a `/works/{id}/edit` page (inputs, selects, textareas with HTML entity decoding). Used by `edit_work` to safely extract current state.

**Story reader (`posting/story_reader.py`):**
- `StoryInfo` dataclass extended with: `rating`, `fandom`, `category`, `categories: list[str]`, `warnings: list[str]`, `characters: list[str]`, `relationships: list[str]`, `work_skin_path: Path | None`. The `__post_init__` ensures lists are never None and falls `categories` back to `[category]` if only the legacy single-string was set.
- `_load_from_story_json` populates all the new fields from `story.json`. Handles legacy `category: str` vs new `categories: list[str]`. Auto-detects `Work_Skin.css` at `<story>/SquidgeWorld/Work_Skin.css`.

**SquidgeWorldPoster (`posting/platforms/squidgeworld.py`) — full refactor:**
- `post()` — now multi-chapter, full-metadata, work-skin-aware. Loads `StoryInfo` via `story_reader.load_story` (just needs `package.story_name`). Finds or creates the Work Skin from `Work_Skin.css`. Trims freeform tags to fit OTW's 75-tag limit (fandom + relationship + character + freeform). Calls `client.create_work` with all metadata for chapter 1, then iterates remaining chapters and calls `client.create_chapter(publish=False)` to keep the work in draft state. Returns `PostResult` with the work_id.
- `edit()` — same shape. Refreshes the Work Skin, edits work metadata via `edit_work` with full metadata, then iterates `client.get_chapter_ids(work_id)` and calls `client.edit_chapter` for each with the corresponding archive file content.
- `_trim_freeform_tags()` — calculates the OTW 75-tag budget (75 - fandoms - relationships - characters) and trims freeform tags to fit.
- `_read_chapter_content(story, ch_idx)` — resolves chapter content by looking first in the story's `SquidgeWorld/` dir (preferred body-only HTML), then falling back to `Chapters/SoFurry_HTML/`.
- `_ensure_work_skin(client, story)` — handles the work skin lifecycle. Returns `skin_id` or empty string if no `Work_Skin.css` is present.
- `_rating_to_sqw()` — maps internal rating values to OTW canonical ("explicit" → "Explicit").

**Test scripts (under `tests/`):**
- `live_test_sqw_draft.py` — exercises the create-draft flow against Chosen Ch1
- `live_test_sqw_edit.py` — full safe form-fetch pattern reference for edits
- `live_test_sqw_full.py` — Work Skin creation + work edit pipeline
- `live_test_sqw_chapters.py` — adds chapters and updates skin metadata
- `live_test_sqw_finalize.py` — clean-up flow for taking a draft to a polished published state
- `live_test_sqw_reupload_chapters.py` — uses `edit_chapter` to update all chapters of a work
- `live_test_sqw_poster.py` — end-to-end test of `SquidgeWorldPoster.edit()` against the live work
- `regen_chosen_sqw.py` — regenerates Chosen's SquidgeWorld body HTML files using the wrapper from the existing files + paragraphs from the regenerated SoFurry HTML

### Fixed
- **httpx 0.28.1 AsyncClient + list-of-tuples bug** — `data=[(k,v),...]` raises "Attempted to send a sync request with an AsyncClient instance". Worked around in `create_work` and all new POSTs by URL-encoding manually with `urlencode(doseq=True)` and using `content=` with explicit `Content-Type: application/x-www-form-urlencoded`. The form data needs duplicate keys for `work[archive_warning_strings][]` and `work[category_strings][]` array fields, which is why a dict can't be used.
- **OTW Archive validation errors** that the previous edit_work silently ignored:
  - `Fandom, relationship, character, and additional tags must not add up to more than 75` — now caught by the strict success check; poster auto-trims freeform tags
  - `Only canonical warning tags are allowed` — fixed by sending `archive_warning_strings[]` (plural array) with canonical values like "No Archive Warnings Apply" instead of the old "Creator Chose Not To Use Archive Warnings"
  - `Work must have at least one creator` — fixed by extracting the author pseud ID from the form HTML and including it as `work[author_attributes][ids][]`
- **OTW Archive edit_work used wrong submit button** — `preview_button` only shows a preview, doesn't save. Fixed to use `save_button=Save As Draft` for drafts and `post_button=Post` for published works.
- **OTW Archive edit_chapter used wrong submit button** — same issue. Fixed to auto-detect `save_button` (draft) vs `post_without_preview_button` (published).
- **Accidentally published a draft work via `create_chapter`** during testing — `post_without_preview_button` on a chapter form publishes the entire work, not just the chapter. Fixed by making `create_chapter` safe-by-default with `publish=False` using a `preview_button` → `save_button` two-step pattern. To get the old behavior, callers must pass `publish=True` explicitly.

### Known Issues / Pending
- **Other platform posters not yet refactored** — IB, FA, SF, WS, BSKY, AO3, IK, DA still use their original implementations. IB/FA/SF were known to work in earlier sessions but haven't been retested with the new full-metadata `story.json` shape. AO3 uses the same OTW Archive software as SquidgeWorld so will likely need the same fixes.
- **Other stories' SquidgeWorld files** still need regeneration. Only Chosen has been redone for the live test. The mass regen for the other 10 stories is mechanical and pending.
- **Styled HTML files** for all stories also need regeneration since they're built from the same converter output and likely contain the same nested-asterisk bug.

### Live Verification — Chosen → SquidgeWorld
- Created draft work 91374 for Chosen via `client.create_work` (with all metadata pulled from story.json)
- Created Work Skin 2820 ("Chosen Skin") from `Chosen/SquidgeWorld/Work_Skin.css`
- Edited Work Skin metadata to add a proper title and description
- Added all 5 chapters via `create_chapter` (note: the initial test used the old `publish=True` behaviour and accidentally published the work — has been left published since the user accepted that state and the metadata was cleaned up properly)
- Verified `SquidgeWorldPoster.edit("91374", package)` end-to-end against the live work — full metadata + work skin + all 5 chapter contents updated in 23.4s in a single call

---

## [2.2.1] - 2026-04-07 — Converter Bug Fix + Mass Regeneration

### Fixed
- **Critical: nested-asterisk emphasis bug** in both `convert_md_to_sofurry_html.py` and `convert_md_to_bbcode.py`. The author convention is `*outer narration *emphasized_word* outer narration*` — single asterisks for both italic narration AND inner emphasis. The previous regex `\*(.+?)\*` matched the OUTER asterisks first (lazy regex), producing wrong-bolded paragraphs where the WHOLE paragraph became `<strong>` and the supposedly-emphasized word was the only un-bolded thing.
- The fix: added an `is_narration_wrapped(text)` check that detects single-asterisk wrappers (excluding `**` bold cases at start/end), strips the outer wrapper before running the inner emphasis regex, and re-applies `<em>` after.
- Also fixed the multi-segment dialogue path in both converters which had the same issue but only triggered when narration segments had >2 asterisks.

### Mass regeneration
- Ran the fixed converters across the entire `Archives/Complete_Stories/` tree
- 148 files regenerated (full-story BBCode + SoFurry HTML for each story, plus all per-chapter BBCode and SoFurry HTML files)
- 0 failures
- Affected stories (with the bug): Chosen, Drumheller_Detour, Extra_Credit, Hypnotic_Claim, Not_So_Efficient_Studying, Ruins_of_Breeding, The_Haunting_Desires, The_Silk_Threaded_Bonds, Velvet_And_Vice
- Unaffected: Tombstone, Overtime (recent stories that didn't use nested asterisks heavily)

### Tools
- `m_x/Scripts_Utils/test_emphasis_fix.py` — unit test demonstrating the bug and the fix
- `m_x/Scripts_Utils/regenerate_all_html_bbcode.py` — walks the archive and runs both converters on every MASTER.md and chapter .md

### Worst case before/after
- Chosen Chapter 4 had **86 `<strong>` tags** in the SquidgeWorld body file before the fix, with most paragraphs incorrectly bolded
- After the fix and regen: **49 single-word emphases** (the chapter genuinely uses lots of emphasis for intensity, but each is now a single word, not a wrongly-bolded paragraph)

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
