# Information-Architecture Consolidation — Design Spec

**Status:** Proposal (spec only — no code) · **Author:** Rhys + Claude · **Date:** 2026-07-13
**Problem in one line:** the content side of the app has grown to **eight overlapping nav
surfaces** and reads as "a mess." This doc maps what each one actually does today, names the
three redundancy clusters, and proposes a reduced target IA (~4 surfaces) with a phased,
independently-shippable migration that retires nav before it merges data.

> Related specs: `docs/specs/collections.md` (the surface we consolidate *toward*),
> `docs/specs/submissions-hub.md` (the `/api/works` aggregation both Library and Submissions ride on).

---

## (a) Current state — the eight surfaces

Nav lives in `frontend/index.html` (lines ~112–173): **Library** is a top-level item; **Submissions /
Stories / Artwork / Posts / Collections / Queue / History** sit under the "Publishing" group;
**Groups / Cross-Platform** sit under "Insights & Tools". Router dispatch is in
`frontend/js/app.js` `route()` (~lines 1021–1085).

| # | Surface (route) | Renderer | What it shows | Backing API / DB | Overlaps |
|---|---|---|---|---|---|
| 1 | **Library** (`#/library`) | `window.Bookshelf` (`frontend/js/bookshelf.js`) | Cover-forward "shelf" of every **work** (stories + artwork). Type/persona/search/sort. Rich **story** detail at `#/library/work/{name}` (per-platform "Published to", chapter×platform reach, per-work medals). | `GET /api/works` (list) + `GET /api/posting/stories/{name}` (detail). Adds **no** backend. | **Submissions** (identical data + filters); **Artwork/Posting** (detail pages) |
| 2 | **Submissions** (`#/submissions`) | `window.Submissions` (`frontend/js/submissions.js`) | Card-grid of every **work** (stories + artwork). All/Stories/Artwork subtabs, persona filter, search, sort. Plus a **Discovered** bucket (`#/submissions/discovered`): polled-but-unmanaged posts → link-to-work / import. "＋ Collection" on cards. | `GET /api/works` (**same endpoint as Library**) + `GET /api/works/discovered`, `POST /api/works/link`, `POST /api/artwork/import/*` (`routes/submissions_api.py`, `routes/artwork_api.py`) | **Library** (near-duplicate); Discovered also in **Artwork** |
| 3 | **Artwork** (`#/artwork`) | `window.Artwork` (`frontend/js/artwork.js`) | Gallery merging **library art** + **discovered art tiles**, folded by cross-platform links into "masters". Uploader (`#/artwork/new`) publishes an image to art sites. Per-art detail (`#/artwork/image/{name}`). "Select to unify" builds a `submission_link` master with pooled stats. | `GET /api/artworks`, `POST /api/artwork/publish`, `POST /api/artwork/upload`, `GET /api/works/discovered`, `GET /api/links` (`routes/artwork_api.py`) | **Library/Submissions** (art rows); **Cross-Platform** (reads/writes `submission_link`) |
| 4 | **Posting / "Stories"** (`#/posting`) | `Posting` (`frontend/js/posting.js`) | The **story publish engine**: card grid of stories, story detail with per-platform **upload/update** controls, pending-queue callout, drift detection, comparison chart, timeline, per-platform tags. Sub-pages Queue (`/posting/queue`) + History (`/posting/log`). | `GET /api/posting/stories`, `GET /api/posting/stories/{name}`, `POST /api/posting/post`, update/queue/log (`routes/posting_api.py`) | **Library** story detail duplicates most of this; publish parallels **Artwork** |
| 5 | **Posts** (`#/posts`) | `window.Posts` (`frontend/js/posts.js`) | Microblog composer + feed. Write once → Bluesky/Mastodon/Threads/Tumblr/X/Instagram. @mention handle-book (contacts). | `POST /api/posts`, `POST /api/posts/{id}/publish`, `GET /api/posts`, `/api/posts/contacts` (`routes/posts_api.py`) | **Distinct** short-form surface — the one clear keep |
| 6 | **Collections** (`#/collections`) | `window.Collections` (`frontend/js/collections.js`) | The newest bundler: one master container per *piece* across every platform. Polymorphic members (`work`/`submission`/`post`), **pooled analytics + merged tags + personas + all locations + companion story + cover**. "Add to Collection" pickers. | `/api/collections*` (`routes/collections_api.py`) → `database/collections_queries.py` `rollup_collection` | **Superset** of Groups + Cross-Platform |
| 7 | **Groups** (`#/groups`) | `App.renderGroups` / `renderGroupDetail` (`frontend/js/app.js` ~8066) | Manually tag submissions from any platform into arbitrary named bundles ("Commission Pieces") for **combined stat tracking**. Add member via **`prompt()`** for platform + submission ID. | `/api/groups*` (`routes/api.py` ~1600) → `database/group_queries.py` (`submission_groups`, `submission_group_members`); `get_group_stats` pools views/faves/comments | **Collections** (weaker, submission-only, no tags/personas/story) |
| 8 | **Cross-Platform** (`#/cross-platform`) | `App.renderCrossPlatform` (`frontend/js/app.js` ~8220) | Link the **same** submission across platforms (1:1) → combined stats + snapshot chart. **Auto-suggests** links by title similarity. Create via **`prompt()`** `"ib:12345, fa:67890"`. | `/api/links*` + `GET /api/links/suggestions` (`routes/api.py` ~1737) → `database/analytics_queries.py` `get_links`, `get_link_combined_stats`, **`auto_suggest_links`** (`submission_link`, `submission_link_members`) | **Collections** (older core idea); **feeds Artwork** masters |

---

## (b) Problems — three redundancy clusters

### Cluster A — Library ≡ Submissions (the works library, built twice)
`bookshelf.js` and `submissions.js` both fetch **`GET /api/works`** and re-implement the *same*
type/persona/search/sort logic (`_filtered()` in each is nearly line-for-line identical). The only
real differences:
- **Library** = editorial "shelf" styling + a rebuilt rich **story** detail (`#/library/work/{name}`
  with chapter×platform reach + work medals) + a Laurels link.
- **Submissions** = plainer card grid + the **Discovered** bucket (link/import) + "＋ Collection".

`bookshelf.js`'s own header comment says it "does NOT replace the Submissions hub" — i.e. the overlap
was known and accepted at build time. Two nav items, one data source, one mental model.

### Cluster B — Collections vs Groups vs Cross-Platform (three "bundle a piece" surfaces)
All three answer "show me one piece's reach across platforms," at three power levels:
- **Cross-Platform** — 1:1 same-content links, submission-only, pooled stats, **+ auto-suggest** (`auto_suggest_links`, Jaccard ≥ 0.6). Data model `submission_link`.
- **Groups** — arbitrary named bundles, submission-only, pooled stats, `prompt()` curation. Data model `submission_groups`.
- **Collections** — curated **cross-type** bundles (work + submission + post) with pooled analytics **+ tags + personas + companion story + cover**. Strict superset of the other two.

Both older surfaces curate via `prompt()` dialogs ("Platform (ib, fa, ws…)", "ib:12345, fa:67890") —
unusable at scale. Collections already does everything they do and more; `docs/specs/collections.md`
§2/§8 explicitly frames unify/masters as a *feeder* for Collections, not a peer.

### Cluster C — two publish engines (Posting vs Artwork), split by content type
Story publishing lives in `posting.js` + `routes/posting_api.py` (`POST /api/posting/post`);
art publishing lives in `artwork.js` + `routes/artwork_api.py` (`POST /api/artwork/publish`).
They are parallel engines with **three** near-duplicate "work detail" pages: `posting.js`
`renderStoryDetail`, `bookshelf.js` `renderWork`, and the `submissions.js`/`artwork.js` cards.
A user choosing "where do I go to post this?" has to first know whether it's a story or an image.

---

## (c) Proposed target IA (~4 surfaces)

Collapse eight content surfaces to **three primary destinations** + one demoted publishing-utility area.

1. **Library** — *the* works home. One grid of every work (stories + art) with a **type filter**
   (All / Stories / Artwork), persona, search, sort, **plus the Discovered bucket** (link/import).
   Absorbs Submissions, the Artwork gallery, and the Stories browse hub. Every card opens the one
   **unified Work detail**.
   - **Work detail** = today's rich story detail (per-platform "Published to", chapter×platform
     reach, analytics, timeline) generalised to art, **plus the single Publish/Update action**
     (routes to `posting_api` for stories, `artwork_api` for art — engines stay, entry point unifies).
     "Add to Collection" lives here. This replaces `renderStoryDetail` + `renderWork` +
     `#/artwork/image/{name}` with one page.
2. **Posts** — microblog composer + feed. **Unchanged.** The one genuinely distinct surface.
3. **Collections** — *the* "bundle a piece across platforms" surface. Absorbs Groups + Cross-Platform.
   Gains an **arbitrary-bundle** affordance (Groups' use-case) and the **auto-suggest** feed
   (Cross-Platform's engine, re-pointed to propose Collections — already `collections.md` §7 Phase 4).
4. **Publishing activity** (demoted) — **Queue** + **History** kept but pulled out of primary nav
   (tabs on the Work detail, or folded into the existing Activity/`#/ledger`). Support views, not destinations.

### Before → after mapping

| Today (route) | Fate | Lands in |
|---|---|---|
| Library `#/library` | **KEEP** as canonical home | **Library** |
| Submissions `#/submissions` | **MERGE** → Library | Library (+ Discovered bucket, import, ＋Collection) |
| Submissions/Discovered `#/submissions/discovered` | **MOVE** | Library sub-view |
| Artwork gallery `#/artwork` | **MERGE** → Library (art filter) | Library; publish → Work detail |
| Artwork detail `#/artwork/image/{name}` | **MERGE** → unified Work detail | Library Work detail |
| Artwork uploader `#/artwork/new` | **KEEP** as "New work / publish image" | Library "＋ New" / Work detail |
| Posting/Stories `#/posting` | **MERGE** → Library (story filter) | Library |
| Story detail `#/posting/story/{name}` | **MERGE** → unified Work detail | Library Work detail |
| Queue `#/posting/queue` | **KEEP, demote** | Publishing activity |
| History `#/posting/log` | **KEEP, demote** | Publishing activity / Activity |
| Posts `#/posts` | **KEEP** | Posts |
| Collections `#/collections` | **KEEP** as canonical bundler | Collections |
| Groups `#/groups` | **RETIRE** → Collections | Collections (arbitrary bundle) |
| Cross-Platform `#/cross-platform` | **RETIRE** → Collections | Collections (+ auto-suggest feed) |

Nav: **8 content items → 3 primary** (Library · Posts · Collections) + a small Publishing-activity area.
Keep `#/editor` (Create) and Insights/Tools as-is.

---

## (d) Shared Visual Picker component

**The pain today:** every "choose a work/submission/post" flow is a title-only `<select>` or a raw
`prompt()` — impractical past a few dozen works:
- `submissions.js` `_discRow` → `<select id="disc-sel-{i}">` "Link to work…" (a flat option list).
- `collections.js` `_addMemberBrowser` → text-only `.coll-pick-row` buttons, capped at `.slice(0,200)`.
- `collections.js` `pickAndAdd` → `prompt('New collection name:')`.
- Groups `renderGroupDetail` → `prompt('Platform (ib, fa, ws…)')` + `prompt('Submission ID:')`.
- Cross-Platform `renderCrossPlatform` → `prompt('platform:id, platform:id')`.

**Proposal:** one reusable modal, `WorkPicker`, that looks like the Library grid — **thumbnail +
title + type chip + platform badges + search/filter** — returning structured selections. The data it
needs is already the shape `GET /api/works` returns (`thumb_url`, `title`, `content_type`,
`platforms`, `persona_ids`), so no new backend.

```
WorkPicker.open({
  mode:        'single' | 'multi',          // one pick, or a checkbox multi-select
  sources:     ['work','submission','post'],// which pools to load + show as tabs
  filterType:  'all'|'story'|'artwork',     // initial type filter
  persona:     0,                           // initial persona filter (0 = all)
  preselected: [{member_type, member_ref}], // greyed/ticked already-in items
  title:       'Add to collection',
  confirmLabel:'Add',
  onPick:      (items) => {...}             // [{member_type, member_ref, label, thumb}]
})
```

**Behaviour**
- Loads `GET /api/works` (works), `GET /api/works/discovered` (submissions), `GET /api/posts` (posts)
  per `sources`; caches like the hubs do; filters **client-side** (snappy) with the same
  type/persona/search controls Library already renders.
- Grid of visual cards (reuse `.story-card` / `.shelf-grid` markup). Click = pick (single, closes) or
  toggle (multi). Confirm returns the selection; `member_ref` is built in the picker
  (`"artwork:Name"`, `"fa:12345"`, `post_id`) so callers stay dumb.
- CSP-safe: built + wired in JS, delegated listeners, no inline handlers (matches
  `collections.js` `_shell`/`_modal`).

**Reused everywhere a work is chosen**
- Collections **Add member** and **Add to Collection** (replaces `_addMemberBrowser` + `pickAndAdd`).
- Discovered **Link to work** (replaces the per-row `<select>`).
- Collections **companion-story** linker.
- The Collections-based replacements for Groups (arbitrary bundle) and Cross-Platform (pick 2+ to link),
  killing both `prompt()` flows.

---

## (e) Migration plan — phased, lowest-risk first

Ordering principle: **retiring a nav item is cheap and reversible; merging data models is expensive
and one-way.** Do the reversible cosmetic work first, prove the target surfaces carry the load, then
migrate data last. Every phase ships on its own.

- **Phase 1 — Nav de-clutter (cosmetic, reversible).** Pull **Groups** and **Cross-Platform** out of
  primary nav (leave the hash routes + `/api/groups`, `/api/links` alive so nothing 404s). Optionally
  surface a "Legacy links/groups" link from Collections. *No data change.* Immediately makes the app
  feel less messy; trivially undone.
- **Phase 2 — Build the Visual Picker.** Ship `WorkPicker` and swap it into Collections add-member,
  Discovered link-to-work, and the companion-story linker. Pure frontend, additive; existing flows
  keep working until each call site is switched.
- **Phase 3 — Auto-suggest → Collections.** Re-point `auto_suggest_links` output to propose
  **Collections** ("these 3 look like one piece — make a Collection?") — the deferred half of
  `collections.md` §7 Phase 4. Add an **arbitrary-bundle** entry in Collections so Groups' use-case
  ("Commission Pieces") is covered. After this, Groups + Cross-Platform are functionally superseded.
- **Phase 4 — Merge Submissions into Library.** Fold the Discovered bucket + import + "＋ Collection"
  into `bookshelf.js`; retire `#/submissions` (redirect → `#/library`). Both already read `/api/works`,
  so this is de-duplication, not new behaviour. Delete `submissions.js` once the redirect is proven.
- **Phase 5 — Unify Publish + fold Artwork/Stories hubs.** Add the single **Publish/Update** action to
  the unified Work detail, delegating to `posting_api` (story) / `artwork_api` (art). Fold the Artwork
  gallery and Stories browse into Library's type filter; retire `#/artwork` and `#/posting` as nav
  items (redirect to Library filtered). Engines and routes unchanged — only the entry point unifies.
- **Phase 6 — Data migration + retire legacy pages (hardest, last).** Migrate `submission_groups`
  and `submission_link` rows into `collections` / `collection_members` (a group/link → a Collection of
  `submission` members). **Keep the `submission_link` table + `/api/links` alive** as the auto-suggest
  feeder and the Artwork "Unify" backend (see Risks). Only after data is migrated, remove the standalone
  Groups + Cross-Platform renderers.

**Independent rollup fix (any time, small):** close the Collections rollup gap in §(f).

---

## (f) Risks & things to preserve

1. **Don't lose auto-suggest.** `analytics_queries.auto_suggest_links` (Jaccard ≥ 0.6) is the only
   automatic same-piece detector in the app and the highest-value part of Cross-Platform. Re-target it
   to propose Collections — **never delete it** with the page.
2. **Don't orphan `submission_link`.** The **Artwork** hub reads it (`artwork.js` `_foldMasters` via
   `GET /api/links`) and writes it ("Unify selected"). Retiring the Cross-Platform *page* must not drop
   the `submission_link` / `submission_link_members` tables or the `/api/links*` routes — they stay as
   the masters backend and suggest feeder. (Decision to make: does "Unify" now create a Collection
   directly, or keep minting `submission_link` masters that seed Collections?)
3. **Don't orphan existing Groups/Collections data.** Migrate `submission_groups` into Collections
   before removing the Groups page; keep `/api/groups*` until the migration runs. Collection delete
   already only unlinks members (`collections_queries.delete_collection`), so members survive.
4. **Keep routes working through the transition.** Retire nav entries first; keep hash routes +
   `/api/works`, `/api/links`, `/api/groups`, `/api/collections`, `/api/posting/*`, `/api/artwork/*`
   responding. Old routes should **redirect** (e.g. `#/submissions` → `#/library`), not 404 — bookmarks,
   the command palette, and deep links point at them.
5. **Collections rollup gap (fix regardless of the IA work).** In
   `collections_queries.rollup_collection`:
   - **`post` members contribute nothing** — the code comment says *"Left out of stats rollup
     intentionally."* A Collection that bundles the X/Bsky posts announcing a piece shows none of their
     reach.
   - **The artwork attached to a posting isn't surfaced.** `work`/`submission` members resolve into
     stat rows (`_location_from_submission`), but the piece's **image/thumbnail** is never pulled in —
     so a Collection of art still shows the 🗂️ placeholder cover (`cover_ref` only set when
     `cover_kind='url'`) and the Locations table has no visual. Fix: resolve each art member's thumb
     (`/api/artwork/image` for works, `thumbnail_url` for discovered submissions) into the location row
     and auto-derive the Collection cover from its primary art member.
6. **Preserve the heavy story-publish workflow.** `posting.js` `renderStoryDetail` carries real
   machinery — pending queue, drift/`change_status` detection, chapter×platform gaps, growth
   comparison, per-platform tags. Merging it into the unified Work detail must carry all of it, not a
   simplified subset.
7. **Persona correctness.** Rollups depend on publications carrying the right `account_id`
   (`collections.md` §3, fixed 2.96.0). Any new merge path (unify → Collection, link → Collection)
   must set `account_id` the way `submissions_api.link_submission` /`_submission_account_id` does, or it
   re-introduces the "everything lumps under the default account" bug.

---

## (g) Open questions for the owner

1. **Stories as a filter, or a saved view?** Does the "Stories" hub fully dissolve into a Library type
   filter, or stay as a named tab (some muscle memory + the story-only publish flow)?
2. **Where do Queue + History live?** Tabs on the Work detail, a small "Publishing" utility area, or
   fold History into Activity (`#/ledger`)? History is an audit log — does it belong with Activity?
3. **Migrate legacy links/groups, or only feed suggestions?** Auto-convert every `submission_link` /
   `submission_group` into a Collection, or leave them read-only and only let auto-suggest *propose*
   Collections going forward? (`collections.md` §8 asks the same for masters.)
4. **What does "Unify" mean after this?** In the Artwork gallery, does "Unify selected" keep creating
   `submission_link` masters (that seed Collections), or create a Collection outright?
5. **One Publish button, or keep art/story affordances distinct?** Story upload is per-chapter with
   drift detection; art is single-image. Is a single "Publish/Update" honest, or do they stay visually
   separate on the unified Work detail?
6. **Cross-persona Collections** — allow one piece posted under two personas in one Collection (show
   both dots), or keep persona a hard boundary? (Still open in `collections.md` §8.)
7. **Vocabulary.** If Library is the home, do "Submissions" / "Artwork" / "Stories" disappear as nav
   words entirely, surviving only as filter labels?
