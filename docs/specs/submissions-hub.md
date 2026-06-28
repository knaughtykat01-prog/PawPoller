# Spec: Unified Submissions Hub (works library + gallery import)

**Status:** Phase 1 built (2.33.0, pending release); Phases 2–4 proposed
**Created:** 2026-06-28
**Targets:** post-2.32.0

---

## 1. Summary

A single **Submissions** hub that becomes the central place to see **every work** the user
has — stories *and* artwork — across all platforms, grouped **per work**, with a click-to-expand
per-work detail view (the same interaction as clicking a story today). **Stories** and **Artwork**
become **subtabs** (a segmented filter) of this hub rather than separate top-level destinations.
Views respect **persona / account separation** where the user has more than one.

It also adds the missing ability to **import existing gallery artwork** (image + metadata) from
platforms like FurAffinity and SoFurry, which is what turns a *discovered* submission into a
*managed* work.

## 2. Motivation

- Today the user must bounce between the **Stories** tab and the **Artwork** tab, and there is no
  single "everything I've posted" view.
- The **Artwork** tab is upload-and-post only — it cannot pull in art the user already has on
  FA/SoFurry/etc. (Stories *can* be imported from a URL; artwork cannot.)
- The pollers already **discover and store every submission** per platform for analytics, so a
  unified library is largely an aggregation + UI layer over data we already collect.

## 3. Goals / Non-goals

**Goals**
- One **Submissions** hub listing all works grouped per work, with `All / Stories / Artwork` subtabs.
- Per-work **detail view** reusing the existing story/artwork detail pattern.
- **Persona/account** filter where applicable.
- A **"discovered (unlinked)"** bucket for posts found by polling but not yet managed locally, with
  **link-to-existing-work** and **import** actions.
- **Artwork import** from platforms (image + metadata) into the local artwork archive.

**Non-goals (for now)**
- Auto-merging discovered cross-platform posts into one work without user action (no reliable key).
- Re-architecting analytics or the posting engine.
- Importing *stories* (already exists via the editor import flow) — only reused, not rebuilt.

## 4. Decided design

| Decision | Choice |
|---|---|
| Grouping | **Per work** (a work = one story or one artwork; shows its cross-platform publications) |
| Navigation | **Submissions** is the central hub; **Stories** + **Artwork** are subtabs (segmented filter). The old standalone nav items deep-link into the hub with that filter preselected, preserving the create/upload/import entry points. |
| Personas | Persona/account filter at the hub top, cascading to subtabs; shown only when >1 persona exists. |
| Discovered-only posts | Shown as **"discovered (unlinked)"** items until imported or linked to a work. |

## 5. The key constraint (read this before implementing)

**Per-work grouping is reliable only for works PawPoller manages.** Local stories
(`Complete_Stories` archive) and artwork (`artwork_reader` archive) are linked to their platform
posts through the **`publications` registry** (`publications` / `posting_queue` / `posting_log`,
keyed `UNIQUE(content_type, story_name, chapter_index, platform, account_id)` — note `content_type`
∈ {story, artwork} and `account_id` for personas). That registry is the per-work → per-platform join.

Posts made **outside** PawPoller and only *discovered* by polling have **no shared cross-platform
key**, so they cannot be auto-grouped into a single work. They appear individually in the
**discovered (unlinked)** bucket. **Import** (or **link-to-work**) is what promotes them into a
managed, grouped work.

## 6. Architecture

### 6.1 Data sources (already exist)

- **Local works:** stories archive + artwork archive (`posting/story_reader.py`,
  `posting/artwork_reader.py`).
- **Per-work → platform link + stats:** `publications` registry
  (`database/posting_queries.py`, `database/posting_schema.sql`), joined to the per-platform
  submission + snapshot tables for live stats.
- **Per-platform discovered submissions + stats:** `fa_submissions`, `sf_submissions`,
  `ws_submissions`, `submissions` (IB), `da_submissions`, `ik_submissions`, `ao3_submissions`,
  each with a type field (`category` / `content_type` / `subtype` / `type_name` → story vs art),
  `thumbnail_url`, and a full-image URL (`download_url` / `media_url` / `files[]`); time-series in
  the matching `*_snapshots` tables. Cross-platform iteration pattern already exists in
  `database/analytics_queries.py` (e.g. `get_trending_submissions`).

### 6.2 Backend

- **`database/analytics_queries.py`** — add `get_works(persona=None, type=None, search=None, sort=...)`:
  returns managed works (stories + artwork) each with aggregate stats + the platforms it's on +
  persona; and `get_discovered_unlinked(...)` returning per-platform submissions with no matching
  publication row.
- **`routes/submissions_api.py` (new)**:
  - `GET /api/submissions` — list works (filters: `type=all|story|art`, `persona`, `search`, `sort`).
  - `GET /api/submissions/work/{content_type}/{name}` — per-work detail (publications + snapshots).
  - `GET /api/submissions/discovered` — discovered-unlinked bucket.
  - `POST /api/submissions/link` — link a discovered submission to an existing work.
- **Artwork import** — `posting/artwork_importer.py` (new), mirroring `posting/importer.py`
  (`import_from_{inkbunny,sofurry,furaffinity}`, `_find_existing_import` dedup by
  `(platform, submission_id)`). Fetch detail → download image bytes (httpx) →
  `artwork_reader.create_artwork(...)` with platform-mapped tags/titles/descriptions and a `source`
  block (`{platform, submission_id, account_id}`) for dedup/linking. New endpoints in
  `routes/artwork_api.py`: `GET /api/artwork/import/available?platform=&account=` (gallery filtered
  to art, minus already-imported) and `POST /api/artwork/import/{platform}/{submission_id}`.

### 6.3 Frontend

- **Nav restructure** (`frontend/index.html` sidebar + `frontend/js/app.js` `route()`): add a
  **Submissions** item; make **Stories**/**Artwork** subtabs (segmented control inside the hub) that
  also exist as deep-links (`#/submissions?type=story`, `#/submissions?type=art`). Routes:
  `#/submissions`, `#/submissions/work/{content_type}/{name}`, `#/submissions/discovered`.
- **Hub list** — render works grouped per work via a card grid (reuse
  `Components.submissionCardGrid` / `Components.submissionsTable`), with a filter bar:
  `[All|Stories|Artwork]` segmented control + persona selector + search + sort.
- **Per-work detail** — generalise the existing `posting.js renderStoryDetail` (header + totals strip
  + per-platform publications table with `buildSparkline`, best-performer 👑, stale/changed badges,
  view/update actions) and `artwork.js renderDetail` into one `renderWorkDetail(content_type, name)`.
  Add a **"Linked / discovered"** section: linked platform posts + any discovered-unlinked posts with
  **Import** / **Link to this work** buttons.
- **Reuse:** `Components.statCard`, `topList`, `dateRangeBar`, `buildSparkline`, `Utils.format*`,
  existing `.story-card-grid` / `.story-detail-*` / `.artwork-*` CSS.

### 6.4 Per-platform import capability

| Platform | List gallery | Download image | Metadata | Notes |
|---|---|---|---|---|
| **Weasyl** | ✅ | ✅ `media_url` | ✅ | Cleanest API — **first target** |
| **Inkbunny** | ✅ | ✅ `files[]` | ✅ | Session SID; fine on server |
| **FurAffinity** | ✅ | ✅ `download_url` | ✅ | **Datacenter-IP block** → run from desktop or CF Worker proxy |
| **SoFurry** | ⚠️ partial | ⚠️ | ✅ | `.data` endpoint; React/beta rewrite + auth = fiddliest |
| DeviantArt / Itaku | partial | thumb only | partial | lower priority |

Like AO3 imports, bulk image pulls are safest from the **desktop** (residential IP) for FA/SF;
Weasyl/IB are fine server-side. Surface this in the import UI.

## 7. Phasing

1. **Submissions hub** — per-work unified list (managed stories + artwork), `All/Stories/Artwork`
   subtabs, persona filter, reusing the per-work detail view. Read-only. *Highest value, lowest risk.*
2. **Discovered (unlinked) bucket + link-to-work** — surface poller-discovered posts; manual linking.
3. **Artwork import** — Weasyl + Inkbunny first, then FurAffinity + SoFurry. Promotes discovered → managed.
4. *(optional)* Bulk "import whole gallery"; DeviantArt / Itaku.

## 8. Edge cases & risks

- **Per-platform metric gaps** (FA/Itaku have no view counts) → render "—", don't zero-fill.
- **Dedup** on import: key on `(platform, submission_id)` via the artwork `source` block; skip/merge
  if already present (mirror `_find_existing_import`).
- **IP blocks / auth** (FA datacenter block, SoFurry beta rewrite) → desktop-run guidance + CF proxy
  fallback; never silently fail an import (report per-item status).
- **Image storage** for imports lands in the artwork archive (Docker `/app/data/artwork` volume or
  desktop `m_x/Archives/Artwork`); account for disk on bulk import.
- **Stories vs Stories tab** — the standalone Stories tab keeps its authoring/import flows; the hub is
  the cross-platform "everything" view. Avoid duplicating the create flows; deep-link into them.

## 9. Touch-points (from the architecture research)

- Schemas: `database/{fa,sf,ws,da,ik,ao3}_schema.sql`, `database/posting_schema.sql`,
  `database/schema.sql` (IB `submissions`).
- Queries: `database/analytics_queries.py` (mirror `get_trending_submissions`),
  `database/posting_queries.py`.
- Pollers / clients (discovery + normalize): `polling/{platform}_poller.py`,
  `clients/{platform}/client.py` (`get_all_gallery_ids`, `_normalize_submission`).
- Story-import model to mirror: `posting/importer.py`, `routes/editor_api.py`
  (`/api/editor/import/{platform}/{submission_id}`, `/api/editor/import/available`).
- Artwork: `posting/artwork_reader.py` (`create_artwork`), `routes/artwork_api.py`.
- Frontend: `frontend/js/app.js` (`route()` + nav active logic), `frontend/index.html` (sidebar),
  `frontend/js/posting.js` (`renderUpload`, `renderStoryDetail`, `buildSparkline`),
  `frontend/js/artwork.js` (`render`, `renderDetail`), `frontend/js/components.js`
  (`submissionCardGrid`, `submissionsTable`, `statCard`), personas/accounts registry
  (`routes/personas_api.py`, `routes/accounts_api.py`).

## 10. Testing

- Backend: unit tests for `get_works` grouping (a work on N platforms → one row with aggregated
  stats), persona filtering, type filtering, discovered-unlinked detection, and import dedup.
- Import: per-platform fetch + create using recorded fixtures (no live creds in CI).
- Frontend: hub renders grouped works; subtab + persona filters; detail view parity with the
  existing story detail.

## 11. Effort (rough)

- Phase 1: moderate — one query + one route module + nav restructure + generalise two render
  functions, mostly reusing existing components.
- Phase 2: small-moderate — discovered query + link endpoint + a bucket view.
- Phase 3: per-platform — Weasyl/IB straightforward; FA/SoFurry are the fiddly ones (IP block, beta
  rewrite, auth).

## 12. Open questions

- Work-detail granularity for stories: surface per-chapter rows (as the story detail does today) or
  collapse to per-work-per-platform in the hub and expand chapters only in detail? *(Lean: hub shows
  per-work; detail keeps the existing per-chapter publications table.)*
- Should the standalone **Stories**/**Artwork** sidebar items remain visible, or collapse entirely
  into the Submissions segmented control? *(Lean: keep as deep-link subtabs for muscle memory.)*
