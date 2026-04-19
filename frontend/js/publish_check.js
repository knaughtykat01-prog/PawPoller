/* PublishCheck — Phase 6a: validation-only publishability matrix.
 *
 * Opens a modal that runs /api/editor/stories/{name}/publish-check and
 * renders a chapter × platform grid. Each cell shows whether the
 * combination is ready, blocked by validation errors, or already posted.
 *
 * No HTTP requests are made to external platforms — this is purely a
 * pre-flight check before the actual publish flow lands in Phase 6b.
 */

window.PublishCheck = (function () {
    const STATUS_LABELS = {
        ready: { icon: '✓', cls: 'cell-ready', label: 'Ready' },
        blocked: { icon: '✗', cls: 'cell-blocked', label: 'Blocked' },
        posted: { icon: '✓', cls: 'cell-posted', label: 'Posted' },
        posted_drifted: { icon: '↑', cls: 'cell-posted-drifted', label: 'Posted (local content changed)' },
        posted_stale: { icon: '!', cls: 'cell-posted-stale', label: 'Posted (now blocked)' },
        deleted_upstream: { icon: '⊘', cls: 'cell-deleted', label: 'Deleted on platform — re-post?' },
        ready_retry: { icon: '↻', cls: 'cell-retry', label: 'Failed prev — retry?' },
        failed_prev: { icon: '✗', cls: 'cell-blocked', label: 'Blocked + prev failed' },
        not_supported: { icon: '–', cls: 'cell-na', label: 'N/A — per-chapter only' },
        error: { icon: '⚠', cls: 'cell-error', label: 'Error' },
    };

    function _ensureModal() {
        let modal = document.getElementById('publish-check-modal');
        if (modal) return modal;
        modal = document.createElement('div');
        modal.id = 'publish-check-modal';
        modal.className = 'publish-check-modal';
        modal.innerHTML = `
            <div class="publish-check-backdrop"></div>
            <div class="publish-check-dialog" role="dialog" aria-label="Publish check">
                <div class="publish-check-header">
                    <div>
                        <div class="publish-check-title" id="publish-check-title">Publish Check</div>
                        <div class="publish-check-subtitle" id="publish-check-subtitle"></div>
                    </div>
                    <button class="publish-check-close" id="publish-check-close" aria-label="Close">&times;</button>
                </div>
                <div class="publish-check-body" id="publish-check-body">
                    <div class="publish-check-loading">Loading...</div>
                </div>
                <div class="publish-check-footer">
                    <span class="publish-check-legend">
                        <span class="cell-legend cell-ready">✓</span> Ready
                        <span class="cell-legend cell-posted">✓</span> Posted
                        <span class="cell-legend cell-posted-drifted">↑</span> Drifted
                        <span class="cell-legend cell-deleted">⊘</span> Deleted
                        <span class="cell-legend cell-posted-stale">!</span> Stale
                        <span class="cell-legend cell-retry">↻</span> Retry
                        <span class="cell-legend cell-blocked">✗</span> Blocked
                        <span class="cell-legend cell-error">⚠</span> Error
                    </span>
                    <button class="btn btn-sm btn-outline" id="publish-check-verify" title="Probe each platform to detect deletions">Verify posted</button>
                    <button class="btn btn-sm btn-outline" id="bulk-all-new" title="Post every ready cell">Publish all new</button>
                    <button class="btn btn-sm btn-outline" id="bulk-all-drifted" title="Update every drifted cell">Update drifted</button>
                    <button class="btn btn-sm" id="publish-check-recheck">Re-check</button>
                </div>
            </div>
        `;
        document.body.appendChild(modal);

        modal.querySelector('.publish-check-backdrop').addEventListener('click', () => close());
        modal.querySelector('#publish-check-close').addEventListener('click', () => close());
        modal.querySelector('#publish-check-recheck').addEventListener('click', (e) => {
            if (!_currentStory) return;
            e.currentTarget.disabled = true;
            load(_currentStory).finally(() => { e.currentTarget.disabled = false; });
        });
        modal.querySelector('#publish-check-verify').addEventListener('click', () => {
            if (_currentStory) verify(_currentStory);
        });
        modal.querySelector('#bulk-all-new').addEventListener('click', () => {
            const targets = _collectTargets('all_new');
            if (targets.length) _openBulkPreflight(targets, 'all_new');
        });
        modal.querySelector('#bulk-all-drifted').addEventListener('click', () => {
            const targets = _collectTargets('all_drifted');
            if (targets.length) _openBulkPreflight(targets, 'all_drifted');
        });

        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape' && modal.classList.contains('open')) close();
        });

        return modal;
    }

    let _currentStory = null;

    async function open(storyName) {
        _currentStory = storyName;
        const modal = _ensureModal();
        modal.classList.add('open');
        document.getElementById('publish-check-title').textContent =
            'Publish Check — ' + storyName.replace(/_/g, ' ');
        document.getElementById('publish-check-subtitle').textContent = '';
        document.getElementById('publish-check-body').innerHTML =
            '<div class="publish-check-loading">Checking ' +
            'every chapter against every platform...</div>';
        await load(storyName);
    }

    function close() {
        const modal = document.getElementById('publish-check-modal');
        if (modal) modal.classList.remove('open');
    }

    async function verify(storyName) {
        const btn = document.getElementById('publish-check-verify');
        const original = btn ? btn.textContent : 'Verify posted';
        if (btn) { btn.disabled = true; btn.textContent = 'Probing...'; }
        try {
            const resp = await fetch(
                '/api/editor/stories/' + encodeURIComponent(storyName) + '/verify',
                { method: 'POST' },
            );
            if (!resp.ok) throw new Error('HTTP ' + resp.status);
            const data = await resp.json();
            const msg = data.deleted + ' deleted, ' + data.still_live +
                ' still live, ' + data.not_probed + ' not probed';
            if (btn) { btn.textContent = msg; setTimeout(() => {
                btn.textContent = original; btn.disabled = false;
            }, 2400); }
            // Reload matrix so deletions appear as ⊘ cells
            await load(storyName);
        } catch (e) {
            if (btn) {
                btn.textContent = 'Probe failed';
                setTimeout(() => { btn.textContent = original; btn.disabled = false; }, 2000);
            }
        }
    }

    async function load(storyName) {
        try {
            const resp = await fetch(
                '/api/editor/stories/' + encodeURIComponent(storyName) + '/publish-check'
            );
            if (!resp.ok) {
                const text = await resp.text();
                throw new Error(text || ('HTTP ' + resp.status));
            }
            const data = await resp.json();
            _render(data);
        } catch (e) {
            document.getElementById('publish-check-body').innerHTML =
                '<div class="publish-check-error">Failed to load: ' +
                _escape(e.message) + '</div>';
        }
    }

    function _render(data) {
        const body = document.getElementById('publish-check-body');
        const sub = document.getElementById('publish-check-subtitle');

        // Stats line
        let totalCells = 0, ready = 0, posted = 0, drifted = 0, deleted = 0, blocked = 0;
        for (const row of data.matrix) {
            for (const platId of Object.keys(row.cells)) {
                const cell = row.cells[platId];
                totalCells++;
                if (cell.status === 'ready' || cell.status === 'ready_retry') ready++;
                else if (cell.status === 'posted') posted++;
                else if (cell.status === 'posted_drifted') drifted++;
                else if (cell.status === 'deleted_upstream') deleted++;
                else if (cell.status === 'blocked' || cell.status === 'posted_stale' || cell.status === 'failed_prev') blocked++;
            }
        }
        sub.innerHTML =
            '<strong>' + data.matrix.length + '</strong> row(s) × ' +
            '<strong>' + data.platforms.length + '</strong> platform(s) = ' +
            totalCells + ' combinations &nbsp;|&nbsp; ' +
            '<span class="stat-posted">' + posted + ' posted</span> &nbsp;|&nbsp; ' +
            (drifted ? '<span class="stat-drifted">' + drifted + ' drifted</span> &nbsp;|&nbsp; ' : '') +
            (deleted ? '<span class="stat-deleted">' + deleted + ' deleted</span> &nbsp;|&nbsp; ' : '') +
            '<span class="stat-ready">' + ready + ' ready</span> &nbsp;|&nbsp; ' +
            '<span class="stat-blocked">' + blocked + ' blocked</span>';

        // Build matrix table
        let html = '<div class="publish-check-table-wrap"><table class="publish-check-table">';
        html += '<thead><tr><th class="ch-col">Chapter</th>';
        for (const p of data.platforms) {
            html += '<th class="plat-col" title="' + _escape(p.name) + '">' +
                _escape(p.name) + '</th>';
        }
        html += '<th class="bulk-col"></th>';
        html += '</tr></thead><tbody>';

        for (const row of data.matrix) {
            const isFull = row.chapter_index === 0;
            const chLabel = isFull
                ? '<strong>Full story</strong> <span class="row-hint">(' +
                  _escape(row.chapter_title) + ')</span>'
                : 'Ch ' + row.chapter_index + '. ' + _escape(row.chapter_title);
            const rowCls = isFull ? 'row-full' : 'row-chapter';
            const titleAttr = isFull ? row.chapter_title : row.chapter_title;
            html += '<tr class="' + rowCls + '" data-ch-idx="' + row.chapter_index +
                '" data-ch-title="' + _escape(titleAttr) + '">' +
                '<td class="ch-col">' + chLabel + '</td>';
            for (const p of data.platforms) {
                const cell = row.cells[p.id] || { status: 'error', errors: ['Missing'] };
                html += _renderCell(cell, p);
            }
            // Row-end bulk button — count actionable cells
            let rowActionable = 0;
            for (const p of data.platforms) {
                const c = row.cells[p.id];
                if (c && (c.status === 'ready' || c.status === 'ready_retry' ||
                    c.status === 'deleted_upstream' || c.status === 'posted_drifted')) {
                    rowActionable++;
                }
            }
            html += '<td class="bulk-col">';
            if (rowActionable > 0) {
                html += '<button class="btn btn-xs btn-outline bulk-row-btn" ' +
                    'data-ch-idx="' + row.chapter_index + '" title="Bulk publish this row">' +
                    rowActionable + '</button>';
            }
            html += '</td>';
            html += '</tr>';
        }
        html += '</tbody></table></div>';

        // Detail panel placeholder
        html += '<div class="publish-check-detail" id="publish-check-detail">' +
            '<div class="publish-check-detail-empty">Click any cell for details.</div>' +
            '</div>';

        body.innerHTML = html;

        // Cache matrix data for bulk target collection
        _lastMatrixData = data;

        // Wire up cell clicks
        _bindCellClicks(body);

        // Wire row-end bulk buttons
        body.querySelectorAll('.bulk-row-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                const chIdx = parseInt(btn.dataset.chIdx);
                const targets = _collectTargets('row', chIdx);
                if (targets.length) _openBulkPreflight(targets, 'row');
            });
        });
    }

    function _renderCell(cell, plat) {
        const meta = STATUS_LABELS[cell.status] || STATUS_LABELS.error;
        const titleParts = [meta.label];
        if (cell.errors && cell.errors.length) {
            titleParts.push(cell.errors.join('; '));
        }
        if (cell.existing && cell.existing.external_url) {
            titleParts.push('Posted: ' + cell.existing.external_url);
        }
        return '<td class="publish-check-cell ' + meta.cls +
            '" data-cell=\'' + _escape(JSON.stringify(cell)) + '\'' +
            ' data-plat-id="' + _escape(plat.id) + '"' +
            ' data-plat-name="' + _escape(plat.name) + '"' +
            ' title="' + _escape(titleParts.join(' — ')) + '">' +
            meta.icon + '</td>';
    }

    // Cell click handler — passes plat info + chapter to detail
    function _bindCellClicks(body) {
        body.querySelectorAll('.publish-check-cell').forEach(td => {
            td.addEventListener('click', () => {
                body.querySelectorAll('.publish-check-cell.selected')
                    .forEach(x => x.classList.remove('selected'));
                td.classList.add('selected');
                const tr = td.closest('tr');
                const chIdx = parseInt(tr.dataset.chIdx);
                const chTitle = tr.dataset.chTitle;
                _showDetail(
                    JSON.parse(td.dataset.cell),
                    td.dataset.platId,
                    td.dataset.platName,
                    chIdx,
                    chTitle,
                );
            });
        });
    }

    function _showDetail(cell, platId, platName, chIdx, chTitle) {
        const detail = document.getElementById('publish-check-detail');
        const meta = STATUS_LABELS[cell.status] || STATUS_LABELS.error;
        let html = '<div class="publish-check-detail-header">' +
            '<span class="cell-legend ' + meta.cls + '">' + meta.icon + '</span>' +
            ' <strong>' + _escape(platName) + '</strong> &middot; ' + meta.label +
            '</div>';

        if (cell.errors && cell.errors.length) {
            html += '<div class="publish-check-detail-section"><strong>Validation errors:</strong><ul>';
            for (const err of cell.errors) {
                html += '<li>' + _escape(err) + '</li>';
            }
            html += '</ul></div>';
        }

        html += '<div class="publish-check-detail-section"><strong>Package:</strong><ul>';
        if (cell.title) html += '<li>Title: <code>' + _escape(cell.title) + '</code></li>';
        html += '<li>Tags: ' + cell.tag_count + '</li>';
        if (cell.file_path) {
            const sizeLabel = cell.file_size
                ? (cell.file_size / 1024).toFixed(0) + ' KB'
                : 'missing';
            const limit = cell.max_file_size
                ? ' / ' + (cell.max_file_size / 1024 / 1024).toFixed(0) + ' MB max'
                : '';
            html += '<li>File: <code>' + _escape(cell.file_path) + '</code> (' +
                sizeLabel + limit + ')</li>';
        }
        html += '<li>Mode required: <code>' + cell.requires_mode + '</code></li>';
        html += '<li>Supports edit: ' + (cell.supports_edit ? 'yes' : 'no — would delete+repost') + '</li>';
        html += '</ul></div>';

        if (cell.existing) {
            html += '<div class="publish-check-detail-section"><strong>Existing publication:</strong><ul>';
            html += '<li>Status: <code>' + _escape(cell.existing.status) + '</code></li>';
            if (cell.existing.external_id) {
                html += '<li>External ID: <code>' + _escape(cell.existing.external_id) + '</code></li>';
            }
            if (cell.existing.external_url) {
                html += '<li>URL: <a href="' + _escape(cell.existing.external_url) +
                    '" target="_blank" rel="noopener">' + _escape(cell.existing.external_url) + '</a></li>';
            }
            if (cell.existing.posted_at) {
                html += '<li>Posted: ' + _escape(cell.existing.posted_at) + '</li>';
            }
            if (cell.existing.updated_at) {
                html += '<li>Last updated: ' + _escape(cell.existing.updated_at) + '</li>';
            }
            html += '</ul></div>';
        }

        // --- Action panel (Phase 6b) ---
        html += _renderActionPanel(cell, platId, platName, chIdx, chTitle);

        detail.innerHTML = html;
        _bindActionPanel(platId, platName, chIdx, chTitle, cell);
    }

    function _renderActionPanel(cell, platId, platName, chIdx, chTitle) {
        const isPosted = cell.existing && cell.existing.status === 'posted';
        const isDeleted = cell.status === 'deleted_upstream';
        const isDrifted = cell.status === 'posted_drifted';
        const isReady = cell.status === 'ready' || cell.status === 'ready_retry'
            || cell.status === 'posted' || cell.status === 'posted_drifted'
            || cell.status === 'deleted_upstream';
        const canEdit = cell.supports_edit;

        let html = '<div class="publish-check-detail-section publish-action-panel">';
        html += '<strong>Actions:</strong>';

        if (!isReady && !isPosted) {
            html += '<div class="publish-action-disabled">' +
                'Resolve validation errors before posting.' +
                '</div></div>';
            return html;
        }

        if (isDrifted) {
            html += '<div class="publish-action-drift-banner">' +
                '<strong>Local content has changed</strong> since this was posted. ' +
                'Hit <em>Update existing</em> to push the fresh file.' +
                '</div>';
        }

        if (isDeleted) {
            html += '<div class="publish-action-deleted-banner">' +
                '<strong>Submission was deleted on ' + _escape(platName) + '.</strong> ' +
                'The previous URL is dead. Hit <em>Re-post</em> to create a new submission.' +
                '</div>';
        }

        html += '<div class="publish-action-options">';
        html += '<label><input type="checkbox" id="publish-opt-draft" checked> ' +
            'Save as draft (where supported)</label>';
        html += '</div>';

        html += '<div class="publish-action-buttons">';

        // Dry-run is always available
        html += '<button class="btn btn-sm btn-outline" data-publish-action="dry_run">' +
            'Dry Run (preview package)</button>';

        if (isDeleted) {
            // Re-post creates a brand new submission (goes through post, not edit)
            html += '<button class="btn btn-sm btn-primary" data-publish-action="post">' +
                'Re-post to ' + _escape(platName) + '</button>';
        } else if (isPosted) {
            const updateClass = isDrifted ? 'btn btn-sm btn-primary' : 'btn btn-sm';
            html += '<button class="' + updateClass + '" data-publish-action="update"' +
                (canEdit ? '' : ' disabled title="Platform does not support edit"') + '>' +
                'Update all' + (isDrifted ? ' (push fresh content)' : '') + '</button>';
            // Metadata-only — faster when only tags/title/summary changed
            html += '<button class="btn btn-sm btn-outline" data-publish-action="update_metadata"' +
                (canEdit ? '' : ' disabled title="Platform does not support edit"') + '>' +
                'Metadata only</button>';
            if (cell.existing && cell.existing.external_url) {
                html += '<a class="btn btn-sm btn-outline" href="' +
                    _escape(cell.existing.external_url) +
                    '" target="_blank" rel="noopener">Open</a>';
            }
        } else if (isReady) {
            html += '<button class="btn btn-sm btn-primary" data-publish-action="post">' +
                'Post to ' + _escape(platName) + '</button>';
        }

        html += '</div>';
        html += '<div class="publish-action-result" id="publish-action-result"></div>';
        html += '</div>';
        return html;
    }

    function _bindActionPanel(platId, platName, chIdx, chTitle, cell) {
        const detail = document.getElementById('publish-check-detail');
        if (!detail) return;
        detail.querySelectorAll('[data-publish-action]').forEach(btn => {
            btn.addEventListener('click', () => {
                const action = btn.dataset.publishAction;
                _executeAction(action, platId, platName, chIdx, chTitle);
            });
        });
    }

    async function _executeAction(action, platId, platName, chIdx, chTitle) {
        // Capture the current story NOW so we don't end up posting to or
        // reloading a different story if the user closes+reopens the modal
        // for a different story while a request is in flight.
        const storyName = _currentStory;
        if (!storyName) return;

        const draftCheckbox = document.getElementById('publish-opt-draft');
        const draft = draftCheckbox ? draftCheckbox.checked : true;
        const resultBox = document.getElementById('publish-action-result');

        // Live confirm gate
        if (action === 'post' || action === 'update' || action === 'update_metadata') {
            const draftLabel = draft ? ' as a DRAFT' : ' LIVE';
            const verb = action === 'post' ? 'Post'
                : action === 'update_metadata' ? 'Update metadata only'
                : 'Update';
            const ok = confirm(
                verb + ' "' + chTitle + '" to ' + platName + draftLabel + '?\n\n' +
                'This will make a real request to the platform.'
            );
            if (!ok) return;
        }

        if (resultBox) {
            resultBox.innerHTML = '<div class="publish-action-loading">Working...</div>';
        }

        try {
            const resp = await fetch(
                '/api/editor/stories/' + encodeURIComponent(storyName) + '/publish',
                {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        platform: platId,
                        chapter: chIdx,
                        action: action,
                        draft: draft,
                        confirm_live: action !== 'dry_run',
                    }),
                }
            );
            const data = await resp.json();
            _renderActionResult(data, action);
            if (action !== 'dry_run' && data.ok) {
                // Refresh the matrix on success — only if the user is still
                // looking at the same story. Prevents a late success callback
                // from clobbering the view if the user moved on.
                setTimeout(() => {
                    if (_currentStory === storyName) load(storyName);
                }, 800);
            }
        } catch (e) {
            if (resultBox) {
                resultBox.innerHTML = '<div class="publish-action-error">Failed: ' +
                    _escape(e.message) + '</div>';
            }
        }
    }

    function _renderActionResult(data, action) {
        const box = document.getElementById('publish-action-result');
        if (!box) return;

        if (action === 'dry_run') {
            const cls = data.ok ? 'publish-action-success' : 'publish-action-error';
            let html = '<div class="' + cls + '"><strong>' +
                (data.ok ? 'Dry run OK' : 'Dry run failed') + '</strong></div>';
            if (data.errors && data.errors.length) {
                html += '<ul>';
                for (const e of data.errors) html += '<li>' + _escape(e) + '</li>';
                html += '</ul>';
            }
            if (data.package) {
                html += '<details><summary>Package</summary><pre>' +
                    _escape(JSON.stringify(data.package, null, 2)) +
                    '</pre></details>';
            }
            box.innerHTML = html;
            return;
        }

        // Real post / update
        const cls = data.ok ? 'publish-action-success' : 'publish-action-error';
        let html = '<div class="' + cls + '"><strong>' +
            (data.ok ? '✓ Success' : '✗ Failed') + '</strong></div>';
        if (data.results && data.results.length) {
            for (const r of data.results) {
                html += '<div class="publish-action-result-row">';
                if (r.success) {
                    html += '<div>Posted: ';
                    if (r.external_url) {
                        html += '<a href="' + _escape(r.external_url) +
                            '" target="_blank" rel="noopener">' +
                            _escape(r.external_url) + '</a>';
                    } else if (r.external_id) {
                        html += 'ID ' + _escape(r.external_id);
                    }
                    html += '</div>';
                    if (r.duration) {
                        html += '<div class="publish-action-meta">' +
                            r.duration.toFixed(1) + 's</div>';
                    }
                } else {
                    if (r.queued_desktop) {
                        html += '<div>Queued for desktop (server unable to post). ' +
                            'Open desktop PawPoller to flush queue.</div>';
                    }
                    if (r.error) {
                        html += '<div class="publish-action-error-msg">' +
                            _escape(r.error) + '</div>';
                    }
                }
                html += '</div>';
            }
        }
        box.innerHTML = html;
    }

    function _escape(s) {
        return String(s == null ? '' : s)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    // ── Phase 6d: Bulk publish ─────────────────────────────────
    //
    // Three entry points: row-end button, "Publish all new", "Update
    // all drifted". Each collects actionable targets from the matrix
    // data, shows a preflight dialog, then runs sequential requests.

    let _lastMatrixData = null;  // cached from _render for bulk target collection

    function _collectTargets(mode, chIdx) {
        if (!_lastMatrixData) return [];
        const targets = [];
        for (const row of _lastMatrixData.matrix) {
            if (mode === 'row' && row.chapter_index !== chIdx) continue;
            for (const p of _lastMatrixData.platforms) {
                const cell = row.cells[p.id];
                if (!cell) continue;
                if (mode === 'all_new' || mode === 'row') {
                    if (cell.status === 'ready' || cell.status === 'ready_retry' || cell.status === 'deleted_upstream') {
                        targets.push({
                            platId: p.id, platName: p.name,
                            chIdx: row.chapter_index, chTitle: row.chapter_title,
                            action: 'post', cell: cell,
                        });
                    }
                }
                if (mode === 'all_drifted' || mode === 'row') {
                    if (cell.status === 'posted_drifted') {
                        targets.push({
                            platId: p.id, platName: p.name,
                            chIdx: row.chapter_index, chTitle: row.chapter_title,
                            action: 'update', cell: cell,
                        });
                    }
                }
            }
        }
        return targets;
    }

    function _openBulkPreflight(targets, mode) {
        if (!targets.length) return;
        const storyName = _currentStory;
        if (!storyName) return;

        const overlay = document.createElement('div');
        overlay.className = 'bulk-preflight-overlay';

        const modeLabel = mode === 'all_new' ? 'Publish all new'
            : mode === 'all_drifted' ? 'Update all drifted'
            : 'Publish row';

        let html = '<div class="bulk-preflight-dialog">';
        html += '<div class="bulk-preflight-header">';
        html += '<strong>' + modeLabel + '</strong> — ' + targets.length + ' target(s)';
        html += '<button class="bulk-preflight-close">&times;</button>';
        html += '</div>';

        html += '<div class="bulk-preflight-body">';
        html += '<div class="bulk-preflight-list">';
        for (let i = 0; i < targets.length; i++) {
            const t = targets[i];
            const verb = t.action === 'post' ? 'Post' : 'Update';
            html += '<label class="bulk-target-row">' +
                '<input type="checkbox" data-idx="' + i + '" checked> ' +
                '<span class="bulk-target-verb">' + verb + '</span> ' +
                _escape(t.chTitle || 'Full story') + ' → ' +
                '<strong>' + _escape(t.platName) + '</strong>' +
                '</label>';
        }
        html += '</div>';

        html += '<div class="bulk-preflight-options">';
        html += '<label><input type="checkbox" id="bulk-draft" checked> Save as draft</label>';
        html += '</div>';
        html += '</div>';

        html += '<div class="bulk-preflight-footer">';
        html += '<button class="btn btn-sm btn-outline" data-bulk="cancel">Cancel</button>';
        html += '<button class="btn btn-sm btn-outline" data-bulk="dry_run">Dry Run All</button>';
        html += '<button class="btn btn-sm btn-primary" data-bulk="go">' +
            modeLabel + ' (' + targets.length + ')</button>';
        html += '</div></div>';

        overlay.innerHTML = html;
        document.body.appendChild(overlay);

        // Update count when checkboxes change
        const updateCount = () => {
            const checked = overlay.querySelectorAll('.bulk-target-row input:checked').length;
            const goBtn = overlay.querySelector('[data-bulk="go"]');
            if (goBtn) goBtn.textContent = modeLabel + ' (' + checked + ')';
        };
        overlay.querySelectorAll('.bulk-target-row input').forEach(cb => {
            cb.addEventListener('change', updateCount);
        });

        overlay.querySelector('.bulk-preflight-close').addEventListener('click', () => {
            overlay.remove();
        });
        overlay.querySelector('[data-bulk="cancel"]').addEventListener('click', () => {
            overlay.remove();
        });
        overlay.querySelector('[data-bulk="dry_run"]').addEventListener('click', () => {
            const selected = _getSelectedTargets(overlay, targets);
            if (!selected.length) return;
            overlay.remove();
            _runBulk(storyName, selected, true);
        });
        overlay.querySelector('[data-bulk="go"]').addEventListener('click', () => {
            const selected = _getSelectedTargets(overlay, targets);
            if (!selected.length) return;
            const draft = overlay.querySelector('#bulk-draft')?.checked ?? true;
            const ok = confirm(
                modeLabel + ': ' + selected.length + ' item(s)' +
                (draft ? ' as DRAFT' : ' LIVE') +
                '.\n\nThis will make real requests to external platforms.'
            );
            if (!ok) return;
            overlay.remove();
            _runBulk(storyName, selected, false, draft);
        });
    }

    function _getSelectedTargets(overlay, targets) {
        const selected = [];
        overlay.querySelectorAll('.bulk-target-row input:checked').forEach(cb => {
            const idx = parseInt(cb.dataset.idx);
            if (targets[idx]) selected.push(targets[idx]);
        });
        return selected;
    }

    let _bulkAborted = false;

    async function _runBulk(storyName, targets, dryRun, draft) {
        _bulkAborted = false;

        // Replace the detail panel with a progress view
        const body = document.getElementById('publish-check-body');
        if (!body) return;

        let html = '<div class="bulk-progress">';
        html += '<div class="bulk-progress-header" id="bulk-progress-header">' +
            (dryRun ? 'Dry run' : 'Publishing') + ' 0/' + targets.length +
            '</div>';
        html += '<div class="bulk-progress-list" id="bulk-progress-list">';
        for (let i = 0; i < targets.length; i++) {
            const t = targets[i];
            const verb = t.action === 'post' ? 'Post' : 'Update';
            html += '<div class="bulk-progress-item" id="bulk-item-' + i + '">' +
                '<span class="bulk-item-status">⏳</span> ' +
                verb + ' ' + _escape(t.chTitle || 'Full story') +
                ' → ' + _escape(t.platName) +
                '<span class="bulk-item-result" id="bulk-result-' + i + '"></span>' +
                '</div>';
        }
        html += '</div>';
        html += '<div class="bulk-progress-footer">';
        if (!dryRun) {
            html += '<button class="btn btn-sm" id="bulk-cancel-btn">Cancel remaining</button>';
        }
        html += '<button class="btn btn-sm btn-outline" id="bulk-close-btn" disabled>Close & refresh</button>';
        html += '</div></div>';

        body.innerHTML = html;

        if (!dryRun) {
            document.getElementById('bulk-cancel-btn')?.addEventListener('click', () => {
                _bulkAborted = true;
                const btn = document.getElementById('bulk-cancel-btn');
                if (btn) { btn.disabled = true; btn.textContent = 'Cancelling...'; }
            });
        }

        let succeeded = 0, failed = 0, skipped = 0;

        for (let i = 0; i < targets.length; i++) {
            if (_bulkAborted) {
                skipped += targets.length - i;
                for (let j = i; j < targets.length; j++) {
                    _updateBulkItem(j, '⊘', 'Cancelled');
                }
                break;
            }

            const t = targets[i];
            _updateBulkItem(i, '⏳', 'Working...');
            _updateBulkHeader(i, targets.length, succeeded, failed);

            try {
                const action = dryRun ? 'dry_run' : t.action;
                const resp = await fetch(
                    '/api/editor/stories/' + encodeURIComponent(storyName) + '/publish',
                    {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            platform: t.platId,
                            chapter: t.chIdx,
                            action: action,
                            draft: draft ?? true,
                            confirm_live: !dryRun,
                        }),
                    }
                );
                const data = await resp.json();

                if (dryRun) {
                    _updateBulkItem(i, data.ok ? '✓' : '✗',
                        data.ok ? 'OK' : (data.errors || []).join('; '));
                    if (data.ok) succeeded++; else failed++;
                } else if (data.ok) {
                    const url = data.results?.[0]?.external_url;
                    const queued = data.results?.[0]?.queued_desktop;
                    _updateBulkItem(i, '✓',
                        queued ? 'Queued for desktop' :
                        url ? '<a href="' + _escape(url) + '" target="_blank">Posted</a>' : 'Done');
                    succeeded++;
                } else {
                    const err = data.results?.[0]?.error || 'Failed';
                    _updateBulkItem(i, '✗', _escape(err));
                    failed++;
                }
            } catch (e) {
                _updateBulkItem(i, '✗', _escape(e.message));
                failed++;
            }
        }

        _updateBulkHeader(targets.length, targets.length, succeeded, failed, skipped);

        const closeBtn = document.getElementById('bulk-close-btn');
        if (closeBtn) {
            closeBtn.disabled = false;
            closeBtn.addEventListener('click', () => {
                if (_currentStory === storyName) load(storyName);
            });
        }
        const cancelBtn = document.getElementById('bulk-cancel-btn');
        if (cancelBtn) cancelBtn.style.display = 'none';
    }

    function _updateBulkItem(idx, icon, text) {
        const item = document.getElementById('bulk-item-' + idx);
        if (!item) return;
        const status = item.querySelector('.bulk-item-status');
        const result = document.getElementById('bulk-result-' + idx);
        if (status) status.textContent = icon;
        if (result) result.innerHTML = ' — ' + text;
        item.className = 'bulk-progress-item ' +
            (icon === '✓' ? 'bulk-success' : icon === '✗' ? 'bulk-fail' : '');
    }

    function _updateBulkHeader(current, total, ok, fail, skip) {
        const h = document.getElementById('bulk-progress-header');
        if (!h) return;
        h.innerHTML = 'Progress: ' + current + '/' + total +
            ' — <span class="stat-ready">' + ok + ' succeeded</span>' +
            (fail ? ', <span class="stat-blocked">' + fail + ' failed</span>' : '') +
            (skip ? ', ' + skip + ' cancelled' : '');
    }

    return { open, close };
})();
