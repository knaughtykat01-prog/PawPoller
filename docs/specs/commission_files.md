# Commission attachments + archive — spec

**Status:** SPEC — building now · **Date:** 2026-07-24 · Ships as **2.188.0**

> Two adds to the 2.187 Commissions module, both from Rhys: (1) **any-file attachments** on a commission — drop in
> reference sheets, WIPs, the DM screenshot, a contract PDF, a source zip; (2) an **archive** so completed commissions
> drop off the active board without being deleted.

## 1. Attachments (any file)
Files live on disk (not in SQLite) under the persistent data volume — **no new table**, the list is the directory.

- **Storage:** `config.DATA_DIR / "commission_files" / <cid> / <safe_name>`. `DATA_DIR` = `/app/data` in Docker (the
  `pawpoller-data` volume) so uploads survive a rebuild. Dir created lazily on first upload.
- **Filename safety:** `_safe_name(name)` — basename only, keep `[A-Za-z0-9._ -]`, other chars → `_`, cap ~120 chars,
  non-empty fallback `file`. Collision → ` (n)` before the extension. Serve path re-anchored + `relative_to` guard
  (mirrors `posting_api.get_story_image`), so a crafted `{filename}` can't escape the commission's folder.
- **Cap:** 25 MB/file (`_MAX_FILE_BYTES`). Over → 413.
- **Endpoints** (`routes/commissions_api.py`, all behind dashboard auth like the rest of the module):
  - `POST /api/commissions/{cid}/files` (multipart `file`) → `{filename, size}`. 404 if commission missing, 413 if too big.
  - `GET  /api/commissions/{cid}/files` → `{files: [{filename, size, uploaded_at, is_image, url}]}` (dir stat, newest first).
  - `GET  /api/commissions/{cid}/files/{filename}` → the bytes. **Images** inline with their image content-type;
    **everything else** `application/octet-stream` + `Content-Disposition: attachment` + `X-Content-Type-Options: nosniff`
    (a stored `.html` can never render/execute in the owner's session).
  - `DELETE /api/commissions/{cid}/files/{filename}` → remove one file.
- **Cascade:** the commission-delete handler also `rmtree`s `commission_files/<cid>`.
- **Frontend (detail page):** an **Attachments** section — a drop-zone (drag-drop + click-to-browse `<input type=file multiple>`),
  a grid of **image thumbnails** (inline `<img>` preview) and **file chips** for non-images (📄 icon + name + size + download),
  each with a `×` delete. `api.js`: `uploadCommissionFile / getCommissionFiles / deleteCommissionFile` (raw multipart fetch).

## 2. Archive completed
- **Column:** `archived INTEGER NOT NULL DEFAULT 0` — added to `commissions_schema.sql` (fresh installs) **and** a guarded
  `ALTER TABLE commissions ADD COLUMN archived …` in `db.py._run_migrations` (the 2.187 table already exists on the VM
  without it — the migration is required, not optional).
- **Queries:** `list_commissions(conn, archived=False)` filters `WHERE archived = ?`; `set_archived(conn, cid, bool)`;
  `count_archived(conn)`; `_row` carries `archived`.
- **API:** list endpoint takes `?archived=1` (default active) and returns `archived_count` for the toggle label;
  `archived` accepted in the PATCH allowed-set (coerced 0/1).
- **Frontend:** board defaults to active; an **📦 Archived (N)** toggle flips to a simple archived list (each with
  **Unarchive**). Card + detail get an **Archive** action (Unarchive when already archived). Archived rows never appear
  in the active status columns.

## Tests (`tests/test_commission_files.py`)
Attachments: upload→list→download (bytes match)→delete; oversized → 413; traversal `{filename}` → 403/404; commission
delete removes the folder. Archive: `set_archived` hides from the default list, shows under `?archived=1`, `count_archived`
tracks it, unarchive restores. API layer via TestClient (`config.DATA_DIR` monkeypatched to a temp dir).
