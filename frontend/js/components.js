/* ── Reusable UI components ────────────────────────────────── */
/*
 * Reusable HTML template functions that return HTML strings.
 * All components use Utils for formatting/escaping and return
 * innerHTML-safe strings. Organized by platform (IB, FA, WS)
 * and feature (Groups, Analytics, Cross-Platform).
 */

const Components = {

    /**
     * Single metric card with optional 24h delta indicator.
     * Used in stats-grid sections on all dashboards (IB, FA, WS, Overview).
     * @param {string} label  - Display label (HTML-escaped internally)
     * @param {number} value  - Metric value (formatted via Utils.formatNumber)
     * @param {number|null} delta - Optional 24-hour change value; null hides the delta row
     * @returns {string} HTML string for one .stat-card element
     */
    statCard(label, value, delta = null) {
        let deltaHtml = '';
        if (delta !== null && delta !== undefined) {
            deltaHtml = Utils.formatDelta(delta);
        }
        return `
            <div class="stat-card">
                <div class="label">${Utils.escapeHtml(label)}</div>
                <div class="value">${Utils.formatNumber(value)}</div>
                ${deltaHtml ? `<div>${deltaHtml} <span style="font-size:11px;color:var(--text-muted)">24h</span></div>` : ''}
            </div>
        `;
    },

    /**
     * Clickable ranked list for IB submissions.
     * Each item navigates to the IB submission detail page via App.navigate().
     * Values are displayed in compact format (e.g. 1.2k) via Utils.formatCompact.
     * @param {Array} items    - Array of submission objects
     * @param {string} valueKey - Object key for the numeric display value (e.g. 'views')
     * @param {string} labelKey - Object key for the display title (default: 'title')
     * @param {string} idKey    - Object key for the submission ID used in navigation (default: 'submission_id')
     * @returns {string} HTML string for a <ul class="top-list"> element
     */
    topList(items, valueKey, labelKey = 'title', idKey = 'submission_id') {
        if (!items || items.length === 0) {
            return '<p style="color:var(--text-muted);font-size:13px">No data yet</p>';
        }
        const lis = items.map(item => `
            <li>
                <span class="top-title" onclick="App.navigate('/submission/${item[idKey]}')">${Utils.escapeHtml(Utils.truncate(item[labelKey], 30))}</span>
                <span class="top-value">${Utils.formatCompact(item[valueKey])}</span>
            </li>
        `).join('');
        return `<ul class="top-list">${lis}</ul>`;
    },

    /**
     * Activity feed for IB faving users with timeAgo timestamps.
     * Each entry shows username, truncated submission title (clickable to detail page),
     * and relative time since the fave was first seen.
     * @param {Array} items - Array of fave objects with username, submission_id, submission_title, first_seen_at
     * @returns {string} HTML string of .fave-item elements
     */
    recentFaves(items) {
        if (!items || items.length === 0) {
            return '<p style="color:var(--text-muted);font-size:13px">No faves recorded yet</p>';
        }
        return items.map(f => `
            <div class="fave-item">
                <span class="fave-user">${Utils.escapeHtml(f.username)}</span>
                <span class="fave-sub" style="cursor:pointer" onclick="App.navigate('/submission/${f.submission_id}')">faved ${Utils.escapeHtml(Utils.truncate(f.submission_title || '', 25))}</span>
                <span class="fave-time">${Utils.timeAgo(f.first_seen_at)}</span>
            </div>
        `).join('');
    },

    /**
     * Time preset buttons bar (24h / 7d / 30d / 90d / All Time).
     * Renders a row of buttons with the active preset highlighted.
     * Event binding for button clicks happens externally in app.js _bindDateRange(),
     * which attaches click listeners to buttons via the data-range attribute.
     * @param {string} activePreset - Currently selected preset key ('24h','7d','30d','90d','all')
     * @param {Function|null} onSelect - Unused; kept for API compatibility. Binding is external.
     * @returns {string} HTML string for the .date-range-bar container
     */
    dateRangeBar(activePreset = '7d', onSelect = null) {
        const presets = ['24h', '7d', '30d', '90d', 'all'];
        const buttons = presets.map(p => `
            <button class="range-btn ${p === activePreset ? 'active' : ''}"
                    data-range="${p}">${p === 'all' ? 'All Time' : p.toUpperCase()}</button>
        `).join('');
        return `<div class="date-range-bar" id="date-range-bar">${buttons}</div>`;
    },

    /**
     * Full IB submissions table with sortable headers, thumbnails, deltas, and links
     * to detail pages. Thumbnails are proxied via Utils.thumbUrl() to avoid CORS issues.
     * Sortable column headers use data-sort attributes; sorting logic is handled in app.js.
     * Each row shows: thumbnail, title (links to #/submission/:id), type, rating,
     * views + delta, faves + delta, comments + delta, and creation date.
     * @param {Array} submissions - Array of IB submission objects
     * @returns {string} HTML string for the full data-table with id="submissions-table"
     */
    submissionsTable(submissions) {
        if (!submissions || submissions.length === 0) {
            return `<div class="empty-state"><h3>No submissions</h3><p>Run a poll to fetch data from Inkbunny.</p></div>`;
        }
        const rows = submissions.map(s => `
            <tr>
                <td>${s.thumb_url ? `<img src="${Utils.thumbUrl(s.thumb_url)}" class="thumb-cell" loading="eager">` : ''}</td>
                <td><a href="#/submission/${s.submission_id}">${Utils.escapeHtml(Utils.truncate(s.title, 45))}</a></td>
                <td>${Utils.escapeHtml(s.type_name || '--')}</td>
                <td>${Utils.escapeHtml(s.rating_name || '--')}</td>
                <td>${Utils.formatNumber(s.views)} ${Utils.formatDelta(s.views_delta)}</td>
                <td>${Utils.formatNumber(s.favorites_count)} ${Utils.formatDelta(s.faves_delta)}</td>
                <td>${Utils.formatNumber(s.comments_count)} ${Utils.formatDelta(s.comments_delta)}</td>
                <td>${Utils.formatDate(s.create_datetime)}</td>
            </tr>
        `).join('');

        return `
            <table class="data-table" id="submissions-table">
                <thead>
                    <tr>
                        <th style="width:60px"></th>
                        <th data-sort="title">Title</th>
                        <th data-sort="type_name">Type</th>
                        <th data-sort="rating_name">Rating</th>
                        <th data-sort="views">Views</th>
                        <th data-sort="favorites_count">Faves</th>
                        <th data-sort="comments_count">Comments</th>
                        <th data-sort="create_datetime">Created</th>
                    </tr>
                </thead>
                <tbody>${rows}</tbody>
            </table>
        `;
    },

    /**
     * IB poll history table with color-coded status indicators.
     * Status colors: green (var(--success)) = success, red (var(--danger)) = error,
     * yellow (var(--warning)) = running/other. Shows time, status, submissions found,
     * snapshots inserted, new faves found, duration, and error message (truncated).
     * @param {Array} polls - Array of IB poll log objects
     * @returns {string} HTML string for the poll log data-table
     */
    pollLogTable(polls) {
        if (!polls || polls.length === 0) {
            return '<p style="color:var(--text-muted)">No polls recorded yet.</p>';
        }
        const rows = polls.map(p => `
            <tr>
                <td>${Utils.formatDateTime(p.started_at)}</td>
                <td><span style="color:${p.status === 'success' ? 'var(--success)' : p.status === 'error' ? 'var(--danger)' : 'var(--warning)'}">${p.status}</span></td>
                <td>${p.submissions_found || 0}</td>
                <td>${p.snapshots_inserted || 0}</td>
                <td>${p.new_faves_found || 0}</td>
                <td>${p.duration_seconds ? p.duration_seconds.toFixed(1) + 's' : '--'}</td>
                <td style="max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${Utils.escapeHtml(p.error_message || '')}</td>
            </tr>
        `).join('');

        return `
            <table class="data-table">
                <thead>
                    <tr>
                        <th>Time</th><th>Status</th><th>Subs</th><th>Snaps</th><th>Faves</th><th>Duration</th><th>Error</th>
                    </tr>
                </thead>
                <tbody>${rows}</tbody>
            </table>
        `;
    },

    /**
     * Table of users who faved a specific IB submission.
     * Each username links externally to their Inkbunny profile (https://inkbunny.net/:username).
     * Shows first-seen timestamp for each faving user.
     * @param {Array} users - Array of objects with username and first_seen_at
     * @returns {string} HTML string for the faving users data-table
     */
    favingUsersTable(users) {
        if (!users || users.length === 0) {
            return '<p style="color:var(--text-muted);font-size:13px">No faving users tracked yet.</p>';
        }
        const rows = users.map(u => `
            <tr>
                <td><a href="https://inkbunny.net/${Utils.escapeHtml(u.username)}" target="_blank">${Utils.escapeHtml(u.username)}</a></td>
                <td>${Utils.formatDateTime(u.first_seen_at)}</td>
            </tr>
        `).join('');
        return `
            <table class="data-table">
                <thead><tr><th>Username</th><th>First Seen</th></tr></thead>
                <tbody>${rows}</tbody>
            </table>
        `;
    },

    /**
     * Threaded comment display for IB submissions.
     * Replies are visually indented (margin-left + left border accent) and tagged with
     * a "reply" label. Each username links externally to the user's inkbunny.net profile.
     * Comments are scraped from the web during polling when comment count changes
     * (only available for IB platform).
     * @param {Array} comments - Array of comment objects with username, comment_text,
     *                           commented_at, is_reply, reply_to_comment_id
     * @returns {string} HTML string for the .comments-list container
     */
    commentsSection(comments) {
        if (!comments || comments.length === 0) {
            return '<p style="color:var(--text-muted);font-size:13px">No comments scraped yet. Comments are fetched during polling when comment count changes.</p>';
        }
        const items = comments.map(c => {
            const indent = c.is_reply ? 'margin-left:32px;border-left:3px solid var(--accent);' : '';
            const replyTag = c.reply_to_comment_id ? `<span style="font-size:11px;color:var(--text-muted)">reply</span> ` : '';
            return `
                <div class="comment-card" style="${indent}">
                    <div class="comment-header">
                        ${replyTag}<a href="https://inkbunny.net/${Utils.escapeHtml(c.username)}" target="_blank" class="comment-user">${Utils.escapeHtml(c.username)}</a>
                        <span class="comment-date">${Utils.escapeHtml(c.commented_at || '')}</span>
                    </div>
                    <div class="comment-body">${Utils.escapeHtml(c.comment_text)}</div>
                </div>
            `;
        }).join('');
        return `<div class="comments-list">${items}</div>`;
    },

    /**
     * Recent watchers feed for dashboards.
     * Shows username and relative timeAgo timestamp for each watcher.
     * Used on both IB and FA dashboards.
     * @param {Array} watchers - Array of watcher objects with username, first_seen_at
     * @returns {string} HTML string of .fave-activity elements
     */
    recentWatchers(watchers) {
        if (!watchers || watchers.length === 0) {
            return '<div class="empty-state"><p>No watchers recorded yet.</p></div>';
        }
        return watchers.map(w => `
            <div class="fave-activity">
                <span class="fave-user">${Utils.escapeHtml(w.username)}</span>
                <span class="fave-time">${Utils.timeAgo(w.first_seen_at)}</span>
            </div>
        `).join('');
    },

    /**
     * Compact recent comments feed for the IB dashboard.
     * Reuses the .fave-item layout: username, clickable submission title (navigates
     * to IB detail page), and relative timeAgo timestamp.
     * @param {Array} items - Array of comment objects with username, submission_id,
     *                        submission_title, first_seen_at
     * @returns {string} HTML string of .fave-item elements
     */
    recentComments(items) {
        if (!items || items.length === 0) {
            return '<p style="color:var(--text-muted);font-size:13px">No comments recorded yet</p>';
        }
        return items.map(c => `
            <div class="fave-item">
                <span class="fave-user">${Utils.escapeHtml(c.username)}</span>
                <span class="fave-sub" style="cursor:pointer" onclick="App.navigate('/submission/${c.submission_id}')">on ${Utils.escapeHtml(Utils.truncate(c.submission_title || '', 25))}</span>
                <span class="fave-time">${Utils.timeAgo(c.first_seen_at)}</span>
            </div>
        `).join('');
    },

    /**
     * Three-period growth rate display (24h / 7d / 30d).
     * Each card shows views/day, faves/day, and comments/day with color-coded values:
     * views = accent, faves = danger, comments = success. Positive values prefixed
     * with '+'. Null/undefined values display as '--'.
     * @param {Object} rates - Object keyed by period ('24h','7d','30d'), each containing
     *                         views_per_day, faves_per_day, comments_per_day
     * @returns {string} HTML string for a .stats-grid.growth-grid container
     */
    growthRateCards(rates, metricLabels) {
        if (!rates) return '';
        const periods = ['24h', '7d', '30d'];
        const labels = { '24h': 'Last 24 Hours', '7d': 'Last 7 Days', '30d': 'Last 30 Days' };
        const ml = metricLabels || { views: 'views/day', faves: 'faves/day', comments: 'comments/day' };
        const fmt = (v) => v === null || v === undefined ? '--' : v >= 0 ? '+' + v.toFixed(1) : v.toFixed(1);
        const cls = (v) => v === null || v === undefined ? 'neutral' : v > 0 ? 'positive' : v < 0 ? 'negative' : 'neutral';

        const cards = periods.map(p => {
            const r = rates[p];
            if (!r) return '';
            return `
                <div class="stat-card growth-card">
                    <div class="label">${labels[p]}</div>
                    <div class="growth-metrics">
                        <div class="growth-metric">
                            <span class="growth-val" style="color:var(--accent)">${fmt(r.views_per_day)}</span>
                            <span class="growth-lbl">${ml.views}</span>
                        </div>
                        <div class="growth-metric">
                            <span class="growth-val" style="color:var(--danger)">${fmt(r.faves_per_day)}</span>
                            <span class="growth-lbl">${ml.faves}</span>
                        </div>
                        <div class="growth-metric">
                            <span class="growth-val" style="color:var(--success)">${fmt(r.comments_per_day)}</span>
                            <span class="growth-lbl">${ml.comments}</span>
                        </div>
                    </div>
                </div>
            `;
        }).join('');

        return `<div class="stats-grid growth-grid">${cards}</div>`;
    },

    /**
     * Parses a JSON keyword string and renders each keyword as a styled tag badge.
     * Handles invalid/empty JSON gracefully by returning empty string.
     * @param {string} jsonStr - JSON-encoded array of keyword strings, e.g. '["fox","wolf"]'
     * @returns {string} HTML string of <span class="tag"> elements, or empty string
     */
    keywords(jsonStr) {
        try {
            const kws = JSON.parse(jsonStr || '[]');
            if (!kws.length) return '';
            return kws.map(k => `<span class="tag">${Utils.escapeHtml(k)}</span>`).join('');
        } catch {
            return '';
        }
    },

    // ── Overview Components ──────────────────────────────────────

    /**
     * Cross-platform top list with platform badges (IB / FA / WS).
     * Determines the correct platform-specific detail route based on item._platform:
     *   'fa' -> /fa/submission/, 'ws' -> /ws/submission/, default -> /submission/ (IB).
     * Each item shows a colored platform badge, clickable title, and compact value.
     * @param {Array} items    - Array of submission objects with _platform field
     * @param {string} valueKey - Object key for numeric display value
     * @param {string} labelKey - Object key for display title (default: 'title')
     * @param {string} idKey    - Object key for submission ID (default: 'submission_id')
     * @returns {string} HTML string for a <ul class="top-list"> with platform badges
     */
    overviewTopList(items, valueKey, labelKey = 'title', idKey = 'submission_id') {
        if (!items || items.length === 0) {
            return '<p style="color:var(--text-muted);font-size:13px">No data yet</p>';
        }
        const lis = items.map(item => {
            const prefixes = { fa: '/fa/submission/', ws: '/ws/submission/', sf: '/sf/submission/', sqw: '/sqw/submission/', ao3: '/ao3/submission/', da: '/da/submission/', wp: '/wp/submission/', ik: '/ik/submission/', ib: '/submission/' };
            const prefix = prefixes[item._platform] || prefixes.ib;
            const badges = { fa: '<span class="platform-badge fa">FA</span>', ws: '<span class="platform-badge ws">WS</span>', sf: '<span class="platform-badge sf">SF</span>', sqw: '<span class="platform-badge sqw">SqW</span>', ao3: '<span class="platform-badge ao3">AO3</span>', da: '<span class="platform-badge da">DA</span>', wp: '<span class="platform-badge wp">WP</span>', ik: '<span class="platform-badge ik">IK</span>', ib: '<span class="platform-badge ib">IB</span>' };
            const badge = badges[item._platform] || badges.ib;
            return `
                <li>
                    ${badge}
                    <span class="top-title" onclick="App.navigate('${prefix}${item[idKey]}')">${Utils.escapeHtml(Utils.truncate(item[labelKey], 28))}</span>
                    <span class="top-value">${Utils.formatCompact(item[valueKey])}</span>
                </li>
            `;
        }).join('');
        return `<ul class="top-list">${lis}</ul>`;
    },

    /**
     * Merged activity feed from all platforms with platform badges and action type.
     * Combines fave and comment activity across IB, FA, and WS into a single feed.
     * Action text is 'faved' for faves and 'on' for comments (based on item._type).
     * Routes to the correct platform-specific detail page based on item._platform.
     * @param {Array} items - Array of activity objects with _platform, _type, username,
     *                        submission_id, submission_title, first_seen_at
     * @returns {string} HTML string of .fave-item elements with platform badges
     */
    overviewRecentActivity(items) {
        if (!items || items.length === 0) {
            return '<p style="color:var(--text-muted);font-size:13px">No recent activity</p>';
        }
        return items.map(item => {
            const prefixes = { fa: '/fa/submission/', ws: '/ws/submission/', sf: '/sf/submission/', sqw: '/sqw/submission/', ao3: '/ao3/submission/', da: '/da/submission/', wp: '/wp/submission/', ik: '/ik/submission/', ib: '/submission/' };
            const prefix = prefixes[item._platform] || prefixes.ib;
            const badges = { fa: '<span class="platform-badge fa">FA</span>', ws: '<span class="platform-badge ws">WS</span>', sf: '<span class="platform-badge sf">SF</span>', sqw: '<span class="platform-badge sqw">SqW</span>', ao3: '<span class="platform-badge ao3">AO3</span>', da: '<span class="platform-badge da">DA</span>', wp: '<span class="platform-badge wp">WP</span>', ik: '<span class="platform-badge ik">IK</span>', ib: '<span class="platform-badge ib">IB</span>' };
            const badge = badges[item._platform] || badges.ib;
            const action = item._type === 'fave' ? 'faved' : 'on';
            return `
                <div class="fave-item">
                    ${badge}
                    <span class="fave-user">${Utils.escapeHtml(item.username)}</span>
                    <span class="fave-sub" style="cursor:pointer" onclick="App.navigate('${prefix}${item.submission_id}')">${action} ${Utils.escapeHtml(Utils.truncate(item.submission_title || '', 22))}</span>
                    <span class="fave-time">${Utils.timeAgo(item.first_seen_at)}</span>
                </div>
            `;
        }).join('');
    },

    // ── FurAffinity Components ─────────────────────────────────

    /**
     * FA-specific ranked list that links to /fa/ routes.
     * Identical in structure to topList() but navigates to /fa/submission/:id.
     * @param {Array} items    - Array of FA submission objects
     * @param {string} valueKey - Object key for numeric display value
     * @param {string} labelKey - Object key for display title (default: 'title')
     * @param {string} idKey    - Object key for submission ID (default: 'submission_id')
     * @returns {string} HTML string for a <ul class="top-list"> for FA submissions
     */
    faTopList(items, valueKey, labelKey = 'title', idKey = 'submission_id') {
        if (!items || items.length === 0) {
            return '<p style="color:var(--text-muted);font-size:13px">No data yet</p>';
        }
        const lis = items.map(item => `
            <li>
                <span class="top-title" onclick="App.navigate('/fa/submission/${item[idKey]}')">${Utils.escapeHtml(Utils.truncate(item[labelKey], 30))}</span>
                <span class="top-value">${Utils.formatCompact(item[valueKey])}</span>
            </li>
        `).join('');
        return `<ul class="top-list">${lis}</ul>`;
    },

    /**
     * FA-specific recent comments feed.
     * Same layout as recentComments() but navigates to /fa/submission/:id routes.
     * @param {Array} items - Array of FA comment objects
     * @returns {string} HTML string of .fave-item elements for FA comments
     */
    faRecentComments(items) {
        if (!items || items.length === 0) {
            return '<p style="color:var(--text-muted);font-size:13px">No comments recorded yet</p>';
        }
        return items.map(c => `
            <div class="fave-item">
                <span class="fave-user">${Utils.escapeHtml(c.username)}</span>
                <span class="fave-sub" style="cursor:pointer" onclick="App.navigate('/fa/submission/${c.submission_id}')">on ${Utils.escapeHtml(Utils.truncate(c.submission_title || '', 25))}</span>
                <span class="fave-time">${Utils.timeAgo(c.first_seen_at)}</span>
            </div>
        `).join('');
    },

    /**
     * FA-specific submissions table linking to /fa/ routes.
     * Uses FA-specific fields: category (instead of type_name), rating text (instead of
     * rating_name), and posted_at (instead of create_datetime). Thumbnails are proxied
     * via Utils.faThumbUrl(). Sortable headers use data-sort attributes.
     * @param {Array} submissions - Array of FA submission objects
     * @returns {string} HTML string for the data-table with id="fa-submissions-table"
     */
    faSubmissionsTable(submissions) {
        if (!submissions || submissions.length === 0) {
            return `<div class="empty-state"><h3>No submissions</h3><p>Connect your FA account and run a poll to fetch data.</p></div>`;
        }
        const rows = submissions.map(s => `
            <tr>
                <td>${s.thumbnail_url ? `<img src="${Utils.faThumbUrl(s.thumbnail_url)}" class="thumb-cell" loading="eager">` : ''}</td>
                <td><a href="#/fa/submission/${s.submission_id}">${Utils.escapeHtml(Utils.truncate(s.title, 45))}</a></td>
                <td>${Utils.escapeHtml(s.category || '--')}</td>
                <td>${Utils.escapeHtml(s.rating || '--')}</td>
                <td>${Utils.formatNumber(s.views)} ${Utils.formatDelta(s.views_delta)}</td>
                <td>${Utils.formatNumber(s.favorites_count)} ${Utils.formatDelta(s.faves_delta)}</td>
                <td>${Utils.formatNumber(s.comments_count)} ${Utils.formatDelta(s.comments_delta)}</td>
                <td>${Utils.formatDate(s.posted_at)}</td>
            </tr>
        `).join('');

        return `
            <table class="data-table" id="fa-submissions-table">
                <thead>
                    <tr>
                        <th style="width:60px"></th>
                        <th data-sort="title">Title</th>
                        <th data-sort="category">Category</th>
                        <th data-sort="rating">Rating</th>
                        <th data-sort="views">Views</th>
                        <th data-sort="favorites_count">Faves</th>
                        <th data-sort="comments_count">Comments</th>
                        <th data-sort="posted_at">Posted</th>
                    </tr>
                </thead>
                <tbody>${rows}</tbody>
            </table>
        `;
    },

    /**
     * FA-specific poll history table with color-coded status.
     * Same color coding as pollLogTable(): green=success, red=error, yellow=running.
     * Shows new_comments_found instead of new_faves_found (FA tracks comment discovery).
     * @param {Array} polls - Array of FA poll log objects
     * @returns {string} HTML string for the FA poll log data-table
     */
    faPollLogTable(polls) {
        if (!polls || polls.length === 0) {
            return '<p style="color:var(--text-muted)">No FA polls recorded yet.</p>';
        }
        const rows = polls.map(p => `
            <tr>
                <td>${Utils.formatDateTime(p.started_at)}</td>
                <td><span style="color:${p.status === 'success' ? 'var(--success)' : p.status === 'error' ? 'var(--danger)' : 'var(--warning)'}">${p.status}</span></td>
                <td>${p.submissions_found || 0}</td>
                <td>${p.snapshots_inserted || 0}</td>
                <td>${p.new_comments_found || 0}</td>
                <td>${p.duration_seconds ? p.duration_seconds.toFixed(1) + 's' : '--'}</td>
                <td style="max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${Utils.escapeHtml(p.error_message || '')}</td>
            </tr>
        `).join('');

        return `
            <table class="data-table">
                <thead>
                    <tr>
                        <th>Time</th><th>Status</th><th>Subs</th><th>Snaps</th><th>Comments</th><th>Duration</th><th>Error</th>
                    </tr>
                </thead>
                <tbody>${rows}</tbody>
            </table>
        `;
    },

    // ── Weasyl Components ──────────────────────────────────────

    /**
     * WS-specific ranked list linking to /ws/ routes.
     * Identical in structure to topList() but navigates to /ws/submission/:id.
     * @param {Array} items    - Array of WS submission objects
     * @param {string} valueKey - Object key for numeric display value
     * @param {string} labelKey - Object key for display title (default: 'title')
     * @param {string} idKey    - Object key for submission ID (default: 'submission_id')
     * @returns {string} HTML string for a <ul class="top-list"> for WS submissions
     */
    wsTopList(items, valueKey, labelKey = 'title', idKey = 'submission_id') {
        if (!items || items.length === 0) {
            return '<p style="color:var(--text-muted);font-size:13px">No data yet</p>';
        }
        const lis = items.map(item => `
            <li>
                <span class="top-title" onclick="App.navigate('/ws/submission/${item[idKey]}')">${Utils.escapeHtml(Utils.truncate(item[labelKey], 30))}</span>
                <span class="top-value">${Utils.formatCompact(item[valueKey])}</span>
            </li>
        `).join('');
        return `<ul class="top-list">${lis}</ul>`;
    },

    /**
     * WS-specific submissions table linking to /ws/ routes.
     * Uses WS-specific fields: subtype (instead of type_name) for the Type column,
     * and posted_at for date. Thumbnails are rendered directly (no proxy needed for WS).
     * Sortable headers use data-sort attributes with 'subtype' for the Type column.
     * @param {Array} submissions - Array of WS submission objects
     * @returns {string} HTML string for the data-table with id="ws-submissions-table"
     */
    wsSubmissionsTable(submissions) {
        if (!submissions || submissions.length === 0) {
            return `<div class="empty-state"><h3>No submissions</h3><p>Connect your Weasyl account and run a poll to fetch data.</p></div>`;
        }
        const rows = submissions.map(s => `
            <tr>
                <td>${s.thumbnail_url ? `<img src="${Utils.escapeHtml(s.thumbnail_url)}" class="thumb-cell" loading="eager">` : ''}</td>
                <td><a href="#/ws/submission/${s.submission_id}">${Utils.escapeHtml(Utils.truncate(s.title, 45))}</a></td>
                <td>${Utils.escapeHtml(s.subtype || '--')}</td>
                <td>${Utils.escapeHtml(s.rating || '--')}</td>
                <td>${Utils.formatNumber(s.views)} ${Utils.formatDelta(s.views_delta)}</td>
                <td>${Utils.formatNumber(s.favorites_count)} ${Utils.formatDelta(s.faves_delta)}</td>
                <td>${Utils.formatNumber(s.comments_count)} ${Utils.formatDelta(s.comments_delta)}</td>
                <td>${Utils.formatDate(s.posted_at)}</td>
            </tr>
        `).join('');

        return `
            <table class="data-table" id="ws-submissions-table">
                <thead>
                    <tr>
                        <th style="width:60px"></th>
                        <th data-sort="title">Title</th>
                        <th data-sort="subtype">Type</th>
                        <th data-sort="rating">Rating</th>
                        <th data-sort="views">Views</th>
                        <th data-sort="favorites_count">Faves</th>
                        <th data-sort="comments_count">Comments</th>
                        <th data-sort="posted_at">Posted</th>
                    </tr>
                </thead>
                <tbody>${rows}</tbody>
            </table>
        `;
    },

    /**
     * WS-specific poll history table with color-coded status.
     * Same color coding as pollLogTable(): green=success, red=error, yellow=running.
     * Notable difference: no Comments column because the WS API does not provide
     * comment discovery data. Only shows Time, Status, Subs, Snaps, Duration, Error.
     * @param {Array} polls - Array of WS poll log objects
     * @returns {string} HTML string for the WS poll log data-table
     */
    wsPollLogTable(polls) {
        if (!polls || polls.length === 0) {
            return '<p style="color:var(--text-muted)">No Weasyl polls recorded yet.</p>';
        }
        const rows = polls.map(p => `
            <tr>
                <td>${Utils.formatDateTime(p.started_at)}</td>
                <td><span style="color:${p.status === 'success' ? 'var(--success)' : p.status === 'error' ? 'var(--danger)' : 'var(--warning)'}">${p.status}</span></td>
                <td>${p.submissions_found || 0}</td>
                <td>${p.snapshots_inserted || 0}</td>
                <td>${p.duration_seconds ? p.duration_seconds.toFixed(1) + 's' : '--'}</td>
                <td style="max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${Utils.escapeHtml(p.error_message || '')}</td>
            </tr>
        `).join('');

        return `
            <table class="data-table">
                <thead>
                    <tr>
                        <th>Time</th><th>Status</th><th>Subs</th><th>Snaps</th><th>Duration</th><th>Error</th>
                    </tr>
                </thead>
                <tbody>${rows}</tbody>
            </table>
        `;
    },

    // ── SF (SoFurry) Components ──────────────────────────────────

    sfTopList(items, valueKey, labelKey = 'title', idKey = 'submission_id') {
        if (!items || items.length === 0) {
            return '<p style="color:var(--text-muted);font-size:13px">No data yet</p>';
        }
        const lis = items.map(item => `
            <li>
                <span class="top-title" onclick="App.navigate('/sf/submission/${item[idKey]}')">${Utils.escapeHtml(Utils.truncate(item[labelKey], 30))}</span>
                <span class="top-value">${Utils.formatCompact(item[valueKey])}</span>
            </li>
        `).join('');
        return `<ul class="top-list">${lis}</ul>`;
    },

    sfSubmissionsTable(submissions) {
        if (!submissions || submissions.length === 0) {
            return `<div class="empty-state"><h3>No submissions</h3><p>Connect your SoFurry account and run a poll to fetch data.</p></div>`;
        }
        const rows = submissions.map(s => `
            <tr>
                <td>${s.thumbnail_url ? `<img src="${Utils.escapeHtml(s.thumbnail_url)}" class="thumb-cell" loading="eager">` : ''}</td>
                <td><a href="#/sf/submission/${s.submission_id}">${Utils.escapeHtml(Utils.truncate(s.title, 45))}</a></td>
                <td>${Utils.escapeHtml(s.content_type || '--')}</td>
                <td>${Utils.escapeHtml(s.rating || '--')}</td>
                <td>${Utils.formatNumber(s.views)} ${Utils.formatDelta(s.views_delta)}</td>
                <td>${Utils.formatNumber(s.favorites_count)} ${Utils.formatDelta(s.faves_delta)}</td>
                <td>${Utils.formatNumber(s.comments_count)} ${Utils.formatDelta(s.comments_delta)}</td>
                <td>${Utils.formatDate(s.posted_at)}</td>
            </tr>
        `).join('');

        return `
            <table class="data-table" id="sf-submissions-table">
                <thead>
                    <tr>
                        <th style="width:60px"></th>
                        <th data-sort="title">Title</th>
                        <th data-sort="content_type">Type</th>
                        <th data-sort="rating">Rating</th>
                        <th data-sort="views">Views</th>
                        <th data-sort="favorites_count">Likes</th>
                        <th data-sort="comments_count">Comments</th>
                        <th data-sort="posted_at">Posted</th>
                    </tr>
                </thead>
                <tbody>${rows}</tbody>
            </table>
        `;
    },

    sfPollLogTable(polls) {
        if (!polls || polls.length === 0) {
            return '<p style="color:var(--text-muted)">No SoFurry polls recorded yet.</p>';
        }
        const rows = polls.map(p => `
            <tr>
                <td>${Utils.formatDateTime(p.started_at)}</td>
                <td><span style="color:${p.status === 'success' ? 'var(--success)' : p.status === 'error' ? 'var(--danger)' : 'var(--warning)'}">${p.status}</span></td>
                <td>${p.submissions_found || 0}</td>
                <td>${p.snapshots_inserted || 0}</td>
                <td>${p.duration_seconds ? p.duration_seconds.toFixed(1) + 's' : '--'}</td>
                <td style="max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${Utils.escapeHtml(p.error_message || '')}</td>
            </tr>
        `).join('');

        return `
            <table class="data-table">
                <thead>
                    <tr>
                        <th>Time</th><th>Status</th><th>Subs</th><th>Snaps</th><th>Duration</th><th>Error</th>
                    </tr>
                </thead>
                <tbody>${rows}</tbody>
            </table>
        `;
    },

    // ── SQW (SquidgeWorld) Components ──────────────────────────────

    sqwTopList(items, valueKey, labelKey = 'title', idKey = 'submission_id') {
        if (!items || items.length === 0) {
            return '<p style="color:var(--text-muted);font-size:13px">No data yet</p>';
        }
        const lis = items.map(item => `
            <li>
                <span class="top-title" onclick="App.navigate('/sqw/submission/${item[idKey]}')">${Utils.escapeHtml(Utils.truncate(item[labelKey], 30))}</span>
                <span class="top-value">${Utils.formatCompact(item[valueKey])}</span>
            </li>
        `).join('');
        return `<ul class="top-list">${lis}</ul>`;
    },

    sqwSubmissionsTable(submissions) {
        if (!submissions || submissions.length === 0) {
            return `<div class="empty-state"><h3>No submissions</h3><p>Connect your SquidgeWorld account and run a poll to fetch data.</p></div>`;
        }
        const rows = submissions.map(s => `
            <tr>
                <td><a href="#/sqw/submission/${s.submission_id}">${Utils.escapeHtml(Utils.truncate(s.title, 45))}</a></td>
                <td>${Utils.escapeHtml(s.fandom || '--')}</td>
                <td>${Utils.escapeHtml(s.rating || '--')}</td>
                <td>${Utils.formatNumber(s.views)} ${Utils.formatDelta(s.views_delta)}</td>
                <td>${Utils.formatNumber(s.favorites_count)} ${Utils.formatDelta(s.faves_delta)}</td>
                <td>${Utils.formatNumber(s.comments_count)} ${Utils.formatDelta(s.comments_delta)}</td>
                <td>${Utils.formatNumber(s.bookmarks_count || 0)}</td>
                <td>${Utils.formatDate(s.posted_at)}</td>
            </tr>
        `).join('');

        return `
            <table class="data-table" id="sqw-submissions-table">
                <thead>
                    <tr>
                        <th data-sort="title">Title</th>
                        <th data-sort="fandom">Fandom</th>
                        <th data-sort="rating">Rating</th>
                        <th data-sort="views">Hits</th>
                        <th data-sort="favorites_count">Kudos</th>
                        <th data-sort="comments_count">Comments</th>
                        <th data-sort="bookmarks_count">Bookmarks</th>
                        <th data-sort="posted_at">Posted</th>
                    </tr>
                </thead>
                <tbody>${rows}</tbody>
            </table>
        `;
    },

    sqwPollLogTable(polls) {
        if (!polls || polls.length === 0) {
            return '<p style="color:var(--text-muted)">No SquidgeWorld polls recorded yet.</p>';
        }
        const rows = polls.map(p => `
            <tr>
                <td>${Utils.formatDateTime(p.started_at)}</td>
                <td><span style="color:${p.status === 'success' ? 'var(--success)' : p.status === 'error' ? 'var(--danger)' : 'var(--warning)'}">${p.status}</span></td>
                <td>${p.submissions_found || 0}</td>
                <td>${p.snapshots_inserted || 0}</td>
                <td>${p.duration_seconds ? p.duration_seconds.toFixed(1) + 's' : '--'}</td>
                <td style="max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${Utils.escapeHtml(p.error_message || '')}</td>
            </tr>
        `).join('');

        return `
            <table class="data-table">
                <thead>
                    <tr>
                        <th>Time</th><th>Status</th><th>Subs</th><th>Snaps</th><th>Duration</th><th>Error</th>
                    </tr>
                </thead>
                <tbody>${rows}</tbody>
            </table>
        `;
    },

    // ── AO3 (Archive of Our Own) Components ──────────────────────

    ao3TopList(items, valueKey, labelKey = 'title', idKey = 'submission_id') {
        if (!items || items.length === 0) {
            return '<p style="color:var(--text-muted);font-size:13px">No data yet</p>';
        }
        const lis = items.map(item => `
            <li>
                <span class="top-title" onclick="App.navigate('/ao3/submission/${item[idKey]}')">${Utils.escapeHtml(Utils.truncate(item[labelKey], 30))}</span>
                <span class="top-value">${Utils.formatCompact(item[valueKey])}</span>
            </li>
        `).join('');
        return `<ul class="top-list">${lis}</ul>`;
    },

    ao3SubmissionsTable(submissions) {
        if (!submissions || submissions.length === 0) {
            return `<div class="empty-state"><h3>No submissions</h3><p>Connect your AO3 account and run a poll to fetch data.</p></div>`;
        }
        const rows = submissions.map(s => `
            <tr>
                <td><a href="#/ao3/submission/${s.submission_id}">${Utils.escapeHtml(Utils.truncate(s.title, 45))}</a></td>
                <td>${Utils.escapeHtml(s.fandom || '--')}</td>
                <td>${Utils.escapeHtml(s.rating || '--')}</td>
                <td>${Utils.formatNumber(s.views)} ${Utils.formatDelta(s.views_delta)}</td>
                <td>${Utils.formatNumber(s.favorites_count)} ${Utils.formatDelta(s.faves_delta)}</td>
                <td>${Utils.formatNumber(s.comments_count)} ${Utils.formatDelta(s.comments_delta)}</td>
                <td>${Utils.formatNumber(s.bookmarks_count || 0)}</td>
                <td>${Utils.formatDate(s.posted_at)}</td>
            </tr>
        `).join('');

        return `
            <table class="data-table" id="ao3-submissions-table">
                <thead>
                    <tr>
                        <th data-sort="title">Title</th>
                        <th data-sort="fandom">Fandom</th>
                        <th data-sort="rating">Rating</th>
                        <th data-sort="views">Hits</th>
                        <th data-sort="favorites_count">Kudos</th>
                        <th data-sort="comments_count">Comments</th>
                        <th data-sort="bookmarks_count">Bookmarks</th>
                        <th data-sort="posted_at">Posted</th>
                    </tr>
                </thead>
                <tbody>${rows}</tbody>
            </table>
        `;
    },

    ao3PollLogTable(polls) {
        if (!polls || polls.length === 0) {
            return '<p style="color:var(--text-muted)">No AO3 polls recorded yet.</p>';
        }
        const rows = polls.map(p => `
            <tr>
                <td>${Utils.formatDateTime(p.started_at)}</td>
                <td><span style="color:${p.status === 'success' ? 'var(--success)' : p.status === 'error' ? 'var(--danger)' : 'var(--warning)'}">${p.status}</span></td>
                <td>${p.submissions_found || 0}</td>
                <td>${p.snapshots_inserted || 0}</td>
                <td>${p.duration_seconds ? p.duration_seconds.toFixed(1) + 's' : '--'}</td>
                <td style="max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${Utils.escapeHtml(p.error_message || '')}</td>
            </tr>
        `).join('');

        return `
            <table class="data-table">
                <thead>
                    <tr>
                        <th>Time</th><th>Status</th><th>Subs</th><th>Snaps</th><th>Duration</th><th>Error</th>
                    </tr>
                </thead>
                <tbody>${rows}</tbody>
            </table>
        `;
    },

    // ── DeviantArt Components ──────────────────────────────────────

    /**
     * DA-specific ranked list linking to /da/ routes.
     * Identical in structure to faTopList() but navigates to /da/submission/:id.
     * @param {Array} items    - Array of DA submission objects
     * @param {string} valueKey - Object key for numeric display value
     * @param {string} labelKey - Object key for display title (default: 'title')
     * @param {string} idKey    - Object key for submission ID (default: 'submission_id')
     * @returns {string} HTML string for a .top-list element
     */
    daTopList(items, valueKey, labelKey = 'title', idKey = 'submission_id') {
        if (!items || items.length === 0) {
            return '<p style="color:var(--text-muted);font-size:13px">No data yet</p>';
        }
        const lis = items.map(item => `
            <li>
                <span class="top-title" onclick="App.navigate('/da/submission/${item[idKey]}')">${Utils.escapeHtml(Utils.truncate(item[labelKey], 30))}</span>
                <span class="top-value">${Utils.formatCompact(item[valueKey])}</span>
            </li>
        `).join('');
        return `<ul class="top-list">${lis}</ul>`;
    },

    /**
     * DA-specific submissions table linking to /da/ routes.
     * Includes Views, Favourites, Comments, and Downloads columns (Downloads is unique to DA).
     * No thumbnail column or proxy. Sortable headers use data-sort attributes.
     * @param {Array} submissions - Array of DA submission objects
     * @returns {string} HTML string for the data-table with id="da-submissions-table"
     */
    daSubmissionsTable(submissions) {
        if (!submissions || submissions.length === 0) {
            return `<div class="empty-state"><h3>No submissions</h3><p>Connect your DeviantArt account and run a poll to fetch data.</p></div>`;
        }
        const rows = submissions.map(s => `
            <tr>
                <td><a href="#/da/submission/${s.submission_id}">${Utils.escapeHtml(Utils.truncate(s.title, 45))}</a></td>
                <td>${Utils.escapeHtml(s.category || '--')}</td>
                <td>${Utils.escapeHtml(s.rating || '--')}</td>
                <td>${Utils.formatNumber(s.views)} ${Utils.formatDelta(s.views_delta)}</td>
                <td>${Utils.formatNumber(s.favorites_count)} ${Utils.formatDelta(s.faves_delta)}</td>
                <td>${Utils.formatNumber(s.comments_count)} ${Utils.formatDelta(s.comments_delta)}</td>
                <td>${Utils.formatNumber(s.downloads || 0)} ${Utils.formatDelta(s.downloads_delta)}</td>
                <td>${Utils.formatDate(s.posted_at)}</td>
            </tr>
        `).join('');

        return `
            <table class="data-table" id="da-submissions-table">
                <thead>
                    <tr>
                        <th data-sort="title">Title</th>
                        <th data-sort="category">Category</th>
                        <th data-sort="rating">Rating</th>
                        <th data-sort="views">Views</th>
                        <th data-sort="favorites_count">Favourites</th>
                        <th data-sort="comments_count">Comments</th>
                        <th data-sort="downloads">Downloads</th>
                        <th data-sort="posted_at">Posted</th>
                    </tr>
                </thead>
                <tbody>${rows}</tbody>
            </table>
        `;
    },

    /**
     * DA-specific poll history table with color-coded status.
     * Same color coding as faPollLogTable(): green=success, red=error, yellow=running.
     * @param {Array} polls - Array of DA poll log objects
     * @returns {string} HTML string for the DA poll log data-table
     */
    daPollLogTable(polls) {
        if (!polls || polls.length === 0) {
            return '<p style="color:var(--text-muted)">No DA polls recorded yet.</p>';
        }
        const rows = polls.map(p => `
            <tr>
                <td>${Utils.formatDateTime(p.started_at)}</td>
                <td><span style="color:${p.status === 'success' ? 'var(--success)' : p.status === 'error' ? 'var(--danger)' : 'var(--warning)'}">${p.status}</span></td>
                <td>${p.submissions_found || 0}</td>
                <td>${p.snapshots_inserted || 0}</td>
                <td>${p.duration_seconds ? p.duration_seconds.toFixed(1) + 's' : '--'}</td>
                <td style="max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${Utils.escapeHtml(p.error_message || '')}</td>
            </tr>
        `).join('');

        return `
            <table class="data-table">
                <thead>
                    <tr>
                        <th>Time</th><th>Status</th><th>Subs</th><th>Snaps</th><th>Duration</th><th>Error</th>
                    </tr>
                </thead>
                <tbody>${rows}</tbody>
            </table>
        `;
    },

    /**
     * Clickable ranked list for WP (Wattpad) submissions.
     * Each item navigates to the WP submission detail page via App.navigate().
     * @param {Array} items    - Array of submission objects
     * @param {string} valueKey - Object key for the numeric display value (e.g. 'reads')
     * @param {string} labelKey - Object key for the display label (default 'title')
     * @param {string} idKey   - Object key for the submission ID (default 'submission_id')
     * @returns {string} HTML string for a .top-list element
     */
    wpTopList(items, valueKey, labelKey = 'title', idKey = 'submission_id') {
        if (!items || items.length === 0) {
            return '<p style="color:var(--text-muted);font-size:13px">No data yet</p>';
        }
        const lis = items.map(item => `
            <li>
                <span class="top-title" onclick="App.navigate('/wp/submission/${item[idKey]}')">${Utils.escapeHtml(Utils.truncate(item[labelKey], 30))}</span>
                <span class="top-value">${Utils.formatCompact(item[valueKey])}</span>
            </li>
        `).join('');
        return `<ul class="top-list">${lis}</ul>`;
    },

    /**
     * WP-specific submissions table linking to /wp/ routes.
     * Includes Reads, Votes, Comments, and Lists columns (Wattpad-specific metric names).
     * Sortable headers use data-sort attributes.
     * @param {Array} submissions - Array of WP submission objects
     * @returns {string} HTML string for the data-table with id="wp-submissions-table"
     */
    wpSubmissionsTable(submissions) {
        if (!submissions || submissions.length === 0) {
            return `<div class="empty-state"><h3>No submissions</h3><p>Connect your Wattpad account and run a poll to fetch data.</p></div>`;
        }
        const rows = submissions.map(s => `
            <tr>
                <td><a href="#/wp/submission/${s.submission_id}">${Utils.escapeHtml(Utils.truncate(s.title, 45))}</a></td>
                <td>${Utils.formatNumber(s.reads || s.views || 0)} ${Utils.formatDelta(s.reads_delta || s.views_delta)}</td>
                <td>${Utils.formatNumber(s.votes || s.favorites_count || 0)} ${Utils.formatDelta(s.votes_delta || s.faves_delta)}</td>
                <td>${Utils.formatNumber(s.comments_count || 0)} ${Utils.formatDelta(s.comments_delta)}</td>
                <td>${Utils.formatNumber(s.num_lists || 0)} ${Utils.formatDelta(s.lists_delta)}</td>
                <td>${Utils.formatDate(s.posted_at)}</td>
            </tr>
        `).join('');

        return `
            <table class="data-table" id="wp-submissions-table">
                <thead>
                    <tr>
                        <th data-sort="title">Title</th>
                        <th data-sort="reads">Reads</th>
                        <th data-sort="votes">Votes</th>
                        <th data-sort="comments_count">Comments</th>
                        <th data-sort="num_lists">Lists</th>
                        <th data-sort="posted_at">Posted</th>
                    </tr>
                </thead>
                <tbody>${rows}</tbody>
            </table>
        `;
    },

    /**
     * WP-specific poll history table with color-coded status.
     * Same color coding as daPollLogTable(): green=success, red=error, yellow=running.
     * @param {Array} polls - Array of WP poll log objects
     * @returns {string} HTML string for the WP poll log data-table
     */
    wpPollLogTable(polls) {
        if (!polls || polls.length === 0) {
            return '<p style="color:var(--text-muted)">No WP polls recorded yet.</p>';
        }
        const rows = polls.map(p => `
            <tr>
                <td>${Utils.formatDateTime(p.started_at)}</td>
                <td><span style="color:${p.status === 'success' ? 'var(--success)' : p.status === 'error' ? 'var(--danger)' : 'var(--warning)'}">${p.status}</span></td>
                <td>${p.submissions_found || 0}</td>
                <td>${p.snapshots_inserted || 0}</td>
                <td>${p.duration_seconds ? p.duration_seconds.toFixed(1) + 's' : '--'}</td>
                <td style="max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${Utils.escapeHtml(p.error_message || '')}</td>
            </tr>
        `).join('');

        return `
            <table class="data-table">
                <thead>
                    <tr>
                        <th>Time</th><th>Status</th><th>Subs</th><th>Snaps</th><th>Duration</th><th>Error</th>
                    </tr>
                </thead>
                <tbody>${rows}</tbody>
            </table>
        `;
    },

    // ── IK (Itaku) Components ────────────────────────────────────

    /**
     * Clickable ranked list for IK submissions.
     * Each item navigates to the IK submission detail page via App.navigate().
     * @param {Array} items    - Array of submission objects
     * @param {string} valueKey - Object key for the numeric display value (e.g. 'likes')
     * @param {string} labelKey - Object key for the display label (default: 'title')
     * @param {string} idKey    - Object key for the submission ID (default: 'submission_id')
     * @returns {string} HTML string for a .top-list element
     */
    ikTopList(items, valueKey, labelKey = 'title', idKey = 'submission_id') {
        if (!items || items.length === 0) {
            return '<p style="color:var(--text-muted);font-size:13px">No data yet</p>';
        }
        const lis = items.map(item => `
            <li>
                <span class="top-title" onclick="App.navigate('/ik/submission/${item[idKey]}')">${Utils.escapeHtml(Utils.truncate(item[labelKey], 30))}</span>
                <span class="top-value">${Utils.formatCompact(item[valueKey])}</span>
            </li>
        `).join('');
        return `<ul class="top-list">${lis}</ul>`;
    },

    /**
     * IK-specific submissions table linking to /ik/ routes.
     * Includes Type, Likes, Comments, and Reshares columns (Itaku-specific metrics — NO views).
     * Sortable headers use data-sort attributes.
     * @param {Array} submissions - Array of IK submission objects
     * @returns {string} HTML string for the data-table with id="ik-submissions-table"
     */
    ikSubmissionsTable(submissions) {
        if (!submissions || submissions.length === 0) {
            return `<div class="empty-state"><h3>No submissions</h3><p>Connect your Itaku account and run a poll to fetch data.</p></div>`;
        }
        const rows = submissions.map(s => `
            <tr>
                <td><a href="#/ik/submission/${s.submission_id}">${Utils.escapeHtml(Utils.truncate(s.title, 45))}</a></td>
                <td>${Utils.escapeHtml(s.content_type || 'image')}</td>
                <td>${Utils.formatNumber(s.likes || 0)} ${Utils.formatDelta(s.likes_delta)}</td>
                <td>${Utils.formatNumber(s.comments_count || 0)} ${Utils.formatDelta(s.comments_delta)}</td>
                <td>${Utils.formatNumber(s.reshares || 0)} ${Utils.formatDelta(s.reshares_delta)}</td>
                <td>${Utils.formatDate(s.posted_at)}</td>
            </tr>
        `).join('');

        return `
            <table class="data-table" id="ik-submissions-table">
                <thead>
                    <tr>
                        <th data-sort="title">Title</th>
                        <th data-sort="content_type">Type</th>
                        <th data-sort="likes">Likes</th>
                        <th data-sort="comments_count">Comments</th>
                        <th data-sort="reshares">Reshares</th>
                        <th data-sort="posted_at">Posted</th>
                    </tr>
                </thead>
                <tbody>${rows}</tbody>
            </table>
        `;
    },

    /**
     * IK-specific poll history table with color-coded status.
     * Green=success, red=error, yellow=running.
     * @param {Array} polls - Array of IK poll log objects
     * @returns {string} HTML string for the IK poll log data-table
     */
    ikPollLogTable(polls) {
        if (!polls || polls.length === 0) {
            return '<p style="color:var(--text-muted)">No IK polls recorded yet.</p>';
        }
        const rows = polls.map(p => `
            <tr>
                <td>${Utils.formatDateTime(p.started_at)}</td>
                <td><span style="color:${p.status === 'success' ? 'var(--success)' : p.status === 'error' ? 'var(--danger)' : 'var(--warning)'}">${p.status}</span></td>
                <td>${p.submissions_found || 0}</td>
                <td>${p.snapshots_inserted || 0}</td>
                <td>${p.duration_seconds ? p.duration_seconds.toFixed(1) + 's' : '--'}</td>
                <td style="max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${Utils.escapeHtml(p.error_message || '')}</td>
            </tr>
        `).join('');

        return `
            <table class="data-table">
                <thead>
                    <tr>
                        <th>Time</th><th>Status</th><th>Subs</th><th>Snaps</th><th>Duration</th><th>Error</th>
                    </tr>
                </thead>
                <tbody>${rows}</tbody>
            </table>
        `;
    },

    // ── Groups Components ────────────────────────────────────────

    /**
     * Grid of group cards that navigate to the group detail page on click.
     * Each card shows group name, description (if present), and member count
     * (number of submissions in the group). Reuses .stat-card styling.
     * @param {Array} groups - Array of group objects with group_id, name, description, member_count
     * @returns {string} HTML string of clickable .stat-card elements
     */
    groupsList(groups) {
        if (!groups || groups.length === 0) {
            return '<div class="empty-state"><h3>No groups yet</h3><p>Create a group to track related submissions across platforms.</p></div>';
        }
        return groups.map(g => `
            <div class="stat-card" style="cursor:pointer" onclick="App.navigate('/group/${g.group_id}')">
                <div class="label">${Utils.escapeHtml(g.name)}</div>
                <div style="font-size:13px;color:var(--text-muted);margin-top:4px">${Utils.escapeHtml(g.description || '')}</div>
                <div style="font-size:12px;color:var(--text-secondary);margin-top:8px">${g.member_count || 0} submissions</div>
            </div>
        `).join('');
    },

    // ── Analytics Components ─────────────────────────────────────

    /**
     * Ranked leaderboard table of top fans.
     * Columns: rank (#), username, fave count, comment count, weighted score.
     * Score formula: (faves * 2) + comments -- weighted to emphasize fave engagement.
     * Rank numbers are 1-indexed from the array position.
     * @param {Array} fans - Array of fan objects with username, fave_count, comment_count, score
     * @returns {string} HTML string for the top fans data-table
     */
    topFansTable(fans) {
        if (!fans || fans.length === 0) {
            return '<p style="color:var(--text-muted);font-size:13px">No fan data available yet. Run polls to build up data.</p>';
        }
        const rows = fans.map((f, i) => `
            <tr>
                <td style="font-weight:600;color:var(--text-muted)">#${i + 1}</td>
                <td>${Utils.escapeHtml(f.username)}</td>
                <td>${f.fave_count || 0}</td>
                <td>${f.comment_count || 0}</td>
                <td style="font-weight:600;color:var(--accent)">${f.score || 0}</td>
            </tr>
        `).join('');

        return `
            <table class="data-table">
                <thead>
                    <tr>
                        <th style="width:40px">#</th><th>Username</th><th>Faves</th><th>Comments</th><th>Score</th>
                    </tr>
                </thead>
                <tbody>${rows}</tbody>
            </table>
        `;
    },

    /**
     * Spike detection results displayed as clickable cards with platform badges.
     * Each card shows the submission title with platform badge (IB/FA/WS), delta values
     * for views/faves/comments that triggered the spike, and the z-score indicating
     * how far above normal the activity is. Navigates to the correct platform-specific
     * detail page on click.
     * @param {Array} items - Array of trending objects with platform, submission_id, title,
     *                        views_delta, faves_delta, comments_delta, max_z
     * @returns {string} HTML string of clickable .stat-card elements
     */
    trendingCards(items) {
        if (!items || items.length === 0) {
            return '<p style="color:var(--text-muted);font-size:13px">No trending submissions detected. Need at least a few polls to calculate trends.</p>';
        }
        return items.map(item => {
            const badgeMap = { fa: '<span class="platform-badge fa">FA</span>', ws: '<span class="platform-badge ws">WS</span>', sf: '<span class="platform-badge sf">SF</span>', sqw: '<span class="platform-badge sqw">SqW</span>', ao3: '<span class="platform-badge ao3">AO3</span>', da: '<span class="platform-badge da">DA</span>', wp: '<span class="platform-badge wp">WP</span>', ik: '<span class="platform-badge ik">IK</span>', ib: '<span class="platform-badge ib">IB</span>' };
            const platformBadge = badgeMap[item.platform] || badgeMap.ib;
            const prefixMap = { fa: '/fa/submission/', ws: '/ws/submission/', sf: '/sf/submission/', sqw: '/sqw/submission/', ao3: '/ao3/submission/', da: '/da/submission/', wp: '/wp/submission/', ik: '/ik/submission/', ib: '/submission/' };
            const prefix = prefixMap[item.platform] || prefixMap.ib;
            const metrics = [];
            if (item.views_delta) metrics.push(`Views +${item.views_delta}`);
            if (item.faves_delta) metrics.push(`Faves +${item.faves_delta}`);
            if (item.comments_delta) metrics.push(`Comments +${item.comments_delta}`);
            return `
                <div class="stat-card" style="cursor:pointer" onclick="App.navigate('${prefix}${item.submission_id}')">
                    <div class="label">${platformBadge} ${Utils.escapeHtml(Utils.truncate(item.title, 35))}</div>
                    <div style="font-size:13px;color:var(--success);margin-top:6px">${metrics.join(' &middot; ')}</div>
                    <div style="font-size:11px;color:var(--text-muted);margin-top:4px">z-score: ${(item.max_z || 0).toFixed(1)}</div>
                </div>
            `;
        }).join('');
    },

    // ── Cross-Platform Link Components ───────────────────────────

    /**
     * Linked submission cards showing members from different platforms.
     * Each card lists all linked submissions with platform badges (IB/FA/WS) and
     * provides Stats and Remove action buttons. Stats button calls App.viewLinkStats()
     * and Remove button calls App.deleteLink() with the link_id.
     * @param {Array} links - Array of link objects with link_id and members array
     *                        (each member has platform, title, submission_id)
     * @returns {string} HTML string of .stat-card elements with action buttons
     */
    linkCards(links) {
        if (!links || links.length === 0) {
            return '<div class="empty-state"><h3>No linked submissions</h3><p>Link the same work across platforms to see combined stats.</p></div>';
        }
        return links.map(link => {
            const members = (link.members || []).map(m => {
                const badgeMap = { fa: '<span class="platform-badge fa">FA</span>', ws: '<span class="platform-badge ws">WS</span>', sf: '<span class="platform-badge sf">SF</span>', sqw: '<span class="platform-badge sqw">SqW</span>', ao3: '<span class="platform-badge ao3">AO3</span>', da: '<span class="platform-badge da">DA</span>', wp: '<span class="platform-badge wp">WP</span>', ik: '<span class="platform-badge ik">IK</span>', ib: '<span class="platform-badge ib">IB</span>' };
                const badge = badgeMap[m.platform] || badgeMap.ib;
                return `${badge} ${Utils.escapeHtml(Utils.truncate(m.title || '#' + m.submission_id, 25))}`;
            }).join('<br>');
            return `
                <div class="stat-card">
                    <div style="font-size:13px;margin-bottom:8px">${members}</div>
                    <div style="display:flex;gap:8px;margin-top:8px">
                        <button class="btn btn-secondary" style="font-size:11px" onclick="App.viewLinkStats(${link.link_id})">Stats</button>
                        <button class="btn btn-danger" style="font-size:11px" onclick="App.deleteLink(${link.link_id})">Remove</button>
                    </div>
                </div>
            `;
        }).join('');
    },

    /**
     * Auto-detected similar titles across platforms with similarity percentage
     * and one-click Link button. Titles are compared across IB/FA/WS and shown
     * with bidirectional arrow (&harr;) between platform-badged entries.
     * Similarity score is displayed as a percentage. The Link button calls
     * App.createLinkFromSuggestion() with the full items array to create the link.
     * @param {Array} suggestions - Array of suggestion objects, each with items array
     *                              (platform, title, submission_id) and similarity float
     * @returns {string} HTML string of .fave-item elements with Link buttons
     */
    linkSuggestions(suggestions) {
        if (!suggestions || suggestions.length === 0) {
            return '<p style="color:var(--text-muted);font-size:13px">No suggestions found. Submissions need similar titles across platforms.</p>';
        }
        return suggestions.map(s => {
            const items = s.items.map(i => {
                const badgeMap = { fa: '<span class="platform-badge fa">FA</span>', ws: '<span class="platform-badge ws">WS</span>', sf: '<span class="platform-badge sf">SF</span>', sqw: '<span class="platform-badge sqw">SqW</span>', ao3: '<span class="platform-badge ao3">AO3</span>', da: '<span class="platform-badge da">DA</span>', wp: '<span class="platform-badge wp">WP</span>', ik: '<span class="platform-badge ik">IK</span>', ib: '<span class="platform-badge ib">IB</span>' };
                const badge = badgeMap[i.platform] || badgeMap.ib;
                return `${badge} ${Utils.escapeHtml(Utils.truncate(i.title, 30))}`;
            }).join(' &harr; ');
            return `
                <div class="fave-item" style="flex-wrap:wrap">
                    <span style="flex:1">${items}</span>
                    <span style="font-size:11px;color:var(--text-muted)">${(s.similarity * 100).toFixed(0)}% match</span>
                    <button class="btn btn-primary" style="font-size:11px;padding:4px 10px" data-items='${Utils.escapeHtml(JSON.stringify(s.items))}' onclick='App.createLinkFromSuggestion(JSON.parse(this.dataset.items))'>Link</button>
                </div>
            `;
        }).join('');
    },

    /**
     * FA comment display with external furaffinity.net profile links.
     * Supports reply threading via reply_level and reply_to fields: replies with
     * reply_level > 0 or a reply_to value are indented with a left accent border.
     * Each username links externally to https://www.furaffinity.net/user/:username/.
     * @param {Array} comments - Array of FA comment objects with username, comment_text,
     *                           commented_at, reply_level, reply_to
     * @returns {string} HTML string for the .comments-list container
     */
    faCommentsSection(comments) {
        if (!comments || comments.length === 0) {
            return '<p style="color:var(--text-muted);font-size:13px">No comments fetched yet. Comments are fetched during polling when comment count changes.</p>';
        }
        const items = comments.map(c => {
            const indent = (c.reply_level > 0 || c.reply_to) ? 'margin-left:32px;border-left:3px solid var(--accent);' : '';
            const replyTag = c.reply_to ? `<span style="font-size:11px;color:var(--text-muted)">reply</span> ` : '';
            return `
                <div class="comment-card" style="${indent}">
                    <div class="comment-header">
                        ${replyTag}<a href="https://www.furaffinity.net/user/${Utils.escapeHtml(c.username)}/" target="_blank" class="comment-user">${Utils.escapeHtml(c.username)}</a>
                        <span class="comment-date">${Utils.escapeHtml(c.commented_at || '')}</span>
                    </div>
                    <div class="comment-body">${Utils.escapeHtml(c.comment_text)}</div>
                </div>
            `;
        }).join('');
        return `<div class="comments-list">${items}</div>`;
    },

    /* ── Pinned Submissions ──────────────────────────────────── */
    pinnedSubmissions(items, platform) {
        if (!items || items.length === 0) return '';
        /* Platform-aware metric labels: WP uses reads/votes, IK has likes (no views) */
        const metricLabels = { ib: { v: 'views', f: 'faves' }, fa: { v: 'views', f: 'faves' }, ws: { v: 'views', f: 'faves' }, sf: { v: 'views', f: 'faves' }, sqw: { v: 'views', f: 'faves' }, ao3: { v: 'views', f: 'faves' }, da: { v: 'views', f: 'faves' }, wp: { v: 'reads', f: 'votes' }, ik: { v: null, f: 'likes' } };
        const labels = metricLabels[platform] || metricLabels.ib;
        const cards = items.map(sub => `
            <div class="pinned-card" data-nav="${platform === 'ib' ? '' : platform + '/'}submission/${sub.submission_id}">
                <div class="pinned-title">${Utils.escapeHtml(sub.title)}</div>
                <div class="pinned-stats">
                    ${labels.v ? `<div><span>${Utils.formatCompact(sub.views || sub.reads || 0)}</span> ${labels.v}</div>` : ''}
                    <div><span>${Utils.formatCompact(sub.favorites_count || sub.votes || sub.likes || 0)}</span> ${labels.f}</div>
                    <div><span>${Utils.formatCompact(sub.comments_count)}</span> cmts</div>
                </div>
                <button class="btn-unpin" data-platform="${platform}" data-id="${sub.submission_id}">Unpin</button>
            </div>
        `).join('');
        return `<div class="pinned-section"><h3>Pinned</h3><div class="pinned-row">${cards}</div></div>`;
    },

    /* ── Goal Progress Cards ─────────────────────────────────── */
    goalProgressCards(goals) {
        if (!goals || goals.length === 0) return '';
        const metricLabels = { views: 'Views', favorites_count: 'Faves', comments_count: 'Comments', watchers: 'Watchers' };
        const cards = goals.map(g => {
            const pct = g.target_value > 0 ? Math.min(100, Math.round((g.current_value / g.target_value) * 100)) : 0;
            const complete = pct >= 100;
            const title = g.submission_title ? Utils.truncate(g.submission_title, 25) : 'Account Total';
            return `
                <div class="goal-card">
                    <div class="goal-header">
                        <div>
                            <div class="goal-title">${Utils.escapeHtml(title)}</div>
                            <div class="goal-metric">${metricLabels[g.metric] || g.metric}</div>
                        </div>
                        <button class="btn-goal-delete" data-goal-id="${g.goal_id}" title="Delete goal">&#x2715;</button>
                    </div>
                    <div class="goal-progress-bar">
                        <div class="goal-progress-fill ${complete ? 'complete' : ''}" style="width:${pct}%"></div>
                    </div>
                    <div class="goal-numbers">
                        <span class="goal-current">${Utils.formatNumber(g.current_value)}</span>
                        <span>${Utils.formatNumber(g.target_value)} (${pct}%)</span>
                    </div>
                </div>
            `;
        }).join('');
        return `<div class="goal-grid">${cards}</div>`;
    },

    /* ── Tag Badge ───────────────────────────────────────────── */
    tagBadge(tag) {
        return `<span class="tag-badge" data-tag-id="${tag.tag_id}" style="background:${Utils.escapeHtml(tag.color)}">${Utils.escapeHtml(tag.name)}</span>`;
    },

    /* ── Highlight Card (Analytics) ──────────────────────────── */
    highlightCard(label, value, subtitle) {
        return `
            <div class="highlight-card">
                <div class="label">${Utils.escapeHtml(label)}</div>
                <div class="value">${value}</div>
                ${subtitle ? `<div class="subtitle">${Utils.escapeHtml(subtitle)}</div>` : ''}
            </div>
        `;
    },
};
