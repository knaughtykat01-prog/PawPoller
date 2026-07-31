# Platform Expansion v2 — spec + PostyBirb comparison

**Captured 2026-07-31.** Two asks: (1) spec new platforms to add, and (2) compare how we implement
the platforms we already have vs how [PostyBirb](https://github.com/mvdicarlo/postybirb) does it
(`apps/client-server/src/app/websites/implementations/`). PostyBirb is a mature, actively-maintained
crossposter — its ~40 implementations are the best available reference for "how each site's API/upload
actually works."

Sources: PostyBirb `main` branch implementations (fetched 2026-07-31), CrosspostSharp's FurryNetwork
client, the Philomena engine docs. PawPoller side from our own code + [[project_pawpoller_platform_expansion]].

> **Scope note.** PostyBirb is **post-only** — it never polls analytics. PawPoller does BOTH poll
> (views/faves/comments over time) and post. So for every new platform, "can we poll stats?" is a
> separate, often harder question than "can we post?" — flagged per platform below.

---

## Part 1 — Existing platforms: how we do it vs PostyBirb

We share ~15 platforms. The table is auth + post mechanism on each side, then the **takeaway** (are we
ahead, behind, or at parity — and any concrete improvement to steal).

| Platform | PawPoller (poll + post) | PostyBirb (post only) | Takeaway |
|---|---|---|---|
| **Inkbunny** | Official API — `api_login.php` → `sid`; upload+edit via `api_upload`/`api_editsubmission` | Same official API (sid, upload+edit) | **Parity.** Both use the clean official API. |
| **e621** | Official API, HTTP Basic (username + api_key) | Same — `POST /uploads.json`, Basic auth | **Parity.** Both official. |
| **Weasyl** | Official **API key** (`ws_api_key`) | **Cookie scrape** + form POSTs (only `/api/whoami` is API) | **We're ahead** — official key beats their cookie session. |
| **Pixiv** | App API via OAuth **refresh token** (pixivpy-style) | **Cookie scrape** of `/ajax/work/create/illustration` + CSRF | **We're ahead** — app API beats web scraping. |
| **Tumblr** | Official **OAuth1** API (consumer + user tokens) | **Cookie scrape** of internal web API v2 (bearer from `__INITIAL_STATE__`) | **We're ahead on stability** (official API); they're lower-friction to connect. |
| **DeviantArt** | Official **OAuth** for stats (`deviation/metadata`) + `da_cookie` for posting | Internal `_puppy`/`_napi` web API + scraped CSRF (fragile, versioned `da_minor_version`) | **We're ahead for polling** (official OAuth); posting is cookie-bound on both. |
| **Bluesky** | AT Protocol **app password** | AT Protocol **app password** (`@atproto/api`) | **Parity.** |
| **Mastodon** | OAuth2 instance URL + access token | OAuth2 **dynamic app registration** (megalodon), instance auto-detect | Parity; their dynamic-registration UX is slightly nicer (no manual app step). |
| **Instagram** | Graph API + public image host (`IG_PUBLIC_BASE_URL`/relay) | Graph API + public host (their Azure blob) | **Parity** — same Meta model, same public-URL requirement. |
| **Itaku** | Token API (`Authorization: Token`) | Same token API (token scraped from `localStorage`) | **Parity** — same API, we take the token more cleanly (paste vs scrape). |
| **FurAffinity** | Cookie scrape (FAExport/direct); **datacenter-IP-blocked → desktop-only posting** | 3-stage HTML-form scrape (`/submit/upload`→`/submit/finalize`) | **Parity** — no official API exists; both scrape. |
| **X / Twitter** | **Cookie session** (`auth_token`+`ct0`), brittle; optional official bearer for polling | OAuth 1.0a official API (user's own app keys, PIN flow) — **but built for pre-2023 Twitter** | **Not a clear win** (user flagged). X killed free API access in 2023: the v2 API now needs the user's own app AND effectively a **paid tier** for media upload — which is precisely why we use cookies. PostyBirb's OAuth1.0a path is likely as stale as its SoFurry one. Cookie brittleness is the lesser evil unless the user pays for X API. |
| **SoFurry** | **React-SPA scrape + session cookies** (rebuilt 2.28.0; fragile, needed 2FA work) | Official REST API `https://api.sofurry.com/v1` (bearer) — **but almost certainly PRE-rewrite / stale** | **Likely a non-finding.** Verified 2026-07-31: `GET api.sofurry.com/v1/user/me` **302-redirects to the SPA login page** (HTML), not a JSON 401 — the hallmark of a *retired* API path swallowed by the new site's auth. SF's SPA rewrite is exactly why we scrape. PostyBirb's SF module predates it. **Our scraping is probably the correct current approach.** |
| **Telegram** | **Bot API** — bot must be a channel admin; broadcasts to your own channel | **MTProto user account** (teleproto) — posts AS the user to any channel/group/topic they're in | Different trade-offs. Ours is simpler + safe; theirs can post anywhere the user is (no admin needed) but needs `my.telegram.org` app + phone/2FA login. Ours is fine for own-channel broadcast. |

### Improvement opportunities this comparison surfaced

> **Meta-caveat (important): PostyBirb's implementations lag platform API changes.** Two "opportunities" that
> looked strong on paper both turned out to be **stale PostyBirb code**, not live APIs: SoFurry's `/v1` API
> (dead since SF's SPA rewrite — now redirects to login) and Twitter's OAuth1.0a (built for pre-2023 Twitter,
> before X paywalled the API). Reality-check every PostyBirb approach against the CURRENT platform before adopting
> it. The user knows these furry/art sites better than PostyBirb's possibly-old code does — trust that.

**Net result: the comparison surfaced no free wins on existing platforms — and that's the useful finding.**

1. **We're already ahead** on Weasyl / Pixiv / Tumblr / DeviantArt: we use official APIs where PostyBirb
   cookie-scrapes. Our approach is the more durable one — no action, just confidence.
2. **SoFurry, Twitter — NOT opportunities** (both flagged by the user, both verified). SF's official API is dead
   post-rewrite; X's official API is paywalled. Our scraper (SF) and cookie session (X) are the correct current
   approaches. Leave them.
3. **The real value of this exercise is Part 2** — the *new* platforms PostyBirb reveals we could add.

---

## Part 2 — New platform candidates (spec)

Each: relevance to our furry-fiction/art, adult-friendly, no-AI audience · auth · post flow · **poll/stats
feasibility** (the hard part) · build effort. Effort baselines: a full poll+post gallery ≈ the ~40-file
e621 build; a Posts-module-only target ≈ the Telegram (2.198.0) build; a fediverse reuse ≈ tiny.

### Tier A — highest value

**FurryNetwork** (`fn`) — *gallery, poll+post.* Confirmed alive + **VM-reachable** (no datacenter block, unlike FA).
- Auth: OAuth2 password grant, `https://furrynetwork.com/api/oauth/token`, `client_id=123` → bearer (1h) + refresh_token. Email+password, vaulted (like IB/SF).
- Model: work is grouped under **characters** (a persona-like layer). `GET /user`, `GET /character/{name}`.
- Post: **chunked/resumable upload** (512 KB chunks, Resumable.js params) to `submission/{character}/artwork/upload` → `PATCH /artwork/{id}` (Title/Description/Tags/Rating 0-2/Status draft|unlisted|public).
- **Poll: YES.** Submission model carries `Views`, `Favorites`, `Comments`, `Rating`, `Status`, `Created`/`Published`, `Images.Original`/`.Thumbnail`. List via `GET /search?character=…&types[]=artwork&from={offset}`.
- Effort: full ~40-file build; the character grouping is the one wrinkle. **Ready to build.** (PostyBirb dropped FN in its rewrite — a longevity caveat, but the site + API are live.)

**Aryion / Eka's Portal** (`ary`) — *furry+vore/kink gallery, adult-heavy. Strong audience fit.*
- Auth: **cookies only** (phpBB forum login `ucp.php?mode=login`). No official API.
- Post: multipart `POST /g4/itemaction.php` (`file`, `title`, `desc` BBCODE, `tags` newline-joined, mandatory `parentid` folder, view/comment perms, `action=new-item`).
- **Poll: NO read API** — would require scraping gallery/item pages for counts. Post-first; analytics is scrape-only and fragile.
- Effort: full build but posting is scrape; polling is the risk. Consider **post-only** first (Posts/Artwork target, no dashboard) and add scraped analytics later.

**Furbooru** (`fbr`) — *furry booru. Core fit; adult via rating tags.*
- Auth: cookies (Philomena login). Post: shared **Philomena** flow — GET `/images/new` (scrape CSRF) → multipart `POST /images` (`image[tag_input]`, `image[image]`, `image[description]`, `image[sources][0][source]`; rating as a `safe/questionable/explicit` tag).
- **Poll: YES (bonus).** Philomena has a **public read JSON API** PostyBirb doesn't use: `GET /api/v1/json/search/images?q=uploaded_by:{user}` and `/api/v1/json/images/:id` return **faves / upvotes / views / score / comment_count**. Clean analytics.
- ⭐ **Leverage:** one **Philomena client** covers Furbooru **and** Derpibooru / Manebooru / Ponybooru / Twibooru (same engine, only the base URL differs). Build once, register several.
- Effort: medium; the read API makes it a genuine poll+post platform, not just a poster.

### Tier B — good galleries, mixed analytics

**Piczel** (`pcz`) — *furry-friendly art gallery + streaming.* Cleanest API of the new galleries.
- Auth: cookies. Post: **JSON** `POST /api/gallery` (`title`, `description`, `tags[]`, `nsfw` bool, files as base64 data-URIs). Folders `GET /api/users/{u}/gallery/folders`.
- **Poll: LIKELY** — genuine `/api/…` surface; user-image listing endpoints almost certainly exist (exact stat fields unconfirmed). Best analytics candidate among Tier B.

**Picarto** (`pic`) — *very furry, adult-capable, streaming + gallery.*
- Auth: Bearer token from `localStorage` (interactive login). Post: **GraphQL** `createArtwork` at `ptvintern.picarto.tv/ptvapi` + per-image JWT upload. Description base64.
- **Poll: LIKELY** — real GraphQL API (already used for albums); stat queries plausibly exist. Heavier (two-token dance + GraphQL).

**Pillowfort** (`pf`) — *furry-friendly art-social, adult allowed.*
- Auth: cookies (Rails CSRF). Post: `POST /image_upload` → `POST /posts/create` (`title`, HTML `content`, `tags`, `nsfw`). **Poll: NO** read API surfaced — scrape-only. **2 MB image cap** is a real limit.

**Hentai Foundry** (`hf`) · **Newgrounds** (`ng`) — adult/art galleries, moderate furry presence.
- Both cookie-scrape, granular per-axis content flags. **Poll: NO.** Newgrounds is the **hardest** flow in the whole set (needs browser-JS `userkey`, ~7 sequential requests). Lower priority.

### Tier C — fediverse (cheap wins by reuse)

⭐ **Pleroma, GoToSocial, Firefish, Pixelfed** — *all Mastodon-API compatible.* PostyBirb drives all four
through **one shared Mastodon base** (megalodon lib): OAuth2-per-instance + bearer token, `uploadMedia` →
`postStatus(text, {media_ids, sensitive, spoiler_text, visibility})`. **Since we already have Mastodon, adding
these is near-free** — parameterise our `mast` client by instance + a small per-platform char-limit/label. All
furry/adult-friendly. Post-only (or reuse mast's polling where the instance exposes it).

**Misskey** (`msk`) — *own API (NOT Mastodon-compatible).* MiAuth flow, token-in-body (`i` field),
`POST /api/notes/create`. Separate integration — big with JP/furry/art communities but its own build.

### Tier D — subscription / support (different engagement model)

**SubscribeStar** (`ss`) — *the adult-creator Patreon alt; heavy furry NSFW use.* Highest-relevance of this tier.
- Auth: session cookies + CSRF. Post: presigned-S3 upload → `POST /posts.json` (`html_content`, `tags[]`,
  `tier_ids[]`, `upload_ids[]`). PostyBirb even ships a separate `subscribe-star-adult` variant.
- **Poll:** engagement here is **subscribers/tiers**, not views/faves — a different analytics shape (we'd track
  subscriber counts like followers, not per-post stats). Fits the Posts module as a broadcast target better than
  the gallery dashboard model.

**Ko-fi** (`kofi`) · **Patreon** (`pat`) — support/subscription. Ko-fi has a gallery + blog (cookie scrape + S3);
Patreon is a full JSON:API with tiers + scheduling. Both announcement-oriented; analytics = patrons/tips, not views.

### Not recommended

- **Cara** — anti-generative-AI artist platform, *thematically* on-brand for our no-AI stance, **BUT it is
  GENERAL-rating only and rejects any mature/adult upload.** Our audience posts adult furry work, so Cara can't
  carry most of it. Low practical value despite the brand alignment. (Revisit only if a SFW-only sub-audience wants it.)
- **Toyhouse** — huge in furry, but it's **OC/character hosting**, not an analytics gallery: image-only, 4 MB cap,
  no view/fave polling surface. Could be a post-only "upload art to a character" target later; not a dashboard platform.
- **Artconomy** (commissions marketplace) · **The Jab Archives** (niche adult comics) — narrow; skip for now.

---

## Part 3 — Recommended roadmap

Ordered by value ÷ effort, honouring the poll+post model and the adult-furry audience:

1. **FurryNetwork** — ready, fully spec'd, VM-reachable, real stats. The clear first build.
2. **Furbooru (+ Philomena family)** — furry booru with a clean public read API for analytics; one client
   unlocks several boorus. High leverage.
3. **Fediverse reuse (Pleroma / GoToSocial / Firefish / Pixelfed)** — near-free posting adds by extending the
   `mast` client. Ship as a batch.
4. **Aryion** — strong furry fit; build **post-first** (scrape analytics is the risk), revisit polling later.
5. **Piczel / Picarto** — good galleries with real APIs; medium effort.
6. **SubscribeStar** — high audience relevance as a **Posts-module/broadcast** target (subscriber-count analytics, not per-post).

*(Dropped from an earlier draft after the user reality-checked them: a "SoFurry official-API migration" and a
"Twitter OAuth1.0a posting path" — both rely on PostyBirb code that predates those sites' API changes (SF's SPA
rewrite; X's 2023 API paywall). Our scraper/cookie approaches are the correct current ones. See Part 1.)*

**Reddit** stays its own track (separate spec) — gated behind Reddit's 2026 manual API approval + the S3 image dance.

Each ships as its own versioned release, stats verified live against the user's real account (the Threads/IG pattern).
