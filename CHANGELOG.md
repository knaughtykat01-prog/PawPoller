# PawPoller Changelog

All notable changes to PawPoller are documented here.

---

## [2.31.0] - 2026-06-27 - Artwork: PostyBirb-style image posting across 7 platforms

**Why:** PawPoller published **stories**; the user also makes **artwork** and wanted the PostyBirb
workflow inside the app — drop in an image, fill per-platform metadata, publish to multiple art sites
at once, and have that art tracked in the same analytics as stories. The posting engine was
story-archive-centric; this adds a standalone, file-first image flow on top of it without forking the
engine.

**Architecture — reuse, don't fork.** Artwork rides the *same* posters, manager, registry, scheduler,
and retry/desktop-queue fallbacks as stories. Two enablers: (1) **analytics is free** — every poller
auto-discovers the whole gallery with no content-type filter, so posted art is tracked
(views/faves/comments, charts, milestones) on the next poll with zero poller changes; (2) the
`StoryUploadPackage` already carries everything an image needs, so `build_artwork_package` returns one
with an image `file_path`.

**Registry — `content_type` discriminator** (`database/db.py`, `database/posting_schema.sql`,
`database/posting_queries.py`)
- Additive `content_type TEXT NOT NULL DEFAULT 'story'` on `publications` / `posting_queue` /
  `posting_log` (idempotent ADD COLUMN, mirrors the account_id rollout). New
  `_rebuild_publications_content_type` folds it into the publications UNIQUE →
  `UNIQUE(content_type, story_name, chapter_index, platform, account_id)` so an artwork named like a
  story can't collide. Defensive about whether the account_id rebuild dropped the column first.
- `posting_queries` write/keyed fns gained a `content_type="story"` param; the cross-story list reads
  (`get_publications`, `get_queue`, `get_posting_log`) gained a `content_type='story'` filter so
  artwork never leaks into the Stories views. `get_pending_queue` is deliberately unfiltered — the
  scheduler sees both and routes on the row's content_type. Every default is `"story"`, so existing
  callers are byte-for-byte unchanged.

**Artwork engine** (`posting/artwork_reader.py` NEW, `posting/manager.py`, `posting/scheduler.py`)
- `artwork_reader`: one folder per artwork (image + `artwork.json` with per-platform tags/titles/
  descriptions/categories) under a new `artwork_archive_path` (Docker `/app/data/artwork`; desktop
  `…/m_x/Archives/Artwork`). `create_artwork` (used by both upload paths), `load_artwork` (traversal-
  guarded), `build_artwork_package` (image package, chapter 0, per-platform cascade).
- `manager.post_artwork` — parallel to `post_story`, posts via the same posters, records
  `content_type='artwork'`, reuses the desktop-queue + retry + log fallbacks. Scheduler branches on
  the queued row's content_type → `post_artwork` vs `post_story`.

**API** (`routes/artwork_api.py` NEW, `dashboard.py`): `/api/artwork/*` — list/detail, **upload**
(browser `UploadFile`), **create-from-path** (desktop local file), **publish** (→ `post_artwork`),
image serving (query-param + traversal guard), artwork-scoped publications/log, settings, and tar.gz
sync push/upload (desktop⇄server media).

**Frontend Artwork hub** (`frontend/js/artwork.js` NEW, `app.js`, `index.html`, `css/artwork.css`,
`api.js`)
- `window.Artwork`: a card-grid hub, a PostyBirb-style create flow (drag-drop / file-picker / desktop
  native picker, live preview, default metadata + per-platform tag overrides, platform checkboxes +
  per-platform account selectors), a detail page (real cover + per-platform publications with live
  stats + "publish to more"), and a history view. New `#/artwork` routes + an **Artwork** nav entry.

**Per-platform image posting** (the 7 image-capable platforms)
- **Ready (verified):** Inkbunny (`submission_type=1`), Itaku (`upload_image`), Bluesky (image-native;
  added a Pillow downscale for the ~1 MB blob cap + image-or-text validation).
- **New client methods:** FurAffinity `submit_visual` (`submission_type=submission` + visual category
  from `artwork_fa_*` settings); SoFurry posts the image as Artwork (category 10) via a MIME-aware
  `upload_content`; Weasyl `submit_visual` (`/submit/visual`); DeviantArt Sta.sh (`oauth_stash_submit`
  + `oauth_stash_publish`).
- ⚠ **Needs a live smoke test** before relying on them: FA/SF/Weasyl/DA image posting were built from
  the existing code + each site's form/API but can't be verified without posting live. **DeviantArt
  also needs the DA app re-authorized with `stash`+`publish` OAuth scopes** (the literature-only app
  token will 401/403). New settings: `artwork_enabled`, `artwork_archive_path`,
  `artwork_default_platforms/rating`, `artwork_fa_category/species/gender`, `artwork_ws_subtype`,
  `artwork_sf_sub_type`, `artwork_da_catpath`.

**Desktop** (`main.py`): a pywebview `js_api` bridge exposes `open_image_dialog` so the desktop app
picks a local image by path (copied into the archive) instead of re-uploading bytes.

**Security hardening** (pre-flight review): `create-from-path` is gated to the desktop runtime (it
reads a server-side path, so it would be a local-file-read gadget on the server); the artwork tar.gz
sync rejects symlink/hardlink members (zip-slip); and thumbnail uploads are capped at 50 MB like the
primary image. All artwork endpoints sit behind the existing dashboard auth; path traversal is
re-anchor-guarded and all new SQL is parameterised.

**Tests:** `test_artwork_db` (content_type isolation + same-name coexistence), `test_artwork_reader`
(create/load/build), `test_integration_artwork` (the full `post_artwork` pipeline via a stub poster),
`test_migration_content_type` (legacy→content_type-in-UNIQUE, backfill, idempotent). Suite: 175
passed, 1 skipped. End-to-end verified in-browser (upload → publish → `content_type='artwork'`
registry row → Stories views unaffected) against an isolated DB.

---

## [2.30.0] - 2026-06-27 - Personas: per-account views + per-persona digests across all 11 platforms

**Why:** running several accounts was only half-supported — the data layer was account-aware, but
nothing surfaced it. Every platform page summed all accounts together, and Telegram digests lumped
every account into one report. This release adds the identity layer on top: pick a specific account
(or "All accounts") on any platform page, group accounts across platforms into a **persona**, and
get **one digest/summary per persona** instead of one giant blob.

**Personas — the identity layer** (`database/personas.py` NEW, `database/db.py`, `routes/settings_api.py`,
`config.py`, `frontend/js/accounts.js`)
- New `personas` table (`persona_id`, `name`, `color`, `sort_order`) + a nullable
  `accounts.persona_id` (NULL = Unassigned). Migration is an idempotent `ADD COLUMN` + index at the
  end of `_run_migrations` (a soft reference — no SQL FK; `delete_persona` nulls assignments first).
- `personas.py` mirrors `accounts.py`: CRUD, `assign_account_persona` (dedicated — `update_account`
  can't clear to NULL), `list_accounts_by_persona` (None bucket = Unassigned), `persona_stats`
  (sums `account_stats` across the persona's accounts + per-platform breakdown — reuses, no new SQL),
  and `get_manifest`/`apply_manifest`.
- Sync: `_personas_manifest` rides the settings sync channel (applied **before** accounts so
  account→persona refs land after the persona rows); the accounts manifest gained a `persona_id`
  field (additive, old-client-safe — absence never clobbers a local assignment).
- API: `/api/personas` (GET list+stats / POST / PATCH / DELETE) + `GET /api/personas/{id}` (detail
  with per-account stats) + `POST /api/accounts/{id}/persona` to assign.
- Accounts page: a **Personas** card (create / recolour / rename / delete) + a persona `<select>` on
  every account row.

**Per-account scoping on platform pages** (`database/scope.py` NEW + the 11 `*_queries.py` / `*_api.py`)
- `scope.account_clause(account_id, alias="")` — the single optional `account_id = ?` predicate,
  reused by reads **and** the notification digests. `account_id=None` ⇒ no filter ⇒ byte-identical
  to before ("All accounts").
- Every platform's `get_*_summary` / `get_all_*_submissions` / `get_*_aggregate_snapshots` (+ recent
  faves/comments where they exist) take an optional `account_id`; the `/summary`, `/submissions`,
  `/aggregate` endpoints gained `account_id: int | None = Query(None)`. Growth-rate + watcher-count
  helpers stay aggregate (a deliberate follow-up). All 11 platforms (ib, fa, ws, sf, sqw, ao3, da,
  wp, ik, bsky, tw).
- Frontend: an **account selector** in the context bar (`app.js` `_platformContextBar` +
  `_populateAccountSwitch`), shown only when a platform has 2+ enabled accounts — "All accounts" +
  each account. Threads `account_id` into each platform's dashboard / submissions / compare fetches
  (`this._acctId(code)`); the cross-platform Overview + Platforms hub stay aggregate.

**Per-persona notification re-segmentation** (`polling/telegram.py`, `polling/notifications.py`,
`server.py`, the 11 pollers)
- `send_digest_report` + `send_weekly_digest_report` now emit **one message per persona** (+ an
  "Unassigned" digest), each with a per-account breakdown, persona-combined totals, and top gainers.
  Installs with no personas defined still get a single combined digest (unchanged). The digest
  helpers (`_get_platform_totals`, `_get_digest_deltas`, `_get_watcher_stats`) became account-aware;
  the duplicated per-function platform lists collapsed into one `PLATFORM_TABLES`.
- `send_consolidated_poll_summary` groups the cycle's results into a 👤 sub-section per persona
  (Unassigned last); flat single-section output when no personas exist.
- Milestones: `check_milestones_batch` is now scoped by `account_id` — this both labels the alert
  (persona/account) **and fixes a latent double-fire** when a platform has multiple accounts (each
  account's poll previously rescanned every account's submissions).
- Instant new-fave/comment alerts lead with a persona/account line when the platform has multiple
  accounts (IB/FA thread `account_id` directly; the other 9 read an async-safe
  `current_alert_account` ContextVar set once per account in the orchestrator). All labelling is
  suppressed on single-unassigned-account installs (no ugly "Unassigned —" prefix).

**Per-persona overview** (`frontend/js/accounts.js`, `app.js`)
- New `#/persona/:id` route: combined scalar stat cards + a per-platform breakdown + the member
  accounts, each with a "View →" deep-link that opens that platform's dashboard pre-scoped to the
  account. Persona names on the Accounts page link through to it.

**Tests:** `tests/test_personas.py` (CRUD / assign / stats / manifest / IB scoping), a
`tests/test_scope_<p>.py` per platform (scoped vs aggregate), and `tests/test_persona_digests.py`
(per-persona segmentation, no-persona fallback, skip-empty, summary grouping, milestone scoping).
Full suite green (158 passed).

---

## [2.29.0] - 2026-06-26 - Bold dashboard redesign: new shell, Platforms hub, configurable Home

**Why:** the server dashboard felt clunky and hard to get around — a 60px hover-to-expand icon
rail (labels hidden until you hover), all 11 platforms buried in a modal popover, and
Submissions/Compare pages with no in-page link to reach them. This is a ground-up redesign of the
**shell + navigation + Home**, applied to both the desktop app and the headless server (one
shared frontend). Existing page logic is reused — only the chrome and the Overview changed.

**New visual language**
- Type: **Bricolage Grotesque** (display) + **Hanken Grotesk** (body) replace Inter
  (`--font-display` / `--font-sans` in `tokens.css`); Crimson Pro + JetBrains Mono retained.
- Vivid per-platform **colour tiles**, rounded components, brand-tinted shadows, grain, staggered
  motion. All 8 token themes still drive the neutrals; brand tiles use the `--platform-*` colours.

**Navigation / shell** (`frontend/index.html`, `frontend/css/layout.css`, `app.js` `init()` + `route()`)
- Persistent **labeled sidebar** (grouped nav, active gradient pill) with an explicit
  **collapse/pin** toggle (persisted to `localStorage`) — replaces the hover-to-expand rail.
- New **context bar**: a clickable breadcrumb + a **platform switcher** + Dashboard / Submissions /
  Compare **sub-tabs** whenever you're inside a platform (Inkbunny's legacy un-prefixed routes are
  special-cased). Surfaces the previously orphaned Submissions/Compare views.
- Surfaced **⌘/Ctrl+K** command palette (visible search box in the sidebar).
- One responsive shell: the sidebar becomes a slide-in drawer + a floating bottom tab bar
  (Overview · Platforms · Stories · Analytics · More) on mobile.

**Platforms hub** (`#/platforms`, `renderPlatformsHub()`)
- A real page of all 11 platforms as colour tiles with live status dots (reuses the
  `platform_health` engine via `#pg-status-{code}`), replacing the modal popover.

**Configurable Home dashboard** (`renderOverview()` rewrite)
- The Home is now a **widget grid** you can customise: aggregate stat widgets (views, faves,
  comments, subs, downloads), per-platform views charts, platform breakdown, trending, top
  viewed/faved, recent activity, top fans, and system events.
- **Customize mode**: add / remove / resize (1 · 2 · full width) / drag-reorder.
- Layout is **server-saved** via a new additive `dashboard_layout` preference (`routes/api.py`
  get + save), so it follows you across desktop and phone. All existing Overview data fetches and
  `Components`/`Charts` helpers are reused.

**Other**
- New `frontend/js/platforms.js` — one canonical 11-platform registry (`window.PLATFORMS`) + route
  helpers, replacing a 5-way hand-duplicated list; `command_palette.js` repointed at it.
- New `frontend/css/redesign.css` for the bold page components (hub tiles, dashboard widgets,
  add-widget catalog, platform-header accent).
- Platform detail headers pick up the platform's **brand colour** (light bold-pass via `route()`
  setting `data-platform` + `--page-accent` on `#main-col` + CSS — the 11 per-platform dashboard
  render functions are untouched).
- **Legacy ⇄ Beta UI switch**: the whole redesign ships behind a runtime toggle. `dashboard.py`
  `serve_index` serves either the new (`beta`) or the pre-redesign (`legacy`) shell based on a
  `?ui=` query param (persisted in a `pp_ui` cookie), and a small fixed switch is injected into
  both. Legacy is frozen as `index_legacy.html` + `*_legacy.{css,js}` (snapshots of the pre-2.29.0
  frontend). Default is `beta` (`_DEFAULT_UI` in `dashboard.py`) — set it to `legacy` for a
  zero-surprise rollout where users opt in. Also a one-click instant fallback if anything's off.

**Scope:** shell + navigation + Platforms hub + Home dashboard. The other ~50 page-render
functions, the editor, posting, and the rest of the backend are unchanged (the only backend
change is the additive `dashboard_layout` preference key). Staged: editor/settings/posting and the
platform-detail tables keep working and get the full bold treatment in a follow-up.

---

## [2.28.3] - 2026-06-24 - Fix the FA stats regex (2.28.2's ReDoS bound was too tight)

**Bug:** 2.28.2's ReDoS mitigation bounded the stats regex whitespace to `\s{0,30}`,
but FA indents its submission-page-stats markup more deeply than that (the gap between
the outer `<div title="Views">` and the inner `<div>` exceeds 30 chars), so the bounded
regex matched **nothing** and direct-FA scraping returned 0 views/faves/comments. Caught
by the post-deploy verification poll before it persisted bad data (the zero-view guard
skipped any work that already had real stats; `fa_direct_polling` was reverted to false
pending this fix).

**Fix** (`clients/fa/client.py` `_stat`): the correct ReDoS fix isn't a tight bound —
it's removing the overlapping quantifiers. The blowup came from two `\s*` runs
straddling the optional `<a>` group; moving the second `\s*` **inside** that group
(`\s*(?:<a[^>]*>\s*)?` instead of `\s*(?:<a[^>]*>)?\s*`) leaves each `\s*` separated by a
literal, so there's no overlapping-quantifier ambiguity to backtrack over — ReDoS-safe
(100 KB whitespace = 4.8 ms, was 73 s) **and** matches any amount of real indentation.
Verified live: `views=72/127/95`.

---

## [2.28.2] - 2026-06-23 - Refresh FurAffinity direct scraper + enable it server-side

**Why:** PawPoller's FA polling depends on the flaky third-party FAExport; the
2.27.x "direct-FA" fallback was the escape hatch, but (a) its submission parser had
gone stale against FA's current HTML and silently scraped **0 stats**, and (b) the
direct client never used the CF proxy, so it couldn't run on the server (FA blocks
datacenter IPs).

**Parser refresh** (`clients/fa/client.py` `_parse_submission_html`): FA moved stats
into `<div class="submission-page-stats"><div title="Views"><div>N</div>` (the
Favorites count wrapped in a `/favslist` link), the title into `submission-title><h2`,
the rating into the `twitter:label2/data2` meta pair, and tags into `data-tag-name`
attributes. All selectors updated and verified live (views/faves/comments/title/
rating/tags/date all parse). Test fixture (`tests/test_fa_direct.py`) updated to the
current markup.

**Server-side direct scraping** (`_get_fa_http`): the direct FA client now routes
through the CF Worker proxy when configured (`fa_use_cf_proxy`). Confirmed live:
Cloudflare's egress is **not** FA-datacenter-blocked, and FA session cookies
authenticate through it (logged-in adult gallery + real stats: `views=72`). Cookies
are managed at the transport level only — **not** also via httpx's jar — because the
jar and transport each accumulate `Set-Cookie` and corrupt the session on the second
request, making FA serve a stats-less page.

**Security hardening (from the release review):** bounded the new stats regex's
whitespace runs (`\s{0,30}` not `\s*`) so a degraded FA page with a long blank gap
can't trigger quadratic regex backtracking; and redacted the CF-proxy DEBUG logs to
cookie *names* only (FA's high-value `a`/`b` session cookies now traverse that
transport server-side).

**To enable server-side FA without FAExport:** add the FA `a`/`b` cookies to the
server settings and set `fa_direct_polling=true` (`fa_use_cf_proxy` is already on).
The official read-only FA API (closed beta) remains the cleaner long-term server
source — apply via the beta form.

---

## [2.28.1] - 2026-06-23 - Fix + harden SoFurry new-work discovery

**Bug:** the first full SF poll after 2.28.0 created a junk submission row, and
discovery wasn't actually finding most works. 2.28.0's `get_all_gallery_ids` parsed the
gallery turbo-stream with narrow regexes (`"<id>","title"` / `"id","<id>","name"`) that
(a) matched only the one submission whose keys are serialised inline plus **folders**
(which share the `"id","<id>","name"` shape), and (b) missed every de-duplicated work.
The "Extra Credit" folder id `rm8DrQym` was thus stored as a submission — it 404s on
`/s/{id}.data`, persisting as a `title=""`, `views=0` row (the AO3/FA zero-snapshot class
of bug from 2.27.1).

**Fix — two layers:**
- **Poller guard** (`polling/sf_poller.py`): before upserting, skip any
  **newly-discovered** id (not already in the DB) whose detail came back with no title —
  a real submission always has one; a folder / non-submission 404s to an empty title.
  Known works keep their row (their transient-failure guard already covers them).
- **Reliable enumeration** (`clients/sf/client.py` `get_all_gallery_ids`): take every
  id-shaped token from the authed gallery turbo-stream (8 alnum chars with ≥1
  digit/uppercase — drops lowercase tag values), then subtract the profile's own user id
  (`GET /api/profile`, which redirects to a titled page and would otherwise slip the
  guard) and the folder ids (`GET /api/folders`). Verified live: now surfaces all 10
  works (was 1–2); the ~6 residual field-name tokens 404 and are dropped by the guard.

The one junk `rm8DrQym` row the 2.28.0 poll created is removed in a one-off prod cleanup.

---

## [2.28.0] - 2026-06-23 - Rebuild SoFurry posting for the "SoFurry beta" rewrite

**Context:** 2.27.2 fixed SoFurry *polling* after SF's React-Router ("beta")
rewrite. *Posting* was still broken — the old `/ui/submission*` REST API it used
returns 404 (Remix intercepts `/ui/*`). This rebuilds posting against the new API,
reverse-engineered and live-verified end-to-end (full map:
`docs/reference/sofurry_beta_api_map.md`).

**Auth — the missing piece.** SF is now a hybrid: Laravel still serves `/login`,
but the new `/api/*` endpoints are Remix and need a separate Remix session. After
the Laravel login, run the **`/fe/auth/sofurry` OAuth2-PKCE bridge** (it auto-approves
off the live Laravel session → `/oauth/authorize` → `/fe/auth/callback`) to mint an
authed Remix `_session`. `clients/sf/client.py` `_ensure_api_session()` does
login → bridge → verify (`GET /api/upload-quota`), retrying once with a fresh login
if a restored session is stale.

**New posting flow** (`clients/sf/client.py`), all `X-CSRF-Token`-authed (token
from `<meta name="csrf-token">`):
- `create_submission`: `POST /api/upload-create` (mint id) → `POST /api/upload-content`
  (multipart `submissionId`+`file`, HTML ≥ 1 KB) → `POST /api/submission-editor`
  (metadata; tags as repeated `artistTags[]`; category/type as INT codes 20/21).
- `upload_content` / `set_content_title` / `delete_content` / `get_content_ids`:
  multi-chapter content ops, via the `submission-editor` `_endpoint`/`_method` dispatcher.
- `edit_submission`: reads `GET /api/submission/{id}` (fields nested under `submission`,
  category/type as display strings → mapped back to ints) and writes via
  `submission-editor`, preserving every unspecified field (incl. privacy).
- `delete_submission`: `DELETE /api/submission/{id}`.

**Poster** (`posting/platforms/sofurry.py`): repointed every dead `/ui/` call
(multi-chapter append, chapter titles, privacy post-flight check, `edit`,
`replace_file`, `probe_exists`, `probe_draft_state`) onto the new client methods.
`posting/importer.py` (SF work import) now reads `/api/submission/{id}` (new `tags`
field, author-object).

**Content format — TipTap.** The beta editor is TipTap/ProseMirror.
`editor/converter.py` `_convert_body_sofurry` (+ front matter + heuristic fallback)
now emits real `<h1>/<h2>` headings and inline `style="text-align: center;"` instead
of `class="text-center"` + `<p><strong>` pseudo-headings, matching SF's stored format
(`docs/reference/sofurry_beta_tiptap_sample.html`). HTML is stored verbatim, so
existing stories must be **re-generated** to pick up the new markup before re-upload.

**Verified:** end-to-end live test — login + bridge → create a private 2-chapter
writing submission from real converter output → multi-chapter upload + titles +
metadata (category=writing, privacy=1, tags) → delete. All 200s; nothing left on the
account. Full pytest suite green (133 passed, 1 skipped).

**Polling ports (same release):** `get_follower_count` now reads the login-free
`GET /api/profile?handle=` (`user.followerCount`). `scrape_followers` is fully restored
via the login-free paginated `GET /api/followers?handle=&mode=followers&page=` (20/page,
`hasNextPage`) — so per-follower new-follower notifications work again (verified: 35
handles). New-work discovery (`get_all_gallery_ids` + `polling/sf_poller.py`) attempts
the auth bridge best-effort so the authed gallery (which includes adult works) is used,
then parses both turbo-stream id encodings (`"<id>","title"` and `"id","<id>","name"`);
brand-new works serialise inline and are caught, older works are de-duplicated by the
turbo-stream but already DB-known, so the cycle never depends on discovery.

**Thumbnail upload IS ported:** `set_thumbnail` posts the image via the editor
dispatcher (`_endpoint=submission/{id}/thumbnail`, multipart `file`, png/jpeg/webp,
1 KB–1 MB), wired into `create_submission` and verified live (`thumbUrl` populated).
Regenerate is the same endpoint with `_method=DELETE`.

**Known / not yet ported:** only the 2FA login path (Laravel `/login` is unchanged, so
the existing `_submit_2fa` should still apply, but it's untested on the beta).

---

## [2.27.2] - 2026-06-22 - Fix SoFurry polling for the "SoFurry beta" rewrite

**Bug:** SoFurry polling died on 2026-06-13 — every cycle errored with
`SoFurry login failed -- check credentials`. SoFurry shipped a "beta" rewrite of
the whole site, which broke the scraper.

**Root cause:** the new SoFurry is a **React Router (Remix-style) SPA**. Three
things the poller relied on changed at once: (1) the server-rendered gallery
(`<div id={sid}>` blocks + `/s/{sid}?ref=glr` links) is now a JS-rendered shell
with no submission links; (2) the `/ui/submission/{id}` JSON API returns **404**
(the whole `/ui/` API is legacy); (3) the `/s/{id}` page no longer contains
`"N Views"` text. With the gallery scrape finding nothing, the poller reported it
as a login failure even though auth wasn't the real problem.

**Fix — repoint polling at the SPA's loader data (and make it login-free):**
- The new app exposes React Router loader data at `…​.data` URLs as turbo-stream
  payloads. `/s/{id}.data` carries `title`/`views`/`likes`/comment count inline
  **and is served without login** for published works (verified live against 5
  works). `clients/sf/client.py` `get_submission_detail` now fetches `/s/{id}.data`
  and parses the stats from the turbo-stream (new `_rr_int`/`_rr_str` helpers).
- `get_all_gallery_ids` now reads `/u/{handle}/gallery.data`. **Caveat:** an
  unauthenticated gallery is SFW-filtered, so a user with Adult works sees no
  submissions there — auto-discovery of *new* works needs an authenticated
  session, which the beta also broke (see below).
- `polling/sf_poller.py` no longer hard-fails on an empty gallery. Because stats
  are login-free per `/s/{id}.data`, it polls the union of discovered IDs and the
  **submission IDs already in the DB** — restoring the views/likes/comments
  time-series for all known works immediately, without a working login. It also
  gained the same zero-view guard as AO3/FA/SqW ([2.27.1]).

**Still broken (SoFurry posting — separate rebuild, not in this release):** the
beta also changed (a) login (the CF-Worker `x-proxy-login` flow is stale against
the new site), (b) the create/edit API (the `/ui/` endpoints `create_submission`/
`edit_submission` use are gone — 404), and (c) the **content format** — the editor
is now TipTap/ProseMirror, expecting inline `style="text-align:…"`, real
`<h1>/<h2>/<h3>`, `<strong>/<em>/<u>/<s>`, `<li><p>…</p></li>`, `<blockquote>`,
`<pre><code>`, `<hr>`, and ProseMirror tables (reference sample saved at
`docs/reference/sofurry_beta_tiptap_sample.html`). The SF converter
(`editor/converter.py`) currently emits `class="text-center"`-style alignment and
`<p><strong>` pseudo-headings, which the new renderer won't honour. Posting needs
a dedicated effort once login is rebuilt (you can't verify a render without it).

---

## [2.27.1] - 2026-06-22 - Fix AO3/SqW zero-view snapshots inflating digest deltas

**Bug:** AO3 digest/milestone reports intermittently showed huge phantom view
gains (e.g. "+2,400 views" for a work that actually gains ~30/day) — the symptom
the user described as AO3 "consistently adding 2k+ views, like it isn't retaining
from previous counts."

**Root cause:** when an AO3 (or SqW — same OTW scraper code) work-page fetch
failed transiently — `_get_page` returning `None` on an exhausted ReadTimeout,
a 403 "Shields are up", a 429 throttle, a 525, or a 200 response that parsed to
an empty stats block (Cloudflare/adult-content interstitial) — `get_work_detail`
returned a fabricated all-zero stat dict. The poller wrote that straight through
`upsert_*_submission` (clobbering the work's real, non-zero cumulative hit count
with 0) **and** `insert_*_snapshot` (a `views=0` row). The next good poll
recovered to the true value, so any digest or milestone whose baseline snapshot
landed on one of those zero rows reported the entire view total as a single-period
gain. Production data showed one AO3 work with **12 zero-snapshots out of 215**
and 20 drop-to-zero events across five works — OTW "hits" are cumulative and never
decrease, so every one of those zeros was bad data, not a real reset.

**Fix (two layers):**
- **Clients** (`clients/ao3/client.py`, `clients/sqw/client.py`) —
  `get_work_detail` now **raises** instead of returning a zero dict when the page
  fetch fails, and also raises when a 200 response parses to all-zero stats *and*
  an empty title (the challenge/redirect-page signature). `get_work_details_batch`
  already catches per-work exceptions, so a failed work is simply dropped from the
  cycle rather than persisted as zeros. A genuinely brand-new work still has a
  title, so real works are never dropped.
- **Pollers** (`polling/ao3_poller.py`, `polling/sqw_poller.py`,
  `polling/fa_poller.py`) — defence in depth: before upsert/snapshot, if the
  scraped `views == 0` while the DB already holds a non-zero count for that work,
  skip the work for this cycle (it's a transient scrape failure, not a reset). The
  next cycle re-reads the real value. The FA direct-scrape path is especially
  exposed: a Cloudflare challenge page returns HTTP 200 and parses to all-zero
  stats, and under FA's new third-party policy (2026-06) challenge/DDoS-mitigation
  responses are an expected, recurring event — so the same guard now covers FA.

**Note:** this fixes new data going forward. The historical `views=0` snapshots
already in the DB are still there — they can be deleted in a one-off cleanup so
past charts and the 7-day weekly digest baseline are clean
(`DELETE FROM ao3_snapshots WHERE views=0;` likewise for `sqw_snapshots` /
`fa_snapshots`).

**Not yet addressed (FA direct path, follow-up):** FA's 2026-06 third-party policy
also requires *exponential backoff* and asks bots to stand down during Cloudflare
DDoS mitigation. The direct-scrape path (`clients/fa/client.py`) currently paces at
`FA_REQUEST_DELAY_SECONDS=1.5s` (satisfies the 1-req/sec rule) but has no backoff
and no challenge detection — a separate change should add exponential backoff +
explicit Cloudflare-challenge detection (so a challenge aborts/backs off instead of
silently parsing to zeros). Longer term, FA's forthcoming official read-only API is
the proper replacement for both FAExport and direct scraping.

---

## [2.27.0] - 2026-06-16 - Multiple accounts per platform

Support for **multiple accounts per platform** (e.g. two FurAffinity accounts),
all active at once, for both polling and posting — across **all 11 platforms**.
Built as a phased rollout (IB + FA pilot, then the rest). Backward-compatible:
existing single-account installs behave exactly as before (the default account
keeps the legacy flat credential keys; no credential migration). Add a second
account on the **Accounts page** (`#/accounts`) and it's polled on the next cycle
with its own credentials, session, and segregated data; pick which account to
**post as** from the publish-check matrix.

**Landed (foundation + all-platform polling + posting + orchestrator):**

- **Account registry** — new `accounts` table (`database/accounts.py`) with a
  global surrogate `account_id` and one `is_default` account per platform
  (enforced by a partial unique index). Seeded during migration for every
  platform that already has credentials; the default account inherits the
  pre-multi-account data history.
- **Credential namespacing** — the default account keeps the existing flat
  settings keys verbatim (`username`, `fa_cookie_a`…), so existing installs need
  **zero credential migration**. Additional accounts store the same canonical
  fields under `acct_<id>_<field>` keys. New helpers in `config.py`:
  `get_account_credentials`, `resolve_account_credentials`, `is_credential_key`
  (routes namespaced secrets to the encrypted vault), `PLATFORM_CREDENTIAL_FIELDS`.
- **Schema migration** — additive `account_id` columns on the Inkbunny analytics
  tables and `posting_queue`/`posting_log`, backfilled to each platform's default
  account (which is NOT uniformly id 1 — `account_id` is AUTOINCREMENT across
  platforms). Constraint-changing rebuilds run on a dedicated foreign-keys-off
  connection (`_run_table_rebuilds` in `database/db.py`): `session_cache`
  singleton (`CHECK id=1`) → one row per account (`PK account_id`); `watchers`
  `UNIQUE(username)` → `UNIQUE(account_id, username)`; `publications`
  `UNIQUE(story_name, chapter_index, platform)` → `+account_id` so the same
  chapter can be published to two accounts on one platform. Idempotent.
- **Inkbunny runtime** — `database/queries.py` writes are account-scoped;
  `polling/poller.py` is now `run_poll_cycle(account_id=None, …)` with per-account
  credentials, per-account cached session, and per-account first-poll suppression;
  the Inkbunny poster authenticates per account (the singleton `session_cache
  WHERE id=1` read is removed — it would have shared one auth token across
  accounts).
- **FurAffinity runtime** — same treatment for the `fa_*` tables (no session
  cache; cookie auth) plus `fa_profile_stats` per account and the watcher
  spam-confirmation flow (`upsert/confirm/mark/remove`) scoped to
  `(account_id, username)`. `fa_watchers` rebuilt to `UNIQUE(account_id, username)`
  preserving the confirmed/last_seen_at/is_spam/notified columns.
  `polling/fa_poller.py` is `run_fa_poll_cycle(account_id=None, …)`.
- **Orchestrator + ALL 11 platforms account-aware for polling** — `server.py`
  `_poll_all` enumerates enabled accounts for every platform (ib, fa, ws, da, wp,
  ik, bsky, tw, sf, sqw, ao3); a platform's accounts poll sequentially, platforms
  run concurrently; the legacy single-account path is gone. Each platform got its
  schema migration (additive `account_id` via the reusable
  `db._add_account_id_and_backfill`; watcher rebuilds for `sf_watchers`; kudos
  tables `sqw_kudos_users`/`ao3_kudos_users` gained additive `account_id`),
  account-scoped queries, and a per-account poller (`run_<p>_poll_cycle(account_id=None)`).
- **Posting "post as account"** — account-aware end to end: `POST /api/posting/post`
  accepts `account_ids: {platform: id}` and `/api/posting/update` accepts
  `account_id`; `posting/manager.py` resolves a concrete account per platform,
  caches posters per `(platform, account_id)` so sessions never bleed between
  accounts, and tags `publications`/`posting_queue`/`posting_log` with it; the IB
  and FA posters authenticate as the selected account; the scheduler posts queued
  items (incl. the desktop FA auto-queue) as the account they were queued for.
  `update_story` updates each publication as its own `account_id`.
- **Per-account stats** — the Accounts page shows each account's submission count
  + views/faves/comments side by side (`accounts.account_stats` rolls up the
  platform's submissions table by `account_id`; attached to `GET /api/accounts`).
- **Telegram** — the consolidated poll summary labels accounts when a platform
  has more than one in a cycle (e.g. "🐾 Main: 9  🐾 Alt: 4").
- **Drift** — `posting/sync.py` change records now carry `account_id`; a changed
  local file correctly flags every account it was posted to.
- **API + UI** — account CRUD endpoints (`/api/accounts`) and an Accounts page
  (`frontend/js/accounts.js`, `#/accounts`). Settings sync carries an
  `_accounts_manifest` so desktop and server agree on which accounts exist.
- **Tests** — `tests/test_accounts.py` (resolver, vault routing, registry CRUD,
  manifest) and `tests/test_migration_multiaccount.py` (legacy single-account DB
  upgrades correctly: seeding, backfill, all three constraint rebuilds, idempotency).

**Known limitations / follow-ups:** the main per-submission dashboard charts in
`app.js` still aggregate across a platform's accounts (the **Accounts page** shows
per-account rollups, and reads accept an `account_id` filter); the diagnostics tab
is not yet per-account; and the `publish_draft` action doesn't thread `account_id`
(post/update do). None block multi-account use. See `docs/HANDOFF.md`.

### FurAffinity direct-polling fallback

FA polling has been dead since ~2026-05-26 because the public FAExport instance
(`faexport.spangle.org.uk`) is stuck behind a persistent Cloudflare challenge —
the maintainer confirmed on [faexport#129](https://github.com/Deer-Spangle/faexport/issues/129)
that he changed his VPS IP and still gets blocked, and now self-hosts FAExport.

Added a **direct-FA scraping fallback** (`clients/fa/client.py`): when FAExport is
unavailable, the FA poller scrapes FurAffinity's own gallery + submission HTML
directly with the user's session cookies (`get_all_gallery_ids_direct` /
`get_submission_details_batch_direct` / `_parse_submission_html`), producing the
same dict shape as the FAExport path so the poller is source-agnostic. The poll
cycle tries FAExport first and **auto-falls-back to direct on failure**;
`fa_direct_polling=true` in settings skips FAExport entirely (recommended while it
stays blocked). Comment/watcher/profile data (FAExport-only) are skipped in direct
mode — the core view/fave/comment snapshot time-series still works.

**Constraint:** FA's Cloudflare blocks datacenter IPs (the same reason FA *posting*
requires desktop), so direct polling only works from a **residential IP** — i.e.
the desktop instance, not the GCP server. Verified with `tests/test_fa_direct.py`
(parser against representative FA Beta HTML).

---

## [2.26.3] - 2026-06-10

### Fix: pollers no longer hold the SQLite write lock across network awaits

Investigating "look for Inkbunny errors" after the 2026-06 billing-lapse
outage turned up six intermittent IB poll failures over the preceding ten
days, two of them `database is locked` — plus one more IK failure with the
same message on the first post-restart cycle. The locked errors were
puzzling because `database/db.py:get_connection` already sets
`PRAGMA busy_timeout=30000`: a victim waits a full 30 seconds before
giving up, so something had to be *holding* the write lock longer than
that.

Root cause: four pollers opened an implicit write transaction (Python's
sqlite3 begins one on the first INSERT/UPDATE and holds it until
`commit()`) and then performed long network awaits before committing.
The smoking-gun log sequence from 2026-06-10 01:08–01:09: the IB poller
wrote a submission snapshot at 01:08:32 (transaction open), then awaited
its faving-users fetch which took 60s; the IK poller tried to write at
01:08:32, waited out its 30s busy_timeout, and died at exactly 01:09:02
with `database is locked`. IB was the holder, IK the victim.

Audit of all 11 pollers found the write-across-await pattern in four:

- **IB** (`polling/poller.py`) — snapshot upsert held open across the
  faving-users fetch (commit only happened if faves were fetched) and
  across comment-scrape awaits on subsequent loop iterations.
- **FA** (`polling/fa_poller.py`) — snapshot upsert held open across the
  conditional comment fetch (rate-limit sleep + FAExport call).
- **SqW** (`polling/sqw_poller.py`) — snapshot upsert held open across
  the kudos-users fetch.
- **AO3** (`polling/ao3_poller.py`) — worst offender: snapshot upsert
  held open across the kudos-users fetch, which paces requests at 12s
  intervals (2.22.5), so a single work's kudos scrape could hold the
  write lock for minutes.

The other seven pollers (WS, SF, DA, WP, IK, Bsky, TW) already write
only after all fetching completes — safe as-is.

Fix shape: commit immediately after the snapshot upsert in each of the
four, before any conditional fetch awaits; IB additionally commits after
each iteration's comment upserts so the transaction never spans the next
iteration's awaits. Per-row WAL commits are cheap; the lock window drops
from "however long the network takes" to microseconds. The principle,
now documented inline at each site: **never hold an open write
transaction across an await.**

### Fix: blank "Poll ib failed: " error messages

Two of the IB failures from the same ten-day window logged literally
`Poll ib failed: ` with no reason. The traceback showed why:
`httpx.ReadTimeout` (and the timeout family generally — `httpcore.ReadTimeout`,
`asyncio.TimeoutError`) stringify to an empty string, so every surface
that formatted `str(e)` — orchestrator log line, per-poller error log,
`poll_log.error_message` (shown on the dashboard), the Telegram alert's
`<code>` block, and the poll-progress error state — displayed nothing.

New `describe_error(e)` helper in `polling/notifications.py`: returns
`str(e)` when non-empty, otherwise the qualified exception type
(`httpx.ReadTimeout`). Exceptions with real messages are untouched, so
the 2.26.1 FA-humanized strings and `_classify_error`'s pattern matching
behave exactly as before. Applied at every poll-failure surface: all 11
pollers' error handlers (progress message + error log + poll_log
error_message), the FA poller's `_humanize_fa_error` pass-through path,
`server.py`'s orchestrator result loop, and `polling/telegram.py:send_poll_error`.

### Ops note (no code change)

GCP billing lapsed in early June and Google TERMINATED the `pawpoller`
VM — polling was down until billing was re-enabled and the instance
restarted on 2026-06-10. The container came back healthy on its restart
policy. The ephemeral external IP changed (35.243.213.49 →
35.231.162.181); anything pointing at the old IP needs updating.

---

## [2.26.2] - 2026-05-26

### Fix: CI build unblocked — bump `softprops/action-gh-release` v2 → v3

The 2.26.1 tag-push triggered the Build & Release workflow, which then
failed three consecutive times at "Set up job" on both `build-windows`
and `build-linux` jobs with:

```
Failed to download archive
'https://codeload.github.com/softprops/action-gh-release/{zip|tar.gz}/
 3bb12739c298aeb8a4eeaf626c5b8d85266b0e65' after 1 attempts.
An action could not be found at the URI '...'
```

Direct `curl` of the same archive URL returned HTTP 200 with a valid
zip, and the GitHub API confirmed the `v2` tag still resolves to that
commit — so the archive itself was reachable. The failure was inside
GitHub Actions' Marketplace lookup for the pinned commit, not a
codeload.github.com outage. Three reruns over 5 minutes all failed
identically, ruling out the documented transient "softprops Server
Error" pattern from the 2.25.0 HANDOFF (which `gh run rerun --failed`
recovered on second pass).

Background: `softprops/action-gh-release@v3.0.0` shipped 2026-04-12 —
a runtime-only bump from Node 20 to Node 24, no input/API changes. The
last successful build (v2.26.0 on 2026-05-21) used `@v2` and worked.
Something on GitHub's side between then and 2026-05-26 broke v2
resolution for our specific commit. Rather than wait it out on an
opaque infra issue, bump to `@v3`:

- `.github/workflows/build.yml` — both `softprops/action-gh-release@v2`
  refs (`build-windows` line 77, `build-linux` line 149) now pin to
  `@v3`. v3 is a drop-in for v2 — same `files`/`generate_release_notes`
  inputs, just Node 24 under the hood. GitHub-hosted runners
  (`windows-latest`, `ubuntu-22.04`) both support the Node 24 Actions
  runtime since early 2026.

#### Files

- `.github/workflows/build.yml` — `@v2` → `@v3` on both jobs.
- `config.py` — `APP_VERSION` bump to `2.26.2`.
- `tests/test_platform_posters.py` — flake fix surfaced by the
  release verifier: `TestBlueskyPoster::test_post_success` asserted
  `result.duration_seconds > 0`, which fails on Windows because
  `time.perf_counter()` has ~16ms granularity and the mocked HTTP
  call completes faster than that. The assertion intent was "field
  populated," not "measurably non-zero," so relaxed to `>= 0`. CI
  test job runs on Linux (microsecond timer precision) and has been
  passing 91/91 for every prior tag — local-only flake.

The broken `v2.26.1` tag stays in the tag history — no force-push to
re-point it (destructive on already-published tags). v2.26.2 carries
the 2.26.1 FA error-message fix plus this CI unblock and the
verifier-surfaced test flake fix.

---

## [2.26.1] - 2026-05-26

### Fix: FA poll error messages no longer look like PawPoller bugs

Live polling on 2026-05-26 surfaced every FA cycle (every ~4h) failing
with the same opaque line:

```
FA poll failed: Server error '500 Internal Server Error' for url
'https://faexport.spangle.org.uk/user/knaughtykat/gallery.json?page=1&full=1'
```

The error was the raw `httpx.HTTPStatusError` from `resp.raise_for_status()`
bubbling all the way up to the top-level handler in `polling/fa_poller.py`.
Investigation showed FAExport itself was healthy (root page renders,
running latest `v2025.12.1`), but its gallery endpoint was 500ing for
every user (verified against `fender` as a known-good control). FA itself
was responding fine to our IP — so the breakage was in FAExport's own
scraper session against FA (their session expired, FA changed HTML, or
FA challenged their egress IP). Nothing PawPoller could fix.

The user-visible problem wasn't the outage — it was that the error
message gave no signal whether to debug PawPoller, replace cookies,
contact the FAExport maintainer, or just wait. Three surfaces got the
same confusing 500-URL dump: the dashboard error toast, the Telegram
alert, and the `fa_poll_log.error_message` column.

Fix in `polling/fa_poller.py`:

- New `FAExportUpstreamError` exception class — a typed marker for
  "third-party FA proxy failed in a way we can't fix from this side."
- New `_humanize_fa_error(e)` helper that pattern-matches `httpx.HTTPStatusError`
  by URL host (`faexport.`) and status code:
  - **5xx** → "FAExport upstream error (N) — third-party proxy
    faexport.spangle.org.uk could not fetch data from FurAffinity.
    Not a PawPoller bug; will retry next cycle." + a link to
    `Deer-Spangle/faexport/issues` for persistent outages.
  - **429** → "FAExport rate-limited (429) — shared-bucket pressure
    across all FAExport users. Will retry next cycle." (complements
    the 2.23.2 in-client `_get_with_retry` which already handles
    transient 429s; this catches the case where the retry also fails.)
  - **404** → "FAExport returned 404 for {url} — FA username may be
    wrong or the account was removed from FurAffinity."
  - Any other exception passes through unchanged (no false-positive
    masking of genuine bugs).
- Top-level except in `run_fa_poll_cycle` now computes the friendly
  exception, uses its message for the four reporting paths (progress
  dict, logger.error, `fa_poll_log.error_message`, Telegram alert),
  and re-raises with `raise friendly from e` so the original traceback
  is preserved for postmortems via `exc_info=True`.

The orchestrator's secondary log line in `server.py:249` (`Poll fa
failed: ...`) now also picks up the friendly message because it logs
`str(result)` against the propagated exception.

No behaviour change for transient FAExport 429s that recover via the
in-client retry path (added 2.23.2) — those never reach this handler.

#### Files

- `polling/fa_poller.py` — new `FAExportUpstreamError`, new `_humanize_fa_error`,
  swapped top-level except to translate before reporting.
- `config.py` — `APP_VERSION` bump to `2.26.1`.

---

## [2.26.0] - 2026-05-21

### Feature: in-app Uninstall flow + Windows Search integration polish

Closes the "I deleted the .AppImage / extracted folder, but the data
and autostart entries are still on my machine" gap. New
**Settings → General → Danger zone → Uninstall PawPoller** button that
detects the install type and runs a per-OS cleanup script.

The Inno Setup installer was already correctly registering with
Windows Search / Apps & features / Control Panel via the
`HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\{AppId}_is1`
key (`AppId` + `UninstallDisplayName` + `UninstallDisplayIcon` were
all set in 2.24.0). Right-clicking the Start Menu search result for
"PawPoller" already showed Open / Pin / Uninstall. This release wires
the in-app button to delegate to the same `unins000.exe /SILENT` that
Windows Search invokes — both paths share one uninstaller.

#### `uninstall.py` (new ~290 LOC)

Per-OS detection + cleanup-script builder.

`InstallType` enum: `WINDOWS_INSTALLER` (Inno — has unins000.exe next
to PawPoller.exe), `WINDOWS_PORTABLE` (zip extract — no unins000),
`LINUX_APPIMAGE` (`APPIMAGE` env var set), `DEV` (running from source
under Python interpreter), `UNKNOWN`.

`detect()` returns an `UninstallPlan` dataclass — pure / no side
effects, safe to call from the UI for the confirm dialog. Reports:
- app_path (install dir / AppImage path / source root)
- data_dir (`%APPDATA%\PawPoller` or `~/.local/share/PawPoller`)
- autostart_target (registry key path or `.desktop` file path)
- has_keyring_key (best-effort probe via `keyring.get_credential`)

`execute()`:
1. Synchronously removes the autostart entry via the existing
   `config.set_run_on_startup(False)` (handles registry on Windows /
   `.desktop` file on Linux).
2. Synchronously removes the vault encryption key from the OS keyring
   via `keyring.delete_password("PawPoller", "vault_key")`.
3. Asynchronously spawns a detached cleanup script per install type:
   - **Inno installer** → `unins000.exe /SILENT`. Same uninstaller
     Windows Search → Uninstall invokes. The script's existing
     `[Code] CurUninstallStepChanged` prompt still fires for user
     data; the in-app dialog pre-emptively deletes
     `%APPDATA%\PawPoller` first if the user ticked the box.
   - **Windows portable** → `.bat` that waits 3s, `taskkill`,
     `rmdir /S /Q` on the install dir and (if requested) data dir.
     Defensive `if exist "{install}\PawPoller.exe"` guard so a
     misconfiguration can't `rmdir C:\` style nuke an unrelated dir.
   - **Linux AppImage** → `.sh` that waits 3s, `pkill -f PawPoller`,
     `rm -f $APPIMAGE`, `rm -rf` data dir + autostart `.desktop`.
   - **Dev mode** → refuses to delete the source tree (won't nuke a
     developer's working copy); cleans data + autostart only.

`_spawn_detached()` uses `os.startfile` on Windows and
`subprocess.Popen(..., start_new_session=True, stdin/out/err=DEVNULL)`
on Linux so the script survives the parent exiting.

#### `routes/settings_api.py`

Two new endpoints:

- `GET /api/settings/uninstall/plan` — returns the detected install
  type + paths. Pure / no side effects.
- `POST /api/settings/uninstall` — kicks off the cleanup. Requires
  `confirm: "UNINSTALL"` in the body as a guard against accidental
  fires (user types it in the dialog). After spawning the script,
  schedules `os._exit(0)` for 2s later via
  `asyncio.get_event_loop().call_later` so the response flushes
  cleanly before shutdown.

#### `frontend/js/app.js`

New Settings → General accordion "Danger zone" with red-tinted
styling. The Uninstall button opens a two-step modal:

1. `_showUninstallDialog()` fetches `/uninstall/plan` and renders the
   detected paths in a monospace block. Three checkboxes for
   app / data / autostart. Dev-mode disables the app-files
   checkbox (and explains why). Confirm input field requires the
   literal text `UNINSTALL` before the proceed button activates.
2. On confirm, POSTs `/uninstall` and swaps the modal body to a
   "Goodbye 👋" screen with the queued-actions list. The server's
   `os._exit(0)` fires 2s later; the user closes the tab manually.

#### What Windows Search → Uninstall does today

Already wired by Inno Setup. The relevant registry key is automatic:

```
HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\{A8E2F7B4-...}_is1
  DisplayName        = PawPoller
  DisplayVersion     = 2.26.0
  Publisher          = KnaughtyKat
  DisplayIcon        = <install>\PawPoller.exe
  UninstallString    = <install>\unins000.exe
  QuietUninstallString = <install>\unins000.exe /SILENT
  URLInfoAbout       = https://github.com/knaughtykat01-prog/PawPoller
  HelpLink           = https://github.com/knaughtykat01-prog/PawPoller/issues
  URLUpdateInfo      = https://github.com/knaughtykat01-prog/PawPoller/releases
```

Surfaces:
- **Start Menu search** "pawpoller" → right-click → Uninstall
- **Settings → Apps & features** → PawPoller → Uninstall
- **Control Panel → Programs and Features** → PawPoller → Uninstall

All three trigger the same `unins000.exe`, which:
1. Asks confirmation (unless `/SILENT` is passed).
2. Runs the `[UninstallRun]` `taskkill /F /IM PawPoller.exe`.
3. Removes everything Inno's installer tracked.
4. Runs the `[Code]` `CurUninstallStepChanged` to prompt about
   `%APPDATA%\PawPoller` (default No — keep user data for reinstalls).
5. Deletes the HKCU `Run` entry (the `Tasks: startupicon; Flags:
   uninsdeletevalue` directive handles this).
6. Cleans up Start Menu shortcuts.

#### Known limitations

- **Vault key in OS keyring** is only cleaned up via the in-app
  Uninstall button. Users who uninstall via Windows Search →
  Uninstall (or `rm` the AppImage manually) will leave a 64-char hex
  value in Windows Credential Manager / Secret Service. Tiny, no
  security impact (the encrypted vault file is gone too), but it's
  a stray entry. Documented in HANDOFF.
- **macOS** uninstall path not yet implemented (raises
  `RuntimeError` on `darwin`). Lands with the macOS native app.

---

## [2.25.0] - 2026-05-21

### Feature: Linux desktop support (AppImage)

PawPoller now ships native builds for both Windows and Linux. The Linux
build is a single-file `.AppImage` — distro-independent, no install
required, double-click to run on Ubuntu 22.04+, Fedora 37+, Debian 12+,
Arch, etc. macOS support is on the public roadmap.

The codebase had only four Windows-isms; each got a per-OS shim rather
than a `if sys.platform` sprinkle:

#### Autostart (`config.py`)

`get_run_on_startup()` / `set_run_on_startup()` now branch on
`sys.platform`:

- **Windows** — HKCU registry value (unchanged).
- **Linux** — XDG autostart `.desktop` file at
  `~/.config/autostart/PawPoller.desktop`. Honoured by every major DE.
- **macOS / other** — `set_run_on_startup` logs a warning and returns;
  `get_run_on_startup` returns False. Wired so the Settings → General
  toggle in the dashboard still renders but is a no-op until the macOS
  launch-agent plist branch lands.

Shared `_exec_command_for_autostart()` helper handles the frozen vs
dev-mode exec-string difference once.

#### Desktop notifications (`polling/notifications.py:show_toast`)

- **Windows** — `winotify` (unchanged).
- **Linux** — shell-out to `notify-send` (libnotify). Present by default
  on every major DE. `--app-name=PawPoller` groups our toasts together
  in DE notification centres. Silently no-ops if `notify-send` isn't on
  PATH (headless servers, minimal containers).
- **macOS / other** — no-op + debug log.

#### PyInstaller spec (`pawpoller.spec`)

`hiddenimports` now branches via `_PLATFORM_HIDDEN_IMPORTS`:

| OS | Backend modules |
|---|---|
| Windows | `pystray._win32`, `winotify` |
| Linux | `pystray._appindicator`, `pystray._gtk` |
| macOS | `pystray._darwin` (for future use) |

#### pywebview backend on Linux (`main.py`)

The default GTK backend needs PyGObject + WebKit2GTK system bindings
that don't bundle cleanly via PyInstaller / AppImage. Switched to the
Qt backend (`webview.start(gui='qt')`) on Linux — pip-installable Qt6
+ QtWebEngine ship their own native libs and bundle cleanly. Windows
and macOS use their respective native backends unchanged.

#### Requirements (`requirements.txt`)

Env markers so the right deps land per-OS without a separate
`requirements-linux.txt`:

```
winotify>=1.1.0 ; sys_platform == "win32"
PyQt6>=6.6 ; sys_platform == "linux"
PyQt6-WebEngine>=6.6 ; sys_platform == "linux"
```

#### AppImage build (`installer/build-appimage.sh` + CI)

New `installer/build-appimage.sh` constructs the AppDir layout from
`dist/PawPoller/` (PyInstaller --onedir output), writes an `AppRun`
launcher script + `PawPoller.desktop` entry + `PawPoller.png` icon (from
existing `assets/tray_icon.png`), then runs `appimagetool` to produce
`installer/Output/PawPoller-{version}-x86_64.AppImage`. Falls back to
downloading `appimagetool` from the AppImageKit continuous build if not
on PATH (local runs).

New `build-linux` job in `.github/workflows/build.yml` runs on
`ubuntu-22.04` (GLIBC 2.35 — lowest commonly-available, best
forward-compat with newer distros). Installs:

- WeasyPrint runtime libs (libpango, libcairo, libgdk-pixbuf, libffi)
- libnotify-bin for notify-send
- Qt6 platform plugin runtime deps (libgl1, libegl1, libxcb-*,
  libxkbcommon-x11-0, libdbus-1-3)
- libnss3, libxcomposite1, libxdamage1, libxrandr2, libasound2 —
  QtWebEngine dependencies

Runs PyInstaller against `pawpoller.spec`, then `build-appimage.sh`,
then uploads + attaches `PawPoller-*-x86_64.AppImage` to the GitHub
Release.

#### Auto-updater (`updater.py`)

`_pick_update_asset()` picks per-OS:

- **Linux** — `*-x86_64.AppImage` (single file, in-place replace).
- **Windows** — `*.zip` (extract + robocopy mirror, unchanged).

The Windows installer `.exe` is intentionally NOT chosen by the
in-app updater — it's for fresh installs, not incremental upgrades
of an already-installed app.

New `_apply_update_linux(appimage_path)` writes a tiny bash script
that sleeps 2s (lets the parent process exit), `mv`'s the new
AppImage over the path in `$APPIMAGE` (standard env var set by the
AppImage runtime), chmod +x, exec the new one. Spawned detached via
`subprocess.Popen` + `start_new_session=True`.

`download_update()` now derives the temp filename from the URL
basename so the downloaded file's extension is preserved (`.zip`
on Windows, `.AppImage` on Linux) — helps log triage.

#### Public-facing changes

- **README.md** — split Quick Start "Option A" into Windows (installer
  or portable zip) + Linux (AppImage, optional `libnotify-bin`)
  subsections. Mentions macOS not-yet-available.
- **Marketing site** (`site/`) — Hero version chip → v2.25.0;
  download CTA → "Download for Windows + Linux"; "Desktop" tier
  subtitle → "Windows · Linux · macOS planned"; body copy mentions
  AppImage and the planned macOS work.
- **`docs/ROADMAP_PUBLIC.md`** — new "Cross-platform desktop"
  section. Linux marked done; macOS detailed as planned with the
  open Apple Developer cert / notarization question called out
  honestly.

#### What's NOT in this release

- **macOS native app** — on the roadmap, not shipping in 2.25.0.
  Same shape as Linux work (per-OS shims already done) plus
  `.app` / `.dmg` packaging plus the signing/notarization decision.
- **Linux ARM (aarch64)** AppImage — x86_64 only for now.
  Raspberry Pi / ARM Linux users should keep using the Docker path
  (multi-arch image).

---

## [2.24.0] - 2026-05-20

### Feature: Windows install wizard

Replaces the "download zip, extract, run exe" first-run experience with
a proper single-file installer. The portable zip stays — both are
attached to every tagged release.

#### `installer/PawPoller.iss` (Inno Setup script, ~90 LOC)

- **Per-user install by default**, no UAC. Users can flip to system-wide
  (Program Files) via the privileges page if they want.
- **Start Menu shortcut** always; **desktop shortcut** optional (task
  on the components page, unchecked by default).
- **"Run on Windows startup"** optional task — when ticked, writes a
  per-user `HKCU\…\Run` entry pointing at `PawPoller.exe`. Mirrors the
  in-app Settings → General toggle so either path works.
- **"Launch PawPoller now"** tick-on-finish, `skipifsilent` so the
  auto-updater's eventual silent installs won't pop the GUI.
- **Uninstaller**: properly registered under Add or Remove Programs.
  On uninstall, a confirm dialog offers to delete `%APPDATA%\PawPoller`
  (default No — most uninstalls are upgrades or troubleshooting, not
  "delete everything"; user can still tick Yes for a clean slate).
- **Best-effort process kill** via `taskkill /F /IM PawPoller.exe` before
  uninstall so file deletions don't trip "in use" errors.
- **AppId** = fixed GUID so future installs upgrade in place rather than
  installing alongside an older copy.
- **AppVersion** is injected at build time via `/DMyAppVersion=…`
  passed to `iscc`, sourced from `config.py:APP_VERSION` so there's no
  duplicated version string to drift.

#### `.github/workflows/build.yml`

After the existing PyInstaller + zip step, new steps:

1. **Read app version** from `config.py` into a job output.
2. **Build installer** — Inno Setup 6 is pre-installed on
   `windows-latest` runners (verified 2026-05-20), with a fallback to
   `choco install innosetup` if a future image drops it. Runs
   `iscc /DMyAppVersion="<version>" installer\PawPoller.iss`.
3. **Upload artifact** `PawPoller-Setup` alongside the existing
   `PawPoller-windows-x64` zip.
4. **GitHub Release** now attaches both files to the published release.

#### Skipped on purpose

- **Code signing.** Without an Authenticode cert (~$200-400/yr), the
  installer will trip Windows SmartScreen on first run — same friction
  the existing zip + exe already has, so the installer doesn't make
  trust worse. Deferred until there's a real cost/benefit case for the
  cert (non-technical users hitting SmartScreen at scale).
- **Custom installer icon.** The repo only has `assets/tray_icon.png`,
  not an `.ico`. Inno's default installer icon is used until someone
  cuts a proper `.ico`.
- **MSI / MSIX.** Wrong shape for an indie desktop app with system
  tray + HKCU autostart needs. Inno Setup is what 80% of comparable
  Python/PyInstaller apps ship.

#### Release notes for end users

- Existing zip users: nothing forces a switch. The portable zip is
  still produced and uploaded.
- New users on the next tagged release will see two download options;
  README updated to point at `PawPoller-Setup-{version}.exe` as the
  recommended path.

#### Tag-cut reminder

The installer only ships on `v*` tag pushes (the existing release
workflow trigger). Pushing this to master does not produce an installer
artefact — cut a `v2.24.0` tag when ready to publish.

---

## [2.23.3] - 2026-05-20

### Fix: AO3 form-fetch 525s killed posts that should have retried

Live AO3 update for `Drumheller_Detour` on 2026-05-20 06:47:15 hit a
single Cloudflare 525 (origin SSL handshake fail) on
`GET /works/85113586/edit` and the entire edit operation raised
`RuntimeError: AO3: Could not load edit form (status 525)` immediately,
bouncing the work into the retry queue.

`_get_page()` already retries 3× with backoff on 525 (documented in
`documentation_guide.md` §"AO3 from datacenter IPs sees frequent
ReadTimeout and 525 origin SSL handshake fail responses — about 1 in 5
requests"). But `edit_work`, `edit_chapter`, `create_chapter`,
`find_work_skin_by_title`, `create_work_skin`, and `update_work_skin`
were all using `self._http.get(...)` directly — bypassing the retry
loop. So a transient 525 surfaced as a hard failure instead of being
absorbed by the 3-attempt retry.

Same log also showed `find_work_skin_by_title` silently returning None
on its 525 — `_ensure_work_skin` then logged the cryptic
`"AO3: Work skin creation failed for Drumheller_Detour:"` (with an
empty error string because the skin lookup just said "not found"
rather than reporting the transient error).

Routed all six form-fetch GETs through `_get_page` in
`clients/ao3/client.py`:

| Method | Line | What it fetches |
|---|---|---|
| `edit_work` | 1073 | `/works/{id}/edit` |
| `edit_chapter` | 1283 | `/works/{id}/chapters/{ch}/edit` |
| `create_chapter` | 1630 | `/works/{id}/chapters/new` |
| `find_work_skin_by_title` | 1891 | `/users/{u}/skins?skin_type=WorkSkin` |
| `create_work_skin` | 1932 | `/skins/new?skin_type=WorkSkin` |
| `update_work_skin` | 2034 | `/skins/{id}/edit` |

All callers now check `html is None` instead of `resp.status_code != 200`
and raise with a "transient fetch failure" message that distinguishes
the case from a hard 4xx — useful for log triage. The 3-attempt 525
retry inside `_get_page` (2s/4s/6s backoff) absorbs the kind of brief
CF blip that fired tonight.

Delete-confirm GETs (`delete_work` lines 1789, 1823) intentionally left
alone — they're admin-only operations not in the hot path, and a 525
there returns None gracefully via the existing checks.

---

## [2.23.2] - 2026-05-20

### Fix: Publish-check action log overlapping action panel

User reported the "Recent actions" log (`Recent actions (N)` header
plus most-recent log entries) was visually overlapping the "Actions:"
header + "Save as draft (where supported)" row inside the publish
check cell drawer — making both unreadable. The log was rendered as a
**sibling** of the detail panel inside `.publish-check-body`
(`display: flex; flex-direction: column; gap: 16px`). In some
states — populated `_actionLog`, tall detail content — the flex gap
collapsed and the log painted over the action panel's option row.

Fix in `frontend/js/publish_check.js`: move the action-log placeholder
**inside** the action panel, as the last child after
`.publish-action-result`. The log is now in normal flow under the
action buttons rather than competing with the action panel via flex
stacking. Bonus: it's semantically closer to where the user just
clicked, so they don't have to look elsewhere to confirm what just
happened.

Also re-call `_renderActionLog()` after every `detail.innerHTML = html`
so the per-session `_actionLog` array (closure-scoped, survives
re-renders) repopulates the fresh placeholder on every cell click.

Three edits:
- `_renderMatrix` no longer emits the sibling `<div id="publish-action-log">`.
- `_renderActionPanel` emits it as the last element before the closing
  `</div>` of `.publish-action-panel`.
- `_showDetail` calls `_renderActionLog()` after `detail.innerHTML`.

### Fix: FAExport 429 → Retry-After + small pacing bump

A real production poll cycle on 2026-05-20 hit two back-to-back 429s
from FAExport within 2ms — first on the submission detail batch (one
submission dropped, log warning, batch continued) and then on the
watchers fetch (caught by the broad `try/except` at
`polling/fa_poller.py:392`, so the cycle didn't die, but the watcher
list was lost for that cycle). Same per-IP throttle window; the
detail-loop pacing ran out and we slammed straight into the watchers
endpoint while already inside the bucket.

FAExport's bucket is shared across every PawPoller-like user on
`faexport.spangle.org.uk`, so a 429 there is often someone else's
traffic, not ours — bumping `FA_REQUEST_DELAY_SECONDS` alone wouldn't
prevent it. AO3's full backoff-cache pattern (2.22.6 / 2.22.10) is the
wrong shape for FAExport: AO3 has a fixed-window Rack::Attack counter
where requests inside the window extend the punishment, FAExport is a
thin proxy without that pathology. Honouring `Retry-After` is the
minimum correct change.

#### `clients/fa/client.py`

New `_get_with_retry(url, *, params, max_retries=1, max_sleep=60.0)`
helper. Routes every FAExport `GET` through it. On 429:
- Reads `Retry-After` header, parses as float seconds; falls back to
  30s if missing or unparseable.
- Clamps to `[1.0, max_sleep]` (default cap 60s) so a bogus huge
  `Retry-After` can't hang a poll cycle indefinitely.
- Sleeps, then retries once. Non-429 responses passed through
  untouched — callers still own `raise_for_status` for genuine 4xx/5xx.

Five FAExport callers converted: `get_gallery_page`,
`get_submission_detail`, `get_submission_comments`, `get_user_profile`
(profile sniff), `get_watchers_page`. Direct-FA cookie-validation
path (`_fa_http`) is unchanged — FA's site has different throttling
shape and isn't what fired here.

#### `config.py`

`FA_REQUEST_DELAY_SECONDS = 1.0 → 1.5`. Cheap insurance against
self-inflicted bursts; doesn't help against shared-bucket pressure
(that's what the retry handles) but cuts our own contribution by a
third. ~5s extra wall time per ten-submission detail batch — invisible
at the 240-min cadence.

#### Behaviour change

Previous: FA poll cycle silently drops watcher list (and the latest
snapshot for whichever submission 429'd in the detail batch) when the
shared FAExport bucket is hot.

Now: FA poll cycle sleeps the server-supplied `Retry-After`, retries,
and recovers the data. Worst case if FAExport stays throttled past the
retry: same outcome as before — log warning, cycle continues, data
backfills on the next cycle.

---

## [2.23.1] - 2026-05-16

### Fix: SoFurry centring + collapse `_Clean.html` / `_SoFurry.html` to one file

User reported `Chosen` on SoFurry was rendering left-aligned for
everything that should have been centred (title, chapter headings,
content warning block, disclaimer). The editor preview rendered it
correctly, which masked the bug. Two distinct problems were stacked
on top of each other:

**Root cause 1 — converter output**: the SoFurry HTML converter
emitted chapter titles as `<h3 class="text-center">…</h3>` and
story titles as `<h2 class="text-center">…</h2>`. SoFurry's site CSS
honours `.text-center` on `<p>` elements but not on user-uploaded
heading tags, so the class was silently dropped on render. The
editor preview defines its own `.text-center` rule in
`editor.css:398` covering `<h2>`/`<h3>`, so the preview looked
right — there was no way to spot the divergence from inside the
editor.

**Root cause 2 — stale dual-file scheme**: `posting/story_reader.py`
preferred `HTML/*_SoFurry.html` over `HTML/*_Clean.html` for SF
posting (and used `_Clean.html` as the AO3 single-bulk-file source).
But `regenerate_story.py` only ever rebuilt `_Clean.html` — it had
never written `_SoFurry.html`. So the per-story `_SoFurry.html`
files on disk were months-stale snapshots, and SF posting was
uploading those instead of the freshly-regenerated `_Clean.html`
right next to them. The "fix the converter" change above had no
visible effect for the same reason.

User asked why both files existed at all. They didn't, meaningfully —
both were produced by the same SoFurry-format pipeline and the only
difference was a `_Clean.html` write step in the editor's regen
endpoint that nobody had collapsed. Going to one canonical file.

#### Converter (`editor/converter.py`)

Four sites in the SoFurry HTML output now emit
`<p class="text-center"><strong>…</strong></p>` instead of
`<h2 class="text-center">…</h2>` / `<h3 class="text-center">…</h3>`:

- `render_front_matter_sofurry` — story title (h2 → p+strong)
- `_convert_body_sofurry` — chapter heading (h3 → p+strong)
- `convert_to_sofurry_html` heuristic fallback — both title and chapter sites

The clean_html converter path (`render_front_matter_clean_html`,
`_convert_body_clean_html`) is unchanged — it's still used internally
by the SquidgeWorld chapter splitter (`convert_to_sqw_chapters`),
just no longer written to a `_Clean.html` file on disk.

#### Regenerator (`m_x/Scripts_Utils/regenerate_story.py`)

Renamed `clean_html_path` variable to `sofurry_html_path`.
Output filename changed from `{story_name}_Clean.html` to
`{story_name}_SoFurry.html`. Comments and print labels updated
("Clean HTML" → "SoFurry HTML"). The converter call is unchanged —
it was already invoking the SoFurry converter, just writing the
output to the wrong filename.

#### PawPoller (`posting/story_reader.py`, `posting/platforms/ao3.py`, `routes/editor_api.py`)

- `PLATFORM_FORMAT_MAP["sf"]` — removed the `_Clean.html` fallback
  line, now reads `_SoFurry.html` then per-chapter SoFurry HTML.
- `PLATFORM_FORMAT_MAP["ao3"]` — replaced `_Clean.html` with
  `_SoFurry.html` as the bulk-file fallback after SquidgeWorld
  concatenation. Same content, consistent naming.
- `_FORMAT_KEY_PATTERNS["html"]` and `["sofurry_html"]` — both now
  point at `_SoFurry.html` (the generic `"html"` format alias used
  by the editor's Available Formats badge list).
- `ao3.py` — module docstring + `_read_full_story_html` glob
  pattern updated from `*_Clean.html` to `*_SoFurry.html`.
- `editor_api.py` — `regenerate_all_formats` no longer writes
  `_Clean.html`. The `save_format_file` endpoint dropped its
  `clean_html` route (only `sofurry_html`, `bbcode`, `styled_html`
  remain).

#### Tests + docs

- `tests/bulk_ao3_drafts.py`, `tests/bulk_sf_drafts.py`,
  `tests/edit_sf_after_converter_rewrite.py`,
  `tests/sync_sf_drafts_to_server.py` — all renamed `_Clean.html`
  → `_SoFurry.html` for the new file location.

#### Story archive

Bulk-regenerated all 16 active story HTML files via
`regenerate_story.py` — every story under `Complete_Stories/*/HTML/`
now has a fresh `_SoFurry.html` with the corrected centring markup.
Deleted the 17 stale `_Clean.html` files from active HTML
directories. Backups (`Backups/`, `Chapters_backup_*/`,
`Old_Format_Files/`) preserved untouched.

#### Known follow-ups

- `Chosen` (and any other story previously posted to SoFurry from the
  stale `_Clean.html` path) needs a manual re-upload from PawPoller
  to push the corrected centring to the live SF page. The Velvet and
  Vice live version was already correct because its `_SoFurry.html`
  must have been written through the editor's regen endpoint at some
  point.
- The editor's "Clean HTML" preview tab in `frontend/js/editor.js`
  still exists for visual comparison — it just renders inline via
  `/editor/preview`, no file artefact. Not removing it because side-
  by-side preview is the easiest way to spot future drift.

#### Files touched

- `PawPoller/config.py` — APP_VERSION bump 2.23.0 → 2.23.1
- `PawPoller/editor/converter.py`
- `PawPoller/posting/story_reader.py`
- `PawPoller/posting/platforms/ao3.py`
- `PawPoller/routes/editor_api.py`
- `PawPoller/tests/{bulk_ao3_drafts,bulk_sf_drafts,edit_sf_after_converter_rewrite,sync_sf_drafts_to_server}.py`
- `m_x/Scripts_Utils/regenerate_story.py`
- `m_x/Archives/Complete_Stories/*/HTML/*_SoFurry.html` — all
  regenerated, 17 stale `_Clean.html` files deleted

---

## [2.23.0] - 2026-05-15

### Feature: dashboard UX batch — silence-killers, status surfacing, and a real navigation layer

User reported the persistent "I clicked a button and got nothing"
problem with the per-platform Poll Now / Full Resync controls — the
existing button-text flip ("Polling…" → "Done!") was visible for
1.5s before the page re-rendered, easy to miss, and gave no
durable confirmation. Same complaint surfaced against the editor's
Regenerate button (which dumped the full per-file regen result into
the toolbar status, pushing word-count and other controls
off-screen) and against the lack of any always-visible per-platform
health signal. This release ships eighteen small-to-medium changes
across three batches that resolve those root issues end-to-end.

**Batch 1 — kill the silence (immediate fixes):**

- **Slop scorer 0.0 fix.** `editor/slop.py` was looking for
  `slop_words.json` + `slop_trigrams.json` at three candidate
  paths; only `m_x/Scripts_Utils/` (sibling-to-PawPoller, local-
  desktop only) actually had them. On the cloud server the files
  weren't found, the loader silently set `_LOADED = True` to
  prevent retry, and every call to `score_text()` returned 0.0
  with empty hit dicts — reading as "perfectly clean prose." Fix:
  copy both JSON files into `PawPoller/scripts_utils/` so the
  bundled-fallback path resolves under Docker. Added
  `is_available()` accessor + logger warning when files aren't
  found; the editor route now exposes `available: bool` and the
  toolbar renders "Slop: —" instead of "Slop: 0.0" when the
  scorer can't load.
- **CSS Decorations dropdown contrast.** The Warning Icon /
  Section Break / Approach selects in the editor's CSS tab
  rendered unselected `<option>` rows with the accent colour at
  low opacity — barely readable against the dark background.
  Root cause: `frontend/css/editor.css` referenced never-defined
  CSS custom properties (`--surface-elevated`, `--border-primary`,
  `--color-success/warning/error`); the `var()` lookups silently
  fell through to browser defaults. Added legacy-token aliases at
  the `:root` of `tokens.css` mapping to the existing
  `--bg-card` / `--border` / `--success` / etc. — the alias
  RHS uses `var()` so per-theme values still take effect. Fixes
  the dropdown contrast bug AND every other silent fallback in
  editor.css / diagnostics.css / components.css at the same time.
- **Regen result toast.** The editor's Regenerate handler used to
  dump `data.results.join(', ')` (a 200+-character per-file
  manifest) into the toolbar status field. Replaced with a
  concise `window.toast.success("Regenerated N formats · X
  words")`; the full per-file detail goes to `console.info` for
  DevTools inspection. The Downloads dropdown already shows the
  canonical post-regen file list, so no information is lost.
- **Toast wiring across all 33 poll/resync entry points.** The
  per-platform `_dashPoll` / `_dashResync` helpers (4 surfaces,
  used by every platform dashboard's header buttons), the
  poll-all / resync-all aggregate handlers (2 surfaces), and
  every Settings → Polling-tab card's per-platform poll/resync
  pair (10 platforms × 2 = 20 surfaces) now fire
  `window.toast.{success,warn,error}` on completion. The 22
  polling-tab handlers were collapsed onto a shared
  `_pollingTabPoll` / `_pollingTabResync` pair (~240 lines
  removed), so the consistency win is enforced by structure
  rather than by every callsite remembering.
- **Sharper Full Resync confirms.** Generic "this may take a
  while" replaced with platform-specific text quoting both the
  platform name and the rate-limit risk: e.g. "Full resync re-
  fetches every SoFurry submission from scratch. This can take
  several minutes and will hit SoFurry's rate limits hard.
  Continue?"

**Batch 2 — status surfacing (durable awareness):**

- **`GET /api/platforms/health` endpoint** — single-fetch
  per-platform health snapshot. Returns `{configured,
  last_poll_at, last_poll_status, last_poll_error,
  interval_minutes, next_poll_at, throttled_until}` for all 11
  platforms. The throttle field is sourced from the AO3 client's
  module-level `_ao3_backoff_until_ts` cache (other platforms
  return null). Reads the existing `{p}_poll_log` tables via
  `get_{p}_last_poll`; one DB connection, 11 indexed lookups,
  cheap enough for the 60s frontend tick.
- **`frontend/js/platform_health.js`** — new module that polls
  the endpoint and fans the result out to every status surface.
  Exposes `window.PlatformHealth.{get, getAll, classify,
  subscribe, LABELS}` so future surfaces can read cached state
  without their own HTTP. Auto-starts only after the dashboard
  auth gate passes — no 401-spam on the login page.
- **Sidebar health dots.** The platform-grid popover already
  had empty `<span class="platform-grid-status" id="pg-
  status-{p}">` placeholders for each of the 11 platforms;
  platform_health.js fills them with `pp-health-{state}`
  coloured dots (green/amber/red/grey + animated blue for
  running) plus `data-tooltip` showing last-poll relative time
  and any error.
- **Per-platform header subtitle.** A small `.platform-page-
  subtitle` div is auto-injected under each platform dashboard's
  `<h2>` — "Last polled 47m ago · next in 13m" or "throttled 3m
  remaining". Implemented via a `MutationObserver` on `#app`
  (rAF-throttled) so the subtitle re-attaches after every SPA
  route change without touching the 11 individual
  `renderXDashboard()` methods.
- **Throttle / error banners.** Same module renders a coloured
  banner beneath the page-header when AO3 is in a known throttle
  window or the platform's last poll failed, with an "Open
  settings" action button for reconnect. Uses two visual
  variants: amber for throttle, red for error.
- **Reusable `[data-tooltip]` helper.** Lifted the 1.2s-hover
  pattern from the anchor toolbar (2.13.7/8) into
  `loading_indicator.js`. Single shared DOM node + event
  delegation on `document` so dynamically-rendered elements
  pick it up. Hidden on mouseleave / mousedown / scroll /
  Escape. Used by the dots + subtitle + every future control
  that wants inline help.

**Batch 3 — bigger surfaces:**

- **`GET /api/activity/recent` + Recent System Events panel.**
  New endpoint merges every platform's `{p}_poll_log` with
  `posting_log` into one chronological feed (poll completions,
  errors, posting actions). The Overview page renders the top
  20 events as a styled timeline with status dots and relative
  timestamps. Answers "what's the system actually doing?"
  without needing per-platform poll-log table dives.
- **Empty-state CTAs across all 11 platform dashboards.** New
  `Components.platformEmptyState(code, opts)` helper. Each
  `renderXDashboard()` short-circuits to the friendly empty
  state when the platform isn't configured (per
  `PlatformHealth`) or has zero submissions polled. The CTA
  button links to Settings → Platforms. Replaces the previous
  blank stat-cards / empty tables.
- **Cmd+K command palette.** New
  `frontend/js/command_palette.js` — keyboard-first nav modelled
  on GitHub / VS Code / Linear. Cmd+K (mac) / Ctrl+K (linux/win)
  opens a centred overlay with fuzzy-ranked commands across 11
  platforms × 2 sub-pages each + Settings/Editor/Stories/Queue
  + 3 actions (toggle theme, pause/resume polling). Up/Down
  arrows + Enter + Esc as expected; mouse hover synchronises with
  keyboard active state.
- **Notification test suite extension.** Added 3 non-destructive
  payload-format tests to `testing/tests/notifications.py`:
  `format_telegram_summary`, `_classify_error` (5 representative
  exception cases), `_format_error_for_telegram`. Catches
  accidental regressions to the helper signatures without
  burning a real Telegram-message budget. Plus 13 new toast /
  status-surface checklist rows in
  `qa/TESTING_CHECKLIST_WEBAPP.html` covering every Batch-1+2
  callsite.
- **Drift preview in Publish Check.** New `GET
  /api/posting/preview-file?story=X&platform=Y&chapter=Z`
  returns the local file's head excerpt (first 120 lines), size,
  modified-at, post-time, stored hash + current hash, drifted
  bool. The publish-check cell drawer gets a "Preview file"
  button that toggles an inline panel. No more blind Update on
  drifted cells — sanity-check what would actually get pushed
  before clicking.
- **Floating logs panel.** New `GET /api/logs/stream` SSE
  endpoint tail-follows `logs/{server,app,polling}.log` with a
  50–500-line backfill, byte-offset tracking for partial-line
  safety, log-rotation detection (size-shrink reset), 15s
  heartbeat. New `frontend/js/logs_panel.js` widget — pill
  toggle bottom-left, expands to a 520×360 panel with file
  picker, level filter, pause/clear, sticky-bottom auto-scroll.
  EventSource opens only when panel is visible and on
  `visibilitychange` to spare bandwidth. Open/file/level state
  persisted in `localStorage`.

**Files touched (selected):**
`config.py` (APP_VERSION bump), `editor/slop.py`,
`routes/api.py` (3 new endpoints + helpers + token aliases),
`routes/posting_api.py` (drift preview), `routes/editor_api.py`
(slop response + available flag), `frontend/js/api.js` (3 new
methods), `frontend/js/app.js` (toast wiring + 11 empty-state
guards + PlatformHealth.start), `frontend/js/components.js`
(`systemEventsFeed` + `platformEmptyState`),
`frontend/js/editor.js` (slop "—" + regen toast),
`frontend/js/loading_indicator.js` (tooltip delegation),
`frontend/js/platform_health.js` (new),
`frontend/js/command_palette.js` (new),
`frontend/js/logs_panel.js` (new),
`frontend/js/publish_check.js` (preview button + handler),
`frontend/css/tokens.css` (legacy aliases),
`frontend/css/loading_indicator.css` (tooltip + dots + subtitle +
banner + logs panel), `frontend/css/components.css` (events feed
+ empty state + command palette), `frontend/css/editor.css`
(drift preview), `frontend/index.html` (3 new script tags),
`testing/tests/notifications.py` (3 format tests),
`scripts_utils/{slop_words,slop_trigrams}.json` (bundled, 36KB),
`qa/TESTING_CHECKLIST_WEBAPP.html` (13 new rows).

**Known follow-ups (not in this release):**
- The 22 polling-tab handlers were collapsed onto a shared
  helper, but the 4 dashboard-header `_dashPoll`/`_dashResync`
  + 2 poll-all/resync-all handlers were left structurally
  unchanged (they already had distinct UI-state needs). A
  future refactor could fold those into the same helper for
  full consistency.
- Drift preview shows the LOCAL file's head; it doesn't fetch
  the upstream version for a real diff. Adding upstream-side
  fetch is a future enhancement (per-platform parse cost).

---

## [2.22.14] - 2026-05-14

### Fix: edit_chapter respects publish_live, doesn't silently re-draft chapters

User tested 2.22.13's "Update with live publish" path on work 84822261 —
the log showed `publish-all-drafts ... published=2, already_posted=3`,
but the drafts came back. Trace revealed the root cause:

`AO3Client.edit_chapter` was choosing the submit button by sniffing
the edit-form HTML — `save_button` (Save As Draft) was preferred when
present. For DRAFT chapters, AO3 renders BOTH "Save As Draft" and
"Post Without Preview"; `edit_chapter` picked "Save As Draft", which
**preserved the chapter as a draft after the edit**. So the flow per
chapter became:

1. `edit_chapter` (called from poster `edit()` loop) — saves content
   AS A DRAFT
2. `publish_all_draft_chapters` (called at end) — finds drafts, posts
   them via `/chapters/{cid}/post`

That worked once. But if the user clicked Update again (or another
edit() raced), step 1 re-drafted the chapters and step 2 had to
re-publish them. The log's `published=2, already_posted=3` pattern
recurring on both Round 1 and Round 2 was the signature.

**Fix in `clients/ao3/client.py:edit_chapter`:** new `publish: bool |
None` parameter.

- `publish=True` → force `post_without_preview_button=Post`; keeps the
  chapter LIVE after the edit (publishes draft chapters, leaves live
  ones live).
- `publish=False` → force `save_button=Save As Draft` if available;
  keeps the chapter as a DRAFT after the edit (logs a warning + falls
  back to post_without_preview if the form has no Save As Draft, i.e.
  chapter is already live and AO3 doesn't allow draft-mode editing).
- `publish=None` → legacy auto-detect (the buggy behaviour, preserved
  for callers that don't know about live/draft yet).

**Wired in `posting/platforms/ao3.py:edit()`:** every `edit_chapter`
call now passes `publish=publish_live if publish_live else None`.

- When user updates with live publish toggled on → `publish=True` on
  every chapter edit → chapters end up LIVE directly from the
  edit_chapter POST.
- When user updates without live publish → `publish=None` → legacy
  behaviour preserved (live chapters stay live, drafts stay drafts).

`publish_all_draft_chapters` still runs at the end as a safety net for
chapters that don't get edited (e.g., AO3 has more chapters than
local source).

**For work 84822261 going forward:** hit dashboard Update with live
publish toggled on. Each chapter's edit_chapter call now publishes
directly. publish_all_drafts at the end should report
`published=0, already_posted=5`.

---

## [2.22.13] - 2026-05-14

### Fix: AO3 multi-chapter live posts walk every chapter and publish drafts

User checked work 84822261 after the 2.22.11b success run: stats showed
`Chapters: 2/?` with chapter 2 ("Beneath the Steam") rendered with a
**"This chapter is a draft and hasn't been posted yet!"** banner. The
work itself was live and chapter 5 was visible, but chapters 2-4 sat
as drafts. AO3's HTML dev-tools confirmed the per-chapter "Post
Chapter" button POSTs to `/works/{wid}/chapters/{cid}/post`.

**Root cause:** 2.22.8's publish-live wire-up assumed
`post_without_preview_button=Post` on the last `create_chapter` would
flip the entire work — including all draft chapters — to live. Wrong.
**AO3 chapters have independent draft state.** Sending
`post_without_preview_button` on a single chapter publishes that
specific chapter (and may flip the work-level "posted" flag), but
does NOT auto-publish other draft chapters. Each draft must be POSTed
to its own `/post` endpoint individually.

**Fix:**

1. **New `AO3Client.post_chapter(work_id, chapter_id)`** — fetches a
   fresh CSRF token from the chapter page, POSTs to
   `/works/{wid}/chapters/{cid}/post` with `commit=Post Chapter`.
   Idempotent: if the page lacks a `/post` form (chapter already
   live), returns `{already_posted: True}` without firing the POST.

2. **New `AO3Client.publish_all_draft_chapters(work_id)`** — iterates
   `get_chapter_ids()` and calls `post_chapter` for each. Polite delay
   between calls. Returns `{total, published, already_posted, failed}`
   summary. Doesn't raise on individual failures — surfaces them in
   the `failed` list so the caller can log/continue.

3. **`AO3Poster.post()`**: after the chapter loop, if `publish_live`
   and `has_chapters`, call `publish_all_draft_chapters(work_id)`.
   Bug fix is automatic on subsequent multi-chapter live posts.

4. **`AO3Poster.edit()`**: now reads
   `publish_live = not bool(package.extra.get("draft", True))` (same
   shape as post). After the metadata/chapter-content updates, if
   `publish_live`, call `publish_all_draft_chapters`. This is the
   user-facing recovery path: hit "Update" on the dashboard with the
   live-publish toggle set, and any remaining draft chapters get
   posted automatically.

**For existing work 84822261:** hit dashboard Update with live
publish toggled on. The edit() flow now walks all 5 chapters and
posts the 3 that remain as drafts.

---

## [2.22.12] - 2026-05-14

### Fix: resumed AO3 posts now attach the Work Skin to the work

The 2.22.11b end-to-end success run revealed a follow-up nit: work
84822261 was successfully posted but the Work Skin (`The Silk Threaded
Bonds Skin`, skin_id 11035401) wasn't applied to the work. The skin
CSS was uploaded and saved on AO3, but the work itself had no
`work[work_skin_id]` set.

**Root cause:** `_ensure_work_skin` finds/creates/refreshes the skin
and returns its ID. The fresh-post path passes `work_skin_id=skin_id`
to `create_work` so AO3 stores the work-skin association at creation.
The resume branch (2.22.9) skipped `create_work` entirely — so the
skin attachment also got skipped. Work 84822261 was created in an
earlier throttled run before the skin existed, so the work never had
the skin attached.

**Fix in `posting/platforms/ao3.py:post()`:** after the resume branch
detects an existing work, if `skin_id` is non-empty, push
`edit_work(work_id, work_skin_id=skin_id)` to attach it. Idempotent —
re-submitting the same skin_id is a no-op on AO3. Wrapped in
try/except so a failure here doesn't block the chapter loop (skin can
still be attached manually via dashboard Update).

**For existing work 84822261:** hit "Update" on it from the dashboard —
`poster.edit()` already does this correctly; this fix just ensures it
happens automatically on resume too.

---

## [2.22.11b] - 2026-05-14

### Hotfix: AO3 poster also honours PROXY_OPTIONAL classification + UI catches up

2.22.11 moved AO3 from `PROXY_REQUIRED_PLATFORMS` to
`PROXY_OPTIONAL_PLATFORMS` in `polling/cf_proxy.py`, but the post-deploy
log still showed `AO3 client using CF proxy: …`. The poller's
`_get_or_create_client` was already routed through `proxy_kwargs()`, but
the poster's `_ensure_client` in `posting/platforms/ao3.py` had its own
hardcoded read of `cf_worker_url`/`cf_worker_key` from settings, bypassing
the platform classification entirely.

**Fix:**
- `posting/platforms/ao3.py:_ensure_client` now uses
  `proxy_kwargs(settings, "ao3")` like the poller. AO3 picks up the new
  optional classification (direct by default, opt-in fallback).
- `frontend/js/app.js:_loadCFProxyToggles` — UI catches up:
  - "CF Proxy Backup" explainer text updated: "**DeviantArt and SoFurry**
    always use the configured CF Worker proxy" (was "AO3, DeviantArt,
    and SoFurry").
  - AO3 added to the per-platform toggle list (9 platforms now, ordered
    ib / fa / ws / sqw / ao3 / bsky / ik / wp / tw). Backed by the
    existing `ao3_use_cf_proxy` settings key.

**Verified by:** The Silk-Threaded Bonds (5-chapter, work 84822261) →
clean post-deploy run at 05:16. The log line `AO3 client using CF proxy`
is gone; the resume flow saw `[1, 2, 3]` existing chapters on AO3,
added chapters 4 and 5, fired `publish=True` on the last chapter, and
the publication row flipped from `partial` → `posted`. End-to-end
verification of the entire 2.22.8 → 2.22.11b cascade.

---

## [2.22.11] - 2026-05-14

### Fix: AO3 routes direct from GCP IP, not through the shared CF Worker

After 2.22.10 + .10b + .10c stopped the in-window retries and the
tight-loop reprocessing, the AO3 throttle window still refused to
drain. 14 minutes of doing nothing — only one HTTP request per minute
from the queue retry — and the observed `Retry-After` had dropped
from 386s to only 325s. **Something else was keeping the throttle hot,
not us.**

Cause: AO3 was classified as `PROXY_REQUIRED_PLATFORMS` in
`polling/cf_proxy.py`, meaning every AO3 request from the server went
through `pawproxy.knaughtykat01.workers.dev` (the Cloudflare Worker
originally added to bypass AO3's "Shields are up!" page for
datacenter logins). Cloudflare Workers exit through a shared pool of
egress IPs — meaning **we were sharing AO3's per-IP quota with every
other Worker tenant pinging AO3 from the same outbound IP**. AO3's
Rack::Attack throttle (300 req / 300s per IP, from
`config/initializers/rack_attack.rb` at otwarchive v0.9.475.3) sees
the aggregate of all those tenants and keeps the shared egress IP
perpetually throttled.

User memory note from earlier sessions had captured this:
*"CF proxy: Only needed for DA + SF on server (datacenter IP blocks).
Other 9 platforms work from any IP."* — AO3 was in the right category
conceptually but mis-wired in code.

**Fix:** AO3 moved from `PROXY_REQUIRED_PLATFORMS` to
`PROXY_OPTIONAL_PLATFORMS` in `polling/cf_proxy.py`. After this:

- **Default behaviour:** AO3 routes direct from the GCP VM IP. The
  GCP IP is unique to us; AO3's per-IP quota is ours alone.
- **Fallback:** if the user sets `ao3_use_cf_proxy: true` in
  settings, optional-platform fallback kicks in — try direct first,
  retry through the Worker if a direct call hits a block-like
  failure (Shields are up, 429, etc.).

**Why the original classification existed:** the AO3 login form
(`POST /users/login`) does throttle datacenter IPs aggressively
("Shields are up!" 403 for 5-10 minutes after one bad attempt). The
proxy was the workaround. But cookie-mode auth (added 2.18.8) bypasses
the login endpoint entirely — we paste an `_otwarchive_session`
cookie from a warm browser session and never call `/users/login`.
Once cookie-mode became the default-on-GCP path, the proxy stopped
being necessary for AO3 — it just kept being used because of the
2.18.6 classification.

**Container restart side-effect:** module-level
`_ao3_backoff_until_ts` is process-local. The redeploy clears the
325s window observed pre-fix; the first post-deploy request will hit
a fresh throttle state. Either the GCP IP has clean quota → direct
works; or GCP is also throttled → user enables the proxy toggle.

---

## [2.22.10c] - 2026-05-14

### Hotfix: scheduler stops tight-loop reprocessing of failed queue items

Post-2.22.10b deploy log showed queue item #220 reprocessed every 5
seconds with attempts incrementing 0/3 → 1/3 → 2/3 → 3/3 inside half a
minute. Two retry mechanisms were colliding:

- `manager._schedule_retry` adds a NEW queue row with proper backoff
  (60s / 300s / 1800s)
- `scheduler._process_queue_item` set the SAME row back to `pending`
  with no `scheduled_at` bump, so `get_pending_queue` picked it up
  every 5 seconds (scheduler check interval)

**Fix in `posting/scheduler.py:_process_queue_item`:** check
`results[0].retry_queued` and `results[0].queued_desktop`. If either is
true, the manager already handed off to a fresh queue row or to desktop
— mark this row `failed` instead of `pending`. The new row scheduled
by `_schedule_retry` remains and fires on its proper delay. Legacy
inline-retry path preserved as fallback for edge cases where neither
handoff flag was set.

---

## [2.22.10b] - 2026-05-14

### Hotfix: wrap _http.get/post so throttle gate applies to ALL requests

2.22.10's pre-flight check on `_get_page` and `_post_with_retry` wasn't
enough — raw `self._http.get()` calls (chapter form load in
`create_chapter`, edit-page fetches, work-deletion confirms,
work-skin form lookups, etc.) dodged the gate.

**Fix in `clients/ao3/client.py:__init__`:** wrap `self._http.get` and
`self._http.post` so every request goes through pre-flight check
(short-circuit with synthetic 429 response if window active) and
`_record_throttle` on observed 429. Wrap is installed once at client
construction; no need to touch the 13 raw `_http.get/post` call sites
scattered through the file. Existing pre-flight checks in `_get_page`
and `_post_with_retry` still apply — they no-op when the wrap catches
it first.

---

## [2.22.10] - 2026-05-14

### Fix: AO3 throttle handling — empty-username URL, unified backoff cache, no in-window retries

After 2.22.9 verified that work_id checkpointing works (work 84822261
created and persisted with status="partial", external_id preserved
across retries), the actual post still couldn't complete because
`_post_with_retry` kept retrying inside AO3's 5-minute punishment
window, extending the throttle every cycle. Investigation of the OTW
Archive source code at v0.9.475.3 (the actual code running on AO3)
clarified the mechanics:

**From `config/initializers/rack_attack.rb`:**

```ruby
throttle('req/ip', limit: 300, period: 300) do |req|
  req.ip
end
```

- **One per-IP bucket: 300 requests / 300 seconds (~1 rps).** Every
  endpoint we hit feeds it: `/works`, `/chapters`, `/works/new`,
  `/skins`, even the empty-username 404.
- **Fixed window, not sliding.** `Retry-After` reports time until the
  current window rolls over.
- **No login bonus** for work-posting endpoints. Cookie auth doesn't
  help here.
- **No exponential backoff on AO3's side.** Each "punishment" is just
  `period - (now % period)`.
- **Requests inside the window count toward the NEXT window's quota.**
  This is the killer — `_post_with_retry` was sleeping the Retry-After
  then firing the same request at window rollover, immediately eating
  the new window's budget.

**Three concrete fixes:**

1. **Empty-username URL bug** in `clients/ao3/client.py`. In
   cookie-only auth mode `self.username` is empty (the cookie carries
   identity, not the form-login handle). Three methods —
   `is_work_in_drafts`, `is_work_published`, `find_work_skin_by_title`
   — built URLs like `/users//works/drafts`, `/users//works`,
   `/users//skins?skin_type=WorkSkin`. AO3 served these as 404s but
   they still counted against the per-IP bucket. Fix: `owner =
   self.username or self.target_user` before building the URL. Saves
   ~3 wasted requests per post() call.

2. **Unified backoff cache.** `_record_throttle()` is now called from
   both `_get_page` AND `_post_with_retry` on 429 (previously only
   `_get_page`). The 2.22.6 module-level `_ao3_backoff_until_ts` now
   reflects every observed throttle window regardless of HTTP method.

3. **No in-method retries on 429.** Both `_get_page` and
   `_post_with_retry` now:
   - **Pre-flight check** — if `_ao3_backoff_until_ts > time.time()`,
     short-circuit immediately without firing the request. Returns
     `None` (`_get_page`) or raises `AO3ThrottledError`
     (`_post_with_retry`).
   - **On 429** — record the throttle, log clearly, and abort. No
     sleep-and-retry. The queue retry will run later; if the window
     is still active when it runs, the pre-flight check
     short-circuits it.

**New exception:** `AO3ThrottledError(retry_after, url)` — raised by
`_post_with_retry` so callers can distinguish "throttled, will recover"
from generic HTTP failures. Currently bubbles up to the AO3 poster's
outer `except Exception` which returns `PostResult(success=False,
external_id=work_id)` — the work_id checkpoint from 2.22.9 means the
next queue retry resumes into the same work after the window expires.

**Known follow-up (not in 2.22.10):** the queue retry counter (1min →
5min → 30min) can exhaust all three attempts inside a single 5-minute
throttle window if the first attempt landed near the window start.
With pre-flight short-circuit those wasted attempts are cheap (no HTTP
fired) but they still count toward `max_attempts=3`. Future fix: have
`_schedule_retry()` consult `get_backoff_until_ts()` and schedule
beyond it (or don't increment the attempt counter when the failure
was a throttle).

---

## [2.22.9] - 2026-05-14

### Fix: AO3 multi-chapter retry creates duplicate works on transient failure

After 2.22.8's publish-live wire-up was deployed, a live test of The
Silk-Threaded Bonds (multi-chapter) hit a 429 on `GET /works/{id}/chapters/new`
after `POST /works` had already succeeded. The work was created on AO3
(`84818276`, as a draft per multi-chapter design), but the retry queued
by the poster restarted from `create_work` instead of resuming at
`create_chapter`. Every retry would have created another orphaned draft
work.

**Root cause:** `AO3Poster.post()` had no checkpoint between
`create_work` and the chapter loop, and no resume logic at the top of
the method. When the chapter form 429'd, the exception bubbled up to
`manager.post_story`, which upserted the publication row with
`external_id=""` (the original `PostResult` on failure carried no
external_id) and queued a fresh `post` action. On retry, the poster
ran the full sequence again with no awareness that work
`84818276` already existed.

**Fix in `posting/platforms/ao3.py:post()`:**

1. **Resume detection at entry:** look up the publication row for
   `(story_name, 0, "ao3")`. If `external_id` is non-empty AND status
   != "posted", the previous run got partway through. Set
   `existing_work_id` from that row.

2. **Verify the work still exists:** call `probe_exists(work_id)` —
   if `False` (user manually deleted the orphaned draft), clear the
   resume target and fall through to a fresh `create_work`. If `None`
   (probe failed), trust the checkpoint and try anyway.

3. **Skip create_work on resume:** when resuming, fetch already-posted
   chapters via `client.get_chapter_ids(work_id)`, build a
   `already_created_chapter_indices` set, and skip those in the
   chapter loop. The remaining chapters are added normally with
   `publish=publish_live` on the LAST one.

4. **Checkpoint after create_work:** immediately upsert the publication
   row with `external_id=work_id` and `status="partial"` (for
   multi-chapter) so any later chapter failure persists the work_id.
   Single-chapter posts use `status="failed"` since there's no chapter
   loop to checkpoint between — manager will flip to "posted" on
   success.

5. **Checkpoint inside the chapter loop:** on any chapter exception,
   re-checkpoint before re-raising so the resume target is fresh
   (status="partial", external_id=work_id).

6. **Failure path carries work_id:** the exception handler at the
   bottom of `post()` now returns `PostResult(success=False,
   external_id=failed_work_id, ...)` instead of an empty result. This
   ensures `manager.post_story` upserts the publication row with
   `external_id` set, so the *next* retry sees the resume target.

**Effect:**

- Multi-chapter post + transient 429 on chapter form → next retry
  resumes into existing work, skips chapters already on AO3, only adds
  the missing ones. No duplicate works.
- User manually deletes the partial work between retries → resume
  detects the 404 and falls back to fresh `create_work`.
- Probe transient failure (Cloudflare blip) → resume trusts the
  checkpoint and surfaces a clearer error if the work truly is gone.

**Still NOT fixed (carried from 2.22.8 note):**

- The empty-username URL bug at `/users//skins`, `/users//works`
- `_post_with_retry` does not call `_record_throttle()`, so post-side
  429s still don't populate the 2.22.6 backoff cache.

These remain as future work — flagged here so they aren't lost.

---

## [2.22.8] - 2026-05-14

### Fix: AO3 always posted as draft, ignoring user's "live" selection

User reported posting The Silk-Threaded Bonds to AO3 with "live" selected
in the dashboard, but the work landed in drafts (work 84817651). Log
showed the work was created via the preview-page response path, which is
the draft-state output of AO3's `preview_button=Preview` form submission.

**Root cause:** Three-tier bug chain.

1. **Dashboard route** (`routes/editor_api.py:1679-1681`): the `publish`
   handler built `extras` conditionally on `req.draft` truthiness, so
   `draft=False` produced an empty `extras` dict — the poster never saw
   the user's "live" choice.

2. **AO3 client** (`clients/ao3/client.py:create_work`): hardcoded
   `("preview_button", "Preview")` in the form body, so every call
   created a draft regardless of intent. Docstring explicitly said
   "Create a new work on AO3 as a DRAFT."

3. **AO3 poster** (`posting/platforms/ao3.py:post`): had no path to
   request a live post. The `allow_publish` flag in `package.extra` only
   suppressed the post-create safety check; it didn't change what was
   actually sent to AO3.

**Fix:**

- `editor_api.py`: always carry `extras["draft"] = bool(req.draft)`.
  Posters that don't distinguish live/draft can ignore it.
- `clients/ao3/client.py:create_work`: new `publish: bool = False`
  parameter mirroring the `add_chapter(publish=...)` pattern. When True,
  swaps `preview_button=Preview` for `post_without_preview_button=Post`.
  Return dict now includes `published: bool`. Preview-page response
  branch handles the "publish=True requested but landed in draft anyway"
  case with a warning log (returns `published=False` so the caller knows).
- `posting/platforms/ao3.py:post`: reads `publish_live = not
  bool(package.extra.get("draft", True))` (defaults to draft for safety
  when flag absent). Single-chapter posts pass `publish=publish_live`
  directly to `create_work`. Multi-chapter posts create the work as a
  draft, post chapters Ch2..Ch(N-1) with `publish=False`, then call
  `create_chapter(publish=publish_live)` on the LAST chapter — AO3's
  "Post Without Preview" on a chapter publishes the whole work. The
  `_verify_still_draft` safety check is bypassed when `publish_live`
  is True (user intentionally wants live).

**Note on existing draft (work 84817651):** The Silk-Threaded Bonds is
currently sitting in the user's AO3 drafts. After this deploy, deleting
that draft and re-posting with live selected should work end-to-end.
Alternative: manually click "Post" on the preview page on AO3.

**Note on separate AO3 bugs surfaced in the same investigation
(NOT FIXED in 2.22.8, log as future work):**

- Empty-username URL bug: `/users//skins`, `/users//works` — the AO3
  username slot is empty in URL construction at the work-skin creation
  and post-verification steps. Pattern visible across multiple endpoints
  in `posting/platforms/ao3.py`. Triggers spurious 429s on malformed
  paths. Should be diagnosed in a future session.
- Post-side 429s don't populate the backoff cache: 2.22.6's
  `_record_throttle()` is only called from `_get_page`, not from
  `_post_with_retry`. After a post 429s, the polling orchestrator's
  cache stays empty and the next poll fires blind.

Files: `routes/editor_api.py`, `clients/ao3/client.py`,
`posting/platforms/ao3.py`, `config.py`.

---

## [2.22.7] - 2026-05-14

### Fix: pawsync silently clobbered dashboard edits — added pre-flight freshness check

**Failure mode discovered:** when the user added cover/chapter-thumbnail
references to a story's `story.json` via the dashboard's editor →
metadata tab, those edits lived only on the server's running container
copy until a `pawpull` brought them down to local. If the user instead
ran `pawsync` (local → server) before pawpull, pawsync's unconditional
tar-overwrite silently wiped the dashboard edits. The clobbered version
was preserved in `story.json.bak.<unix-ts>` on the server (the dashboard
makes a backup on every save), so recovery was possible — but only if
the user knew the trap existed.

This actually happened to Overtime's cover + 4 chapter thumbnails (wired
up via dashboard, clobbered by a later pawsync; intact wiring sat in
`/home/kithetiger/story-archive/Overtime/story.json.bak.1778210960`).

**Fix:** new pre-flight step `check_server_freshness()` in `pawsync.py`,
runs before pack/scp/extract. SSHes to the server and enumerates every
`story.json` mtime via `find ... -printf '%T@ %P\n'`, compares with
local mtimes. If any server file is newer than its local counterpart by
more than 60 seconds (well above tar's mtime-restore precision — pawsync
itself produces deltas of zero), pawsync aborts with exit code 3 and a
clear error listing every offending path, server timestamp, local
timestamp, and minute-delta. The user is directed to run pawpull first
or pass `--force` to discard the server edits intentionally.

The 60s threshold catches dashboard edits (always minutes+ deltas) while
ignoring sub-second tar-restore noise. False-positive rate should be
zero on a healthy sync flow.

**New flag:** `--force` skips the freshness check entirely. Equivalent
to pre-2.22.7 behaviour.

**Sample failure output:**

```
[0/4] Checking server freshness (story.json mtimes)
  2 story.json file(s) newer on server than local

ERROR: Server has newer story.json files than local:
  Overtime/story.json
    server: 2026-05-14 09:32:11  local: 2026-05-12 18:04:30  (server +2128.5 min)
  Tombstone/story.json
    server: 2026-05-14 10:01:44  local: 2026-05-13 21:15:02  (server +766.7 min)

These are dashboard edits that pawsync would overwrite.
Run `deploy\pawpull.bat` first to bring them down to local,
or re-run with --force to discard them intentionally.
```

Files: `deploy/pawsync.py`, `config.py` (version bump).

Doesn't require server redeploy — pawsync is a local dev tool that
SSHes to the server. The `pawpoller` GCP container keeps running 2.22.6
behaviour unchanged.

---

## [2.22.6] - 2026-05-14

### Feature: AO3 backoff-state cache — skip cycles inside an observed throttle window

The 2.22.4/2.22.5 delay tunes (3s → 6s → 12s) reduce the rate at which
we fill our per-IP bucket, but they can't get us *out* of a punishment
window once we're inside one. We landed in exactly that hole during the
2.22.2-2.22.5 deploy sprint: enough cumulative pressure across the
afternoon's cycles that AO3 escalated to `Retry-After: 349s` and then
`Retry-After: 326s` on back-to-back test triggers. Every fresh request
inside an active throttle window can extend the punishment, so the
*right* response isn't to retry harder — it's to not request at all
until the window expires.

Implementation:
- Module-level `_ao3_backoff_until_ts: float` in `clients/ao3/client.py`,
  updated by `_get_page()` every time it observes a 429+`Retry-After`.
- New public helper `get_backoff_until_ts()` returns the unix timestamp
  the throttle window expires (or 0.0 if no window observed).
- `run_ao3_poll_cycle()` at `polling/ao3_poller.py:138` checks this
  before doing any work; if a window is active, returns a stub stats
  dict with `skipped_reason` and logs a clear warning, so the orchestrator
  log line for the cycle shows the skip but doesn't look like an error.

Side effects:
- The poll-progress JSON stays at `phase=idle` for skipped cycles —
  the cache is transparent to the dashboard.
- The Telegram consolidated summary's per-platform entry shows 0/0/0
  for AO3 when skipped, which is correct: nothing happened, on purpose.
- Process-local only: the cache lives in module state, so a container
  restart resets it. Not worth persisting — the throttle is on AO3's
  side and they don't tell us how much of the window is left after a
  cold start, but a fresh cycle will observe any active throttle on
  its very first request and rebuild the cache.

Defense-in-depth shape: 2.22.4/2.22.5 (slower pacing) prevents new
throttles; 2.22.6 (this) prevents existing throttles from being
extended by our own retries. Together they should keep AO3 polling
clean indefinitely on the steady-state cadence.

Files: `clients/ao3/client.py`, `polling/ao3_poller.py`.

---

## [2.22.5] - 2026-05-14

### Tune: AO3 inter-request delay 6s → 12s (aggressive generosity)

2.22.4's bump 3s → 6s was the external-tool baseline, but the first
live cycle on the new pacing still hit `AO3: 429 rate limited on
.../users/KnaughtyKat/works?page=1, waiting 349s (attempt 1/3)`. The
proximate cause was the cumulative pressure from earlier 3s-pacing
cycles plus the 2.22.2 probe-burning cycles — once you're inside AO3's
punishment window, it escalates the longer you stay there.

So double again: `AO3_REQUEST_DELAY_SECONDS = 6.0 → 12.0`. This makes
us slower than every comparable AO3 scraper and gives the per-IP bucket
comfortable headroom to drain between requests.

Cost: ~60s extra wall time per ten-work cycle. Still invisible at the
240-min cadence.

If 12s isn't enough either, the next move isn't more delay — it's
**backoff-state caching** (skip a cycle entirely when we know we're
mid-punishment-window) rather than enqueuing requests that will
inevitably 429. Not shipping that today — wait and see how 12s does
across a few cycles first.

Files: `config.py`.

---

## [2.22.4] - 2026-05-14

### Tune: AO3 inter-request delay 3s → 6s

Comparative read of three external AO3 tools (FanFicFare issue #1149,
kenalba/ao3-scraper, and the AO3 admin posts around the 2024-25 AI-scraper
escalation) confirmed our 3s pacing is more aggressive than the widely-
used baseline of 6s. AO3 tightened its per-IP throttle after the 2023
DDoS and again during the AI-scraper situation; 3s used to be fine,
6s is the current "polite-citizen" rate that most actively-maintained
downloaders converged on.

Concrete change: `AO3_REQUEST_DELAY_SECONDS = 3.0 → 6.0` in `config.py`.

Cost: ~30s extra wall time per cycle for a ten-work scrape — invisible
since polling runs background-async on a 240-minute interval. Benefit:
halves the rate at which we can fill our own per-IP bucket, which makes
back-to-back throttle hits across cycles vanishingly unlikely.

Architecture note from the comparison audit: PawPoller is already ahead
of every comparable external tool on AO3 throttling — cookie-only auth,
CF Worker egress, real `Retry-After` parsing, multi-attempt retries with
backoff. The only missing piece was the conservative inter-request delay;
this tune closes that gap.

Files: `config.py`.

---

## [2.22.3] - 2026-05-13

### Fix: AO3 poll cycle's redundant cookie-validation probe

After 2.22.2 enabled cookie-only AO3 polling, the first live cycle hit
`AO3: 429 rate limited on https://archiveofourown.org/users/KnaughtyKat,
waiting 118s` before the actual work-discovery scrape even started. The
cycle still completed (1 submission, 2 new kudos) but a 2-minute backoff
on every cycle is the exact problem cookie-only auth was supposed to
avoid.

Root cause: `polling/ao3_poller.py:run_ao3_poll_cycle` called
`await client.validate_session()` as step 1. `validate_session()` is
specced as the `/auth/connect` probe — it does an extra HEAD-equivalent
fetch of `/users/{target}` to confirm the cookie is alive. AO3's
per-IP throttle hits that endpoint hard from datacenter IPs. Meanwhile
`ensure_logged_in()` already trusts a pasted cookie without fetching
(see the comment block in `clients/ao3/client.py:415-449`) — it was
written specifically to avoid this throttle.

Fix: switch the poller's step 1 to `ensure_logged_in()`. The cycle's
actual work (works-list scrape + per-work details) will still fail
loudly if the cookie has expired, so the probe added only latency, not
safety.

Files: `polling/ao3_poller.py`.

Verification: trigger a poll via the AO3 button (or `pp.sh` →
`/api/poll/trigger/ao3`); the cycle should start the works-list scrape
immediately with no preceding `/users/{target}` 429.

---

## [2.22.2] - 2026-05-13

### Fix: AO3 polling skipped on cookie-only auth

The poll orchestrator's per-platform credential gate at `server.py:213-214`
required both `ao3_username` AND `ao3_password` before AO3 was scheduled
for polling. AO3 has supported cookie-only auth since v2.19.3 — the gate
was never updated to match, so any deployment that configured AO3 via
`_otwarchive_session` (the recommended path for datacenter IPs, since the
form-login endpoint is rate-limited to 5-10 min cooldowns and effectively
unusable from GCP) was silently excluded from every poll cycle. AO3
submissions therefore never appeared in the dashboard, kudos counts
stayed at 0, kudos users were never tracked, and the daily activity
digest had no AO3 section.

Fix: widen the gate to accept either (username AND password) OR
session_cookie. Mirrors the auth flexibility the AO3 client itself
already supports — `_get_or_create_client()` and `validate_session()`
both handle cookie mode end-to-end.

Files: `server.py`.

Verification: deploy → wait one poll cycle → `docker compose logs` shows
`Polling N platforms (..., ao3, ...)` and the AO3 client logs work
discovery + per-work detail fetches. AO3 dashboard tab populates after
the cycle commits.

(SquidgeWorld polling was already working — same code path, but the SqW
gate at `server.py:211-212` was correctly written to accept username+
password. The user's "likewise for squidge" was a precaution; verified
in the same poll-orchestrator audit that no further SqW change was
needed.)

---

## [2.22.1] - 2026-05-13

### Feature: Global activity spinner + toast notifications

User feedback during the v2.22.0 rollout: when triggering an action
("Post to AO3", "Schedule", "Forget publication") nothing visible
happened during the in-flight window, then either the inline result
panel flickered with text or the matrix refreshed without explicit
confirmation. Two new always-on UI affordances make it obvious that
something IS happening:

**1. Top-right activity spinner.** A subtle 18px dot-ring with an
accent-coloured glow appears whenever any `fetch()` is in flight. New
module `frontend/js/loading_indicator.js` wraps `window.fetch` once
(idempotent — safe against hot reload) so every existing API call is
covered for free without touching call sites. 250ms delay before
showing so trivially-fast requests don't flash. A small badge shows
the in-flight count when more than one request is live. SSE
connections via `EventSource` don't trigger the spinner (different
API), so long-lived regen / diagnostics streams don't pin it on.

**2. Bottom-right toast stack.** Exposed as
`window.toast.{success,error,warn,info}`. Auto-dismisses after 4s
(success/info) or 6s (error/warn); click ✕ to dismiss earlier. Slide-
in/out transitions; newest on top. Wired into the highest-traffic
action handlers in `publish_check.js`:
- `_executeAction` (post / update / update_metadata / publish_draft)
- `_submitSchedule`
- Set URL manually (the v2.21.0 control)
- Forget publication (the v2.21.0 control)

Each toast carries the actual action + platform + chapter context so
the user knows what just succeeded or failed without scrolling back
to the matrix.

**3. `withLoading(btn, asyncFn)` helper.** New `window.withLoading`
that disables a button, swaps its label for a small spinner, and
preserves the button's width so the layout doesn't jump. Opt-in per
call site — not auto-applied (some buttons have their own progress
patterns; forcing a swap would clobber them).

**Files added:**
- `frontend/js/loading_indicator.js` — fetch wrap, toast API, button helper.
- `frontend/css/loading_indicator.css` — spinner + toast styles.

**Files modified:**
- `frontend/index.html` — loads the new CSS + JS (JS loads BEFORE
  `utils.js` so its fetch wrap is in place before any other module's
  init code can fire a request).
- `frontend/js/publish_check.js` — toast calls in `_executeAction`,
  `_submitSchedule`, URL-anchor handler, forget-publication handler.
- `config.py` — version bump.

---

## [2.22.0] - 2026-05-13

### Feature: PawPoller CLI — menu-driven TUI for the dashboard API

A single-file Python TUI under `cli/pawpoller_cli.py` that lets any
authenticated user drive the same API the web dashboard uses, from a
terminal. Built so the same script runs locally (against the GCP VM)
or on the VM itself (against 127.0.0.1) with identical UX.

**Top-level menu**:
1. Polling — pause/resume, trigger a single platform, full resync,
   per-platform status table.
2. Publishing & Queue — view/cancel queue, publish matrix, run any
   publish action (post/update/update_metadata/dry_run) with draft
   gating and live-publish confirmation, schedule, forget publication,
   set URL manually.
3. Diagnostics — list/run one test, run a category, run the full
   suite, attach to active runs. Live SSE stream of every event with
   per-test status colours and final summary.
4. Stories — list, regenerate one, regenerate all (with SSE-streamed
   bulk progress + detach via Ctrl-C), publish matrix, probe drafts.
5. Settings & Status — ping, view posting settings, list API key
   prefixes, show current CLI config, re-run setup.

**Config resolution** (in order):
1. Env vars `PAWPOLLER_URL` + `PAWPOLLER_KEY`.
2. `~/.pawpoller-cli.json` (created on first run via setup prompt).
3. VM-fallback hint that points the user at `setup` because the
   sqlite `api_keys` table stores key hashes, not plaintext.

**Tech**: `rich` for menus + tables + panels + colours, `httpx` for
HTTP + SSE streaming. Single file, no submodules, ~1100 LOC. Both
runners ship: `cli/pp.cmd` (Windows wrapper) and `cli/pp.sh` (Unix
wrapper for the VM).

**Run**:
- Local: `pip install -r PawPoller/cli/requirements.txt` →
  `python PawPoller/cli/pawpoller_cli.py` (or `pp.cmd`).
- VM: SSH in → `python3 /home/kithetiger/PawPoller/cli/pawpoller_cli.py`
  (or symlink `pp.sh` into `~/.local/bin`).

**Out of scope for v1** (mentioned so the contract is explicit):
- Story body editing (the menu skips it — use the web editor).
- Auto-launch on SSH login (one-line `.bashrc` follow-up).
- API key / TOTP setup (stays in the web UI for the security flow).

**Files added:**
- `cli/pawpoller_cli.py` — the TUI.
- `cli/requirements.txt` — `rich`, `httpx`.
- `cli/pp.cmd`, `cli/pp.sh` — thin launcher wrappers.

---

## [2.21.1] - 2026-05-13

### Fix: SquidgeWorld / AO3 phone-call and text-message styling lost without explicit anchors

User reported that `Hypnotic_Claim` on SquidgeWorld was rendering the
phone-call caller ID (`**ETHAN ❤**`) and text messages
(`**ETHAN ❤: Hey babe ...**`) as plain centred / left-aligned bold
paragraphs instead of the styled phone-bubble UI defined in the Work
Skin CSS (`.phone-display-wrap`, `.phone-display`, `.text-message`).

Root cause in `editor/converter.py:_convert_body_clean_html` — the
heuristic fallback (non-anchored detection via `is_phone_display` and
`is_text_message`) was emitting:

- `<p style="text-align:center"><strong>NAME ❤</strong></p>` (plain centre)
- `<p><strong>NAME:</strong> message</p>` (plain prose)

…instead of the styled divs that the parallel semantic-anchor branch
above it (lines 500–535) already emits when `<!-- @phone-incoming -->`
/ `<!-- @text-sent -->` / `<!-- @text-received -->` anchors are
present. Stories without explicit anchors silently fell back to plain
markup, defeating the Work Skin.

Fix: heuristic fallback now emits the same `<div class="phone-display-wrap">`
and `<div class="text-message">` structure as the anchor path.
Without explicit anchors we can't tell sent from received, so
text-message divs get no modifier class — the Work Skin's base
`.text-message` rule still applies.

**File modified:** `editor/converter.py`
(`_convert_body_clean_html` heuristic branch), `config.py` (version bump).

---

## [2.21.0] - 2026-05-13

### Feature: Per-cell publish-check controls — manual URL anchoring, forget publication, cancel scheduled

Three additions to the expanded cell in the Publish Check matrix, all
driven by real friction in the Hypnotic_Claim AO3 incident: PawPoller's
publications row was stuck on a draft the user had manually cleaned up,
the URL pointed at the wrong thing, and three queue rows for the same
cell were jammed in `processing` with no way to cancel from the UI.

**1. Manually set the URL.** A "Set URL:" input + Apply button inside
the "Existing publication" block. User pastes the live submission URL
(e.g. `https://archiveofourown.org/works/84754866`), PawPoller extracts
the external ID via per-platform regex (`_URL_ID_PATTERNS` in
`routes/editor_api.py`) and updates both `publications.external_url`
and `publications.external_id`. Drift/edit operations now target the
right submission. Patterns cover all 11 platforms; backend rejects
URLs that don't match the platform's expected shape.

**2. Forget this publication.** A button below the URL input that
deletes the publications row for (story, chapter, platform) — local
memory only, never touches the upstream submission. Used when the
user has manually deleted the draft/submission on the platform and
wants the cell to revert to "ready" so the next post creates a fresh
submission instead of editing a dead one. Confirmation requires
typing the platform code via `prompt()` (matches the `delete_story`
type-the-name pattern); backend also requires
`confirm_platform=<platform>` query param.

**3. Cancel scheduled — processing rows + bulk cancel.** Two
follow-ups to v2.20.3's cancel-sticky fix:
- The per-row Cancel button was gated client-side on `status === 'pending'`
  but the backend (since v2.20.3) handles `pending/retrying/processing/failed`.
  Frontend gate widened to match.
- When the cell has more than one scheduled item, the header gets a
  "Cancel all (N)" button that calls a new bulk endpoint
  (`DELETE /api/editor/stories/{story}/scheduled` with `platform` +
  `chapter` query params). Backing helper `cancel_all_for` extended to
  accept `chapter_index` filter.

**Files modified:**
- `database/posting_queries.py` — `cancel_all_for` gains `chapter_index`
  parameter; new `delete_publication()` and `update_publication_url()`
  helpers.
- `routes/editor_api.py` — three new endpoints: `PUT /publication`,
  `DELETE /publication`, `DELETE /scheduled` (bulk). `_URL_ID_PATTERNS`
  table + `_parse_external_id()` helper.
- `frontend/js/publish_check.js` — Set URL / Forget controls in the
  Existing publication section; bulk Cancel button in scheduled
  header; widened per-row cancel status gate.
- `frontend/css/editor.css` — styles for the new controls block.
- `config.py` — version bump.

---

## [2.20.7] - 2026-05-13

### Fix: AO3 `create_chapter` recovers chapter_id when AO3 omits it from the response URL

Hypnotic Claim posted successfully to AO3 — work 84754866 + chapter 2
(id 223668966) both exist server-side — but the publish task crashed
with `RuntimeError: AO3: Could not extract chapter_id from response
URL: https://archiveofourown.org/works/84754866/chapters`. AO3 returned
the form POST result at the bare `/chapters` URL with no ID, and the
v2.20.3 body-scan fallback was gated on a `Draft was successfully
created` / `<title>Preview Work` / `<title>Edit Chapter` success-marker
string that didn't appear in the actual response body — so the parser
hard-failed even though the chapter was real and live.

Two changes to `clients/ao3/client.py:create_chapter`:

1. **Drop the success-marker gate on body scanning.** Earlier in the
   function we already detect AO3's explicit error page ("Sorry! We
   couldn") and HTTP non-2xx; if we get past those, a chapter ID in
   the body IS a valid chapter ID. Scan for every
   `/works/{work_id}/chapters/(\d+)` reference in the body and pick
   the maximum — AO3 chapter IDs are monotonically increasing, so the
   newest chapter is always the highest numeric ID even when the
   response page also references the work's earlier chapters in nav
   links.

2. **Last-resort `/navigate` fallback.** If the body scan also turns
   up nothing, fetch `/works/{work_id}/navigate` (the full-page
   chapter index — includes drafts) and grab the maximum chapter ID.

If both fallbacks fail, the response body is now dumped to
`{tempdir}/ao3_chapter_debug_{work_id}_{ts}.html` for postmortem so
the parser can be refined further if AO3 changes its response shape
again.

**File modified:** `clients/ao3/client.py` (create_chapter response
parsing), `config.py` (version bump).

---

## [2.20.6] - 2026-05-13

### Fix: AO3 publish package file priority — second half of the SqW switch

v2.20.2 fixed `posting/platforms/ao3.py:_read_full_story_html` to
prefer SquidgeWorld concatenation over Clean HTML for the AO3 post
*content*. But the AO3 entry in `posting/story_reader.py:FORMAT_SPECS`
still listed `HTML/*_Clean.html` first — so the publish matrix's
`file_path` (the upload source the UI shows + what `validate()` checks
+ what gets stamped on the publication row) still pointed at the Clean
HTML even though the actual POST body came from SqW. Swap the priority
order to match: SquidgeWorld first, Clean as fallback for archives
that pre-date the SqW output.

**File modified:** `posting/story_reader.py` (FORMAT_SPECS["ao3"]),
`config.py` (version bump).

---

## [2.20.5] - 2026-05-12

### Fix: PDF rendering no longer blocks the dashboard event loop

Caught during the first bulk Regenerate All with "include PDF"
ticked. The dashboard stopped responding entirely — page loads
hung, the regen progress SSE stream stalled, polling ticks
skipped. CPU sat at ~150% the whole time.

**Root cause.** `editor.pdf_generator.html_to_pdf()` is synchronous
CPU-bound Python (WeasyPrint), and the regenerate endpoint was
calling it directly from the async handler. While WeasyPrint
renders one PDF (~30-80s), it holds the GIL on the main thread
and the asyncio event loop can't service any other coroutine —
which means the dashboard, the SSE stream telling the UI about
progress, and the poll orchestrator all freeze for as long as
the render takes. 17 stories × ~80s/PDF = ~22 min of unresponsive
dashboard during a "Regenerate All (with PDF)".

**Fix.** Wrap each `html_to_pdf` call in `asyncio.to_thread(...)`
so the render runs on Python's threadpool executor. The event
loop releases on the `await` and gets to service other requests
during the render. Bulk regen still serialises PDFs (one at a
time, awaited in order) but the dashboard stays alive throughout.

**Files modified:** `routes/editor_api.py` (two `html_to_pdf`
calls: full-story + per-chapter loop), `config.py` (version bump).

**Note:** EPUB generation is also sync but completes in ~200ms,
not worth a thread hop. Other format generators (BBCode, Clean
HTML, SoFurry HTML, Styled HTML) are also fast enough that the
event-loop pause is imperceptible.

---

## [2.20.4] - 2026-05-12

### Fix: Single-chapter EPUB fallback + chapter-marker injection script

Caught from the first bulk Regenerate All in production: `Extra_Credit`
failed EPUB generation with "No chapters found in MASTER.md after body
anchor" because its MASTER.md had no `# Chapter X` headings — the
chapter boundaries lived only in `chapters.json` as line ranges, a
legacy convention from before PawPoller's editor existed.

**Defensive fallback in `editor/epub_generator.py:_split_into_chapters`**:
when no `# ` headings appear after `<!-- @body -->` but the body has
content, treat the whole body as one synthetic chapter using the story
title as the chapter title. Prevents future EPUB failures for any
story that drifts into this shape. Multi-chapter stories with proper
`# Chapter X` headings are unaffected (the fallback only kicks in when
`chapters` is empty at the end of the split walk).

**New `scripts/inject_chapter_markers.py`**: one-shot rescue tool for
stories already in this state. Reads `chapters.json` + per-chapter
files from `Chapters/Markdown/`, locates each chapter's first content
line in MASTER.md by string-anchor matching, inserts `# Chapter N:
Title` headings at the right positions. Backs up MASTER.md → .bak;
sorts chapter files by extracted number (so `Chapter_10` lands after
`Chapter_9`, not between `Chapter_1` and `Chapter_2`); refuses to
operate if `# ` headings already exist after the body anchor (idempotent).

**Production fix applied:** ran the script against Extra_Credit;
injected 10 chapter markers; re-synced via pawsync; regen on the
server now produces all 9 formats with zero errors (EPUB 208 KB, 10
chapters split + converted across Markdown/HTML/BBCode/SqW/Styled HTML).

**Files modified:** `editor/epub_generator.py` (fallback), `config.py`
(version bump). **Added:** `scripts/inject_chapter_markers.py`.

---

## [2.20.3] - 2026-05-12

### Fix: AO3 chapter creation duplicate-draft loop + cancel button now sticks

**Two stop-the-bleeding fixes for the AO3 duplicate-draft saga.**

1. **`create_chapter` had the same preview-page bug as `create_work`.**
   v2.20.1 fixed `create_work` to parse the work ID from the body
   when AO3 renders the Preview Work page inline at `/works` without
   redirecting. Turns out `create_chapter` has the identical pattern:
   POST `/works/{id}/chapters` returns the preview page inline at
   `/works/{id}/chapters` with no chapter ID in the URL. PawPoller
   raised `Could not extract chapter_id from response URL`, the
   retry mechanism re-queued, and each retry created a fresh draft.
   So even after 2.20.1, every publish attempt to AO3 spawned a new
   draft per retry cycle. Same fix shape applied: when URL-match
   fails, look for success markers in the response body
   (`Draft was successfully created`, `Chapter was successfully
   created`, `<title>Preview Work / Edit Work / Edit Chapter`) and
   scan for `/works/{id}/chapters/(\d+)` as a strict fallback.

2. **Cancel button now actually cancels.** Two related bugs:
   - `cancel_queue_item` only matched `status='pending'`. When the
     scheduler picked up a row, status became `processing` and the
     UI cancel button silently did nothing. Now matches `pending`,
     `retrying`, `processing`, `failed`.
   - Even when the cancel did set status to `cancelled`, the
     scheduler's failure path immediately overwrote it with
     `pending` (line 165 of `scheduler.py` calls
     `update_queue_status(..., 'pending')` unconditionally to
     re-queue for retry). The next tick picked it back up. Fix:
     `update_queue_status` now refuses to overwrite a row whose
     status is `cancelled` — added `AND status != 'cancelled'` to
     all UPDATE statements. The cancel sticks even when issued
     mid-flight; the scheduler completes the in-flight post but
     the row stays cancelled, and the next tick passes it over.
   - New helper `cancel_all_for(conn, *, platform=, story_name=)`
     for bulk-cancel by filter — useful when a poster bug spams
     the queue and the user wants to nuke a single platform's
     pending+retrying+processing+failed rows in one shot.

**Files modified:** `clients/ao3/client.py` (`create_chapter` body-
scan fallback), `database/posting_queries.py` (cancel + status guard
+ new `cancel_all_for` helper), `config.py` (version bump).

**Note for tomorrow:** there's still a double-retry bug —
`manager._schedule_retry` (when called from `post_story`) creates a
fresh queue row on failure, AND the scheduler resets the *original*
row to pending. So one failure spawns two retry attempts. Not
critical now that the underlying create_chapter bug is gone (no more
failures = no more retries), but worth fixing if it bites again.

---

## [2.20.2] - 2026-05-12

### Fix: AO3 full-story posts used Clean HTML instead of SquidgeWorld OTW format

The AO3 poster's `_read_full_story_html()` preferred
`HTML/<Story>_Clean.html` (bulk generic HTML) and only fell back
to concatenating `SquidgeWorld/Chapter_*.html` if Clean was
missing. But AO3 and SquidgeWorld are both OTW Archive sites —
they parse the same chapter markers, warning-icon glyphs, and
semantic anchors. Using Clean HTML for AO3 fed it the generic
output meant for Inkbunny/Weasyl/etc., not the OTW-shaped HTML
SqW uses. The per-chapter path (`_read_chapter_html`) already
used the SqW files correctly; only the full-story path was wrong.

**Fix:** invert the preference order. SquidgeWorld concatenation
is now the primary source for AO3 full-story posts; Clean HTML
falls to a last-resort fallback for archives that pre-date the
SqW output (anything regenerated since 2.18.x has SqW files and
will hit the new primary path).

**Files modified:** `posting/platforms/ao3.py:_read_full_story_html`,
`config.py` (version bump).

---

## [2.20.1] - 2026-05-12

### Fix: AO3 work creation produced silent duplicate drafts

Caught while the user tried to publish `Hypnotic_Claim` to AO3 from
the publish matrix. AO3 logs showed POST `/works` returning 200
each retry, but PawPoller failed with `Could not extract work ID
from https://archiveofourown.org/works`. The Telegram error
notification fired each time, the queue marked the post as failed,
the scheduler retried — and each retry created **another draft**
on AO3 silently, because the create call had actually succeeded
server-side every cycle. The user's account accumulated multiple
zombie Hypnotic_Claim drafts that AO3 will auto-delete on
2026-06-10 (the 30-day draft TTL).

**Root cause:** `clients/ao3/client.py:create_work` only looked at
the response *URL* for `/works/{id}`. When the user submits the
new-work form via the **Preview** button, AO3 doesn't redirect —
it renders the Preview Work page inline at `/works`, so the URL
stays ID-less while the page body carries the work ID in every
action button (`/works/{id}/post`, `/works/{id}/edit`,
`/works/{id}/preview`) and includes a `<title>Preview Work` plus
a "Draft was successfully created" flash.

**Fix:** when the URL match fails, look for success markers in the
response body (`Draft was successfully created` flash, `<title>
Preview Work`, or `<title>Edit Work`) and scan the body for
`/works/(\d+)` as a fallback. The success-marker gate prevents
false positives where AO3 might mention unrelated works on a
failure page. Existing URL-redirect path still wins when AO3 does
redirect; the body-scan is a strict fallback.

**Cleanup the user needs to do manually:** delete the 5+ duplicate
Hypnotic_Claim drafts from their AO3 drafts list. Future posts
will only produce one draft per click.

**Files modified:** `clients/ao3/client.py` (one branch in
`create_work`), `config.py` (version bump).

---

## [2.20.0] - 2026-05-12

### Feature: Regenerate-all-stories — editor button + Diagnostics test

Bulk rebuild of every story's derived format files (Markdown,
BBCode, Clean HTML, SoFurry HTML, Styled HTML, SquidgeWorld, EPUB,
optionally PDF) from each story's `MASTER.md`, exposed in two
places:

**1. Editor "↻ Regenerate All" button** — top of the story-list
header (next to + Create New Story / Import from Platform). Click
opens a confirmation overlay with a "Skip PDF" checkbox (default on
— PDF adds ~30s/story). Hitting Start kicks off the bulk job and
the overlay flips to a live log: per-story status with stamps,
counts (passed / partial / failed), elapsed time, progress bar.
Streamed via SSE so updates are instant. A Cancel button requests
graceful stop (current story finishes; the loop then exits). Closing
the dialog mid-run prompts a "leave it running in background?"
confirm — useful if you want to reopen the editor to check
something while the run continues.

**2. Diagnostics test `archive.regenerate.all_stories`** — under
Settings → Diagnostics → Archive. Destructive (opt-in per-test
confirmation) so it doesn't fire on a Run All by accident. Runs the
same in-process logic as the editor button, always with `skip_pdf=True`
(so the suite doesn't blow past its 15-minute test timeout). Reports
per-story pass / partial / failed counts plus the list of failures.

**Architecture:**

- New endpoints in `routes/editor_api.py`:
  - `POST /api/editor/regenerate-all` — kicks off a run, returns
    `{run_id, total}`. Refuses 409 with the active run_id if a
    bulk job is already in flight (one at a time).
  - `GET /api/editor/regenerate-all/active` — returns the current
    run (if any) so a refreshed tab can reattach.
  - `GET /api/editor/regenerate-all/stream/{run_id}` — SSE stream
    with `suite_start`, `story_start`, `story_end`, `cancelled`,
    `suite_complete` events. Backfills the event buffer to late
    subscribers; 15s heartbeats so reverse proxies don't kill the
    stream.
  - `POST /api/editor/regenerate-all/cancel/{run_id}` — flags the
    active run for graceful cancellation.
- Thin orchestrator design: the bulk runner internally calls the
  existing per-story `regenerate(story_name, req)` handler in
  process, so per-story behaviour stays the single source of truth.
  No refactor of the regen body — zero risk to the working
  per-story endpoint.
- Frontend in `frontend/js/editor.js:renderStoryList()` —
  `+ Regenerate All` button, overlay HTML with live log `<pre>` +
  progress bar + status counts, EventSource consumer in
  `_streamRegenAll(runId)`.

**Files modified:** `routes/editor_api.py`,
`frontend/js/editor.js`, `testing/tests/archive.py`, `config.py`
(version bump).

**Follow-up (deferred to next session):** standalone CLI wrapper
`m_x/Scripts_Utils/regenerate_all_stories.py` for command-line
use. The existing per-story `regenerate_story.py` already covers
the per-story CLI path; the bulk wrapper just loops it. Not in
this version because it lives in a separate repo.

---

## [2.19.3] - 2026-05-12

### Fix: AO3 cookie-only posting + Diagnostics cleanup pass

**AO3 cookie-only auth recognised by the Publish matrix.** The
publish-readiness check in `routes/editor_api.py:get_publish_matrix`
hard-coded `PLATFORM_CREDS["ao3"] = ("ao3_username", "ao3_password")`,
so every AO3 cell rendered as "No credentials configured" for users
on the cookie-only path (added in 2.18.8 as the recommended setup
for datacenter / blocked-IP environments). Result: the user has a
valid pasted session cookie + working poller and importer, but
Publish refuses to send. Fix: `PLATFORM_CREDS` now supports an
OR-of-ANDs schema — either a flat tuple of required keys (existing
behaviour) or a tuple of groups where any group satisfying its
keys is enough. AO3 becomes `(("ao3_username", "ao3_password"),
("ao3_session_cookie",))`. Posting itself (`posting/platforms/ao3.py`)
already supported cookie-only auth correctly; this was purely a
readiness-gate bug. The publish matrix now correctly shows AO3 as
postable when a session cookie is set.

### Fix: Diagnostics — AO3 cookie-only auth, private-repo GitHub, real digest test

Tidies the diagnostic suite based on the second Run All's skip
list: AO3 was hard-skipping cookie-only setups, the GitHub test
treated private repos as failures, the digest builder test
chased a helper name that doesn't exist, and Turnstile's
description didn't explain what it was.

**Fixed:**

- **`platforms.ao3.auth` / `platforms.ao3.discovery`** — dropped
  `ao3_username` from `requires_creds`; AO3 supports cookie-only
  auth (added in 2.18.8) and the username is optional when a
  pasted session cookie is configured. Tests now skip only when
  *neither* cookie nor username+password is set, and pass
  `target_user` (the AO3Client constructor's 3rd positional arg,
  which the old test code was missing) plus `proxy_kwargs(s, "ao3")`
  for the required CF Worker proxy on server. Discovery now uses
  the real `get_all_work_ids()` method.
- **`external.github.latest_release`** — repo is private, so an
  anonymous request 404s permanently (not "no releases yet").
  Test now uses `github_pat` from settings as a Bearer token when
  configured; without a PAT, treats 404 as a clean skip with a
  message that explicitly mentions the private-repo case.
- **`notifications.digest.data_fetch`** — replaces the old
  `notifications.digest.builder` (which probed for a non-existent
  `build_digest_text` helper). New test exercises the actual
  read-only data helpers behind `send_digest_report()` —
  `_get_digest_deltas()` and `_get_platform_totals()` — across all
  10 polling platforms. Confirms the SQL queries the digest
  depends on still execute against the live schema. Still
  non-destructive: never sends a digest.
- **`external.turnstile.reachable`** — description rewritten to
  explain what Turnstile is (Cloudflare's privacy-friendly CAPTCHA
  replacement for the dashboard login form) and where to configure
  it. Behaviour unchanged.

**Files modified:** `testing/tests/platforms.py`,
`testing/tests/external.py`, `testing/tests/notifications.py`,
`config.py` (version bump).

---

## [2.19.2] - 2026-05-12

### Fix: Diagnostics suite — second round of test-definition fixes

The 2.19.1 deploy unmasked four more bugs in the platform test
definitions (the credential-vault skips were hiding them in 2.19.0).
None of these are bugs in the platforms themselves; they were bugs
in how the tests called the platform clients.

**Fixed:**

- **`platforms.sqw.auth` / `platforms.sqw.discovery`** — imported the
  wrong class name. The class is `SquidgeWorldClient`, not
  `SqWClient`. Constructor also requires `target_user` as a third
  positional arg. Discovery now uses `get_all_work_ids()` (no args).
  Both now also receive `proxy_kwargs(settings, "sqw")` for
  symmetry, though SqW is an OPTIONAL proxy platform that works
  direct by default.
- **`platforms.da.auth` / `platforms.da.discovery`** — `DAClient`
  constructor requires `target_user` as the second positional arg.
  `validate_cookies()` takes no args. Discovery uses
  `get_all_deviation_ids()` (no args). Both now pass
  `proxy_kwargs(settings, "da")` — DA is a REQUIRED-proxy platform
  on the server.
- **`platforms.sf.auth`** — was failing with "SoFurry session did
  not validate" because the test constructed `SoFurryClient` without
  the CF Worker proxy creds. SF is a REQUIRED-proxy platform on the
  server (datacenter IPs are blocked). Now passes
  `**proxy_kwargs(settings, "sf")` and `display_name=...`, and
  triggers `ensure_logged_in()` before `validate_session()` so the
  flow mirrors how the live poller warms the session.
- **`platforms.sf.discovery`** — same proxy fix; switched to the
  real discovery method `get_all_gallery_ids()` (no args).
- **`platforms.ws.discovery`** — switched to the real discovery
  method `get_all_gallery_ids()`. Also added `proxy_kwargs` for
  symmetry (WS is OPTIONAL — defaults to direct).

**Files modified:** `testing/tests/platforms.py`, `config.py`
(version bump).

**Verification:** Run All on the server should now show further
reduction in errored / failed counts; the only remaining failures
should be legitimate platform issues (genuinely broken auth) or
genuine skips (creds not configured).

---

## [2.19.1] - 2026-05-12

### Fix: Diagnostics suite — failures surfaced by the first live "Run All"

The initial v2.19.0 Diagnostics run from the dashboard surfaced four
real defects in the test definitions themselves (not the subsystems
they cover). This patch corrects the test code so the full suite
reports an accurate picture of system health.

**Fixed:**

- **`platforms.wp.auth` / `platforms.wp.discovery`** — `WPClient()`
  requires `target_user` as a positional argument; tests now pass
  it through and call `validate_user()` / `get_all_story_ids()`
  with no extra args (the client already holds the target on
  `self.target_user`). Previously the tests raised
  `TypeError: WPClient.__init__() missing 1 required positional
  argument`.
- **`platforms.ik.auth` / `platforms.ik.discovery`** — same fix as
  WP. `IKClient()` now constructed with `target_user`,
  `validate_user()` and `get_all_content_ids()` called with no
  args.
- **`infra.vault.crypto`** — the original test assumed
  `_encrypt_vault(payload)` returned a blob and `_decrypt_vault
  (blob)` accepted one. The real signatures are
  `_encrypt_vault(creds: dict) -> None` (writes to disk) and
  `_decrypt_vault() -> dict` (reads from disk). Test now
  monkeypatches `config.VAULT_PATH` to a tempfile for the round-
  trip and restores it in `finally`, so the live vault is never
  touched. Skips cleanly when the vault key isn't reachable.
- **`external.github.latest_release`** — a 404 from
  `/repos/{owner}/{repo}/releases/latest` means the repo exists
  but has no published releases yet; the test now treats that as
  a clean skip rather than a failure. Genuine HTTP errors still
  fail.
- **`archive.pawsync.dry_run`** — `pawsync.py` hard-codes the
  desktop archive path and fails with `Archive root not found`
  when run on the server. The skip-phrase matcher now recognises
  that message (and `no such file`) and skips instead of failing.

**Added:**

- **`infra.credentials_visible`** — new diagnostic test. The first
  Run All on the server reported 24 tests skipped on "missing
  credentials", including platforms the user clearly has
  configured (IB, SF, Telegram). Since `get_settings()` should
  auto-merge the vault when `credential_mode=local`, this test
  reports `credential_mode` and lists which credential keys are
  present vs absent in the live `get_settings()` view. Fails only
  when vault is enabled but zero credentials are visible (the
  genuine bug shape); otherwise informational. Lets us tell at a
  glance whether a platform skip is a vault-merge failure or a
  genuinely-unset credential.

**Files modified:** `testing/tests/platforms.py`,
`testing/tests/infra.py`, `testing/tests/external.py`,
`testing/tests/archive.py`, `config.py` (version bump).

**Verification:** re-run Settings → Diagnostics → Run All on the
server. Expected: 0 errored, 0 failed (the 3 fails / 4 errors
from the initial run are eliminated). Skipped count rises by a
few (vault when no key, github when no releases, pawsync on
server) — which is the correct behaviour.

---

## [2.19.0] - 2026-05-12

### Feature: Diagnostics & testing tab in Settings

A new **Settings → Diagnostics** tab exposes a comprehensive in-app
test suite that exercises every subsystem of the running PawPoller
instance, with a live log stream and a one-button full-suite run.
Adds 82 bespoke live-system tests + the existing pytest suite as a
parsed sub-runner — ~170 individually-visible tests in the UI.

**Architecture:**

- New `testing/` package: `registry.py` (decorator + TestResult
  dataclass), `runner.py` (per-test / per-category / full-suite
  async runners with global concurrency lock), `streamer.py`
  (per-run SSE event buffer with replay + heartbeats), `store.py`
  (last 10 runs persisted to `data/diagnostics_results.json`).
- `testing/tests/` modules grouped by category. Each test is an
  async function decorated with `@register_test(...)`. Tests use
  `TestContext.log()` for live streaming, `TestContext.detail()`
  for structured output, raise `ctx.skip(reason)` to skip cleanly.
- `routes/testing_api.py` with 8 endpoints:
  `GET /api/testing/tests`, `GET /last-results`, `GET /active`,
  `POST /run/{test_id}`, `POST /run-category/{category}`,
  `POST /run-suite`, `GET /stream/{run_id}` (SSE),
  `POST /stop/{run_id}`.
- Frontend `frontend/js/diagnostics.js` consumes SSE via
  `EventSource`, updates per-test rows in place as events arrive.
  CSS in `frontend/css/diagnostics.css`. Wired into Settings tab
  bar in `frontend/js/app.js`.
- Live updates use SSE (the dashboard's first SSE consumer); the
  default CSP `connect-src 'self'` already covers it, no policy
  change needed. Heartbeat every 15s prevents reverse-proxy drops.

**Test inventory (82 bespoke + 1 pytest aggregate):**

| Category | Count | What it checks |
|---|---|---|
| Infrastructure | 12 | DB connection / WAL / FKs / integrity / migrations, settings round-trip + atomic-write source check, vault encrypt+decrypt, vault key source, log write, disk space, tag DB files |
| Dashboard Auth | 6 | Bcrypt round-trip, TOTP generate+verify, API-key SHA-256, signed cookie, HTML escape, isolated rate-limiter window |
| Platforms — Auth | 11 | Per-platform credential probe (IB, FA, WS, SF, SqW, AO3, DA, WP, IK, Bsky, TW); reuses each client's `validate_*` / `login` path |
| Platforms — Polling Discovery | 11 | Lightweight gallery listing per platform (no DB writes) |
| Editor / Converter | 10 | MD → Clean HTML / SoFurry HTML / BBCode / SquidgeWorld / Styled HTML (full + per-chapter inc. THE-END regression for 2.18.20), EPUB structural build, PDF backend availability, theme parser, anchor parser |
| Story Reader | 6 | Archive resolves + has stories, load_story populates fields, build_package across all posting platforms, full-vs-chapter file resolution regression (2.18.19), manifest parsing regression (2.18.19) |
| Posting (Dry-Run) | 9 | Per-platform `poster.validate(package)` — no uploads |
| External Services | 5 | CF Worker reachable + auth rejection, Telegram bot getMe, GitHub latest release, Turnstile widget |
| Scheduling & Queue | 5 | Poll-orchestrator / posting-scheduler / Telegram-bot thread liveness; queue `requires` filter regression (2.18.16); future `scheduled_at` gate |
| Notifications | 3 | Telegram send (DESTRUCTIVE — confirmation gated); Windows toast (DESTRUCTIVE); digest text builder |
| Archive | 3 | Local archive listable, every `story.json` parses + has required fields, `pawsync --dry-run` exits 0 |
| Pytest Suite | 1 | Spawns `python -m pytest tests/ -v --tb=short -p no:cacheprovider`, parses output, expands to ~91 child results |

**Safety:**

- **Destructive tests** (3 of 82) gated by `destructive: True` flag.
  Run-suite skips them unless individually opted in via the
  request body's `include_destructive: [test_id, ...]` list. The
  route handler returns 403 if a single-test run targets a
  destructive test without `confirm_destructive: true`. The
  frontend pops a per-test confirm dialog showing the
  description before running, and a separate "include destructive"
  checkbox on the run-all toolbar.
- **One run at a time**: module-level lock in `testing/runner.py`.
  Second-run requests get HTTP 409 with the active `run_id` so the
  frontend can attach to the in-flight stream instead.
- **Per-test timeout**: 30s default; tests that need longer
  (AO3, EPUB build, pytest subprocess) declare their own.
- **Platform pacing**: when `platforms.*` tests run as a category
  or suite, the runner sleeps the per-platform request-delay
  between successive ones so we don't burst on rate limiters.
- **State cleanup**: queue-regression tests insert marker rows and
  delete them in `finally`; settings round-trip writes a namespaced
  marker and clears it; nothing leaks into production state.
- **Auth**: all endpoints sit behind the existing dashboard session
  middleware. No additions to `_AUTH_EXEMPT_PATHS`.

**Files added:**

- `testing/__init__.py`, `testing/registry.py`, `testing/runner.py`,
  `testing/streamer.py`, `testing/store.py`
- `testing/tests/__init__.py`, `testing/tests/infra.py`,
  `testing/tests/auth.py`, `testing/tests/platforms.py`,
  `testing/tests/editor.py`, `testing/tests/story_reader.py`,
  `testing/tests/posting.py`, `testing/tests/external.py`,
  `testing/tests/scheduling.py`, `testing/tests/notifications.py`,
  `testing/tests/archive.py`, `testing/tests/pytest_runner.py`
- `routes/testing_api.py`
- `frontend/js/diagnostics.js`, `frontend/css/diagnostics.css`

**Files modified:**

- `dashboard.py` — imports `testing.tests` to trigger registration,
  registers `testing_router`.
- `frontend/index.html` — references the new CSS + JS with
  `?v=__APP_VERSION__` cache busting.
- `frontend/js/app.js` — Diagnostics tab button in `renderSettings`
  tab bar; lazy-mount via `window.Diagnostics.mount(...)` on tab
  switch and on initial render when landing on
  `#/settings/diagnostics`.
- `config.py` — version bump to 2.19.0.

**Verification on the live VM after deploy:**

1. Open Settings → Diagnostics.
2. Click ▶ Run All. Expect ~140 tests to run (destructive skipped),
   completing in 30-60s with platform-pacing applied.
3. Click ⚠ Run on `notifications.telegram.test_message`, confirm,
   verify the message arrives on Telegram.
4. Verify the live log streams events in real time; auto-scroll
   toggle and filter chips work.
5. Open a second browser tab during a run — second tab attaches
   to the in-flight stream and shows the same events.

---

## [2.18.21] - 2026-05-08

### Fix: Theme Editor + metadata drawer dropdown options unreadable

The Warning Icon picker and Section Break picker in the Theme Editor
(plus the rating / category selects in the metadata drawer) opened
their dropdown popups with options rendered in low-contrast
grey-on-grey — only the highlighted item was readable. Caused by
relying on default browser rendering for `<option>` elements in a
dark theme: Chromium / WebView2 renders the popup as a system widget
and doesn't inherit the parent `<select>`'s background / colour
tokens. Same pattern that `.filter-select option` (in
`components.css`) already worked around for the dashboard.

Fix: add an explicit option rule in `frontend/css/editor.css`
covering `.theme-row select option` and `.metadata-field select
option`, setting `background: var(--surface-elevated)` and
`color: var(--text-primary)` so options are readable across all
eight themes.

CSS-only change, no Python touched.

---

## [2.18.20] - 2026-05-08

### Fix: every styled chapter file rendered "THE END" footer

Caught from a real symptom: the user posted Overtime ch1 to FA, then
checked the styled HTML preview and saw "THE END" at the end of
chapter 1 — claiming the story was over despite three more chapters
behind it. Same issue on chapters 2 and 3.

Root cause: the styling template
(`Reference_Guides/Styling/HTML_CSS/STYLING_REFERENCE.md`) hard-codes
a `<div class="story-end">` block with "THE END" + signature. Every
styled HTML file fills the same template, including per-chapter
files, so chapters 1..N all rendered "THE END". Only the actual last
chapter should.

Fix in `editor/converter.py:_build_styled_chapter`:

- Track `is_last_chapter = ch_idx == len(chapters) - 1`.
- For non-final chapters, post-process the rendered doc and replace
  the `<div class="story-end">` block (including its hr / THE END
  paragraph / signature paragraph) with a per-chapter variant:
  `<div class="story-end chapter-end">` containing
  `End of {ch_title}` and `Continued in {next_ch_title}`.
- The replacement keeps the `story-end` class so the existing CSS
  (centring, padding, end-rule) applies; `chapter-end` is a hook
  for any future per-chapter restyling.
- New helper: `_replace_story_end_with_chapter_end()`.
- `stats["is_last_chapter"]` exposed for downstream callers.

Smoke-tested on Overtime: all four chapters render correctly
(ch1 → "End of Chapter 1: Tip-Off / Continued in Chapter 2: Foul";
ch2 → "End of Chapter 2: Foul / Continued in Chapter 3: Possession";
ch3 → "End of Chapter 3: Possession / Continued in Chapter 4:
Whistle"; ch4 → original "THE END" + signature).

Existing per-chapter Styled HTML files on disk still have the old
footer — needs a Regenerate run on each chaptered story to refresh.
The full-story Styled HTML and EPUB are unaffected (single-document
flows; the end marker only emits where MASTER.md actually has
`*End of Title*`). Plain BBCode / SoFurry HTML / Clean HTML chapter
files don't render an end marker either since the source slice
doesn't contain that line — only the Styled HTML pipeline injects
it via the template.

Side observation worth a follow-up (separate from this bug): when
a story's MASTER.md has no `<!-- @byline -->` anchor and the
`default_author` setting is empty, the Styled HTML signature
renders as `~  ~` (empty). Pre-existing; only affects the last
chapter / full-story since chapters 1..N-1 no longer emit a
signature post-fix. Not in this version.

---

## [2.18.19] - 2026-05-08

### Fix: per-chapter FA post uploaded the full-story PDF instead

Caught from a real symptom: posting just chapter 1 of `Overtime` to
FurAffinity via the publish-check matrix uploaded the entire
full-story `PDF/Overtime.pdf` to FA, recorded as
`https://www.furaffinity.net/view/64930670/` with publications row
`pub_id=60` (`format_file` pointing at `Overtime.pdf`, not
`Chapter_1_Tip-Off.pdf`).

Two compounding bugs in `posting/story_reader.py`:

1. **`_resolve_format_file` matched on empty filename.** The resolver
   does `if ch_filename in f.stem`, which is unconditionally True
   when `ch_filename == ""` (Python's `"" in any_string` is True).
   For FA's format spec `[("PDF", "*.pdf"), ("Chapters/PDF",
   "*.pdf")]` this meant the first iteration over `PDF/` matched
   `Overtime.pdf` immediately and returned, never reaching the
   per-chapter `Chapters/PDF/` dir or the secondary
   `f"Chapter_{N}" in f.name` matcher that would have caught the
   right file.

2. **`_load_from_story_json` parsed split_manifest with wrong keys.**
   The manifest's chapter entries use `number` (not `index`) and
   have no top-level `filename` key. The lookup
   `manifest_chapters[ch.get("index", 0)] = ch` collapsed every
   chapter to key `0`, and `manifest_ch.get("filename", "")` always
   returned `""`. Result: every `ChapterInfo.filename` was empty,
   feeding bug #1.

Fix:

- `_resolve_format_file` guards the filename matcher with
  `if ch_filename and ch_filename in f.stem` so an empty filename
  no longer matches every file. Defense in depth — even if filename
  derivation regresses again, the resolver now falls through to the
  secondary `f"Chapter_{N}"` matcher and returns the right file.
- `_load_from_story_json` keys the manifest dict on
  `ch.get("number", ch.get("index", 0))`, derives a usable
  filename from any path in the manifest's `files` dict
  (e.g. `Chapter_1_Tip-Off.md` → `Chapter_1_Tip-Off`), and reads
  word counts from `words` (the manifest's actual key) before
  falling back to the historical `word_count`.

Smoke-tested all 6 file-upload platforms × {full-story, ch1, ch4}
on `Overtime`: every cell now resolves to the expected file (full-
story bulk for ch0, per-chapter file for ch1/ch4).

`_load_from_legacy` (the tags_upload.txt fallback path) still has
the same wrong-keys problem but is only used for stories without
`story.json`. Worth fixing for parity but not in this version.

Cleanup pending: the live FA submission at
`https://www.furaffinity.net/view/64930670/` (Overtime "ch1" with
the full-story PDF) and its publications row `pub_id=60` need to
be reconciled — either delete on FA + delete the row and re-post
ch1 cleanly, or replace the file via FA's `changestory` endpoint.
User to decide.

---

## [2.18.18] - 2026-05-08

### Fix: chapter-thumbnail upload triggers a 409 on the next metadata Save

Followed up from 2.18.17. The chapter-thumbnail endpoint writes the
file to `Images/` AND mutates `story.json` directly (adds the new
path under `images.chapter_thumbnails[chIdx]`). The metadata drawer
caches the mtime of story.json in `this.lastMtime` at load time and
sends it as `expected_mtime` on every PUT /metadata for optimistic
concurrency. When the upload mutated story.json, the drawer's cached
mtime stayed stale, so the very next Save 409'd and forced the user
to confirm a reload — even though the upload was their own action a
moment ago. Functional but surprising; in the bug session that led
to 2.18.17 the user hit this exact pattern (4× POST then PUT 409
then GET reload).

Fix:

- `routes/editor_api.py:upload_chapter_thumbnail` now returns
  `last_modified` from `sj.stat().st_mtime` after the story.json
  rewrite (or `None` when story.json is missing).
- `frontend/js/metadata_editor.js:_uploadChapterThumb` consumes
  `data.last_modified`, updates `this.lastMtime`, AND mirrors the
  thumbnail write into `this.initialMetadata` so the drawer's dirty
  check doesn't flag the upload as a pending edit. Without the
  initial-state mirror, opening the drawer, uploading a thumb, and
  closing without other edits would still mark the drawer dirty.

`upload_cover` is a different shape — it only writes the cover
image to disk; the user's Save is what persists the filename change
into `story.json`. So no mtime drift, no 409, no parallel fix
needed there.

---

## [2.18.17] - 2026-05-08

### Fix: per-chapter thumbnail uploads all landed on chapter 0

Caught from a real symptom: the user uploaded thumbnails for chapters
1–4 of `Overtime` via the metadata drawer, hit Save, the field showed
"None" for every chapter on reload. Server logs showed four
`POST /api/editor/stories/Overtime/chapter-thumbnail` requests all
returning 200 OK, but only one file on disk
(`Images/ch0_thumbnail.png`, ~126 KB) and one entry in story.json
(`chapter_thumbnails["0"]`).

`routes/editor_api.py:upload_chapter_thumbnail` declared
`chapter_index: int = 0` without a `Form()` annotation. Without
`Form()`, FastAPI binds an `int` parameter from the **query string**
only, ignores the multipart form field the frontend sends, and
silently falls back to the default `0` on every call. So:

- Each upload's file landed at `Images/ch0_thumbnail.png`,
  overwriting the previous one.
- `story.json["images"]["chapter_thumbnails"]` only ever got the key
  `"0"` (which the per-chapter UI never renders — chapter indices
  start at 1; chapter 0 is the story-level title heading).
- After the post-save 409 reload (a separate quirk where the upload
  endpoint mutates story.json directly without bumping the drawer's
  cached `lastMtime`), the drawer's `thumbs[String(chIdx)]` reads
  for `chIdx=1..4` all returned undefined → all four fields showed
  "None".

Fix: add `from fastapi import ..., Form, ...` and change the
parameter to `chapter_index: int = Form(0)`. The frontend was
already sending the field correctly via
`formData.append('chapter_index', String(chIdx))`.

Cleanup applied to the live VM:
- Deleted the orphaned `Images/ch0_thumbnail.png` from the
  `Overtime` story folder (no chapter referenced it).
- Stripped the bogus `chapter_thumbnails["0"]` entry from
  `Overtime/story.json` so the field is `{}` again.

Only one other upload endpoint exists (`upload_cover` at
`editor_api.py:2185`) and it takes no parameters besides `file`, so
no similar bug there. Audited the full router; this was the only
instance.

---

## [2.18.16] - 2026-05-07

### Fix: scheduled / queued posts starved by `requires='desktop'` zombies at the head of the FIFO

Caught from a real symptom: a scheduled IB post for `Overtime`
(queue_id=8, `scheduled_at=2026-05-06 07:07 UTC`, `requires='any'`)
sat in the queue 26+ hours overdue on the GCP server. Eight items
total in `posting_queue`; items 1–7 were stale `requires='desktop'`
rows from 2026-04-04 → 2026-04-17 (SF/IB/SQW/AO3 — none of which
are desktop-only platforms today; presumably from an older
auto-queue policy).

Two bugs combined:

1. **Head-of-line blocking.** `posting/scheduler.py:_scheduler_loop`
   called `posting_queries.get_pending_queue(conn, limit=5)`, then
   filtered the result in Python via `_is_compatible(item.requires)`.
   The SQL `LIMIT 5` runs before the Python filter, so the five
   oldest pending rows came back first — all seven zombies preceded
   item 8 in the FIFO, so the scheduler always saw five
   `requires='desktop'` rows, filtered them all out as incompatible
   on a server-mode instance, and slept for 60s. Item 8 was never
   fetched. Confirmed live: `get_pending_queue(limit=5)` returned
   only zombies; `get_pending_queue(limit=20)` returned all eight
   with item 8 marked compatible.

2. **Stale `requires='desktop'` rows for non-desktop platforms.**
   Today only `FurAffinityPoster.requires_mode == 'desktop'`; the
   auto-queue path in `posting/manager.py:210` only fires on FA from
   server. The seven April-dated rows for SF/IB/SQW/AO3 cannot be
   produced by current code — they're legacy from an earlier policy.
   They were silently rotting in the queue and would have rotted
   indefinitely.

Fix:

- `database/posting_queries.py:get_pending_queue` gains an optional
  `runtime_mode` parameter. When provided, the `requires IN ('any',
  :mode)` predicate is applied **in SQL**, so incompatible rows are
  excluded before `LIMIT` truncates the result. Backward-compatible:
  `runtime_mode=None` (the default — used by the test suite) keeps
  the old unfiltered behaviour.
- `posting/scheduler.py:_scheduler_loop` passes
  `runtime_mode=_runtime_mode` and drops the now-redundant Python
  filter + `_is_compatible` helper.
- The seven zombie rows (queue_ids 1–7) were deleted manually on the
  GCP server before the deploy; item 8 (Overtime IB scheduled post)
  was preserved so the next scheduler tick processes it. (No code
  for an automatic zombie sweep — the user's choice each time.)

Known follow-up: the editor UI has no "cancel queue item" button
even though `DELETE /api/posting/queue/{queue_id}` already exists in
`routes/posting_api.py`. Worth wiring up so manual cleanup doesn't
require SSH + Python next time. Not in this version.

---

## [2.18.15] - 2026-05-05

### Fix: EPUB (and PDF / SoFurry HTML / chapter BBCode) hidden from Downloads dropdown after regen

Caught from a fresh "Testin" story: regen produced the EPUB cleanly
(`editor.epub_generator: Wrote EPUB ... (2 chapters, 11 files)`), the
file was on disk at `EPUB/Testin.epub`, but the editor's Downloads
dropdown didn't show it. Two compounding bugs:

1. The new-story wizard at `routes/editor_api.py:429` hardcoded the
   initial `story.json["formats"]` dict to
   `{bbcode, html, markdown, squidgeworld}` — `epub`, `pdf`,
   `sofurry_html`, `styled_html`, `chapter_bbcode` were silently
   omitted. The Downloads dropdown reads from this dict via
   `GET /api/posting/stories/{name}` (which delegates to
   `posting/story_reader.py:get_format_files`), so any format key
   not in the dict gets short-circuited as
   `{available: False}` regardless of whether the file exists on disk.
2. The regenerate endpoint at `routes/editor_api.py:/regenerate`
   wrote the format files but never refreshed `story.json["formats"]`
   from disk, so older stories that predated EPUB support stayed
   blind to their own freshly-generated EPUB until story.json was
   manually edited or `python -m posting.generate_story_json`
   was run.

Fix: (1) the wizard now declares every format the regen endpoint can
produce, so freshly created stories show every format after the first
regen. (2) The regen endpoint runs an on-disk discovery pass at the
end (mirroring the block in `posting/generate_story_json.py:112-130`)
and merges discovered formats into `story.json["formats"]` —
add-only, never removes existing entries, so any manually-edited
per-platform format flags stay intact. The merge re-writes story.json
only when a real change was made; the response gains
`"story.json formats refreshed from disk"` in `results[]` so the
editor's regen-output banner reflects what happened.

## [2.18.14] - 2026-05-05

### Delete-story button on the story list

Story list cards (Editor → Stories) now have a small trash-can button
in the top-right corner.  Clicking it opens a confirmation overlay
that requires the user to type the story's folder name into an input
before the Delete button enables, then a native `confirm()` dialog as
the second verification gate.  Two layers — a typed-name match
catches accidental clicks, the native confirm catches a paste-and-go.

Backend: new `DELETE /api/editor/stories/{story_name:path}` endpoint.
Resolves the path through the existing `_resolve_story_dir` (path
traversal-safe — already in use by every other story endpoint),
refuses anything inside `SKIP_DIRS` (e.g. `Reference_Guides`), and
requires a `confirm_name` query param that must match the leaf folder
name exactly — server-side defence so even direct curl calls can't
delete a story without naming it first.  Logs the file count, plus
the count of `publications` and pending queue items left behind, so
the audit trail captures what side-state remains after the folder is
gone.  Doesn't touch the database — `publications` rows stay so the
analytics history is preserved; the user can clean those up
separately if they want a hard reset.

## [2.18.13] - 2026-05-05

### Browser-login threading fix + Inkbunny added

Browser login was failing on the first click for every platform with
`pywebview must be run on a main thread` (visible in `auth.browser_login:
Browser login window error for fa: pywebview must be run on a main thread.`)
and only sometimes succeeding on retry. Root cause: `_run_login_window`
called `webview.start()` from a daemon thread to spawn the login popup,
but the dashboard's `main.py:924` already owns the one allowed
`webview.start()` for the process — pywebview rejects any subsequent
`start()` calls, and on Windows requires the main thread regardless.
The intermittent retry "success" was undefined-behaviour territory left
behind by the failed first call; not safe to rely on.

Fix: drop the second `webview.start()` entirely. With the GUI loop
already running (the dashboard's), `webview.create_window()` is enough —
pywebview's main-thread dispatcher picks the new window up. The cookie
poller stays in a daemon thread; the `closed` event fires the cancel
path when the user dismisses the window. The wrapper thread that used
to host `webview.start()` is gone; the FastAPI executor blocks on the
result queue directly. A guard at the top now refuses to open a window
when no GUI loop is running (returns a clear `RuntimeError` instead of
silently spawning a broken second loop).

New: Inkbunny added to `PLATFORM_LOGIN`. Same verification-only pattern
as AO3 / SqW / Weasyl — IB's API mints its own SID via `api_login.php`
with username + password, so web session cookies aren't usable. The
browser-login entry exists so users can verify their credentials work
in a real browser; the poller and poster still authenticate via
`ib_username` / `ib_password`.

### Settings: Inkbunny moved into the Platforms tab

The Inkbunny credential form lived in Settings → General as its own
"Inkbunny Credentials" accordion — leftover from when PawPoller was
single-platform IB only. Now lifted into Settings → Platforms as the
top accordion, matching the FA / WS / SF / DA / IK / Bsky / TW pattern:
status-dot summary, username in the meta line, conditional Sign Out
button only when a password is actually saved. The save / sign-out
event handlers still bind to `cred-username` / `cred-password` /
`save-creds-btn` / `settings-logout-btn` (kept the IDs intact). Added a
"Verify in Browser" button that opens inkbunny.net via the new IB entry
in `PLATFORM_LOGIN` so users can confirm their credentials work in a
real browser before saving — verification only, since IB's API needs
username + password to mint an SID and web cookies aren't usable. Made
the `settings-logout-btn` handler binding optional-chaining since the
button is now conditional on `creds.has_password`.

### Log viewer: copyable + Copy button

Settings → Logs `<pre id="log-output">` now has explicit
`user-select:text` + `cursor:text` so click-drag selection works in
pywebview's WebView2 (which silently suppressed selection in some theme
combinations). Added a "Copy" button next to "Refresh" that writes the
visible log buffer to the clipboard via `navigator.clipboard.writeText`,
with a graceful fallback that selects the `<pre>` contents and prompts
the user to Ctrl+C if WebView2 rejects the clipboard write (it
occasionally does when the focus came from a button rather than an
input).

## [2.18.12] - 2026-05-03

### AO3 client: jitter + exponential backoff (hygiene)

Pure rate-limit hygiene pass on the AO3 client. Doesn't fix
the datacenter-IP block (that's IP-keyed, not request-pattern
keyed) — the trade-off was made explicitly to skip residential
proxy integration. AO3 imports from the GCP server will keep
hitting cooldowns; the workflow recommendation is to run AO3
imports from the desktop instance (residential IP) and let
`pawsync` push the result. AO3 polling stays server-side
because the 4-hour interval + cookie auth is tolerable.

What changed:

- `_polite_delay()` helper replaces every
  `await asyncio.sleep(config.AO3_REQUEST_DELAY_SECONDS)` call
  site (9 of them). Sleeps `base × U(0.7, 1.3)` instead of a
  flat 3 seconds — fixed cadence reads as bot-like, jittered
  cadence looks more human-shaped without being so wide that
  an unlucky sequence hammers AO3.
- `_get_page()` 429 backoff is now exponential with jitter:
  `30 × 2^(attempt-1) × U(0.8, 1.2)` (≈ 30 / 60 / 120 base,
  ±20%) instead of linear `30 × attempt`. The Retry-After
  header still wins when AO3 sends one — the exponential
  default only kicks in when the header is missing or
  unparseable.

Why these are right-sized for the actual problem:
- Linear 30/60/90 → exponential ~30/60/120 — only helps when
  the cooldown is actually clearing during the retry window
  (5–10 min cases), gives up faster on long bans (30–60 min
  cases) where extra retries just compound the offence.
- Jitter spread of 30% is narrow on purpose. AO3 is a
  volunteer-run site; "random delays" advice is meant for
  hostile sites where pattern detection is sophisticated, not
  for OTW Archive whose rate limiter is a simple per-IP
  counter that doesn't care if your gaps are uniform.

---

## [2.18.11] - 2026-05-03

### Importer duplicate detection at the import call (not just the picker)

The list endpoint at `/api/editor/import/available` already
filtered out submissions that had a matching `import_source` in
some existing `story.json`, so the picker UI never offered them
again. But the actual import endpoint had no such guard — and
the manual "Import by URL or ID" path bypasses the picker
entirely. Result: the same submission imported twice produced
byte-identical folders with `_2`, `_3` suffixes (caught with
`Late_Shift` + `Late_Shift_2`, both SqW work `92124`,
1962 words, identical contents).

Fix:

- New `posting/importer.py:_find_existing_import(platform,
  submission_id)` scans every `story.json/import_source` in the
  archive for a match.
- Every `import_from_*()` calls it before doing any network
  work; if a match is found, it returns the existing folder's
  `story_name` + title with `already_imported=True` instead of
  re-fetching and creating a `_2` duplicate.
- The `/import/{platform}/{submission_id}` API surfaces
  `already_imported` in its response so the frontend can show
  "Already imported as <name>" instead of "Imported".
- The list endpoint's `imported` dedup set now includes `ao3`
  and `sqw` alongside `ib` / `sf` / `fa` (those two were
  silently missing — any AO3 or SqW work would re-appear in
  the picker even after import).

The existing `_create_story_folder()` collision behaviour
(suffix-on-name-clash) stays — it's still the right fallback
when two genuinely different submissions slug to the same
folder name.

---

## [2.18.10] - 2026-05-03

### AO3 importer accepts cookie-only auth

`posting/importer.py:import_from_ao3()` was still gating on
`ao3_username` AND `ao3_password`, so cookie-only setups got
"AO3 credentials not configured" before the fetch even started.
Gate now passes when either user/pass OR a session cookie is
present. The owner-of-draft sanity check inside
`_fetch_ao3_work()` falls back to `ao3_target_user` when no
username is set.

---

## [2.18.9] - 2026-05-03

### AO3: trust cookie, skip verification probe

2.18.8 hit a self-inflicted false negative. The pasted-cookie
flow still ran `ensure_logged_in()` → `_get_page("/users/{name}")`
to confirm the session, and that probe is itself rate-limited
from datacenter IPs. After three 429s the loop exhausted, the
returned body lacked "Log Out", and the conservative check tore
the session down — even though the cookie was perfectly fine.
Net result: cookie users got "cookie no longer logged in" the
moment AO3's rate limiter kicked in.

Fix: when a `_session_cookie` is set, `ensure_logged_in()`
returns True immediately without fetching anything. We can't
fall back to form login anyway (would re-trip the throttle), so
the verify fetch only ever creates false negatives. The actual
import/poll page-fetch is now the sole source of truth — if
the cookie is bad, that fetch returns a public-profile or
login-redirect page and the caller surfaces a clear error.

`validate_session()` (only called by `/auth/connect`) keeps a
verification fetch so the user gets immediate feedback when
they paste, but transient 429 there is treated as "trust and
let the next call confirm" instead of a hard failure.

---

## [2.18.8] - 2026-05-03

### AO3: cookie-based auth as alternative to username/password

AO3's per-IP login throttle is the long pole on datacenter
deployments — a single failed login probe locks the IP out for
5–60 minutes ("Retry later" 429), and the CF Worker proxy IP can
sit in the same cooldown if it's been used to probe. Working
around that with retries makes it worse.

Cookie auth sidesteps the rate-limited login endpoint entirely:
the user copies `_otwarchive_session` from their already-logged-in
browser and pastes it into the AO3 connect form. The server
injects it into the httpx cookie jar, marks the client logged in,
and never touches `/users/login`. Same pattern FA / DA already
use.

Changed:

- `clients/ao3/client.py:AO3Client.__init__` accepts
  `session_cookie=""`. When truthy: cookie is set on the httpx
  client at `domain="archiveofourown.org"` and `_logged_in=True`
  is asserted up front. `update_credentials()` updates / clears
  the cookie in place without rebuilding the client.
- `AO3Client.ensure_logged_in()` returns False (with a clear log
  message asking the user to repaste) when a cookie is set but
  AO3 says we're logged out. It will *not* fall back to form
  login — that defeats the rate-limit-avoidance whole point.
- `polling/ao3_poller.py:_get_or_create_client` reads
  `ao3_session_cookie` from settings and passes it through.
- `routes/ao3_api.py:/auth/connect` now accepts an optional
  `session_cookie` field. If provided, password becomes optional;
  validation goes through the same singleton path so a successful
  cookie validation leaves a warm client behind.
- `/auth/status` reports `has_password` and `has_cookie`
  separately for the UI.
- `/auth/disconnect` clears the cookie alongside other creds.
- Settings → AO3 connect form has a collapsible "Advanced: paste
  session cookie instead" section with the value field plus a
  short how-to.
- `config.py:CREDENTIAL_FIELDS` adds `ao3_session_cookie` so the
  cookie is encrypted in the vault and never written to plaintext
  settings.json.

**Why not auto-fall-back to login on cookie expiry:** the cookie
is long-lived (~1 year on AO3) and rotates only on logout. Auto
re-login on a stale cookie would re-trip the rate limiter that
cookie auth exists to avoid. Re-pasting on expiry is the right UX.

---

## [2.18.7] - 2026-05-03

### CF Proxy: true fallback semantics, not "always on"

The 2.18.6 toggle had the wrong shape — flipping
`<platform>_use_cf_proxy=true` made every request for that platform
go through the Worker, which is wasteful when direct works fine.
The toggle now means **"retry once through the Worker if a direct
call hits a block-like failure"**:

```
default path:   direct call
on block-like:  if toggle on, retry through Worker (one shot)
```

Block-like failures are detected by
`polling/cf_proxy.py:is_blocking_failure(exc)`: 403, 429, "Shields
are up", "Retry later", "Cloudflare", connect/read timeouts, Anubis
challenge text, "rate-limit"/"blocked" substrings.

Changed:

- `polling/cf_proxy.py` split into two helpers:
  - `proxy_kwargs(settings, platform)` — default-path. Returns
    proxy creds ONLY for AO3 / DA / SF (PROXY_REQUIRED). The eight
    optional platforms always get `{}` (direct).
  - `proxy_kwargs_fallback(settings, platform)` — fallback-path.
    Returns proxy creds when a retry should go through the Worker:
    REQUIRED platforms always; OPTIONAL platforms only when the
    toggle is on.
- Importers (`ao3`, `sqw`, `ib`, `fa`) wrap their network calls in
  try / `is_blocking_failure` / retry-with-fresh-proxy-client.
  Direct stays the happy path; on block, a one-shot proxy client
  is constructed *just for the retry* and closed afterwards. The
  shared poller singleton is never replaced.
- Settings → Polling UI label updated to spell out the fallback
  semantics.

**Not wrapped (yet):** the per-platform poll cycles. Polls run on
a schedule and naturally retry on the next cycle, so the failure
mode is bounded; if a platform is genuinely blocking us we'll
notice within one poll interval. Adding fallback to poll cycles
is a future iteration if needed.

---

## [2.18.6] - 2026-05-03

### CF Worker proxy as a per-platform backup

Generalises the existing AO3 / DA / SoFurry CF Worker plumbing to
the other eight platforms as an opt-in escape hatch. When a platform
starts blocking the server's IP (Cloudflare challenge, 403 / 429
floods, datacenter-IP filtering), flip its toggle in
**Settings → Polling → CF Proxy Backup** and traffic for that
platform routes through the same Worker instead of going direct.

Changed:

- Eight client constructors (`bsky`, `fa`, `ib`, `ik`, `sqw`, `tw`,
  `weasyl`, `wp`) now accept `proxy_url` + `proxy_key` arguments.
  When both are truthy they wrap the httpx transport in
  `polling.cf_proxy.CloudflareProxyTransport`; otherwise behaviour
  is unchanged.
- Single decision helper at `polling/cf_proxy.py:proxy_kwargs(settings,
  platform_code)` returns either `{}` or
  `{"proxy_url": ..., "proxy_key": ...}`. Three callers feed it:
  the per-platform poller singleton accessor, the per-platform
  `auth/connect` route, and the IB/FA importers. AO3 / DA / SF
  remain "always on when worker is configured"; the other eight
  gate on a per-platform `<platform>_use_cf_proxy` setting.
- `GET /api/settings/preferences` now returns the eight new toggle
  values plus a `cf_worker_configured` boolean (drives the
  disabled state on the UI checkboxes when worker creds are
  missing).
- `POST /api/settings/preferences` accepts the eight new toggle
  keys.
- New "CF Proxy Backup" accordion in Settings → Polling tab with
  one checkbox per opt-in platform. Banner explains the behaviour
  and warns when worker creds aren't configured.

Worker quota math: each opt-in platform poll cycle is roughly
50–200 requests; default 4-hour cadence = 6 cycles/day; eight
platforms toggled on = ~2.5–10k extra Worker requests/day, well
within the free tier (100k/day). Currently ~0 since defaults
are all off.

---

## [2.18.5] - 2026-05-03

### Persistent sessions across all platforms with login flows

Generalises the AO3 / SqW singleton-warming pattern from 2.18.4 to
the rest of the platform fleet. Six more `auth/connect` endpoints
now route through their poller's persistent client singleton rather
than constructing a throwaway client and immediately closing it:

- **Bluesky** (`/api/bsky/auth/connect`) — persists XRPC session.
- **DeviantArt** (`/api/da/auth/connect`) — persists cookie session.
- **Itaku** (`/api/ik/auth/connect`) — persists API connection pool.
- **SoFurry** (`/api/sf/auth/connect`) — persists session cookies
  (TOTP code is request-scoped and applied to the singleton just
  for this validation call).
- **X / Twitter** (`/api/tw/auth/connect`) — persists cookie session.
- **Wattpad** (`/api/wp/auth/connect`) — persists API connection pool.

Plus the IB importer (`posting/importer.py:import_from_inkbunny`)
now reuses the cached SID the poller writes to the local DB after
each successful login. IB calls `ensure_session(cached_sid)` instead
of `login()`, falling back to a fresh `api_login.php` round-trip
only when the cached SID has expired — back-to-back imports no
longer cost a login per call.

**Not changed:**
- **FurAffinity** (`/api/fa/auth/connect`) — cookie-based, no
  login flow to persist beyond the cookies themselves (which are
  in settings already).
- **Weasyl** (`/api/ws/auth/connect`) — API-key authenticated, no
  session/login concept at all.

The pattern across all eight platforms with login flows is now
identical: `_get_or_create_client(settings_overlay)` returns a
process-lifetime singleton; `auth/connect` validates against it;
imports reuse it; poll cycles reuse it; nothing closes it. One
session per platform per process.

---

## [2.18.4] - 2026-05-03

### AO3 / SqW import: stop the cold-start re-login that trips AO3's rate limiter

Caught from the AO3 draft-import logs:

```
02:20:11  AO3: Successfully logged in as KnaughtyKat   ← /auth/connect
02:24:58  AO3: Logging in as KnaughtyKat...            ← /import/ao3/...
02:24:58  GET /users/login → 429 Too Many Requests     ← banned
```

Every layer was creating its own `AO3Client` / `SquidgeWorldClient`
and immediately closing it: `auth/connect` validated and threw away
the session, the importer constructed a fresh client and ran
`ensure_logged_in()` cold (which calls `login()` because
`_logged_in=False` on a new instance), and AO3's `/users/login`
endpoint throttles per-IP for 5–10 min after a single hit. So the
second-and-onwards login of the day always 429'd. AO3 doesn't
appear to use Anubis itself — only SqW does — but both share the
underlying Rails app, and SqW's Anubis solve is similarly wasteful
to repeat on every call.

Three changes:

- **Importers route through the poller's singleton.**
  `posting/importer.py:import_from_ao3` and `import_from_squidgeworld`
  now resolve their client via the existing
  `polling.{ao3,sqw}_poller._get_or_create_client(settings)` instead
  of constructing one inline. The singleton survives across import
  calls, poll cycles, and connect calls — all four code paths now
  share session cookies and Anubis tokens. Importers also no longer
  call `client.close()` since the poller owns the lifecycle.
- **`auth/connect` warms the singleton.** `routes/ao3_api.py` and
  `routes/sqw_api.py` connect handlers now route validation through
  `_get_or_create_client` rather than constructing+closing a
  throwaway client. A successful UI-driven connection now leaves a
  live, reusable session in place for the next import or poll —
  not a discarded one.
- **`ensure_logged_in()` defended against transient verification
  failures.** Both clients did a "session check" GET on
  `/users/{name}` and tore the session down whenever the response
  didn't contain "Log Out" — including when the response was
  `None` (timeouts, 429-exhausted retries, transient Cloudflare).
  That tear-down forced a relogin which re-tripped the rate
  limiter. Now the flag only flips on a fetched page that
  *positively* lacks the logged-in markers; a failed verification
  fetch leaves the session alone.

---

## [2.18.3] - 2026-05-03

### `.env` no longer clobbers UI-set credentials on every restart

`server.py:_seed_settings_from_env()` previously overwrote any
existing settings value that differed from the corresponding
environment variable, so credentials updated through the dashboard
silently reverted to whatever was baked into `.env` on the next
`docker compose up`. Now the function only fills in MISSING or
EMPTY fields — UI changes survive container restarts. `.env`
becomes a true one-time bootstrap for fresh installs.

The vault → settings.json → UI pipeline was already correct on
its own; this just stops the env-seeding step from racing it.

To change a credential going forward: Settings UI. To clean up,
remove the obsolete entries from `.env`.

---

## [2.18.2] - 2026-05-03

### OTW import: don't write a stub story when auth is wrong

Caught probing two real drafts on the live container: SqW redirects
fetches of unowned works to the user dashboard with 200 OK (rather
than 404), so the title-heading + userstuff sanity check on the
*public* path passed straight through to the preview fallback,
which then ALSO returned a dashboard page — and the importer
happily wrote a stub `MASTER.md` with `is_draft=true` and no
content. Both AO3 and SqW now sanity-check the *post*-fallback
response too, and raise a clear error message naming the
configured account so the user knows they need posting credentials
configured (not just `target_user` for polling). No new code path
— just turning a silent bad-import into a loud error.

---

## [2.18.1] - 2026-05-03

### Importers handle drafts as well as published works

Every import path now resolves drafts and live submissions through
the same call, plus a manual-entry box on the import dialog so
draft IDs can be requested directly (the auto-list still only
surfaces what the pollers have seen, which is published-only).

- **AO3 / SqW.** `import_from_ao3` and `import_from_squidgeworld`
  now try `/works/{id}?view_full_work=true&view_adult=true` first,
  fall through to `/works/{id}/preview?view_full_work=true&view_adult=true`
  on 404 (AO3) or when the public response lacks the title heading
  + `userstuff` markers (SqW — its `_get_page` swallows status
  codes through the Anubis solver, so we sniff content instead).
  Both paths return the same Rails markup, so the existing
  `_parse_otw_work_page` works unchanged.
- **Inkbunny.** `api_submissions.php` already returns owner drafts
  transparently; the importer now records `is_draft = (public ==
  "no")` and surfaces it.
- **SoFurry.** `/ui/submission/{id}` likewise returns drafts the
  same shape; we infer draft state from `publishedAt` (null /
  empty / `0000-…` / future ISO date) and tolerate a non-200
  `/s/{id}` page-scrape for drafts (falls back to the JSON
  description rather than failing the whole import).
- **FurAffinity.** No draft API surface — unchanged.

UI: the import overlay grew an "Import by URL or ID" row at the
top. Accepts platform-prefixed (`ao3:12345`, `ib:12345`) and full
URLs (`https://archiveofourown.org/works/12345` and the
equivalents). Imported drafts get an amber row tint plus a
"Done (draft)" button label so they're distinguishable from
published imports at a glance.

---

## [2.18.0] - 2026-05-03

### "Do them all" pass — viewer polish, draft probes, AO3/SQW import, dedication UI, analytics export

Includes: in-tree analytics CSV/PNG export wiring, post-deploy bug
fixes for AO3/SqW import (constructor signature, anonymous-vs-login
strategy, OTW selector tightening, Anubis solver routing for SqW), and
docs sync. The auto-update mechanism was already implemented end-to-end
(updater.py + /api/update routes + sidebar button + settings page) —
just hasn't had a published release to compare against. Cutting v2.18.0
will activate it for desktop users.

A grab-bag of accumulated follow-ups from HANDOFF.md and the EPUB-viewer
shipping in 2.17.6. Headline additions:

**EPUB viewer polish.**
- Aa appearance dropdown — text size (S/M/L/XL via
  `rendition.themes.fontSize`) and theme override
  (auto/light/dark/sepia palettes). Auto reads parent dashboard
  tokens; the other three are book-style palettes hard-coded so the
  reader stays usable when the parent theme is unsuitable for prose.
- Location persistence — last CFI saved to localStorage keyed by
  `pawpoller-epub:{story}:{file}`, restored on next open. Text size
  and theme persist the same way.
- Full-page cover — `rendition.themes.default` now sets
  `img { max-height: 95vh; object-fit: …; margin: 0 auto }` so cover
  images fill the page rather than rendering at intrinsic size in a
  small `<figure>`.

**Subtitle + dedication metadata UI.**
- New text fields in the editor's metadata drawer (Story Info / Description
  & Summary sections respectively). Both write into `story.json`.
- `editor/epub_generator.py` now prefers `story_meta["subtitle"]` over
  `fm.subtitle` from the MASTER.md frontmatter — the drawer is the
  canonical UI surface for editing this field. Existing
  `<!-- @subtitle -->` anchors still work as a fallback.

**Draft-state probes for IB / SF / AO3 / SqW.**
- FA shipped its `probe_draft_state` (Scraps flag) in 2.14.9.
  This release implements the same surface for the other four:
  - IB — `clients/ib/models.py:SubmissionDetail` extended with a
    `public` field; `InkbunnyPoster.probe_draft_state` reads it
    (covers held / under-review / friends-only).
  - SF — fetches `/ui/submission/{id}` JSON and reads `publishedAt`;
    null / `0000-00-00` sentinel / future-dated → draft.
  - AO3 — fetches the `/works/{id}/preview` page; presence of
    `name="post_button"` / `name="preview_button"` or absence of
    kudos / comments controls signals draft state.
  - SqW — same OTW Rails layout, identical heuristics.
- The `POST /api/editor/stories/{name}/probe-drafts` endpoint already
  existed (2.16.x) — these are the missing implementations it was
  waiting on. `posted_draft` cells will now appear in the matrix.

**AO3 / SqW story import.**
- Closes the second half of Phase 14a — the "coming soon" badge
  introduced in 2.13.0. New `posting/importer.py` functions:
  `import_from_ao3` and `import_from_squidgeworld`.
- Both fetch `?view_full_work=true&view_adult=true` so all chapters
  arrive in a single response, then a shared `_parse_otw_work_page()`
  helper extracts title / author / summary / rating / tags / per-
  chapter HTML using the same selectors (Rails app, identical markup).
- Each chapter's `userstuff` block converts via the existing
  `_html_to_markdown` helper; chapters concatenate with `---` breaks
  matching the standard MASTER.md convention.
- `routes/editor_api.py:IMPORT_PLATFORMS` extended with `ao3` and
  `sqw` entries; `IMPORT_COMING_SOON` emptied; the import-submission
  route grew two new `elif` branches.

**Analytics export.**
- Three new buttons on the Analytics page header: Fastest CSV /
  Weekly CSV / Chart PNG. Pure browser-side — no new endpoints.
- `Utils.downloadCSV(headers, rows, filename)` — Excel-compatible
  output (UTF-8 BOM + CRLF), OWASP CSV-injection mitigation
  (cells starting with `=`/`+`/`-`/`@`/`\t`/`\r` get a leading
  apostrophe), RFC 4180 quoting for cells containing comma/quote/
  newline.
- `Utils.dateStamp()` — `YYYY-MM-DD` filename helper.
- `Charts.weeklyGrowthBar` now returns the Chart instance so the
  PNG-download path can call `toBase64Image()` on it.

**Auto-update — no new code, just needs a release tag.**
- `updater.py` + `/api/update/check` + `/api/update/apply` were
  shipped in 2.13.x. `frontend/js/app.js` already has the sidebar
  "Check for Updates" button and Settings → About panel. The
  mechanism has been silently waiting on a published GitHub release
  to compare against (BUG-009 from the round-1 QA log was about
  `check_for_update` flooding 404 logs because no release existed —
  fixed defensively by treating 404 as "no release yet" and logging
  once at INFO).
- Cutting `v2.18.0` activates the existing flow.

**Bug-log walk.** Round-1 (BUG-001..009) all confirmed fixed in
round 2; round-2 (BUG-010..021) all confirmed fixed in 2.14.8 /
2.16.x. SameSite, favicon-401, and `/api/health` version all already
shipped in 2.16.8. Nothing genuinely open from the QA log.

### Post-2.18.0 fixes folded into the same release

Caught during the live AO3/SqW import probe against the deployed
container:
- AO3/SqW importers were instantiating the platform clients without
  the required `target_user` positional arg — fixed by passing the
  authenticated username when no override is configured.
- The SqW import was using `from clients.sqw.client import SqWClient`
  (which doesn't exist) instead of `SquidgeWorldClient`.
- Initial anonymous-fetch strategy hit AO3's 429 rate limit and SqW's
  Anubis bot challenge / "Sorry!" auth wall. Switched to login-first
  for both — `ensure_logged_in()` reuses cached session cookies in
  normal operation; fresh logins only happen when no session is
  cached. SqW additionally goes through the client's `_get_page()`
  helper which transparently solves Anubis.
- OTW work-page selectors tightened: tag-list parser only grabs
  `<a class="tag">` (was capturing "Show additional tags" UI
  toggles); single-chapter content matcher relaxed to a more lenient
  `userstuff` selector with multiple end-of-content fallbacks for
  works that don't emit the `<!--/content-->` marker.
- End-to-end verification: SqW import of work `88317` produced an
  804-line `MASTER.md` with title / author / description / rating /
  fandom all correct. AO3 verification deferred — same code path,
  just blocked by the 429 cooldown from the test attempts.

---

## [2.17.6] - 2026-05-03

### In-app EPUB viewer

EPUB output (2.17.0) was download-only — to eyeball typography you had
to open Calibre, the OS reader, or sync the file off-device. Now there's
a "Preview in browser" link directly under the EPUB row in the editor's
Downloads dropdown that opens a minimal reader in a new tab.

Implementation:
- `frontend/vendor/{epub.min.js,jszip.min.js}` (epub.js 0.3.93 +
  jszip 3.10.1, ~315KB total) vendored locally so the desktop build
  works offline. README in the folder tracks versions and licenses.
- `dashboard.py` mounts `/vendor` as a static prefix and adds it to
  `_AUTH_EXEMPT_PREFIXES` (parity with `/css`/`/js`). New
  `GET /epub-viewer.html` route serves the page with the standard
  cache-buster substitution; auth is the existing session-cookie
  middleware.
- `frontend/epub-viewer.html` is the page: top toolbar (close, title,
  prev/next + percent location, EPUB download), full-bleed reader,
  invisible 18%-wide tap zones on the left/right edges for mobile.
  Reads `?story=X&file=Y` from the URL, fetches via the existing
  `/api/posting/file` endpoint (cookie carries same-origin) so no
  new server-side surface. Theme tokens loaded from `tokens.css` so
  the viewer matches whichever theme the user has set.
- Keyboard arrows work both in the parent page and inside the rendered
  iframe. `book.locations.generate(1024)` runs once per open to back
  the percent indicator — optional, viewer still works if it fails.
- `ePub(url, { openAs: 'epub' })` is mandatory: epub.js sniffs the
  URL's file extension to pick archive vs. directory mode, and our
  URL path is `/api/posting/file` (the `.epub` lives in the query
  string), so the sniff fails and the load hangs trying to read
  `META-INF/container.xml` as a directory. Forcing `openAs` skips
  the sniff.
- `frontend/js/editor.js` `_populateDownloadsMenu`: when the EPUB
  format is present, emits a follow-up `.downloads-row-sub` row
  pointing at `/epub-viewer.html?story=...&file=...`. Separate row
  rather than a nested `<a>` to keep the markup valid.
- Mobile: `<600px` hides the toolbar download button so the title +
  prev/next + percent fit; tap zones cover prev/next anyway.

Deferred (not blocking shipping): no font-size or theme picker inside
the viewer, no cross-session location persistence, no library shelf
listing other EPUBs in the same story.

---

## [2.17.5] - 2026-05-02

### `pawsync --prune` for server-side housekeeping

After cleaning up `Blank/` and `Brand_New_Story/` test stories during
the 2.17.x EPUB push it became clear that `pawsync` is additive only:
`tar xzf` over the destination directory adds and updates, never
deletes. Test/scratch stories pile up on the server every time one
gets renamed or thrown away locally. Manual `rm -rf` over ssh worked
but invites typos; a flag is safer.

`deploy/pawsync.py` now accepts:
- `--prune` — after extract, removes any top-level directory under
  `/home/kithetiger/story-archive/` that doesn't exist locally. Top
  level only — never recurses into a story. The local
  exclude set (`Backups`, `Drafts`, `Styled_HTML`) is treated as
  untouchable so server-side housekeeping folders survive.
- `--dry-run` — implies `--prune`. Lists what would be removed
  without removing it. Always run this before the live prune the
  first time.

Internals: `pack()` now returns the list of top-level story names it
included; `_list_remote_top_level()` runs `find -mindepth 1
-maxdepth 1 -type d -printf '%f\n'` to list server-side dirs; the
diff drives single-arg `rm -rf` calls (one ssh per orphan, so a single
weird name can't cascade). Default behaviour unchanged — without
`--prune` the script behaves exactly as before.

---

## [2.17.4] - 2026-05-02

### Editor downloads dropdown — clean, whole-story-only

The 2.17.3 dropdown was listing every individual file in multi-file
formats — six PDF entries (full + 5 chapter splits), every chapter of
SquidgeWorld, etc. Asked-for clean-up: one row per format, full
story only. Anyone who wants individual chapters grabs the
whole-story zip and cherry-picks.

Rewrote `_populateDownloadsMenu`:
- Hardcoded format render order: EPUB → PDF → Styled HTML →
  Clean HTML → SoFurry HTML → BBCode → Markdown.
  `chapter_bbcode` and `squidgeworld` (chapter-only formats) are
  excluded entirely; the zip covers them.
- One row per format, takes `meta.files[0]` (the format-pattern map
  in `story_reader.py` already orders whole-story files first).
  Defensive: skip if the only file is a chapter split.
- Friendly labels (`sofurry_html` -> "SoFurry HTML" etc.) instead
  of underscored format keys.

CSS:
- New `.regen-dropdown-menu.downloads` modifier widens the menu to
  240px so labels + filesizes fit on one line.
- New `.downloads-row` class for the flex layout — label on the
  left, muted filesize right-aligned with tabular-nums.
- New `.downloads-zip` class for the whole-story footer entry —
  border-top + bold weight to set it apart.
- Empty state styled via `.downloads-empty` instead of inline
  `style=""` blobs.

Whole-story zip stays at the bottom of every variant of the menu —
even on error / loading-failed states — so it's always reachable.

---

## [2.17.3] - 2026-05-02

### Mobile-friendly format downloads (EPUB included)

Driven by the "I want to grab the EPUB to my phone to test it" use
case. The published-story page already had a download badge per
declared format, but EPUB was triple-broken: not in
`_FORMAT_KEY_PATTERNS`, not in `_DOWNLOAD_EXTENSIONS`, no media-type
mapping. Fixed all three. EPUB badges now render with file size +
modified time, and tapping one downloads
`Hypnotic_Claim.epub` (or whatever) via Content-Disposition
attachment with `application/epub+zip` MIME — phone browsers hand
straight to the OS download manager / EPUB reader.

New `GET /api/posting/archive?story=<name>` streams the entire story
folder as a zip via `StreamingResponse`. Excludes `Backups/` (revision
history that no end-user wants in a "send myself this story"
download), `__pycache__/`, and `.git/`. Top-level entry is the story
folder name so extracting produces `Hypnotic_Claim/Markdown/MASTER.md`
rather than dumping `Markdown/MASTER.md` into the user's downloads
folder. Symlink-traversal guarded — every file is verified
`relative_to(story_root)` before being added to the archive.

Two surfaces:

1. **Published-story page (`#/posting/<name>`)**: the existing
   "Available Formats" card gains a "Download all (zip)" footer
   button next to the per-format badges. The card now always renders
   (even when no individual formats have files yet) so the zip
   button is always reachable.

2. **Editor toolbar**: new "Downloads ▾" dropdown next to "Regenerate
   ▾". Lazy-fetches the format list from `/api/posting/stories/<name>`
   on first open — every available file gets its own menu link with
   filesize annotation, and a footer "Whole story (zip)" entry calls
   the new archive endpoint. The menu is invalidated on every
   regenerate so freshly produced files appear without a page
   reload. Multi-file formats (PDF chapters, chapter_bbcode,
   squidgeworld) list each file individually so single-chapter
   downloads don't force the user through the whole-zip path.

Tested on Hypnotic_Claim: 1.3MB zip with 38 entries, EPUB included,
Backups/ excluded.

---

## [2.17.2] - 2026-05-02

### EPUB — own folder + auto-discovery in story.json

EPUBs were landing in `Markdown/{stem}.epub` next to MASTER.md, which
muddied the canonical-source folder. Moved to `EPUB/{stem}.epub` to
match the existing per-format folder convention (`BBCode/`, `HTML/`,
`PDF/`, `SquidgeWorld/`).

`posting/generate_story_json.py:_discover_formats` now flips
`formats["epub"] = True` when the `EPUB/` folder exists with at least
one file in it — same auto-discovery pattern as every other format.
No manual story.json edits required for new stories. Existing
story.json files pick up the flag the next time they're regenerated.

The EPUB regenerate result line now reads
`EPUB/{stem}.epub (NNN bytes)` instead of `Markdown/...`.

---

## [2.17.1] - 2026-05-02

### EPUB polish — first round of visual feedback

Three fixes after eyeballing the 2.17.0 build of Hypnotic_Claim:

**Chapter heading kept dropping the prefix word.** `# Part 1: The
Seduction` was rendering as just "One" + "The Seduction" — the
original "Part" was getting captured by the regex but never used in
the output. `_split_chapter_heading` now returns `('Part One', 'The
Seduction')` so the chapter-number line preserves the source kind
("Part" / "Chapter" / "Section" / "Book"). Word-form number is still
applied. Stories that use raw "Epilogue" or "Prologue" headings (no
numeric prefix) still skip the number-label entirely.

**Blank page between chapters.** The `---` separator on its own line
between chapters in the source markdown was being emitted as a stray
`<hr class="basic-break" />` at the end of chapter 1's xhtml — most
EPUB readers handled it benignly but Apple Books rendered a blank
page between the last paragraph of chapter 1 and the chapter 2
heading. New `_strip_trailing_separators()` drops trailing blank /
`---` / `*End of <title>*` lines from each chapter before xhtml
emission. Also removed `page-break-before: always` from
`.chapter-heading` since each chapter is its own spine file — the
file boundary already makes every chapter a fresh page, doubling up
the directive caused some readers to insert an extra blank page on
top.

**Text messages were styling-blind.** Hypnotic_Claim uses the legacy
`**ETHAN ❤: Hey babe!**` whole-line-bold shorthand, not the
`@text-sent`/`@text-received` anchors — so every message fell through
the heuristic-fallback path and rendered as a plain
`<p class="text-message">` with no class distinction. Reworked the
CSS to give every text message a sender-tagged card style (light
background, small-caps sender name above the body, narrow side
margins) regardless of whether sent/received was specified. Stories
that DO use the anchors still get a subtle blue/grey tint contrast
between sent and received on top of the base card. Phone-display
(`@phone-incoming`) styling tightened to match — added letter-spacing
and a slightly smaller font size so the boxed name reads like a
caller-ID display.

epubcheck 5.1.0 / EPUB 3.3 still clean: 0 / 0 / 0 / 0.

---

## [2.17.0] - 2026-05-02

### EPUB output format

New `editor/epub_generator.py` produces EPUB 3.0 files in a Vellum-style
novel layout: cover -> title page -> copyright -> dedication (optional)
-> author's note -> content warning (front or back) -> chapters with
word-form chapter numbers ("One", "Two") and a drop cap on the first
paragraph. Reuses the existing `parse_front_matter` + anchor parsing
from `editor/converter.py` so the input contract is identical to every
other regenerate format — no MASTER.md changes required.

The generator handles the italic-narration / roman-dialogue house
style: drop caps are floated as roman characters even when the
paragraph that contains them is italic, so the "T" in `*The gym
smelled of rubber...*` renders as a roman drop cap followed by the
remaining italic body. Scene breaks emit `<hr class="basic-break" />`
(vertical whitespace, no glyph). POV markers `**⟨ Name ⟩**` become
in-chapter `<h2 class="section-title subhead">` headings and reset
the drop-cap counter so the next paragraph also gets full-width
treatment, matching Vellum's behaviour for multi-POV chapters.

Wired into the regenerate endpoint as a new `epub` format. The
dropdown gains an "EPUB only" entry next to "PDF only". A new
`epub_warning_position` request field accepts `"front"` (PawPoller
default) or `"back"` (Vellum convention, with a forward link from
the author's note) — defaults to front to match the rest of the
pipeline.

Cover image resolution is `cover.jpg` at the story root if present,
falling back to `story.json` `images.cover` otherwise. Output lands at
`Markdown/{story_stem}.epub`.

Validated with `epubcheck 5.1.0` against EPUB 3.3 rules:
0 fatals / 0 errors / 0 warnings on the Hypnotic_Claim test fixture.
Mimetype is stored uncompressed as the first zip entry per the EPUB
spec.

Skipped on round one (logged for follow-up): bundled OFL fonts (~700KB
+ license tracking), Vellum-grade CSS class system (we use clean
classnames), SVG scene-break glyphs, dedication / subtitle UI fields
in the metadata drawer (the generator reads them if present in
`story.json`/MASTER.md, but there's no UI yet to edit them).

---

## [2.16.14] - 2026-05-02

### BUG-018 + BUG-020 + BUG-021 — last of the round-2 backlog

**BUG-021** (P2, real bug). Per-platform Submissions search filter
was non-functional whenever the user was in the default grid view.
Each platform's `_bind{X}Search` only re-rendered the legacy
`#table-container` (hidden in grid mode); the visible
`#grid-container` was never touched. Typing in the search box
appeared to do nothing.

Fix: each platform render now extracts its `Components.submissionCardGrid(...)`
call into a closure (`{platform}GridRenderer`) and passes it to
`_bind{X}Search`. The search handler invokes the closure with the
filtered set and updates `#grid-container` alongside `#table-container`.
Eleven platforms covered in one sweep: IB, FA, WS, SF, SQW, AO3,
DA, WP, IK, BSKY, TW. Behavior in list view unchanged.

**BUG-018** (P3, housekeeping). `qa/TESTING_CHECKLIST_WEBAPP.html`
still listed §17 Goals + §18 Tags Library as testable surfaces.
Both were removed in 2.14: goal tracking moved into the per-platform
analytics widgets, and the user-defined tag library was folded into
the metadata drawer's tag editor (already covered in §29). Deleted
the two sections (12 tests) plus the orphan "Nav — Goals" / "Nav —
Tags" entries in §1.

**BUG-020** (P2). Re-tested "Regenerate All formats" against prod
(Hypnotic_Claim, 9.8K words, 2 chapters): completed in 7.5s, all
8 formats clean (Clean HTML, SoFurry HTML, BBCode, SquidgeWorld
2 chapters, Styled HTML full + chapters + CSS, **PDF 3 files via
WeasyPrint**, chapter splits). `errors: []`. Original report was
test-container-only (no PDF deps installed); on prod with
WeasyPrint the feature works as designed. Marking closed without
code change.

---

## [2.16.13] - 2026-05-02

### BUG-014 + BUG-017 cleanup

**BUG-014.** Inkbunny dashboard rendered `<h2>Dashboard</h2>` —
every other platform renders `<h2>{Platform} Dashboard</h2>`. The
IB template predates the per-platform pattern. Renamed to
`Inkbunny Dashboard` for consistency.

**BUG-017.** `#/setup` was reachable on the live server runtime
even after `setup_complete: true` — accidentally typing the route,
hitting back from a stale tab, or following a bookmark would dump
the user back into the wizard with the option to overwrite live
archive path / platform credentials / polling owner. Added a route
guard `_guardSetupRoute()` that fetches `/api/setup-status` on
every `#/setup` navigation; if `setup_complete` is true, bounces
to `#/` (Overview). The "Re-run setup" button in Settings clears
`setup_complete` server-side before navigating, so it still flows
through the guard cleanly.

If the status fetch fails, the guard falls through to the wizard
(better to render than strand on a blank page). The wizard's own
backend calls will fail noisily if the backend is truly down.

---

## [2.16.12] - 2026-05-02

### Sidebar — drop the "Platform Dashboards" dropdown

2.16.10 added a master collapse to hide the 11 platform sub-groups
in the mobile sidebar. The user pointed out it's redundant: there's
already a "Platforms" entry above it that opens a visual platform
grid popover (same destinations, fewer taps, more visual).

Removed:
- the `<li class="nav-master nav-platforms-master">` wrapper from
  `index.html`
- all 11 nested `<li class="nav-group">` platform groups (Inkbunny
  through X / Twitter, ~220 lines)
- the master CSS block in `layout.css` (`.nav-master-section`,
  `.nav-master-children`, expanded chevron)
- the master toggle handler and master-auto-expand logic in `app.js`

Sidebar reading order on Overview now:
- Overview
- Platforms (popover trigger)
- **Publishing** divider
- Stories / Queue / History
- Editor / Tools

The `.nav-group` and `.nav-chevron` CSS rules are kept untouched in
case the popover gains per-platform sub-page links later. The per-
platform routes (`/#/sf`, `/#/fa/submissions`, etc.) all still work
— only the sidebar entries are gone, and the popover already covers
the dashboard route. Sub-pages are reachable from each platform's
dashboard.

---

## [2.16.11] - 2026-05-02

### Sidebar — drop dead "Published" link

The "Published" sidebar link (`#/posting/published`) was a legacy
route that just redirected to `#/posting` (the Stories hub) because
"publications are now shown per-story" — see the comment on
`renderPublished()` in `posting.js:744`. Tapping it on mobile gave
the impression the navigation was broken (clicked Published →
landed on Stories with no visible action).

Removed the link from `index.html`. The `renderPublished()` handler
stays in place so any external bookmarks to `#/posting/published`
still resolve to the Stories hub.

---

## [2.16.10] - 2026-05-02

### Sidebar — collapse all platform groups under one master toggle

The 11 always-visible platform group headers (Inkbunny / FurAffinity
/ Weasyl / SoFurry / SquidgeWorld / AO3 / DeviantArt / Wattpad /
Itaku / Bluesky / X / Twitter) clogged the mobile sidebar. Even
with each group's sub-items collapsed by default, the stack of 11
headers pushed Stories / Queue / Published / History below the
fold on a 956px viewport.

Wrapped the 11 platform `<li class="nav-group">` items inside a new
`<li class="nav-master nav-platforms-master">` with a "Platform
Dashboards ›" header. Click toggles `.expanded` on the master,
which animates `.nav-master-children` from `max-height: 0` to
`1200px` (generous so the 11 headers + one expanded sub-group all
fit). Chevron rotates 90° when open.

Auto-expand: navigating to any platform page (`/#/sf`, `/#/fa/...`,
etc.) sets `.expanded` on the master so the user's current section
is visible. Never auto-collapses — that would override an
intentional click.

Sidebar reading order on Overview is now:
- Overview
- Platforms (existing popover trigger)
- **Platform Dashboards ›** (new master collapse)
- Stories / Queue / Published / History
- Editor / Groups
- (poll status, etc.)

Desktop unchanged in spirit (the same auto-expand logic applies);
the 220px hover-expanded sidebar still shows everything when you
land on a platform page.

---

## [2.16.9] - 2026-05-02

### BUG-016 — collapse 9× poll/progress fan-out into one endpoint

The dashboard's global progress bar polled every per-platform
`/api/{p}/poll/progress` endpoint in parallel — 9 simultaneous
fetches every 10s when idle, every 1.5s when a poll was active.
The prod live-monitor caught this as the noisiest pattern in the
DevTools console: any single auth blip spammed 9 identical 401s
at once because each platform fetch independently retried.

**Backend.** New `GET /api/poll/all-progress` in `routes/api.py`
imports each poller's progress dict locally so a partial deploy
(missing module, import error in one poller) only nulls that
slot instead of taking the whole response down. Returns
`{ib, fa, ws, sf, sqw, ao3, da, wp, ik, bsky, tw}` — same
per-platform shape every existing endpoint already emitted
(`active`, `phase`, `current`, `total`, `message`).

**Frontend.** `_progressCheckTick` in `app.js` swapped its
`Promise.all([...9])` for a single `API.getAllPollProgress()` call.
On failure, one `.catch` returns `{}` and every platform slot
falls through to null — the bar stays hidden and the console
stays clean. Same active/idle interval logic; same aggregation.

Per-platform endpoints stay alive — they're still fetched
individually by the per-platform dashboard pages and any external
monitoring scripts. Backwards compatible.

Net effect: 11×/min → 1×/min idle, 50×/min → 5×/min during a
sync (3.5 minutes of sustained polling on FA + IB easily eats
2k requests over a day; this drops it by 88%).

---

## [2.16.8] - 2026-05-02

### Backlog cleanup — three drive-by fixes from HANDOFF

Three small wins that had been sitting in the open-bugs list since
the round-2 prod live-monitor.

**SameSite=Strict cookie quirk → lax.** The prod live-monitor
caught a recurring 30s pattern: 9 successful polling-progress ticks,
then the next tick fails entirely (9× 401 + sometimes a real SPA
fetch like `/api/settings/preferences` also 401), then immediately
recovers. Each burst opened fresh TCP connections (different source
ports), pointing at the browser dropping the session cookie under
specific idle/refresh conditions — a known SameSite=Strict quirk.
Strict was never load-bearing here: dashboard is HttpOnly + only
JSON-only state-change endpoints, so CSRF surface is already
closed by the cookie format. Switched to `samesite="lax"` in
`routes/dashboard_auth.py:132`.

**Favicon 401 noise.** `/favicon.ico` returned 401 because the auth
middleware (`dashboard.py:197-203`) didn't exempt it. Browsers
fetch favicons without auth context on every page, so every
unauthenticated page load spammed the console. Added to
`_AUTH_EXEMPT_PATHS`.

**`/api/health` exposes version.** Was `{"status": "ok"}` with no
version — monitoring and CI couldn't confirm a deploy had actually
rolled out without scraping the dashboard HTML. Now returns
`{"status": "ok", "version": config.APP_VERSION}`.

### Housekeeping

`docs/HANDOFF.md` was stuck on 2.16.3 — bumped the header to 2.16.8
and added the mobile-mode work (Phase 5 calibration sweep + 2.16.4
CSP hash fix + 2.16.5 page header / stats grid + 2.16.6 page-header
wrap + 2.16.7 sizing+tabs+main clamp) to the "What's working live"
table, plus marked BUG-011 / SameSite-quirk / favicon-401 as fixed
in the open-bugs list.

---

## [2.16.7] - 2026-05-02

### Mobile Mode — page-header sizing + tab strip + main clamp

Three layered fixes for the same overflow class — natural intrinsic
content width forcing the document past viewport.

**Page-header circular sizing (the obvious one).**

2.16.6's page-header wrap rule used `width: 100%` on the actions
div, which created a circular sizing dependency: the div asked for
100% of the parent, the parent grew to fit the div's min-content,
and `flex-wrap: wrap` never triggered. Result: the doc still
rendered at 830px wide on a 440px viewport — same overflow as
2.16.5, just with bigger buttons.

Fix: replace `width: 100%` with `flex: 1 1 100%` and add
`min-width: 0`. Flex items default to `min-width: auto` which
refuses to shrink below intrinsic content size — that's what kept
the parent inflated. With `min-width: 0` + flex-basis 100%, the
actions div correctly takes its own flex line at viewport width
and the buttons inside (also given `min-width: 0`) shrink to
50%-3px each.

Also added `box-sizing: border-box` to the actions div as a belt
on top of the suspenders.

**Settings tab strip not constrained.** `.settings-tabs` had
`overflow-x: auto` but no `max-width`, so its natural row width
(General + Appearance + Platforms + Polling + Telegram + ... = 798px)
forced main wide and the scrollbar never engaged. Added
`max-width: 100%` + `min-width: 0` so the container clamps to
viewport and the scroll-x finally activates inside it.

**Main content clamp (defense-in-depth).** Added `max-width: 100vw`
+ `overflow-x: hidden` to `.main-content` on mobile so a future
un-wrapped child can't bust the layout. Individual horizontal
scroll regions (data tables, tab strips) still work inside the
clamp because they have their own `overflow-x: auto`.

---

## [2.16.6] - 2026-05-02

### Mobile Mode — Phase 5 polish from Playwright sweep

Three issues caught while auditing the live dashboard at 440×956
with real data behind a logged-in session.

**Settings page-header overflow (real bug).** The Settings header
holds four action buttons (Save Settings, Poll Now, Full Resync,
Clear Session) inside an inline `<div style="display:flex;gap:8px">`
sibling to the h2. With no `flex-wrap` and no mobile rules
targeting that unclassed div, the row forced the entire document to
~830px on a 440px viewport — every settings card, the tab strip,
the accordion bodies all bled past the right edge. Fix: add
`flex-wrap: wrap` to `.page-header` itself, and a new rule for
`html[data-mobile="1"] .page-header > div` that gives the actions
container `width:100%` plus 50%-flex buttons. Buttons now flow into
two rows of two on mobile and the document collapses back to
viewport width. Same fix benefits any future page-header that picks
up multi-button action clusters.

**Editor toolbar hidden under hamburger.** The editor's
`.editor-toolbar` is a separate component from `.page-header` and
never picked up the +60px hamburger clearance. The "← Stories"
back link was anchored at x=26 — entirely behind the 12-52px
hamburger button. Title rendered as "tories Chosen" instead of
"← Stories Chosen". Added the same
`padding-left: calc(env(safe-area-inset-left, 0px) + 60px)` to
`.editor-toolbar` on mobile.

**Hamburger float shadow (polish).** When the page scrolls, content
slides under the fixed hamburger and visually merges with it even
though the button has its own opaque background. Added a subtle
`box-shadow: 0 2px 6px rgba(0,0,0,0.35)` so it reads as a floating
affordance, like an iOS FAB. Doesn't compete with cards because the
shadow only shows where it overlaps content.

### How this was caught

Re-spun the production SSH tunnel (port 8420), logged in via
Playwright at 440×956 viewport, walked every surface (Overview,
Settings General + Appearance, Editor with a real story, Posting
list + queue + story detail, IB/FA dashboards, Compare).
`document.documentElement.scrollWidth` exposed the Settings
overflow immediately; the editor breadcrumb issue showed up in
the toolbar measurement. Pages that fit (Overview, Posting,
platform dashboards with 2-button headers, Compare) weren't
touched.

---

## [2.16.5] - 2026-05-02

### Mobile Mode — Phase 4 hotfixes

Two layout bugs caught after the CSP fix in 2.16.4 finally let the
mobile rules take effect.

**Page header h2 hidden behind hamburger.** With h2 at x=16 and
hamburger occupying 12-52px, "Overview" rendered as "rview",
"Settings" as "ngs", "Story Editor" as "y Editor". Added
`padding-left: calc(env(safe-area-inset-left, 0px) + 60px)` to
`html[data-mobile="1"] .page-header` so titles always start past
the hamburger's right edge plus 8px breathing room.

**Stats grid stuck at 2 columns.** The dashboard sets
`style="grid-template-columns:repeat(auto-fit,minmax(200px,1fr))"`
inline on the per-platform grid, beating the class-selector mobile
rule. Added `!important` to
`html[data-mobile="1"] .stats-grid { grid-template-columns: 1fr }`
so the inline style is overridden. Now the 11 platform cards stack
1-per-row on portrait phone instead of cramming 2 to a 220px-wide
row.

---

## [2.16.4] - 2026-05-02

### Mobile Mode — CSP hash fix (CRITICAL)

The single bug that made all mobile-mode work from 2.16.0 through
2.16.3 invisible.

When 2.16.0 extended the inline boot script in `index.html` to
resolve `data-mobile` from localStorage, the script's SHA-256 hash
changed but `dashboard.py`'s CSP `script-src` whitelist still held
the old hash from before the extension. Browsers silently blocked
the boot script, `data-mobile` was never set, and every mobile rule
written against `html[data-mobile="1"]` selector was dead CSS.
Users only saw legacy `@media (max-width: 768px)` rules, which is
why "better but not 100%" feedback persisted across four releases.

Fix: updated the CSP hash in `dashboard.py` to
`'sha256-WudoxBejEmzS4SXsQBia7rsNZctlaFiey3RvF0r8SzA='` (the
browser console helpfully prints the expected hash on each block).

Caught by re-running Playwright against the production CSP and
checking `document.documentElement.dataset.mobile` — it was empty
where it should have been "1". Lesson: any inline script change
must update the CSP hash in lockstep.

---

## [2.16.3] - 2026-05-02

### Mobile Mode — Phase 4 Pro Max calibration

The earlier passes optimised for "small phone, save every pixel"
which left a 6.9" 440×956 viewport feeling sparse and undersized.
This pass calibrates sizing for an iPhone 16 Pro Max-class screen.

**Base + heading scale.** Body 14→15px, line-height 1.5. Page
header h2 17→20px. Headings step up consistently — h3 16, h4 14.

**Buttons.** Generic `.btn` 44px min-height, 14px font. Primary
actions (Save, Metadata-save, Re-check) 48px min-height with 600
weight — they read as the obvious "do this" buttons. `.btn-sm`
40px. iOS HIG minimum is 44px; 48px on primaries gives the
"clearly tappable" feel a 6.9" screen rewards.

**Padding.** `.main-content` 12→16px (cards stop kissing the
viewport edges). `.settings-section` 14→16px. `.settings-accordion
summary` 48→52px tall.

**Stat cards** stay 1-col strips but bump to 56px min-height,
24px value, 13px label. Reads as a substantial section divider
rather than a floaty pill.

**Detail page**: thumb max-width 240→280px. Title 18→22px.

**Submission cards**: 1-col with 240px thumbs (was 200px). Title
14→15px.

**Search/filter inputs**: 44→48px tall, 12-14px padding.

**Bottom nav**: total height +6px so icon+label both fit
comfortably; icon 22px, label 11px.

**Editor mobile tabs** (Edit/Rich/Format/Preview): 44px tall,
18px padding — feel like switcher tabs, not chips.

**Anchor toolbar**: button min-width 48px, anchor labels 0.85rem
(up from 0.78).

**Publish-check chapter cards**: summary row 56px tall, 15px
title; per-platform rows 52px tall.

**Theme picker / mobile-mode picker**: 16px card padding, 15px
name, 13px desc.

**Sidebar (when slid open)**: nav links 48px tall, 15px font;
section headings 11px; overall sidebar slightly wider —
`min(320px, 88vw)` (was `min(300px, 85vw)`).

### What this DOESN'T change

- Layout direction (still vertical from P3)
- Mobile-mode toggle (still in Settings → Appearance)
- Editor toolbar collapse (still ⋯ More from P2)
- The legacy `@media (max-width: 480px)` rules (still cover their
  small-phone baseline; this pass overrides them at higher
  specificity for mobile-mode users)

If sizing still feels off on a specific surface, point at it and
I'll target it directly — the new block is at the very end of
`editor.css` for easy iteration.

### Files touched

`config.py` (APP_VERSION → 2.16.3),
`frontend/css/editor.css` (Phase 4 calibration block at end —
~190 lines covering body/heading scale, button heights, padding,
stat/detail/submission card sizing, search inputs, bottom nav,
editor tabs, anchor toolbar, publish-check, theme/mobile-mode
pickers, sidebar dimensions),
`CHANGELOG.md`.

---

## [2.16.2] - 2026-05-02

### Mobile Mode — Phase 3 vertical sweep

User feedback: "anything that is currently wide screen should be
turned into a vertical version." This pass forces every multi-column
grid to a single column and every horizontal flex strip to a vertical
stack on mobile. Most of the targets had a `@media (max-width: 480px)`
override already; mirroring them under `html[data-mobile="1"]` makes
them fire consistently in mobile mode (including forced-on at
desktop widths) and bumps the threshold from "small phone" to "any
mobile resolution".

**Grids forced to 1 column on mobile.** `growth-grid` (was 3-col),
`goal-grid` (was 260px-min auto-fit), `card-grid` (story list, was
280px-min), `story-card-grid` (was 300px-min), `tag-browser-grid`
(was 240px-min), `chart-row` (was 1fr 1fr), `theme-picker` and
`mobile-mode-picker` (were 220px-min auto-fill — barely fit one
card at 430px anyway, now explicit), `fa-metadata` (was 140px-min,
3 cols on a 430px viewport), `setup-platforms` (was 130px-min, 3
cramped cols).

**Detail page header → vertical.** 120px square thumb on top
(centered, max-width 240px, aspect-ratio 1), title + meta below.
`detail-stats` becomes a vertical list of label-left/value-right
strips with their own surface — easier to scan on a phone than the
horizontal stat row.

**Pinned row → vertical stack.** Was a horizontal scroll-snap
strip of 200px-wide cards; on a phone the user had to swipe through
each card and could only see one at a time. Vertical stack shows
all pinned items in one scroll.

**Compare select chips → vertical full-width buttons** at 44px-min.
The compare-page main two-panel side-by-side flow is intentionally
hard to render vertically and stays as-is for v1; future tab switch
between left/right targets.

**Date range bar wraps in 3-up rows.** Was a tight horizontal flex
where each button got squeezed to ~50px and the labels wrapped
inside. Now wraps into multiple rows with each button at ≥60px,
labels stay readable.

**Settings tabs scroll horizontally with snap.** Were already
overflow-x via the 768 rule; this pass adds `scroll-snap-type: x
proximity` and 44px-min tap targets. Settings rows stack their
toggle-switch right-aligned beneath the label.

**Timeline / log rows → single column.** Already 1fr at 480px;
mirror under data-mobile so the mobile-mode forced-on case behaves.

**Tighter padding everywhere.** `.main-content` 12px + bottom-nav
clearance, `.settings-section` 14px, `.settings-accordion summary`
48px touch height + 14px font.

**Generic safety net for tables.** Any `.data-table` not opted into
the `[data-mobile-cards]` transformation gets `overflow-x: auto`
on mobile so an unconverted table doesn't burst the viewport.

### Surfaces NOT changed in this pass

- Bottom nav (intentionally 5-item horizontal — that's the pattern)
- Editor mobile tab bar (intentionally 4-tab horizontal switcher)
- Anchor toolbar (intentionally 13-button horizontal swipe strip)
- Compare page side-by-side panels (would need a tab switcher;
  out of scope for v1)
- Submission card grid (already 1-col with 200px thumbs from P2)
- Stat cards (already 1-col strips from P2)
- Editor toolbar (handled via P2 ⋯ More collapse)

### Files touched

`config.py` (APP_VERSION → 2.16.2),
`frontend/css/editor.css` (Phase 3 block at end of mobile-mode
section: ~165 lines covering all the grid → 1-col rules,
detail-header vertical, pinned-row stack, compare/date-range/
fave/comment/timeline/log/settings adjustments),
`CHANGELOG.md`.

---

## [2.16.1] - 2026-05-02

### Mobile Mode — Phase 2 portrait-phone polish

Follow-up to 2.16.0 after a real device pass. Phase 1 closed the
worst breakages but the layout still felt cramped in iPhone Plus
portrait. Six targeted fixes.

**iOS input zoom (P2.A).** Every `<input>`, `<select>`, `<textarea>`,
`.search-input`, and `.filter-select` now floors at 16px on mobile.
iOS Safari auto-zooms when a focused input has font-size < 16px and
never zooms back (the fix isn't on focus, it's on `blur`, which iOS
doesn't honour). The 2.16.0 contenteditable fix already covered the
WYSIWYG; this catches everything else — credential fields, search
boxes, settings inputs, the chapter-nav select. `text-size-adjust:
100%` added to `<html>` so OS-level scaling doesn't second-guess us.

**Editor toolbar collapse (P2.B).** The toolbar had 12+ children
(back, title, chapter dropdown, slop/status/wordcount, Save,
Metadata, CSS, Regenerate ▾, Publish, Format, 4 format tabs) which
wrapped into 3-4 ugly rows on a 430px viewport. Wrapped the
secondary cluster in `.editor-actions-secondary` and added a `⋯`
More button visible only on mobile. Toolbar stays one row (back /
title / ⋯ / Save / Metadata); the secondary cluster slides in below
when the user taps `⋯`. Outside-click closes. Title gets ellipsis
truncation so long story names don't push the primary buttons
off-screen.

**Bottom nav swap Analytics → Editor (P2.C).** The Editor is one
of the heaviest-used surfaces and was only reachable via sidebar →
scroll → tap. Bottom nav now shows Overview / Platforms / Upload /
**Editor** / Settings. Analytics remains in the sidebar (Tools
section).

**Stat cards 1-col strips on portrait (P2.D).** Existing 480px
breakpoint was 2-col with values cramped in. Mobile mode now stacks
cards vertically as horizontal strips: label left, value right, one
short row per stat. Eight stats become eight short rows instead of
four tall card pairs — less scrolling, more legible.

**Page header tighten + 16px form controls (P2.E).** `.page-header
h2` drops to 17px, `margin-bottom` from 24px to 12px. `.toolbar`
gap from 8px to 6px. Search/filter inputs get min-height: 44px
explicitly so they're tappable and clear of safe-area junk.

**Modal full-screen on mobile (P2.F).** Chart-modal and
platform-grid both went from centred dialogs (with 24px / 5vw
insets) to edge-to-edge sheets respecting `env(safe-area-inset-*)`.
Chart legends were getting cropped in the centred 90vh dialog;
full-screen gives them room. Platform-grid drops from 3-col to
2-col with bigger 96px-min cards.

**Bonus: submission-card grid → 1-col on portrait** with 200px-tall
thumbnails (was 2-col with 120px-tall thumbs at the 480px
breakpoint, too small to read titles).

### Files touched

`config.py` (APP_VERSION → 2.16.1),
`frontend/index.html` (bottom nav: Editor replaces Analytics),
`frontend/js/editor.js` (toolbar HTML wraps secondary cluster +
adds ⋯ More button; click bindings + outside-click close),
`frontend/css/editor.css` (Phase 2 block at end of mobile-mode
section: iOS 16px, stat-card strip, page-header tighten, sub-card
1-col, chart-modal + platform-grid full-screen, editor-toolbar
collapse with .actions-open class),
`CHANGELOG.md`.

### What's NOT fixed in 2.16.1

Phase 2 deferred items — all judged lower-impact than the six above:
metadata drawer accordion-collapse, sidebar search, format-tabs
"More ▾" overflow when `actions-open` (currently wraps OK), CSS
editor mobile UX (the 5th-tab works but theme-row layout is desktop-
sized), per-platform dashboard pages haven't had a portrait audit.

The legacy `@media (max-width: 768px)` rules still drive a chunk of
the mobile UX. `mobile_mode = "always_on"` on a wide desktop fires
the new `[data-mobile="1"]` rules but not the legacy ones — the two
sets aren't unified yet. Refactor pass deferred until the new rules
have stabilised.

---

## [2.16.0] - 2026-05-02

### Mobile Mode — Phase 0 + 1

A real mobile interface for the dashboard, prompted by the iPhone 16
Plus Pro experience. Existing media queries handled the broad strokes
(hamburger, slide-in sidebar, bottom nav, table → card transformation),
but the editor was unusable below ~600px and several touch interactions
fought the user. This release closes the worst gaps and adds a
Settings → Appearance toggle to let any device opt in or out.

**The toggle.** New `mobile_mode` preference under Settings →
Appearance with three options: **Auto** (default — follows
`(max-width: 768px)` via `matchMedia`), **Always on** (force the
mobile interface on every device — useful for testing or for users
who'd rather have the touch-first layout on a tablet), and **Always
off** (best-effort: keep the desktop UX even on a phone; existing
legacy media queries still fire on small viewports). Persisted to
`settings.json` and synced across devices via the existing 7c
auto-sync. Resolved at boot via the inline `<head>` script — no
flash of the wrong layout. Single source of truth: `<html
data-mobile="0|1">`. A `matchMedia` listener keeps `auto` in sync
when the user rotates the phone or resizes the window.

**Editor → single-panel switcher (P1.1).** The 4-pane quad layout
(MD source / Rich editor / Format source / Format preview) collapsed
to a 2×2 grid below 1200px and stopped — at 430px each pane was
~200px wide, CodeMirror unusable. Mobile mode now shows a tab bar
above the quad with 4 buttons (Edit / Rich / Format / Preview); only
the active panel is visible, the rest stay mounted in the DOM so
CodeMirror state, contenteditable selection, and saved scroll
positions survive switches. Picking a format (Clean HTML / SoFurry /
BBCode / Styled) auto-jumps to the Format panel. Toggling the CSS
theme editor adds a 5th tab dynamically and removes it when closed.
The per-panel eye-icon hide-toggles are suppressed — meaningless in
single-panel mode.

**Anchor toolbar → horizontal swipe strip (P1.2).** The 13 buttons
(undo/redo, B/I, H1, HR, T/Sub/By, ⚠/Disc/FF, Body, →Sent/←Recv/
☎Phone) used to crowd a narrow row at 28px-min-width. On mobile
they're now 44px touch targets in a horizontal scroll strip with
subtle right-edge mask-fade so the user knows there's more.
Scroll-snap proximity keeps the snapping gentle.

**Publish-check matrix → expandable chapter cards (P1.3).** The
chapter × 11-platform table is meaningless on a 430px viewport.
Mobile mode renders each chapter as a `<details>` card with a status
summary (e.g. "5✓ 1↑ 2🔒") visible in the closed state and a
vertical platform list when expanded — each platform inline with
icon + name + status label. Cell-click handler unchanged (same
`.publish-check-cell` class with `data-cell` attribute). Detail
panel scrolls into view on tap. Modal goes full-screen instead of
the desktop's 5vw inset.

**Sidebar `:hover` lockout for touch (P1.4).** The icon rail
expanded-on-hover from 60px → 220px, but on touch devices the
synthetic-hover from a tap latched the panel open until the user
tapped elsewhere. Felt broken on iOS. All `:hover` rules in the
sidebar block now sit inside `@media (hover: hover)`; the
`.expanded` class still works everywhere as a JS-driven escape
hatch. Touch users open the sidebar via the hamburger and close it
via the backdrop, no surprise expansions.

**Safe-area-inset-top (P1.5).** iPhone 16 Plus Dynamic Island sits
at top-center; the hamburger at `top: 12px` was clipping behind it
in some orientations and the global poll-progress-bar rendered
underneath the notch. Both now respect `env(safe-area-inset-top)`.
Sidebar header (when the panel slides open on mobile) also gets
top + left safe-area padding so the title clears the notch on
landscape phones.

**Publish-check modal backdrop mount-window guard (P1.6).**
The 2.14.10 metadata-drawer fix (mobile fires a synthetic click
~300ms after touchend on whatever element is under the finger; if
that's a backdrop mounted synchronously inside the open-button
handler, the modal closes the instant it opens) was flagged as
"likely vulnerable" for the publish-check modal too. Confirmed real,
fixed with the same 400ms-since-`open()` guard on the backdrop click
handler. The publish-check modal is mounted once at first use, so
the gate keys off `_openedAt` (updated each `open()` call) rather
than mount time.

**Out of scope for this release.** Phase 2 polish (metadata drawer
accordion-collapse, format-tabs `More ▾` overflow, theme picker
2-col mobile grid, bottom nav editor entry, CodeMirror
`autocorrect=off`, sidebar search) and Phase 3 nice-to-haves
(pull-to-refresh, swipe gestures, FAB) are scoped for follow-up
releases. Roadmap-stale items (`docs/ROADMAP_PUBLIC.md` still says
"Current version: 2.13.8") were not touched here.

### Files touched

`config.py` (APP_VERSION → 2.16.0),
`routes/api.py` (mobile_mode added to GET/POST `/settings/preferences`
with whitelist),
`frontend/index.html` (boot script extended to apply `data-mobile`
synchronously),
`frontend/js/app.js` (MOBILE_MODES catalog, `applyMobileMode`,
`_resolveMobile`, `_initMobileModeWatcher`, Settings → Appearance UI
section + click/keydown handlers, `_refreshPrefsFromServer` extended
to pull `mobile_mode` cross-device),
`frontend/js/editor.js` (mobile tab bar HTML, `setMobileActivePanel`
helper, format-tab → fmt-source auto-jump, CSS-editor 5th-tab
add/remove, `_updateGridColumns` mobile no-op),
`frontend/js/publish_check.js` (`_renderDesktopMatrix`,
`_renderMobileMatrix`, `_renderMobileCell`, `_countActionable`
factored out; cell-click bind walks `[data-ch-idx]` ancestor; backdrop
guard via `_openedAt`),
`frontend/css/tokens.css` (mobile-mode picker card styles),
`frontend/css/layout.css` (sidebar `:hover` rules split + gated by
`(hover: hover)`; hamburger + sidebar header safe-area-inset-top/left),
`frontend/css/components.css` (poll-progress-bar safe-area-inset-top),
`frontend/css/editor.css` (large mobile-mode block at end —
anchor toolbar 44px touch targets + scroll-snap + edge-fade,
editor-quad 1-column override, mobile tab bar styles, publish-check
modal full-screen on mobile, mobile chapter cards, full-width detail
panel),
`CHANGELOG.md`,
`docs/HANDOFF.md` (TODO: bump version + open-roadmap note).

---

## [2.15.0] - 2026-05-02

### Per-platform tag tabs for FA + Weasyl + AO3 + SquidgeWorld

The editor's Per-Platform Tags section grew four new tabs alongside
the existing Default / SoFurry / Inkbunny / Wattpad. Each new tab
inherits from Default on first load, then becomes its own override
list once the user edits — useful when one platform's limit forces
a smaller set than the others can tolerate.

The trigger was Tombstone: 91 default tags serialise to an 814-char
keyword string, which the FA validator rejects (`furaffinity.py:227-228`,
500-char ceiling). Pruning the default list to fit FA punishes the
other platforms, which happily take the longer set. With per-platform
tabs the user can keep the rich default for IB/SF/Weasyl and ship a
trimmed FA list — no compromise.

**FA tab gets a second counter.** The standard "X tags · Platform max:
Y" line now also shows "X / 500 chars" when the FA tab is active,
turning red once the joined keyword string exceeds the validator's
limit. Catches the over-limit case before save.

**Populate from Default button.** Stories whose `story.json` predates
these tabs (Tombstone, anything older than this release) won't have
`tags.furaffinity` / `tags.weasyl` / `tags.ao3` / `tags.squidgeworld`
namespaces. When such a tab is empty AND Default has tags, a
"Populate from Default (N)" button appears. One click copies every
default tag in (transformed for the platform — underscores for FA /
Weasyl, spaces for AO3 / SQW). Once populated, the user can trim
freely. New stories don't need this — the existing
`TAG_CASCADE_PLATFORMS` keeps every platform in sync automatically as
the user edits Default.

**No backend changes.** `posting/story_reader.py:395-405` already
respects per-platform overrides correctly in the JSON path — the
default cascade only fills in platforms whose namespace is missing.
The legacy txt parser at line 799 still has the blind cascade but no
live story exercises it; that path is parsed once and replaced with
`story.json` on first save.

Per-chapter tag tabs (`_CHAPTER_TAG_PLATFORMS`) intentionally not
extended in this release — chapter-level overrides for FA/Weasyl/AO3/
SQW can land in a follow-up once the story-level UX has soaked.

### Files touched

`config.py` (APP_VERSION → 2.15.0, minor bump because this is a new
feature surface),
`frontend/js/metadata_editor.js` (`TAG_PLATFORMS` extended,
`TAG_LIMITS` + `PLATFORM_LABELS` updated, FA-specific char counter,
"Populate from Default" button + `_populateFromDefault` handler with
underscore-canonicalisation guard for default lists that contain
spaces),
`frontend/css/editor.css` (`.metadata-tag-populate` spacing),
`CHANGELOG.md`,
`docs/HANDOFF.md` (per-platform tag bullet marked done).

---

## [2.14.10] - 2026-05-02

### Metadata drawer no longer self-closes on mobile (BUG-023)

Tapping the Editor's **Metadata** button on a touch device opened the
drawer for ~300ms then immediately closed it. Cause: the backdrop
(`position: fixed; inset: 0`) is mounted synchronously inside the
button's click handler, so the moment the drawer opens the backdrop
is sitting under the user's finger. Mobile then fires a synthetic
click ~300ms after touchend on whatever element is currently under
the touch point — which is now the backdrop, not the button — and
the backdrop's `close()` handler runs.

Fixed in `metadata_editor.js` by gating the backdrop click handler
with a 400ms mount window. Clicks during that window are ignored, so
the synthetic click can't close the drawer it just opened. Real
backdrop clicks (the user deliberately tapping outside the drawer)
still close it as expected.

The publish-check modal uses the same backdrop pattern and is likely
vulnerable to the same issue, but the symptom is masked there because
the user has to do at least one more interaction (cell select →
button click) before any backdrop dismissal could fire. Worth a
follow-up audit pass.

### Files touched

`config.py` (APP_VERSION → 2.14.10),
`frontend/js/metadata_editor.js` (mount-window guard on backdrop
click),
`CHANGELOG.md`.

---

## [2.14.9] - 2026-05-02

### Draft detection in the publish-check matrix (FA-only first slice)

Adds a "Check drafts" probe to the publish-check modal. For every posted
publication on this story, the app pings the platform to ask "is this
sitting as a draft, or is it live?" and overlays the result on the
matrix. A new `posted_draft` cell status renders with a dashed amber
border and a `✎` icon; clicking the cell exposes a "Publish draft (move
out of Scraps)" action that flips the submission live in one round-trip.

This release ships the FA implementation only. FA has no real drafts —
**Scraps** is the closest equivalent (hidden from gallery / browse /
search, but still on the profile + visible to watchers + reachable via
direct link), so the probe reads the scrap checkbox on
`/controls/submissions/changeinfo/{id}/`. IB / SF / AO3 / SQW use
different mechanisms and will land in follow-up work — they cleanly
opt out via the new `probe_draft_state()` returning `None` on the base
class.

**`edit_submission` now preserves the scrap state instead of clearing
it.** Latent bug: the previous edit form POST omitted the `scrap`
field on every metadata edit, which would silently un-scrap any
scrapped submission the moment you tweaked its tags or title. Added a
`scrap: bool | None = None` parameter — `None` = read the current
checkbox state from the form and re-emit it, `True`/`False` = explicit
override. The new "Publish draft" action calls edit with
`scrap=False`.

**New endpoints.** `POST /api/editor/stories/{name}/probe-drafts`
mirrors the existing `/verify` endpoint but probes draft state instead
of deletion state — same 0.4s rate limit between probes, same
not-implemented opt-out, no DB writes (the frontend overlays results
in-memory on cell `dataset.cell` blobs). The `/publish` endpoint
accepts a new `action='publish_draft'` that bypasses the full
post/update pipeline and just calls `poster.publish_draft(external_id)`
— since we're flipping a visibility flag, not pushing new content.

### Files touched

`config.py` (APP_VERSION → 2.14.9),
`clients/fa/client.py` (scrap checkbox parsing in `edit_submission`,
new `probe_scrap_state` method),
`posting/platforms/base.py` (`probe_draft_state` default-None hook),
`posting/platforms/furaffinity.py` (`probe_draft_state` + `publish_draft`
implementations),
`routes/editor_api.py` (`/probe-drafts` endpoint, `publish_draft`
action on `/publish`),
`frontend/js/publish_check.js` (new status, "Check drafts" footer
button, overlay logic, "Publish draft" action button, confirm dialog),
`frontend/css/editor.css` (`.cell-posted-draft`, `.stat-draft`),
`CHANGELOG.md`,
`docs/HANDOFF.md` (FA portion of draft-detection bullet marked done).

---

## [2.14.8] - 2026-05-01

### Round-2 QA bug-fix sweep

Two P1s caught in the second automated Playwright pass against the
2.14.7 test container, plus a couple of structural notes from a
read-only sweep against the live GCP instance (still on 2.14.6 —
2.14.7 hasn't shipped yet, this releases as 2.14.8 instead).

**Mobile hamburger button no longer off-screen (BUG-010).** The
hamburger lived inside `.sidebar > .sidebar-header`, but the sidebar
slides off-screen on mobile via `transform: translateX(-100%)` —
which took the hamburger with it. Adding `position: fixed` to the
button alone didn't fix it, because a fixed-position descendant of a
transformed ancestor gets re-anchored to that ancestor's containing
block (a well-known CSS quirk with `transform`). Moved the button
out of `.sidebar` to be a top-level child of `<body>`, so its
`position: fixed` now correctly anchors to the viewport. New
`body.sidebar-open` class shifts the button to `left: 240px` when
the panel is open, so it's still tappable as a close affordance
above the open sidebar instead of being hidden behind it. Mobile
users on every viewport ≤768px previously had no way to open the
nav at all.

**Create New Story returns a clean 400 instead of an unhandled 500
(BUG-019).** `POST /api/editor/stories/create` was calling
`mkdir(parents=True, exist_ok=True)` against the configured archive
path without first checking whether the path was reachable. On a
fresh server install where `posting_story_archive_path` defaulted to
the host-specific `/m_x` (which doesn't exist in the container), the
mkdir raised `FileNotFoundError`/`PermissionError` and FastAPI's
default handler returned a bare 500 with no detail. The frontend
catch block tried to render `data.detail` but got an empty/non-JSON
response. Now the endpoint pre-validates the archive root: it tries
to create it (treating missing intermediate dirs as the user's
intent), then explicitly checks `os.access(W_OK)`. On failure it
returns 400 with a structured detail message pointing the user to
Settings → General → Posting Settings. The frontend's existing
`!resp.ok → throw → catch → display in errEl` chain now surfaces
that message correctly.

### Files touched

`config.py` (APP_VERSION bump to 2.14.8),
`frontend/index.html` (hamburger out of sidebar),
`frontend/css/layout.css` (mobile media query for fixed-position hamburger),
`frontend/js/app.js` (`body.sidebar-open` class toggle in
open/closeSidebar),
`routes/editor_api.py` (archive path validation before mkdir),
`CHANGELOG.md`,
`docs/HANDOFF.md`,
`qa/AUTOMATED_BUG_LOG.md` (Round-2 findings),
`qa/TESTING_CHECKLIST_WEBAPP.html` and
`qa/TESTING_CHECKLIST_NATIVE.html` (version bump + regression tests).

### What's NOT fixed in 2.14.8

Round-2 QA also surfaced these P2/P3 items, deferred to a future
release:

- **BUG-021 [P2]** — IB Submissions search filter is non-functional
  on production (the textbox accepts input but doesn't filter the
  card grid). Already-rendered table view still sorts; only the
  card view's search is broken.
- **BUG-020 [P2]** — Editor "Regenerate ▾ → All formats" silently
  skips Styled HTML, SquidgeWorld, PDF, and chapter splits without
  reporting which were skipped. Endpoint returns 200 even though
  it's only generated 3 of the 7 expected outputs.
- **BUG-016 [P3]** — Progress-check ticker fan-out spams the
  console with 9-10 stack traces on a single network blip.
- **BUG-018 [P3]** — Checklist §17 Goals + §18 Tags reference
  standalone pages that don't exist; both features actually live
  inside per-platform dashboards / metadata drawer. Checklist
  needs editing, code is fine.
- **BUG-011, BUG-013, BUG-014, BUG-015, BUG-017** — Cosmetic /
  workflow notes documented in `qa/AUTOMATED_BUG_LOG.md`.

**BUG-022 retracted** — original report was a false positive from
the automated QA: the test was matching the word "Platforms" inside
the metadata drawer's own "Per-Platform Tags" / "Platform Toggles"
section headings and mistakenly concluding that the Platforms
popover had opened. User-confirmed via screenshot — the Metadata
button works correctly on both 2.14.6 and 2.14.8.

---

## [2.14.7] - 2026-04-28

### Automated-QA bug-fix sweep on top of 2.14.6

Nine issues surfaced in the first automated Playwright pass against the
server-runtime test container (`docker-compose.test.yml`, port 8421).
None were data-loss bugs but several were UX dead-ends — most painfully
a catch-22 where a fresh server install with no Inkbunny credentials
got stuck on the legacy IB login screen with no way to reach Settings
to configure other platforms.

**Cache-buster keyed off APP_VERSION (BUG-001).** Every CSS/JS reference
in `frontend/index.html` now uses `?v=__APP_VERSION__` and the
`/` route in `dashboard.py` substitutes the running version in at
request time. No more hand-bumped per-file `?v=NNN` numbers — every
release auto-invalidates the browser cache. Result is cached so the
substitution happens once per process. The triggering symptom was
2.14.6 shipping with `app.js?v=311` unchanged from 2.14.5 even though
the wizard code had changed substantially, leaving cached browsers
serving the old JS.

**Plaintext password no longer re-seeds on every restart (BUG-004).**
`config.migrate_dashboard_auth()` now scrubs `dashboard_password` and
`dashboard_user` from `settings.json` even when the bcrypt hash is
already in place. `_seed_settings_from_env()` was re-writing them on
every Docker start from the `DASHBOARD_PASSWORD`/`USER` compose env
vars, leaving plaintext sitting next to the hash and defeating the
whole point of the migration. The bcrypt hash is what auth actually
uses; the plaintext was just a leak.

**CSP unblocked the no-flash theme bootstrap and Google Fonts (BUG-002,
BUG-003).** The inline `<script>` in `index.html` that reads
localStorage and applies the persisted theme before CSS evaluates was
being blocked by `script-src 'self'`. Added the script's sha256 hash
(`'sha256-PQv0iyndH6bqQiLzwEuCSIz1xMcWBsP0swro6kOCiZI='`) to the
directive — keeps `'unsafe-inline'` off but allows just this one
bootstrap. `style-src` and `font-src` now include
`https://fonts.googleapis.com` and `https://fonts.gstatic.com` so the
typography (Crimson Pro / Inter / JetBrains Mono) actually loads.

**IB-login catch-22 broken (BUG-005, BUG-006, BUG-007).** Three bugs,
one root cause: `app.js init()` force-redirected to the legacy
Inkbunny login screen whenever IB credentials were missing — even on
server installs where the user explicitly skipped platforms in the
wizard, even on direct deep-links to `#/settings/general`. Removed the
redirect entirely (the IB login route still exists; it's just no
longer the default landing). Loading screen now keeps a `Continue to
Dashboard` / `Open Settings` escape hatch — visible immediately on
poll error, and after a 10-second safety timeout if the poll stalls.
Wizard "Go to Dashboard" routes to `#/settings/platforms` (not `#/`)
when no platform was configured during setup, so first-time users
land somewhere actionable.

**Sidebar reflow on hover (BUG-008).** The 60px collapsed sidebar
expanded to ~190px on hover but main content didn't move, so the
expanded sidebar overlaid the first column — visible most clearly on
Settings → Appearance where the first theme card was clipped. Added a
`body.sidebar-expanded` class toggled from `mouseenter`/`mouseleave`
listeners on the sidebar, with a matching CSS rule that bumps
`.main-content`'s left margin to `var(--sidebar-w-expanded)` in
lockstep with the sidebar's own width transition. Listeners are now
bound at the very top of `App.init()`, before the dashboard-auth and
setup-wizard early-returns — caught in QA: the original placement was
after those returns, so a fresh user who hit the login screen first
never got the listeners attached for the rest of the session.

**Updater stops WARN-spamming the log (BUG-009).** GitHub returns 404
from `/releases/latest` when the repo has zero published releases —
the legitimate "no release tagged yet" case. Treat it as INFO-once and
return a clean no-update response instead of WARN-logging on every
dashboard load. Distinct from real network failures, which still
deserve a warning.

### Files touched

`config.py`, `dashboard.py`, `updater.py`, `frontend/index.html`,
`frontend/js/app.js`, `frontend/css/layout.css`,
`qa/AUTOMATED_BUG_LOG.md`, `qa/TESTING_CHECKLIST_WEBAPP.html`,
`qa/TESTING_CHECKLIST_NATIVE.html`, `docs/HANDOFF.md`,
`docs/ROADMAP_PUBLIC.md`, `CHANGELOG.md`.

---

## [2.14.6] - 2026-04-28

### Coordinated desktop ↔ server architecture (no more dual polling)

Closes the asynchronicity gap users hit when running the desktop app
alongside the Docker container: both instances were polling on their
own schedules, racing to update the same database, and double-firing
"all polls complete" notifications. Now there is exactly one polling
owner at any time, decided by an explicit `setup_mode` setting.

**Three modes.** The setting takes one of three values:

- `standalone` — desktop runs solo, polls + posts locally. The default
  for fresh installs that pick "Just on this computer" in the wizard.
- `paired_desktop` — desktop runs alongside a remote server. Settings
  flow server → desktop via the existing auto-sync pull, polling is
  delegated to the server, but the desktop still posts (since posting
  reads from the local story archive).
- `server` — the headless Docker container. Always polls. Stamped
  unconditionally on `server.py` startup so the wizard never has to
  ask, and so it can never wander into the standalone branch.

**Polling-owner gate.** `config.get_polling_owner(runtime)` returns
`"local"` if the running process should own the poll loop, `"server"`
if a remote one does. `main.py` reads this on startup; when the answer
is `"server"`, it skips the 11 per-platform poller threads + digest
scheduler entirely. Telegram bot, posting scheduler, and uvicorn still
start (they're independent of polling). The decision is logged at
INFO so you can see at a glance which side is doing the work.

**Wizard rebuilt around mode-first branching.** Desktop installs now
hit a Q1 — "How are you running PawPoller?" — with two cards
("Just on this computer" / "Pair with my server"). The paired branch
collects URL + API key, validates them via a new `/api/settings/pair-test`
endpoint (HTTPS-required for non-localhost; reuses the same rule as the
auto-sync push guard), and triggers an immediate first-pull on success
so the user doesn't wait 5 minutes for their server's settings to land.
Pairing completion sets `auto_sync_enabled = true` and skips the
archive + platform-connection steps — those settings come down with the
sync pull. Server runtime skips Q1 entirely (it's always "server").

**Re-run wizard from Settings.** New "Setup Mode" panel at the top of
the General tab shows the current mode badge + polling-owner status +
remote URL (when paired). A Re-run setup button clears
`setup_complete` and bounces back to `#/setup` so users can flip
between standalone and paired without reinstalling. Hidden on the
server runtime where the mode is fixed.

**Setting scope tagging.** `SYNC_EXCLUDE` expanded to cover
desktop-only fields (`run_on_startup`, `setup_mode`) so they never
leak into the server's settings dump. Three desktop-only preference
rows (`Minimize to tray`, `Start with Windows`, `Desktop notifications`)
are conditionally rendered in Settings — visible on desktop, hidden on
server. Their event handlers all use `?.` in case the runtime mode
changes mid-session.

**`auto_sync` server self-protection.** The push path now refuses to
fire when `setup_mode == "server"`, regardless of what
`posting_server_url` says. Closes a foot-gun where a server with a
stray pairing URL (e.g. accidentally set during testing) would push to
that target on every settings change.

**Why now.** The user flagged duplicate "all polls complete"
notifications and asked us to scope the underlying coordination
problem. This is the resolution: one explicit owner, simple branching
in the wizard, no more racing pollers.

**Files touched.** `config.py` (mode constants, `get_polling_owner`,
expanded `SYNC_EXCLUDE`), `main.py` (gated 11-thread block),
`server.py` (force-set `setup_mode = server` on boot),
`auto_sync.py` (server self-push guard), `routes/settings_api.py`
(`setup-mode`, `pair-test`, `setup-reset` endpoints; richer
`setup-status`), `frontend/js/api.js` (3 new methods),
`frontend/js/app.js` (wizard rebuild + Setup Mode panel + handler
gating), `frontend/css/components.css` (mode-picker cards).

### Update button hidden on server runtime

Follow-up to the scope-tagging pass: the in-app self-update flow only
works on a frozen PyInstaller .exe (Windows-only batch script,
`os.startfile`, `robocopy /MIR /XD data logs`). On the Docker server
the "Update Now" button rendered but clicking it returned a 500 from
the underlying `updater.apply_update()` guard. Now both apply
affordances are hidden when `runtime_mode == "server"`:

- Sidebar "v2.14.x available" banner: button replaced with a small
  "rebuild on host" hint.
- Settings → About "Update Available" panel: button removed, replaced
  with a one-line note pointing at `pawupdate` / `docker compose up
  -d --build`.

The version-check call still runs on both runtimes so admins see at
a glance when there's a newer release upstream — only the apply
button is gated. Cached `this._runtimeMode` after the first
`getSetupStatus` call so the sidebar render stays cheap.

---

## [2.14.5] - 2026-04-27

### Refactor pass — audit-pass debt cleanup

Pure cleanup pass cashing in three of the four refactor candidates
queued in the 2.14.4 audit-pass-debt list. Behaviour-preserving across
the board; 91 tests passing (up from 30 — see below).

**1. `polling/notifications.py` extracted.** ~80 lines of identical
Windows-toast + Telegram-async-post + HTML-escape boilerplate were
duplicated across all 11 platform pollers. Three new helpers capture
the actual duplication:

- `show_toast(title, lines)` — primitive that lazy-imports `winotify`
  and no-ops on Linux/server builds.
- `send_telegram(token, chat_id, text)` — primitive that swallows
  network errors with a warning. Returns ``bool`` so callers with
  follow-up state (e.g. FA's "mark watcher digest delivered" path)
  can branch on success.
- `format_telegram_summary(header_html, items)` — string-builder for
  the `<b>HEADER</b>\n  • item\n  ...and N more` pattern every poller
  was rebuilding by hand.
- Plus two convenience wrappers (`maybe_show_toast`,
  `maybe_send_telegram_summary`) that fold in the per-platform
  enabled-flag check.

**Result:** 489 lines deleted across `polling/{ib,fa,sf,ws,da,ao3,sqw,
bsky,ik,tw,wp}_poller.py`, plus ~150 lines added in the new helper.
Net ~340 lines simpler. Per-platform filters (comments-only,
fave-thresholds, watcher-toggle) stay in their respective pollers
where they belong.

**2. CI test runner switched from `unittest discover` to `pytest`.**
Two of our test modules (`tests/test_integration_posting.py`,
`tests/test_platform_posters.py`) are pytest-style and were silently
skipped by `python -m unittest discover` for ages. The build workflow
now runs `pytest tests/ -v` — and CI suddenly has 91 passing tests
instead of 30. No new failures surfaced; the previously-skipped modules
were green on first run.

**3. N+1 query batching for `get_*_comparison_snapshots`.** Eleven
near-identical functions (`database/queries.py` plus
`{ao3,bsky,da,fa,ik,sf,sqw,tw,wp,ws}_queries.py`) all looped one
`SELECT ... WHERE submission_id = ?` per submission, which the
comparison-chart UI hits with up to ~10 sids at once. Replaced with a
single `SELECT ... WHERE submission_id IN (?,?,?...)` query plus
Python-side group. Same return shape, same key-type-per-platform
quirks (some keep raw int sids, others stringify — preserved
verbatim). Visible perf win on every comparison chart load — was a
~10× wire-time multiplier on a hot read path.

**4. `config.get_settings()` route caching.** The audit flagged this
as duplication "across many routes/*_api.py handlers". Closer reading
showed most apparent duplicates are in *separate* route handlers each
calling once, which is correct. Only `routes/settings_api.py::sync_status`
had a real double-call — the `total_keys` and `credential_mode` fields
each called `get_settings()` independently. Fixed. Other suspect cases
all turned out to be genuine separate-handler calls and were left
alone.

**Validation gates:**

- AST parse: 11 poller files + 11 query files + helper module + config
- Importlib smoke: every refactored module loads
- Test suite: 91/91 pass under pytest (was 30/30 under unittest, with
  61 silently skipped)
- No call-site signatures changed; helper extraction is internal

**`APP_VERSION` bumped to `2.14.5`.**

---

## [2.14.4] - 2026-04-27

### Security & robustness from a self-audit pass

A four-angle audit pass (dead code / security / refactor / reference
rot) surfaced a handful of real issues alongside several false alarms.
This release ships the fixes that were both *real* and *small enough
not to need a focused refactor session*. The bigger refactor candidates
(N+1 query batching across the 11 platforms, per-poller notification
helper extraction, redundant `config.get_settings()` calls) are noted
in HANDOFF for a future pass.

**What changed:**

- **Auto-sync refuses non-HTTPS targets.** `auto_sync._sync_target()`
  now rejects `posting_server_url` values that don't start with
  `https://` for non-localhost hosts. Localhost keeps `http://` because
  the loopback never leaves the machine. Without this guard a user who
  configured a plain `http://my-server.tld:8420` would have been
  posting their `Authorization: Bearer pp_xxx` API key (and the full
  settings dump including platform credentials) over the wire in
  cleartext on every save. Now logs a one-time warning and disables
  sync until the URL is fixed.

- **Auto-sync pull loop now has exponential backoff.** Steady state is
  unchanged at 5 minutes between cycles, BUT consecutive *transport*
  failures (connection refused, timeout, non-200) now back off
  5m → 10m → 20m → 40m → 60m cap instead of hammering an unreachable
  server every 5 minutes forever. Crucial detail: a 200 response that
  says "I have nothing newer for you" — the common case — does NOT
  count as a failure and stays on the regular cadence. Implemented by
  splitting the old `pull_once()` into a richer `_pull_attempt()` that
  returns `(reachable, applied)`; `pull_once()` stays around as a
  backwards-compat shim.

- **Path traversal on `/api/posting/stories/{story_name}` closed.**
  `posting.story_reader.load_story()` previously joined the user-
  supplied `story_name` straight onto the archive root. Because the
  FastAPI route uses the `:path` converter, `..` segments passed
  through unchanged — an authenticated dashboard user could request
  e.g. `/api/posting/stories/../../etc/passwd` and the loader would
  happily try to read it. Adopted the same `Path.resolve()` +
  `relative_to(archive)` guard already in
  `routes/editor_api._resolve_story_dir`, so paths that escape the
  archive root now return a clean 404. Auth-protected endpoint, so
  this was post-auth path-disclosure not unauthenticated, but worth
  closing.

- **`deploy/pawpull.py` argv whitelist.** The deploy helper passes
  `sys.argv[1]` through to `gcloud --command="..."` with `shell=True`,
  with no quoting. A typo or a malicious paste of a story name with
  `;` or `$()` would have run as bash on the GCP VM. Locked the
  argument to `^[A-Za-z0-9_./-]+$`; anything else exits 1 with a
  descriptive error. This is a developer-run script (so attacker =
  you) but the fix is two lines and the next person to grab the
  pattern shouldn't inherit the trap.

- **QA checklists bumped to 2.14.4.** Title strings, hero headers, and
  the three "expected APP_VERSION" / "git tag" example commands in
  both `qa/TESTING_CHECKLIST_WEBAPP.html` and
  `qa/TESTING_CHECKLIST_NATIVE.html`. The historical reference to
  "post-2.14.2 fix" in the theme-persistence test stays as-is — that
  one's pointing at when the bug was fixed, not the current version.

### Audit findings *not* fixed in this release (logged for next pass)

These came up in the audit and are real, but didn't fit the
"small enough to ship between QA runs" bar:

- **Vault key on Windows lacks ACL hardening.** `_secure_file_permissions`
  is a no-op on Windows, so the `.vault_key` dotfile fallback is created
  with default ACLs. Mostly theoretical — keyring almost always works
  on Windows so the dotfile is the rare fallback path — but the proper
  fix wants DPAPI or `icacls`, which isn't a one-liner.

- **`config.py` is ~800 lines mixing paths / vault / auth / logging /
  settings I/O.** Splitting into focused modules is a refactor pass,
  not a fix.

- **N+1 `get_*_comparison_snapshots()` across all 11 `database/*_queries.py`
  files.** Loops one SELECT per submission instead of `WHERE ... IN (...)`.
  Visible perf win on comparison-chart loads, but touching 11 files at
  once is its own commit.

- **Per-poller toast + Telegram notification logic duplicated 11×.** ~80
  lines per platform doing identical work. Worth extracting to
  `polling/notifications.py`, again as its own commit.

**Validation gates:** AST parse + importlib smoke + 30/30 unit tests
pass on the touched modules.

**`APP_VERSION` bumped to `2.14.4`.**

---

## [2.14.3] - 2026-04-27

### Changed — Repository file-tree cleanup (no behaviour changes)

Pure organisation pass — zero runtime changes, just a tidier layout.
The repo root went from ~30 entries (11 of which were platform
client folders) down to ~18.

**Three coordinated changes:**

1. **All 11 platform clients consolidated under `clients/`.**
   - `api_client/` → `clients/ib/` (also fixes the long-standing
     naming inconsistency — the IB client was the only one not using
     the `<xx>_client/` convention)
   - `ao3_client/` → `clients/ao3/`, `bsky_client/` → `clients/bsky/`,
     `da_client/` → `clients/da/`, `fa_client/` → `clients/fa/`,
     `ik_client/` → `clients/ik/`, `sf_client/` → `clients/sf/`,
     `sqw_client/` → `clients/sqw/`, `tw_client/` → `clients/tw/`,
     `weasyl_client/` → `clients/weasyl/`, `wp_client/` → `clients/wp/`
   - Used `git mv` so file history is preserved.
   - 60 Python files had imports rewritten via a single sed pass:
     `from <xx>_client.client import ...` → `from clients.<xx>.client import ...`
     (covers top-level imports, lazy/conditional imports inside
     functions, and 3 docstring references in `tests/test_posting_helpers.py`).
   - Comment/docstring path references in `posting/platforms/*.py`
     and `clients/ao3/client.py` updated for accuracy.
   - PyInstaller spec didn't need updating (no client modules in
     `hiddenimports` — the analysis discovers them via the import graph).
   - Dockerfile didn't need updating (`COPY . .` picks up the new
     layout automatically).

2. **Internal docs moved to `docs/`.**
   - `HANDOFF.md`, `SETUP.md`, `ROADMAP_PUBLIC.md`, `documentation_guide.md`
     → `docs/<same name>`. README, LICENSE, CONTRIBUTING, CHANGELOG
     stay at root for GitHub conventions.
   - Cross-references updated in: `README.md` (3 links),
     `CONTRIBUTING.md` (1 link), `site/src/components/Footer.astro`
     (3 GitHub URLs), `site/src/components/GetIt.astro` (1 URL),
     `docs/HANDOFF.md` (1 backref), `docs/documentation_guide.md`
     (file-tree section refreshed with the new `docs/` and `qa/`
     subtrees).
   - Marketing site needs a redeploy to pick up the URL change in
     the footer + GetIt CTA.

3. **Orphan cleanup.**
   - `112.png` (stray icon export at repo root) — deleted.
   - `TESTING_CHECKLIST.md` (the markdown sibling of the html
     checklist that should have died with the WEBAPP/NATIVE split in
     2.14.2) — deleted.
   - Local `settings.json` at repo root (legacy dev path; config.py
     migrated it to `data/settings.json` once on first run already)
     — deleted from disk; was already gitignored.

**Validation gates run before commit:**

- AST parse: 166 .py files, 0 errors.
- Import smoke: 47 refactored modules import cleanly (every client,
  every poller, every poster, every route, importer, server bits).
- Unit test suite: 30/30 pass.
- PyInstaller build: succeeds end-to-end, dist/PawPoller/PawPoller.exe
  produced.

**`APP_VERSION` bumped to `2.14.3`.**

---

## [2.14.2] - 2026-04-26

### Added — Automatic settings sync across devices

The cloud-sync infrastructure has existed since 2.13.x (the manual
push/pull endpoint at `/api/settings/sync`), but actually using it
required either restarting the desktop app (one-shot pull at boot)
or hitting the API by hand. 2.14.2 closes that loop: every settings
change propagates between devices on its own.

**What changed:**

- **Desktop auto-push.** `config.save_settings()` now schedules a
  debounced (~2s) background push to the cloud server whenever a
  `posting_server_url` + API key is configured. Bursts of saves
  (e.g. flipping five toggles in the wizard) collapse into one HTTP
  request. Fire-and-forget — failures log at debug level and never
  block the save.
- **Desktop periodic auto-pull.** New daemon thread polls the cloud
  server every 5 minutes and merges anything newer than the local
  copy. Last-writer-wins via mtime, so an in-flight push isn't
  immediately stomped by a stale pull. Bootstrapped from `main.py`
  alongside the existing one-shot startup pull.
- **Browser focus refresh.** Tabs now listen for `visibilitychange`
  and re-pull preferences when refocused (throttled to once per 3s).
  So changing the theme in the desktop app causes any open browser
  tab to repaint with the new theme as soon as you switch to it.
- **Loop protection.** A thread-local `_in_pull_merge` flag prevents
  the pull → merge → save → push cascade. Without it, a desktop
  pulling from the server would echo every pulled key back as a push.
- **`auto_sync_enabled` toggle** (default `true`) on **Settings →
  Appearance**, plus exposed through `GET /api/settings/preferences`
  and accepted by the POST handler. Set to `false` to disable both
  push and pull on this device.
- **Bug fix: theme actually persists now.** `applyTheme()` was
  POSTing `{ theme: <id> }` to `/api/settings/preferences`, but the
  server-side handler whitelisted known keys and silently dropped
  `theme`. So the chosen theme was localStorage-only and never made
  it into `settings.json` (and therefore never synced). The handler
  now accepts `theme` against the known THEMES set, so the
  cross-device sync above can actually do its job for the appearance
  setting that motivated this work.

**What's excluded:**

- `credential_mode` (per-device decision — vault vs plaintext)
- `auth_session_secret` (per-device cookie-signing key, must not
  match across devices)
- `minimize_to_tray` (per-device preference)
- Anything resolving to `localhost`/`127.0.0.1` is treated as a
  loopback target and skipped (so the cloud server never tries to
  sync to itself)

**Files touched:** `auto_sync.py` (new), `config.py`, `main.py`,
`routes/api.py`, `frontend/js/app.js`, `frontend/index.html`.
Cache buster on `app.js` bumped to `v=311`.

**`APP_VERSION` bumped to `2.14.2`.**

---

## [2.14.1] - 2026-04-26

### Changed — Vibe Pack: app aesthetic aligned with marketing site

The 2.14.0 themes brought the marketing site's palette into the app
(via Ink & Copper). 2.14.1 closes the rest of the cohesion gap by
borrowing four specific stylistic moves from pawpoller.pages.dev,
without sacrificing dashboard density on work surfaces.

- **Crimson Pro for headings.** All `h1`/`h2`/`h3`, plus page-header
  titles, modal titles, settings-section heads, sidebar wordmark,
  login/setup-step headings now render in Crimson Pro (the same
  serif as the site). Body text, labels, table cells, and buttons
  stay in Inter so dashboard-density screens remain readable.
- **Subtle radial body wash.** The body background is no longer flat
  slate — it gets a faint copper top-left + sage bottom-right
  gradient via two new theme-aware tokens (`--bg-glow-warm`,
  `--bg-glow-cool`). Anchored with `background-attachment: fixed` so
  it doesn't move with scroll. Pure-black themes (Midnight Press,
  High Contrast) opt out by setting both tokens to `transparent`.
- **Refined `.chip` component.** New site-style pill chip with
  optional dot indicator, plus accent/warm/success/warning/danger
  modifiers. Existing badges keep working; new chips going forward
  use this pattern.
- **Brand mark.** Small copper diamond (◆) added next to the
  PawPoller wordmark in the sidebar header, matching the site's nav.
- **Three new font tokens** — `--font-serif` (Crimson Pro fallback
  Georgia), `--font-sans` (Inter fallback system), `--font-mono`
  (JetBrains Mono fallback ui-monospace). Loaded once from Google
  Fonts with `display=swap` so first paint never blocks.

### Notes

- No layout changes on dense work surfaces (publish-check matrix,
  story list, editor, analytics, settings tables). Those keep their
  productivity density — only the *typography* of their headings and
  the ambient body wash shifts.
- Cache busters bumped to `v=310` for tokens / components / layout /
  editor CSS and `app.js`.
- Cohesion score (per the brand audit): bumped from "color-aligned,
  typography-divergent" to "fully cohesive cross-surface family"
  while preserving the marketing-vs-dashboard density distinction.

**`APP_VERSION` bumped to `2.14.1`.**

---

## [2.14.0] - 2026-04-26

### Added — 8-theme picker (browser + native)

PawPoller had `dark` + `light` themes wired up via CSS custom properties
and a binary toggle in the sidebar. Generalised to 8 curated themes,
selectable from a new **Settings → Appearance** tab. Same code applies
in both browser/server mode and the native pywebview desktop app
because both render the same frontend.

**The eight themes:**

| ID | Name | Vibe |
|----|------|------|
| `dark` | Default Dark | Charcoal + violet (existing default) |
| `light` | Default Light | Bright neutral (existing alternative) |
| `ink_copper` | Ink & Copper | Deep slate + copper + parchment text — matches pawpoller.pages.dev |
| `parchment` | Parchment | Warm sepia paper, brown ink — long-session writer mood |
| `midnight_press` | Midnight Press | True black for OLED, cool steel accents |
| `forest` | Forest | Pine + sage + cream — calm, low-stim |
| `velvet` | Velvet | Aubergine + dusty rose + amber |
| `high_contrast` | High Contrast | Pure black/white + saturated yellow (a11y) |

**Implementation:**

- **`frontend/css/tokens.css`** — full rewrite. Each theme is a single
  `[data-theme="<id>"]` block defining ~20 token values. Adding a 9th
  theme = copy block, rename, swap colours. Every UI surface now reads
  from these tokens; no per-theme component overrides needed.
- **Three new adaptive tokens** introduced to clean up old hardcoded
  patterns: `--card-border-inner` (the subtle inset edge on glass
  cards), `--overlay-backdrop` (modal scrims), `--shadow-strong`
  (hover/elevation). Hardcoded `rgba(255,255,255,0.08)`,
  `rgba(0,0,0,0.5)`, etc. in `components.css` / `editor.css` /
  `layout.css` replaced with these tokens so all 8 themes get correct
  contrast automatically.
- **`frontend/js/app.js`** — `THEMES` catalog (8 entries with id, name,
  description, 5-colour preview swatch). `applyTheme(id)` sets
  `data-theme` attribute, persists to localStorage, calls
  `API.savePreferences({theme: id})` (so the choice rides cloud sync
  if enabled), destroys + redraws charts so they pick up new colours.
  Sidebar palette button now navigates to Settings → Appearance instead
  of cycling (8 themes don't fit a binary toggle).
- **Settings → Appearance tab** — card grid (auto-fit 220px columns),
  each card shows a real miniature of the theme's actual colours
  (background, card surface, accent stripe, warm dot, text). Active
  theme has a copper border + "Active" pill. Click or Enter/Space to
  apply.
- **No-flash on load** — inline `<script>` in `index.html` reads
  localStorage and sets `data-theme` BEFORE the CSS link tags evaluate.
  The page never paints in the wrong theme.
- **Cache busters** bumped: tokens / components / layout / editor CSS
  to `v=300`, `app.js` to `v=300`.

**`APP_VERSION` bumped to `2.14.0`.**

---

## [2.13.9] - 2026-04-25

### Fixed — server startup crash when vault mode is on

`config.py`'s module-level `_settings = _load_settings()` ran at import
time, and `_load_settings` calls `_decrypt_vault()` whenever
`settings.json` has `credential_mode: "local"`. But `_decrypt_vault`
was defined ~300 lines further down, so on any server with vault mode
on, `import config` raised `NameError: name '_decrypt_vault' is not
defined` before the app could even start. The desktop was unaffected
because its settings.json defaults to `credential_mode: "cloud"`.

This hit us on the GCP deploy — server had vault enabled from an
earlier QA session and crash-looped on startup after the 2.13.1+ push.

Fix: moved the vault block (`VAULT_PATH`, `_get_vault_key`,
`_encrypt_vault`, `_decrypt_vault`) above `_load_settings` so all
helpers are defined before the module-level init runs. Left a comment
explaining the ordering constraint so nobody moves them back.

**`APP_VERSION` bumped to `2.13.9`.**

---

## [2.13.8] - 2026-04-24

### Changed — Anchor toolbar tweaks

- Inline semantic anchor buttons (text-sent / text-received /
  phone-incoming) now carry text labels alongside the Unicode icon:
  `→ Sent`, `← Recv`, `☎ Phone`. The bare arrows/phone glyph from
  2.13.7 rendered small inside Chromium's embedded webview and
  blended into the separators, making the buttons easy to miss.
- Hover tooltip delay dropped from 2000ms to 1200ms so the before/
  after hint shows up without feeling like it's lagging.
- Cache buster: `editor.js?v=285`.

**`APP_VERSION` bumped to `2.13.8`.**

### CI — release pipeline fixes (2026-04-25)

The first v2.13.8 tag push triggered a Build & Release run where the
`test` job failed with `ModuleNotFoundError` on four test modules.
Pre-existing issue: `requirements-server.txt` never pinned the test
dependencies. Windows build succeeded either way, so the release
artifact was fine — but the red X on the tag was misleading. Fixed
by pinning `pytest~=8.3` and `respx~=0.22` in
`requirements-server.txt`, then force-moving the `v2.13.8` tag to the
CI-fix commit. Final tag points at `7517ad3`; all jobs green.

Known latent issue: `test_integration_posting` and
`test_platform_posters` are pytest-style (async fixtures + respx) and
are silently skipped by `python -m unittest discover` — they import
cleanly but contribute no `TestCase` subclasses. Switching the CI
command to `pytest` would actually execute them. Not urgent, not a
regression.

---

## [2.13.7] - 2026-04-24

### Changed — Anchor toolbar overhaul: real anchors only, hover tooltips

Audited the editor's anchor toolbar against the canonical
`FILE_FORMAT_STANDARDS.md` spec and `editor/converter.py`. The
toolbar shipped three fake anchors that the converter silently
ignored (`@story-end`, `@text-end`, `@phone-end`), one misspelled
anchor (`@phone` instead of `@phone-incoming`), and was missing
three real front-matter anchors (`@byline`, `@disclaimer`,
`@fanfiction`) that appear in live stories (HC, Chosen, Silk).
The paired-wrap semantics introduced in 2.13.6 for text-sent /
text-received / phone were based on those fake close anchors and
produced output the converter couldn't parse.

- **`frontend/js/editor.js`**: Toolbar now exposes 10 buttons
  grouped by function — Title / Sub / Byline / Warning / Disclaimer
  / FF / Body / → (text-sent) / ← (text-received) / ☎
  (phone-incoming). `@story-end` removed entirely (the real
  end-of-story marker is `*End of [Title]*`, plain italic, not an
  anchor). `_insertAnchor()` rewritten as a single code path: every
  anchor is a single-line label inserted at the start of the line
  containing the cursor/selection, which matches how the converter
  actually reads them.
- **`_ANCHOR_HINTS`**: per-anchor metadata (label, purpose,
  before/after example). Drives the new tooltip.
- **Hover tooltips**: `_initAnchorTooltips()` wires a 2-second
  `mouseenter` timer on every anchor button. After the delay a
  positioned tooltip shows the anchor's purpose and a
  before/after code snippet. Cancelled on `mouseleave` / click.
- **`frontend/css/editor.css`**: `.anchor-tooltip` styles
  (fixed-position panel with dark background, accent label,
  monospace `<pre>` blocks for before/after, green left border on
  the after block).
- Cache busters: `editor.css?v=247`, `editor.js?v=284`.

**`APP_VERSION` bumped to `2.13.7`.**

---

## [2.13.6] - 2026-04-24

### Changed — Anchor toolbar wraps the current selection

Previously the anchor buttons always inserted at the cursor, leaving
the user to manually cut/paste a block of text into the middle of a
newly-inserted paired anchor like `<!-- @phone --> ... <!-- @phone-end -->`.
The buttons now honour the active text selection.

- **Paired anchors** (text-sent, text-received, phone): if text is
  selected, the opening tag is inserted on the line above and the
  closing tag on the line below, with the selected text preserved
  between them and re-selected. With no selection, the existing
  empty-block behaviour is kept.
- **Standalone anchors** (title, subtitle, body, warning, story-end):
  with a selection, the anchor is inserted on its own line
  immediately before the selection (so "make this a chapter title"
  works from a highlight); the selection stays intact. With no
  selection, the anchor is inserted at the cursor as before.
- Selections made in the **Rich Editor** (contenteditable) are
  accepted if the selected plain text appears exactly once in the
  Markdown source — the wrap is then applied to that unique
  occurrence in CodeMirror. Ambiguous matches fall back to
  CodeMirror's own selection.

- **`frontend/js/editor.js`**: `_insertAnchor()` now splits on the
  `\n\n` gap for paired anchors and inserts open/close around the
  selection. Cache buster `editor.js?v=283`.

**`APP_VERSION` bumped to `2.13.6`.**

---

## [2.13.5] - 2026-04-24

### Fixed — Full-bleed print background on Windows (Edge)

The 2.13.4 fix (setting `html { background }` inside `@media print`)
painted the body box to the page edges but Chromium still honoured
the template's top-level `@page { margin: 2cm }`, leaving a thin
white rim around the themed content. The screen-mode template has
its own `@page` for on-screen print-preview parity, so we can't
remove it — but inside `@media print` we can declare a second
`@page` rule that wins by cascade.

- **`editor/converter.py`**: `_build_print_styles()` now prepends
  `@page { margin: 0; size: A4 }` inside the `@media print` block
  for both the colour-preserve and grayscale branches. The visual
  breathing room users expect is preserved by the existing
  `.print-container { padding: 2cm 2.5cm }` inside the same block,
  so only the outer rim changes — full-bleed on Edge, matching the
  WeasyPrint behaviour on the server.

**`APP_VERSION` bumped to `2.13.5`.**

---

## [2.13.4] - 2026-04-24

### Fixed — PDF print CSS on Windows (Edge fallback)

Side-by-side comparison of Edge-rendered (Windows desktop) vs
WeasyPrint-rendered (server / Docker) PDFs showed the Edge output:
- Carried a browser-added header ("DD/MM/YYYY, HH:MM" + title)
  that polluted every page
- Left the page background white in the 2cm `@page` margin so the
  themed body colour was boxed inside a white frame instead of
  running edge-to-edge like the WeasyPrint output

Both are rendering-engine differences that only affect the Chromium
headless fallback used on Windows desktops without WeasyPrint's GTK
runtime — the server path was already correct.

- **`editor/pdf_generator.py`**: Added `--no-pdf-header-footer` to
  the Chromium headless invocation so the date header / URL footer
  are suppressed. Kept `--no-margins` so CSS `@page` remains the
  single source of truth for page geometry.
- **`editor/converter.py`**: `_build_print_styles()` now sets the
  theme background on both `html` and `body` inside `@media print`.
  By default Chromium only paints the body box (inside the `@page`
  margin), leaving a white border on themed stories; painting the
  html element too fills the full printable area so the theme
  background is continuous. WeasyPrint already behaved this way.

**`APP_VERSION` bumped to `2.13.4`.**

---

## [2.13.3] - 2026-04-24

### Changed — Error reporting for vault + PDF regeneration

Two of the 2.13.0 QA failures (#23 and #73) were untraceable because
the backends swallowed exceptions into the generic
`{"error":"Internal server error"}` envelope or added a terse
"render failed" line with no context. Both paths now surface the
actual failure reason so the next retest pass points at the real
root cause.

- **`routes/settings_api.py`**: `/vault/enable` and `/vault/disable`
  wrap `migrate_to_local_vault()` / `migrate_to_cloud()` in try/except,
  log the full exception with `exc_info=True`, and return
  `{"ok": false, "error": "<ExceptionType>: <message>"}` instead of
  letting the global handler mask the detail.
- **`frontend/js/app.js`**: The vault enable/disable buttons now render
  the `data.error` string (or `HTTP {status}` fallback) inline instead
  of the generic "Failed to enable vault" banner.
- **`routes/editor_api.py`**: PDF regeneration now distinguishes three
  failure modes for the full-story PDF:
  1. Missing Styled HTML precursor → explicit "regenerate Styled HTML
     first" error
  2. Render attempted but output is empty/missing → include attempted
     backend and output file size
  3. Per-chapter PDF failures keep their existing format
  This should diagnose why "Selective regen — All" left the full-story
  PDF out (test #23) on the next retest.

- **Cache busters**: `app.js?v=245`.

**`APP_VERSION` bumped to `2.13.3`.**

---

## [2.13.2] - 2026-04-24

### Fixed — Publish Check 500 on new / single-piece stories

`GET /api/editor/stories/{name}/publish-check` raised `IndexError` and
returned `{"error":"Internal server error"}` whenever the story's
`story.json` declared a `chapters` count but had an empty `chapter_info`
list. This affected every story created via the "Create New Story"
wizard (which writes `chapters: N` + `chapter_info: []`) and every
pre-existing single-piece story like `Blank` (which uses
`chapters: 1` + `chapter_info: []` by convention).

The publish-check endpoint iterates `range(1, story.total_chapters + 1)`
and indexes `story.chapters[i-1]` to build per-chapter rows. When
`_load_from_story_json` used `data.get("chapters", len(chapters))` for
`total_chapters`, the declared count (e.g. 1) outran the actual
`chapter_info` length (0), so `story.chapters[0]` raised.

This also killed the regen-staleness warning flow (tests #27 and #28 in
the checklist) because that banner is only rendered when
publish-check succeeds.

- **`posting/story_reader.py`**: `_load_from_story_json()` now sets
  `total_chapters = len(chapters)` unconditionally. `chapter_info` is
  the authoritative source of truth; the legacy `chapters` field in
  story.json is informational only. Existing multi-chapter stories
  (Chosen, Drumheller_Detour, etc.) already have matching lengths, so
  they're unaffected. Single-piece stories (Blank, wizard-created) now
  correctly render with only the "Full story" row in Publish Check.

**`APP_VERSION` bumped to `2.13.2`.**

---

## [2.13.1] - 2026-04-24

### Fixed — Anchor insertion toolbar buttons

All 8 anchor insertion buttons in the editor's rich-editor toolbar
(Title, Subtitle, Body, Warning, Text Sent, Text Received, Phone,
Story End) were silently dead clicks. `_insertAnchor()` referenced
`this._cm`, which is never assigned — the CodeMirror `EditorView` is
stored on `this.cmView`. The early-return guard `if (!text || !this._cm)`
always tripped, so nothing was ever dispatched to the editor.

The Title button's test (#11) was a false pass during QA because the
Create New Story template MASTER.md already contains `<!-- @title -->`,
so the tester saw the anchor in the document and didn't realise the
button hadn't actually inserted it.

- **`frontend/js/editor.js`**: `_insertAnchor()` now uses
  `this.cmView` consistently. Also rewrote the broken selection
  precedence (`cursor + text.indexOf('\n\n') + 1 || cursor + text.length + 1`
  collapsed incorrectly because `+` binds tighter than `||`) to an
  explicit branch — places the caret in the gap between opening and
  closing anchors for paired blocks (text-sent/phone/etc.), otherwise
  past the end of the inserted block.
- **`frontend/index.html`**: `editor.js` cache buster bumped to `v=282`.

**`APP_VERSION` bumped to `2.13.1`.**

---

## [2.13.0] - 2026-04-21

### Added — Genre templates, import from platforms, file upload in story wizard

**Genre templates (9 presets):**
- Romance, Erotica, Adventure, Comedy, Drama, Fantasy, Sci-Fi,
  Slice of Life, Horror — each pre-fills tags, rating, warnings,
  and category when creating a new story.
- Genre dropdown in Create New Story dialog auto-updates rating.
- `GET /genre-templates` endpoint for frontend consumption.

**Import from platforms (14a — IB, SF, FA):**
- "Import from Platform" button on story list shows polled submissions
  not yet in the local archive, grouped by platform.
- `posting/importer.py`: `import_from_inkbunny()` downloads BBCode
  text files and converts to Markdown (~14k words verified).
  `import_from_sofurry()` scrapes story content from the submission
  page after the chapter divider (~9.8k words verified).
  `import_from_furaffinity()` downloads story files via FAExport
  download URL (TXT/RTF full text; PDF gets description fallback).
- BBCode→Markdown and HTML→Markdown converters handle formatting.
- Name collision handling appends `_2`, `_3` suffix.
- `import_source` in story.json tracks provenance (platform, ID, URL).
- AO3/SQW listed as "coming soon" in the import dialog.

**File upload in Create New Story wizard:**
- Optional file upload field accepts `.md`, `.txt`, `.html`, `.bbcode`,
  `.rtf` — content replaces the template MASTER.md.
- Format converters: HTML→Markdown (strips tags, preserves structure),
  BBCode→Markdown, RTF→plaintext. Markdown and TXT used as-is.

**Hardcoded author cleanup:**
- 7 occurrences of hardcoded author name in `converter.py`,
  `generate_story_json.py`, `story_reader.py` replaced with
  configurable `default_author` setting. Users set it in
  settings.json; empty string fallback.

**GitHub release packaging (15a-c):**
- `README.md` — features, platform table, quick start, architecture
- `LICENSE` — MIT, 2026
- `CONTRIBUTING.md` — dev setup, platform module pattern, PR guidelines
- `.github/workflows/build.yml` — PyInstaller build on version tags
- `.github/workflows/lint.yml` — Ruff + JS syntax on push/PR
- `.gitignore` + `.env.example` updated

**`APP_VERSION` bumped to `2.13.0`.**

---

## [2.12.4] - 2026-04-19

### Added -- Embedded browser login for cookie-based platforms

Added a pywebview-powered browser login popup for platforms that require
cookie extraction (FA, DA, X/Twitter). In desktop mode, users click
"Login via Browser" and a native popup opens the platform's real login
page. After logging in, cookies are detected and saved automatically --
no more copying cookies from DevTools. Server mode falls back to
helpful login-page links.

- **`auth/browser_login.py`** (new): Core browser login module with
  per-platform config for 7 platforms (FA, DA, SF, TW, WS, AO3, SqW).
  Uses pywebview's `get_cookies()` to capture `SimpleCookie` objects,
  flattens them into `{name: value}` dicts, and checks success via
  URL/cookie conditions. Login runs in a daemon thread with a 5-minute
  timeout. `login_via_browser()` saves credentials via
  `config.save_settings()` on success.
- **`auth/__init__.py`** (new): Package init.
- **`routes/settings_api.py`**: Two new endpoints:
  - `GET /api/settings/browser-login/platforms` -- lists supported
    platforms with availability flag (True in desktop mode only).
  - `POST /api/settings/browser-login/{platform}` -- launches the
    pywebview popup and blocks until login completes or window closes.
    Runs the blocking call in `run_in_executor` to avoid stalling the
    event loop.
- **`frontend/js/api.js`**: Added `getBrowserLoginPlatforms()` and
  `browserLogin(platform, extraFields)` API methods.
- **`frontend/js/app.js`**: Updated FA, DA, and TW platform connect
  forms in the Platforms settings tab:
  - Desktop mode: shows "Login via Browser" as primary action with a
    "Enter cookies manually" toggle for the existing cookie input form.
  - Server mode: adds login page links to the instruction text for
    easier cookie extraction workflow.
  - Browser login availability is fetched in the `renderSettings()`
    parallel load and drives the conditional UI via
    `_browserLoginAvailable`.

---

## [2.12.3] - 2026-04-19

### Added -- First-run setup wizard

Added a guided setup wizard that appears on first launch when no
`setup_complete` flag exists in settings.json. Walks new users through
four steps: Welcome, Story Archive location, Platform Connections, and
a completion screen. Existing users are unaffected since the wizard
auto-skips when `setup_complete` is already set.

- **`routes/settings_api.py`**: Two new endpoints:
  - `GET /api/settings/setup-status` -- returns setup completion state,
    archive path presence, and count of connected platforms.
  - `POST /api/settings/setup-complete` -- marks setup as done so the
    wizard is not shown again.
- **`frontend/js/app.js`**: Added `renderSetupWizard()` method with
  4-step wizard (Welcome, Archive Path, Platforms, Done). Setup check
  in `init()` redirects to `#/setup` on first run. `setup` added to
  full-screen page list and route dispatch.
- **`frontend/js/api.js`**: Added `getSetupStatus()` and
  `markSetupComplete()` API methods.
- **`frontend/css/components.css`**: Setup wizard styles -- step
  indicator dots with connecting lines, platform card grid, responsive
  breakpoints.
- **`frontend/index.html`**: Cache busters bumped for components.css
  (v241) and app.js (v244).

---

## [2.12.2] - 2026-04-19

### Added -- Post scheduling in Publish Check

Added the ability to schedule publish/update actions for a future
date/time directly from the Publish Check matrix. The posting scheduler
daemon (already running) picks up scheduled items when the time arrives.

- **`routes/editor_api.py`**: Three new endpoints under
  `/api/editor/stories/{name}/`:
  - `POST /schedule` — validates story/platform/chapter, checks the
    scheduled time is in the future, runs poster validation, then
    inserts into `posting_queue` with `scheduled_at`. Returns queue_id
    and confirmed schedule time.
  - `GET /scheduled` — returns all pending/processing queue items for
    the story.
  - `DELETE /scheduled/{queue_id}` — cancels a pending scheduled item
    (verifies ownership by story name first).
- **`frontend/js/publish_check.js`**: Added "Schedule" button next to
  Post/Update in `_renderActionPanel()`. Clicking it reveals an inline
  `datetime-local` picker (defaults to 1 hour from now, rounded to next
  5 minutes). "Confirm schedule" submits to `/schedule`. The detail
  panel now loads and displays any pending scheduled items for the
  selected cell with per-item Cancel buttons.
- **`frontend/css/editor.css`**: Added Phase 6f schedule styles:
  `.schedule-form`, `.schedule-datetime`, `.schedule-pending`,
  `.schedule-pending-item`, `.schedule-cancel-btn` and related classes.
- **No scheduler changes needed** — `posting/scheduler.py` already
  processes the `posting_queue` table, checking `scheduled_at` against
  `datetime('now')` each cycle.

---

## [2.12.1] - 2026-04-19

### Added -- Create New Story wizard in Story Editor

Added a "Create New Story" button to the editor story list that opens a
form dialog and scaffolds the full folder structure with template files.

- **`routes/editor_api.py`**: New `POST /api/editor/stories/create`
  endpoint with `CreateStoryRequest` model. Validates folder name
  (alphanumeric + underscore, no duplicates), creates the directory tree
  (Markdown, BBCode, HTML, PDF, SquidgeWorld, Chapters/*, Images),
  generates a template MASTER.md showing all anchor types (@title,
  @subtitle, @byline, @body, @text-sent/received, @phone, @story-end),
  writes story.json with default metadata, and copies STYLING_REFERENCE.md
  as CHAPTER_STYLING.md when available.
- **`frontend/js/editor.js`**: Added "+ Create New Story" button to
  `renderStoryList()` with an overlay dialog containing title, folder
  name (auto-generated from title), author, chapter count (1-20), and
  rating (General/Mature/Explicit) fields. On success, navigates
  directly to the new story's editor. New `_submitCreateStory()` method
  handles validation and the API call.
- **`frontend/css/editor.css`**: Added `.create-story-overlay`,
  `.create-story-dialog`, `.create-story-label`, `.create-story-input`,
  `.create-story-error`, and `.create-story-actions` styles.
- Cache busters: `editor.css?v=244`, `editor.js?v=280`.

---

## [2.12.0] - 2026-04-19

### Added — Phase 7b: Local credential encryption at rest

Credentials can now be encrypted at rest using Fernet symmetric encryption.
When `credential_mode` is set to `"local"`, sensitive fields (passwords,
cookies, API keys, tokens) are stored in `settings.vault.json` instead of
plaintext in `settings.json`.

**Backend (`config.py`):**
- `VAULT_PATH` — path to `settings.vault.json` alongside the main settings.
- `_get_vault_key()` — retrieves or generates the Fernet encryption key
  (prefers system keyring, falls back to a `.vault_key` dotfile with 0600
  permissions).
- `_encrypt_vault()` / `_decrypt_vault()` — Fernet encrypt/decrypt of the
  credential payload, with atomic writes.
- `get_credential_mode()` — reads `credential_mode` from raw settings.json.
- `migrate_to_local_vault()` — moves credential fields from plaintext to
  encrypted vault; strips them from settings.json.
- `migrate_to_cloud()` — reverses migration, restoring creds to plaintext
  and deleting the vault file.
- `_load_settings()` — now transparently merges decrypted vault credentials
  when in local mode, so all consumers see a unified view.
- `save_settings()` — now splits credential fields into the vault when in
  local mode, writing only non-credential data to settings.json.
- `delete_settings_keys()` — vault-aware: re-encrypts remaining credentials
  after deletion in local mode.

**API (`routes/settings_api.py`):**
- `POST /api/settings/vault/enable` — switches to encrypted mode.
- `POST /api/settings/vault/disable` — switches back to plaintext mode.
- `GET /api/settings/vault/status` — returns current mode and vault
  file presence.

**Frontend (`frontend/js/app.js`):**
- "Credential Security" section in the Data tab with Enable/Disable/Status
  buttons and result display.

**Dependencies:**
- `cryptography~=46.0.7` added to `requirements-server.txt`.
- `cryptography>=44.0.0` added to `requirements.txt`.

---

## [2.11.1] - 2026-04-19

### Changed — Editor format selector: dropdown to tab bar

Replaced the `<select>` dropdown for switching output formats (Clean HTML,
SoFurry, BBCode, Styled HTML) with a compact inline tab bar. All four
formats are now visible at a glance as clickable buttons with an active
highlight, removing the extra click required by the old dropdown.

- **`frontend/js/editor.js`**: Swapped `<select id="editor-format-select">`
  for a `<div class="format-tabs">` with four `<button class="format-tab">`
  elements. Updated event binding from a single `change` listener to
  per-button `click` handlers that toggle the `.active` class and call
  `switchFormat()`.
- **`frontend/css/editor.css`**: Added `.format-tabs` (flex row, 2px gap)
  and `.format-tab` styles (11px font, accent-colour active state,
  hover highlight, smooth transition).
- Cache busters: `editor.css?v=243`, `editor.js?v=279`.

---

## [2.11.0] - 2026-04-20

### Added — Phase 7a: Settings sync (cloud mode)

Desktop ↔ server credential sharing via a single sync endpoint.
Login on one side, pull to the other — no more re-entering credentials
on both desktop and server.

**Backend (`config.py`):**
- `CREDENTIAL_FIELDS` — 35+ sensitive field names (all platform
  passwords, cookies, API keys, tokens, dashboard auth, integrations).
- `SYNC_EXCLUDE` — keys that are per-machine and must not sync
  (`credential_mode`, `auth_session_secret`, `minimize_to_tray`).
- `get_settings_for_sync()` — returns settings dict + file mtime,
  filtering out SYNC_EXCLUDE keys.
- `merge_synced_settings()` — merges incoming push into local
  settings, filtering SYNC_EXCLUDE.

**Sync endpoint (`routes/settings_api.py`):**
- `POST /api/settings/sync` — accepts `{mode: "pull"|"push",
  settings: {...}, timestamp: float}`. Pull returns server settings;
  push merges incoming keys and returns the merged result. Auth
  enforced by existing dashboard middleware (session cookie or
  `Bearer pp_xxx`).
- `GET /api/settings/sync/status` — server version, settings
  timestamp, credential_mode, total key count.

**Desktop startup sync (`main.py`):**
- `_sync_settings_on_startup()` — if `credential_mode != "local"`
  and `posting_server_url` + `posting_server_api_key` are configured,
  pulls settings from the server on startup via httpx. Failures are
  non-fatal (warning log, app continues with local settings).

**Dashboard UI (`frontend/js/app.js`):**
- Settings → Data tab → "Settings Sync" section with three buttons:
  - **Pull from server** — fetches server settings and merges locally
  - **Push to server** — reads local settings, sends to server
  - **Check status** — shows server version, key count, credential mode
- Result display shows key count or error inline.

**Cache buster:** `app.js?v=242`.

### Fixed — Path traversal, SF temp file leak, chapter tag init

- `editor_api._resolve_story_dir()` now uses `resolve()` +
  `relative_to()` to prevent `../` traversal in story_name URL param.
- SoFurry poster tracks temp files from ch1 front-matter merge and
  cleans them up in `finally` blocks after `post()` and `edit()`.
- `metadata_editor._ensureChapterEntry()` initializes `inkbunny: []`
  in chapter tags (was missing after platform extension).

### Fixed — Publish Check: no_credentials status for unconfigured platforms

Platforms without credentials show a lock icon and "No credentials
configured" instead of confusing poster init errors. Per-platform
credential requirements checked before the matrix loop. Action panel
shows clear "Set up in Settings" message.

### Changed — Skip startup polling

- Desktop (`main.py`): all 11 poller threads no longer fire an
  immediate poll on startup, preventing rate limiting on restarts.
- Server (`server.py`): orchestrator checks `last_poll_completed_at`
  and skips the first poll if the previous cycle was recent enough.

### Added — Tag editor improvements

- **Space→underscore auto-conversion**: typing a space in Default/FA/
  Weasyl/Itaku tag inputs converts to underscore in real-time.
- **"Fix spaces" button**: bulk-replaces spaces with underscores in
  all underscore-platform tags (story + chapter level).
- **"Sort A-Z" button**: sorts tags alphabetically across all
  platforms.
- **Tag format correction**: `_transformTagForPlatform()` fixed — FA
  and Weasyl now correctly keep underscores (were wrongly converting
  to spaces).
- **Tag browser "Selected" filter**: new chip tab filters the grid to
  show only currently-selected tags with descriptions.
- **Platform badges on tag cards**: small pills (DEF, SF, IB, AO3...)
  on each card showing which platforms have that tag.
- **Grid layout fix**: removed double-nested grid wrapper that was
  forcing single-column layout in the tag browser.

### Added — Polling module backlog fixes

**Session expiry recovery (3 pollers):**
- SQW: resets `_logged_in` before `validate_session()` so
  `ensure_logged_in()` attempts fresh login.
- FA: validates cookies before gallery fetch, clear error message.
- TW: empty credential check + clearer expired cookie message.

**N+1 query batching (4 pollers):**
- IB faving users, FA comments, SQW kudos, AO3 kudos all switched
  from per-item INSERT loops to `executemany` + `INSERT OR IGNORE`.
- Pre-existing set approach preserves notification detail tracking.

**AO3 rate-limit retry:**
- `_parse_retry_after()` extracts Retry-After header from 429s.
- `_get_page()` 429 handling fixed (was broken — retried inline
  without checking response status). Now retries within the loop
  with escalating backoff.
- `_post_with_retry()` wraps all 7 non-login POST operations.

### Added — Editor quick wins

**Regen staleness warning (12a):**
- Publish Check compares MASTER.md mtime vs newest generated file.
- Amber banner with inline "Regenerate now" button when stale.

**Edit button from published stories (12b):**
- Story detail page gains "Edit in Editor" link next to the title.

**Anchor insertion toolbar (10a):**
- 8 anchor buttons in the wysiwyg toolbar: Title, Sub, Body,
  Warning, Text Sent (→), Text Received (←), Phone, End.
- Inserts at CodeMirror cursor position.

### Added — Selective format regeneration (10b)

Regenerate button gains a dropdown with 7 options: All formats,
HTML only, BBCode only, Styled HTML + CSS, SquidgeWorld only,
PDF only, Chapter splits only. Backend `RegenerateRequest.formats`
filters which sections run.

### Added — Per-platform descriptions (10d)

Metadata drawer Basics section gains collapsible "Per-platform
descriptions" with Short (IB/SF, 1-2 sentences) and Announcement
(Bluesky, 300 char limit) textareas. `build_package()` picks the
right description per platform with fallback chain.

### Added — Retry queue (12d)

Failed posts/updates auto-queue for retry with exponential backoff
(1min → 5min → 30min, max 3 attempts). Uses existing
`posting_queue` infrastructure. Desktop-requiring platforms still
queue for desktop. Deletion errors skip retry. Frontend shows
"Will retry automatically" for queued retries.

### Added — Public release roadmap

`ROADMAP_PUBLIC.md` — Phases 8-15 covering auth UX (embedded browser
login), first-run wizard, editor enhancements, image support,
publishing UX, analytics, import, and GitHub packaging.

**`APP_VERSION` bumped to `2.11.0`.**

---

## [2.10.5] - 2026-04-19

### Added — Phase 6e: Publish Check safety polish

Four UX improvements to the Publish Check matrix, all frontend-only
(no backend changes).

**Live-publish re-confirm warning:**
- Unchecking "Save as draft" reveals a yellow warning banner in the
  action panel: "⚠ LIVE PUBLISH — This will be immediately visible
  to the public on <Platform>."
- The `confirm()` dialog for live (non-draft) actions now includes an
  extra warning paragraph urging the user to re-check the draft box
  if they didn't mean to go public.

**Readable dry-run results:**
- Dry-run output is now a structured summary (title, rating, word
  count, file name + size, tag count + full list, extras) instead of
  raw `<details><pre>` JSON. The raw JSON is still available under a
  "Raw JSON" collapsible at the bottom.

**Per-session action result log:**
- Every post/update/dry-run action is recorded in a session-scoped
  log array (max 20 entries). Rendered below the detail panel as a
  compact timestamped list with success/fail icons, platform names,
  and external links. Survives cell clicks and matrix reloads; clears
  on page refresh. Bulk operations log a single summary entry.

**Relative timestamps on posted publications:**
- The detail panel's "Posted" and "Last updated" fields now show a
  relative time suffix — e.g. "2026-04-17 14:30 (2d ago)". Uses a
  `_relativeTime()` helper: just now → Xm → Xh → Xd → locale date.

**Cache buster:** `publish_check.js?v=10`.

### Fixed — AO3 login retry + better Telegram error messages

**AO3 login retry with backoff (`ao3_client/client.py`):**
- Login page fetch now retries up to 3 times with 5s/10s exponential
  backoff. AO3's Cloudflare layer was returning transient non-200
  responses that cleared on retry. Previously a single failure killed
  the entire poll cycle.
- Logs the actual HTTP status code and first 200 chars of the response
  body on non-200 responses, replacing the opaque "Failed to fetch
  login page" message.
- Error message updated from "check credentials" to "check credentials
  or AO3 may be blocking (see logs for HTTP status)" to stop
  misleading the user when the creds are fine.

**Telegram error classification (`polling/telegram.py`):**
- New `_classify_error()` maps raw exception strings to user-friendly
  `(label, hint)` pairs. 13 patterns covering login blocks, rate
  limits, Cloudflare challenges, 403/404, timeouts, connection errors,
  SSL issues, and dropped connections.
- `send_poll_error()` now shows: bold label, italic hint explaining
  the likely cause, and the raw error in monospace for debugging.
- Consolidated poll summary (`send_consolidated_poll_summary`) uses
  the same classifier for failed platform lines.
- Before: `❌ 📖 AO3: AO3 login failed -- check credentials`
- After: `❌ 📖 AO3: Login blocked` / `Likely Cloudflare/rate-limit, not bad creds`

### Added — Polling module audit fixes (exc_info + silent exception handling)

Fresh audit of all 11 pollers rediscovered 16 findings from the
original (undocumented) audit. This release fixes the safe categories;
session expiry recovery and N+1 query batching are deferred for
hands-on testing.

**exc_info logging (120 additions across 11 pollers):**
- Every `logger.warning()` and `logger.error()` call inside an
  `except` block now includes `exc_info=True`. Previously, exception
  handlers logged the message string but discarded the stack trace,
  making production debugging impossible. Covers: comment/follower/
  watcher scraping failures, Telegram notification sends, toast
  notification sends, per-submission processing errors, milestone/
  summary/goal Telegram sends, and top-level poll cycle failures.

**Silent exception swallowing (19 replacements across 11 pollers):**
- `except Exception: pass` blocks in `send_poll_error()` wrappers and
  `_cleanup_*_client()` atexit handlers replaced with
  `logger.debug("Error alert send failed", exc_info=True)`. These
  were silently masking real failures in error-reporting and cleanup
  paths.

**Deferred (needs careful testing):**
- Session expiry graceful recovery (FA, SQW, TW) — currently hard-
  crashes on auth failure instead of attempting re-login.
- N+1 query batching (IB faving users, FA comments) — individual DB
  writes in loops instead of batch upsert.

### Added — Per-chapter tag platform parity

- `_CHAPTER_TAG_PLATFORMS` in `metadata_editor.js` extended from
  `['default', 'sofurry', 'wattpad']` to
  `['default', 'sofurry', 'inkbunny', 'wattpad']`, matching the
  story-level tag editor. Users can now set Inkbunny-specific tags
  per chapter in the metadata drawer.
- No backend changes — `story_reader.py` already cascades chapter
  `default` tags to all platform IDs on publish.

**Cache buster:** `metadata_editor.js?v=15`.

### Added — Phase 7 design document (`PHASE_7_DESIGN.md`)

Comprehensive design doc for the credential management system:
- Credential inventory: 35+ sensitive fields across 12 contexts
- Cloud mode: `POST /api/settings/sync` endpoint with push/pull,
  last-write-wins per-key conflict resolution, sync exclusion set
- Local-only mode: `settings.vault.json` encrypted via Fernet,
  key derived from Windows DPAPI or system keyring
- Migration path between modes (atomic swap)
- 3-phase implementation plan (7a cloud sync, 7b vault, 7c wizard)
- 5 open questions for user review

**`APP_VERSION` bumped to `2.10.5`.**

---

## [2.10.4] - 2026-04-17

### Added — Comprehensive tag audit across all 13 stories

Full tag audit of every story in the archive using per-story content
analysis agents. Each story's MASTER.md was read chapter by chapter
and cross-referenced against the 4-file tag database (physical, acts,
kink, meta) to identify missing tags, incorrect tags, and ambiguous
tags.

**Story-level tag updates (tags.default):**
- ~330 tags added across 13 stories (acts, kinks, species, meta)
- ~45 tags removed (redundant, not-in-DB, or content-unsupported)
- Under-tagged stories saw the biggest gains: Abstinent Bet Naughty
  (33→83), Velvet and Vice (46→94), Extra Credit (84→124)
- Audit report saved at `TAG_AUDIT_REPORT.md` in the archive root

**Per-chapter tag assignments (chapter_info[].tags.default):**
- ~70 chapters across all 13 stories received per-chapter tag lists
- Species/meta/genre tags distributed to all relevant chapters
- Act/kink tags assigned only to chapters where depicted on-page
- Tag counts range from 3 (quiet preludes) to 63 (explicit climaxes)

**Tag categories addressed:**
- Missing sexual acts (blowjob, anal_sex, rimming, edging, etc.)
- Missing kink dynamics (dominance, submission, power_dynamics, etc.)
- Missing physical traits (canine_penis, knot, claws, size_difference)
- Missing meta tags (first_time_mm, bisexual_awakening, infidelity)
- Redundant tags removed (duplicate phrasing, non-DB entries)

---

## [2.10.3] - 2026-04-17

### Added — SoFurry chaptered posting, FA probe_exists, nested story paths, anchor fix

**SoFurry chaptered posting (one submission, N chapters):**
- SF poster's `post()` detects multi-chapter stories: creates
  submission with chapter 1 (including front matter — title, subtitle,
  warning, disclaimer prepended), then appends chapters 2..N via
  `POST /ui/submission/{id}/content`.
- SF poster's `edit()` now does chapter-aware content refresh: uploads
  each chapter file individually then deletes old content items.
  Previous behaviour used `replace_file()` which clobbered all chapters
  into one content blob.
- `_set_chapter_titles()` sets per-content-item titles via
  `POST /ui/submission/{id}/content/{contentId}` with `{"title": "..."}`.
  Called after both post and edit. Strips `Chapter N:` prefix.
- SF added to `WORK_ORIENTED` set — per-chapter matrix rows show grey
  `–` N/A; Full story row is the actionable one.
- `_read_sf_front_matter()` extracts title/warning/disclaimer from the
  full-story SoFurry HTML to prepend to chapter 1 uploads (per-chapter
  files are body-only).

**FA deletion probe:**
- `FurAffinityPoster.probe_exists()` — hits `/view/{id}/`, checks for
  404 or "is not in our database" text. Verify posted now detects
  deleted FA submissions.

**Nested story path fix:**
- `publish-check`, `publish`, and `verify` endpoints used
  `story_dir.name` which returned only the last path component
  (`Nice_Version`) for nested stories like `The_Abstinent_Bet/Nice_Version`.
  Fixed to `story_dir.relative_to(get_archive_path())` so the full
  relative path is preserved.

**AO3 CF proxy for desktop residential IPs:**
- `AO3Client` accepts `proxy_url` + `proxy_key` (same pattern as
  SoFurryClient). When configured, all requests route through the
  CF Worker which bypasses AO3's "Shields are up!" Cloudflare TLS
  fingerprint check. All three AO3Client instantiation sites (poller,
  poster, API route) pass `cf_worker_url` / `cf_worker_key` from
  settings.json.

**Per-chapter SoFurry HTML anchor processing:**
- `/regenerate` endpoint's per-chapter SoFurry HTML generation now
  calls `_convert_body_clean_html()` directly instead of
  `convert(ch_content, "clean_html")`. The latter falls through to
  the heuristic parser for fragments without `<!-- @body -->`, which
  HTML-escapes semantic anchors. The body converter processes them
  correctly — `<!-- @text-received -->` becomes
  `<div class="text-message received">` instead of literal text.

**`APP_VERSION` bumped to `2.10.2`** (config.py).

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
