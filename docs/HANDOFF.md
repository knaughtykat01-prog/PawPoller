# PawPoller Session Handoff

**Last updated:** 2026-07-17
**Current version (master):** 2.153.0 — **Replace a Masterpiece's canonical image.**
Rhys asked for swapping in a better/higher-res file. `PATCH /images/{name}` is metadata-only, so this is a new
**`POST /api/masterpieces/{name}/image`** (multipart) + **⇪ Replace image** under the detail hero. **Keeps the record**
(masterpiece.json + every `masterpiece_members` link → pooled stats carry over); only the hero pointer (`image`) moves.
**Non-destructive** — the old file stays as a 2.152 gallery alternate, and a colliding filename saves as `name_v1.ext`
(the hero can never be clobbered). Drops the cached `__mp__` hash so the de-dup finder re-reads the NEW pixels. Same
50 MB cap + extension allowlist as the uploader. +3 tests.
**Also confirmed (no code needed):** uploading artwork **without** posting already works — Create → New artwork →
*"Save to library"* (vs *"Save & publish"*).

**Prior — 2.152.0 — Masterpiece detail gallery (see every image in the set).**
`GET /api/masterpieces/{name}` now returns `images:[...]` (every folder image, hero first); the detail page renders a
**gallery strip** under the hero when there are 2+ (click swaps the hero; `.mp-alts` CSS). Shipped alongside the art
audit's data ops on prod: the **13 recovered multi-image set-images** pushed into their server folders (birthday
dedication variant, Kinar×Tigress, 2nd Vektorich piece, dash-of-seed, Franubis body-writing) and the **6 duplicate
pairs merged** (55 → 49 folders; byte-identical verified; cat-censored daki + PFP test render preserved as alts in
their survivors). +2 tests. NOTE: Self_Serving_Pt_1 / Self_Served_Pt_2 are DIFFERENT images (before/after) that hash
near-identically — if the dup finder flags them, hit ✗ Not the same.

**Prior — 2.151.0 — Image Tool + stop duplicate Masterpieces forming.**
Backlog **J**: new **`#/imagetool`** (Create → Image Tool) — crop / rotate / flip / resize-by-longest-edge / ⬛ censor /
▨ pixelate, undo (12-deep), export PNG·JPEG·WebP + quality, exits via Download / Send to Posts / Save as **new** artwork.
Entirely client-side canvas; `_work` (offscreen canvas) is the source of truth and `_toWork()` maps pointer→image pixels.
**Non-destructive** — never overwrites the source. Backlog **M**: ★ Master now pre-checks the piece's thumbnail hash
against Masterpiece hero hashes (`GET /api/masterpieces/match`) and **offers** to link into the existing Masterpiece
instead of minting a duplicate — a **prompt, never automatic** (SFW/NSFW edits of one ref hash identically), best-effort
so a failed check never blocks the promote.

**Prior — 2.150.0 — Story detail: tabbed sections (one screen, not ten).**
Backlog **K** done. The Story detail stacked TEN sections (the real "endless scroll" complaint). Now the hero + pending
callout + totals stay visible and the rest sit behind tabs — *Platforms · Chapters · Tags · Timeline · History ·
Formats* (`posting.js renderStoryDetail`). Empty sections are filtered out (no dead tabs). **Platforms is first on
purpose** — the comparison chart lives there and Chart.js must size on a *visible* canvas. New reusable
`.det-tabs/.det-tab/.det-panel` in `components.css`. Masterpiece/Artwork details left alone (3–4 sections, already
tightened in 2.141; their chart would hit the same hidden-canvas issue). Also fixed `SITE_VERSION` drift (was 2.148.0).

**Prior — 2.149.0 — Masterpiece junk bin (kept-but-hidden status).**
Rhys's ask: a junk category "for arts it had pulled but is not needed or useful, or archived". New
`masterpieces.status` column (`''`/`'junk'`, guarded migration) + `mq.set_status/get_status/statuses`; new
**`POST /api/masterpieces/{name}/status`** (works for **index-only names** — the 13 swept-in tweets have no folder);
list + detail carry `status`. Grid hides junked pieces + gains a **🗑 Junk (N)** toggle view with per-card **♻ Restore**;
detail gets a **🗑 Junk / ♻ Restore** button + badge. Junking keeps folder/metadata/members — reversible, softer than
merge. +4 tests (`test_masterpiece_junk.py`). Companion to the standalone **art audit** (55 pieces named/described/
tagged, see `docs/BACKLOG.md` item O; deliverable `C:\Users\rhysc\claude\art_audit\review.html`) — the audit's 14 junk
finds are this feature's first customers.

**Prior — 2.148.0 — 4 more Overview widgets + Promo censor bars & Send-to-Posts.**
Backlog **H**: catalog 19 → 23 — **🌐 Platforms live**, **🥇 Best platform** (ranks by views so engagement-only platforms
can't win), **🗨 Recent comments** (activity filtered to comments), **⏳ Pending queue**. First two read a new `platRollup`
in `_dashCtx` (no extra fetch); queue adds one additive `getPostingQueue()`. Backlog **I** finished: Promo **censor bars**
(`censor:true` highlight → black bar painted *over* the words; `_hlColor`→`_hlFor`) and **💬 Send to Posts**
(canvas → `Posts._handoffFiles` → `#/posts/new` with the image attached). Frontend-only.

**Prior — 2.147.0 — Library performance sorts, per-metric stat links, Promo-from-story.**
Also (backlog **I**, partial): Promo Maker gained **📖 Pull from a story** — picks a story, loads `MASTER.md` via the
editor API, lifts your selected passage into the excerpt box (`_stripMd` strips metadata/headings/emphasis to clean
prose; highlights reset since offsets move). Censor bars + share-to-Posts remain open.
Backlog **G** closed. `/api/works` now uses `get_publications_with_stats`; `assemble_works.enrich` pools
views/favourites/comments per work (resolving `views|hits|reads` + `favorites_count|kudos|votes` per row, so AO3
reads/kudos land correctly; statless pubs → 0). Library gained **Most viewed / Most favourited / Most comments** sorts;
Overview stat cards deep-link per metric via the new **`#/library/sort/{key}`** route. +3 tests.

**Prior — 2.146.0 — Fix: SoFurry thumbnails/images now captured.**
SF submissions had no thumbnail anywhere — `clients/sf/client.py` `get_submission_detail` parsed stats from the beta
`/s/{id}.data` payload but hard-coded `thumbnail_url=""`. Now extracts the full CDN URL under `/submissions/thumbnails/`
(distinct from `/users/avatars/`); text works stay blank. CDN is hotlinkable (200, webp, no referer) so it renders direct.
Verified via the CF proxy (the `.data` endpoint 403s datacenter IPs directly). +2 tests. **Post-deploy:** force an SF poll
to backfill — `docker exec … python -c "import asyncio; from polling.sf_poller import run_sf_poll_cycle; asyncio.run(run_sf_poll_cycle(force_full=True))"`.

**Prior — 2.145.0 — "Not the same" — dismiss false-positive duplicate matches.**
Companion to 2.144's finder: a **✗ Not the same** button on each duplicate group persists every pair to a new
`masterpiece_not_duplicate` table (`mq.add_not_duplicate`, normalised); `duplicate_masterpiece_groups(dismissed=...)` skips
those edges so rejected look-alikes never regroup. New `POST /api/masterpieces/not-duplicate`; `/duplicates` passes
`mq.not_duplicate_pairs()` in. +1 test.

**Prior — 2.144.0 — Merge duplicate Masterpieces (perceptual-hash finder).**
Same image → two Masterpieces (e.g. "Ki's New Ref" twice). New **🔍 Find duplicates** (`#/masterpieces/duplicates`, button
in the Masterpieces grid bar): dHash each hero image (`image_hash.hash_masterpieces` under synthetic `__mp__`, self-pruning)
→ cluster by Hamming (`duplicate_masterpiece_groups`, union-find, ≤8) → merge each group into a survivor (most views/sites,
overridable) via `masterpiece_queries.merge_masterpieces` (folds site-links in, deletes the redundant record + folder).
New `GET /api/masterpieces/duplicates` + `POST /api/masterpieces/merge` (before `/{name}`). +3 tests. Follow-up:
auto-link on import so new dupes don't form.

**Prior — 2.143.0 — Ignore button added to the Library's discovered view.**
2.140's 🚫 Ignore existed only on the Artwork hub's discovered tiles; the primary review surface is
**`#/library/discovered`** (`Submissions.renderDiscovered`), which is unfiltered (the Artwork hub's `_PLATFORMS`
allowlist excludes X/Threads/etc.), so tweet/microblog art shows there. Added Ignore to each `_discRow` (`_ignoreOne`,
reuses the 2.140 endpoint) + an **Ignored** header link → `#/artwork/ignored`. Frontend-only. Masterpiece-member dedup
already applies to this view (both read `get_discovered_unlinked`).

**Prior — 2.142.0 — Navigation restructure: Create hub + Posts split.**
IA reshape (backlog F, Option A): **Create** group = New Story/New Artwork/New Post/Promo Maker; **Posts** is now a
view-only feed with composing moved to **`#/posts/new`** (`Posts.renderCompose`, redirects to feed on success); sidebar
"Publishing" → **Publish** (Stories·Artwork·Posts·Collections) with Queue/History moved to Insights & Tools. Library stays
the unified works catalogue. Also updated: sidebar active-state, Quick-actions widget, Posts tour (split `posts` +
`posts-new`), command palette. Frontend-only. **Deferred (Option B):** merging Library/Stories/Artwork into one hub.

**Prior — 2.141.0 — Detail pages: less scrolling (compaction pass).**
Conservative CSS-first density pass (backlog E, "detail poetization / no scrolling"): artwork detail cover column is
**sticky** (stays in view while reading the right column); story detail info card becomes a **2-col hero** (cover beside
body) when a cover exists — saves ~a screenful — via `story-detail-info--hascover` + a wide-screen rule (narrow/no-cover
unchanged); masterpiece `.mp-section` spacing tightened. Frontend-only. Follow-up if wanted: tabbed sections.

**Prior — 2.140.0 — Artwork hub: dedup Masterpiece members + Ignore list + multi-account Overview.**
(1) A discovered piece that's a **Masterpiece member no longer shows as a duplicate tile** — `get_discovered_unlinked`
subtracts `masterpiece_queries.all_member_pairs`. (2) New **🚫 Ignore** on discovered tiles → `ignored_submissions` table
(`database/ignored_queries.py`) + `POST/DELETE/GET /api/works/discovered/ignore[d]`; reversible via **Ignored** view
(`#/artwork/ignored`). (3) The **"By persona" multi-account widget now shows by default** on the Overview when you have 2+
accounts (was hidden behind ⚙ Customize). +3 tests. See `docs/BACKLOG.md` items B/C/D → Done.

**Prior — 2.139.0 — Instagram is now an artwork publish target.**
IG graduated from Posts-only to a first-class **artwork** target: new `posting/platforms/instagram.py` `InstagramPoster`
(wired into `manager._get_poster` + `artwork_reader._ALL_POSTER_IDS`), reusing the Posts module's public-image-hosting
path (`ig_media`: stash a web-safe JPEG at a public URL / relay to a paired server → Meta cURLs it → publish → cleanup).
Caption = description/title + sanitised hashtags (cap 30). **Post-only** (no IG edit API) → added to frontend `_PLATFORMS`
+ the `_POST_ONLY` sets so Masterpiece Sync skips it. +6 tests. Backend+frontend.

**📋 NEW: request tracker — `docs/BACKLOG.md`.** Every ask Rhys makes now gets a row there (single source of truth,
cross-session) so nothing slips. Update it when a request lands AND when an item ships (move to Done + version). Live
session progress also mirrored in the harness task list.

**Prior — 2.138.0 — Promo Maker (BookTok-style excerpt images).**
New **`#/promo`** tool (sidebar **Create → Promo Maker**): paste an excerpt, select phrases + tap a colour to highlight,
pick a gradient/photo background + size preset (Square/Portrait/Story), download a PNG. All **client-side canvas**
(`frontend/js/promo.js` + `promo.css`; wired into `index.html` + `app.js` router). This is backlog item 7
(marketing-image generator; reference was the pastel-highlight book-page card). Frontend-only. Follow-ups: source excerpt
from a story, per-word censor bars, "share to Posts".

**Prior — 2.137.0 — Four new Overview widgets.**
The customisable Overview board grew from 15 → 19 widgets (all opt-in via ⚙ Customize): **⚡ Quick actions** (create-flow
tiles), **📊 Engagement rate** (interactions/view + avg views/work), **🎯 Milestones** (progress bars to the next
round-number goal), **⭐ Spotlight** (top-performing work). All render from the cached `_dashCtx` — no new endpoints.
Frontend-only. (Backlog item 1 "more Overview widgets"; per-metric sorted stat-card destinations still open.)

**Prior — 2.136.0 — Artwork tab: filter/search + editable metadata.**
The Artwork hub gained a segmented filter (**All · In library · Discovered**, live counts) + a **title search** box
(`artwork.js render()` now stores `_hubItems`, re-renders via `_applyHubFilters()`). The standalone-artwork **detail page
is now editable** — Title/Description/**Rating**/Tags edit card PATCHing the existing `/api/artwork/images/{name}` (closes
the "change an artwork's rating" gap for standalone pieces; Masterpieces could already edit+sync). Frontend-only.

**Prior — 2.135.0 — Overview stat cards are click-through.**
The Overview headline stat cards (Submissions/Views/Faves/Comments/Downloads) now deep-link to the works library
(`#/library`) — `app.js _dashWidgetHtml` wraps each in a `[data-nav]` link (suppressed in ⚙ Customize). First step of the
"clickable widgets" ask (per-metric sorted destinations still to come). Frontend-only.

**⚠️ BIG-DUMP RE-RAISED (2026-07-17):** the user re-sent the original "enjoy haha" UI dump with 2026-07-16 screenshots
saying several things are "still" broken. **The screenshots are STALE** (they predate the deploys — proof: the
Platforms-in-Settings shot shows the OLD stacked list, but the card grid shipped 2.133.0 and is live; editor-centering
`editor.css:193` and the SquidgeWorld `sqw_author_* OR sqw_*` cred-check `editor_api.py:1286` are both present in current
code). **Tell the user to hard-refresh (PWA service worker may be caching).** Done-vs-undone ledger against the dump:
- **DONE + deployed:** choose-image button (2.122), editor toolbar wrap+center (2.122), artwork tag browser = story
  format (2.123), platforms-in-settings card grid (2.133), SquidgeWorld cred-key lock (2.122), the whole Masterpiece
  build 0–7, Collections grouping + multi-match suggest, multi-account Overview persona widget (2.132), AO3 525 logging.
- **GENUINELY UNDONE (backlog):** (1) Overview clickable widgets — *stat cards done in 2.135; per-metric sorted views +
  20 more widgets NOT done*; ~~(2) Artwork/Gallery filters + separations~~ **DONE 2.136**; (3) story/artwork/Masterpiece
  detail "poetization" (less scrolling); ~~(4) change rating of STANDALONE artwork~~ **DONE 2.136** (edit card on the
  artwork detail — title/desc/rating/tags); (5) IA: posting under **Create**, split **Submissions** (stories+art) from
  **Posts** (microblog catalogue), move Create-posts into Create; (6) **Instagram → art upload** (deferred — needs a
  net-new `IGPoster` adapter); ~~(7) marketing-image generator~~ **DONE 2.138** (Promo Maker `#/promo`, client-side
  canvas); (8) simple **image editor** (crop/resize/format/stickers/blur/censor) — future.
- **Overview widgets:** ~~(1) more widgets~~ stat click-through **DONE 2.135**, +4 widgets **DONE 2.137**; per-metric
  *sorted* stat-card destinations still open.

**Prior — 2.134.0 — In-app "What's new" popup on update + real GitHub Release notes. DEPLOYED.**
When the running version differs from the one this browser last saw (a desktop self-update **or** a server redeploy), the
app pops a changelog modal of what changed. New **`GET /api/whatsnew?since=<ver>`** (`routes/whatsnew_api.py`) parses the
**bundled** `CHANGELOG.md` (added to `pawpoller.spec` datas) and returns entries newer than the browser's last-seen
version (capped 12). Frontend (`app.js` `_maybeShowWhatsNew`/`_showWhatsNewModal`/`_mdLite`): tracks last-seen in
`localStorage['pp_seen_version']`, fires once per session on the first authenticated page (guard in `route()`), renders
via a **safe** markdown-lite pass (escape-first allow-list — no raw HTML reaches the DOM); first run is silent. Also
**fixed the GitHub Release notes**: CI (`build.yml`) now sets the Release body from the CHANGELOG entry
(`installer/changelog_extract.py` → `body_path`) on both build jobs, replacing `generate_release_notes` (which only
produced a bare compare link on this direct-commit repo). +5 tests (`test_whatsnew.py`). **v2.134.0 release cut** (tag).
When the running version differs from the one this browser last saw (a desktop self-update **or** a server redeploy), the
app pops a changelog modal of what changed. New **`GET /api/whatsnew?since=<ver>`** (`routes/whatsnew_api.py`) parses the
**bundled** `CHANGELOG.md` (added to `pawpoller.spec` datas) and returns entries newer than the browser's last-seen
version (capped 12). Frontend (`app.js` `_maybeShowWhatsNew`/`_showWhatsNewModal`/`_mdLite`): tracks last-seen in
`localStorage['pp_seen_version']`, fires once per session on the first authenticated page (guard in `route()`), renders
via a **safe** markdown-lite pass (escape-first allow-list — no raw HTML reaches the DOM); first run is silent. Also
**fixed the GitHub Release notes**: CI (`build.yml`) now sets the Release body from the CHANGELOG entry
(`installer/changelog_extract.py` → `body_path`) on both build jobs, replacing `generate_release_notes` (which only
produced a bare compare link on this direct-commit repo). +5 tests (`test_whatsnew.py`). **DEPLOY pending; then cut the
v2.134.0 release** (tag → CI) which also validates the new CHANGELOG-based notes. Backlog empty.

**v2.133.0 was CUT as a GitHub Release** (2026-07-17) to un-stall desktop self-update (had been stuck at v2.53.0) — CI
built all 3 assets (win zip + Setup.exe, Linux AppImage). Process recorded in memory [[reference_pawpoller_cut_release]]:
a release = **push a `vX.Y.Z` tag** → `build.yml`; `/pp-release` bumps+deploys the VM but does NOT push the tag.

**Prior — 2.133.0 — Settings → Platforms as a card grid. DEPLOYED.**
Frontend-only CSS (`components.css`): the Settings → Platforms connection accordions lay out as a responsive card grid
(mirrors the Platforms tab's `.hub-grid`) — collapsed = compact cards, an **open** one spans full-width for form room,
Session-health + footer full-width. Zero risk to the connect flow (no markup/id changed; accordions stay direct children
so `_enhancePlatformSettings` is untouched).

**Prior — 2.132.0 — Overview "By persona" multi-account widget. DEPLOYED.**
Opt-in Overview dashboard widget (`app.js` `_dashWidgetMeta`/`_dashWidgetHtml` + `_personasWidgetHtml`): one row per
**persona** — swatch · name · account count · pooled 👁/❤/💬 — linking to `#/persona/{id}`. `GET /api/personas` already
returns each persona with `stats.combined`; fetched in parallel with the events feed. Catalog-only (⚙ Customize → Add
widget), so existing dashboards are untouched. (#63 self-update VERIFIED live — check reaches the now-public repo, but
GitHub Releases stalled at v2.53.0 while code is at 2.13x, so desktop self-update needs releases cut — a build-pipeline
step, not a code fix.)

**★ THE MASTERPIECE BUILD IS COMPLETE — all 8 phases (0–7) shipped (2.124.0 → 2.131.0), DEPLOYED.** A single image now
has the master record a story always had: promote/create → publish (auto-links members) → edit once → sync to editable
sites → bundle into Collections. Spec `docs/specs/masterpieces.md`; architecture `documentation_guide.md` §20.10.
**Deferred follow-ups (not blocking):** a net-new `IGPoster` adapter so Instagram can be an artwork/Masterpiece target
(the artwork `post_artwork`/`_get_poster` path can't post to IG — IG posting lives only in the Posts module); and (§9)
materialise-on-migrate for index-only Masterpieces created by `migrate_links_to_masterpieces` (a callable, not
startup-wired). **#63 self-update: VERIFIED** on the live server — `check_for_update()` reaches the now-public repo,
compares correctly (2.13x > latest release v2.53.0 → no-update), resolves the asset URL; GUI wiring present. Finding:
GitHub Releases stalled at **v2.53.0** while code is at 2.13x — `/pp-release` bumps the version but hasn't been cutting
Releases, so desktop self-update has nothing new until releases are published (a build-pipeline step, not a code fix).

**Prior — 2.131.0 — Masterpieces Phase 7 (FINAL): retire old art-masters minting + links→Masterpieces migration. DEPLOYED.**
`artwork.js` stops minting `submission_link` masters (removed Select→Unify + "Possible matches" strip + methods/state,
~170 lines); dormant link display kept (`_foldMasters`/`_masterCard`/split — honours "keep `/api/links` dormant").
`auto_suggest_collections` stamps `target` (image→masterpiece, title→collection). `migrate_links_to_masterpieces`
(idempotent/reversible, callable NOT startup-wired — migrated masters are index-only/grid-invisible until materialised,
§9). Live had 0 `submission_links`. +5 tests.

**Prior — 2.130.0 — Masterpieces Phase 6: a Masterpiece can join a Collection. DEPLOYED.**
New `masterpiece` member type in `collection_members` (`member_ref` = bare name); `rollup_collection` folds a
Masterpiece's whole set of site-uploads into the Collection's pooled stats/tags/personas; snapshot pairs +
suggestion-exclusion handle it; lazy import avoids the cycle. **"＋ Add to Collection"** on the detail (existing
document-level delegate); **WorkPicker** gains a Masterpieces source chip. §1.2 boundary holds. +3 tests.

**Prior — 2.129.0 — Masterpieces Phase 5: edit the canonical record once, sync everywhere. DEPLOYED.**
Editable canonical form (title/description/rating/characters/tags + TagPicker) → `PATCH /api/masterpieces/{name}` →
`save_artwork_metadata` (preserves per-platform tag overrides via new `read_raw_metadata`). **Sync-all**:
`manager.update_artwork` (mirrors `update_story`, off `masterpiece_members`, metadata-only — `skip_content_refresh`)
edits `supports_edit` members; Bluesky/e621/Itaku are skipped **post-only**. Async `POST /{name}/sync`; **↑ Sync to
sites** saves then pushes behind a confirm. Finding: per-platform `edit()` already handle artwork metadata → new
orchestration, not net-new posting code. +5 tests.

**Prior — 2.128.0 — Masterpieces Phase 4: publishing IS mastering + fresh create (post-only). DEPLOYED.**
`post_artwork` auto-links a `masterpiece_member` on each successful post (`linked_via='publication'`, account carried)
— a fresh master accumulates members as it publishes; idempotent + best-effort. **"＋ New Masterpiece"** on the grid
→ the `#/artwork/new` uploader. **e621** added to `artwork_reader._ALL_POSTER_IDS`; **IG deliberately not** (needs a
net-new `IGPoster` adapter — the artwork path can't post to IG). +2 tests.

**Prior — 2.127.0 — Masterpieces Phase 3: promote flow + same-image linking (first write surface). DEPLOYED.**
**"★ Master" on Gallery discovered tiles** → `POST /api/masterpieces {from:{…}}` → `promote_from_submission` (reuses
`artwork_importer.import_artwork`, idempotent), seeds the source as **primary** member (account carried), stores the
canonical **pHash**. Detail view interactive: **"Link the same image elsewhere"** suggestions (`GET /{name}/suggestions`
→ anchored native dHash), **＋ Link** / **↻ Scan** (`hash-scan`) / **✕ unlink**; attach (`POST /{name}/members`) /
detach re-pool live. `api.js` +4; document-level click delegate. +4 tests (`test_masterpiece_promote.py`).

**Prior — 2.126.0 — Masterpieces Phase 2: managed grid in Library + read-only detail view. DEPLOYED.**
First user-visible surface (frontend-only, over the Phase 1 read API). Library shelf (`bookshelf.js`) gains a 4th type
segment **All / Stories / Artwork / Masterpieces**; the Masterpieces segment delegates the grid to
**`frontend/js/masterpieces.js`** (`renderGrid`) — a card per Masterpiece (canonical cover · title · N sites · pooled
stats · persona dots). Cards link to a read-only detail (`#/masterpieces/{name}`): image hero + pooled headline + a
Canonical record panel + a Published-to Locations table + combined chart. `api.js` +3; `app.js` routes both; new
`masterpieces.css`. Additive (existing segments untouched).

**Prior — 2.125.0 — Masterpieces Phase 1: membership model + cross-site rollup + read API. DEPLOYED.**
New **`masterpiece_members` table** (`database/db.py`) — NAME-keyed membership, PK `(masterpiece_name, platform,
submission_id)` (idempotent, spec §0-A2), carrying `account_id`/`role`/`linked_via`; stats resolve live against the
`*_submissions` tables at rollup, like a Collection's members. New **`database/masterpiece_queries.py`** — membership
CRUD + `rollup_members` + `summarize`, **reusing `collections_queries`' per-platform normalisation** so a Masterpiece
and a Collection pool identically. New **`/api/masterpieces`** read API (`routes/masterpieces_api.py`, wired in
`dashboard.py`): list + `/{name}` (canonical merged with rollup) + `/{name}/snapshots`. +7 tests.

**Prior — 2.124.0 — Masterpieces Phase 0: `masterpiece.json` (back-compat artwork rename). DEPLOYED.**
No behaviour change. `posting/artwork_reader.py` reads BOTH `masterpiece.json` and legacy `artwork.json` (new
`_meta_path`, prefers the new); writers emit `masterpiece.json` and migrate a folder on first edit (retiring the
legacy file — strict superset). New `characters` field (parity with `story.json`). New name-keyed `masterpieces`
index table (spec §0-A2). `artwork_importer.find_existing` uses `import_source` from `list_artworks`. +4 tests.

**Prior — 2.123.0 — Artwork tag browser now matches the story tag browser.**
The artwork uploader's "Browse tag library" picker (`TagPicker`, `tag_picker.js`) rendered compact name+category
chips; it now renders the story editor's richer `.tag-browser-card` layout (name + coloured category badge +
description + ＋Add/✓Added), with All/Selected + per-category count chips and a "Selected: N" footer, reusing the
exact `.tag-browser-*` CSS. Frontend-only; reusable everywhere `TagPicker` is used. **DEPLOY pending.** First item
of the UI-polish track (remaining: story/artwork detail tightening + artwork ratings, Platforms-in-Settings card
layout, Artwork gallery filters). **Masterpiece spec DRAFTED** at `docs/specs/masterpieces.md` (masterpiece.json on
disk mirroring the story model + `masterpiece_members` table + pHash-suggested promote flow; supersedes the old
"fold submission_links into Collections" plan — masters→Masterpieces, a Masterpiece can be a Collection member;
phased 0–6). Not yet deep-reviewed.

**Prior — 2.122.0 — UI bug sweep (start of the Artwork/Masterpiece/IA overhaul). DEPLOYED.**
Five fixes from a UI review pass: (1) **"Choose image" button** un-mangled — `.artwork-preview` `display:block`
overrode `[hidden]` so the empty preview showed + squished the flex column until the `<label class="btn">`
wrapped to a blob; fixed `.artwork-preview[hidden]` + gave `.btn` `display:inline-flex`. (2) **Story Editor top
toolbar** wraps + actions get their own **centered** full-width row on desktop (was pinned right, overflowed).
(3) **Rich-editor toolbar** wraps to a 2nd row on desktop instead of a cramped scroll strip. (4) **SquidgeWorld
🔒 in publish matrix** — publish-check required `sqw_author_*` but the connect flow saves `sqw_username`/
`sqw_password` and the poster resolves `sqw_author_* OR sqw_*`; publish-check (`editor_api.py PLATFORM_CREDS`)
now mirrors that OR. (5) **AO3 5xx** logs "AO3/Cloudflare temporarily unavailable — will retry" instead of
"unknown error" (behaviour unchanged; manager already retries 1/5/30-min). Frontend CSS + 2 small backend
touches; no schema change. `SITE_VERSION`→2.122.0. **DEPLOY pending.**

**BIG PICTURE — locked with the user 2026-07-16:** a large **Artwork/Masterpiece/IA overhaul** is now the active
direction. Entity model (confirmed): **Masterpiece** = master record for ONE image (the image analog of a story's
MASTER.md — canonical title/desc/tags/rating/JSON; every site-upload points back to it); **Artwork = Gallery** of
discovered+imported images (grid); **Collection** = cross-type folder for pooled stats (exists); **Submissions** =
stories+artwork only; **Posts** = microblog catalogue only; **Create** = the single home for ALL publishing;
**Instagram** reclassified as an art-gallery platform (moves out of Posts). ~18-item backlog triaged into Bugs
(this release) / UI polish / IA restructure / Masterpieces / Future (marketing-image generator + simple image
editor). Plus two later adds: **multi-account Overview** and **test the in-app GUI self-update** (repo now public).
Task list tracks it. **The X full-history backfill (desktop walk → server ingest + steady-state `--range` cap) is
PARKED** — greenlit but deprioritised behind this overhaul.

**Prior — 2.121.0 — X follower counts ride the free gallery-dl scrape (no billed call).**
Completes the "$0 X polling" work. After 2.119.0/2.120.0 tweets came from free gallery-dl, but the per-cycle
**follower-count** snapshot still spent one billed official X API v2 `/users/by/username` call per account (the
07:15 UTC poll logs showed 3 accounts → 3 paid calls). Cause: `TWClient.get_follower_count` tried the official API
first, and its "reuse the count cached during fetch_tweets" trick no longer warms (official `fetch_tweets` doesn't
run when gallery-dl serves tweets → guaranteed cache miss → fresh billed lookup). Fix: **gallery-dl now captures
`author.followers_count`** from the `-j` dump it already parses (new `gallerydl._extract_follower_count` +
`_LAST_FOLLOWERS` cache + pure-cache-read `gallerydl.get_follower_count`), and `TWClient.get_follower_count` is
reordered **gallery-dl (free, cached) → official API (paid) → GraphQL scrape**. Each `fetch_tweets` attempt
invalidates the handle's cached count up front and re-sets only on success, so a failed cycle can't return a stale
number (it falls through to the paid/scrape path); `get_follower_count` also returns `None` under backend
`"official"`/`"graphql"`. Net: a gallery-dl poll is now **truly $0** — tweets *and* followers free; the paid API is
billed only on a cycle gallery-dl can't serve. +7 tests in `test_tw_gallerydl.py`; full X suite green (59).
**DEPLOY pending.**

**Prior — 2.120.0 — X multi-account: round-robin fix + account stagger (poll all 3 free).**
Follow-up to 2.119.0. With gallery-dl the primary (IP-bound) X backend, the round-robin that keeps X inside the
per-IP throttle budget was silently OFF — so all 3 X accounts polled every cycle and the tail still fell back to
the paid API (~35c). Two fixes: (1) **`roundrobin.effective_batch` bug** — it disabled round-robin whenever an X
API token was merely *present* (`official_active`), stale now that the official API is only a paid fallback;
renamed to **`official_primary`**, caller computes `official_api.is_enabled(s) AND NOT gallerydl.is_enabled(s)` so
round-robin correctly activates when gallery-dl is primary. (2) **`rate_limit.tw_account_stagger`** — for
`tw_roundrobin_batch=0` (poll all), X accounts poll in **bursts of 2** with an **8-min gap** between bursts
(`TW_ACCOUNT_STAGGER_SECONDS=480`), long enough for X's per-IP window to reset → every account stays on free
gallery-dl. First burst has no wait, so a 1–2 account cycle / round-robin batch 2 is never slowed; applied in all
three account loops (server/desktop scheduled + manual dispatch); X-only. **This user set to `tw_roundrobin_batch=0`**
(all 3 every cycle): burst {1,2} → 8-min gap → {3}, all free. +3 files of tests. Full suite green. **DEPLOYED** pending
(also sets `tw_roundrobin_batch=0` on the server).

**Prior — 2.119.0 — X poll: gallery-dl primary, paid API as the fallback.**
X polling defaulted to the **paid** official X API v2 every cycle (~35c/poll even for a 1-tweet account); gallery-dl
(free) was tier 2 and never ran. Flipped the priority in `TWClient.get_all_tweets`: **gallery-dl → official API →
GraphQL** (was official→gallerydl→graphql). gallery-dl is the free primary; the official API is the **paid fallback**,
reached only when gallery-dl returns `None`. So a normal poll costs **nothing** and X (paid) is the safety net. Also:
`gallerydl.is_enabled` now stands down under `tw_polling_backend="official"` (so that explicit mode still forces
paid-first); `/api/tw/auth/status` reports the true primary. **No server setting change needed** — the VM is already
on `auto` with gallery-dl baked into the image, so post-deploy `auto` = gallerydl→official→graphql; the Bearer token
stays as the fallback. Verified live: gallery-dl authenticated with the real cookies + returned real engagement
metrics from the datacenter IP, 2s/request throttle. +3 tests in `test_tw_gallerydl.py`. Full suite green. **DEPLOYED** pending.

**Prior — 2.118.0 — e621 posting (poll-only → poll+post) + v2-extended polling.**
e621's official OpenAPI (https://e621.wiki/openapi.yaml) confirmed the upload endpoint takes the **same HTTP Basic
username + API key** we already store, so e621 is now a **posting target**. New **`E621Client.upload_post`**
(`POST /uploads.json` multipart: file + tag_string + rating s/q/e + optional source/description; rejections
surface e621's own message incl. duplicate→existing-post URL) and **`E621Poster`** (`posting/platforms/e621.py`,
art-only, registered in `manager._get_poster`, rating map, validates image + ≥4 tags, `requires_mode="any"`).
Frontend: e621 added to the Artwork hub poster list (`artwork.js._PLATFORMS`), `pollOnly:false` in platforms.js.
**Polling future-proofed:** poller now requests **v2 extended** (`v2=true&mode=extended`, nested `files`/`stats`)
instead of the legacy `{"posts":[…]}` shape e621's spec marks *deprecated* — `_parse_post` tolerates **both**
(both verified live). **up/down vote split now trends** (`e621_snapshots.up_score/down_score`, guarded migration).
**PawPoller now posts to 11 platforms** (was 10). New `tests/test_e621_posting.py` (20 cases). Full suite green.
**Caveats:** e621 uploads hit a janitor approval queue, demand accurate tags + a source, and reject duplicates.
**DEPLOYED** pending. Follow-up still flagged: consolidating the Artwork hub's "masters" (submission_links) into Collections.

**Prior — 2.116.0 — Publishing settings tab folded into General — Phase 7a of the linking/picker overhaul.**
The user's call on the "Publishing module" removal: it's the **Settings → Publishing tab**, and they only want a
yes/no posting toggle, in **General**. So the Publishing + Server Sync accordions (Enable-posting toggle, default
rating/platforms, remote server URL/key/archive-path, Save button) moved into **Settings → General**; the on/off
relabelled **"Enable posting"**. **Every element ID preserved** → the existing Publishing handlers keep working
(pure DOM relocation, reversible). Publishing tab button removed; `#/settings/publishing` redirects to General.
Frontend-only. Full suite 437 pass. **DEPLOYED.** **Phase 7b NEXT (in progress):** the user chose "move
Submissions' extras (＋Collection / discovered bucket / gallery import) onto Library FIRST, then hide Submissions"
— not yet done.

**Prior — 2.115.0 — Art workflow cleanup — Phase 5 of the linking/picker overhaul.**
Two concrete art fixes. **Discoverable delete:** the artwork *detail* page always had Delete but it was buried
(the "missing remove artwork" complaint = a discoverability gap); every **library hub card** now has a hover
**🗑 Delete** (`artwork.js._deleteFromHub`, confirm; published posts stay live). **Art in Collections:**
`_location_from_submission` now returns each location's `thumbnail_url` → the collection detail Locations table
shows a per-posting thumbnail and the hub card **auto-covers** from the first location with an image
(`cover_thumb`/`cover_platform`; FA/IB/Pixiv via the thumbnail relays). Fixes "Collections is missing the Artwork
attached." **Flagged for §7 (not done):** the Artwork hub still groups art into "masters" via the same
`submission_links` that §3 folded into Collections → two grouping systems; consolidating is a structural change
deferred to the removals scoping. New collections test (+1). Full suite 437 pass. **DEPLOYED** (`316f47b`).
Settings search (#8) verified already-shipped since 2.103.0 (`_wireSettingsSearch`) — Phase 6 needs no build.

**Prior — 2.114.0 — Native pixel-hash image-similarity suggestions (no AI) — Phase 4 of the linking/picker overhaul.**
Collection suggestions matched only by title; now they also match by **pixels** — the same art across platforms
via a perceptual hash, **no AI/ML/embeddings/external service**, pure Pillow, local. New **`database/image_hash.py`**:
**dHash** (9×8 greyscale grid → 64-bit fingerprint, resize-invariant so full-res ↔ thumbnail match by small
**Hamming distance**); pure primitives + an `image_hashes` store keyed by `(platform, submission_id)`. Two safe
populators via **`POST /api/collections/hash-scan`**: `hash_local_artworks` (zero-network, hashes local art →
stores against each posted platform copy) + `hash_scan` (fetches thumbnails **only** from a hardcoded public-CDN
allowlist — https-only, host-suffix, redirect-disabled, size-capped; same SSRF posture as `/thumb`; pixiv/e621/
Mastodon excluded). `auto_suggest_collections` now unions **title** (Jaccard) + **image** (Hamming ≤ 8) deduped on
the member pair → `reason` title/image/both. Frontend: Collections hub "Suggested collections" card gains a
**🔍 Scan images** button + reason chips, shows even when empty. New `tests/test_image_hash.py` (9). Full suite
436 pass. **DEPLOYED** (`beff84d`; `image_hashes` table live, 0 rows until first scan).

**Prior — 2.113.0 — Cross-Platform Links folded into Collections — Phase 3 of the linking/picker overhaul.**
Cross-Platform Links and Collections were the same idea (one piece across platforms + pooled analytics); Links
only added a combined chart + title suggestions. Both moved into Collections; the Cross-Platform screen is
retired. **Backend:** reusable `analytics_queries.get_combined_snapshots(conn, pairs)` (link wrapper +
`collections_queries.collection_member_pairs` both feed it); shared `_auto_suggest(conn, existing)` engine
(links exclude linked pairs, new `auto_suggest_collections` excludes collected). New endpoints
`GET /api/collections/{cid}/snapshots` + `GET /api/collections/suggestions` (declared before `/{cid}`).
**Migration** `migrate_links_to_collections` (db.py) — one-time, idempotent, **reversible**: adds
`collections.source_link_id`, creates a Collection per link, leaves `submission_links` intact. **Frontend:**
Collections detail gains a Combined-growth chart; hub gains a "Suggested collections" card (one-click Make
collection); Cross-Platform nav removed, `#/cross-platform`→`#/collections` redirect, palette/tour re-pointed.
`/api/links*` stays dormant. New `tests/test_collections_merge.py` (6). Full suite 427 pass. **DEPLOYED**
(`798ebc7`; prod had 0 links → migration a correct no-op, infra in place).

**Prior — 2.112.0 — Tag library in the Art module (TagPicker) — Phase 2 of the linking/picker overhaul.**
The artwork upload screen only had a free-typed comma box for tags — no access to the canonical 4,600-tag
database the story editor browses. New **`frontend/js/tag_picker.js`** `TagPicker.open({title, selected,
onConfirm})` — a standalone picker reusing the tag browser's modal chrome (`.tag-browser-*`) with **selectable
tag chips** (name + category badge), the six category filter chips (physical/acts/kink/meta/image/user) + live
search, loading `/api/editor/tags` (cached in `sessionStorage` `pawpoller_tag_db_v1`, shared with the editor).
**Deliberately standalone, not a refactor** — the editor's own browser (`metadata_editor.js`) writes straight
into `this.metadata.tags` and is too coupled to externalise; TagPicker is pure-in/pure-out like WorkPicker,
**zero changes to the story editor**. Wired into `artwork.js` via a `🏷️ Browse tag library` button under the
default-tags box; opens pre-loaded with current tags, writes the confirmed selection back, **lossless** (free-
typed non-library tags preserved). `.tp-*` CSS in `editor.css`, script in `index.html`. Frontend-only. Full
suite 421 pass (regression). **DEPLOYED** (`30de906`). Spec + remaining phases (Collections←Cross-Platform merge,
native pHash image-similarity suggest, art cleanup, settings search, removals): `docs/specs/linking_picker_overhaul.md`.

**Prior — 2.111.0 — Visual work-picker (WorkPicker) — Phase 1 of the linking/picker overhaul.**
Selecting a work to add to a Collection was a text list capped at 200 rows (`collections._addMemberBrowser`),
unusable at 1000s of works. New **`frontend/js/work_picker.js`** `WorkPicker.open({title, confirmLabel, multi,
onConfirm})` — a **visual thumbnail-grid picker** that reuses the story-editor tag browser's modal chrome
(`.tag-browser-*` classes) with image cards (thumb + title + badge), multi-select, selection surviving
re-searches. **Scales via server-side search** `/api/works?search=&type=` (+ discovered bucket); filter chips
All/Stories/Artwork/Discovered. Collections "Add members" now opens it. `.wp-*` CSS in `editor.css`, script in
`index.html`. Reusable — will replace the Cross-Platform `prompt()` in the merge. Frontend-only. Full suite
421 pass (regression). **DEPLOYED.**

**Prior — 2.110.0 — Per-account "Poll Now" (poll one account or all), every platform.**
Manual "Poll Now" triggered `run_<code>_poll_cycle()` with no account → only ever polled the platform
**default** (why connecting the X token + Poll Now refreshed only KnaughtyKat). New **`polling/multi_account.py`**
`poll_platform_accounts(platform, account_id=None)`: an id polls that account; `None` enumerates enabled
accounts and polls each (falls back to a single default poll if none seeded). `get_poll_cycles()` = code→cycle
registry (17). New endpoint **`POST /api/poll/trigger/{code}?account_id=`** (`routes/api.py`); manual polls are
explicit so they **ignore** the scheduled round-robin/save-tokens throttle. Frontend `_dashPoll` reads the
context-bar account switcher (`_accountFilter[code]`) → `API.triggerAccountPoll(code, id)`; selected account
polls one, "All accounts" polls all. Works for every multi-account platform (switcher already renders at 2+
accounts). New: `tests/test_multi_account_poll.py` (5). Full suite 421 pass. **DEPLOYED.**

**Prior — 2.109.0 — Backend-aware X round-robin + "save API costs" toggle.** DEPLOYED (`9c70acc`).
New **`effective_batch(configured, *, official_active, save_tokens)`** (`polling/roundrobin.py`): scrapers
always round-robin (per-IP protection); the official API polls **every** account each cycle **unless** the
user opts into `tw_roundrobin_save_tokens` (X settings → Official X API card → "Throttle polling to save API
costs", default off) to spend fewer paid reads. `server.py` consults `official_api.is_enabled` + the setting.
**Net: with a Bearer token connected, all X accounts poll every scheduled cycle.** New: `test_tw_roundrobin.py` +4.

**Live status (X official API, verified 2026-07-14):** Bearer token connected on prod (`has_api_token: True`,
backend `auto` → official). A poll of @KnaughtyKat ran via the **official API in 0.4 s** — token valid, tier
allows `public_metrics` reads.

**Live status (X official API, verified 2026-07-14):** Bearer token connected on prod (`has_api_token: True`,
backend `auto` → official). A poll of @KnaughtyKat ran via the **official API in 0.4 s** (`clients.tw.official_api:
TW official API: 1 tweets`) — token valid, tier allows `public_metrics` reads. **Gotcha found:** the manual
`/api/tw/poll/trigger` polls only the **default account** (→ account picker is the next build, all platforms).

**Prior — 2.108.0 — Settings toggle for the floating logs button.**
The bottom-right **"Logs"** live-tail button (`frontend/js/logs_panel.js`) was always rendered; now gated by
the **`logs_panel_enabled`** preference (Settings → App Preferences → "Floating logs button", **default on**).
Reads the pref via `API.getPreferences()`, exposes `window.LogsPanel.setEnabled(bool)` (live show/hide).
Whitelisted in `routes/api.py`. New: `tests/test_logs_panel_pref.py` (3). **NOT DEPLOYED.**

**Prior — 2.107.0 — Round-robin X polling: poll ≤ N accounts per cycle to stay under the per-IP budget.**
The measured fix for the multi-account throttle. A sequential 3-account test on a cooled datacenter IP still
threw the **3rd** account (gallery-dl 480 s → GraphQL `429`) after the first two made only ~3-4 requests —
X's per-IP budget for the datacenter is **~2 account-scrapes per window**, reset >8 min. No in-cycle rate
limit fixes that; you have to poll **fewer accounts per cycle**. New **`polling/roundrobin.py`**
(`select_roundrobin`) picks the `batch_size` **least-recently-polled** accounts (from `tw_poll_log`
timestamps via `tw_queries.get_tw_last_poll_by_account`, so rotation survives redeploys). `server.py` narrows
the X account list to **`TW_ROUNDROBIN_BATCH` (default 2**, per-user override `tw_roundrobin_batch`, 0 = poll
all) before building tasks; **only X is round-robined.** **DEPLOYED + verified** — selection against the live
prod DB picked accounts 12+13, rotating 14; **polling resumed** (`polling_paused: False`). New:
`polling/roundrobin.py`, `tests/test_tw_roundrobin.py` (9).

**Prior — 2.106.1 — Shared cross-account rate limiter for X polling (burst guard, not a full fix).**
New **`polling/rate_limit.py`** = async sliding-window limiter; `TWClient._get_json` (GraphQL) +
`official_api.py` (official API) `await tw_acquire()` before every request → **≤ 15 per 30 s, globally**
(FIFO). gallery-dl (subprocess) isn't gated. The same 3-account test that motivated 2.107.0 showed the
limiter is a **burst guard** — it can't create budget the IP lacks — which is why round-robin followed.
Full suite 400 pass.

**Prior — 2.106.0 — Official X API v2 as an opt-in X-polling backend (top of the hybrid).**
Adds the official X API v2 as an **opt-in, bring-your-own-token** poll backend — the ToS-compliant,
**IP-agnostic** fix for the datacenter rate-limit that throttles the scrapers server-side. New priority:
**official API → gallery-dl → GraphQL scrape** (`TWClient.get_all_tweets()`/`validate_cookies()`); each
returns `None` when not its turn, so no-token users are unaffected (zero regression). Reads X API v2
`public_metrics` → our exact 6 columns (`impression_count`→views, like/retweet/reply/quote/bookmark), no
schema change; `clients/tw/official_api.py` returns the same detail-dict shape (content-type from
`referenced_tweets`, photo `media_urls`, follower count from the same user-lookup — no extra billed call).
**Opt-in UI:** an "Official X API" card under Settings → X takes a **Bearer token** (developer.x.com),
validated then vaulted (`tw_api_bearer_token` secret). `tw_polling_backend`: `auto`/`official` use it when
a token is set; `graphql`/`gallerydl` force a scraper. `/api/tw/auth/status` reports `poll_backend` +
`has_api_token`; new `POST /api/tw/api-token/connect` + `/api-token/disconnect`. **Token-only works with
no cookies** (poller drops the cookie requirement when the official backend is configured). **Posting is
unaffected** (still cookie/GraphQL — the official write API costs $). **One token covers all accounts.**
**Cost:** pay-per-use, no free tier but no minimum; owned reads ~$0.001 → ~$2–7/month; don't `force_full`
on a timer. New: `clients/tw/official_api.py`, `tests/test_tw_official_api.py` (respx-mocked). Spec:
`docs/specs/x_official_api.md` (Phase 1 shipped). Full suite 395 pass.

**Prior — 2.105.1 — Raise the gallery-dl poll timeout so it can ride out an X rate-limit reset.**
Follow-up to 2.105.0 from verifying the migration live on prod. `TW_GALLERYDL_TIMEOUT_SECONDS` **300 → 480**
(5 → 8 min). Live test confirmed gallery-dl works — it authenticates, uses **current** query IDs (validating
the migration), and fetched a fresh account in 15s — but from the **GCP datacenter IP** X often `429`s the
timeline endpoint and gallery-dl then correctly waits for X's reset (`[twitter] Waiting for 6 minutes … (rate
limit)`). The old 300s cap killed gallery-dl mid-wait → fell back to the GraphQL scrape, which `429`s on the
same per-IP limit. 8 min lets gallery-dl ride out a typical reset and actually fetch. Rate-limiting is a
pre-existing, backend-agnostic datacenter-IP constraint (same family as the AO3 datacenter throttle); this
just stops us cutting gallery-dl off early. Trade: a rate-limited account can block its poll up to 8 min
(negligible at the 12h cadence). Full suite 384 pass (unchanged — constant tweak).

**Prior — 2.105.0 — X/Twitter polling moves to gallery-dl (hybrid, with GraphQL fallback).**
The X/Twitter **poll path** now prefers **gallery-dl** (a maintained downloader that tracks X's changing
internal API) over PawPoller's hand-rolled GraphQL scrape with its rotating query IDs. **Hybrid, never a
regression:** `TWClient.get_all_tweets()` + `validate_cookies()` try gallery-dl first and **fall back to the
existing GraphQL scrape** when gallery-dl is absent/disabled/errors — so if gallery-dl isn't installed, X
polling behaves exactly as before. **Read-path only:** gallery-dl can't post, so tweet posting (Posts module →
`create_tweet`/`upload_media`) stays entirely on GraphQL. **Licence isolation:** gallery-dl is GPL-2.0 and is
invoked **only as a subprocess, never imported** (mere aggregation — MIT unaffected); the boundary lives in
`clients/tw/gallerydl.py` (do not `import gallery_dl` anywhere). Runs `gallery-dl -j -q --cookies <tmp jar>
-o extractor.twitter.text-tweets=true -o …retweets=false ".../<user>/tweets"` with the **same auth_token+ct0**,
parses the JSON dump into the identical detail-dict shape (all 6 metrics, multi-image `media_urls`, Snowflake
date fallback); capped by `TW_GALLERYDL_TIMEOUT_SECONDS` (300s). **Delivery:** added to `requirements-server.txt`
(server auto-installs → console script on PATH) + `requirements.txt` (source/dev); **NOT bundled** into the
frozen `.exe` (never imported → PyInstaller skips it) — packaged desktop auto-detects a system install or falls
back. Overrides (plain settings, not secrets): `tw_gallerydl_path`, `tw_polling_backend` (`auto`/`graphql`).
`/api/tw/auth/status` now returns `poll_backend` + `gallerydl_available`. New: `clients/tw/gallerydl.py`,
`tests/test_tw_gallerydl.py` (17 tests). Full suite 384 pass.
**Behavioural delta:** the gallery-dl path tracks own posts (`retweets=false`), so the GraphQL path's niche
"keep a repost that @-mentions me" doesn't apply on that backend (captured tweets are never deleted).

**Prior — 2.104.0 — e621 is the 17th platform (poll-only) + platforms sort alphabetically.**
Added **e621** as a poll-only analytics platform (**PawPoller now tracks 17 platforms**). Connect username +
API key (Account → Manage API Access — the API key, NOT the password); tracks your own uploads'
**score** (score.total, can be negative — e621 has no view count so Score is the headline), **favorites**
(fav_count) and **comments** (comment_count), with the standard dashboard/submissions/detail/compare screens.
Official e621 REST API over HTTP Basic; poller pages `/posts.json?tags=user:<username>` (before-id cursor),
snapshots each post. **Policy-compliant:** descriptive **non-browser** User-Agent + ~1 req/s throttle
(`E621_REQUEST_DELAY_SECONDS`), both mandated by e621. CDN is hotlinkable → no thumb proxy; no follower series.
New files: `database/e621_schema.sql`, `database/e621_queries.py`, `clients/e621/client.py`,
`polling/e621_poller.py`, `routes/e621_api.py`; wired through config vault (`e621_api_key` secret,
`e621_username` plaintext), accounts registry, orchestrator, per-platform pause, session-health, Telegram,
analytics/collections rollups, discovered-works, settings connect card + poll-interval, and the Overview totals.
Also: **platforms now sort alphabetically** across the UI (registry sort in `platforms.js` drives the Platforms
hub / command palette / context-bar / Overview tiles; Polling tab cards sort too, IB pinned first; Settings
accordions were already A→Z). Tests: `tests/test_scope_e621.py`. Full suite 367 pass.
**e621 needs per-account creds entered in Settings before it polls.**

**Prior — 2.103.0 — Quick-wins batch: cross-platform fix, per-platform pause, settings search, artwork remove.**
Isolated UX/bug fixes from a product-direction review (no data-model changes; larger IA/art
consolidation spec'd separately in `docs/specs/ia_consolidation.md`). (1) **Cross-platform screen crash**
"Cannot read properties of undefined (reading 'map')" — `Components.linkSuggestions()` read `s.items.map()`
but `auto_suggest_links()` returns members under `submissions`; corrected + guarded `(s.submissions || [])`.
(2) **Itaku infinite retry** — a post to an unconnected Itaku account fails "… not configured (ik_auth_token)",
a permanent error queued as transient; `posting/manager.py` `_schedule_retry()` now classifies "… not
configured" permanent (no retry, log tells user to connect first). (3) **Artwork upload "✕ Remove image"
button** (`artwork.js` `_clearFile()`). (4) **Per-platform pause polling** — Settings → Polling cards get a
⏸ Pause / ▶ Resume toggle; new `POST /api/poll/pause/{code}` + `/poll/resume/{code}`, state in
`settings.polling_paused_platforms`, scheduler `_poll_all()` skips paused codes each cycle (manual Poll/Resync
still work; distinct from global pause; "· paused" tag on card). (5) **Polling tab → grid** (`.polling-grid`
auto-fill min 340px; was a vertical stack). (6) **Settings search** — box above the tab strip filters ALL tabs
at once (`_wireSettingsSearch`), hides non-matching sections/accordions, Esc/clear restores; eager-loads lazy
Polling/Logs tabs on first search. (7) **Threads/Instagram guides** now warn (first note) to do token setup on
**desktop in Microsoft Edge / any non-Chrome browser** — Chrome breaks Meta's dashboard. Full suite: 363 pass.

**Prior — 2.102.0 — OWASP ASVS 5.0 Level 2 self-assessment + the fixes it surfaced.**
Walked all 253 L1+L2 ASVS 5.0 requirements against the app with file-level evidence → published
`docs/security/ASVS_ASSESSMENT.md` (ships public; README links it; honest Known-Gaps register; single-tenant
threat model). Nine gaps fixed in the same pass: (1) `Utils.safeUrl()` — scraped `sub.link`/`d.url`/`external_url`
were HTML-escaped but not scheme-checked, so a `javascript:` URL executed on click; wraps all external-URL href
sinks (V1.2.2). (2) `Utils.cssUrl()` — `submissions.js` `thumb_url` raw in `background-image:url()`; note
`encodeURIComponent` leaves `'()` alone so cssUrl percent-encodes them explicitly (V1.2.1). (3) CSP
`object-src 'none'; base-uri 'none'` added to both CSPs — base-uri has no default-src fallback (V3.4.3). (4)
FastAPI `/docs`/`/redoc`/`/openapi.json` off unless `PAWPOLLER_ENABLE_DOCS=1` (V13.4.5). (5) auth events logged
w/ IP+sanitized-user; rejected API key now counts toward rate limiter (V16.3.1). (6) `_sanitize_for_log()` strips
CR/LF from username (V16.4.1). (7) 5xx `StarletteHTTPException` handler scrubs `detail=str(e)` → generic (logs
real) while 4xx pass through — closes ~200 leak sites without touching them (V16.5.1). (8)
`config.rotate_session_secret()` on password change invalidates ALL stateless sessions (V7.4.3). (9) log rotation
(RotatingFileHandler 10MB×5) in server.py+main.py. Tests: `test_error_scrub.py`, `test_session_rotation.py`; full
suite 363 pass. Residual gaps (documented + mitigated): SSRF on thumbnail proxy (KG-1), no breached-password check
(KG-5), stateless-session revocation limits (KG-8), no AV / remote-log-shipping (KG-4/11). **Public-readiness §7
security: re-closed at a named standard (ASVS L2).**

**Prior — 2.101.0 — Credential vault is now ALWAYS ON — plaintext credential storage no longer exists.**
Rhys: "why have vault as an option, it should just exist" → the vault is no longer opt-in. `save_settings()`/
`delete_settings_keys()` route secrets to the Fernet vault unconditionally (vault rewritten even when EMPTY —
fixes a stale-ciphertext bug where deleting the last credential resurrected on next load); `get_credential_mode()`
always `local` (the stored `credential_mode:"local"` stamp is kept for downgrade compat); new
`config.ensure_vault()` startup sweep (dashboard lifespan + server main) migrates plaintext stragglers from
pre-2.101.0 files / hand edits / old-backup restores. UI "Enable/Disable encryption" buttons + `POST
/api/settings/vault/enable|disable` REMOVED; `GET /api/settings/vault/status` reports `key_source` (new
`config.vault_key_source()`: operator/keyring/dotfile) and the Credential Security card displays it.
`config.migrate_to_cloud()` kept as console-only break-glass decrypt. Desktop startup settings-pull re-gated on
`auto_sync_enabled` (was gated on credential_mode — storage mode was a bad proxy for "do I sync"; always-local
would have silently killed startup pull for paired desktops). **conftest.py now redirects `VAULT_PATH` + supplies
a suite-wide `PAWPOLLER_VAULT_KEY`** — mandatory, since every save now writes the vault (the suite would have
clobbered the real one). `tests/test_vault_always_on.py`. Docs: SETUP.md §5.1 ("always on — what varies is where
the key lives"), `.env.example`, documentation_guide Phase-7b section + endpoint table.

**Prior — 2.100.0 — Security-audit pass: shell-quoting hardening, dependency CVE fixes, persona-leak scrub (+ DA URL bug).**
Full pass: security-reviewer agent (auth/creds/shell/path — **0 critical/high**; SQLi, traversal, CSRF, login
rate-limit, session expiry, IG pubmedia host all verified clean) + `pip-audit` + a public-copy rebuild-and-scan.
Fixed: `shlex.quote()` on every interpolated path in the generated Linux uninstall/self-update scripts
(`uninstall.py` `_build_linux_script`, `updater.py` `_apply_update_linux` — the review's 3 Mediums, one class);
frozen-Linux `APPDATA_DIR` now falls back to `XDG_DATA_HOME`/`~/.local/share` instead of a CWD-relative dir
(`config.py`); `cryptography` `~=48.0.1` server pin + `>=48.0.1` desktop floor (GHSA-537c-gmf6-5ccf, OpenSSL in
older wheels), `pytest~=9.0.3` (PYSEC-2026-1845; suite green on 9 — 353 passed), weasyprint CVE-2026-49452
assessed N/A (own-content HTML, no `presentational_hints`; noted in requirements-server.txt); DA client/poster no
longer hardcode an account username in post URLs (real bug for self-hosters — now `target_user`); persona handles
scrubbed from comments/fixtures; `make_public.py` excludes caught up (`.plan/`, `prototype/`, `docs/research/`,
root mockup HTMLs) + case-insensitive persona-handle leak patterns (scan: 17 would-be leaks → 0, verified clean
build). `keyring>=25.0` added to desktop requirements (vault key → OS keystore, not a dotfile). **Ops:** prod
vault was ALREADY enabled (since ~Apr) but its key sat in `/app/data/.vault_key` NEXT to the ciphertext on the
backed-up volume — key relocated to `PAWPOLLER_VAULT_KEY` in the VM's `.env` (0600, gitignored; SETUP.md §5.1),
dotfile deleted after verify. Desktop instance vault ENABLED (AO3 creds migrated), key in Windows Credential
Manager; stale 2-Jul `.vault_key`+vault test artifacts cleaned. **§2 (creds-at-rest): CLOSED for both live
deployments** (vault default-on for NEW installs remains open — §3 first-run wizard material). Review's remaining
informational note: plaintext-by-default for fresh installs is a conscious, documented decision.

**Prior — 2.99.0 — Poll-interval fix: 6/8/10/12-hour selections now save (+ "Set all platforms" one-shot).**
Editing a poll interval to anything **longer than 4 hours silently did nothing** — the Settings dropdowns render
6/8/10/12-hour options, but `save_preferences`'s validator only accepted `{15,30,60,120,240}` minutes, so longer
picks were quietly rejected and the platform kept its old interval (the "my edits aren't saving" report). Fix:
widened `_ALLOWED_INTERVALS` → `{15,30,60,120,240,360,480,600,720}` in `routes/api.py` (with a comment tying it to
the dropdown options so they can't drift again). Also new **"Set all platforms"** control at the top of the Poll
Intervals section (`frontend/js/app.js`): pick one interval → applied to **all 16 platforms** in a single save,
mirrored into every per-platform dropdown, with a toast. No schema change. Developed on `master`; needs deploy.

**Prior — 2.98.0 — Throttle visibility: tell throttled/partial polls from clean successes (+ AO3 "shields up" ≠ expired).**
A throttled poll (X 429, AO3 shields) used to log as `success` even with partial data. Now: new **`partial`** poll
state — the X client sets a `throttled` flag on any 429, the poller finishes `partial` (+ reason) not `success`
(no schema change; `/api/platforms/health` carries `last_poll_status:'partial'` + `last_poll_error`).
`platform_health.js` classifies `partial` → the existing **amber "throttled"** state (dot + subtitle + banner), and
`get_notifications` emits a "X: last poll was throttled" bell alert for any configured platform whose last poll was
`partial` (deduped by poll ts, gated on configured). **AO3 fix:** the client records a `blocked_reason` on
shields/rate-limit and `validate_session` **raises** → the session check shows amber **"Unverified — AO3 temporarily
blocking (shields up)"** with a clear message (retry later / use cookie auth), NOT the misleading red **"session
expired — re-enter credentials"** (same pattern as the 2.83.0 Threads/IG fix). Wired for X + AO3; the client-flag
mechanism extends to any platform. Touches `clients/tw/client.py`, `polling/tw_poller.py`, `clients/ao3/client.py`,
`routes/api.py`, `frontend/js/platform_health.js`. Verified live (simulated `partial` poll → amber + bell alert);
notification/session tests green. Developed on `master`; needs deploy.

**Prior — 2.97.0 — Collections: one master container per piece (gallery + microblog + companion story).**
New **Collections** hub — a user-curated master folder per piece bundling every place it lives (gallery works +
microblog submissions) with pooled analytics, all links, merged tags, and an optional companion story. Phases 1–3 +
companion story of `docs/specs/collections.md` (Phase 0 = 2.96.0). **Backend:** `collections` +
`collection_members` tables (`collections_schema.sql`, loaded in `db.py`); `database/collections_queries.py`
(CRUD + `rollup_collection()` — polymorphic members `work`/`submission`/`post` resolved live into per-platform
locations, pooled totals reusing the unify-master stat map, merged tags, personas, companion story);
`routes/collections_api.py` (`/api/collections` list/create/get/patch/delete + members), registered in
`dashboard.py`. **Frontend:** `frontend/js/collections.js` + `collections.css` — nav entry, hub (`#/collections`)
+ detail (`#/collections/:id`); curation via "＋ Collection" on Submissions-hub work cards + a browse-to-add on the
detail page. CSP-safe. `tests/test_collections.py`. Verified live end-to-end (create → add work from hub → detail
rollup pools 102 views + tags; zero console errors). **Deferred:** unify-engine auto-suggestions (spec §7 Phase 4).
_(Built autonomously overnight with the user's full permission; local dev server restarted as `python server.py`.)_

**Prior — 2.96.0 — Fix: imported works attributed to the wrong account/persona (+ one-time backfill).**
Phase 0 of the Collections plan (`docs/specs/collections.md`), shippable alone. Persona filtering "lumped" content
under the wrong persona (Hustlestick FA + KiiKinar X all showed as KnaughtyKat) because **imports/links dropped the
account**: `artwork_importer.import_artwork()` + `POST /api/works/link` called `upsert_publication()` without
`account_id`, so every imported work landed on the platform default account (the hub derives a work's persona from
its publications' `account_id`). Fix: `import_artwork` passes the source submission's `account_id`; `works/link`
resolves it via new `_submission_account_id()`; **one-time backfill migration** (`db.py`, `pp_meta`-flag-guarded)
re-points existing `publications.account_id` from the matching `{platform}_submissions` row (INTEGER↔TEXT join).
Dry-run on prod: **58 pubs** corrected (32 FA→10/15, 26 X→13/14). `tests/test_publication_account_backfill.py`.
Touches `posting/artwork_importer.py` + `routes/submissions_api.py` + `database/db.py`. Deploy runs the migration.
**In progress (autonomous, user asleep, full permission given):** the rest of the **Collections** feature
(`docs/specs/collections.md`, Phases 1–4) → will ship as 2.97.0.

**Prior — 2.95.0 — Button audit: fix a CSP-dead "Link" button + stop Poll/Resync silently skipping platforms.**
Two fixes from a static button audit (every control → handler → endpoint cross-referenced; wiring otherwise clean —
all 337 `api.js` calls + editor/settings fetches resolve to real routes, every action `data-*` trigger has a
handler). Frontend-only. (1) **Dead "Link" button:** the link-*suggestions* "Link" button (`Components.linkSuggestions`)
was the one control missed in the 2.51.4 inline→delegation migration — it used inline `onclick=`, which CSP blocks,
so it did nothing. Now a `data-link-suggest` trigger on the shared delegated listener → existing
`App.createLinkFromSuggestion`. (2) **Poll Now / Full Resync silently skipping platforms:** both global buttons
gated each platform on a **cached** `_pollingAuth` snapshot; if stale, a configured platform was dropped with no
error. Now they call new `App._configuredPollCodes()` which reads `/api/platforms/health` **fresh at click time**
(falls back to the cached snapshot only on fetch failure). Both verified live-in-browser (link handler fires with
parsed items; helper returns the configured set), zero console errors. `frontend/js/{app,components}.js`. Developed
on `master`; needs deploy.
    · **Polling note (from this session):** the scheduler polls on a 240-min interval and does NOT full-poll on
    startup, so frequent redeploys reset the timer and can leave platforms un-polled for a while; multi-image
    `media_urls` only populates on a poll with 2.91.0+/2.93.0 code (Bluesky verified live; X was transiently
    rate-limited 429; IG needs an actual carousel). Backfill = per-platform Full Resync.

**Prior — 2.94.0 — Test isolation: per-test database (no more shared-DB bleed / 30s stalls).**
Test-infrastructure only — **no runtime change**. The suite shared ONE temp SQLite DB, isolating only by per-test
`DELETE`s that swallowed `OperationalError` — so partial wipes bled rows into later tests (`test_personas` +
`test_scope_bsky` failed intermittently on wrong counts) and a single leaked connection stalled others up to the 30s
`busy_timeout` (~15 min suite). Fix: an `autouse` fixture in `tests/conftest.py` points `config.DB_PATH`+`SETTINGS_PATH`
at a **fresh per-test file** and `init_db()`s before each test (`get_connection` reads the path fresh; `monkeypatch`
auto-reverts). **348 passed in 2m44s** (was 3 failed/124 passed/2 errors, ~15 min filtered). `tests/conftest.py` only.
**Readiness note (2026-07-12):** verified the public-readiness posture still holds (loopback-default bind, auth-gated
creds, vault-at-rest, `deploy/make_public.py`, LICENSE) — **shippable for a small private alpha**; open items = a
short ToS/disclaimer (only a LICENSE exists) + first-run UX polish (audit §3). See [[project_pawpoller_public_readiness]].

**Prior — 2.93.0 — Multi-image import: now X photos + Instagram carousels too.**
Extends 2.91.0's all-images artwork import from Bluesky to **X** and **Instagram** — a multi-image post imports as
**one artwork per image** (`Title (i/N)`). The importer is platform-agnostic (reads the `media_urls` column via
`media_url_list`), so only per-platform capture + storage changed. **X** (`clients/tw/client.py`): every
`type=="photo"` `media_url_https` from `extended_entities.media` (videos/GIFs skipped; quoted-tweet photos as
fallback). **Instagram** (`clients/ig/client.py`): `_MEDIA_FIELDS` now requests `children{media_url,media_type}`;
a `CAROUSEL_ALBUM` collects each IMAGE child's `media_url` (single-media posts unchanged). New `media_urls` column
on `tw_submissions`+`ig_submissions` (schemas + the shared `db.py` migration loop over bsky/tw/ig; upserts persist
JSON). Only the **post's own** media. **Backfill:** existing X/IG posts stay single until re-polled — run a **Full
Resync**. Verified end-to-end (migration + 3-photo tweet→3, 2-img carousel→2, single-row fallback); suites green.
Bluesky + X + Instagram now covered. Developed on `master`; needs deploy.

**Prior — 2.92.0 — Fix: Wattpad story-list polling hit a dead v3 endpoint (400 every cycle).**
Recurring `[ERROR] clients.wp.client: … 400` on `/api/v3/users/{u}/stories/published`. Wattpad's API is **split by
endpoint**: `users/{u}` (validate/followers) + `stories/{id}` (detail) are **v3**, but the story-*list*
`users/{u}/stories/published` moved to **v4** (v3 now returns `400 InvalidEndpoint`). `get_all_story_ids` called v3
first (→ 400, logged ERROR) then fell back to v4 — so polling kept working but logged an error + wasted a request
each cycle. Fix: **v4 first** for the story list, v3 as legacy fallback; the other two calls already used the right
version. Verified live (one v4 request, 200, no error, story returned). `clients/wp/client.py` only. Developed on
`master`; needs deploy.  ·  **Next up (tracked):** extend 2.91.0's multi-image import to **X** and **Instagram**
carousels (2.93.0).

**Prior — 2.91.0 — Multi-image import: a Bluesky post's whole image set, not just the first.**
A multi-image post (e.g. a 4-image skeet) now imports as **one artwork per image** (titled `Title (i/N)`, each
independently publishable) instead of silently keeping only the first — the single-image artwork model is
unchanged (N artworks, not a gallery). Only the **post's own** images, never comment/reply media. **Bluesky
first**; X/Instagram carousels still import their first image until extended. Flow: `clients/bsky/client.py`
collects every embed image's `fullsize` into a `media_urls` list → persisted as a JSON array in the new
`bsky_submissions.media_urls` column (`bsky_schema.sql` + additive `db.py` migration; `bsky_queries` upsert) →
`posting/artwork_importer.py` `media_url_list(row)` returns the set (falls back to single `image_url()` for
old/single rows) and `import_artwork` loops it: each image → its own `create_artwork` (`source.image_index`), the
FIRST piece carries the publication (`external_id=submission_id`) that clears the Discovered bucket, per-image
failures collected not fatal, idempotent on re-import. **Backfill:** existing posts stay single-image until
re-polled — run a **Full Resync**. Tests: `media_url_list` cases + end-to-end migration/upsert/fallback verified;
bsky/artwork/import suites green (39). Developed on `master`; needs deploy.

**Prior — 2.90.0 — Fix: bulk "Import all" was unreachable (route shadowing).**
Backend bug fix (surfaced in the server log while testing artwork import). The per-platform **Import all** button
always failed with `Unknown platform: bulk`: `POST /import/{platform}/{submission_id}` (generic) was registered
*before* `POST /import/bulk/{platform}` (specific), and Starlette matches in registration order — so
`/import/bulk/bsky` was captured by the generic route as `platform="bulk"`, making the bulk route dead code since
it shipped (2.36.0). Reordered so the specific `bulk`/`discovered-art` routes precede the generic two-segment route
(inline comment guards it); verified with Starlette's matcher. Handlers unchanged; artwork import tests green (7).
For the record — artwork import is **single-image** (`import_artwork` grabs one `image_url()`, `create_artwork`
takes one `image_bytes`, pollers store a single `thumbnail_url` = `images[0]` of a multi-image post), so a
multi-image tweet/skeet imports as one artwork using the first image. Touches `routes/artwork_api.py` only.
Developed on `master`; needs deploy.

**Prior — 2.89.0 — Artwork unify: floating select bar (+ fix the bar leaking visible).**
Two fixes to the Artwork → "Select to unify" flow. Frontend-only. (1) **Bug:** `#art-select-bar` carries the
`hidden` attribute, but its `.artwork-select-bar { display:flex }` rule overrides `[hidden]` in the cascade, so the
"0 selected · Unify selected · Cancel · Tick 2 or more…" bar sat on the Artwork page **permanently** (and the
"Select" toggle likewise failed to hide in select mode, since `.btn` display overrides `[hidden]`). Visibility is now
driven by explicit state classes — `_enterSelect` adds `.is-active` to the bar + `.is-hidden` to the toggle,
`_exitSelect` removes them; base rule is `display:none`. (2) **Floating bar:** `#art-select-bar` now floats
(`position:fixed`, bottom-centre, rounded card + shadow + slide-up), so the count + **Unify selected** + **Cancel**
stay in reach while you scroll a long gallery ticking pieces (hint on its own line above the controls;
`.artwork-grid.selecting` gets bottom padding to clear it). Touches `frontend/js/artwork.js`
(`_enterSelect`/`_exitSelect`) + `frontend/css/artwork.css`. Verified live-in-browser (hidden by default, floats on
Select, toggle hides, Cancel restores, zero console errors). Developed on `master`; needs deploy.

**Prior — 2.88.0 — Settings → Platforms: uniform logos, true-centred titles, accounts link + logo disclaimer.**
Follow-up polish to 2.87.0. Frontend-only. (1) **Tiny logo:** the X/Twitter mark (`img/platforms/tw.png`) filled
only 50% of its 64px canvas (transparent padding), so it rendered half-size — trimmed to its content bbox +
re-padded to ~89% fill, matching the rest; all 16 logos now render a uniform 20×20 (bumped 18→20px). (2)
**True-centred titles ("justified but centred"):** the connected-account meta (e.g. "— KnaughtyKat") sat *inside*
the centred group, shoving titles on connected rows off-centre vs account-less rows — now pinned right (absolute,
muted, ellipsised) and out of the centring flow, so every title lands on the same centre. (3) **Accounts pointer:**
a footer note ("Managing more than one account? … your **primary** account …") + a **Manage accounts →** button to
`#/accounts`, via new `App._appendPlatformsFooter()` (idempotent, re-appended last each paint). (4) **Logo-usage
disclaimer:** a centred trademark line at the bottom (names/logos are trademarks of their owners, identification
only, PawPoller not affiliated). Touches `frontend/js/app.js`, `frontend/css/components.css`, `frontend/img/platforms/tw.png`.
Verified live-in-browser (X logo full size, 16 uniform + centred, meta pinned right, footer + button + disclaimer,
zero console errors). Developed on `master`; needs deploy.

**Prior — 2.87.0 — Settings → Platforms: fix Inkbunny auto-open, alphabetise, logos + centred titles.**
Polish for the Settings → Platforms accordion list. Frontend-only. (1) **Bug:** the Inkbunny accordion had a
hardcoded `open` attribute in `app.js`, so it was expanded every time Settings → Platforms opened — removed, now
collapsed like the rest. (2) **Alphabetical:** a post-render pass `App._enhancePlatformSettings()` (idempotent,
try/wrapped so it can never break Settings) re-appends the 16 platform accordions A→Z by name (Session-health dot
pinned first); no DOM rewrite, so every connect handler stays intact. (3) **Logos:** each summary gets its official
brand logo from `window.PLATFORMS[].logo` (`/img/platforms/{code}.{png,svg}`) with an emoji fallback on 404. (4)
**Centred titles:** new `.pset-summary` CSS centres logo+name, status dot absolutely pinned left, caret pinned
right. Touches `frontend/js/app.js` (+3 helpers `_enhancePlatformSettings`/`_accordionName`/`_decoratePlatformSummary`,
call site after the platforms lazy-tab load, `open`-removal) and `frontend/css/components.css` (`.pset-summary`/
`.pset-logo`/`.pset-emoji`). Verified live-in-browser (Inkbunny collapsed, all 16 alphabetical, 16 logos, all
centred, zero console errors). Superseded by 2.88.0.

**Prior — 2.86.0 — Quick Reconnect: paste a fresh token from the alert.**
When a platform's session goes expired/error (dead cookie / invalidated token — e.g. Meta code 190), a
**Reconnect** button on the alert opens a small modal to paste fresh credentials → validates + re-saves +
re-syncs in one go, without digging through Settings. Frontend-only; reuses the existing per-platform connect +
poll + session-check endpoints, no backend change. NEW `frontend/js/reconnect.js` (`window.Reconnect.open(code)`)
+ `reconnect.css`: a per-platform field spec (mirrors each `/auth/connect` body) renders the right inputs for the
9 session-checkable platforms (single paste for thr/ig/pix/mast/bsky/tum token/key; full field set for
ao3/sf/sqw login), POSTs to the SAME `POST /api/{code}/auth/connect` (validates live before saving). On success:
`POST /api/{code}/poll/trigger` + `POST /api/platforms/sessions/check` + toast + close + refresh feed; on failure
shows the endpoint's real error inline and re-enables. Two entry points off the live session state: a Reconnect
button beside Mute on each `kind:"session"` notification (`notifications_center.js`), and a **Reconnect →** action
on the app-wide expired banner (`platform_health.js`) when a single expired platform is quick-reconnectable
(else the Settings link). CSP-safe (external script/style, mirrors the guide-modal shell). Registered in
`index.html`. Verified live-in-browser (fields, required validation, bogus-token error path, both entry points).
Developed on `master`; needs deploy.

**Prior — 2.85.0 — Laurels: 100+ achievements, grouped & filterable.**
Big expansion of the Laurels gamification page — ~23 account medals → a **104-medal catalogue**. Frontend-only
(`laurels.js`+`laurels.css`), same read-only endpoints, no backend. Each engagement metric is now a full
**ladder** (a medal per rung, earned when the total passes it) instead of one "top+next" badge — Views (13 rungs
to 1M), Favourites (12), Comments (9) — plus new categories: Library (works/stories/art counts), Reach (breadth +
single-work cross-post depth), Following (watcher ladder), Breakouts (best work by views), Momentum (streak +
tracking-longevity), Personas (best persona tier + count), Milestones (all-rounder + collection meta at
15/30/50/75/100). The grid is now **grouped by category** (per-group earned/total) with an **All/Earned filter**.
`workMedals` expanded to ~20/work (full view/fave/comment tiers + chapter/word badges). Celebration guard: seen-key
bumped to `pp_laurels_seen_v2` (silent re-baseline once against the new per-rung ids) + a >3 burst cap so an upgrade
/ bulk catch-up never fires a confetti flood (single crossings still pop). Verified live-in-browser (104 medals, 10
groups, 0 dup ids, filter works, silent re-baseline, 0 console errors). Developed on `master`; needs deploy.

**Prior — 2.84.0 — Mute a platform's session alert (per-platform, auto-clears on recovery).**
Follow-up to 2.83.0. A per-platform **Mute** control on session-health notifications lets the user silence a
repeated alert they're handling externally (e.g. a Meta app-block) without disabling notifications wholesale or
hiding a *future* failure. Mute = quiet-but-visible: the item stays in the feed (dimmed, with an **Unmute**
button) but stops toasting and stops counting toward the unread badge; the health dot is untouched. It
**auto-clears** the moment the platform's session validates again (`session_check.check_platform` re-reads
settings fresh so concurrent clears don't clobber) — "mute until fixed", not forever. Backend: new
`POST /api/platforms/sessions/mute {code,muted}` (additive; checkable platforms only; unknown→400);
`get_notifications` marks session items `muted` from `settings.json muted_session_codes` and drops muted from
the unread count. Frontend: `notifications_center.js` Mute/Unmute button on `kind:"session"` items + toast-skip
+ dim (`loading_indicator.css`); `api.js muteSessionAlert()`. Tests: endpoint add/remove/reject, quiet-filter,
auto-clear. Verified live-in-browser (Mute→Unmute flip, stays visible, no badge, zero console errors).
Developed on `master`; needs deploy.

**Prior — 2.83.0 — Threads/Instagram: distinguish a Meta app-block from an expired token.**
Bug fix for a user-reported false "session expired — re-enter credentials" notification on **fresh** Threads +
Instagram tokens. Live logs showed Meta returning `OAuthException code 200 "API access blocked"` for both (they
share one Meta app) — an **app-level block, not an expired token** — but `polling/session_check` mislabels any
failed `validate_session()` as "expired". Fix: `clients/{thr,ig}/client.py` `validate_session()` now inspects the
Meta error `code` (issues the `/me` probe directly, not via `_get_json` which swallowed the code): **code 190**
(real expiry) → returns `None` → red "expired — re-enter" (unchanged); **code 200 / permission / rate-limit /
network** → raises new `ThrAuthError`/`IgAuthError` with the real Meta message → session_check's existing exception
branch renders amber "couldn't verify" with that detail. Blast radius checked: posting calls `create_*` directly
(never `validate_session`); pollers + `/auth/*/connect` already treat a raise as failure. New
`tests/test_meta_auth_classification.py` (6 cases). Does NOT un-block the Meta app (Meta-side: check app status/
permissions in the Meta Developer dashboard, regenerate the token once restored) — it just makes PawPoller report
the cause honestly. Developed on `master`; needs deploy.

**Prior — 2.82.0 — Guided tours: server-backed "seen" state.**
Resolves the user-reported reappearing-guides bug (and the 2.81.0 iOS-PWA tour caveat). The onboarding
tours (`frontend/js/tour.js`) recorded "seen" only in per-browser `localStorage`, so a dismissal didn't
follow the user — a different browser, a cleared/Private store, or the installed PWA (iOS gives it storage
separate from Safari) all re-offered the tours. Now backed by **server preferences**. **Frontend + two small
`routes/api.py` additions; no polling/auth logic changed.** New `tours_seen` list in `settings.json`, exposed
on `GET /api/settings/preferences`; new **additive** `POST /api/settings/tour-seen {name}` (appends one name,
never removes — race-safe, un-wipeable; rejects empty/oversized 400). `tour.js` gains `hydrate()` (called once
past the auth gate in `App.init`) → GETs the seen set, mirrors it to localStorage, and **reconciles** local-only
dismissals *up* to the server (one-time migration); memoised but clears the memo on 401/403/network so a pre-login
attempt can't cache empty. `maybeAuto()` now `await hydrate()`s before deciding (a tour dismissed elsewhere never
flashes first); `isDone` = server set ∪ localStorage; `end()` writes local **and** POSTs to server. Verified locally
in-browser across 3 scenarios (server→client isDone with empty localStorage; client→server on dismiss; local→server
reconcile), zero console errors. Developed on `master`; needs deploy.

**Prior — 2.81.0 — PWA: installable to the home screen (standalone).**
Builds on the 2.80.0 mobile work — PawPoller now installs to the phone home screen and launches as a
standalone app (no Safari chrome). **Frontend + a few `dashboard.py` routes; no polling/auth logic changed.**
New `frontend/manifest.webmanifest` (served at `/manifest.webmanifest`, `application/manifest+json`):
`display:standalone`, `orientation:portrait`, warm-paper colours, 3 icons (192/512/512-maskable = the sienna
quill on paper, `frontend/img/pwa-*.png`). `index.html` gains the iOS metas (`apple-mobile-web-app-capable`,
`-status-bar-style=default`, `-title`, `mobile-web-app-capable`, `theme-color`) — iOS keeps using the paw
`apple-touch-icon` for the icon and now launches full-screen. **Service worker** `frontend/sw.js` (served
root-scoped at `/sw.js`, `no-cache`, `__APP_VERSION__` spliced into the cache name) written safely for a live
dashboard: **NEVER caches `/api/*`**, non-GET, or cross-origin; network-first for navigations (offline shell as
fallback); cache-first ONLY for `?v=`-versioned static assets. `frontend/js/pwa.js` (external → covered by CSP
`script-src 'self'`) registers the worker + syncs `theme-color` to the active theme's `--bg-primary`. `dashboard.py`:
routes for both files, both added to `_AUTH_EXEMPT_PATHS`, CSP gains `worker-src 'self'` + `manifest-src 'self'`;
the PyInstaller spec already bundles `frontend/` so the desktop build ships it. Verified locally: manifest parses,
SW registers + controls at root scope, **0 `/api` entries cached** (58 static assets), theme-color syncs, zero
console/CSP errors. Needs a secure context (live HTTPS is fine). The iOS-PWA tour-reappearance caveat this note
originally carried is **RESOLVED in 2.82.0** (server-backed tour-seen — see the current-version header above).

**Prior — 2.80.0 — Mobile polish for the reskin pages + iOS safe-area fixes.**
A vigilant emulated-iPhone (393×852) audit of the reskin + gamification pages found five layout issues, all
fixed here — **CSS-only, no logic/DOM/backend change** (no horizontal scroll anywhere; the celebration overlay,
achievements card, KPI cards + book grid already reflowed fine). (1) **Header no longer hidden under the mobile
hamburger** — `.shelf-topbar`/`.lr-head`/`.work-back` get `padding-top: calc(env(safe-area-inset-top,0px)+44px)`
on mobile so the top-left eyebrow/title/back-link clears the fixed hamburger. (2) **Laurels medals → 2-up grid**
on phones (`.lr-medals` was stuck at 1 column because `minmax(180px)+gap` doesn't fit two at ~360px → 22 stacked
cards). (3) **Bell clears the iOS status bar / Dynamic Island** (`top: calc(env(safe-area-inset-top,0px)+8px)` —
it was a flat `top:8px`). (4) **Work-hero stacks on mobile** (capped 128px cover on top, head full-width below —
was a cramped `120px 1fr` with a long summary in the narrow column). (5) **Bottom nav clears the home indicator /
swipe-up bar** (`height: calc(var(--bottom-nav-h) + env(safe-area-inset-bottom,0px))` — border-box + fixed height
+ padding was squeezing the 50px tap targets into the inset). Touched `frontend/css/{bookshelf,laurels,
loading_indicator,layout}.css`. Verified on emulated iPhone (all five fixed, bell drops to 67px clear of the
Island, nav items sit above the 818px home-indicator line, no h-scroll, zero console errors); iOS `env()`
reasoned from CSS + a rendered safe-area simulation, real-device glance still worth it. Developed on `master`;
needs deploy + hard-refresh. **Native desktop app (pywebview) shares these files but is desktop-width → unaffected
at normal size; needs a `build.bat` rebuild to bundle it. No native iOS/Android app — mobile is the responsive
web app, not yet a PWA (no manifest / `apple-mobile-web-app-capable`).**

**Prior — 2.79.0 — App-wide milestone celebrations (fires on poll, any screen).**
Follows 2.78.0. The achievement celebration used to fire only when the Laurels page was open; now a
background **`Laurels.startAchievementWatch`** (started once from `App.init()`, behind the same auth gate as
PlatformHealth) pops it **wherever you are** the moment a poll crosses a milestone. It does a silent catch-up
~4s after login, then re-checks whenever a poll completes — detected by subscribing to **`PlatformHealth`** and
watching the newest `last_poll_at` advance (no new trigger fetch). The fetch+aggregate+medal-compute that was
inline in `render()` is extracted to a shared **`Laurels._load()`**, so the page and the watcher compute the
**same medal ids** against the **same `pp_laurels_seen` baseline** — each crossing celebrates exactly once
(first run still silently baselines). **Frontend only, no backend/new files/new endpoints** — the watcher +
`_load()` extraction in `laurels.js` and a one-line start in `app.js`; reduced-motion + Brut carry over from
2.78.0. Verified in-browser: watcher auto-starts + records a poll baseline; a simulated poll-advance pops
"500 Favourites" **on the Overview** (not Laurels) and records it; the refactored Laurels page still renders +
animates (count-up 26,342→42,800, bars fill); zero console errors. Developed directly on `master`. Needs a
server deploy + hard-refresh.

**Prior — 2.78.0 — Gamification expansion (per-work achievements + more medals + animated popups).**
Builds on the Slice-C Laurels (2.75.0). Path A, **frontend only, no backend added.** (1) **Account medals grown
9 → 23** (`Laurels._buildMedals`), each now with a **stable id**: First Words/Canvas, Storyteller, Gallery,
Shelf of Ten/Prolific/Century, Cross-Poster/Wide Reach/Full Spread, Breakout/Viral Hit, Following of 100/500 👑,
On a Roll 🔥 (4-week streak), Dedicated 📅 (year tracked), Decorated 🎖 (earn 15). Tier + per-work-derived medals
show a **source badge** (the work that earned them). (2) **Per-work achievements** — new pure engine
**`Laurels.workMedals(w)`** scores one work from its own numbers; the **Bookshelf work-detail** now renders an
**"Achievements — N of M earned"** card (lit/dimmed chips w/ live gaps) between "Published to" and "Chapters".
(3) **Library → Laurels button** (🏅 in `.shelf-topbar`). (4) **Animated laurel popup** — a new medal fires a
scale-in **celebration overlay** (🏆, "Achievement unlocked", name+desc, 28 confetti, 4.6s auto-close, queued);
**first visit records a silent baseline** (`localStorage pp_laurels_seen`) so existing users aren't spammed —
only medals earned *after* baseline celebrate (`_celebrateNew`/`_drainCeleb`). (5) **Hero entry animations** —
the view count **counts up** and progress bars **fill from 0** (`_animateIn`). **Reduced-motion** disables all of
it; **Brut** squares the popup + chips. All in **existing files** — `laurels.js`, `bookshelf.js`, `laurels.css`,
`bookshelf.css` (no new files, no new routes). Verified in-browser (populated mock): 23 medals w/ correct
earned/locked + source badges, count-up caught mid-flight + bars fill, work-detail "5 of 9 earned" w/ real
chapter-gap data, 🏅 button routes to `#/laurels`, the celebration pops (28 confetti) and stays silent on first
visit; zero console errors. Developed directly on `master`. Needs a server deploy + hard-refresh.

**Prior — 2.77.0 — reskin concept Slice E: Health strip + Workbench (final reskin slice).**
Extends the Overview's existing customisable widget board (which already does drag/resize/add/remove/persist).
**Observatory:** a new **`health`** widget — a compact live 16-platform status strip (dot+name per platform +
"N healthy · N need attention · N not set up" summary), reading the shared `PlatformHealth` cache via
`subscribe()` (no new fetch); theme-aware states; added to the default layout + catalog. **Bento:** the charts
widget gains a **Line/Bar toggle** persisted **per-widget** via a new `cfg` field on the layout entry
(`{id,span,cfg:{chartType}}`) — `Charts.aggregateLine` took a backward-compat `type` param, and the
`dashboard_layout` loader now preserves `cfg`. The full edit-mode "Workbench" (⚙ Customize → drag/resize/remove/
add-catalog, saved to the `dashboard_layout` pref) **predated this slice** — Slice E extends it, doesn't rebuild.
New `frontend/css/workbench.css`; touched `app.js` (widget registry + `w` arg + loader cfg + toggle handler +
`_healthStripHtml`/`_mountHealthStrip`) and `charts.js`. Verified in-browser (16-platform strip with AO3 ringing
red, Line/Bar toggle persists across reload, health widget drags/resizes in edit mode; zero console errors).
Developed directly on `master`. **This COMPLETED the reskin concept-layer
plan — all 5 slices (A Bookshelf → B Modes → C Laurels → D Ledger → E Health/Workbench) are shipped live.**

**Prior — 2.76.0 — reskin concept Slice D: the Ledger (dated timelines).**
A dated spine of typed events, two scopes / one renderer (`window.Ledger`), Path A, **no backend added**.
**Work timeline** = a "Timeline" tab on the Bookshelf work-detail (`#/library/work/{name}`), built from
the publications already fetched (each `first_posted_at` → "Posted to X" node, chapter-labelled;
`last_updated_at` w/ `update_count>0` → "Updated on X"); lazy-rendered on first open. **Activity ledger**
= a new `#/ledger` destination (**Activity**, Insights group) over the ready-made `/api/activity/recent`
typed feed — status-coloured nodes (errors ring red), filter segments (All/Posts/Polls/Issues) + a
platform dropdown (filter to one platform = that account's history). **Deliberately not the home**
(time-order buries "is everything OK now"). New `frontend/js/ledger.js` + `frontend/css/ledger.css`; wired
an Activity nav item, `#/ledger` route + breadcrumb, and the work-detail tab bar in `bookshelf.js`; Brut
covers it. Verified in-browser (Activity vs real local poll history — AO3 failures ring red, filters work;
work timeline via mock — 5 dated nodes, tab toggle both ways; zero console errors). Developed directly on
`master`. Needs a server deploy + hard-refresh.

**Prior — 2.75.0 — reskin concept Slice C: Laurels (achievements & milestones).**
A new top-level **Laurels** (`#/laurels`, Insights & Tools group) — the motivational "Den" view. A
milestone **hero** (all-time total views + progress bar to the next rung, using the app's own
`milestone_views/faves/comments` ladders from `/api/settings/preferences` — the same rungs the Telegram
alerts use), a **medals** grid (metric-tier + catalogue/special: First Words, Cross-Poster, Full Spread,
Breakout, Following of 100 — locked ones show the real gap), **persona trophy cards** (metal tier
Bronze→Diamond + level, from the normalized `stats.combined` in `/api/personas`), and a **rhythm** strip
(weeks-with-a-publish over 12 + days tracked). Path A — reuses `getPersonas`/`getPreferences`/`getWorks`/
`getSummary`/`getAggregate`/`getPostingLog`, **no backend added**. **Open Slice-C decision resolved:**
milestones use each platform's **current cumulative** (all-time) totals — credit for everything earned;
stated in a footnote. New `frontend/js/laurels.js` + `frontend/css/laurels.css`; Brut covers its cards.
Verified in-browser (real sparse data + populated mock — hero/progress, 9 medals, Gold/Silver tiers,
3-week streak; zero console errors). Developed directly on `master`. Needs a server deploy + hard-refresh.

**Prior — 2.74.0 — reskin concept Slice B: the Modes pane + Brut display mode.**
A new **Display mode** picker in Settings → Appearance (sits with Theme + Navigation as the look-and-feel controls):
**Default** (soft editorial) vs **Brut** (neo-brutalist). Brut = `html[data-mode="brut"]`, a *character* layer that
keeps the active theme's colours and only changes the hand — thick ink borders, hard `4px 4px 0` offset shadows,
squared corners (overrides `--radius*` app-wide), bold-sans headings (overrides the Vibe-Pack serif), press-down
buttons. **Theme-aware** (shadow/border = the theme's ink `--text-primary`, so it reads on paper *and* dark themes).
New `frontend/css/brut.css` targeting the real primitives; `App.applyMode()`/`getModeOverride()`/`DISPLAY_MODES`
mirror the nav-mode idiom (attribute absent = Default); the no-flash boot `<script>` resolves `data-mode` pre-paint
(hash self-computes, no CSP edit). **Terminal/Console is deliberately NOT a dashboard skin** — that green-on-black
operator aesthetic belongs to the headless/Docker surface (recorded as a design decision in `documentation_guide.md`);
only Default + Brut ship. Verified in-browser (Brut on Settings + Library, no-flash reload, clean toggle-back, zero
console errors). **Developed directly on `master`** — the `reskin` branch is retired now Slice A is live. Needs a
server deploy + hard-refresh.

**Prior — 2.73.0 — reskin concept Slice A: the Bookshelf (Library + editorial work detail).**
A new top-level **Library** (`#/library`, peer to Overview): a cover-forward shelf of works (gilt "N live"/"published"
ribbons, quiet Draft markers) + a rich work-detail (`#/library/work/{name}`: big cover, marginalia stats, per-platform
"Published to" list with live counts, and a **chapter × platform reach** card that flags **incomplete** chapters).
New `frontend/js/bookshelf.js` + `frontend/css/bookshelf.css`; reuses `/api/works` + `/api/posting/stories/{name}`,
**no backend added** (Path A). Verified in-browser (shelf + populated work-detail via mock data — per-platform counts,
chapter dots, incomplete flags all correct). Follows **`docs/RESKIN_BUILD_PLAN.md`** — the approved staged plan for the
reskin's **concept layers** (A Bookshelf ✅ → B Modes pane → C Laurels → D Ledger → E Health strip/Workbench), each
reusing real APIs, previewed locally, **deployed after each slice**. Earlier: 2.72.1 fixed the top-nav dropdown
close-behaviour (one delegated handler: toggle on label; close on outside-click/Escape/item-select/re-click).
**DEPLOY NOTE:** Slice A is the reskin's live debut — deploying it merges `reskin`→`master` (bringing Quill + top nav +
Bookshelf live at once). **After that first merge, subsequent slices (B–E) develop directly on `master`** (the
"keep-off-live" reason is gone), build→verify→deploy each. Path A holds (reskin the
real `frontend/` in place, keep all logic;
`prototype/` is the design reference — `styles.css` is the porting source, and the approved look is also in the
published artifacts: *Site Storyboard*, *UI Directions III (Synthesis)*, *App Atlas*).
**2.72.0 — the shell change.** The classic left sidebar becomes a **horizontal top bar** by default
(`data-navmode="top"`), the three nav groups (Publishing / Create / Insights & Tools) collapsing into
**hover / `:focus-within` dropdowns**; a new **Settings → Appearance → Navigation** picker (`#nav-mode-picker`,
`App.applyNavMode()`, localStorage `pawpoller-nav`) flips back to the classic **left side rail**. Desktop-only —
phones keep the bottom nav + drawer. DOM unchanged; a `@media (min-width:769px)` block in `layout.css` (gated on
`html[data-navmode="top"]:not([data-mobile="1"])`) restyles the sidebar into a 58px top bar, the nav groups wrapped
as `.nav-group > button.nav-group-label + ul.nav-sub` with CSP-safe dropdowns (`:hover`/`:focus-within`/`.expanded`,
no inline handlers, + an invisible hover-bridge). The no-flash boot `<script>` (index.html + epub-viewer.html) now
resolves `data-navmode` synchronously too; the CSP hash self-computes (2.71.0) so no hash edit is needed.
**Gotcha fixed:** the attribute was first `data-nav`, which collided with the app's document-level `[data-nav]`
click-delegation (every click matched `<html>` → navigated to `#top`); renamed to `data-navmode` everywhere.
**Polish:** `posting.js` comparison chart's primary series now reads the live `--accent` (was a hardcoded violet).
Verified live in-browser: top bar + dropdowns, side-rail toggle, mobile bottom nav, command palette, editor 4-pane,
Analytics — all coherent Quill. Files: `frontend/css/{layout,tokens}.css`, `frontend/{index,epub-viewer}.html` (via
`frontend/`), `frontend/js/{app,posting}.js`, `config.py`.

**Reskin context (2.70.0–2.71.0).** Slice 1 (2.70.0) put Quill on the token layer; **2.71.0 made it global** —
components/editor/charts hardcoded the dark theme's exact values so the theme couldn't reach them: **154 CSS
literal→token replacements** (`components.css`, `editor.css`, `loading_indicator.css`, `redesign.css`) + **charts.js**
reads `--accent` for the primary series + **editor.css** metadata/e621 pills made theme-adaptive via `color-mix` +
`accounts.js` persona default. **Kept invariant:** platform-brand hexes, theme swatches, EPUB reader themes,
diagnostics console + CodeMirror One-Dark editor panes, Platforms-hub health LEDs (on saturated tiles). 2.71.0 also
**fixed a live CSP regression** from 2.70.0 — the SHA-256-pinned no-flash boot `<script>` in `dashboard.py` was edited
without updating the hash (browsers silently blocked it); the hash is now **computed from the file at runtime**
(`_theme_inline_hash()`) so it self-heals.
**Reskin leak sweep (2.72.0): clean** — a full CSS/JS grep for the violet family + old dark-surface hexes found only
intentional survivors (SquidgeWorld brand tint, theme-preview swatches, now-defined `--bg-elevated` dead fallbacks,
secondary categorical chart hues). No unaddressed leaks remain.
**Optional future:** the structural IA follow-ups from `DESIGN_RATIONALE.md` (Submissions-as-hub, unified
Accounts+Connect, Settings config/runtime split) remain separate work beyond the visual reskin.
**DEPLOYED:** Slice A merged `reskin` → `master` and shipped live as 2.73.0 — Quill + the top-nav bar + the Bookshelf
are now on `pawpoller.syncopates.app` (the reskin's live debut). The version bump cache-busts all `?v=` CSS/JS.
**Slices B–E now develop directly on `master`** (the "keep-off-live" reason is gone). The local-only `/skeleton`
preview mount was dropped from the working tree; the `prototype/` design reference still lives on disk.

**Prior release — 2.69.0 — Import discovered art from any platform → managed works.**
The Submissions hub shows *managed* works, so polled ("discovered") art only appears once imported — and art from six
platforms couldn't be imported at all. Root cause: `posting/sync.py`'s `PLATFORM_TABLES` (the submission-table registry
behind discovery + artwork import) listed only 10 platforms; the six newest (`mast,tum,pix,thr,ig,tw`, **incl.
image-first Pixiv & Instagram**) were missing. Added all six (each has a `link` permalink + `thumbnail_url`) →
**covers all 16**. `classify_kind` gained a `has_image` tie-breaker (image-bearing inconclusive post → art), pix/ig are
image-first, and `build_discovered`/importer prefer the stored `link` for URLs. New **`POST
/api/artwork/import/discovered-art`** imports every discovered art item across platforms (download → create managed
artwork → link publication; per-item failures collected — FA needs desktop). Submissions hub gained a suggestion
banner (**Import all art** / **Review →**), a count on the Discovered link, and a smart Artwork-segment empty state.
Import quality: Weasyl/IB full-res; FA desktop-only; DA/Itaku/pix/ig/thr/mast/tum/tw thumbnail-res; SF unsupported.
**3 new tests (338 green). Needs a server deploy + hard-refresh.** Files: `posting/sync.py`,
`routes/submissions_api.py`, `posting/artwork_importer.py`, `routes/artwork_api.py`, `frontend/js/api.js`,
`frontend/js/submissions.js`, `frontend/css/components.css`, `config.py`, `tests/test_works.py`.

**Prior release — 2.68.0 — Submissions is its own all-platform page + desktop multi-account polling.**
Two changes. **(1) Submissions hub** — the **Submissions** nav (`#/submissions`) now opens the cross-platform works
hub (`/api/works`, every story+artwork grouped per work) instead of the legacy Inkbunny-only table. The hub shipped in
2.33–2.36 but a router-ordering bug shadowed it (the IB `#/submissions` branch matched first). Fix: **Inkbunny loses its
legacy un-prefixed routing** and joins the uniform `#/{code}/…` scheme — IB's table/detail/compare moved to
`#/ib/submissions` / `#/ib/submission/{id}` / `#/ib/compare`, freeing bare `#/submissions` for the hub. Touched
`platformRoute`, the router branches, `isPlatformRoute`/page-tint, the context-bar resolver, the nav-active rule, IB's
own links, and `Components.submissionsTable`. **(2) Desktop multi-account polling** — `main.py`'s poller threads called
`run_<code>_poll_cycle()` with no `account_id` (default account only); new shared `_poll_platform_accounts(platform,
run_cycle)` mirrors the server's `_poll_accounts` (enumerate enabled accounts → poll each with its `account_id`, fall
back to default), wired into all 16 desktop scheduled polls. Desktop-runtime only. **335 tests green. Needs a server
deploy (frontend) + a desktop rebuild (multi-account polling).** Files: `frontend/js/app.js`,
`frontend/js/platforms.js`, `frontend/js/components.js`, `main.py`, `config.py`.

**Prior release — 2.67.0 — Instagram posting from the desktop app (image relay).**
IG posting is no longer server-only. A **paired desktop** instance posts to Instagram by borrowing its server as the
image host — reusing the existing `posting_server_url` + `posting_server_api_key` pairing (no new settings/UI). New
authenticated **`POST /api/ig/pubmedia`** (`routes/ig_api.py`) accepts an uploaded image, stashes it via `ig_media`
(new `stash_bytes`), returns `{token, url}`; it requires auth (the POST has no trailing slash, so it's outside the
`/api/ig/pubmedia/` auth-exempt prefix — the desktop uses its sync Bearer key). `post_publisher`'s `ig` branch now
chooses its host: `ig_public_base_url` set → stash locally (server, unchanged); else paired → relay each image to
the server (`_relay_stash_image`, multipart via httpx); else a clear error. Instagram inherently needs a public
`image_url` (Meta cURLs it — never accepts bytes), which is why the relay exists. **3 new tests (335 green). Needs a
server deploy** (the server gains the relay endpoint) **+ a desktop rebuild for desktop posting.** Files:
`posting/ig_media.py`, `routes/ig_api.py`, `posting/post_publisher.py`, `frontend/js/platform_guides.js`,
`config.py`, `tests/test_ig_posting.py`.

**Prior release — 2.66.0 — "Setup guide" button on un-set-up platform tiles.**
The **Platforms hub** (`#/platforms`) now surfaces onboarding: any tile whose credentials aren't configured shows
**"Not set up yet"** + a **"📖 Setup guide"** button that opens that platform's 2.65.0 guide modal.
`renderPlatformsHub` fetches `/api/platforms/health` in parallel with the summaries and reads each platform's
`configured` flag — configured tiles keep the stat number, un-configured ones swap to the CTA (only when a guide
exists, `PlatformGuides.has(code)`). The button is a `role="button"` span inside the tile `<a>`; the delegated
`[data-guide]` handler `preventDefault()`s so it opens the modal not the link, plus a new Enter/Space keydown
delegate. Frontend-only, theme-aware (`.hub-tile-guide`/`.hub-tile-notset` from tokens). **332 tests green. Needs a
server deploy + hard-refresh.** Files: `frontend/js/app.js` (`renderPlatformsHub`), `frontend/js/platform_guides.js`
(keydown delegate), `frontend/css/guides.css`.

**Prior release — 2.65.0 — "How to get started" guides for every platform.**
All 16 platforms now have a step-by-step setup guide (nothing → connected) + a "keeping it alive" renewal section
(cookies for FA/DA/X, ~60-day Meta tokens for Threads/IG, app-passwords/API-keys that don't expire, etc.). One
structured dataset in `frontend/js/platform_guides.js` (`window.PlatformGuides` + `window.Guides` controller),
surfaced two ways: (1) a **"📖 Setup guide"** button injected onto every platform's Settings connect card
(`Guides.injectSettingsButtons` runs at the end of `renderSettings`; finds `{code}-connect/disconnect-btn` +
`save-creds-btn`→ib) → opens a **modal**; (2) a **Getting Started hub** at `#/getting-started` (new sidebar nav
item) with a card per platform. One delegated `[data-guide]` click handler powers both. Theme-aware
`frontend/css/guides.css` (design tokens, all 8 themes). Frontend-only — no backend change. Files:
`frontend/js/platform_guides.js` (new), `frontend/css/guides.css` (new), `frontend/index.html` (script + css +
nav), `frontend/js/app.js` (router `getting-started` branch + injector call in `renderSettings`).

**Prior release — 2.64.0 — Instagram posting (Posts module).**
Instagram joins the Posts module as a publish target (photo + caption), alongside bsky/mast/thr/tum/tw. Two
IG-specific problems solved: (1) **every IG post requires media** (no text-only) → new `_IMAGE_REQUIRED` guard
refuses a caption-only IG post; (2) **Instagram cURLs a public `image_url`** (no byte upload) → new
`posting/ig_media.py` stashes a JPEG (converts + downscales to 1440px) and serves it **unauthenticated** at
`GET /api/ig/pubmedia/{token}` (auth-exempt in `dashboard.py`; uuid4 token + path-traversal guard + 15-min TTL,
deleted after publish). `IgClient` gains `_create_container`→`_wait_container_ready`→`_publish_container` +
carousel (2–10). `post_publisher` `ig` branch stashes→posts→cleans up; caption via `_render_body`. Needs
`instagram_business_content_publish` scope + Business/Creator (dev-mode/Standard Access OK for own account, no App
Review). **Server-only** (image must be publicly reachable): set `IG_PUBLIC_BASE_URL` in `.env`
(→ `ig_public_base_url`), e.g. `https://pawpoller.syncopates.app`. Composer shows IG with a **"photo"** badge.
6 new tests (**332 green**). **Live-verify = a real public IG post; Meta must reach the pubmedia URL through
Cloudflare.** Files: `posting/ig_media.py`, `clients/ig/client.py`, `routes/ig_api.py`, `dashboard.py`,
`posting/post_publisher.py`, `config.py`, `server.py`, `frontend/js/posts.js`, `tests/test_ig_posting.py`.
**Needs a server deploy + `IG_PUBLIC_BASE_URL` in `.env` + hard-refresh.**

**Prior release — 2.63.0 — Instagram: the 16th platform (analytics).**
PawPoller now tracks **Instagram** (code `ig`), poll-only (analytics, no posting). Polls your media for **views,
reach, likes, comments, saved, shares** over time with the full dashboard/detail/compare/CSV/trending/session-dot/
notification treatment. Built on the official **Instagram Graph API** (`graph.instagram.com`, "Instagram API with
Instagram Login" — no Facebook Page), cloned from the Threads (`thr`) sibling. Auth = a long-lived Instagram
**user access token** (~60 days, auto-refreshed) from a Meta app with `instagram_business_basic` +
`instagram_business_manage_insights`, on a **Business/Creator** account. `likes`/`comments` off the media object;
`views`/`reach`/`saved`/`shares` from a per-media `/insights` call (one per post; `impressions`→`views` post
2024-07-02). New: `clients/ig/client.py`, `polling/ig_poller.py`, `database/ig_schema.sql`+`ig_queries.py`,
`routes/ig_api.py` (`/api/ig/*`), full registry + frontend wiring (`ig.svg`, `--platform-ig`). **Limitations:**
insights 400 the whole call if one metric is invalid for a media type (client degrades to zeros; likes/comments
always captured); connecting is the same heavy Meta dance as Threads **plus** a Business/Creator account; Meta
gates + removes adult content, so it may be unusable for some accounts. **Connect needs a per-account token.**
New tests `test_ig_parse.py`(5)+`test_scope_ig.py`(1) + an `ig` gate in `test_session_check.py`. **326 tests
green. Needs a server deploy + hard-refresh.** Posting to IG is feasible later (container→publish, public image
URL + `instagram_business_content_publish`) but out of scope here.

**Prior release — 2.62.0 — Posts: contacts manager + Bluesky auto-facets a directly-typed @handle.**
Two follow-ups to 2.61.0. (1) **Contacts manager** at `#/posts/contacts` (a **Tag contacts** button on the Posts
header): each saved contact as a card (name + handle chips) with **Edit** (`PATCH`) / **Delete** (`DELETE`, drops
bindings) + **New contact** — previously contacts could only be created inline and never fixed/removed.
`Posts.renderContacts`/`_loadContactList`/`_contactCard`/`_openManagerForm`/`_saveManagerContact`/`_deleteContact`
in `posts.js`; `#/posts/contacts` route in `app.js`; `posts.css`. (2) **Bluesky auto-facets a directly-typed full
`@handle.tld`** — no binding needed: `BskyClient._detect_handle_mentions` (domain-shaped only, so a bare `@alias`
still needs a binding and an email's `@domain` is skipped) → resolve → facet; `_build_facets` reworked to merge
bound + typed handles and drop mention/tag facets overlapping a URL facet. `clients/bsky/client.py`. 1 new test
(**320 green**). **Needs a server deploy + hard-refresh.**

**Prior release — 2.61.0 — Posts: cross-platform @mentions (handle-book) + Bluesky #tag/@ facets.**
Tagging people now works across networks and Bluesky hashtags finally link. Problem: a person's handle differs
per platform (`@name.bsky.social`/`@xname`/`@user@instance`/`@threadsname`) so one shared post can't share a
literal `@handle`; and Bluesky needs explicit **rich-text facets** (X/Mastodon/Threads auto-link), so `#tag`/`@`
were dead plain text there. Fix — an **alias + handle-book**: tag with `@luna`, bind it once to a **contact**
holding that person's per-platform handles; the publisher expands the alias to the right handle per network at
send time. New `post_contacts` (name + `handle_bsky/tw/mast/thr/tum`) + `post_mentions` (`post_id, token,
contact_id`) tables (auto-created); contacts CRUD API (`/api/posts/contacts`, declared before `/{post_id}`);
`POST /api/posts` takes a `mentions` JSON field. `post_publisher._render_body` does whole-token per-platform
substitution (no handle → left plain); `BskyClient` builds facets — `#hashtags` on **every** post (the dead-tag
fix) + `@mentions` via `resolve_handle`→DID (`_build_facets`/`_build_mention_facets`/`_extract_tag_facets`),
dropping overlapping ranges. Composer: a **Tag** panel binds each `@alias` to a contact or an inline add-contact
form; contacts load once per render, degrade gracefully. Files: `database/posts_schema.sql`+`posts_queries.py`,
`routes/posts_api.py`, `posting/post_publisher.py`, `clients/bsky/client.py`, `frontend/js/posts.js`+`api.js`+
`css/posts.css`, `tests/test_posts.py`. Live DID resolution / a real faceted skeet is user-side (fires a real
post). **319 tests green. Needs a server deploy + hard-refresh.**

**Prior release — 2.60.0 — Artwork: "possible matches" banner nudges the obvious unifies.**
Follow-up to 2.59.0. The Artwork gallery surfaces a dismissible **Possible matches** banner proposing likely
same-piece merges, reusing the existing title-similarity engine (`GET /api/links/suggestions` →
`auto_suggest_links`, Jaccard ≥ 0.6, already excludes linked pairs) — **no backend change**.
`Artwork._loadSuggestions` fetches it **lazily after the grid paints** (the O(N·M) scan never delays first
paint); `_artSuggestions` keeps only pairs whose members are **both standalone art tiles in this gallery** (so
story matches / already-mastered pieces never show). Each pair → a card (platform emojis + shared title) with
one-click **Unify** (same `POST /api/links` path) and **✕ Dismiss** (persisted in `localStorage`
`pp_artunify_dismissed`). Frontend only: `frontend/js/artwork.js`, `frontend/css/artwork.css`. Completes
`prototype/docs/ARTWORK_UNIFY.md` §6.5. 314 tests green. **Needs a server deploy + hard-refresh.**

**Prior release — 2.59.0 — Artwork: unify the same piece across sites into one master.**
The Artwork gallery can now coalesce the same artwork posted to several sites (each with its own per-site
submission id) into one **master tile with pooled stats** — like cross-posted stories already pool. **No new
backend:** a master *is* a generic cross-platform link, and discovered art tiles already carry the
`(platform, submission_id)` identity `submission_links`/`submission_link_members` key on, so it reuses
`POST /api/links` / `DELETE /api/links/{id}` / `GET /api/links` (zero schema, zero new endpoints). Read path:
`Artwork.render()` fetches `/api/links` and folds tiles sharing a link into a master card ("N sites" badge,
platform emojis, pooled views, expand → per-member rows + **Split**); a link becomes a master only when 2+ of
its members are art tiles in the gallery, so story/unrelated links fall through (`_foldMasters`). Write path: a
**Select** toggle → tick 2+ discovered tiles → **Unify selected** (`POST /api/links`) → they collapse into a
master. Frontend only: `frontend/js/artwork.js`, `frontend/css/artwork.css`. Spec:
`prototype/docs/ARTWORK_UNIFY.md` (§6.2 read + §6.3 write + §6.5 suggestions shipped; cover/title management
deferred). 314 tests green (backend unchanged). **Needs a server deploy + hard-refresh.**

**Prior release — 2.58.1 — Fix: Posts images to Bluesky 400'd when over ~1 MB.**
Live test of 2.58.0 hit a Bluesky `createRecord` 400 (`BlobTooLarge`): bsky rejects a feed-post image blob over
~976 KB at record validation, but the Posts path uploaded the original (composer allows 25 MB). Added
`BskyClient._fit_blob()` (downscale/re-encode to JPEG ≤950 KB, mirroring the stories path's `_prepare_bsky_image`,
kept local to avoid a posting→clients import cycle); `create_post` runs each image through it + cleans up temps.
X/Mastodon keep the original (higher caps). `_post_json` now logs the PDS error body on 4xx/5xx.
`clients/bsky/client.py`. 314 tests green. **Needs a server deploy** (backend only — no hard-refresh needed).

**Prior release — 2.58.0 — Posts: X/Twitter image posting + up to 4 images per post.**
The Posts module now posts images to **X/Twitter** and lets X/Bluesky/Mastodon carry **up to 4 images**. New
`post_media` table (`ordinal, path, alt`, auto-created) holds the ordered set; legacy `posts.image_path` still
mirrors the first image so the feed thumbnail + `/api/posts/image` (now with an `idx` param) keep working.
`POST /api/posts` takes a `files` multi-field (legacy `file` still accepted); delete cleans up all files. X:
new `TWClient.upload_media()` (simple v1.1 upload on `upload.x.com`, reusing the poller's cookie/CSRF/bearer
session) + `create_tweet(media_ids=…)`; publisher uploads then tweets; `tw` dropped from `_TEXT_ONLY`.
`BskyClient.create_post`/`MastClient.create_status` gained `image_paths`/`image_alts` (single path preserved).
Compose UI takes multiple images with removable thumbs; X un-badged. Files: `database/posts_schema.sql`+
`posts_queries.py`, `routes/posts_api.py`, `posting/post_publisher.py`, `clients/{tw,bsky,mast}/client.py`,
`frontend/js/posts.js`+`css/posts.css`, `tests/test_posts.py`. ⚠️ **X posting is unverified in CI** (needs a
live session + fires a real tweet) — if the media endpoint moved off `upload.x.com` it errors into the post
result and needs a one-line domain fix. Threads/Tumblr stay text-only. 314 tests green.
**Needs a server deploy + hard-refresh.**

**Prior release — 2.57.3 — Fix: Posts "Remove image" did nothing (hidden overridden by display:flex).**
Same class as the 2.54.3 notif-panel bug: `.post-image-preview { display:flex }` beat the `[hidden]` attribute,
so `_clearFile()` set `hidden=true` but the box stayed visible (and it showed before a file was even picked).
One-line CSS fix: `.post-image-preview[hidden] { display:none }`. No JS change. `frontend/css/posts.css`.
312 tests green. **Needs a server deploy + hard-refresh.**

**Prior release — 2.57.2 — Fix: Posts compose image preview blocked by CSP (blob:).**
The compose "attachment preview" was a broken image: `Posts._setFile` uses a `blob:` object URL, but the main
CSP (`_build_csp`, `dashboard.py`) was `img-src 'self' https:` — no `blob:`/`data:` — so the browser blocked the
`<img>`. Added `blob: data:` to the main CSP's `img-src` (matches the epub-viewer CSP). `dashboard.py`.
CSP is a response header → **needs a container restart/deploy**, not just a hard-refresh. 312 tests green.
Not changed: **X/Twitter image posting** — X *text* posting already works (`post_publisher.py`→`create_tweet`);
image cross-posting to X/Threads/Tumblr stays gated (`_TEXT_ONLY`). X needs the chunked media-upload flow, which
can't be verified without live X creds (would fire a real public tweet), so it's left for a live-tested pass.

**Prior release — 2.57.1 — Fix: blank thumbnails on discovered Artwork cards (FA/IB/Pixiv).**
The Artwork gallery's discovered cards were blank for FurAffinity/Inkbunny/Pixiv: those thumbnails can't be
hotlinked (CORS + mixed-content), so the app relays them via `/api/fa/thumb` / `/api/thumb` / `/api/pix/thumb`
(`Utils.faThumbUrl`/`thumbUrl`/`pixThumbUrl`), but `Artwork._discoveredCard` used the raw `thumbnail_url` in a
CSS `background-image`, bypassing the proxy. Added `Artwork._thumbSrc(d)` (per-platform relay routing) and used
it for the discovered cover. `frontend/js/artwork.js`. Display-only. 312 tests green.
**Needs a server deploy + hard-refresh.**

**Prior release — 2.57.0 — Per-page tours: a guided walkthrough for every nav destination.**
Generalised 2.56.0's single tour into a **registry of named tours** (`window.Tour`): the getting-started shell
tour plus **13 page tours** (Platforms, Submissions, Stories, Queue, History, Editor, Artwork, Posts, Analytics,
Groups, Cross-Platform, Accounts, Settings), 5-6 steps each, targeting each page's durable, **empty-state-safe**
chrome (headers, toolbars, filters, action buttons, list/grid containers — never a data row). The engine now
**auto-skips any step whose target is missing or hidden** (both directions), so state-exclusive steps
(`.empty-state` vs a populated `.data-table`/`.story-card-grid`) read correctly on empty *and* populated
accounts. **Auto-fire is gated**: getting-started once on the overview, then each page tour once on first visit
*after* getting-started is done (`pp_tour_done__<page>` flags), with a debounce so tours don't chain — via a new
`Tour.maybeAuto()` hook in `App.route()`. The sidebar **"?"** is now context-aware (`Tour.startHere()` = tour
for wherever you are). Routing note: the **Submissions** nav link renders the legacy IB analytics view
(`renderSubmissions`) because its un-prefixed route shadows the unified hub (`Submissions.render`, redesign-
pending) — the tour targets what actually renders there. `frontend/js/tour.js`, `frontend/js/app.js`,
`docs/documentation_guide.md`. Display-only, no backend change. 312 tests green.
**Needs a server deploy + hard-refresh.**

**Prior release — 2.56.0 — Getting-started tour (interactive coach-mark onboarding).**
New users finished setup and hit a busy 15-platform dashboard with no guidance. Added an interactive spotlight
**tour**: a dark overlay + moving spotlight (single `box-shadow: 0 0 0 9999px` trick, no canvas) with a popover
per step (Back/Next/Skip, Esc + arrows). All 10 steps target **persistent sidebar/header chrome** (Platforms →
Submissions → Stories → Editor → Analytics → Settings, the poll badge, the new "?" button) so it never races a
route render. **Auto-fires once** the first time a set-up user lands on overview (per-browser `pp_tour_done`;
never over `#/loading` or a deep link) and **replays** from a new sidebar-footer **"?"** button. New files
`frontend/js/tour.js` + `frontend/css/tour.css`; wired via `frontend/index.html` (link/script/footer button) +
`frontend/js/app.js` (`_maybeStartTour()` in `init()` + help-button handler). Note: existing users see it
auto-fire once on next load (dismissible). Additive, no backend change. 312 tests green.
**Needs a server deploy + hard-refresh.**

**Prior release — 2.55.2 — Settings polish: drop the redundant Save-Milestones button + surface the dashboard-password setup.**
Three design-rationale-review Settings items (§9 Q2, §10 Q3, §7 verify). (1) Removed the standalone **Save Milestones**
button — milestones already persist via the header **Save Settings** (`saveSettings()` writes them alongside everything
else), so the second save was a redundant subset; replaced with a hint + removed its dead handler. (2) Settings ›
Security › Change Password now shows an amber **"No dashboard password is set … Set up a password →"** CTA linking
`#/dashboard-setup`, shown only when `_dashboardAuthRequired` is false. (3) Verified **Inkbunny doesn't dictate other
platforms' login** (no code change) — each platform has its own `has_credentials`; the IB gate only fires for
IB-creds-but-no-data on root nav. `frontend/js/app.js`. Also lands the **Settings redesign spec**
(`prototype/docs/SETTINGS_REDESIGN.md`, config-vs-runtime split → Settings ⟂ Operations). Display-only + docs; 312
tests green. **Needs a server deploy + hard-refresh.**

**Prior release — 2.55.1 — Cleanup: unify "drift" wording + drop the dead `retrying` queue status.**
Two design-rationale-review cleanups (§4 Q3, §7 Q8). (1) The Story-detail Platforms card's hash-mismatch badge now
reads "⚠ drifted" / "Update Drifted (N)" (was "stale") to match the publish-check matrix's `posted_drifted` and stop
colliding with its `posted_stale` (=validation-fails); `change-stale` CSS→`change-drift`, `staleCount`→`driftedCount`.
(2) Removed `posting_queue.retrying` — it was in the cancel filters but never written (retries enqueue a fresh
`pending` row); no schema CHECK referenced it, so no migration. No behaviour change. `frontend/js/posting.js` +
`components.css`, `database/posting_queries.py`, `frontend/js/publish_check.js`, `docs/documentation_guide.md`. 312
tests green. **Needs a server deploy + hard-refresh.**

**Prior release — 2.55.0 — Live-publish safety guard on the quick-path posting endpoints.**
The Story-detail quick path ("Upload to {platform}" / "Update" / "Update All") hit `POST /api/posting/post` +
`/api/posting/update`, which fire live public posts, yet had **no server-side guard** — only a frontend `confirm()`.
Added the same guard the editor's matrix uses: both endpoints now 400 unless `confirm_live=true`. The three
`posting.js` handlers set it after their confirm; the Upload dialog now shows an explicit "⚠ LIVE PUBLISH" warning.
Retry/scheduler path unaffected (it calls `manager` directly, not the HTTP endpoint). Surfaced by the UI-redesign
design-rationale review (§7 Q7). `routes/posting_api.py`, `frontend/js/posting.js`, `docs/documentation_guide.md`.
312 tests green. **Needs a server deploy + hard-refresh.**

**Prior release — 2.54.3 — Fix: notification panel wouldn't close.**
The dropdown couldn't be dismissed by anything — ✕, bell re-toggle, click-outside, Escape all ran `close()` (sets
`_panel.hidden = true`), but `.pp-notif-panel`'s `display: flex` beats the UA `[hidden]{display:none}` rule, so the
attribute was set yet the panel stayed visible. This is why the centre felt half-built — the close paths were wired,
just inert. One-line CSS fix: `.pp-notif-panel[hidden] { display: none; }`. No JS change.
`frontend/css/loading_indicator.css`. **Needs a server deploy + hard-refresh.**

**Prior release — 2.54.2 — Notification centre: close button + Clear all.**
Added a **✕ close button** to the panel header and a **Clear all** action. The feed is server-rebuilt from the
activity logs each poll, so clear persists a `notifications_cleared_at` watermark (new `POST
/api/notifications/clear`, mirrors `mark-read` + resets unread) and `get_notifications` drops anything at or before
it; a still-broken session resurfaces after the next session check. `routes/api.py`,
`frontend/js/{notifications_center,api}.js`, `frontend/css/loading_indicator.css`, `tests/test_notifications.py`.

**Prior release — 2.54.1 — Fix spurious "Could not verify SF display name" warning.**
`SoFurryClient.validate_session()` checked the handle against the retired server-rendered profile HTML (`/gallery`
substring / `window.handle` marker), which the 2026-06 SoFurry SPA rewrite removed — so it logged the warning every
session-check cycle despite login+polling working. Rewritten to verify via the SPA-era endpoints: `GET
/api/profile?handle=` (authoritative), fallback `GET /u/{handle}/gallery.data`. `clients/sf/client.py`.

**Prior release — 2.54.0 — Notification centre (bell + feed) + auth-failure modal.**
Final release of the notifications/error-visibility batch (2.52 digest concision → 2.53 session checks → **2.54
centre**). Layered model now complete: **centre = everything · toast = heads-up · banner = critical ongoing · modal =
an action you just clicked failing.** New `frontend/js/notifications_center.js` — self-contained bell widget top-right
+ unread badge + dropdown feed of every event type (poll cycles, posts/uploads done+failed, session expiry). Backed
by new `GET /api/notifications` (reuses `_collect_activity_events`, refactored out of `/activity/recent`, merged with
synthetic session-expiry events; per-item + total unread vs server-side `notifications_last_read_at`;
`POST /api/notifications/mark-read` on open). `_norm_ts` reconciles the two timestamp formats. Toast policy: centre
logs everything, only NEW failures/warnings toast (errors sticky), successes silent; first-load backlog seeded
silently. Auth modal: new `window.errorModal(...)`; the API layer escalates to it when a POST for a just-triggered
post/publish/upload fails on an expired session (narrow detection — status + session/cookie message + action path,
excluding connect/validate — additive to the caller's own handling). 311 tests green. **Needs a server deploy.**
`routes/api.py`, `frontend/js/{notifications_center(new),api,loading_indicator,app}.js`, `frontend/index.html`,
`frontend/css/loading_indicator.css`, `tests/test_notifications.py` (new).

**NEXT (user-flagged, not started): general UI-polish pass.** The user said "i still think we need work on the UI"
after this batch. Candidates surfaced while building: notification **bell placement** is a fixed top-right overlay
(may overlap the platform-page account switcher on the right of the context bar — integrate into the context bar
instead of `position:fixed`); the per-platform **Settings status dots** still key off `has_credentials` (creds
exist) not live session validity — only the new "Session health" card + banner reflect real validity, so recolouring
the 15 dots is unfinished; mobile bell in the bottom nav; banner could also cover polling-paused. Design decisions
already locked (see 2.53/2.54 entries) — this is styling/placement, not re-architecture.

**Prior release — 2.53.0 — Session-expiry checking + app-wide banner + sticky error toasts + Settings "Check now".**
`polling/session_check.py` validates the 8 `validate_session()` platforms (AO3/SF/SQW/BSKY/MAST/TUM/PIX/THR) via the
pollers' singleton client; results cached process-local; orchestrator runs it at startup + every ~6h (not on the 60s
health poll — rate limits). `expired`=red, `error`=amber. Banner (`platform_health.js::renderGlobalBanner`), sticky
error toasts, Settings "Session health" card + "Check sessions now". Folded into `/api/platforms/health`; new
`/api/platforms/sessions` + `.../sessions/check`. `polling/session_check.py`, `server.py`, `routes/api.py`,
`frontend/js/{platform_health,app,api,loading_indicator}.js`, `frontend/css/{loading_indicator,components}.css`,
`tests/test_session_check.py`.

**Prior release — 2.52.0 — Telegram digest concision (skip platforms with nothing new).**
The periodic digest printed every account that merely had submissions (full `+0/+0/+0` blocks; empty personas still
messaged). `_persona_account_lines()` now takes `only_changed`; `send_digest_report()` passes `only_changed=True` to
skip zero-delta accounts (an all-quiet persona sends nothing). The **weekly** digest stays exempt
(`only_changed=False`) as a complete standing report. `polling/telegram.py`, `tests/test_persona_digests.py`.

**Prior release — 2.51.8 — Fix: "forget publication" 500 (FK constraint) + clearer AO3 expired-session error.**
Two server-log bugs. (1) `DELETE /api/editor/stories/{story}/publication` threw `FOREIGN KEY constraint failed`:
`publications.pub_id` is referenced by `posting_queue` and the immutable `posting_log`, and with
`PRAGMA foreign_keys=ON` a bare `DELETE FROM publications` fails once the row has been posted (a log row references
it). `delete_publication()` now **NULLs** the children's `pub_id` first (both nullable — queue keeps its identity,
audit log stays intact) then deletes. Two regression tests added. (2) AO3 posting failed with a cryptic "Could not
extract author pseud ID" — real cause was an expired `_otwarchive_session` cookie (AO3 302'd `/works/new`→
`/users/login`; the client parsed the login page). `create_work()` now detects the login page (`user[login]` field)
and raises an actionable "session expired — re-copy your cookie" error. **Diagnostics only — the operational fix is
to re-paste a fresh AO3 cookie in Settings → Platforms → AO3.** 302 tests green. **Needs a server deploy.**
`database/posting_queries.py`, `clients/ao3/client.py`, `tests/test_integration_posting.py`.

**Prior release — 2.51.7 — Fix: two more scroll-jump-to-top spots (dashboard poll/resync, artwork import).**
Follow-up sweep after 2.51.6. Same pattern — an in-page action that triggers a full `#app` rebuild and drops the
viewport to the top — fixed in two more places: (1) dashboard **Poll Now / Full Resync** (`app.js`
`_dashPoll`/`_dashResync`) ran `setTimeout(() => this.route(), 1500)` on success; since polls are fire-and-forget
(2.51.5) that re-render showed no fresh data and only reset the button, so it's now a plain button reset (the 60 s
`_startAutoRefresh` on every platform page already re-renders with scroll preserved). (2) **Artwork → Import
discovered** (`artwork.js` `_importDiscovered`) called `this.render()`; wrapped in the file's scroll-restore idiom
(`const y = window.scrollY; await this.render(); window.scrollTo(0, y)`). Audited-and-left: `submissions.js`/`posts.js`
already update sub-sections in place; the account-filter dropdown re-scopes the whole view (defensible top-of-page
control); the three `location.reload()` calls (setup-finish/re-run-wizard/restore-backup) are intentional. Frontend
only. `frontend/js/app.js`, `frontend/js/artwork.js`.

**Prior release — 2.51.6 — Fix: Accounts page jumped to the top on every action.**
Any Accounts-page mutation (assign platform account to persona, rename/delete persona, add/rename/enable/delete
account) scrolled the viewport back to the top. Cause: every handler ended in `this.render()`, and `render()`'s
first act is `app.innerHTML = <shell with "Loading…">`, which collapses the page height and resets window scroll to
0 before the re-fetched data refills. Fix: split `render()` — it still builds the shell (on navigation), but the
data fetch + sub-section fill moved to a new `_refresh()` that updates `personas-card`/`accounts-add`/`accounts-list`
**in place** (never touches the shell, so scroll is preserved); the 8 post-mutation `this.render()` calls now call
`this._refresh()`. Frontend only. 300 tests green. `frontend/js/accounts.js`.

**Prior release — 2.51.5 — Fix: manual Poll/Resync 524 timeout — trigger endpoints are now fire-and-forget.**
Companion to 2.51.4 (which un-blocked the buttons). Each of the 30 manual poll/full-resync endpoints used to
`await run_<platform>_poll_cycle()` inside the request, so slow platforms (AO3/X) blew past Cloudflare's ~100 s cap
→ 524. New `polling/background.py` `spawn(coro, label)` runs the cycle as a detached task (strong-ref'd so it isn't
GC-cancelled; logs exceptions) and the endpoint returns `{"status":"started"}` immediately. All 15 `routes/*_api.py`
converted; the frontend only needs acceptance so the shape change is transparent; scheduled polling unchanged. 300
tests green. `polling/background.py` (new), `routes/*_api.py`.

**Prior release — 2.51.4 — Fix: dashboard buttons dead in the browser — strict CSP was blocking all inline `on*=` handlers.**
Every inline `onclick=` (Poll/Resync, Export, submission-card nav, group/link/posting actions — ~90) silently did
nothing in a browser (`pawpoller.syncopates.app`); the desktop webview doesn't enforce the response CSP so it was
unaffected. Cause: CSP is `script-src 'self' <hash>` (no `'unsafe-inline'`), so browsers block inline event
handlers (confirmed from a live console). Fix: kept the strict CSP and removed inline handlers — all `on*=` became
`data-*` attributes dispatched by two document-level delegated listeners in `App.init()` (click + capture-phase
image-error). Zero inline handlers remain. **Known follow-up:** manual Poll/Resync also 524 on slow platforms
(AO3/X) because the trigger endpoint awaits the whole scrape in-request — fire-and-forget is a separate backend
patch. Frontend only; **needs a server deploy**. `frontend/js/{app,components,posting,posts,metadata_editor}.js`.

**Prior release — 2.51.3 — Fix: the in-app Uninstall dialog was invisible (missing modal `.open` class).**
2.51.2's uninstall attempt hardened listener wiring but missed the real cause: `.modal-overlay` is `display:none`
until `.open` is added, and `_showUninstallDialog()` built its overlay with `className='modal-overlay'` and never
added `open` — so the click fired, the plan loaded, the dialog was appended, but it rendered hidden ("nothing
happens" — no dialog, no error). One-line fix (`'modal-overlay open'`). `frontend/js/app.js`. **Lesson:** when a
hand-rolled modal "does nothing," check it got the `.open` class before chasing the event binding.

**Prior release — 2.51.2 — Three fresh-install fixes: uninstall button, phantom Inkbunny "301 views", and legacy-UI removal.**
(1) **Uninstall button did nothing** — `renderSettings()` attaches its listeners in one sequential pass, and several
binds used unguarded `getElementById('x').addEventListener`; a single missing control (setup-mode dependent) threw
and silently killed every later bind, including the uninstall button. Guarded the seven with `?.`. (2) **Inkbunny
"301 views" on a clean install** — `config.VIEWS_OFFSET` was hardcoded to 301 (a personal deleted/private-submission
reconciliation fudge) and added to every install's IB "All accounts" total; defaulted to 0 (mechanism kept, value
honest). (3) **Legacy UI removed** — deleted the frozen pre-2.29.0 shell (`index_legacy.html` + `app_legacy.js` +
`tokens_legacy.css`/`layout_legacy.css`) and the `?ui=` toggle / floating Legacy-Beta switch in `dashboard.py`; beta
is now the sole UI (`_render_index_html` no longer takes a `ui` arg; cache keyed on version only). Full suite **300
passing**. Desktop-facing; **not deployed to the VM** — the 301 fix reaches the server on its next deploy.
`config.py`, `frontend/js/app.js`, `dashboard.py`.

**Prior release — 2.51.1 — Desktop packaging fix: the Posts-module schema (`posts_schema.sql`) is now bundled into the PyInstaller build.**
2.49.0's Posts module added `database/posts_schema.sql`, which `init_db()` reads on every startup, but the file
was never added to `pawpoller.spec`'s hand-maintained `datas` list — so clean packaged installs (Windows/Linux)
crashed on first launch with `FileNotFoundError: …\_internal\database\posts_schema.sql`. Dev and the Dockerised
server were unaffected (they run from source, where the file exists). Fix: the spec now **globs `database/*.sql`**
(rooted at `SPECPATH`) so every current and future schema is bundled automatically — the list can't silently rot
again. **Desktop-only, not deployed to the VM** (the server already had the file); no code/behaviour change.

**Prior release — 2.51.0 — Follower tracking (count + growth chart) for 8 platforms + submission thumbnails for DeviantArt/Itaku/Wattpad.**
Two parity features. **(1) Thumbnails:** DA/Itaku/Wattpad now show their stored preview/cover in the submissions
grid, table, and detail views (was `thumbKey: null`) — pure frontend; the pollers already captured the URLs and
the list endpoints already return them. AO3/SQW stay text-only (no platform image). **(2) Followers:** a new
cross-platform count-with-history layer for the 8 platforms whose API exposes one (Weasyl, DeviantArt, Wattpad,
Itaku, Bluesky, X, Mastodon, Pixiv — IB/FA/SF already track individual watchers). Shared store
`database/followers.py` (`account_follower_snapshots` keyed by the global `account_id`, + cached
`accounts.follower_count`/`_at`; `record_snapshot` skips None/negative so a failed fetch never writes a bogus 0).
Each client got a uniform `get_follower_count()` (Bluesky/Mastodon/X/Wattpad solid; Weasyl/DA/Itaku/Pixiv probe
the field defensively), and each poller calls `polling/followers.capture_followers()` **after its main commit**
— the count is fetched before the DB write so no lock is held across the await (gotcha #10), and any failure is
swallowed. API `GET /api/followers/{platform}` (`supported:false` for platforms with no source). Frontend: each
of the 8 dashboards shows a **Followers** stat card + **Follower Growth** chart (injected after the stats grid by
`App._loadFollowerWidget`, reusing `Charts.aggregateLine`), and the Accounts page shows a per-account
**followers** chip. New `tests/test_followers.py` (15); full suite **300 passing**. **NOT yet deployed** — the
other session owns the cloud shell; ship with `/pp-deploy`. **Post-deploy:** confirm the four best-effort
platforms (Weasyl/DA/Itaku/Pixiv) actually populate on the next poll — DA also needs the app token's `user`
scope — and refine the field probes in those clients against a real API response if any come back empty.

**Prior release — 2.50.0 — Posts module posts to ALL FIVE microblog platforms (Threads/Tumblr/X added).**
The **Posts** hub (`#/posts`) now publishes to Bluesky, Mastodon, Threads, Tumblr and X. The three new ones are
**text-only** (image cross-posting needs per-platform work: Threads=public image_url, X=chunked media upload,
Tumblr=NPF) — an attached image is refused on those three up front; Bluesky/Mastodon still carry images.
**Threads** = 2-step Graph API create→publish (`clients/thr/client.py` `create_thread`, reuses
`thr_access_token`/`thr_user_id`; token needs `threads_content_publish`). **X** = internal CreateTweet GraphQL
mutation over the existing cookie session (`clients/tw/client.py` `create_tweet`, no new creds; query
IDs/feature flags rotate — refresh `_GRAPHQL_CREATE_TWEET`/`_CREATE_TWEET_FEATURES` if it errors). **Tumblr** =
OAuth1-signed legacy create (`clients/tum/client.py` `create_text_post`); the read `api_key` can't post, so it
needs NEW creds `tum_consumer_secret`/`tum_oauth_token`/`tum_oauth_token_secret` (added to
`PLATFORM_CREDENTIAL_FIELDS` + vault `CREDENTIAL_FIELDS`); the HMAC-SHA1 signer is hand-rolled (`_oauth1_header`)
and unit-tested vs the canonical Twitter vector, cross-checked with openssl. `posting/post_publisher.py`
`SUPPORTED` = all five, `_TEXT_ONLY = (thr,tw,tum)`. Frontend: composer lists all five; Threads/Tumblr/X badged
**text** and unticked by default. New `tests/test_oauth1.py` (2) + `test_posts.py` (8); full suite **285 passing**;
TestClient smoke confirms all five resolve with correct per-platform errors.
**Session plan COMPLETE** (Phase 1 gallery → Phase 2 Posts → Phase 3 all-five). Deferred task remaining:
in-dashboard **Pixiv guided-paste Connect** (Pixiv's `pixiv://` redirect blocks true one-click).
**Actions for the user to actually post:** Mastodon → reconnect with a **write**-scope token (connect token was
`read`). Threads → token needs `threads_content_publish`. Tumblr → add the 3 OAuth1 tokens. X → uses the existing
cookie session (brittle — query IDs rotate). Bluesky → works with the app password.

**Prior release — 2.49.0 — New "Posts" module — microblog publishing (Bluesky + Mastodon live).**
A third publishing hub beside Stories and Artwork: **Posts** (`#/posts`) composes a short post once and pushes
it to microblog accounts at once. Self-contained store (`database/posts_schema.sql` + `posts_queries.py`) — NOT
the story/artwork `publications` registry. Engine `posting/post_publisher.py`; API `routes/posts_api.py`
(`/api/posts/*`); frontend `posts.js`+`posts.css` + **Posts** nav + `#/posts`.

**Prior release — 2.48.0 — Artwork tab is now a full gallery — discovered art merged into the grid.**
The Artwork hub (`#/artwork`) also surfaces **discovered art** the pollers found on your art accounts, reading
like the Stories hub. Pure/tested `routes/submissions_api.py` `classify_kind` tags each discovered submission
`art`/`text`/`unknown`; `build_discovered` stamps `kind`. `frontend/js/artwork.js` merges `/api/artwork/images`
+ `/api/works/discovered` (filtered to art-capable platforms + visual `kind` + thumbnail); discovered cards show
a platform badge + views with **View ↗** / **Import**. No schema change.

**Prior release — 2.47.0 — DeviantArt polling moved to the official OAuth2 API (off the cookie/_napi scrape).**
DA polling now uses an app-only **client-credentials** token (`da_client_id` + `da_client_secret`, no cookie):
`/gallery/all` enumerates the target user, `/deviation/metadata?ext_stats=true` returns views/favourites/
comments/downloads (batched 10/call). The DB still keys by the **integer** deviation id (parsed from each
deviation's URL; the API's UUID is used only for the metadata call), so `da_queries`, `da_schema.sql`, the
hub/analytics/telegram/group code, and the dashboard are **untouched — no schema migration**. Mature works are
included via `mature_content=true`. **DA left `PROXY_REQUIRED_PLATFORMS`** — the official API answers from
datacenter IPs (verified 200 from the VM), so no CF proxy for DA polling. Connect form now takes
client_id/client_secret/username (`frontend/js/app.js`, `routes/da_api.py`). Legacy cookie `_napi` path retained
as a fallback. New `tests/test_da_parse.py` (13 cases); full suite 271 passing; live-validated end-to-end
against a real gallery. Research: `docs/research/deviantart_official_api.md`. **Deploy note:** DA had no creds
configured on the server, so this is a clean cutover; existing cookie installs keep working via the fallback
until reconnected.

**Prior release — 2.46.2 — HTTPS-ready: uvicorn honours proxy headers behind a TLS reverse proxy.**
`server.py` now runs uvicorn with `proxy_headers=True` + `forwarded_allow_ips` (new `PAWPOLLER_FORWARDED_IPS`,
default `127.0.0.1`). Behind a TLS-terminating reverse proxy (the maintainer's Caddy for
`pawpoller.syncopates.app`), the app sees `X-Forwarded-Proto: https` so the dashboard session cookie's
**Secure** flag turns on and `request.client.host` is the real client (fixes the 2.46.0 deferred-minor
rate-limiter proxy-IP note). No change when bound directly (default trusts loopback only). The Caddy
layer is a VM-only `docker-compose.override.yml`, not in this repo. Full pattern + gotchas: Claude memory
`reference-https-caddy-cloudflare`.

**Prior release — 2.46.1 — Credential vault: operator-supplied key (real at-rest protection on servers).**
Follow-up to the §2 security finding. The Fernet vault is genuine at-rest protection on desktop (OS keyring)
but not on a server (key falls back to `data/.vault_key` next to the ciphertext). `config._get_vault_key()`
now checks an operator-supplied key first — `PAWPOLLER_VAULT_KEY`, or the file at `PAWPOLLER_VAULT_KEY_FILE`
(Docker/K8s secret) — so a server can hold the key off the data volume; malformed keys fail fast. Falls
through to keyring→dotfile exactly as before when unset (no change for existing installs). Documented in
`.env.example` + `docs/SETUP.md §5.1`; new `tests/test_vault_key.py` (5). Audit item **§2**; §3 first-run
remains, §4 signing out-of-scope by choice. Backward-compatible — no deploy action needed.

**Prior release — 2.46.0 — Security: close the open-instance credential leak (pre-public hardening).**
A full-surface security review (public threat model) found a ship-blocker: an open-by-default server
(`0.0.0.0` bind + auth middleware short-circuits when no password) leaked every stored credential via
`POST /api/settings/sync`. Fixes: `docker-compose.yml` binds **loopback by default**
(`${PAWPOLLER_BIND:-127.0.0.1}:8420:8420`); the auth middleware **gates credential/backup/destructive
endpoints to 403 for non-loopback callers on an unconfigured instance** (`dashboard.py`); `server.py` warns
loudly if bound public with no auth; `.env.example` strengthened. Also: tar-import symlink traversal fixed
(`routes/posting_api.py` `/sync/upload`), vault at-rest expectation corrected for the server
(`docs/SETUP.md §5.1` — real protection is desktop-only), cookie value redacted in `cf_proxy` debug logs. New
`tests/test_auth_gate.py` (4). Review found path-traversal / SSRF / SQL / session-crypto SOLID.
Deferred-minor: rate-limiter proxy-IP, debug-dump temp dir, `str(e)` in some errors, constant-time compares.
Audit item **§7**; §2/§3/§4/§5 still open. **Deploy:** server `.env` set `PAWPOLLER_BIND=0.0.0.0` to preserve
its current exposure.

**Prior release — 2.45.0 — Distribution readiness: personal-data scrub + public-copy packaging.**
First slice of "ready for others." This repo stays PRIVATE; public distribution is a *cleaned copy* built by
the new **`deploy/make_public.py`** — it excludes the private dev/ops layer (`deploy/`, `qa/`, `site/`,
`scripts*`, internal docs, personal `tests/` harnesses; keeps the pytest CI suite) and runs a **leak scan**
that fails the build if any personal identifier (username, VM user, emails, personal paths, story titles)
survives. Verified: 306 files, scan clean, 250 tests pass in the clean copy. In-place hygiene too:
`docker-compose.yml` archive mount → `${PAWPOLLER_ARCHIVE_DIR:-./story-archive}` (**server `.env` now sets
`PAWPOLLER_ARCHIVE_DIR`** to keep the live mount); `posting/generate_story_json.py` + `cli/pawpoller_cli.py`
hardcoded paths → env-overridable; real story titles in doc examples → `Example_Story`. This is audit item
**§1** of public-readiness; §2 (credential-at-rest), §3 (first-run), §4 (signing), §5 (docs/legal), §7
(security) still open. Regenerate the public copy anytime: `python deploy/make_public.py [OUTDIR]`.

**Prior release — 2.44.4 — Fix: posting-failure debug dumps wrote to broken/hardcoded paths.** When a
posting flow can't parse the created work's ID, the client dumps the response body for postmortem. Two of
three dump sites used paths that don't work where the code runs: `sqw` used a hardcoded personal path
(`C:/Users/rhysc/…` — write throws on the Linux server, litters the repo root on desktop); `ao3` work-create
used `/tmp` (AO3 posting runs on the **Windows desktop**, where `/tmp` doesn't exist → body never captured).
Both now use `tempfile.gettempdir()` (portable), matching the third site (`ao3` add-chapter) which already
did. Failure path only — no success-path or polling change. `clients/sqw/client.py`, `clients/ao3/client.py`.

**Prior release — 2.44.3 — Mobile polish: scroll hint on the Settings tab strip.** Third item from the
mobile sweep. 11 settings tabs, only ~4 fit at 390px, scrolled with no cue. Added a scroll-aware edge fade
(`frontend/css/editor.css` + `frontend/js/app.js`): settings render toggles `of-end`/`of-start` on
`.settings-tabs` by scroll position → soft mask fade on whichever side has more; active tab scrolled into
view on render. Mobile-only (mask rules `data-mobile`-scoped); listener on the per-render element (no leak).
Verified live. **Mobile sweep now complete** — 3 fixes (2.44.1 drawer labels, 2.44.2 breadcrumb, 2.44.3 tab
hint); all 13 routes otherwise clean.

**Prior release — 2.44.2 — Mobile fix: context-bar breadcrumb no longer hidden under the Legacy/Beta
UI switch.** From a full mobile sweep (all 13 routes driven at 390px in headless Chrome). On platform pages
the breadcrumb ran under the fixed top-right `#pp-ui-switch` toggle, occluding the current page name.
Fix (`frontend/css/layout.css` `@media ≤768px`): `.ctx-crumbs` gets `max-width: calc(100% - 150px)` + the
earlier crumbs truncate (ellipsis) while `.here` + `.sep` are pinned `flex:0 0 auto` → "Pl… › In… ›
Submissions". Verified live (crumb right 295→224px). Sweep otherwise clean (zero horizontal overflow on
every route). Known-minor left as-is: Settings 11-tab strip scrolls horizontally with no scroll hint.
CSS-only; deploy via `pawupdate`.

**Prior release — 2.44.1 — Mobile fix: nav drawer section labels no longer chopped in half.**
`.nav-group-label` had a default `flex-shrink` + `overflow:hidden` (→ flex `min-height` computes to 0), so
the flex layout crushed the drawer's "PUBLISHING / CREATE / INSIGHTS & TOOLS" headings to a padding-sliver
when the drawer overflowed a short phone viewport (nav rows resist — `min-height:48px` on mobile). Added
`flex-shrink: 0` in `frontend/css/layout.css`; labels keep full height and the drawer scrolls. Verified via
a headless-Chrome phone repro (24px→41px). CSS-only; deploy via `pawupdate`.

**Prior release — 2.44.0 — New platform: Threads (poll-only, 15th platform)**. **Completes the
four-platform expansion** (Mastodon, Tumblr, Pixiv, Threads all shipped).
**Released + deployed** 2026-06-30 (tag `v2.44.0`). Threads (Meta) has an OFFICIAL API
(graph.threads.net); connect with a long-lived access token from a Meta app with `threads_basic` +
`threads_manage_insights` scopes (best-effort token refresh on connect). Tracks views/likes/reposts/
replies/quotes (X-shaped); per-post engagement from `/{media}/insights` (handles total_value + values[]
shapes). Posts typed Text/Image/Video/Album/Quote/Repost. New: `clients/thr/`, `polling/thr_poller.py`,
`routes/thr_api.py`, `database/thr_*`; wired through everything; maps to views/likes/replies like X.
Monochrome logo badge, `--platform-thr` = mid-grey (#555, reads on light+dark). Tests: `test_scope_thr.py`,
`test_thr_parse.py`. **CAVEAT (told Rhys, he said build anyway):** Meta gates the API behind Business-app
review and removes adult/furry content → may be connectable-but-empty/blocked for his accounts. Client is
built to the documented API; live behaviour depends on his Meta app. **To go live:** stand up a Meta app,
get a long-lived token with the insights scope → connect under Settings → poll.

**Prior release — 2.43.0 — New platform: Pixiv (poll-only, 14th platform)**.
**Released + deployed** 2026-06-30 (tag `v2.43.0`). Pixiv tracks illustrations + novels via the
reverse-engineered app-API (pixivpy-style), OAuth via a one-time refresh token; gallery metrics
(views/bookmarks/comments). **Thumbnail proxy** `GET /api/pix/thumb` injects a pixiv Referer. New:
`clients/pix/` etc. Pixiv-blue logo badge.

**Prior release — 2.42.0 — New platform: Tumblr (poll-only, 13th platform)**.
**Released + deployed** 2026-06-30 (tag `v2.42.0`). Tumblr read via the v2 API with the app's OAuth
Consumer Key ("API key") + a blog identifier — no token dance. Tracks **notes** (Tumblr's single
engagement number; no reliable breakdown). New: `clients/tum/` etc. Tumblr "t" logo (SVG, brand navy).

**Prior release — 2.41.1 — Fix CI: Mastodon test event-loop** (test-only; `asyncio.run()` instead
of the deprecated `get_event_loop()` in `test_mast_parse.py`, which hard-failed on CI's Python 3.11 and
blocked Build & Release — so 2.41.0 built no desktop installers). App code identical to 2.41.0.

**Prior release — 2.41.0 — New platform: Mastodon (poll-only, 12th platform)**.
**Released + deployed** 2026-06-30 (tag `v2.41.0`). Added Mastodon as the 12th tracked platform,
poll-only, mirroring the Bluesky/X pattern. Decentralised → connect with your **instance URL** + a
**personal access token** (Settings → Development → New application, scope `read`). Tracks likes
(favourites) / reposts (boosts) / replies; posts typed Post/Reply/Quote/Repost; boosts kept only when
you're @-tagged. No native quote count (column kept for schema parity, hidden in UI). Posting NOT
included. New: `clients/mast/`, `polling/mast_poller.py`, `routes/mast_api.py`, `database/mast_*`; wired
through accounts/config/db/server/main/dashboard/telegram/analytics/cli/frontend; official logo
(recoloured to brand purple `#6364ff`, SVG). Tests: `test_scope_mast.py`, `test_mast_parse.py`.
**To go live:** connect an account under Settings, then poll — clients can't pull data until a token is
supplied. Adding the next platforms (Threads, Tumblr, Pixiv) is largely replication of this pattern.

**Prior release — 2.40.2 — Marketing-site link in About**.
**Released + deployed** 2026-06-30 (tag `v2.40.2`). The Settings → **About** tab gained a **Website** row
linking to the marketing site (`https://pawpoller.pages.dev`, new tab). `frontend/js/app.js`. (Marketing
site source lives in `site/` — Cloudflare Pages project, deployed at pawpoller.pages.dev.)

**Prior release — 2.40.1 — Sharper Inkbunny + Weasyl logos**.
**Released + deployed** 2026-06-29 (tag `v2.40.1`). The 2.40.0 Inkbunny/Weasyl logos were tiny 16px
favicons; replaced with Inkbunny's bunny mascot (`logo/bunny.png` 154×164) and Weasyl's scalable SVG
favicon. `frontend/js/platforms.js` now treats both `ik` and `ws` as SVG logos. (Browser was used to grab
these where urllib was Cloudflare/DNS-blocked.)

**Prior release — 2.40.0 — Platform logos + Bluesky content-type tagging**.
**Released + deployed** 2026-06-29 (tag `v2.40.0`). (1) Bundled real platform logos (favicons; Itaku=SVG)
under `frontend/img/platforms/`, shown on the Platforms hub tiles (white badge) + Accounts cards via
`platformByCode().logo`, with a trademark **disclaimer** on both pages. (2) Bluesky now tags posts
Post/Reply/Quote/Repost (parity with X 2.39.3): replies/quotes detected in `_parse_post`, reposts kept
only when the account is @-tagged (`_post_mentions_did`) and shown with the original's stats. Logos are
served via the existing auth-exempt `/img` mount and bundled in the desktop build (`pawpoller.spec`
includes `frontend/`). Re-poll Bluesky to populate the new types. CHANGELOG [2.40.0].

**Prior release — 2.39.3 — X: content-type tags on cards (Tweet/Reply/Quote/Repost)**.
**Released + deployed** 2026-06-29 (tag `v2.39.3`). Each tweet card shows a colour-coded type badge
(Tweet/Reply/Quote/Repost) so entries are identifiable at a glance. `submissionCardGrid` gained
`typeKey`/`typeLabels`; X grid passes `content_type` + `Components.TW_TYPE_LABELS` (also used by the table
Type column + detail meta). `frontend/js/components.js`, `frontend/js/app.js`, `frontend/css/components.css`.

**Prior release — 2.39.2 — X: quote tweets show the quoted post's image**.
**Released + deployed** 2026-06-29 (tag `v2.39.2`). Quote tweets carry no media of their own (the image
is in the quoted post), so all 6 quote tweets showed no thumbnail. `_extract_tweet_stats` now falls back
to the quoted post's media (`quoted_status_result.result.legacy.{extended_entities,entities}.media`).
`clients/tw/client.py`. Existing quote rows fill in on the next successful poll (X rate limits apply).

**Prior release — 2.39.1 — X: tweet dates + show attached images**.
**Released + deployed** 2026-06-29 (tag `v2.39.1`). (1) Tweet dates were blank (X stopped filling
`legacy.created_at`); now derived from the Snowflake tweet id (`_snowflake_to_utc` →
`YYYY-MM-DD HH:MM:SS` UTC) and back-filled onto existing rows from their ids. (2) Tweets/posts with an
attached image now show it in the submissions grid + X detail page (`thumbKey: 'thumbnail_url'`,
`proxyThumb: false`; CSP allows `img-src https:`); X media capture prefers `extended_entities.media`.
`clients/tw/client.py`, `frontend/js/app.js`.

**Prior release — 2.39.0 — X: real tweet stats (from timeline) + tagged reposts**.
**Released + deployed** 2026-06-29 (tag `v2.39.0`). (1) Every X tweet was "(untitled)"/0: the poller
discovered via `UserTweets` then fetched per-tweet detail via `TweetResultByRestId`, whose GraphQL id
rotated and **404'd for every tweet**. The `UserTweets` timeline already carries text + stats, so
`clients/tw/client.py` now parses them straight from the timeline (`get_all_tweets()` →
`_extract_tweet_stats`) and `polling/tw_poller.py` drops the dead detail pass. Re-poll repopulates.
(2) Reposts stay excluded **except when the account is @-tagged** in them (`_user_tagged_in` /
`_repost_original`); a kept repost shows the original post's stats, `content_type='retweet'`.
If X stats ever zero out again, suspect a rotated GraphQL query id. CHANGELOG [2.39.0].

**Prior release — 2.38.5 — Dashboards: count stat card opens the list**.
**Released + deployed** 2026-06-29 (tag `v2.38.5`). The "Total Tweets/Posts/Works/Submissions" stat card
on every platform dashboard is now a link to that platform's submissions list (scoped to the viewed
account). `Components.statCard` gained an optional `href` → renders `a.stat-card`; all 11 dashboards pass
their submissions route (`frontend/js/components.js`, `frontend/js/app.js`).

**Prior release — 2.38.4 — Accounts: platform-named counts + click-through**.
**Released + deployed** 2026-06-29 (tag `v2.38.4`). Account/persona stat chips use a platform-appropriate
noun for the count (X→tweets, Bluesky/Itaku→posts, DA→deviations, AO3/SQW→works, WP→stories,
IB/FA/WS/SF→submissions; persona combined stays "subs"), and the count chip is now a link that opens the
platform's submissions list scoped to the account (reuses `App._accountFilter`/`_acctId`).
`frontend/js/accounts.js` (`_unit`, `_statChips`, `_viewAccount`), `frontend/css/accounts.css`.

**Prior release — 2.38.3 — Accounts: rename account labels**.
**Released + deployed** 2026-06-29 (tag `v2.38.3`). Added a **Rename** button to each account row on the
Accounts page (`frontend/js/accounts.js`, `_renameAccount`) — prompts for a new label and calls the
existing `PATCH /api/accounts/{id}`. Backend already supported it; only the UI was missing.

**Prior release — 2.38.2 — Bluesky polling: skip reposts (+ track replies)**.
**Released + deployed** 2026-06-29 (tag `v2.38.2`). Same fix as X (2.38.1), for Bluesky: `getAuthorFeed`
interleaves the actor's posts with reposts whose `post` is the original author's, so their stats were
polluting the dashboard. `get_all_post_uris` now skips repost items (`_is_repost_item` in
`clients/bsky/client.py`; `reasonRepost` dropped, `reasonPin`/pins kept) and the feed filter moved from
`posts_no_replies` to `posts_with_replies` so your replies (comments) are tracked too — matching X (own
posts + replies, no reposts). Existing repost rows (author handle ≠ your handle) were purged from the
live DB (e.g. a reposted "Old Tai Lung Drawing" with 891 likes). CHANGELOG [2.38.2].

**Prior release — 2.38.1 — X polling: skip reposts + usable empty state**.
**Released + deployed** 2026-06-29 (tag `v2.38.1`). (1) The X poller skipped reposts: `UserTweets`
interleaves the account's own posts/replies with retweets whose stats belong to the original author, so
`get_all_tweet_ids` now drops reposts at discovery (`_is_repost` in `clients/tw/client.py`) — own posts,
replies, and quote tweets are kept; existing `content_type='retweet'` rows were purged from the live DB.
(2) `platformEmptyState` (all 11 platforms) now distinguishes *not connected* from *connected but empty*;
the empty case shows "No {platform} data yet" + a working **Poll now** button (the X-with-0-tweets state
previously had no poll/retry action). CHANGELOG [2.38.1].

**Prior release — 2.38.0 — Accounts page redesign**.
**Released + deployed** 2026-06-29 (tag `v2.38.0`). The Accounts/personas page was raw, unstyled markup
(bare inputs, undefined `.badge`, one oversized card per platform, an empty FA-prefs card); rebuilt it
to match the bold UI: new token-based `frontend/css/accounts.css`, per-platform brand-coloured cards
(`--pc` via `window.platformByCode()`), account rows with `DEFAULT` badge + stat chips + themed persona
dropdown + a toggle switch for enable/disable, themed add-account/persona forms, and the FA-polling
toggle as a styled setting row. Defined the missing `.badge` primitive. Frontend-only — no backend
changes. Verified visually via a stubbed-API harness screenshot. CHANGELOG [2.38.0].

**Prior release — 2.37.2 — Fix: newly-connected platforms never got an account row**.
**Released + deployed** 2026-06-29 (tag `v2.37.2`). After connecting X/Bluesky (possible since 2.37.1)
they never showed on the Accounts page or got polled: `get_default_account_id(create=True)` inserted the
default-account row but never committed, so the pollers' `account_id=None` path and `server.py`'s
per-cycle `seed_default_accounts` (both close without committing) rolled it back every time. Fixed it to
`conn.commit()` after the INSERT; `GET /api/accounts` now seeds before listing so freshly connected
platforms appear immediately. Regression test in `tests/test_accounts.py`. CHANGELOG [2.37.2].

**Prior release — 2.37.1 — Fix: all platform "Connect" buttons were 500ing**.
**Released + deployed** 2026-06-29 (tag `v2.37.1`). Connecting any account (caught in prod for **X** and
**Bluesky**) crashed with `TypeError: _get_or_create_client() missing N required positional arguments`:
the pollers moved to multi-account signatures `_get_or_create_client(settings, <creds...>)` but all eight
`/auth/connect` handlers still called the old single-arg `(overlay)` form. Fixed each
`routes/{ao3,bsky,da,ik,sf,sqw,tw,wp}_api.py` to pass the creds its poller requires, plus a static
arity regression guard (`tests/test_connect_client_arity.py`). CHANGELOG [2.37.1].

**Prior release — 2.37.0 — Full-resolution Inkbunny import**:
**Released + deployed** 2026-06-29 (tag `v2.37.0`). Artwork import now re-fetches Inkbunny's **original
file** (`files[].file_url_full`) via the API — reusing the poller's cached session SID — instead of the
stored thumbnail (`_resolve_ib_full_url` in `posting/artwork_importer.py`, applied only for `ib`;
FA/Weasyl already store full-res). **SoFurry full-res is NOT feasible**: its `/s/{id}.data` reader
exposes no image URL and SF is text-centric, so SF art import stays unsupported (graceful, guarded).
DeviantArt/Itaku remain thumbnail-only (no full-res column).

**Prior release — 2.36.0 — Submissions hub, Phase 4** (bulk import + DeviantArt/Itaku + IB/SF guard):
**Released + deployed** 2026-06-28 (commit `4b1c4cf`, tag `v2.36.0`; VM-verified — IB guard imports a
real thumbnail, SF fails gracefully, DA/Itaku scanned). Completed the Submissions hub spec
(`docs/specs/submissions-hub.md`): bulk `import/bulk/{platform}` + "Import all" bar, DA/Itaku in
`PLATFORM_TABLES`, and the import image-validation guard.

**Prior release — 2.35.0 — Submissions hub, Phase 3** (gallery import):
**Released + deployed** 2026-06-28 (commit `7c57ca0`, tag `v2.35.0`; VM-verified end-to-end — FA import
downloaded a real 119 KB image, mapped tags/rating, linked, then reverted). Generic
`posting/artwork_importer.py` + `POST /api/artwork/import/{platform}/{submission_id}` + Import button.

**Prior release — 2.34.0 — Submissions hub, Phase 2** (discovered bucket + link-to-work):
**Released + deployed** 2026-06-28 (commit `e6afbaf`, tag `v2.34.0`; VM verified — 16 discovered
submissions). `/api/works/discovered` + `/api/works/link`; Discovered view with per-row work-picker.

**Prior release — 2.33.0 — Submissions hub, Phase 1** (unified per-work library):
**Released + deployed** 2026-06-28 (commit `1787d7e`, tag `v2.33.0`; CI published desktop assets; VM
verified — 16 works, 2 personas). `/api/works` + central **Submissions** tab; per-work grouping,
`All/Stories/Artwork` subtabs, persona filter; cards open the existing per-work detail.

**Prior release — 2.32.0 — Brand identity** (quill-tail logo + nib-badge app icon):
**Released + deployed** 2026-06-28 (commit `e6c1d31`, tag `v2.32.0`; CI published all three desktop
assets — `PawPoller-Setup-2.32.0.exe`, `PawPoller-windows-x64.zip`, `PawPoller-2.32.0-x86_64.AppImage`;
GCP VM `/api/health` reports `2.32.0`, clean boot; suite green, 175 passed / 1 skipped). New brand mark
in the dashboard sidebar + favicon (new `/img` static mount + `/favicon.ico` route; `frontend/index.html`,
`frontend/css/layout.css`, `dashboard.py`) and the desktop tray + EXE/taskbar icon (`assets/tray_icon.png`,
new `assets/pawpoller.ico`, `pawpoller.spec` — reaches desktop users via the v2.32.0 installers above).
Marketing site shipped separately to pawpoller.pages.dev (commit `a939e12`). CHANGELOG [2.32.0].

**Prior release — 2.31.0 — Artwork** (PostyBirb-style image posting across 7 platforms):
**Released + deployed** on 2026-06-27 (commit `e7cbe96`, tag `v2.31.0`; CI published all three desktop
assets; GCP VM `/api/health` reports `2.31.0`, clean boot, the content_type migration ran on the
production DB — log: "Rebuilt publications to fold content_type into UNIQUE"). Full suite green (175
passed, 1 skipped). End-to-end verified in-browser (upload → publish → `content_type='artwork'`
registry row, Stories views unaffected). ⚠ **FA / SoFurry / Weasyl / DeviantArt image posting is
implemented but needs a live smoke test** (can't post without creds); **DeviantArt also needs the DA
app re-authorized with `stash`+`publish` OAuth scopes**.

**2.31.0 artwork (this session)** — a standalone PostyBirb-style image uploader parallel to Stories.
Reuses the posting engine; analytics are free (pollers auto-discover the gallery). CHANGELOG [2.31.0].
- **Registry reuse** (`db.py`, `posting_queries.py`): additive `content_type` on publications/
  posting_queue/posting_log (`_rebuild_publications_content_type` folds it into the UNIQUE). Write/
  keyed query fns take `content_type="story"`; cross-story list reads filter to `'story'`;
  `get_pending_queue` stays unfiltered (scheduler routes on it). Defaults keep story callers unchanged.
- **Engine** (`posting/artwork_reader.py` NEW, `manager.post_artwork`, `scheduler.py`): one folder per
  artwork (image + `artwork.json`) under `artwork_archive_path` (Docker `/app/data/artwork`, desktop
  `…/m_x/Archives/Artwork`); `build_artwork_package` → a `StoryUploadPackage` with an image file_path
  fed through the SAME posters; records `content_type='artwork'`.
- **API + UI** (`routes/artwork_api.py` NEW, `frontend/js/artwork.js` NEW, `app.js`/`index.html`/
  `css/artwork.css`/`api.js`): `/api/artwork/*` (list/detail/upload/create-from-path/publish/image/
  settings/log/sync); `window.Artwork` hub + create flow + detail + `#/artwork` routes + nav entry.
- **Posters** — Inkbunny/Itaku/Bluesky verified (bsky got a Pillow downscale). FA `submit_visual`,
  SoFurry image-as-Artwork (MIME-aware `upload_content`), Weasyl `submit_visual`, DA Sta.sh
  (`oauth_stash_submit`+`oauth_stash_publish`) — **all need a live smoke test**; DA needs `stash`+
  `publish` scope re-auth. Desktop: `main.py` `js_api.open_image_dialog` bridge.
- **Follow-ups:** live-verify FA/SF/WS/DA + DA re-auth; multi-image galleries; per-platform category
  pickers in the UI (today FA/SF/WS categories come from `artwork_*` settings); artwork sync wired to
  the desktop pawsync flow.

**2.30.0 personas (prior session)** — the identity layer on top of the existing multi-account data
model. Four parts, all account-aware via the new `database/scope.py` `account_clause`. CHANGELOG [2.30.0].
- **Personas** (`database/personas.py` NEW): `personas` table + nullable `accounts.persona_id`
  (NULL = Unassigned; soft ref, no FK). CRUD + `assign_account_persona` + `list_accounts_by_persona`
  + `persona_stats` (sums `account_stats`). Synced via `_personas_manifest` (applied before accounts).
  API under `/api/personas` + `POST /api/accounts/{id}/persona`. Accounts page: Personas card +
  per-row persona `<select>`.
- **Per-account scoping** (`scope.py` + 11 `*_queries.py`/`*_api.py`): `get_*_summary` /
  `_submissions` / `_aggregate_snapshots` take optional `account_id` (None ⇒ All accounts, identical
  to before); endpoints gain `account_id` Query param. Context-bar **account selector** (`app.js`
  `_populateAccountSwitch`) appears when a platform has 2+ enabled accounts; threads `_acctId(code)`
  into dashboard/submissions/compare. Growth-rates + watcher counts stay aggregate (follow-up).
- **Per-persona notifications** (`polling/telegram.py`): digests (regular + weekly) emit **one
  message per persona** + Unassigned (per-account breakdown + combined totals); no-personas installs
  get the original single digest. Consolidated poll summary groups by persona. `check_milestones_batch`
  scoped by `account_id` (labels + fixes a multi-account double-fire). Instant alerts lead with a
  persona/account line (IB/FA explicit; 9 others via a `current_alert_account` ContextVar set in
  `server.py`). All labelling suppressed on single-unassigned-account installs.
- **Persona overview** (`accounts.js`, `app.js`): `#/persona/:id` — combined stat cards +
  per-platform breakdown + member accounts (each "View →" deep-links to the platform dashboard
  pre-scoped to the account).
- **Follow-ups:** desktop `.exe` not rebuilt (same as 2.29.0); growth-rate/watcher-count scoping +
  a per-persona Telegram chat override + a cross-platform combined time-series are deferred.

**2.29.0 redesign (prior session)** — a ground-up redesign of the dashboard **shell + navigation +
Home**, on the shared frontend (desktop + server), reusing the ~50 existing page-render functions
(only the chrome and the Overview changed). CHANGELOG [2.29.0].
- **Shell** (`index.html`, `css/layout.css`, `app.js` `init()`+`route()`): persistent **labeled
  sidebar** (collapse/pin, persisted to `localStorage`) + a **context bar** (clickable breadcrumb +
  platform switcher + Dashboard/Submissions/Compare sub-tabs, IB's un-prefixed routes special-cased)
  + surfaced ⌘K search + a responsive drawer / floating bottom tab bar on mobile. New type
  (**Bricolage Grotesque** + **Hanken Grotesk**) and vivid per-platform **colour tiles**; all 8
  token themes intact.
- **Platforms hub** (`#/platforms`, `renderPlatformsHub()`) replaces the modal popover — colour
  tiles + live status dots (reuses `platform_health` via `#pg-status-{code}`).
- **Configurable Home dashboard**: `renderOverview()` rewritten to a **widget grid** with a
  **customize mode** (add/remove/resize/drag); layout **server-saved** via the new additive
  `dashboard_layout` preference (`routes/api.py` get+save → `settings.json`).
- New files: `frontend/js/platforms.js` (canonical 11-platform registry + route helpers, replaces a
  5-way duplicated list) and `frontend/css/redesign.css` (hub tiles + dashboard widgets + header
  accent). Platform-detail headers pick up the brand colour via `route()` + CSS (no per-platform edits).
- **Legacy ⇄ Beta switch**: `dashboard.py` `serve_index` serves the new (`beta`) or the frozen
  pre-redesign (`legacy`) shell per `?ui=` (cookie-persisted `pp_ui`); a small fixed switch is
  injected into both. Legacy = `index_legacy.html` + `tokens_legacy.css`/`layout_legacy.css`/
  `app_legacy.js` (git-HEAD snapshots). Default `beta` (`_DEFAULT_UI`); flip to `legacy` for a
  zero-surprise rollout + one-click fallback.
- **Verified live** via Chrome DevTools on a local `uvicorn dashboard:app`: no JS console errors;
  desktop + mobile shell, the hub, and the configurable dashboard (incl. the **server-save
  round-trip**) all render. `node --check` on touched JS + `py_compile` on `routes/api.py` pass.
- **Staged follow-up**: editor / settings / posting / platform-detail tables keep working and get
  the full bold restyle later. Before deploy, regenerate any cached `*_SoFurry.html` per the note
  below if stories were touched.

---

### 2.28.x (deployed) — SoFurry beta migration + FurAffinity direct-scraper
The 2.28.x line completed the **SoFurry "beta" migration** (2.28.0 posting rebuild + 2.28.1
discovery fix) and the **FurAffinity direct-scraper** work: 2.28.2 refreshed the stale FA
submission parser (FA's HTML moved to `submission-page-stats` / `data-tag-name` / twitter-meta
rating) and wired the direct FA client through the CF Worker proxy so it can run on the **server**.
**2.28.0–2.28.3 are released + deployed** (`/api/health` reports `2.28.3`). **2.28.3** fixed a bug
2.28.2 introduced: its ReDoS mitigation bounded the stats regex whitespace too tightly (`\s{0,30}`)
and matched nothing on FA's deep indentation; the correct fix de-overlaps the quantifiers instead.
CHANGELOG [2.28.3].

**Server FA state — DONE 2026-06-24:** 2.28.3 deployed; FA `a`/`b` cookies in the
encrypted vault; `fa_use_cf_proxy=true` + `fa_direct_polling=true` — the server now
**direct-scrapes FA stats through the CF proxy** (verified live: views 324/364/203…),
off the flaky FAExport. 77 corrupt zero-snapshots cleaned. **Caveat:** under
`fa_direct_polling` the watcher/comment paths still go via FAExport (so they're paused
while it's down) — porting direct watchers (`/watchlist/by/{user}/` scrapes fine) +
comments off the `/view/` page is the remaining follow-up. Full SF API map:
`docs/reference/sofurry_beta_api_map.md`.

**Heads-up:** existing stories' `*_SoFurry.html` use the OLD class-based markup —
**re-generate** them so the SF converter emits the new TipTap HTML before re-uploading,
or the new render won't apply. FA direct polling must run from the **desktop** instance
(datacenter IP is Cloudflare-blocked). See "Multi-account model" below before touching
accounts / credentials / pollers / posting.

**Historical zero-snapshot cleanup — DONE 2026-06-23.** After deploying 2.27.2, the
one-off cleanup ran against prod: **746 corrupt `views=0` rows deleted** (ao3 25, sqw 270,
fa 451), each one provably bad (every zero belonged to a work that also had a non-zero
snapshot; cumulative counts never decrease). 0 remain. DB backed up first to
`/app/data/pawpoller.db.bak.1782177890`. Past charts and the 7-day weekly-digest baseline
are now clean; the 2.27.1 guards stop new ones forming.

---

## Multi-account (in progress) — multiple accounts per platform

**Goal:** run more than one account per platform (e.g. two FurAffinity accounts), all active
at once, for both polling and posting. Plan file:
`~/.claude/plans/stateless-nibbling-newell.md`. Pilot = Inkbunny + FurAffinity first, then
roll out the other 9. Same-platform accounts poll **sequentially** (per-IP rate limits).

**End-to-end status:** multi-account **polling works for ALL 11 platforms** on the server —
the orchestrator enumerates each platform's enabled accounts (sequential within a platform,
concurrent across platforms). Add a 2nd account on the Accounts page and it gets polled on
the next cycle with its own credentials, session, and segregated data. **Posting** "post as
account" is fully wired for IB + FA; the other posters still need the per-account
`_ensure_client` treatment (see remaining list).

**Landed so far (Phase 0 + IB + FA + WS verticals + orchestrator + posting + cross-cutting):**
- **`accounts` table** (`database/accounts.py`) — global surrogate `account_id`, one
  `is_default` account per platform (partial unique index). Seeded in `database/db.py`
  `_run_migrations` (Migration 0) for every platform that has credentials.
- **Credential model** (`config.py`): default account keeps the legacy flat keys
  (`username`, `fa_cookie_a`…); extra accounts use `acct_<id>_<field>` keys. Resolver
  `get_account_credentials` / `resolve_account_credentials`; vault routing via
  `is_credential_key` (catches namespaced secrets). **Zero credential migration** for
  existing installs.
- **Schema migrations** (`database/db.py`): additive `account_id` on IB
  submissions/snapshots/comments/poll_log/faving_users + posting_queue/posting_log
  (backfilled to the platform's default account — NOT literally id 1); constraint rebuilds
  in `_run_table_rebuilds()` on an FK-off connection: `session_cache` singleton →
  PK `account_id`, `watchers` → `UNIQUE(account_id, username)`, `publications` →
  `UNIQUE(story_name, chapter_index, platform, account_id)`.
- **IB queries** (`database/queries.py`): session/snapshot/submission/faving/watcher/
  poll_log writes all take `account_id`.
- **IB poller** (`polling/poller.py`): `run_poll_cycle(account_id=None, …)` — per-account
  creds + session; first-poll suppression is per-account; `account_id=None` ⇒ default account.
- **IB posting**: `posting_queries.upsert_publication` / `get_publication_by_story` are
  account-aware (default → platform default); IB poster `_ensure_client` reads
  `session_cache WHERE account_id = ?` (the old `id=1` shared-token read is GONE).
- **FurAffinity vertical** — additive `account_id` on `fa_submissions`/`fa_snapshots`/
  `fa_comments`/`fa_poll_log`/`fa_profile_stats`; `fa_watchers` rebuilt to
  `UNIQUE(account_id, username)` preserving spam columns; `fa_queries.py` (incl. the
  watcher spam-confirmation flow) and `fa_poller.py` are account-scoped;
  `send_fa_watcher_digest` iterates accounts.
- **Orchestrator** (`server.py` `_poll_all`) — enumerates enabled accounts for
  account-aware platforms (`ib`, `fa`), polling a platform's accounts sequentially and
  platforms concurrently; per-account creds gate via `accounts.DEFAULT_CRED_CHECKS`.
- **Account CRUD API** (`routes/accounts` in `routes/settings_api.py`) + Accounts page
  (`frontend/js/accounts.js`, nav + `#/accounts` route). Sync carries an `_accounts_manifest`.
- **Tests**: `tests/test_accounts.py`, `tests/test_migration_multiaccount.py` (legacy→multi
  upgrade for IB **and** FA, all green — 121 passed).

- **Posting "post as account"** — account-aware end to end (HTTP →
  manager → posters → scheduler → queue → DB). `POST /api/posting/post` takes
  `account_ids: {platform: id}`, `/api/posting/update` takes `account_id`;
  `manager._get_poster` is keyed `(platform, account_id)`; IB+FA posters
  authenticate per account; `update_story` updates each pub as its own account;
  the scheduler/desktop-auto-queue carry `account_id`.

- **Per-account stats** on the Accounts page (each account's subs/views/faves/
  comments side by side, via `accounts.account_stats` + `GET /api/accounts`).
- **Telegram** consolidated summary labels accounts when a platform has >1.
- **Drift** (`posting/sync.py`) change records carry `account_id`.

**Remaining:**
1. **Posting "post as account" for the other posters** — IB + FA posters
   authenticate per account in `_ensure_client`; the rest (`ws`, `sf`, `sqw`,
   `ao3`, `da`, `bsky`, `ik` posters) still read flat creds, so they post as the
   default account regardless of the selected account. Give each the same
   treatment the IB/FA posters got (read `config.resolve_account_credentials`
   + per-account session/cookies). The posting *data layer*
   (`posting_queries`/manager/scheduler) is already account-aware.
2. **Frontend "post as" selector** — the publish-check matrix
   (`frontend/js/publish_check.js`) should let you pick which account to post as
   and pass `account_ids` to `/api/posting/post`. Backend is ready.
3. **Deeper dashboard integration** — an account picker on the main per-submission
   charts/tables in `app.js` (the Accounts page already shows per-account rollups;
   the big dashboard still aggregates across accounts).
4. **Diagnostics per account**; desktop `main.py` account enumeration (polling is
   server-side, so lower priority).
5. **Version bump + CHANGELOG version entry + deploy** once the pilot is end-to-end.

**FurAffinity polling — FAExport upstream (resolved diagnosis, 2026-06-16):**
The owner (Deer-Spangle) replied on
[faexport#129](https://github.com/Deer-Spangle/faexport/issues/129): the public
`faexport.spangle.org.uk` instance is hitting a **persistent Cloudflare challenge
page** (now the standard managed-challenge interstitial, not a text error). He
**tried changing his VPS IP and still gets blocked**, and switched his own
services to a **locally-hosted FAExport** (which works); the public site is
best-effort and has been blocked unusually long. A community commenter
(bshahin101) mapped the Cloudflare codes: 1006/1007/1008 = IP-banned, 1015 =
rate-limited, managed challenge = needs a real browser/token — and noted a
managed challenge (which is what FA now serves) is **not** solvable by IP
rotation. **Implication for PawPoller:** the CF Worker proxy (IP rotation) will
NOT fix FA polling — it's a challenge, not just an IP block. The only viable
fixes are (a) **self-host FAExport** (the owner's own solution), or (b) the
**direct-FA-cookie polling** fallback (the posting path already talks to FA
directly via cookies). Owner may file an FA trouble ticket; no public-API ETA.

**Fallback (b) is now implemented.** `clients/fa/client.py` gained
`get_all_gallery_ids_direct` / `get_submission_details_batch_direct` /
`_parse_submission_html` — they scrape FA's gallery + submission pages directly
via the session cookies and return the same dict shape as the FAExport path. The
FA poller tries FAExport first and **auto-falls-back to direct on failure**; set
`fa_direct_polling=true` to skip FAExport entirely (recommended while it's
blocked). Comment/watcher/profile data is FAExport-only and skipped in direct
mode; the core views/faves/comments snapshot still works. **Run it from the
desktop instance** — FA's Cloudflare blocks the datacenter server IP. Parser
verified by `tests/test_fa_direct.py`. If FA HTML drifts, the regexes in
`_parse_submission_html` (stats/title/rating/tags) are the things to update.

**FA official policy + upcoming API (announced ~2026-06-22) — changes the plan.**
FA published a formal third-party / bot policy and announced an **official
read-only API** (invite-only closed beta; application form
https://forms.gle/8XNUo61fK4VyQdHA6 ; FA+ members can join via Discord). Net
effect for PawPoller:
- **The official read-only API is the proper long-term replacement** for BOTH
  FAExport and the direct-cookie scrape. Apply to the closed beta. Read-only is
  exactly what polling needs (views/faves/comments); writes (posting) come later.
- **Legitimise the current scraping NOW:** FA asks M2M scraping/verification
  services to file a **Trouble Ticket → Tech → "Access Requests"** so they can
  identify the traffic pattern and *retain* access; they also said they'll reach
  out to people whose scripts broke on CF blocks who filed tickets. File one for
  the desktop direct-polling traffic.
- **Stated technical rules:** ≤1 request/second (we're at 1.5s ✅), proper
  **exponential backoff** (direct path has NONE ⚠️), stand down during CF DDoS
  mitigation, and keep activity to periods with <15k users online. The direct
  path needs exponential backoff + explicit Cloudflare-challenge detection (a
  challenge page is HTTP 200 and silently parses to all-zero stats — the
  2.27.1 zero-snapshot guard now stops it corrupting data, but a real backoff is
  still the policy-compliant fix). Postybirb/FABUI are explicitly permitted; an
  app like PawPoller is the "third-party software" the access-request path covers.

**SoFurry "beta" rewrite (broke ~2026-06-13) — React Router SPA.**
SoFurry replaced the whole site with a React Router (Remix-style) SPA. What this
broke and where it stands:
- **Polling — FIXED ([2.27.2]).** Old gallery scrape + `/ui/submission/{id}` JSON
  API (now 404) + `/s/{id}` "N Views" text are all gone. New source: React Router
  loader data at `…​.data` URLs (turbo-stream). `/s/{id}.data` carries
  views/likes/comments/title **login-free** for published works. The poller now
  polls DB-known IDs (∪ discovery) via `/s/{id}.data`, so the time-series resumed
  without a working login. Parser = `_rr_int`/`_rr_str` in `clients/sf/client.py`,
  verified live against 5 works.
- **New-work discovery — degraded.** `/u/{handle}/gallery.data` is SFW-filtered
  when unauthenticated, so adult galleries return no items. Auto-discovery of NEW
  works needs a rebuilt authenticated session. Existing works keep polling fine.
- **Posting — STILL BROKEN, needs a dedicated rebuild.** Three things to redo:
  (1) **login** — the CF-Worker `x-proxy-login` flow is stale vs the new site (new
  login page still has a Laravel `_token` + `<meta csrf-token>`, so direct login
  may still work from a residential IP; the Worker's hardcoded login logic likely
  needs updating — Worker source is deployed on Cloudflare, not in this repo);
  (2) **create/edit API** — `create_submission`/`edit_submission` POST to the
  `/ui/submission` endpoints, which now 404. Reverse-engineer the new React Router
  action routes (likely `.data` POSTs with the `csrfToken` from the loader data);
  (3) **content format** — the editor is now TipTap/ProseMirror. Target HTML
  reference: `docs/reference/sofurry_beta_tiptap_sample.html`. The SF converter
  (`editor/converter.py` `_convert_body_sofurry`) currently emits
  `class="text-center"`/`"text-right"` alignment + `<p><strong>` pseudo-headings;
  the new renderer wants inline `style="text-align:…"` and real `<h1>/<h2>/<h3>`.
  Can't verify a render until login+create are working, so sequence: login →
  create/edit endpoints → converter, then post a test work and eyeball it.

**Riskiest watch-items:** any poster still reading `session_cache WHERE id=1` (silent
shared token); reintroducing the write-lock-across-await bug in pollers; account-manifest
sync surrogate stability; backfill landing on the right per-platform default account.

---

**Per-version history lives in `../CHANGELOG.md`** — every release has a full prose entry
there. Grep it by version (`## [2.26.1]`) instead of reading it whole. This file carries
only current state.

**Deployed to:** GCP instance `pawpoller` (zone `us-east1-c`), running 2.26.3 — in sync
with master.

**Ops notes (2026-06-10):**
- **Billing-lapse outage:** GCP billing lapsed in early June; Google TERMINATED the VM
  (polling down for up to ~2 weeks). Billing re-enabled + VM restarted 2026-06-10;
  container came back healthy on its restart policy. The ephemeral external IP changed:
  35.243.213.49 → **35.231.162.181** — anything pointing at the old IP (bookmarks,
  desktop pairing `posting_server_url`) needs updating. Consider a reserved static IP.
- **FAExport outage (FA polling dead since ~2026-05-26):** every JSON endpoint on
  faexport.spangle.org.uk 500s with `error_type: unknown_http` (web UI fine, all users,
  all client IPs — their scraper session against FA is broken, most likely a Cloudflare
  block of their egress IP in a page format their detection misses). Reported upstream
  with code-level diagnosis as
  [Deer-Spangle/faexport#129](https://github.com/Deer-Spangle/faexport/issues/129) —
  check there before re-investigating FA poll errors. Long-term fallback if it stays
  dead: direct-FA polling via cookie auth (the posting path already talks to FA directly).

**GitHub master:** https://github.com/knaughtykat01-prog/PawPoller — push-to-master
triggers no auto-deploy; ship with `/pp-deploy` (or `deploy/pawcli.bat`).

Living document — update as state shifts. Read this first when picking up a session.

---

## What PawPoller is

Multi-platform story publishing + polling pipeline for furry fiction. Runs two ways:

- **Desktop** (Windows exe / Linux AppImage): `main.py` → PyInstaller → pywebview +
  pystray. Needed for FA posting (datacenter IP blocks) and Edge-fallback PDF rendering.
- **Headless** (GCP/Docker): `server.py`. Polls 11 platforms, serves dashboard + editor,
  posts to everything except FA (auto-queued to desktop).

Port 8420. Story archive at `/app/story-archive` on server,
`../m_x/Archives/Complete_Stories/` locally.

## Where we are

**Public beta ready.** Everything on `ROADMAP_PUBLIC.md` through the must/should-haves is
shipped: setup wizard, embedded browser login, credential vault, story wizard,
multi-format editor with anchor toolbar, selective regeneration, publish-check matrix
with scheduling + retry queue + drift detection + draft probes, per-platform
tags/descriptions, cover/chapter thumbnails, EPUB output + in-app viewer, mobile mode,
8-theme picker, diagnostics tab (~170 tests), CLI TUI, Windows installer (Inno), Linux
AppImage, auto-updater, in-app uninstall. The feature-by-feature record is in CHANGELOG.

### Genuinely open work

- **Weasyl posting test** — blocked on account-level verification, not code.
- **Draft probes for Bsky / Wattpad / DA / Itaku / Weasyl** — confirm per-platform
  whether a draft state even exists before adding probes (FA/IB/SF/AO3/SqW are done).
- **AO3 import end-to-end verification** — code path identical to SqW (which works);
  test was blocked by AO3's throttle. Run imports from desktop (residential IP).
- **Bundled fonts in EPUB** — deferred until an EPUB appearance panel exists.
- **macOS desktop build** — same per-OS shim shape as Linux (2.25.0) plus .app/.dmg
  packaging; Apple Developer cert / notarization decision open.
- **Marketing site version refresh** — Hero version chip + GetIt CTA label are still a
  manual edit after each release (CF Pages auto-deploys on push to `site/**`).

---

## Critical file paths

### PawPoller
- `routes/editor_api.py` — all editor endpoints
- `routes/settings_api.py` — settings sync + vault + browser login + setup wizard
- `editor/converter.py` — format converters + anchor handling
- `editor/pdf_generator.py` — WeasyPrint + Edge fallback
- `editor/epub_generator.py` — EPUB output
- `posting/manager.py` — post_story / update_story + extras passthrough
- `posting/story_reader.py` — load_story, build_package, platform name cascade
- `posting/sync.py` — hash_file for drift detection
- `posting/platforms/{ib,fa,ws,sf,sqw,ao3,da,ik,bsky}.py` — 9 posters
- `clients/{ib,fa,weasyl,sf,sqw,ao3,da,wp,ik,bsky,tw}/client.py` — 11 platform clients
- `polling/{platform}_poller.py` + `polling/notifications.py` (shared helpers,
  `describe_error`) + `polling/cf_proxy.py` (proxy classification)
- `database/db.py` (connection + PRAGMAs) + `database/*_queries.py` + `*_schema.sql`
- `auth/browser_login.py` — pywebview cookie capture
- `frontend/js/{editor,metadata_editor,publish_check,platform_health}.js`
- `uninstall.py`, `updater.py`, `auto_sync.py`
- `tag_database/` — bundled in Docker image, **NOT under data/**
- `docs/ROADMAP_PUBLIC.md`, `docs/documentation_guide.md`
- `installer/PawPoller.iss` (AppId GUID must never change), `installer/build-appimage.sh`

### Archive / stories
- `../m_x/Archives/Complete_Stories/` — story folders (`_Test_Story/` = known-good fixture)
- `../m_x/Scripts_Utils/regenerate_story.py` — CLI regenerator / desktop fallback

### Tag DB (canonical — edit here, not in PawPoller)
- `C:/Users/rhysc/claude/Tag_Database/` → copy to `PawPoller/tag_database/` → commit →
  push → deploy

---

## Deploy cheat sheet

```bash
# Code changes (or just use /pp-deploy)
cd C:/Users/rhysc/claude/PawPoller
git add <files> && git commit -m "..." && git push
gcloud compute ssh pawpoller --zone=us-east1-c --command="cd /home/kithetiger/PawPoller && sudo -u kithetiger git pull && sudo docker compose up -d --build"

# Story archive: local -> server / server -> local
deploy/pawpush.bat            # alias: pawsync.bat; supports --prune / --dry-run / --force
deploy/pawpull.bat [Story]    # full sync or single story

# Verify
gcloud compute ssh pawpoller --zone=us-east1-c --command="curl -s http://localhost:8420/api/health"
gcloud compute ssh pawpoller --zone=us-east1-c --command="sudo docker compose -f /home/kithetiger/PawPoller/docker-compose.yml logs --tail=30 pawpoller"
```

Pause/resume polling: `POST /api/poll/pause` / `/resume` with `Authorization: Bearer pp_…`
(key in server settings.json).

---

## Known gotchas (don't get caught again)

1. **Tag DB location**: `/app/data/` is a Docker volume — it SHADOWS bundled files.
   That's why `tag_database/` lives at PawPoller root.
2. **story.json `index` not `number`** in `chapter_info[]` entries.
3. **Default tag cascade**: `default` tags cascade to every poster in `_parse_story_json()`.
4. **SQW is per-chapter only** — full-story SQW cell shows `not_supported`.
5. **FA posting requires desktop** — server posts auto-queue for desktop pickup.
6. **pawsync must precede code push** referencing new story files; it pre-checks server
   freshness and aborts if the server copy is newer (then: pawpull first, or `--force`).
7. **Server perm on archive**: container runs uid 1001, archive owned by kithetiger
   (1000); pawsync does `chmod o+rwX`.
8. **WeasyPrint on Windows**: missing GTK → automatic Edge headless fallback.
9. **confirm_live guard**: backend rejects post/update without `confirm_live=true`.
10. **Never hold a SQLite write transaction across an await** in pollers — commit before
    any network fetch that follows a write (2.26.3; busy_timeout is 30s and AO3's 12s
    pacing held the lock for minutes).
11. **AO3 routes direct from GCP** (`PROXY_OPTIONAL_PLATFORMS`) — the shared CF Worker
    egress pool burns AO3's per-IP quota (2.22.11). CF proxy is for DA + SF only.

---

## Claude Code automation

Two skills + two subagents live under `~/.claude/` (global, not in this repo):

| Ask | Use |
|---|---|
| "cut v2.27.0" / "release" | `/pp-release 2.27.0 "blurb"` — verifies (both subagents in parallel), commits, tags, pushes, watches CI, confirms 3 release assets |
| "deploy to prod" / "pawupdate" | `/pp-deploy [version]` — sync-check, confirm, SSH rebuild, health + log verification |
| "is the release ready to tag?" | `release-verifier` subagent (read-only: version/CHANGELOG/HANDOFF/AppId-GUID/tests/tree checks → SAFE TO TAG / DO NOT TAG) |
| "audit security of recent changes" | `security-reviewer` subagent (read-only, scoped to auth/credential/shell-out/path surface → SAFE / BLOCK) |

Both skills are `disable-model-invocation: true` — only the user typing them fires them.
Files: `~/.claude/skills/pp-{release,deploy}/SKILL.md`,
`~/.claude/agents/{release-verifier,security-reviewer}.md`.

---

## CI / release pipeline

`Build & Release` fires on `v*` tag pushes: `build-windows` (PyInstaller zip + Inno
installer), `build-linux` (ubuntu-22.04, AppImage), `test` (pytest, 91 green). `Lint`
(ruff + JS syntax) on every master push. Release uses `softprops/action-gh-release@v3`
(v2 broke 2026-05-26 — see CHANGELOG [2.26.2]). Known flake: asset upload can hit a
transient "Server Error"; `gh run rerun --failed` recovers it. Three assets per release:
windows zip, `PawPoller-Setup-*.exe`, `*-x86_64.AppImage`. Tags lag master by design —
last tag v2.26.x; cut releases deliberately, not per-commit.

Marketing site (https://pawpoller.pages.dev) auto-deploys via CF Pages on master pushes
touching `site/**`.

---

## QA

All QA artefacts under `qa/`:
- `qa/TESTING_CHECKLIST_WEBAPP.html` — ~566 rows, browser/Docker surface
  (localStorage `pawpoller_test_webapp`)
- `qa/TESTING_CHECKLIST_NATIVE.html` — ~638 rows, Windows/Linux desktop surface
  (localStorage `pawpoller_test_native`)
- `qa/fixtures/` — reproducible upload payloads (see its README)
- `qa/AUTOMATED_BUG_LOG.md` — Playwright sweep findings (all filed bugs through BUG-021
  fixed or retracted as of 2.16.14)

Sweep WEBAPP first (covers the Docker surface), NATIVE on a real Windows build for the
native-only sections. Python unit tests live in `tests/` — different surface.

---

## For the next session

1. This file.
2. `../CHANGELOG.md` top entry (and grep deeper history as needed).
3. `documentation_guide.md` for architecture depth (poller patterns, DB PRAGMAs + the
   write-lock rule, EPUB viewer, auto-sync, diagnostics).
4. `routes/editor_api.py` + `routes/settings_api.py` if touching the API surface.
