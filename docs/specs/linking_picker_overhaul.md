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

### 4. Auto-suggest v2 — title + **image** similarity (NATIVE, NO AI)
Current `analytics_queries.auto_suggest_links` uses **title** Jaccard similarity.
Add **image** similarity via **perceptual hashing** (pHash/dHash): reduce each
artwork to a grayscale ~8×8 fingerprint, hash the gradient; same artwork across
platforms → small **Hamming distance**. Pure-Python on Pillow (already a dep) —
no ML model, no embeddings, no external service, runs locally. Store a hash per
artwork (compute on poll/import), compare by Hamming distance to suggest links.
Combine with title similarity for the merged suggestion engine.

### 5. Art workflow cleanup (#3 — "feels like a mess")
Umbrella for the art experience. Depends on 1, 2, 4. Map the current art flow
(upload → tags → artwork hub → submissions → collections) and propose a cleaner
one. Clarify #1 "remove artwork" (there IS a hidden "Remove image" button that
appears after adding a file — confirm whether that's the gap or deleting a saved
artwork).

### 6. Settings search (#8)
A filter box over the settings sections/accordions.

### 7. Removals — scope before deleting (chose: scope with me first)
- **Submissions tab (#5)**: it's the `/api/works` library hub (also hosts
  "＋ Collection"). Map dependencies, then decide hide vs delete.
- **Publishing module (#9)**: clarify which surface (Stories/Posts/queue/history).

## Already done (verified — do NOT rebuild)
- **Per-platform pause button** (#10) — exists since 2.103.0 (inside each Polling
  accordion; the real gap is discoverability — surface it at the summary level).
- **Polling grid** (#11) — `.polling-grid` is already responsive
  (`minmax(340px,1fr)`); collapses to 1 col when narrow.
- **Cross-Platform "map" error** (#7) — user confirms it works now; not a bug.

## Platforms-grid note (#11)
The connect screen (Settings → Platforms) is vertical `<details>` accordions;
gridding them is awkward when expanded (grid reflow). Prefer surfacing status
compactly over forcing accordions into a grid.
