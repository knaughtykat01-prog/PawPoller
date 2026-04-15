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
        posted_stale: { icon: '!', cls: 'cell-posted-stale', label: 'Posted (now blocked)' },
        ready_retry: { icon: '↻', cls: 'cell-retry', label: 'Failed prev — retry?' },
        failed_prev: { icon: '✗', cls: 'cell-blocked', label: 'Blocked + prev failed' },
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
                        <span class="cell-legend cell-posted-stale">!</span> Posted (stale)
                        <span class="cell-legend cell-retry">↻</span> Retry
                        <span class="cell-legend cell-blocked">✗</span> Blocked
                        <span class="cell-legend cell-error">⚠</span> Error
                    </span>
                    <button class="btn btn-sm" id="publish-check-recheck">Re-check</button>
                </div>
            </div>
        `;
        document.body.appendChild(modal);

        modal.querySelector('.publish-check-backdrop').addEventListener('click', () => close());
        modal.querySelector('#publish-check-close').addEventListener('click', () => close());
        modal.querySelector('#publish-check-recheck').addEventListener('click', () => {
            if (_currentStory) load(_currentStory);
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
        let totalCells = 0, ready = 0, posted = 0, blocked = 0;
        for (const row of data.matrix) {
            for (const platId of Object.keys(row.cells)) {
                const cell = row.cells[platId];
                totalCells++;
                if (cell.status === 'ready' || cell.status === 'ready_retry') ready++;
                else if (cell.status === 'posted') posted++;
                else if (cell.status === 'blocked' || cell.status === 'posted_stale' || cell.status === 'failed_prev') blocked++;
            }
        }
        sub.innerHTML =
            '<strong>' + data.matrix.length + '</strong> chapter(s) × ' +
            '<strong>' + data.platforms.length + '</strong> platform(s) = ' +
            totalCells + ' combinations &nbsp;|&nbsp; ' +
            '<span class="stat-posted">' + posted + ' posted</span> &nbsp;|&nbsp; ' +
            '<span class="stat-ready">' + ready + ' ready</span> &nbsp;|&nbsp; ' +
            '<span class="stat-blocked">' + blocked + ' blocked</span>';

        // Build matrix table
        let html = '<div class="publish-check-table-wrap"><table class="publish-check-table">';
        html += '<thead><tr><th class="ch-col">Chapter</th>';
        for (const p of data.platforms) {
            html += '<th class="plat-col" title="' + _escape(p.name) + '">' +
                _escape(p.name) + '</th>';
        }
        html += '</tr></thead><tbody>';

        for (const row of data.matrix) {
            const chLabel = row.chapter_index === 0
                ? '<em>Full story</em>'
                : 'Ch ' + row.chapter_index + '. ' + _escape(row.chapter_title);
            html += '<tr data-ch-idx="' + row.chapter_index +
                '" data-ch-title="' + _escape(row.chapter_title) + '">' +
                '<td class="ch-col">' + chLabel + '</td>';
            for (const p of data.platforms) {
                const cell = row.cells[p.id] || { status: 'error', errors: ['Missing'] };
                html += _renderCell(cell, p);
            }
            html += '</tr>';
        }
        html += '</tbody></table></div>';

        // Detail panel placeholder
        html += '<div class="publish-check-detail" id="publish-check-detail">' +
            '<div class="publish-check-detail-empty">Click any cell for details.</div>' +
            '</div>';

        body.innerHTML = html;

        // Wire up cell clicks
        _bindCellClicks(body);
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
        const isReady = cell.status === 'ready' || cell.status === 'ready_retry'
            || cell.status === 'posted';
        const canEdit = cell.supports_edit;

        let html = '<div class="publish-check-detail-section publish-action-panel">';
        html += '<strong>Actions:</strong>';

        if (!isReady && !isPosted) {
            html += '<div class="publish-action-disabled">' +
                'Resolve validation errors before posting.' +
                '</div></div>';
            return html;
        }

        html += '<div class="publish-action-options">';
        html += '<label><input type="checkbox" id="publish-opt-draft" checked> ' +
            'Save as draft (where supported)</label>';
        html += '</div>';

        html += '<div class="publish-action-buttons">';

        // Dry-run is always available
        html += '<button class="btn btn-sm btn-outline" data-publish-action="dry_run">' +
            'Dry Run (preview package)</button>';

        if (isPosted) {
            html += '<button class="btn btn-sm" data-publish-action="update"' +
                (canEdit ? '' : ' disabled title="Platform does not support edit"') + '>' +
                'Update existing</button>';
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
        const draftCheckbox = document.getElementById('publish-opt-draft');
        const draft = draftCheckbox ? draftCheckbox.checked : true;
        const resultBox = document.getElementById('publish-action-result');

        // Live confirm gate
        if (action === 'post' || action === 'update') {
            const draftLabel = draft ? ' as a DRAFT' : ' LIVE';
            const verb = action === 'post' ? 'Post' : 'Update';
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
                '/api/editor/stories/' + encodeURIComponent(_currentStory) + '/publish',
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
                // Refresh the matrix on success so the cell flips to 'posted'
                setTimeout(() => load(_currentStory), 800);
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

    return { open, close };
})();
