# PawPoller — Request & Feature Backlog

**Purpose:** the single running list of everything Rhys has asked for, with status, so nothing gets lost between
sessions. Update this **every time** a request lands or an item ships. Newest requests go at the top of "Open".
Cross-reference shipped items to their `CHANGELOG.md` version.

_Last updated: 2026-07-23 (after 2.172.0 — Retro 2005 theme; backlog AA done). **All open feature items shipped** — only deferred cleanup (L1/L2) remains._

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
| V | ~~**Discovered triage inbox** — one card at a time: keep / variant-of / ignore / →Posts~~ | 🟢 **DONE 2.169** | Analysis easy-win. `#/submissions/triage` (`Submissions.renderTriage`): one big card at a time over the discovered queue, contextual actions (Import-art / →Posts / ★Master / 🔗Link / 🚫Ignore / Skip) + **keyboard A/P/M/L/I/→**. Reuses the list view's endpoints (frontend only). **Writing flag** on no-image non-microblog items (link, don't import as art). ★Master + 🔗Link advance in-flow. Entry: ⚡ button on Discovered header + Library segment. Deferred: folding Ignored/Masterpieces/suggestions into the same flow |
| W | ~~**Proactive credential-expiry warnings** where platforms expose it~~ | 🟢 **DONE 2.170** | Today's status only reddens AFTER failure; this warns as a finite-lifetime **no-refresh cookie login ages** — **X (30d)/FA (45d)/DA (45d)** only (IG/Threads auto-refresh; Mastodon/Tumblr/Bluesky/e621 don't expire → omitted, never cry wolf). `config.save_settings` stamps `credential_set_at` on (re)connect; `credential_age_report()` levels ok/aging/stale; `backfill_credential_stamps()` for existing installs. `GET /api/platforms/credential-age`. Surfaced in Settings→Platforms→Session health ("⏳ reconnect before these expire"). Signal = credential AGE, no fragile expiry-API. +8 tests. Deferred: Meta token-debug exact days; per-extra-account |
| X | ~~**Perf guardrails** — pagination + cached rollups on the list endpoints (Masterpieces list = live rollup × N)~~ | 🟢 **DONE 2.165 + 2.167** | Public-readiness prerequisite for 1000s of works. **(2.165) DB side:** killed the N+1 fan-out — Masterpieces `summarize` was 1 submission query PER MEMBER + a write PER NAME (~460q+196w/load on prod) → **batched** `summarize_many` (bulk members + `_submission_rows_bulk` one query/platform + `ensure_indexed_bulk`) = ~20q+≤1w, O(platforms). `/api/works` batched the same way. Pure speedup (equivalence + query-bound tests). **(2.167) Browser side:** both grids **windowed** — paint first ~60 cards, stream the rest on scroll via IntersectionObserver (`_windowInto` in `masterpieces.js` + `bookshelf.js`), so 1000s of works don't build every DOM/img node up front. **Parked as marginal:** DB cache of the per-folder `masterpiece.json` reads (~tens of ms, OS-cached — not worth the invalidation surface). Both real bottlenecks (queries + DOM) handled |
| Y | ~~**Backup/restore UX** — user-facing "download my everything" / "restore from file" pair~~ | 🟢 **DONE 2.171** | Top self-host objection. `routes/backup_api.py` (`/api/backup/export|import|info`): export = one `.zip` of everything under `DATA_DIR` (db + settings + encrypted vault + artwork/posts_media/story-archive media) + manifest; **destructive restore is safety-first** — manifest-kind check, **zip-slip guard**, timestamped `restore-safety-<ts>/` copy before overwrite, merge (never blind-delete) media, 2 GB cap, "restart to finish". Upgraded Settings→Data→Backup & Restore from DB-only to full (size line, cookie-riding download, `.zip` restore + strong confirm). +6 tests (round-trip + safety copy + zip-slip). Old `/api/backup/database` left intact |
| Z | ~~**SCHEDULING** — "publish this Friday 8pm across these sites"; the missing core feature of a publishing tool~~ | 🟢 **DONE (2.163–2.164, 2.168)** | Analysis: most conspicuous gap. **Phase 1 (2.163):** artwork scheduling + a global **Queue & Schedule** page (reschedule + cancel). **Phase 2 (2.164):** **Posts** scheduling — posts ride the same `posting_queue` (`content_type='post'`); `scheduler` post-branch → `publish_post`; `POST /api/posts/{id}/schedule`. **All 3 content types schedulable.** **Calendar (2.168):** ☰ List / 📅 Calendar toggle on Queue & Schedule; `_renderQueueCalendar` lays pending scheduled items on a local-time month grid (‹ › paging, click→detail). Timezone: local UI / UTC stored. **Logged as future features (NOT completion — see CHANGELOG rationale):** drag-to-reschedule (inline editor already does it), recurring schedules (only useful as a slot-based content calendar, not re-posting one-offs), best-time suggestions (needs an engagement model). FA/desktop-only platforms fire next time desktop is open (warned, not blocked; no post platform is desktop-gated) |
| AA | ~~**Retro "2005 web" theme** — early-2000s style: beveled buttons, gradient headers, boxy tables, Verdana energy~~ | 🟢 **DONE 2.172, FULL MAKEOVER 2.173** | Palette in tokens.css (`[data-theme="retro_2005"]`); **full component skin in new `frontend/css/retro_2005.css`** (loaded LAST, modelled on brut.css) — every surface reconfigured: cards→beveled windows w/ blue gradient title bars, app-window page-header, task-pane sidebar, 3D press-in buttons, sunken inputs, gridlined zebra tables, folder tabs, dialog modals+toasts, portal login, chunky scrollbars, underlined links, Verdana. **Verified via rendered preview screenshot.** Registered in `app.js` THEMES + `routes/api.py` allowlist. Rhys wanted "every single surface, completely reconfiged" — done |
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

> **Gap sweep (2026-07-23):** a use-case-persona review found these missing. Full survey + implementation-ready specs
> in `docs/specs/user_gap_analysis.md`. Verified against source (dropped false gaps — notifications + follower tracking
> already exist). G1–G7 are the recommended builds (ranked); G8+ are parked. Effort: S≈a session, M≈a few, L≈multi.

| # | Item | Status | Notes |
|---|------|--------|-------|
| J | ~~Simple **image editor**~~ | 🟢 **DONE 2.151** | `#/imagetool` — crop / rotate / flip / resize / censor / pixelate, undo, PNG·JPEG·WebP export, Download · Send to Posts · Save as new artwork. Non-destructive, all client-side |
| G1 | ~~**Serialized / "drip" scheduling** — post Ch.1 now, a chapter every Friday 8pm~~ | 🟢 **DONE 2.181** | `drip_group` column + `POST /api/editor/stories/{name}/drip` (validates every ch×plat up front; expands into ordinary queue rows, per-chapter slots) + group-cancel endpoint. 💧 button in Publish Check + "Cancel whole drip" on the Queue page. Rows independent (no dependency gate — possible v2). Spec: `gap_wave2.md` §3 |
| G2 | ~~**First-run setup wizard** — connect-first-account → first-post~~ | 🟢 **DONE 2.181** | CORRECTION: a `#/setup` wizard already existed (survey wrong) — extended it with a "Your persona" step + a Done-step "Run my first poll now" (loops per-platform triggers; global trigger is IB-only). Spec: `gap_wave2.md` §4 |
| G3 | ~~**Reply-to-comments inbox** — unified `#/inbox` across personas~~ | 🟢 **DONE 2.182 (full A0+A1+B)** | 💬 Inbox in the sidebar: IB+FA (legacy tables) ∪ bsky/mast/e621/da (new capped delta-capture into `platform_comments`) with handled flags + **native reply on bsky/mast/e621** (auto-handles on success; mast needs a write-scope token). Scrape platforms (ws/sf/sqw/ao3/tw) stay "Open ↗ reply on-site"; DA/thr/ig replies need extra OAuth scopes (future). Audit matrix: spec §2.3 |
| AT | ~~**"Posted via PawPoller" credit line** (Rhys ask, 2026-07-23) — on by default, plea modal on opt-out~~ | 🟢 **DONE 2.181** | `posting/attribution.py` at the two package-build choke points → every story/artwork posting path; skips bsky; idempotent; NOT on microblog Posts. Toggle in Settings→General→Publishing, self-saving, "Keep it on 💛 / Turn off anyway" modal. Spec: `gap_wave2.md` §1 |
| G4 | ~~**Discord announce webhook** — POST an embed on publish~~ | 🟢 **DONE 2.180** | `posting/discord.py` + `routes/discord_api.py`; webhook + auto-toggle in Settings→Data + Send-test. Auto-announce wired into the shared publishers (`post_publisher.publish_post` + `manager.post_artwork`) → fires for interactive + scheduled posts/artwork; adult ratings drop the inline image. Deferred: per-piece manual button (endpoint exists), story announce |
| G5 | ~~**Analytics CSV / report export**~~ | 🟢 **DONE 2.180** | Correction: the Analytics page ALREADY had client-side Fastest/Weekly CSV — the real gap was a COMPLETE export. Built `GET /api/works/export.csv` (one row per work×platform + all stats) + "↓ Full data CSV" button. Spec §2.5 |
| G6 | ~~**Alt-text on gallery uploads**~~ | 🟢 **DONE 2.181** | `alt_text` through ArtworkInfo/json/upload/PATCH/GET + upload+edit form inputs → Bluesky `image_alt = alt_text or title`. (Mastodon is Posts-only + already had alt; gallery sites have no alt concept.) Spec: `gap_wave2.md` §2 |
| G7 | ~~**Scheduled automatic backups**~~ | 🟢 **DONE 2.180** | `backup_api.py` `run_auto_backup()` (timestamped zip → folder + prune-to-keep) + `run_auto_backup_scheduler()` daemon (main.py + server.py, 30-min tick, self-throttles). `GET`/`POST /api/backup/auto`; Settings→Data "Automatic backups" row. Off by default |
| G8 | ~~**Multi-post threads** (tweetstorms)~~ | 🟢 **DONE 2.184** | 🧵 parts in Posts compose; bsky+mast reply-chaining (reuses G3 plumbing); other platforms post part 1 + note; X deferred. Also shipped 2.184: benchmark analytics + best-time histograms + per-persona posting defaults (G9 items). Spec: `gap_wave3.md` |
| G9 | **Commission workflow / client queue** · **cross-platform series** · **beta-reader draft share** · **per-persona posting defaults** · **comparative/benchmark analytics** · **best-time-to-post** · **multi-user + 2FA** · **watermark on export** | ⚪ | Parked batch — see `docs/specs/user_gap_analysis.md` §3 |

---

## 🟢 Done (from the big "enjoy haha" UI dump + follow-ups)

> ⚠️ Rhys's screenshots for the re-sent dump were **stale** (dated the day before the deploys). Many items he flagged as
> "still broken" were already fixed + live — a hard-refresh clears the cached PWA shell.

| Item | Shipped |
|------|---------|
| **Global SFW/NSFW toggle** ("across the entire platform, can i have a toggle button for sfw and nsfw") | 2.178 — 🔒 sidebar button blurs every non-`general` cover app-wide (Library/Artwork/Masterpieces/Collections/Posts); `data-sfw` pre-paint, per-device, fail-safe (un-tagged → blurred). `safe_mode.css` + `data-rating` on covers. **2.179:** click-to-peek — first click reveals one blurred tile (no nav), second click opens it |
| Retro theme: shelf covers cropped/uneven + editor toolbar misaligned | 2.176 (removed `content-visibility` fighting cover `aspect-ratio`) + 2.177 (`.editor-actions-secondary` → flex row; was baseline-staggered in every theme) |
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
