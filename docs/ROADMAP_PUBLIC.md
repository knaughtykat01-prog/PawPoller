# PawPoller Public Release Roadmap

**Status:** Public beta shipped
**Date:** 2026-04-25
**Current version:** 2.13.8
**Latest release:** https://github.com/knaughtykat01-prog/PawPoller/releases/tag/v2.13.8

---

## Vision

PawPoller is a **story-first multi-platform publishing pipeline** for furry fiction writers. Write in Markdown, generate every format (BBCode, HTML, PDF, SquidgeWorld, Styled HTML), publish to 9+ platforms, and track analytics — all from one app.

Two modes:
- **Desktop** — local app (Windows), no server needed. Polls platforms, tracks stats, publishes. Only mode that can post to FurAffinity (datacenter IP blocks).
- **Server + Desktop** — server handles polling/analytics 24/7, desktop syncs settings + handles FA via a queue.

What makes PawPoller different from PostyBirb: PawPoller is built for **writers**, not visual artists. Chaptered posting, per-chapter tags, format conversion, story analytics, drift detection, work skins. PostyBirb posts images with descriptions; PawPoller publishes novels.

---

## What shipped

All must-have and should-have items from the original plan are live in 2.13.8. Condensed status across Phases 8–15:

| Phase | Feature | Shipped | Notes |
|-------|---------|---------|-------|
| 8a | Embedded browser login | 2.12.x | pywebview popup for FA / DA / TW / SF / WS / AO3 / SqW |
| 8b | Manual credential fallback | ✓ | Per-platform settings cards with paste-cookie helpers |
| 8c | Credential vault | 2.12.0 | Fernet + keyring/dotfile key; enable/disable from UI |
| 9a | Setup wizard | 2.12.x | 4-step first-run flow with platform cards |
| 9b | New story wizard | 2.12.1 → 2.13.0 | Title/author/chapters/rating + 9 genre templates + optional file upload |
| 10a | Anchor toolbar | 2.11.0 → 2.13.8 | 10 buttons after the 2.13.7 audit (Title / Sub / Byline / Warning / Disclaimer / FF / Body / → Sent / ← Recv / ☎ Phone) with 1.2 s hover tooltips showing before/after examples |
| 10b | Selective regeneration | 2.11.0 | HTML / BBCode / Styled / SQW / PDF / chapters |
| 10c | Work skin auto-gen | 2.10.0 | `_ensure_work_skin()` on post/edit for AO3 + SqW |
| 10d | Per-platform descriptions | 2.11.0 | Short (IB/SF) + Announcement (Bsky) fields in metadata drawer |
| 10e | Format preview | ✓ | Format tab bar in editor replaces the old dropdown |
| 11a | Cover image upload | ✓ | IB, FA, SF, WS wired end-to-end |
| 11b | Per-chapter thumbnails | 2.12.1 | Metadata drawer slot per chapter, auto-updates story.json |
| 12a | Regen staleness warning | 2.11.0 | Inline warning in Publish Check with "Regenerate now" button |
| 12b | Edit from published stories | 2.11.0 | Edit button on submissions view routes back to editor |
| 12c | Post scheduling | 2.11.0 | Date/time picker + `scheduled_posts` table + cron-like dispatch |
| 12d | Retry queue | 2.11.0 | 1 min / 5 min / 30 min backoff, max 3 attempts |
| 14a | Import from platform | 2.13.0 | IB / SF / FA end-to-end (BBCode/HTML → Markdown). AO3 + SQW still "coming soon" |
| 15a | Repo cleanup + licensing | 2.13.0 | MIT LICENSE, CONTRIBUTING.md, .env.example, `.gitignore` hardening |
| 15b | README + SETUP | 2.13.8 | README trimmed to highlights + Quick Start; new SETUP.md walks through desktop / Docker / web-facing / from-source end-to-end |
| 15c | GitHub Actions CI | 2.13.0 → 2.13.8 | `build.yml` (PyInstaller → zip → release on `v*` tag) + `lint.yml` (ruff + JS syntax) + pinned test deps |

Polling-side improvements (outside the original phase plan but shipped as part of the 2.10 – 2.11 push): session expiry recovery across all 11 platforms, N+1 query batching (IB / FA / SQW / AO3 executemany), AO3 rate-limit handling (`Retry-After` + exponential backoff), Telegram error UX, skip-startup-poll.

---

## Open roadmap

### Near-term (completes the 2.13.x line)

- [ ] **AO3 / SquidgeWorld import** — finish the second half of 14a. Scraping + BBCode/HTML → Markdown conversion for OTW-archive stories. Shares most of its code with the existing AO3/SQW poster clients.
- [ ] **Analytics export** — CSV + PNG chart export for story performance. The chart infrastructure (Chart.js) is already in place; needs a "Download CSV" button and an `html2canvas`-style chart → PNG path.
- [ ] **Auto-update mechanism (15d)** — the partial updater (`updater.py`) already checks GitHub for the latest tag and surfaces a notification. Remaining work: one-click "Download + replace .exe + restart" flow using a helper exe (can't self-overwrite a running binary on Windows).
- [ ] **Weasyl end-to-end test** — blocked on account-level verification, not a code issue. Everything else on the Weasyl side is wired.
- [ ] **Deploy 2.13.1+ to the GCP server** — 2.13.1 through 2.13.8 are currently desktop-only. Server still runs 2.13.0. The editor fixes and vault diagnostics are safe to roll out; the anchor-toolbar changes are frontend-only so no server compatibility concerns.

### Medium-term

- [ ] **Cloud sync polish** — Phase 7a shipped the pull/push flow. Outstanding: delta conflict resolution (right now "push" is authoritative), audit log of what synced when, "sync health" badge on the Settings page.
- [ ] **Plugin-ish platform registration** — formalize the per-platform file pattern (`clients/{xx}/`, `polling/{xx}_poller.py`, `database/{xx}_queries.py`, `routes/{xx}_api.py`, `posting/platforms/{xx}.py`) into a contributor-friendly cookiecutter or template command so adding a new platform is a single scaffold step. No dynamic loader — still statically imported.
- [ ] **CI test modernization** — switch the test job from `python -m unittest discover` to `pytest`. Two test modules (`test_integration_posting`, `test_platform_posters`) are pytest-style today and get silently skipped by unittest discovery. Changing the command gets them actually executed.
- [ ] **Thumbnail auto-resize** — Pillow is already a dep; fall back to auto-resize when an uploaded cover exceeds a platform's size cap instead of surfacing an error.
- [ ] **Story template library** — beyond the 9 genre presets, let users save their own starting templates (e.g. "my chaptered m/m romance template with these 12 tags pre-selected").

### Audit-pass debt (surfaced 2.14.4, not yet fixed)

These came out of the 2026-04-27 audit pass and are real but didn't fit
the "ship between QA runs" bar. Each is its own focused commit:

- [ ] **N+1 query batching across `database/*_queries.py`** —
  `get_*_comparison_snapshots()` in 11 files runs one SELECT per
  submission. Convert to `WHERE submission_id IN (...)` + Python-side
  group. Visible perf win on comparison-chart load.
- [ ] **Per-poller toast + Telegram notification helper** — ~80 lines of
  identical Windows toast / Telegram async post / HTML escaping
  duplicated across all 11 `polling/*_poller.py` files. Extract to
  `polling/notifications.py:send_activity_notification()`.
- [ ] **Cache `config.get_settings()` at top of route handlers** —
  several `routes/*_api.py` handlers call it 2-3× within one function
  body. Read once at entry, reuse.
- [ ] **`config.py` split** — ~800 lines mixing paths, vault crypto,
  auth helpers, settings I/O, logging setup. Split into
  `paths.py` / `vault.py` / `auth.py` / `settings_io.py`.
- [ ] **Vault key ACL hardening on Windows** — `_secure_file_permissions`
  is a Unix-only no-op, so the `.vault_key` dotfile fallback inherits
  default ACLs on Windows. Mostly theoretical (Windows keyring almost
  always works so the dotfile path is rarely taken), but worth
  closing with DPAPI or `icacls`.
- [ ] **Dashboard frontend cache-buster consistency** — JS files in
  `frontend/index.html` are scattered across `v=240, 285, 22, 13, 311`
  while CSS files are uniformly at `v=310`. Either move to a single
  global constant or hash-bust on file-mtime so a forgotten bump
  doesn't ship stale JS.

### Cloud / hosted access — separate development stream

Surface a "use it in the browser" story without rewriting the world. Three layered options, picked up in order as demand proves out:

**Stage 1 — Demo mode** (low effort, low commitment). Add a `DEMO_MODE=1` flag that short-circuits writes and ships a public sandbox instance hosted by the maintainer. Visitors click around the dashboard/editor, can't save or post. Feeds the "Try it" button on the marketing site. ~1 day of work.

**Stage 2 — One-click deploy (Option A in the site's "Cloud" tier)**. Polish Fly.io / Railway / DigitalOcean deploy manifests so users can spin up their own PawPoller instance with one click. They own their data, they pay the PaaS, the maintainer holds zero credentials. Needs: a `fly.toml` / `railway.json`, a cleaner empty-state first-run flow, a "Deploy your own" button on the site. ~1–2 days of work.

**Stage 3 — Multi-tenant SaaS (Option B)** — *deferred, not planned*. True "sign up and write" hosted service. Requires rewriting every query for per-user scoping, per-user credential vaults, quota/billing, terms of service, security review — and makes the maintainer a credential custodian for everyone who signs up. Gated on real demand + funding for the ongoing liability. Kept open in the roadmap so architectural decisions don't close the door on it (e.g. don't hardcode single-user assumptions in new code), but no work planned.

Design decisions that keep Stage 3 achievable later without breaking Stage 1/2:
- New database tables should carry an optional `owner_id` column (nullable for single-user mode).
- New routes should accept (but not yet require) an authenticated user identity.
- Avoid sprinkling `/app/data/` paths into new code — use `config.DATA_DIR` so it can be per-user later.

### Long-term / "nice someday"

- [ ] **Goal tracking UI** — set targets for views / faves / comments per story, render progress bars, Telegram notification on hit.
- [ ] **Story performance comparison** — side-by-side charts for multiple stories on one dashboard.
- [ ] **Offline analytics cache** — show last-known stats when a platform is unreachable instead of blank cells.
- [ ] **`.docx` / `.rtf` import** — the new-story wizard accepts these file types today but the conversion is basic; richer Word/RTF → Markdown via `python-docx` / `pandoc` fallback would preserve more formatting.
- [ ] **Multi-user mode** — unclear if there's demand. Would need PostgreSQL + per-user credential isolation. Not on the roadmap; flagged so the decision's recorded.

---

## Decisions locked in

These came up in the original plan as open questions and have now been answered by shipping:

1. **pywebview over Electron** — stayed with pywebview. Browser-login worked fine with it; no need for Electron's heavier footprint.
2. **Story format** — Markdown with HTML-comment anchors (`<!-- @title -->` etc.) is the canonical source. `.docx` / `.rtf` are import-only, never the source of truth.
3. **Database** — SQLite (WAL mode). No move to PostgreSQL planned while the app stays single-user.
4. **Name** — stayed "PawPoller" despite the publishing-heavy pivot. Too much muscle memory and existing deploys to rename now.
5. **Plugin system** — platforms share a consistent file pattern but are statically imported. No dynamic loader; contributors add a new platform by following the pattern, not by registering with a runtime API.
6. **Auth mechanism** — session-based for the dashboard (bcrypt + signed cookie + optional TOTP + optional Turnstile + API keys). HTTP Basic was considered and rejected for the richer auth model.

---

## How the public release landed

- **v2.13.0** (2026-04-20) — shipped the full 14a import, genre templates, configurable author, and all the GitHub packaging (15a/b/c).
- **v2.13.1 – v2.13.7** (2026-04-24) — six fixes and polish passes: anchor-toolbar silent-no-op bug, publish-check IndexError for single-piece stories, vault-enable error surfacing, PDF regen diagnostics, PDF header/footer suppression, full-bleed print background, anchor-toolbar audit removing fake anchors.
- **v2.13.8** (2026-04-24) — inline anchor button labels + tooltip pacing + CI pipeline fixes (pytest and respx pinned in `requirements-server.txt`).

What's live right now on GitHub:
- README + SETUP.md + CHANGELOG + documentation_guide + CONTRIBUTING
- GitHub Actions building Windows zip on every `v*` tag push
- MIT license, .env.example, `.gitignore` hardened, no secrets in tracked files
- Single `v2.13.8` release with structured release notes (old v1.x releases from the pre-rename era deleted)

See [`../CHANGELOG.md`](../CHANGELOG.md) for the per-version detail.
