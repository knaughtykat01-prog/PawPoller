# User Gap Analysis — what a user could still want

**Status:** SURVEY + specs · **G4 + G5 + G7 BUILT 2.180.0** · **Author:** Rhys + Claude (fable) · **Date:** 2026-07-23

> A use-case-persona sweep of PawPoller (as of 2.179.0) looking for what a real user would reach for and not find.
> Every "gap" below was checked against the source — claims the app *already* covers new-comment/fave/milestone
> notifications and follower tracking were dropped after verification. This doc is the survey (§1), implementation-ready
> specs for the recommended builds (§2), and a parked list of the rest (§3). Split any §2 item into its own spec file
> when it graduates to active work.

---

## 1. The boxes (persona survey)

Legend: ✅ already covered · ⚠️ partial · ❌ genuine gap (verified absent).

### 📖 Serial novelist — chaptered work across AO3/SF/IB/WS, a chapter a week
- ❌ **Serialized / recurring scheduling.** Scheduling is one-off only (`rrule`/`cron`/`recurring`/`serialize` = 0 hits). No "drip a chaptered work on a cadence." **← top recommendation, §2.1**
- ❌ **Beta-reader / draft share.** No private-draft-for-feedback step between draft and publish.
- ❌ **Cross-platform series object.** No ordered "Book 2 of N" that maps to each site's series/folder concept. (Collections group a *piece's* footprint, not an *ordered reading order* across works.)

### 🎨 Gallery artist — FA/WS/IB/e621/Bluesky
- ⚠️ **Alt-text on gallery uploads.** Posts carry `image_alt`; the Artwork upload path has none. **← quick win, §2.6**
- ❌ **Watermark / signature-on-export.** No image-watermarking feature found.
- ❌ **Commission workflow.** No client/commission queue (who owes what, deliver-to-these-sites).

### 🐦 Microblogger / promoter — Bluesky/Mastodon/Threads/Tumblr/X
- ❌ **Multi-post threads.** Posts fans a *single* post to many platforms; no thread/tweetstorm builder.
- ⚠️ **Publish-only, no inbox.** Broadcaster not client — no reply/quote/boost (see multi-persona box).
- ❌ **Discord announce target.** Discord isn't a publish/crosspost target (Telegram is *your* notifications only). **← top recommendation, §2.4**

### 📊 Data-driven creator
- ❌ **Analytics export.** No CSV/report export (only the full backup `.zip`). **← top recommendation, §2.5**
- ❌ **Comparative / benchmark framing.** Absolute trends only; nothing like "2.3× your median."
- ❌ **Best-time-to-post.** Absent, though the engagement history to power it is already collected.
- ✅ Milestone alerts, Laurels, follower tracking, per-work pooled stats are strong.

### 🎭 Multi-persona operator (KnaughtyKat / Hustlestick / KiiKinar)
- ❌ **Reply-to-comments from the app.** Comments are surfaced + notified, but there's no reply action. **← top recommendation, §2.3**
- ❌ **Per-persona posting defaults** (time / platforms / voice) beyond the quick-publish preset.

### 🔒 Self-hoster
- ⚠️ **Backups manual only.** Export/restore exists (2.171); no *scheduled automatic* backup. **← quick win, §2.7**
- ❌ **Single-user only.** No user roles/multi-user (`setup_mode` is instance-role, not account-role).
- ❌ **No 2FA on the dashboard login** (assume — hardening pass).

### 👋 Newcomer
- ⚠️ **Onboarding is educational, not operational.** Getting-started page + tours exist, but no first-run *setup* wizard that walks connect-first-account → first-post. **← top recommendation, §2.2**

---

## 2. Recommended builds (implementation-ready)

Ranked by value-to-build. Effort: **S** ≈ a session, **M** ≈ a few, **L** ≈ multi-session.

### 2.1 Serialized / "drip" scheduling — **M**
**Problem:** the natural writer flow ("post Ch.1 now, then one chapter every Friday 8pm") must be hand-queued item by item.
**Approach:** a **finite drip** — expand the campaign into N ordinary one-off `posting_queue` items *at creation time*, so the existing `posting/scheduler.py` daemon fires them unchanged. No recurring-daemon logic (evergreen re-posting was judged low-value in the product analysis). A "Drip…" action on a chaptered work (and on a multi-item set of art/posts): pick start datetime + interval (every N days / weekly on <day> at <time>) → preview the computed slots → enqueue all.
**Touch-points:** `frontend/js/editor.js` (chaptered) + a shared drip modal; new bulk-schedule endpoint in `routes/artwork_api.py` / `routes/posts_api.py`; `database/posting_queries.py` insert-many + cancel-group; Queue & Schedule page (`app.js`) renders a drip as one collapsible campaign.
**Data:** add `drip_group_id` (nullable) + `drip_seq` to `posting_queue` so a campaign can be shown/cancelled as a unit; store the cadence string for display only.
**Open Qs:** desktop-gated platforms (FA) in a drip — warn per-slot (fire next time desktop is open), same as today's single-schedule behaviour.

### 2.2 First-run setup wizard — **M**
**Problem:** onboarding teaches *about* the app but never gets a newcomer *live*. Gate on the public-readiness push.
**Approach:** detect a fresh install (a `first_run_completed` settings flag, false when unset) → a wizard overlay on first dashboard load: (1) welcome, (2) name your first persona, (3) connect your first platform account — deep-link into the *existing* per-platform connect flow inside the wizard shell, (4) trigger a first poll (or a test post), (5) done → set the flag. Skippable; re-runnable from Settings.
**Touch-points:** new `frontend/js/firstrun.js` + overlay CSS; boot check in `app.js` `init()`; reuse `accounts.js` connect flows; flag via `config.save_settings`; a "Re-run setup" entry in Settings → Getting started.
**Data:** `first_run_completed: bool` in settings.
**Open Qs:** desktop vs server first-run differ (server has no local file pickers) — branch the "connect" step on `setup_mode`.

### 2.3 Reply-to-comments inbox — ✅ **BUILT 2.182.0 (full A0+A1+B)** — audit 2026-07-23 held up; staging below shipped as one release
**Problem:** managing three personas' comment sections means opening every site.

**AUDIT VERDICT (17-platform sweep + DB audit; anchors in the sweep report):**
- **Content already stored, with threading:** **IB** (`comments` table — id/username/text/timestamp/threading; poller fetches
  the full list on count-change) and **FA** (`fa_comments` — same, + `is_deleted`; ⚠ skipped in FAExport-"direct mode").
  Permalinks constructible from submission URL + comment id. Missing only a "handled/replied" flag.
- **Cheap content adds** (official API, existing auth, one new GET per changed submission — mirror IB's delta-trigger):
  **bsky** (`getPostThread`), **mast** (`/statuses/{id}/context`), **e621** (`/comments.json?search[post_id]`),
  **da** (official `GET /comments/deviation/{id}`); **thr/ig** official too but need extra token permissions;
  pix unofficial-API risk; ik/tum public-but-partial.
- **Expensive content adds (new scraping — skip in v1):** ws, sf, sqw, ao3, tw (wp needs a v4-endpoint check).
- **Reply tier 1 (official write, near-trivial):** **bsky** (add `reply:{root,parent}` refs to the existing
  `create_post`), **mast** (`in_reply_to_id` one-param add — ⚠ poll token is read-scope; reply needs the write-scope
  token), **e621** (`POST /comments.json`, same HTTP-Basic creds). Next: **da** (official `POST /comments/post/…`,
  needs `comment.post` scope — CORRECTION: DA is *not* read-only, it already runs user-token OAuth write flows),
  **thr/ig** (official reply endpoints, need manage-replies/comments permissions re-granted).
- **Reply tier 2 (session form-POST scraping — plausible, fragile, defer):** ib, fa (desktop-only writes), sqw, ao3,
  ws, sf, tw, pix, ik. **Not plausible:** wp (client has zero auth), tum (no official reply endpoint).

**Revised staging + cost:**
- **Stage A0 — S/M:** `#/inbox` over the IB + FA rows *already in the DB* (persona/platform/unread filters, permalink
  out-links) + a `handled` flag (small migration or a shared `inbox_state` table keyed platform+comment_id).
- **Stage A1 — M:** capture content for bsky/mast/e621/da via the cheap official GETs into a **unified
  `platform_comments` table** (don't mint four more per-platform tables; IB/FA stay put and the inbox UNIONs).
- **Stage B — M:** native reply for bsky → mast → e621 (then da/thr/ig as scopes allow); everything else keeps
  "Reply on site ↗".
**Touch-points:** new `routes/inbox_api.py`, `frontend/js/inbox.js`, delta-triggered fetches in 4 pollers,
reply methods on 3 clients.

### 2.4 Discord announce webhook — **S** (best value/cost — build first)
**Problem:** furry audiences live in Discord servers; new work isn't announced there.
**Approach:** user pastes a Discord **webhook URL** (per persona/server; no OAuth). On a successful publish, POST a formatted embed (title, link, thumbnail, platform). Plus a manual "📣 Announce to Discord" button on a work/post, and a per-publish opt-out.
**Touch-points:** small `posting/discord.py` (build + POST embed); hook the publish-success path (artwork/posts/story); settings UI under Accounts/Platforms; optional per-post checkbox.
**Data:** `discord_webhooks` (list; optional `persona_id` + "announce on publish" toggle) in settings/vault.
**Open Qs:** rate-limit/backoff on the webhook; SFW/NSFW embeds (respect rating — spoiler/omit thumbnail for adult).

### 2.5 Analytics CSV / report export — **S** — ✅ BUILT 2.180.0
**Correction (found while building):** the Analytics page *already* exported its two summary tables client-side
(Fastest-growing CSV, Weekly-growth CSV) — the survey's "no export" was wrong (the grep only checked `routes/analytics*`).
The real gap was a **complete** export, which is what shipped: `GET /api/works/export.csv` (one row per work × platform
with all stats) + a "Full data CSV" button.
**Problem:** no way to get the *full* dataset into a spreadsheet or a year-in-review.
**Approach:** an **Export** button on Analytics → streams a CSV. Two shapes: (a) per-work snapshot (one row per work × platform with current pooled + per-platform stats); (b) time-series (snapshot history for a date range). Reuse existing rollup queries; stream server-side.
**Touch-points:** `routes/analytics_api.py` new `GET /api/analytics/export.csv?shape=…&range=…`; button in `frontend/js/analytics.js`.
**Open Qs:** printable "year in review" is a nice follow-on but out of scope for v1.

### 2.6 Alt-text on gallery uploads — **S/M** (quick win)
**Problem:** Bluesky/Mastodon reward alt-text; the gallery upload path has no description field.
**Approach:** add an `image_alt` / description field to the Artwork upload + edit forms; map it to each platform's alt/description field on post (platforms that accept one). Falls back to the artwork description where a platform has no dedicated alt.
**Touch-points:** `frontend/js/artwork.js` (upload + edit forms), `routes/artwork_api.py` (persist), the per-platform posters that accept alt/description.
**Open Qs:** per-platform vs single alt — start single, allow per-platform override later (mirrors tags).

### 2.7 Scheduled automatic backups — **S** (quick win)
**Problem:** restore only saves you if a backup exists; nobody remembers to click Export.
**Approach:** a scheduler job that runs the existing backup-export on a cadence to a configured folder, with a retention count (keep last N). Reuse `routes/backup_api.py` export logic.
**Touch-points:** a small scheduled task alongside the poll scheduler; settings for enable / cadence / destination / retention; Settings → Data surface + "last auto-backup" line.
**Open Qs:** desktop (local folder) vs server (volume path / off-box target) — branch on `setup_mode`.

---

## 3. Parked (lower priority, tracked)

| Gap | Note |
|---|---|
| Multi-post threads (tweetstorms) | Real daily-use gap for threaders; needs a thread composer + per-platform reply-chain posting |
| Commission workflow / client queue | Big adjacent product; the app is close to being the right home |
| Cross-platform series (ordered) | AO3-style series mapped per platform; niche vs Collections |
| Beta-reader / draft share link | Private draft feedback loop before publish |
| Per-persona posting defaults | Time / platforms / voice carried by a persona |
| Comparative / benchmark analytics | "vs your median", "best weekday" |
| Best-time-to-post suggestions | Data already collected; needs a light engagement model |
| Multi-user / roles + 2FA | Self-host: shared instance + login hardening |
| Watermark / signature on export | Stamp a handle on posted copies |
