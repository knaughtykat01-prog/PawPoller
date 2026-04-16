# Phase 6d Plan — Bulk Publish Actions

Generated 2026-04-17 by design session. Design-phase doc; no code changes yet.

## Recommended path

**Frontend-orchestrated loop over the existing `/api/editor/stories/{name}/publish` endpoint.** No new bulk endpoint. No server-side state. No SSE/WebSocket. Just iterate the targets client-side, fire sequentially, render progress as each resolves. Existing `confirm_live`, rate limit (`poster._rate_limit()` runs inside each `post_story` / `update_story` call), desktop-queue fallback, and audit logs all keep working unchanged.

### Why not a `/publish-bulk` endpoint

- **Pro bulk endpoint**: one request, server-side state persists across browser close, easier mid-batch cancel signalling.
- **Con**: duplicates orchestration that already works per-cell, needs a new job-state table or in-memory registry, needs SSE streaming, needs its own cancel route, and the `confirm_live` guard has to be collapsed into an array-level flag (weaker safety).
- Batches are small (a story has ~8 platforms × ~5 chapters = dozens of cells, minutes of wall clock). Browser-tab resume is listed as a nice-to-have; not worth the server-state cost now. Ship frontend loop first; promote to server if users ask for resume.

## UX

Three entry points, all in the matrix modal:

1. **Row-end button**: append a `<td>` per row, after the last platform column, rendering a compact "Publish row" button. Enabled only when the row has at least one `ready` / `deleted_upstream` / `posted_drifted` cell.
2. **Top toolbar**: two buttons next to the existing "Verify posted" / "Re-check" in `.publish-check-footer`:
   - "Publish all new" (primary, disabled if zero `ready` cells)
   - "Update all drifted" (outline, disabled if zero `posted_drifted` cells)
3. No context menu. Discoverability over cleverness.

### Preflight dialog (one confirm, replacing N individual `confirm()` calls)

Full modal overlay (not `window.confirm`) with:

- Scrollable target list: `Ch 3 → FA (post)`, `Ch 3 → AO3 (update)`, etc.
- Platform/chapter checkbox filters (satisfies "only these platforms / chapters" nice-to-have for ~free).
- Draft toggle (same semantics as single-cell).
- Dry-run toggle → fires loop with `action: 'dry_run'` for every target, produces a report view instead of posting.
- Buttons: `Cancel` / `Dry run` / `Publish N items LIVE`.
- Text: "This will make N real requests to external platforms."

### Progress panel (replaces preflight in-place once firing starts)

- Header: `Publishing 3/9 — 2 succeeded, 0 failed`
- Live list of targets with per-row status icon updating as each settles (queued / in-flight / success + URL / failed + error / queued-desktop).
- `Cancel remaining` button — flips an `aborted` flag; loop checks between requests and stops dequeuing. In-flight request is left to resolve (as required).
- On completion: summary with `Close & refresh matrix` button. Failures are not dismissive — list stays visible for copy-paste of errors.

**Matrix update strategy:** Do NOT reload after each cell (expensive, causes flicker, loses scroll). Instead, locally patch each cell's `data-cell` + CSS class on success using the response payload, then do one full `load(storyName)` reload when the batch ends.

## Backend approach

- No new endpoint.
- Reuse `POST /api/editor/stories/{name}/publish` per target.
- Sequential per-platform grouping on the frontend: group targets by `platform`, run platforms in parallel, chapters sequentially within a platform. This mirrors `manager.post_story`'s intra-platform rate limit and gives multi-platform speedup for free.
- Each call sends `confirm_live: true` (user already gated at the preflight). Server guard remains; UI simply passes it through per-request. This preserves the requirement that `confirm_live` stays — just batched at the UI layer.
- FA desktop queue: each request returns `queued_desktop: true` without blocking. Tally those into the summary ("3 queued for desktop — open PawPoller desktop to flush").

## Progress / cancellation mechanism

Plain promise loop with an `AbortController`:

- `controller = new AbortController()` created per batch.
- Each `fetch` receives `signal: controller.signal`.
- Cancel button calls `controller.abort()` (in-flight request may still complete on the server — documented as the "in-flight completes" behaviour).
- Remaining queued targets short-circuit via `if (aborted) break;`.
- Per-target state kept in a plain JS array `[{platId, chIdx, status, result}]` re-rendered each transition.

## Files to touch

- `frontend/js/publish_check.js` — add `_openBulkPreflight`, `_runBulk`, `_renderProgress`, wire three entry-points, patch `_render` to add row-end action column and footer buttons.
- `frontend/css/editor.css` — styles for preflight dialog, progress rows, row-end button cell.
- `CHANGELOG.md` — Phase 6d entry.
- `documentation_guide.md` — update Story Editor → Publish Check section with bulk flow.

**No backend changes.** `routes/editor_api.py`, `posting/manager.py`, posters: untouched.

## Complexity

| Sub-task | Size |
|---|---|
| Row-end "Publish row" button + handler | S |
| Footer "Publish all new" / "Update all drifted" buttons | S |
| Target enumeration (filter matrix by status → target list) | S |
| Preflight dialog (target list + filters + draft/dry-run toggles) | M |
| Batch runner (per-platform fan-out, AbortController, per-target state machine) | M |
| Progress panel + live per-target status rendering | M |
| Local matrix cell patching on success (skip full reload mid-batch) | S |
| Summary + error list at end | S |
| Dry-run-whole-batch report view | S |
| CSS for new UI | S |
| Manual test pass (IB + SF + AO3 + SQW on Test Story) | M |
| Docs + CHANGELOG | S |

Total: **~M overall**. All vanilla JS inside one ~520-line file and one CSS file. ~1 day of work.

## Nice-to-haves decision

- **Configurable subset (platforms/chapters):** included — cheap once preflight exists (just checkboxes).
- **Dry-run whole batch:** included — same runner with `action: 'dry_run'`.
- **Browser-close resume:** **deferred**. Needs server-side job state + polling endpoint + reconciliation on page reopen. Not worth the cost until real demand shows up. Document the limitation: "closing the tab cancels the batch; in-flight posts complete server-side."

## Critical files for implementation (reference list)

- `frontend/js/publish_check.js` (edit)
- `frontend/css/editor.css` (edit)
- `routes/editor_api.py` (read-only reference; confirms no backend touch needed)
- `posting/manager.py` (read-only reference; confirms rate limit + desktop queue behaviour stays intact)
- `CHANGELOG.md` (add entry)
