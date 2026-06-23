# SoFurry "beta" API map (2026-06, post-rewrite)

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
