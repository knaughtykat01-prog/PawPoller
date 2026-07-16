# Masterpieces — Design Spec

**Status:** Proposal (spec only — no code) · **Author:** Rhys + Claude · **Date:** 2026-07-16
**One line:** give an image the same "master record" a story already has. Today a story is a
`MASTER.md` + `story.json` that every platform upload is derived from and kept in sync with; an
**image has no equivalent**. A **Masterpiece** is that missing master-per-image, and the thing every
FA / Weasyl / Inkbunny / Bluesky / e621 / Instagram copy of one picture points back to.

> Related specs: `docs/specs/collections.md` (the cross-type bundler a Masterpiece can *belong to*
> but must not duplicate), `docs/specs/linking_picker_overhaul.md` (the `WorkPicker` + tag-browser +
> perceptual-hash machinery this reuses wholesale), `docs/specs/ia_consolidation.md` (the surrounding
> IA cleanup — this spec **supersedes** its "fold art masters into Collections" call; see §7).

---

## 1. Concept & boundary

### 1.1 What a Masterpiece is

A **Masterpiece** (working name; "Masterwork" is the fallback) is the **master record for ONE image**.
It is the image analog of how a story works:

| Story (today) | Masterpiece (proposed) |
|---|---|
| `Markdown/MASTER.md` — canonical source text | the canonical **full-res image file** |
| `story.json` — real title, rating, tags, characters, per-platform overrides | `masterpiece.json` — same shape, for an image |
| `publications` rows — every platform the story was posted to, kept in sync via `update_story` | `masterpiece_members` rows — every site-upload of the image, kept in sync via `update_masterpiece` |
| Editor → publish-check → post/update from the Create area | Gallery → promote → publish/update from the Create area |

The **canonical metadata is the single source of truth**: edit the title / description / tags / rating
on the Masterpiece, and a "sync" pushes that to every site-upload that supports editing — exactly as a
story's edits propagate. This is the concept that is **currently missing**: PawPoller can post one
image to eight sites, but afterwards those eight uploads are eight unrelated rows with no shared master.

**A Masterpiece is the formalisation of the existing "local artwork folder."** The Artwork hub already
stores one folder per image (`artwork.json` + image; see `posting/artwork_reader.py`) with canonical
title/description/rating and per-platform tag/title/description/category overrides — that is *already* a
per-image master in everything but name and cross-site membership. The Masterpiece **upgrades that
folder in place** (`artwork.json` → `masterpiece.json`, a back-compatible superset) and adds the one
genuinely new thing: a first-class link from the master to **every** site-upload of the image, including
copies discovered by polling that were never posted through PawPoller.

### 1.2 The four concepts, disambiguated

There must be zero ambiguity between Masterpiece, the Gallery, a Collection, and the Submissions hub.

| Concept | Grain (what is "one" of these) | Holds | Backed by | Its job |
|---|---|---|---|---|
| **Masterpiece** | **ONE image** | Canonical title/desc/tags/rating/characters + the source image; membership = **the same image's uploads across sites** | `masterpiece.json` on disk (metadata) **+** `masterpiece_members` table (cross-site links) | Master a single image so every site copy stays in sync + pools its stats |
| **Artwork = Gallery** | **ONE raw tile** (a single discovered-or-imported image) | A thumbnail, a source platform, a `submission_id` | `{platform}_submissions` rows (+ un-promoted local images) | The **raw pool you promote FROM** into Masterpieces — a grid, not a manager |
| **Collection** | **ANY mix of pieces** | Polymorphic members: **Masterpieces + stories + posts** (and legacy submissions) | `collections` + `collection_members` | **Cross-type** bundle ("this piece + its companion story + the tweets announcing it") for pooled stats |
| **Submission (Submissions hub)** | **One local managed work** | A story **or** a Masterpiece + its publications | `/api/works` aggregation over `publications` | Browse/manage/publish local works (stories + art). **Not** a bundler |

The two grouping surfaces are orthogonal and **must not duplicate each other**:

- A **Masterpiece is PER-IMAGE mastering** — every member is *the same picture* on a different site.
  It answers "where does THIS image live, and are all copies in sync?"
- A **Collection is CROSS-TYPE grouping** — members are *different things* about one creative piece
  (the art, the written companion, the announcement posts). It answers "show me everything about this
  release, pooled."

A Masterpiece can be a **member of** a Collection (see §7); a Collection can never be a member of a
Masterpiece. If you find yourself putting two *different* images in one Masterpiece, you want a
Collection; if you find yourself putting the same image's FA + IB copies in a Collection, you want a
Masterpiece.

---

## 2. Data model / DB schema

### 2.1 Design principle — mirror the story model exactly

Stories keep **canonical metadata on disk** (`story.json`, diffable, backup-able, the source of truth)
and the **relational part in SQLite** (`publications` — which platform, which account, external id,
stats join key). Masterpieces do the same. This is deliberate: it reuses `artwork_reader` /
`post_artwork` / the `publications` registry with almost no change, and it matches the user's stated
mental model ("one canonical source file + one JSON").

**On disk** — the Masterpiece archive folder (the current artwork archive, `posting/artwork_reader.get_artwork_archive_path()`),
one folder per image:

```
{masterpiece_archive}/{Name}/
  image.png                 # the canonical full-res source image  (== story MASTER.md)
  thumbnail.png             # optional separate thumb
  masterpiece.json          # canonical metadata  (== story.json)
```

`masterpiece.json` is a back-compatible **superset of today's `artwork.json`** (a reader that finds
`artwork.json` treats it as a Masterpiece with no members yet):

```jsonc
{
  "title":        "Canonical title",
  "description":  "Canonical description",
  "rating":       "explicit",              // general | mature | explicit(/adult)
  "characters":   ["char_a", "char_b"],    // NEW — parity with story.json
  "image":        "image.png",
  "thumbnail":    "thumbnail.png",
  "phash":        "b3c1…",                 // dHash of image.png (image_hash.dhash_from_path)
  "tags":         { "default": ["…"], "fa": ["…"] },   // per-platform, "default" cascades
  "titles":       { "fa": "…" },           // per-platform overrides (unchanged from artwork.json)
  "descriptions": { "default": "…", "announcement": "…" },
  "categories":   { "fa": { "cat": "…", "species": "…" } },
  "platforms":    ["ib", "fa", "ws", "bsky"],
  "import_source": { "kind": "promote", "platform": "fa", "submission_id": "67890" },
  "migrated_from_link_id": 42,             // provenance when created by the submission_links migration
  "created_at":   "2026-07-16 04:00:00",
  "updated_at":   "2026-07-16 04:00:00"
}
```

**In SQLite** — one required new table plus one recommended thin index table.

```sql
-- REQUIRED: the genuinely-new relational data — the cross-site membership.
-- Same (platform, submission_id) shape as submission_link_members and a
-- Collection's 'submission' members, so masters, links and collections all
-- reference site-uploads identically.
CREATE TABLE IF NOT EXISTS masterpiece_members (
    masterpiece_id  INTEGER NOT NULL,        -- FK -> masterpieces.id (ON DELETE CASCADE)
    platform        TEXT    NOT NULL,         -- 'fa', 'ib', 'bsky', 'e621', 'ig', …
    submission_id   TEXT    NOT NULL,         -- the site-upload id (== publications.external_id)
    account_id      INTEGER,                  -- carried from the source row so persona rollup is correct
    role            TEXT DEFAULT 'crosspost', -- 'primary' | 'crosspost'
    linked_via      TEXT DEFAULT 'manual',    -- 'phash' | 'title' | 'manual' | 'publication'
    added_at        TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (masterpiece_id, platform, submission_id)
);
CREATE INDEX IF NOT EXISTS idx_mp_members_site ON masterpiece_members(platform, submission_id);

-- RECOMMENDED: a thin index over the on-disk folders. Not the source of truth
-- (masterpiece.json is), but gives (a) a stable integer id for FKs and for
-- collection_members references, (b) fast listing without walking the disk,
-- (c) an idempotency/provenance ledger for the submission_links migration.
CREATE TABLE IF NOT EXISTS masterpieces (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL UNIQUE,     -- folder key (the artwork/masterpiece name)
    source_link_id  INTEGER,                  -- provenance: migrated from this submission_link (nullable)
    created_at      TEXT DEFAULT (datetime('now')),
    updated_at      TEXT DEFAULT (datetime('now'))
);
```

Notes:

- **Members are references, not copies** — resolved live against `{platform}_submissions` at read time
  so pooled stats stay current (same discipline as `rollup_collection`).
- **`account_id` on every member is mandatory-in-spirit.** The persona rollup only works if members
  carry the account that actually owns the site-upload (`collections.md` §3 — the "everything lumps
  under the default account" bug). Populate it from `{platform}_submissions.account_id` when adding a
  discovered member, and from `pub.account_id` when a member is created by posting through PawPoller.
- **`publications` is not duplicated.** A copy posted *through* PawPoller already has a `publications`
  row (its `external_id` == the `submission_id`). Those uploads become `masterpiece_members` with
  `linked_via='publication'` automatically on post (§6). A copy *discovered by polling only* (art you
  uploaded to FA by hand years ago) has **no** `publications` row — the members table is the only place
  it can be attached to the master, which is the whole point.
- **Relationship to `image_hashes`:** unchanged and reused. `image_hashes(platform, submission_id → phash)`
  is the matching index that *suggests* members; `masterpiece_members` is the durable, user-confirmed
  result. Storing `phash` on `masterpiece.json` lets the canonical image itself participate in matching.
- **Relationship to `submission_links`:** a `submission_link` (an art "master") is exactly a Masterpiece
  whose members are all `submission` rows and which has no canonical file yet. §7 migrates them.
- **Relationship to `collection_members`:** a Masterpiece joins a Collection as a **new member type**,
  `member_type='masterpiece'`, `member_ref='<masterpiece name>'` (see §7) — Collections stay cross-type.

### 2.2 Migrations (idempotent + reversible)

Follow the established `database/db.py` pattern (guarded `CREATE TABLE IF NOT EXISTS`, `pp_meta` flags,
provenance columns, never destructive):

1. **Create `masterpiece_members` + `masterpieces`** unconditionally (`IF NOT EXISTS`). Additive.
2. **Adopt existing artwork folders.** For each folder with `artwork.json` and no `masterpieces` row,
   insert a `masterpieces` index row (`name = folder`). No file rewrite needed — the reader treats
   `artwork.json` as `masterpiece.json`. `characters`/`phash` are backfilled lazily on first edit or by
   the hash pass. Idempotent (keyed on `name`).
3. **`submission_links` → Masterpieces** (`migrate_links_to_masterpieces`, §7). Mirrors the existing
   `collections_queries.migrate_links_to_collections`: each link with ≥2 members becomes a Masterpiece;
   the `submission_links` rows are **left intact** (reversible); idempotency tracked via
   `masterpieces.source_link_id`. Guard on the `masterpieces` table existing so legacy-migration tests
   that run before the schema is applied skip it cleanly.
4. **No column churn on `publications`.** The registry is unchanged; membership is derived, not stored
   twice.

---

## 3. The two creation flows

Both mirror how a story is made (promote/import an existing draft vs. start a fresh `MASTER.md`).

### 3.1 Promote existing — "Make Masterpiece" (the common case)

Start from a tile already in the **Gallery** (a discovered `{platform}_submissions` row, or an imported
local image).

1. **Trigger.** "＋ Make Masterpiece" on a Gallery tile / the Gallery detail view (reuses the hover-action
   pattern already on library cards).
2. **Materialise the master.** Create the Masterpiece folder from the tile's stored metadata
   (title/description/keywords/rating) and its image: reuse `posting/artwork_importer` to pull **full-res**
   where the platform supports it (FA/Weasyl/IB), else the thumbnail (DA/Itaku). This is the same import
   path the Submissions hub already uses. Compute + store `phash` (`image_hash.dhash_from_path`).
3. **Seed the primary member.** Add the source `(platform, submission_id, account_id)` as
   `role='primary'`, `linked_via='manual'`.
4. **Suggest the same image elsewhere (REUSE pHash — do NOT invent matching).** Call
   `image_hash.image_suggestions(conn, existing)` (dHash, Hamming ≤ 8, cross-platform only) — optionally
   seeded by the canonical image's own `phash` — plus the title-Jaccard signal, exactly as
   `auto_suggest_collections` merges them. Present the candidates as a **checklist of visual cards**
   (thumbnail + platform badge + similarity %), reusing the `WorkPicker` / tag-browser modal chrome.
   Run `POST /api/collections/hash-scan`'s populator first if the hash store is cold.
5. **Merge into one master.** Ticked candidates become `masterpiece_members` (`linked_via='phash'` or
   `'title'`). Now the Masterpiece knows every site the image lives on.
6. **Result.** A managed Masterpiece with pooled stats (§4) and a detail view (§5). It can now be
   edited-and-synced and added to a Collection.

### 3.2 Fresh — create the master first, publish later

Mirror "New story": make the master before it exists anywhere.

1. **Trigger.** "＋ New Masterpiece" in the **Create** area (the upgraded Artwork uploader,
   `#/artwork/new` → `#/create/masterpiece/new`).
2. **Upload + describe.** Choose the canonical image; fill title / description / rating / characters /
   tags (tags via the **tag browser**, `window.TagPicker`, already wired into the art module). Reuse
   `artwork_reader.create_artwork` to write the folder + `masterpiece.json` (empty `members`).
3. **Publish from Create (§6).** Select target sites; `post_artwork` posts the image; each success
   auto-adds a `masterpiece_member` (`linked_via='publication'`). The master now has members without any
   pHash matching, because PawPoller created every upload.
4. **Later** discovered copies (e.g. someone mirrors it, or a delayed poll finds your own upload) surface
   as pHash suggestions to attach, exactly as in §3.1 step 4.

---

## 4. Rollup / analytics

`rollup_masterpiece(conn, id_or_name)` returns the master + resolved locations + pooled totals + merged
tags + persona(s), **mirroring `collections_queries.rollup_collection`**. Reuse its machinery rather than
re-implement:

- Factor the shared helpers `_TABLE_MAP`, `_METRICS`, `_submission_row`, `_stats_from_row`,
  `_location_from_submission`, `_acct_to_persona`, `_parse_tags` out of `collections_queries.py` into a
  small `database/_rollup.py` (or import them directly). A Masterpiece and a Collection then pool stats
  **identically** — the same discipline that already keeps a Collection and a Cross-Platform master in
  sync.
- For each `masterpiece_member`, resolve `(platform, submission_id)` → `_location_from_submission` → a
  location dict with `stats` (views/faves/comments normalised per platform's available metrics),
  `keywords`, `thumbnail_url`, `account_id`.
- Pool: sum non-`None` metrics; union tags; collect the persona(s) spanned (member `account_id` →
  persona). Respect per-platform metric availability (Bsky has no views; e621 uses `score`; Tumblr only
  notes) — `_METRICS` already encodes this.
- The **combined time-series chart** reuses `analytics_queries.get_combined_snapshots(conn, pairs)` where
  `pairs = [(platform, submission_id), …]` from the members — the same call
  `collection_member_pairs` + `GET /collections/{id}/snapshots` already make.

`list_masterpieces_with_summary` mirrors `list_collections_with_summary`: light rollup + an auto-cover
(the primary member's `thumbnail_url`, or the canonical `thumbnail.png`).

**API surface** (mirror `routes/collections_api.py`), `routes/masterpieces_api.py`,
prefix `/api/masterpieces`:

- `GET /api/masterpieces` — list + light rollup for the grid.
- `POST /api/masterpieces` — fresh-create (title/rating/tags/image) or promote (`{from: {platform, submission_id}}`).
- `GET /api/masterpieces/{id}` — full rollup (metadata + locations + totals + tags + personas).
- `GET /api/masterpieces/{id}/snapshots` — combined time-series.
- `GET /api/masterpieces/{id}/suggestions` — pHash + title same-image candidates not yet members.
- `PATCH /api/masterpieces/{id}` — edit canonical metadata (writes `masterpiece.json`).
- `POST /api/masterpieces/{id}/members` / `DELETE …/members` — attach/detach a site-upload.
- `POST /api/masterpieces/{id}/publish` / `…/sync` — post to new sites / push canonical metadata to
  existing members (§6).

---

## 5. UI & information architecture

### 5.1 Where Masterpieces live

Following the locked IA:

- **Artwork → Gallery** (`#/artwork`, renamed **Gallery**): the raw thumbnail grid of discovered +
  imported tiles. Each tile gets a **"＋ Make Masterpiece"** hover action (§3.1). This is the *promote-from*
  surface; it stops trying to be a manager (the `_foldMasters` / "Unify selected" masters UI is retired
  into Masterpieces — §7).
- **Masterpieces**: the managed grid — a card per Masterpiece (cover, title, N sites, pooled headline
  stat, persona dot), living alongside stories in the **Submissions** hub (Submissions = stories +
  artwork/Masterpieces) rather than as a separate top-level nav item, so "my managed works" is one place.
  A type filter (All / Stories / Masterpieces) selects between them.
- **Create**: the single publishing home. "＋ New Masterpiece" (fresh, §3.2) and the publish/sync actions
  (§6) live here beside the Story Editor. The Artwork uploader moves under Create.
- **Instagram reclassified.** IG moves out of **Posts** and becomes an **art-gallery poster** — added to
  `artwork_reader._ALL_POSTER_IDS` (with e621) so a Masterpiece can target it. IG posting already exists
  (2.64.0, image-mandatory, server-only); this is a classification + surfacing change, not new posting code.

### 5.2 Masterpiece detail view (analogous to the story detail view)

A gallery-forward analog of the rich story detail (`bookshelf.js renderWork` / `posting.js renderStoryDetail`):

- **Header:** the canonical image (large), title, rating, persona dot(s), pooled headline stats.
- **Canonical metadata panel:** title / description / rating / characters / tags — editable, with a
  **tag browser** button (`TagPicker`) and per-platform override tabs (reuse the artwork editor's
  per-platform tag/title/description UI). "Save" writes `masterpiece.json`.
- **Locations table** ("Published to"): one row per member — platform · account/persona · link · per-platform
  stats · thumbnail — the same shape as the Collections Locations table. Row actions: open ↗, detach,
  **sync** (push canonical metadata to this upload).
- **Suggestions strip:** "This image also appears on … ?" — pHash/title candidates (§3.1 step 4) with a
  one-click attach.
- **Publish/Update bar:** target new sites, or "Sync all" to push canonical metadata to every editable
  member (§6). Drift indicators reuse the publish-check `file_hash`/drift logic already in
  `editor_api.publish_check`.
- **Combined chart + timeline:** `…/snapshots`.
- **Add to Collection:** a `WorkPicker`-backed action (the Masterpiece is the item being added).

### 5.3 Reused components (build nothing new for selection)

- **`WorkPicker`** (`frontend/js/work_picker.js`, `window.WorkPicker.open`) — the promote/attach
  candidate lists and the "add to Collection" flow use the existing slide-in modal (thumbnail cards,
  search, filter chips, selected strip, footer). Extend `FILTERS` with a `masterpiece` source so a
  Masterpiece can be picked (e.g. as a Collection member) the same way works/submissions are.
- **Tag browser** (`window.TagPicker` / `.tag-browser-*` chrome from `metadata_editor.js` /
  `tag_picker.js`) — canonical + per-platform tag editing.
- **Perceptual hash** (`database/image_hash.py`) — matching, unchanged.
- **Posting** (`posting/manager.post_artwork` / `update_story`-style sync / `posting/platforms/*`) — publishing.

---

## 6. Publishing a Masterpiece from Create

Publishing reuses the artwork posting path end-to-end — the Masterpiece **is** the artwork folder, so
`posting/manager.post_artwork(name, platforms, account_ids=…)` already does the work:

1. **Post to N sites.** `post_artwork` reads `masterpiece.json` via `artwork_reader.build_artwork_package`
   (canonical title/desc/tags/rating + per-platform overrides cascade from `default`), validates, posts,
   and writes a `publications` row per success — including the existing desktop-queue / retry fallbacks
   (FA/DA need desktop; server auto-queues). **New:** on each success, also upsert a `masterpiece_member`
   (`platform`, `external_id`, `account_id`, `role='crosspost'`, `linked_via='publication'`). So posting
   and mastering are one action.
2. **Sync canonical metadata to existing uploads.** A Masterpiece-scoped analog of
   `manager.update_story` / `update_all_changed`: for every member whose platform `supports_edit`, rebuild
   the package from `masterpiece.json` and call `poster.edit(external_id, package)`. This is the core
   promise — **change the tags/description/rating once, push everywhere**. Reuse drift detection
   (`file_hash`) so "Sync all" only touches uploads that are actually behind.
3. **Metadata-only vs. content.** Reuse the existing `extra={"skip_content_refresh": True}` convention so
   a tag/description change doesn't necessarily re-upload the image where the platform separates the two.
4. **Rating parity.** Canonical `rating` maps to each platform's own scale via the poster (already handled
   for artwork). Editing it on the master and syncing keeps all copies' maturity flags aligned.

No new posting engine — Create is the single entry point over the existing per-platform posters.

---

## 7. Relationship to Collections (explicit boundary + supersession)

**They are different axes and must not duplicate each other** (see the §1.2 table). To make that concrete
in the data model:

- A Masterpiece becomes a Collection member via a **new member type**: `member_type='masterpiece'`,
  `member_ref='<masterpiece name>'`, resolved in `rollup_collection` by pulling the Masterpiece's members
  and folding their locations into the Collection's pooled stats (a Masterpiece contributes its *whole*
  set of site-uploads to the Collection). Collections stay **cross-type**; a Collection of one Masterpiece
  + one story + three posts is the canonical "everything about this release."
- Collections do **not** gain per-image mastering, and Masterpieces do **not** gain cross-type members.
  The old habit of dropping an art piece's FA+IB copies straight into a Collection as loose `submission`
  members is replaced by: make a Masterpiece, then add the Masterpiece to the Collection.

**Supersession — this changes an earlier documented decision.** `collections.md` §8 and
`ia_consolidation.md` §(c)/§(e) proposed folding the art "masters" (`submission_links`) **into
Collections**. That predates the locked entity model. Because a master is *inherently per-image* and a
Collection is *inherently cross-type*, folding masters into Collections would blur the exact boundary the
owner just locked. **Revised decision: `submission_links` migrate into Masterpieces, not Collections.**

- `migrate_links_to_masterpieces` (mirrors the existing `migrate_links_to_collections`): each
  `submission_link` with ≥2 members → one Masterpiece (no canonical file yet; `role='primary'` on the
  first member that resolves a title); `submission_links` rows kept intact (reversible); idempotent via
  `masterpieces.source_link_id`.
- The `image_hash` / title auto-suggest engine now proposes **Masterpieces** for same-image sets and
  **Collections** for same-*piece*-different-*type* sets (title match across a gallery upload and a
  microblog post about it). One engine, two targets, chosen by whether the candidates are the same image.
- Any Collections already created by the *previous* `migrate_links_to_collections` run (if it shipped)
  are left alone; going forward, new same-image folds land as Masterpieces. (Open question §9.)

**Preserve (do not regress):** persona correctness — every merge path (promote, publish, migrate) must
set member `account_id` from the source row / `pub.account_id`, or it re-introduces the "everything lumps
under the default account" bug (`collections.md` §3).

---

## 8. Phased build sequence

Ordering principle (from the linking overhaul + IA specs): **additive backend first, reversible cosmetic
IA next, one-way data migration last.** Each phase ships independently. Versions are indicative — current
master is **2.122.0** — and may shift as the parallel bug / UI-polish / IA phases of the wider overhaul
interleave.

| Phase | Ships | Version (indicative) |
|---|---|---|
| **0 — Rename in place.** `masterpiece.json` = back-compat superset of `artwork.json`; reader/writer accept both; `masterpieces` index table + folder adoption migration; `characters` field + `phash` backfill. No behaviour change. | Backend + migration | **2.123.0** |
| **1 — Model + rollup + read API.** `masterpiece_members` table; `rollup_masterpiece` (shared helpers factored from `collections_queries`); `GET /api/masterpieces`, `/{id}`, `/{id}/snapshots`; unit tests on the rollup (pure function, like `rollup_collection`). | Backend | **2.124.0** |
| **2 — Masterpiece detail view + Masterpieces grid.** Read-only detail (canonical panel, Locations table, combined chart) + the managed grid in Submissions with the type filter. Reuses story-detail chrome. | Frontend | **2.125.0** |
| **3 — Promote flow.** "＋ Make Masterpiece" on Gallery tiles; import full-res; pHash + title **suggestions** via `image_hash.image_suggestions` in a `WorkPicker`-style checklist; attach/detach members. | Frontend + small API | **2.126.0** |
| **4 — Fresh create + publish/sync from Create.** "＋ New Masterpiece"; `post_artwork` auto-adds members; the Masterpiece-scoped **Sync all** (metadata → every editable member) with drift detection; IG + e621 added to `_ALL_POSTER_IDS`. | Frontend + posting glue | **2.127.0** |
| **5 — Collections interop.** `member_type='masterpiece'` in `collection_members` + `rollup_collection`; "Add to Collection" on the Masterpiece detail; `WorkPicker` gains a `masterpiece` source. | Backend + frontend | **2.128.0** |
| **6 — `submission_links` → Masterpieces migration + retire the old masters UI.** Idempotent/reversible fold; re-point the auto-suggest engine to propose Masterpieces (same-image) vs Collections (same-piece); remove `artwork.js` `_foldMasters` / "Unify selected" (the Gallery stops minting `submission_link` masters). Keep `/api/links` dormant until the fold is proven. | Backend + frontend | **2.129.0** |

**Independent, any time:** the Collections rollup gaps flagged in `ia_consolidation.md` §(f)5 (post
members contribute nothing; art thumbnails) — orthogonal but adjacent; fix while the rollup helpers are
being factored out in Phase 1.

---

## 9. Open questions / risks

1. **Canonical-file duplication vs. Gallery.** Promoting downloads a full-res copy into the Masterpiece
   folder while the Gallery tile still references the platform thumbnail. Is the promoted copy the sole
   truth (Gallery tile becomes a pointer to the Masterpiece), or do both persist? Lean: Masterpiece owns
   the file; the Gallery tile shows a "mastered ✓" badge and links to it.
2. **One master, or per-variant masters?** An image with an SFW/NSFW pair or alternate versions — one
   Masterpiece with variants, or one Masterpiece per file? Lean: one file per Masterpiece (matches "ONE
   image"); use a Collection to bundle variants. Confirm.
3. **Multi-image imports.** Bluesky/X/IG carousels already import as *one artwork per image* (2.91.0/2.93.0).
   Each becomes its own Masterpiece — confirm that's desired vs. a carousel-level grouping (which would be
   a Collection).
4. **pHash precision at scale.** `HAMMING_THRESHOLD=8` on a 64-bit dHash is tuned for near-dupes but can
   pair visually similar different pieces (recolours, same character/pose). Promote suggestions are
   user-confirmed (safe), but tune/threshold-expose if false positives annoy. Never auto-attach without
   confirmation.
5. **Migration collision with any shipped `migrate_links_to_collections`.** If the earlier links→Collections
   fold already ran on this DB, do we (a) leave those Collections and only fold *new* links to Masterpieces,
   (b) also convert those Collections-of-submissions into Masterpieces, or (c) leave both and de-dupe via
   `source_link_id`? Lean: (a) — never rewrite user data; §7 idempotency keys prevent double-folding.
6. **"Sync all" blast radius.** Pushing canonical metadata to N sites is N authenticated edits (rate
   limits, FA/DA desktop-only, partial failures). Reuse `update_story`'s per-platform rate-limit + retry +
   desktop-queue; show a per-member result matrix; never silently overwrite a hand-edited upload without a
   drift/confirm step.
7. **SSRF surface unchanged but worth restating.** Full-res import + thumbnail hashing stay behind the
   existing `image_hash` https-only host allowlist + the `/thumb` proxy posture; promoting must not open a
   new fetch path.
8. **Vocabulary.** "Masterpiece" vs "Masterwork" vs "Master." "Masterpiece" reads best for a single
   finished image; confirm before it appears in nav + `masterpiece.json` keys (a rename after ship is a
   data migration).
9. **Does the local "artwork" word survive?** After Phase 0 the managed unit is a Masterpiece and the grid
   is the Gallery — should "Artwork" persist anywhere as a user-facing word, or only as the archive path
   and legacy JSON filename?
```
