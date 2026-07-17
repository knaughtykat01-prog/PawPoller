# PawPoller — Request & Feature Backlog

**Purpose:** the single running list of everything Rhys has asked for, with status, so nothing gets lost between
sessions. Update this **every time** a request lands or an item ships. Newest requests go at the top of "Open".
Cross-reference shipped items to their `CHANGELOG.md` version.

_Last updated: 2026-07-17 (after 2.140.0 — artwork dedup / ignore / multi-account Overview)._

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
| O | **Art audit: name/describe/tag all 55 Masterpieces** | 🟡 awaiting review | 2026-07-17. All 55 archive images pulled from the server + viewed; titles/descriptions/tags proposed for every piece. Deliverable: `C:\Users\rhysc\claude\art_audit\review.html` (+ `proposals/*.json`). Found: 6 duplicate/variant pairs, 14 junk entries (13 index-only tweets + 1 commission ad), ~7 explicit pieces rated *general*, 12+ artists recovered from in-image signatures. NEXT: Rhys reviews → apply via `PATCH /api/masterpieces/{name}`, merge dupes (2.144 finder), delete junk |
| G | ~~Overview widgets: **per-metric sorted** stat-card destinations~~ | 🟢 **DONE 2.147** | Works now carry pooled stats; Library gained Most viewed/favourited/comments sorts; cards deep-link via `#/library/sort/{key}` |
| H | Overview: **more widgets** (Rhys said "20 more") | 🟡 ongoing | +4 in 2.137 (Quick actions, Engagement, Milestones, Spotlight); keep adding useful ones |
| I | Promo Maker follow-ups: ~~source excerpt **from a story**~~ **DONE 2.147**; per-word **censor bars**; **"share to Posts"** hand-off | 🟡 partly done | 2.138 shipped the core tool; 2.147 added the story-excerpt picker. Censor bars + share-to-Posts still open |
| K | Detail compaction follow-up: collapse secondary sections into **tabs** for even less scroll | ⚪ | 2.141 did the CSS-first pass |
| L | **Merge the works hubs** (Option B) — fold Library/Stories/Artwork into one "Submissions" hub with type filters | ⚪ | Rhys chose Option A for the IA reshape; this is the bigger end-state if wanted later |
| M | **Auto-link on import** — when a newly imported/promoted image matches an existing Masterpiece (pHash), link into it instead of minting a duplicate | ⚪ | 2.144 added the finder+merge for existing dupes; this prevents new ones forming |

## 🔴 Bugs

| # | Item | Status | Notes |
|---|------|--------|-------|
| N | ~~**SoFurry not grabbing thumbnails/images**~~ | 🟢 **FIXED 2.146** | `get_submission_detail` never extracted the image from the `.data` payload (`thumbnail_url` hard-coded `""`). Now pulls the `/submissions/thumbnails/` CDN URL. Force an SF poll to backfill. |

## ⚪ Deferred / future

| # | Item | Status | Notes |
|---|------|--------|-------|
| J | Simple **image editor** (crop / resize / reformat / stickers / blur / censor) before publishing | ⚪ future | Large client-side canvas feature; Rhys did **not** pick it in the last prioritisation |

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
| AO3 525 error logging | (per HANDOFF ledger) |
| In-app "what's new" changelog popup on update | 2.134 |

---

### How to use this file
- When Rhys asks for something, **add a row to Open (top)** before starting — even mid-task.
- When an item ships, **move it to Done** with its version, and tick the HANDOFF ledger too.
- Keep the "In progress / next up" table in Rhys's stated priority order.
