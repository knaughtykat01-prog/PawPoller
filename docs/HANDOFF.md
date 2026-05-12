# PawPoller Session Handoff

**Last updated:** 2026-05-12
**Current version:** 2.19.2 (**Fix: Diagnostics platform test definitions — second round.** First post-2.19.1 Run All on the server (where vault creds were now visible) unmasked four more bugs in how the platform tests called their clients — none are bugs in the platforms themselves. SqW tests imported `SqWClient` but the class is `SquidgeWorldClient`, and its constructor needs `target_user` as a third positional; discovery now calls `get_all_work_ids()`. DA tests constructed `DAClient` without the required `target_user` positional; `validate_cookies()` takes no args; discovery uses `get_all_deviation_ids()`; DA is a REQUIRED-proxy platform, now receives `**proxy_kwargs(settings, "da")`. SF auth failed with "session did not validate" because the test constructed `SoFurryClient` without CF Worker proxy creds (SF needs proxy on server) — now passes `display_name` and `**proxy_kwargs(settings, "sf")` plus calls `ensure_logged_in()` before `validate_session()` to mirror the poller's session-warming flow. SF discovery: same proxy fix, switched to real method `get_all_gallery_ids()`. WS discovery: switched to real method `get_all_gallery_ids()`. Verification on next Run All: errored / failed counts should drop further; remaining failures should only be legitimate platform issues or genuine cred-missing skips.)
**Previous version:** 2.19.1 (**Fix: Diagnostics suite test definitions.** First live "Run All" from the new Diagnostics tab on the server surfaced four defects in test code (not the subsystems under test): `platforms.wp.auth/discovery` and `platforms.ik.auth/discovery` constructed `WPClient()` / `IKClient()` without their required `target_user` positional arg (and called `validate_user(target)` with an arg the method doesn't accept) — fixed to pass target via constructor and call the no-arg form, also switched discovery to the correct `get_all_story_ids` / `get_all_content_ids` methods; `infra.vault.crypto` assumed `_encrypt_vault(payload)` returned a blob — the real signature is `_encrypt_vault(creds: dict) -> None` that writes to `VAULT_PATH` and `_decrypt_vault() -> dict` that reads from it, so the test now monkeypatches `config.VAULT_PATH` to a tempfile for the round-trip and restores it in finally, skipping cleanly when the vault key isn't reachable; `external.github.latest_release` now treats 404 as a clean skip (repo has no published releases yet) instead of a failure; `archive.pawsync.dry_run` now recognises `Archive root not found` / `no such file` in pawsync stderr as an environment-mismatch skip rather than a failure. Expected outcome on next Run All: 0 errored, 0 failed; skipped goes up by 1-3.)
**Earlier:** 2.19.0 (**Feature: Diagnostics & testing tab.** New Settings → Diagnostics surfaces a comprehensive in-app suite — 82 bespoke live-system tests + the existing pytest suite as a parsed sub-runner, ~170 individual test rows. New `testing/` package: registry with `@register_test` decorator + TestResult, async runner with global concurrency lock + per-test timeout + platform pacing, per-run SSE event streamer with replay + heartbeats, store persisting last 10 runs to `data/diagnostics_results.json`. New `routes/testing_api.py` with 8 endpoints under `/api/testing/*` including SSE stream. New `frontend/js/diagnostics.js` (EventSource consumer, two-pane layout: catalogue + live log, per-test/per-category/full-suite run buttons, destructive-test confirms, run-failed-only, log download/filter) + `frontend/css/diagnostics.css`. Categories: Infrastructure (12), Dashboard Auth (6), Platforms-Auth (11), Platforms-Polling (11), Editor/Converter (10) including regression tests for 2.18.20 chapter-end + 2.18.19 file resolution + 2.18.16 queue filter, Story Reader (6), Posting Dry-Run (9), External (5: CF Worker, Telegram getMe, GitHub, Turnstile), Scheduling (5), Notifications (3, all destructive), Archive (3), Pytest Suite (1 → ~91 children). Destructive tests gated by per-test `confirm_destructive` flag in route layer + frontend confirm dialog. One run at a time enforced by module lock (second-run requests get 409 with active run_id so the frontend attaches to the stream). All endpoints sit behind existing session auth, no auth-exempt additions.)
**Earlier:** 2.18.21 (Fix: Theme Editor + metadata drawer `<select>` dropdown options unreadable. The Warning Icon and Section Break pickers (and the metadata drawer's rating/category selects) opened with options rendered in low-contrast grey-on-grey — only the highlighted row was readable. Chromium / WebView2 renders the dropdown popup as a system widget and doesn't inherit the parent `<select>`'s background / colour tokens in dark themes. Fix in `frontend/css/editor.css`: add `.theme-row select option, .metadata-field select option { background: var(--surface-elevated); color: var(--text-primary); }`. Same pattern `.filter-select option` already used in `components.css` for the dashboard. CSS-only.)
**Earlier:** 2.18.20 (Fix: every styled chapter file rendered "THE END" footer. The styling template at `Reference_Guides/Styling/HTML_CSS/STYLING_REFERENCE.md` hard-codes a `<div class="story-end">` block with THE END + signature, and every per-chapter Styled HTML file fills the same template — so chapters 1..N all claimed the story ended there. Fix in `editor/converter.py:_build_styled_chapter`: track `is_last_chapter`, and for non-final chapters post-process the doc to replace the static block with `<div class="story-end chapter-end">` containing `End of {ch_title}` and `Continued in {next_ch_title}`. Keeps the `story-end` class so existing CSS still applies. New helper `_replace_story_end_with_chapter_end()`. Smoke-tested on Overtime: all 4 chapters render correctly (ch1–3 get continuation footer, ch4 keeps THE END). Existing Styled HTML chapter files on disk still have the old footer — needs Regenerate on each chaptered story to refresh. Full-story Styled HTML, EPUB, and the plain Clean HTML / SoFurry HTML / BBCode chapter files are unaffected (the end marker only emits where MASTER.md contains `*End of Title*`, which only chapter N's slice does). Pre-existing follow-up: when a story has no `@byline` anchor and `default_author` setting is empty, the last chapter's signature renders as `~  ~` empty.)
**Earlier:** 2.18.19 (Fix: per-chapter FA post uploaded the full-story PDF. Caught from posting just chapter 1 of `Overtime` to FA via the publish matrix — the upload contained the full Overtime PDF, not `Chapter_1_Tip-Off.pdf`. Two compounding bugs in `posting/story_reader.py`: (1) `_resolve_format_file` did `if ch_filename in f.stem` without guarding empty `ch_filename`, and `"" in any_string == True` in Python — so the first matcher loop always returned the first file in the highest-priority spec dir (FA priority 1 is `PDF/*.pdf`, the full-story bulk). The secondary `f"Chapter_{N}" in f.name` matcher never ran. (2) `_load_from_story_json` keyed `manifest_chapters` on `ch.get("index", 0)`, but split_manifest entries use `number` not `index` — so all chapters collapsed to key 0 — AND read `filename` from a non-existent top-level field, so every `ChapterInfo.filename` was `""`. That fed bug #1. Fix: guard the filename matcher with `if ch_filename and ...`, key the manifest dict on `number`, and derive `filename` from any path in the manifest's `files` dict (stem of e.g. `Chapter_1_Tip-Off.md`). Smoke-tested all 6 file-upload platforms × {full, ch1, ch4} on Overtime — every cell now resolves correctly. `_load_from_legacy` has the same key mismatches but only handles stories without story.json — left for follow-up. Cleanup pending: live FA submission `https://www.furaffinity.net/view/64930670/` and publications row `pub_id=60` (Overtime ch1 with full-story PDF) need to be reconciled — user to decide whether to delete+re-post or replace_file.)
**Earlier:** 2.18.18 (Fix: chapter-thumbnail upload triggered a 409 on the next metadata Save. Followed up from 2.18.17. The endpoint writes both the image file AND the new path into `story.json` server-side, but the drawer caches the mtime at load time as `this.lastMtime` and sends it as `expected_mtime` on the next PUT — which 409'd because the upload had bumped the mtime behind the drawer's back. `routes/editor_api.py:upload_chapter_thumbnail` now returns `last_modified: sj.stat().st_mtime` after the story.json rewrite. `frontend/js/metadata_editor.js:_uploadChapterThumb` updates `this.lastMtime` from it AND mirrors the thumbnail write into `this.initialMetadata` so the dirty check doesn't flag the upload as a pending edit. `upload_cover` is a different shape — it only writes the image; Save is what persists the filename — so no parallel fix needed there.)
**Earlier:** 2.18.17 (Fix: per-chapter thumbnail uploads all landed on chapter 0. The user uploaded thumbnails for chapters 1–4 of `Overtime` via the metadata drawer, hit Save, the field showed "None" for every chapter on reload. Server logs showed four `POST /chapter-thumbnail` requests all returning 200 OK, but only one file on disk (`Images/ch0_thumbnail.png`) and one story.json entry (`chapter_thumbnails["0"]`). Root cause: `routes/editor_api.py:upload_chapter_thumbnail` declared `chapter_index: int = 0` without a `Form()` annotation — FastAPI binds an `int` parameter from the query string only without `Form()`, so the multipart form field the frontend sent was ignored and every call fell back to default 0. Fix: import `Form` and change to `chapter_index: int = Form(0)`. The frontend was already sending the field correctly. Cleanup on the live VM: deleted the orphaned `Overtime/Images/ch0_thumbnail.png` and stripped the bogus `chapter_thumbnails["0"]` entry from `Overtime/story.json`. Only one other upload endpoint (`upload_cover`) exists and takes no extra parameters, so no similar bug. Side observation worth a follow-up: the chapter-thumbnail endpoint mutates story.json directly without bumping the drawer's cached `lastMtime`, so the next save always 409s. Functional but ugly. Not in this version.)
**Earlier:** 2.18.16 (Fix: scheduled / queued posts starved by `requires='desktop'` zombies at the head of the FIFO. Caught from a 26h-overdue scheduled IB post for `Overtime` (queue_id=8, `scheduled_at=2026-05-06 07:07 UTC`, `requires='any'`) that the server scheduler never picked up. `posting/scheduler.py` was calling `get_pending_queue(limit=5)` and filtering compatibility in Python — so seven April-dated `requires='desktop'` rows for non-desktop platforms (SF/IB/SQW/AO3, presumably from an earlier auto-queue policy) sat at the head of the FIFO, filled the LIMIT-5 window, were all filtered out as incompatible on a server instance, and the loop slept without ever reaching item 8. Fix: `database/posting_queries.py:get_pending_queue` gains an optional `runtime_mode` parameter that applies a `requires IN ('any', :mode)` predicate in SQL, so incompatible rows are excluded before LIMIT truncates the result. Scheduler passes `_runtime_mode` and drops the now-redundant Python filter + `_is_compatible` helper. The seven zombie rows (queue_ids 1–7) were deleted manually on the server before deploy; item 8 preserved. Known follow-up: editor UI has no "cancel queue item" button despite `DELETE /api/posting/queue/{queue_id}` existing in `routes/posting_api.py` — worth wiring up.)
**Earlier:** 2.18.15 (Fix: EPUB / PDF / SoFurry HTML / chapter BBCode missing from the editor's Downloads dropdown for newly-created stories. Two compounding bugs: (1) the new-story wizard at `editor_api.py:429` hardcoded `story.json["formats"]` to `{bbcode, html, markdown, squidgeworld}` only — `epub` and friends were silently omitted, so even after regen wrote the files to disk the Downloads dropdown short-circuited them as `{available: false}` because `posting/story_reader.py:get_format_files` only iterates the dict. (2) Regen never refreshed `story.json["formats"]` from on-disk reality, so older stories also missed any format added after their initial creation. Fix: wizard now declares every format regen can produce, AND the regen endpoint runs an on-disk discovery pass at the end (mirrors `posting/generate_story_json.py:112-130`), add-only merge so user-edited fields stay intact. Caught from "Testin" — regen log showed `editor.epub_generator: Wrote EPUB ... (2 chapters, 11 files)` cleanly but EPUB row never appeared in the dropdown.)
**Earlier:** 2.18.14 (Delete-story button on the editor's story-list cards. Each card now has a 🗑 button in the top-right corner; clicking opens a confirmation overlay that demands the user type the story's leaf folder name into an input — Delete button stays disabled until the typed value matches — then a native `confirm()` dialog as the second verification gate. Backend: new `DELETE /api/editor/stories/{story_name:path}` endpoint, requires `confirm_name` query param matching the leaf folder name, refuses anything in `SKIP_DIRS`. The endpoint logs the file count and the leftover `publications` / queue-item counts so the audit trail records what side-state survives the folder removal — DB rows are intentionally NOT deleted so analytics history is preserved.)
**Earlier:** 2.18.13 (Browser-login threading fix + Inkbunny entry + Settings → Logs copyable / Copy button + IB credentials moved into Settings → Platforms. The pywebview popup spawned by `auth/browser_login.py:login_via_browser` was calling `webview.start()` from a daemon thread, but the dashboard's `main.py:924` already owns the one allowed `webview.start()` for the process — Windows also requires the main thread for that call. First click on "Login via Browser" for FA / DA / SF / TW / WS / AO3 / SqW errored with `pywebview must be run on a main thread`; subsequent retries "succeeded" by accident, riding on undefined state left behind by the failed first call. Fix: the GUI loop is already running for the dashboard, so `webview.create_window()` is sufficient — pywebview marshals the new window onto the main thread internally. The second `webview.start()` is gone, the wrapper thread is gone, the cancel path is now driven by the window's `closed` event instead of `start()` returning. A guard at the top of `login_via_browser` raises a clear `RuntimeError` when there's no live GUI loop (e.g. someone calls it on the headless server) instead of silently spawning a broken second loop. New: Inkbunny added to `PLATFORM_LOGIN` mirroring the AO3 / SqW / Weasyl verification-only pattern — IB's API needs `api_login.php` username+password to mint an SID, so web cookies aren't usable for auth, but the entry lets users open the IB login page from the dashboard to confirm their credentials work. Log viewer: `<pre id="log-output">` got `user-select:text` + `cursor:text` (some pywebview WebView2 theme paths suppressed selection) and a new "Copy" button next to Refresh that writes the visible buffer to the clipboard, with a select-all fallback for cases where WebView2 rejects the clipboard write. Settings layout: Inkbunny credentials lifted from Settings → General to the top of Settings → Platforms — same accordion shape as FA/WS/SF/etc., with a status-dot summary, the username in the meta line, a conditional Sign Out button (only when `creds.has_password`), and a new "Verify in Browser" button that opens the IB website so users can confirm credentials before saving. The existing `cred-username` / `cred-password` / `save-creds-btn` / `settings-logout-btn` IDs were kept intact so the existing event handlers bind to the same controls; `settings-logout-btn`'s addEventListener moved to optional-chaining since the button is now conditional.)
**Earlier:** 2.18.12 (AO3 client jitter + exponential backoff. Pure hygiene pass — does NOT fix the datacenter-IP block (that's IP-keyed, not request-pattern keyed). Decision recorded: skip residential proxy integration; AO3 imports run from the desktop instance (residential IP), `pawsync` pushes to server. AO3 polling stays server-side (4hr interval + cookie auth is tolerable). New `_polite_delay()` helper replaces all 9 `asyncio.sleep(AO3_REQUEST_DELAY_SECONDS)` sites — sleeps `base × U(0.7, 1.3)`. `_get_page()` 429 backoff is now `30 × 2^(attempt-1) × U(0.8, 1.2)` (≈30/60/120 ±20%) instead of linear `30 × attempt`. Retry-After header still wins when AO3 sends one. Jitter spread is intentionally narrow — AO3's rate limiter is a simple per-IP counter, not pattern-aware. **2.18.11:** Importer duplicate detection at the import call. The list endpoint at `/api/editor/import/available` already deduped against existing `story.json/import_source` so the picker UI hid already-imported items, but the actual `POST /import/{platform}/{submission_id}` endpoint had no guard — and the manual "Import by URL or ID" path bypasses the picker entirely. Result: same submission imported twice produced byte-identical `_2`/`_3` suffix folders (caught with `Late_Shift` + `Late_Shift_2`, both SqW `92124`, 1962 words, identical). New `posting/importer.py:_find_existing_import(platform, submission_id)` scans every story.json import_source; every `import_from_*()` calls it before any network work and returns the existing folder + `already_imported=True` if matched. List endpoint dedup now includes `ao3` + `sqw` (silently missing). API response surfaces `already_imported` for the frontend. **2.18.10:** AO3 importer accepts cookie-only auth — credential gate at top of `import_from_ao3()` was still requiring username AND password, so cookie-only setups failed with "credentials not configured" before any fetch ran. Gate now passes when either user/pass OR a cookie is set; owner-of-draft check falls back to `ao3_target_user` when no username is configured. **2.18.9:** Cookie-mode false-negative fix. 2.18.8's `ensure_logged_in()` still ran a verify fetch against `/users/{name}` even when a pasted cookie was set — and that probe is itself rate-limited from datacenter IPs. After three 429s the loop exhausted, the returned body lacked "Log Out", the conservative check tore the session down, and cookie users got "cookie no longer logged in" the moment AO3's rate limiter fired. Fix: when a `_session_cookie` is set, `ensure_logged_in()` returns True immediately without fetching. We can't fall back to login anyway, so the verify fetch only creates false negatives. Actual import/poll fetches are the source of truth — bad cookie → public-profile/login-redirect page → caller surfaces clear error. `validate_session()` (only called by `/auth/connect`) keeps a verification fetch for immediate paste-time feedback but treats transient 429 as "trust and let next call confirm".)
**Earlier:** 2.18.8 (AO3 cookie-based auth as alternative to username/password — sidesteps the per-IP login throttle that locks datacenter IPs out for 5–60 min after a single failed probe. `clients/ao3/client.py:AO3Client.__init__` accepts `session_cookie=""`; when truthy it injects `_otwarchive_session` at `domain="archiveofourown.org"` and asserts `_logged_in=True` up front. `update_credentials()` updates / clears the cookie in place. `ensure_logged_in()` returns False with a clear "repaste cookie" log when a cookie is set but AO3 says we're logged out — it deliberately does NOT fall back to form login (would re-trip the rate limiter cookie auth exists to avoid). `polling/ao3_poller.py:_get_or_create_client` reads `ao3_session_cookie` from settings. `routes/ao3_api.py:/auth/connect` accepts optional `session_cookie`; password becomes optional when cookie is provided. `/auth/status` reports `has_password` + `has_cookie` separately. Settings → AO3 connect form has a collapsible "Advanced: paste session cookie instead" section with how-to. `config.py:CREDENTIAL_FIELDS` adds `ao3_session_cookie` so the cookie is encrypted in the vault.)
**Earlier:** 2.18.7 (CF Proxy toggle now has true fallback semantics — direct call first, retry through CF Worker only when the direct call hits a block-like failure (403/429/"Shields are up"/"Retry later"/Cloudflare/timeouts/Anubis-challenge/etc, detected by `polling/cf_proxy.py:is_blocking_failure(exc)`). Helper split into `proxy_kwargs()` (default-path: REQUIRED platforms only) + `proxy_kwargs_fallback()` (retry-path: REQUIRED + OPTIONAL-with-toggle-on). AO3 / SqW / IB / FA importers wrap their network calls in try/is_blocking_failure/retry-with-fresh-proxy-client. The shared poller singleton is never replaced; a one-shot proxy client is constructed just for the retry and closed afterwards. Poll cycles deliberately not wrapped — they retry naturally on the next cycle, so the failure mode is bounded. **2.18.6:** CF Worker proxy now available as a per-platform backup. Eight clients (`ib`, `fa`, `ws`, `sqw`, `bsky`, `ik`, `wp`, `tw`) gained `proxy_url` + `proxy_key` constructor args matching the existing AO3/DA/SF pattern. Single gate at `polling/cf_proxy.py:proxy_kwargs(settings, platform_code)` decides whether to use the proxy: AO3/DA/SF always use it when `cf_worker_url` is set (those need it from datacenter IPs); the other eight gate on a per-platform `<platform>_use_cf_proxy` flag (default off). Pollers, auth-connect routes, and the IB/FA importers all funnel through the same helper so the toggle propagates everywhere. New "CF Proxy Backup" accordion in Settings → Polling tab with one checkbox per opt-in platform; backed by extended `/api/settings/preferences` GET+POST. **2.18.5:** persistent sessions generalised to the rest of the platform fleet — Bluesky / DeviantArt / Itaku / SoFurry / X-Twitter / Wattpad `auth/connect` endpoints all now warm their poller singleton instead of validating-and-discarding. The IB importer reuses the cached SID the poller writes to the DB after each login (`ensure_session(cached_sid)` falls back to a fresh `api_login.php` only when stale). FA and WS skipped on purpose — cookie auth and API-key auth respectively have no login flow to persist. **2.18.4:** AO3/SqW import + auth-connect now route through the poller's persistent client singleton instead of constructing+closing throwaway clients. Caught from the AO3 import logs: `auth/connect` validated and discarded the session at 02:20:11; the import endpoint then ran `ensure_logged_in()` cold at 02:24:58 (because each fresh AO3Client has `_logged_in=False`) which called `login()` and got 429ed by AO3's per-IP login throttle. Three fixes: (1) importers and `auth/connect` both now resolve via `polling.{ao3,sqw}_poller._get_or_create_client(settings)` so all four code paths share session cookies + Anubis tokens (SqW); (2) importers no longer `client.close()` — the singleton outlives the import call; (3) `ensure_logged_in()` on both AO3 + SqW clients only flips `_logged_in=False` when the verification fetch returned a fetched page lacking "Log Out" — when the fetch failed entirely (timeout / 429-exhausted retries / transient Cloudflare) the session is assumed still valid rather than torn down. AO3 itself doesn't use Anubis; only SqW does. **2.18.3:** `.env` no longer clobbers UI-set credentials. `server.py:_seed_settings_from_env()` was running on every container start and overwriting any setting that differed from the corresponding env var, so credential changes made through the dashboard silently reverted on restart. Behaviour is now strictly one-way: env vars only fill in missing/empty fields — UI/vault values always win. Followed from the SqW draft probe where `sqw_username` was stuck on `'PawPoller'` despite the vault having a different value, because `.env` had `SQW_USERNAME=PawPoller` and was clobbering it. **2.18.2:** OTW import auth-wall guard — caught when the user supplied two real drafts (AO3 `82713211`, SqW `92124`) and the SqW import wrote a stub story with `is_draft=true` and no content. Root cause: AO3 + SqW have no posting credentials in `settings.json` (only `ao3_target_user` / `sqw_target_user` for polling), and SqW redirects unauthorized work fetches to the user dashboard with 200 OK rather than 404, so the heuristic accepted the fallback response. Both importers now sanity-check the post-fallback HTML for the title-heading + userstuff markers, raising a clear "drafts are owner-only — check credentials" error instead of silently writing a stub. **2.18.1**: importer draft support — `import_from_ao3` and `import_from_squidgeworld` now try `/works/{id}` first and fall back to `/works/{id}/preview` for unposted drafts; `import_from_inkbunny` and `import_from_sofurry` flag draft state from existing API responses (`public == "no"` for IB; `publishedAt` null/empty/0000-prefixed/future for SF). Manual "Import by URL or ID" row added to the editor's import overlay so draft IDs can be pasted directly — accepts platform-prefixed (`ao3:12345`) and full URLs across all five supported platforms. Imported drafts get an amber row tint + "Done (draft)" button label.)
**Earlier:** 2.18.0 ("do them all" pass — EPUB viewer Aa appearance dropdown (size + theme + persistence) + full-page cover override + last-position restore via localStorage; subtitle + dedication input fields wired into the metadata drawer with `editor/epub_generator.py` preferring story.json over MASTER.md frontmatter; draft-state probes implemented for IB / SF / AO3 / SqW (the `POST /api/editor/stories/{name}/probe-drafts` endpoint had existed since 2.16.x — these are the missing implementations); AO3 + SqW story importers built using a shared `_parse_otw_work_page()` helper that pulls title/author/summary/rating/tags/chapters out of the OTW Rails work page in one `?view_full_work=true` round trip, closes the "coming soon" badge from Phase 14a (2.13.0). Walk of `qa/AUTOMATED_BUG_LOG.md` confirmed every round-1 + round-2 bug is already closed in 2.14.8 / 2.16.x.)
**Even earlier:** 2.17.6 (in-app EPUB viewer — closes the "EPUB is download-only" follow-up from 2.17.4. Vendors `epub.js` 0.3.93 + `jszip` 3.10.1 to `frontend/vendor/` (~315KB), adds `frontend/epub-viewer.html` + `frontend/js/epub-viewer.js`, and a `GET /epub-viewer.html` route in `dashboard.py` with a scoped CSP relaxation that allows `blob:` for style/img/font/connect/frame on that one path only — the rest of the dashboard keeps the strict default. The editor's Downloads dropdown grows a "↗ Preview in browser" sub-row directly under the EPUB row that opens the viewer in a new tab. Two CSP gotchas during the Playwright-driven QA pass: (1) inline scripts in `epub-viewer.html` were blocked because the dashboard CSP only allowlists one specific SHA-256 hash (the `index.html` theme bootstrap) — fixed by extracting viewer logic to `/js/epub-viewer.js` and copying `index.html`'s boot script byte-for-byte so the existing hash covers it; (2) epub.js extracts the EPUB's stylesheets/fonts/images into `blob:` URLs which the strict CSP dropped — fixed via the path-scoped CSP. End-to-end verified on the live VM: cover → title → author's note → chapter content all render with two-column spread, italic narration in Crimson Pro, percent indicator updates, prev/next + tap zones + keyboard arrows all advance pages. 2.17.5 — `pawsync.py` now supports `--prune` / `--dry-run` for removing server-side top-level story orphans missing locally. 2.17.0–2.17.4 — Vellum-style EPUB 3.0 generator at `editor/epub_generator.py` validated under epubcheck 5.1.0 / EPUB 3.3 (0/0/0/0); EPUB lives in its own `EPUB/{stem}.epub` folder, `.epub` allowlisted in `/api/posting/file`, whole-story `.zip` archive endpoint, downloads dropdown polished. Earlier in the session: Mobile Mode Phase 5 sweep + backlog cleanup through 2.16.14.)
**Deployed to:** GCP instance `pawpoller` (zone `us-east1-c`) — pending 2.18.1 deploy.
**GitHub release:** https://github.com/knaughtykat01-prog/PawPoller/releases/tag/v2.18.0 — current published release. Master is one version ahead (2.18.1).

> **2.14.3 file-tree refactor — read this before navigating the codebase.** All 11 platform clients moved into `clients/` (e.g. `api_client/` → `clients/ib/`, `ao3_client/` → `clients/ao3/`, ...). Imports now look like `from clients.ib.client import InkbunnyClient`. Internal docs (HANDOFF, SETUP, ROADMAP_PUBLIC, documentation_guide) moved into `docs/`. Three orphans deleted from root (`112.png`, `TESTING_CHECKLIST.md`, legacy `settings.json`). Zero behaviour change. See CHANGELOG `[2.14.3]` for the full validation gates.

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
