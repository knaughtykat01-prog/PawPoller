# PawPoller Session Handoff

**Last updated:** 2026-04-19
**Current version:** 2.11.0
**Deployed to:** GCP instance `pawpoller` (zone `us-east1-c`)

Living document — update as the roadmap shifts. Read this first when picking up a fresh session.

---

## What PawPoller is

Multi-platform story publishing + polling pipeline for furry fiction. Runs two ways:

- **Desktop** (Windows): `main.py` → PyInstaller bundle → pywebview + pystray. Needed for FA posting (datacenter IP blocks) and PDF rendering via Edge fallback.
- **Headless** (GCP/Docker): `server.py`. Polls 11 platforms, serves the dashboard + editor, posts to everything except FA (which gets auto-queued to desktop).

Port 8420. Story archive mounted at `/app/story-archive` on server, `../m_x/Archives/Complete_Stories/` locally.

---

## Where we are right now

The **Story Editor + Publish Check** system (documentation_guide.md §15) is feature-complete for **Phase 6b (POC)** and has drift detection on top. Successfully posted "Late Shift" (Test Story) to an Inkbunny draft end-to-end via the UI.

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
- [x] Frontend-only (no backend changes, no SSE) per PHASE_6D_PLAN.md

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

### Phase 7b — Local-only vault (NOT STARTED)

Design doc: `PHASE_7_DESIGN.md`. Fernet encryption with DPAPI/keyring
key derivation. `settings.vault.json` for credential fields.

### Phase 7c — Desktop setup wizard (NOT STARTED)

First-run flow: choose cloud/local, configure accordingly.

### Tag audit

- [x] Story-level tag audit across all 13 stories (~330 additions, ~45 removals)
- [x] Per-chapter tag assignments for all ~70 chapters
- [x] TAG_AUDIT_REPORT.md saved in archive root
- [x] Per-chapter tags for platform-specific arrays — chapter tag editor now shows Default/SF/IB/WP tabs (matching story-level); cascade still handles remaining platforms on publish

### WeasyPrint CSS fix

- [x] `@page { margin: 0 }` moved to top-level (was nested inside `@media print` — invalid CSS, WeasyPrint ignored it → double margins)
- [ ] Stories need Regenerate to pick up the new CSS — existing `style.css` files still have the old rule

### Other pending

- [x] Polling module audit: exc_info logging fixes (10 pollers) + silent exception swallowing replaced with debug logging
- [ ] Polling module: session expiry graceful recovery (3 pollers — needs careful testing)
- [ ] Polling module: N+1 query batching (faving users, comments — needs batch DB functions)
- [ ] AO3 rate-limit retry (backoff on 429)
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
- `PawPoller/frontend/js/editor.js` — page-level editor UI (~275 vers)
- `PawPoller/frontend/js/metadata_editor.js` — drawer + tag autocomplete (~2900 lines, v15)
- `PawPoller/frontend/js/publish_check.js` — matrix + action panel + bulk actions + action log (v10)
- `PawPoller/PHASE_7_DESIGN.md` — credential management design doc (cloud sync + local-only vault)
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

# Sync story archive only (after story file changes)
C:/Users/rhysc/claude/PawPoller/deploy/pawsync.bat

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
2. `CHANGELOG.md` top section — covers 2.9.0 onwards, which is where the publish check system lives
3. `documentation_guide.md` §14 (Posting Module) + §15 (Story Editor)
4. `routes/editor_api.py` — `/publish-check` and `/publish` endpoints are the tight loop

If the user says "what's next?" — **Phase 6c** (test the other 8 platforms end-to-end) is the obvious answer. If they want to keep the matrix UX moving, **Phase 6d** (bulk actions) is the other direction.
