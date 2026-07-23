# Gap Wave 3 — persona defaults · benchmark analytics · best-time-to-post · threads (G8)

**Status:** SPEC — building now · **Author:** Rhys + Claude (fable) · **Date:** 2026-07-24

> Wave 3 off the gap analysis (everything through G7 + G3 shipped in 2.176–2.183). Three scout passes grounded this
> spec. Build order: persona defaults → analytics insights (benchmark + best-time share one endpoint) → threads.

## 1. Per-persona posting defaults

**What:** a persona carries server-side defaults — platforms, rating, preferred posting time — synced desktop↔server,
instead of the browser-local quick-publish preset being the only memory.

- **Schema:** plain additive columns on `personas` (the codebase's established pattern, ~15 precedents; NOT a JSON blob,
  NOT settings keys — settings.json is a global singleton that doesn't sync): `default_platforms TEXT ''` (CSV of
  codes), `default_rating TEXT ''`, `preferred_post_time TEXT ''` ("HH:MM" local). Guarded ALTERs in db.py +
  `ensure_personas_table`.
- **Plumbing:** `create_persona`/`update_persona` whitelist (`personas.py` ~:61/:72), **sync manifest tuple + upsert**
  (~:148/:169 — with absent-key tolerance for old clients), `PersonaCreate`/`PersonaUpdate` + patch handler
  (`settings_api.py` ~:599-668).
- **UI:** persona detail page (`accounts.js` `renderPersonaDetail`) gains a "Posting defaults" card: platform
  checkboxes, rating select, time input.
- **Consumers (v1, scope-disciplined):** Quick Publish only — seed rating/off-platforms from the persona when no
  localStorage preset exists (localStorage stays as a per-browser override), and `_defaultScheduleLocal` uses the
  persona's preferred time (tomorrow at HH:MM) instead of hardcoded now+1h. Posts compose + the full artwork form have
  no persona context — not wired v1.

## 2 + 3. Analytics insights — benchmark + best-time (one endpoint)

**What:** `GET /api/analytics/insights?tz_offset=<minutes>` → one pass over the 17 submission tables (reusing
`analytics_queries._metrics` normalization — consolidating, not minting a 5th platform map):

- **Benchmark:** per-platform median views/faves/comments per piece; top-5 overperformers (piece views ÷ its
  platform's median, min 5 pieces on the platform); best platform by median.
- **Best-time:** weekday + hour-of-day histograms of median engagement per post, bucketed server-side with the
  client's tz offset applied. Honesty rules: per-bucket post counts returned (frontend greys < 3); **SQW/AO3 are
  date-only → weekday histogram only**; FA's scraped human-readable date gets a best-effort parse (skip on failure);
  unparseable rows dropped, never guessed.
- **UI:** Analytics page gains "Benchmarks" (overperformer table + platform medians) and "When your audience responds"
  (two bar rows: weekday, hour — n= counts shown).

## 4. Threads (G8) — multi-part posts on Bluesky + Mastodon

**What:** compose a thread in Posts; each part publishes as a reply to the previous, reusing the G3 reply plumbing
(bsky `create_post(reply={root,parent})` returns uri+cid; mast `create_status(in_reply_to_id)` returns id).

- **Model — child rows** (fits every existing table): `parent_post_id INTEGER NOT NULL DEFAULT 0` + `thread_ordinal`
  on `posts` (guarded ALTER + posts_schema.sql). Each part is a full post row → `post_media` and
  `post_publications` (UNIQUE per post_id) work unchanged, and each part records its own external_id/url.
- **Scope v1:** part 1 carries media; **parts 2+ are text-only** (sidesteps the compose module's singleton file
  state). **bsky + mast chain; every other platform posts part 1 only** and the result carries a "threads
  unsupported here" note. X deferred (rotating-query-ID fragility). Scheduled threads work free: the queue row
  points at the parent; the publisher walks children.
- **Publisher:** `publish_post` loads children; per platform posts sequentially — bsky keeps `{uri, cid}` per part
  (root = part 1, parent = previous; the client already returns cid, `_publish_one` just dropped it); mast passes
  the previous part's id + a **per-part idempotency key** (`pp-{post_id}-p{ordinal}-mast` — the current per-post key
  would dedupe parts). One publication row per part per platform.
- **Compose:** "+ Add part" → extra textareas with per-part counters against a new `_PLAT_LIMITS` map
  (bsky 300 / mast 500); parts ride the create payload as a JSON array; feed shows a 🧵 N-part badge on parents
  (`list_posts` filters `parent_post_id = 0`, attaches part counts).

**Tests:** persona defaults round-trip + manifest sync tolerance; insights bucketing/median math on seeded rows
(incl. date-only + unparseable timestamps); threads — create-with-parts, feed filtering, and a publisher chain test
with monkeypatched clients asserting part 2 carries part 1's refs (the core correctness property).

**Ship:** 2.184.0, one release, full suite pre-deploy.
