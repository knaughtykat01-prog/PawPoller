# PawPoller Session Handoff

**Last updated:** 2026-07-05
**Current version:** 2.51.8 — **Fix: "forget publication" 500 (FK constraint) + clearer AO3 expired-session error.**
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
