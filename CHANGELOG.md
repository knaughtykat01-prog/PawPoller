# PawPoller Changelog

All notable changes to PawPoller are documented here.

---

## [2.16.13] - 2026-05-02

### BUG-014 + BUG-017 cleanup

**BUG-014.** Inkbunny dashboard rendered `<h2>Dashboard</h2>` —
every other platform renders `<h2>{Platform} Dashboard</h2>`. The
IB template predates the per-platform pattern. Renamed to
`Inkbunny Dashboard` for consistency.

**BUG-017.** `#/setup` was reachable on the live server runtime
even after `setup_complete: true` — accidentally typing the route,
hitting back from a stale tab, or following a bookmark would dump
the user back into the wizard with the option to overwrite live
archive path / platform credentials / polling owner. Added a route
guard `_guardSetupRoute()` that fetches `/api/setup-status` on
every `#/setup` navigation; if `setup_complete` is true, bounces
to `#/` (Overview). The "Re-run setup" button in Settings clears
`setup_complete` server-side before navigating, so it still flows
through the guard cleanly.

If the status fetch fails, the guard falls through to the wizard
(better to render than strand on a blank page). The wizard's own
backend calls will fail noisily if the backend is truly down.

---

## [2.16.12] - 2026-05-02

### Sidebar — drop the "Platform Dashboards" dropdown

2.16.10 added a master collapse to hide the 11 platform sub-groups
in the mobile sidebar. The user pointed out it's redundant: there's
already a "Platforms" entry above it that opens a visual platform
grid popover (same destinations, fewer taps, more visual).

Removed:
- the `<li class="nav-master nav-platforms-master">` wrapper from
  `index.html`
- all 11 nested `<li class="nav-group">` platform groups (Inkbunny
  through X / Twitter, ~220 lines)
- the master CSS block in `layout.css` (`.nav-master-section`,
  `.nav-master-children`, expanded chevron)
- the master toggle handler and master-auto-expand logic in `app.js`

Sidebar reading order on Overview now:
- Overview
- Platforms (popover trigger)
- **Publishing** divider
- Stories / Queue / History
- Editor / Tools

The `.nav-group` and `.nav-chevron` CSS rules are kept untouched in
case the popover gains per-platform sub-page links later. The per-
platform routes (`/#/sf`, `/#/fa/submissions`, etc.) all still work
— only the sidebar entries are gone, and the popover already covers
the dashboard route. Sub-pages are reachable from each platform's
dashboard.

---

## [2.16.11] - 2026-05-02

### Sidebar — drop dead "Published" link

The "Published" sidebar link (`#/posting/published`) was a legacy
route that just redirected to `#/posting` (the Stories hub) because
"publications are now shown per-story" — see the comment on
`renderPublished()` in `posting.js:744`. Tapping it on mobile gave
the impression the navigation was broken (clicked Published →
landed on Stories with no visible action).

Removed the link from `index.html`. The `renderPublished()` handler
stays in place so any external bookmarks to `#/posting/published`
still resolve to the Stories hub.

---

## [2.16.10] - 2026-05-02

### Sidebar — collapse all platform groups under one master toggle

The 11 always-visible platform group headers (Inkbunny / FurAffinity
/ Weasyl / SoFurry / SquidgeWorld / AO3 / DeviantArt / Wattpad /
Itaku / Bluesky / X / Twitter) clogged the mobile sidebar. Even
with each group's sub-items collapsed by default, the stack of 11
headers pushed Stories / Queue / Published / History below the
fold on a 956px viewport.

Wrapped the 11 platform `<li class="nav-group">` items inside a new
`<li class="nav-master nav-platforms-master">` with a "Platform
Dashboards ›" header. Click toggles `.expanded` on the master,
which animates `.nav-master-children` from `max-height: 0` to
`1200px` (generous so the 11 headers + one expanded sub-group all
fit). Chevron rotates 90° when open.

Auto-expand: navigating to any platform page (`/#/sf`, `/#/fa/...`,
etc.) sets `.expanded` on the master so the user's current section
is visible. Never auto-collapses — that would override an
intentional click.

Sidebar reading order on Overview is now:
- Overview
- Platforms (existing popover trigger)
- **Platform Dashboards ›** (new master collapse)
- Stories / Queue / Published / History
- Editor / Groups
- (poll status, etc.)

Desktop unchanged in spirit (the same auto-expand logic applies);
the 220px hover-expanded sidebar still shows everything when you
land on a platform page.

---

## [2.16.9] - 2026-05-02

### BUG-016 — collapse 9× poll/progress fan-out into one endpoint

The dashboard's global progress bar polled every per-platform
`/api/{p}/poll/progress` endpoint in parallel — 9 simultaneous
fetches every 10s when idle, every 1.5s when a poll was active.
The prod live-monitor caught this as the noisiest pattern in the
DevTools console: any single auth blip spammed 9 identical 401s
at once because each platform fetch independently retried.

**Backend.** New `GET /api/poll/all-progress` in `routes/api.py`
imports each poller's progress dict locally so a partial deploy
(missing module, import error in one poller) only nulls that
slot instead of taking the whole response down. Returns
`{ib, fa, ws, sf, sqw, ao3, da, wp, ik, bsky, tw}` — same
per-platform shape every existing endpoint already emitted
(`active`, `phase`, `current`, `total`, `message`).

**Frontend.** `_progressCheckTick` in `app.js` swapped its
`Promise.all([...9])` for a single `API.getAllPollProgress()` call.
On failure, one `.catch` returns `{}` and every platform slot
falls through to null — the bar stays hidden and the console
stays clean. Same active/idle interval logic; same aggregation.

Per-platform endpoints stay alive — they're still fetched
individually by the per-platform dashboard pages and any external
monitoring scripts. Backwards compatible.

Net effect: 11×/min → 1×/min idle, 50×/min → 5×/min during a
sync (3.5 minutes of sustained polling on FA + IB easily eats
2k requests over a day; this drops it by 88%).

---

## [2.16.8] - 2026-05-02

### Backlog cleanup — three drive-by fixes from HANDOFF

Three small wins that had been sitting in the open-bugs list since
the round-2 prod live-monitor.

**SameSite=Strict cookie quirk → lax.** The prod live-monitor
caught a recurring 30s pattern: 9 successful polling-progress ticks,
then the next tick fails entirely (9× 401 + sometimes a real SPA
fetch like `/api/settings/preferences` also 401), then immediately
recovers. Each burst opened fresh TCP connections (different source
ports), pointing at the browser dropping the session cookie under
specific idle/refresh conditions — a known SameSite=Strict quirk.
Strict was never load-bearing here: dashboard is HttpOnly + only
JSON-only state-change endpoints, so CSRF surface is already
closed by the cookie format. Switched to `samesite="lax"` in
`routes/dashboard_auth.py:132`.

**Favicon 401 noise.** `/favicon.ico` returned 401 because the auth
middleware (`dashboard.py:197-203`) didn't exempt it. Browsers
fetch favicons without auth context on every page, so every
unauthenticated page load spammed the console. Added to
`_AUTH_EXEMPT_PATHS`.

**`/api/health` exposes version.** Was `{"status": "ok"}` with no
version — monitoring and CI couldn't confirm a deploy had actually
rolled out without scraping the dashboard HTML. Now returns
`{"status": "ok", "version": config.APP_VERSION}`.

### Housekeeping

`docs/HANDOFF.md` was stuck on 2.16.3 — bumped the header to 2.16.8
and added the mobile-mode work (Phase 5 calibration sweep + 2.16.4
CSP hash fix + 2.16.5 page header / stats grid + 2.16.6 page-header
wrap + 2.16.7 sizing+tabs+main clamp) to the "What's working live"
table, plus marked BUG-011 / SameSite-quirk / favicon-401 as fixed
in the open-bugs list.

---

## [2.16.7] - 2026-05-02

### Mobile Mode — page-header sizing + tab strip + main clamp

Three layered fixes for the same overflow class — natural intrinsic
content width forcing the document past viewport.

**Page-header circular sizing (the obvious one).**

2.16.6's page-header wrap rule used `width: 100%` on the actions
div, which created a circular sizing dependency: the div asked for
100% of the parent, the parent grew to fit the div's min-content,
and `flex-wrap: wrap` never triggered. Result: the doc still
rendered at 830px wide on a 440px viewport — same overflow as
2.16.5, just with bigger buttons.

Fix: replace `width: 100%` with `flex: 1 1 100%` and add
`min-width: 0`. Flex items default to `min-width: auto` which
refuses to shrink below intrinsic content size — that's what kept
the parent inflated. With `min-width: 0` + flex-basis 100%, the
actions div correctly takes its own flex line at viewport width
and the buttons inside (also given `min-width: 0`) shrink to
50%-3px each.

Also added `box-sizing: border-box` to the actions div as a belt
on top of the suspenders.

**Settings tab strip not constrained.** `.settings-tabs` had
`overflow-x: auto` but no `max-width`, so its natural row width
(General + Appearance + Platforms + Polling + Telegram + ... = 798px)
forced main wide and the scrollbar never engaged. Added
`max-width: 100%` + `min-width: 0` so the container clamps to
viewport and the scroll-x finally activates inside it.

**Main content clamp (defense-in-depth).** Added `max-width: 100vw`
+ `overflow-x: hidden` to `.main-content` on mobile so a future
un-wrapped child can't bust the layout. Individual horizontal
scroll regions (data tables, tab strips) still work inside the
clamp because they have their own `overflow-x: auto`.

---

## [2.16.6] - 2026-05-02

### Mobile Mode — Phase 5 polish from Playwright sweep

Three issues caught while auditing the live dashboard at 440×956
with real data behind a logged-in session.

**Settings page-header overflow (real bug).** The Settings header
holds four action buttons (Save Settings, Poll Now, Full Resync,
Clear Session) inside an inline `<div style="display:flex;gap:8px">`
sibling to the h2. With no `flex-wrap` and no mobile rules
targeting that unclassed div, the row forced the entire document to
~830px on a 440px viewport — every settings card, the tab strip,
the accordion bodies all bled past the right edge. Fix: add
`flex-wrap: wrap` to `.page-header` itself, and a new rule for
`html[data-mobile="1"] .page-header > div` that gives the actions
container `width:100%` plus 50%-flex buttons. Buttons now flow into
two rows of two on mobile and the document collapses back to
viewport width. Same fix benefits any future page-header that picks
up multi-button action clusters.

**Editor toolbar hidden under hamburger.** The editor's
`.editor-toolbar` is a separate component from `.page-header` and
never picked up the +60px hamburger clearance. The "← Stories"
back link was anchored at x=26 — entirely behind the 12-52px
hamburger button. Title rendered as "tories Chosen" instead of
"← Stories Chosen". Added the same
`padding-left: calc(env(safe-area-inset-left, 0px) + 60px)` to
`.editor-toolbar` on mobile.

**Hamburger float shadow (polish).** When the page scrolls, content
slides under the fixed hamburger and visually merges with it even
though the button has its own opaque background. Added a subtle
`box-shadow: 0 2px 6px rgba(0,0,0,0.35)` so it reads as a floating
affordance, like an iOS FAB. Doesn't compete with cards because the
shadow only shows where it overlaps content.

### How this was caught

Re-spun the production SSH tunnel (port 8420), logged in via
Playwright at 440×956 viewport, walked every surface (Overview,
Settings General + Appearance, Editor with a real story, Posting
list + queue + story detail, IB/FA dashboards, Compare).
`document.documentElement.scrollWidth` exposed the Settings
overflow immediately; the editor breadcrumb issue showed up in
the toolbar measurement. Pages that fit (Overview, Posting,
platform dashboards with 2-button headers, Compare) weren't
touched.

---

## [2.16.5] - 2026-05-02

### Mobile Mode — Phase 4 hotfixes

Two layout bugs caught after the CSP fix in 2.16.4 finally let the
mobile rules take effect.

**Page header h2 hidden behind hamburger.** With h2 at x=16 and
hamburger occupying 12-52px, "Overview" rendered as "rview",
"Settings" as "ngs", "Story Editor" as "y Editor". Added
`padding-left: calc(env(safe-area-inset-left, 0px) + 60px)` to
`html[data-mobile="1"] .page-header` so titles always start past
the hamburger's right edge plus 8px breathing room.

**Stats grid stuck at 2 columns.** The dashboard sets
`style="grid-template-columns:repeat(auto-fit,minmax(200px,1fr))"`
inline on the per-platform grid, beating the class-selector mobile
rule. Added `!important` to
`html[data-mobile="1"] .stats-grid { grid-template-columns: 1fr }`
so the inline style is overridden. Now the 11 platform cards stack
1-per-row on portrait phone instead of cramming 2 to a 220px-wide
row.

---

## [2.16.4] - 2026-05-02

### Mobile Mode — CSP hash fix (CRITICAL)

The single bug that made all mobile-mode work from 2.16.0 through
2.16.3 invisible.

When 2.16.0 extended the inline boot script in `index.html` to
resolve `data-mobile` from localStorage, the script's SHA-256 hash
changed but `dashboard.py`'s CSP `script-src` whitelist still held
the old hash from before the extension. Browsers silently blocked
the boot script, `data-mobile` was never set, and every mobile rule
written against `html[data-mobile="1"]` selector was dead CSS.
Users only saw legacy `@media (max-width: 768px)` rules, which is
why "better but not 100%" feedback persisted across four releases.

Fix: updated the CSP hash in `dashboard.py` to
`'sha256-WudoxBejEmzS4SXsQBia7rsNZctlaFiey3RvF0r8SzA='` (the
browser console helpfully prints the expected hash on each block).

Caught by re-running Playwright against the production CSP and
checking `document.documentElement.dataset.mobile` — it was empty
where it should have been "1". Lesson: any inline script change
must update the CSP hash in lockstep.

---

## [2.16.3] - 2026-05-02

### Mobile Mode — Phase 4 Pro Max calibration

The earlier passes optimised for "small phone, save every pixel"
which left a 6.9" 440×956 viewport feeling sparse and undersized.
This pass calibrates sizing for an iPhone 16 Pro Max-class screen.

**Base + heading scale.** Body 14→15px, line-height 1.5. Page
header h2 17→20px. Headings step up consistently — h3 16, h4 14.

**Buttons.** Generic `.btn` 44px min-height, 14px font. Primary
actions (Save, Metadata-save, Re-check) 48px min-height with 600
weight — they read as the obvious "do this" buttons. `.btn-sm`
40px. iOS HIG minimum is 44px; 48px on primaries gives the
"clearly tappable" feel a 6.9" screen rewards.

**Padding.** `.main-content` 12→16px (cards stop kissing the
viewport edges). `.settings-section` 14→16px. `.settings-accordion
summary` 48→52px tall.

**Stat cards** stay 1-col strips but bump to 56px min-height,
24px value, 13px label. Reads as a substantial section divider
rather than a floaty pill.

**Detail page**: thumb max-width 240→280px. Title 18→22px.

**Submission cards**: 1-col with 240px thumbs (was 200px). Title
14→15px.

**Search/filter inputs**: 44→48px tall, 12-14px padding.

**Bottom nav**: total height +6px so icon+label both fit
comfortably; icon 22px, label 11px.

**Editor mobile tabs** (Edit/Rich/Format/Preview): 44px tall,
18px padding — feel like switcher tabs, not chips.

**Anchor toolbar**: button min-width 48px, anchor labels 0.85rem
(up from 0.78).

**Publish-check chapter cards**: summary row 56px tall, 15px
title; per-platform rows 52px tall.

**Theme picker / mobile-mode picker**: 16px card padding, 15px
name, 13px desc.

**Sidebar (when slid open)**: nav links 48px tall, 15px font;
section headings 11px; overall sidebar slightly wider —
`min(320px, 88vw)` (was `min(300px, 85vw)`).

### What this DOESN'T change

- Layout direction (still vertical from P3)
- Mobile-mode toggle (still in Settings → Appearance)
- Editor toolbar collapse (still ⋯ More from P2)
- The legacy `@media (max-width: 480px)` rules (still cover their
  small-phone baseline; this pass overrides them at higher
  specificity for mobile-mode users)

If sizing still feels off on a specific surface, point at it and
I'll target it directly — the new block is at the very end of
`editor.css` for easy iteration.

### Files touched

`config.py` (APP_VERSION → 2.16.3),
`frontend/css/editor.css` (Phase 4 calibration block at end —
~190 lines covering body/heading scale, button heights, padding,
stat/detail/submission card sizing, search inputs, bottom nav,
editor tabs, anchor toolbar, publish-check, theme/mobile-mode
pickers, sidebar dimensions),
`CHANGELOG.md`.

---

## [2.16.2] - 2026-05-02

### Mobile Mode — Phase 3 vertical sweep

User feedback: "anything that is currently wide screen should be
turned into a vertical version." This pass forces every multi-column
grid to a single column and every horizontal flex strip to a vertical
stack on mobile. Most of the targets had a `@media (max-width: 480px)`
override already; mirroring them under `html[data-mobile="1"]` makes
them fire consistently in mobile mode (including forced-on at
desktop widths) and bumps the threshold from "small phone" to "any
mobile resolution".

**Grids forced to 1 column on mobile.** `growth-grid` (was 3-col),
`goal-grid` (was 260px-min auto-fit), `card-grid` (story list, was
280px-min), `story-card-grid` (was 300px-min), `tag-browser-grid`
(was 240px-min), `chart-row` (was 1fr 1fr), `theme-picker` and
`mobile-mode-picker` (were 220px-min auto-fill — barely fit one
card at 430px anyway, now explicit), `fa-metadata` (was 140px-min,
3 cols on a 430px viewport), `setup-platforms` (was 130px-min, 3
cramped cols).

**Detail page header → vertical.** 120px square thumb on top
(centered, max-width 240px, aspect-ratio 1), title + meta below.
`detail-stats` becomes a vertical list of label-left/value-right
strips with their own surface — easier to scan on a phone than the
horizontal stat row.

**Pinned row → vertical stack.** Was a horizontal scroll-snap
strip of 200px-wide cards; on a phone the user had to swipe through
each card and could only see one at a time. Vertical stack shows
all pinned items in one scroll.

**Compare select chips → vertical full-width buttons** at 44px-min.
The compare-page main two-panel side-by-side flow is intentionally
hard to render vertically and stays as-is for v1; future tab switch
between left/right targets.

**Date range bar wraps in 3-up rows.** Was a tight horizontal flex
where each button got squeezed to ~50px and the labels wrapped
inside. Now wraps into multiple rows with each button at ≥60px,
labels stay readable.

**Settings tabs scroll horizontally with snap.** Were already
overflow-x via the 768 rule; this pass adds `scroll-snap-type: x
proximity` and 44px-min tap targets. Settings rows stack their
toggle-switch right-aligned beneath the label.

**Timeline / log rows → single column.** Already 1fr at 480px;
mirror under data-mobile so the mobile-mode forced-on case behaves.

**Tighter padding everywhere.** `.main-content` 12px + bottom-nav
clearance, `.settings-section` 14px, `.settings-accordion summary`
48px touch height + 14px font.

**Generic safety net for tables.** Any `.data-table` not opted into
the `[data-mobile-cards]` transformation gets `overflow-x: auto`
on mobile so an unconverted table doesn't burst the viewport.

### Surfaces NOT changed in this pass

- Bottom nav (intentionally 5-item horizontal — that's the pattern)
- Editor mobile tab bar (intentionally 4-tab horizontal switcher)
- Anchor toolbar (intentionally 13-button horizontal swipe strip)
- Compare page side-by-side panels (would need a tab switcher;
  out of scope for v1)
- Submission card grid (already 1-col with 200px thumbs from P2)
- Stat cards (already 1-col strips from P2)
- Editor toolbar (handled via P2 ⋯ More collapse)

### Files touched

`config.py` (APP_VERSION → 2.16.2),
`frontend/css/editor.css` (Phase 3 block at end of mobile-mode
section: ~165 lines covering all the grid → 1-col rules,
detail-header vertical, pinned-row stack, compare/date-range/
fave/comment/timeline/log/settings adjustments),
`CHANGELOG.md`.

---

## [2.16.1] - 2026-05-02

### Mobile Mode — Phase 2 portrait-phone polish

Follow-up to 2.16.0 after a real device pass. Phase 1 closed the
worst breakages but the layout still felt cramped in iPhone Plus
portrait. Six targeted fixes.

**iOS input zoom (P2.A).** Every `<input>`, `<select>`, `<textarea>`,
`.search-input`, and `.filter-select` now floors at 16px on mobile.
iOS Safari auto-zooms when a focused input has font-size < 16px and
never zooms back (the fix isn't on focus, it's on `blur`, which iOS
doesn't honour). The 2.16.0 contenteditable fix already covered the
WYSIWYG; this catches everything else — credential fields, search
boxes, settings inputs, the chapter-nav select. `text-size-adjust:
100%` added to `<html>` so OS-level scaling doesn't second-guess us.

**Editor toolbar collapse (P2.B).** The toolbar had 12+ children
(back, title, chapter dropdown, slop/status/wordcount, Save,
Metadata, CSS, Regenerate ▾, Publish, Format, 4 format tabs) which
wrapped into 3-4 ugly rows on a 430px viewport. Wrapped the
secondary cluster in `.editor-actions-secondary` and added a `⋯`
More button visible only on mobile. Toolbar stays one row (back /
title / ⋯ / Save / Metadata); the secondary cluster slides in below
when the user taps `⋯`. Outside-click closes. Title gets ellipsis
truncation so long story names don't push the primary buttons
off-screen.

**Bottom nav swap Analytics → Editor (P2.C).** The Editor is one
of the heaviest-used surfaces and was only reachable via sidebar →
scroll → tap. Bottom nav now shows Overview / Platforms / Upload /
**Editor** / Settings. Analytics remains in the sidebar (Tools
section).

**Stat cards 1-col strips on portrait (P2.D).** Existing 480px
breakpoint was 2-col with values cramped in. Mobile mode now stacks
cards vertically as horizontal strips: label left, value right, one
short row per stat. Eight stats become eight short rows instead of
four tall card pairs — less scrolling, more legible.

**Page header tighten + 16px form controls (P2.E).** `.page-header
h2` drops to 17px, `margin-bottom` from 24px to 12px. `.toolbar`
gap from 8px to 6px. Search/filter inputs get min-height: 44px
explicitly so they're tappable and clear of safe-area junk.

**Modal full-screen on mobile (P2.F).** Chart-modal and
platform-grid both went from centred dialogs (with 24px / 5vw
insets) to edge-to-edge sheets respecting `env(safe-area-inset-*)`.
Chart legends were getting cropped in the centred 90vh dialog;
full-screen gives them room. Platform-grid drops from 3-col to
2-col with bigger 96px-min cards.

**Bonus: submission-card grid → 1-col on portrait** with 200px-tall
thumbnails (was 2-col with 120px-tall thumbs at the 480px
breakpoint, too small to read titles).

### Files touched

`config.py` (APP_VERSION → 2.16.1),
`frontend/index.html` (bottom nav: Editor replaces Analytics),
`frontend/js/editor.js` (toolbar HTML wraps secondary cluster +
adds ⋯ More button; click bindings + outside-click close),
`frontend/css/editor.css` (Phase 2 block at end of mobile-mode
section: iOS 16px, stat-card strip, page-header tighten, sub-card
1-col, chart-modal + platform-grid full-screen, editor-toolbar
collapse with .actions-open class),
`CHANGELOG.md`.

### What's NOT fixed in 2.16.1

Phase 2 deferred items — all judged lower-impact than the six above:
metadata drawer accordion-collapse, sidebar search, format-tabs
"More ▾" overflow when `actions-open` (currently wraps OK), CSS
editor mobile UX (the 5th-tab works but theme-row layout is desktop-
sized), per-platform dashboard pages haven't had a portrait audit.

The legacy `@media (max-width: 768px)` rules still drive a chunk of
the mobile UX. `mobile_mode = "always_on"` on a wide desktop fires
the new `[data-mobile="1"]` rules but not the legacy ones — the two
sets aren't unified yet. Refactor pass deferred until the new rules
have stabilised.

---

## [2.16.0] - 2026-05-02

### Mobile Mode — Phase 0 + 1

A real mobile interface for the dashboard, prompted by the iPhone 16
Plus Pro experience. Existing media queries handled the broad strokes
(hamburger, slide-in sidebar, bottom nav, table → card transformation),
but the editor was unusable below ~600px and several touch interactions
fought the user. This release closes the worst gaps and adds a
Settings → Appearance toggle to let any device opt in or out.

**The toggle.** New `mobile_mode` preference under Settings →
Appearance with three options: **Auto** (default — follows
`(max-width: 768px)` via `matchMedia`), **Always on** (force the
mobile interface on every device — useful for testing or for users
who'd rather have the touch-first layout on a tablet), and **Always
off** (best-effort: keep the desktop UX even on a phone; existing
legacy media queries still fire on small viewports). Persisted to
`settings.json` and synced across devices via the existing 7c
auto-sync. Resolved at boot via the inline `<head>` script — no
flash of the wrong layout. Single source of truth: `<html
data-mobile="0|1">`. A `matchMedia` listener keeps `auto` in sync
when the user rotates the phone or resizes the window.

**Editor → single-panel switcher (P1.1).** The 4-pane quad layout
(MD source / Rich editor / Format source / Format preview) collapsed
to a 2×2 grid below 1200px and stopped — at 430px each pane was
~200px wide, CodeMirror unusable. Mobile mode now shows a tab bar
above the quad with 4 buttons (Edit / Rich / Format / Preview); only
the active panel is visible, the rest stay mounted in the DOM so
CodeMirror state, contenteditable selection, and saved scroll
positions survive switches. Picking a format (Clean HTML / SoFurry /
BBCode / Styled) auto-jumps to the Format panel. Toggling the CSS
theme editor adds a 5th tab dynamically and removes it when closed.
The per-panel eye-icon hide-toggles are suppressed — meaningless in
single-panel mode.

**Anchor toolbar → horizontal swipe strip (P1.2).** The 13 buttons
(undo/redo, B/I, H1, HR, T/Sub/By, ⚠/Disc/FF, Body, →Sent/←Recv/
☎Phone) used to crowd a narrow row at 28px-min-width. On mobile
they're now 44px touch targets in a horizontal scroll strip with
subtle right-edge mask-fade so the user knows there's more.
Scroll-snap proximity keeps the snapping gentle.

**Publish-check matrix → expandable chapter cards (P1.3).** The
chapter × 11-platform table is meaningless on a 430px viewport.
Mobile mode renders each chapter as a `<details>` card with a status
summary (e.g. "5✓ 1↑ 2🔒") visible in the closed state and a
vertical platform list when expanded — each platform inline with
icon + name + status label. Cell-click handler unchanged (same
`.publish-check-cell` class with `data-cell` attribute). Detail
panel scrolls into view on tap. Modal goes full-screen instead of
the desktop's 5vw inset.

**Sidebar `:hover` lockout for touch (P1.4).** The icon rail
expanded-on-hover from 60px → 220px, but on touch devices the
synthetic-hover from a tap latched the panel open until the user
tapped elsewhere. Felt broken on iOS. All `:hover` rules in the
sidebar block now sit inside `@media (hover: hover)`; the
`.expanded` class still works everywhere as a JS-driven escape
hatch. Touch users open the sidebar via the hamburger and close it
via the backdrop, no surprise expansions.

**Safe-area-inset-top (P1.5).** iPhone 16 Plus Dynamic Island sits
at top-center; the hamburger at `top: 12px` was clipping behind it
in some orientations and the global poll-progress-bar rendered
underneath the notch. Both now respect `env(safe-area-inset-top)`.
Sidebar header (when the panel slides open on mobile) also gets
top + left safe-area padding so the title clears the notch on
landscape phones.

**Publish-check modal backdrop mount-window guard (P1.6).**
The 2.14.10 metadata-drawer fix (mobile fires a synthetic click
~300ms after touchend on whatever element is under the finger; if
that's a backdrop mounted synchronously inside the open-button
handler, the modal closes the instant it opens) was flagged as
"likely vulnerable" for the publish-check modal too. Confirmed real,
fixed with the same 400ms-since-`open()` guard on the backdrop click
handler. The publish-check modal is mounted once at first use, so
the gate keys off `_openedAt` (updated each `open()` call) rather
than mount time.

**Out of scope for this release.** Phase 2 polish (metadata drawer
accordion-collapse, format-tabs `More ▾` overflow, theme picker
2-col mobile grid, bottom nav editor entry, CodeMirror
`autocorrect=off`, sidebar search) and Phase 3 nice-to-haves
(pull-to-refresh, swipe gestures, FAB) are scoped for follow-up
releases. Roadmap-stale items (`docs/ROADMAP_PUBLIC.md` still says
"Current version: 2.13.8") were not touched here.

### Files touched

`config.py` (APP_VERSION → 2.16.0),
`routes/api.py` (mobile_mode added to GET/POST `/settings/preferences`
with whitelist),
`frontend/index.html` (boot script extended to apply `data-mobile`
synchronously),
`frontend/js/app.js` (MOBILE_MODES catalog, `applyMobileMode`,
`_resolveMobile`, `_initMobileModeWatcher`, Settings → Appearance UI
section + click/keydown handlers, `_refreshPrefsFromServer` extended
to pull `mobile_mode` cross-device),
`frontend/js/editor.js` (mobile tab bar HTML, `setMobileActivePanel`
helper, format-tab → fmt-source auto-jump, CSS-editor 5th-tab
add/remove, `_updateGridColumns` mobile no-op),
`frontend/js/publish_check.js` (`_renderDesktopMatrix`,
`_renderMobileMatrix`, `_renderMobileCell`, `_countActionable`
factored out; cell-click bind walks `[data-ch-idx]` ancestor; backdrop
guard via `_openedAt`),
`frontend/css/tokens.css` (mobile-mode picker card styles),
`frontend/css/layout.css` (sidebar `:hover` rules split + gated by
`(hover: hover)`; hamburger + sidebar header safe-area-inset-top/left),
`frontend/css/components.css` (poll-progress-bar safe-area-inset-top),
`frontend/css/editor.css` (large mobile-mode block at end —
anchor toolbar 44px touch targets + scroll-snap + edge-fade,
editor-quad 1-column override, mobile tab bar styles, publish-check
modal full-screen on mobile, mobile chapter cards, full-width detail
panel),
`CHANGELOG.md`,
`docs/HANDOFF.md` (TODO: bump version + open-roadmap note).

---

## [2.15.0] - 2026-05-02

### Per-platform tag tabs for FA + Weasyl + AO3 + SquidgeWorld

The editor's Per-Platform Tags section grew four new tabs alongside
the existing Default / SoFurry / Inkbunny / Wattpad. Each new tab
inherits from Default on first load, then becomes its own override
list once the user edits — useful when one platform's limit forces
a smaller set than the others can tolerate.

The trigger was Tombstone: 91 default tags serialise to an 814-char
keyword string, which the FA validator rejects (`furaffinity.py:227-228`,
500-char ceiling). Pruning the default list to fit FA punishes the
other platforms, which happily take the longer set. With per-platform
tabs the user can keep the rich default for IB/SF/Weasyl and ship a
trimmed FA list — no compromise.

**FA tab gets a second counter.** The standard "X tags · Platform max:
Y" line now also shows "X / 500 chars" when the FA tab is active,
turning red once the joined keyword string exceeds the validator's
limit. Catches the over-limit case before save.

**Populate from Default button.** Stories whose `story.json` predates
these tabs (Tombstone, anything older than this release) won't have
`tags.furaffinity` / `tags.weasyl` / `tags.ao3` / `tags.squidgeworld`
namespaces. When such a tab is empty AND Default has tags, a
"Populate from Default (N)" button appears. One click copies every
default tag in (transformed for the platform — underscores for FA /
Weasyl, spaces for AO3 / SQW). Once populated, the user can trim
freely. New stories don't need this — the existing
`TAG_CASCADE_PLATFORMS` keeps every platform in sync automatically as
the user edits Default.

**No backend changes.** `posting/story_reader.py:395-405` already
respects per-platform overrides correctly in the JSON path — the
default cascade only fills in platforms whose namespace is missing.
The legacy txt parser at line 799 still has the blind cascade but no
live story exercises it; that path is parsed once and replaced with
`story.json` on first save.

Per-chapter tag tabs (`_CHAPTER_TAG_PLATFORMS`) intentionally not
extended in this release — chapter-level overrides for FA/Weasyl/AO3/
SQW can land in a follow-up once the story-level UX has soaked.

### Files touched

`config.py` (APP_VERSION → 2.15.0, minor bump because this is a new
feature surface),
`frontend/js/metadata_editor.js` (`TAG_PLATFORMS` extended,
`TAG_LIMITS` + `PLATFORM_LABELS` updated, FA-specific char counter,
"Populate from Default" button + `_populateFromDefault` handler with
underscore-canonicalisation guard for default lists that contain
spaces),
`frontend/css/editor.css` (`.metadata-tag-populate` spacing),
`CHANGELOG.md`,
`docs/HANDOFF.md` (per-platform tag bullet marked done).

---

## [2.14.10] - 2026-05-02

### Metadata drawer no longer self-closes on mobile (BUG-023)

Tapping the Editor's **Metadata** button on a touch device opened the
drawer for ~300ms then immediately closed it. Cause: the backdrop
(`position: fixed; inset: 0`) is mounted synchronously inside the
button's click handler, so the moment the drawer opens the backdrop
is sitting under the user's finger. Mobile then fires a synthetic
click ~300ms after touchend on whatever element is currently under
the touch point — which is now the backdrop, not the button — and
the backdrop's `close()` handler runs.

Fixed in `metadata_editor.js` by gating the backdrop click handler
with a 400ms mount window. Clicks during that window are ignored, so
the synthetic click can't close the drawer it just opened. Real
backdrop clicks (the user deliberately tapping outside the drawer)
still close it as expected.

The publish-check modal uses the same backdrop pattern and is likely
vulnerable to the same issue, but the symptom is masked there because
the user has to do at least one more interaction (cell select →
button click) before any backdrop dismissal could fire. Worth a
follow-up audit pass.

### Files touched

`config.py` (APP_VERSION → 2.14.10),
`frontend/js/metadata_editor.js` (mount-window guard on backdrop
click),
`CHANGELOG.md`.

---

## [2.14.9] - 2026-05-02

### Draft detection in the publish-check matrix (FA-only first slice)

Adds a "Check drafts" probe to the publish-check modal. For every posted
publication on this story, the app pings the platform to ask "is this
sitting as a draft, or is it live?" and overlays the result on the
matrix. A new `posted_draft` cell status renders with a dashed amber
border and a `✎` icon; clicking the cell exposes a "Publish draft (move
out of Scraps)" action that flips the submission live in one round-trip.

This release ships the FA implementation only. FA has no real drafts —
**Scraps** is the closest equivalent (hidden from gallery / browse /
search, but still on the profile + visible to watchers + reachable via
direct link), so the probe reads the scrap checkbox on
`/controls/submissions/changeinfo/{id}/`. IB / SF / AO3 / SQW use
different mechanisms and will land in follow-up work — they cleanly
opt out via the new `probe_draft_state()` returning `None` on the base
class.

**`edit_submission` now preserves the scrap state instead of clearing
it.** Latent bug: the previous edit form POST omitted the `scrap`
field on every metadata edit, which would silently un-scrap any
scrapped submission the moment you tweaked its tags or title. Added a
`scrap: bool | None = None` parameter — `None` = read the current
checkbox state from the form and re-emit it, `True`/`False` = explicit
override. The new "Publish draft" action calls edit with
`scrap=False`.

**New endpoints.** `POST /api/editor/stories/{name}/probe-drafts`
mirrors the existing `/verify` endpoint but probes draft state instead
of deletion state — same 0.4s rate limit between probes, same
not-implemented opt-out, no DB writes (the frontend overlays results
in-memory on cell `dataset.cell` blobs). The `/publish` endpoint
accepts a new `action='publish_draft'` that bypasses the full
post/update pipeline and just calls `poster.publish_draft(external_id)`
— since we're flipping a visibility flag, not pushing new content.

### Files touched

`config.py` (APP_VERSION → 2.14.9),
`clients/fa/client.py` (scrap checkbox parsing in `edit_submission`,
new `probe_scrap_state` method),
`posting/platforms/base.py` (`probe_draft_state` default-None hook),
`posting/platforms/furaffinity.py` (`probe_draft_state` + `publish_draft`
implementations),
`routes/editor_api.py` (`/probe-drafts` endpoint, `publish_draft`
action on `/publish`),
`frontend/js/publish_check.js` (new status, "Check drafts" footer
button, overlay logic, "Publish draft" action button, confirm dialog),
`frontend/css/editor.css` (`.cell-posted-draft`, `.stat-draft`),
`CHANGELOG.md`,
`docs/HANDOFF.md` (FA portion of draft-detection bullet marked done).

---

## [2.14.8] - 2026-05-01

### Round-2 QA bug-fix sweep

Two P1s caught in the second automated Playwright pass against the
2.14.7 test container, plus a couple of structural notes from a
read-only sweep against the live GCP instance (still on 2.14.6 —
2.14.7 hasn't shipped yet, this releases as 2.14.8 instead).

**Mobile hamburger button no longer off-screen (BUG-010).** The
hamburger lived inside `.sidebar > .sidebar-header`, but the sidebar
slides off-screen on mobile via `transform: translateX(-100%)` —
which took the hamburger with it. Adding `position: fixed` to the
button alone didn't fix it, because a fixed-position descendant of a
transformed ancestor gets re-anchored to that ancestor's containing
block (a well-known CSS quirk with `transform`). Moved the button
out of `.sidebar` to be a top-level child of `<body>`, so its
`position: fixed` now correctly anchors to the viewport. New
`body.sidebar-open` class shifts the button to `left: 240px` when
the panel is open, so it's still tappable as a close affordance
above the open sidebar instead of being hidden behind it. Mobile
users on every viewport ≤768px previously had no way to open the
nav at all.

**Create New Story returns a clean 400 instead of an unhandled 500
(BUG-019).** `POST /api/editor/stories/create` was calling
`mkdir(parents=True, exist_ok=True)` against the configured archive
path without first checking whether the path was reachable. On a
fresh server install where `posting_story_archive_path` defaulted to
the host-specific `/m_x` (which doesn't exist in the container), the
mkdir raised `FileNotFoundError`/`PermissionError` and FastAPI's
default handler returned a bare 500 with no detail. The frontend
catch block tried to render `data.detail` but got an empty/non-JSON
response. Now the endpoint pre-validates the archive root: it tries
to create it (treating missing intermediate dirs as the user's
intent), then explicitly checks `os.access(W_OK)`. On failure it
returns 400 with a structured detail message pointing the user to
Settings → General → Posting Settings. The frontend's existing
`!resp.ok → throw → catch → display in errEl` chain now surfaces
that message correctly.

### Files touched

`config.py` (APP_VERSION bump to 2.14.8),
`frontend/index.html` (hamburger out of sidebar),
`frontend/css/layout.css` (mobile media query for fixed-position hamburger),
`frontend/js/app.js` (`body.sidebar-open` class toggle in
open/closeSidebar),
`routes/editor_api.py` (archive path validation before mkdir),
`CHANGELOG.md`,
`docs/HANDOFF.md`,
`qa/AUTOMATED_BUG_LOG.md` (Round-2 findings),
`qa/TESTING_CHECKLIST_WEBAPP.html` and
`qa/TESTING_CHECKLIST_NATIVE.html` (version bump + regression tests).

### What's NOT fixed in 2.14.8

Round-2 QA also surfaced these P2/P3 items, deferred to a future
release:

- **BUG-021 [P2]** — IB Submissions search filter is non-functional
  on production (the textbox accepts input but doesn't filter the
  card grid). Already-rendered table view still sorts; only the
  card view's search is broken.
- **BUG-020 [P2]** — Editor "Regenerate ▾ → All formats" silently
  skips Styled HTML, SquidgeWorld, PDF, and chapter splits without
  reporting which were skipped. Endpoint returns 200 even though
  it's only generated 3 of the 7 expected outputs.
- **BUG-016 [P3]** — Progress-check ticker fan-out spams the
  console with 9-10 stack traces on a single network blip.
- **BUG-018 [P3]** — Checklist §17 Goals + §18 Tags reference
  standalone pages that don't exist; both features actually live
  inside per-platform dashboards / metadata drawer. Checklist
  needs editing, code is fine.
- **BUG-011, BUG-013, BUG-014, BUG-015, BUG-017** — Cosmetic /
  workflow notes documented in `qa/AUTOMATED_BUG_LOG.md`.

**BUG-022 retracted** — original report was a false positive from
the automated QA: the test was matching the word "Platforms" inside
the metadata drawer's own "Per-Platform Tags" / "Platform Toggles"
section headings and mistakenly concluding that the Platforms
popover had opened. User-confirmed via screenshot — the Metadata
button works correctly on both 2.14.6 and 2.14.8.

---

## [2.14.7] - 2026-04-28

### Automated-QA bug-fix sweep on top of 2.14.6

Nine issues surfaced in the first automated Playwright pass against the
server-runtime test container (`docker-compose.test.yml`, port 8421).
None were data-loss bugs but several were UX dead-ends — most painfully
a catch-22 where a fresh server install with no Inkbunny credentials
got stuck on the legacy IB login screen with no way to reach Settings
to configure other platforms.

**Cache-buster keyed off APP_VERSION (BUG-001).** Every CSS/JS reference
in `frontend/index.html` now uses `?v=__APP_VERSION__` and the
`/` route in `dashboard.py` substitutes the running version in at
request time. No more hand-bumped per-file `?v=NNN` numbers — every
release auto-invalidates the browser cache. Result is cached so the
substitution happens once per process. The triggering symptom was
2.14.6 shipping with `app.js?v=311` unchanged from 2.14.5 even though
the wizard code had changed substantially, leaving cached browsers
serving the old JS.

**Plaintext password no longer re-seeds on every restart (BUG-004).**
`config.migrate_dashboard_auth()` now scrubs `dashboard_password` and
`dashboard_user` from `settings.json` even when the bcrypt hash is
already in place. `_seed_settings_from_env()` was re-writing them on
every Docker start from the `DASHBOARD_PASSWORD`/`USER` compose env
vars, leaving plaintext sitting next to the hash and defeating the
whole point of the migration. The bcrypt hash is what auth actually
uses; the plaintext was just a leak.

**CSP unblocked the no-flash theme bootstrap and Google Fonts (BUG-002,
BUG-003).** The inline `<script>` in `index.html` that reads
localStorage and applies the persisted theme before CSS evaluates was
being blocked by `script-src 'self'`. Added the script's sha256 hash
(`'sha256-PQv0iyndH6bqQiLzwEuCSIz1xMcWBsP0swro6kOCiZI='`) to the
directive — keeps `'unsafe-inline'` off but allows just this one
bootstrap. `style-src` and `font-src` now include
`https://fonts.googleapis.com` and `https://fonts.gstatic.com` so the
typography (Crimson Pro / Inter / JetBrains Mono) actually loads.

**IB-login catch-22 broken (BUG-005, BUG-006, BUG-007).** Three bugs,
one root cause: `app.js init()` force-redirected to the legacy
Inkbunny login screen whenever IB credentials were missing — even on
server installs where the user explicitly skipped platforms in the
wizard, even on direct deep-links to `#/settings/general`. Removed the
redirect entirely (the IB login route still exists; it's just no
longer the default landing). Loading screen now keeps a `Continue to
Dashboard` / `Open Settings` escape hatch — visible immediately on
poll error, and after a 10-second safety timeout if the poll stalls.
Wizard "Go to Dashboard" routes to `#/settings/platforms` (not `#/`)
when no platform was configured during setup, so first-time users
land somewhere actionable.

**Sidebar reflow on hover (BUG-008).** The 60px collapsed sidebar
expanded to ~190px on hover but main content didn't move, so the
expanded sidebar overlaid the first column — visible most clearly on
Settings → Appearance where the first theme card was clipped. Added a
`body.sidebar-expanded` class toggled from `mouseenter`/`mouseleave`
listeners on the sidebar, with a matching CSS rule that bumps
`.main-content`'s left margin to `var(--sidebar-w-expanded)` in
lockstep with the sidebar's own width transition. Listeners are now
bound at the very top of `App.init()`, before the dashboard-auth and
setup-wizard early-returns — caught in QA: the original placement was
after those returns, so a fresh user who hit the login screen first
never got the listeners attached for the rest of the session.

**Updater stops WARN-spamming the log (BUG-009).** GitHub returns 404
from `/releases/latest` when the repo has zero published releases —
the legitimate "no release tagged yet" case. Treat it as INFO-once and
return a clean no-update response instead of WARN-logging on every
dashboard load. Distinct from real network failures, which still
deserve a warning.

### Files touched

`config.py`, `dashboard.py`, `updater.py`, `frontend/index.html`,
`frontend/js/app.js`, `frontend/css/layout.css`,
`qa/AUTOMATED_BUG_LOG.md`, `qa/TESTING_CHECKLIST_WEBAPP.html`,
`qa/TESTING_CHECKLIST_NATIVE.html`, `docs/HANDOFF.md`,
`docs/ROADMAP_PUBLIC.md`, `CHANGELOG.md`.

---

## [2.14.6] - 2026-04-28

### Coordinated desktop ↔ server architecture (no more dual polling)

Closes the asynchronicity gap users hit when running the desktop app
alongside the Docker container: both instances were polling on their
own schedules, racing to update the same database, and double-firing
"all polls complete" notifications. Now there is exactly one polling
owner at any time, decided by an explicit `setup_mode` setting.

**Three modes.** The setting takes one of three values:

- `standalone` — desktop runs solo, polls + posts locally. The default
  for fresh installs that pick "Just on this computer" in the wizard.
- `paired_desktop` — desktop runs alongside a remote server. Settings
  flow server → desktop via the existing auto-sync pull, polling is
  delegated to the server, but the desktop still posts (since posting
  reads from the local story archive).
- `server` — the headless Docker container. Always polls. Stamped
  unconditionally on `server.py` startup so the wizard never has to
  ask, and so it can never wander into the standalone branch.

**Polling-owner gate.** `config.get_polling_owner(runtime)` returns
`"local"` if the running process should own the poll loop, `"server"`
if a remote one does. `main.py` reads this on startup; when the answer
is `"server"`, it skips the 11 per-platform poller threads + digest
scheduler entirely. Telegram bot, posting scheduler, and uvicorn still
start (they're independent of polling). The decision is logged at
INFO so you can see at a glance which side is doing the work.

**Wizard rebuilt around mode-first branching.** Desktop installs now
hit a Q1 — "How are you running PawPoller?" — with two cards
("Just on this computer" / "Pair with my server"). The paired branch
collects URL + API key, validates them via a new `/api/settings/pair-test`
endpoint (HTTPS-required for non-localhost; reuses the same rule as the
auto-sync push guard), and triggers an immediate first-pull on success
so the user doesn't wait 5 minutes for their server's settings to land.
Pairing completion sets `auto_sync_enabled = true` and skips the
archive + platform-connection steps — those settings come down with the
sync pull. Server runtime skips Q1 entirely (it's always "server").

**Re-run wizard from Settings.** New "Setup Mode" panel at the top of
the General tab shows the current mode badge + polling-owner status +
remote URL (when paired). A Re-run setup button clears
`setup_complete` and bounces back to `#/setup` so users can flip
between standalone and paired without reinstalling. Hidden on the
server runtime where the mode is fixed.

**Setting scope tagging.** `SYNC_EXCLUDE` expanded to cover
desktop-only fields (`run_on_startup`, `setup_mode`) so they never
leak into the server's settings dump. Three desktop-only preference
rows (`Minimize to tray`, `Start with Windows`, `Desktop notifications`)
are conditionally rendered in Settings — visible on desktop, hidden on
server. Their event handlers all use `?.` in case the runtime mode
changes mid-session.

**`auto_sync` server self-protection.** The push path now refuses to
fire when `setup_mode == "server"`, regardless of what
`posting_server_url` says. Closes a foot-gun where a server with a
stray pairing URL (e.g. accidentally set during testing) would push to
that target on every settings change.

**Why now.** The user flagged duplicate "all polls complete"
notifications and asked us to scope the underlying coordination
problem. This is the resolution: one explicit owner, simple branching
in the wizard, no more racing pollers.

**Files touched.** `config.py` (mode constants, `get_polling_owner`,
expanded `SYNC_EXCLUDE`), `main.py` (gated 11-thread block),
`server.py` (force-set `setup_mode = server` on boot),
`auto_sync.py` (server self-push guard), `routes/settings_api.py`
(`setup-mode`, `pair-test`, `setup-reset` endpoints; richer
`setup-status`), `frontend/js/api.js` (3 new methods),
`frontend/js/app.js` (wizard rebuild + Setup Mode panel + handler
gating), `frontend/css/components.css` (mode-picker cards).

### Update button hidden on server runtime

Follow-up to the scope-tagging pass: the in-app self-update flow only
works on a frozen PyInstaller .exe (Windows-only batch script,
`os.startfile`, `robocopy /MIR /XD data logs`). On the Docker server
the "Update Now" button rendered but clicking it returned a 500 from
the underlying `updater.apply_update()` guard. Now both apply
affordances are hidden when `runtime_mode == "server"`:

- Sidebar "v2.14.x available" banner: button replaced with a small
  "rebuild on host" hint.
- Settings → About "Update Available" panel: button removed, replaced
  with a one-line note pointing at `pawupdate` / `docker compose up
  -d --build`.

The version-check call still runs on both runtimes so admins see at
a glance when there's a newer release upstream — only the apply
button is gated. Cached `this._runtimeMode` after the first
`getSetupStatus` call so the sidebar render stays cheap.

---

## [2.14.5] - 2026-04-27

### Refactor pass — audit-pass debt cleanup

Pure cleanup pass cashing in three of the four refactor candidates
queued in the 2.14.4 audit-pass-debt list. Behaviour-preserving across
the board; 91 tests passing (up from 30 — see below).

**1. `polling/notifications.py` extracted.** ~80 lines of identical
Windows-toast + Telegram-async-post + HTML-escape boilerplate were
duplicated across all 11 platform pollers. Three new helpers capture
the actual duplication:

- `show_toast(title, lines)` — primitive that lazy-imports `winotify`
  and no-ops on Linux/server builds.
- `send_telegram(token, chat_id, text)` — primitive that swallows
  network errors with a warning. Returns ``bool`` so callers with
  follow-up state (e.g. FA's "mark watcher digest delivered" path)
  can branch on success.
- `format_telegram_summary(header_html, items)` — string-builder for
  the `<b>HEADER</b>\n  • item\n  ...and N more` pattern every poller
  was rebuilding by hand.
- Plus two convenience wrappers (`maybe_show_toast`,
  `maybe_send_telegram_summary`) that fold in the per-platform
  enabled-flag check.

**Result:** 489 lines deleted across `polling/{ib,fa,sf,ws,da,ao3,sqw,
bsky,ik,tw,wp}_poller.py`, plus ~150 lines added in the new helper.
Net ~340 lines simpler. Per-platform filters (comments-only,
fave-thresholds, watcher-toggle) stay in their respective pollers
where they belong.

**2. CI test runner switched from `unittest discover` to `pytest`.**
Two of our test modules (`tests/test_integration_posting.py`,
`tests/test_platform_posters.py`) are pytest-style and were silently
skipped by `python -m unittest discover` for ages. The build workflow
now runs `pytest tests/ -v` — and CI suddenly has 91 passing tests
instead of 30. No new failures surfaced; the previously-skipped modules
were green on first run.

**3. N+1 query batching for `get_*_comparison_snapshots`.** Eleven
near-identical functions (`database/queries.py` plus
`{ao3,bsky,da,fa,ik,sf,sqw,tw,wp,ws}_queries.py`) all looped one
`SELECT ... WHERE submission_id = ?` per submission, which the
comparison-chart UI hits with up to ~10 sids at once. Replaced with a
single `SELECT ... WHERE submission_id IN (?,?,?...)` query plus
Python-side group. Same return shape, same key-type-per-platform
quirks (some keep raw int sids, others stringify — preserved
verbatim). Visible perf win on every comparison chart load — was a
~10× wire-time multiplier on a hot read path.

**4. `config.get_settings()` route caching.** The audit flagged this
as duplication "across many routes/*_api.py handlers". Closer reading
showed most apparent duplicates are in *separate* route handlers each
calling once, which is correct. Only `routes/settings_api.py::sync_status`
had a real double-call — the `total_keys` and `credential_mode` fields
each called `get_settings()` independently. Fixed. Other suspect cases
all turned out to be genuine separate-handler calls and were left
alone.

**Validation gates:**

- AST parse: 11 poller files + 11 query files + helper module + config
- Importlib smoke: every refactored module loads
- Test suite: 91/91 pass under pytest (was 30/30 under unittest, with
  61 silently skipped)
- No call-site signatures changed; helper extraction is internal

**`APP_VERSION` bumped to `2.14.5`.**

---

## [2.14.4] - 2026-04-27

### Security & robustness from a self-audit pass

A four-angle audit pass (dead code / security / refactor / reference
rot) surfaced a handful of real issues alongside several false alarms.
This release ships the fixes that were both *real* and *small enough
not to need a focused refactor session*. The bigger refactor candidates
(N+1 query batching across the 11 platforms, per-poller notification
helper extraction, redundant `config.get_settings()` calls) are noted
in HANDOFF for a future pass.

**What changed:**

- **Auto-sync refuses non-HTTPS targets.** `auto_sync._sync_target()`
  now rejects `posting_server_url` values that don't start with
  `https://` for non-localhost hosts. Localhost keeps `http://` because
  the loopback never leaves the machine. Without this guard a user who
  configured a plain `http://my-server.tld:8420` would have been
  posting their `Authorization: Bearer pp_xxx` API key (and the full
  settings dump including platform credentials) over the wire in
  cleartext on every save. Now logs a one-time warning and disables
  sync until the URL is fixed.

- **Auto-sync pull loop now has exponential backoff.** Steady state is
  unchanged at 5 minutes between cycles, BUT consecutive *transport*
  failures (connection refused, timeout, non-200) now back off
  5m → 10m → 20m → 40m → 60m cap instead of hammering an unreachable
  server every 5 minutes forever. Crucial detail: a 200 response that
  says "I have nothing newer for you" — the common case — does NOT
  count as a failure and stays on the regular cadence. Implemented by
  splitting the old `pull_once()` into a richer `_pull_attempt()` that
  returns `(reachable, applied)`; `pull_once()` stays around as a
  backwards-compat shim.

- **Path traversal on `/api/posting/stories/{story_name}` closed.**
  `posting.story_reader.load_story()` previously joined the user-
  supplied `story_name` straight onto the archive root. Because the
  FastAPI route uses the `:path` converter, `..` segments passed
  through unchanged — an authenticated dashboard user could request
  e.g. `/api/posting/stories/../../etc/passwd` and the loader would
  happily try to read it. Adopted the same `Path.resolve()` +
  `relative_to(archive)` guard already in
  `routes/editor_api._resolve_story_dir`, so paths that escape the
  archive root now return a clean 404. Auth-protected endpoint, so
  this was post-auth path-disclosure not unauthenticated, but worth
  closing.

- **`deploy/pawpull.py` argv whitelist.** The deploy helper passes
  `sys.argv[1]` through to `gcloud --command="..."` with `shell=True`,
  with no quoting. A typo or a malicious paste of a story name with
  `;` or `$()` would have run as bash on the GCP VM. Locked the
  argument to `^[A-Za-z0-9_./-]+$`; anything else exits 1 with a
  descriptive error. This is a developer-run script (so attacker =
  you) but the fix is two lines and the next person to grab the
  pattern shouldn't inherit the trap.

- **QA checklists bumped to 2.14.4.** Title strings, hero headers, and
  the three "expected APP_VERSION" / "git tag" example commands in
  both `qa/TESTING_CHECKLIST_WEBAPP.html` and
  `qa/TESTING_CHECKLIST_NATIVE.html`. The historical reference to
  "post-2.14.2 fix" in the theme-persistence test stays as-is — that
  one's pointing at when the bug was fixed, not the current version.

### Audit findings *not* fixed in this release (logged for next pass)

These came up in the audit and are real, but didn't fit the
"small enough to ship between QA runs" bar:

- **Vault key on Windows lacks ACL hardening.** `_secure_file_permissions`
  is a no-op on Windows, so the `.vault_key` dotfile fallback is created
  with default ACLs. Mostly theoretical — keyring almost always works
  on Windows so the dotfile is the rare fallback path — but the proper
  fix wants DPAPI or `icacls`, which isn't a one-liner.

- **`config.py` is ~800 lines mixing paths / vault / auth / logging /
  settings I/O.** Splitting into focused modules is a refactor pass,
  not a fix.

- **N+1 `get_*_comparison_snapshots()` across all 11 `database/*_queries.py`
  files.** Loops one SELECT per submission instead of `WHERE ... IN (...)`.
  Visible perf win on comparison-chart loads, but touching 11 files at
  once is its own commit.

- **Per-poller toast + Telegram notification logic duplicated 11×.** ~80
  lines per platform doing identical work. Worth extracting to
  `polling/notifications.py`, again as its own commit.

**Validation gates:** AST parse + importlib smoke + 30/30 unit tests
pass on the touched modules.

**`APP_VERSION` bumped to `2.14.4`.**

---

## [2.14.3] - 2026-04-27

### Changed — Repository file-tree cleanup (no behaviour changes)

Pure organisation pass — zero runtime changes, just a tidier layout.
The repo root went from ~30 entries (11 of which were platform
client folders) down to ~18.

**Three coordinated changes:**

1. **All 11 platform clients consolidated under `clients/`.**
   - `api_client/` → `clients/ib/` (also fixes the long-standing
     naming inconsistency — the IB client was the only one not using
     the `<xx>_client/` convention)
   - `ao3_client/` → `clients/ao3/`, `bsky_client/` → `clients/bsky/`,
     `da_client/` → `clients/da/`, `fa_client/` → `clients/fa/`,
     `ik_client/` → `clients/ik/`, `sf_client/` → `clients/sf/`,
     `sqw_client/` → `clients/sqw/`, `tw_client/` → `clients/tw/`,
     `weasyl_client/` → `clients/weasyl/`, `wp_client/` → `clients/wp/`
   - Used `git mv` so file history is preserved.
   - 60 Python files had imports rewritten via a single sed pass:
     `from <xx>_client.client import ...` → `from clients.<xx>.client import ...`
     (covers top-level imports, lazy/conditional imports inside
     functions, and 3 docstring references in `tests/test_posting_helpers.py`).
   - Comment/docstring path references in `posting/platforms/*.py`
     and `clients/ao3/client.py` updated for accuracy.
   - PyInstaller spec didn't need updating (no client modules in
     `hiddenimports` — the analysis discovers them via the import graph).
   - Dockerfile didn't need updating (`COPY . .` picks up the new
     layout automatically).

2. **Internal docs moved to `docs/`.**
   - `HANDOFF.md`, `SETUP.md`, `ROADMAP_PUBLIC.md`, `documentation_guide.md`
     → `docs/<same name>`. README, LICENSE, CONTRIBUTING, CHANGELOG
     stay at root for GitHub conventions.
   - Cross-references updated in: `README.md` (3 links),
     `CONTRIBUTING.md` (1 link), `site/src/components/Footer.astro`
     (3 GitHub URLs), `site/src/components/GetIt.astro` (1 URL),
     `docs/HANDOFF.md` (1 backref), `docs/documentation_guide.md`
     (file-tree section refreshed with the new `docs/` and `qa/`
     subtrees).
   - Marketing site needs a redeploy to pick up the URL change in
     the footer + GetIt CTA.

3. **Orphan cleanup.**
   - `112.png` (stray icon export at repo root) — deleted.
   - `TESTING_CHECKLIST.md` (the markdown sibling of the html
     checklist that should have died with the WEBAPP/NATIVE split in
     2.14.2) — deleted.
   - Local `settings.json` at repo root (legacy dev path; config.py
     migrated it to `data/settings.json` once on first run already)
     — deleted from disk; was already gitignored.

**Validation gates run before commit:**

- AST parse: 166 .py files, 0 errors.
- Import smoke: 47 refactored modules import cleanly (every client,
  every poller, every poster, every route, importer, server bits).
- Unit test suite: 30/30 pass.
- PyInstaller build: succeeds end-to-end, dist/PawPoller/PawPoller.exe
  produced.

**`APP_VERSION` bumped to `2.14.3`.**

---

## [2.14.2] - 2026-04-26

### Added — Automatic settings sync across devices

The cloud-sync infrastructure has existed since 2.13.x (the manual
push/pull endpoint at `/api/settings/sync`), but actually using it
required either restarting the desktop app (one-shot pull at boot)
or hitting the API by hand. 2.14.2 closes that loop: every settings
change propagates between devices on its own.

**What changed:**

- **Desktop auto-push.** `config.save_settings()` now schedules a
  debounced (~2s) background push to the cloud server whenever a
  `posting_server_url` + API key is configured. Bursts of saves
  (e.g. flipping five toggles in the wizard) collapse into one HTTP
  request. Fire-and-forget — failures log at debug level and never
  block the save.
- **Desktop periodic auto-pull.** New daemon thread polls the cloud
  server every 5 minutes and merges anything newer than the local
  copy. Last-writer-wins via mtime, so an in-flight push isn't
  immediately stomped by a stale pull. Bootstrapped from `main.py`
  alongside the existing one-shot startup pull.
- **Browser focus refresh.** Tabs now listen for `visibilitychange`
  and re-pull preferences when refocused (throttled to once per 3s).
  So changing the theme in the desktop app causes any open browser
  tab to repaint with the new theme as soon as you switch to it.
- **Loop protection.** A thread-local `_in_pull_merge` flag prevents
  the pull → merge → save → push cascade. Without it, a desktop
  pulling from the server would echo every pulled key back as a push.
- **`auto_sync_enabled` toggle** (default `true`) on **Settings →
  Appearance**, plus exposed through `GET /api/settings/preferences`
  and accepted by the POST handler. Set to `false` to disable both
  push and pull on this device.
- **Bug fix: theme actually persists now.** `applyTheme()` was
  POSTing `{ theme: <id> }` to `/api/settings/preferences`, but the
  server-side handler whitelisted known keys and silently dropped
  `theme`. So the chosen theme was localStorage-only and never made
  it into `settings.json` (and therefore never synced). The handler
  now accepts `theme` against the known THEMES set, so the
  cross-device sync above can actually do its job for the appearance
  setting that motivated this work.

**What's excluded:**

- `credential_mode` (per-device decision — vault vs plaintext)
- `auth_session_secret` (per-device cookie-signing key, must not
  match across devices)
- `minimize_to_tray` (per-device preference)
- Anything resolving to `localhost`/`127.0.0.1` is treated as a
  loopback target and skipped (so the cloud server never tries to
  sync to itself)

**Files touched:** `auto_sync.py` (new), `config.py`, `main.py`,
`routes/api.py`, `frontend/js/app.js`, `frontend/index.html`.
Cache buster on `app.js` bumped to `v=311`.

**`APP_VERSION` bumped to `2.14.2`.**

---

## [2.14.1] - 2026-04-26

### Changed — Vibe Pack: app aesthetic aligned with marketing site

The 2.14.0 themes brought the marketing site's palette into the app
(via Ink & Copper). 2.14.1 closes the rest of the cohesion gap by
borrowing four specific stylistic moves from pawpoller.pages.dev,
without sacrificing dashboard density on work surfaces.

- **Crimson Pro for headings.** All `h1`/`h2`/`h3`, plus page-header
  titles, modal titles, settings-section heads, sidebar wordmark,
  login/setup-step headings now render in Crimson Pro (the same
  serif as the site). Body text, labels, table cells, and buttons
  stay in Inter so dashboard-density screens remain readable.
- **Subtle radial body wash.** The body background is no longer flat
  slate — it gets a faint copper top-left + sage bottom-right
  gradient via two new theme-aware tokens (`--bg-glow-warm`,
  `--bg-glow-cool`). Anchored with `background-attachment: fixed` so
  it doesn't move with scroll. Pure-black themes (Midnight Press,
  High Contrast) opt out by setting both tokens to `transparent`.
- **Refined `.chip` component.** New site-style pill chip with
  optional dot indicator, plus accent/warm/success/warning/danger
  modifiers. Existing badges keep working; new chips going forward
  use this pattern.
- **Brand mark.** Small copper diamond (◆) added next to the
  PawPoller wordmark in the sidebar header, matching the site's nav.
- **Three new font tokens** — `--font-serif` (Crimson Pro fallback
  Georgia), `--font-sans` (Inter fallback system), `--font-mono`
  (JetBrains Mono fallback ui-monospace). Loaded once from Google
  Fonts with `display=swap` so first paint never blocks.

### Notes

- No layout changes on dense work surfaces (publish-check matrix,
  story list, editor, analytics, settings tables). Those keep their
  productivity density — only the *typography* of their headings and
  the ambient body wash shifts.
- Cache busters bumped to `v=310` for tokens / components / layout /
  editor CSS and `app.js`.
- Cohesion score (per the brand audit): bumped from "color-aligned,
  typography-divergent" to "fully cohesive cross-surface family"
  while preserving the marketing-vs-dashboard density distinction.

**`APP_VERSION` bumped to `2.14.1`.**

---

## [2.14.0] - 2026-04-26

### Added — 8-theme picker (browser + native)

PawPoller had `dark` + `light` themes wired up via CSS custom properties
and a binary toggle in the sidebar. Generalised to 8 curated themes,
selectable from a new **Settings → Appearance** tab. Same code applies
in both browser/server mode and the native pywebview desktop app
because both render the same frontend.

**The eight themes:**

| ID | Name | Vibe |
|----|------|------|
| `dark` | Default Dark | Charcoal + violet (existing default) |
| `light` | Default Light | Bright neutral (existing alternative) |
| `ink_copper` | Ink & Copper | Deep slate + copper + parchment text — matches pawpoller.pages.dev |
| `parchment` | Parchment | Warm sepia paper, brown ink — long-session writer mood |
| `midnight_press` | Midnight Press | True black for OLED, cool steel accents |
| `forest` | Forest | Pine + sage + cream — calm, low-stim |
| `velvet` | Velvet | Aubergine + dusty rose + amber |
| `high_contrast` | High Contrast | Pure black/white + saturated yellow (a11y) |

**Implementation:**

- **`frontend/css/tokens.css`** — full rewrite. Each theme is a single
  `[data-theme="<id>"]` block defining ~20 token values. Adding a 9th
  theme = copy block, rename, swap colours. Every UI surface now reads
  from these tokens; no per-theme component overrides needed.
- **Three new adaptive tokens** introduced to clean up old hardcoded
  patterns: `--card-border-inner` (the subtle inset edge on glass
  cards), `--overlay-backdrop` (modal scrims), `--shadow-strong`
  (hover/elevation). Hardcoded `rgba(255,255,255,0.08)`,
  `rgba(0,0,0,0.5)`, etc. in `components.css` / `editor.css` /
  `layout.css` replaced with these tokens so all 8 themes get correct
  contrast automatically.
- **`frontend/js/app.js`** — `THEMES` catalog (8 entries with id, name,
  description, 5-colour preview swatch). `applyTheme(id)` sets
  `data-theme` attribute, persists to localStorage, calls
  `API.savePreferences({theme: id})` (so the choice rides cloud sync
  if enabled), destroys + redraws charts so they pick up new colours.
  Sidebar palette button now navigates to Settings → Appearance instead
  of cycling (8 themes don't fit a binary toggle).
- **Settings → Appearance tab** — card grid (auto-fit 220px columns),
  each card shows a real miniature of the theme's actual colours
  (background, card surface, accent stripe, warm dot, text). Active
  theme has a copper border + "Active" pill. Click or Enter/Space to
  apply.
- **No-flash on load** — inline `<script>` in `index.html` reads
  localStorage and sets `data-theme` BEFORE the CSS link tags evaluate.
  The page never paints in the wrong theme.
- **Cache busters** bumped: tokens / components / layout / editor CSS
  to `v=300`, `app.js` to `v=300`.

**`APP_VERSION` bumped to `2.14.0`.**

---

## [2.13.9] - 2026-04-25

### Fixed — server startup crash when vault mode is on

`config.py`'s module-level `_settings = _load_settings()` ran at import
time, and `_load_settings` calls `_decrypt_vault()` whenever
`settings.json` has `credential_mode: "local"`. But `_decrypt_vault`
was defined ~300 lines further down, so on any server with vault mode
on, `import config` raised `NameError: name '_decrypt_vault' is not
defined` before the app could even start. The desktop was unaffected
because its settings.json defaults to `credential_mode: "cloud"`.

This hit us on the GCP deploy — server had vault enabled from an
earlier QA session and crash-looped on startup after the 2.13.1+ push.

Fix: moved the vault block (`VAULT_PATH`, `_get_vault_key`,
`_encrypt_vault`, `_decrypt_vault`) above `_load_settings` so all
helpers are defined before the module-level init runs. Left a comment
explaining the ordering constraint so nobody moves them back.

**`APP_VERSION` bumped to `2.13.9`.**

---

## [2.13.8] - 2026-04-24

### Changed — Anchor toolbar tweaks

- Inline semantic anchor buttons (text-sent / text-received /
  phone-incoming) now carry text labels alongside the Unicode icon:
  `→ Sent`, `← Recv`, `☎ Phone`. The bare arrows/phone glyph from
  2.13.7 rendered small inside Chromium's embedded webview and
  blended into the separators, making the buttons easy to miss.
- Hover tooltip delay dropped from 2000ms to 1200ms so the before/
  after hint shows up without feeling like it's lagging.
- Cache buster: `editor.js?v=285`.

**`APP_VERSION` bumped to `2.13.8`.**

### CI — release pipeline fixes (2026-04-25)

The first v2.13.8 tag push triggered a Build & Release run where the
`test` job failed with `ModuleNotFoundError` on four test modules.
Pre-existing issue: `requirements-server.txt` never pinned the test
dependencies. Windows build succeeded either way, so the release
artifact was fine — but the red X on the tag was misleading. Fixed
by pinning `pytest~=8.3` and `respx~=0.22` in
`requirements-server.txt`, then force-moving the `v2.13.8` tag to the
CI-fix commit. Final tag points at `7517ad3`; all jobs green.

Known latent issue: `test_integration_posting` and
`test_platform_posters` are pytest-style (async fixtures + respx) and
are silently skipped by `python -m unittest discover` — they import
cleanly but contribute no `TestCase` subclasses. Switching the CI
command to `pytest` would actually execute them. Not urgent, not a
regression.

---

## [2.13.7] - 2026-04-24

### Changed — Anchor toolbar overhaul: real anchors only, hover tooltips

Audited the editor's anchor toolbar against the canonical
`FILE_FORMAT_STANDARDS.md` spec and `editor/converter.py`. The
toolbar shipped three fake anchors that the converter silently
ignored (`@story-end`, `@text-end`, `@phone-end`), one misspelled
anchor (`@phone` instead of `@phone-incoming`), and was missing
three real front-matter anchors (`@byline`, `@disclaimer`,
`@fanfiction`) that appear in live stories (HC, Chosen, Silk).
The paired-wrap semantics introduced in 2.13.6 for text-sent /
text-received / phone were based on those fake close anchors and
produced output the converter couldn't parse.

- **`frontend/js/editor.js`**: Toolbar now exposes 10 buttons
  grouped by function — Title / Sub / Byline / Warning / Disclaimer
  / FF / Body / → (text-sent) / ← (text-received) / ☎
  (phone-incoming). `@story-end` removed entirely (the real
  end-of-story marker is `*End of [Title]*`, plain italic, not an
  anchor). `_insertAnchor()` rewritten as a single code path: every
  anchor is a single-line label inserted at the start of the line
  containing the cursor/selection, which matches how the converter
  actually reads them.
- **`_ANCHOR_HINTS`**: per-anchor metadata (label, purpose,
  before/after example). Drives the new tooltip.
- **Hover tooltips**: `_initAnchorTooltips()` wires a 2-second
  `mouseenter` timer on every anchor button. After the delay a
  positioned tooltip shows the anchor's purpose and a
  before/after code snippet. Cancelled on `mouseleave` / click.
- **`frontend/css/editor.css`**: `.anchor-tooltip` styles
  (fixed-position panel with dark background, accent label,
  monospace `<pre>` blocks for before/after, green left border on
  the after block).
- Cache busters: `editor.css?v=247`, `editor.js?v=284`.

**`APP_VERSION` bumped to `2.13.7`.**

---

## [2.13.6] - 2026-04-24

### Changed — Anchor toolbar wraps the current selection

Previously the anchor buttons always inserted at the cursor, leaving
the user to manually cut/paste a block of text into the middle of a
newly-inserted paired anchor like `<!-- @phone --> ... <!-- @phone-end -->`.
The buttons now honour the active text selection.

- **Paired anchors** (text-sent, text-received, phone): if text is
  selected, the opening tag is inserted on the line above and the
  closing tag on the line below, with the selected text preserved
  between them and re-selected. With no selection, the existing
  empty-block behaviour is kept.
- **Standalone anchors** (title, subtitle, body, warning, story-end):
  with a selection, the anchor is inserted on its own line
  immediately before the selection (so "make this a chapter title"
  works from a highlight); the selection stays intact. With no
  selection, the anchor is inserted at the cursor as before.
- Selections made in the **Rich Editor** (contenteditable) are
  accepted if the selected plain text appears exactly once in the
  Markdown source — the wrap is then applied to that unique
  occurrence in CodeMirror. Ambiguous matches fall back to
  CodeMirror's own selection.

- **`frontend/js/editor.js`**: `_insertAnchor()` now splits on the
  `\n\n` gap for paired anchors and inserts open/close around the
  selection. Cache buster `editor.js?v=283`.

**`APP_VERSION` bumped to `2.13.6`.**

---

## [2.13.5] - 2026-04-24

### Fixed — Full-bleed print background on Windows (Edge)

The 2.13.4 fix (setting `html { background }` inside `@media print`)
painted the body box to the page edges but Chromium still honoured
the template's top-level `@page { margin: 2cm }`, leaving a thin
white rim around the themed content. The screen-mode template has
its own `@page` for on-screen print-preview parity, so we can't
remove it — but inside `@media print` we can declare a second
`@page` rule that wins by cascade.

- **`editor/converter.py`**: `_build_print_styles()` now prepends
  `@page { margin: 0; size: A4 }` inside the `@media print` block
  for both the colour-preserve and grayscale branches. The visual
  breathing room users expect is preserved by the existing
  `.print-container { padding: 2cm 2.5cm }` inside the same block,
  so only the outer rim changes — full-bleed on Edge, matching the
  WeasyPrint behaviour on the server.

**`APP_VERSION` bumped to `2.13.5`.**

---

## [2.13.4] - 2026-04-24

### Fixed — PDF print CSS on Windows (Edge fallback)

Side-by-side comparison of Edge-rendered (Windows desktop) vs
WeasyPrint-rendered (server / Docker) PDFs showed the Edge output:
- Carried a browser-added header ("DD/MM/YYYY, HH:MM" + title)
  that polluted every page
- Left the page background white in the 2cm `@page` margin so the
  themed body colour was boxed inside a white frame instead of
  running edge-to-edge like the WeasyPrint output

Both are rendering-engine differences that only affect the Chromium
headless fallback used on Windows desktops without WeasyPrint's GTK
runtime — the server path was already correct.

- **`editor/pdf_generator.py`**: Added `--no-pdf-header-footer` to
  the Chromium headless invocation so the date header / URL footer
  are suppressed. Kept `--no-margins` so CSS `@page` remains the
  single source of truth for page geometry.
- **`editor/converter.py`**: `_build_print_styles()` now sets the
  theme background on both `html` and `body` inside `@media print`.
  By default Chromium only paints the body box (inside the `@page`
  margin), leaving a white border on themed stories; painting the
  html element too fills the full printable area so the theme
  background is continuous. WeasyPrint already behaved this way.

**`APP_VERSION` bumped to `2.13.4`.**

---

## [2.13.3] - 2026-04-24

### Changed — Error reporting for vault + PDF regeneration

Two of the 2.13.0 QA failures (#23 and #73) were untraceable because
the backends swallowed exceptions into the generic
`{"error":"Internal server error"}` envelope or added a terse
"render failed" line with no context. Both paths now surface the
actual failure reason so the next retest pass points at the real
root cause.

- **`routes/settings_api.py`**: `/vault/enable` and `/vault/disable`
  wrap `migrate_to_local_vault()` / `migrate_to_cloud()` in try/except,
  log the full exception with `exc_info=True`, and return
  `{"ok": false, "error": "<ExceptionType>: <message>"}` instead of
  letting the global handler mask the detail.
- **`frontend/js/app.js`**: The vault enable/disable buttons now render
  the `data.error` string (or `HTTP {status}` fallback) inline instead
  of the generic "Failed to enable vault" banner.
- **`routes/editor_api.py`**: PDF regeneration now distinguishes three
  failure modes for the full-story PDF:
  1. Missing Styled HTML precursor → explicit "regenerate Styled HTML
     first" error
  2. Render attempted but output is empty/missing → include attempted
     backend and output file size
  3. Per-chapter PDF failures keep their existing format
  This should diagnose why "Selective regen — All" left the full-story
  PDF out (test #23) on the next retest.

- **Cache busters**: `app.js?v=245`.

**`APP_VERSION` bumped to `2.13.3`.**

---

## [2.13.2] - 2026-04-24

### Fixed — Publish Check 500 on new / single-piece stories

`GET /api/editor/stories/{name}/publish-check` raised `IndexError` and
returned `{"error":"Internal server error"}` whenever the story's
`story.json` declared a `chapters` count but had an empty `chapter_info`
list. This affected every story created via the "Create New Story"
wizard (which writes `chapters: N` + `chapter_info: []`) and every
pre-existing single-piece story like `Blank` (which uses
`chapters: 1` + `chapter_info: []` by convention).

The publish-check endpoint iterates `range(1, story.total_chapters + 1)`
and indexes `story.chapters[i-1]` to build per-chapter rows. When
`_load_from_story_json` used `data.get("chapters", len(chapters))` for
`total_chapters`, the declared count (e.g. 1) outran the actual
`chapter_info` length (0), so `story.chapters[0]` raised.

This also killed the regen-staleness warning flow (tests #27 and #28 in
the checklist) because that banner is only rendered when
publish-check succeeds.

- **`posting/story_reader.py`**: `_load_from_story_json()` now sets
  `total_chapters = len(chapters)` unconditionally. `chapter_info` is
  the authoritative source of truth; the legacy `chapters` field in
  story.json is informational only. Existing multi-chapter stories
  (Chosen, Drumheller_Detour, etc.) already have matching lengths, so
  they're unaffected. Single-piece stories (Blank, wizard-created) now
  correctly render with only the "Full story" row in Publish Check.

**`APP_VERSION` bumped to `2.13.2`.**

---

## [2.13.1] - 2026-04-24

### Fixed — Anchor insertion toolbar buttons

All 8 anchor insertion buttons in the editor's rich-editor toolbar
(Title, Subtitle, Body, Warning, Text Sent, Text Received, Phone,
Story End) were silently dead clicks. `_insertAnchor()` referenced
`this._cm`, which is never assigned — the CodeMirror `EditorView` is
stored on `this.cmView`. The early-return guard `if (!text || !this._cm)`
always tripped, so nothing was ever dispatched to the editor.

The Title button's test (#11) was a false pass during QA because the
Create New Story template MASTER.md already contains `<!-- @title -->`,
so the tester saw the anchor in the document and didn't realise the
button hadn't actually inserted it.

- **`frontend/js/editor.js`**: `_insertAnchor()` now uses
  `this.cmView` consistently. Also rewrote the broken selection
  precedence (`cursor + text.indexOf('\n\n') + 1 || cursor + text.length + 1`
  collapsed incorrectly because `+` binds tighter than `||`) to an
  explicit branch — places the caret in the gap between opening and
  closing anchors for paired blocks (text-sent/phone/etc.), otherwise
  past the end of the inserted block.
- **`frontend/index.html`**: `editor.js` cache buster bumped to `v=282`.

**`APP_VERSION` bumped to `2.13.1`.**

---

## [2.13.0] - 2026-04-21

### Added — Genre templates, import from platforms, file upload in story wizard

**Genre templates (9 presets):**
- Romance, Erotica, Adventure, Comedy, Drama, Fantasy, Sci-Fi,
  Slice of Life, Horror — each pre-fills tags, rating, warnings,
  and category when creating a new story.
- Genre dropdown in Create New Story dialog auto-updates rating.
- `GET /genre-templates` endpoint for frontend consumption.

**Import from platforms (14a — IB, SF, FA):**
- "Import from Platform" button on story list shows polled submissions
  not yet in the local archive, grouped by platform.
- `posting/importer.py`: `import_from_inkbunny()` downloads BBCode
  text files and converts to Markdown (~14k words verified).
  `import_from_sofurry()` scrapes story content from the submission
  page after the chapter divider (~9.8k words verified).
  `import_from_furaffinity()` downloads story files via FAExport
  download URL (TXT/RTF full text; PDF gets description fallback).
- BBCode→Markdown and HTML→Markdown converters handle formatting.
- Name collision handling appends `_2`, `_3` suffix.
- `import_source` in story.json tracks provenance (platform, ID, URL).
- AO3/SQW listed as "coming soon" in the import dialog.

**File upload in Create New Story wizard:**
- Optional file upload field accepts `.md`, `.txt`, `.html`, `.bbcode`,
  `.rtf` — content replaces the template MASTER.md.
- Format converters: HTML→Markdown (strips tags, preserves structure),
  BBCode→Markdown, RTF→plaintext. Markdown and TXT used as-is.

**Hardcoded author cleanup:**
- 7 occurrences of hardcoded author name in `converter.py`,
  `generate_story_json.py`, `story_reader.py` replaced with
  configurable `default_author` setting. Users set it in
  settings.json; empty string fallback.

**GitHub release packaging (15a-c):**
- `README.md` — features, platform table, quick start, architecture
- `LICENSE` — MIT, 2026
- `CONTRIBUTING.md` — dev setup, platform module pattern, PR guidelines
- `.github/workflows/build.yml` — PyInstaller build on version tags
- `.github/workflows/lint.yml` — Ruff + JS syntax on push/PR
- `.gitignore` + `.env.example` updated

**`APP_VERSION` bumped to `2.13.0`.**

---

## [2.12.4] - 2026-04-19

### Added -- Embedded browser login for cookie-based platforms

Added a pywebview-powered browser login popup for platforms that require
cookie extraction (FA, DA, X/Twitter). In desktop mode, users click
"Login via Browser" and a native popup opens the platform's real login
page. After logging in, cookies are detected and saved automatically --
no more copying cookies from DevTools. Server mode falls back to
helpful login-page links.

- **`auth/browser_login.py`** (new): Core browser login module with
  per-platform config for 7 platforms (FA, DA, SF, TW, WS, AO3, SqW).
  Uses pywebview's `get_cookies()` to capture `SimpleCookie` objects,
  flattens them into `{name: value}` dicts, and checks success via
  URL/cookie conditions. Login runs in a daemon thread with a 5-minute
  timeout. `login_via_browser()` saves credentials via
  `config.save_settings()` on success.
- **`auth/__init__.py`** (new): Package init.
- **`routes/settings_api.py`**: Two new endpoints:
  - `GET /api/settings/browser-login/platforms` -- lists supported
    platforms with availability flag (True in desktop mode only).
  - `POST /api/settings/browser-login/{platform}` -- launches the
    pywebview popup and blocks until login completes or window closes.
    Runs the blocking call in `run_in_executor` to avoid stalling the
    event loop.
- **`frontend/js/api.js`**: Added `getBrowserLoginPlatforms()` and
  `browserLogin(platform, extraFields)` API methods.
- **`frontend/js/app.js`**: Updated FA, DA, and TW platform connect
  forms in the Platforms settings tab:
  - Desktop mode: shows "Login via Browser" as primary action with a
    "Enter cookies manually" toggle for the existing cookie input form.
  - Server mode: adds login page links to the instruction text for
    easier cookie extraction workflow.
  - Browser login availability is fetched in the `renderSettings()`
    parallel load and drives the conditional UI via
    `_browserLoginAvailable`.

---

## [2.12.3] - 2026-04-19

### Added -- First-run setup wizard

Added a guided setup wizard that appears on first launch when no
`setup_complete` flag exists in settings.json. Walks new users through
four steps: Welcome, Story Archive location, Platform Connections, and
a completion screen. Existing users are unaffected since the wizard
auto-skips when `setup_complete` is already set.

- **`routes/settings_api.py`**: Two new endpoints:
  - `GET /api/settings/setup-status` -- returns setup completion state,
    archive path presence, and count of connected platforms.
  - `POST /api/settings/setup-complete` -- marks setup as done so the
    wizard is not shown again.
- **`frontend/js/app.js`**: Added `renderSetupWizard()` method with
  4-step wizard (Welcome, Archive Path, Platforms, Done). Setup check
  in `init()` redirects to `#/setup` on first run. `setup` added to
  full-screen page list and route dispatch.
- **`frontend/js/api.js`**: Added `getSetupStatus()` and
  `markSetupComplete()` API methods.
- **`frontend/css/components.css`**: Setup wizard styles -- step
  indicator dots with connecting lines, platform card grid, responsive
  breakpoints.
- **`frontend/index.html`**: Cache busters bumped for components.css
  (v241) and app.js (v244).

---

## [2.12.2] - 2026-04-19

### Added -- Post scheduling in Publish Check

Added the ability to schedule publish/update actions for a future
date/time directly from the Publish Check matrix. The posting scheduler
daemon (already running) picks up scheduled items when the time arrives.

- **`routes/editor_api.py`**: Three new endpoints under
  `/api/editor/stories/{name}/`:
  - `POST /schedule` — validates story/platform/chapter, checks the
    scheduled time is in the future, runs poster validation, then
    inserts into `posting_queue` with `scheduled_at`. Returns queue_id
    and confirmed schedule time.
  - `GET /scheduled` — returns all pending/processing queue items for
    the story.
  - `DELETE /scheduled/{queue_id}` — cancels a pending scheduled item
    (verifies ownership by story name first).
- **`frontend/js/publish_check.js`**: Added "Schedule" button next to
  Post/Update in `_renderActionPanel()`. Clicking it reveals an inline
  `datetime-local` picker (defaults to 1 hour from now, rounded to next
  5 minutes). "Confirm schedule" submits to `/schedule`. The detail
  panel now loads and displays any pending scheduled items for the
  selected cell with per-item Cancel buttons.
- **`frontend/css/editor.css`**: Added Phase 6f schedule styles:
  `.schedule-form`, `.schedule-datetime`, `.schedule-pending`,
  `.schedule-pending-item`, `.schedule-cancel-btn` and related classes.
- **No scheduler changes needed** — `posting/scheduler.py` already
  processes the `posting_queue` table, checking `scheduled_at` against
  `datetime('now')` each cycle.

---

## [2.12.1] - 2026-04-19

### Added -- Create New Story wizard in Story Editor

Added a "Create New Story" button to the editor story list that opens a
form dialog and scaffolds the full folder structure with template files.

- **`routes/editor_api.py`**: New `POST /api/editor/stories/create`
  endpoint with `CreateStoryRequest` model. Validates folder name
  (alphanumeric + underscore, no duplicates), creates the directory tree
  (Markdown, BBCode, HTML, PDF, SquidgeWorld, Chapters/*, Images),
  generates a template MASTER.md showing all anchor types (@title,
  @subtitle, @byline, @body, @text-sent/received, @phone, @story-end),
  writes story.json with default metadata, and copies STYLING_REFERENCE.md
  as CHAPTER_STYLING.md when available.
- **`frontend/js/editor.js`**: Added "+ Create New Story" button to
  `renderStoryList()` with an overlay dialog containing title, folder
  name (auto-generated from title), author, chapter count (1-20), and
  rating (General/Mature/Explicit) fields. On success, navigates
  directly to the new story's editor. New `_submitCreateStory()` method
  handles validation and the API call.
- **`frontend/css/editor.css`**: Added `.create-story-overlay`,
  `.create-story-dialog`, `.create-story-label`, `.create-story-input`,
  `.create-story-error`, and `.create-story-actions` styles.
- Cache busters: `editor.css?v=244`, `editor.js?v=280`.

---

## [2.12.0] - 2026-04-19

### Added — Phase 7b: Local credential encryption at rest

Credentials can now be encrypted at rest using Fernet symmetric encryption.
When `credential_mode` is set to `"local"`, sensitive fields (passwords,
cookies, API keys, tokens) are stored in `settings.vault.json` instead of
plaintext in `settings.json`.

**Backend (`config.py`):**
- `VAULT_PATH` — path to `settings.vault.json` alongside the main settings.
- `_get_vault_key()` — retrieves or generates the Fernet encryption key
  (prefers system keyring, falls back to a `.vault_key` dotfile with 0600
  permissions).
- `_encrypt_vault()` / `_decrypt_vault()` — Fernet encrypt/decrypt of the
  credential payload, with atomic writes.
- `get_credential_mode()` — reads `credential_mode` from raw settings.json.
- `migrate_to_local_vault()` — moves credential fields from plaintext to
  encrypted vault; strips them from settings.json.
- `migrate_to_cloud()` — reverses migration, restoring creds to plaintext
  and deleting the vault file.
- `_load_settings()` — now transparently merges decrypted vault credentials
  when in local mode, so all consumers see a unified view.
- `save_settings()` — now splits credential fields into the vault when in
  local mode, writing only non-credential data to settings.json.
- `delete_settings_keys()` — vault-aware: re-encrypts remaining credentials
  after deletion in local mode.

**API (`routes/settings_api.py`):**
- `POST /api/settings/vault/enable` — switches to encrypted mode.
- `POST /api/settings/vault/disable` — switches back to plaintext mode.
- `GET /api/settings/vault/status` — returns current mode and vault
  file presence.

**Frontend (`frontend/js/app.js`):**
- "Credential Security" section in the Data tab with Enable/Disable/Status
  buttons and result display.

**Dependencies:**
- `cryptography~=46.0.7` added to `requirements-server.txt`.
- `cryptography>=44.0.0` added to `requirements.txt`.

---

## [2.11.1] - 2026-04-19

### Changed — Editor format selector: dropdown to tab bar

Replaced the `<select>` dropdown for switching output formats (Clean HTML,
SoFurry, BBCode, Styled HTML) with a compact inline tab bar. All four
formats are now visible at a glance as clickable buttons with an active
highlight, removing the extra click required by the old dropdown.

- **`frontend/js/editor.js`**: Swapped `<select id="editor-format-select">`
  for a `<div class="format-tabs">` with four `<button class="format-tab">`
  elements. Updated event binding from a single `change` listener to
  per-button `click` handlers that toggle the `.active` class and call
  `switchFormat()`.
- **`frontend/css/editor.css`**: Added `.format-tabs` (flex row, 2px gap)
  and `.format-tab` styles (11px font, accent-colour active state,
  hover highlight, smooth transition).
- Cache busters: `editor.css?v=243`, `editor.js?v=279`.

---

## [2.11.0] - 2026-04-20

### Added — Phase 7a: Settings sync (cloud mode)

Desktop ↔ server credential sharing via a single sync endpoint.
Login on one side, pull to the other — no more re-entering credentials
on both desktop and server.

**Backend (`config.py`):**
- `CREDENTIAL_FIELDS` — 35+ sensitive field names (all platform
  passwords, cookies, API keys, tokens, dashboard auth, integrations).
- `SYNC_EXCLUDE` — keys that are per-machine and must not sync
  (`credential_mode`, `auth_session_secret`, `minimize_to_tray`).
- `get_settings_for_sync()` — returns settings dict + file mtime,
  filtering out SYNC_EXCLUDE keys.
- `merge_synced_settings()` — merges incoming push into local
  settings, filtering SYNC_EXCLUDE.

**Sync endpoint (`routes/settings_api.py`):**
- `POST /api/settings/sync` — accepts `{mode: "pull"|"push",
  settings: {...}, timestamp: float}`. Pull returns server settings;
  push merges incoming keys and returns the merged result. Auth
  enforced by existing dashboard middleware (session cookie or
  `Bearer pp_xxx`).
- `GET /api/settings/sync/status` — server version, settings
  timestamp, credential_mode, total key count.

**Desktop startup sync (`main.py`):**
- `_sync_settings_on_startup()` — if `credential_mode != "local"`
  and `posting_server_url` + `posting_server_api_key` are configured,
  pulls settings from the server on startup via httpx. Failures are
  non-fatal (warning log, app continues with local settings).

**Dashboard UI (`frontend/js/app.js`):**
- Settings → Data tab → "Settings Sync" section with three buttons:
  - **Pull from server** — fetches server settings and merges locally
  - **Push to server** — reads local settings, sends to server
  - **Check status** — shows server version, key count, credential mode
- Result display shows key count or error inline.

**Cache buster:** `app.js?v=242`.

### Fixed — Path traversal, SF temp file leak, chapter tag init

- `editor_api._resolve_story_dir()` now uses `resolve()` +
  `relative_to()` to prevent `../` traversal in story_name URL param.
- SoFurry poster tracks temp files from ch1 front-matter merge and
  cleans them up in `finally` blocks after `post()` and `edit()`.
- `metadata_editor._ensureChapterEntry()` initializes `inkbunny: []`
  in chapter tags (was missing after platform extension).

### Fixed — Publish Check: no_credentials status for unconfigured platforms

Platforms without credentials show a lock icon and "No credentials
configured" instead of confusing poster init errors. Per-platform
credential requirements checked before the matrix loop. Action panel
shows clear "Set up in Settings" message.

### Changed — Skip startup polling

- Desktop (`main.py`): all 11 poller threads no longer fire an
  immediate poll on startup, preventing rate limiting on restarts.
- Server (`server.py`): orchestrator checks `last_poll_completed_at`
  and skips the first poll if the previous cycle was recent enough.

### Added — Tag editor improvements

- **Space→underscore auto-conversion**: typing a space in Default/FA/
  Weasyl/Itaku tag inputs converts to underscore in real-time.
- **"Fix spaces" button**: bulk-replaces spaces with underscores in
  all underscore-platform tags (story + chapter level).
- **"Sort A-Z" button**: sorts tags alphabetically across all
  platforms.
- **Tag format correction**: `_transformTagForPlatform()` fixed — FA
  and Weasyl now correctly keep underscores (were wrongly converting
  to spaces).
- **Tag browser "Selected" filter**: new chip tab filters the grid to
  show only currently-selected tags with descriptions.
- **Platform badges on tag cards**: small pills (DEF, SF, IB, AO3...)
  on each card showing which platforms have that tag.
- **Grid layout fix**: removed double-nested grid wrapper that was
  forcing single-column layout in the tag browser.

### Added — Polling module backlog fixes

**Session expiry recovery (3 pollers):**
- SQW: resets `_logged_in` before `validate_session()` so
  `ensure_logged_in()` attempts fresh login.
- FA: validates cookies before gallery fetch, clear error message.
- TW: empty credential check + clearer expired cookie message.

**N+1 query batching (4 pollers):**
- IB faving users, FA comments, SQW kudos, AO3 kudos all switched
  from per-item INSERT loops to `executemany` + `INSERT OR IGNORE`.
- Pre-existing set approach preserves notification detail tracking.

**AO3 rate-limit retry:**
- `_parse_retry_after()` extracts Retry-After header from 429s.
- `_get_page()` 429 handling fixed (was broken — retried inline
  without checking response status). Now retries within the loop
  with escalating backoff.
- `_post_with_retry()` wraps all 7 non-login POST operations.

### Added — Editor quick wins

**Regen staleness warning (12a):**
- Publish Check compares MASTER.md mtime vs newest generated file.
- Amber banner with inline "Regenerate now" button when stale.

**Edit button from published stories (12b):**
- Story detail page gains "Edit in Editor" link next to the title.

**Anchor insertion toolbar (10a):**
- 8 anchor buttons in the wysiwyg toolbar: Title, Sub, Body,
  Warning, Text Sent (→), Text Received (←), Phone, End.
- Inserts at CodeMirror cursor position.

### Added — Selective format regeneration (10b)

Regenerate button gains a dropdown with 7 options: All formats,
HTML only, BBCode only, Styled HTML + CSS, SquidgeWorld only,
PDF only, Chapter splits only. Backend `RegenerateRequest.formats`
filters which sections run.

### Added — Per-platform descriptions (10d)

Metadata drawer Basics section gains collapsible "Per-platform
descriptions" with Short (IB/SF, 1-2 sentences) and Announcement
(Bluesky, 300 char limit) textareas. `build_package()` picks the
right description per platform with fallback chain.

### Added — Retry queue (12d)

Failed posts/updates auto-queue for retry with exponential backoff
(1min → 5min → 30min, max 3 attempts). Uses existing
`posting_queue` infrastructure. Desktop-requiring platforms still
queue for desktop. Deletion errors skip retry. Frontend shows
"Will retry automatically" for queued retries.

### Added — Public release roadmap

`ROADMAP_PUBLIC.md` — Phases 8-15 covering auth UX (embedded browser
login), first-run wizard, editor enhancements, image support,
publishing UX, analytics, import, and GitHub packaging.

**`APP_VERSION` bumped to `2.11.0`.**

---

## [2.10.5] - 2026-04-19

### Added — Phase 6e: Publish Check safety polish

Four UX improvements to the Publish Check matrix, all frontend-only
(no backend changes).

**Live-publish re-confirm warning:**
- Unchecking "Save as draft" reveals a yellow warning banner in the
  action panel: "⚠ LIVE PUBLISH — This will be immediately visible
  to the public on <Platform>."
- The `confirm()` dialog for live (non-draft) actions now includes an
  extra warning paragraph urging the user to re-check the draft box
  if they didn't mean to go public.

**Readable dry-run results:**
- Dry-run output is now a structured summary (title, rating, word
  count, file name + size, tag count + full list, extras) instead of
  raw `<details><pre>` JSON. The raw JSON is still available under a
  "Raw JSON" collapsible at the bottom.

**Per-session action result log:**
- Every post/update/dry-run action is recorded in a session-scoped
  log array (max 20 entries). Rendered below the detail panel as a
  compact timestamped list with success/fail icons, platform names,
  and external links. Survives cell clicks and matrix reloads; clears
  on page refresh. Bulk operations log a single summary entry.

**Relative timestamps on posted publications:**
- The detail panel's "Posted" and "Last updated" fields now show a
  relative time suffix — e.g. "2026-04-17 14:30 (2d ago)". Uses a
  `_relativeTime()` helper: just now → Xm → Xh → Xd → locale date.

**Cache buster:** `publish_check.js?v=10`.

### Fixed — AO3 login retry + better Telegram error messages

**AO3 login retry with backoff (`ao3_client/client.py`):**
- Login page fetch now retries up to 3 times with 5s/10s exponential
  backoff. AO3's Cloudflare layer was returning transient non-200
  responses that cleared on retry. Previously a single failure killed
  the entire poll cycle.
- Logs the actual HTTP status code and first 200 chars of the response
  body on non-200 responses, replacing the opaque "Failed to fetch
  login page" message.
- Error message updated from "check credentials" to "check credentials
  or AO3 may be blocking (see logs for HTTP status)" to stop
  misleading the user when the creds are fine.

**Telegram error classification (`polling/telegram.py`):**
- New `_classify_error()` maps raw exception strings to user-friendly
  `(label, hint)` pairs. 13 patterns covering login blocks, rate
  limits, Cloudflare challenges, 403/404, timeouts, connection errors,
  SSL issues, and dropped connections.
- `send_poll_error()` now shows: bold label, italic hint explaining
  the likely cause, and the raw error in monospace for debugging.
- Consolidated poll summary (`send_consolidated_poll_summary`) uses
  the same classifier for failed platform lines.
- Before: `❌ 📖 AO3: AO3 login failed -- check credentials`
- After: `❌ 📖 AO3: Login blocked` / `Likely Cloudflare/rate-limit, not bad creds`

### Added — Polling module audit fixes (exc_info + silent exception handling)

Fresh audit of all 11 pollers rediscovered 16 findings from the
original (undocumented) audit. This release fixes the safe categories;
session expiry recovery and N+1 query batching are deferred for
hands-on testing.

**exc_info logging (120 additions across 11 pollers):**
- Every `logger.warning()` and `logger.error()` call inside an
  `except` block now includes `exc_info=True`. Previously, exception
  handlers logged the message string but discarded the stack trace,
  making production debugging impossible. Covers: comment/follower/
  watcher scraping failures, Telegram notification sends, toast
  notification sends, per-submission processing errors, milestone/
  summary/goal Telegram sends, and top-level poll cycle failures.

**Silent exception swallowing (19 replacements across 11 pollers):**
- `except Exception: pass` blocks in `send_poll_error()` wrappers and
  `_cleanup_*_client()` atexit handlers replaced with
  `logger.debug("Error alert send failed", exc_info=True)`. These
  were silently masking real failures in error-reporting and cleanup
  paths.

**Deferred (needs careful testing):**
- Session expiry graceful recovery (FA, SQW, TW) — currently hard-
  crashes on auth failure instead of attempting re-login.
- N+1 query batching (IB faving users, FA comments) — individual DB
  writes in loops instead of batch upsert.

### Added — Per-chapter tag platform parity

- `_CHAPTER_TAG_PLATFORMS` in `metadata_editor.js` extended from
  `['default', 'sofurry', 'wattpad']` to
  `['default', 'sofurry', 'inkbunny', 'wattpad']`, matching the
  story-level tag editor. Users can now set Inkbunny-specific tags
  per chapter in the metadata drawer.
- No backend changes — `story_reader.py` already cascades chapter
  `default` tags to all platform IDs on publish.

**Cache buster:** `metadata_editor.js?v=15`.

### Added — Phase 7 design document (`PHASE_7_DESIGN.md`)

Comprehensive design doc for the credential management system:
- Credential inventory: 35+ sensitive fields across 12 contexts
- Cloud mode: `POST /api/settings/sync` endpoint with push/pull,
  last-write-wins per-key conflict resolution, sync exclusion set
- Local-only mode: `settings.vault.json` encrypted via Fernet,
  key derived from Windows DPAPI or system keyring
- Migration path between modes (atomic swap)
- 3-phase implementation plan (7a cloud sync, 7b vault, 7c wizard)
- 5 open questions for user review

**`APP_VERSION` bumped to `2.10.5`.**

---

## [2.10.4] - 2026-04-17

### Added — Comprehensive tag audit across all 13 stories

Full tag audit of every story in the archive using per-story content
analysis agents. Each story's MASTER.md was read chapter by chapter
and cross-referenced against the 4-file tag database (physical, acts,
kink, meta) to identify missing tags, incorrect tags, and ambiguous
tags.

**Story-level tag updates (tags.default):**
- ~330 tags added across 13 stories (acts, kinks, species, meta)
- ~45 tags removed (redundant, not-in-DB, or content-unsupported)
- Under-tagged stories saw the biggest gains: Abstinent Bet Naughty
  (33→83), Velvet and Vice (46→94), Extra Credit (84→124)
- Audit report saved at `TAG_AUDIT_REPORT.md` in the archive root

**Per-chapter tag assignments (chapter_info[].tags.default):**
- ~70 chapters across all 13 stories received per-chapter tag lists
- Species/meta/genre tags distributed to all relevant chapters
- Act/kink tags assigned only to chapters where depicted on-page
- Tag counts range from 3 (quiet preludes) to 63 (explicit climaxes)

**Tag categories addressed:**
- Missing sexual acts (blowjob, anal_sex, rimming, edging, etc.)
- Missing kink dynamics (dominance, submission, power_dynamics, etc.)
- Missing physical traits (canine_penis, knot, claws, size_difference)
- Missing meta tags (first_time_mm, bisexual_awakening, infidelity)
- Redundant tags removed (duplicate phrasing, non-DB entries)

---

## [2.10.3] - 2026-04-17

### Added — SoFurry chaptered posting, FA probe_exists, nested story paths, anchor fix

**SoFurry chaptered posting (one submission, N chapters):**
- SF poster's `post()` detects multi-chapter stories: creates
  submission with chapter 1 (including front matter — title, subtitle,
  warning, disclaimer prepended), then appends chapters 2..N via
  `POST /ui/submission/{id}/content`.
- SF poster's `edit()` now does chapter-aware content refresh: uploads
  each chapter file individually then deletes old content items.
  Previous behaviour used `replace_file()` which clobbered all chapters
  into one content blob.
- `_set_chapter_titles()` sets per-content-item titles via
  `POST /ui/submission/{id}/content/{contentId}` with `{"title": "..."}`.
  Called after both post and edit. Strips `Chapter N:` prefix.
- SF added to `WORK_ORIENTED` set — per-chapter matrix rows show grey
  `–` N/A; Full story row is the actionable one.
- `_read_sf_front_matter()` extracts title/warning/disclaimer from the
  full-story SoFurry HTML to prepend to chapter 1 uploads (per-chapter
  files are body-only).

**FA deletion probe:**
- `FurAffinityPoster.probe_exists()` — hits `/view/{id}/`, checks for
  404 or "is not in our database" text. Verify posted now detects
  deleted FA submissions.

**Nested story path fix:**
- `publish-check`, `publish`, and `verify` endpoints used
  `story_dir.name` which returned only the last path component
  (`Nice_Version`) for nested stories like `The_Abstinent_Bet/Nice_Version`.
  Fixed to `story_dir.relative_to(get_archive_path())` so the full
  relative path is preserved.

**AO3 CF proxy for desktop residential IPs:**
- `AO3Client` accepts `proxy_url` + `proxy_key` (same pattern as
  SoFurryClient). When configured, all requests route through the
  CF Worker which bypasses AO3's "Shields are up!" Cloudflare TLS
  fingerprint check. All three AO3Client instantiation sites (poller,
  poster, API route) pass `cf_worker_url` / `cf_worker_key` from
  settings.json.

**Per-chapter SoFurry HTML anchor processing:**
- `/regenerate` endpoint's per-chapter SoFurry HTML generation now
  calls `_convert_body_clean_html()` directly instead of
  `convert(ch_content, "clean_html")`. The latter falls through to
  the heuristic parser for fragments without `<!-- @body -->`, which
  HTML-escapes semantic anchors. The body converter processes them
  correctly — `<!-- @text-received -->` becomes
  `<div class="text-message received">` instead of literal text.

**`APP_VERSION` bumped to `2.10.2`** (config.py).

---

## [2.10.2] - 2026-04-17

### Added — Unit tests, CF Worker hostname allowlist, docs refresh

Low-risk polish pass while the user was away from keyboard. No
runtime behaviour changes to the posting paths themselves — this
release locks in the 2.10.x helpers with tests, hardens the CF
proxy, and brings the reference docs back in sync with the code.

**Unit tests (`tests/test_posting_helpers.py`)**
- 30 tests, all passing, runnable via
  `python -m unittest tests.test_posting_helpers` from the PawPoller
  root. Plain stdlib `unittest`, no pytest dependency.
- Covers `posting.manager._looks_like_deletion` — deletion pattern
  matcher with explicit false-positive guards (`File not found on
  disk`, `model not found in cache`, etc. that the old `not found`
  catch-all would have matched).
- Covers `_strip_chapter_prefix` on both AO3 and SQW posters, with
  a divergence-check test that asserts the two verbatim-copied
  helpers produce identical output for identical input.
- Covers `_extract_work_form_fields` on both AO3 and SQW clients,
  with a hand-built OTW-style form fixture exercising text inputs,
  checkboxes (checked vs unchecked), selects (selected option),
  textareas, submit skipping, auth_token skipping, and HTML entity
  decoding. Also asserts AO3 and SQW helpers produce identical
  output for identical input.

**CF Worker hostname allowlist (`deploy/cf-worker.js`)**
- New `ALLOWED_HOSTS` set — only `sofurry.com`, `deviantart.com`,
  `archiveofourown.org`, `squidgeworld.org`, `furaffinity.net` (+ `www.`
  variants). Requests to anything else return
  `403 Target host not on allowlist: <host>`. Chain URLs validated
  against the same list so they can't bypass.
- Closes the open-proxy risk if `PROXY_SECRET` ever leaks: an
  attacker with the secret can only hit platforms we already route
  through, not arbitrary SSRF targets.
- **Requires manual redeploy via wrangler or the CF dashboard** —
  the Worker doesn't auto-deploy from git.

**`documentation_guide.md` refresh**
- Section 14 (AO3 poster) rewritten to reflect reality: chaptered
  posting via `create_work + create_chapter` loop, work skin
  CRUD, safe fetch-form overlay edit pattern, `content=None`
  preservation in `edit_chapter`, `skip_content_refresh` mode,
  `probe_exists` deletion detection, email-login account-name
  resolution. Removed the "Known limitations" block that falsely
  claimed AO3 had no chaptered / no work skin / chapter-1-only-edit.
- Section 15 (Story Editor) extended with three new subsections:
  Publish Check Matrix, Publish Action Panel, Theme-Save Trailing
  Content. Cell states documented, work-oriented vs per-chapter
  distinction explained, confirm_live guard noted.
- Section 10 (CF Worker) gained the hostname allowlist description.

**`PHASE_6D_PLAN.md` added**
- Design doc for bulk publish actions (Publish row, Publish all new,
  Update all drifted). Recommended path: frontend-orchestrated loop
  over existing `/publish` endpoint, no backend changes, no
  server-side state. AbortController-based cancellation. ~1 day
  complexity, all changes within `publish_check.js` + `editor.css`.

**Pyflakes-flagged dead imports removed**
- `asyncio`, `PostResult`, `StoryUploadPackage` from
  `posting/manager.py`.
- `pathlib.Path` from `posting/platforms/ao3.py` and
  `posting/platforms/squidgeworld.py`.
- No behaviour change; verified all tests still pass after removal.

### Not changed this release
- 13 polling module audit findings deferred — low-risk fixes there
  require careful testing that the user will do when back at a machine.
- Weasyl / FurAffinity / DeviantArt / Itaku / Bluesky still untested
  end-to-end. FA is blocked on desktop queue flush; Weasyl is blocked
  on account verification; DA / IK / BSky are user's choice to skip.

---

## [2.10.1] - 2026-04-16

### Fixed — Bug hunt round + edit_chapter overlay + AO3 shields

After Test Story posting was verified end-to-end on IB, SF, AO3, and
SQW, ran two rounds of automated audits against the posting module,
routes, editor, and frontend JS. Plus a few things that surfaced during
testing.

**Bug hunt finds:**
- `DELETION_ERROR_PATTERNS` no longer has a generic `"not found"`
  catch-all. Scoped to phrasings that specifically refer to the
  submission/work/URL (`submission has been deleted`, `work does not
  exist`, `page does not exist`, `client error 404`). Prevents
  false-positives on unrelated `"File not found on disk"` errors.
- `/verify` endpoint: `probe_exists()` is supposed to swallow its own
  errors, but now wrapped in try/except so one bad platform can't crash
  the whole verify loop. Rate-limited to 400ms between probes.
- `routes/posting_api.py` had a duplicate `get_sync_status` function
  both registered at `GET /sync/status`. FastAPI resolves last-one-wins;
  the earlier (simpler) one became dead code. Removed.
- **Silent data loss fix**: theme-save in `routes/editor_api.py`
  computed `after_idx` (position after `<!-- THEME_VARIABLES_END -->`)
  but never used it. Any content below the end marker — user notes,
  credits, extra CSS sections — got wiped on every theme save. Now
  properly re-attaches.
- `publish_check.js` v8: `_executeAction` captures `_currentStory` into
  a local at start; success-reload guards with `_currentStory ===
  storyName`. Prevents wrong-story matrix reload if user opens Publish
  Check for Story A → clicks Post → closes → opens for Story B.
- Re-check button disables itself immediately on click to prevent
  double-fire on rapid double-click.

**edit_chapter overlay pattern (AO3):**
- Ported from sqw_client — GET edit form, extract every chapter[*]
  field, overlay only caller overrides, POST with save_button.
- `content: str | None = None` — passing None preserves body on AO3.
- Metadata-only button on AO3 now pushes chapter title changes without
  re-uploading the chapter body.

**AO3 "Shields are up!" workaround:**
- Residential IPs were getting 403 on `/users/login` even though
  GCP/datacenter IPs worked fine. Expanded `_HEADERS` to match a real
  Chrome 131: added Sec-Fetch-Dest/Mode/Site/User, Sec-Ch-Ua/Mobile/
  Platform, Upgrade-Insecure-Requests, Priority.
- Login now warms up the session by GETting the homepage first, then
  navigates to `/users/login` with Referer + Sec-Fetch-Site:
  same-origin — mimics a real browser navigation instead of a cold
  direct-hit.

**Version bump:**
- `config.py APP_VERSION` bumped from `1.5.0` to `2.10.0`. Had been
  stale for months — every release was tracked in CHANGELOG.md but
  the in-app constant stayed behind. This is what the desktop tray
  tooltip shows, so the desktop was silently advertising year-old
  vintage even with current code.

---

## [2.10.0] - 2026-04-16

### Added — AO3 parity pass (chaptered posting, work skins, edit fidelity)

Large bundle of AO3 improvements driven by end-to-end testing of
chaptered story publishing on AO3 drafts. Chaptered stories now post
to AO3 the same way they post to SquidgeWorld: one work with N chapters
via `create_work` + `create_chapter` loop. Metadata edits push every
field instead of silently dropping the submission.

**Work skins on AO3 (mirroring SQW, same OTW Archive software):**
- `ao3_client.find_work_skin_by_title`, `create_work_skin`,
  `get_or_create_work_skin`, `edit_work_skin` — full CRUD on
  `/skins/{id}` via `skin_type=WorkSkin`.
- `edit_work` gains a `work_skin_id` kwarg so the assigned skin can
  be updated alongside other metadata.
- `AO3Poster._ensure_work_skin()` — finds or creates the per-story
  "<Story> Skin" on every post/edit, auto-refreshing the CSS from
  `SquidgeWorld/Work_Skin.css` so local edits propagate. Leading
  underscores on story folder names (`_Test_Story`) are stripped so
  the skin title is `Test Story Skin` rather than `_Test Story Skin`.

**Chaptered posting:**
- `ao3_client.create_chapter` — ported from SqW. POST to
  `/works/{id}/chapters/new` with `preview_button=Preview` so a
  draft work stays a draft while the chapter is added.
- `AO3Poster.post()` detects multi-chapter stories via
  `story.total_chapters > 1`. Multi-chapter → `create_work` with
  ch1 content, then iterate ch2..N via `create_chapter`. Single
  chapter → previous behaviour (full-story Clean HTML as one chapter).
- `AO3Poster.edit()` iterates AO3's existing chapters via
  `get_chapter_ids()`, edits each from the matching SquidgeWorld
  chapter HTML, appends any local chapters missing upstream.
- `_read_chapter_content(story, idx)` resolves
  `SquidgeWorld/Chapter_<idx>_*.html` with a prefer-exact-match
  glob (avoids picking up debris files).

**`edit_work` safe-overlay pattern (critical bug fix):**
Earlier builds sent `_method=patch` with only 5 `work[*]` fields
and no commit button. AO3 returned 302 but never persisted the
changes — a silent no-op. `edit_work` now:
1. GETs `/works/{id}/edit` and extracts every current `work[*]`
   field via `_extract_work_form_fields`.
2. Overlays only the caller-supplied overrides (title, summary,
   additional_tags, warnings, categories, relationship, characters,
   fandom, rating, work_skin_id).
3. `_append_if_missing()` any scalar override whose field name isn't
   in the form (defensive net against OTW rendering fields differently
   between new-work and edit forms).
4. POSTs the full form back with `save_button=Save As Draft`
   (or `post_button=Post` when `save_as_draft=False`).
5. Parses flash messages and logs notice/error/caution/warning
   classes at INFO so canonicalisation notices and validation errors
   surface in logs.

**Safety fixes:**
- Login with email instead of account name resolves via the login
  redirect URL so every `/users/{name}/...` call hits the right
  page. Fixes SQW SAFETY ABORT after `create_work` (draft-state
  check was hitting `/users/<email>/works/drafts` → 404 → treated
  as missing → work deleted). Same fix in AO3 client.
- `probe_exists()` added for AO3 + SQW. `/works/{id}/edit` 404 means
  deleted, 2xx means live, transient errors return None so we don't
  misflag live works.

**Matrix work-oriented flip:**
- Removed `PER_CHAPTER_ONLY = {"sqw"}` (had semantics inverted).
  Replaced with `WORK_ORIENTED = {"ao3", "sqw"}`. For chaptered
  stories on these platforms, per-chapter rows show grey `–` N/A
  with the hint to use the Full story row. The full-story row is
  the actionable one — internally handles multi-chapter creation.

**`Metadata only` update action:**
- New cell button next to `Update all`. Sends `skip_content_refresh`
  through `package.extra`. Short-circuits the chapter-refresh / file
  re-upload loop on IB, SF, FA, AO3, SQW (WS was metadata-only by
  API constraint). Faster edits when only tags/title/summary changed.
- `manager.update_story()` gains an `extras: dict` kwarg (mirrors
  `post_story`).
- Existing action renamed `Update existing` → `Update all` for
  clarity.

**Upstream deletion detection:**
- `PlatformPoster.probe_exists(external_id) -> bool | None` — new
  abstract method. SF / IB / AO3 / SQW implemented; others return
  None (not probed).
- `POST /api/editor/stories/{name}/verify` endpoint — walks every
  `posted` publication, probes each poster, flips confirmed deletions
  to `status='deleted'` in the registry. Matrix then renders those
  cells as red ⊘ with a `Re-post to <platform>` primary button.
- `manager.update_story()` catches deletion error strings (IB, FA,
  AO3) and flips the registry row to `deleted` instead of auto-queuing
  for desktop (which would hit the same wall).

**Content-refresh parity:**
- SF `edit()` now calls `replace_file()` alongside `edit_submission()`
  — previously metadata-only. FA `edit()` likewise calls
  `replace_file()` (changestory endpoint). WS explicitly documents
  the API limitation + returns a soft warning so the UI can surface
  `delete + repost required`.
- IB `edit()` skips BBCode read when `skip_content_refresh` is set.

**Tag cascade fix (editor UI):**
- `TAG_CASCADE_PLATFORMS` replaces the old `TAG_PLATFORMS` cascade
  target. Default tab now propagates added/removed tags to SF, IB,
  WP, **plus** AO3, SQW, WS, FA, DA, IK (everyone with a poster
  except Bluesky, which uses hashtag-style tags). Previously only
  the first three were synced, so AO3/SQW/etc. would keep stale
  tag lists and silently ignore updates.
- `_transformTagForPlatform` branch added for Itaku (underscores
  like default).

**Chapter title de-duplication (OTW display):**
- AO3 and SQW both render chapters as `Chapter N: <title>`. Passing
  `chapter_title="Chapter 1: The Counter"` ended up rendering as
  `Chapter 1: Chapter 1: The Counter`. Both posters now strip the
  leading `Chapter N:` / `Part N:` / `Prelude:` / `Epilogue:`
  prefix from chapter titles before `create_work` / `create_chapter`
  / `edit_chapter` calls.

**Cache busters:** `metadata_editor.js?v=14`, `publish_check.js?v=7`.

---

## [2.9.4] - 2026-04-15

### Added — Content drift detection in the Publish Check matrix

When you regenerate a story after posting, the matrix now flags
any (chapter × platform) cell whose local file has changed since the
last successful upload. The cell flips to a violet `↑` "Drifted"
state, and the detail panel shows a banner: *"Local content has
changed since this was posted. Hit Update existing to push the fresh
file."* — with the Update button promoted to primary so it's hard to
miss.

This fixes the silent failure mode where you edit MASTER.md, post
without regenerating, then later regenerate and forget the platform
copies are now out of date.

**Backend (`routes/editor_api.py`):**
- `/publish-check` now imports `posting.sync.hash_file`. For each
  cell whose `existing.status == 'posted'` and which has a file
  path, it hashes the current local file and compares to the
  `publications.file_hash` recorded at post time. Mismatch →
  `posted_drifted` cell status; the existing.drifted flag and
  the stored hash are surfaced to the UI.
- Tag-only platforms (Bsky, Itaku) store an empty file_hash on
  post and are skipped by the drift check.

**Frontend (`frontend/js/publish_check.js`):**
- New `posted_drifted` cell state — icon `↑`, violet colour.
- Stats line gains a "X drifted" counter (only shown when > 0).
- Action panel detects drift and:
  - Renders a violet banner explaining the drift.
  - Promotes Update to btn-primary with an extra "(push fresh
    content)" hint, so the right action is the obvious one.
- Footer legend updated.

**Frontend (`frontend/css/editor.css`):**
- `.cell-posted-drifted`, `.publish-action-drift-banner`,
  `.stat-drifted` styles.

**Cache buster:** `publish_check.js?v=4`.

---

## [2.9.3] - 2026-04-15

### Added — Full-story row in the Publish Check matrix

For chaptered stories the matrix previously only showed per-chapter
rows. You now get a "Full story" row at the top so you can choose to
post the whole work as one submission OR split into per-chapter
submissions. Some platforms suit one mode (FA chaptered for size,
SQW per-chapter only); others (SF, IB, AO3, WS) work either way.

The full row gets a heavier border + bold label so it's visually
distinct from chapter rows.

**Backend (`routes/editor_api.py`):**
- `chapters` array now always starts with `{"index": 0, "kind": "full"}`
  followed by per-chapter rows (if any). Single-chapter stories still
  show only the full-story row.
- New `PER_CHAPTER_ONLY = {"sqw"}` set — these platforms get a
  dedicated `not_supported` cell on the full-story row with a clear
  "use a chapter row" hint.
- New cell status `not_supported` (icon `–`, label "N/A —
  per-chapter only").

**Backend (`posting/story_reader.py`):**
- `_parse_story_json()` now cascades `default` tags to every poster
  ID that wasn't given an explicit list — at both the story level and
  the per-chapter level. Fixes the bug where DA / IK / BSky returned
  0 tags for the full-story package even when `default` had plenty.
- Platform name map extended with `deviantart→da`, `itaku→ik`,
  `bluesky→bsky` so editor-written story.json keys translate to the
  short IDs the package builder uses.

**Frontend (`frontend/js/publish_check.js`):**
- Full-story row gets `class="row-full"` + a "(<title>)" hint after
  the bold "Full story" label.
- New `cell-na` colour-block (subtle grey) for `not_supported` cells.

**Cache buster:** `publish_check.js?v=3`.

---

## [2.9.2] - 2026-04-15

### Added — Phase 6b: Publish actions (POC, all platforms via single endpoint)

The Publish Check matrix gains real action buttons. Click any cell, and
the detail panel now shows: **Dry Run** (always available — rebuilds
package + validates, returns full payload as JSON), **Post** (for
`ready` cells), **Update** (for `posted` cells where the platform
supports edit), and **Open** (for posted cells with an external URL).

Two safety layers:
- **Frontend**: `confirm()` dialog with the title, platform, and draft
  state spelled out. User must explicitly approve before any external
  HTTP fires.
- **Backend**: `confirm_live=true` is required in the request body for
  any non-dry-run action. The endpoint 400s without it — server-side
  guard if the UI is bypassed.

A "Save as draft" checkbox (default ON) sets `package.extra["draft"] =
True`, which on supported platforms (SF, SQW, AO3, etc.) creates the
submission as a draft instead of going public. Platforms that don't
support drafts ignore the flag.

**Backend (`routes/editor_api.py`):**
- `POST /api/editor/stories/{name}/publish` — body
  `{platform, chapter, action, draft, confirm_live}`. Routes to
  `manager.post_story()` or `manager.update_story()` for a single
  (platform, chapter) pair. Dry-run path skips manager entirely and
  returns the rebuilt package as JSON for inspection.

**Backend (`posting/manager.py`):**
- `post_story()` gains an `extras: dict | None` parameter. Values are
  merged into `package.extra` before posting. Update path inherits
  existing behaviour (no extras yet).

**Frontend (`frontend/js/publish_check.js`):**
- `_renderActionPanel()` produces the action buttons inside the detail
  panel based on cell state.
- `_executeAction()` handles dry-run / post / update calls, shows
  loading state, and refreshes the matrix on success.
- Result panel renders dry-run package as a `<details><pre>` JSON
  block, real posts as success/failure with external URL link.
- Matrix rows now carry `data-ch-idx` + `data-ch-title` for cell
  click → detail-panel context.

**Cache buster:** `publish_check.js?v=2`.

**Next (Phase 6c):** broaden testing to the other 8 platforms, then
6d adds bulk "Publish to all" and "Update all changed" actions.

---

## [2.9.1] - 2026-04-15

### Added — Phase 6a: Publish Check (read-only validation matrix)

Pre-flight check before the actual publish flow lands in 6b. Opens a
chapter × platform grid showing which combinations are ready, blocked,
or already posted — without making a single HTTP request to any
external platform.

**Backend (`routes/editor_api.py`):**
- `GET /api/editor/stories/{name}/publish-check` — returns
  `{ok, story_name, story_title, total_chapters, platforms[], chapters[], matrix[]}`.
- For each chapter × platform: builds the `StoryUploadPackage` via
  `story_reader.build_package()`, runs `poster.validate(package)`,
  cross-references the publications registry. No external HTTP.
- Cell statuses: `ready`, `blocked`, `posted`, `posted_stale`
  (already posted but file/tags now invalid), `ready_retry` (previous
  attempt failed, package now valid), `failed_prev` (previous attempt
  failed and still blocked), `error` (poster init or package build threw).
- `PUBLISH_PLATFORMS` constant defines display order: IB, FA, WS, SF,
  SQW, AO3, DA, IK, BSky.

**Frontend (`frontend/js/publish_check.js` — new):**
- `PublishCheck.open(storyName)` opens a full-screen modal (5vw inset,
  z-index 10010) with the matrix.
- Each cell shows a status icon (✓ / ✗ / ! / ↻ / ⚠) colour-coded by
  status. Click a cell → detail panel with package title, tag count,
  file path + size + max-size, mode requirement, edit support,
  existing publication link.
- Sticky header row (platform names) and sticky first column (chapter
  titles) so the matrix scales for stories with many chapters.
- Stats line: total combinations / posted / ready / blocked.
- "Re-check" button re-fires the endpoint without closing the modal.
- ESC and backdrop click both close.

**Frontend (`frontend/js/editor.js`):**
- New "Publish" button between Regenerate and Format, opens
  `PublishCheck.open(storyName)`.

**Frontend (`frontend/css/editor.css`):**
- Full modal styling: `.publish-check-modal`, `.publish-check-dialog`,
  `.publish-check-table`, status colour cells (`.cell-ready`,
  `.cell-posted`, `.cell-posted-stale`, `.cell-retry`,
  `.cell-blocked`, `.cell-error`), detail panel.

**Cache busters:** `editor.js?v=276`, `publish_check.js?v=1`.

---

## [2.9.0] - 2026-04-15

### Added — Native PDF generation in the editor (WeasyPrint primary, Edge fallback)

The editor's `/regenerate` endpoint previously skipped PDF generation entirely
(the `skip_pdf` flag on `RegenerateRequest` was dead — nothing read it).
PDFs only existed if a user manually ran `m_x/Scripts_Utils/regenerate_story.py`
locally with Edge installed. This blocked Phase 6 (publish buttons) for FA,
which requires per-chapter PDFs because of the 10 MB upload limit.

**New module — `editor/pdf_generator.py`:**
- `html_to_pdf(html_path, pdf_path) -> (ok, backend)` — picks the best
  available backend automatically.
- **WeasyPrint** is primary. Pure-Python HTML→PDF, no browser required.
  Renders styled HTML using the existing `style.css` next to it
  (resolved via `base_url=html_path.parent`). Works server-side in the
  GCP container, so PDFs regenerate without needing desktop mode.
- **Edge headless** is the fallback. Probes the two standard install
  paths on Windows; renders via `--print-to-pdf=...`. Used when
  WeasyPrint can't import its native libs (typical on bare Windows
  without GTK runtime).
- `get_backend()` reports which backend is currently usable
  (`weasyprint` / `edge` / `none`).

**Backend (`routes/editor_api.py`):**
- `RegenerateRequest.skip_pdf` default flipped from `True` to `False`
  (PDFs now generated by default — WeasyPrint is fast enough that the
  opt-in pattern is no longer warranted).
- New PDF block runs after the Styled HTML pass:
  - Full story → `PDF/{stem}.pdf` from `HTML/{stem}_Styled.html`.
  - Each `Chapters/Styled_HTML/Chapter_*.html` → `Chapters/PDF/Chapter_*.pdf`.
  - Tracks per-file failures in `errors[]`, total count in `results[]`.

**Dockerfile:**
- Added `apt-get install` for WeasyPrint's native deps:
  `libpango-1.0-0`, `libpangoft2-1.0-0`, `libharfbuzz0b`, `libcairo2`,
  `libgdk-pixbuf-2.0-0`, `libffi8`, `fonts-dejavu-core`. ~50 MB image growth.
  Fonts pkg ensures consistent rendering on the headless container.

**Dependencies:**
- `weasyprint>=68.0` added to `requirements.txt`.
- `weasyprint~=68.1` added to `requirements-server.txt`.

**Why not Playwright?** Bundling Chromium is ~150 MB and pixel-perfect
rendering isn't needed for these PDFs (clean text + headings + page
breaks). WeasyPrint is the right shape for the job.

**Verification:** `_Test_Story` regenerated locally — full PDF (200 KB)
+ 4 chapter PDFs (96–164 KB). On Windows it routed through the Edge
fallback (WeasyPrint missing GTK), but the server will use WeasyPrint
natively after deploy.

---

## [2.8.2] - 2026-04-15

### Added — Metadata Editor Phases 4 + 5 + 4b: Tag Browser + Per-Chapter Tags

**Phase 4 — Tag Browser modal:**
- Full-screen browser opened from "Browse all matches" button in the
  autocomplete dropdown. Shows ALL tags from the local DB filtered by
  category chips (`physical`, `acts`, `kink`, `meta`, `image`, `user`).
- Search box filters in real time. Click a tag to add it to the active
  platform with normal cross-platform propagation rules.
- Portal-mounted to `document.body` to escape `.metadata-section-body`'s
  `overflow: hidden` clipping (same fix as the autocomplete dropdown).

**Phase 5 — Section toggles + collapse memory:**
- Each metadata section header has a chevron — click to collapse.
- Expanded/collapsed state persists per-section in `localStorage`
  (`pawpoller_metadata_section_state_v1`).
- Smooth height transition; respects `prefers-reduced-motion`.

**Phase 4b — Per-chapter tag editing:**
- New `Chapter Tags` section in the metadata drawer. One sub-panel per
  chapter, each with the same tab strip + autocomplete UI as the
  story-level Tags section.
- Backend (`routes/editor_api.py`):
  - `chapter_info[i].tags[platform]` shape added to `story.json`.
  - `GET /api/editor/stories/{name}/chapters` returns the per-chapter
    tag map alongside titles/descriptions/thumbnails.
  - `PUT /api/editor/stories/{name}/chapters` upserts per-chapter tags
    atomically (write to `.tmp` → rename, with `.bak.{ts}` snapshot).
- Frontend (`frontend/js/metadata_editor.js`):
  - **NO cross-platform sync** for chapter tags (unlike story-level
    Default → SF/IB/WP cascade). Reasoning: per-chapter tags are
    typically platform-specific edits (e.g. SF "Chapter 3 of 5" vs IB
    "story-arc"), not universal labels.
  - Same e621 lookup + "+ Library" workflow available per chapter.

**Cache buster:** `metadata_editor.js?v=13`

---

## [2.8.1] - 2026-04-15

### Added — Metadata Editor Phase 3b: e621 lookup fallback + "+ Library" workflow

**Bundled e621 lookup TSV:**
- `tag_database/e621_lookup.tsv` — 26,829 tags, ~500KB. Filtered from the raw
  e621 dump (drop cat 1/2/4 + low-post + IMAGE_NOISE regex + bad-name chars).
- Generator lives at `m_x/Scripts_Utils/generate_e621_lookup.py` (not shipped —
  only the output TSV ships with the repo).

**Backend (`routes/editor_api.py`):**
- New lazy loader `_load_e621_lookup()` — parses TSV once on first lookup call.
- `GET /api/editor/tags/lookup?q=<str>&limit=<N>` — substring search against
  the e621 lookup, excluding tags already in the local DB. Ranking:
  exact > prefix > substring, post_count desc. Returns `{matches: [{name, category, post_count}]}`.
- `POST /api/editor/tags/add` — appends a tag to one of the local DB files.
  Body: `{name, target, description}`. `target` is one of
  `physical|acts|kink|meta|image|user`. Validates against
  `^[a-z0-9_/-]+$`, rejects dupes (409), invalidates the in-memory
  `_TAG_DB_CACHE` on success.
- `tag_database_user.txt` added to `_TAG_DB_FILES` with category label
  `user`. Auto-created with a header on first write.
- Curated DBs get a new `USER ADDITIONS` section appended on first
  per-file user-add, then appended-to on subsequent adds.

**Frontend (`frontend/js/metadata_editor.js`):**
- Autocomplete dropdown now appends an "e621 suggestions" block below local
  matches whenever local hits < 5 and query length >= 3.
- Debounced (300ms) fetch; session-scoped `Map` cache keyed by lowercased query.
- Each e621 row shows: name, category chip (`e621 general/species/copyright/meta/lore`),
  post count, and three actions:
  - **+ {Target}** primary button — target is derived from the e621 category
    (species → physical, general → user, copyright → meta, etc.).
  - **Caret dropdown** — choose any of the 6 library buckets explicitly.
  - **Use once** — adds the tag to the current platform without mutating
    the library (same as pressing Enter on the raw query).
- `_addTagToLibrary(name, target)` — POST to `/api/editor/tags/add`, then
  clears `sessionStorage['pawpoller_tag_db_v1']`, reloads the local tag DB,
  clears the e621 cache, and routes through `_addTagFromDropdown` so the
  tag is immediately applied with normal cross-platform propagation.
- Status toast: "Added '<name>' to <Target> library".
- Tag browser categories now include `user` (so user-added tags show up
  in the expanded browse modal's filter chips).

**Frontend (`frontend/css/editor.css`):**
- `.metadata-tag-result-divider` — section header above e621 block.
- `.metadata-tag-result-e621` — subtle violet wash to distinguish from local rows.
- `.metadata-tag-cat-e621` — violet category chip for e621 rows.
- `.metadata-tag-cat-user` — warm beige chip for user-added tags.
- `.metadata-tag-add-library-btn` — primary "+ Library" button.
- `.metadata-tag-use-once-btn` — subtle "Use once" link-style button.
- `.metadata-tag-target-menu*` — caret + dropdown for explicit target choice.

**Cache buster:** `metadata_editor.js?v=12`

---

## [2.8.0] - 2026-04-15

### Added — Metadata Editor Phase 3a: Tag Autocomplete

**Bundled tag database:**
- `data/tag_database/` shipped with the repo (5 tag files + `tag_aliases.json`, ~2MB raw / ~400KB gzipped)
- Sourced from `C:\Users\rhysc\claude\Tag_Database\`: physical, acts, kink, meta, image categories + 23K aliases
- `.gitignore` + `.dockerignore` carve-outs so `data/` stays ignored but `data/tag_database/` ships
- Loads + parses once per process (version-hashed cache); served from memory

**Backend (`routes/editor_api.py`):**
- `GET /api/editor/tags` — returns `{tags: [...], aliases: {...}, version: sha256}`
- Section-aware parser for `name | description` tag files
- SHA256 version hash over all files → cache self-invalidates if files change on disk

**Frontend (`frontend/js/metadata_editor.js`):**
- Per-platform tag section now renders a tab strip (Default / SoFurry / Wattpad / Inkbunny) with separate pill lists per platform
- Lazy tag DB load on first autocomplete interaction (cached in `sessionStorage` by version hash, background refresh)
- Autocomplete dropdown: exact → alias → prefix → substring match ranking, capped at 30 results
- Alias matching: typing "boobs" surfaces `breasts` with alias badge; selection adds the canonical tag
- Keyboard nav: ArrowUp/Down, Enter to add, Esc to close, Backspace-on-empty to remove last pill
- Unknown-tag handling: "No matches — Press Enter to add anyway" with yellow-bordered pill flag
- Tag count footer with per-platform limits (SoFurry 97, Wattpad 24, Inkbunny/Default ∞), turns red over limit

**Frontend (`frontend/css/editor.css`):**
- Tab strip + dropdown + pill styles matching dark theme tokens
- Per-category chips with colour coding (physical/acts/kink/meta/image)

**Cache busters:** `metadata_editor.js?v=3`, `editor.css?v=241`

---

## [2.7.0] - 2026-04-13

### Added — WYSIWYG Editor, Semantic Anchors, Format Tools, Theme Persistence

**Theme Save persistence + Regenerate integration:**
- Theme Save now persists variables to `CHAPTER_STYLING.md` (survives Regenerate)
- Regenerate now includes Styled HTML (full + chapters + `style.css`)
- `pawpull.py` reverse sync script (server → local)
- Text message colour pickers in theme GUI (`TEXT_SENT_COLOUR`, `TEXT_RECEIVED_COLOUR`)
- Warning icon + section break mega dropdown selectors (55 icons, 47 breaks, custom option)
- `GET /theme` endpoint fills defaults for missing variables
- `PUT /format-file` endpoint for saving formatted output

**WYSIWYG Rich Editor (panel 2):**
- Contenteditable panel with formatting toolbar (Bold, Italic, Heading, Section Break, Undo, Redo)
- Bidirectional sync with CM source via Turndown (HTML→markdown) library
- Front matter locked as non-editable; body edits sync to all panels
- Source-flag pattern prevents infinite sync loops
- Paste handler sanitises to plain text

**Semantic anchors for text messages + phone displays:**
- New body-level anchors: `<!-- @text-sent -->`, `<!-- @text-received -->`, `<!-- @phone-incoming -->`
- All 4 body converters (Clean HTML, SoFurry, BBCode, Styled HTML) handle anchors
- Clean/Styled HTML: `<div class="text-message sent/received">` with CSS styling
- BBCode: colour-coded `[right]` (sent) / `[left]` (received) alignment
- SoFurry: `text-right` / `text-left` class alignment
- Text-message + phone-display CSS added to STYLING_REFERENCE.md template
- `is_text_message()` regex fixed to match `**Name:** message` format (was broken)

**Format Document button:**
- js-beautify library (141KB) for HTML/CSS prettification
- Format button + Shift+Alt+F keyboard shortcut
- Formats + saves the prettified content to disk via `PUT /format-file` endpoint

**Editor improvements:**
- Bidirectional scroll sync across all 4 panels (60ms lock prevents wobble)
- Cross-panel selection sync (highlight text in any panel → shows in others)
- Selection highlights skip contenteditable panel to prevent DOM corruption
- Preview truncation limit raised from 100K to 500K chars
- Print-container added to STYLING_REFERENCE.md template (print margins)
- Ruins of Breeding: fixed 44 bogus `<strong>` tags from parser bug
- 8 stories: added print-container wrapper to styled HTML files
- Converter: `---` separator no longer leaks into disclaimer text

**Bug fixes (comprehensive audit — 12 issues):**
- Auto-save timer properly cleared on re-render
- CM instances destroyed on re-render (prevents orphaned listeners)
- beforeunload listener cleaned up between stories
- Scroll sync flag in try/finally (prevents stuck state)
- Toolbar overflow handled with nowrap + overflow-x
- Front matter re-extracted from CM on every WYSIWYG sync (prevents stale cache)

---

## [2.6.0] - 2026-04-12

### Added — Visual Theme Editor with live preview sync

**Theme GUI (editor.js / editor_api.py):**
- Visual colour picker interface for all 14 styled HTML theme variables
- Live preview: changing any colour immediately updates the Styled HTML preview iframe (~300ms debounce)
- CSS source view stays in sync with GUI changes (returned from preview endpoint)
- Undo button — steps back one change at a time (50-entry stack, debounced for colour picker drags)
- Revert button — resets to last-saved values (the revert itself is undoable)
- Save writes `style.css` to `HTML/` and `Chapters/Styled_HTML/`, clears undo history
- Source/GUI toggle switches between visual editor and raw CSS CodeMirror view

**Backend (editor_api.py):**
- `PreviewRequest` accepts optional `theme` dict for live GUI → preview pipeline
- Preview response includes generated `css` field for styled_html format
- `PUT /theme` endpoint: better error handling (PermissionError, template-not-found, CSS generation failures)
- `PUT /theme` and `PUT /css`: proper HTTP error detail parsing in frontend

**External CSS migration (all 13 stories):**
- Generated `style.css` for all 13 stories (28 files: `HTML/` + `Chapters/Styled_HTML/`)
- Converted 89 Styled HTML files from embedded `<style>` to external `<link rel="stylesheet" href="style.css">`
- ~600 KB total size reduction across all styled HTML files

**Infrastructure:**
- `deploy/pawsync.py`: changed `chmod o+rX` to `o+rwX` so Docker container can write to story archive
- Cache-busting on `editor.js` (v250 → v253)

---

## [2.5.1] - 2026-04-10

### Fixed — Full code audit cleanup

4-domain audit across editor code, standalone scripts, MASTER.md files, format files, and documentation. 66 findings addressed.

**Code fixes:**
- converter.py: removed unreachable `else` block (dead code from subtitle iteration)
- editor_api.py: removed duplicate path resolution (copy-paste error)
- editor.js: removed dead `_setupDivider()` method (19 lines, old split pane)
- editor.css: removed dead `.preview-source-header` style

**Portability fixes (14 scripts):**
- Eliminated all hardcoded `C:/Users/rhysc/claude/...` absolute paths across 14 Scripts_Utils files
- All now use `Path(__file__).resolve().parent.parent / "Archives" / "Complete_Stories"` (relative to script location)
- Scripts work on any machine, any OS, any user account

**Data fixes:**
- AB Nice + Naughty: added missing `#workskin em` CSS rule to Work_Skin.css
- Velvet story.json: title "Velvet And Vice" → "Velvet and Vice" (lowercase "and")
- 7 MASTER.md files: added `---` separator after `<!-- @body -->` for cross-story consistency
- slop_scorer.py: fixed formula docstring to match actual implementation

**Documentation fixes:**
- EDITOR_PLAN.md: updated all phase statuses (Phases 1-4 marked DONE, Phase 5 TODO list updated)
- FILE_FORMAT_STANDARDS.md: added external CSS architecture section for Styled HTML

---

## [2.5.0] - 2026-04-10

### Added — Story Editor: all formats complete + anchor system + slop scoring

The story editor is now a full pipeline — every format automated from MASTER.md.

**Anchor-based MASTER.md parsing (Phases 1-2):**
- 7 HTML comment anchors mark structural sections: `@title`, `@subtitle`, `@byline`, `@warning`, `@disclaimer`, `@fanfiction`, `@body`
- `parse_front_matter()` extracts structured `FrontMatter` dataclass from anchored files
- 4 format-specific front matter renderers (Clean HTML, SoFurry HTML, BBCode, SQW)
- Heuristic fallback for non-anchored files (backwards compatible)
- Migration script `add_anchors_to_master.py` processed all 13 stories — warning/disclaimer text sourced from canonical SQW Chapter 1 files
- `@fanfiction` anchor for IP attribution (Chosen = DreamWorks, Silk = Bethesda)

**Standalone converter unification (Phase 3):**
- `convert_md_to_sofurry_html.py` and `convert_md_to_bbcode.py` replaced with 80-line wrappers that import from `editor/converter.py`
- ~1,000 lines of duplicate parser code eliminated

**SQW auto-generation (Phase 4):**
- `convert_to_sqw_chapters()` generates per-chapter SquidgeWorld body HTML from anchored source
- Chapter 1: full warning-page div; Chapter 2+: bare title block
- Warning icon read from CHAPTER_STYLING.md per story
- Wired into editor regenerate endpoint

**Styled HTML generator (the last manual format):**
- `convert_to_styled_html()` generates complete HTML documents with embedded CSS
- `parse_chapter_styling()` reads 14 colour variables from CHAPTER_STYLING.md
- 3 modes: full story, per-chapter, single chapter
- Template from STYLING_REFERENCE.md with `{{PLACEHOLDER}}` variable filling
- Print CSS generation (colour-preserve + grayscale modes)
- Editor renders Styled HTML in sandboxed iframe

**Slop scoring:**
- `editor/slop.py` — ported EQ-Bench scorer for in-memory use
- `POST /api/editor/{story}/slop` endpoint
- Colour-coded badge in editor toolbar (green CLEAN < 15, yellow BORDERLINE 15-25, red SLOP > 25)
- Refreshes on load + after save

**SF replace_file() fix:**
- Upload-first-then-delete order (SF won't delete the last content item)
- 32 duplicate content items cleaned across 12 stories

**SoFurry HTML converter:**
- New `convert_to_sofurry_html()` using SF's actual HTML capabilities (`<h2>`, `<h3>`, `text-center`)
- `story_reader.py` updated to prefer `*_SoFurry.html` over `*_Clean.html` for SF uploads
- SoFurry HTML capabilities reference documented from `sofurry_html_capabilities.html`

**Content warning standardisation:**
- 7 MASTER.md files received Content Warning + DISCLAIMER blocks (were missing)
- Centering rules enforced: title, subtitle, CW, disclaimer, chapter headings, POV markers, section breaks, end marker — all centred in every format
- `_is_warning_line()` detector + `in_warning_block` state tracking (heuristic, replaced by anchors)

**Editor format dropdown:** Clean HTML (AO3), SoFurry HTML, BBCode (IB), Styled HTML (PDF) — 4 formats, all live-converting from the textarea

**converter.py:** 1,722 lines (from 457 at session start)

---

## [2.4.0] - 2026-04-09

### Added — Story Editor (Phase 1: Edit + Preview + Regenerate)

New in-app story editor accessible at `#/editor`. Edit MASTER.md directly in the PawPoller web UI with a live format preview and one-click format regeneration.

**Backend** (`editor/` package + `routes/editor_api.py`):
- `editor/converter.py` — core markdown parser (`parse_markdown_formatting()`) + HTML/BBCode renderers. Same parser used by the standalone CLI converters. Handles `*italic*`, `**bold**`, `***both***`, nested italics, POV markers, text messages, chapter headings, section breaks.
- `routes/editor_api.py` — 5 endpoints:
  - `GET /api/editor/stories` — lists all stories in the archive (13 found)
  - `GET /api/editor/stories/{name}/content` — reads MASTER.md, detects chapters
  - `PUT /api/editor/stories/{name}/content` — saves with backup + optimistic concurrency
  - `POST /api/editor/stories/{name}/preview` — live format conversion (clean_html, bbcode)
  - `POST /api/editor/stories/{name}/regenerate` — writes BBCode + Clean HTML + chapter splits

**Frontend** (`editor.js` + `editor.css`):
- Story list page (`#/editor`) — card grid of all stories with word counts
- Split-pane editor (`#/editor/{story}`) — textarea left, live preview right
- Draggable divider between panes
- Format switcher (Clean HTML / BBCode dropdown)
- Ctrl+S keyboard shortcut for save
- Debounced live preview (400ms after typing stops)
- Dirty-state tracking with beforeunload warning
- Word count in toolbar (live)
- Regenerate button (saves first if dirty, then writes BBCode + HTML + chapter files)
- Sidebar nav link under new "Editor" section

**File management:**
- Editor reads/writes directly to the story archive (resolved via `story_reader.get_archive_path()` — works for both desktop and Docker)
- Save creates a timestamped backup (`MASTER.md.bak.{timestamp}`), keeps last 10
- Atomic write via temp file + `os.replace()` to prevent corruption
- Regenerate creates folder structure if missing (`BBCode/`, `HTML/`, `Chapters/`)

**Architecture docs:** `docs/EDITOR_PLAN.md` — full implementation plan covering all 5 phases, file sync model, API design, frontend design, risk assessment.

**What's next (Phases 2-5):**
- Phase 2: SQW + Styled HTML preview tabs, chapter outline sidebar
- Phase 3: Live slop score + validation panel
- Phase 4: CSS theme editor (colour pickers → live styled preview)
- Phase 5: PDF generation + one-click platform push

---

## [2.3.19] - 2026-04-09

### Fixed — Platform push of regenerated files (SF + IB + AO3 attempt)

Pushed the converter-rewrite output to all accessible platforms:

- **SoFurry**: 13/13 submissions updated via `SoFurryPoster.replace_file()` (Clean HTML body content replaced). Both published and draft works updated. Total time ~16s.
- **Inkbunny**: 7/7 submissions updated via `InkbunnyPoster.replace_file()` (BBCode story text replaced via `api_editsubmission.php`). All published works updated. Total time ~9s.
- **AO3**: 0/13 — "Shields are up!" (AO3 rate-limit wall). Script `tests/edit_ao3_after_converter_rewrite.py` ready for retry.

### Changed — Inkbunny `replace_file()` implemented

`posting/platforms/inkbunny.py`: Replaced the "not implemented" stub with a working implementation that reads the BBCode file and pushes via `client.edit_submission(story=text)`. The IB API's `api_editsubmission.php` accepts a `story` field for the reading-panel body text — only that field is sent, so title/description/tags/visibility are preserved.

### New test scripts
- `tests/edit_sf_after_converter_rewrite.py` — bulk SoFurry content push
- `tests/edit_ao3_after_converter_rewrite.py` — bulk AO3 content push (ready for retry)

---

## [2.3.18] - 2026-04-09

### Fixed — Converter rewrite: proper `*`/`**` italic/bold parser

**Root cause fix** for the `<em><strong>` / `[i][b]` nested-italic bug class that affected Clean HTML (SoFurry/AO3), BBCode (Inkbunny), and SquidgeWorld body files across the entire catalogue.

Both `convert_md_to_sofurry_html.py` and `convert_md_to_bbcode.py` rewritten with a new `parse_markdown_formatting()` function that scans left-to-right, toggling italic state on `*` and bold state on `**`. Replaces the old pipeline (`split_dialogue_narration` → `apply_narration_italic` → `convert_emphasis` → outer wrapper stripping) which had these bugs:
- Inner `*word*` inside italic context rendered as `<strong>` (bold) instead of toggling italic OFF (roman)
- Outer wrapper stripping heuristic was fragile (counted asterisks, broke on mixed-italic lines)
- Default-italic mode wrapped un-marked paragraphs in italic
- POV marker regex didn't support Unicode `⟨⟩`
- HTML converter lacked text message detection (BBCode had it)

**Files regenerated:**
- 22 full-story files (11 Clean HTML + 11 BBCode)
- 118 per-chapter files (SoFurry HTML + BBCode per chapter)
- All from current MASTER.md source

**Verification:** `grep -rl "<em><strong>"` on all Clean HTML returns only legitimate `***bold+italic***` constructions (Extra Credit epilogue title, Velvet story-name references). Zero converter bugs.

---

## [2.3.17] - 2026-04-09

### Fixed — Section break styling + inline emphasis + PDF regen (final clean-up pass)

Continuation of the [2.3.16] standardisation sweep. Targets the remaining validator warnings.

**Fixes:**
- **67 SQW section breaks styled** — `<p>* * *</p>` → `<p class="section-break">* * *</p>` across 23 files / 8 stories. The CSS accent colour + centering now applies.
- **108 styled HTML section breaks styled** — same fix applied to per-chapter and full-story styled HTML across 21 files / 6 stories. PDFs now render section breaks with proper spacing.
- **32 inline `*word*` emphasis converted** — bare markdown emphasis in dialogue that the old converter never processed (e.g. `*looking*`, `*Kristoff*`, `*me*`) → `<em>word</em>` across 9 styled HTML files / 3 stories (Extra Credit, Ruins, Velvet).
- **1 Ruins ch1 styled HTML fix** — leading literal `*` + `<em><strong>` converter artefact on the "His hooves" paragraph (same bug class as the SQW bolding fix, but in the styled source).
- **87 PDFs regenerated** from updated styled HTML.
- **Validator false-positive fix** — `validate_story.py` no longer flags `* * *` inside `<p class="section-break">` as stray asterisks.

**New script:** `fix_sqw_plain_section_breaks.py` — converts standalone `<p>* * *</p>` → `<p class="section-break">* * *</p>` across all SQW chapters.

**Final validator result:** 11 of 12 stories at 0 fails, 0 warnings. Only NSES remains (incomplete folder build — separate scope).

---

## [2.3.16] - 2026-04-09

### Fixed — Full SQW standardisation pass (11 stories) + NSES species fix

Catalogue-wide standardisation sweep against `Reference_Guides/FILE_FORMAT_STANDARDS.md`, then bulk re-push of all 11 SQW drafts. Reduced validator fails from 67 → 9 (the 9 are all structural gaps in Not So Efficient Studying's incomplete folder build).

**Fixes applied (in order of severity):**

| Fix | Files | Stories |
|---|---|---|
| Subtitle separator `—` → `:` to match story.json | 58 | 10 |
| Duplicate section breaks removed (`<p>* * *</p>` + `<p><strong>~ End ~</strong></p>`) | 18 | 9 |
| Duplicate plain front matter deleted after warning-page div | 6 | 6 |
| em-strong narrative bolding fixed (Hypnotic text messages + Extra Credit labels) | 14 | 2 |
| Missing `#workskin em` CSS rule added | 2 | 2 (Chosen + Silk) |
| **Not So Efficient Studying species fix** — Mack was described as "bull terrier" in story.json description + summary; he's a **rat** (confirmed from MASTER.md) | 1 | 1 |

**New helper scripts** (under `m_x/Scripts_Utils/`):
- `fix_sqw_subtitle_separator.py` — reads story.json chapter_info titles and replaces mismatched h2 text in SQW chapter files
- `fix_sqw_duplicate_front_matter.py` — detects and deletes plain-paragraph title/byline/warning blocks that appear after the warning-page div
- `fix_sqw_duplicate_section_breaks.py` — removes plain `<p>* * *</p>` lines that duplicate a styled `<p class="section-break">`, and plain `<p><strong>~ End ~</strong></p>` that duplicate a styled `<div class="story-end">`
- `validate_story.py` — validates any story folder against FILE_FORMAT_STANDARDS.md rules (folder structure, MASTER.md asterisk balance, story.json fields, SQW body anti-patterns, CSS selectors, styled HTML chapter headings, div balance). Run `python validate_story.py --all` for a full sweep.

**Standards document**: `Reference_Guides/FILE_FORMAT_STANDARDS.md` — comprehensive rules for all 13 file types with required structure, anti-patterns, cross-story consistency rules, and a validation checklist.

**SQW push**: All 11 stories re-pushed via `tests/edit_sqw_after_fixes.py --apply --yes`. Total edit time ~330s. All draft states preserved (verified by poster safety checks).

---

## [2.3.15] - 2026-04-09

### Fixed — SquidgeWorld bulk re-edit after body normalisation pass (5 stories)

Pushed local SquidgeWorld body fixes live to 5 existing draft works. The fixes covered five distinct bug categories the user surfaced after browsing the drafts:

1. **Velvet and Vice** — chapter labels in all 9 SQW chapter HTML files were `Chapter X — Title` matching the file index, but the canonical labels (per the styled HTML) are `Prelude: Threads Unraveling` then `Chapter 1: Callum`, `Chapter 2: Sierra`, ..., `Chapter 8: Communion` (offset by 1). Plus Velvet's `Work_Skin.css` had no `.chapter-subtitle` selector, so every h2 fell back to default browser styling (left-aligned, plain bold) instead of the canonical centred small-caps Georgia. Plus chapter 1's warning page was missing the `warning-heading`/`warning-body` paragraphs and had a duplicate plain front matter block below the div. Fixed all three.

2. **Drumheller Detour** — chapter 1 warning page had only the disclaimer (no actual content warning text), with the real warning content dumped as plain `<p><em>...</em></p>` paragraphs immediately below the div. Restored the canonical warning-heading/warning-body inside the div, deleted the duplicate plain block.

3. **Ruins of Breeding** — 46 narrative paragraphs across 6 chapters had `<em><strong>X</strong> Y <strong>Z</strong></em>` artefacts from an old converter mishandling nested italics. The script `m_x/Scripts_Utils/fix_sqw_em_strong_bolding.py` parses MASTER.md as ground truth and re-renders each affected line as alternating italic/roman segments using a small Python parser (`parse_italic_alternation` + `md_line_to_html`). Plus deleted Ruins ch1's duplicate plain front matter block.

4. **Overtime** — already fixed locally yesterday (print-container strip + `chapter-heading` → `chapter-subtitle` rename via `normalize_sqw_print_container.py`). Pushed via this pass. Chapter headings now render centred italic in the work skin (the rename made the existing `.chapter-subtitle` rule apply).

5. **Tombstone** — same as Overtime, fixed locally yesterday, pushed in this pass.

### New helper scripts (under `m_x/Scripts_Utils/`)

- **`normalize_sqw_print_container.py`** — strips vestigial `<div class="print-container">` outer wrapper from Overtime + Tombstone SQW chapters and renames `<h2 class="chapter-heading">` → `<h2 class="chapter-subtitle">`. Verifies div balance pre/post. Idempotent. Backups at `*.sqw-bak`.
- **`fix_sqw_em_strong_bolding.py`** — Ruins-only narrative bolding fix. Reads MASTER.md, finds each `<p>` paragraph in the SQW chapter HTML containing `<em><strong>` patterns, looks up the corresponding MASTER.md line by text signature (HTML tags + `*` markers stripped, whitespace collapsed), then re-renders the line as alternating italic/roman segments. 46 paragraphs fixed across 6 Ruins chapters with 0 no-match. Restricted to Ruins because other stories use `<em><strong>` legitimately for chat-message styling (Drumheller, Hypnotic), POV markers (Velvet `⟨ Sierra ⟩`), and story-title references.

### New test script

- **`tests/edit_sqw_after_fixes.py`** — drives `SquidgeWorldPoster.edit()` for the 5 affected stories. Looks up each work_id by matching the local title against the user's SQW drafts + published lists, then runs `edit()` per story (which auto-detects draft state, preserves it, refreshes the work skin, edits metadata, iterates all chapters, and verifies state didn't flip). Single-story mode via `--story <folder>`, batch via no flag. Dry run by default; `--apply` to push.

### SquidgeWorld results

| Story | work_id | Edit time | Notes |
|---|---|---|---|
| Velvet and Vice | [91397](https://squidgeworld.org/works/91397) | 45.5s | CSS rule + 9 chapter labels + ch1 warning rebuild |
| Drumheller Detour | [91391](https://squidgeworld.org/works/91391) | 39.1s | ch1 warning page rebuilt, duplicate plain block deleted |
| Ruins of Breeding | [91395](https://squidgeworld.org/works/91395) | 33.0s | 46 narrative paragraphs cleaned, ch1 dup deleted |
| Overtime | [91394](https://squidgeworld.org/works/91394) | 26.4s | print-container strip + class rename, headings now centred |
| Tombstone | [91390](https://squidgeworld.org/works/91390) | 22.4s | same as Overtime |

All 5 still in draft state post-edit (verified by `SquidgeWorldPoster.edit()`'s built-in safety check). Total edit time across all 5: 166.4s.

---

## [2.3.14] - 2026-04-09

### Added — Story detail page enrichment (Batch 3 of 3): sparklines, comparison chart, timeline, format downloads

Final batch of the story detail page overhaul. Adds the analytics tier: per-pub sparklines, a Chart.js comparison overlay, a publication timeline, format file metadata + direct downloads, and a best-performer badge. Completes the brainstorm from the Drumheller Detour screenshot session.

**Backend:**

- **Per-pub snapshots in `get_story_detail`.** New `_SNAP_TABLES` mapping in the route handler keys each platform to its snapshot table + primary metric (`snapshots.views`, `fa_snapshots.views`, `sqw_snapshots.hits`, `wp_snapshots.reads`, `ik_snapshots.likes`, etc.). For each pub we query the last 30 days of snapshots (capped at 60 points) and attach them as `pub.snapshots = [{t, v}]` in chronological order. Wrapped in try/except for `OperationalError` (table missing on fresh installs) and `ValueError` (TEXT vs INT id mismatch on BSKY/TW). The frontend renders these via inline SVG sparklines + a Chart.js comparison overlay.
- **`story_reader.get_format_files()` helper.** New function + new `_FORMAT_KEY_PATTERNS` dict that maps each `formats` key in `story.json` (`bbcode`, `chapter_bbcode`, `html`, `sofurry_html`, `squidgeworld`, `markdown`, `pdf`, `styled_html`) to its directory + glob pattern. For each declared format, resolves all matching files, stats them, and returns `{available, files: [{path, size, modified}]}`. The relative `path` is exactly what the new `/api/posting/file` endpoint expects in its `file` query param. `_iso_mtime()` helper converts the float mtime into a UTC ISO timestamp string.
- **`get_story_detail` now returns `formats` as the enriched dict** instead of the raw `{key: bool}` flag dict from `story.json`. The frontend uses the file metadata to render badge tooltips and download links.
- **`GET /api/posting/file?story=&file=`** — new download endpoint. Same security model as `/api/posting/image`: query params, `Path.resolve().relative_to()` traversal guard, extension allowlist. The download allowlist is wider than the image one — `.txt, .html, .htm, .md, .pdf, .json` — covering all the format files the badges link to. Sends `Content-Disposition: attachment; filename="..."` so browsers download rather than render. `Cache-Control: no-cache` because format files change frequently and a cached BBCode would be misleading.

**Frontend (`frontend/js/posting.js`):**

- **`buildSparkline(snapshots, w, h)` helper.** Pure inline SVG line chart, no Chart.js per row. SVG was chosen over Chart.js for the per-row sparklines because Chart.js per row means N canvases × N resize observers × N animation loops on the page — too much for what should be a tiny visual cue. SVG is one DOM tree per chart, no JS lifecycle. Renders polyline + a small dot on the most recent point so flat series still have a visual anchor.
- **`formatFileSize(bytes)` helper.** Bytes → "1.2 KB" / "3.4 MB" for the format download badges.
- **`PUB_CHART_COLORS`** palette — 11 colours picked to be distinct on a dark background (one per platform, modulo cycling).
- **Pub row gains a sparkline column** rendered from `p.snapshots`. Empty for fresh pubs with <2 data points (sparkline helper early-returns).
- **👑 Best-performer badge.** Computed client-side: find the pub with the highest views (or views-equivalent), tag its row. Only renders when there are 2+ pubs — best-of-one is meaningless.
- **`Posting._renderComparisonChart(pubsWithData)`** — new method that builds a Chart.js line chart in the new `#story-comparison-chart` canvas with one dataset per pub. Reads CSS custom properties (`--text-muted`, `--border`) so the chart matches the active theme. Manages its own canvas lifecycle via `canvas._ppChart` (route() doesn't clean up posting.js charts the way it does for the main app's charts, so the destroy-before-recreate pattern is local). Only renders when there are 2+ pubs with at least 2 snapshot points each.
- **Publication Timeline card.** Chronological list of post + update events, derived from the existing `first_posted_at` / `last_updated_at` columns on each pub. No new backend data needed — pure client-side aggregation. Sorted newest-first. Update events use a green dot, post events a purple one.
- **Formats card rebuilt for the enriched dict.** Each format becomes a clickable `<a class="format-link" download>` pointing at `/api/posting/file?story=&file=` with the size shown inline ("bbcode 24 KB") and full file path + modified timestamp on hover. Multi-file formats (chapter_bbcode, squidgeworld) link the first file's download and show "(N files)" instead of a single size. Formats declared in story.json but with no files on disk get rendered as a muted, non-clickable `format-empty` badge.

**CSS (`frontend/css/components.css`):**

- New: `.pub-spark` (sparkline column on pub rows, accent-colored), `.best-badge`, `.timeline-list` + `.timeline-event` + `.timeline-dot` (with `.timeline-update` variant), `.timeline-when`, `.timeline-label`. Format badges revamped: `.format-link` (clickable download with hover state), `.format-empty` (muted no-files-on-disk variant), `.format-meta` (the size span).
- Mobile breakpoint extended: sparkline scales to row width, timeline collapses the time + label into stacked rows.

**Verified:**
- `python -m py_compile routes/posting_api.py posting/story_reader.py` clean
- `node --check frontend/js/posting.js` clean
- Single round-trip preserved: still one request to `/api/posting/stories/{name}`. The detail page now carries cover, summary, chips, totals, change-detection, top fans, recent log, queue, snapshots, format metadata — all in one response. The format download endpoint is hit only on click.
- Chart.js lifecycle: `_renderComparisonChart` destroys any existing chart on the canvas before recreating, so navigating away and back doesn't leak.
- Path traversal: `/api/posting/file` rejects `../etc/passwd` style paths via the same `relative_to()` guard the image endpoint uses, plus the wider extension allowlist still excludes `.py`, `.sh`, `.exe`, etc. — no arbitrary file exfiltration from the story folder.

**Not done in this version:**
- Did NOT add zoom/pan to the comparison chart. Chart.js zoom is a separate plugin and the 30-day window is small enough that fixed scale is fine.
- Did NOT add metric selector (views vs faves vs comments) to the comparison chart. Hardcoded to views (or views-equivalent per platform). Adding a metric switch would require either re-querying snapshots with a different value column or fetching all metrics up-front; out of scope for this batch.
- Did NOT add a "regenerate format files" button next to the download links. The format files are regenerated externally via the `m_x/Scripts_Utils/regenerate_story.py` workflow on the desktop, not by the dashboard. Adding a regen button would require shell-out to that script and runtime mode awareness.
- BSKY/IK/DA/TW publications: snapshots queries should work for these now since we added them to `_SNAP_TABLES`, but they still don't have stats populated by `get_publications_with_stats` (separate `stat_tables` dict in `posting_queries.py` doesn't have entries for them). Worth aligning the two dicts in a future change.

### Wraps up the story detail page enrichment series

This is the third and final batch of the detail page overhaul started in 2.3.12 and continued in 2.3.13. The Drumheller Detour screenshot from the brainstorm session — a sparse page showing just title/words/chapters/2 pubs/8 chapters/6 format badges — now renders with cover image, summary, characters, relationships, cross-platform totals, sparklines per pub, change-detection badges, top fans, a comparison overlay chart, the publication timeline, recent activity log, per-platform tags accordion, and clickable format downloads. All driven by data the backend was already storing — most of the work was just surfacing it.

---

## [2.3.13] - 2026-04-09

### Added — Story detail page enrichment (Batch 2 of 3): change detection, history, queue, top fans

Continues the story detail page enrichment from 2.3.12. Adds the four cross-cutting items that needed backend work: per-publication change-detection badges, recent posting log card, pending queue callout, and IB top-fans inline. Everything still served in a single `/api/posting/stories/{name}` round-trip — the alternative would have been four separate fetches and a noticeably slower page render.

**Backend:**

- **`posting/sync.py:detect_changes()`** now accepts an optional `story_name` parameter. Without it the function still walks every publication (existing behaviour for the dashboard's `/api/posting/changes` endpoint); with it, only that story's pubs are hashed. Story-scoped detection is what `get_story_detail` actually wants — paying the cost of hashing every other story's files just to render one detail page is wasteful and would scale badly as the archive grows.
- **`database/posting_queries.py:get_queue()`** now accepts an optional `story_name` parameter. Backwards-compatible default (`None` = all queue items). Used by `get_story_detail` to surface only this story's pending items.
- **`routes/posting_api.py:get_story_detail`** is now the single round-trip backend for the detail page. It now returns:
  - `recent_log`: last 5 entries from `posting_log` filtered to this story (already supported by `get_posting_log(story_name=...)`).
  - `pending_queue`: in-flight or scheduled queue items for this story.
  - `publications[].top_fans`: for IB pubs, the 5 most recent rows from `faving_users` for that submission_id, as `[{username, first_seen_at}]`. Other platforms get an empty list. Wrapped in try/except for `OperationalError` so a fresh install without an IB poll yet doesn't crash the endpoint.
  - `publications[].change_status` and `publications[].change_detected`: per-pub output of the new story-scoped `detect_changes()`. Status is one of `changed`/`unchanged`/`file_missing`/`no_hash`. Merged onto each publication by `(chapter_index, platform)` — the unique key. Wrapped in try/except so a transient `story_reader` failure doesn't break the page.

**Frontend (`frontend/js/posting.js:renderStoryDetail`):**

- **Pending queue callout** at the top of the page (below the info card) when there are in-flight or scheduled items. Per-item lines show action / chapter / platform / status / scheduled time. Visually styled as an accented card so it can't be missed.
- **Per-pub change badges:** `⚠ stale` (yellow) when the local file hash differs from `publications.file_hash`, `? missing` (red) when the format file can't be resolved, `? no hash` (grey) when the publication was claimed retroactively without a stored hash. The "unchanged" case stays silent — no green badge — since silence is the desired default.
- **Smarter "Update All" button.** When change detection knows N pubs are stale, the button label becomes `Update Stale (N)` and switches to primary styling; otherwise it stays `Update All` in secondary styling. Communicates intent at a glance.
- **Top fans inline** on IB publication rows: a small strip below the row showing up to 5 fan-name chips drawn from `faving_users`. Empty for non-IB pubs. The full list is still available via the IB submission detail page.
- **Recent activity card** showing the last 5 posting log entries for this story. Each row displays relative time (with raw timestamp on hover), action emoji, success/failure colour, duration, and an inline link if available. Failed entries also show a truncated error message tooltip.

**CSS (`frontend/css/components.css`):**

- New: `.pending-queue-card` (accented left border), `.pending-queue-list`, `.change-badge` + `.change-stale` / `.change-missing` / `.change-unknown`, `.pub-row-wrapper` (containing div so the fan strip can sit under the row without breaking the existing border-bottom pattern), `.pub-fans` + `.fan-chip`, `.log-row` (3-column grid: time / action / status, with full-width error subline), `.log-success` / `.log-failed`, `.log-when` / `.log-action` / `.log-status` / `.log-error`.
- Mobile breakpoint extended: `.log-row` collapses to a single column and `.pub-fans` un-indents.

**Verified:**
- `python -m py_compile routes/posting_api.py database/posting_queries.py posting/sync.py` clean
- `node --check frontend/js/posting.js` clean
- Backwards compatibility: `detect_changes()` and `get_queue()` both keep their no-arg signatures working — existing callers (`/api/posting/changes`, `/api/posting/queue`) are unchanged.
- Defensive: every new field early-returns to empty when its source data is absent. Stories with no change history, no queue items, no IB pub, and no recent log render exactly as before this change.
- Single round-trip: the detail page still makes one request to `/api/posting/stories/{name}`. No extra fetches added.

**Not done in this version:**
- Did NOT add a "claim history" view to surface publications that came in via `claim_existing_submissions` (status `no_hash`) — the badge tells the user the state but there's no UI to convert them to "tracked from now on" by re-uploading. Reasonable follow-up.
- Did NOT add per-platform comment/reply user lists (FA has comments + reply users via `fa_comments`, AO3/SqW have kudos users in their own tables). Top-fans is IB-only for now because faving_users is the cleanest source. Multi-platform top-fans goes in batch 3 alongside the comparison overlay chart.
- Did NOT add a "stale chip count" badge to the listing-page story cards. Worth doing in a separate change so the listing can show "3 stories have stale publications" at a glance, but out of scope for the detail page.

---

## [2.3.12] - 2026-04-09

### Added — Story detail page enrichment (Batch 1 of 3)

The Publishing → Stories detail page (`#/posting/story/{name}`) was rendering only a fraction of what the backend already returns. `get_story_detail` was sending `summary`, `characters`, `relationships`, `tags_by_platform`, per-chapter `description` fields, and full `update_count` / `tags_used` / file-hash columns from the publications table — all dropped on the floor by the frontend. This batch wires them up.

**Frontend (`frontend/js/posting.js:renderStoryDetail`):**

1. **Cover image** at the top of the info card. Same `/api/posting/image` route + `encodeURIComponent` shape as the listing cards. Backed by the same `detect_cover_relative()` auto-detect, so stories with a thumbnail file in the folder root but no `images.cover` entry in `story.json` finally render the cover on the detail page too.
2. **Summary block.** OTW-style longer blurb (`data.summary`) rendered as a callout card below the description, but only when it differs from `data.description` — many stories duplicate the two and we don't want side-by-side identical paragraphs.
3. **Characters & relationships chips.** Two-tone pill chips (purple-bordered for characters, green for relationships) below the warnings line.
4. **Per-chapter descriptions** rendered as italic muted text under each chapter row. The data was already returned per `data.chapters[].description` — the JS just had a 3-field render loop that ignored it.
5. **Per-platform tags accordion.** Native `<details>` blocks (one per platform that has tags), sorted by tag count desc so the densest list opens first. Each platform's full tag list shown as small pills inside the `<details>` body. Collapsed by default — IB carries 100+ tags on some stories and would otherwise dominate the page.
6. **Update count badge** on each pub row. Renders `↻ N` next to the date when `p.update_count > 0`, hover shows "N updates since first post". Drawn from the existing `update_count` column on `publications` (already on the wire — `get_publications_with_stats` does `SELECT *`).
7. **Cross-platform totals strip.** New card under the info section: total views, faves, comments summed across all publications, plus a platform count. Computed client-side from `data.publications[]` with platform-aware metric resolution (views/hits/reads, favorites_count/kudos/votes) so SqW kudos and Wattpad reads roll up correctly into the same totals.
8. **Days-since timestamps.** Pub-row dates now show `Utils.timeAgo()` output ("5d ago") with the raw `last_updated_at` on hover via `title=`. Reads better than `2026-04-04 00:52:59` and survives timezone confusion since timeAgo is relative.

**Backend (`routes/posting_api.py:get_story_detail`):**

- Enriched the `images` dict in the response with `detect_cover_relative()` fallback when `story.json` doesn't declare an `images.cover`. Mirrors the fix from 2.3.11 that added the same fallback to `_story_entry()` for the listing endpoint, so the listing and detail page can never disagree about which file is the cover. Without this, the detail page would have shown no cover for stories like Drumheller Detour where the thumbnail sits in the folder root but isn't recorded in `story.json`.

**CSS (`frontend/css/components.css`):**

- New: `.story-detail-cover` (200px desktop / 140px mobile, edge-to-edge above the info body), `.story-detail-info-body` (16px padding wrapper since `.story-detail-info` is now `padding: 0` for the cover bleed), `.story-detail-summary` (callout block with accent left-border), `.story-detail-chips` + `.chip` / `.chip-character` / `.chip-relationship`, `.totals-strip` + `.totals-stat` / `.totals-value` / `.totals-label`, `.chapter-entry` (wraps the existing `.chapter-row` so the description can sit under it), `.chapter-desc`, `.update-count-badge`, `.tags-platform` + `.tag-count` + `.tag-pill`.
- Mobile breakpoint extended: detail cover scales to 140px, totals-strip switches to a 2-up grid, pub-row stacks vertically.

**Verified:**
- `python -m py_compile routes/posting_api.py` clean
- `node --check frontend/js/posting.js` clean
- All new fields render conditionally — empty data is never shown as an empty block (covers, summary, chips, tags, totals, update badges all early-return when their source data is absent).

**Not done in this version:**
- Did NOT add per-pub change-detection badges (item 7 in the original brainstorm) — that lands in batch 2 because it needs an enriched API response or a separate fetch. Same for recent posting log card, pending queue card, and IB top-fans (batch 2). Per-pub sparklines, comparison overlay, and posting cadence timeline are batch 3.
- Did NOT add an "About" accordion that combines summary + characters + relationships into a single collapsible — opted for inline rendering since the data is short and screen real estate is fine. Reconsider if it gets noisy.
- BSKY/IK/DA/TW publications still won't have `stats` populated because `get_publications_with_stats` doesn't have entries for those platforms in its `stat_tables` dict — they fall through to `pub_dict["stats"] = None` and contribute 0 to the totals strip. Worth fixing in a separate change but out of scope for this batch.

---

## [2.3.11] - 2026-04-09

### Fixed — Story cover images never rendered in the Publishing → Stories hub

The card grid in `frontend/js/posting.js:renderUpload` had cover-image markup since the page was first written, but covers never appeared. Two combining bugs:

1. **No backend route.** `posting.js:56` built `/api/posting/image/{name}/{cover}` URLs but no FastAPI handler matched — every cover request 404'd silently (the card just rendered with no `.story-card-cover` div).
2. **Listing endpoint never auto-detected covers.** `routes/posting_api.py:list_stories` calls `story_reader.list_stories()` → `_story_entry()`, which only surfaced `images.cover` when `story.json` declared one explicitly. The richer auto-detect glob (`*_thumbnail_full_series.*`, `*_thumbnail.*`, `cover.*`, `thumbnail.*`) lived inside `_load_from_story_json` and only ran on the per-story detail endpoint. So stories with a thumbnail file in the folder root but no `images.cover` entry — which is the common case in this archive — silently rendered cover-less in the listing even though the detail page would have found the same file.

**Fix:**
- New route `GET /api/posting/image?story=&file=` in `routes/posting_api.py:134-185`. Query params (not path segments) so sub-stories like `The_Abstinent_Bet/Nice_Version` and nested files like `Images/cover.png` round-trip cleanly through `encodeURIComponent` without path/segment ambiguity. Hardened with `Path.resolve().relative_to()` traversal guard, image extension allowlist, and a 1-hour `Cache-Control` header.
- Extracted `detect_cover_relative()` + `COVER_EXTENSIONS` tuple in `posting/story_reader.py:229-262`, and pointed both `_story_entry()` and `_load_from_story_json()` at it. Listing and detail can no longer drift.
- `frontend/js/posting.js:55-63` now uses the query-param URL with `encodeURIComponent` for both `story` and `file`.

**Verified:**
- `python -m py_compile posting/story_reader.py routes/posting_api.py` clean
- Route registration check: `posting_router.routes` shows `/api/posting/image` registered (20 total routes)
- Path traversal: `(story_root / "../../../etc/passwd").resolve().relative_to(story_root)` raises `ValueError` → caught and returned as HTTP 403
- Extension allowlist: rejects anything outside `{.png, .jpg, .jpeg, .gif, .webp}` with HTTP 415

**Not done in this version:**
- Did not add a frontend fallback placeholder image for stories that genuinely have no cover (the card just renders without the `.story-card-cover` div, which is the existing graceful-degradation path).
- Did not update `documentation_guide.md` to mention the new route — the route is implementation detail rather than architecture, and the existing "Posting Module → Story Detail" section already documents the listing behaviour at the right level.

### Process note (for future me)

This session also surfaced that I'd been merging code changes without a CHANGELOG entry. The CHANGELOG is load-bearing here — `documentation_guide.md` cross-references entries by version (e.g. "see CHANGELOG 2.3.4") to explain *why* code looks the way it does. Going forward: every PawPoller code change ships with a versioned CHANGELOG entry plus the full deploy workflow (build → commit → push → `pawupdate`).

---

## [2.3.10] - 2026-04-09

### Fixed — stray markdown asterisks in styled HTML files (47 across 4 stories)

While verifying the FA Hypnotic + Silk submissions after the metadata + PDF replacement work in [2.3.9], spotted that Silk Chapter 2 was rendering literal `*` characters in the body text on FA. Investigation showed:

- **Bug pattern in styled HTML**: `<em>*Text...</em>` (leading `*` inside an italic opener), `<em>*</em>` (orphan italic with just an asterisk), `*</em>` (trailing `*` before closer). All three are leftover markdown italic markers from an old converter mishandling unmatched `*` in the source.
- **Root cause in MASTER.md**: 46 lines in Silk Threaded Bonds alone have unmatched asterisk counts — opening `*italic narration*` markers that were never closed (forgotten end-of-paragraph `*`) or stray closing markers left from edits. Other stories have a handful too: Hypnotic (4), Extra Credit (4), Ruins of Breeding (5).
- **Why this didn't affect BBCode/SoFurry HTML**: those were regenerated using the converter fix from [2.2.1] which correctly handles nested asterisk emphasis. The styled HTML files are manually maintained per workflow rule, so they never got the converter fix re-applied.

**Total bug count fixed**: 47 stray markers across 11 styled HTML files (5 Silk per-chapter + 1 Silk full + 2 Hypnotic + 2 Extra Credit + 2 Ruins = correct on close inspection — Silk full was already clean from yesterday's chapter-heading fix pass).

**Tooling added**: `m_x/Scripts_Utils/strip_stray_em_asterisks.py` — applies the 3-pattern cleanup to a list of styled HTML files. Idempotent. Returns 0 if all files end up clean. Used in this session against all 9 affected files in one batch.

**Plus one manual fix**: Ruins of Breeding `Chapter_2_The_Temple.html` had a standalone `*read*` markdown emphasis in dialogue that the original converter missed entirely (different bug class — bare `*word*` standalone emphasis not wrapped in narration italic). Manually replaced with `<em>read</em>`.

**FA submissions re-pushed after the fix** (5 of the 7 — Silk ch2 was already done in the session's first push, Hypnotic Part 2 wasn't affected):
- Hypnotic Part 1 (64274343)
- Silk Ch 1 (64284286)
- Silk Ch 3 (64284355)
- Silk Ch 4 (64284453)
- Silk Ch 5 (64284497)

**Verified live on FA** by downloading each PDF, extracting text via pypdf, counting literal `*` characters across all pages. Result: **0 asterisks across all 7 submissions, 74 pages of story text total.**

### Local-only fixes (not pushed because not on FA yet)
- Extra Credit: 4 stray asterisks fixed
- Ruins of Breeding: 4 stray asterisks + 1 standalone `*read*` fixed

These will be uploaded with clean PDFs whenever the stories get drip-posted to FA via the upcoming `bulk_fa_posts.py` flow.

### Documentation
- Per-story changelog updates for Silk, Hypnotic, Extra Credit, Ruins
- Note about MASTER.md authoring inconsistency (46 unmatched asterisk lines in Silk alone). The styled HTML files are now in their canonical clean state — the bug only re-emerges if you run the OLD converter against the still-broken MASTER.md. Future Layer 2 fix: clean up MASTER.md so any future regeneration is also clean.

### Not done in this version
- MASTER.md asterisk cleanup (Layer 2 — author-facing fix). Currently planned as a manual pass requiring careful per-line judgement (italic intent vs stray markers vs nested italic vs bold conventions like `**Dev:**` chat names that are intentional).

---

## [2.3.9] - 2026-04-09

### Added — FurAffinity edit-existing flow + per-chapter description prefix

Two new test scripts and one library improvement, in service of bringing the existing FA submissions for Hypnotic Claim and The Silk-Threaded Bonds in line with the regenerated PDFs and refreshed `story.json` metadata.

**`tests/verify_fa_edit_existing.py`** — verify (and optionally apply) metadata edits + PDF file replacements on existing FA submissions.

- **Default mode is read-only**: fetches the current FA state via FAExport, builds a fresh package via `build_package`, and prints a diff (title, description, tags, rating). Exits without writing anything.
- **`--apply`** flag: actually performs edits via `FurAffinityPoster.edit()` (changeinfo endpoint).
- **`--update-file`** flag: ALSO replaces the source PDF via `FurAffinityPoster.replace_file()` (changestory endpoint), 2-second pause between metadata edit and file replacement.
- **`--skip-tags`** flag: preserve existing FA tags (path A: SEO/act-focused tags work better for FA discovery than the new atmospheric/character set the build_package would produce).
- **`--skip-rating`** flag: preserve existing rating.
- **`--story <name>`** filter: substring-match by story name.
- **`--yes`** flag: skip the typed confirmation prompt (for scripted runs).
- **Hard typed confirmation prompt** before any write: must type exactly `EDIT N LIVE FA SUBMISSIONS` (with the right N) — no other input proceeds.
- **Hardcoded fallback list of 7 known FA submissions** (Hypnotic 2 + Silk 5) so the script works locally without needing the server's publications DB.
- **Inter-edit delay: 3 seconds** (NOT 70). Empirically confirmed FA's 70-second rate limit applies to *new submissions only*, not edits — see "FA edit rate limit" finding below.

**`tests/fa_changestory_canary.py`** — single-submission canary test of the changestory endpoint flow. Reads the current submission state, calls `replace_file()`, re-reads to confirm the download URL changed. Used to validate the existing `FurAffinityPoster.replace_file()` code path before extending the bulk script. Confirmed working end-to-end on Hypnotic Part 1 (FA 64274343).

**`posting/story_reader.py`** — `build_package()` now prepends a `Chapter X of N. ` or `Part X of N. ` navigation prefix to per-chapter FA descriptions. Auto-detects "Part" vs "Chapter" from the chapter title in `story.json` so Hypnotic Claim (which uses "Part 1" / "Part 2") gets `Part 1 of 2. <description>` while normal stories get `Chapter X of N. <description>`. The prefix is only added for FA platform packages with `chapter_index > 0`.

### Empirically confirmed — FA's 70-second rate limit is for new submissions, not edits

The FA poster's `min_post_interval = 70` constant is correctly named — it applies to new uploads (changeinfo endpoints don't have the same throttle). Two batches of edits performed in this session:

- **Hypnotic Claim batch**: 2 metadata edits + 2 file replacements, ~10s total wallclock
- **Silk Threaded Bonds batch**: 5 metadata edits + 5 file replacements, ~25s total wallclock with 3-second pauses

No 429s, no rate-limit errors. The previous 70s sleeps in `verify_fa_edit_existing.py` were a precautionary copy from the upload constraint and have been removed. New constant: `FA_RATE_LIMIT_SECONDS = 3`.

### FA submissions updated this session (live writes)

| Submission | Story | What changed |
|---|---|---|
| 64274343 | Hypnotic Claim Part 1 | title (em-dash + Part), description (rewritten + prefix), PDF (regenerated with proper warning page) |
| 64274371 | Hypnotic Claim Part 2 | same |
| 64284286 | Silk Threaded Bonds Ch 1 | same (Chapter prefix) |
| 64284325 | Silk Threaded Bonds Ch 2 | same |
| 64284355 | Silk Threaded Bonds Ch 3 | same |
| 64284453 | Silk Threaded Bonds Ch 4 | same |
| 64284497 | Silk Threaded Bonds Ch 5 | same |

**Tags + rating preserved on all 7** (path A — kept the existing SEO/act-focused tag sets that work for FA's tag-search). **Thumbnails not touched.**

For Silk specifically, the per-chapter PDFs were regenerated TWICE this session — first as part of the bulk regeneration that landed yesterday, then a second time after a follow-up fix to the per-chapter Styled HTML files (see story-side changelog for The Silk-Threaded Bonds). The second regeneration was triggered by spotting that Silk's per-chapter chapter-heading rendered as default browser h2 instead of the canonical centred Cormorant Garamond small-caps form. The per-chapter Silk Styled HTML files had `<h2 class="chapter-heading">` markup but no CSS rule for it.

### Documentation updates
- `m_x/Archives/Complete_Stories/Hypnotic_Claim/CHANGELOG.md` — full FA sync entry
- `m_x/Archives/Complete_Stories/The_Silk_Threaded_Bonds/CHANGELOG.md` — full FA sync entry + the per-chapter Styled HTML follow-up fix
- `m_x/Archives/Complete_Stories/The_Silk_Threaded_Bonds/CHAPTER_STYLING.md` — addendum documenting the per-chapter `.chapter-heading` rule fix
- `m_x/Archives/Complete_Stories/Hypnotic_Claim/story.json` — `chapter_info[].title` confirmed as `"Part 1: ..."` / `"Part 2: ..."` (briefly flipped to "Chapter" then reverted — Part is canonical)
- `m_x/Archives/Complete_Stories/The_Silk_Threaded_Bonds/story.json` — `title` field hyphen restored (`"The Silk Threaded Bonds"` → `"The Silk-Threaded Bonds"`); all 5 `chapter_info[].description` fields rewritten to ~half length

### Not done (intentionally)
- The 11 stories not yet on FA still need bulk-posting via a `bulk_fa_posts.py` script (not written yet — drip-feed strategy preferred over bulk-and-done)
- Tags on the 7 existing FA submissions are deliberately stale relative to what `build_package` would produce — the new tag set is more atmospheric/character-driven and would hurt FA discoverability

---

## [2.3.8] - 2026-04-08

### Fixed — CF Worker proxy was stripping Content-Type, silently breaking every body-bearing request

The Cloudflare Worker at `pawproxy.knaughtykat01.workers.dev` had a long-standing bug in `buildHeaders()` that stripped both `Content-Type` and `Content-Length` from every forwarded request. The bug was discovered while wiring up server-side SF posting:

- **Polling never noticed** because polling is GET-only — no request body, no Content-Type to forward, no boundary= parameter to lose.
- **Posting from local always worked** because the proxy is bypassed when `cf_worker_url` is empty in settings — and PawPoller's local dev settings.json has it empty.
- **Posting from the GCP server** was the first scenario where the proxy actually had to forward POST/PUT bodies. Every body-bearing request would arrive at the target site with no `Content-Type`, causing JSON / form-urlencoded / multipart bodies to be unparseable. SF/AO3/SQW posting via proxy would have been silently broken.

**Reproduced before fixing** with `tests/cf_proxy_content_type_repro.py` — sent a JSON POST through the proxy to `httpbin.org/post` (which echoes back the headers it received) and confirmed `target received Content-Type: None`.

**Fix in `deploy/cf-worker.js:buildHeaders()`:**
- Strip ONLY `host` (we set our own per-target) and `cookie` (we manage cookies in our own jar so domain-matching works through the workers.dev → real-target hop)
- **Preserve `Content-Type`** — it's a property of the request body, not the connection. Multipart bodies in particular MUST keep their `boundary=` parameter or the body is unparseable
- **Strip `Content-Length`** — Cloudflare Workers' inner `fetch()` recomputes the length from the body itself (or uses chunked encoding for streams). Forwarding the original Content-Length from the outer client→worker request would set a stale value that may not match what the worker actually streams to the target
- Long history-note comment in the source warning the next person not to add Content-Type back to the strip list
- Login flow's `extraHeaders: {'Content-Type': 'application/x-www-form-urlencoded'}` override still works because `Headers.set()` replaces existing values

**Also fixed: redirect path stale headers.** When the worker follows a redirect, it converts to GET method. The original Content-Type and Content-Length from a POST/PUT would still be in the headers built by `buildHeaders` and would be misleading (or rejected by strict servers) on a body-less GET. Added an explicit `redirHeaders.delete('content-type'); redirHeaders.delete('content-length')` in the redirect loop.

**Verified end-to-end:**
1. `tests/cf_proxy_content_type_repro.py` flipped from `[BUG]` to `[OK]` — `Content-Type: application/json` now forwarded correctly
2. `tests/sf_proxy_post_smoke.py` posted Tombstone as Private through the proxy from inside the GCP container (multipart upload, JSON metadata, full 3-step REST flow). Submission `myw0PxW1` created with `privacy=1 (Private)`, 75 tags, 2.1s end-to-end (basically as fast as direct local posting). Cleaned up afterwards.

**This unblocks server-side posting on every platform that uses bodies:**
- **SoFurry** — JSON + multipart, both confirmed working through proxy
- **SquidgeWorld** — form-urlencoded, OTW Archive (uses the same Rails form pattern as AO3, will work through proxy if needed; SQW doesn't strictly need the proxy from GCP but the path is now available)
- **AO3** — form-urlencoded, currently runs from GCP without the proxy and works most days; the proxy is now a viable fallback if AO3 starts blocking GCP IPs
- **DeviantArt** — JSON over OAuth2, currently the only platform that NEEDS the proxy from GCP. Bug was definitely affecting any DA POST attempts.

### Deployment

- `deploy/cf-worker.js` — patched `buildHeaders()` (preserve Content-Type, strip Content-Length) + redirect-path Content-Type/Length cleanup + long history-note comment
- `deploy/wrangler.toml` — added minimal wrangler config so future deploys can use `npx wrangler deploy` from `PawPoller/deploy/`
- Deployed via `npx wrangler deploy` to the `knaughtykat01@gmail.com` Cloudflare account (the one that owns the `knaughtykat01.workers.dev` subdomain). Initial deploy attempt landed on the wrong account because `wrangler login` had logged into a different identity — fixed by `wrangler logout` + `wrangler login` and picking the right account in the OAuth flow.

### Test files
- `tests/check_cf_proxy_state.py` — audit `cf_worker_url`/`cf_worker_key` settings and report which mode the SF poster would pick
- `tests/cf_proxy_content_type_repro.py` — reproduces the bug against `httpbin.org/post` (read-only deterministic regression test)
- `tests/sf_proxy_post_smoke.py` — server-side SF posting smoke test that exercises multipart upload through the proxy
- `tests/sf_delete_proxy_test_dup.py` — cleans up the duplicate Tombstone draft created by the smoke test

---

## [2.3.7] - 2026-04-08

### Added — SoFurry draft mode + bulk drafting

SoFurry now supports the same draft pattern as IB / SQW / AO3. SF has built-in privacy levels (1=Private, 2=Unlisted, 3=Public) so this is a real first-class draft state — owner-only visibility — not a workaround.

**6 SF drafts** (single-bulk-file convention via `HTML/<Story>_Clean.html`, all Private/owner-only):

| Story | Submission | Words |
|---|---|---|
| Tombstone | [nLrR4PBe](https://sofurry.com/s/nLrR4PBe) | 8,414 |
| Chosen | [m0KjxlKe](https://sofurry.com/s/m0KjxlKe) | 15,958 |
| Not_So_Efficient_Studying | [ePdyAZ5e](https://sofurry.com/s/ePdyAZ5e) | 13,602 |
| Overtime | [1xJGPWZm](https://sofurry.com/s/1xJGPWZm) | 11,513 |
| Ruins_of_Breeding | [nd4Pol7n](https://sofurry.com/s/nd4Pol7n) | 24,457 |
| The_Haunting_Desires | [mXB73JG1](https://sofurry.com/s/mXB73JG1) | 30,480 |

After this run, every local story is now on SF — 7 live published works + 6 new private drafts. Drafts are recorded in the publications table on the server with `status=draft`.

**SF posting was *fast*** — 2-3 seconds per submission, vs AO3's 20-150 seconds with retries. SoFurry's 3-step REST API (PUT empty → POST file → POST metadata) is much cleaner than OTW Archive's CSRF form scraping.

**`SoFurryPoster.post()` refactor:**
- New `_normalize_privacy()` helper that accepts ints (1/2/3) or strings ("private"/"unlisted"/"public") and maps to SF's numeric codes
- `package.extra["draft"] = True` → `privacy=1` (Private, owner-only) — same convention as IB/AO3
- `package.extra["privacy"] = 1|2|3` for explicit override (wins over draft)
- Default: `privacy=3` (Public) — preserves the existing behaviour for callers who don't set anything
- Post-flight verification: hits `/ui/submission/{id}` raw and confirms `privacy=1` server-side after a Private draft. Logs a warning if the server returns something else (defensive — `create_submission` has the privacy parameter wired correctly so this should never fire, but better to know).

### Fixed — `sf_client.edit_submission` was silently downgrading every edited work to Private

A pair of cascading bugs in `sf_client/client.py:edit_submission`:

1. **It used `get_submission_detail()` to fetch current state.** That helper strips the response down to public-facing fields (title, description, rating, etc) and **does not return `privacy`, `category`, `type`, or any of the other write-only metadata fields**. So `current.get("privacy")` always returned `None`.

2. **The fallback default was wrong.** When `current.get("privacy", 1)` returned the fallback, it returned **`1` (Private)** — the *least permissive* option. So every single edit silently overwrote whatever the work's actual privacy was with Private.

**Caught this the hard way:** while retrying the 4-day-old failed `Hypnotic_Claim` edit, the edit went through and reported success — then a follow-up fetch showed `privacy: 1` (Private). Hypnotic Claim had been a public live work for weeks. The script then ran an emergency restoration script that fetched the raw JSON, set `privacy=3` explicitly, and posted back, restoring the live state within 60 seconds of the regression.

**Why no other live works were affected:** the `failed` row in `publications` for Hypnotic_Claim shows the original 2026-04-04 edit failed with `"SoFurry login failed"` — i.e. it errored out at the *auth* step before reaching the metadata POST. So the buggy code path never actually fired in production, and the 7 live works on SF stayed Public. My retry today was the **first time the bug actually executed end-to-end**, and it was caught and rolled back inside the same script run.

**The fix:**
- `edit_submission` now fetches the **raw** `/ui/submission/{id}` JSON directly (not the stripped helper), so the merge sees every field on the server
- The fallback for `privacy` is now `current.get("privacy", 3)` — defaulting to Public is the safer choice when the field is somehow missing
- Added an explicit `privacy: int | None = None` parameter to `edit_submission` so callers can override (used by `SoFurryPoster.edit()` when `extra["draft"]` or `extra["privacy"]` is set)
- A long docstring on the method warns the next person not to substitute `get_submission_detail()` back in

**Audit confirmed all 13 SF works are in correct state:**
| 7 live works | privacy=3 (Public) ✓ |
| 6 new drafts | privacy=1 (Private) ✓ |

### Test files
- `tests/sf_smoke.py` — login + CSRF read-only check
- `tests/verify_sf_draft.py` — Tombstone canary draft with raw-JSON privacy verification
- `tests/bulk_sf_drafts.py` — bulk draft 5 missing stories (Tombstone already drafted)
- `tests/sf_retry_hypnotic_edit.py` — retry the 4-day-old failed edit
- `tests/sf_emergency_restore_hypnotic.py` — emergency restoration script (used once to undo the privacy regression)
- `tests/sf_audit_all_privacy.py` — full audit of expected vs actual privacy state for every known SF submission
- `tests/sf_mark_hypnotic_posted.py` — mark the publications row from `failed` back to `posted`

---

## [2.3.6] - 2026-04-08

### Fixed — `pawsync.bat` rewritten in Python after intermittent batch hang

The original `pawsync.bat` had two intermittent gotchas that survived three rounds of patching:

1. **Windows tar's `Cannot connect to C:` silent failure.** Windows tar (libarchive port) interprets `C:\\...` paths as remote SSH hosts unless given `--force-local`. Without it the pack would silently fail and the script would still upload whatever stale tarball was left in `%TEMP%` from the previous run — which we caught the hard way when [2.3.4]'s pawsync uploaded an Apr-6 archive 2 days after the fact.

2. **gcloud-from-batch hang.** When `gcloud compute scp` was invoked from inside a `.bat` file (vs interactively or via `cmd /c "..."`), it would silently hang somewhere after the upload reached 100% — never reaching the next command, never returning control to cmd.exe, no visible processes left running. The same gcloud command worked fine in every isolated test (interactive cmd, inline `cmd /c`, with or without `--quiet`, with or without `< nul` stdin redirect, with `--quiet` as top-level flag vs subcommand flag — none of those workarounds dislodged the hang in `.bat` context).

**Resolution: rewrote `deploy/pawsync.bat` in Python** as `deploy/pawsync.py` with a 3-line `.bat` wrapper that just calls `python pawsync.py %*`. Python sidesteps both bugs:

- **Pack via `tarfile` module** instead of Windows tar — cross-platform, no `--force-local` gotcha, no path interpretation surprises, and cleanly skips `Backups/`, `Drafts/`, `Styled_HTML/` via a name filter.
- **scp + ssh via `subprocess.run`** with `stdin=subprocess.DEVNULL`, `capture_output=True`, `shell=True` (needed on Windows so the OS resolves `gcloud.cmd`), explicit `timeout=600` for upload and `timeout=300` for extract. Zero ambiguity about stdio inheritance, deterministic exit code propagation, no batch context to confuse the wrapper.
- Uses `kithetiger@pawpoller` consistently for both scp and ssh (was previously mismatched — scp uploaded as `kithetiger`, default `gcloud ssh` ran as your Google identity user, which couldn't `rm` the kithetiger-owned file in `/tmp` due to the sticky bit).
- Aborts on any failure with a non-zero exit code (no silent stale uploads).

**One-time server cleanup applied during the rewrite:**
The server's `/home/kithetiger/story-archive/` files were owned by `rhysc` (my Google account user from previous extracts). After switching the new pawsync to extract as `kithetiger`, the first run hit `tar: Cannot open: File exists` because tar can't overwrite files owned by another user. Fixed with a one-shot `sudo chown -R kithetiger:kithetiger /home/kithetiger/story-archive`. All subsequent syncs work cleanly.

### File changes
- `deploy/pawsync.py` — new Python script (185 lines) that does the full pack-upload-extract-cleanup pipeline
- `deploy/pawsync.bat` — replaced 30-line batch script with 3-line wrapper that calls `python pawsync.py %*`

---

## [2.3.5] - 2026-04-08

### Added — AO3 Refactor + Bulk Drafting

Brought the Archive of Our Own client and poster up to par with the SquidgeWorld stack and bulk-drafted the entire local catalogue (13 drafts) on AO3.

**13 AO3 drafts** (every local story, all in preview/draft state, none published):

| Story | Work ID | Words |
|---|---|---|
| Tombstone | [82711601](https://archiveofourown.org/works/82711601/preview) | 8,414 |
| Chosen | [82712456](https://archiveofourown.org/works/82712456/preview) | 15,958 |
| Drumheller_Detour | [82712566](https://archiveofourown.org/works/82712566/preview) | 10,062 |
| Hypnotic_Claim | [82712801](https://archiveofourown.org/works/82712801/preview) | 9,809 |
| Not_So_Efficient_Studying | [82712821](https://archiveofourown.org/works/82712821/preview) | 13,602 |
| Overtime | [82712896](https://archiveofourown.org/works/82712896/preview) | 11,513 |
| Ruins_of_Breeding | [82712911](https://archiveofourown.org/works/82712911/preview) | 24,457 |
| The_Haunting_Desires | [82713001](https://archiveofourown.org/works/82713001/preview) | 30,480 |
| The_Silk_Threaded_Bonds | [82713066](https://archiveofourown.org/works/82713066/preview) | 13,904 |
| Velvet_And_Vice | [82713131](https://archiveofourown.org/works/82713131/preview) | 73,068 |
| Extra_Credit | [82713211](https://archiveofourown.org/works/82713211/preview) | 24,433 |
| The_Abstinent_Bet — Nice Version | [82713236](https://archiveofourown.org/works/82713236/preview) | 15,767 |
| The_Abstinent_Bet — Naughty Version | [82713271](https://archiveofourown.org/works/82713271/preview) | 9,704 |

All 13 are recorded in the publications table on the server with `status=draft`. Each is the canonical single-bulk-file shape (full story body HTML in one chapter, matching the IB convention) sourced from `HTML/<Story>_Clean.html`.

### Fixed — `ao3_client/client.py` was a pre-SQW codebase with multiple critical bugs

Before this session, the AO3 client was missing every refinement that landed on `sqw_client/client.py` over the past month. `create_work` was effectively broken — it would have failed validation if anyone tried to use it. The full list of fixes:

**1. `_get_page` retries on timeout/525.** AO3 from datacenter IPs sees frequent `ReadTimeout` and `525 origin SSL handshake fail` responses (about 1 in 5 requests). The previous implementation caught the exception, logged with an empty `str(e)` (the user saw `"AO3: Failed to fetch ...: "` with nothing after the colon), and gave up. Now retries 3 times with backoff, distinguishes 525s from timeouts in the logs, and still preserves a clean error path for hard failures (403/404/etc).

**2. `create_work` rewritten to mirror SQW's pattern.** The previous version sent:
```python
"work[archive_warning_string]": warning,    # SINGULAR — wrong field name
"work[category_string]": category,          # SINGULAR — wrong field name
# missing: work[author_attributes][ids][]   # REQUIRED — pseud_id
# missing: work[work_skin_id]
# missing: work[wip_length]
```
Now uses the correct OTW Archive form fields:
```python
"work[author_attributes][ids][]": pseud_id,            # extracted from /works/new HTML
"work[archive_warning_strings][]": warnings_array,     # plural with hidden empty value
"work[category_strings][]": categories_array,          # plural
"work[work_skin_id]": skin_id,
"work[wip_length]": "1",
"preview_button": "Preview",
```

The pseud_id extraction is critical — every OTW work must be linked to at least one author pseud via `work[author_attributes][ids][]`. Without it the form silently rejects with "Sorry! We couldn't save this work because: ...". The pseud is unique per user and is embedded in the `/works/new` HTML.

**3. `language_id="en"` was wrong.** AO3's form expects the numeric language ID (1 = English), not the ISO code "en". The previous code's "en" produced a server-side validation error: `"Language cannot be blank."` which was the first thing the new client hit even after the form-fields fix. Default is now `"1"`.

**4. Added `delete_work`, `is_work_in_drafts`, `is_work_published`.** Direct ports of the SQW versions. Critical for safety — without `delete_work` we can't auto-clean if a draft test goes wrong. Mirror the SQW confirm_delete flow (`_method=delete` + `commit=Yes, Delete Work`).

**5. State checks return tri-state (`True | False | None`).** AO3's `/users/<user>/works/drafts` page is **slow and times out frequently**. The SQW versions return `False` on fetch failure, which would cause the post-flight safety check to spuriously fire `not in_drafts` and try to delete healthy drafts. The AO3 versions distinguish:
- `True`  — fetched and present
- `False` — fetched and not present
- `None`  — fetch failed (network/timeout/CF) — caller cannot conclude

### Added — Smart safety logic in `AO3Poster.post()`

The post-flight verifier in `_verify_still_draft` was rewritten to handle AO3's flakiness:

```python
in_published = await client.is_work_published(work_id)
if in_published is True:
    # Confirmed published — abort + delete
elif in_published is None:
    # Fetch failed — trust preview_button (which guarantees draft state)
    logger.warning(...)
# in_published is False -> definitely safe
```

Before this fix, the first bulk-draft test ran into a real disaster:
1. `create_work` actually succeeded (work `82710971` created in preview state)
2. Post-flight `is_work_in_drafts` timed out 3 times → returned `None` (wrongly interpreted as `False`)
3. `is_work_published` also timed out → returned `False`
4. Safety check: `not in_drafts == True` → triggered abort
5. Auto-delete `delete_work(82710971)` was called
6. `delete_work` ALSO timed out and threw an exception with empty `str()`
7. The script reported `"DELETE FAILED: ."` and exited

The new logic only aborts on **positive** confirmation that the work is published. Since `create_work` exclusively uses `preview_button` (no `post_button` path exists in our client), publication is impossible by construction. Fetch failures are now logged-and-trusted.

### Added — `posting/platforms/ao3.py` rewritten as a SquidgeWorldPoster mirror

The previous `AO3Poster` was 187 lines of legacy minimal-viable code: no draft mode, no fandom passthrough, no warnings/categories/characters/relationships, no tag truncation, no safety checks, no publications tracking. Replaced with a 350-line implementation that mirrors `SquidgeWorldPoster`:

- Loads full StoryInfo from `story.json`
- Builds the OTW metadata bundle (fandom, warnings, categories, characters, relationships)
- Trims freeform tags to fit OTW's 75-tag total budget (`fandom + relationships + characters + freeform <= 75`)
- Reads single-bulk-file body HTML from `HTML/<story>_Clean.html` (with `SquidgeWorld/Chapter_*.html` concatenation as fallback)
- Posts via the new `create_work` with `preview_button`
- Smart post-flight safety check (see above)
- Returns standard `PostResult`

**Difference from SQW**: AO3 client doesn't yet have multi-chapter `create_chapter` or Work Skin support. For chaptered prose we use the IB-style **single bulk file** convention (`HTML/<Story>_Clean.html` is body-only HTML with all chapters as `<p>` elements in one big body). Multi-chapter `create_chapter` is the next deferred refactor if needed.

### Fixed — `_resolve_format_file` for AO3

Added `("HTML", "*_Clean.html", "html")` as the highest-priority entry in `PLATFORM_FORMAT_MAP["ao3"]`. The previous map only listed `Chapters/SoFurry_HTML/*.html` and `SquidgeWorld/*.html` — both per-chapter dirs. With the earlier `Chapters/` skip fix from 2.3.4, full-story AO3 requests now correctly resolve to `HTML/<story>_Clean.html`.

### Fixed — `StoryInfo.title` field for human display titles

`StoryInfo` was missing the `title` field from `story.json` (only `name` = folder name). `build_package` therefore derived titles via `story.name.replace("_", " ")`, which produced `"The Abstinent Bet/Nice Version"` (with a slash) when the story was loaded from a subfolder path like `The_Abstinent_Bet/Nice_Version`.

Added `title: str = ""` to `StoryInfo` and made `build_package` prefer `story.title` over the folder-name fallback. The two Abstinent Bet AO3 drafts that were posted with the slashy titles were retroactively fixed via `client.edit_work(work_id, title=...)`.

### Test files
- `tests/ao3_smoke.py` — login + list works (read-only smoke test)
- `tests/ao3_diagnose.py` — `_get_page` retry-vs-direct timing diagnostic (helped find the timeout-as-empty-error bug)
- `tests/verify_ao3_draft.py` — single-story draft test (Tombstone) with full safety verification
- `tests/bulk_ao3_drafts.py` — bulk-draft 11 missing stories (Extra_Credit + Abstinent_Bet versions failed and were retried)
- `tests/ao3_retry_failed.py` — retry script for the 3 stories that failed in bulk
- `tests/ao3_fix_abstinent_titles.py` — `edit_work` retroactive title fix for the 2 Abstinent Bet drafts
- `tests/check_ao3_pubs.py` — quick query helper

### Important: deployment status

**The refactor lives only in the running container's filesystem right now** — files were `docker cp`'d in for fast iteration, NOT pulled from a deployed git repo. The local repo has the same files. To make the refactor permanent across container rebuilds:

1. Commit the refactor (`ao3_client/client.py`, `posting/platforms/ao3.py`, `posting/story_reader.py`, the test files)
2. Push to GitHub
3. Run `pawupdate` (`gcloud ... git pull && docker compose up -d --build`)

Without that, the next `docker compose up` will pull the legacy AO3 code back from the image.

### AO3 access notes

- **Local desktop access**: shielded ("Shields are up!" CF JS challenge). No bypass via header tweaks. All AO3 testing must run from the GCP container.
- **GCP container access**: works most of the time but with frequent `ReadTimeout` and `525 origin SSL` errors. AO3's infrastructure is volunteer-run and intermittent. The new retry logic in `_get_page` handles this transparently.
- **AO3 throughput observations**: bulk-drafting 11 stories over 12 minutes hit ~1 in 6 form fetches that needed 2-3 retries to get through. One story (`Extra_Credit`) needed a full retry after exhausting all 3 attempts on the same form fetch.

---

## [2.3.4] - 2026-04-08

### Added — Inkbunny Bulk Drafting + `story_reader` Fixes

**Bulk Inkbunny upload** — Posted 5 missing stories as HIDDEN DRAFTS to KnaughtyKat's IB account in a single run via `tests/bulk_inkbunny_drafts.py`:

| Story | Submission | Words | Tags |
|---|---|---|---|
| Chosen | [3847118](https://inkbunny.net/s/3847118) | 15,958 | 105 |
| Not_So_Efficient_Studying | [3847119](https://inkbunny.net/s/3847119) | 13,602 | 57 |
| Overtime | [3847120](https://inkbunny.net/s/3847120) | 11,513 | 88 |
| Ruins_of_Breeding | [3847121](https://inkbunny.net/s/3847121) | 24,457 | 92 |
| The_Haunting_Desires | [3847122](https://inkbunny.net/s/3847122) | 30,480 | 108 |

Plus the previously-rebuilt **Tombstone** ([3847083](https://inkbunny.net/s/3847083), 8,414 words, 75 tags) which was registered into the publications table during this run.

After this run, the `publications` table holds 6 IB rows — every Tombstone, Chosen, NSE Studying, Overtime, Ruins, and Haunting record knows its IB submission_id and can be edited or replaced from the dashboard.

**Bulk-draft script safety:**
- Pulls every published submission via `client.search_user_submissions()` and aborts if any local target's display title overlaps with a live work — protects the 9 already-published stories from accidental overwrite.
- Sets `extra["draft"] = True` on every package so visibility is omitted (IB defaults hidden).
- Verifies each post via `get_submission_details()` (title, page count, keyword count) before recording.
- Records each result via `upsert_publication()` so the registry is the single source of truth.

**Empirical finding:** Inkbunny accepts at least 108 keywords on a single submission. The previously-assumed 75-keyword cap is wrong — no truncation needed. (NSE Studying sent 58 tags and IB returned 57; one duplicate or empty was silently dropped server-side, not a hard limit.)

### Fixed — `story_reader` resolved chapter file instead of full-story file

`posting/story_reader.py:_resolve_format_file()` was returning the wrong file when called with `chapter_index=0`. The IB format spec is:

```python
"ib": [
    ("Chapters/BBCode", "*.txt", "bbcode"),   # per-chapter
    ("BBCode", "*_bbcode.txt", "bbcode"),     # full story
],
```

For full-story requests, the loop iterated specs in order, hit `Chapters/BBCode` first, found that `*.txt` matched any chapter file, and returned `Chapter_1_*_bbcode.txt`. The full-story spec was never reached.

**Fix:** when `chapter_index == 0`, skip any subdir whose path contains `Chapters/`. Per-chapter directories are inherently chapter-only and should never serve full-story requests.

```python
else:
    # Full-story file — skip per-chapter subdirs (Chapters/...)
    if "Chapters" in subdir.split("/"):
        continue
    ...
```

This bug masqueraded as a successful upload — IB submission 3847080 was created from chapter 1 only and verification reported `pages=1` correctly. Caught only by inspecting `file_path` in the script output. The user-visible result: posting any story via `build_package(story, 0, "ib")` would silently upload chapter 1 instead of the full bulk file. Now fixed for IB and — by extension — every other platform with the same `Chapters/...` + `BBCode/...` spec ordering (FA, Weasyl).

### Fixed — `story_reader` thumbnail auto-detection when `images.cover` empty

Stories with thumbnails sitting at the story root but no `images.cover` entry in `story.json` (the common case — `<story>_thumbnail_full_series.png` is the convention) returned `thumbnail_path = None`. The IB poster then uploaded with no thumbnail.

**Fix:** when `images.cover` is empty, glob the story root for common thumbnail naming patterns:
- `*_thumbnail_full_series.*`
- `*_thumbnail.*`
- `*_cover.*`
- `thumbnail.*`
- `cover.*`

First match wins, restricted to `.png/.jpg/.jpeg/.gif`. Verified end-to-end: Tombstone's `tombstone_thumbnail_full_series.png` was auto-detected and attached to submission 3847083, and IB returned a populated `thumbnail_url_huge` after the post.

The 5 newly drafted stories don't have thumbnail files yet, so they posted thumbnail-less — they can be added via the IB UI later.

### Inkbunny Tombstone single-bulk-file rebuild

Replaced the experimental two-page Tombstone test (3847063 → deleted) with a clean single-file submission:
- Submission **3847083** = full Tombstone bulk file (`BBCode/Tombstone_bbcode.txt`, 49,200 bytes, all 3 chapters in one BBCode)
- Title `Tombstone`
- Description: 30-word version from `story.json`
- 75 IB keywords
- Auto-detected thumbnail attached
- Stays HIDDEN — ready for live submission whenever

This is the canonical IB shape for chaptered stories: one submission, one bulk file with chapter dividers, one thumbnail. IB's per-page navigation is for multi-image art, not for chaptered prose where the story field is a single blob anyway.

### Test files
- `tests/verify_inkbunny_bulk_rebuild.py` — Tombstone single-file rebuild verification
- `tests/bulk_inkbunny_drafts.py` — bulk-draft 5 missing stories with safety guards

---

## [2.3.3] - 2026-04-08

### Added — Work Skin CSS Auto-Refresh

`SquidgeWorldPoster._ensure_work_skin()` now **always pushes the current local CSS to SquidgeWorld** on every `post()` and `edit()` call, not just when creating a new skin. Previously, if a Work Skin already existed by title, the poster would return its skin_id and skip the update — meaning local CSS edits would never propagate.

**New behavior:**
1. If no `Work_Skin.css` for the story → return `''` (no skin applied)
2. If skin doesn't exist by title → create new with current CSS
3. **If skin exists → call `client.edit_work_skin()` to push the current CSS and description** (auto-refresh, best-effort — if the edit fails, log a warning but still return the skin_id so the work can use the existing skin)

**Verified end-to-end** with a sentinel-color test:
- Modified Tombstone's `Work_Skin.css` locally (replaced `#5a7a52` with `#abcdef`)
- Called `SquidgeWorldPoster.edit("91390", package)`
- Confirmed `#abcdef` was present in the live SQW skin CSS
- Auto-restored original

**Note:** SquidgeWorld (OTW Archive) **strips CSS comments server-side** as part of its sanitization. This is intentional on their end and doesn't affect functionality. Don't rely on string-equality comparisons between local CSS files and the live skin CSS — strip comments from local before comparing.

---

## [2.3.2] - 2026-04-08

### Added — Work Skins for the 3 Stories That Were Missing Them

Created `Work_Skin.css` for Drumheller_Detour, The_Haunting_Desires, and Velvet_And_Vice, then uploaded them as Work Skins on SquidgeWorld and applied them to the live drafts via `SquidgeWorldPoster.edit()`:

- **Drumheller_Detour Skin** (id 2827) — Badlands Dust theme: dark brown background (#1c1510), warm cream text (#e0d5c8), badlands orange accents (#c17817). Includes `.comic-panel` / `.comic-caption` rules for the story's embedded illustration images.
- **The Haunting Desires Skin** (id 2828) — Haunted Dark theme: near-black background (#08090e), warm grey text (#d0ccc8), antique gold accents (#c8a050).
- **Velvet And Vice Skin** (id 2829) — Velvet Noir theme: dark wine background (#100808), warm off-white text (#e2dad0), deep burgundy primary (#8b1a1a), copper secondary (#b87040). Handles both `<p class="chapter-heading">` and `.chapter-heading` since V&V uses the `<p>` variant.

All 3 skins were uploaded via `client.create_work_skin()` and applied through the existing `SquidgeWorldPoster.edit()` flow which auto-detects draft/published state. All 3 stories stayed in draft state throughout.

After this change, every SquidgeWorld work has a custom Work Skin matching its story's theme.

---

## [2.3.1] - 2026-04-08

### Added — SquidgeWorld Bulk Upload + Description Cleanup + Safety Hardening

**Bulk SquidgeWorld upload** — Posted 7 missing stories as DRAFTS to SquidgeWorld in a single run:
- Tombstone (91390, 3 chapters)
- Drumheller_Detour (91391, 8 chapters)
- Not_So_Efficient_Studying (91393, 3 chapters)
- Overtime (91394, 4 chapters)
- Ruins_of_Breeding (91395, 6 chapters)
- The_Haunting_Desires (91396, 8 chapters)
- Velvet_And_Vice (91397, 9 chapters)
- Total: **41 new chapters added**. All verified to stay in draft state throughout.

**Safety infrastructure** added to prevent accidental publishing:
- `SquidgeWorldClient.delete_work(work_id)` — emergency cleanup mechanism via the `/works/{id}/confirm_delete` form (POST `_method=delete` + `commit=Yes, Delete Work`).
- `SquidgeWorldClient.is_work_in_drafts(work_id)` / `is_work_published(work_id)` — state check helpers that query `/users/{user}/works/drafts` and `/users/{user}/works`.
- `SquidgeWorldPoster.post()` now has post-flight draft-state verification after `create_work` AND after every `create_chapter`. If the work ever leaves draft state, it's **automatically deleted** and the call fails. Opt out with `package.extra["allow_publish"] = True`.
- `SquidgeWorldPoster.edit()` now **auto-detects** whether the work is draft or published and uses the matching submit button (`save_button=Save As Draft` for drafts, `post_button=Post` for published), then verifies the state didn't change after the edit. Opt out with `package.extra["allow_state_change"] = True`.

**`SquidgeWorldClient.create_chapter` simplified and fixed:**
- The previous `publish=False` path was broken (tried a two-step preview→save flow that returned 400 because it didn't resend the chapter fields).
- **Verified empirically** that a single `preview_button=Preview` POST creates the chapter fully AND leaves the work in its current state. No follow-up `save_button` click is needed. Confirmed via `tests/test_chapter_after_preview_only.py` — the new chapter is present in `get_chapter_ids()` after the preview POST with no state change.
- `publish=True` still uses `post_without_preview_button=Post` which DOES publish the work (never call this on drafts).

**Description cleanup** — Updated 9 story.json `description` fields to be ≤30 words and ≤2 sentences for cleaner platform listings:
- Chosen: 40w → 30w
- Drumheller_Detour: 39w → 28w
- Not_So_Efficient_Studying: 29w → 28w (merged to 2 sentences)
- Overtime: 64w → 26w
- Ruins_of_Breeding: 31w → 23w
- The_Haunting_Desires: 31w → 29w
- The_Silk_Threaded_Bonds: 35w → 29w
- Tombstone: 56w → 30w (4 sentences → 2)
- Velvet_And_Vice: 35w → 29w (3 sentences → 2)
- Extra_Credit and Hypnotic_Claim already fit the target (28w and 27w respectively)
- All changes pushed live to SquidgeWorld via the refactored `SquidgeWorldPoster.edit()` (drafts stayed drafts, Chosen stayed published)

**Bulk upload test infrastructure (`tests/`):**
- `verify_draft_chapter_safety.py` — creates a throwaway draft, verifies draft state, adds a chapter via `publish=False`, verifies still draft, deletes. Always cleans up.
- `test_chapter_after_preview_only.py` — proved the preview POST alone is sufficient (the fix that made `create_chapter(publish=False)` actually work)
- `inspect_draft_chapter_form.py` — dumps the fields OTW Archive expects on the chapter preview page
- `post_missing_stories_to_sqw_drafts.py` — bulk-upload script with fuzzy title matching, dry-run, per-story confirmation, and post-flight safety checks
- `verify_all_drafts.py` — sequential read-only audit of all draft works, comparing each against its `story.json`
- `update_descriptions_and_push.py` — updates story.json descriptions and pushes them to SquidgeWorld

### Fixed
- **`edit_chapter`** had a silent-failure bug — the original partial-fields approach sent `_method=patch` + a few fields + a generic `commit=Update` button. This matched nothing the OTW form expected and sometimes returned 200 with no actual save. Fully refactored to the safe form-fetch pattern: GET `/works/{id}/chapters/{ch_id}/edit`, extract every `chapter[*]` field with its current value (inputs, selects, textareas), override only the requested fields, POST with the appropriate submit button (auto-detected: `save_button` for drafts, `post_without_preview_button` for published), strict success check for "successfully updated" flash.

### Known Issues / Follow-ups
- **Chosen work_skin fandom drift**: OTW Archive's tag wrangler auto-canonicalises `Kung Fu Panda` → `Kung Fu Panda - Fandom`. The story.json stays as `Kung Fu Panda` and SQW adds the suffix server-side. Not a bug, just informational.
- **Character/relationship tag canonicalisation**: OTW converts `(Original Character)` to `[Original Character]` or appends `[OC]`. Same — server-side transformation, not a client bug.
- **Missing Work_Skin.css for 3 stories**: Drumheller_Detour, The_Haunting_Desires, Velvet_And_Vice have no `Work_Skin.css` in their `SquidgeWorld/` folder. These stories were uploaded without a custom work skin (they use the default OTW styling). Create work skins for them as a follow-up if desired.
- **Tag curation** — current behavior dumbly truncates to first N tags to fit the 75-tag OTW limit. Smart prioritisation or dedicated `tags.sqw` lists in `story.json` would be better, but deferred.

### Verification
- All 8 stories on SquidgeWorld verified sequentially via `verify_all_drafts.py` — correct title, fandom, rating, warnings, categories, characters, relationships, tag counts, chapter counts, and draft/published state.
- `The Silk-Threaded Bonds` correctly matched as pre-existing via fuzzy matching (`The Silk Threaded Bonds` in story.json vs `The Silk-Threaded Bonds` on SQW — hyphen difference).
- Description updates pushed live, auto-detected draft state for each work, preserved existing state.

---

## [2.3.0] - 2026-04-07

### Added — SquidgeWorld Posting: Full Refactor + Live Verification

**SquidgeWorldClient (`sqw_client/client.py`):**
- `find_work_skin_by_title(title)` — looks up an existing Work Skin by title from `/users/<user>/skins?skin_type=WorkSkin`, returns skin_id or None
- `create_work_skin(title, css, description, public, role)` — POSTs to `/skins` to create a new Work Skin. Handles `skin_type=WorkSkin` field and the multipart form structure.
- `get_or_create_work_skin(title, css, description)` — find-or-create wrapper. Idempotent.
- `edit_work_skin(skin_id, title, description, css, public)` — safe form-fetch pattern. Extracts every `skin[*]` field from `/skins/{id}/edit`, overrides only the requested fields, POSTs back with `_method=patch` and `commit=Update`. Includes the strict success check.
- `create_work` — added `warnings: list[str]`, `categories: list[str]`, `work_skin_id`, `chapter_title` parameters. Defaults to `warnings=["No Archive Warnings Apply"]`. Now extracts the author pseud ID from the form (required field that was missing). Sends form data via `urlencode(doseq=True)` + `content=` because httpx 0.28.1 has an `AsyncClient` bug with list-of-tuples in `data=`. Backwards compat shims for old `warning`/`category` single-string parameters.
- `edit_work` — full refactor. Uses safe form-fetch pattern: GET `/works/{id}/edit`, extract every `work[*]` field with current value (handles inputs, selects, textareas, radios, checkboxes), override only the requested fields, POST back with `_method=patch` and `save_button=Save As Draft` (or `post_button=Post` if `save_as_draft=False`). Strict success check looks for explicit "successfully updated" flash and raises with the OTW error block if not present. **This was the silent-fail bug** — previous version only checked for "have not been saved" but missed cases where the form was rejected for other validation reasons.
- `edit_chapter` — full refactor. Same safe form-fetch pattern as `edit_work`. Auto-detects whether the form has `save_button=Save As Draft` (draft work) or `post_without_preview_button=Post` (published work) and uses the right one. Strict success check.
- `create_chapter` — **new**. POSTs to `/works/{id}/chapters/new`. **Safe by default**: uses `preview_button=Preview` then submits the preview's `save_button=Save As Draft` so adding a chapter to a draft work does NOT publish the work. Set `publish=True` explicitly to use `post_without_preview_button=Post` (which publishes the work for chapters added to a draft). This safety default was added after a session-mistake accidentally published Chosen.
- `_extract_work_form_fields(html)` — module-level helper that parses every `work[*]` field from a `/works/{id}/edit` page (inputs, selects, textareas with HTML entity decoding). Used by `edit_work` to safely extract current state.

**Story reader (`posting/story_reader.py`):**
- `StoryInfo` dataclass extended with: `rating`, `fandom`, `category`, `categories: list[str]`, `warnings: list[str]`, `characters: list[str]`, `relationships: list[str]`, `work_skin_path: Path | None`. The `__post_init__` ensures lists are never None and falls `categories` back to `[category]` if only the legacy single-string was set.
- `_load_from_story_json` populates all the new fields from `story.json`. Handles legacy `category: str` vs new `categories: list[str]`. Auto-detects `Work_Skin.css` at `<story>/SquidgeWorld/Work_Skin.css`.

**SquidgeWorldPoster (`posting/platforms/squidgeworld.py`) — full refactor:**
- `post()` — now multi-chapter, full-metadata, work-skin-aware. Loads `StoryInfo` via `story_reader.load_story` (just needs `package.story_name`). Finds or creates the Work Skin from `Work_Skin.css`. Trims freeform tags to fit OTW's 75-tag limit (fandom + relationship + character + freeform). Calls `client.create_work` with all metadata for chapter 1, then iterates remaining chapters and calls `client.create_chapter(publish=False)` to keep the work in draft state. Returns `PostResult` with the work_id.
- `edit()` — same shape. Refreshes the Work Skin, edits work metadata via `edit_work` with full metadata, then iterates `client.get_chapter_ids(work_id)` and calls `client.edit_chapter` for each with the corresponding archive file content.
- `_trim_freeform_tags()` — calculates the OTW 75-tag budget (75 - fandoms - relationships - characters) and trims freeform tags to fit.
- `_read_chapter_content(story, ch_idx)` — resolves chapter content by looking first in the story's `SquidgeWorld/` dir (preferred body-only HTML), then falling back to `Chapters/SoFurry_HTML/`.
- `_ensure_work_skin(client, story)` — handles the work skin lifecycle. Returns `skin_id` or empty string if no `Work_Skin.css` is present.
- `_rating_to_sqw()` — maps internal rating values to OTW canonical ("explicit" → "Explicit").

**Test scripts (under `tests/`):**
- `live_test_sqw_draft.py` — exercises the create-draft flow against Chosen Ch1
- `live_test_sqw_edit.py` — full safe form-fetch pattern reference for edits
- `live_test_sqw_full.py` — Work Skin creation + work edit pipeline
- `live_test_sqw_chapters.py` — adds chapters and updates skin metadata
- `live_test_sqw_finalize.py` — clean-up flow for taking a draft to a polished published state
- `live_test_sqw_reupload_chapters.py` — uses `edit_chapter` to update all chapters of a work
- `live_test_sqw_poster.py` — end-to-end test of `SquidgeWorldPoster.edit()` against the live work
- `regen_chosen_sqw.py` — regenerates Chosen's SquidgeWorld body HTML files using the wrapper from the existing files + paragraphs from the regenerated SoFurry HTML

### Fixed
- **httpx 0.28.1 AsyncClient + list-of-tuples bug** — `data=[(k,v),...]` raises "Attempted to send a sync request with an AsyncClient instance". Worked around in `create_work` and all new POSTs by URL-encoding manually with `urlencode(doseq=True)` and using `content=` with explicit `Content-Type: application/x-www-form-urlencoded`. The form data needs duplicate keys for `work[archive_warning_strings][]` and `work[category_strings][]` array fields, which is why a dict can't be used.
- **OTW Archive validation errors** that the previous edit_work silently ignored:
  - `Fandom, relationship, character, and additional tags must not add up to more than 75` — now caught by the strict success check; poster auto-trims freeform tags
  - `Only canonical warning tags are allowed` — fixed by sending `archive_warning_strings[]` (plural array) with canonical values like "No Archive Warnings Apply" instead of the old "Creator Chose Not To Use Archive Warnings"
  - `Work must have at least one creator` — fixed by extracting the author pseud ID from the form HTML and including it as `work[author_attributes][ids][]`
- **OTW Archive edit_work used wrong submit button** — `preview_button` only shows a preview, doesn't save. Fixed to use `save_button=Save As Draft` for drafts and `post_button=Post` for published works.
- **OTW Archive edit_chapter used wrong submit button** — same issue. Fixed to auto-detect `save_button` (draft) vs `post_without_preview_button` (published).
- **Accidentally published a draft work via `create_chapter`** during testing — `post_without_preview_button` on a chapter form publishes the entire work, not just the chapter. Fixed by making `create_chapter` safe-by-default with `publish=False` using a `preview_button` → `save_button` two-step pattern. To get the old behavior, callers must pass `publish=True` explicitly.

### Known Issues / Pending
- **Other platform posters not yet refactored** — IB, FA, SF, WS, BSKY, AO3, IK, DA still use their original implementations. IB/FA/SF were known to work in earlier sessions but haven't been retested with the new full-metadata `story.json` shape. AO3 uses the same OTW Archive software as SquidgeWorld so will likely need the same fixes.
- **Other stories' SquidgeWorld files** still need regeneration. Only Chosen has been redone for the live test. The mass regen for the other 10 stories is mechanical and pending.
- **Styled HTML files** for all stories also need regeneration since they're built from the same converter output and likely contain the same nested-asterisk bug.

### Live Verification — Chosen → SquidgeWorld
- Created draft work 91374 for Chosen via `client.create_work` (with all metadata pulled from story.json)
- Created Work Skin 2820 ("Chosen Skin") from `Chosen/SquidgeWorld/Work_Skin.css`
- Edited Work Skin metadata to add a proper title and description
- Added all 5 chapters via `create_chapter` (note: the initial test used the old `publish=True` behaviour and accidentally published the work — has been left published since the user accepted that state and the metadata was cleaned up properly)
- Verified `SquidgeWorldPoster.edit("91374", package)` end-to-end against the live work — full metadata + work skin + all 5 chapter contents updated in 23.4s in a single call

---

## [2.2.1] - 2026-04-07 — Converter Bug Fix + Mass Regeneration

### Fixed
- **Critical: nested-asterisk emphasis bug** in both `convert_md_to_sofurry_html.py` and `convert_md_to_bbcode.py`. The author convention is `*outer narration *emphasized_word* outer narration*` — single asterisks for both italic narration AND inner emphasis. The previous regex `\*(.+?)\*` matched the OUTER asterisks first (lazy regex), producing wrong-bolded paragraphs where the WHOLE paragraph became `<strong>` and the supposedly-emphasized word was the only un-bolded thing.
- The fix: added an `is_narration_wrapped(text)` check that detects single-asterisk wrappers (excluding `**` bold cases at start/end), strips the outer wrapper before running the inner emphasis regex, and re-applies `<em>` after.
- Also fixed the multi-segment dialogue path in both converters which had the same issue but only triggered when narration segments had >2 asterisks.

### Mass regeneration
- Ran the fixed converters across the entire `Archives/Complete_Stories/` tree
- 148 files regenerated (full-story BBCode + SoFurry HTML for each story, plus all per-chapter BBCode and SoFurry HTML files)
- 0 failures
- Affected stories (with the bug): Chosen, Drumheller_Detour, Extra_Credit, Hypnotic_Claim, Not_So_Efficient_Studying, Ruins_of_Breeding, The_Haunting_Desires, The_Silk_Threaded_Bonds, Velvet_And_Vice
- Unaffected: Tombstone, Overtime (recent stories that didn't use nested asterisks heavily)

### Tools
- `m_x/Scripts_Utils/test_emphasis_fix.py` — unit test demonstrating the bug and the fix
- `m_x/Scripts_Utils/regenerate_all_html_bbcode.py` — walks the archive and runs both converters on every MASTER.md and chapter .md

### Worst case before/after
- Chosen Chapter 4 had **86 `<strong>` tags** in the SquidgeWorld body file before the fix, with most paragraphs incorrectly bolded
- After the fix and regen: **49 single-word emphases** (the chapter genuinely uses lots of emphasis for intensity, but each is now a single word, not a wrongly-bolded paragraph)

---

## [2.2.0] - 2026-04-06

### Added
- **Per-chapter tag support** — story_reader.py now reads `chapter_info[].tags` from story.json and populates `chapter_tags_by_platform`. Per-chapter uploads (FA, SQW) use chapter-specific tags when available, falling back to story-level tags.
- **Platform tag limits reference** — `posting/references/platform_tag_limits.md` documenting tag limits (SF≤97, WP≤24, DA≤30), SQW/AO3 archive warnings, categories, ratings, and relationship notation.
- **Complete story.json metadata** for all 11 stories — descriptions, summaries, categories, warnings, characters, relationships, per-platform tags (from Tag_Database), per-chapter tags and descriptions for all 67 chapters.
- **Itaku posting support** (platform 8) — image gallery uploads and text posts via Django REST Framework token auth.
- **DeviantArt posting support** (platform 9) — via official OAuth2 literature API with auto-refreshing tokens.
- **AO3 posting support** (platform 7) — same OTW Archive form structure as SquidgeWorld.

### Changed
- `posting/story_reader.py` — `_load_from_story_json()` now reads per-chapter tags and populates `chapter_tags_by_platform` dict. `build_package()` tag selection chain: chapter tags → story tags → empty.
- `posting/generate_story_json.py` — generates AO3 and DeviantArt platform configs in story.json.
- `database/db.py` — SQLite timeout increased from 10s to 30s + `PRAGMA busy_timeout=30000` for concurrent poll cycle contention.

### Fixed
- **SQLite "database is locked" errors** during concurrent poll cycles — busy_timeout pragma makes writers queue instead of erroring.
- **Styled HTML title font-size** standardised to 2.8rem across all stories (was 3rem in Hypnotic Claim and NSES).

---

## [2.1.0] - 2026-04-05

### Added
- **DeviantArt posting support** (platform 9) — via official OAuth2 literature API
  - `da_client/client.py` — `oauth_create_literature()`, `oauth_update_literature()`, `oauth_refresh_token()`
  - `posting/platforms/deviantart.py` — DeviantArtPoster with post, edit, replace_file (body content)
  - Uses official OAuth2 API (not undocumented _napi) — stable, works from any IP
  - Requires app registration: `da_client_id`, `da_client_secret`, `da_refresh_token` in settings
  - Auto-refreshes access tokens (1-hour expiry, 3-month refresh tokens)
  - Title max 50 chars, max 30 tags, mature level/classification support
  - Format: reads from Markdown (MASTER.md or chapter files)

- **Itaku posting support** (platform 8) — image gallery uploads and text posts
  - `ik_client/client.py` — `upload_image()` (multipart gallery), `create_post()` (JSON text post)
  - `posting/platforms/itaku.py` — ItakuPoster with image upload and text post support
  - Auth: Django REST Framework token from browser session (`ik_auth_token` setting)
  - Min 5 tags, max 10MB images, ratings: SFW/Questionable/NSFW
  - No edit or file replacement support (Itaku API limitation)
  - Note: Itaku is primarily for art, not literature. Text posts limited to ~5000 chars.

- **AO3 posting support** (platform 7) — same OTW Archive software as SquidgeWorld
  - `ao3_client/client.py` — `create_work()`, `edit_work()`, `edit_chapter()`, `get_chapter_ids()`, HTML whitespace collapse
  - `posting/platforms/ao3.py` — AO3Poster with post, edit (metadata + chapters), replace_file
  - Uses existing `ao3_username`/`ao3_password` credentials (same account for polling and posting)
  - 3-second rate limit between requests (AO3 is volunteer-run)
  - Registered in manager, story_reader, frontend, story.json generator

### Fixed
- **SQLite "database is locked" errors** — increased timeout from 10s to 30s + added `PRAGMA busy_timeout=30000` for concurrent poll cycle contention

---

## [2.0.0] - 2026-04-04

### Added — Multi-Platform Posting Module
Complete story publishing system — upload, edit, and manage stories across 7 platforms from PawPoller.

**Core Infrastructure:**
- `posting/` module — manager, scheduler, story reader, sync, platform posters
- `database/posting_schema.sql` — 3 tables: publications, posting_queue, posting_log
- `database/posting_queries.py` — Full CRUD for all posting tables
- `routes/posting_api.py` — 12+ REST endpoints for posting operations
- `posting/scheduler.py` — Background daemon thread processing the posting queue
- Desktop/server queue mode — FA items auto-queue for desktop when server can't process

**Platform Posters (6 platforms):**
- **Inkbunny** (`posting/platforms/inkbunny.py`) — API upload + edit via `api_upload.php` / `api_editsubmission.php`. Story text uses `story` field (reading panel), `desc` for summary. BBCode text message styling (coloured, aligned sent/received).
- **FurAffinity** (`posting/platforms/furaffinity.py`) — 3-step form scrape (GET key → POST upload → POST finalize). Edit via `/controls/submissions/changeinfo/`. File replace via `/controls/submissions/changestory/`. 70s rate limit.
- **SoFurry** (`posting/platforms/sofurry.py`) — REST + CSRF (PUT create → POST content chapter → POST metadata). Chapter-based story content. Author credentials for editing.
- **Weasyl** (`posting/platforms/weasyl.py`) — CSRF + form POST to `/submit/literary`. API key auth.
- **SquidgeWorld** (`posting/platforms/squidgeworld.py`) — OTW Archive form scraping. Author credentials (separate from polling account). HTML whitespace collapse to prevent `<br />` injection. Work Skin CSS classes preserved.
- **Bluesky** (`posting/platforms/bluesky.py`) — AT Protocol `createRecord` + `uploadBlob`. Announcement posts with NSFW labels. Link facet extraction.

**Story Archive System:**
- `story.json` per story — standardised metadata (title, author, rating, warnings, tags, chapters, platforms, images)
- `posting/generate_story_json.py` — generates story.json from existing tags_upload.txt + split_manifest.json
- `posting/story_reader.py` — reads story.json (preferred) or falls back to legacy tag/manifest parsing
- Platform-specific description selection (summary for SQW/AO3, short blurb for IB/SF)
- Format file resolution per platform (BBCode→IB, PDF→FA, SoFurry HTML→SF, SquidgeWorld HTML→SQW)

**Retroactive Sync:**
- `posting/sync.py` — claim existing submissions into publications registry by title matching
- 25 publications claimed across IB, FA, SF, SQW, WP
- Fuzzy matching: full stories, per-chapter (FA), sub-stories (Abstinent Bet), part words
- `/claim` Telegram command and `/api/posting/claim` endpoint

**Change Detection:**
- `file_hash` column on publications — SHA-256 of format file at time of posting
- `detect_changes()` / `get_changed_stories()` / `get_sync_status_summary()`
- `/changes` Telegram command and `/api/posting/changes` endpoint
- After `/update`, hashes are refreshed so `/changes` shows stories as up-to-date

**Desktop Queue Mode:**
- `requires` column on posting_queue: `any`, `desktop`, `server`
- FA flagged as `requires_mode = "desktop"` (needs residential IP)
- Scheduler auto-detects runtime mode (pywebview importable = desktop)
- Failed server posts auto-queue for desktop with `requires=desktop`

**Batch Operations:**
- `/update all [platforms]` — pushes all changed stories to all platforms
- `/update all fa` — batch update on single platform
- Auto-queue fallback: failed server edits queued for desktop processing

**Dashboard UI:**
- Story card hub (`#/posting`) — grid of cards with title, words, chapters, rating, platform badges
- Story detail page (`#/posting/story/{name}`) — full metadata, publications with live stats, upload/update buttons, chapter list, format inventory
- Queue page (`#/posting/queue`) — pending items with cancel
- History page (`#/posting/log`) — audit trail
- Published page redirects to Stories hub
- Mobile responsive: single-column cards, full-width buttons, 44px touch targets
- Bottom nav: Stories link added

**Telegram Commands:**
- `/stories` — list archive stories
- `/upload <story> [platforms]` — post story to platforms
- `/update <story> [platforms]` — push updates to posted submissions
- `/update all [platforms]` — batch update all changed stories
- `/posted [story]` — show publication registry
- `/claim [platforms]` — claim existing submissions
- `/changes` — show which stories have changed since last update

**BBCode Converter Fixes:**
- Title uses `[t]` tag (IB title style) instead of `[b]`
- Subtitle detection: only `*by Author*` or `*A Something Story*` patterns, window closes on first non-subtitle content
- Text messages styled: sent (MAYA) right-aligned blue `#4a9eff`, received left-aligned grey `#aab0bc`
- Phone calls: centred with `📱` emoji and decorative lines
- No longer centres first italic body paragraph after chapter headings

**Story Sync:**
- `deploy/pawsync.bat` — syncs story archive to GCP server
- Fixed: was excluding `*/SquidgeWorld/*` — now includes all format folders
- PyInstaller spec updated with `posting_schema.sql`

### Changed
- `api_client/client.py` — added `upload_submission()`, `edit_submission()` with `story` field
- `bsky_client/client.py` — added `_post_json()`, `upload_blob()`, `create_post()`, `delete_post()`
- `weasyl_client/client.py` — added `submit_literary()`, `edit_submission()` with CSRF
- `sf_client/client.py` — added `_get_csrf_meta()`, `create_submission()` (chapter-based), `edit_submission()`
- `fa_client/client.py` — added `submit_story()` (3-step), `edit_submission()` via `changeinfo`, file replace via `changestory`
- `sqw_client/client.py` — added `create_work()`, `edit_work()`, `edit_chapter()`, `get_chapter_ids()`, `_collapse_html_whitespace()`
- `dashboard.py` — registered `posting_router`
- `database/db.py` — loads `posting_schema.sql`, migrations for `file_hash` and `requires` columns
- `main.py` + `server.py` — posting scheduler daemon thread added
- `polling/telegram_bot.py` — 7 new commands + help text updated
- `inkbunny_analytics.spec` — added `posting_schema.sql` to PyInstaller data files

---

## [1.6.0] - 2026-03-10

### Added
- **Bluesky platform support** (platform 10) — AT Protocol integration with JWT session auth via app passwords
  - `bsky_client/client.py` — `BskyClient` with login/refresh/check session chain, batch post fetching (25 URIs per call), cursor-paginated feed discovery
  - `database/bsky_schema.sql` — `bsky_submissions` (TEXT PK for AT URIs), `bsky_snapshots`, `bsky_poll_log`
  - `database/bsky_queries.py` — Full CRUD with `get_bsky_submission_by_rkey()` suffix match for AT URI resolution
  - `polling/bsky_poller.py` — Poll cycle with 🦋 emoji notifications, activity trigger on likes/reposts changes
  - `routes/bsky_api.py` — `/api/bsky/*` endpoints with `{submission_id:path}` for AT URI path params
  - Frontend: Dashboard (4 stat cards: likes, reposts, replies, quotes — no views), posts table, detail view, comparison charts
  - Metrics: likes, reposts, replies, quotes (4 metrics, no view counts)

- **X/Twitter platform support** (platform 11) — Cookie-based GraphQL scraping of internal endpoints
  - `tw_client/client.py` — `TWClient` with auth_token + ct0 cookie auth, GraphQL query endpoints (UserByScreenName, UserTweets, TweetResultByRestId), content type detection (tweet/reply/retweet/quote)
  - `database/tw_schema.sql` — `tw_submissions` (TEXT PK for tweet IDs), `tw_snapshots`, `tw_poll_log`
  - `database/tw_queries.py` — Full CRUD with 6 metrics, default sort by views DESC
  - `polling/tw_poller.py` — Poll cycle with 🐦 emoji notifications, 2s inter-request delay (aggressive rate limiting)
  - `routes/tw_api.py` — `/api/tw/*` endpoints with content_type filtering
  - Frontend: Dashboard (7 stat cards: views, likes, retweets, replies, quotes, bookmarks), tweets table with type column, detail view, comparison charts
  - Metrics: views, likes, retweets, replies, quotes, bookmarks (6 metrics — most of any platform)

- **Cross-platform integration** for both platforms:
  - Overview page: BSKY/TW included in totals, top lists, recent activity, aggregate charts, export buttons
  - Settings page: BSKY (identifier + app_password) and TW (auth_token + ct0 + target_user) credential sections with connect/disconnect/poll/resync controls
  - Telegram notifications: digest reports, milestone alerts, `/stats`, `/top`, `/poll`, `/interval`, `/notifications` bot commands
  - Analytics: trending detection, cross-platform links, group stats
  - Platform badges: `.platform-badge.bsky` (blue #0085ff) and `.platform-badge.tw` (blue #1d9bf0)
  - Navigation: Bluesky and X/Twitter sidebar groups with Dashboard/Posts/Compare links

### Changed
- Thread count increased from 12 to 14 daemon threads (added BSKY + TW pollers)
- `config.py` — Added `BSKY_REQUEST_DELAY_SECONDS = 1.0` and `TW_REQUEST_DELAY_SECONDS = 2.0`
- `database/db.py` — Schema init loads `bsky_schema.sql` and `tw_schema.sql`
- `dashboard.py` — Registers `bsky_router` and `tw_router`
- `server.py` — Added env-to-settings mappings for BSKY/TW credentials
- `polling/telegram.py` — Added BSKY/TW to platform metrics, emoji, name maps, digest reports, goal checking
- `polling/telegram_bot.py` — Added BSKY/TW to all 10+ platform maps (stats, poll, interval, notify commands)
- `database/analytics_queries.py` — Added BSKY/TW to trending and cross-platform metrics
- `database/group_queries.py` — Added BSKY/TW to group stats metrics
- `routes/api.py` — Added BSKY/TW to table maps and allowed metrics (reposts, retweets, bookmarks, quotes)
- `inkbunny_analytics.spec` — Added BSKY/TW schema files to PyInstaller datas

---

## [1.5.0] - 2026-03-09

### Added
- **Mobile-first UI overhaul** — comprehensive responsive redesign for phone and tablet use
- **Collapsible sidebar navigation** — platform sections collapse into accordion groups on mobile (<=768px), reducing 30+ links to manageable groups that expand on tap
- **Bottom navigation bar** — fixed bottom bar on mobile with quick access to Overview, Platforms (opens sidebar), Analytics, and Settings
- **Table-to-card transformation** — all 9 platform submission tables transform into stacked card layouts on mobile using `data-label` attributes for inline column headers
- **Safe area support** — `viewport-fit=cover` and `env(safe-area-inset-*)` CSS for notched devices (iPhone etc.)
- **Touch optimisation** — `touch-action: manipulation` on all interactive elements, `-webkit-tap-highlight-color: transparent`, 44px minimum touch targets
- **Responsive chart sizing** — chart heights reduce from 280px to 220px/200px at tablet/phone breakpoints
- **Mobile-friendly settings** — form inputs stack vertically with full-width fields and 44px min-height on mobile
- **Wider sidebar on mobile** — sidebar expands to 280px (up from 220px) when opened as overlay for easier tap targets
- **Date range buttons** — range buttons flex-fill and centre-align on mobile for even spacing

### Changed
- Sidebar overlay element moved from JS-created to HTML for better bottom-nav integration
- Stat cards use 10px gap on mobile (down from 16px) and single-column at 480px
- Pinned cards use smaller flex-basis (160px/140px) for better mobile scrolling
- Top list titles truncate at 55vw/60vw on mobile for consistent layout
- Comment cards reduce padding on mobile for space efficiency
- Growth rate values use smaller font (14px) at 480px

---

## [1.4.2] - 2026-03-09

### Security
- **Zip Slip prevention** — auto-updater now validates all ZIP entry paths before extraction to prevent path traversal attacks
- **XSS fix** — `escapeHtml()` now escapes single quotes (`'` -> `&#39;`) preventing attribute injection via submission titles
- **Timing attack fix** — HTTP Basic Auth now evaluates both username and password in constant time (no short-circuit)
- **Error response hardening** — global exception handler no longer leaks internal error details to clients

### Fixed
- **SqW Anubis solver** — proof-of-work implementation now correctly finds a nonce with leading zeros matching difficulty, instead of computing a single hash (which always failed)
- **WP/IK detail charts broken** — `Charts.submissionLine()` now accepts a custom metrics array; Wattpad charts correctly plot reads/votes/lists and Itaku charts plot likes/reshares
- **WP/IK missing from 5 UI components** — added Wattpad and Itaku entries to `overviewTopList`, `overviewRecentActivity`, `trendingCards`, `linkCards`, and `linkSuggestions` badge/route maps; items no longer misidentified as Inkbunny
- **Poll error logs lost** — all 9 pollers now `conn.commit()` after writing error status to poll_log; failed cycles are no longer silently rolled back
- **IB web session lock-in** — CSRF token failure no longer permanently locks the web client in a failed state; session now properly detects expiry and re-authenticates
- **IB comment truncation** — added double-quote fallback for BBCode extraction regex; comments containing apostrophes are no longer silently truncated
- **5 batch methods crash on single failure** — SqW, AO3, WP, IK, and DA `get_*_details_batch()` methods now catch per-item exceptions instead of crashing the entire batch
- **Server startup fallthrough** — main.py now exits with error code if the server fails to start within 15 seconds, instead of opening a blank native window
- **Poll interval zero spin** — poll intervals are now clamped to minimum 1 minute, preventing infinite CPU spin or crashes from zero/negative/non-numeric values
- **Telegram /notify comments** — command now toggles comment-specific setting instead of the IB master notification switch
- **Telegram /notify missing platforms** — added sqw, ao3, da, wp, ik to the notification toggle map
- **DB restore corruption** — backup restore now removes stale WAL/SHM journal files to prevent replaying old transactions against the restored database
- **SF schema incomplete** — added missing `new_watchers_found` column to `sf_poll_log` table definition
- **Update temp cleanup** — failed update downloads now clean up their temp directory instead of leaving orphaned files

---

## [1.4.1] - 2026-03-09

### Security
- **Dashboard authentication** — optional HTTP Basic Auth for server/Docker deployments (set `DASHBOARD_PASSWORD` env var)
- **Update endpoint hardened** — `/api/update/apply` now restricted to GitHub URLs only (prevents SSRF)
- **SQL injection fix** — parameterized weeks value in historical analytics query
- **Thumbnail proxy domain whitelist** — fixed substring matching bypass on IB and FA proxies (e.g. `evil-metapix.net` no longer passes)
- **Thread-safe credentials** — added mutex lock protecting credential reads/writes between web and poller threads

### Fixed
- **Poller deadlock** — all 9 pollers could permanently lock up if database connection failed at startup; restructured try/finally to guarantee lock release
- **WP/IK column name crashes** — milestones, digest, goals, and analytics now use platform-aware column mapping (Wattpad: reads/votes, Itaku: likes/reshares)
- **10 database connection leaks** — all `auth_status` endpoints now close connections in `finally` blocks
- **HTML injection in Telegram** — all titles and usernames are now HTML-escaped in notification messages across all 9 pollers
- **Poll log not committed** — "no submissions found" cycles now persist their poll log entries
- **WS/DA/WP/IK missing notifications** — notification functions were defined but never called; now wired into poll cycles
- **Telegram bot incomplete** — `/stats`, `/top`, `/poll`, `/status`, `/interval` commands now support all 9 platforms
- **table_map incomplete** — pins, goals, tags, historical analytics, groups, and links now include all 9 platforms
- **AO3 work discovery** — narrowed regex to only match works in the listing section, not sidebar/related works
- **DA cookie validation** — now checks for authenticated indicators instead of generic page words
- **IB login check** — removed overly permissive `status_code == 200` fallback
- **IB rating unlock** — response now checked for errors (prevents silent adult content filtering)
- **AO3 login detection** — changed fragile "greeting" text match to `class="greeting"` attribute check
- **SF empty CSRF** — login now fails early with clear error instead of proceeding with empty token
- **SF poll log** — `new_watchers_found` was accepted but silently dropped from SQL UPDATE
- **Rate limit constants** — AO3/DA/WP/IK/SqW clients now use config.py values instead of hardcoded local copies
- **SqW dead code** — removed unused `guest_match` variable
- **IK unused import** — removed `from urllib.parse import urlencode`
- **Frontend: compare chip IDs** — SF/SqW/AO3 now use `parseInt()` matching other platforms
- **Frontend: overview activity** — recent activity timeline now merges all 9 platforms
- **Frontend: groups dropdown** — all 9 platforms available for adding group members
- **Frontend: metric labels** — pinned submissions, growth rates, and analytics use correct platform-specific labels (reads/votes for WP, likes for IK)
- **Frontend: poll interval settings** — added UI controls for SqW/AO3/DA/WP/IK
- **Frontend: interval stacking** — auto-refresh and poll progress intervals now cleared before recreation

### Added
- **FA watcher spam protection** — 3-layer system: keyword filter, confirmation delay (must survive 2 poll cycles), profile sniff (zero-activity detection)
- **FA watcher digest mode** — `fa_watcher_notification_mode` setting: immediate, daily, or off
- **Pagination safety limits** — all client pagination loops capped at 1000 pages to prevent infinite loops
- **Async context managers** — all 9 client classes support `async with` for safe resource cleanup
- **Transport-level retries** — all HTTP clients retry on connection errors (2 retries via httpx transport)
- **Client shutdown cleanup** — atexit handlers close persistent HTTP clients on app termination
- Bullet character consistency — SF/SqW/AO3 Telegram messages now use `•` matching other platforms

---

## [1.4.0] - 2026-03-09

### Added
- **AO3 (Archive of Our Own)** platform support — dashboard, submissions, detail, compare, settings, polling, Telegram notifications
- **DeviantArt** platform support — cookie-based auth, gallery tracking, deviation stats (views, favorites, comments, downloads)
- **Wattpad** platform support — public API, story stats (reads, votes, comments, reading lists), no auth required
- **Itaku** platform support — public API, image/post tracking (likes, comments, reshares), no auth required
- Changelog file

---

## [1.3.1] - 2026-03-08

### Added
- **SquidgeWorld** platform support (full stack)
  - OTW Archive scraper with Anubis bot challenge solver
  - Login via username/password with CSRF token extraction
  - Works discovery and detail scraping (hits, kudos, comments, bookmarks, word count, chapters)
  - Individual kudos user tracking
  - Database schema, queries, poller, REST API (16 endpoints)
  - Frontend: dashboard, submissions table, detail view, compare tool, settings section
  - Overview page integration (totals, platform card, charts)
  - Poll progress bar integration
  - Telegram notifications with platform emoji
- **Headless server mode** (`server.py`) for 24/7 deployment without GUI
  - Runs pollers + dashboard on `0.0.0.0:8420`
  - Docker support with `Dockerfile` and `docker-compose.yml`
  - Environment variable credential injection
  - Graceful SIGTERM/SIGINT handling
- Docker deployment files (`.dockerignore`, `docker-compose.yml`, `Dockerfile`)
- `requirements-server.txt` for server-only dependencies
- Oracle Cloud deployment script (`deploy/setup-oracle.sh`)

---

## [1.3.0] - 2026-03-07

### Added
- **Light/dark theme toggle** with localStorage persistence
- **User-defined tags** — create colour-coded labels and assign them to submissions across platforms
- **Goals** — set metric targets (views, faves, comments) per platform or per submission, track progress with visual cards
- **Pinned submissions** — pin favourites to the top of any platform dashboard
- **Analytics page** — top fans, trending submissions, historical best periods
- **Database backup/restore** — download `.db` file or restore from upload
- **Poll progress bar** — real-time progress indicator during poll cycles
- **SoFurry** platform support (full stack)
  - Email/password + 2FA authentication
  - Gallery scraping with content type detection
  - Stats: views, likes, comments
  - Dashboard, submissions, detail, compare, settings
- `python-multipart` dependency for backup restore endpoint

---

## [1.2.0] - 2026-03-07

### Added
- **Telegram bot command handler** — two-way interaction via `/status`, `/poll`, `/stats` commands
- **Weasyl** platform support (full stack)
  - API key authentication
  - Gallery and submission stats via Weasyl REST API
  - Dashboard, submissions, detail, compare, settings
- **FurAffinity** platform support (full stack)
  - Cookie-based authentication (cookie_a, cookie_b)
  - Scraping via FAExport proxy API
  - Dashboard, submissions, detail, compare, settings
- **Cross-platform overview page** — aggregated stats, merged top lists, per-platform cards and charts
- **Submission groups** — organise submissions from any platform into named groups
- **Cross-platform links** — link the same work across platforms for combined stats
- Watcher tracking for Inkbunny and FurAffinity

---

## [1.1.1] - 2026-03-06

### Added
- Version display and update check in sidebar footer
- "Check for Updates" button in Settings page

---

## [1.1.0] - 2026-03-06

### Added
- **Comprehensive Telegram notifications**
  - Poll summaries after each cycle
  - Milestone alerts (configurable thresholds for views, faves, comments)
  - New fave/comment/watcher alerts
  - Digest reports (daily/weekly)
  - Error notifications for failed polls
- Telegram bot token and chat ID configuration in Settings

---

## [1.0.0] - 2026-03-06

### Added
- Initial release
- **Inkbunny** platform support
  - Username/password API authentication
  - Submission discovery and stats polling (views, favorites, comments)
  - Individual fave user tracking
  - Comment scraping with reply threading
- SQLite database with WAL mode for concurrent access
- FastAPI web dashboard (SPA with hash routing)
  - Dashboard with stat cards, aggregate charts, top lists, growth rates
  - Submissions table with sorting, search, and rating filters
  - Submission detail with time-series charts and date range selection
  - Compare tool (2-5 submissions side by side)
  - Settings page with credential management and preferences
- Background polling with configurable intervals
- Windows system tray integration (pystray)
- Windows toast notifications (winotify)
- PyInstaller packaging for standalone `.exe` distribution
- CSV export for submissions and snapshots
- Run-on-startup via Windows registry
- Minimize-to-tray on close
