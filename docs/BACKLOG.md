# PawPoller — Request & Feature Backlog

**Purpose:** the single running list of everything Rhys has asked for, with status, so nothing gets lost between
sessions. Update this **every time** a request lands or an item ships. Newest requests go at the top of "Open".
Cross-reference shipped items to their `CHANGELOG.md` version.

_Last updated: 2026-07-23 (after 2.166.0 — Quick Publish: one-screen drop-image → pick-persona → go for artwork)._

Legend: 🔴 open · 🟡 in progress · 🟢 done · ⚪ deferred/parked

---

## 🟡 In progress / next up (Rhys's chosen order)

| # | Item | Status | Notes |
|---|------|--------|-------|
_All of Rhys's chosen items are shipped._ **A** Instagram → artwork upload (**2.139**); **B** dedup, **C** Ignore, **D**
multi-account Overview (**2.140**); **E** detail compaction pass (**2.141**); **F** IA restructure — Create hub + Posts
split, Option A (**2.142**).

## 🔴 Open (smaller / follow-ups)

| # | Item | Status | Notes |
|---|------|--------|-------|
| U | ~~**Quick-publish path** — drop image → pick per-persona preset → go; one screen for the 80% case~~ | 🟢 **DONE 2.166** | From the product analysis "easy wins". `#/artwork/quick` (`Artwork.renderQuick`): a persona IS the preset (its accounts → art platforms + per-platform account). Drop image → persona chip → toggle sites → Publish now / 🕐 Schedule. Per-persona rating/tags/off-platforms remembered in localStorage; last-used persona reselected. Entry: Create nav (⚡, first), Overview Quick-actions, New-Artwork link. **Frontend only** — reuses the artwork upload/publish/schedule endpoints, no backend change. Deferred: named multi-presets, quick path for stories/posts |
| V | **Discovered triage inbox** — one card at a time: keep / variant-of / ignore / →Posts; collapses discovered/ignored/masters/suggestions into one flow | 🔴 | Analysis easy-win. Also: discovered tiles should FLAG story/writing submissions (see bug fix 2.158.1) instead of offering artwork import |
| W | **Proactive credential-expiry warnings** ("your Mastodon token expires in 6 days") where platforms expose it | 🔴 | Analysis easy-win; today's amber states are reactive-after-failure |
| X | **Perf guardrails** — pagination + cached rollups on the list endpoints (Masterpieces list = live rollup × N) | 🟡 **Batched 2.165** | MUST land before any user with 1000s of works (public-readiness prerequisite). **Done (2.165):** killed the N+1 fan-out on both hot list endpoints. Masterpieces `summarize` was 1 submission query PER MEMBER + a write PER NAME (~460q+196w/load on prod) → **batched** `summarize_many` (bulk members + `_submission_rows_bulk` one query/platform + `ensure_indexed_bulk`) = ~20q+≤1w, O(platforms) not O(members). `/api/works` `get_publications_with_stats` batched the same way. Pure speedup (equivalence + query-bound tests). Added optional `limit`/`offset` + `total`. **Still open (lower priority):** disk = one `masterpiece.json`/folder read (O(N) files); frontend consuming `limit`/`offset` + server-side sort/filter for TRUE pagination |
| Y | **Backup/restore UX** — user-facing "download my everything" / "restore from file" pair | 🔴 | Analysis easy-win; top self-host objection |
| Z | **SCHEDULING** — "publish this Friday 8pm across these sites"; the missing core feature of a publishing tool | 🟡 **Phases 1–2 DONE (2.163–2.164)** | Analysis: most conspicuous gap. **Phase 1 (2.163):** artwork scheduling (was stories-only) + a global **Queue & Schedule** page (When column, local-time, reschedule + cancel). **Phase 2 (2.164):** microblog **Posts** scheduling — posts ride the same `posting_queue` (`content_type='post'`, `story_name`=post_id, snippet in `title_override`); `scheduler` post-branch → `post_publisher.publish_post`; `POST /api/posts/{id}/schedule`; composer 🕐 Schedule…. **All three content types now schedulable.** Timezone: local UI / UTC stored. **Phase 3+ (TODO):** recurring schedules ("every Friday"), best-time suggestions, calendar drag-drop. FA/desktop-only platforms fire next time desktop is open (warned in UI, not blocked; no post platform is desktop-gated) |
| AA | **Retro "2005 web" theme** — early-2000s style: beveled buttons, gradient headers, boxy tables, Verdana energy | 🔴 | Rhys 2026-07-19. Fits the existing tokens.css multi-theme system (Default/parchment/etc.) as a new theme entry |
| AB | ~~**Achievement-style ERROR popups + send/report action**~~ | 🟢 **DONE 2.159.0 (2026-07-19)** | Rhys confirmed destination: *"send it to say me the dev"* = the instance's Telegram. Shipped: Laurels-style card on every failed mutating call (`error_popup.js`/`.css`), Copy report + Send to dev → `POST /api/report-error` → `send_telegram`, always server-logged, `{sent}` feedback. Follow-up polish still open: tag-format display at post time ("will post as: …") |
| T | ~~**Whole-app product/business analysis** (opportunities, gaps, refinement, ease-of-use)~~ | 🟢 **DONE 2026-07-19** | Deliverable: `C:\Users\rhysc\claude\outputs\pawpoller_product_analysis.md` (outside repo — strategy stays out of the public copy). Verdict: pursue community self-host release (B) + BA-portfolio framing (D); hosted SaaS not yet. Top blockers: first-run wizard (§3), connect-flow pain, ToS/docs (§5), signing decision (§4), then SCHEDULING as the missing core feature |
| S | ~~**Masterpiece VARIANTS + XMB Showcase**~~ | 🟢 **DONE 2.158** | Variants: `variant_key` on members + `masterpiece.json` variants list → per-variant stats, cohort untouched; merge-as-variant + dup-finder "🖇 Variants of one piece"; declare/demote/attribute endpoints. UI: piece detail = stage (giant blurred backdrop + labeled chips + per-variant stats); Library gains the **opt-in** Showcase shelves (▤/✕ toggle, last choice remembered, default classic — Rhys: "deploy as an option choice"). Mockups approved after PawPoller-token re-theme + clipping fix. NEXT (spec §4): import the ~130 collection pieces |
| R | ~~**Apply the audit: retag + retitle + re-describe all Masterpieces** (descriptions ≤2 sentences)~~ | 🟢 **DONE 2026-07-18** | 48 surviving pieces updated on prod via `save_artwork_metadata` (canonical title/desc/rating/tags; per-platform overrides preserved; typo tags fixed). Ratings corrected incl. the explicit-rated-general pieces. NOT yet done: Sync-to-sites push (edits live uploads — needs Rhys's go), junking the 14 |
| O | ~~**Art audit: name/describe/tag all 55 Masterpieces**~~ | 🟢 **DONE** | 2026-07-17. All 55 archive images pulled from the server + viewed; titles/descriptions/tags proposed for every piece. Deliverable: `C:\Users\rhysc\claude\art_audit\review.html` (+ `proposals/*.json`). Found: 6 duplicate/variant pairs, 14 junk entries (13 index-only tweets + 1 commission ad), ~7 explicit pieces rated *general*, 12+ artists recovered from in-image signatures. **Multi-image sets recovered** (13 extra images off the tweets' `media_urls`): Bread2Garlic birthday set (incl. the "To Dar, Happy Birthday. Love, Ki" dedication + a 2nd Kinar×Tigress piece), 2nd VektorichArt piece, buffer-Kii "dash of seed" variant, Franubis body-writing variant; Kasscabel confirmed as the harness-daki artist. **DONE 2026-07-17** — Rhys confirmed the audit is complete. |
| Q | ~~**See the multi-image grabs in the app** ("should i not be able to see the extra images?")~~ | 🟢 **DONE 2.152** | 13 recovered set-images pushed to the server folders + detail-page gallery strip (`images:[...]` on GET /{name}, `.mp-alts` click-to-swap). Also: the 6 dupe pairs merged on prod (55→49, byte-identical verified, variants preserved as alts) |
| P | ~~**Junk category for Masterpieces** ("for arts it had pulled but is not needed or useful, or archived")~~ | 🟢 **DONE 2.149** | `masterpieces.status` + `POST /api/masterpieces/{name}/status`; grid 🗑 Junk (N) view + ♻ Restore; detail Junk/Restore button. Works for index-only names (the 13 swept-in tweets). Kept-but-hidden, reversible |
| G | ~~Overview widgets: **per-metric sorted** stat-card destinations~~ | 🟢 **DONE 2.147** | Works now carry pooled stats; Library gained Most viewed/favourited/comments sorts; cards deep-link via `#/library/sort/{key}` |
| H | Overview: **more widgets** (Rhys said "20 more") | 🟢 **catalog 19 → 23** (2.148) | +4 in 2.137 (Quick actions, Engagement, Milestones, Spotlight), +4 in 2.148 (Platforms live, Best platform, Recent comments, Pending queue). Deliberately useful-over-filler — say the word for more |
| I | ~~Promo Maker follow-ups: source excerpt from a story · censor bars · share to Posts~~ | 🟢 **DONE** | Story-excerpt picker **2.147**; censor bars + 💬 Send to Posts **2.148** |
| K | ~~Detail compaction follow-up: collapse secondary sections into **tabs**~~ | 🟢 **DONE 2.150** | Story detail (the 10-section offender) now hero + pending + totals visible, rest behind tabs. Masterpiece/Artwork left alone on purpose (3–4 sections, already tightened 2.141; their chart needs a visible canvas) |
| L | ~~**Merge the works hubs** (Option B) — fold Library/Stories/Artwork into one hub with type filters~~ | 🟢 **DONE 2.155** | The **Library** is the one hub. `#/posting` + `#/artwork` redirect in; segments deep-link via `#/library/type/{story\|artwork\|masterpiece\|discovered}`. Discovered = 5th segment reusing `Submissions.renderDiscoveredInto()`. Story blurb/category/⚠ now projected by `assemble_works`. Nav/bottom-nav/breadcrumbs/palette/tours all repointed. See L1–L2 for the two known gaps |
| L1 | **Masters-folding of discovered art** — lost with the Artwork hub | ⚪ | It grouped one piece cross-posted to several sites into one discovered tile (via `submission_links`); the Discovered segment lists them as separate rows. NOT ported on purpose: **Masterpieces supersedes it** and cross-platform links are slated to merge into Collections. Port source still in `artwork.js` (`_foldMasters`/`_masterCard`/`_splitMaster`). **Say the word if you want it back** |
| L2 | **Excise the retired hubs' dead code** | ⚪ | `Posting.renderUpload`, `Artwork.render` (+ ~400 lines of hub-only helpers) and `Submissions.render` are unreachable but still present — `Artwork`'s are the port source for L1. Each verified reachable *only* from its own dead hub block, so removal is safe once L1 is settled |
| M | ~~**Auto-link on import**~~ | 🟢 **DONE 2.151** | ★ Master pre-checks the hash vs Masterpiece heroes (`GET /api/masterpieces/match`) and **offers** to link into the existing one. Deliberately a prompt, not automatic — SFW/NSFW edits hash identically |
| U | ~~**Group rough/final & SFW/NSFW into one piece** ("i thought we implemented them into variants … it didnt merge the variants")~~ | 🟢 **DONE 2.160** | After the collection import → ~200 Masterpieces. Root cause: the dedup finder matches by *image* (pHash); rough-vs-final & SFW/NSFW are *different images* so it can't group them — but the **titles** line up (8 families on prod). NEW `variant_suggest.py` + `GET /variant-suggestions` + a "Same piece, different renders" section on the tidy-up screen; folds a family via existing `merge-as-variant`, labels derived from the title suffix, hero pickable, own "✗ Not variants" dismiss. Review-only. Also cleaned 13 orphan tweet-named index rows |

| R | ~~**Discovered is all imageless tweets — those should import into Posts**~~ | 🟢 **DONE 2.157** | Confirmed on live data: 62 discovered, **60 with no image, 54 tweets**. Only import was as-*artwork* (needs an image) → Ignore was the only workable action for ~90% of the queue. New `post_importer` + **→ Posts** button + bulk bar; carries `account_id` so posts land on the right persona; `post_publications` added as a 4th discovered-exclusion set so imports actually leave the queue. Text-only by design (image → artwork, text → post) |

## 🔴 Bugs

| # | Item | Status | Notes |
|---|------|--------|-------|
| S | ~~Discovered offered **artwork Import on text rows** (and "Import all 54" for X)~~ | 🟢 **FIXED 2.157** | Import-as-artwork downloads an image — on the 54 text tweets it could only fail. Now only renders on rows WITH an image; the per-platform bulk bar counts importable-as-art rows only and hides when there are none |
| N | ~~**SoFurry not grabbing thumbnails/images**~~ | 🟢 **FIXED 2.146** | `get_submission_detail` never extracted the image from the `.data` payload (`thumbnail_url` hard-coded `""`). Now pulls the `/submissions/thumbnails/` CDN URL. Force an SF poll to backfill. |

## ⚪ Deferred / future

| # | Item | Status | Notes |
|---|------|--------|-------|
| J | ~~Simple **image editor**~~ | 🟢 **DONE 2.151** | `#/imagetool` — crop / rotate / flip / resize / censor / pixelate, undo, PNG·JPEG·WebP export, Download · Send to Posts · Save as new artwork. Non-destructive, all client-side |

---

## 🟢 Done (from the big "enjoy haha" UI dump + follow-ups)

> ⚠️ Rhys's screenshots for the re-sent dump were **stale** (dated the day before the deploys). Many items he flagged as
> "still broken" were already fixed + live — a hard-refresh clears the cached PWA shell.

| Item | Shipped |
|------|---------|
| "Choose image" button on artwork upload | 2.122 |
| Editor toolbar buttons wrap + centre on screen | 2.122 (`editor.css`) |
| SquidgeWorld credential-key lock ("still locked despite redone configs") | 2.122 (`editor_api.py` `sqw_author_* OR sqw_*`) |
| Artwork tag browser = story tag browser format | 2.123 |
| Platforms-in-Settings look like the Platforms tab (card grid) | 2.133 |
| Artwork tab = Gallery for discovered + imported work | (pre-existing, Submissions hub 2.33–2.36) |
| Collections group artworks + stories + posts | Collections 2.97 |
| Masterpiece = master file for one image, two creation methods | Masterpiece build 2.124–2.131 |
| Collections multiple recommendation matches | `auto_suggest_collections` |
| Stories cross-platform already grouped | pre-existing |
| Change the rating of a (standalone) artwork | **2.136** |
| Artwork tab filters / separations | **2.136** (All / In library / Discovered + search) |
| Overview clickable stat widgets (part 1: stat cards → library) | **2.135** |
| Marketing image generator (BookTok excerpt cards, ref IMG_0351.jpg) | **2.138** (Promo Maker `#/promo`) |
| Instagram as an artwork upload target | **2.139** |
| Masterpiece member dedup (no duplicate discovered tiles) | **2.140** |
| Ignore function for discovered artwork (+ Ignored/restore view) | **2.140** |
| Multi-account Overview shown by default ("By persona" widget) | **2.140** |
| Detail pages compaction (less scrolling) — CSS-first pass | **2.141** |
| IA: Create hub + Posts split (view-only feed, composer in Create) | **2.142** |
| Ignore button in the Library's discovered review view (tweet-art) | **2.143** |
| Merge duplicate Masterpieces (pHash finder + one-click merge) | **2.144** |
| "Not the same" — dismiss + remember false-positive dup matches | **2.145** |
| SoFurry thumbnails/images not captured (bug) | **2.146** |
| Library performance sorts + per-metric Overview stat links | **2.147** |
| Promo Maker: pull an excerpt from a story | **2.147** |
| Overview widgets +4 (Platforms live, Best platform, Recent comments, Queue) | **2.148** |
| Promo Maker: censor bars + 💬 Send to Posts | **2.148** |
| Masterpiece junk bin (kept-but-hidden status) | **2.149** |
| Story detail tabs (one screen, not ten) | **2.150** |
| Image Tool (crop/rotate/resize/censor/blur, non-destructive) | **2.151** |
| Masterpiece detail gallery (every image in the set) | **2.152** |
| Replace a Masterpiece's canonical image (keeps record + links) | **2.153** |
| Stop duplicate Masterpieces forming (link-instead-of-create prompt) | **2.151** |
| AO3 525 error logging | (per HANDOFF ledger) |
| In-app "what's new" changelog popup on update | 2.134 |

---

### How to use this file
- When Rhys asks for something, **add a row to Open (top)** before starting — even mid-task.
- When an item ships, **move it to Done** with its version, and tick the HANDOFF ledger too.
- Keep the "In progress / next up" table in Rhys's stated priority order.
