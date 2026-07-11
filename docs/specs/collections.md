# Collections — Design Plan

**Status:** draft / not yet built · **Author:** Rhys + Claude · **Date:** 2026-07-12

## 1. The vision

A **Collection** is one master container for a single *piece* — everywhere it lives, everything about it, in one place.

Example: a piece of art posted to **FurAffinity + Inkbunny + Itaku** (gallery sites) **and** announced on **X + Bluesky** (microblog). Today those are five separate rows in five separate places. A Collection unifies them into one entity that holds:

- every **location** it's posted to (per-platform links),
- **pooled analytics** across all of them (total views / faves / comments / reposts …),
- all the **tags** (merged across platforms),
- an optional **accompanying story** (link a written work to the art),
- one **cover** + title + notes.

Think "the master folder for this piece." Working name: **Collections** (alternatives: Masters, Pieces — see §8).

## 2. What already exists (and the gap)

PawPoller already has ~70% of the machinery — it just isn't joined up across types:

| Existing thing | What it does | Gap for Collections |
| --- | --- | --- |
| **Works** (`/api/works`, Submissions hub) | One local story **or** artwork + its **publications** across platforms, with pooled platform list + persona. `assemble_works()` groups publications by `(content_type, name)`. | Single-type (art *or* story). Doesn't include the X/Bluesky posts *about* the art. No cross-work linking (art ↔ story). |
| **Masters / Unify** (`submission_link`, `/api/links`) | Merges same-piece **discovered** tiles across platforms into one master + **pools their stats** (`_foldMasters`, `link_stats`). | Artwork-only, discovered-only (pre-import), auto-suggested by title similarity. Not user-curated, not cross-type. |
| **Posts** (`/api/posts`, `#/posts`) | Microblog posts to X/Bsky/Mast/Thr/Tum/IG. | Not linked to the artwork/work they're announcing. |
| **Publications** (`publications` table) | Per (work, platform, account) publication row with `external_id`/`external_url`/stats. | Carries the wrong `account_id` on imports — see §3. |
| **Personas** (`personas`, account grouping) | Bundle accounts → one identity; scoped views. | Rely on correct publication `account_id` (see §3). |

**The genuinely-new pieces Collections add:**
1. **Cross-type membership** — a tweet/skeet *and* an FA/IB/Itaku art post *and* a story can all belong to one Collection.
2. **User curation** — "add this to Collection X" (not just auto-suggested duplicates).
3. **A Collection detail view** — pooled stats + every location + merged tags + the linked story.

## 3. Prerequisite bug fix — publication account attribution (BLOCKER)

Found while diagnosing "persona filtering lumps Hustlestick into KnaughtyKat" (2026-07-12).

- **FA analytics** are attributed correctly per account: `fa_submissions` → account 2 (KnaughtyKat) 12, account 10 (Hustlestick) 11, account 15 (KiiTheTiger) 21.
- **FA publications are ALL account 2** (45/45). So the works library thinks every FA piece is KnaughtyKat's → the Submissions-hub persona filter mis-buckets Hustlestick + KiiTheTiger under KnaughtyKat.

**Root cause:** `posting/artwork_importer.import_artwork()` (and the story importer / link paths) call `upsert_publication(...)` **without `account_id`**, so it defaults to the platform's default account. The discovered submission's real `account_id` (which polling stored correctly on `*_submissions`) is dropped.

**Fix:**
1. On import/link, look up the source submission's `account_id` from `{platform}_submissions` and pass it to `upsert_publication(account_id=…)`.
2. **Backfill:** one-off migration to re-point existing publications' `account_id` from the matching `{platform}_submissions.account_id` (join on `platform` + `external_id` = `submission_id`).

This must land **before** Collections, because a Collection's persona/analytics rollup is only correct if its publications carry the right account. It also independently fixes the persona filter the user reported.

## 4. Data model

Recommendation: a **new lightweight, polymorphic grouping** rather than overloading `submission_link` (which is `(platform, submission_id)`-only and can't reference local works or stories cleanly).

```
collections
  id            INTEGER PK
  name          TEXT              -- display title
  cover_kind    TEXT              -- 'artwork' | 'story' | 'url'
  cover_ref     TEXT              -- artwork/story name, or an image URL
  notes         TEXT DEFAULT ''
  created_at    TEXT
  updated_at    TEXT

collection_members
  collection_id INTEGER  FK -> collections.id  (ON DELETE CASCADE)
  member_type   TEXT     -- 'work' | 'submission' | 'post'
  member_ref    TEXT     -- work: "artwork:Name" / "story:Name"
                         -- submission: "fa:12345"  (platform:submission_id)
                         -- post: post_id
  role          TEXT     -- 'primary' | 'art' | 'story' | 'announcement'
  added_at      TEXT
  PRIMARY KEY (collection_id, member_type, member_ref)
```

Notes:
- **Members are polymorphic references, not copies** — resolve to live data at read time so analytics stay current.
- A Collection with one artwork + its gallery works + the X/Bsky tweets about it + a companion story = 1 collection row + N member rows.
- `submission_link` masters can be *migrated into* Collections later (a master = a Collection whose members are all `submission` rows), or kept as an auto-suggest feeder that proposes Collections. Don't rip out unify; let it seed Collections.

## 5. Analytics + tag rollup

`GET /api/collections/{id}` resolves every member and pools:
- **work** members → their publications' per-platform stats (views/faves/comments), tags, external_urls.
- **submission** members → the `{platform}_submissions` row's stats + link + keywords.
- **post** members → the post's per-platform stats.

Rollup = union of locations (one row per platform+account), summed metrics (respecting each platform's available metrics — e.g. Bsky has no views), merged/deduped tag set, and the **persona(s)** spanned (via each member's `account_id` → persona — hence §3). Reuse the existing `link_stats` pooling shape where possible.

## 6. UI

- **New hub tab** `#/collections` (4th, beside Stories / Artwork / Posts) — a grid of Collection cards (cover, title, N platforms, pooled headline stat, persona dot).
- **Collection detail** `#/collections/:id` — cover + title + notes, pooled stat cards, a **Locations** table (platform · account/persona · link · per-platform stats), merged **tags**, the linked **story** (if any), and the member list with add/remove.
- **Curation entry points:**
  - "Add to Collection" on a work card, a discovered tile, a submission detail, and a post — a small picker (existing collection or "new").
  - Reuse the **unify suggestion** engine to *propose* collections ("These 3 look like the same piece — make a Collection?").
- Extends, doesn't replace: the Artwork "unify → master" flow becomes "create/extend a Collection."

## 7. Build phases

1. **Phase 0 — attribution fix (§3).** Importer passes `account_id`; backfill migration. Ships on its own (also fixes the persona filter). *Small.*
2. **Phase 1 — model + read.** `collections` + `collection_members` tables (+ migration); `GET/POST/DELETE /api/collections`, `GET /api/collections/{id}` with rollup; unit tests on the rollup (pure function, like `assemble_works`). *Backend.*
3. **Phase 2 — hub + detail UI.** `#/collections` grid + detail view (read-only rollup). *Frontend.*
4. **Phase 3 — curation.** "Add to Collection" pickers across work/tile/submission/post; create-new; remove. *Frontend + small API.*
5. **Phase 4 — companion story + suggestions.** Link a story to an art Collection; wire the unify suggestion engine to propose Collections. *Polish.*

Each phase is independently shippable; Phase 0 is a prerequisite and worth doing immediately regardless of the rest.

## 8. Open decisions

- **Name:** Collections vs Masters vs Pieces. ("Collections" reads clearest for a mixed art+story+posts bundle.)
- **Relationship to existing masters (`submission_link`):** migrate them into Collections, keep both, or make unify a Collection-suggester? (Lean: keep unify as the *suggester*, Collections as the durable container.)
- **Auto vs manual:** how aggressive should auto-suggested Collections be (title similarity across gallery + microblog)?
- **One story per Collection, or many?** (Lean: one primary companion story, but the model allows N.)
- **Cross-persona Collections:** can a single piece posted under two personas live in one Collection, or should persona stay a hard boundary? (Lean: allow, and show both persona dots.)
