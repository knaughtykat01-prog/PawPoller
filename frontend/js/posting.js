/* ── Posting Module — Frontend Pages ─────────────────────────── */
/*
 * Four pages:
 *   1. Upload    (#/posting)           — Select story, platforms, preview, post
 *   2. Queue     (#/posting/queue)     — Pending/scheduled items
 *   3. Published (#/posting/published) — Registry of what's posted where
 *   4. History   (#/posting/log)       — Audit log of all posting actions
 *
 * All rendering uses App._setContent() to replace the #app container.
 * API calls go through the API singleton (api.js).
 */

const PLATFORM_LABELS = {
    ib: '🐾 Inkbunny', fa: '🦊 FurAffinity', ws: '🦎 Weasyl',
    sf: '🐺 SoFurry', bsky: '🦋 Bluesky',
};
const ALL_PLATFORMS = ['ib', 'fa', 'ws', 'sf', 'bsky'];

const Posting = {

    /* ── 1. Upload Page ──────────────────────────────────────── */
    async renderUpload() {
        App._setContent('<div class="page-header"><h2>Upload Story</h2></div><div class="loading">Loading stories...</div>');

        try {
            // Load stories and sync status in parallel
            const [storiesData, syncData] = await Promise.all([
                API.getPostingStories(),
                API.getSyncStatus().catch(() => ({ stories: [] })),
            ]);
            const { stories } = storiesData;
            const syncStories = syncData.stories || [];

            // Build sync status lookup
            const syncMap = {};
            syncStories.forEach(s => { syncMap[s.name] = s; });

            let syncHtml = '';
            if (syncStories.length > 0) {
                const changed = syncStories.filter(s => s.changed);
                const unpublished = syncStories.filter(s => s.status === 'not published');
                syncHtml = `
                    <div class="card sync-status-card" style="margin-bottom: 1rem">
                        <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 0.5rem">
                            <div>
                                <strong>Archive Status</strong> —
                                ${syncStories.length} stories,
                                ${changed.length > 0 ? `<span class="status-badge status-pending">${changed.length} changed</span>` : '<span class="status-badge status-posted">all up to date</span>'}
                                ${unpublished.length > 0 ? `, ${unpublished.length} unpublished` : ''}
                            </div>
                            <div style="display: flex; gap: 0.5rem">
                                <button id="sync-refresh-btn" class="btn btn-sm btn-secondary" title="Refresh status">Refresh</button>
                            </div>
                        </div>
                        <p style="font-size: 12px; color: var(--text-muted); margin: 0.5rem 0 0">
                            To sync after revisions, run <code>pawsync.bat</code> from your PC or use <code>/sync push</code> from desktop PawPoller.
                        </p>
                    </div>`;
            }

            let html = `
                <div class="page-header"><h2>Upload Story</h2>
                    <p class="page-subtitle">Select a story and platforms to publish to</p>
                </div>
                ${syncHtml}
                <div class="posting-form card">
                    <div class="form-group">
                        <label>Story</label>
                        <select id="posting-story-select" class="form-control">
                            <option value="">-- Select a story --</option>
                            ${stories.map(s => `<option value="${Utils.escapeHtml(s.name)}"
                                ${!s.has_tags ? 'disabled' : ''}
                                >${s.name.replace(/_/g, ' ')}${s.has_tags ? '' : ' (no tags)'}${s.has_manifest ? '' : ' (no chapters)'}</option>`).join('')}
                        </select>
                    </div>
                    <div class="form-group">
                        <label>Platforms</label>
                        <div class="platform-checkboxes" id="posting-platforms">
                            ${ALL_PLATFORMS.map(p => `
                                <label class="checkbox-label">
                                    <input type="checkbox" name="platform" value="${p}" checked>
                                    ${PLATFORM_LABELS[p]}
                                </label>
                            `).join('')}
                        </div>
                    </div>
                    <div id="posting-preview" class="posting-preview"></div>
                    <div class="form-actions">
                        <button id="posting-preview-btn" class="btn btn-secondary" disabled>Preview</button>
                        <button id="posting-submit-btn" class="btn btn-primary" disabled>Upload Now</button>
                    </div>
                    <div id="posting-results" class="posting-results"></div>
                </div>`;
            App._setContent(html);

            // Wire events
            const select = document.getElementById('posting-story-select');
            const previewBtn = document.getElementById('posting-preview-btn');
            const submitBtn = document.getElementById('posting-submit-btn');

            select.addEventListener('change', () => {
                const hasValue = select.value !== '';
                previewBtn.disabled = !hasValue;
                submitBtn.disabled = !hasValue;
                document.getElementById('posting-preview').innerHTML = '';
                document.getElementById('posting-results').innerHTML = '';
            });

            previewBtn.addEventListener('click', () => this._loadPreview(select.value));
            submitBtn.addEventListener('click', () => this._doUpload(select.value));

            // Sync refresh button
            const syncRefreshBtn = document.getElementById('sync-refresh-btn');
            if (syncRefreshBtn) {
                syncRefreshBtn.addEventListener('click', () => this.renderUpload());
            }

            // Add sync status indicators to story dropdown
            const options = select.querySelectorAll('option[value]');
            options.forEach(opt => {
                const info = syncMap[opt.value];
                if (info && info.changed) {
                    opt.textContent += ' (changed)';
                }
            });

        } catch (err) {
            App._setContent(`<div class="error-state"><h3>Error loading stories</h3><p>${Utils.escapeHtml(err.message)}</p></div>`);
        }
    },

    async _loadPreview(storyName) {
        const preview = document.getElementById('posting-preview');
        preview.innerHTML = '<div class="loading">Loading story details...</div>';
        try {
            const data = await API.getPostingStory(storyName);
            let chaptersHtml = '';
            if (data.chapters && data.chapters.length > 0) {
                chaptersHtml = `<div class="preview-section">
                    <strong>Chapters (${data.total_chapters}):</strong>
                    <ul>${data.chapters.map(ch => `<li>Ch${ch.index}: ${Utils.escapeHtml(ch.title)} (${ch.word_count.toLocaleString()} words)</li>`).join('')}</ul>
                </div>`;
            }
            let tagsHtml = '';
            if (data.tags_by_platform) {
                const platforms = Object.keys(data.tags_by_platform).filter(p => p !== 'default');
                tagsHtml = `<div class="preview-section">
                    <strong>Tags available for:</strong> ${platforms.join(', ')}
                </div>`;
            }
            preview.innerHTML = `
                <div class="preview-card">
                    <h4>${Utils.escapeHtml(data.name.replace(/_/g, ' '))}</h4>
                    <p><strong>Words:</strong> ${(data.total_words || 0).toLocaleString()} | <strong>Author:</strong> ${Utils.escapeHtml(data.author || 'Unknown')}</p>
                    <p class="preview-desc">${Utils.escapeHtml((data.description || '').substring(0, 200))}${(data.description || '').length > 200 ? '...' : ''}</p>
                    ${chaptersHtml}
                    ${tagsHtml}
                </div>`;
        } catch (err) {
            preview.innerHTML = `<div class="error-inline">${Utils.escapeHtml(err.message)}</div>`;
        }
    },

    async _doUpload(storyName) {
        const platforms = Array.from(document.querySelectorAll('#posting-platforms input:checked')).map(cb => cb.value);
        if (!platforms.length) {
            alert('Select at least one platform');
            return;
        }
        const results = document.getElementById('posting-results');
        const submitBtn = document.getElementById('posting-submit-btn');
        submitBtn.disabled = true;
        submitBtn.textContent = 'Uploading...';
        results.innerHTML = '<div class="loading">Posting to platforms... this may take a minute.</div>';

        try {
            const data = await API.postStory({ story_name: storyName, platforms });
            let lines = data.results.map(r => {
                const emoji = PLATFORM_LABELS[r.platform] || r.platform;
                const ch = r.chapter_title ? `Ch${r.chapter_index} "${Utils.escapeHtml(r.chapter_title)}"` : 'Full';
                if (r.success) {
                    const link = r.external_url ? `<a href="${Utils.escapeHtml(r.external_url)}" target="_blank">${Utils.escapeHtml(r.external_url)}</a>` : '';
                    return `<div class="result-success">${emoji} ${ch} — posted &#10003; ${link}</div>`;
                }
                return `<div class="result-failure">${emoji} ${ch} — failed &#10007; ${Utils.escapeHtml(r.error || '')}</div>`;
            });
            results.innerHTML = `
                <div class="results-summary">${data.successes}/${data.total} uploads successful</div>
                ${lines.join('')}`;
        } catch (err) {
            results.innerHTML = `<div class="error-inline">${Utils.escapeHtml(err.message)}</div>`;
        } finally {
            submitBtn.disabled = false;
            submitBtn.textContent = 'Upload Now';
        }
    },

    /* ── 2. Queue Page ───────────────────────────────────────── */
    async renderQueue() {
        App._setContent('<div class="page-header"><h2>Posting Queue</h2></div><div class="loading">Loading queue...</div>');

        try {
            const { queue } = await API.getPostingQueue({ include_completed: true });
            if (!queue.length) {
                App._setContent(`
                    <div class="page-header"><h2>Posting Queue</h2></div>
                    <div class="empty-state"><h3>Queue is empty</h3><p>Use the Upload page or Telegram /upload command to add items.</p></div>`);
                return;
            }

            const rows = queue.map(item => `
                <tr>
                    <td data-label="Story">${Utils.escapeHtml(item.story_name.replace(/_/g, ' '))}</td>
                    <td data-label="Ch">${item.chapter_index || 'Full'}</td>
                    <td data-label="Platform">${PLATFORM_LABELS[item.platform] || item.platform}</td>
                    <td data-label="Action">${item.action}</td>
                    <td data-label="Status"><span class="status-badge status-${item.status}">${item.status}</span></td>
                    <td data-label="Scheduled">${item.scheduled_at || 'Immediate'}</td>
                    <td data-label="Created">${Utils.escapeHtml(item.created_at || '')}</td>
                    <td data-label="Actions">${item.status === 'pending'
                        ? `<button class="btn btn-sm btn-danger" onclick="Posting._cancelQueue(${item.queue_id})">Cancel</button>`
                        : (item.last_error ? `<span class="error-text" title="${Utils.escapeHtml(item.last_error)}">&#9888;</span>` : '')
                    }</td>
                </tr>`).join('');

            App._setContent(`
                <div class="page-header"><h2>Posting Queue</h2>
                    <p class="page-subtitle">${queue.length} items</p>
                </div>
                <div class="card">
                    <table class="data-table" data-mobile-cards>
                        <thead><tr>
                            <th>Story</th><th>Ch</th><th>Platform</th><th>Action</th>
                            <th>Status</th><th>Scheduled</th><th>Created</th><th>Actions</th>
                        </tr></thead>
                        <tbody>${rows}</tbody>
                    </table>
                </div>`);
        } catch (err) {
            App._setContent(`<div class="error-state"><h3>Error</h3><p>${Utils.escapeHtml(err.message)}</p></div>`);
        }
    },

    async _cancelQueue(queueId) {
        if (!confirm('Cancel this queue item?')) return;
        try {
            await API.cancelPostingQueue(queueId);
            this.renderQueue();
        } catch (err) {
            alert('Cancel failed: ' + err.message);
        }
    },

    /* ── 3. Published Page ───────────────────────────────────── */
    async renderPublished() {
        App._setContent('<div class="page-header"><h2>Published</h2></div><div class="loading">Loading publications...</div>');

        try {
            const { publications } = await API.getPublications();
            if (!publications.length) {
                App._setContent(`
                    <div class="page-header"><h2>Published</h2></div>
                    <div class="empty-state"><h3>Nothing published yet</h3><p>Upload a story to get started.</p></div>`);
                return;
            }

            // Group by story
            const byStory = {};
            publications.forEach(p => {
                if (!byStory[p.story_name]) byStory[p.story_name] = [];
                byStory[p.story_name].push(p);
            });

            let html = `<div class="page-header"><h2>Published</h2>
                <p class="page-subtitle">${publications.length} publications across ${Object.keys(byStory).length} stories</p>
            </div>`;

            for (const [story, pubs] of Object.entries(byStory)) {
                const rows = pubs.map(p => {
                    const ch = p.chapter_index > 0 ? `Ch${p.chapter_index}` : 'Full';
                    const title = p.chapter_title ? Utils.escapeHtml(p.chapter_title) : '';
                    const link = p.external_url
                        ? `<a href="${Utils.escapeHtml(p.external_url)}" target="_blank" title="${Utils.escapeHtml(p.external_url)}">${Utils.escapeHtml(p.external_id).substring(0, 20)}</a>`
                        : (p.external_id || '—');
                    const updated = p.update_count > 0 ? `(${p.update_count} updates)` : '';
                    return `<tr>
                        <td data-label="Platform">${PLATFORM_LABELS[p.platform] || p.platform}</td>
                        <td data-label="Chapter">${ch} ${title}</td>
                        <td data-label="ID">${link}</td>
                        <td data-label="Status"><span class="status-badge status-${p.status}">${p.status}</span></td>
                        <td data-label="Posted">${Utils.escapeHtml(p.first_posted_at || '')}</td>
                        <td data-label="Updated">${Utils.escapeHtml(p.last_updated_at || '—')} ${updated}</td>
                        <td data-label="Actions">
                            <button class="btn btn-sm btn-secondary" onclick="Posting._updateSingle('${Utils.escapeHtml(story)}', '${p.platform}', ${p.chapter_index})">Update</button>
                        </td>
                    </tr>`;
                }).join('');

                html += `
                    <div class="card" style="margin-bottom: 1rem">
                        <h3 style="margin: 0 0 0.5rem">${Utils.escapeHtml(story.replace(/_/g, ' '))}</h3>
                        <table class="data-table" data-mobile-cards>
                            <thead><tr>
                                <th>Platform</th><th>Chapter</th><th>ID</th><th>Status</th>
                                <th>Posted</th><th>Updated</th><th>Actions</th>
                            </tr></thead>
                            <tbody>${rows}</tbody>
                        </table>
                        <div style="margin-top: 0.5rem">
                            <button class="btn btn-sm btn-primary" onclick="Posting._updateAll('${Utils.escapeHtml(story)}')">Update All</button>
                        </div>
                    </div>`;
            }
            App._setContent(html);
        } catch (err) {
            App._setContent(`<div class="error-state"><h3>Error</h3><p>${Utils.escapeHtml(err.message)}</p></div>`);
        }
    },

    async _updateSingle(storyName, platform, chapterIndex) {
        if (!confirm(`Push update for ${storyName.replace(/_/g, ' ')} ch${chapterIndex} on ${platform}?`)) return;
        try {
            await API.updateStory({ story_name: storyName, platforms: [platform], chapters: [chapterIndex] });
            alert('Update sent!');
            this.renderPublished();
        } catch (err) {
            alert('Update failed: ' + err.message);
        }
    },

    async _updateAll(storyName) {
        if (!confirm(`Push updates for ALL ${storyName.replace(/_/g, ' ')} publications?`)) return;
        try {
            await API.updateStory({ story_name: storyName });
            alert('Updates sent!');
            this.renderPublished();
        } catch (err) {
            alert('Update failed: ' + err.message);
        }
    },

    /* ── 4. History / Log Page ───────────────────────────────── */
    async renderLog() {
        App._setContent('<div class="page-header"><h2>Posting History</h2></div><div class="loading">Loading log...</div>');

        try {
            const { log } = await API.getPostingLog({ limit: 100 });
            if (!log.length) {
                App._setContent(`
                    <div class="page-header"><h2>Posting History</h2></div>
                    <div class="empty-state"><h3>No posting activity yet</h3></div>`);
                return;
            }

            const rows = log.map(entry => {
                const ch = entry.chapter_index > 0 ? `Ch${entry.chapter_index}` : 'Full';
                const statusClass = entry.status === 'success' ? 'status-posted' : 'status-failed';
                const link = entry.external_url
                    ? `<a href="${Utils.escapeHtml(entry.external_url)}" target="_blank">Link</a>`
                    : '';
                const error = entry.error_message
                    ? `<span class="error-text" title="${Utils.escapeHtml(entry.error_message)}">&#9888; ${Utils.escapeHtml(entry.error_message).substring(0, 40)}</span>`
                    : '';
                const dur = entry.duration_seconds ? `${entry.duration_seconds.toFixed(1)}s` : '';
                return `<tr>
                    <td data-label="Time">${Utils.escapeHtml(entry.created_at || '')}</td>
                    <td data-label="Story">${Utils.escapeHtml((entry.story_name || '').replace(/_/g, ' '))}</td>
                    <td data-label="Ch">${ch}</td>
                    <td data-label="Platform">${PLATFORM_LABELS[entry.platform] || entry.platform}</td>
                    <td data-label="Action">${entry.action}</td>
                    <td data-label="Status"><span class="status-badge ${statusClass}">${entry.status}</span></td>
                    <td data-label="Link">${link}</td>
                    <td data-label="Duration">${dur}</td>
                    <td data-label="Error">${error}</td>
                </tr>`;
            }).join('');

            App._setContent(`
                <div class="page-header"><h2>Posting History</h2>
                    <p class="page-subtitle">${log.length} entries</p>
                </div>
                <div class="card">
                    <table class="data-table" data-mobile-cards>
                        <thead><tr>
                            <th>Time</th><th>Story</th><th>Ch</th><th>Platform</th>
                            <th>Action</th><th>Status</th><th>Link</th><th>Duration</th><th>Error</th>
                        </tr></thead>
                        <tbody>${rows}</tbody>
                    </table>
                </div>`);
        } catch (err) {
            App._setContent(`<div class="error-state"><h3>Error</h3><p>${Utils.escapeHtml(err.message)}</p></div>`);
        }
    },
};
