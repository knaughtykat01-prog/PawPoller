/* ── Posting Module — Frontend Pages ─────────────────────────── */
/*
 * Five pages:
 *   1. Stories    (#/posting)              — Story card hub (browse all stories)
 *   2. Detail     (#/posting/story/{name}) — Single story detail with platform controls
 *   3. Queue      (#/posting/queue)        — Pending/scheduled items
 *   4. Published  (#/posting/published)    — Registry of what's posted where (legacy, redirects to stories)
 *   5. History    (#/posting/log)          — Audit log of all posting actions
 */

const PLATFORM_LABELS = {
    ib: '🐾 Inkbunny', fa: '🦊 FurAffinity', ws: '🦎 Weasyl',
    sf: '🐺 SoFurry', sqw: '🦑 SquidgeWorld', bsky: '🦋 Bluesky', wp: '📙 Wattpad',
    inkbunny: '🐾 Inkbunny', furaffinity: '🦊 FurAffinity', weasyl: '🦎 Weasyl',
    sofurry: '🐺 SoFurry', squidgeworld: '🦑 SquidgeWorld', bluesky: '🦋 Bluesky', wattpad: '📙 Wattpad',
};
const PLATFORM_EMOJI = {
    ib: '🐾', fa: '🦊', ws: '🦎', sf: '🐺', sqw: '🦑', bsky: '🦋', wp: '📙',
    inkbunny: '🐾', furaffinity: '🦊', weasyl: '🦎', sofurry: '🐺', squidgeworld: '🦑', bluesky: '🦋', wattpad: '📙',
};
const PLAT_ID = { inkbunny: 'ib', furaffinity: 'fa', weasyl: 'ws', sofurry: 'sf', squidgeworld: 'sqw', bluesky: 'bsky', wattpad: 'wp' };

const Posting = {

    /* ── 1. Stories Hub (Card Grid) ──────────────────────────── */
    async renderUpload() {
        App._setContent('<div class="page-header"><h2>Stories</h2></div><div class="loading">Loading stories...</div>');

        try {
            const { stories } = await API.getPostingStories();

            if (!stories.length) {
                App._setContent(`
                    <div class="page-header"><h2>Stories</h2></div>
                    <div class="empty-state"><h3>No stories found</h3><p>Sync your archive with <code>pawsync.bat</code></p></div>`);
                return;
            }

            const cards = stories.map(s => {
                const title = Utils.escapeHtml(s.title || s.name.replace(/_/g, ' '));
                const words = (s.word_count || 0).toLocaleString();
                const chs = s.chapters || 0;
                const rating = s.rating ? `<span class="story-rating rating-${s.rating}">${s.rating}</span>` : '';
                const category = s.category ? `<span class="story-category">${Utils.escapeHtml(s.category)}</span>` : '';

                // Platform badges
                const published = s.published_platforms || [];
                const available = (s.platforms || []).map(p => PLAT_ID[p] || p);
                const platformBadges = available.map(p => {
                    const emoji = PLATFORM_EMOJI[p] || '📦';
                    const isPublished = published.includes(p);
                    return `<span class="plat-badge ${isPublished ? 'plat-published' : 'plat-available'}" title="${isPublished ? 'Published' : 'Not uploaded'}">${emoji}</span>`;
                }).join('');

                // Cover image
                const coverSrc = s.images && s.images.cover ? `/api/posting/image/${Utils.escapeHtml(s.name)}/${Utils.escapeHtml(s.images.cover)}` : '';
                const coverHtml = coverSrc ? `<div class="story-card-cover" style="background-image:url('${coverSrc}')"></div>` : '';

                // Description
                const desc = s.description ? Utils.escapeHtml(s.description.substring(0, 120)) + (s.description.length > 120 ? '...' : '') : '';

                // Warnings
                const warnings = (s.warnings || []).length > 0
                    ? `<span class="story-warning" title="${Utils.escapeHtml(s.warnings.join(', '))}">⚠</span>` : '';

                return `
                    <a href="#/posting/story/${Utils.escapeHtml(s.name)}" class="story-card">
                        ${coverHtml}
                        <div class="story-card-body">
                            <div class="story-card-header">
                                <h3 class="story-card-title">${title} ${warnings}</h3>
                                <div class="story-card-meta">${rating} ${category}</div>
                            </div>
                            <p class="story-card-desc">${desc}</p>
                            <div class="story-card-footer">
                                <span class="story-card-stats">${words} words${chs > 0 ? ` · ${chs} ch` : ''}</span>
                                <div class="story-card-platforms">${platformBadges}</div>
                            </div>
                        </div>
                    </a>`;
            }).join('');

            App._setContent(`
                <div class="page-header"><h2>Stories</h2>
                    <p class="page-subtitle">${stories.length} stories in archive</p>
                </div>
                <div class="story-card-grid">${cards}</div>`);
        } catch (err) {
            App._setContent(`<div class="error-state"><h3>Error loading stories</h3><p>${Utils.escapeHtml(err.message)}</p></div>`);
        }
    },

    /* ── 2. Story Detail Page ────────────────────────────────── */
    async renderStoryDetail(storyName) {
        App._setContent('<div class="loading">Loading story...</div>');

        try {
            const data = await API.getPostingStory(storyName);
            const title = Utils.escapeHtml(data.title || storyName.replace(/_/g, ' '));

            // Info section
            const infoHtml = `
                <div class="story-detail-info card">
                    <h2>${title}</h2>
                    <p class="page-subtitle">by ${Utils.escapeHtml(data.author || 'Unknown')}</p>
                    <div class="story-detail-meta">
                        <span>${(data.total_words || 0).toLocaleString()} words</span>
                        <span>${data.total_chapters || 0} chapters</span>
                        ${data.rating ? `<span class="story-rating rating-${data.rating}">${data.rating}</span>` : ''}
                        ${data.category ? `<span>${Utils.escapeHtml(data.category)}</span>` : ''}
                        ${data.fandom ? `<span>${Utils.escapeHtml(data.fandom)}</span>` : ''}
                    </div>
                    ${data.warnings && data.warnings.length ? `<p class="story-warnings">⚠ ${Utils.escapeHtml(data.warnings.join(', '))}</p>` : ''}
                    <p class="story-detail-desc">${Utils.escapeHtml(data.description || '')}</p>
                </div>`;

            // Chapters section
            let chaptersHtml = '';
            if (data.chapters && data.chapters.length > 0) {
                const chRows = data.chapters.map(ch => `
                    <div class="chapter-row">
                        <span class="chapter-num">Ch${ch.index}</span>
                        <span class="chapter-title">${Utils.escapeHtml(ch.title)}</span>
                        <span class="chapter-words">${(ch.word_count || 0).toLocaleString()}w</span>
                    </div>`).join('');
                chaptersHtml = `<div class="card"><h3>Chapters</h3>${chRows}</div>`;
            }

            // Platforms section — published + available
            const published = data.published_platforms || [];
            const unpublished = data.unpublished_platforms || [];
            const pubs = data.publications || [];

            let pubRows = '';
            if (pubs.length > 0) {
                pubRows = pubs.map(p => {
                    const emoji = PLATFORM_EMOJI[p.platform] || '📦';
                    const ch = p.chapter_index > 0 ? `Ch${p.chapter_index}` : 'Full';
                    const link = p.external_url
                        ? `<a href="${Utils.escapeHtml(p.external_url)}" target="_blank">View</a>` : '';
                    let statsHtml = '';
                    if (p.stats) {
                        const v = p.stats.views || p.stats.hits || p.stats.reads || 0;
                        const f = p.stats.favorites_count || p.stats.kudos || p.stats.votes || 0;
                        const c = p.stats.comments_count || 0;
                        statsHtml = `<span class="pub-stats">${v.toLocaleString()}v / ${f.toLocaleString()}f / ${c.toLocaleString()}c</span>`;
                    }
                    const updated = p.last_updated_at || p.first_posted_at || '';
                    return `
                        <div class="pub-row">
                            <span class="pub-platform">${emoji} ${(PLATFORM_LABELS[p.platform] || p.platform).replace(/^.+\s/, '')}</span>
                            <span class="pub-chapter">${ch}</span>
                            ${statsHtml}
                            <span class="pub-date">${Utils.escapeHtml(updated)}</span>
                            <span class="pub-actions">${link}
                                <button class="btn btn-sm btn-secondary" onclick="Posting._updateSingle('${Utils.escapeHtml(storyName)}', '${p.platform}', ${p.chapter_index})">Update</button>
                            </span>
                        </div>`;
                }).join('');
            }

            // Upload buttons for unpublished platforms
            let uploadHtml = '';
            if (unpublished.length > 0) {
                const uploadBtns = unpublished.map(p => {
                    const emoji = PLATFORM_EMOJI[p] || '📦';
                    const label = (PLATFORM_LABELS[p] || p).replace(/^.+\s/, '');
                    return `<button class="btn btn-sm btn-primary" onclick="Posting._uploadTo('${Utils.escapeHtml(storyName)}', '${p}')">${emoji} Upload to ${label}</button>`;
                }).join('');
                uploadHtml = `<div class="upload-actions">${uploadBtns}</div>`;
            }

            const platformsHtml = `
                <div class="card">
                    <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:0.5rem;margin-bottom:0.75rem">
                        <h3 style="margin:0">Platforms</h3>
                        ${pubs.length > 0 ? `<button class="btn btn-sm btn-primary" onclick="Posting._updateAll('${Utils.escapeHtml(storyName)}')">Update All</button>` : ''}
                    </div>
                    ${pubRows || '<p class="page-subtitle">Not published anywhere yet.</p>'}
                    ${uploadHtml}
                </div>`;

            // Formats section
            const formats = data.formats || {};
            const formatList = Object.keys(formats).map(f =>
                `<span class="format-badge">${f.replace(/_/g, ' ')}</span>`
            ).join('');
            const formatsHtml = formatList ? `<div class="card"><h3>Available Formats</h3><div class="format-list">${formatList}</div></div>` : '';

            App._setContent(`
                <a href="#/posting" class="back-link">&larr; All Stories</a>
                ${infoHtml}
                ${platformsHtml}
                ${chaptersHtml}
                ${formatsHtml}`);

        } catch (err) {
            App._setContent(`<div class="error-state"><h3>Error</h3><p>${Utils.escapeHtml(err.message)}</p></div>`);
        }
    },

    async _uploadTo(storyName, platform) {
        if (!confirm(`Upload ${storyName.replace(/_/g, ' ')} to ${PLATFORM_LABELS[platform] || platform}?`)) return;
        try {
            const data = await API.postStory({ story_name: storyName, platforms: [platform] });
            const successes = data.successes || 0;
            alert(successes > 0 ? 'Upload complete!' : 'Upload failed — check the log.');
            this.renderStoryDetail(storyName);
        } catch (err) {
            alert('Upload failed: ' + err.message);
        }
    },

    async _updateSingle(storyName, platform, chapterIndex) {
        if (!confirm(`Push update for ${storyName.replace(/_/g, ' ')} on ${PLATFORM_LABELS[platform] || platform}?`)) return;
        try {
            await API.updateStory({ story_name: storyName, platforms: [platform], chapters: [chapterIndex] });
            alert('Update sent!');
            this.renderStoryDetail(storyName);
        } catch (err) {
            alert('Update failed: ' + err.message);
        }
    },

    async _updateAll(storyName) {
        if (!confirm(`Push updates for ALL ${storyName.replace(/_/g, ' ')} publications?`)) return;
        try {
            await API.updateStory({ story_name: storyName });
            alert('Updates sent!');
            this.renderStoryDetail(storyName);
        } catch (err) {
            alert('Update failed: ' + err.message);
        }
    },

    /* ── 3. Queue Page ───────────────────────────────────────── */
    async renderQueue() {
        App._setContent('<div class="page-header"><h2>Posting Queue</h2></div><div class="loading">Loading queue...</div>');

        try {
            const { queue } = await API.getPostingQueue({ include_completed: true });
            if (!queue.length) {
                App._setContent(`
                    <div class="page-header"><h2>Posting Queue</h2></div>
                    <div class="empty-state"><h3>Queue is empty</h3><p>Upload or update stories to add items.</p></div>`);
                return;
            }

            const rows = queue.map(item => `
                <tr>
                    <td data-label="Story"><a href="#/posting/story/${Utils.escapeHtml(item.story_name)}">${Utils.escapeHtml(item.story_name.replace(/_/g, ' '))}</a></td>
                    <td data-label="Ch">${item.chapter_index || 'Full'}</td>
                    <td data-label="Platform">${PLATFORM_LABELS[item.platform] || item.platform}</td>
                    <td data-label="Action">${item.action}</td>
                    <td data-label="Status"><span class="status-badge status-${item.status}">${item.status}</span></td>
                    <td data-label="Created">${Utils.escapeHtml(item.created_at || '')}</td>
                    <td data-label="Actions">${item.status === 'pending'
                        ? `<button class="btn btn-sm btn-danger" onclick="Posting._cancelQueue(${item.queue_id})">Cancel</button>`
                        : ''
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
                            <th>Status</th><th>Created</th><th>Actions</th>
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

    /* ── 4. Published (redirects to Stories hub) ─────────────── */
    async renderPublished() {
        // Redirect to the stories hub — publications are now shown per-story
        window.location.hash = '#/posting';
    },

    /* ── 5. History / Log Page ───────────────────────────────── */
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
                    ? `<a href="${Utils.escapeHtml(entry.external_url)}" target="_blank">Link</a>` : '';
                const error = entry.error_message
                    ? `<span class="error-text" title="${Utils.escapeHtml(entry.error_message)}">&#9888;</span>` : '';
                const dur = entry.duration_seconds ? `${entry.duration_seconds.toFixed(1)}s` : '';
                return `<tr>
                    <td data-label="Time">${Utils.escapeHtml(entry.created_at || '')}</td>
                    <td data-label="Story"><a href="#/posting/story/${Utils.escapeHtml(entry.story_name)}">${Utils.escapeHtml((entry.story_name || '').replace(/_/g, ' '))}</a></td>
                    <td data-label="Platform">${PLATFORM_LABELS[entry.platform] || entry.platform}</td>
                    <td data-label="Action">${entry.action}</td>
                    <td data-label="Status"><span class="status-badge ${statusClass}">${entry.status}</span></td>
                    <td data-label="">${link} ${error}</td>
                    <td data-label="Duration">${dur}</td>
                </tr>`;
            }).join('');

            App._setContent(`
                <div class="page-header"><h2>Posting History</h2>
                    <p class="page-subtitle">${log.length} entries</p>
                </div>
                <div class="card">
                    <table class="data-table" data-mobile-cards>
                        <thead><tr>
                            <th>Time</th><th>Story</th><th>Platform</th>
                            <th>Action</th><th>Status</th><th>Details</th><th>Duration</th>
                        </tr></thead>
                        <tbody>${rows}</tbody>
                    </table>
                </div>`);
        } catch (err) {
            App._setContent(`<div class="error-state"><h3>Error</h3><p>${Utils.escapeHtml(err.message)}</p></div>`);
        }
    },
};
