# Official X (Twitter) API v2 as an X-polling backend — Assessment & Design Spec

**Status:** Proposal (spec only — no code yet) · **Author:** Rhys + Claude · **Date:** 2026-07-13
**Problem in one line:** X polling from the server scrapes X's internal API (gallery-dl → GraphQL
fallback, shipped 2.105.x), but X **rate-limits the GCP datacenter IP** on the timeline endpoint —
so from the server, later accounts in a cycle get `429`'d regardless of backend. The official X API
v2 is IP-agnostic (OAuth/Bearer, not IP-throttled the same way) and returns **exactly** the six
metrics we already track. This doc assesses cost/fit and designs it as an **opt-in, bring-your-own-token**
fourth backend that slots into the existing hybrid.

> Related: `clients/tw/client.py` (GraphQL client + posting), `clients/tw/gallerydl.py`
> (2.105.0 gallery-dl backend), `docs/documentation_guide.md` → "gallery-dl poll backend".

---

## 1. Why consider it — the datacenter-IP wall

Verified live on prod (2.105.x, 2026-07-13): gallery-dl works and uses **current** query IDs, but from
the GCP datacenter IP, X `429`s the `UserTweets` endpoint and tells the client to wait ~6-15 min for the
reset. This is **backend-agnostic** — the old GraphQL scraper `429`s on the same limit — and it stacks
when the scheduler polls multiple X accounts back-to-back in one cycle (`server.py` `_poll_accounts`
polls accounts sequentially with no spacing). It's the same family as the AO3 datacenter throttle
(AO3 imports run from the desktop's residential IP for this reason).

The official API authenticates per-app/per-user (OAuth 2.0 / Bearer), so it is **not** subject to the
per-datacenter-IP scraping throttle. It's the "proper" fix for server-side X analytics.

## 2. Pricing reality (2026)

The old free/Basic/Pro tiers are **closed to new signups** and being auto-migrated to **pay-per-use**
(the default for new developers since Feb 2026). There is **no free allowance** — but there is also
**no monthly minimum**: you pay only for calls made.

| Read type | Cost | Notes |
|---|---|---|
| **Owned read** (your own account's data) | **$0.001 / post** | This is our case — we only ever read the user's own tweets |
| Standard post read | $0.005 / post | Not needed here |
| Post create (write) | $0.015 (+$0.20 if it contains a link) | Posting stays on the GraphQL client regardless; not part of this |
| Hard cap | 2,000,000 reads/month (~$2,000 at owned-read price) | Nowhere near our volume |

Legacy Basic was $200/mo and Pro $5,000/mo; **Enterprise ≈ $42,000/mo.** None are relevant — a new
PawPoller self-hoster lands on pay-per-use.

Sources: [twitterapi.io breakdown](https://twitterapi.io/blog/x-api-cost-breakdown-2026),
[Blotato pricing guide](https://www.blotato.com/blog/twitter-api-pricing),
[X docs — Metrics](https://docs.x.com/x-api/fundamentals/metrics).

### Cost for THIS user's scale (owned reads @ $0.001)

3 X accounts, ~40 own tweets total, re-reading all each cycle:

| Poll cadence | Reads/month | **Monthly cost** |
|---|---|---|
| 12h (current prod, 2×/day) | 40 × 2 × 30 = 2,400 | **~$2.40** |
| 4h (default, 6×/day) | 40 × 6 × 30 = 7,200 | **~$7.20** |
| Even at 200 tweets, 6×/day | 36,000 | ~$36 |

So for realistic hobby scale, the official API is **single-digit dollars per month** — cheap insurance
against the scraping fragility + datacenter throttle. Cost scales linearly with `tweet_count ×
poll_frequency`, and can be cut further by **only re-reading recent/active tweets** (old tweets stop
changing) — a worthwhile optimisation if a user's timeline is large.

## 3. Metrics fit — a perfect map

X API v2 `public_metrics` returns the **exact six** metrics PawPoller already stores. No schema change.

| PawPoller metric | v2 `public_metrics` field |
|---|---|
| views | `impression_count` |
| likes | `like_count` |
| retweets | `retweet_count` |
| replies | `reply_count` |
| quotes | `quote_count` |
| bookmarks | `bookmark_count` |

- `public_metrics` needs only an **app-only Bearer token** and works for any public post → simplest auth.
- `organic_metrics` / `non_public_metrics` (profile clicks, URL link clicks, detailed media views) are
  **owner-only** and need **OAuth 2.0 user-context**. These are *extra* metrics we don't currently track;
  out of scope for v1 (could be a later enhancement — new columns).

**Endpoints:** `GET /2/users/:id/tweets?max_results=100&tweet.fields=public_metrics,created_at,...`
(user timeline, paginated, ~3,200-tweet lookback cap) or `GET /2/tweets?ids=<up to 100>` (batch lookup
of known ids). Resolve the user id once via `GET /2/users/by/username/:handle`.

### Multi-account — one app covers all three personas (NOT one account)

A common worry: "does this only work for one account?" **No.** For `public_metrics` (our six metrics), an
**app-only Bearer token reads *any* public account's tweets** — X docs: *"Access public metrics with any
authentication… Public metrics require only a Bearer Token."* The token is not bound to a single account.
So **one dev app + one Bearer token polls all of KnaughtyKat, NaughtyKiiKinar, and the third persona**
(and any public account) — one app, one bill, no per-account setup.

The only per-account step is the *owner-only* `organic_metrics`/`non_public_metrics` (profile/link clicks —
which we do **not** currently track): those need a one-time OAuth 2.0 authorization per account, but a
single app holds multiple users' tokens simultaneously (*"one app can read multiple user accounts by
managing separate access tokens for each authorized user"*). So even that is one app + N one-time
authorizations, not N apps.

**Pricing caveat across accounts:** the cheap **$0.001 "owned read"** rate is for the app-owner's own
account; reading the *other* personas via app-only Bearer likely bills at the **$0.005 standard read**
(or you OAuth-authorize each persona to reclaim owned-read pricing). At ~40 tweets total the spread is
between ~$2.40 and ~$12/month — trivial either way. Verify exact scope on the dev portal before relying on
a specific figure.

## 4. Design — opt-in fourth backend in the hybrid

Reuse the exact pattern from `clients/tw/gallerydl.py`. Priority order in `TWClient.get_all_tweets()`:

```
1. Official X API v2   — if the user configured an X API token (reliable, IP-agnostic, ~$0.001/read)
2. gallery-dl          — if the binary is present (free, tracks X's API)
3. GraphQL scrape      — always-available fallback (free, brittle query IDs)
```

- **New module `clients/tw/official_api.py`** — `fetch_tweets(bearer, handle, settings) -> list[dict] | None`
  and `validate(...) -> bool | None`, returning the same detail-dict shape as the other backends
  (so `tw_queries` / poller / routes are untouched). `None` → fall through to gallery-dl, exactly like today.
- **Bring-your-own-token** (same philosophy as the self-host Meta app for IG/Threads): new settings
  `tw_api_bearer_token` (**secret → vault**, add to `CREDENTIAL_FIELDS`) and optional
  `tw_api_client_id`/`tw_api_client_secret` if we later add OAuth for organic metrics. A
  `tw_polling_backend` value of `official` forces it; `auto` uses it when a token is present.
- **No new tables/metrics** — `public_metrics` maps onto the existing `tw_submissions` columns.
- **Posting is unaffected** — still the GraphQL `create_tweet` path (the official write API costs
  $0.015+/post and we have a working free path).
- **UI:** a connect card under Settings → X for the API token, a one-line **cost estimate**
  ("~N reads/cycle ≈ $X/month at your cadence"), and `/api/tw/auth/status` gains `poll_backend:
  "official"`.

## 5. Trade-offs

**For:**
- Solves the datacenter-IP throttle outright — reliable server-side X analytics.
- Exact metric parity, no schema change, clean fit into the shipped hybrid.
- Cheap at hobby scale (single-digit $/month); $0 when idle.
- Official + ToS-compliant; no scraping fragility or query-id chasing.

**Against / caveats:**
- **Costs money** (small, but non-zero and per-user) — each self-hoster needs their own X dev account
  with **billing enabled** and must paste a token. Not "free out of the box."
- Pay-per-use billing means a runaway/misconfigured poll loop = real charges → we should **cap/guard**
  (e.g. respect the poll cadence, offer a "recent-tweets-only" mode, never force_full on a timer).
- The public-readiness story is now "free scraping by default, optional paid official API for
  reliability" — needs a clear docs note so users aren't surprised by X charges.
- Can't be validated without a real token + billing (I can't set that up) — so v1 ships behind the
  opt-in and is tested by the user against their own account.

## 6. Recommendation & phased plan

**Recommend building it as the opt-in top-priority backend** — it's the only real fix for server-side
reliability, the cost is trivial at this scale, and it drops cleanly into the hybrid we already shipped.
Gate the work on the user deciding to fund an X dev account (needed to test).

1. **Phase 1 — client + wiring (needs a test token).** `clients/tw/official_api.py`, vault the token,
   slot it as priority-1 in `get_all_tweets()`/`validate_cookies()`, add the settings + status field.
   Tested by the user against their own account. Ship behind opt-in (absent token → today's behaviour).
2. **Phase 2 — cost guardrails + UX.** Cost estimate in the connect card; a "recent/active tweets only"
   read mode to bound spend; docs note on billing. Optional: OAuth 2.0 user-context for
   `organic_metrics` (profile clicks, link clicks) as new tracked metrics.

**Open questions for Rhys:**
- Fund an X dev account (pay-per-use, ~$2-7/month at your cadence) so Phase 1 can be built + tested?
- App-only Bearer (public_metrics = our 6) enough for v1, or also want the owner-only organic metrics
  (needs OAuth, more setup)?
- Keep the free scraping path as the default and official-API strictly opt-in (recommended), yes?
