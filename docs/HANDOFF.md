# PawPoller Session Handoff

**Last updated:** 2026-04-26
**Current version:** 2.14.2 (deployed; tag still at v2.13.8 — see "Release packaging" below)
**Deployed to:** GCP instance `pawpoller` (zone `us-east1-c`) — server now on 2.14.2 (was crashing on 2.13.1+ because of a vault-mode init order bug; fixed in 2.13.9)
**GitHub release:** https://github.com/knaughtykat01-prog/PawPoller/releases/tag/v2.13.8 — tag points at commit `7517ad3`. 2.13.9+ has shipped to master + GCP but no new tag has been cut yet (no Windows artifact published)

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
2. `CHANGELOG.md` top section — covers 2.10.5 through 2.14.2
3. `ROADMAP_PUBLIC.md` — public release plan (all must/should-haves + most nice-to-haves now COMPLETE)
4. `documentation_guide.md` — full technical reference (now includes auto-sync architecture under "Settings Auto-Sync (2.14.2+)")
5. **Testing checklists** — all QA artefacts live under `qa/`:
   - `qa/TESTING_CHECKLIST_WEBAPP.html` — 461 rows × 43 sections, browser/Docker/server flavour. localStorage key `pawpoller_test_webapp`. CSV exports as `pawpoller_test_webapp.csv`.
   - `qa/TESTING_CHECKLIST_NATIVE.html` — 497 rows × 49 sections, Windows desktop build (PyInstaller exe + pywebview + tray). localStorage key `pawpoller_test_native`. CSV exports as `pawpoller_test_native.csv`.
   - `qa/fixtures/` — sample upload payloads (`sample_story.{md,html,bbcode,txt,rtf}`, `sample_multichapter.md`, `sample_cover.jpg`, `sample_chapter_thumb.jpg`) referenced by file-upload rows so QA results stay reproducible. See `qa/fixtures/README.md` for the file/test mapping.
   Both checklists share ~430 universal rows (every nav link, every settings toggle, every platform's auth/list/poll/export, every editor anchor, the publish-check matrix, posting per platform, auto-sync, themes, vault, security, API). The native version adds 7 native-only sections (tray, run-on-startup, browser-login popups for 7 platforms, file dialogs, Edge PDF, vault keyring, auto-update, process behaviour). The webapp version adds 1 webapp-only section (multi-tab, HttpOnly cookies, CSP, reverse proxy, CF Tunnel, CORS).
   Both have a search/status filter bar + pass/fail/skip three-state + Import/Export CSV. Old single root-level `TESTING_CHECKLIST.html` was deleted in the same change that introduced the split. (The Python unit tests still live in `tests/` — different surface, don't confuse with `qa/`.)
6. `routes/editor_api.py` + `routes/settings_api.py` — main API surface
7. `auto_sync.py` — new in 2.14.2; small (~170 LOC), worth a glance before touching settings persistence

### CI / release pipeline state (2026-04-26)

The `Build & Release` workflow fires on `v*` tag pushes and has two
jobs: `test` (Ubuntu, unittest discover) and `build-windows`
(PyInstaller → zip → `softprops/action-gh-release@v2`). The `Lint`
workflow fires on every push to master (ruff + JS syntax).

`requirements-server.txt` pins the test deps (`pytest~=8.3`,
`respx~=0.22`) — before that the test job always failed on ModuleNotFoundError.
Latent issue: `test_integration_posting` and `test_platform_posters` are
pytest-style so `unittest discover` skips them silently. Switching the
workflow `test` step to `pytest` would actually run them; not urgent.

**Tag drift**: `v2.13.8` is still the most recent published release.
2.13.9 / 2.14.0 / 2.14.1 / 2.14.2 have shipped to master + GCP but
no Windows artifacts have been published. Cutting `v2.14.2` would
require re-running the build job; do this once the auto-sync work has
soaked for a day or two.

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

Next retest pass should:
1. Import the previous CSV snapshot into WEBAPP via Import CSV (IDs have shifted — most rows will need re-running rather than mass-import). Keep the old CSV around as historical reference.
2. Sweep WEBAPP first (it covers everything that runs in Docker — most of the surface).
3. Sweep NATIVE only on a Windows machine with the PyInstaller build, focusing on sections 41–47 (the native-only blocks).

If the user says "what's next?" — all must-have and should-have items
from the roadmap are complete, plus most nice-to-haves (import, genre
templates, configurable author, GitHub packaging all shipped in 2.13.0).
Remaining:
- AO3/SQW import (second half of 14a — listed "coming soon" in 2.13.0)
- Analytics export (charts, CSV reports)
- Auto-update mechanism (15d — in-app update download)
- Weasyl testing (blocked on account verification, not code)
- Cut `v2.14.2` GitHub release (currently undeployed to release page; master + GCP are ahead)

Story archive sync commands:
- `deploy/pawpush.bat` — local → server (push)
- `deploy/pawpull.bat` — server → local (pull)
- `deploy/pawpull.bat Story_Name` — pull single story

GitHub release workflow:
- `git tag v2.12.4 && git push --tags` → triggers build + release
- PAT needs `workflow` scope for pushing `.github/workflows/` changes
