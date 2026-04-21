# PawPoller v2.13.0 — Testing Checklist

Test each item and mark with [x] when verified. Notes column for issues found.

---

## Editor — Story Management

| # | Test | Steps | Expected Result | Status | Notes |
|---|------|-------|-----------------|--------|-------|
| 1 | Create New Story | Story list → "+ Create New Story" → enter title "Test Story" + author → Create | New folder created, editor opens with template MASTER.md containing all anchor examples | [ ] | |
| 2 | Genre template | Create new story → select "Erotica" genre | Rating auto-switches to Explicit. After creation, story.json tags.default contains erotica-related tags (erotica, explicit, sexual_content, etc.) | [ ] | |
| 3 | Genre rating override | Select "Horror" genre (mature) → manually switch rating to Explicit → Create | story.json has rating=explicit (user override wins), but tags/warnings from Horror template | [ ] | |
| 4 | File upload — Markdown | Create new story → upload a .md file → Create | MASTER.md contains the uploaded file content wrapped in @title/@body anchors, not the template | [ ] | |
| 5 | File upload — HTML | Create new story → upload a .html file → Create | MASTER.md has HTML converted to Markdown (headings as #, bold as **, tags stripped) | [ ] | |
| 6 | File upload — BBCode | Create new story → upload a .bbcode file → Create | MASTER.md has BBCode converted to Markdown ([b]→**, [i]→*, [url] converted) | [ ] | |
| 7 | File upload — Plain text | Create new story → upload a .txt file → Create | MASTER.md has the raw text content as-is | [ ] | |
| 8 | Folder name auto-gen | Type title "My Great Story" | Folder name field auto-fills as "My_Great_Story" | [ ] | |
| 9 | Folder name validation | Try folder name with special chars (e.g. "test@story!") | Error: "letters, digits, and underscores only" | [ ] | |
| 10 | Duplicate folder name | Try creating with a name that already exists | Error message about existing folder | [ ] | |

## Editor — Editing Features

| # | Test | Steps | Expected Result | Status | Notes |
|---|------|-------|-----------------|--------|-------|
| 11 | Anchor — Title | Place cursor in CodeMirror → click "T" button | `<!-- @title -->` inserted at cursor position | [ ] | |
| 12 | Anchor — Subtitle | Click "Sub" button | `<!-- @subtitle -->` inserted | [ ] | |
| 13 | Anchor — Body | Click "Body" button | `<!-- @body -->` inserted | [ ] | |
| 14 | Anchor — Warning | Click warning button (⚠) | `<!-- @warning -->` inserted | [ ] | |
| 15 | Anchor — Text Sent | Click → button | `<!-- @text-sent -->` + blank line + `<!-- @text-end -->` inserted | [ ] | |
| 16 | Anchor — Text Received | Click ← button | `<!-- @text-received -->` + blank line + `<!-- @text-end -->` inserted | [ ] | |
| 17 | Anchor — Phone | Click phone button | `<!-- @phone -->` + blank line + `<!-- @phone-end -->` inserted | [ ] | |
| 18 | Anchor — Story End | Click "End" button | `<!-- @story-end -->` inserted | [ ] | |
| 19 | Format tab — Clean HTML | Click "Clean HTML" tab | Source and preview panels update to show Clean HTML output | [ ] | |
| 20 | Format tab — SoFurry | Click "SoFurry" tab | Preview shows SoFurry-specific HTML formatting | [ ] | |
| 21 | Format tab — BBCode | Click "BBCode" tab | Source shows BBCode with [b], [i], [hr] tags | [ ] | |
| 22 | Format tab — Styled | Click "Styled" tab | Preview shows styled HTML with theme colours | [ ] | |
| 23 | Selective regen — All | Regenerate ▾ → "All formats" | All format files regenerated (check results list for HTML, BBCode, SQW, Styled, PDF, chapters) | [ ] | |
| 24 | Selective regen — HTML only | Regenerate ▾ → "HTML only" | Only Clean HTML and SoFurry HTML regenerated | [ ] | |
| 25 | Selective regen — BBCode only | Regenerate ▾ → "BBCode only" | Only BBCode file regenerated | [ ] | |
| 26 | Selective regen — PDF only | Regenerate ▾ → "PDF only" | Only PDF files regenerated | [ ] | |
| 27 | Regen staleness warning | Edit MASTER.md → Save → open Publish Check | Amber banner: "MASTER.md has been modified since the last regeneration" with "Regenerate now" button | [ ] | |
| 28 | Regen from Publish Check | Click "Regenerate now" in amber banner | Loading state → files rebuild → banner disappears → matrix reloads | [ ] | |

## Editor — Metadata Drawer

| # | Test | Steps | Expected Result | Status | Notes |
|---|------|-------|-----------------|--------|-------|
| 29 | Per-platform descriptions | Open metadata → Basics section → expand "Per-platform descriptions" | Two tabs: "Short (IB/SF)" and "Announcement (Bsky)". Each has a textarea. | [ ] | |
| 30 | Short description | Type in Short textarea → save metadata | story.json has `descriptions.short` with your text | [ ] | |
| 31 | Announcement char limit | Type in Announcement textarea | Shows character counter, maxlength=300 | [ ] | |
| 32 | Tag space→underscore (Default) | Default tag tab → type "slow burn" in tag input | Auto-converts to "slow_burn" as you type (underscore replaces space instantly) | [ ] | |
| 33 | Tag space→underscore (FA) | Switch to FA tag tab → type "slow burn" | Same auto-conversion to underscore | [ ] | |
| 34 | Tag NO conversion (SF) | Switch to SoFurry tag tab → type "slow burn" | Stays as "slow burn" (SF uses spaces) | [ ] | |
| 35 | Fix spaces button | Have some tags with spaces in Default → click "Fix spaces" | Status message: "Fixed N tag(s) — spaces replaced with underscores". Tags updated. | [ ] | |
| 36 | Fix spaces — no changes | All tags already have underscores → click "Fix spaces" | Status: "No spaces found in tags" | [ ] | |
| 37 | Sort A-Z button | Tags in random order → click "Sort A-Z" | Tags reorder alphabetically. Status: "Sorted tags on N platform(s)" | [ ] | |
| 38 | Tag browser — open | Click "Browse all matches" link or search icon | Expanded tag browser modal opens | [ ] | |
| 39 | Tag browser — Selected tab | Click "Selected" chip in filter bar | Grid shows only tags currently added to the active platform. Count badge updates. | [ ] | |
| 40 | Tag browser — Selected exclusive | Click "Selected" then click "Physical" | Selected deactivates, Physical activates (mutually exclusive) | [ ] | |
| 41 | Platform badges | In tag browser, look at an added tag card | Small platform pills (DEF, SF, IB, AO3, etc.) showing which platforms have that tag | [ ] | |
| 42 | Tag browser grid | Open browser with many tags | Cards fill full width in 3-5 columns (not single column) | [ ] | |
| 43 | Chapter tags — 4 tabs | Expand a chapter in Chapters section → look at tag tabs | Shows: Default, SoFurry, Inkbunny, Wattpad (4 tabs) | [ ] | |
| 44 | Chapter thumbnail upload | Expand chapter → click "Upload" next to thumbnail → select PNG/JPG | Filename appears. Check story.json → images.chapter_thumbnails has the entry | [ ] | |
| 45 | Cover image upload | Cover section → upload image | Preview shows the image. story.json images.cover updated. | [ ] | |

## Publish Check

| # | Test | Steps | Expected Result | Status | Notes |
|---|------|-------|-----------------|--------|-------|
| 46 | No-credentials status | Open Publish Check for a story → look at platforms you haven't configured | Lock icon (🔒) with "No credentials configured" tooltip. Not a red error. | [ ] | |
| 47 | No-credentials detail | Click a lock cell | Detail panel: "No credentials configured for this platform. Set up in Settings." No action buttons. | [ ] | |
| 48 | Live-publish warning banner | Click a ready cell → uncheck "Save as draft" | Yellow banner appears: "⚠ LIVE PUBLISH — This will be immediately visible..." | [ ] | |
| 49 | Live-publish re-check draft | Re-check "Save as draft" | Yellow banner disappears | [ ] | |
| 50 | Live confirm dialog | With draft unchecked → click Post | confirm() dialog includes extra "⚠ WARNING: This is a LIVE publish..." paragraph | [ ] | |
| 51 | Dry run — readable | Click Dry Run on any ready cell | Structured summary showing Title, Rating, Words, File (name + size), Tags (count + full list), Extras. Raw JSON available under collapsible. | [ ] | |
| 52 | Action result log | Do 3-4 dry runs or actions | "Recent actions" section appears below detail panel. Shows timestamp, action type, chapter, platform, icon. | [ ] | |
| 53 | Action log persists | Click different cells | Log stays visible (doesn't reset when switching cells) | [ ] | |
| 54 | Relative timestamps | Click a cell that has been posted | "Posted: 2026-04-17 ... (3d ago)" with relative time in parentheses | [ ] | |
| 55 | Edit from posted story | Go to Posting section → click a story → story detail page | "Edit in Editor" button visible next to title. Click → navigates to #/editor/{story}. | [ ] | |
| 56 | Schedule — open picker | Click a ready cell → click "Schedule" | Inline datetime picker appears (defaults to ~1hr from now) | [ ] | |
| 57 | Schedule — confirm | Set a future time → "Confirm schedule" | Success message with scheduled time. Queue item appears in detail panel. | [ ] | |
| 58 | Schedule — cancel | Click Cancel on a pending scheduled item | Item removed from pending list | [ ] | |
| 59 | Retry queue display | If a post fails → check the result | Shows "Will retry automatically with backoff" instead of just "Failed" | [ ] | |

## Publish Check — Bulk Actions

| # | Test | Steps | Expected Result | Status | Notes |
|---|------|-------|-----------------|--------|-------|
| 60 | Publish all new | Footer → "Publish all new" → preflight dialog | Shows all ready cells with checkboxes. Draft toggle. Go button with count. | [ ] | |
| 61 | Update all drifted | Footer → "Update drifted" | Shows only drifted cells. Same preflight pattern. | [ ] | |
| 62 | Row publish | Click number badge at end of a row | Preflight dialog for just that row's actionable cells | [ ] | |
| 63 | Bulk dry run | Preflight → "Dry Run All" | Progress panel with per-item status. All show ✓ or ✗. | [ ] | |
| 64 | Bulk cancel | During bulk operation → "Cancel remaining" | Remaining items show ⊘ Cancelled. Completed items unaffected. | [ ] | |

## Polling & Notifications

| # | Test | Steps | Expected Result | Status | Notes |
|---|------|-------|-----------------|--------|-------|
| 65 | No startup poll | Restart the app or container | Logs show "Skipping startup poll — last cycle was recent" (not immediate poll) | [ ] | |
| 66 | AO3 login retry | Wait for next poll cycle → check server logs | AO3 shows "login page retry 1/2 after 5s" if first attempt fails. Logs actual HTTP status code. | [ ] | |
| 67 | AO3 429 handling | If AO3 returns 429 | Logs show "429 rate limited, waiting Xs" with Retry-After parsing | [ ] | |
| 68 | Telegram error — classified | Trigger a platform poll failure (e.g. disconnect FA cookies) | Telegram message: "❌ 🦊 FurAffinity: Login blocked" + hint line, not raw exception | [ ] | |
| 69 | Telegram error — consolidated | Wait for orchestrated poll with a failure | Combined summary: "⚠️ 8/9 Polls Complete" with classified error for failed platform | [ ] | |

## Settings

| # | Test | Steps | Expected Result | Status | Notes |
|---|------|-------|-----------------|--------|-------|
| 70 | Sync — Check status | Settings → Data → Sync section → "Check status" | Shows: version (v2.13.0), key count, credential mode (cloud) | [ ] | |
| 71 | Sync — Pull | Click "Pull from server" | "Pulled X keys from server" message | [ ] | |
| 72 | Sync — Push | Click "Push to server" | "Pushed X keys to server" message | [ ] | |
| 73 | Vault — Enable | Settings → Data → Credential Security → "Enable encryption" | Success: "mode: local, fields_migrated: N". Check data/ folder → settings.vault.json exists | [ ] | |
| 74 | Vault — Status | Click "Check status" | Shows: mode=local, vault_exists=true | [ ] | |
| 75 | Vault — Verify settings.json | Open data/settings.json while vault is enabled | Credential fields (passwords, cookies, tokens) should NOT be in plaintext settings.json | [ ] | |
| 76 | Vault — App still works | With vault enabled, navigate around the app | All platform auth status still shows correctly (creds loaded from vault transparently) | [ ] | |
| 77 | Vault — Disable | Click "Disable encryption" → confirm | Success: "mode: cloud". settings.vault.json removed. Creds back in settings.json. | [ ] | |
| 78 | Browser login — desktop FA | Settings → Platforms → FA section → "Login via Browser" | Pywebview popup opens FA login page. Log in normally → popup closes → cookies saved. | [ ] | |
| 79 | Browser login — manual toggle | Click "Enter cookies manually" toggle | Expands to show cookie_a / cookie_b input fields (existing UI) | [ ] | |
| 80 | Browser login — server mode | Access dashboard from server (not desktop) | FA section shows "Open login page" link instead of "Login via Browser" | [ ] | |

## Setup Wizard

| # | Test | Steps | Expected Result | Status | Notes |
|---|------|-------|-----------------|--------|-------|
| 81 | First-run trigger | Remove `setup_complete` key from settings.json → reload page | Wizard appears instead of normal dashboard. Sidebar hidden. | [ ] | |
| 82 | Step 1 — Welcome | Read welcome text → click "Get Started" | Advances to Step 2. Step indicator dot 1 fills. | [ ] | |
| 83 | Step 2 — Archive path | Enter a path (e.g. `C:\Stories`) → click Next | Path saved to `posting_story_archive_path` in settings. Advances to Step 3. | [ ] | |
| 84 | Step 3 — Platforms | View platform cards | 11 platforms shown with connection status (green = connected, grey = not). "Connect" links open login pages in new tabs. | [ ] | |
| 85 | Step 3 — Skip | Click "Skip" or "Next" without connecting anything | Advances to Step 4 (skipping is fine) | [ ] | |
| 86 | Step 4 — Finish | Click "Go to Dashboard" | `setup_complete: true` saved. Page reloads to normal dashboard. Wizard doesn't appear again. | [ ] | |
| 87 | Wizard doesn't re-appear | Reload the page after completing setup | Normal dashboard loads, no wizard | [ ] | |

## Import from Platforms

| # | Test | Steps | Expected Result | Status | Notes |
|---|------|-------|-----------------|--------|-------|
| 88 | Import dialog | Story list → "Import from Platform" | Dialog shows submissions grouped by platform (IB, SF, FA). Each shows title, author, rating. | [ ] | |
| 89 | IB import | Click Import on an IB "Writing" submission | Loading state → success → "Open" link appears. New folder with MASTER.md (full BBCode→Markdown content), story.json, BBCode original. | [ ] | |
| 90 | SF import | Click Import on an SF "story" submission | Similar to IB. MASTER.md has HTML→Markdown converted content. HTML original saved. | [ ] | |
| 91 | FA import — PDF story | Import an FA story uploaded as PDF | story.json created with tags/rating. MASTER.md has description (PDF content placeholder). | [ ] | |
| 92 | FA import — TXT story | Import an FA story uploaded as .txt | MASTER.md has full text content | [ ] | |
| 93 | Already imported filter | Import a story → close → reopen import dialog | That story no longer appears in the list (filtered by import_source in story.json) | [ ] | |
| 94 | Name collision | Import a story whose folder name already exists | Creates folder with `_2` suffix. No overwrite. | [ ] | |
| 95 | Import provenance | Check imported story's story.json | Has `import_source: {platform, submission_id, url}` field | [ ] | |
| 96 | Coming soon | Check AO3/SQW in import dialog | Shown as "Coming soon" — no import button | [ ] | |

## Desktop Build

| # | Test | Steps | Expected Result | Status | Notes |
|---|------|-------|-----------------|--------|-------|
| 97 | PyInstaller build | Run `python -m PyInstaller inkbunny_analytics.spec --noconfirm` | Build completes. `dist/PawPoller/PawPoller.exe` exists. | [ ] | |
| 98 | App launches | Double-click `PawPoller.exe` | Native window opens with dashboard. No crash. | [ ] | |
| 99 | Tray icon | Check system tray after launch | PawPoller icon visible. Right-click shows menu (Show/Hide, Quit). | [ ] | |
| 100 | Desktop polling | Wait for one poll interval | Poll cycle runs, stats update on dashboard | [ ] | |

## Server Deploy

| # | Test | Steps | Expected Result | Status | Notes |
|---|------|-------|-----------------|--------|-------|
| 101 | Docker build | `sudo docker compose up -d --build` | Container builds and starts without errors | [ ] | |
| 102 | Health check | `curl http://localhost:8420/api/health` | Returns 200 OK with version info | [ ] | |
| 103 | Logs clean | `docker compose logs --tail=30 pawpoller` | No ERROR lines on startup. Poll orchestrator starts with correct interval. | [ ] | |
| 104 | Server polling | Wait for poll cycle | Consolidated Telegram summary arrives. Stats update on dashboard. | [ ] | |

## GitHub & CI/CD

| # | Test | Steps | Expected Result | Status | Notes |
|---|------|-------|-----------------|--------|-------|
| 105 | README renders | Visit repo page on GitHub | README.md displays with features, platform table, quick start | [ ] | |
| 106 | LICENSE visible | Check repo root | MIT license file present | [ ] | |
| 107 | CONTRIBUTING visible | Check repo root | Contributing guide present | [ ] | |
| 108 | Lint on push | Push a commit → check Actions tab | Lint workflow runs: ruff passes, JS syntax passes | [ ] | |
| 109 | Build on tag | `git tag v2.13.0 && git push --tags` | Build workflow triggers → PyInstaller runs → .zip artifact on release page | [ ] | |
