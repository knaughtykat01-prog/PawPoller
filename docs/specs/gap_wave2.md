# Gap Wave 2 — Attribution line · G6 alt-text · G1 drip scheduling · G2 first-run wizard

**Status:** ALL FOUR BUILT & SHIPPED 2.181.0 · **Author:** Rhys + Claude (fable) · **Date:** 2026-07-23

> The second build wave off `user_gap_analysis.md` (G4/G5/G7 shipped in 2.180.0), plus one new ask: an opt-out
> **"Posted via PawPoller" attribution line** on story + artwork descriptions. All four verified against source with
> exact anchors before writing this spec (three scout passes). Build order: Attribution → G6 → G1 → G2 — cheapest
> first, and the first two touch the same files.

---

## 1. Attribution line — "Posted via PawPoller" (new ask)

**What:** story + artwork descriptions get a credit line appended at post time. **On by default.** Turning it off
triggers a gentle plea modal ("we understand why — but it would mean a lot if you kept it on") with
**Keep it on** / **Turn off anyway**. Deliberately NOT applied to microblog Posts (char limits, different genre).

**The line:** `\n\n🐾 Posted via PawPoller — pawpoller.pages.dev` — plain text + bare URL so it survives BBCode
(IB/WS), HTML (SF/AO3/SQW) and plain-text description fields alike.

**Where it's applied — the two choke points every posting path flows through** (post, edit, update, retry, scheduler):
- Artwork: `posting/artwork_reader.py` `build_artwork_package` — append after description resolution (lines ~224-231),
  before the `StoryUploadPackage(...)` return (~247).
- Story: `posting/story_reader.py` `build_package` — append after description resolution (~628-645), before the
  return (~699).

**Implementation:**
- New `posting/attribution.py`: `maybe_append(description: str, platform: str) -> str`.
  - Gates on `config.get_settings().get("pawpoller_attribution", True)` (absent = ON).
  - **Skip set: `{"bsky"}`** — the Bluesky poster truncates text to 295 chars inside `bluesky.py` (~69-70), and its
    "description" is an announcement post, not a gallery description; a credit line there would eat the announcement.
  - **Idempotent:** if the description already contains "Posted via PawPoller", return unchanged (protects edit/update
    re-builds and users who typed their own credit).
- Settings UI: **General tab → Publishing accordion** (`app.js` ~10226) gains a checkbox (checked by default),
  **self-saving** (independent of the accordion's Save button):
  - Check → save immediately.
  - Uncheck → **plea modal** first (new tiny `_confirmModal` following the app's `.modal-overlay open` + `.modal`
    convention — modelled on the uninstall dialog `app.js` ~9329-9382; there is no shared confirm helper today).
    "Keep it on 💛" re-checks and saves nothing; "Turn off anyway" saves `pawpoller_attribution: false`.
- Persistence: `POST` the single key through the existing settings-save path (`config.save_settings`).

**Tests:** on→appended (story + artwork package), off→absent, bsky skipped, already-present→no double-append.

## 2. G6 — Alt-text on gallery uploads

**Reality from the scout:** Mastodon is not an artwork poster (Posts-only, which already has alt). Among artwork
platforms only **Bluesky** supports image alt — and today it hard-codes `image_alt=package.title`
(`posting/platforms/bluesky.py` ~92-97). So G6 = a real `alt_text` field that Bluesky uses, stored canonically so
future platforms can map it too.

**Implementation:**
- `posting/artwork_reader.py`: `ArtworkInfo` gains `alt_text: str = ""`; `load_artwork` reads json key `alt_text`;
  `build_artwork_package` passes it through as `package.extra["alt_text"]`.
- `posting/platforms/bluesky.py`: `image_alt=package.extra.get("alt_text") or package.title` (title stays the
  fallback — never regress to empty alt).
- `routes/artwork_api.py`: add `alt_text` to the upload metadata keys (~149-163), the `/create-from-path` twin
  (~210-224), and the PATCH allowlist (~231-232).
- `frontend/js/artwork.js`: "Alt text" input on the upload form (`renderUpload` ~541-556) + the edit-metadata form
  (`renderDetail` ~882-897), with a hint ("describes the image for screen readers; used on Bluesky").

**Tests:** PATCH persists `alt_text`; `build_artwork_package` carries it in `extra`; empty alt falls back to title.

## 3. G1 — Serialized "drip" scheduling

**What:** "post Chapter 1 at T, then one chapter every N days at the same time." A **finite drip**: the campaign is
expanded into N ordinary one-off `posting_queue` rows at creation, each with its own `scheduled_at` — the scheduler
daemon (`posting/scheduler.py` story branch ~161-165: one row = one chapter posted) fires them **unchanged**. No
recurring-rule engine.

**Data:** new nullable `drip_group TEXT` column on `posting_queue`:
- Migration in `database/db.py` `_run_migrations` following the `content_type` pattern (~1014-1021, idempotent
  duplicate-column guard) + added to `database/posting_schema.sql` for fresh installs.
- `posting_queries.add_to_queue` gains `drip_group=None` param → INSERT.
- `posting_queries.cancel_all_for` gains a `drip_group=` filter (it's AND-composed already, ~405).
- `get_scheduled_items` includes the column (it selects the row; verify and surface).

**Endpoint:** `POST /api/editor/stories/{name}/drip` (beside `schedule_publish`, `routes/editor_api.py` ~1791) —
body `{platforms: [...], account_ids?: {}, start: ISO, interval_days: int, chapters?: [...] (default: all),
action: "post", draft: true}`:
1. Validate start is future (reuse schedule_publish's 30s-grace check ~1810-1822) and `1 <= interval_days <= 60`.
2. Per chapter×platform: validate via `story_reader.build_package` + `poster.validate` (reuse ~1824-1842). A chapter
   that fails validation on a platform aborts with a clear error listing the failures (don't half-enqueue).
3. Compute `scheduled_at_i = start + i * interval_days` per **chapter** (all platforms of a chapter share the slot);
   enqueue one row per chapter×platform via `add_to_queue(..., scheduled_at=..., drip_group=<uuid4>,
   title_override="💧 drip {i+1}/{N}")`, `requires` from the poster.
4. Return `{drip_group, slots: [{chapter, scheduled_at}], rows: n}`.

**Group cancel:** `DELETE /api/posting/drip/{drip_group}` in `routes/posting_api.py` → `cancel_all_for(conn,
drip_group=...)`, returns the cancelled count.

**UI:** the story-level **Publish Check** panel (`frontend/js/publish_check.js` — the existing per-cell schedule form
lives ~699/1541) gains a header button **"💧 Drip chapters…"** → small form: platform checkboxes, start
`datetime-local`, "every N days", live **preview of the computed slots** (chapter → local datetime), Go. On success:
toast + the Queue & Schedule page shows the rows (each carries the 💧 badge via `title_override`, which the queue list
already renders); rows with a `drip_group` get a **"Cancel whole drip"** action in the queue list
(`posting.js` `_renderQueueList` ~801 / `_wireQueueActions` ~953).

**Failure semantics (v1, documented):** rows are independent — chapter 3 still fires if chapter 2 failed (the
scheduler's existing retry handles transient failures). Dependency-gating a drip on prior success is a possible v2.

**Tests:** drip creates N×P rows with correctly staggered UTC times + shared group + 💧 title_override; group-cancel
cancels exactly the group; validation failure enqueues nothing; interval bounds enforced.

## 4. G2 — First-run setup wizard → EXTEND the existing one

**Correction (boot-flow scout):** a first-run setup wizard **already exists** — the `#/setup` full-screen route
wizard, gated on `setup_complete` in settings (`app.js` init gate ~246-259; wizard shell ~2426-2432; finish calls
`API.markSetupComplete()` ~2532), with steps welcome → mode → archive → platforms → done, plus a working
"Re-run setup wizard" button in Settings → General (`#btn-rerun-wizard` ~9737, handler ~11843) and server endpoints
(`GET /api/settings/setup-status`, `POST setup-complete` / `setup-reset`). The gap survey's "no operational wizard"
was **wrong** — what the wizard lacks is a *persona* step and a *first-poll* step. So G2 = extend it, not rebuild it.

**Implementation:**
- **New "Your persona" step** (after the platforms-connect step): explains what a persona is (a creative identity that
  groups accounts), one-field form → `API.createPersona({name, color})` (`POST /api/personas`,
  `settings_api.py` ~648-658). Skippable ("I'll do this later" — a default persona can be made any time on Accounts).
- **First-poll offer on the Done step:** if `platforms_connected > 0` (already in `getSetupStatus()`), the Done step
  gains a "Run my first poll now" button → `API.triggerPoll()` (`POST /api/poll/trigger`) + a "polling started — your
  dashboard will fill in over the next few minutes" note. Skippable; the scheduler polls anyway.
- Tour handoff: `#/setup` is already in the whatsnew skip-list (~960) and returns no tour — after finish, the existing
  getting-started tour auto-fires on the dashboard as today. No overlay work needed at all.

**Tests:** persona-create endpoint already covered; wizard is client-only — manual pass (fresh-profile run via
setup-reset).

---

## Ship plan

One release (2.181.0): version bump ritual, CHANGELOG entry per feature under one blockquote, HANDOFF, BACKLOG
(G1/G2/G6 → Done; new row for Attribution), tests green, deploy VM, health check. Leak-scan note: no persona data
involved; the attribution URL is the public marketing site.
