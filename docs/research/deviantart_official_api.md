# DeviantArt Official OAuth2 API — polling research

**Date:** 2026-07-03 · **Outcome:** DA polling migrated off the browser-cookie
Eclipse `_napi` scrape onto the official OAuth2 API (shipped 2.47.0).

This is the reference for *why* and *how* DA polling works now, so a future
session doesn't have to re-derive it. All findings below were verified with live
calls (a Confidential DA app, client-credentials grant).

---

## TL;DR

The official API returns full per-deviation stats — **including view counts** —
for **any public deviation**, via an **app-only** client-credentials token (no
user login, no cookie). This is exactly what the old cookie/`_napi` scrape gave
us, minus the fragility (cookie expiry, Eclipse-frontend churn, datacenter-IP
blocks / CF proxy).

The old client docstring claimed *"there is no public gallery stats API."* That
was wrong (or outdated): `ext_stats` is the answer.

---

## Auth

- **Grant:** `client_credentials` (app-only). `client_id` + `client_secret` from
  a registered DA app (Client type: **Confidential**). No user authorization-code
  flow, no refresh token, no cookie needed for polling.
- **Token endpoint:** `POST https://www.deviantart.com/oauth2/token`
  — **NOT** `…/api/v1/oauth2/token`. The `/api/v1/...` prefix is only for API
  *methods*; hitting it for the token 404s with `"Api endpoint not found."`
- Token body: `grant_type=client_credentials&client_id=…&client_secret=…`.
- Response: `{access_token, token_type: "Bearer", expires_in: 3600, status}`.
  Scope came back `null` but browse + metadata calls still worked (the
  client-credentials default grants public browse access).
- Access tokens last ~1h; mint a fresh one when expired. Call methods with
  `Authorization: Bearer <token>`.

For **posting**, PawPoller still uses the authorization-code grant + refresh
token (`da_refresh_token`), because creating deviations acts as the user. The
`client_id`/`client_secret` are shared between posting and polling.

## Endpoints used for polling

| Endpoint | Purpose |
|----------|---------|
| `GET /api/v1/oauth2/gallery/all?username=<u>&offset=<n>&limit=24&mature_content=true` | Enumerate a user's gallery. Paginated: response has `results[]`, `has_more`, `next_offset`. |
| `GET /api/v1/oauth2/deviation/metadata?deviationids[]=<uuid>&ext_stats=true&ext_submission=true&mature_content=true` | Per-deviation stats + metadata. **`ext_stats` caps at 10 deviationids per call** (base metadata allows 50). |

### `gallery/all` result object (fields we use)
`deviationid` (UUID), `url` (ends in the **integer** deviation id, e.g.
`…/art/PFP-1351854174`), `title`, `published_time` (Unix seconds), `is_mature`,
`thumbs[]` (`.src`), `content.src`, `author.username`. Note its own `stats`
object only has `favourites`+`comments` (no views) — so we always call
`metadata?ext_stats` for stats.

### `metadata` object with `ext_stats=true`
```json
"stats": { "views": 1275965, "views_today": 0, "favourites": 204,
           "comments": 21, "downloads": 28, "downloads_today": 0 }
```
Also returns `title`, `author.username`, `description` (HTML), `is_mature`,
`submission.category`, `tags[].tag_name`. British spelling: **`favourites`**
(maps to our DB column `favorites_count`).

## Key findings (all verified live)

1. **Views are returned, and NOT owner-only.** Verified on a deviation owned by
   another user (`suspicioussmoothie`, 1,275,965 views) with an app-only token.
2. **Mature content works** with `mature_content=true` (13/24 results on tag
   `nsfw` were `is_mature`; `ext_stats` on a mature one returned `views:478921`).
   `mature_content=false` → **403** `"Content blocked due to user's mature
   content setting"`. So the flag is the switch; we always pass `true`.
3. **Not IP-walled.** From the GCP `pawpoller` VM, `browse/dailydeviations` and
   `gallery/all` both return **200**. The Eclipse `_napi` *frontend* blocks
   datacenter IPs (hence the old CF proxy requirement); the *API* does not. → DA
   left `PROXY_REQUIRED_PLATFORMS` (`polling/cf_proxy.py`), same as AO3 in 2.22.11.

## How the migration keeps the DB unchanged

The DB keys deviations by **integer** `submission_id` (`da_submissions`,
`da_snapshots`). The official API keys by **UUID** `deviationid`. To avoid a
schema/type migration (and ripple across the hub/analytics/telegram/group code
that references these tables), the client:

- parses the **integer** id from each deviation's `url` (trailing `-<digits>`) for
  the DB, and
- uses the **UUID** only transiently to make the `metadata` call.

So `DAClient` returns the exact same detail-dict shape as before
(`deviation_id`, `views`, `favorites_count`, `comments_count`, `downloads`,
`title`, `keywords`, `link`, `thumbnail_url`, `posted_at`, `rating`,
`description`, `category`). The poller, queries, schema, and dashboard are
untouched. Enumeration caches `{int_id → uuid,title,url,thumb,date,mature}` so the
details step can batch metadata by UUID and merge.

## Gotchas / notes for future work

- **Token URL** is `/oauth2/token`, not `/api/v1/oauth2/token` (404 trap).
- **`ext_stats` batch cap = 10.** Chunk deviationids by 10; base metadata is 50.
- **`mature_content=true`** is required to see (and not 403 on) mature works.
- **UUID case:** `gallery/all` and `metadata` return the same UUID; we match
  case-insensitively (upper) to be safe.
- **Rate limits:** the API rate-limits but is stable; at the 240-min poll cadence
  and 10-per-call batching, volume is trivial. `DA_REQUEST_DELAY_SECONDS` still
  applies between pages/chunks.
- **Legacy fallback retained:** if `da_client_id`/`da_client_secret` are absent
  but a `da_cookie` is, `DAClient` falls back to the old `_napi` scrape (which
  still needs the CF proxy on datacenter IPs). Not the default path.
- **No thumbnail on some deviations** (e.g. text/literature): `_pick_thumb`
  returns `""` — expected, not a bug.

## Repro (one-liner shape)

```
POST https://www.deviantart.com/oauth2/token           grant_type=client_credentials + id/secret
GET  /api/v1/oauth2/gallery/all?username=<u>&mature_content=true          → deviationid + url
GET  /api/v1/oauth2/deviation/metadata?deviationids[]=<uuid>&ext_stats=true → stats.views …
```

Live-validated end-to-end against `knaughtykat` (2 deviations, views 10 + 12).
