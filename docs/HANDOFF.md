# PawPoller Session Handoff

**Last updated:** 2026-06-10
**Current version:** 2.26.3 — pollers no longer hold the SQLite write lock across network
awaits (IB/FA/SqW/AO3 now commit before any fetch that follows a write; was causing
intermittent `database is locked` failures across all platforms), and timeout-family
exceptions no longer produce blank "Poll ib failed: " messages (`describe_error()` in
`polling/notifications.py`, applied at all 11 pollers + orchestrator + Telegram).

**Per-version history lives in `../CHANGELOG.md`** — every release has a full prose entry
there. Grep it by version (`## [2.26.1]`) instead of reading it whole. This file carries
only current state.

**Deployed to:** GCP instance `pawpoller` (zone `us-east1-c`), running 2.26.3 — in sync
with master.

**Ops notes (2026-06-10):**
- **Billing-lapse outage:** GCP billing lapsed in early June; Google TERMINATED the VM
  (polling down for up to ~2 weeks). Billing re-enabled + VM restarted 2026-06-10;
  container came back healthy on its restart policy. The ephemeral external IP changed:
  35.243.213.49 → **35.231.162.181** — anything pointing at the old IP (bookmarks,
  desktop pairing `posting_server_url`) needs updating. Consider a reserved static IP.
- **FAExport outage (FA polling dead since ~2026-05-26):** every JSON endpoint on
  faexport.spangle.org.uk 500s with `error_type: unknown_http` (web UI fine, all users,
  all client IPs — their scraper session against FA is broken, most likely a Cloudflare
  block of their egress IP in a page format their detection misses). Reported upstream
  with code-level diagnosis as
  [Deer-Spangle/faexport#129](https://github.com/Deer-Spangle/faexport/issues/129) —
  check there before re-investigating FA poll errors. Long-term fallback if it stays
  dead: direct-FA polling via cookie auth (the posting path already talks to FA directly).

**GitHub master:** https://github.com/knaughtykat01-prog/PawPoller — push-to-master
triggers no auto-deploy; ship with `/pp-deploy` (or `deploy/pawcli.bat`).

Living document — update as state shifts. Read this first when picking up a session.

---

## What PawPoller is

Multi-platform story publishing + polling pipeline for furry fiction. Runs two ways:

- **Desktop** (Windows exe / Linux AppImage): `main.py` → PyInstaller → pywebview +
  pystray. Needed for FA posting (datacenter IP blocks) and Edge-fallback PDF rendering.
- **Headless** (GCP/Docker): `server.py`. Polls 11 platforms, serves dashboard + editor,
  posts to everything except FA (auto-queued to desktop).

Port 8420. Story archive at `/app/story-archive` on server,
`../m_x/Archives/Complete_Stories/` locally.

## Where we are

**Public beta ready.** Everything on `ROADMAP_PUBLIC.md` through the must/should-haves is
shipped: setup wizard, embedded browser login, credential vault, story wizard,
multi-format editor with anchor toolbar, selective regeneration, publish-check matrix
with scheduling + retry queue + drift detection + draft probes, per-platform
tags/descriptions, cover/chapter thumbnails, EPUB output + in-app viewer, mobile mode,
8-theme picker, diagnostics tab (~170 tests), CLI TUI, Windows installer (Inno), Linux
AppImage, auto-updater, in-app uninstall. The feature-by-feature record is in CHANGELOG.

### Genuinely open work

- **Weasyl posting test** — blocked on account-level verification, not code.
- **Draft probes for Bsky / Wattpad / DA / Itaku / Weasyl** — confirm per-platform
  whether a draft state even exists before adding probes (FA/IB/SF/AO3/SqW are done).
- **AO3 import end-to-end verification** — code path identical to SqW (which works);
  test was blocked by AO3's throttle. Run imports from desktop (residential IP).
- **Bundled fonts in EPUB** — deferred until an EPUB appearance panel exists.
- **macOS desktop build** — same per-OS shim shape as Linux (2.25.0) plus .app/.dmg
  packaging; Apple Developer cert / notarization decision open.
- **Marketing site version refresh** — Hero version chip + GetIt CTA label are still a
  manual edit after each release (CF Pages auto-deploys on push to `site/**`).

---

## Critical file paths

### PawPoller
- `routes/editor_api.py` — all editor endpoints
- `routes/settings_api.py` — settings sync + vault + browser login + setup wizard
- `editor/converter.py` — format converters + anchor handling
- `editor/pdf_generator.py` — WeasyPrint + Edge fallback
- `editor/epub_generator.py` — EPUB output
- `posting/manager.py` — post_story / update_story + extras passthrough
- `posting/story_reader.py` — load_story, build_package, platform name cascade
- `posting/sync.py` — hash_file for drift detection
- `posting/platforms/{ib,fa,ws,sf,sqw,ao3,da,ik,bsky}.py` — 9 posters
- `clients/{ib,fa,weasyl,sf,sqw,ao3,da,wp,ik,bsky,tw}/client.py` — 11 platform clients
- `polling/{platform}_poller.py` + `polling/notifications.py` (shared helpers,
  `describe_error`) + `polling/cf_proxy.py` (proxy classification)
- `database/db.py` (connection + PRAGMAs) + `database/*_queries.py` + `*_schema.sql`
- `auth/browser_login.py` — pywebview cookie capture
- `frontend/js/{editor,metadata_editor,publish_check,platform_health}.js`
- `uninstall.py`, `updater.py`, `auto_sync.py`
- `tag_database/` — bundled in Docker image, **NOT under data/**
- `docs/ROADMAP_PUBLIC.md`, `docs/documentation_guide.md`
- `installer/PawPoller.iss` (AppId GUID must never change), `installer/build-appimage.sh`

### Archive / stories
- `../m_x/Archives/Complete_Stories/` — story folders (`_Test_Story/` = known-good fixture)
- `../m_x/Scripts_Utils/regenerate_story.py` — CLI regenerator / desktop fallback

### Tag DB (canonical — edit here, not in PawPoller)
- `C:/Users/rhysc/claude/Tag_Database/` → copy to `PawPoller/tag_database/` → commit →
  push → deploy

---

## Deploy cheat sheet

```bash
# Code changes (or just use /pp-deploy)
cd C:/Users/rhysc/claude/PawPoller
git add <files> && git commit -m "..." && git push
gcloud compute ssh pawpoller --zone=us-east1-c --command="cd /home/kithetiger/PawPoller && sudo -u kithetiger git pull && sudo docker compose up -d --build"

# Story archive: local -> server / server -> local
deploy/pawpush.bat            # alias: pawsync.bat; supports --prune / --dry-run / --force
deploy/pawpull.bat [Story]    # full sync or single story

# Verify
gcloud compute ssh pawpoller --zone=us-east1-c --command="curl -s http://localhost:8420/api/health"
gcloud compute ssh pawpoller --zone=us-east1-c --command="sudo docker compose -f /home/kithetiger/PawPoller/docker-compose.yml logs --tail=30 pawpoller"
```

Pause/resume polling: `POST /api/poll/pause` / `/resume` with `Authorization: Bearer pp_…`
(key in server settings.json).

---

## Known gotchas (don't get caught again)

1. **Tag DB location**: `/app/data/` is a Docker volume — it SHADOWS bundled files.
   That's why `tag_database/` lives at PawPoller root.
2. **story.json `index` not `number`** in `chapter_info[]` entries.
3. **Default tag cascade**: `default` tags cascade to every poster in `_parse_story_json()`.
4. **SQW is per-chapter only** — full-story SQW cell shows `not_supported`.
5. **FA posting requires desktop** — server posts auto-queue for desktop pickup.
6. **pawsync must precede code push** referencing new story files; it pre-checks server
   freshness and aborts if the server copy is newer (then: pawpull first, or `--force`).
7. **Server perm on archive**: container runs uid 1001, archive owned by kithetiger
   (1000); pawsync does `chmod o+rwX`.
8. **WeasyPrint on Windows**: missing GTK → automatic Edge headless fallback.
9. **confirm_live guard**: backend rejects post/update without `confirm_live=true`.
10. **Never hold a SQLite write transaction across an await** in pollers — commit before
    any network fetch that follows a write (2.26.3; busy_timeout is 30s and AO3's 12s
    pacing held the lock for minutes).
11. **AO3 routes direct from GCP** (`PROXY_OPTIONAL_PLATFORMS`) — the shared CF Worker
    egress pool burns AO3's per-IP quota (2.22.11). CF proxy is for DA + SF only.

---

## Claude Code automation

Two skills + two subagents live under `~/.claude/` (global, not in this repo):

| Ask | Use |
|---|---|
| "cut v2.27.0" / "release" | `/pp-release 2.27.0 "blurb"` — verifies (both subagents in parallel), commits, tags, pushes, watches CI, confirms 3 release assets |
| "deploy to prod" / "pawupdate" | `/pp-deploy [version]` — sync-check, confirm, SSH rebuild, health + log verification |
| "is the release ready to tag?" | `release-verifier` subagent (read-only: version/CHANGELOG/HANDOFF/AppId-GUID/tests/tree checks → SAFE TO TAG / DO NOT TAG) |
| "audit security of recent changes" | `security-reviewer` subagent (read-only, scoped to auth/credential/shell-out/path surface → SAFE / BLOCK) |

Both skills are `disable-model-invocation: true` — only the user typing them fires them.
Files: `~/.claude/skills/pp-{release,deploy}/SKILL.md`,
`~/.claude/agents/{release-verifier,security-reviewer}.md`.

---

## CI / release pipeline

`Build & Release` fires on `v*` tag pushes: `build-windows` (PyInstaller zip + Inno
installer), `build-linux` (ubuntu-22.04, AppImage), `test` (pytest, 91 green). `Lint`
(ruff + JS syntax) on every master push. Release uses `softprops/action-gh-release@v3`
(v2 broke 2026-05-26 — see CHANGELOG [2.26.2]). Known flake: asset upload can hit a
transient "Server Error"; `gh run rerun --failed` recovers it. Three assets per release:
windows zip, `PawPoller-Setup-*.exe`, `*-x86_64.AppImage`. Tags lag master by design —
last tag v2.26.x; cut releases deliberately, not per-commit.

Marketing site (https://pawpoller.pages.dev) auto-deploys via CF Pages on master pushes
touching `site/**`.

---

## QA

All QA artefacts under `qa/`:
- `qa/TESTING_CHECKLIST_WEBAPP.html` — ~566 rows, browser/Docker surface
  (localStorage `pawpoller_test_webapp`)
- `qa/TESTING_CHECKLIST_NATIVE.html` — ~638 rows, Windows/Linux desktop surface
  (localStorage `pawpoller_test_native`)
- `qa/fixtures/` — reproducible upload payloads (see its README)
- `qa/AUTOMATED_BUG_LOG.md` — Playwright sweep findings (all filed bugs through BUG-021
  fixed or retracted as of 2.16.14)

Sweep WEBAPP first (covers the Docker surface), NATIVE on a real Windows build for the
native-only sections. Python unit tests live in `tests/` — different surface.

---

## For the next session

1. This file.
2. `../CHANGELOG.md` top entry (and grep deeper history as needed).
3. `documentation_guide.md` for architecture depth (poller patterns, DB PRAGMAs + the
   write-lock rule, EPUB viewer, auto-sync, diagnostics).
4. `routes/editor_api.py` + `routes/settings_api.py` if touching the API surface.
