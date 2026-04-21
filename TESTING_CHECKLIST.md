# PawPoller v2.13.0 — Testing Checklist

Test each item and mark with [x] when verified.

---

## Editor — Story Management

- [ ] **Create New Story**: Click "+ Create New Story" → fill title/author → Create → navigates to editor with template MASTER.md
- [ ] **Genre template**: Select a genre (e.g. Erotica) → rating auto-updates to Explicit → story.json has pre-filled tags
- [ ] **File upload**: Create new story with a .txt or .html file uploaded → MASTER.md contains the file content, not the template
- [ ] **Folder name auto-gen**: Type a title with spaces → folder name field auto-fills with underscores
- [ ] **Import from Platform**: Click "Import from Platform" → shows IB/SF/FA submissions → click Import on one → story created and opens in editor

## Editor — Editing Features

- [ ] **Anchor toolbar**: Click each anchor button (T, Sub, Body, Warning, →, ←, Phone, End) → anchor inserted at cursor in CodeMirror
- [ ] **Format tabs**: Click Clean HTML / SoFurry / BBCode / Styled tabs → preview updates to that format
- [ ] **Selective regen**: Click Regenerate dropdown → pick "BBCode only" → only BBCode regenerated (check results list)
- [ ] **Regen staleness warning**: Edit MASTER.md → save → open Publish Check → amber "regenerate" banner appears
- [ ] **Regen from Publish Check**: Click "Regenerate now" in the amber banner → files rebuild → banner disappears

## Editor — Metadata Drawer

- [ ] **Per-platform descriptions**: Open metadata → Basics → expand "Per-platform descriptions" → Short and Announcement textareas appear
- [ ] **Tag space→underscore**: Type a tag with a space in the Default tab → auto-converts to underscore
- [ ] **Fix spaces button**: Click "Fix spaces" → tags with spaces converted to underscores, count shown
- [ ] **Sort A-Z button**: Click "Sort A-Z" → tags reorder alphabetically
- [ ] **Tag browser Selected tab**: Open expanded tag browser → click "Selected" chip → shows only selected tags
- [ ] **Platform badges on tags**: In tag browser, selected tags show platform badges (DEF, SF, IB, etc.)
- [ ] **Tag browser grid layout**: Tag cards fill the full width (3-4 columns), not single column
- [ ] **Chapter tags Inkbunny tab**: Expand a chapter → tag tabs show Default/SF/IB/WP (4 tabs)
- [ ] **Chapter thumbnail upload**: Expand a chapter → click Upload → select image → filename appears, story.json updated
- [ ] **Cover image upload**: Cover section → upload image → preview shows

## Publish Check

- [ ] **No-credentials status**: Platform without credentials shows lock icon, not error
- [ ] **Live-publish warning**: Uncheck "Save as draft" → yellow warning banner appears
- [ ] **Confirm dialog for live**: Click Post with draft unchecked → confirm dialog has extra warning paragraph
- [ ] **Readable dry-run**: Click Dry Run → shows structured summary (title, rating, tags list), not raw JSON
- [ ] **Action result log**: Do a few dry runs → "Recent actions" section appears below detail panel
- [ ] **Relative timestamps**: Click a posted cell → "Posted" and "Last updated" show "(Xd ago)" suffix
- [ ] **Edit button**: Go to Posting → story detail → "Edit in Editor" button links to editor
- [ ] **Schedule button**: Click Schedule → datetime picker appears → set future time → confirm → queue item shows

## Publish Check — Bulk Actions

- [ ] **Publish all new**: Footer "Publish all new" button → preflight dialog with checkboxes → works
- [ ] **Update drifted**: Footer "Update drifted" button → works for drifted cells
- [ ] **Row publish**: Click row number badge → bulk posts that row

## Polling & Notifications

- [ ] **No startup poll**: Restart app → no immediate poll cycle (waits for scheduled interval)
- [ ] **AO3 retry**: Check server logs after next poll → AO3 login shows retry attempts with HTTP status codes
- [ ] **Telegram errors**: If a platform fails → Telegram message shows friendly label + hint (not raw exception)
- [ ] **Telegram error test**: Verify "Login blocked — Likely Cloudflare/rate-limit" style messages

## Settings

- [ ] **Settings sync — Check status**: Settings → Data → Sync → "Check status" → shows version + key count
- [ ] **Settings sync — Pull**: Click "Pull from server" → shows "Pulled X keys"
- [ ] **Settings sync — Push**: Click "Push to server" → shows "Pushed X keys"
- [ ] **Credential vault — Enable**: Settings → Data → "Enable encryption" → success message
- [ ] **Credential vault — Status**: Click "Check status" → shows mode + vault exists
- [ ] **Credential vault — Disable**: Click "Disable encryption" → confirm → back to plaintext
- [ ] **Browser login (desktop)**: Settings → Platforms → FA → "Login via Browser" → popup opens FA login page
- [ ] **Browser login fallback (server)**: On server dashboard → FA shows "Open login page" link instead

## Setup Wizard

- [ ] **First-run detection**: Delete `setup_complete` from settings.json → reload → wizard appears
- [ ] **Step 1 Welcome**: "Get Started" button advances to step 2
- [ ] **Step 2 Archive path**: Enter path → Next saves it to settings
- [ ] **Step 3 Platforms**: Shows 11 platform cards with connect links
- [ ] **Step 4 Done**: "Go to Dashboard" marks setup complete and redirects

## Import from Platforms

- [ ] **IB import**: Import an IB story → MASTER.md has full text content (BBCode converted to Markdown)
- [ ] **SF import**: Import an SF story → MASTER.md has full text content (HTML converted to Markdown)
- [ ] **FA import**: Import an FA story → story.json has tags/rating/description (PDF = description only, TXT = full text)
- [ ] **Name collision**: Import a story that already exists → creates with `_2` suffix
- [ ] **Import source tracking**: Check imported story's story.json → `import_source` has platform/id/url

## Desktop Build

- [ ] **PyInstaller build**: `python -m PyInstaller inkbunny_analytics.spec --noconfirm` → succeeds
- [ ] **App launches**: `dist/PawPoller/PawPoller.exe` → opens dashboard in native window
- [ ] **Tray icon**: System tray shows PawPoller icon with menu

## Server Deploy

- [ ] **Docker build**: `docker compose up -d --build` → container starts
- [ ] **Health check**: `curl http://localhost:8420/api/health` → 200 OK
- [ ] **Logs clean**: `docker compose logs --tail=30` → no errors on startup

## GitHub

- [ ] **README renders**: Visit repo on GitHub → README displays correctly
- [ ] **LICENSE visible**: MIT license file present
- [ ] **Lint workflow**: Push triggers lint → passes (ruff + JS syntax)
- [ ] **Build workflow**: Tag a release → build triggers → exe artifact created
