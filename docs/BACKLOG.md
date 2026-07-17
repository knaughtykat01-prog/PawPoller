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
| E | **Detail compaction** ("poetization / no scrolling") — story, artwork & Masterpiece detail denser, fits without scrolling | 🟡 next (Rhys pick #2) | Layout/CSS; somewhat subjective — keep the key info above the fold |
| F | **IA restructure** — split **Submissions** (stories+art) from **Posts** (microblog catalogue); move post-creation into **Create**; posting-under-Create | 🔴 queued (Rhys pick #3) | Big navigation reshape, touches many screens |

_Recently shipped from this table:_ **A** Instagram → artwork upload (**2.139**); **B** Masterpiece member dedup,
**C** Ignore function, **D** multi-account Overview default (**2.140**).

## 🔴 Open (smaller / follow-ups)

| # | Item | Status | Notes |
|---|------|--------|-------|
| G | Overview widgets: **per-metric sorted** stat-card destinations (views → sorted-by-views, faves → similar) | 🔴 | 2.135 made stat cards → `#/library`; still need sorted landing views |
| H | Overview: **more widgets** (Rhys said "20 more") | 🟡 ongoing | +4 in 2.137 (Quick actions, Engagement, Milestones, Spotlight); keep adding useful ones |
| I | Promo Maker follow-ups: source excerpt **from a story/chapter**; per-word **censor bars**; **"share to Posts"** hand-off | ⚪ | 2.138 shipped the core tool |

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
| AO3 525 error logging | (per HANDOFF ledger) |
| In-app "what's new" changelog popup on update | 2.134 |

---

### How to use this file
- When Rhys asks for something, **add a row to Open (top)** before starting — even mid-task.
- When an item ships, **move it to Done** with its version, and tick the HANDOFF ledger too.
- Keep the "In progress / next up" table in Rhys's stated priority order.
