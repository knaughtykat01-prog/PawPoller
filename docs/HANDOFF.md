# PawPoller Session Handoff

**Last updated:** 2026-05-20
**Current version:** 2.23.2 (**Two fixes shipped together.** **(a) Publish-check action log was overlapping the action panel.** User screenshot showed `Recent actions (N)` header + log entries painting on top of the "Save as draft (where supported)" checkbox row inside the cell drawer. Root cause: the action-log placeholder was a **sibling** of the detail panel inside `.publish-check-body` (flex column, `gap: 16px`); with the log populated and the detail content tall, the gap collapsed in some browser layouts and the log overlaid the action panel options. Fix in `frontend/js/publish_check.js`: move the placeholder **inside** the action panel as the last child after `.publish-action-result`, and re-call `_renderActionLog()` after every `detail.innerHTML = html` so the per-session `_actionLog` closure repopulates the fresh placeholder. Three edits: drop the sibling div from `_renderMatrix`; emit it inside `_renderActionPanel`; call `_renderActionLog()` in `_showDetail` after the innerHTML assignment. **(b) FAExport 429 → Retry-After + small pacing bump.** Live FA poll cycle on 2026-05-20 hit two back-to-back FAExport 429s within 2ms — first on a submission detail call (logged + skipped, batch continued), then on the watchers fetch (caught by the broad except in `polling/fa_poller.py:392`, cycle survived but watcher list was lost for the cycle). Same per-IP throttle window; pacing inside the detail loop ran out before the watchers call, and FAExport's bucket is shared across all `faexport.spangle.org.uk` users — so a 429 there is usually someone else's traffic, not ours. Picking the right shape for the fix mattered: bumping pacing alone doesn't help with shared-bucket pressure, and AO3's full backoff-cache pattern (2.22.6/2.22.10) is the wrong shape — AO3 has a fixed-window Rack::Attack counter where requests inside the window extend the punishment, FAExport is a thin proxy without that pathology. Honouring `Retry-After` is the minimum correct change. New `_get_with_retry(url, *, params, max_retries=1, max_sleep=60)` on `FAClient` wraps every FAExport `GET`. On 429: reads `Retry-After` (defaults 30s, clamped to [1, 60]), sleeps, retries once; non-429 passed through untouched so callers still own raise_for_status. Five callers converted: `get_gallery_page`, `get_submission_detail`, `get_submission_comments`, `get_user_profile`, `get_watchers_page`. Direct-FA cookie-validation path unchanged — different throttling shape, wasn't what fired. Also bumped `FA_REQUEST_DELAY_SECONDS = 1.0 → 1.5` as cheap insurance — doesn't help against shared-bucket pressure but cuts our own contribution by a third; ~5s extra per ten-submission detail batch, invisible at the 240-min cadence.)
**Earlier:** 2.23.1 (SoFurry centring + collapse `_Clean.html` / `_SoFurry.html` to one file. SF converter was emitting `<h2/h3 class="text-center">` for titles + chapter headings; SF's site CSS only honours `.text-center` on `<p>`, so the class was silently dropped on render. Editor preview defined its own h2/h3 `.text-center` rule, so the bug was invisible inside the editor. Four sites in the SoFurry converter now emit `<p class="text-center"><strong>…</strong></p>`. Stale dual-file scheme cleaned up at the same time: `regenerate_story.py` only ever wrote `_Clean.html` but story_reader preferred `_SoFurry.html`, so SF posts were uploading months-old snapshots. Renamed output to `_SoFurry.html`, dropped the `_Clean.html` fallback from PLATFORM_FORMAT_MAP[sf]/[ao3] — one canonical file per format.)
**Earlier:** 2.23.0 (**Feature: dashboard UX batch — silence-killers, status surfacing, and a real navigation layer.** 18 small-to-medium changes across three batches that resolve "I clicked a button and got nothing" end-to-end. **Batch 1 (immediate fixes):** slop scorer 0.0 fix (bundled `slop_words.json` + `slop_trigrams.json` into `PawPoller/scripts_utils/` so the cloud server's loader resolves them; added `is_available()` accessor + frontend "Slop: —" state); CSS Decorations dropdown contrast fix (added legacy-token aliases at `:root` for `--surface-elevated` / `--border-primary` / `--color-*` — the `var()` lookups were silently falling through to browser defaults; same fix lifts contrast on every other place using those undefined vars); editor regen result → toast (was dumping the full per-file file-list into the toolbar status, pushing word-count off-screen); toast wiring across all 33 poll/resync entry points (the 22 Settings → Polling-tab handlers collapsed onto a shared `_pollingTabPoll` / `_pollingTabResync` helper, ~240 lines removed); sharper Full Resync confirms quoting platform name + rate-limit risk. **Batch 2 (status surfacing):** new `GET /api/platforms/health` endpoint returning per-platform `{configured, last_poll_at, last_poll_status, last_poll_error, interval_minutes, next_poll_at, throttled_until}` (AO3 throttle sourced from `_ao3_backoff_until_ts` cache); new `frontend/js/platform_health.js` module that polls the endpoint and fans the result out to sidebar grid dots, per-platform header subtitles ("Last polled 47m ago · next in 13m"), and throttle/error banners on platform pages; reusable `[data-tooltip]` helper added to `loading_indicator.js` (1.2s hover delay, single shared DOM node, event delegation on `document`). **Batch 3 (bigger surfaces):** new `GET /api/activity/recent` endpoint merges every platform's `poll_log` + `posting_log` into one chronological feed, surfaced as a "Recent System Events" panel on Overview; empty-state CTAs across all 11 platform dashboards (`Components.platformEmptyState(code)` short-circuit when unconfigured/zero-data); Cmd+K command palette (`frontend/js/command_palette.js`, fuzzy-ranked across every page + 3 actions); notification test suite extended with 3 non-destructive payload-format tests (`format_telegram_summary`, `_classify_error`, `_format_error_for_telegram`) + 13 dashboard-toast checklist rows; drift preview in publish check (new `GET /api/posting/preview-file` returns local file head + hash comparison; cell drawer gets a "Preview file" button); floating logs panel (`GET /api/logs/stream` SSE tail-follow + bottom-left toggle widget with file picker / level filter / pause / sticky-bottom auto-scroll). All 18 items shipped in one release; see CHANGELOG `[2.23.0]` for the full per-item story.)
**Earlier:** 2.22.14 (**Fix: `edit_chapter` respects `publish_live`, no longer silently re-drafts chapters.** 2.22.13's Update-with-live path showed `publish-all-drafts ... published=2, already_posted=3` BUT the drafts came back — chapters wouldn't stick as live. Root cause in `AO3Client.edit_chapter`: it chose the submit button by sniffing the edit-form HTML and PREFERRED `save_button=Save As Draft` whenever present. For draft chapters AO3 renders BOTH buttons, so `edit_chapter` picked "Save As Draft" — **preserving the chapter as a draft after the edit**. The flow per chapter became: edit_chapter (saves as draft) → publish_all_drafts (publishes) → user clicks Update again → edit_chapter re-drafts → repeat. Fix: new `publish: bool | None` param on `edit_chapter`. `True` forces `post_without_preview_button` (keeps live); `False` forces `save_button` (keeps draft, falls back + warning if form has no Save As Draft); `None` is legacy auto-detect (preserved for callers that don't know about live/draft yet). `posting/platforms/ao3.py:edit()` now passes `publish=publish_live if publish_live else None` to every edit_chapter call. With live publish toggled on, each chapter's edit POST publishes directly. publish_all_drafts still runs at the end as a safety net for chapters AO3 has that local doesn't.)
**Earlier:** 2.22.13 (**Fix: AO3 multi-chapter live posts walk every chapter and publish drafts.** User checked work 84822261 after 2.22.11b's success run: stats showed `Chapters: 2/?` with chs 2-4 still rendered as drafts. AO3's per-chapter dev-tools confirmed each draft chapter has its own `<form action="/works/{wid}/chapters/{cid}/post">` "Post Chapter" button. 2.22.8 assumed `post_without_preview_button=Post` on the last `create_chapter` would publish the whole work + all chapters; wrong — AO3 chapters have INDEPENDENT draft state. Fix: new `AO3Client.post_chapter(work_id, chapter_id)` (fetches CSRF from the chapter page, POSTs `commit=Post Chapter`; idempotent — returns `{already_posted: True}` if the page lacks a /post form) + `AO3Client.publish_all_draft_chapters(work_id)` (iterates `get_chapter_ids()`, calls `post_chapter` for each, returns summary `{total, published, already_posted, failed}`, doesn't raise on individual failures). `AO3Poster.post()`: after chapter loop, when `publish_live=True` and `has_chapters`, call publish_all_draft_chapters. `AO3Poster.edit()`: now reads `publish_live = not bool(package.extra.get("draft", True))` (same shape as post); after metadata/content updates, if publish_live, call publish_all_draft_chapters. **For work 84822261:** hit dashboard Update with live-publish toggled on; the edit() flow walks all 5 chapters and posts the 3 remaining drafts.)
**Earlier:** 2.22.12 (**Fix: resumed AO3 posts now attach the Work Skin to the work.** The 2.22.11b end-to-end success run revealed a follow-up nit: work 84822261 posted successfully but the Work Skin (skin_id 11035401) wasn't applied to the work. The skin CSS was on AO3 but the work itself had no `work[work_skin_id]` set. Root cause: `_ensure_work_skin` returns the skin_id, fresh-post passes it to `create_work` so AO3 stores the association at creation. The resume branch (2.22.9) skipped `create_work` entirely — so the skin attachment got skipped too. Work 84822261 was created in an earlier throttled run before the skin existed, so it never had the skin attached. Fix in `posting/platforms/ao3.py:post()`: after resume detects an existing work, if `skin_id` is non-empty, push `edit_work(work_id, work_skin_id=skin_id)` to attach it. Idempotent (resubmitting same skin_id is a no-op). Wrapped in try/except so failure doesn't block the chapter loop. For work 84822261 specifically: hit "Update" on it from the dashboard — `poster.edit()` does this correctly already; the fix just makes it automatic on resume.)
**Earlier:** 2.22.11b (**Hotfix: AO3 poster also honours PROXY_OPTIONAL classification + UI catches up.** 2.22.11 reclassified AO3 in `polling/cf_proxy.py` but the post-deploy log still showed `AO3 client using CF proxy: …` — the poster's `_ensure_client` in `posting/platforms/ao3.py` had its own hardcoded read of `cf_worker_url`/`cf_worker_key` from settings, bypassing the platform classification. The poller was already routed through `proxy_kwargs()`; the poster wasn't. Fix: poster now uses `proxy_kwargs(settings, "ao3")` like the poller. Frontend updated: "CF Proxy Backup" explainer text lists only DA + SF as "always proxy"; AO3 added to the per-platform toggle list (9 platforms total: ib/fa/ws/sqw/ao3/bsky/ik/wp/tw). Verified end-to-end: The Silk-Threaded Bonds posted clean at 05:16 — work 84822261 picked up at resume target, chapters 1-3 detected as existing, chapters 4 and 5 added, `publish=True` fired on chapter 5, publication flipped `partial` → `posted`. Closes the entire 2.22.8 → 2.22.11b cascade.)
**Earlier:** 2.22.11 (**Fix: AO3 routes direct from GCP IP, not through the shared CF Worker.** After 2.22.10 + .10b + .10c stopped the in-window retries and the tight-loop reprocessing, the AO3 throttle window still refused to drain — 14 minutes of doing nothing, only one HTTP request per minute from the queue retry, observed `Retry-After` only dropped from 386s to 325s. Something else was keeping the throttle hot. Cause: AO3 was in `PROXY_REQUIRED_PLATFORMS` (alongside DA + SF) in `polling/cf_proxy.py`, so every AO3 request went through `pawproxy.knaughtykat01.workers.dev`. Cloudflare Workers exit through a shared pool of egress IPs — we were sharing AO3's per-IP quota (300 req/300s from rack_attack.rb at otwarchive v0.9.475.3) with every other Worker tenant pinging AO3 from the same outbound IP. The throttle stayed permanently saturated by aggregate Worker traffic from across all tenants. User's earlier memory note captured this: *"CF proxy: Only needed for DA + SF on server (datacenter IP blocks)."* — AO3 was correctly understood as direct-capable but mis-classified in code. Fix: moved `"ao3"` from `PROXY_REQUIRED_PLATFORMS` to `PROXY_OPTIONAL_PLATFORMS`. Default behaviour now: AO3 routes direct from the GCP VM IP (unique to us, our own quota). Fallback: set `ao3_use_cf_proxy: true` in settings to opt into the optional-platform try-direct-then-fall-back-to-Worker logic. Original classification existed because AO3's login form (`POST /users/login`) throttles datacenter IPs aggressively ("Shields are up!"), but cookie-mode auth (added 2.18.8) bypasses login entirely — the proxy stopped being necessary, it just kept being used because of the 2.18.6 classification. Redeploy clears `_ao3_backoff_until_ts` (process-local module state); first post-deploy request hits a fresh throttle state.)
**Earlier:** 2.22.10 (**Fix: AO3 throttle handling — empty-username URLs, unified backoff cache, no in-window retries.** After 2.22.9's work_id checkpointing was verified working (work 84822261 created + persisted with status="partial"), the post still couldn't complete because `_post_with_retry` kept retrying inside AO3's 300s punishment window, extending the throttle every cycle. Read of the OTW Archive source at v0.9.475.3 (the actual code running on AO3) clarified the mechanics: single per-IP bucket of 300 req/300s, fixed window (not sliding), no login bonus for work-posting endpoints, and — the killer — **requests inside the window count toward the NEXT window's quota**, so any sleep-and-retry-on-429 just keeps us throttled forever. Three fixes in `clients/ao3/client.py`: (1) `is_work_in_drafts`, `is_work_published`, `find_work_skin_by_title` now use `owner = self.username or self.target_user` instead of `self.username`, killing the `/users//{path}` empty-username URLs that 404'd but still cost quota; (2) `_post_with_retry` now calls `_record_throttle()` on 429 (previously only `_get_page` did), so the 2.22.6 module-level `_ao3_backoff_until_ts` reflects every observed window regardless of HTTP method; (3) both `_get_page` and `_post_with_retry` now pre-flight-check the backoff cache and short-circuit immediately if the window is still active; on observed 429 they record + abort without sleep-and-retry. New `AO3ThrottledError(retry_after, url)` raised by `_post_with_retry` so callers can distinguish throttled from generic failures. Bubbles to the AO3 poster's outer try/except → `PostResult(success=False, external_id=work_id)` — 2.22.9's work_id checkpoint means the next queue retry resumes into the same work after the window expires. **Known follow-up:** queue retry counter (1min/5min/30min) can exhaust 3 attempts inside a single 5-minute throttle window if the first failure landed early; pre-flight short-circuit makes the wasted attempts cheap (no HTTP) but they still count. Future fix: have `_schedule_retry()` align with `get_backoff_until_ts()`.)
**Earlier:** 2.22.9 (**Fix: AO3 multi-chapter retry creates duplicate works on transient failure.** First live test of 2.22.8's publish-live wire-up for The Silk-Threaded Bonds (multi-chapter) created work 84818276 successfully via `POST /works`, then 429'd on `GET /works/{id}/chapters/new`. Exception bubbled to `manager.post_story` which queued a fresh `post` action — the retry restarted from `create_work`, creating a duplicate orphaned draft. Every transient post-side failure would have cloned the work. Root cause: `AO3Poster.post()` had no resume awareness — `external_id` was lost when the exception bubbled, so the manager's `upsert_publication(external_id="")` erased the only handle on the partial work. Fix in `posting/platforms/ao3.py:post()`: (1) at entry, look up the publication for `(story_name, 0, "ao3")` — if external_id is non-empty AND status != "posted", set `existing_work_id`. (2) `probe_exists()` to confirm the work still exists; on confirmed 404 (user-deleted between retries) clear the resume target and fall through to fresh `create_work`. (3) when resuming, skip `create_work`, call `get_chapter_ids(work_id)` to build `already_created_chapter_indices`, and skip those in the chapter loop. (4) immediately after `create_work` succeeds, checkpoint via `upsert_publication(status="partial", external_id=work_id, ...)`. (5) on any chapter-loop exception, re-checkpoint before re-raising. (6) failure-path `PostResult` now carries `external_id=failed_work_id` so the manager's next upsert preserves it. Effect: multi-chapter post + transient 429 → retry resumes into existing work, only adds missing chapters, no duplicates. **Still NOT fixed (carried from 2.22.8):** empty-username URL bug at `/users//skins`, `/users//works`; `_post_with_retry` doesn't call `_record_throttle()` so post-side 429s don't populate the 2.22.6 backoff cache.)
**Earlier:** 2.22.8 (**Fix: AO3 always posted as draft, ignoring user's "live" selection.** User reported posting The Silk-Threaded Bonds with "live" selected; work landed in drafts (work 84817651). Three-tier bug chain: (1) `editor_api.py:1680` built `extras` conditionally on `req.draft` truthiness, so `draft=False` produced empty extras and the poster never saw the user's "live" choice. (2) `clients/ao3/client.py:create_work` hardcoded `preview_button=Preview` in the form body — every call created a draft regardless of intent. (3) `posting/platforms/ao3.py:post` had no path to request live posting; the existing `allow_publish` flag only suppressed the post-create safety check. Fix: always carry `extras["draft"]=bool(req.draft)`; new `publish: bool = False` parameter on `create_work` mirroring `add_chapter`'s pattern (swaps button to `post_without_preview_button=Post` when True, returns `published: bool` in dict). Poster reads `publish_live = not extra.get("draft", True)`, defaults to draft for safety. Single-chapter: passes `publish=publish_live` directly. Multi-chapter: creates work as draft, posts Ch2..Ch(N-1) as drafts, LAST chapter uses `publish=publish_live` — AO3's "Post Without Preview" on a chapter publishes the whole work. `_verify_still_draft` bypassed when `publish_live=True`. **Note:** existing draft work 84817651 still sits in AO3 drafts — delete + re-post after deploy. **Future work** surfaced in same investigation: empty-username URL bug (`/users//skins`, `/users//works`) at work-skin creation and post-verification steps in `posting/platforms/ao3.py`; post-side 429s don't populate the backoff cache (2.22.6's `_record_throttle` only called from `_get_page`).)
**Older:** 2.22.7 (**Fix: pawsync silently clobbered dashboard edits — added pre-flight freshness check.** Failure discovered while investigating "why isn't Overtime's cover wired up in story.json": user had added cover + 4 chapter thumbnails via dashboard editor → metadata tab, then a later `pawsync` (local → server) silently wiped them. Clobbered version was preserved in `story.json.bak.1778210960` on the server (dashboard auto-bak on save). Same trap would catch any future dashboard edits made between pawpulls. Fix: new `check_server_freshness()` in `deploy/pawsync.py`, runs before pack/scp/extract. SSHes server, enumerates all `story.json` mtimes via `find ... -printf '%T@ %P\\n'`, compares with local. If any server file is newer by >60s (well above tar's mtime-restore precision), pawsync aborts with exit code 3 and a clear error listing offending paths, timestamps, and minute-deltas, directing user to run pawpull first or pass `--force`. New `--force` flag skips the check for power users intending to overwrite. Local-only tool — no server redeploy needed; running container stays on 2.22.6 behaviour unchanged.)
**Older:** 2.22.6 (**Feature: AO3 backoff-state cache — skip cycles inside an observed throttle window.** The 2.22.4/2.22.5 delay tunes reduce the rate at which we fill our per-IP bucket but can't extract us from a punishment window once we're inside one. Landed in exactly that hole during the 2.22.2-2.22.5 deploy sprint — cumulative pressure had AO3 returning `Retry-After: 349s` then `Retry-After: 326s` on back-to-back tests. Every fresh request inside an active throttle window can extend the punishment. Module-level `_ao3_backoff_until_ts: float` in `clients/ao3/client.py` updated by `_get_page()` every time it observes a 429+Retry-After. New `get_backoff_until_ts()` returns the unix expiry. `run_ao3_poll_cycle()` checks this first; if a window is active, returns a stub `{submissions_found:0, snapshots_inserted:0, new_kudos_found:0, skipped_reason:"throttled, Ns remaining"}` and logs a clear `AO3 poll skipped — N s remain in observed throttle window`. Process-local (resets on restart, rebuilt by the first 429 of any fresh cycle). Defense-in-depth: 2.22.4/2.22.5 (slower pacing) prevents new throttles; 2.22.6 (this) prevents existing throttles from being extended by our own retries.)
**Older:** 2.22.5 (**Tune: AO3 inter-request delay 6s → 12s (aggressive generosity).** 2.22.4's bump 3s → 6s was the external-tool baseline (kenalba/ao3-scraper), but the first live cycle on the new pacing still hit `AO3: 429 rate limited on .../users/KnaughtyKat/works?page=1, waiting 349s (attempt 1/3)`. Proximate cause was cumulative pressure from earlier 3s-pacing cycles + 2.22.2 probe-burning cycles — once inside AO3's punishment window, escalation is sharp. Double again: `AO3_REQUEST_DELAY_SECONDS = 6.0 → 12.0`. This makes us slower than every comparable AO3 scraper and gives the per-IP bucket comfortable headroom to drain between requests. Cost ~60s extra wall time per ten-work cycle, still invisible at the 240-min cadence. If 12s isn't enough either, the next move isn't more delay — it's **backoff-state caching** (skip a cycle entirely when mid-punishment-window) rather than enqueuing requests that will inevitably 429. Not shipping that today — wait and see how 12s does across a few cycles first. The 2.22.4 entry below explains the methodology and source comparison.)
**Older:** 2.22.4 (**Tune: AO3 inter-request delay 3s → 6s.** Comparative read of FanFicFare issue #1149, kenalba/ao3-scraper, and the AO3 admin posts around the 2024-25 AI-scraper escalation confirmed our 3s pacing was more aggressive than the widely-used 6s baseline. AO3 tightened its per-IP throttle after the 2023 DDoS and again during the AI-scraper situation; 3s used to be fine, 6s is the current "polite-citizen" rate most actively-maintained downloaders converged on. Concrete change: `AO3_REQUEST_DELAY_SECONDS = 3.0 → 6.0` in `config.py`. Cost ~30s extra per cycle on a ten-work scrape — invisible at the 240-min cadence. Architectural note from the audit: PawPoller is already ahead of every comparable external AO3 tool on throttling (cookie-only auth, CF Worker egress, real `Retry-After` parsing, multi-attempt retries) — the conservative delay was the one missing piece.)
**Older:** 2.22.3 (**Fix: AO3 poll cycle's redundant cookie-validation probe.** After 2.22.2 enabled cookie-only AO3 polling, the first live cycle hit `AO3: 429 rate limited on https://archiveofourown.org/users/KnaughtyKat, waiting 118s` before the actual work-discovery scrape even started — exactly the throttle cookie-only auth was meant to avoid. Root cause: `polling/ao3_poller.py:run_ao3_poll_cycle` called `client.validate_session()` as its step-1 auth check, which does an extra `/users/{target}` fetch to confirm the cookie is alive (its docstring says "Only used by /auth/connect" but the poller was calling it too). `ensure_logged_in()` already trusts a pasted cookie without fetching — written specifically to avoid this throttle. Fix: poller step-1 now uses `ensure_logged_in()`. Cycle's actual work (works-list scrape + per-work detail fetches) still fails loudly if the cookie has expired, so the probe added only latency, not safety. The original AO3 fix landed in 2.22.2 — see CHANGELOG for the orchestrator gate widening that re-enabled AO3 polling. Verified post-deploy: 1 submission, 2 new kudos recorded on first cycle.)
**Older:** 2.22.2 (**Fix: AO3 polling was skipped on cookie-only auth.** Poll orchestrator's per-platform gate at `server.py:213-214` required both `ao3_username` AND `ao3_password` before scheduling AO3 in the cycle. AO3 has supported cookie-only auth since 2.19.3, and the recommended path on GCP is cookie-only (AO3's form-login endpoint has a 5-10 minute per-IP cooldown that makes cold-login from datacenter IPs effectively unusable). Any deployment that wired AO3 via `_otwarchive_session` was silently excluded from every poll cycle — dashboard never populated, kudos counts stayed at 0, kudos users were never tracked, daily digest had no AO3 section. Live VM was hitting this: `data/settings.vault.json` had `ao3_session_cookie` + `ao3_target_user` but no username/password, so log line `Polling N platforms (ib, fa, ws, sf, sqw, da, wp, ik)` consistently omitted `ao3`. Fix: widen the gate to `(ao3_username AND ao3_password) OR ao3_session_cookie`, mirroring `_get_or_create_client()` and `validate_session()` which already handle cookie mode end-to-end. SquidgeWorld gate was correct already — `sqw_username AND sqw_password` matches how SqW is configured; the "likewise for squidge" precaution turned out to be a non-issue (one SqW work in the live DB has favorites_count=1 confirming the kudos pipeline works there). File: `server.py`.)
**Earlier:** 2.22.1 (**Feature: Global activity spinner + toast notifications.** During the v2.22.0 rollout the user noted that when triggering a publish/schedule/forget action, nothing visible happened during the in-flight window then either the inline result panel flickered or the matrix silently refreshed. Two new always-on UI affordances: (1) Top-right activity spinner — `frontend/js/loading_indicator.js` wraps `window.fetch` once (idempotent), shows a subtle 18px dot-ring with accent glow whenever any request is in flight, 250ms delay before showing so trivially-fast requests don't flash, badge shows in-flight count when >1. SSE via EventSource is a separate API so long-lived regen / diagnostics streams don't pin it on. (2) Bottom-right toast stack — `window.toast.{success,error,warn,info}`. Auto-dismiss 4s success/info or 6s error/warn, click ✕ earlier, slide-in/out. Wired into the highest-traffic handlers in `publish_check.js` (post/update/update_metadata/publish_draft via `_executeAction`, `_submitSchedule`, URL-anchor handler, forget-publication handler). Each toast carries action+platform+chapter context. Also exposes `window.withLoading(btn, asyncFn)` helper that disables a button + swaps its label for a small spinner while preserving its width. Opt-in per call site — not auto-applied. New files: `frontend/js/loading_indicator.js`, `frontend/css/loading_indicator.css`. JS loads BEFORE `utils.js` so the fetch wrap is in place before any other module fires a request.)
**Earlier:** 2.22.0 (**Feature: PawPoller CLI — menu-driven TUI for the dashboard API.** Single-file Python TUI under `cli/pawpoller_cli.py` that runs locally (against the GCP VM) or on the VM itself (against 127.0.0.1) with identical UX. Top-level menu has 5 sections: Polling (pause/resume/trigger/full-resync/status), Publishing & Queue (view/cancel queue, publish matrix, post/update/dry-run/schedule with draft + live-publish confirmation, forget publication, set URL manually), Diagnostics (run one/category/suite, attach to active, SSE-streamed live progress with per-test colours), Stories (list/regen one/regen all + SSE stream/attach/probe drafts), Settings & Status (ping, view posting settings, list API key prefixes, show/re-run config). Tech: `rich` for menus+tables+panels, `httpx` for HTTP + SSE streaming. Config resolution: env vars `PAWPOLLER_URL` + `PAWPOLLER_KEY` → `~/.pawpoller-cli.json` → VM hint. Launchers ship: `cli/pp.cmd` (Windows) + `cli/pp.sh` (Unix). Install: `pip install -r PawPoller/cli/requirements.txt`. Out-of-scope for v1 by design: story body editing, auto-launch on SSH login, API key / TOTP setup. Two follow-ups worth doing next: (1) one-line `.bashrc` entry on the VM to auto-launch `pp.sh` on login so SSH = TUI, (2) a `/api/posting/queue/cancel-all` bulk endpoint to reduce CLI HTTP roundtrips when nuking a stuck queue.)
**Earlier:** 2.21.1 (**Fix: SquidgeWorld / AO3 phone-call and text-message styling lost without explicit anchors.** User reported Hypnotic_Claim's SqW chapters were rendering `**ETHAN ❤**` and `**ETHAN ❤: Hey babe...**` as plain centred / left-aligned bold paragraphs instead of the styled phone-bubble UI defined in the Work Skin CSS (`.phone-display-wrap`, `.phone-display`, `.text-message`). Root cause in `editor/converter.py:_convert_body_clean_html`: the heuristic fallback (non-anchored detection via `is_phone_display` / `is_text_message`) emitted plain `<p><strong>...</strong></p>` instead of the styled divs that the semantic-anchor branch above (lines 500-535) already produced for stories with `<!-- @phone-incoming --> / <!-- @text-sent --> / <!-- @text-received -->` markers. Stories like Hypnotic_Claim that don't carry the anchors silently fell back to plain markup. Fix: heuristic emits the same `<div class="phone-display-wrap">` and `<div class="text-message">` structure as the anchor path. Without anchors we can't distinguish sent/received so text-message divs get no modifier class — the Work Skin's base `.text-message` rule still applies. Also updated `m_x/Scripts_Utils/regenerate_story.py` (separate repo) with the same post-process pass `apply_phone_text_styling()` since regen builds SqW + Styled HTML from SoFurry HTML body lines, not from PawPoller's converter — both paths fixed, Hypnotic_Claim re-regened and pawsync'd to server.)
**Earlier:** 2.21.0 (**Feature: Per-cell publish-check controls — manual URL anchoring, forget publication, cancel scheduled.** Three additions to the expanded-cell drawer in Publish Check, driven by the Hypnotic_Claim AO3 incident where the publications row was stuck on a now-deleted draft, the stored URL was wrong, and three jammed `processing` queue rows had no UI cancel. (1) **Set URL** — input + Apply in the Existing publication block. Pastes the live URL, server-side regex extracts the platform's external ID (`_URL_ID_PATTERNS` covers all 11 platforms), both `publications.external_url` and `publications.external_id` get overwritten so drift/edit operations target the right submission. (2) **Forget this publication** — button that deletes the publications row only (no upstream call). Confirms by `prompt()` requiring the user to type the platform code; backend also requires `confirm_platform=<platform>` query param. Reverts cell to "ready" so next post creates fresh. (3) **Cancel scheduled — processing + bulk** — fixed the v2.20.3 follow-through. Per-row Cancel was hidden client-side for non-`pending` rows but the backend has handled pending/retrying/processing/failed since 2.20.3; gate widened. New bulk-cancel button "Cancel all (N)" appears in the scheduled header when >1 item; backed by `DELETE /api/editor/stories/{story}/scheduled?platform=&chapter=`. `cancel_all_for` extended with `chapter_index` filter. New helpers `delete_publication()` and `update_publication_url()` in `database/posting_queries.py`. Three new endpoints in `routes/editor_api.py`. UI lives in `frontend/js/publish_check.js` + styles in `frontend/css/editor.css`.)
**Earlier:** 2.20.7 (**Fix: AO3 `create_chapter` recovers chapter_id when AO3 omits it from the response URL.** Hypnotic_Claim posted successfully to AO3 — work 84754866 + chapter 2 (id 223668966) both exist server-side — but the publish task crashed with "Could not extract chapter_id from response URL: …/works/84754866/chapters". AO3 returned the form POST result at the bare `/chapters` URL with no ID, and the v2.20.3 body-scan fallback was gated on success-marker strings ("Draft was successfully created" / "<title>Preview Work" / "<title>Edit Chapter") that didn't appear in the actual response body — so the parser hard-failed even though the chapter was real and live. Two changes to `clients/ao3/client.py:create_chapter`: (1) drop the success-marker gate on body scanning — we already detect AO3's error page ("Sorry! We couldn") and non-2xx earlier in the function, so if we get past those, any `/works/{work_id}/chapters/(\d+)` reference in the body IS a valid chapter ID; pick the maximum since AO3 chapter IDs are monotonically increasing. (2) Last-resort `/works/{work_id}/navigate` fetch — full-page chapter index, includes drafts — grab the max ID there. If both fail, dump the response body to `{tempdir}/ao3_chapter_debug_{work_id}_{ts}.html` for postmortem. **Verified server-side via Playwright**: work 84754866 has 9,815 words across two chapters (223668946 + 223668966) so the fix is just about recognising what AO3 already did, not about retrying.)
**Earlier:** 2.20.6 (**Fix: AO3 publish package file priority — second half of the SqW switch.** v2.20.2 flipped the AO3 post content from Clean HTML to SquidgeWorld concatenation, but only on the read-path in `posting/platforms/ao3.py:_read_full_story_html`. The publish-matrix package builder at `posting/story_reader.py:FORMAT_SPECS["ao3"]` still listed `HTML/*_Clean.html` first, so the package's `file_path` (what the UI shows, what `validate()` checks, what gets stamped on the publication row) still pointed at Clean even though the post body itself came from SqW. This v2.20.6 swap completes the change — SqW first, Clean fallback. Now consistent everywhere.)
**Earlier:** 2.20.0 (**Feature: Regenerate-all-stories.** Bulk rebuild of every story's derived formats from MASTER.md, exposed as the editor's `↻ Regenerate All` button and as `archive.regenerate.all_stories` in Diagnostics. SSE-streamed live progress + Ctrl-C-style detach + concurrency-locked. Thin orchestrator design — calls the existing per-story regen endpoint in-process so per-story behaviour stays the single source of truth.)
**Earlier:** 2.19.0 (**Feature: Diagnostics & testing tab.** 82 bespoke live-system tests + the pytest suite as a parsed sub-runner, ~170 individual rows. New `testing/` package: registry decorator, async runner with concurrency lock + per-test timeout, SSE event streamer, results store. 12 categories from Infrastructure / DB through Pytest Suite. Destructive tests gated behind per-test confirmation. See §16 in documentation_guide.md.)
**Older versions:** see `CHANGELOG.md` for the full version-by-version history (2.18.x through 2.20.x covered there in detail). Notable foundations still in active use: **2.18.8** introduced AO3 dual-mode auth (username/password OR session cookie); **2.18.13** moved IB creds into Settings → Platforms and fixed the pywebview multi-`start()` bug for browser-login; **2.18.16** added the `requires_mode` SQL filter to `get_pending_queue` so server-incompatible rows don't starve compatible ones at the head of the FIFO; **2.20.3** made cancelled queue rows sticky against scheduler retry overwrites; **2.20.5** wrapped WeasyPrint PDF rendering in `asyncio.to_thread()` so bulk regen no longer freezes the event loop. The 2.14.3 file-tree refactor moved all 11 platform clients into `clients/` (e.g. `clients/ib/`, `clients/ao3/`) and internal docs into `docs/` — imports use `from clients.ib.client import InkbunnyClient`.

**Deployed to:** GCP instance `pawpoller` (zone `us-east1-c`), running 2.22.14. **Master is at 2.23.0 — needs `pawupdate` to ship.**
**GitHub master:** https://github.com/knaughtykat01-prog/PawPoller — push-to-master triggers no auto-deploy; run `pawupdate` (or `deploy/pawcli.bat` → menu) to ship.

Living document — update as the roadmap shifts. Read this first when picking up a fresh session.

---

## What PawPoller is

Multi-platform story publishing + polling pipeline for furry fiction. Runs two ways:

- **Desktop** (Windows): `main.py` → PyInstaller bundle → pywebview + pystray. Needed for FA posting (datacenter IP blocks) and PDF rendering via Edge fallback.
- **Headless** (GCP/Docker): `server.py`. Polls 11 platforms, serves the dashboard + editor, posts to everything except FA (which gets auto-queued to desktop).

Port 8420. Story archive mounted at `/app/story-archive` on server, `../m_x/Archives/Complete_Stories/` locally.

---

## Where we are right now

**Public beta ready.** All must-have and should-have items from
`ROADMAP_PUBLIC.md` are implemented. The app has a setup wizard,
embedded browser login, credential encryption, story creation wizard,
multi-format editor with anchor toolbar, selective regeneration,
publish check with scheduling, retry queue, per-platform descriptions,
cover/chapter thumbnail uploads, and GitHub release packaging.

### What's working live on the server

| Feature | Version | Notes |
|---------|---------|-------|
| Markdown editor with anchor system | 2.7.0 | `<!-- @title -->`, `<!-- @body -->`, text-messages, phones, story-end |
| Theme editor + CHAPTER_STYLING.md save | 2.7.0 | 14 colour vars + section break + warning icon, `.bak.{ts}` snapshot |
| Format regenerator (`/regenerate`) | 2.7.0–2.9.0 | Clean/SoFurry/BBCode/SquidgeWorld/Styled HTML + **native PDFs via WeasyPrint** |
| Native PDF generation | 2.9.0 | WeasyPrint primary (Linux), Edge fallback (Windows). `skip_pdf=False` by default |
| Tag database | 2.8.0–2.8.1 | 8,757 fiction + 11,932 image tags + 23,159 aliases + 26,829 e621 lookup entries |
| Metadata editor drawer | 2.8.0 | 8 sections: basics, cover, classification, characters, tags, chapter tags, chapters, advanced |
| Tag autocomplete + e621 lookup + "+Library" | 2.8.0–2.8.1 | Local DB hits + e621 fallback with "add to library" button |
| Per-chapter tag editing | 2.8.2 | Same UI as story tags, no cross-platform sync |
| Publish Check matrix | 2.9.1 | Chapter × platform validation grid, detail panel |
| Full-story row in matrix | 2.9.3 | Also fixed DA/IK/Bsky tag cascade from default |
| Post / Update / Dry-run actions | 2.9.2 | confirm_live guard on backend, frontend confirm() dialog |
| Content drift detection | 2.9.4 | Flags cells where local file hash differs from posted hash |
| **AO3 chaptered posting** | 2.10.0 | create_work + create_chapter loop, mirrors SQW |
| **AO3 work skin upload** | 2.10.0 | `_ensure_work_skin` on post + edit, auto-refreshes CSS |
| **Metadata only update button** | 2.10.0 | Skips content refresh via `skip_content_refresh` extras |
| **Upstream deletion probe + /verify** | 2.10.0 | SF / IB / AO3 / SQW probed; deleted cells flip to ⊘ |
| **SF/FA edit content refresh** | 2.10.0 | edit() now calls replace_file() for drifted uploads |
| **AO3 edit safe-overlay** | 2.10.0 | Fetch form → overlay → resubmit with save_button |
| **Tag cascade all platforms** | 2.10.0 | Default tab syncs to every poster (except BSky) |
| **Chapter prefix strip** | 2.10.0 | AO3/SQW don't show "Chapter 1: Chapter 1: Title" anymore |
| **Email-login account resolution** | 2.10.0 | SQW/AO3 login with email resolves to account name for URLs |
| **Metadata-only chapter retitles** | 2.10.0 | AO3/SQW edit_chapter now supports content=None (title-only edits preserve body) |
| **Shields-up resistance** | 2.10.0 | AO3 login uses full Chrome 131 header set + homepage warmup |
| **Bug hunt round** | 2.10.0 | DELETION_PATTERNS tightened, /verify hardened with try/except + rate limit, duplicate /sync/status removed, theme-save no longer wipes trailing content, Publish Check _currentStory race fixed |
| **SF chaptered posting** | 2.10.3 | One submission with N chapters via /content append, chapter titles set, front matter prepended to ch1 |
| **FA deletion probe** | 2.10.3 | probe_exists checks /view/{id}/ for 404 / "not in our database" |
| **Nested story path fix** | 2.10.3 | publish-check/publish/verify now resolve The_Abstinent_Bet/Nice_Version correctly |
| **AO3 CF proxy on desktop** | 2.10.3 | Routes through Worker to bypass Shields-up TLS fingerprinting |
| **Per-chapter anchor processing** | 2.10.3 | /regenerate uses body converter directly so text-message anchors render |
| **Phase 6e safety polish** | 2.10.5 | Live-publish warning banner, readable dry-run results, per-session action log, relative timestamps |
| **Phase 7a settings sync** | 2.11.0 | Cloud sync endpoint, desktop startup pull, dashboard sync buttons |
| **Polling backlog** | 2.11.0 | Session recovery, N+1 batching, AO3 429 retry, exc_info logging, Telegram error UX |
| **Tag editor overhaul** | 2.11.0 | Space→underscore, sort A-Z, Selected filter, platform badges, format fix |
| **Editor quick wins** | 2.11.0 | Anchor toolbar, regen staleness warning, edit button from posted stories |
| **Selective regen** | 2.11.0 | Dropdown for HTML/BBCode/Styled/SQW/PDF/chapters |
| **Per-platform descriptions** | 2.11.0 | Short (IB/SF) + Announcement (Bsky) fields in metadata drawer |
| **Retry queue** | 2.11.0 | Auto-retry failed posts with 1min/5min/30min backoff |
| **No-credentials status** | 2.11.0 | Lock icon for unconfigured platforms in Publish Check |
| **Skip startup polling** | 2.11.0 | No more rate-limiting on app restart |
| **Format tab bar** | 2.11.1 | Compact tabs replace format dropdown in editor |
| **Weasyl cover upload** | 2.11.1 | coverfile support in submit_literary |
| **Credential vault (7b)** | 2.12.0 | Fernet encryption, keyring/dotfile key, vault enable/disable API + UI |
| **New story wizard (9b)** | 2.12.1 | Create New Story button, template MASTER.md, folder scaffolding |
| **Per-chapter thumbnails** | 2.12.1 | Upload per-chapter covers in metadata drawer, auto-updates story.json |
| **Genre templates (9b ext)** | 2.13.0 | 9 presets (Romance, Erotica, Adventure, Comedy, Drama, Fantasy, Sci-Fi, Slice of Life, Horror) pre-fill tags/rating/warnings in story wizard |
| **Import from platforms (14a)** | 2.13.0 | IB/SF/FA — downloads content, converts BBCode/HTML→Markdown, tracks `import_source` in story.json. AO3/SQW "coming soon" |
| **Story wizard file upload** | 2.13.0 | Optional `.md`/`.txt`/`.html`/`.bbcode`/`.rtf` upload replaces template MASTER.md |
| **Configurable default author** | 2.13.0 | 7 hardcoded author references in `converter.py`, `generate_story_json.py`, `story_reader.py` replaced with `default_author` setting |
| **GitHub release packaging (15a-c)** | 2.13.0 | README, MIT LICENSE, CONTRIBUTING, `.github/workflows/build.yml` + `lint.yml`, `.env.example` |
| **Anchor toolbar fix** | 2.13.1 | `_insertAnchor` was calling `this._cm` (never assigned) instead of `this.cmView`. All 8 buttons were silent no-ops since 2.11.0 |
| **Publish-check IndexError fix** | 2.13.2 | `_load_from_story_json` derived `total_chapters` from `data["chapters"]` (declared), but the subsequent index loop used `story.chapters[i-1]` (from `chapter_info`). Wizard-created + single-piece stories (`chapters: N, chapter_info: []`) crashed. Now `total_chapters = len(chapter_info)` |
| **Vault + regen diagnostic errors** | 2.13.3 | `/vault/enable`, `/vault/disable`, and PDF regen now surface the actual exception type + message instead of a masked 500. `errors[]` gets a specific reason when full-story PDF is skipped (missing Styled HTML precursor vs. empty render output). Frontend vault buttons show the detail inline |
| **PDF Edge fallback polish** | 2.13.4 | `--no-pdf-header-footer` added so Edge-rendered PDFs no longer get browser date/URL banners. `_build_print_styles()` sets theme background on `html` too so the theme colour runs past the `@page` margin |
| **Full-bleed print background** | 2.13.5 | `@page { margin: 0; size: A4 }` inserted inside `@media print` in both colour-preserve and grayscale branches. `.print-container` padding (2cm 2.5cm) keeps the visual margin while the theme colour goes edge-to-edge |
| **Anchor toolbar wraps selection** | 2.13.6 | Buttons act on the active selection: paired anchors wrap the selected text, standalone anchors sit on the line above. CM selection and unique-match Rich Editor selection both supported |
| **Anchor toolbar realignment + tooltips** | 2.13.7 | Toolbar audited against `FILE_FORMAT_STANDARDS.md`. `@story-end`, `@text-end`, `@phone-end` removed (all fake); `@phone` → `@phone-incoming` (converter's real name); Byline/Disclaimer/Fanfiction buttons added. Every anchor now inserts a single-line label at the start of the target line — no more paired wraps (the converter never supported them). 1.2s hover tooltip (2.13.8) with label / purpose / before-after preview |
| **Inline anchor labels + tooltip pacing** | 2.13.8 | Inline buttons relabelled `→ Sent` / `← Recv` / `☎ Phone`; tooltip delay dropped from 2000ms to 1200ms |
| **Vault-mode init order fix** | 2.13.9 | Module-level `_settings = _load_settings()` was crashing with `NameError: _decrypt_vault` on servers with `credential_mode: "local"` because the vault helper block lived ~300 lines below the import-time call. Moved the vault block above `_load_settings`. Unblocked deploying 2.13.x to GCP |
| **8-theme picker (browser + native)** | 2.14.0 | Generalised binary dark/light toggle into 8 cohesive themes via `[data-theme=...]` blocks: dark, light, ink_copper, parchment, midnight_press, forest, velvet, high_contrast. New Settings → Appearance tab with picker grid. Adaptive tokens (`--card-border-inner`, `--overlay-backdrop`, `--shadow-strong`) avoid per-component overrides. No-flash inline theme apply in `<head>` |
| **Vibe Pack — typography cohesion** | 2.14.1 | Crimson Pro for h1/h2/h3 + page headers + sidebar wordmark, Inter for body, JetBrains Mono for code. Subtle radial body wash (copper top-left, sage bottom-right via theme-aware `--bg-glow-warm`/`--bg-glow-cool`). New `.chip` component, copper diamond brand mark on sidebar wordmark. Closes the cross-surface cohesion gap with the marketing site without sacrificing dashboard density |
| **Settings auto-sync** | 2.14.2 | Built on the existing 7a sync endpoint. `auto_sync.py` schedules a debounced 2s push on every desktop save and runs a 5-min pull thread; thread-local `_in_pull_merge` guard prevents pull→save→push echoes; localhost-resolved targets skip (so the cloud server can't sync to itself). Browser tabs re-pull prefs on `visibilitychange` so theme changes flow between desktop and browser within seconds. New `auto_sync_enabled` toggle on Appearance tab (default true). Bug fix: `theme` was being silently dropped by the preferences POST handler so it was localStorage-only — now persists to settings.json properly |
| **Repo file-tree cleanup** | 2.14.3 | Pure organisation. 11 platform clients consolidated under `clients/{ib,ao3,bsky,da,fa,ik,sf,sqw,tw,weasyl,wp}/` (60 .py files import-rewritten via one sed pass; PyInstaller spec + Dockerfile needed no changes). Internal docs moved to `docs/` (README/LICENSE/CONTRIBUTING/CHANGELOG stay at root). 3 root-level orphans deleted. Validation: 166 .py files parse, 47 modules import smoke-test, 30/30 unit tests pass, PyInstaller bundle builds end-to-end |
| **Coordinated desktop ↔ server architecture** | 2.14.6 | Closes the dual-polling gap: explicit `setup_mode` (standalone / paired_desktop / server) + `get_polling_owner()` helper decide which instance owns the poll loop. Desktop wizard rebuilt around a Q1 mode question with a paired-pairing flow that validates URL+API key via `/api/settings/pair-test` and triggers an immediate first-pull. Server runtime force-stamps `setup_mode = server` on boot. Settings page gets a "Setup Mode" panel + "Re-run setup" button so users can flip modes without reinstalling. `auto_sync` now refuses to push when running as the server (closes a foot-gun where a stray `posting_server_url` would loop the server back to itself). `SYNC_EXCLUDE` expanded to keep desktop-only fields out of the server's settings dump. 91 tests still green |
| **Audit-debt refactor pass** | 2.14.5 | Cashed in three of four audit-pass-debt items from 2.14.4. (1) `polling/notifications.py` extracted — `show_toast`, `send_telegram`, `format_telegram_summary`, plus two convenience wrappers. 489 lines deleted across 11 pollers, ~150 added in the helper. Per-platform filters stay in each poller. (2) CI test runner switched from `unittest discover` → `pytest` — was silently skipping `test_integration_posting` + `test_platform_posters`. CI now runs 91 tests instead of 30, all green. (3) N+1 batching for `get_*_comparison_snapshots` across all 11 query files — `WHERE submission_id IN (...)` instead of one SELECT per submission. (4) `config.get_settings()` route caching turned out to be largely a false alarm — most apparent duplicates were across separate handlers, only `settings_api.sync_status` had a real double-call. Fixed |
| **EPUB output (Vellum-style)** | 2.17.0 | New `editor/epub_generator.py` (~600 LOC). Spine: cover → title page → copyright → author's note → content warning (front or back, configurable) → chapters. Word-form chapter numbers + drop cap, italic-narration body preserved. epubcheck 5.1.0 / EPUB 3.3 clean (0/0/0/0). Wired into regenerate dropdown as new `epub` format with `epub_warning_position` request field. |
| **EPUB visual polish** | 2.17.1 | Chapter heading kept dropping the source prefix word — `_split_chapter_heading` now returns `("Part One", "The Seduction")` not just `("One", "The Seduction")`. Trailing `---` between chapters was emitting a stray `<hr>` that created a blank page in Apple Books — `_strip_trailing_separators` drops them. Text-message CSS reworked into sender-tagged card style that works regardless of whether anchors are used. |
| **EPUB own folder + auto-discovery** | 2.17.2 | Output moved from `Markdown/{stem}.epub` → `EPUB/{stem}.epub` to match the per-format folder convention. `posting/generate_story_json.py:_discover_formats` flips `formats["epub"] = True` automatically when the folder has files. |
| **Format downloads (mobile-friendly)** | 2.17.3 | EPUB triple-broken in 2.17.0–2.17.2 — not in `_FORMAT_KEY_PATTERNS`, not in `_DOWNLOAD_EXTENSIONS`, no media-type. All three fixed. New `GET /api/posting/archive` streams the entire story folder (excluding `Backups/`) as a zip via `StreamingResponse`. Two surfaces: "Download all (zip)" footer on the Available Formats card on the published-story page, and a new "Downloads ▾" dropdown in the editor toolbar that lazy-fetches the format list and includes the zip. |
| **Downloads dropdown polish** | 2.17.4 | One row per format, fixed display order (EPUB → PDF → Styled HTML → Clean HTML → SoFurry HTML → BBCode → Markdown). Per-chapter formats (`chapter_bbcode`, `squidgeworld`) hidden — the zip covers them. Proper CSS (`.downloads-row` flex layout, `.downloads-zip` styled footer, `.downloads-empty` muted state). |
| **`pawsync --prune`** | 2.17.5 | Closes the "manual `rm -rf` after deleting test stories" gap. `pawsync.py` accepts `--prune` (removes server-side top-level dirs missing locally; `Backups`/`Drafts`/`Styled_HTML` untouchable) and `--dry-run` (lists without removing). Default behaviour unchanged — `pawsync.bat` keeps the additive `tar xzf` semantics. Roadmap also corrected: cache-buster consistency and CI pytest items were stale (already done in earlier versions). |
| **In-app EPUB viewer** | 2.17.6 | Vendors `epub.js` 0.3.93 + `jszip` 3.10.1 to `frontend/vendor/`. New `frontend/epub-viewer.html` + `frontend/js/epub-viewer.js`: minimal toolbar (close/title/prev/percent/next/download), full-bleed reader, 18% tap zones, keyboard arrows, theme tokens resolved into the rendered iframe via `rendition.themes.default`. `dashboard.py` mounts `/vendor` static prefix (auth-exempt parity with `/css/`, `/js/`), serves `/epub-viewer.html` with cache-buster substitution, and adds `_build_epub_viewer_csp()` — a path-scoped relaxed CSP that allows `blob:` in style/img/font/connect/frame so epub.js's extracted resources render. Strict default CSP unchanged for every other path. Editor Downloads dropdown grows a "↗ Preview in browser" sub-row under EPUB. Two non-obvious gotchas: (1) `ePub(url, { openAs: 'epub' })` is mandatory — the URL path is `/api/posting/file` (the `.epub` lives in the query string), so epub.js's default extension sniff fails and the loader hangs trying to read `META-INF/container.xml` as a directory; (2) the inline boot script in the viewer must be byte-identical to `index.html`'s so the existing CSP SHA-256 hash covers it (verified via `hashlib.sha256` — both hash to `WudoxBejEmzS4SXsQBia7rsNZctlaFiey3RvF0r8SzA=`). |
| **Mobile Mode (Phase 5 sweep)** | 2.16.4–2.16.8 | After-deploy audit pass. **2.16.4** hot-fixed the silent CSP block that had been dropping every `data-mobile` rule since 2.16.0 — inline boot-script SHA-256 hash had to be re-computed in `dashboard.py`. **2.16.5** added page-header `padding-left:60px` so titles ("Overview", "Settings") aren't half-hidden behind the hamburger, and `!important` on stats-grid 1-col rule to beat the inline JS style on the per-platform grid. **2.16.6** wrapped `.page-header` and gave its inline-styled action div 100%-width / 50%-flex buttons so 4-button rows (Save Settings / Poll Now / Full Resync / Clear Session) flow into 2×2 instead of forcing the doc to 830px. **2.16.7** clamped `.settings-tabs` (`max-width:100%`+`min-width:0`) so the existing scroll-x actually engages, plus `.main-content { max-width:100vw; overflow-x:hidden }` as defense-in-depth. **2.16.8** closed deferred backlog: SameSite=Strict→lax (fixes periodic 401 bursts on prod), favicon-401 exemption, `/api/health` exposes `version`. |
| **Mobile Mode (Phase 3)** | 2.16.2 | Vertical sweep — every multi-col grid (growth/goal/card/story/tag/chart-row/theme/fa-metadata/setup-platforms) forced to 1-col on mobile. Detail header → thumb-on-top vertical. Pinned row scroll-snap → vertical stack. Compare chips → full-width buttons. Date range → wraps in 3-up rows. Settings rows toggle right-aligned. Log + timeline → single column. |
| **Mobile Mode (Phase 2)** | 2.16.1 | Portrait-phone polish after a real device pass. iOS 16px floor on all inputs (no auto-zoom on focus). Editor toolbar collapses behind ⋯ More button; only back/title/⋯/Save/Metadata visible by default. Bottom nav swap: Editor replaces Analytics. Stat cards become 1-col horizontal strips. Page header h2 17px + tighter margins. Chart-modal + platform-grid full-screen with safe-area. Submission cards 1-col with 200px thumbs. |
| **Mobile Mode (Phase 0 + 1)** | 2.16.0 | Settings → Appearance toggle (auto/on/off) sets `<html data-mobile="0\|1">`. Editor 4-pane quad → single-panel switcher (Edit/Rich/Format/Preview tabs). Anchor toolbar → 44px swipe strip. Publish-check matrix → expandable chapter cards with status summary. Sidebar `:hover` gated by `@media (hover: hover)`. Safe-area-inset-top on hamburger + poll-progress-bar + sidebar header. Publish-check modal gets the 400ms backdrop guard from 2.14.10. |
| **Audit pass: security + robustness** | 2.14.4 | Driven by a four-angle code audit. (1) Auto-sync now refuses non-HTTPS `posting_server_url` — was sending the API key in cleartext if the user pointed at plain `http://`. (2) Auto-sync pull loop got exponential backoff on transport failures (5m → 60m cap) so an unreachable server isn't hammered indefinitely; "200 with no new settings" stays on the regular cadence. (3) `posting.story_reader.load_story` now resolves+re-anchors `story_name` against the archive root — auth-protected post-auth path traversal closed. (4) `deploy/pawpull.py` whitelists `argv[1]` against `^[A-Za-z0-9_./-]+$` — was interpolating into shell=True without quoting. (5) QA checklists bumped to 2.14.4. False alarms documented in CHANGELOG: `.env` is gitignored (agent saw the local file), TOTP secret is in the URI anyway so dropping the standalone field is no-op. Vault key Windows ACL gap and bigger refactor candidates (N+1 batching, notification helper extraction, `config.py` split) deferred to focused passes |

### What posted successfully during testing
- Inkbunny draft of "Late Shift" full story — flipped cell from green ✓ → blue ✓ posted with URL.

---

## Open roadmap

### Phase 6c — broader platform testing (COMPLETE)

All target platforms confirmed end-to-end: post, update, metadata-only,
drift detection, deletion probe, re-post.

- [x] Inkbunny (post + re-post after delete + deletion probe)
- [x] SoFurry (chaptered posting + chapter titles + front matter on ch1 + edit with chapter-aware content refresh + deletion probe)
- [x] AO3 (chaptered + work skin + safe-overlay edit + metadata-only retitles + CF proxy bypass for desktop + deletion probe)
- [x] SquidgeWorld (chaptered + work skin + email-login resolution + deletion probe)
- [x] FurAffinity (direct from server — no desktop queue needed! + PDF update via changestory + deletion probe)
- [ ] Weasyl (account not verified — blocked on account-level verification, not a code issue)
- [skip] DeviantArt / Itaku / Wattpad / Bluesky/X — user opted out

### Phase 6d — bulk actions (COMPLETE)

- [x] "Publish row" button — number badge at row end, bulk-posts all actionable cells
- [x] "Publish all new" — footer button, posts every ready/deleted cell
- [x] "Update all drifted" — footer button, updates every drifted cell
- [x] Preflight dialog with per-item checkboxes + draft toggle + dry-run
- [x] Progress panel with live per-item status + cancel + close-and-refresh
- [x] Frontend-only (no backend changes, no SSE)

### Phase 6e — safety polish (COMPLETE)

- [x] Require re-confirm for "live" (non-draft) publishes in the confirm dialog (extra yellow banner)
- [x] Dry-run results should be readable inline, not just `<details><pre>`
- [x] Action result log per session (so you can see "last 5 posts" without refreshing)
- [x] Per-platform "posted at" clock display in the detail panel

### Phase 7a — Cloud sync (COMPLETE)

- [x] `CREDENTIAL_FIELDS` + `SYNC_EXCLUDE` sets in `config.py`
- [x] `get_settings_for_sync()` / `merge_synced_settings()` helpers
- [x] `POST /api/settings/sync` endpoint (pull/push modes)
- [x] `GET /api/settings/sync/status` endpoint
- [x] Desktop startup pull in `main.py` (`_sync_settings_on_startup()`)
- [x] Dashboard UI: Settings → Data tab → Sync section (Pull/Push/Status buttons)

### Phase 7c — Auto-sync (COMPLETE — 2.14.2)

- [x] `auto_sync.py` module with debounced push + 5-min pull thread
- [x] `config.save_settings()` post-write hook → `schedule_push()`
- [x] `_in_pull_merge` thread-local flag for echo prevention
- [x] Localhost loopback skip in `_sync_target()`
- [x] Browser `visibilitychange` listener re-pulls preferences
- [x] `auto_sync_enabled` toggle on Settings → Appearance (default true)
- [x] `theme` persists to settings.json (was dropped by POST handler before 2.14.2)

### Phase 7b — Credential vault (COMPLETE)

- [x] Fernet encryption with keyring/dotfile key derivation
- [x] `settings.vault.json` encrypted credential storage
- [x] `migrate_to_local_vault()` / `migrate_to_cloud()` mode switching
- [x] API: `/vault/enable`, `/vault/disable`, `/vault/status`
- [x] Dashboard UI: Credential Security section

### Phase 8a — Embedded browser login (COMPLETE)

- [x] `auth/browser_login.py` — pywebview popup for 7 platforms
- [x] Cookie/URL monitoring for login success detection
- [x] Desktop mode: "Login via Browser" as primary for FA/DA/TW
- [x] Server mode: manual entry with "Open login page" links
- [x] API: `/browser-login/{platform}`, `/browser-login/platforms`

### Phase 9a — Setup wizard (COMPLETE)

- [x] First-run detection via `setup_complete` flag
- [x] 4-step flow: Welcome → Archive path → Platform connections → Done
- [x] 11 platform cards with connection status
- [x] API: `/setup-status`, `/setup-complete`

### Phase 9b — New story wizard (COMPLETE)

- [x] "Create New Story" button on story list
- [x] Dialog with title, author, chapters, rating
- [x] Template MASTER.md showing all anchor types
- [x] Full folder structure scaffolding
- [x] API: `POST /stories/create`

### Phase 10 — Editor enhancements (COMPLETE)

- [x] Anchor insertion toolbar (8 buttons)
- [x] Selective format regeneration (7-option dropdown)
- [x] Format tab bar (replaces dropdown)
- [x] Per-platform descriptions (Short + Announcement)
- [x] Regen staleness warning in Publish Check

### Phase 11 — Image support (COMPLETE)

- [x] Cover upload wired to all 4 platforms (IB, FA, SF, WS)
- [x] Per-chapter thumbnails in metadata drawer
- [x] `POST /chapter-thumbnail` endpoint

### Phase 12 — Publishing UX (COMPLETE)

- [x] Regen staleness warning with inline Regenerate button
- [x] Edit button from published stories
- [x] Post scheduling (datetime picker + queue)
- [x] Retry queue (exponential backoff, max 3 attempts)
- [x] No-credentials status for unconfigured platforms

### Phase 15 — GitHub packaging (COMPLETE)

- [x] README.md, LICENSE (MIT), CONTRIBUTING.md
- [x] .gitignore + .env.example updated
- [x] GitHub Actions: build.yml (PyInstaller → release), lint.yml (ruff + JS syntax)
- [x] Credential audit — no secrets in tracked files

### Tag audit

- [x] Story-level tag audit across all 13 stories (~330 additions, ~45 removals)
- [x] Per-chapter tag assignments for all ~70 chapters
- [x] TAG_AUDIT_REPORT.md saved in archive root
- [x] Per-chapter tags for platform-specific arrays — chapter tag editor now shows Default/SF/IB/WP tabs (matching story-level); cascade still handles remaining platforms on publish

### WeasyPrint CSS fix (COMPLETE)

- [x] `@page { margin: 0 }` moved to top-level (was nested inside `@media print` — invalid CSS, WeasyPrint ignored it → double margins)
- [x] All stories regenerated with new CSS

### Other pending

- [x] Polling module audit: exc_info logging fixes (10 pollers) + silent exception swallowing replaced with debug logging
- [x] Polling module: session expiry recovery (SQW forces re-login, FA/TW detect expired cookies with clear messages)
- [x] Polling module: N+1 query batching (IB faves, FA comments, SQW kudos, AO3 kudos — all use executemany now)
- [x] AO3 rate-limit retry (_post_with_retry + Retry-After parsing + exponential backoff on all POST operations)
- [ ] Weasyl testing (blocked on account verification)
- [x] Per-platform tag selection in editor — shipped 2.15.0. FA / Weasyl / AO3 / SQW tabs added alongside the existing Default / SF / IB / WP. FA tab carries a 500-char joined-string counter. Empty non-default tabs on older stories show a "Populate from Default" backfill button. Backend was already correct for JSON-backed stories (`story_reader.py:395-405`). Per-chapter tabs not extended — follow-up. The `settings.platform_*_enabled` gating proposed in the original bullet was dropped because no such setting exists; the cleaner play was to always show the tabs and let users ignore the ones they don't post to. Future enhancement: a chapter-level version of the same tabs.
- [~] Draft detection in publish check — surface stories that are sitting on a platform as drafts (uploaded but not public). Today the matrix only knows `ready`/`posted`/`blocked`/`drifted`/`deleted_upstream` (`publish_check.js:12-24`); add a `posted_draft` cell status so the user can see at a glance which platforms have a draft waiting to be flipped live. Per-platform probe surface:
  - [x] **FA** — shipped 2.14.9. Scraps treated as draft equivalent; probe reads the changeinfo checkbox; `edit_submission` now preserves scrap state on every edit (latent un-scrap bug fixed); "Publish draft" action wired through `/publish` with `action='publish_draft'`.
  - [x] **IB** — shipped 2.18.0. `clients/ib/models.py:SubmissionDetail` extended with a `public` field; `InkbunnyPoster.probe_draft_state` reads it. Covers held / under-review / friends-only.
  - [x] **SF** — shipped 2.18.0. `SoFurryPoster.probe_draft_state` fetches `/ui/submission/{id}` JSON and reads `publishedAt` — null / `0000-00-00` sentinel / future-dated → draft.
  - [x] **AO3** — shipped 2.18.0. Fetches `/works/{id}/preview`; `name="post_button"` / `name="preview_button"` or absence of kudos / comments controls signals draft state.
  - [x] **SqW** — shipped 2.18.0. Same OTW Rails layout, identical heuristics.
  - [ ] **Bluesky / Wattpad / DA / Itaku / Weasyl** — confirm individually before adding probes; some have nothing draft-like.

  Action panel grows a "Publish draft" button (and maybe "Discard draft") next to the existing Post/Update buttons. Useful both as a sanity check (catch the case where the draft toggle was left on and you forgot to publish) and as a workflow (deliberately stage everything as drafts, then flip them all live in one bulk action — pairs with the existing "Publish all new" footer button).

### EPUB follow-ups (post-2.17.4)

- [x] **In-app EPUB viewer** — shipped 2.17.6 + 2.18.0 polish (Aa appearance dropdown, location persistence, full-page cover override). See feature-table row above and the 2.18.0 CHANGELOG entry for the full architecture.
- [x] **Subtitle / dedication UI** — shipped 2.18.0. Drawer fields write to story.json; `editor/epub_generator.py` prefers `story_meta["subtitle"]` over the MASTER.md `<!-- @subtitle -->` anchor.
- [ ] **Bundled fonts in EPUB.** 2.17.0 deferred bundling OFL fonts (~700KB + license tracking) for system fallbacks. Worth adding once an editor "appearance" panel exists for picking the EPUB body font; today the user can't pick anything so bundling is premature.
- [ ] **Subtitle / dedication UI.** `epub_generator.build_epub` already reads `fm.subtitle` and `story_meta.dedication` if present, but the metadata drawer has no input field for either. Two-line form addition. Until then, only stories whose MASTER.md happens to have a `<!-- @subtitle -->` anchor get a subtitle on the title page.
- [x] **`pawsync` doesn't delete server-side files** — fixed in 2.17.5. `pawsync.py` now accepts `--prune` (removes server-side top-level story dirs missing locally; `Backups`/`Drafts`/`Styled_HTML` are treated as untouchable) and `--dry-run` (lists what would be removed). Verified end-to-end against the live VM on 2026-05-02 — extract + dry-run prune reported "no orphans found" against the 16 currently-synced stories.

---

## Critical file paths

### PawPoller
- `PawPoller/routes/editor_api.py` — all editor endpoints (~900 lines)
- `PawPoller/editor/converter.py` — format converters + anchor handling
- `PawPoller/editor/pdf_generator.py` — WeasyPrint + Edge fallback
- `PawPoller/posting/manager.py` — `post_story()` / `update_story()` / `update_all_changed()` + extras passthrough
- `PawPoller/posting/story_reader.py` — `load_story()`, `build_package()`, platform name cascade
- `PawPoller/posting/sync.py` — `hash_file()` for drift detection
- `PawPoller/posting/platforms/{ib,fa,ws,sf,sqw,ao3,da,ik,bsky}.py` — 9 posters
- `PawPoller/clients/{ib,fa,weasyl,sf,sqw,ao3,da,wp,ik,bsky,tw}/client.py` — 11 platform HTTP clients (consolidated under `clients/` in 2.14.3)
- `PawPoller/database/posting_queries.py` — `publications` table CRUD
- `PawPoller/auth/browser_login.py` — embedded browser login module (pywebview cookie capture)
- `PawPoller/routes/settings_api.py` — settings sync + vault + browser login + setup wizard endpoints
- `PawPoller/frontend/js/editor.js` — editor UI + anchor toolbar + format tabs + create story wizard
- `PawPoller/frontend/js/metadata_editor.js` — drawer + tags + per-platform descriptions + chapter thumbnails
- `PawPoller/frontend/js/publish_check.js` — matrix + actions + bulk + scheduling + action log
- `PawPoller/docs/ROADMAP_PUBLIC.md` — public release roadmap (Phases 8-15: auth UX, setup wizard, editor, images, publishing, analytics, import, GitHub packaging)
- `PawPoller/deploy/pawpush.bat` — push story archive local → server (alias for pawsync.bat)
- `PawPoller/deploy/pawpull.bat` — pull story archive server → local (supports single-story: `pawpull.bat Story_Name`)
- `PawPoller/frontend/css/editor.css` — all editor/drawer/matrix styles
- `PawPoller/tag_database/` — 5 tag files + aliases.json + e621_lookup.tsv (**bundled in Docker image, NOT under data/**)

### Archive / stories
- `m_x/Archives/Complete_Stories/` — story folders
- `m_x/Archives/Complete_Stories/_Test_Story/` — known-good test fixture, all tags ready, all platforms green
- `m_x/Archives/Complete_Stories/Reference_Guides/Styling/HTML_CSS/STYLING_REFERENCE.md` — Styled HTML template
- `m_x/Scripts_Utils/regenerate_story.py` — CLI regenerator (used before the editor endpoint existed; still the fallback for desktop Edge PDF gen)

### Tag DB (canonical — edit here, not in PawPoller)
- `C:/Users/rhysc/claude/Tag_Database/` — canonical source
- Audit scripts: `_rewriter.py`, `FLAGS_20260415.md`
- Deploy to server: copy → `PawPoller/tag_database/` → commit → push → `pawupdate`

---

## Deploy cheat sheet

```bash
# Deploy code changes
cd C:/Users/rhysc/claude/PawPoller
git add <files>
git commit -m "..."
git push
gcloud compute ssh pawpoller --zone=us-east1-c --command="cd /home/kithetiger/PawPoller && sudo -u kithetiger git pull && sudo docker compose up -d --build"

# Push story archive to server (local -> server)
deploy/pawpush.bat
# or: deploy/pawsync.bat  (same thing, original name)

# Pull story archive from server (server -> local)
deploy/pawpull.bat                    # full sync
deploy/pawpull.bat Extra_Credit       # single story

# Verify
gcloud compute ssh pawpoller --zone=us-east1-c --command="sudo docker compose -f /home/kithetiger/PawPoller/docker-compose.yml logs --tail=30 pawpoller"

# Pause/resume polling (API key lookup: server settings.json)
gcloud compute ssh pawpoller --zone=us-east1-c --command="curl -s -H 'Authorization: Bearer pp_YOUR_API_KEY' -X POST http://localhost:8420/api/poll/pause"
```

---

## Known gotchas (don't get caught again)

1. **Tag DB location**: `/app/data/` is a Docker volume — it SHADOWS bundled files. That's why `tag_database/` lives at PawPoller root, not under `data/`.
2. **story.json `index` not `number`**: `chapter_info[]` entries must use `index`, not `number`. The metadata editor writes correct files; Test Story's old file had `number` and broke chapter file resolution.
3. **Default tag cascade**: `default` tags now cascade to every poster ID in `_parse_story_json()`. Before 2.9.3, only the chapter-level parser did this; story-level fell through to empty lists for DA/IK/Bsky.
4. **SQW is per-chapter only**: OTW archive format. Full-story SQW cell shows `not_supported` with a `–` icon.
5. **FA requires desktop**: Server posts get auto-queued via `manager.post_story()` → `scheduler._runtime_mode == "server"` branch → desktop picks up from queue.
6. **pawsync must precede code push**: Server archive is a separate copy. Run `deploy/pawsync.bat` BEFORE pushing PawPoller code that references new story files.
7. **Server perm on archive**: Docker runs as uid 1001, archive owned by kithetiger (1000). pawsync.bat does `chmod o+rwX` so the container can write (theme saves, PDF regen).
8. **WeasyPrint on Windows**: Missing GTK runtime → falls back to Edge headless automatically. GCP container has `apt-get`'d libs so it renders natively there.
9. **Confirm_live guard**: Backend rejects `action='post'|'update'` without `confirm_live=true`. Frontend confirm dialog sets this; direct curl calls need it explicitly.

---

## MEMORY quick index

`C:/Users/rhysc/.claude/projects/C--Users-rhysc-claude/memory/MEMORY.md` has:
- PawPoller deploy workflow
- Story Archive Sync procedure (`feedback_pawsync.md`)
- MASTER.md convention
- Manuscript formatting conventions
- Writing quality standards / GPT-ism guide
- Hooks system

---

## For the next session

If the user asks to resume, the most useful things to read first are:
1. This file (HANDOFF.md)
2. `../CHANGELOG.md` top section — most recent: 2.17.6 (in-app EPUB viewer + 2 CSP fixes), 2.17.5 (`pawsync --prune`), 2.17.4 (downloads dropdown), 2.17.0–2.17.3 (EPUB output + mobile downloads). Pre-EPUB pivot history goes back to 2.10.5
3. `ROADMAP_PUBLIC.md` — public release plan (all must/should-haves + most nice-to-haves now COMPLETE)
4. `documentation_guide.md` — full technical reference (now includes auto-sync architecture under "Settings Auto-Sync (2.14.2+)" and the in-app EPUB viewer under "EPUB Viewer (2.17.6+)")
5. **Testing checklists** — all QA artefacts live under `qa/`:
   - `qa/TESTING_CHECKLIST_WEBAPP.html` — 461 rows × 43 sections, browser/Docker/server flavour. localStorage key `pawpoller_test_webapp`. CSV exports as `pawpoller_test_webapp.csv`.
   - `qa/TESTING_CHECKLIST_NATIVE.html` — 497 rows × 49 sections, Windows desktop build (PyInstaller exe + pywebview + tray). localStorage key `pawpoller_test_native`. CSV exports as `pawpoller_test_native.csv`.
   - `qa/fixtures/` — sample upload payloads (`sample_story.{md,html,bbcode,txt,rtf}`, `sample_multichapter.md`, `sample_cover.jpg`, `sample_chapter_thumb.jpg`) referenced by file-upload rows so QA results stay reproducible. See `qa/fixtures/README.md` for the file/test mapping.
   Both checklists share ~430 universal rows (every nav link, every settings toggle, every platform's auth/list/poll/export, every editor anchor, the publish-check matrix, posting per platform, auto-sync, themes, vault, security, API). The native version adds 7 native-only sections (tray, run-on-startup, browser-login popups for 7 platforms, file dialogs, Edge PDF, vault keyring, auto-update, process behaviour). The webapp version adds 1 webapp-only section (multi-tab, HttpOnly cookies, CSP, reverse proxy, CF Tunnel, CORS).
   Both have a search/status filter bar + pass/fail/skip three-state + Import/Export CSV. Old single root-level `TESTING_CHECKLIST.html` was deleted in the same change that introduced the split. (The Python unit tests still live in `tests/` — different surface, don't confuse with `qa/`.)
6. `routes/editor_api.py` + `routes/settings_api.py` — main API surface
7. `auto_sync.py` — new in 2.14.2; small (~170 LOC), worth a glance before touching settings persistence

### CI / release pipeline state (updated 2026-05-02)

The `Build & Release` workflow fires on `v*` tag pushes and has two
jobs: `test` (Ubuntu, `python -m pytest tests/ -v` since 2.13.8) and
`build-windows` (PyInstaller → zip → `softprops/action-gh-release@v2`).
The `Lint` workflow fires on every push to master (ruff + JS syntax).
`requirements-server.txt` pins the test deps (`pytest~=8.3`,
`pytest-asyncio~=1.3`, `respx~=0.22`). 91 tests, all green.

**Tag drift**: `v2.13.8` is still the most recent published release.
2.13.9 → 2.17.6 (24 versions: vault init fix, 8-theme picker, Vibe
Pack, auto-sync, file-tree refactor, audit-debt refactor, coordinated
desktop ↔ server, mobile mode phases 0–5, BUG-* sweep, EPUB output,
mobile downloads, pawsync prune, in-app EPUB viewer) has shipped to
master + GCP but no Windows artifacts have been published. Cutting
`v2.17.6` would re-run the build job and produce a fresh
`PawPoller-windows-x64.zip` artifact; worth doing as a "release
everything that's accumulated" pass before the next feature push.

### QA status as of 2026-04-26

Mid-way through the first full QA pass against `TESTING_CHECKLIST`. Last
CSV snapshot lives at `C:\Users\rhysc\Downloads\pawpoller_test_results.csv`.
Issues found + fixes shipped during 2.13.1–2.13.8:
- **#11–18 anchor buttons**: silent no-ops (wrong `this._cm` reference) — fixed in 2.13.1, toolbar restructured in 2.13.7/8
- **#23 full-story PDF missing**: diagnostics improved in 2.13.3 (shows specific reason). Awaiting user retest to confirm fix
- **#26 PDF CSS**: fixed 2.13.4+2.13.5 (header/footer suppressed, full-bleed theme background)
- **#27/#28 regen staleness 500**: fixed in 2.13.2 (stories with `chapter_info: []` no longer crash publish-check)
- **#73 vault enable**: diagnostics improved in 2.13.3 (real exception shown in UI). Awaiting user retest

The old 128-row checklist has been retired and replaced with the two ~470-row files described above. All previously-fixed 2.13.x items are still represented (under their new IDs in the WEBAPP checklist's Editor / Anchor Toolbar / Publish Check sections). The 2.14.x theme + auto-sync coverage is in sections 29–30 of WEBAPP and the same in NATIVE.

### Round-2 automated QA + production live-monitor (2026-05-01)

Automated Playwright sweep ran against the 2.14.7 test container (port 8421, empty seed), then read-only sweep against production (35.243.213.49:8420, was on 2.14.6). 11 bugs filed in `qa/AUTOMATED_BUG_LOG.md` (BUG-010 through BUG-018) plus BUG-021 (production-only). BUG-022 was logged then retracted — false positive from Playwright detection logic matching "Platforms" inside the metadata drawer's own section headings. **2.14.8 fixes the two P1s (BUG-010 mobile hamburger off-screen via `transform` containing-block; BUG-019 create-story 500 → 400 with structured detail).** Production now confirmed running 2.14.8 with zero console errors.

**Open bugs after 2.16.8 ship** (all P2/P3, none blocking):
- ~~**BUG-011** P3: `/api/health` should include `version` field~~ — fixed in 2.16.8, now returns `{"status": "ok", "version": APP_VERSION}`
- ~~**BUG-014** P3~~ — fixed in 2.16.13. IB dashboard now renders `<h2>Inkbunny Dashboard</h2>` matching every other platform's `<h2>{Platform} Dashboard</h2>` pattern
- ~~**BUG-016** P3~~ — fixed in 2.16.9. New `GET /api/poll/all-progress` returns the full `{ib, fa, ws, sf, sqw, ao3, da, wp, ik, bsky, tw}` map; frontend ticker is now one fetch with one `.catch` instead of 9 parallel requests with 9 independent error paths. Per-platform endpoints kept for direct callers
- ~~**BUG-017** P3~~ — fixed in 2.16.13. New `_guardSetupRoute()` fetches `/api/setup-status` on every `#/setup` navigation; bounces to `#/` if `setup_complete: true`. The Re-run setup button still works because it clears the flag server-side first
- ~~**BUG-018**~~ — fixed in 2.16.14. §17 Goals + §18 Tags + nav-link tests removed from webapp checklist
- ~~**BUG-020**~~ — confirmed working on prod in 2.16.14 (Hypnotic_Claim regen 7.5s, 8 formats clean, 3 PDFs via WeasyPrint, errors:[]). Original report was test-container-only (no PDF deps)
- ~~**BUG-021**~~ — fixed in 2.16.14. All 11 platforms' search filter now re-renders both the grid and the table view via a closure passed to `_bind{X}Search(allSubmissions, gridRenderer)`
- ~~**SameSite=Strict cookie quirk**~~ — fixed in 2.16.8, switched to `samesite="lax"` in `routes/dashboard_auth.py`
- ~~**`/favicon.ico` returns 401**~~ — fixed in 2.16.8, added to `_AUTH_EXEMPT_PATHS` in `dashboard.py`

**Live-monitor finding worth chasing — periodic 401 burst on production session.** While the user was idle in the browser (no logout, no auth changes), the server logged a recurring pattern every ~30s: a successful progress tick (9× 200), then the next tick fails entirely (9× 401 + sometimes a real SPA fetch like `/api/settings/preferences` also 401), then immediately recovers (next tick 200). Each burst opens fresh TCP connections (different source ports). Server-side session secret is cached in memory — verify path can't flake. Most likely cause: **`SameSite=Strict` cookie quirk** where the browser drops the cookie under specific idle/refresh conditions. Fix candidate: change `samesite="strict"` to `samesite="lax"` in `routes/dashboard_auth.py:132`. Self-hosted dashboard with HttpOnly cookies + JSON-only state-change endpoints doesn't need Strict's CSRF protection. Side-bug surfaced by same monitor: `/favicon.ico` returns 401 because the auth middleware (`dashboard.py:197-203`) doesn't exempt it; add to `_AUTH_EXEMPT_PATHS` or `_AUTH_EXEMPT_PREFIXES`.

**Test-account strategy decided:** automated signup is not viable (CAPTCHA, Cloudflare, SMS verification, ToS violations across 11 platforms). Manual user-driven account creation with a dummy Gmail, then handing creds to the test environment, is the clean path. Browser-login flows on platforms that support it (CF-proxied SF/DA, etc.) avoid storing passwords entirely. No test-account work has started — flagged as a future option, not a planned step.

Next retest pass should:
1. Import the previous CSV snapshot into WEBAPP via Import CSV (IDs have shifted — most rows will need re-running rather than mass-import). Keep the old CSV around as historical reference.
2. Sweep WEBAPP first (it covers everything that runs in Docker — most of the surface).
3. Sweep NATIVE only on a Windows machine with the PyInstaller build, focusing on sections 41–47 (the native-only blocks).

If the user says "what's next?" — 2.18.0 cleared the entire
"do them all" list including the late additions.

**Shipped in 2.18.0:**
- Analytics export (Fastest CSV + Weekly CSV + Chart PNG buttons,
  pure client-side, no new endpoints)
- Auto-update mechanism (was already implemented end-to-end; cutting
  v2.18.0 activates it)

**Genuinely remaining:**
- Weasyl posting test (blocked on account verification, not code)
- Cut `v2.18.0` GitHub release — that's it; everything else is
  cosmetic.
- Bluesky / Wattpad / DA / Itaku / Weasyl draft probes — fragmentary;
  some platforms have no draft equivalent.
- AO3 import end-to-end verification — code path identical to SqW
  (which works) but the test was blocked by AO3's 10-min 429 cooldown
  from probe attempts.

Story archive sync commands:
- `deploy/pawpush.bat` — local → server (push)
- `deploy/pawpull.bat` — server → local (pull)
- `deploy/pawpull.bat Story_Name` — pull single story

GitHub release workflow:
- `git tag v2.12.4 && git push --tags` → triggers build + release
- PAT needs `workflow` scope for pushing `.github/workflows/` changes
