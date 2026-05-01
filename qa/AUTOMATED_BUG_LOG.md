# Automated QA Bug Log — 2.14.6

**Run started:** 2026-04-28
**Driver:** Playwright MCP, dark theme, viewport 1280×720 (default)
**Target:** `http://127.0.0.1:8421/` (test container, server runtime, fresh state)
**Tester:** Claude Code automated pass
**Scope:** Web dashboard only. No publishing actions, no posting to live platforms.

---

## Severity legend

- **P0** — Blocks usage of a major flow
- **P1** — Visible regression / broken UX, no data loss
- **P2** — Console/network noise, cosmetic glitches
- **P3** — Minor / nice-to-fix

---

## Summary

**Scenarios walked**

| # | Scenario | Status |
|---|---|---|
| 1 | Setup wizard server-runtime walk (welcome → archive → platforms → done) | ✅ pass |
| 2 | Dashboard navigation, theme picker, sidebar | ⚠ blocked by sidebar overlay (BUG-008) |
| 3 | Settings tabs walkthrough (10 tabs) | ✅ all render |
| 4 | Editor empty state | ✅ pass |
| 5 | Auth + security pages (Change Password / TOTP / API Keys / Turnstile) | ✅ pass |
| 6 | Posting list, queue, FA dashboard, analytics | ✅ pass |

**Bugs by severity**

- P0: 0
- P1: 2 — BUG-001 (cache-buster), BUG-007 (loading-screen IB error trap)
- P2: 5 — BUG-002 / BUG-003 / BUG-004 / BUG-005 / BUG-006 / BUG-008
- P3: 1 — BUG-009

**Total: 9 bugs**, 7 found inside the wizard or first-run flow.

**Test artefacts** (in `qa/`)
- 13 screenshots: `qa-test-login-page.png`, `qa-wizard-server-step1..4`,
  `qa-after-cachebust.png`, `qa-after-wizard-finish.png`,
  `qa-dashboard-loaded.png`, `qa-settings-{appearance,general,
  platforms,polling,about,security-expanded,publishing,telegram,
  data,logs}.png`, `qa-fa-dashboard.png`, `qa-editor.png`,
  `qa-posting-stories.png`, `qa-posting-queue.png`, `qa-analytics.png`
- `qa/_seed_for_qa.py` — bootstrap script used to seed dummy IB
  credentials + a placeholder submission row so the front-end gates
  pass during automated runs. Cherry-pickable into a future
  `qa/run_automated_qa.py` script.

**How to repro**

1. `docker compose -f docker-compose.test.yml up -d --build`
2. Reset wizard:
   `docker exec pawpoller-test sh -c "cd /app && PYTHONPATH=/app python -c 'import config; config.save_settings({\"setup_complete\": False})'"`
3. Bump cache-buster in container (BUG-001 workaround):
   `docker exec pawpoller-test sh -c "sed -i 's/app.js?v=311/app.js?v=312/' /app/frontend/index.html"`
4. (Optional, to bypass IB-gate beyond wizard) seed dummy creds via
   `_seed_for_qa.py`.
5. Drive via Playwright MCP from `http://127.0.0.1:8421/`.

**What's working well**
- 2.14.6 server-runtime wizard renders correctly (4 dots, no mode question)
- Setup Mode panel shows server badge + polling owner correctly
- Tray / Windows-startup / desktop-notifications rows correctly hidden
  on server runtime
- "Update Now" button correctly hidden on server, "Check for Updates"
  remains
- Server auto-stamps `setup_mode = "server"` on first boot
- All 10 Settings tabs render and the tab strip is keyboard-navigable
  via direct URL hash
- Empty states (Stories / Queue / Analytics / Editor) all show
  reasonable copy

---

## Bugs found

### BUG-001 — `app.js` cache-buster not bumped for 2.14.6 [P1]

**Where:** `frontend/index.html:467` — `<script src="/js/app.js?v=311">`

**Symptom:** Users on the dashboard with a cached `app.js` continue
serving the pre-2.14.6 file because the `?v=311` cache-key wasn't
incremented when the wizard code changed. Old wizard renders, new
modes / pairing / Setup Mode panel never reaches the user.

**Repro:**

1. Hit dashboard with cached older app.js
2. Console shows new wizard code paths absent
3. Hard reload (`Ctrl+F5`) recovers; normal nav doesn't

**Evidence:**
- Container hash: `3866f86dc527 (564442 bytes)` ✅ contains `currentIdx > 0`
- Browser served: same `?v=311` URL but `558568 bytes`, missing
  `currentIdx > 0` — the OLD JS from before today's deploy.
- Confirmed by `fetch('/js/app.js?v=' + Date.now())` returning the
  current 564442-byte file with all new code.

**Fix:** Bump `?v=311` → `?v=312` (and bring the other JS files'
cache-busters in line, or move to mtime-based hashing — same as the
audit-debt item in `docs/ROADMAP_PUBLIC.md`).

**Workaround during this QA pass:** Patched the cache-buster in the
live test container only via `docker exec sed`. Repo state untouched.

---

### BUG-002 — CSP blocks inline `<script>` in `index.html` [P2]

**Where:** `frontend/index.html:9` (inline theme-apply for no-flash on
cold load)

**Console:**

```
Executing inline script violates the following Content Security Policy
directive 'script-src 'self''. Either the 'unsafe-inline' keyword,
a hash ('sha256-PQv0iyndH6bqQiLzwEuCSIz1xMcWBsP0swro6kOCiZI='), or a
nonce ('nonce-...') is required to enable inline execution. The action
has been blocked. @ http://127.0.0.1:8421/:9
```

**Symptom:** Brief unstyled flash on first load before CSS-cached theme
applies. Then settles. Functional, but the no-flash UX is regressed.

**Fix options:**
- Add the printed sha256 hash to `script-src` directive.
- Generate a per-request nonce in middleware and inject it into the
  CSP header + script tag.

---

### BUG-004 — Plaintext `dashboard_password` re-seeded on every server restart [P2]

**Where:** `server.py` `_seed_settings_from_env()` runs on every boot
and writes `dashboard_password` / `dashboard_user` from env vars into
settings.json. `config.migrate_dashboard_auth()` then runs second —
but if `auth_password_hash` already exists (from the first migration)
it returns early without deleting the newly-seeded plaintext.

**Symptom:** `settings.json` accumulates a plaintext password after
every restart. Live evidence from the test container right now:

```json
{
  "auth_username": "admin",
  "auth_password_hash": "$2b$12$k/zPiOVper...",
  "dashboard_password": "test",      ← plaintext, should not be here
  "dashboard_user": "admin",         ← ditto
  ...
}
```

**Severity:** P2 — bcrypt hash is what's actually used for auth, but
having the plaintext sitting next to it in settings.json defeats the
point of the migration. Anyone with read access to the JSON gets the
real password.

**Fix:** Make the early-return path also delete the legacy keys when
they're present:

```python
def migrate_dashboard_auth() -> None:
    settings = get_settings()
    if settings.get("auth_password_hash"):
        # Even if we've already migrated, scrub any plaintext that
        # _seed_settings_from_env keeps re-adding from env vars.
        if settings.get("dashboard_password") or settings.get("dashboard_user"):
            delete_settings_keys(["dashboard_password", "dashboard_user"])
        return
    ...
```

---

### BUG-009 — `updater.check_for_update` floods logs with 404 warnings when no releases are tagged yet [P3]

**Where:** `updater.py` `check_for_update()` calls
`api.github.com/repos/.../releases/latest`. GitHub returns 404 when the
repo has zero published releases (or none after a tag was deleted).

**Symptom:** every dashboard load triggers a check, every check logs:

```
[INFO] httpx: HTTP Request: GET https://api.github.com/repos/.../releases/latest "HTTP/1.1 404 Not Found"
[WARNING] updater: Update check failed: Client error '404 Not Found' for url '...'
```

server.log right now has dozens of these because 2.14.6 isn't tagged
yet. Production server will keep doing this until a release is cut.

**Severity:** P3 — noisy logs. Functionally, the updater correctly
returns `available: False` so the UI doesn't break. But every visit
to Settings → About refires the check, and `_initSidebarVersion()`
fires it on every page load.

**Fix:** treat 404 as the legitimate "no releases yet" case — log
once at INFO if at all, don't WARN. Distinct from real network /
auth failures which still deserve a warning.

---

### BUG-008 — Sidebar expansion overlaps main content [P2]

**Where:** Settings page (and likely all pages) when sidebar transitions
from collapsed (60px) to expanded (~190px).

**Symptom:** Sidebar slides over the main content area instead of pushing
it right. First theme card in Settings → Appearance is half-hidden
behind the expanded sidebar; the section heading "Click any theme to
apply it instantly..." text is also clipped.

**Repro:**

1. Land on dashboard, sidebar in collapsed/icon mode (60px wide)
2. Click theme-picker icon (🎨) in sidebar → routes to
   Settings → Appearance
3. Sidebar expands to ~190px to show full labels
4. Main content area was rendered at the 60px-margin width and
   doesn't reflow → sidebar overlays it

**Severity:** P2 — content stays clickable (just shifted right) but
visually broken first impression.

**Fix:** Either reflow main content on sidebar expand (CSS grid /
flex layout), or use absolute positioning + push-content padding
that responds to the sidebar's expanded class.

---

### BUG-007 — Loading screen stuck on IB API error, blocks every route [P1]

**Where:** `app.js` `renderLoading()` triggers an IB poll cycle on first
dashboard hit. If IB returns an auth error (or if the user has no
real IB account), the screen displays the error and never advances —
all other routes (Settings, Editor, every platform tab) are blocked
behind this loading state on first run.

**Symptom:** Dashboard shows "Setting Up — An error occurred. Login
failed: Invalid login..." and no nav. User can't reach Settings to
fix their credentials. Browser back button is the only escape.

**Repro:**

1. Fresh server install with no IB creds (or wrong creds)
2. Wizard finishes, route to `/`
3. Stuck on loading-with-error indefinitely

**Severity:** P1 — blocks any non-IB workflow until the user
hard-resets settings.json. Hits FA/SF/AO3-only writers immediately,
hits any server install where IB hasn't been seeded.

**Fix:** Loading screen should:
- Treat IB-creds-missing as a normal empty-state, not an error
- Route to Settings → Platforms when no platform creds at all
- Keep nav available even during the initial poll so Settings is
  reachable
- Or: gate on "first IB poll completed OR 10 seconds" so an IB API
  outage doesn't lock the whole UI

---

### BUG-006 — IB login gate blocks every deep link, not just dashboard root [P2]

**Where:** `app.js` route gate.

**Symptom:** Direct navigation to e.g. `#/settings/general` is redirected
to `#/login` if IB credentials aren't set. Even Settings — the place
where you'd configure platform credentials — is locked behind a
platform credential. Catch-22.

**Severity:** P2 — broken UX for server installs and for desktop users
without an IB account who just want to configure a single platform
(say, AO3-only writers).

**Fix:** Settings route shouldn't be IB-gated. The gate should apply
only to the IB-specific dashboard views. Other platforms' tabs likely
have the same issue — Bluesky-only / AO3-only users probably can't
reach their analytics until they fake IB creds. Worth confirming.

---

### BUG-005 — Wizard "Go to Dashboard" bounces to IB login on server install [P2]

**Where:** Wizard "done" step → `Go to Dashboard` button → reload to `#/`
→ app.js init flow → routes to `#/login` (Inkbunny credentials login).

**Symptom:** User finishes setup wizard on a server install. Next thing
they see is *"Sign in with your Inkbunny account to get started."* —
even though they explicitly skipped the platform-connection step. This
is the legacy IB-as-primary-login flow that pre-dates 2.14.x. On a
server-mode install where the user only configured a dashboard
password (which they already entered), this shouldn't gate them again.

**Repro:**

1. Fresh server install, run wizard
2. Skip platforms step → reach Done
3. Click `Go to Dashboard`
4. Land on `#/login` asking for Inkbunny username/password

**Severity:** P2 — confusing for users on server installs without IB,
plausibly drives them to enter dummy credentials. Doesn't block usage
because they can navigate to other tabs via URL.

**Fix:** The login gate logic in `app.js` `init()` should treat
"setup_complete && polling_owner is server && no IB creds" as a valid
empty-state — route to `#/dashboard` (or whatever the empty dashboard
view should be) instead of `#/login`.

---

### BUG-003 — CSP blocks Google Fonts stylesheet [P2]

**Where:** `frontend/index.html:21`

**Console:**

```
Loading the stylesheet 'https://fonts.googleapis.com/css2?family=
Crimson+Pro...' violates the following Content Security Policy directive:
"style-src 'self' 'unsafe-inline'".
```

**Symptom:** Google Fonts CDN call blocked. Bundled fonts (if any) cover
typography fallback — Welcome heading still renders Crimson-style serif
in the screenshot, so the typography token system is mostly intact —
but the explicit weight/family controls fall back to the browser's
serif/sans defaults. Hairline visual regressions across the dashboard.

**Fix options:**
- Whitelist `fonts.googleapis.com` and `fonts.gstatic.com` in
  `style-src` and `font-src`.
- Or self-host the three font families and drop the Google Fonts call.

---

# Round 2 — 2026-05-01

Re-run of the automated sweep against the 2.14.7 test container after
BUG-001..009 were fixed. Verifies prior fixes hold and broadens
coverage to `§2 Sidebar & Navigation`, `§3 Dashboard`, and other UI
flows that the first run didn't reach.

## Round 2 summary

**Sections walked**

| § | Section | Result |
|---|---|---|
| 1 | Boot & First-Run | ✅ pass (T1, T2 cosmetic mismatch BUG-011, T3 ✓, T13-15 auth flows ✓) |
| 2 | Sidebar & Navigation | ⚠ desktop ✓ (all 18 routes, no console errors); mobile broken — BUG-010 |
| 3 | Dashboard / Cross-Platform | ✅ pass (stats cards, recent activity, top fans, charts, all 5 date ranges, last polled) |
| 15-16 | Groups / Cross-Platform Links | ✅ pass (empty-state pages render with create buttons) |
| 17-18 | Goals / Tags | ⚠ checklist mismatch — BUG-018 (no standalone pages; surfaced inside platform dashboards / metadata drawer) |
| 19-23 | Editor & Publish Check | ⚠ Create flow detonates on misconfigured archive — BUG-019 (P1); Regenerate "All formats" incomplete — BUG-020 (P2); anchor toolbar ✓; metadata drawer ✓; format tabs ✓; publish-check matrix renders ✓ |
| 24-44 | Settings, Posting, Telegram, etc. | ✅ pass (10 settings tabs render, API key Bearer auth ✓, pause/resume polling ✓, login security ✓, password length enforced ✓, malformed payloads handled ✓, SQL injection on goals metric blocked ✓) |

**Verified BUG-001..009 fixes (from first round)**

| Bug | Verification | Result |
|---|---|---|
| BUG-001 cache-buster | All 4 CSS + 9 JS refs serve `?v=2.14.7` | ✓ |
| BUG-002 inline theme CSP | Zero CSP violations | ✓ |
| BUG-003 Google Fonts CSP | Zero CSP violations | ✓ |
| BUG-004 plaintext scrub | Inject + restart → keys removed, hash preserved | ✓ |
| BUG-005/6/7 IB-login catch-22 | `#/settings/platforms` reachable without IB creds | ✓ |
| BUG-008 sidebar reflow | Hover → body class + main-content margin both shift | ✓ after BUG-012 listener-placement fix |
| BUG-009 updater 404 | Once-only info log, no exception spam | ✓ |

**New bugs found this round**

- **P1** — BUG-010 (mobile hamburger off-screen), BUG-019 (Create New Story 500 + silent UI)
- **P2** — BUG-012 (sidebar listener placement; FIXED in this pass), BUG-020 (Regen "All formats" incomplete)
- **P3** — BUG-011 (health endpoint version cosmetic), BUG-013 (checklist title traceability), BUG-014 (IB heading inconsistency), BUG-015 (cache-buster QA workflow), BUG-016 (progress-check error fan-out), BUG-017 (#/setup reachable on server runtime), BUG-018 (Goals/Tags checklist mismatch)

**Total round-2 new bugs: 11** (1 fixed in this pass: BUG-012). 4 are checklist-mismatch / cosmetic / workflow notes rather than code bugs.

**P1s remaining: BUG-010, BUG-019.** Recommend fixing both before
shipping 2.14.7 publicly — mobile users have no way to navigate, and
fresh server installs can't create their first story without
manually editing the archive path in settings.

---

---

### BUG-010 — Mobile hamburger button slides off-screen with the sidebar [P1]

**Where:** `frontend/index.html:40` (button DOM placement) +
`frontend/css/layout.css:454-466` (mobile media query)

**Steps to repro:**
1. Resize viewport to ≤768 px (e.g. 600×800)
2. Reload `/`
3. Inspect `#hamburger-btn` bounding rect

**Observed:** Button reports `display: block` and is technically in
the layout, but its bounding rect is `x = -264`, fully outside the
viewport. The hamburger lives inside `.sidebar > .sidebar-header`,
and `.sidebar` has `transform: translateX(-100%)` on mobile to slide
off-screen — the transform takes the hamburger with it.

**Impact:** Mobile users have no way to open the navigation. P1 — the
entire mobile experience is unreachable.

**Why `position: fixed` alone won't fix it:** A `position: fixed`
descendant of a transformed ancestor is bound to that ancestor's
containing block, not the viewport. Confirmed by adding
`position: fixed; top: 12px; left: 12px;` directly to the button —
its rect was still negative because `.sidebar`'s `transform`
re-anchored the fixed element.

**Fix options:**
- **(preferred) Move the `<button>` out of `.sidebar` in `index.html`**
  to a top-level child of `<body>`, then `position: fixed` in the
  mobile media query works correctly. Add `body.sidebar-open` toggle
  in `openSidebar`/`closeSidebar` so the button can shift to sit
  above the open sidebar (`left: 240px`) instead of being covered.
- Alternatively, drop the transform on `.sidebar` and animate
  `width` or `margin-left` instead — but that's a larger refactor.

---

### BUG-011 — `/api/health` doesn't expose version (checklist mismatch) [P3]

**Where:** `routes/api.py:45-53`

**Test:** Webapp checklist test ID 2 expects
`200 OK with JSON {"status": "ok", ...} including version 2.14.7`,
but the endpoint returns `{"status": "ok"}` only.

**Impact:** Cosmetic. Monitoring tools that hit `/api/health` can't
easily distinguish container versions; checklist expectation does not
match implementation. Either:
- Add `version: APP_VERSION` to the health response (cheap; matches
  monitoring norms), or
- Update the checklist expectation to remove the version requirement
  and document `/api/version` (or `/api/system/info`) as the
  version surface — but neither of those endpoints exist either.

The docs say "Health check for Docker `{\"status\": \"ok\"}`" so the
current behaviour matches design — only the QA expectation is wrong.

**Suggested:** Add `version` field to health (small win, matches
ecosystem norms). Endpoint is unauthenticated by design (so Docker
HEALTHCHECK works), and version isn't a secret.

---

### BUG-012 — `init()` early-returns skipped sidebar reflow listeners [P2] (FIXED in this pass)

**Where:** `frontend/js/app.js:170-185` (original placement)

**Steps to repro (against original 2.14.6→2.14.7 code):**
1. Fresh container + fresh tab → land on `#/dashboard-login`
2. Sign in
3. Navigate to any sidebar-bearing route (e.g. `#/settings/platforms`)
4. Hover the sidebar — body class never gets `sidebar-expanded`,
   main content remains overlapped (BUG-008 visible again)

**Root cause:** The hover/focus listener attachment block sat *after*
two `return` statements in `App.init()` — the dashboard-auth gate at
line ~107 and the setup-wizard gate at line ~127. On first page load
for an unauthenticated user, init() returned early at the auth gate
and never reached the listener block. Hash navigation never re-runs
init(), so for the rest of the session the listeners were absent
even though the sidebar element was always present in the static
HTML.

**Fix (applied in this pass):** Listener block moved to the top of
init(), immediately after the `hashchange` registration. Verified
with `dispatchEvent(new MouseEvent('mouseenter'))` that body class
now toggles on every page including login/setup, and with a real
Playwright hover that the full chain (sidebar 220px + main margin
220px) works after navigating to settings.

---

### BUG-013 — Webapp checklist title still says "v2.14.4" in document title block (cosmetic) [P3]

Already fixed in 2.14.7 sweep but logging here for traceability —
checked at QA time, both occurrences of "v2.14.4" in
`qa/TESTING_CHECKLIST_WEBAPP.html` were updated to "v2.14.7" along
with the per-test version expectations.

---

### BUG-014 — Inkbunny page heading is a generic "Dashboard" [P3]

**Where:** Wherever IB renders its page title (likely
`frontend/js/components.js` or `app.js` route handler for `#/ib`)

**Observed:** Hash-walking the 11 platform routes, every one renders
heading `"<Platform> Dashboard"` — except IB which renders just
`"Dashboard"`. Probably a hand-rolled IB template that pre-dates the
generic per-platform component. Cosmetic but inconsistent.

---

### BUG-015 — `?v=2.14.7` cache-buster collides during same-version iterative QA [P3]

**Observed:** When fixing a regression discovered during QA without
bumping `APP_VERSION`, the browser keeps the old cached bundle
because the URL is byte-identical to before the fix. The container
serves the new file (verified via `fetch` with `cache: 'no-store'`)
but the existing tab won't pick it up without a hard reload that
bypasses cache.

**Impact:** Doesn't affect end users (each release bumps the
version). But during a QA round where multiple fixes ship under one
version number, tests can read stale assets and miss real fixes.

**Fix options:**
- Document a "QA mode" workflow: explicitly hard-reload (or add
  `?bust=<ts>` to the URL) between iterative fixes within a single
  version.
- Or, in dev/test builds, swap `?v=APP_VERSION` for `?v=APP_VERSION-<git-sha>`
  or `?v=<mtime>` so iterative dev edits invalidate cache without a
  version bump. Not worth it for a small project — workflow note is
  enough.

---

### BUG-016 — Progress-check ticker fan-out spams console on transient failures [P3]

**Where:** `frontend/js/app.js _progressCheckTick` (around line 9750)
+ `frontend/js/api.js` per-platform `getXxxPollProgress`

**Steps to repro:**
1. Open dashboard with progress check active
2. Briefly interrupt connectivity (container restart, DNS hiccup,
   network blip)
3. Watch the console

**Observed:** Every tick, the progress-check fires 9-10 parallel
fetches: `/api/poll/progress`, `/api/{ib,fa,ws,sf,sqw,ao3,da,wp,ik,...}/poll/progress`.
A single network blip produces 9-10 stack traces of the form:

```
[API] Network error: TypeError: Failed to fetch
    at Object.get (api.js:33)
    at Object.getXxxPollProgress (api.js:NNN)
    at Object._progressCheckTick (app.js:9763)
```

**Impact:** Cosmetic. The polling continues fine on the next tick,
no data is lost, but the 18-error console storm makes diagnosing
real errors harder during QA.

**Fix options:**
- Suppress the per-platform `[API] Network error` log inside the
  progress-check fan-out (keep only one summary line per tick).
- Or short-circuit the fan-out: have the backend return all
  platform progress in one `/api/poll/progress` call and stop firing
  9 parallel fetches per tick. The backend already has the data
  centrally.

---

### BUG-020 — Editor "Regenerate ▾ → All formats" silently skips Styled HTML, SquidgeWorld, PDF, and chapter splits [P2]

**Where:** Editor → Regenerate dropdown → "All formats". Server
endpoint `POST /api/editor/stories/<folder>/regenerate`.

**Steps to repro:**
1. Create a fresh story via `+ Create New Story` (e.g.
   `QA_Smoke_Test`)
2. Editor opens at `#/editor/QA_Smoke_Test` with the default 1-chapter
   template loaded
3. Regenerate ▾ → "All formats"
4. Wait for the request to complete (returns 200 OK)
5. Inspect `/app/data/story-archive/QA_Smoke_Test/` on disk

**Observed:** Endpoint returns 200, no error toast or banner, but
only 6 files are written:
- `Markdown/MASTER.md`
- `CHAPTER_STYLING.md`
- `BBCode/QA_Smoke_Test_bbcode.txt`
- `HTML/QA_Smoke_Test_Clean.html`
- `HTML/QA_Smoke_Test_SoFurry.html`
- `story.json`

Empty subdirs are created but never populated:
- `PDF/` (empty)
- `SquidgeWorld/` (empty)
- No Styled HTML file under `HTML/`
- `Chapters/<chapter>/` subdirs exist but are empty

**Impact:** Checklist test 196 ("All formats" → "Every format file
rebuilt; staleness banner clears") fails. Users who pick "All
formats" expecting a complete bundle get a partial one with no
indication of what was skipped.

**Possible causes (not yet diagnosed):**
- "All formats" is intentionally a subset and the menu item is
  mislabelled (should be "Common formats" or similar).
- WeasyPrint may not be available in the container — but the
  endpoint reports 200 instead of partial-success.
- Styled HTML and SquidgeWorld may require specific story.json
  fields or multi-chapter content; if so, the UI should signal
  that these were skipped and why.

**Suggested:** Have the regen endpoint return a structured response
listing which formats it generated and which it skipped (with
reason). Frontend then surfaces a toast like
`"Generated: BBCode, Clean HTML, SoFurry HTML. Skipped: Styled HTML
(reason), PDF (WeasyPrint unavailable), SquidgeWorld (single
chapter)."`

---

### BUG-019 — `POST /api/editor/stories/create` 500s with unhandled `FileNotFoundError` when archive path is missing [P1]

**Where:** `routes/editor_api.py` (or wherever `stories/create` is
mounted) + the Editor "+ Create New Story" flow.

**Steps to repro:**
1. Fresh container, no `posting_story_archive_path` set (or set to a
   path that doesn't exist on the container)
2. Open `#/editor` → click `+ Create New Story`
3. Fill in title/folder/author → Create

**Observed:** API returns HTTP 500. Container logs show:

```
[ERROR] dashboard: Unhandled error on POST /api/editor/stories/create:
[Errno 13] Permission denied: '/m_x'
…
FileNotFoundError: [Errno 2] No such file or directory:
'/m_x/Archives/Complete_Stories/QA_Smoke_Test/Markdown'
```

The Frontend swallows the 500 silently — no toast, no inline error.
The Create modal stays open, the user can't tell anything is wrong.

**Two bugs in one:**
1. **Default archive path is host-specific** (`/m_x`) and doesn't
   exist inside the container. On fresh installs the wizard collects
   a path, but if the user skipped the wizard or the path is wrong,
   the create flow detonates.
2. **The endpoint doesn't validate path before mkdir** and lets the
   `FileNotFoundError` / `PermissionError` propagate to FastAPI's
   default 500 handler instead of returning a 400 with a helpful
   message.

**Impact:** The Create New Story flow is broken on every fresh
server install where the wizard wasn't fully walked. Even after the
wizard, if the configured path is wrong, this 500 happens with no
user-visible error.

**Fix options:**
- Validate `posting_story_archive_path` exists + is writable before
  attempting to create, return 400 with `{"error": "Archive path is
  not configured or not writable. Set it in Settings → General."}`
- Frontend should toast on 4xx/5xx responses from
  `/api/editor/stories/create` instead of silently swallowing.
- Provide a sensible default that exists in the container (e.g.
  `/app/data/story-archive` and auto-create it).

---

## Round 2.5 — Production sweep — 2026-05-01

Read-only Playwright sweep against the live GCP instance at
`http://35.243.213.49:8420/`. Production is on **2.14.6**, so
BUG-001..009 are all visible in the wild. Sweep limited to navigation,
viewing, and reversible actions — no Save/Create/Delete/Resync/posting.

### BUG-021 — IB Submissions search filter is broken (does not filter at all) [P2]

**Where:** IB submissions page (`#/submissions` on prod, equivalent
list view on the test container — but test container had no rows so
this couldn't be observed there).

**Steps to repro:**
1. Open `#/submissions` on prod (9 IB submissions in the list)
2. Type any string into the "Search titles and keywords..." textbox
3. Wait for input event to fire

**Observed:** Card list does not filter. With search="extra" all 9
submissions remain visible (only "Extra Credit" should match). With
search="xyzunlikelynothingmatch" all 9 still visible (zero should
match). The input value updates in the DOM but no filtering is
applied to the rendered cards.

**Note on view modes:** The page may have two render modes (a
`<table>` view and a card view). On first load, hitting column
headers to test sort flipped the view from table to cards. The
search filter may be implemented for the table view but not the
card view, or the filter may key off the wrong DOM tree.

**Impact:** Checklist test 57 fails on real data. Users with many
submissions can't narrow the list. Not a P1 because URL deep-links
to specific submissions still work, and the table view sort still
helps.

---

### BUG-022 — Editor "Metadata" button on prod 2.14.6 opens Platforms popover, not metadata drawer [P2]

**Where:** Editor (`#/editor/<story>`) → "Metadata" button
(`#editor-metadata-btn`).

**Steps to repro (on prod 2.14.6):**
1. Open Editor for any real story (e.g.
   `#/editor/Chosen`)
2. Click the **Metadata** button in the toolbar

**Observed:** Instead of the expected metadata drawer with
collapsible sections (Story Info, Description, Classifications,
Per-Platform Tags, Platform Toggles, Chapters, Cover Image, Raw
JSON), the click pops the **Platforms** modal — the same modal
opened from the sidebar's "Platforms" nav button.

The 2.14.7 test container does NOT have this issue — the metadata
drawer renders correctly there with all 8 sections. So this looks
like a regression already fixed between 2.14.6 → 2.14.7, but worth
flagging here so the deployment is prioritised.

**Impact on prod users:** Cannot edit story metadata at all from
the editor toolbar. They have to either edit story.json directly
or use the Publishing tab in Settings (different, less convenient).

**Resolution:** Will resolve when 2.14.7 ships. Confirm during
post-deploy verification.

---

### BUG-018 — Checklist §17 Goals + §18 Tags reference standalone pages that don't exist [P3]

**Where:** `qa/TESTING_CHECKLIST_WEBAPP.html` §17 (tests 147-152) and
§18 (tests 153-157) describe a `#/goals` page and a `#/tags` page
with create/edit/delete CRUD UIs.

**Observed:** Both routes return the SPA's "Page not found" empty
state. Goals are surfaced *inside* per-platform dashboards (IB, FA,
etc. — see `app.js:1852-1873` `goalProgressCards`), and tags are
managed inside the Editor's metadata drawer (Section 22 of the
checklist correctly covers this). Neither feature has a top-level
nav entry in the sidebar.

**Impact:** None on functionality — the features exist and work in
the right places. Only the checklist expectations are wrong.

**Suggested:**
- Remove §17 Goals as a standalone section and fold its tests into
  the relevant per-platform sections (or a "Goals widget on
  platform dashboards" subsection).
- Remove §18 Tags Library entirely; §22 Metadata Drawer tag tests
  cover the real surface.
- Or, add the missing `#/goals` and `#/tags` pages if a top-level
  list view is desired.

---

### BUG-017 — Welcome wizard reachable while authenticated even when `setup_complete=true` [P3]

**Where:** `frontend/js/app.js init()` setup-complete check + the
hash router for `#/setup`

**Observed:** During QA, after `setup_complete` was forced to `true`
via the Python helper, navigating to `#/setup` directly (deep link)
re-rendered the wizard. Probably benign — re-running setup is an
intended flow on the desktop side ("Re-run wizard from Settings"
documented in 2.14.6 changelog) — but on the server runtime there
is no exit path back to `setup_complete`, and the wizard's
"Go to Dashboard" button writes `setup_complete = true` again
unnecessarily.

**Impact:** Low. Internal-only oddity, didn't break QA flow.

**Suggested:** Make `#/setup` redirect to `#/` when
`setup_complete && runtime === 'server'` to match design intent
(server can't re-run setup).

---


