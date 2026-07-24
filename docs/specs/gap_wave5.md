# Gap Wave 5 — the last parked creator features

**Status:** SPEC — building now · **Author:** Rhys + Claude (fable) · **Date:** 2026-07-24

> The remaining G9 parked batch, minus multi-user/roles (deliberately deferred — a large architectural change that
> unwinds the just-hardened single-admin model; needs its own design pass). Four scout passes grounded this. Ships as
> **two releases**: the M/S trio (watermark + series + beta-share) as 2.186, then the Commissions module as 2.187.

## 1. Watermark on export (S)  → 2.186
Stamp a configurable text/handle onto artwork images before they post. **One choke point** covers every image
platform: `posting/manager.post_artwork` between `build_artwork_package` (`:359`) and `validate` (`:364`) — produce a
watermarked temp copy, swap `package.file_path`, delete the temp after `poster.post` (+ the `hash_file` at `:382`).
- New `posting/watermark.py` `apply(src, text, position, opacity) -> (path, tmp_or_None)` (PIL `ImageDraw`/`ImageFont`;
  DejaVuSans on the server, `ImageFont.load_default()` fallback), mirroring `_prepare_bsky_image`'s cleanup contract.
- Settings (4 keys) in `routes/artwork_api.py` get/save (`:557`/`:574`): `artwork_watermark_enabled`,
  `artwork_watermark_text`, `artwork_watermark_position` (corner), `artwork_watermark_opacity`.
- Add an explicit `Pillow` pin to `requirements-server.txt` (currently only transitive via weasyprint).
- Artwork export is always single-image (multi split at import) — no carousel handling. Posts carousels = later.
- UI: a "Watermark" block in Settings → General → Publishing (enable, text, corner, opacity).

## 2. Cross-platform series (M)  → 2.186
Group ordered distinct stories into a named Series (Book 1, Book 2…). **v1 is display-only** — no poster supports AO3
series / SF folders today (documented later add-on). Collections is the wrong vehicle (pools one piece's footprint,
unordered).
- Storage = **`story.json` fields** (stories are file-based; no new table): `series` (name), `series_index` (int).
  Read path: `StoryInfo` (`story_reader.py:68`), `_load_from_story_json` (`:496`), `_story_entry` (`:200`), pass
  through `assemble_works` (`submissions_api.py:114`). Write path already accepts arbitrary metadata
  (`MetadataSaveRequest`) — no endpoint change.
- UI: a "📚 Series: <name> #<n>" pill on the library card (`bookshelf.js` `_book`) + work-detail; a Series
  assign control on the work-detail page (saves via the existing metadata PUT); a "group by series" affordance in the
  library (client-side, over the field the API now returns).

## 3. Beta-reader draft share (M)  → 2.186
A tokenized, read-only public link to preview a story draft — no login.
- New `database/share_tokens.py` `ensure_share_tokens_table` (`share_token PK, story_name, created_at, expires_at,
  enabled`), wired into `_run_migrations` beside the inbox/personas ensures. Token = `secrets.token_urlsafe`.
- Endpoints (`routes/editor_api.py`): `POST .../stories/{name}/share` (create/return token+URL, optional expiry),
  `GET .../stories/{name}/share` (list active), `DELETE .../share/{token}` (revoke).
- **Public route** `@app.get("/share/{token}")` in `dashboard.py` (epub-viewer route shape): look up token → check
  enabled + not-expired → render the story via the editor's existing self-contained styled-HTML path
  (`convert_to_styled_html_external_css(mode="full")` + inline `<style>`, `editor_api.py:576-610`) → return HTML.
  404 on miss/expired. Add `"/share/"` to `_AUTH_EXEMPT_PREFIXES` (`dashboard.py:389`) + a `/share/` CSP branch
  (`:304`, mirror the epub-viewer special-case so inline `<style>` is allowed).
- UI: a "🔗 Share draft" button in the editor's `#editor-actions-secondary` cluster → creates a token, shows the
  copyable link (+ a note it's public/read-only), and a revoke.

## 4. Commissions module (L)  → 2.187
A client/commission tracker. **Single self-contained table** (simpler than Collections — skip the members/rollup
half), copying the Collections full-stack skeleton across its 8 surfaces.
- `database/commissions_schema.sql` — `commissions(id, client_name, description, price REAL, currency,
  status DEFAULT 'quote', due_date, artwork_name, deliver_sites TEXT '[]' JSON, notes, created_at, updated_at)`;
  register in `db.py init_db` schema-load list. Status set `{quote, accepted, paid, wip, delivered}` validated in the
  handlers.
- `database/commissions_queries.py` (CRUD only, copy `collections_queries.py:49-104`) · `routes/commissions_api.py`
  (`/api/commissions`, include in `dashboard.py`) · `frontend/js/api.js` methods · `frontend/js/commissions.js`
  (hub `#/commissions` + detail, CSP-safe delegated clicks) · `commissions.css` · nav entry + script tag in
  `index.html` · route dispatch in `app.js`.
- Money = data only (no payment integration). `artwork_name` links a delivered piece (deep-link
  `#/artwork/image/<name>`); `deliver_sites` = JSON array of platform codes from `_ALL_POSTER_IDS`.
- A board-ish hub: group by status, due-date sort, per-commission status advance.

**Tests:** watermark (produces a distinct temp file, disabled = passthrough); series (round-trips through story.json →
StoryInfo → assemble_works); share tokens (create/lookup/expire/revoke, public route 404s on bad token);
commissions (CRUD + status validation + deliver_sites JSON round-trip). Full suite pre-deploy for each release.
