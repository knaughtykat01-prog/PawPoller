# Self-comment detection + unified art detail page — spec

Captured 2026-07-30 from two Rhys asks in one session. Two independent deliverables;
ship as two versions (2.192.0 then 2.193.0). Investigated against source before writing —
every claim below carries a file:line.

---

## Ask 1 (verbatim)

> "Comments at the moment are also looping in our own comments as new. it should detect
> any comments made by the posting account is not tracked as a new comment for the post,
> rather a reply or not nothing all together."

**Decision (Rhys, 2026-07-30):** *store it, flag it, exclude it.* Keep the row, mark it
`is_own`, drop it out of every "new comment" surface, retro-flag what's already in the DB.
Rejected: dropping the row at ingestion (loses thread context, unrecoverable on a bad match).

## Ask 2 (verbatim)

> "when you are in masterpieces and click on a piece, vs clicking on a piece when in
> artwork, it comes up with two different kinds of pages. they should be unified but when
> its say a variant piece, it should come up with that variant piece looped in with the rest."

**Decision (Rhys, 2026-07-30):** *both routes integrated* — `#/masterpieces/{name}` and
`#/artwork/image/{name}` both stay live and render the same unified page. No redirect.

---

# Part A — self-comment detection (2.192.0)

## A.1 What's actually broken

Three comment tables, three different states of wrongness:

| Table | Platforms | Defined | Self-filter today |
|---|---|---|---|
| `comments` | ib | `database/schema.sql:108-126` | **none** |
| `fa_comments` | fa | `database/fa_schema.sql:98-115` | **none** |
| `platform_comments` | bsky, mast, e621, da | `database/inbox_queries.py:28-41` (Python DDL) | partial, broken |

Every other platform (ws/sf/sqw/ao3/wp/ik/tw/tum/pix/thr/ig) stores only an integer
`comments_count` — no per-comment rows, so nothing to filter. Out of scope.

### The partial filter, and its three defects

`polling/inbox_capture.py:75-76`:

```python
if own and r.get("author", "").lower().lstrip("@").split("@")[0] == own.split("@")[0]:
    inbox_queries.set_handled(conn, platform, r["comment_id"], True)
```

1. **`.split("@")[0]` compares local-part only.** A Mastodon commenter
   `@rhys@some.other.instance` matches our own `@rhys@our.instance`. Silently marks a
   stranger's comment as ours.
2. **Auto-handles, doesn't exclude.** The row still counts in `captured`
   (`inbox_capture.py:74`) and still appears as a comment everywhere downstream.
3. **New-rows-only** — inside `if is_new:` (`inbox_capture.py:73`). A self-comment already
   sitting unhandled is never retro-fixed.
4. **Silently no-ops when `own_author` is empty** (`if own and …`).

The only other self-filter in the codebase is for watchers, not comments
(`clients/ib/client.py:509-515`).

### Every surface a self-comment currently pollutes

| # | Surface | Location | Effect |
|---|---|---|---|
| 1 | IB new-comment counter + toast + Telegram | `polling/poller.py:394-397`, toast `:110-117`, TG `:164-170` | "you commented on your own post" notification |
| 2 | FA new-comment counter + toast + Telegram | `polling/fa_poller.py:422-430`, toast `:172-174`, TG `:210-215` | same |
| 3 | **Top Fans leaderboard** | `database/analytics_queries.py:66-67` (ib), `:81-82` (fa), score `:100` | **your own account ranks as your own top fan** |
| 4 | Inbox "N to answer" | `routes/inbox_api.py:37-38` over `database/inbox_queries.py:116-195` | IB/FA self-comments count as needing a reply |
| 5 | Recent-comments activity feeds | `database/queries.py:339`; `database/fa_queries.py:238` | own text in the dashboard activity list |
| 6 | Activity ledger "+N comments" | `routes/api.py:471-490` `_format_poll_summary` | fed by `new_comments_found`, so fixed by #1/#2 |
| 7 | Telegram poll summary / persona digest | `polling/telegram.py:242,247-248`; `:372,378` | same — fed by `new_comments_found` |

**Explicitly out of scope — platform-reported numbers we cannot correct locally.**
Verified during implementation, and it is a bigger set than first assumed:

- `milestone_comments` (`polling/telegram.py:444-471`) reads the platform's own
  `comments_count`/`replies` snapshot column (column map `polling/telegram.py:31-46`).
- `total_comments` in `get_summary` / `get_fa_summary` is
  `COALESCE(SUM(comments_count),0)` over the *submissions* table
  (`database/queries.py:445`, `database/fa_queries.py` equivalent) — **not** a COUNT over
  the comment rows, so an `is_own` flag cannot reach it either. Initially mis-scoped in this
  spec as fixable; it is not.

Both numbers are computed server-side by FA/IB/Bluesky and already include your replies.
Do **not** fake either by subtracting a local count: the local and remote tallies drift
(deleted comments, capture caps, throttled polls) and the subtraction eventually goes
negative. Known limitation, documented in `documentation_guide.md`.

## A.2 Knowing our own handle

`config.PLATFORM_CREDENTIAL_FIELDS` (`config.py:643-664`) per comment-capable platform:

| Platform | Own-identity key | State |
|---|---|---|
| ib | `username` (`config.py:644`) | known, **unused** in the comment path |
| fa | `fa_username` (`config.py:645`) | known, **unused** in the comment path |
| e621 | `e621_username` (`config.py:663`) | known, passed as `own_author` (`polling/e621_poller.py:219`) |
| da | `da_target_user` (`config.py:651`) | known, passed (`polling/da_poller.py:261`) |
| bsky | `bsky_identifier` (`config.py:655`) | **unreliable — may be an email**; real handle is runtime `client._handle` (`clients/bsky/client.py:144`) |
| mast | — | **no stored handle at all**; runtime `client._username` only (`clients/mast/client.py:145`) |

Runtime-only identity is fine for ingestion (login always precedes a poll) but useless for
the two things we now need it for: **read-side filtering** (`get_top_fans`, `get_inbox` run
with no client instance) and the **one-time backfill**.

**Therefore: persist the resolved handle.** New plaintext setting per platform
`<code>_own_handle`, written after a successful session validation, multi-account aware via
`config.account_setting_key` (`config.py:771-776`) so extra accounts land at
`acct_<id>_<code>_own_handle`. Not a secret → must **not** go in `CREDENTIAL_FIELDS`
(`config.py:565-615`); it stays plaintext.

## A.3 Design

### New module `polling/self_comment.py`

```
normalise_handle(s)            -> str    # strip, casefold, drop ONE leading "@"
own_handles(conn, platform, account_id=None) -> set[str]
is_own_author(author, handles) -> bool   # full-string compare, never local-part
```

`own_handles` unions: the persisted `<code>_own_handle`, the platform's canonical identity
key from the table in A.2, and (for mast) the bare local part of `mast_handle` so a
home-instance `acct` of `rhys` matches a stored `rhys@our.instance`. **The host is never
discarded from the *incoming* author** — that is the defect being fixed.

### Schema — `is_own INTEGER NOT NULL DEFAULT 0` on all three tables

⚠️ **Migration-order gotcha (cost a real incident before):** schema load runs *before*
`_run_migrations`, so a `*_schema.sql` file must never index or constrain a
migration-added column. Put each `ALTER TABLE` **and its index** together inside
`_run_migrations` in `database/db.py`.

- `comments` — guarded ALTER + `idx_comments_own(account_id, is_own)`
- `fa_comments` — guarded ALTER + matching index
- `platform_comments` — add to the `CREATE TABLE` in `inbox_queries.py:28-41` for fresh
  installs **and** a guarded ALTER for existing ones (the CREATE is
  `IF NOT EXISTS`, so upgraders never see the new column otherwise)

### Ingestion changes

- `polling/poller.py:394-397` (IB) — resolve own handles once per cycle; stamp `is_own` on
  upsert; when own, **skip** the `new_comments_found` increment and the
  `new_comment_details.append`. No toast, no Telegram.
- `polling/fa_poller.py:422-430` (FA) — same shape.
- `polling/inbox_capture.py` — replace the broken comparison with `is_own_author`; stamp
  `is_own`; keep the existing auto-handle (a self-comment is never "to answer"); stop
  counting own rows in `captured`.
- `database/queries.py:307` `upsert_comment` and `database/fa_queries.py:211`
  `upsert_fa_comments_batch` / `:184` `upsert_fa_comment` and
  `database/inbox_queries.py:55` `upsert_platform_comment` all take `is_own`.

### Read-side exclusion

- `analytics_queries.get_top_fans` — `AND is_own = 0` on both the `comments` and
  `fa_comments` legs (`:66-67`, `:81-82`).
- `queries.get_recent_comments` / `get_summary` totals; `fa_queries.get_fa_recent_comments`
  / `get_fa_summary` totals — exclude own.
- `inbox_queries.get_inbox` — **keep** own rows in the feed (Rhys wants thread context) but
  surface `is_own` and force them `handled`, so `routes/inbox_api.py:37-38` can never count
  them as "to answer". Frontend labels them.

### Backfill

`backfill_own_comments(conn)` — idempotent, flags existing rows whose author matches a
known own-handle. Mirrors the established `backfill_credential_stamps()` pattern from
2.170 (runs opportunistically, not in `_run_migrations`, because handles may not be known
at migration time). Exposed as an endpoint so it can be re-run after connecting an account.

### Tests — `tests/test_self_comments.py`

Currently **zero** tests cover `inbox_capture.py` at all. New coverage:
normalisation (case, `@`, whitespace) · **the cross-instance false positive**
(`rhys@other.social` must NOT match `rhys@ours.social`) · IB and FA flagging ·
own comment fires no notification and does not increment `new_comments_found` ·
`get_top_fans` excludes own · inbox unhandled count excludes own ·
backfill retro-flags and is idempotent · empty-own-handle degrades safely.

---

# Part B — unified art detail page (2.193.0)

## B.1 They are already the same record

There is **no** artwork-vs-masterpiece distinction in the data:

- `posting/artwork_reader.py:48-49` — `_META_FILE = "masterpiece.json"`,
  `_LEGACY_META_FILE = "artwork.json"`; the docstring at `:43-47` states `masterpiece.json`
  is a back-compatible **superset**, and `_meta_path` (`:52`) accepts either.
- Both detail endpoints load through the same function: `routes/artwork_api.py:78` and
  `routes/masterpieces_api.py:749` both call `artwork_reader.load_artwork(name)`.
- `masterpieces_api.py:47-50` — `list_masterpieces` adopts **every** artwork folder into the
  index via `mq.ensure_indexed_bulk`. There is no discriminator; the `masterpieces` table is
  a thin name-keyed index, not a source of truth (`database/db.py:694-709`).

So this is two frontend renderers over one record. The unification is a frontend job plus
one payload alignment.

## B.2 What each page has

| Capability | Artwork `#/artwork/image/…` | Masterpiece `#/masterpieces/…` |
|---|---|---|
| Renderer | `frontend/js/artwork.js:831` `renderDetail` | `frontend/js/masterpieces.js:527` → `:595` `_paintDetail` |
| Metadata edit (title/desc/rating) | ✅ `:900-915` | ✅ `:754-767` |
| **Alt text** | ✅ `:908-910` | ❌ |
| Characters | ❌ | ✅ `:762-763` |
| Tags + tag browser | ✅ `:916-920` | ✅ `:765-767` |
| Stats chart | ❌ | ✅ `_loadChart` `:1255` |
| Members list + detach | ❌ (shows *publications*) | ✅ `:681-715`, `:696` |
| pHash link / scan | ❌ | ✅ `:1151`, `:1188` |
| Variants panel (rename/split) | ❌ (read-only strip `:850-858`) | ✅ `:631-654` |
| Per-variant stats | ❌ | ✅ `:610-616`, `:626` |
| Add-variant upload | ❌ | ✅ `:726-729` |
| Prev/next + arrow keys | ❌ | ✅ `:551-577`, `:580` |
| Sync to sites | ❌ | ✅ `:770` |
| Add to Collection | ❌ | ✅ `:737-739` |
| Junk / restore | ❌ | ✅ `:660-663` |
| Replace canonical image | ❌ | ✅ `:722-725` |
| Fold into another piece | ❌ | ✅ `:792-816` |
| Persona chips | ❌ | ✅ `:71`, `:656` |
| **Publish now** | ✅ `:935` → `_publishMore` `:1126` | ❌ |
| **Schedule + pending list** | ✅ `:936-949`, `:1021`, `:1060` | ❌ |
| **Delete** | ✅ `:894` → `_delete` `:1146` | ❌ (junk only) |

**Masterpiece is the superset.** Four capabilities live only on the Artwork page:
publish now, schedule, delete, alt text. Those port *in*; the Masterpiece renderer becomes
the single renderer.

## B.3 Two bugs to fix while in here

1. `frontend/js/artwork.js:959` queries `#art-detail-platforms .art-plat-row`, but
   `_renderPlatformRows` emits `class="artwork-plat-row"` (`:586`). The "already-posted
   platforms are dimmed and disabled" logic has therefore **never fired**.
2. The per-platform **Override tags** inputs are rendered (`:593-598`) but never read by
   `_publishMore` (`:1126-1144`) or `_confirmSchedule` (`:1021`) — only the upload page's
   `_collectMetadata` (`:754`) reads `.art-plat-tags`. Silently discarded user input. Wire
   them into both publish paths.

## B.4 Design

**One renderer, both routes.** `masterpieces.js` `renderDetail`/`_paintDetail` becomes
canonical; `Artwork.renderDetail` delegates to it. `app.js:1175` and `app.js:1210` both
dispatch into the same function. Neither URL redirects — per Rhys's "can both be
integrated". Consequence: `submissions_api.py:172`'s server-authored `detail_route` and the
assertion at `tests/test_works.py:133` need **no change**.

**Port in:** publish-now, schedule + pending-schedule list + cancel, delete (behind a
confirm, alongside junk), alt-text field on the canonical record, plus the two bug fixes
above. Reuse the live shared helpers `_renderPlatformRows` (`:582`),
`_populateAccountSelectors` (`:603`), `_parseTags` (`:721`).

**Variant deep-link.** Selector rides the hash as a query suffix — `?v=<key>` — not a path
segment, because artwork names may contain `/` (`app.js:1175` does `parts.slice(2).join('/')`)
and a path segment would be ambiguous:

```
#/masterpieces/{name}?v=nsfw
#/artwork/image/{name}?v=nsfw
```

On load with `?v=`, the page selects that variant — hero swaps to its image, its
per-variant stats show — **with the full sibling strip still rendered and that one marked
active**. That is Rhys's "looped in with the rest": you get the variant you clicked, in
context, not an isolated page.

**Repoint the variant tiles.** `frontend/js/bookshelf.js:432` `_variantBooks` currently
links to a bare `#/artwork/image/{name}` with the key dropped entirely, so clicking a
variant tile lands you on the hero — the exact complaint. Append `?v={key}`. Backend:
`routes/submissions_api.py:145-156` builds `variant_tiles` (primary `""` excluded at
`:145`) — give each tile its own `detail_route` carrying the selector.

**Payload alignment.** `GET /api/artwork/images/{name}` (`artwork_api.py:98-116`) returns
raw `variants` with no `totals`/`member_count`, and `images` unordered; the masterpiece
route enriches per-variant rollups (`masterpieces_api.py:768-772`) and hero-orders `images`
(`:758-760`). Since one renderer now consumes both, align the artwork payload to the
masterpiece shape.

## B.5 Do not unify against dead code

`frontend/js/artwork.js:56-506` (≈450 lines) is the **retired hub** — `#/artwork` redirects
to `#/library/type/artwork` (`app.js:1163-1168`), so `Artwork.render()` has no reachable
caller, and every helper in that range is bound only by the click delegate installed inside
`render()` itself (`:153-174`). Confirmed dead: `render` `:56`, `_ignoreDiscovered` `:180`,
`_hubFilterBar` `:201`, `_applyHubFilters` `:218`, `_key` `:250`, `_unkey` `:251`,
`_foldMasters` `:261`, `_masterCover` `:280`, `_masterTitle` `:288`, `_masterCard` `:293`,
`_toggleMaster` `:337`, `_splitMaster` `:342`, `_isArt` `:356`, `_thumbSrc` `:366`,
`_discoveredCard` `:375`, `_importDiscovered` `:409`, `_makeMasterpiece` `:432`, `_card`
`:466`, `_deleteFromHub` `:492`. Corroborated by `docs/BACKLOG.md:44-45` (L1/L2).

**Unify against `renderDetail` (`:831`) and the live shared helpers only.** Do not delete
the dead block in this change — backlog **L1** keeps `_foldMasters`/`_masterCard`/
`_splitMaster` as the deliberate port source for a possible masters-folding revival, and
L2 (the deletion) is explicitly gated behind that decision.

## B.6 Entry points — no repointing required

Because both routes stay live, every existing link keeps working:
`bookshelf.js:368`,`:432` · `showcase.js:86`,`:93` · `submissions.js:217`,`:496`,`:501` ·
`posting.js:821`,`:957` · `commissions.js:156` · `imagetool.js:480` ·
`artwork.js:809`,`:822`,`:1631` · `masterpieces.js:513`,`:569`,`:585`,`:949`,`:968`,`:1075` ·
`submissions_api.py:172`. Only `bookshelf.js:432` changes, to carry the variant selector.

## B.7 Tests

Existing coverage to keep green: `tests/test_artwork_variants_expose.py`,
`test_masterpiece_variants.py`, `test_masterpiece_variant_split.py`,
`test_masterpiece_images.py`, `test_masterpiece_rollup.py`, `test_masterpiece_sync.py`,
`test_works.py:128-133`. New: artwork detail payload matches the masterpiece variant shape
(`totals`, `member_count`, hero-first `images`); `variant_tiles` carry a `?v=` detail route.
There is no JS test harness in the repo, so the renderer merge is verified by rendered
preview instead.

---

## Sequence — all shipped 2026-07-30

1. ✅ A: schema + `self_comment.py` + persist handles
2. ✅ A: ingestion (ib, fa, inbox_capture) + read-side exclusion + backfill
3. ✅ A: tests (13) → **2.192.0**
4. ✅ B: payload alignment + unified renderer + variant deep-link + the two bug fixes
5. ✅ B: tests (9) → **2.193.0**
6. ✅ Docs: `CHANGELOG.md` ×2, `docs/HANDOFF.md` header,
   `docs/documentation_guide.md` §24 + §25, `docs/BACKLOG.md` rows SC + UD,
   `APP_VERSION` → 2.193.0
7. **No deploy, no tag, not committed** — Rhys: "No cutting a new release yet."

## Corrections found during implementation

Recorded because the spec was wrong about them before the code existed:

- **`total_comments` is not fixable** — it is `COALESCE(SUM(comments_count),0)` over
  the *submissions* table (`database/queries.py:445`), i.e. platform-reported, not a COUNT
  over comment rows. Moved from the fixable list into the known-limitations bucket with
  `milestone_comments`.
- **`config.account_setting_key` is `(account_id, field, is_default)`** — not
  `(field, account_id)`. Determining is_default needs the accounts table, so
  `self_comment` takes `conn` and reads both the bare and namespaced keys on the way in
  (tolerant, costs nothing).
- **There is no `tag_overrides` parameter on `POST /api/artwork/publish`.** Passing one
  would have silently dropped the input exactly like the bug being fixed, one layer up.
  `_applyOverrides` writes the overrides into the per-platform tag map instead — the
  documented mechanism the posters already cascade from.
- **`PATCH /api/masterpieces/{name}` did not accept `alt_text`** — added, otherwise the
  unified page could show the field but never save it.
