# SoFurry "beta" API map (2026-06, post-rewrite)

> ## ⚠ SUPERSEDED FOR WRITES — an OFFICIAL API now exists (found 2026-08-07)
>
> SoFurry shipped a public API at **`https://api.sofurry.com`** (docs:
> `developer.sofurry.com/dev-docs` — note it **403s a bot User-Agent**, send a browser one).
> Auth is a bearer **Personal Access Token**. Everything in the "new posting API" section
> below — the Laravel login, the OAuth2-PKCE bridge, `X-CSRF-Token`, `/api/upload-create`,
> `/api/upload-content`, `/api/submission-editor` — should migrate to it. See §"Official
> API (v1)" at the foot of this file and backlog row `SFAPI`.
>
> **This document is NOT obsolete.** The official API is a *write* API with **no
> per-submission stats and no follower counts**, so the analytics half documented here —
> `/s/{id}.data`, `/api/profile`, `/api/followers` — remains the only source for those and
> must be kept. Those three are login-free, which is why the PAT can still replace the
> entire authenticated-session stack.

Reverse-engineered 2026-06-23 from the live site (read-only probes + the Remix
client bundle). This is the reference for rebuilding **SF posting**; polling was
already fixed in 2.27.2.

## Architecture: hybrid Laravel + Remix

`sofurry.com` is now **two stacks behind one host**:

- **Laravel (legacy)** still serves **auth**: `GET/POST /login` returns a real
  `<form method="POST" action="https://sofurry.com/login">` with a hidden
  `name="_token"` field, sets `XSRF-TOKEN` + `sofurry_session` cookies (Laravel
  `encrypt()` blobs), and a `<meta name="csrf-token">` (40-char Laravel CSRF).
  It loads the classic uploader assets (TinyMCE/plupload/croppie) — but that UI
  is legacy; new uploads go through Remix (below).
- **Remix / React-Router (new)** serves **browse + the new API**. Any `/api/*`,
  `/s/:id`, `/s/:id/edit`, `/u/:handle/gallery`, `*.data` path is Remix. Hitting a
  non-route (e.g. `/ui/submission`) returns the Remix "Oops - SoFurry" 404 page
  with header `x-remix-response: yes`. **The entire old `/ui/submission*` API is
  dead** — Remix intercepts `/ui/*`.

### Two logins
| Path | Remix route id | What it is |
|---|---|---|
| `/login` | `routes/login.legacy` | the legacy Laravel form (still live, still sets `sofurry_session`) |
| `/fe/auth/login` | `routes/login` | the new canonical login |
| `/fe/auth/sofurry`, `/fe/auth/callback` | `routes/auth.*` | OAuth-style callback flow |
| `/logout` | `routes/logout` | |

### Authenticated `/api/*` session — SOLVED (live-tested 2026-06-23)
Legacy `/login` authenticates the **Laravel** session (`sofurry_session`) but that
alone returns 401/500 on the Remix `/api/*`. You must then run a **server-side
OAuth2-PKCE bridge** to mint an authenticated **Remix** `_session`:

1. `GET /login` → scrape hidden `name="_token"`.
2. `POST /login` with `_token,email,password,remember=on` → 302 to `/home` (a 404 in
   Remix, harmless); sets `sofurry_session` + `remember_web_*` (success markers).
3. **`GET /fe/auth/sofurry`** (follow redirects). Because the Laravel session is
   already authed, `/oauth/authorize?...client_id=a13e8c19-...&scope=profile` (PKCE,
   `code_challenge_method=S256`) auto-approves → `/fe/auth/callback?code=…` → sets an
   **authed `_session`** (+ `oauth2:*`, `sf_sfw`) and lands on `/`.
4. Now every authed endpoint returns 200 (`GET /api/upload-quota` →
   `{"remaining":N,"isExempt":false}` is the cheap auth check).

A single shared `httpx`/cookie jar carries Laravel + Remix cookies through all of it.
If creds use 2FA the POST redirects to `/auth/2fa` — not handled yet.

## The new posting API (all Remix `/api/*`)

| Purpose | Method + path | Old (dead) equivalent |
|---|---|---|
| Form options (categories/types/limits) | `GET /api/upload-config` *(public)* | hardcoded ints |
| Upload quota | `GET /api/upload-quota` *(auth; 500 unauth)* | — |
| **Create submission** | `POST /api/upload-create` (multipart FormData) | `PUT /ui/submission` |
| **Upload story file/content** | `POST /api/upload-content` (multipart FormData) | `POST /ui/submission/{id}/content` |
| **Edit metadata** | `POST /api/submission-editor` | `POST /ui/submission/{id}` |
| Submission JSON (read) | `GET /api/submission/:id` *(public for published)* | `GET /ui/submission/{id}` |
| Folders | `GET /api/folders` | — |
| Tag autocomplete | `GET /api/search-tags` | — |
| Delete content | `POST /api/upload-content` with `_method=DELETE` override | `DELETE /ui/submission/{id}/content/{cid}` |

### Request shapes (from `upload.mass-*.js` + `submission._id.edit-*.js`)

**`POST /api/upload-create`** — `FormData` keys observed:
`title`, `description`, `category`, `type`, `rating`, `privacy`,
`allowComments`, `allowDownloads`, `isWip`, `isAdvert`, `optimize`, `pixelPerfect`.
Returns the new submission id.

**`POST /api/upload-content`** — `FormData` keys: `file` (the multipart file),
`submissionId`, `name`, plus the method-override pair `_endpoint` and `_method`
(Remix resource routes accept only POST, so PUT/DELETE are tunnelled via
`_method`, and `_endpoint` selects the sub-action).

**`POST /api/submission-editor`** — `FormData`/JSON keys: `title`, `description`,
`category`, `type`, `rating`, `privacy`, `allowComments`, `allowDownloads`
(merge-with-server to preserve unspecified fields, as the old edit path did).

### Data model changes (from `GET /api/submission/noX5xXp1`)
```json
{"submission":{"id":"noX5xXp1","title":"…","description":"…",
  "rating":20,                // int: 0=Clean 10=Mature 20=Adult (unchanged)
  "category":"writing",       // STRING now (was int 20)
  "type":"shortstory",        // STRING now (was int 21)
  "privacy":3,                // int: 1=Private 2=Unlisted 3=Public (unchanged)
  "allowComments":true,"allowDownloads":true,"isWip":false,"pixelPerfect":false,
  "tags":["worldbuilding","novella","third person speech", …]  // flat, SPACE-separated
}}
```
`/api/upload-config` returns int category ids for media (10=Artwork, 30=Photography,
40=Music, 50=Video) + per-extension size limits, but **lists no text/story entry**
in the first page of `data[]` — so whether `upload-create` wants `category:"writing"`
(string) or `20` (int) for a story is **unconfirmed**; resolve via the live test.

### CSRF
`api.client-*.js` (the shared fetch wrapper) references `X-CSRF` + `csrfToken`.
Token sources on a Remix page: `<meta name="csrf-token">` (64-hex) and the
`_session` cookie (base64url JSON `{"csrfToken":"…"}.<sig>`). Exact write-request
header name is **unconfirmed** — capture it in the live test.

### Content format / editor
Editor is **TipTap/ProseMirror** (`vendor-tiptap-*.js`). The stored/rendered HTML
uses real `<h1>/<h2>/<h3>`, inline `style="text-align:…"`, `<strong>/<em>/<u>/<s>`,
`<ul>/<ol><li><p>`, `<blockquote>`, `<pre><code>`, `<hr>`, ProseMirror tables.
Sample: `sofurry_beta_tiptap_sample.html`. Our `editor/converter.py`
`_convert_body_sofurry` still emits `class="text-center"` + `<p><strong>`
pseudo-headings — needs updating to the above. **TipTap sanitizes pasted/imported
HTML to its own schema, so the exact accepted markup must be confirmed by posting a
private test work and reading it back via `GET /api/submission/:id`.**

## Profile + followers (read, login-free)
- `GET /api/profile?handle={handle}` → `{user:{...}}` with `followerCount`,
  `followingCount`, `submissionCount`, `totalViews`, `totalLikes`, etc. No auth.
- `GET /api/followers?handle={handle}&mode={followers|following}&page={0-based}` →
  `{users:[{handle,username,avatarUrl,headline,followerCount}], page, hasNextPage}`,
  20 per page. No auth. (The old `/u/{handle}/followers` HTML page is gone.)

## How to refresh this map
Route manifest: `GET /assets/manifest-<hash>.js` (URL is in any Remix page's HTML).
It lists every `routes/*` id → `path` + `module`. Fetch a route's `module`
(`/assets/<name>-<hash>.js`) and grep for `/api/…`, `.append("…"`, `method:`.

## CONFIRMED create recipe (live-tested 2026-06-23, end-to-end 200s)
Auth via the bridge above, then for a writing submission:
1. `POST /api/upload-create`, headers `{X-CSRF-Token: <meta csrf-token>}`, **no body**
   → `{"id":"<sid>"}`.
2. `POST /api/upload-content`, **multipart**, header `X-CSRF-Token`, fields
   `submissionId=<sid>` + `file=(name.html, bytes, "text/html")`
   → `{"contentId":"…","extension":"html"}`. **File must be ≥ 1 KB and ≤ 512000 KB**
   (the 1 KB floor bit the first probe). The HTML is stored verbatim as the "original"
   on `s3.sofurryfiles.com`.
3. `POST /api/submission-editor`, **multipart**, header `X-CSRF-Token`, fields:
   `_endpoint=submission/<sid>`, `_method=POST`, `title`, `description`,
   `category=20`, `type=21`, `rating=0|10|20`, `privacy=1|2|3`,
   `allowComments=true`, `allowDownloads=true`, `isWip=false`, `optimize=true`,
   `pixelPerfect=false`, `isAdvert=false`, and **one repeated `artistTags[]=<tag>`
   per tag** (space-separated values). → returns the saved submission JSON.
4. `DELETE /api/submission/<sid>`, header `X-CSRF-Token` → `{"ok":true}`.

**Resolved unknowns:** (a) auth → Laravel login **+ `/fe/auth/sofurry` bridge**;
(b) write CSRF header → **`X-CSRF-Token`** (value from `<meta name="csrf-token">`);
(c) write encoding → **ints** `category=20`/`type=21` (read endpoint echoes the display
strings `"writing"`/`"shortstory"`); (d) content → an **HTML file** (≥1 KB), stored
verbatim, so the converter just needs to emit TipTap-friendly tags (real `<h1>`, inline
`style="text-align:…"`, `<strong>/<em>/<u>/<s>`, lists, `<blockquote>`, `<hr>`).
Writing accepts `txt, pdf, epub, html`; types: `21`=Short Story, `29`=Book.

**Still to do for multi-chapter** (not yet probed): how additional chapters / content
items are added & ordered, and chapter titling — the old flow POSTed extra files to
`…/content` then set per-content titles. Likely `POST /api/upload-content` again with
the same `submissionId` (the `content[]` array supports multiple items) + a title set
via `submission-editor` (`_endpoint=content/<contentId>`?). Probe before building.
**→ The official API answers this** — see below.

---

## Official API (v1) — `https://api.sofurry.com` (found 2026-08-07)

Docs: `developer.sofurry.com/dev-docs`. **Fetching them requires a browser
`User-Agent`** — a default bot UA gets 403, which reads like an auth wall but isn't.
The site also publishes an **OpenAPI 3.0.3 spec** (`servers: [https://api.sofurry.com]`)
and a **Postman collection** — use those rather than scraping prose. **Both are vendored
here** precisely because the docs 403 a bot UA and would otherwise be hard to re-fetch:
`sofurry_openapi.yaml` · `sofurry_postman_collection.json` (both retrieved 2026-08-07).

**Surface confirmed against four independent copies** (live HTML, a 33-page PDF print,
the OpenAPI spec, the Postman collection), all in agreement: **20 paths / 23 operations**;
`GET /v1/user/{handle}/submissions` is the last one. Machine-checking every schema in the
spec yields **109 distinct property names** — see the gap list below for what is *not*
among them.

### Auth
`Authorization: Bearer <token>`. The spec declares exactly **one** security scheme
(`type: http, scheme: bearer`) — **no OAuth2 flow is described in the spec at all** — and
applies it at top level, i.e. **every endpoint requires a token, including the public
reads** `GET /v1/submission/{id}` and `GET /v1/user/{handle}`. Note the contrast with the
internal endpoints we scrape today, which serve published works with no session.

**⚠ `Accept: application/json` is MANDATORY.** Without it an unauthenticated call
**302s to `https://sofurry.com/login` with an HTML body** instead of returning an error.
With it you get the real thing:
`{"statusCode":401,"message":"Unauthenticated","description":"…","errorCode":401,
"help":"https://developer.sofurry.com"}`. A client that omits the header will read the
302 as success-ish and mis-report auth failures. (Live-tested 2026-08-07.)

Two token types exist (per the prose docs):
- **Personal Access Token** — Settings → Developer → New token; direct link
  `https://www.sofurry.com/settings/pat-create`, which pre-fills from
  `?name=…&description=…`. **This is the one we want.**
- **OAuth app** — for acting on behalf of *other* users. **Not applicable to us:**
  PawPoller only ever touches its operator's own account, and a third party
  self-hosting it would mint their own PAT. No redirect URI / callback listener needed,
  which matters on a headless VM. (No scope list is documented anywhere.)

### Endpoint map vs what we do today
| Ours (internal, undocumented) | Official |
|---|---|
| `POST /api/upload-create` | `PUT /v1/submission` → `{id}` (draft, privacy=1) |
| `POST /api/upload-content` | `POST /v1/submission/{id}/content` (multipart `file`, `description`) |
| `POST /api/submission-editor` | `POST /v1/submission/{id}` (metadata; set `privacy=3` to publish) |
| `GET /api/submission/:id` | `GET /v1/submission/{id}` |
| gallery scrape | `GET /v1/user/{handle}/submissions` (paginated, `meta.total`) |
| `GET /api/search-tags` | `GET /v1/tags/suggest/{query}` |
| `GET /api/folders` | full folder CRUD (`/v1/folder…`) — **new capability** |
| hardcoded enum ints | `GET /v1/uploader/settings` — canonical categories/types/MIME/size limits |

Enums confirm our reverse-engineering: `category` 10 Artwork · **20 Writing** · 30
Photography · 40 Music · 50 Video · 60 3D · 70 Game; `type` **21 Short Story** · 22 Book
· 29 Other; `rating` 0 Clean · 10 Mature · 20 Adult; `privacy` 1 Private · 2 Unlisted ·
3 Public; `status` 0 New · 10 Processing · 100 Processed. Tags go as `artistTags[]`.

**Multi-chapter — the open question above is answered:** order via `contentOrder`
(array of content hashids) on Update Submission; per-chapter titles via
`POST /v1/submission/{sub}/content/{contentId}` with `title` / `description` / `binary`.

### LIVE-PROBED 2026-08-07 with a real PAT — results
Harness: `sf_api_probe.py` (session scratchpad). Must run from a **residential IP**.

- **`x-ratelimit-limit: 60` + `x-ratelimit-remaining` on every response** —
  **completely undocumented**; the prose and the spec mention no limits at all. Decrements
  per request; no `x-ratelimit-reset` or `retry-after` until exceeded, which is the
  signature of Laravel's default `throttle:60,1` → **60 requests per minute**. Ample for
  posting; would matter for any per-submission sweep.
- **Stats: CONFIRMED ABSENT in the live response, not just the docs.** A real submission
  fetched via `GET /v1/submission/{id}` returned **zero undocumented keys vs the spec**.
  The only stat-shaped names on the object are `allowComments` (a flag), `inReview` and
  `status` (processing state). **The docs being unfinished was not hiding anything — the
  analytics scrape must stay.**
- `GET /v1/user/me` *does* carry 6 undocumented keys — `id` (a user hashid), `createdAt`,
  `pronouns`, `sfwDefault`, `handleBeenReset`, `privileges` — **none of them stats**, and
  still no follower count.
- **Pagination is richer than documented**: `meta` also has `from`, `to`, `path` and a
  `links[]` array of page descriptors. 15 per page.
- **`content[].body` does NOT match the docs.** Documented as `{"url": …}`; actually
  returns `{"extension": …, "displayUrl": …}` where `displayUrl` is a **presigned Garage-S3
  URL on `s3.sofurryfiles.com` that expires in 600 s** (`X-Amz-Expires=600`). Never persist
  one — re-fetch it. This is the one real doc/reality divergence found.
- **`maxFileSizes` in the wild ≠ the doc's example.** Live: `content 512000`,
  `thumbnail 1024`, `cover 1024`, and **`subscriber` is identical to `regular`** (no premium
  advantage today). The doc's example (`content 52428800`) is illustrative, not real. The
  live `512000` matches the `≤ 512000 KB` ceiling we measured against the internal API in
  June, so **the unit is KB** (→ thumbnail/cover cap = 1 MB) — but confirm before relying on it.

### Write probes — live results (2026-08-07, one private draft `nLrRPLAe`)
**Multi-chapter WORKS end to end** — the open question at the top of this file is closed:
- `POST /v1/submission/{id}/content` → `201` + `contentId`, repeatable for N chapters.
- **`contentOrder` is respected.** Sent deliberately reversed; read back in the sent
  order with `position` 0/1 renumbered to match.
- **Per-content titles work** via `POST /v1/submission/{sub}/content/{cid}` with
  `{title, description, binary}` → `200`, title applied. `binary` *replaces* the stored
  body (the `displayUrl` points at a new S3 object afterwards).
- **JSON bodies are accepted** for `POST /v1/submission/{id}` — the internal API demanded
  multipart. `artistTags` round-tripped as a JSON array; category/type/rating/privacy all
  saved as sent.

**No thumbnail upload exists.** All four plausible routes 404:
`/thumbnail`, `/thumb`, `/cover`, `/content/thumbnail`. `thumbUrl`/`coverUrl` stayed
`null` with no way to set them. **`set_thumbnail` must stay on the internal endpoint.**

**No DELETE for submissions — the server says so itself:** `"The DELETE method is not
supported for route v1/submission/{id}. Supported methods: GET, HEAD, POST."` Same for
content items. **Anything created via the API can only be removed through the website UI**
(or the internal cookie-session endpoint). Plan test flows around that.

**⚠ HTTP status and body `statusCode` DISAGREE on errors.** That DELETE returned
**HTTP 500** carrying `{"statusCode": 400, "message": "Invalid request", "errorCode": 0}`.
**Never branch on the HTTP status alone — parse the body.** A client treating 5xx as
"retry later" will hammer the server over a permanent 400.

**⚠ The 1 KB floor is real, and it settles the unit question.** Uploading 11 bytes and
707 bytes both fail `422`: `"The file must be between 1 and 512000 kilobytes."` So
`maxFileSizes` is in **KB**, min **1 KB**, max **512000 KB**. **A chapter under ~1 KB
(roughly 150 words) is REJECTED** — the poster needs a guard, exactly as the internal API
did.

**⚠ Tag suggestions appear BROKEN.** `GET /v1/tags/suggest/{q}` returns `200 []` for every
query tried (`drag`, `macro`, `vore`). Endpoint is live but yields nothing — **do not build
the tag pipeline on it** without re-probing.

**Folders work** — `GET /v1/folders` returned real folders with `id` + `name`.

**Rate limit is PER MINUTE** — `x-ratelimit-remaining` went 52 → 59 across a 65 s idle
gap, i.e. the counter resets. 60/min.

**⚠ The PAT does NOT authenticate the internal Remix endpoints.** Two entirely separate
auth systems: with a valid bearer token, `sofurry.com/api/folders` → `401 Not
authenticated` and `DELETE /api/submission/{id}` → `403 CSRF token missing from session`.
So the hybrid client genuinely spans two auth contexts — **but this costs nothing**,
because the endpoints we keep (`/s/{id}.data`, `/api/profile`, `/api/followers`) need no
auth at all. The login stack still dies.

### ⚠ What the official API does NOT provide
*(Established by walking every `properties` block in the OpenAPI spec — 109 names — then
confirmed against live responses. Prose, spec and reality all agree.)*
- **No per-submission statistics.** No `views`, `likes`, `favorites` or comment-count
  field on any endpoint. The only matches for view/like/comment across all 109 names are
  `contentViewCountTotal` / `uploadCommentsCountTotal` inside `GET /v1/statistics/global`
  — **site-wide, rounded to the nearest 50**, useless to us — plus three false friends:
  `allowComments` (a boolean flag), `show_likes` (a profile privacy toggle) and `rating`
  (content rating, not a score).
- **No follower/following counts, `totalViews`, `totalLikes` or `submissionCount`** on
  `GET /v1/user/{handle}`.
- No Comments, Likes, Watches or Notifications sections at all.
- **No thumbnail/cover upload.** `thumbUrl`/`coverUrl` are read-only response fields and
  `Add File Content` accepts only `file` + `description` — yet `uploader/settings` still
  declares `maxFileSizes.thumbnail` and `.cover`, so the capability exists server-side
  but is unexposed. `set_thumbnail` may have to stay on the internal endpoint.
- **No documented rate limits.** The sole throttle signal is a 429 on Create Submission:
  `{"statusCode":429,"message":"Too Many Requests","description":"You have reached your
  upload limit."}`.

The doc is visibly unfinished in places (the two `GET …/content/{contentid}` endpoints
and `POST /v1/user` carry no description at all), so some of the above may be
undocumented rather than genuinely missing — **probe with a real PAT before concluding**.

### ⚠ The GCP VM is IP-BLOCKED from the official API (live-tested 2026-08-07)
`api.sofurry.com` is **not directly reachable from the prod VM** — every request returns
a Cloudflare **403 with a 5-byte body**, regardless of User-Agent or `Accept` header. The
same 403 hits `www.sofurry.com` and `developer.sofurry.com`. From a residential IP the
identical request returns a normal `401 Unauthenticated` JSON.

It is **SoFurry's own WAF rule against the GCP range, not generic Cloudflare
datacenter-blocking**: `e621.net` — also Cloudflare-fronted — returns `200` from the same
VM in the same session. There is no `cf-mitigated` header, so it's a custom block rule
rather than a managed challenge.

**Consequence:** the official API has to route through the **existing CF Worker proxy**,
exactly like current SF + DA polling (see `polling/cf_proxy.py`). This is already-built
machinery, so it's a routing detail rather than a blocker — but a PAT client written
against a direct `https://api.sofurry.com` base URL will work on the desktop and fail on
the server, which is precisely the FA-posting trap in a new costume. **Build it
proxy-aware from the first commit.**

### Consequence for `clients/sf/client.py`
Hybrid. **Delete** the whole auth stack — `login`, `_submit_2fa`, `check_session`,
`ensure_logged_in`, `_bridge_session`, `_ensure_api_session`, `_get_csrf_meta`,
`_api_headers`, `export_cookies`/`import_cookies`, and stored email+password.
**This permanently closes the 2FA gap**: a PAT never logs in, so the unhandled
`/auth/2fa` redirect stops existing as a failure mode.
**Keep** `get_submission_detail`, `get_follower_count`, `scrape_followers` exactly as
they are — they need no session (see the docstring at `client.py:550`), which is
precisely why dropping the auth stack costs us nothing on the analytics side.
