# Linking / Picker / Collections overhaul — spec & backlog

Captured 2026-07-14 from a product-review pass. This is the coherent cluster of
work around **selecting things, linking the same piece across platforms, tags,
and art**. Execute in the sequence below; each item is independently shippable.

## The unifying insight
Collections and Cross-Platform Links are the **same idea** — bundle one piece's
appearances across platforms and pool analytics. Collections is the richer model
(polymorphic members, tags, personas, companion story); Cross-Platform only adds
a **combined snapshot chart** and **auto-suggestions**. So: fold Cross-Platform
into Collections and retire it. Everywhere you *select* a work is the same UX
problem, solved once by a reusable visual **picker** modeled on the tag browser.

## Reference UX: the tag browser
`frontend/js/metadata_editor.js` — `openTagBrowser()` / `_mountTagBrowser()` /
`_renderTagBrowser()` / `_renderTagBrowserResults()`. A slide-in
`.tag-browser-modal` with: search input, category **filter chips** (with counts),
a paginated **results grid**, a **selected strip**, and a footer. This is the
template the user wants for the picker.

## Work items (sequenced)

### 1. Visual work-picker (`WorkPicker`) — FOUNDATION — ✅ DONE (2.111.0)
Replace the title-only scroll lists + `prompt()` selectors with a searchable
**thumbnail grid** modeled on the tag browser. Scales to 1000s via server-side
search.
- Data: `/api/works?search=` (returns `thumb_url` covers, supports search) +
  `/api/works/discovered` (thumbnailed submissions).
- Draft started at `frontend/js/work_picker.js` — **rework to the
  `.tag-browser-modal` pattern** (slide-in, filter chips for type/platform,
  selected strip, footer), reuse its CSS.
- Replaces: collections `_addMemberBrowser` (currently text list capped at 200),
  the cross-platform `prompt("platform:id,…")`, and any future "link to work".

### 2. Tag browser in the Art module (#2) — ✅ DONE (2.112.0)
The tag browser works in the story editor; wire the **same** browser into the
**Art posting/upload module** (artwork.js) so artwork gets the identical tag UX.
Shipped as **`frontend/js/tag_picker.js`** (`window.TagPicker`) — a *standalone*
picker reusing the `.tag-browser-*` chrome + `/api/editor/tags`, NOT a refactor of
the editor's `metadata_editor.js` browser (too coupled to `this.metadata.tags`).
Wired into `artwork.js` via a "🏷️ Browse tag library" button; lossless merge with
free-typed tags. `.tp-*` CSS in `editor.css`.

### 3. Collections ← Cross-Platform merge (chose: migrate then retire) — ✅ DONE (2.113.0)
- **Snapshot chart → Collections**: new `GET /collections/{id}/snapshots`. Refactor
  `analytics_queries.get_link_combined_snapshots` into a helper taking a list of
  `(platform, submission_id)` pairs; call it from both links and collections.
  Add a time-series chart to the Collections detail view.
- **Auto-suggest → Collections**: new `GET /collections/suggestions` (the deferred
  "unify-engine"). See item 4 for the engine.
- **Migrate + retire**: one-time migration of `submission_links` rows → collections;
  remove the Cross-Platform nav item + `renderCrossPlatform` + link components
  (`linkCards`/`linkSuggestions`/`viewLinkStats`). Keep `/api/links*` dormant or remove.

### 4. Auto-suggest v2 — title + **image** similarity (NATIVE, NO AI) — ✅ DONE (2.114.0)
Current `analytics_queries.auto_suggest_links` uses **title** Jaccard similarity.
Add **image** similarity via **perceptual hashing** (pHash/dHash): reduce each
artwork to a grayscale ~8×8 fingerprint, hash the gradient; same artwork across
platforms → small **Hamming distance**. Pure-Python on Pillow (already a dep) —
no ML model, no embeddings, no external service, runs locally. Store a hash per
artwork (compute on poll/import), compare by Hamming distance to suggest links.
Combine with title similarity for the merged suggestion engine.

### 5. Art workflow cleanup (#3 — "feels like a mess") — ✅ DONE (2.115.0)
Umbrella for the art experience. Shipped:
- **Discoverable delete** — the artwork *detail* page always had a Delete button,
  but it was buried (the "missing remove artwork" complaint was a discoverability
  gap). Now every library hub card has a hover **🗑 Delete** (confirm; published
  posts stay live). The upload screen's "Remove image" already clears a pending file.
- **Art shown in Collections** — `_location_from_submission` now returns each
  location's `thumbnail_url`; the collection detail's Locations table shows a
  thumbnail per posting and the hub card auto-covers from the first location with
  an image (`cover_thumb`/`cover_platform` in the summary). Fixes "Collections is
  missing the Artwork attached to the selected postings."

**Flagged for §7 scoping — the real structural "mess":** the Artwork hub groups
cross-posted art into "**masters**" via the *same* `submission_links` tables that
§3 just folded into Collections (`artwork.js._foldMasters` / Unify / Split →
`create_link`/`delete_link`). So art now has **two** grouping systems (masters vs
Collections). Consolidating masters → Collections is the right end-state but it is
a structural change that overlaps the removals work, so it is deferred to §7 where
the user wants to scope removals first — NOT done unilaterally.

### 6. Settings search (#8) — ✅ ALREADY DONE (2.103.0 — do NOT rebuild)
Verified in code 2026-07-14: a full cross-tab settings filter already ships.
`app.js._wireSettingsSearch` + the `#settings-search` search bar (placeholder
"🔍 Search settings…") rendered above the tabs in `renderSettings`; a non-empty
query shows all panels and hides `.settings-section`/`.settings-accordion` units
whose text doesn't match, eager-loading the lazy Polling/Logs tabs so they're
searchable too, with a live match count. Same "already exists" pattern as the
per-platform pause button and the polling grid.

### 7. Removals — scope before deleting (SCOPED WITH USER 2026-07-14)
- **Publishing module (#9) → ✅ DONE (2.116.0).** User clarified: it's the
  **Settings → Publishing tab**, and they only want a yes/no posting toggle, in
  **General**. Moved the whole Publishing + Server Sync panel into General (all
  element IDs preserved so handlers keep working), relabelled the toggle "Enable
  posting", removed the tab button, redirect old deep link. Reversible.
- **Submissions tab (#5) → ⏳ IN PROGRESS (7b).** User chose **"move extras to
  Library first, then hide Submissions"**. Extras to port from `submissions.js`
  onto the Library (`bookshelf.js`) screen: (1) the **＋ Collection** affordance on
  work cards, (2) the **discovered-art bucket** (`#/submissions/discovered` →
  `Submissions.renderDiscovered`), (3) **gallery import**. THEN hide Submissions
  from nav (keep route + module = reversible). Both list `/api/works`; Library is
  the cover-forward view, Submissions adds subtab filters/search/sort.

## Already done (verified — do NOT rebuild)
- **Per-platform pause button** (#10) — exists since 2.103.0 (inside each Polling
  accordion; the real gap is discoverability — surface it at the summary level).
- **Polling grid** (#11) — `.polling-grid` is already responsive
  (`minmax(340px,1fr)`); collapses to 1 col when narrow.
- **Cross-Platform "map" error** (#7) — user confirms it works now; not a bug.
- **Settings search** (#8, §6) — exists since 2.103.0 (`_wireSettingsSearch` +
  `#settings-search`). See §6.

## Platforms-grid note (#11)
The connect screen (Settings → Platforms) is vertical `<details>` accordions;
gridding them is awkward when expanded (grid reflow). Prefer surfacing status
compactly over forcing accordions into a grid.
