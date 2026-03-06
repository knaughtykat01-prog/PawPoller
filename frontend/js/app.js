/* ── SPA Router & Page Rendering ───────────────────────────── */
/*
 * Main application singleton — hash-based SPA router, page renderers,
 * and state management. Coordinates API calls, component rendering,
 * and chart creation for all pages (Inkbunny, FurAffinity, Weasyl,
 * cross-platform overview, groups, settings).
 */

const App = {
    /* ── Session-Persisted State ──────────────────────────────
     * These properties survive re-renders within the same browser
     * session but reset to their defaults on a fresh page load.
     *
     * _sortState / _faSortState / _wsSortState:
     *   Current column sort for the IB / FA / WS submissions tables.
     *   { field: 'views'|'favorites_count'|..., order: 'asc'|'desc' }
     *
     * _dateRange:
     *   Active date-range filter ('all', '7d', '30d', '90d', 'year')
     *   shared by dashboard and detail chart date-range bars.
     *
     * _compareIds / _faCompareIds / _wsCompareIds:
     *   Set of submission IDs currently selected on the IB / FA / WS
     *   comparison page (max 5 each).
     *
     * _compareMetric / _faCompareMetric / _wsCompareMetric:
     *   Metric shown on the comparison overlay chart ('views',
     *   'favorites_count', 'comments_count').
     *
     * _autoRefreshTimer:
     *   Handle returned by setInterval for the 60-second auto-refresh
     *   cycle. Cleared on every route change so stale timers don't fire.
     *
     * _autoRefreshInterval:
     *   Interval in milliseconds (60 000 = 60 s). The auto-refresh
     *   re-renders the current page to show fresh poll data. It is
     *   paused automatically when the browser tab is hidden
     *   (document.hidden check inside _startAutoRefresh).
     */
    currentPage: null,
    _sortState: { field: 'views', order: 'desc' },
    _dateRange: 'all',
    _compareIds: new Set(),
    _compareMetric: 'views',
    _autoRefreshTimer: null,
    _autoRefreshInterval: 60000,
    _faSortState: { field: 'views', order: 'desc' },
    _faCompareIds: new Set(),
    _faCompareMetric: 'views',
    _wsSortState: { field: 'views', order: 'desc' },
    _wsCompareIds: new Set(),
    _wsCompareMetric: 'views',
    _sfSortState: { field: 'views', order: 'desc' },
    _sfCompareIds: new Set(),
    _sfCompareMetric: 'views',

    /*
     * init() — Boot sequence, called once from index.html on DOMContentLoaded.
     *
     * 1. Registers the hashchange listener so every URL fragment change
     *    triggers route().
     * 2. Auth check: redirects to #/login if the server has no stored
     *    credentials, or to #/loading if credentials exist but no
     *    submission data has been fetched yet.
     * 3. Fires the initial route() to render whatever hash is in the URL.
     * 4. Starts a 60-second poll-status interval that updates the
     *    "last polled" badge in the sidebar.
     * 5. Creates the hamburger menu toggle + sidebar overlay for mobile
     *    viewports (< 768 px). Clicking the overlay or any nav link
     *    closes the mobile sidebar.
     * 6. Wires up the logout button to call API.authLogout then redirect
     *    to the login screen.
     */
    async init() {
        /* Listen for hash changes so browser back/forward works */
        window.addEventListener('hashchange', () => this.route());
        /* Auth gate — decide which screen the user should land on */
        try {
            const auth = await API.getAuthStatus();
            if (!auth.has_credentials) {
                window.location.hash = '#/login';
            } else if (!auth.has_data) {
                window.location.hash = '#/loading';
            }
        } catch (err) {
            console.warn('[App] Auth status check failed:', err);
        }

        /* Render the initial page and kick off the poll-status ticker */
        this.route();
        this._updatePollStatus();
        this._pollStatusInterval = setInterval(() => this._updatePollStatus(), 60000);

        /* Hamburger menu — create an overlay backdrop for mobile sidebar */
        const sidebar = document.querySelector('.sidebar');
        const overlay = document.createElement('div');
        overlay.className = 'sidebar-overlay';
        overlay.id = 'sidebar-overlay';
        document.body.appendChild(overlay);
        /* Toggle sidebar open/closed when the hamburger icon is tapped */
        document.getElementById('hamburger-btn')?.addEventListener('click', () => {
            sidebar?.classList.toggle('open');
            overlay.classList.toggle('open');
        });

        /* Tapping the translucent overlay closes the sidebar */
        overlay.addEventListener('click', () => {
            sidebar?.classList.remove('open');
            overlay.classList.remove('open');
        });

        /* Close sidebar on nav click (mobile) so the page behind is visible */
        document.querySelectorAll('.nav-link').forEach(link => {
            link.addEventListener('click', () => {
                sidebar?.classList.remove('open');
                overlay.classList.remove('open');
            });
        });

        /* Logout button — fire-and-forget the API call, then redirect */
        document.getElementById('logout-btn')?.addEventListener('click', async () => {
            try {
                await API.authLogout();
            } catch { /* ignore */ }
            this.navigate('/login');
        });
    },

    /*
     * navigate() — Programmatic navigation helper.
     * Sets window.location.hash which triggers the hashchange listener
     * and therefore route(). Use instead of direct hash assignment for
     * readability (e.g. this.navigate('/login')).
     */
    navigate(path) {
        window.location.hash = path;
    },

    /* route() — Main SPA router. Parses hash, toggles sidebar, dispatches to renderer. */
    route() {
        this._stopAutoRefresh();

        /* Parse hash: '#/fa/submission/42' -> hash='/fa/submission/42', parts=['fa','submission','42'] */
        const hash = window.location.hash.slice(1) || '/';
        const parts = hash.split('/').filter(Boolean);

        /* Full-screen pages (login, loading) hide the sidebar and remove left margin */
        const isFullScreen = parts[0] === 'login' || parts[0] === 'loading';
        const sidebar = document.querySelector('.sidebar');
        const main = document.getElementById('app');
        if (sidebar) sidebar.style.display = isFullScreen ? 'none' : '';
        if (main) main.style.marginLeft = isFullScreen ? '0' : '';

        /* Highlight the active nav link in the sidebar */
        document.querySelectorAll('.nav-link').forEach(link => {
            link.classList.toggle('active', link.getAttribute('href') === '#' + hash ||
                (hash === '/' && link.getAttribute('href') === '#/'));
        });

        /* Destroy old Chart.js instances to free canvas memory */
        Charts.destroyAll();

        if (parts[0] === 'login') {
            this.renderLogin();
        } else if (parts[0] === 'loading') {
            this.renderLoading();
        } else if (parts[0] === 'overview') {
            this.renderOverview();
        } else if (hash === '/' || hash === '') {
            this.renderDashboard();
        } else if (parts[0] === 'submissions' && !parts[1]) {
            this.renderSubmissions();
        } else if (parts[0] === 'submission' && parts[1]) {
            this.renderDetail(parseInt(parts[1]));
        } else if (parts[0] === 'compare') {
            this.renderCompare();
        } else if (parts[0] === 'fa' && (!parts[1] || parts[1] === '')) {
            this.renderFADashboard();
        } else if (parts[0] === 'fa' && parts[1] === 'submissions' && !parts[2]) {
            this.renderFASubmissions();
        } else if (parts[0] === 'fa' && parts[1] === 'submission' && parts[2]) {
            this.renderFADetail(parseInt(parts[2]));
        } else if (parts[0] === 'fa' && parts[1] === 'compare') {
            this.renderFACompare();
        } else if (parts[0] === 'ws' && (!parts[1] || parts[1] === '')) {
            this.renderWSDashboard();
        } else if (parts[0] === 'ws' && parts[1] === 'submissions' && !parts[2]) {
            this.renderWSSubmissions();
        } else if (parts[0] === 'ws' && parts[1] === 'submission' && parts[2]) {
            this.renderWSDetail(parseInt(parts[2]));
        } else if (parts[0] === 'ws' && parts[1] === 'compare') {
            this.renderWSCompare();
        } else if (parts[0] === 'sf' && (!parts[1] || parts[1] === '')) {
            this.renderSFDashboard();
        } else if (parts[0] === 'sf' && parts[1] === 'submissions' && !parts[2]) {
            this.renderSFSubmissions();
        } else if (parts[0] === 'sf' && parts[1] === 'submission' && parts[2]) {
            this.renderSFDetail(parts[2]);
        } else if (parts[0] === 'sf' && parts[1] === 'compare') {
            this.renderSFCompare();
        } else if (parts[0] === 'groups' && !parts[1]) {
            this.renderGroups();
        } else if (parts[0] === 'group' && parts[1]) {
            this.renderGroupDetail(parseInt(parts[1]));
        } else if (parts[0] === 'cross-platform') {
            this.renderCrossPlatform();
        } else if (parts[0] === 'settings') {
            this.renderSettings();
        } else {
            this._setContent('<div class="empty-state"><h3>Page not found</h3></div>');
        }
    },

    /* _setContent() — DOM helper: replaces the #app main content area with the given HTML string. */
    _setContent(html) {
        document.getElementById('app').innerHTML = html;
    },

    /* _loading() — DOM helper: shows a spinner placeholder while async data loads. */
    _loading() {
        this._setContent('<div class="loading-spinner">Loading...</div>');
    },

    /* ── Login Screen ──────────────────────────────────────────
     * renderLogin() — Full-screen login form with username, password, and
     * remember-me checkbox. The submit handler calls API.authLogin, strips
     * "API NNN:" prefixes from error messages, and tries to JSON-parse the
     * detail field for cleaner display. Enter on username focuses password;
     * Enter on password triggers submit. Auto-focuses the username field. */

    renderLogin() {
        if (this._pollStatusInterval) {
            clearInterval(this._pollStatusInterval);
            this._pollStatusInterval = null;
        }
        this._setContent(`
            <div class="login-screen">
                <div class="login-card">
                    <h2>PawPoller</h2>
                    <p style="color:var(--text-muted);margin-bottom:20px;font-size:13px">Sign in with your Inkbunny account to get started.</p>
                    <div class="login-field">
                        <label>Username</label>
                        <input type="text" id="login-username" class="search-input" placeholder="Inkbunny username" style="width:100%">
                    </div>
                    <div class="login-field">
                        <label>Password</label>
                        <input type="password" id="login-password" class="search-input" placeholder="Password" style="width:100%">
                    </div>
                    <label class="login-remember">
                        <input type="checkbox" id="login-remember" checked>
                        <span>Remember me</span>
                    </label>
                    <button class="btn btn-primary login-btn" id="login-submit">Sign In</button>
                    <div class="login-error" id="login-error"></div>
                </div>
            </div>
        `);

        const submit = async () => {
            const btn = document.getElementById('login-submit');
            const errEl = document.getElementById('login-error');
            const username = document.getElementById('login-username').value.trim();
            const password = document.getElementById('login-password').value;
            const remember = document.getElementById('login-remember').checked;

            if (!username || !password) {
                errEl.textContent = 'Username and password are required.';
                return;
            }

            btn.disabled = true;
            btn.textContent = 'Signing in...';
            errEl.textContent = '';

            try {
                await API.authLogin({ username, password, remember });
                this.navigate('/loading');
            } catch (err) {
                /* Strip "API 401: " prefix and try to extract JSON .detail for cleaner display */
                let msg = err.message.replace(/^API \d+:\s*/, '');
                try { msg = JSON.parse(msg).detail || msg; } catch {}
                errEl.textContent = msg;
                btn.textContent = 'Sign In';
                btn.disabled = false;
            }
        };

        /* Wire submit button + Enter key handlers: Enter on username focuses password,
         * Enter on password triggers submit */
        document.getElementById('login-submit').addEventListener('click', submit);
        document.getElementById('login-password').addEventListener('keydown', (e) => {
            if (e.key === 'Enter') submit();
        });
        document.getElementById('login-username').addEventListener('keydown', (e) => {
            if (e.key === 'Enter') document.getElementById('login-password').focus();
        });

        // Auto-focus username
        document.getElementById('login-username').focus();
    },

    /* ── Loading Screen ─────────────────────────────────────────
     * renderLoading() — First-run loading screen shown after login when no
     * submission data exists yet. Displays a progress bar and phase label.
     *
     * Flow: triggers an initial poll via API.triggerPoll() (fire-and-forget),
     * then polls /api/poll/progress every 1.5 seconds to update the progress
     * bar percentage and human-readable phase labels (idle -> starting ->
     * logging_in -> searching -> fetching_details -> processing -> complete).
     * During the "processing" phase, progress is interpolated from 40-95%
     * based on current/total submission count. Auto-navigates to the IB
     * dashboard (#/) on completion after a 600 ms delay. On error, displays
     * the error message in red. The poll interval handle is stored in
     * _loadingPollInterval so it can be cleaned up if the user navigates away. */

    renderLoading() {
        this._setContent(`
            <div class="loading-screen">
                <div class="loading-card">
                    <h2>Setting Up</h2>
                    <p id="loading-message" style="color:var(--text-muted);margin-bottom:16px;font-size:13px">Starting initial sync...</p>
                    <div class="progress-bar-container">
                        <div class="progress-bar" id="loading-bar" style="width:0%"></div>
                    </div>
                    <p id="loading-detail" style="color:var(--text-muted);margin-top:10px;font-size:12px"></p>
                </div>
            </div>
        `);

        // Fire-and-forget: trigger a poll
        API.triggerPoll().catch(() => {});

        const msgEl = document.getElementById('loading-message');
        const barEl = document.getElementById('loading-bar');
        const detailEl = document.getElementById('loading-detail');

        /* Human-readable labels for each poll phase (shown as progress text) */
        const phaseLabels = {
            idle: 'Waiting to start...',
            starting: 'Initialising...',
            logging_in: 'Authenticating with Inkbunny...',
            searching: 'Searching for submissions...',
            fetching_details: 'Fetching submission details...',
            processing: 'Processing submissions...',
            complete: 'Sync complete!',
            error: 'An error occurred.',
        };

        /* Base progress % for each phase; "processing" interpolates 40-95% from current/total */
        const phaseProgress = {
            idle: 0, starting: 5, logging_in: 10, searching: 20,
            fetching_details: 35, processing: 40, complete: 100, error: 0,
        };

        /* Poll /api/poll/progress every 1.5s; auto-navigate to dashboard on completion */
        const pollInterval = setInterval(async () => {
            try {
                const p = await API.getPollProgress();
                const label = phaseLabels[p.phase] || p.message || p.phase;
                if (msgEl) msgEl.textContent = label;

                let pct = phaseProgress[p.phase] || 0;
                if (p.phase === 'processing' && p.total > 0) {
                    pct = 40 + Math.round((p.current / p.total) * 55);
                }
                if (barEl) barEl.style.width = pct + '%';

                if (p.phase === 'processing' && p.total > 0) {
                    if (detailEl) detailEl.textContent = p.current + ' / ' + p.total + ' submissions';
                } else {
                    if (detailEl) detailEl.textContent = p.message || '';
                }

                if (p.phase === 'complete') {
                    clearInterval(pollInterval);
                    setTimeout(() => this.navigate('/'), 600);
                }
                if (p.phase === 'error') {
                    clearInterval(pollInterval);
                    if (detailEl) {
                        detailEl.textContent = p.message || 'Poll failed. Check Settings for details.';
                        detailEl.style.color = 'var(--danger)';
                    }
                }
            } catch {
                // Server might not be ready yet, keep trying
            }
        }, 1500);

        // Store so we can clean up if user navigates away
        this._loadingPollInterval = pollInterval;
    },

    /* ── Combined Overview ───────────────────────────────────────
     * renderOverview() — Cross-platform overview page aggregating data from
     * all four platforms (IB, FA, WS, SF).
     *
     * Fetches IB+FA+WS+SF summaries, aggregate snapshots, top fans, and trending
     * data in parallel via Promise.all, with individual .catch() fallbacks so
     * one platform's failure does not block the others. Merges top-viewed and
     * top-faved lists across platforms by sorting combined arrays by the
     * relevant metric and taking the top 10. Also merges recent faves and
     * comments into a unified recent-activity timeline sorted by first_seen_at.
     *
     * Renders: cross-platform stat totals, per-platform summary cards, trending
     * section (if any), date-range-filtered aggregate charts (one per platform),
     * top viewed/faved lists, recent activity feed, and top fans table.
     * Binds date range bar and starts auto-refresh. */

    async renderOverview() {
        this._loading();
        try {
            /* Fetch all platform data in parallel; .catch() fallbacks prevent one failure from blocking all */
            const [ibSummary, faSummary, wsSummary, sfSummary, ibAgg, faAgg, wsAgg, sfAgg, topFans, trending] = await Promise.all([
                API.getSummary().catch(() => null),
                API.getFASummary().catch(() => null),
                API.getWSSummary().catch(() => null),
                API.getSFSummary().catch(() => null),
                API.getAggregate(Utils.getDateRange(this._dateRange)).catch(() => null),
                API.getFAAggregate(Utils.getDateRange(this._dateRange)).catch(() => null),
                API.getWSAggregate(Utils.getDateRange(this._dateRange)).catch(() => null),
                API.getSFAggregate(Utils.getDateRange(this._dateRange)).catch(() => null),
                API.getTopFans(10).catch(() => ({ fans: [] })),
                API.getTrending({ hours: 24, threshold: 2.0 }).catch(() => ({ trending: [] })),
            ]);

            const ib = ibSummary || {};
            const fa = faSummary || {};
            const ws = wsSummary || {};
            const sf = sfSummary || {};

            /* Sum totals across all four platforms for the top-level stat cards */
            const totalSubs = (ib.total_submissions || 0) + (fa.total_submissions || 0) + (ws.total_submissions || 0) + (sf.total_submissions || 0);
            const totalViews = (ib.total_views || 0) + (fa.total_views || 0) + (ws.total_views || 0) + (sf.total_views || 0);
            const totalFaves = (ib.total_favorites || 0) + (fa.total_favorites || 0) + (ws.total_favorites || 0) + (sf.total_favorites || 0);
            const totalComments = (ib.total_comments || 0) + (fa.total_comments || 0) + (ws.total_comments || 0) + (sf.total_comments || 0);

            /* Merge top lists across platforms: tag each with _platform, sort desc, take top 10 */
            const mergeTop = (ibList, faList, wsList, sfList, key) => {
                const merged = [];
                (ibList || []).forEach(item => merged.push({ ...item, _platform: 'ib' }));
                (faList || []).forEach(item => merged.push({ ...item, _platform: 'fa' }));
                (wsList || []).forEach(item => merged.push({ ...item, _platform: 'ws' }));
                (sfList || []).forEach(item => merged.push({ ...item, _platform: 'sf' }));
                merged.sort((a, b) => (b[key] || 0) - (a[key] || 0));
                return merged.slice(0, 10);
            };

            const topViewed = mergeTop(ib.top_viewed, fa.top_viewed, ws.top_viewed, sf.top_viewed, 'views');
            const topFaved = mergeTop(ib.top_faved, fa.top_faved, ws.top_faved, sf.top_faved, 'favorites_count');

            /* Merge recent faves + comments into a unified timeline, sorted newest first */
            const recentActivity = [];
            (ib.recent_faves || []).forEach(item => recentActivity.push({ ...item, _platform: 'ib', _type: 'fave' }));
            (ib.recent_comments || []).forEach(item => recentActivity.push({ ...item, _platform: 'ib', _type: 'comment' }));
            (fa.recent_comments || []).forEach(item => recentActivity.push({ ...item, _platform: 'fa', _type: 'comment' }));
            recentActivity.sort((a, b) => new Date(b.first_seen_at || 0) - new Date(a.first_seen_at || 0));

            /* Per-platform mini stat card showing views, faves, subs with a coloured badge */
            const platformCard = (badge, label, data) => `
                <div class="stat-card">
                    <div class="label">${badge} ${label}</div>
                    <div style="display:flex;gap:16px;margin-top:6px">
                        <div><span style="font-size:18px;font-weight:600">${Utils.formatCompact(data.total_views || 0)}</span> <span style="font-size:11px;color:var(--text-muted)">views</span></div>
                        <div><span style="font-size:18px;font-weight:600">${Utils.formatCompact(data.total_favorites || 0)}</span> <span style="font-size:11px;color:var(--text-muted)">faves</span></div>
                        <div><span style="font-size:18px;font-weight:600">${Utils.formatCompact(data.total_submissions || 0)}</span> <span style="font-size:11px;color:var(--text-muted)">subs</span></div>
                    </div>
                </div>`;

            const html = `
                ${this._refreshIndicatorHtml()}
                <div class="page-header">
                    <h2>Overview</h2>
                    <div style="display:flex;gap:8px">
                        <button class="btn btn-secondary" onclick="API.exportSubmissions('ib')" title="Export IB CSV">Export IB</button>
                        <button class="btn btn-secondary" onclick="API.exportSubmissions('fa')" title="Export FA CSV">Export FA</button>
                        <button class="btn btn-secondary" onclick="API.exportSubmissions('ws')" title="Export WS CSV">Export WS</button>
                        <button class="btn btn-secondary" onclick="API.exportSubmissions('sf')" title="Export SF CSV">Export SF</button>
                    </div>
                </div>

                <div class="stats-grid">
                    ${Components.statCard('Total Submissions', totalSubs)}
                    ${Components.statCard('Total Views', totalViews)}
                    ${Components.statCard('Total Favorites', totalFaves)}
                    ${Components.statCard('Total Comments', totalComments)}
                </div>

                <div class="stats-grid" style="grid-template-columns:repeat(auto-fit,minmax(200px,1fr));margin-top:0">
                    ${platformCard('<span class="platform-badge ib">IB</span>', 'Inkbunny', ib)}
                    ${platformCard('<span class="platform-badge fa">FA</span>', 'FurAffinity', fa)}
                    ${platformCard('<span class="platform-badge ws">WS</span>', 'Weasyl', ws)}
                    ${platformCard('<span class="platform-badge sf">SF</span>', 'SoFurry', sf)}
                </div>

                ${(trending.trending || []).length > 0 ? `
                <div class="chart-container">
                    <h3>Trending Now</h3>
                    <div class="stats-grid" style="margin-bottom:0">${Components.trendingCards(trending.trending)}</div>
                </div>` : ''}

                ${Components.dateRangeBar(this._dateRange)}

                <div class="chart-row">
                    <div class="chart-container">
                        <h3>Inkbunny Views</h3>
                        <div class="chart-wrap"><canvas id="chart-ib-views"></canvas></div>
                    </div>
                    <div class="chart-container">
                        <h3>FurAffinity Views</h3>
                        <div class="chart-wrap"><canvas id="chart-fa-views"></canvas></div>
                    </div>
                </div>

                ${wsAgg?.snapshots?.length > 0 ? `
                <div class="chart-container">
                    <h3>Weasyl Views</h3>
                    <div class="chart-wrap"><canvas id="chart-ws-views"></canvas></div>
                </div>` : ''}

                ${sfAgg?.snapshots?.length > 0 ? `
                <div class="chart-container">
                    <h3>SoFurry Views</h3>
                    <div class="chart-wrap"><canvas id="chart-sf-views"></canvas></div>
                </div>` : ''}

                <div class="chart-row">
                    <div class="chart-container">
                        <h3>Top Viewed</h3>
                        ${Components.overviewTopList(topViewed, 'views')}
                    </div>
                    <div class="chart-container">
                        <h3>Top Faved</h3>
                        ${Components.overviewTopList(topFaved, 'favorites_count')}
                    </div>
                </div>

                <div class="chart-row">
                    <div class="chart-container">
                        <h3>Recent Activity</h3>
                        ${Components.overviewRecentActivity(recentActivity.slice(0, 15))}
                    </div>
                    <div class="chart-container">
                        <h3>Top Fans</h3>
                        ${Components.topFansTable((topFans.fans || []).slice(0, 10))}
                    </div>
                </div>
            `;

            this._setContent(html);

            /* Render per-platform aggregate line charts (only if snapshots exist) */
            if (ibAgg?.snapshots?.length > 0) {
                Charts.aggregateLine('chart-ib-views', ibAgg.snapshots, ['views']);
            }
            if (faAgg?.snapshots?.length > 0) {
                Charts.aggregateLine('chart-fa-views', faAgg.snapshots, ['views']);
            }
            if (wsAgg?.snapshots?.length > 0) {
                Charts.aggregateLine('chart-ws-views', wsAgg.snapshots, ['views']);
            }
            if (sfAgg?.snapshots?.length > 0) {
                Charts.aggregateLine('chart-sf-views', sfAgg.snapshots, ['views']);
            }

            /* Wire date range buttons to full re-render; start 60s auto-refresh */
            this._bindDateRange(() => this.renderOverview());
            this._startAutoRefresh(() => this.renderOverview());
        } catch (err) {
            this._setContent(`<div class="empty-state"><h3>Error loading overview</h3><p>${Utils.escapeHtml(err.message)}</p></div>`);
        }
    },

    /* ── Dashboard Overview ────────────────────────────────────
     * renderDashboard() — Inkbunny-specific dashboard (the default landing page).
     *
     * Fetches IB summary stats and aggregate snapshots in parallel. Renders:
     * stat cards (submissions, views, faves, comments), growth rate cards
     * (1h/24h/7d/30d deltas), date-range-filtered aggregate views-over-time
     * line chart, top viewed and top faved horizontal bar charts, fastest
     * growing list (24h views gained), recent fave activity, and recent
     * comments. Binds date range bar and starts auto-refresh. */

    async renderDashboard() {
        this._loading();
        try {
            /* Fetch IB summary stats and aggregate snapshots in parallel */
            const [summary, agg] = await Promise.all([
                API.getSummary(),
                API.getAggregate(Utils.getDateRange(this._dateRange)),
            ]);

            const html = `
                ${this._refreshIndicatorHtml()}
                <div class="page-header"><h2>Dashboard</h2></div>

                <div class="stats-grid">
                    ${Components.statCard('Total Submissions', summary.total_submissions)}
                    ${Components.statCard('Total Views', summary.total_views)}
                    ${Components.statCard('Total Favorites', summary.total_favorites)}
                    ${Components.statCard('Total Comments', summary.total_comments)}
                    ${Components.statCard('Total Watchers', summary.total_watchers || 0)}
                </div>

                ${Components.growthRateCards(summary.growth_rates)}

                ${Components.dateRangeBar(this._dateRange)}

                <div class="chart-container">
                    <h3>Views Over Time (Aggregate)</h3>
                    <div class="chart-wrap"><canvas id="chart-agg-views"></canvas></div>
                </div>

                <div class="chart-row">
                    <div class="chart-container">
                        <h3>Top Viewed</h3>
                        <div class="chart-wrap"><canvas id="chart-top-views"></canvas></div>
                    </div>
                    <div class="chart-container">
                        <h3>Top Faved</h3>
                        <div class="chart-wrap"><canvas id="chart-top-faves"></canvas></div>
                    </div>
                </div>

                <div class="chart-row">
                    <div class="chart-container">
                        <h3>Fastest Growing (24h)</h3>
                        ${Components.topList(summary.fastest_growing, 'views_gained')}
                    </div>
                    <div class="chart-container">
                        <h3>Recent Fave Activity</h3>
                        ${Components.recentFaves(summary.recent_faves)}
                    </div>
                </div>

                <div class="chart-row">
                    <div class="chart-container">
                        <h3>Recent Comments</h3>
                        ${Components.recentComments(summary.recent_comments)}
                    </div>
                    <div class="chart-container">
                        <h3>Recent Watchers</h3>
                        ${Components.recentWatchers(summary.recent_watchers)}
                    </div>
                </div>
            `;

            this._setContent(html);

            // Render charts
            if (agg.snapshots && agg.snapshots.length > 0) {
                Charts.aggregateLine('chart-agg-views', agg.snapshots, ['views']);
            }
            if (summary.top_viewed && summary.top_viewed.length > 0) {
                Charts.topBar('chart-top-views', summary.top_viewed, 'views');
            }
            if (summary.top_faved && summary.top_faved.length > 0) {
                Charts.topBar('chart-top-faves', summary.top_faved, 'favorites_count');
            }

            // Date range click handler
            this._bindDateRange(() => this.renderDashboard());

            this._startAutoRefresh(() => this.renderDashboard());
        } catch (err) {
            this._setContent(`<div class="empty-state"><h3>Error loading dashboard</h3><p>${Utils.escapeHtml(err.message)}</p></div>`);
        }
    },

    /* ── Submissions Table ─────────────────────────────────────
     * renderSubmissions() — IB submissions table with search, rating filter,
     * and type filter. Loads all submissions sorted by _sortState. Binds
     * column-header sort (_bindTableSort) and client-side search/filter
     * (_bindSearch). Starts auto-refresh. */

    async renderSubmissions() {
        this._loading();
        try {
            const data = await API.getSubmissions({
                sort_by: this._sortState.field,
                order: this._sortState.order,
            });

            const html = `
                ${this._refreshIndicatorHtml()}
                <div class="page-header"><h2>Submissions</h2></div>
                <div class="toolbar">
                    <input type="text" class="search-input" id="search-input" placeholder="Search titles and keywords...">
                    <select class="filter-select" id="filter-rating">
                        <option value="">All Ratings</option>
                        <option value="0">General</option>
                        <option value="1">Mature</option>
                        <option value="2">Adult</option>
                    </select>
                    <select class="filter-select" id="filter-type">
                        <option value="">All Types</option>
                        <option value="Picture/Pinup">Picture</option>
                        <option value="Writing - Document">Writing</option>
                        <option value="Music - Single Track">Music</option>
                    </select>
                </div>
                <div id="table-container" class="table-scroll">
                    ${Components.submissionsTable(data.submissions)}
                </div>
            `;

            this._setContent(html);
            this._bindTableSort();
            this._bindSearch(data.submissions);

            this._startAutoRefresh(() => this.renderSubmissions());
        } catch (err) {
            this._setContent(`<div class="empty-state"><h3>Error loading submissions</h3><p>${Utils.escapeHtml(err.message)}</p></div>`);
        }
    },

    /* ── Submission Detail — IB detail: thumbnail, metadata, stats, growth rates,
     * time-series chart, faving users table, comments. Date range re-fetches snapshots only. */

    async renderDetail(id) {
        this._loading();
        try {
            const data = await API.getSubmission(id);
            const sub = data.submission;

            const html = `
                ${this._refreshIndicatorHtml()}
                <a href="#/submissions" class="back-link">&larr; Back to Submissions</a>
                <div class="detail-header">
                    ${sub.thumb_url ? `<img src="${Utils.thumbUrl(sub.thumb_url)}" class="detail-thumb">` : ''}
                    <div class="detail-info">
                        <h2>${Utils.escapeHtml(sub.title)}</h2>
                        <div class="detail-meta">by ${Utils.escapeHtml(sub.username)} &middot; ${Utils.formatDate(sub.create_datetime)} &middot; ${Utils.escapeHtml(sub.type_name)} &middot; ${Utils.escapeHtml(sub.rating_name)}</div>
                        <div class="detail-meta"><a href="https://inkbunny.net/s/${sub.submission_id}" target="_blank">View on Inkbunny</a></div>
                        <div class="detail-stats">
                            <div class="detail-stat">${Utils.formatNumber(sub.views)} <span class="lbl">views</span></div>
                            <div class="detail-stat">${Utils.formatNumber(sub.favorites_count)} <span class="lbl">faves</span></div>
                            <div class="detail-stat">${Utils.formatNumber(sub.comments_count)} <span class="lbl">comments</span></div>
                        </div>
                        <div style="margin-top:8px">${Components.keywords(sub.keywords)}</div>
                    </div>
                </div>

                ${Components.growthRateCards(data.growth_rates)}

                ${Components.dateRangeBar(this._dateRange)}

                <div class="chart-container">
                    <h3>Stats Over Time</h3>
                    <div class="chart-wrap"><canvas id="chart-detail"></canvas></div>
                </div>

                <div class="chart-container">
                    <h3>Faving Users (${data.faving_users.length})</h3>
                    ${Components.favingUsersTable(data.faving_users)}
                </div>

                <div class="chart-container">
                    <h3>Comments (${(data.comments || []).length})</h3>
                    ${Components.commentsSection(data.comments)}
                </div>
            `;

            this._setContent(html);

            if (data.snapshots && data.snapshots.length > 0) {
                Charts.submissionLine('chart-detail', data.snapshots);
            }

            /* Date range changes re-fetch only snapshots for the chart, not the full detail */
            this._bindDateRange(async () => {
                const range = Utils.getDateRange(this._dateRange);
                const snaps = await API.getSnapshots(id, range);
                Charts.submissionLine('chart-detail', snaps.snapshots);
            });

            this._startAutoRefresh(() => this.renderDetail(id));
        } catch (err) {
            this._setContent(`<div class="empty-state"><h3>Error loading submission</h3><p>${Utils.escapeHtml(err.message)}</p></div>`);
        }
    },

    /* ── Comparison — IB comparison page: chip selection (max 5), metric
     * dropdown, date range, overlay chart. Chips toggle _compareIds; metric/
     * date changes re-render only the chart via _loadComparisonChart(). */

    async renderCompare() {
        this._loading();
        try {
            const data = await API.getSubmissions({ sort_by: 'views', order: 'desc' });
            const subs = data.submissions;

            /* Build chip labels for every submission; pre-check selected state from _compareIds */
            const chips = subs.map(s => `
                <label class="compare-chip ${this._compareIds.has(s.submission_id) ? 'selected' : ''}" data-id="${s.submission_id}">
                    <input type="checkbox" ${this._compareIds.has(s.submission_id) ? 'checked' : ''}>
                    ${Utils.escapeHtml(Utils.truncate(s.title, 25))}
                </label>
            `).join('');

            const html = `
                ${this._refreshIndicatorHtml()}
                <div class="page-header">
                    <h2>Compare Submissions</h2>
                    <div>
                        <select class="filter-select" id="compare-metric">
                            <option value="views" ${this._compareMetric === 'views' ? 'selected' : ''}>Views</option>
                            <option value="favorites_count" ${this._compareMetric === 'favorites_count' ? 'selected' : ''}>Favourites</option>
                            <option value="comments_count" ${this._compareMetric === 'comments_count' ? 'selected' : ''}>Comments</option>
                        </select>
                    </div>
                </div>
                <p style="font-size:13px;color:var(--text-muted);margin-bottom:12px">Compare how your submissions perform over time. Select 2-5 submissions and choose a metric (views, favourites, or comments) to see their trends side by side.</p>
                <div class="compare-select">${chips}</div>

                ${Components.dateRangeBar(this._dateRange)}

                <div class="chart-container" id="compare-chart-container" style="${this._compareIds.size < 2 ? 'display:none' : ''}">
                    <h3>Comparison</h3>
                    <div class="chart-wrap"><canvas id="chart-compare"></canvas></div>
                </div>
                ${this._compareIds.size < 2 ? '<div class="empty-state"><p>Select at least 2 submissions above to see their trends compared.</p></div>' : ''}
            `;

            this._setContent(html);

            /* Chip click handlers: toggle selection in _compareIds (max 5), re-render page */
            document.querySelectorAll('.compare-chip').forEach(chip => {
                chip.addEventListener('click', (e) => {
                    e.preventDefault();
                    const id = parseInt(chip.dataset.id);
                    if (this._compareIds.has(id)) {
                        this._compareIds.delete(id);
                    } else if (this._compareIds.size < 5) {
                        this._compareIds.add(id);
                    }
                    this.renderCompare();
                });
            });

            /* Metric dropdown: changing it stores the value and re-renders only the chart */
            const metricSelect = document.getElementById('compare-metric');
            if (metricSelect) {
                metricSelect.addEventListener('change', () => {
                    this._compareMetric = metricSelect.value;
                    this._loadComparisonChart();
                });
            }

            this._bindDateRange(() => this._loadComparisonChart());

            if (this._compareIds.size >= 2) {
                await this._loadComparisonChart();
            }

            this._startAutoRefresh(() => this.renderCompare());
        } catch (err) {
            this._setContent(`<div class="empty-state"><h3>Error</h3><p>${Utils.escapeHtml(err.message)}</p></div>`);
        }
    },

    /* _loadComparisonChart() — Fetches comparison data for selected IB submissions
     * (_compareIds) and renders an overlay line chart. Bails out if fewer than 2
     * submissions are selected. Shows the compare-chart-container div and delegates
     * to Charts.comparisonLine() with the current _compareMetric. */
    async _loadComparisonChart() {
        try {
            if (this._compareIds.size < 2) return;
            const range = Utils.getDateRange(this._dateRange);
            const data = await API.getComparison([...this._compareIds], range);
            const container = document.getElementById('compare-chart-container');
            if (container) container.style.display = '';
            Charts.comparisonLine('chart-compare', data.series, data.titles, this._compareMetric);
        } catch (e) {
            console.error('Failed to load comparison chart:', e);
        }
    },

    // ── FA Dashboard ───────────────────────────────────────────
    // FurAffinity-specific dashboard page. Follows the same pattern as the IB
    // dashboard but uses FA API methods (getFASummary, getFAAggregate) and FA
    // components (faTopList, faRecentComments). Displays summary stat cards
    // (submissions, views, favourites, comments), growth rate cards, aggregate
    // views-over-time chart, top viewed/faved bar charts, fastest-growing list,
    // and a recent comments panel.

    async renderFADashboard() {
        this._loading();
        try {
            // Fetch summary stats and aggregate snapshots in parallel
            const [summary, agg] = await Promise.all([
                API.getFASummary(),
                API.getFAAggregate(Utils.getDateRange(this._dateRange)),
            ]);

            const html = `
                ${this._refreshIndicatorHtml()}
                <div class="page-header"><h2>FurAffinity Dashboard</h2></div>

                <div class="stats-grid">
                    ${Components.statCard('Total Submissions', summary.total_submissions)}
                    ${Components.statCard('Total Views', summary.total_views)}
                    ${Components.statCard('Total Favorites', summary.total_favorites)}
                    ${Components.statCard('Total Comments', summary.total_comments)}
                    ${Components.statCard('Total Watchers', summary.total_watchers || 0)}
                </div>

                ${Components.growthRateCards(summary.growth_rates)}

                ${Components.dateRangeBar(this._dateRange)}

                <div class="chart-container">
                    <h3>Views Over Time (Aggregate)</h3>
                    <div class="chart-wrap"><canvas id="chart-agg-views"></canvas></div>
                </div>

                <div class="chart-row">
                    <div class="chart-container">
                        <h3>Top Viewed</h3>
                        <div class="chart-wrap"><canvas id="chart-top-views"></canvas></div>
                    </div>
                    <div class="chart-container">
                        <h3>Top Faved</h3>
                        <div class="chart-wrap"><canvas id="chart-top-faves"></canvas></div>
                    </div>
                </div>

                <div class="chart-row">
                    <div class="chart-container">
                        <h3>Fastest Growing (24h)</h3>
                        ${Components.faTopList(summary.fastest_growing, 'views_gained')}
                    </div>
                    <div class="chart-container">
                        <h3>Recent Comments</h3>
                        ${Components.faRecentComments(summary.recent_comments)}
                    </div>
                </div>

                <div class="chart-row">
                    <div class="chart-container">
                        <h3>Recent Watchers</h3>
                        ${Components.recentWatchers(summary.recent_watchers)}
                    </div>
                </div>
            `;

            this._setContent(html);

            // Render charts only when data exists to avoid empty canvas errors
            if (agg.snapshots && agg.snapshots.length > 0) {
                Charts.aggregateLine('chart-agg-views', agg.snapshots, ['views']);
            }
            if (summary.top_viewed && summary.top_viewed.length > 0) {
                Charts.topBar('chart-top-views', summary.top_viewed, 'views');
            }
            if (summary.top_faved && summary.top_faved.length > 0) {
                Charts.topBar('chart-top-faves', summary.top_faved, 'favorites_count');
            }

            // Wire date range buttons to re-render the entire dashboard with new date window
            this._bindDateRange(() => this.renderFADashboard());
            // Start 60s auto-refresh cycle for live data updates
            this._startAutoRefresh(() => this.renderFADashboard());
        } catch (err) {
            this._setContent(`<div class="empty-state"><h3>Error loading FA dashboard</h3><p>${Utils.escapeHtml(err.message)}</p></div>`);
        }
    },

    // ── FA Submissions ─────────────────────────────────────────
    // FA submissions table with text search (title/keywords) and rating filter
    // dropdown (General/Mature/Adult). Sorting is handled server-side via
    // _faSortState. Search/filter is client-side against the full data set.

    async renderFASubmissions() {
        this._loading();
        try {
            // Fetch all FA submissions, sorted according to current sort state
            const data = await API.getFASubmissions({
                sort_by: this._faSortState.field,
                order: this._faSortState.order,
            });

            const html = `
                ${this._refreshIndicatorHtml()}
                <div class="page-header"><h2>FA Submissions</h2></div>
                <div class="toolbar">
                    <input type="text" class="search-input" id="search-input" placeholder="Search titles and keywords...">
                    <select class="filter-select" id="filter-rating">
                        <option value="">All Ratings</option>
                        <option value="General">General</option>
                        <option value="Mature">Mature</option>
                        <option value="Adult">Adult</option>
                    </select>
                </div>
                <div id="table-container" class="table-scroll">
                    ${Components.faSubmissionsTable(data.submissions)}
                </div>
            `;

            this._setContent(html);
            // Bind column header click handlers for table sorting
            this._bindFATableSort();
            // Bind text input and rating dropdown for client-side filtering
            this._bindFASearch(data.submissions);
            this._startAutoRefresh(() => this.renderFASubmissions());
        } catch (err) {
            this._setContent(`<div class="empty-state"><h3>Error loading FA submissions</h3><p>${Utils.escapeHtml(err.message)}</p></div>`);
        }
    },

    // ── FA Submission Detail ───────────────────────────────────
    // Individual FA submission detail page. Shows header with thumbnail, title,
    // author, post date, rating, and a direct link to FurAffinity. Includes
    // FA-specific metadata grid (category, theme, species, gender) that IB does
    // not have. Displays keywords, growth rate cards, stats-over-time chart,
    // and a comments section. Unlike IB detail, there is no faving-users list
    // because the FA API does not expose who faved a submission.

    async renderFADetail(id) {
        this._loading();
        try {
            const data = await API.getFASubmission(id);
            const sub = data.submission;

            const html = `
                ${this._refreshIndicatorHtml()}
                <a href="#/fa/submissions" class="back-link">&larr; Back to FA Submissions</a>
                <div class="detail-header">
                    ${sub.thumbnail_url ? `<img src="${Utils.faThumbUrl(sub.thumbnail_url)}" class="detail-thumb">` : ''}
                    <div class="detail-info">
                        <h2>${Utils.escapeHtml(sub.title)}</h2>
                        <div class="detail-meta">by ${Utils.escapeHtml(sub.username)} &middot; ${Utils.formatDate(sub.posted_at)} &middot; ${Utils.escapeHtml(sub.rating || '')}</div>
                        <div class="detail-meta"><a href="${Utils.escapeHtml(sub.link || '#')}" target="_blank">View on FurAffinity</a></div>
                        <div class="detail-stats">
                            <div class="detail-stat">${Utils.formatNumber(sub.views)} <span class="lbl">views</span></div>
                            <div class="detail-stat">${Utils.formatNumber(sub.favorites_count)} <span class="lbl">faves</span></div>
                            <div class="detail-stat">${Utils.formatNumber(sub.comments_count)} <span class="lbl">comments</span></div>
                        </div>
                        <div class="fa-metadata">
                            ${sub.category ? `<div class="fa-meta-item"><span class="fa-meta-label">Category</span><span class="fa-meta-value">${Utils.escapeHtml(sub.category)}</span></div>` : ''}
                            ${sub.theme ? `<div class="fa-meta-item"><span class="fa-meta-label">Theme</span><span class="fa-meta-value">${Utils.escapeHtml(sub.theme)}</span></div>` : ''}
                            ${sub.species ? `<div class="fa-meta-item"><span class="fa-meta-label">Species</span><span class="fa-meta-value">${Utils.escapeHtml(sub.species)}</span></div>` : ''}
                            ${sub.gender ? `<div class="fa-meta-item"><span class="fa-meta-label">Gender</span><span class="fa-meta-value">${Utils.escapeHtml(sub.gender)}</span></div>` : ''}
                        </div>
                        <div style="margin-top:8px">${Components.keywords(sub.keywords)}</div>
                    </div>
                </div>

                ${Components.growthRateCards(data.growth_rates)}

                ${Components.dateRangeBar(this._dateRange)}

                <div class="chart-container">
                    <h3>Stats Over Time</h3>
                    <div class="chart-wrap"><canvas id="chart-detail"></canvas></div>
                </div>

                <div class="chart-container">
                    <h3>Comments (${(data.comments || []).length})</h3>
                    ${Components.faCommentsSection(data.comments)}
                </div>
            `;

            this._setContent(html);

            // Render the stats-over-time line chart if snapshot data is available
            if (data.snapshots && data.snapshots.length > 0) {
                Charts.submissionLine('chart-detail', data.snapshots);
            }

            // Date range changes only re-fetch snapshots (not the full submission),
            // then re-render just the chart for a faster update
            this._bindDateRange(async () => {
                const range = Utils.getDateRange(this._dateRange);
                const snaps = await API.getFASnapshots(id, range);
                Charts.submissionLine('chart-detail', snaps.snapshots);
            });

            this._startAutoRefresh(() => this.renderFADetail(id));
        } catch (err) {
            this._setContent(`<div class="empty-state"><h3>Error loading FA submission</h3><p>${Utils.escapeHtml(err.message)}</p></div>`);
        }
    },

    // ── FA Compare ─────────────────────────────────────────────
    // FA comparison page. Same chip-selection / metric-dropdown / chart pattern
    // as the IB comparison page. Users select 2-5 FA submissions via toggle
    // chips, choose a metric (views/favourites/comments), and view a comparison
    // line chart. Selected submission IDs are tracked in _faCompareIds (a Set),
    // and the active metric lives in _faCompareMetric.

    async renderFACompare() {
        this._loading();
        try {
            // Fetch all FA submissions sorted by views to populate the chip selector
            const data = await API.getFASubmissions({ sort_by: 'views', order: 'desc' });
            const subs = data.submissions;

            // Build selectable chips for each submission; pre-check any already selected
            const chips = subs.map(s => `
                <label class="compare-chip ${this._faCompareIds.has(s.submission_id) ? 'selected' : ''}" data-id="${s.submission_id}">
                    <input type="checkbox" ${this._faCompareIds.has(s.submission_id) ? 'checked' : ''}>
                    ${Utils.escapeHtml(Utils.truncate(s.title, 25))}
                </label>
            `).join('');

            const html = `
                ${this._refreshIndicatorHtml()}
                <div class="page-header">
                    <h2>Compare FA Submissions</h2>
                    <div>
                        <select class="filter-select" id="compare-metric">
                            <option value="views" ${this._faCompareMetric === 'views' ? 'selected' : ''}>Views</option>
                            <option value="favorites_count" ${this._faCompareMetric === 'favorites_count' ? 'selected' : ''}>Favourites</option>
                            <option value="comments_count" ${this._faCompareMetric === 'comments_count' ? 'selected' : ''}>Comments</option>
                        </select>
                    </div>
                </div>
                <p style="font-size:13px;color:var(--text-muted);margin-bottom:12px">Select 2-5 FA submissions to compare their trends over time.</p>
                <div class="compare-select">${chips}</div>

                ${Components.dateRangeBar(this._dateRange)}

                <div class="chart-container" id="compare-chart-container" style="${this._faCompareIds.size < 2 ? 'display:none' : ''}">
                    <h3>Comparison</h3>
                    <div class="chart-wrap"><canvas id="chart-compare"></canvas></div>
                </div>
                ${this._faCompareIds.size < 2 ? '<div class="empty-state"><p>Select at least 2 submissions above to see their trends compared.</p></div>' : ''}
            `;

            this._setContent(html);

            // Chip click handlers: toggle selection, cap at 5, re-render to update visual state
            document.querySelectorAll('.compare-chip').forEach(chip => {
                chip.addEventListener('click', (e) => {
                    e.preventDefault();
                    const id = parseInt(chip.dataset.id);
                    if (this._faCompareIds.has(id)) {
                        this._faCompareIds.delete(id);
                    } else if (this._faCompareIds.size < 5) {
                        this._faCompareIds.add(id);
                    }
                    this.renderFACompare();
                });
            });

            // Metric dropdown: changing metric re-fetches and redraws the chart
            const metricSelect = document.getElementById('compare-metric');
            if (metricSelect) {
                metricSelect.addEventListener('change', () => {
                    this._faCompareMetric = metricSelect.value;
                    this._loadFAComparisonChart();
                });
            }

            // Date range changes also reload the comparison chart
            this._bindDateRange(() => this._loadFAComparisonChart());

            // Immediately load chart if enough submissions are selected
            if (this._faCompareIds.size >= 2) {
                await this._loadFAComparisonChart();
            }

            this._startAutoRefresh(() => this.renderFACompare());
        } catch (err) {
            this._setContent(`<div class="empty-state"><h3>Error</h3><p>${Utils.escapeHtml(err.message)}</p></div>`);
        }
    },

    // Fetches FA comparison data for the selected submission IDs and renders
    // the multi-line comparison chart. Unhides the chart container if hidden.
    async _loadFAComparisonChart() {
        try {
            // Guard: need at least 2 submissions to draw a meaningful comparison
            if (this._faCompareIds.size < 2) return;
            const range = Utils.getDateRange(this._dateRange);
            // Spread the Set into an array for the API call
            const data = await API.getFAComparison([...this._faCompareIds], range);
            const container = document.getElementById('compare-chart-container');
            if (container) container.style.display = '';
            Charts.comparisonLine('chart-compare', data.series, data.titles, this._faCompareMetric);
        } catch (e) {
            console.error('Failed to load FA comparison chart:', e);
        }
    },

    // ── WS Dashboard ──────────────────────────────────────────
    // Weasyl-specific dashboard. Same layout as FA/IB dashboards: stat cards,
    // growth rates, aggregate chart, top viewed/faved charts, and fastest
    // growing list. Unlike FA, there is no recent comments section because
    // the Weasyl API does not expose individual comment text. Includes a
    // CSV export button in the header.

    async renderWSDashboard() {
        this._loading();
        try {
            // Parallel fetch: summary stats and aggregate snapshot time-series
            const [summary, agg] = await Promise.all([
                API.getWSSummary(),
                API.getWSAggregate(Utils.getDateRange(this._dateRange)),
            ]);

            const html = `
                ${this._refreshIndicatorHtml()}
                <div class="page-header">
                    <h2>Weasyl Dashboard</h2>
                    <button class="btn btn-secondary" onclick="API.exportSubmissions('ws')">Export CSV</button>
                </div>

                <div class="stats-grid">
                    ${Components.statCard('Total Submissions', summary.total_submissions)}
                    ${Components.statCard('Total Views', summary.total_views)}
                    ${Components.statCard('Total Favorites', summary.total_favorites)}
                    ${Components.statCard('Total Comments', summary.total_comments)}
                </div>

                ${Components.growthRateCards(summary.growth_rates)}

                ${Components.dateRangeBar(this._dateRange)}

                <div class="chart-container">
                    <h3>Views Over Time (Aggregate)</h3>
                    <div class="chart-wrap"><canvas id="chart-agg-views"></canvas></div>
                </div>

                <div class="chart-row">
                    <div class="chart-container">
                        <h3>Top Viewed</h3>
                        <div class="chart-wrap"><canvas id="chart-top-views"></canvas></div>
                    </div>
                    <div class="chart-container">
                        <h3>Top Faved</h3>
                        <div class="chart-wrap"><canvas id="chart-top-faves"></canvas></div>
                    </div>
                </div>

                <div class="chart-row">
                    <div class="chart-container" style="grid-column: 1 / -1">
                        <h3>Fastest Growing (24h)</h3>
                        ${Components.wsTopList(summary.fastest_growing, 'views_gained')}
                    </div>
                </div>
            `;

            this._setContent(html);

            // Conditionally render each chart only when data exists
            if (agg.snapshots && agg.snapshots.length > 0) {
                Charts.aggregateLine('chart-agg-views', agg.snapshots, ['views']);
            }
            if (summary.top_viewed && summary.top_viewed.length > 0) {
                Charts.topBar('chart-top-views', summary.top_viewed, 'views');
            }
            if (summary.top_faved && summary.top_faved.length > 0) {
                Charts.topBar('chart-top-faves', summary.top_faved, 'favorites_count');
            }

            this._bindDateRange(() => this.renderWSDashboard());
            this._startAutoRefresh(() => this.renderWSDashboard());
        } catch (err) {
            this._setContent(`<div class="empty-state"><h3>Error loading WS dashboard</h3><p>${Utils.escapeHtml(err.message)}</p></div>`);
        }
    },

    // ── WS Submissions ────────────────────────────────────────
    // Weasyl submissions table. Identical structure to FA submissions but with
    // different rating options: General/Mature/Explicit (Weasyl terminology)
    // instead of General/Mature/Adult (FA terminology). Sort and search follow
    // the same pattern using _wsSortState and _bindWSSearch/_bindWSTableSort.

    async renderWSSubmissions() {
        this._loading();
        try {
            // Fetch WS submissions with current sort column and direction
            const data = await API.getWSSubmissions({
                sort_by: this._wsSortState.field,
                order: this._wsSortState.order,
            });

            const html = `
                ${this._refreshIndicatorHtml()}
                <div class="page-header"><h2>Weasyl Submissions</h2></div>
                <div class="toolbar">
                    <input type="text" class="search-input" id="search-input" placeholder="Search titles and keywords...">
                    <select class="filter-select" id="filter-rating">
                        <option value="">All Ratings</option>
                        <option value="General">General</option>
                        <option value="Mature">Mature</option>
                        <option value="Explicit">Explicit</option>
                    </select>
                </div>
                <div id="table-container" class="table-scroll">
                    ${Components.wsSubmissionsTable(data.submissions)}
                </div>
            `;

            this._setContent(html);
            this._bindWSTableSort();   // Column header sort click handlers
            this._bindWSSearch(data.submissions);  // Client-side text/rating filter
            this._startAutoRefresh(() => this.renderWSSubmissions());
        } catch (err) {
            this._setContent(`<div class="empty-state"><h3>Error loading WS submissions</h3><p>${Utils.escapeHtml(err.message)}</p></div>`);
        }
    },

    // ── WS Submission Detail ──────────────────────────────────
    // Weasyl submission detail page. Simpler than FA and IB detail pages:
    // no comments section (WS API doesn't expose comment text) and no
    // faving-users list. Shows thumbnail, title, author, date, rating,
    // external link to Weasyl, stat counters, keywords, growth rate cards,
    // and a stats-over-time chart.

    async renderWSDetail(id) {
        this._loading();
        try {
            const data = await API.getWSSubmission(id);
            const sub = data.submission;

            const html = `
                ${this._refreshIndicatorHtml()}
                <a href="#/ws/submissions" class="back-link">&larr; Back to WS Submissions</a>
                <div class="detail-header">
                    ${sub.thumbnail_url ? `<img src="${Utils.escapeHtml(sub.thumbnail_url)}" class="detail-thumb">` : ''}
                    <div class="detail-info">
                        <h2>${Utils.escapeHtml(sub.title)}</h2>
                        <div class="detail-meta">by ${Utils.escapeHtml(sub.username)} &middot; ${Utils.formatDate(sub.posted_at)} &middot; ${Utils.escapeHtml(sub.rating || '')}</div>
                        <div class="detail-meta"><a href="${Utils.escapeHtml(sub.link || '#')}" target="_blank">View on Weasyl</a></div>
                        <div class="detail-stats">
                            <div class="detail-stat">${Utils.formatNumber(sub.views)} <span class="lbl">views</span></div>
                            <div class="detail-stat">${Utils.formatNumber(sub.favorites_count)} <span class="lbl">faves</span></div>
                            <div class="detail-stat">${Utils.formatNumber(sub.comments_count)} <span class="lbl">comments</span></div>
                        </div>
                        <div style="margin-top:8px">${Components.keywords(sub.keywords)}</div>
                    </div>
                </div>

                ${Components.growthRateCards(data.growth_rates)}

                ${Components.dateRangeBar(this._dateRange)}

                <div class="chart-container">
                    <h3>Stats Over Time</h3>
                    <div class="chart-wrap"><canvas id="chart-detail"></canvas></div>
                </div>
            `;

            this._setContent(html);

            // Render stats-over-time chart if snapshot data exists
            if (data.snapshots && data.snapshots.length > 0) {
                Charts.submissionLine('chart-detail', data.snapshots);
            }

            // Date range changes re-fetch only WS snapshots and redraw chart
            this._bindDateRange(async () => {
                const range = Utils.getDateRange(this._dateRange);
                const snaps = await API.getWSSnapshots(id, range);
                Charts.submissionLine('chart-detail', snaps.snapshots);
            });

            this._startAutoRefresh(() => this.renderWSDetail(id));
        } catch (err) {
            this._setContent(`<div class="empty-state"><h3>Error loading WS submission</h3><p>${Utils.escapeHtml(err.message)}</p></div>`);
        }
    },

    // ── WS Compare ────────────────────────────────────────────
    // Weasyl comparison page. Same chip/metric/chart pattern as the IB and FA
    // comparison pages. Selected IDs in _wsCompareIds, metric in _wsCompareMetric.

    async renderWSCompare() {
        this._loading();
        try {
            // Fetch all WS submissions sorted by views for chip population
            const data = await API.getWSSubmissions({ sort_by: 'views', order: 'desc' });
            const subs = data.submissions;

            // Build toggle chips for each submission with pre-selected state
            const chips = subs.map(s => `
                <label class="compare-chip ${this._wsCompareIds.has(s.submission_id) ? 'selected' : ''}" data-id="${s.submission_id}">
                    <input type="checkbox" ${this._wsCompareIds.has(s.submission_id) ? 'checked' : ''}>
                    ${Utils.escapeHtml(Utils.truncate(s.title, 25))}
                </label>
            `).join('');

            const html = `
                ${this._refreshIndicatorHtml()}
                <div class="page-header">
                    <h2>Compare WS Submissions</h2>
                    <div>
                        <select class="filter-select" id="compare-metric">
                            <option value="views" ${this._wsCompareMetric === 'views' ? 'selected' : ''}>Views</option>
                            <option value="favorites_count" ${this._wsCompareMetric === 'favorites_count' ? 'selected' : ''}>Favourites</option>
                            <option value="comments_count" ${this._wsCompareMetric === 'comments_count' ? 'selected' : ''}>Comments</option>
                        </select>
                    </div>
                </div>
                <p style="font-size:13px;color:var(--text-muted);margin-bottom:12px">Select 2-5 Weasyl submissions to compare their trends over time.</p>
                <div class="compare-select">${chips}</div>

                ${Components.dateRangeBar(this._dateRange)}

                <div class="chart-container" id="compare-chart-container" style="${this._wsCompareIds.size < 2 ? 'display:none' : ''}">
                    <h3>Comparison</h3>
                    <div class="chart-wrap"><canvas id="chart-compare"></canvas></div>
                </div>
                ${this._wsCompareIds.size < 2 ? '<div class="empty-state"><p>Select at least 2 submissions above to see their trends compared.</p></div>' : ''}
            `;

            this._setContent(html);

            // Chip click handlers: toggle selection in _wsCompareIds (max 5), re-render
            document.querySelectorAll('.compare-chip').forEach(chip => {
                chip.addEventListener('click', (e) => {
                    e.preventDefault();
                    const id = parseInt(chip.dataset.id);
                    if (this._wsCompareIds.has(id)) {
                        this._wsCompareIds.delete(id);
                    } else if (this._wsCompareIds.size < 5) {
                        this._wsCompareIds.add(id);
                    }
                    this.renderWSCompare();
                });
            });

            // Metric dropdown change reloads the comparison chart with the new metric
            const metricSelect = document.getElementById('compare-metric');
            if (metricSelect) {
                metricSelect.addEventListener('change', () => {
                    this._wsCompareMetric = metricSelect.value;
                    this._loadWSComparisonChart();
                });
            }

            // Date range changes also reload the comparison chart
            this._bindDateRange(() => this._loadWSComparisonChart());

            // If 2+ submissions already selected, load chart immediately
            if (this._wsCompareIds.size >= 2) {
                await this._loadWSComparisonChart();
            }

            this._startAutoRefresh(() => this.renderWSCompare());
        } catch (err) {
            this._setContent(`<div class="empty-state"><h3>Error</h3><p>${Utils.escapeHtml(err.message)}</p></div>`);
        }
    },

    // Fetches WS comparison data for selected submissions and renders the
    // multi-line comparison chart. Unhides the chart container if it was hidden.
    async _loadWSComparisonChart() {
        try {
            if (this._wsCompareIds.size < 2) return;  // Guard: need 2+ selections
            const range = Utils.getDateRange(this._dateRange);
            const data = await API.getWSComparison([...this._wsCompareIds], range);
            const container = document.getElementById('compare-chart-container');
            if (container) container.style.display = '';  // Unhide if previously hidden
            Charts.comparisonLine('chart-compare', data.series, data.titles, this._wsCompareMetric);
        } catch (e) {
            console.error('Failed to load WS comparison chart:', e);
        }
    },

    // ── SF Dashboard ──────────────────────────────────────────
    // SoFurry-specific dashboard. Same layout as WS dashboard.

    async renderSFDashboard() {
        this._loading();
        try {
            const [summary, agg] = await Promise.all([
                API.getSFSummary(),
                API.getSFAggregate(Utils.getDateRange(this._dateRange)),
            ]);

            const html = `
                ${this._refreshIndicatorHtml()}
                <div class="page-header">
                    <h2>SoFurry Dashboard</h2>
                    <button class="btn btn-secondary" onclick="API.exportSubmissions('sf')">Export CSV</button>
                </div>

                <div class="stats-grid">
                    ${Components.statCard('Total Submissions', summary.total_submissions)}
                    ${Components.statCard('Total Views', summary.total_views)}
                    ${Components.statCard('Total Likes', summary.total_favorites)}
                    ${Components.statCard('Total Comments', summary.total_comments)}
                </div>

                ${Components.growthRateCards(summary.growth_rates)}

                ${Components.dateRangeBar(this._dateRange)}

                <div class="chart-container">
                    <h3>Views Over Time (Aggregate)</h3>
                    <div class="chart-wrap"><canvas id="chart-agg-views"></canvas></div>
                </div>

                <div class="chart-row">
                    <div class="chart-container">
                        <h3>Top Viewed</h3>
                        <div class="chart-wrap"><canvas id="chart-top-views"></canvas></div>
                    </div>
                    <div class="chart-container">
                        <h3>Top Liked</h3>
                        <div class="chart-wrap"><canvas id="chart-top-faves"></canvas></div>
                    </div>
                </div>

                <div class="chart-row">
                    <div class="chart-container" style="grid-column: 1 / -1">
                        <h3>Fastest Growing (24h)</h3>
                        ${Components.sfTopList(summary.fastest_growing, 'views_gained')}
                    </div>
                </div>
            `;

            this._setContent(html);

            if (agg.snapshots && agg.snapshots.length > 0) {
                Charts.aggregateLine('chart-agg-views', agg.snapshots, ['views']);
            }
            if (summary.top_viewed && summary.top_viewed.length > 0) {
                Charts.topBar('chart-top-views', summary.top_viewed, 'views');
            }
            if (summary.top_faved && summary.top_faved.length > 0) {
                Charts.topBar('chart-top-faves', summary.top_faved, 'favorites_count');
            }

            this._bindDateRange(() => this.renderSFDashboard());
            this._startAutoRefresh(() => this.renderSFDashboard());
        } catch (err) {
            this._setContent(`<div class="empty-state"><h3>Error loading SF dashboard</h3><p>${Utils.escapeHtml(err.message)}</p></div>`);
        }
    },

    // ── SF Submissions ────────────────────────────────────────

    async renderSFSubmissions() {
        this._loading();
        try {
            const data = await API.getSFSubmissions({
                sort_by: this._sfSortState.field,
                order: this._sfSortState.order,
            });

            const html = `
                ${this._refreshIndicatorHtml()}
                <div class="page-header"><h2>SoFurry Submissions</h2></div>
                <div class="toolbar">
                    <input type="text" class="search-input" id="search-input" placeholder="Search titles and keywords...">
                    <select class="filter-select" id="filter-rating">
                        <option value="">All Ratings</option>
                        <option value="Clean">Clean</option>
                        <option value="Mature">Mature</option>
                        <option value="Adult">Adult</option>
                    </select>
                </div>
                <div id="table-container" class="table-scroll">
                    ${Components.sfSubmissionsTable(data.submissions)}
                </div>
            `;

            this._setContent(html);
            this._bindSFTableSort();
            this._bindSFSearch(data.submissions);
            this._startAutoRefresh(() => this.renderSFSubmissions());
        } catch (err) {
            this._setContent(`<div class="empty-state"><h3>Error loading SF submissions</h3><p>${Utils.escapeHtml(err.message)}</p></div>`);
        }
    },

    // ── SF Submission Detail ──────────────────────────────────

    async renderSFDetail(id) {
        this._loading();
        try {
            const data = await API.getSFSubmission(id);
            const sub = data.submission;

            const html = `
                ${this._refreshIndicatorHtml()}
                <a href="#/sf/submissions" class="back-link">&larr; Back to SF Submissions</a>
                <div class="detail-header">
                    ${sub.thumbnail_url ? `<img src="${Utils.escapeHtml(sub.thumbnail_url)}" class="detail-thumb">` : ''}
                    <div class="detail-info">
                        <h2>${Utils.escapeHtml(sub.title)}</h2>
                        <div class="detail-meta">by ${Utils.escapeHtml(sub.username)} &middot; ${Utils.escapeHtml(sub.posted_at || '')} &middot; ${Utils.escapeHtml(sub.rating || '')}</div>
                        <div class="detail-meta"><a href="${Utils.escapeHtml(sub.link || '#')}" target="_blank">View on SoFurry</a></div>
                        <div class="detail-stats">
                            <div class="detail-stat">${Utils.formatNumber(sub.views)} <span class="lbl">views</span></div>
                            <div class="detail-stat">${Utils.formatNumber(sub.favorites_count)} <span class="lbl">likes</span></div>
                            <div class="detail-stat">${Utils.formatNumber(sub.comments_count)} <span class="lbl">comments</span></div>
                        </div>
                        <div style="margin-top:8px">${Components.keywords(sub.keywords)}</div>
                    </div>
                </div>

                ${Components.growthRateCards(data.growth_rates)}

                ${Components.dateRangeBar(this._dateRange)}

                <div class="chart-container">
                    <h3>Stats Over Time</h3>
                    <div class="chart-wrap"><canvas id="chart-detail"></canvas></div>
                </div>
            `;

            this._setContent(html);

            if (data.snapshots && data.snapshots.length > 0) {
                Charts.submissionLine('chart-detail', data.snapshots);
            }

            this._bindDateRange(async () => {
                const range = Utils.getDateRange(this._dateRange);
                const snaps = await API.getSFSnapshots(id, range);
                Charts.submissionLine('chart-detail', snaps.snapshots);
            });

            this._startAutoRefresh(() => this.renderSFDetail(id));
        } catch (err) {
            this._setContent(`<div class="empty-state"><h3>Error loading SF submission</h3><p>${Utils.escapeHtml(err.message)}</p></div>`);
        }
    },

    // ── SF Compare ────────────────────────────────────────────

    async renderSFCompare() {
        this._loading();
        try {
            const data = await API.getSFSubmissions({ sort_by: 'views', order: 'desc' });
            const subs = data.submissions;

            const chips = subs.map(s => `
                <label class="compare-chip ${this._sfCompareIds.has(s.submission_id) ? 'selected' : ''}" data-id="${s.submission_id}">
                    <input type="checkbox" ${this._sfCompareIds.has(s.submission_id) ? 'checked' : ''}>
                    ${Utils.escapeHtml(Utils.truncate(s.title, 25))}
                </label>
            `).join('');

            const html = `
                ${this._refreshIndicatorHtml()}
                <div class="page-header">
                    <h2>Compare SF Submissions</h2>
                    <div>
                        <select class="filter-select" id="compare-metric">
                            <option value="views" ${this._sfCompareMetric === 'views' ? 'selected' : ''}>Views</option>
                            <option value="favorites_count" ${this._sfCompareMetric === 'favorites_count' ? 'selected' : ''}>Likes</option>
                            <option value="comments_count" ${this._sfCompareMetric === 'comments_count' ? 'selected' : ''}>Comments</option>
                        </select>
                    </div>
                </div>
                <p style="font-size:13px;color:var(--text-muted);margin-bottom:12px">Select 2-5 SoFurry submissions to compare their trends over time.</p>
                <div class="compare-select">${chips}</div>

                ${Components.dateRangeBar(this._dateRange)}

                <div class="chart-container" id="compare-chart-container" style="${this._sfCompareIds.size < 2 ? 'display:none' : ''}">
                    <h3>Comparison</h3>
                    <div class="chart-wrap"><canvas id="chart-compare"></canvas></div>
                </div>
                ${this._sfCompareIds.size < 2 ? '<div class="empty-state"><p>Select at least 2 submissions above to see their trends compared.</p></div>' : ''}
            `;

            this._setContent(html);

            document.querySelectorAll('.compare-chip').forEach(chip => {
                chip.addEventListener('click', (e) => {
                    e.preventDefault();
                    const id = chip.dataset.id;
                    if (this._sfCompareIds.has(id)) {
                        this._sfCompareIds.delete(id);
                    } else if (this._sfCompareIds.size < 5) {
                        this._sfCompareIds.add(id);
                    }
                    this.renderSFCompare();
                });
            });

            const metricSelect = document.getElementById('compare-metric');
            if (metricSelect) {
                metricSelect.addEventListener('change', () => {
                    this._sfCompareMetric = metricSelect.value;
                    this._loadSFComparisonChart();
                });
            }

            this._bindDateRange(() => this._loadSFComparisonChart());

            if (this._sfCompareIds.size >= 2) {
                await this._loadSFComparisonChart();
            }

            this._startAutoRefresh(() => this.renderSFCompare());
        } catch (err) {
            this._setContent(`<div class="empty-state"><h3>Error</h3><p>${Utils.escapeHtml(err.message)}</p></div>`);
        }
    },

    async _loadSFComparisonChart() {
        try {
            if (this._sfCompareIds.size < 2) return;
            const range = Utils.getDateRange(this._dateRange);
            const data = await API.getSFComparison([...this._sfCompareIds], range);
            const container = document.getElementById('compare-chart-container');
            if (container) container.style.display = '';
            Charts.comparisonLine('chart-compare', data.series, data.titles, this._sfCompareMetric);
        } catch (e) {
            console.error('Failed to load SF comparison chart:', e);
        }
    },

    // ── Groups ────────────────────────────────────────────────
    // Submission groups management page. Groups are cross-platform collections
    // that let users organise related submissions from any platform (IB, FA, WS, SF)
    // into named groups for combined tracking. New groups are created via a
    // browser prompt() dialog asking for name and optional description.

    async renderGroups() {
        this._loading();
        try {
            const data = await API.getGroups();
            const groups = data.groups || [];

            const html = `
                <div class="page-header">
                    <h2>Submission Groups</h2>
                    <button class="btn btn-primary" id="create-group-btn">Create Group</button>
                </div>
                <p style="font-size:13px;color:var(--text-muted);margin-bottom:16px">Organise submissions from any platform into groups for combined tracking.</p>
                <div class="stats-grid">
                    ${Components.groupsList(groups)}
                </div>
            `;

            this._setContent(html);

            document.getElementById('create-group-btn').addEventListener('click', async () => {
                const name = prompt('Group name:');
                if (!name) return;
                const description = prompt('Description (optional):') || '';
                try {
                    await API.createGroup({ name, description });
                    this.renderGroups();
                } catch (err) {
                    alert('Failed: ' + err.message);
                }
            });
        } catch (err) {
            this._setContent(`<div class="empty-state"><h3>Error</h3><p>${Utils.escapeHtml(err.message)}</p></div>`);
        }
    },

    // Group detail page. Shows the group name, description, aggregated stats
    // (total views/faves/comments across all member submissions), and a member
    // table with platform badges (IB/FA/WS), title links to individual detail
    // pages, stat columns, and per-row remove buttons. "Add Submission" uses
    // prompt() dialogs for platform and submission ID. "Delete Group" confirms
    // then navigates back to the groups list.
    async renderGroupDetail(groupId) {
        this._loading();
        try {
            // Fetch group list (to find this group's metadata) and stats in parallel
            const [groupData, statsData] = await Promise.all([
                API.getGroups(),
                API.getGroupStats(groupId),
            ]);
            // Locate the specific group by ID from the full groups list
            const group = (groupData.groups || []).find(g => g.group_id === groupId);
            if (!group) { this._setContent('<div class="empty-state"><h3>Group not found</h3></div>'); return; }

            const stats = statsData;
            const members = stats.members || [];

            // Build table rows for each member: platform badge, linked title
            // (routing to the correct platform detail page), stats, and remove button
            const memberRows = members.map(m => {
                // Determine platform badge colour and the correct hash route prefix
                const badgeMap = { fa: '<span class="platform-badge fa">FA</span>', ws: '<span class="platform-badge ws">WS</span>', sf: '<span class="platform-badge sf">SF</span>', ib: '<span class="platform-badge ib">IB</span>' };
                const badge = badgeMap[m.platform] || badgeMap.ib;
                const prefixMap = { fa: '/fa/submission/', ws: '/ws/submission/', sf: '/sf/submission/', ib: '/submission/' };
                const prefix = prefixMap[m.platform] || prefixMap.ib;
                return `
                    <tr>
                        <td>${badge}</td>
                        <td><a href="#${prefix}${m.submission_id}">${Utils.escapeHtml(Utils.truncate(m.title || '#' + m.submission_id, 40))}</a></td>
                        <td>${Utils.formatNumber(m.views || 0)}</td>
                        <td>${Utils.formatNumber(m.favorites_count || 0)}</td>
                        <td>${Utils.formatNumber(m.comments_count || 0)}</td>
                        <td><button class="btn btn-danger" style="font-size:11px;padding:2px 8px" onclick="App.removeGroupMember(${groupId},'${m.platform}','${m.submission_id}')">Remove</button></td>
                    </tr>
                `;
            }).join('');

            const html = `
                <a href="#/groups" class="back-link">&larr; Back to Groups</a>
                <div class="page-header">
                    <h2>${Utils.escapeHtml(group.name)}</h2>
                    <div style="display:flex;gap:8px">
                        <button class="btn btn-primary" id="add-member-btn">Add Submission</button>
                        <button class="btn btn-danger" id="delete-group-btn">Delete Group</button>
                    </div>
                </div>
                ${group.description ? `<p style="color:var(--text-muted);font-size:13px;margin-bottom:16px">${Utils.escapeHtml(group.description)}</p>` : ''}

                <div class="stats-grid">
                    ${Components.statCard('Total Views', stats.total_views || 0)}
                    ${Components.statCard('Total Favorites', stats.total_favorites || 0)}
                    ${Components.statCard('Total Comments', stats.total_comments || 0)}
                    ${Components.statCard('Members', members.length)}
                </div>

                <table class="data-table">
                    <thead><tr><th style="width:40px"></th><th>Title</th><th>Views</th><th>Faves</th><th>Comments</th><th style="width:80px"></th></tr></thead>
                    <tbody>${memberRows || '<tr><td colspan="6" style="text-align:center;color:var(--text-muted)">No members yet</td></tr>'}</tbody>
                </table>
            `;

            this._setContent(html);

            // "Add Submission" button: prompt for platform (ib/fa/ws/sf) then
            // submission ID, add to group via API, and re-render
            document.getElementById('add-member-btn').addEventListener('click', async () => {
                const platform = prompt('Platform (ib, fa, ws, or sf):');
                if (!platform || !['ib', 'fa', 'ws', 'sf'].includes(platform)) { alert('Invalid platform'); return; }
                const subId = prompt('Submission ID:');
                if (!subId) { alert('Invalid ID'); return; }
                if (platform !== 'sf' && isNaN(subId)) { alert('Invalid ID'); return; }
                try {
                    await API.addGroupMember(groupId, { platform, submission_id: platform === 'sf' ? subId.trim() : parseInt(subId) });
                    this.renderGroupDetail(groupId);
                } catch (err) {
                    alert('Failed: ' + err.message);
                }
            });

            // "Delete Group" button: confirmation dialog, then delete and navigate
            // back to the groups list page
            document.getElementById('delete-group-btn').addEventListener('click', async () => {
                if (!confirm('Delete this group? This cannot be undone.')) return;
                try {
                    await API.deleteGroup(groupId);
                    this.navigate('/groups');
                } catch (err) {
                    alert('Failed: ' + err.message);
                }
            });
        } catch (err) {
            this._setContent(`<div class="empty-state"><h3>Error</h3><p>${Utils.escapeHtml(err.message)}</p></div>`);
        }
    },

    // Confirms and removes a single submission from a group, then re-renders
    // the group detail page. Called via inline onclick on each member row's
    // remove button.
    async removeGroupMember(groupId, platform, subId) {
        if (!confirm('Remove this submission from the group?')) return;
        try {
            await API.removeGroupMember(groupId, platform, subId);
            this.renderGroupDetail(groupId);
        } catch (err) {
            alert('Failed: ' + err.message);
        }
    },

    // ── Cross-Platform ────────────────────────────────────────
    // Cross-platform links page. Links connect the same submission across
    // platforms (e.g. IB #12345 + FA #67890) so their stats can be viewed
    // together. Shows auto-suggested links (based on title matching) and
    // existing links. New links are created via a text input prompt using
    // the format "platform:id, platform:id" (e.g. "ib:12345, fa:67890").

    async renderCrossPlatform() {
        this._loading();
        try {
            // Fetch existing links and auto-suggestions in parallel;
            // suggestions endpoint failure is non-fatal (falls back to empty)
            const [linksData, suggestionsData] = await Promise.all([
                API.getLinks(),
                API.getLinkSuggestions().catch(() => ({ suggestions: [] })),
            ]);

            const html = `
                <div class="page-header">
                    <h2>Cross-Platform Links</h2>
                    <button class="btn btn-primary" id="create-link-btn">Create Link</button>
                </div>
                <p style="font-size:13px;color:var(--text-muted);margin-bottom:16px">Link the same submission across platforms to view combined analytics.</p>

                ${(suggestionsData.suggestions || []).length > 0 ? `
                <div class="chart-container">
                    <h3>Suggested Links</h3>
                    ${Components.linkSuggestions(suggestionsData.suggestions)}
                </div>` : ''}

                <div class="stats-grid">
                    ${Components.linkCards(linksData.links || [])}
                </div>

                <div id="link-stats-container"></div>
            `;

            this._setContent(html);

            // "Create Link" button: prompt for comma-separated platform:id pairs,
            // parse them into member objects, create the link via API, then re-render
            document.getElementById('create-link-btn').addEventListener('click', async () => {
                const input = prompt('Enter members as: platform:id, platform:id\nExample: ib:12345, fa:67890, ws:11111, sf:abc123');
                if (!input) return;
                try {
                    // Parse "ib:12345, fa:67890" into [{platform:"ib", submission_id:12345}, ...]
                    // SF uses alphanumeric IDs so only parseInt for non-SF platforms
                    const members = input.split(',').map(s => {
                        const [platform, id] = s.trim().split(':');
                        const p = platform.trim();
                        return { platform: p, submission_id: p === 'sf' ? id.trim() : parseInt(id.trim()) };
                    });
                    await API.createLink({ members });
                    this.renderCrossPlatform();
                } catch (err) {
                    alert('Failed: ' + err.message);
                }
            });
        } catch (err) {
            this._setContent(`<div class="empty-state"><h3>Error</h3><p>${Utils.escapeHtml(err.message)}</p></div>`);
        }
    },

    // Loads combined stats and a snapshot chart for a cross-platform link.
    // Fetches link stats and snapshots in parallel, then renders them into
    // the #link-stats-container div on the cross-platform page. Shows
    // combined views/faves/comments stat cards and an aggregate line chart.
    async viewLinkStats(linkId) {
        try {
            // Parallel fetch: aggregated stats and time-series snapshots
            const [stats, snapshots] = await Promise.all([
                API.getLinkStats(linkId),
                API.getLinkSnapshots(linkId),
            ]);
            const container = document.getElementById('link-stats-container');
            if (!container) return;

            container.innerHTML = `
                <div class="chart-container" style="margin-top:16px">
                    <h3>Combined Stats for Link #${linkId}</h3>
                    <div class="stats-grid" style="margin-bottom:12px">
                        ${Components.statCard('Combined Views', stats.total_views || 0)}
                        ${Components.statCard('Combined Faves', stats.total_favorites || 0)}
                        ${Components.statCard('Combined Comments', stats.total_comments || 0)}
                    </div>
                    ${(snapshots.snapshots || []).length > 0 ? '<div class="chart-wrap"><canvas id="chart-link-combined"></canvas></div>' : '<p style="color:var(--text-muted)">No snapshot data yet</p>'}
                </div>
            `;

            if ((snapshots.snapshots || []).length > 0) {
                Charts.aggregateLine('chart-link-combined', snapshots.snapshots, ['views', 'favorites_count', 'comments_count']);
            }
        } catch (err) {
            alert('Failed to load link stats: ' + err.message);
        }
    },

    // Confirms and deletes a cross-platform link, then re-renders the page.
    // Called from link card delete buttons.
    async deleteLink(linkId) {
        if (!confirm('Remove this cross-platform link?')) return;
        try {
            await API.deleteLink(linkId);
            this.renderCrossPlatform();
        } catch (err) {
            alert('Failed: ' + err.message);
        }
    },

    // Creates a cross-platform link from an auto-suggestion. Called when the
    // user clicks "Link" on a suggested match. The items array contains the
    // pre-built platform/submission_id member objects from the suggestion.
    async createLinkFromSuggestion(items) {
        try {
            await API.createLink({ members: items });
            this.renderCrossPlatform();
        } catch (err) {
            alert('Failed: ' + err.message);
        }
    },

    // ── Settings ──────────────────────────────────────────────
    // Massive settings page. Fetches 12 API endpoints in parallel for all state.
    // Sections: IB credentials, app preferences (tray/startup/notifications/poll
    // intervals), notification filters, auto-update, Telegram integration, FA
    // connection (cookie_a/cookie_b), WS connection (API key), poll logs for all
    // platforms. After HTML render, attaches event handlers for all interactive
    // elements: save/logout/poll/resync buttons, toggle switches, select dropdowns,
    // connect/disconnect buttons, threshold inputs, and apply-update button.

    async renderSettings() {
        this._loading();
        try {
            // Parallel-fetch all 15 settings endpoints; FA/WS/SF use .catch() fallbacks
            const [status, pollLog, creds, prefs, telegram, faAuth, faStatus, faPollLog, wsAuth, wsStatus, wsPollLog, sfAuth, sfStatus, sfPollLog, updateInfo] = await Promise.all([
                API.getStatus(),
                API.getPollLog(20),
                API.getCredentials(),
                API.getPreferences(),
                API.getTelegram(),
                API.getFAAuthStatus().catch(() => ({ has_cookies: false })),
                API.getFAStatus().catch(() => ({})),
                API.getFAPollLog(20).catch(() => ({ polls: [] })),
                API.getWSAuthStatus().catch(() => ({ has_key: false })),
                API.getWSStatus().catch(() => ({})),
                API.getWSPollLog(20).catch(() => ({ polls: [] })),
                API.getSFAuthStatus().catch(() => ({ has_credentials: false })),
                API.getSFStatus().catch(() => ({})),
                API.getSFPollLog(20).catch(() => ({ polls: [] })),
                API.checkUpdate().catch(() => ({ available: false, current: '?', latest: '?' })),
            ]);

            const lastPoll = status.last_poll;

            const html = `
                <div class="page-header">
                    <h2>Settings</h2>
                    <div style="display:flex;gap:8px">
                        <button class="btn btn-primary" id="poll-now-btn">Poll Now</button>
                        <button class="btn btn-secondary" id="full-resync-btn" title="Re-scrape all faves and comments">Full Resync</button>
                        <button class="btn btn-secondary" id="clear-session-btn" title="Clear cached API session">Clear Session</button>
                    </div>
                </div>

                <div class="settings-section">
                    <h3>Inkbunny Credentials</h3>
                    <div class="settings-row" style="flex-direction:column;align-items:stretch;gap:8px">
                        <label style="font-size:13px;color:var(--text-muted)">Username</label>
                        <input type="text" id="cred-username" class="search-input" value="${Utils.escapeHtml(creds.username || '')}" placeholder="Inkbunny username" style="max-width:300px">
                    </div>
                    <div class="settings-row" style="flex-direction:column;align-items:stretch;gap:8px;margin-top:8px">
                        <label style="font-size:13px;color:var(--text-muted)">Password ${creds.has_password ? '(saved — leave blank to keep)' : ''}</label>
                        <input type="password" id="cred-password" class="search-input" placeholder="${creds.has_password ? '********' : 'Inkbunny password'}" style="max-width:300px">
                    </div>
                    <div style="margin-top:12px;display:flex;align-items:center;gap:12px">
                        <button class="btn btn-primary" id="save-creds-btn">Save Credentials</button>
                        <button class="btn btn-danger" id="settings-logout-btn">Sign Out</button>
                        <span id="creds-msg" style="font-size:13px"></span>
                    </div>
                </div>

                <div class="settings-section">
                    <h3>Application</h3>
                    <div class="settings-row">
                        <div>
                            <span class="settings-label">Minimize to system tray on close</span>
                            <div style="font-size:11px;color:var(--text-muted);margin-top:2px">Hide to tray instead of quitting — poller keeps running</div>
                        </div>
                        <label class="toggle-switch">
                            <input type="checkbox" id="pref-tray" ${prefs.minimize_to_tray ? 'checked' : ''}>
                            <span class="toggle-slider"></span>
                        </label>
                    </div>
                    <div class="settings-row">
                        <div>
                            <span class="settings-label">Start with Windows</span>
                            <div style="font-size:11px;color:var(--text-muted);margin-top:2px">Launch automatically when you log in</div>
                        </div>
                        <label class="toggle-switch">
                            <input type="checkbox" id="pref-startup" ${prefs.run_on_startup ? 'checked' : ''}>
                            <span class="toggle-slider"></span>
                        </label>
                    </div>
                    <div class="settings-row">
                        <div>
                            <span class="settings-label">Desktop notifications</span>
                            <div style="font-size:11px;color:var(--text-muted);margin-top:2px">Toast notifications when new faves or comments are detected</div>
                        </div>
                        <label class="toggle-switch">
                            <input type="checkbox" id="pref-notifications" ${prefs.notifications_enabled ? 'checked' : ''}>
                            <span class="toggle-slider"></span>
                        </label>
                    </div>
                    <div class="settings-row">
                        <div>
                            <span class="settings-label">Watcher notifications</span>
                            <div style="font-size:11px;color:var(--text-muted);margin-top:2px">Toast + Telegram alerts for new watchers</div>
                        </div>
                        <label class="toggle-switch">
                            <input type="checkbox" id="pref-watcher-notif" ${prefs.watcher_notifications_enabled !== false ? 'checked' : ''}>
                            <span class="toggle-slider"></span>
                        </label>
                    </div>
                    <div class="settings-row">
                        <div>
                            <span class="settings-label">IB poll interval</span>
                            <div style="font-size:11px;color:var(--text-muted);margin-top:2px">How often to check for new Inkbunny data</div>
                        </div>
                        <select class="filter-select" id="pref-poll-interval" style="width:auto">
                            <option value="15" ${prefs.poll_interval_minutes === 15 ? 'selected' : ''}>15 min</option>
                            <option value="30" ${prefs.poll_interval_minutes === 30 ? 'selected' : ''}>30 min</option>
                            <option value="60" ${prefs.poll_interval_minutes === 60 || !prefs.poll_interval_minutes ? 'selected' : ''}>1 hour</option>
                            <option value="120" ${prefs.poll_interval_minutes === 120 ? 'selected' : ''}>2 hours</option>
                            <option value="240" ${prefs.poll_interval_minutes === 240 ? 'selected' : ''}>4 hours</option>
                        </select>
                    </div>
                    <div class="settings-row">
                        <div>
                            <span class="settings-label">FA poll interval</span>
                            <div style="font-size:11px;color:var(--text-muted);margin-top:2px">How often to check for new FurAffinity data</div>
                        </div>
                        <select class="filter-select" id="pref-fa-poll-interval" style="width:auto">
                            <option value="15" ${prefs.fa_poll_interval_minutes === 15 ? 'selected' : ''}>15 min</option>
                            <option value="30" ${prefs.fa_poll_interval_minutes === 30 ? 'selected' : ''}>30 min</option>
                            <option value="60" ${prefs.fa_poll_interval_minutes === 60 || !prefs.fa_poll_interval_minutes ? 'selected' : ''}>1 hour</option>
                            <option value="120" ${prefs.fa_poll_interval_minutes === 120 ? 'selected' : ''}>2 hours</option>
                            <option value="240" ${prefs.fa_poll_interval_minutes === 240 ? 'selected' : ''}>4 hours</option>
                        </select>
                    </div>
                    <div class="settings-row">
                        <div>
                            <span class="settings-label">WS poll interval</span>
                            <div style="font-size:11px;color:var(--text-muted);margin-top:2px">How often to check for new Weasyl data</div>
                        </div>
                        <select class="filter-select" id="pref-ws-poll-interval" style="width:auto">
                            <option value="15" ${prefs.ws_poll_interval_minutes === 15 ? 'selected' : ''}>15 min</option>
                            <option value="30" ${prefs.ws_poll_interval_minutes === 30 ? 'selected' : ''}>30 min</option>
                            <option value="60" ${prefs.ws_poll_interval_minutes === 60 || !prefs.ws_poll_interval_minutes ? 'selected' : ''}>1 hour</option>
                            <option value="120" ${prefs.ws_poll_interval_minutes === 120 ? 'selected' : ''}>2 hours</option>
                            <option value="240" ${prefs.ws_poll_interval_minutes === 240 ? 'selected' : ''}>4 hours</option>
                        </select>
                    </div>
                    <div class="settings-row">
                        <div>
                            <span class="settings-label">SF poll interval</span>
                            <div style="font-size:11px;color:var(--text-muted);margin-top:2px">How often to check for new SoFurry data</div>
                        </div>
                        <select class="filter-select" id="pref-sf-poll-interval" style="width:auto">
                            <option value="15" ${prefs.sf_poll_interval_minutes === 15 ? 'selected' : ''}>15 min</option>
                            <option value="30" ${prefs.sf_poll_interval_minutes === 30 ? 'selected' : ''}>30 min</option>
                            <option value="60" ${prefs.sf_poll_interval_minutes === 60 || !prefs.sf_poll_interval_minutes ? 'selected' : ''}>1 hour</option>
                            <option value="120" ${prefs.sf_poll_interval_minutes === 120 ? 'selected' : ''}>2 hours</option>
                            <option value="240" ${prefs.sf_poll_interval_minutes === 240 ? 'selected' : ''}>4 hours</option>
                        </select>
                    </div>
                </div>

                <div class="settings-section">
                    <h3>Notification Filters</h3>
                    <div class="settings-row">
                        <div>
                            <span class="settings-label">IB: Comments only</span>
                            <div style="font-size:11px;color:var(--text-muted);margin-top:2px">Only notify for new comments, not faves</div>
                        </div>
                        <label class="toggle-switch">
                            <input type="checkbox" id="pref-notif-comments-only" ${prefs.notification_comments_only ? 'checked' : ''}>
                            <span class="toggle-slider"></span>
                        </label>
                    </div>
                    <div class="settings-row">
                        <div>
                            <span class="settings-label">FA: Comments only</span>
                            <div style="font-size:11px;color:var(--text-muted);margin-top:2px">Only notify for new FA comments</div>
                        </div>
                        <label class="toggle-switch">
                            <input type="checkbox" id="pref-fa-notif-comments-only" ${prefs.fa_notification_comments_only ? 'checked' : ''}>
                            <span class="toggle-slider"></span>
                        </label>
                    </div>
                    <div class="settings-row">
                        <div>
                            <span class="settings-label">WS: Comments only</span>
                            <div style="font-size:11px;color:var(--text-muted);margin-top:2px">Only notify for Weasyl comment changes</div>
                        </div>
                        <label class="toggle-switch">
                            <input type="checkbox" id="pref-ws-notif-comments-only" ${prefs.ws_notification_comments_only ? 'checked' : ''}>
                            <span class="toggle-slider"></span>
                        </label>
                    </div>
                    <div class="settings-row">
                        <div>
                            <span class="settings-label">SF: Comments only</span>
                            <div style="font-size:11px;color:var(--text-muted);margin-top:2px">Only notify for SoFurry comment changes</div>
                        </div>
                        <label class="toggle-switch">
                            <input type="checkbox" id="pref-sf-notif-comments-only" ${prefs.sf_notification_comments_only ? 'checked' : ''}>
                            <span class="toggle-slider"></span>
                        </label>
                    </div>
                    <div class="settings-row">
                        <div>
                            <span class="settings-label">Min views delta</span>
                            <div style="font-size:11px;color:var(--text-muted);margin-top:2px">Minimum view increase to trigger notification</div>
                        </div>
                        <input type="number" class="search-input" id="pref-min-views-delta" value="${prefs.notification_min_views_delta || 0}" min="0" style="width:80px;text-align:center">
                    </div>
                    <div class="settings-row">
                        <div>
                            <span class="settings-label">Min faves delta</span>
                            <div style="font-size:11px;color:var(--text-muted);margin-top:2px">Minimum fave increase to trigger notification</div>
                        </div>
                        <input type="number" class="search-input" id="pref-min-faves-delta" value="${prefs.notification_min_faves_delta || 0}" min="0" style="width:80px;text-align:center">
                    </div>
                </div>

                ${updateInfo.available ? `
                <div class="settings-section" style="border-color:var(--success)">
                    <h3>Update Available</h3>
                    <div class="settings-row">
                        <div>
                            <span class="settings-label">Current: ${Utils.escapeHtml(updateInfo.current)} &rarr; Latest: ${Utils.escapeHtml(updateInfo.latest)}</span>
                        </div>
                        <button class="btn btn-primary" id="apply-update-btn">Update Now</button>
                    </div>
                </div>` : `
                <div class="settings-section">
                    <h3>Version</h3>
                    <div class="settings-row">
                        <span class="settings-label">Version ${Utils.escapeHtml(updateInfo.current)}</span>
                        <span class="settings-value" style="color:var(--success)">Up to date</span>
                    </div>
                </div>`}

                <div class="settings-section">
                    <h3>Telegram Notifications</h3>
                    ${telegram.connected ? `
                    <div class="settings-row">
                        <div>
                            <span class="settings-label">Status</span>
                        </div>
                        <span class="telegram-status connected">Connected</span>
                    </div>
                    <div class="settings-row">
                        <div>
                            <span class="settings-label">Send Telegram notifications</span>
                            <div style="font-size:11px;color:var(--text-muted);margin-top:2px">Receive fave/comment alerts via Telegram</div>
                        </div>
                        <label class="toggle-switch">
                            <input type="checkbox" id="pref-telegram" ${telegram.enabled ? 'checked' : ''}>
                            <span class="toggle-slider"></span>
                        </label>
                    </div>
                    <div style="margin-top:12px;display:flex;align-items:center;gap:8px">
                        <button class="btn btn-secondary" id="telegram-test-btn">Test</button>
                        <button class="btn btn-danger" id="telegram-disconnect-btn">Disconnect</button>
                        <span id="telegram-msg" style="font-size:13px"></span>
                    </div>
                    ` : `
                    <p class="telegram-instructions">Paste your bot token (from <a href="https://t.me/BotFather" target="_blank" style="color:var(--accent)">@BotFather</a>), send <code>/start</code> to your bot on Telegram, then click Connect.</p>
                    <div style="margin-top:12px;display:flex;gap:8px;align-items:center;flex-wrap:wrap">
                        <input type="text" id="telegram-token" class="search-input" placeholder="123456:ABC-DEF..." style="flex:1;min-width:200px">
                        <button class="btn btn-primary" id="telegram-connect-btn">Connect</button>
                    </div>
                    <div id="telegram-msg" style="font-size:13px;margin-top:8px"></div>
                    `}
                </div>

                <div class="settings-section">
                    <h3>FurAffinity</h3>
                    ${faAuth.has_cookies ? `
                    <div class="settings-row">
                        <div>
                            <span class="settings-label">Status</span>
                        </div>
                        <span class="telegram-status connected">Connected as ${Utils.escapeHtml(faAuth.username || '')}</span>
                    </div>
                    <div class="settings-row" style="margin-top:8px">
                        <div>
                            <span class="settings-label">FA desktop notifications</span>
                            <div style="font-size:11px;color:var(--text-muted);margin-top:2px">Toast + Telegram alerts for FA comments</div>
                        </div>
                        <label class="toggle-switch">
                            <input type="checkbox" id="pref-fa-notifications" ${prefs.fa_notifications_enabled ? 'checked' : ''}>
                            <span class="toggle-slider"></span>
                        </label>
                    </div>
                    <div class="settings-row" style="margin-top:8px">
                        <div>
                            <span class="settings-label">FA watcher notifications</span>
                            <div style="font-size:11px;color:var(--text-muted);margin-top:2px">Toast + Telegram alerts for new FA watchers</div>
                        </div>
                        <label class="toggle-switch">
                            <input type="checkbox" id="pref-fa-watcher-notif" ${prefs.fa_watcher_notifications_enabled !== false ? 'checked' : ''}>
                            <span class="toggle-slider"></span>
                        </label>
                    </div>
                    <div style="margin-top:12px;display:flex;align-items:center;gap:8px;flex-wrap:wrap">
                        <button class="btn btn-primary" id="fa-poll-btn">FA Poll Now</button>
                        <button class="btn btn-secondary" id="fa-resync-btn">FA Full Resync</button>
                        <button class="btn btn-danger" id="fa-disconnect-btn">Disconnect</button>
                        <span id="fa-msg" style="font-size:13px"></span>
                    </div>
                    ` : `
                    <p style="color:var(--text-muted);font-size:13px;margin-bottom:12px">Connect your FurAffinity account using browser cookies. Open FA in your browser, find your <code style="background:var(--bg-tertiary);padding:2px 4px;border-radius:3px">a</code> and <code style="background:var(--bg-tertiary);padding:2px 4px;border-radius:3px">b</code> cookie values.</p>
                    <div style="display:flex;flex-direction:column;gap:8px;max-width:400px">
                        <input type="text" id="fa-username" class="search-input" placeholder="FA username">
                        <input type="text" id="fa-cookie-a" class="search-input" placeholder="Cookie a value">
                        <input type="text" id="fa-cookie-b" class="search-input" placeholder="Cookie b value">
                    </div>
                    <div style="margin-top:12px;display:flex;align-items:center;gap:8px">
                        <button class="btn btn-primary" id="fa-connect-btn">Connect</button>
                        <span id="fa-msg" style="font-size:13px"></span>
                    </div>
                    `}
                </div>

                <div class="settings-section">
                    <h3>Weasyl</h3>
                    ${wsAuth.has_key ? `
                    <div class="settings-row">
                        <div>
                            <span class="settings-label">Status</span>
                        </div>
                        <span class="telegram-status connected">Connected as ${Utils.escapeHtml(wsAuth.username || '')}</span>
                    </div>
                    <div class="settings-row" style="margin-top:8px">
                        <div>
                            <span class="settings-label">WS desktop notifications</span>
                            <div style="font-size:11px;color:var(--text-muted);margin-top:2px">Toast + Telegram alerts for WS activity</div>
                        </div>
                        <label class="toggle-switch">
                            <input type="checkbox" id="pref-ws-notifications" ${prefs.ws_notifications_enabled ? 'checked' : ''}>
                            <span class="toggle-slider"></span>
                        </label>
                    </div>
                    <div style="margin-top:12px;display:flex;align-items:center;gap:8px;flex-wrap:wrap">
                        <button class="btn btn-primary" id="ws-poll-btn">WS Poll Now</button>
                        <button class="btn btn-secondary" id="ws-resync-btn">WS Full Resync</button>
                        <button class="btn btn-danger" id="ws-disconnect-btn">Disconnect</button>
                        <span id="ws-msg" style="font-size:13px"></span>
                    </div>
                    ` : `
                    <p style="color:var(--text-muted);font-size:13px;margin-bottom:12px">Connect your Weasyl account using an API key. Get your key from <a href="https://www.weasyl.com/control/apikeys" target="_blank" style="color:var(--accent)">Weasyl API Keys</a>.</p>
                    <div style="display:flex;gap:8px;align-items:center;max-width:400px">
                        <input type="text" id="ws-api-key" class="search-input" placeholder="Weasyl API key" style="flex:1">
                        <button class="btn btn-primary" id="ws-connect-btn">Connect</button>
                    </div>
                    <div id="ws-msg" style="font-size:13px;margin-top:8px"></div>
                    `}
                </div>

                <div class="settings-section">
                    <h3>SoFurry</h3>
                    ${sfAuth.has_credentials ? `
                    <div class="settings-row">
                        <div>
                            <span class="settings-label">Status</span>
                        </div>
                        <span class="telegram-status connected">Connected as ${Utils.escapeHtml(sfAuth.username || '')}</span>
                    </div>
                    <div class="settings-row" style="margin-top:8px">
                        <div>
                            <span class="settings-label">SF desktop notifications</span>
                            <div style="font-size:11px;color:var(--text-muted);margin-top:2px">Toast + Telegram alerts for SF activity</div>
                        </div>
                        <label class="toggle-switch">
                            <input type="checkbox" id="pref-sf-notifications" ${prefs.sf_notifications_enabled ? 'checked' : ''}>
                            <span class="toggle-slider"></span>
                        </label>
                    </div>
                    <div style="margin-top:12px;display:flex;align-items:center;gap:8px;flex-wrap:wrap">
                        <button class="btn btn-primary" id="sf-poll-btn">SF Poll Now</button>
                        <button class="btn btn-secondary" id="sf-resync-btn">SF Full Resync</button>
                        <button class="btn btn-danger" id="sf-disconnect-btn">Disconnect</button>
                        <span id="sf-msg" style="font-size:13px"></span>
                    </div>
                    ` : `
                    <p style="color:var(--text-muted);font-size:13px;margin-bottom:12px">Connect your SoFurry account using your <strong>email address</strong>, password, and <strong>display name</strong> (your profile name, e.g. "KnaughtyKat").</p>
                    <div style="display:flex;flex-direction:column;gap:8px;max-width:400px">
                        <input type="email" id="sf-username" class="search-input" placeholder="SoFurry email address">
                        <input type="password" id="sf-password" class="search-input" placeholder="SoFurry password">
                        <input type="text" id="sf-display-name" class="search-input" placeholder="Display name (profile name)">
                        <input type="text" id="sf-totp" class="search-input" placeholder="2FA code (if enabled)" maxlength="6" inputmode="numeric" autocomplete="one-time-code" style="max-width:160px">
                    </div>
                    <div style="margin-top:12px;display:flex;align-items:center;gap:8px">
                        <button class="btn btn-primary" id="sf-connect-btn">Connect</button>
                        <span id="sf-msg" style="font-size:13px"></span>
                    </div>
                    `}
                </div>

                <div class="settings-section">
                    <h3>Inkbunny Polling Status</h3>
                    <div class="settings-row">
                        <span class="settings-label">Submissions tracked</span>
                        <span class="settings-value">${status.total_submissions}</span>
                    </div>
                    <div class="settings-row">
                        <span class="settings-label">Snapshots stored</span>
                        <span class="settings-value">${Utils.formatNumber(status.total_snapshots)}</span>
                    </div>
                    <div class="settings-row">
                        <span class="settings-label">Last poll</span>
                        <span class="settings-value">${lastPoll ? Utils.formatDateTime(lastPoll.started_at) : 'Never'}</span>
                    </div>
                    <div class="settings-row">
                        <span class="settings-label">Last poll status</span>
                        <span class="settings-value" style="color:${lastPoll?.status === 'success' ? 'var(--success)' : lastPoll?.status === 'error' ? 'var(--danger)' : 'var(--text-primary)'}">
                            ${lastPoll?.status || '--'}
                        </span>
                    </div>
                    ${lastPoll?.error_message ? `
                    <div class="settings-row">
                        <span class="settings-label">Last error</span>
                        <span class="settings-value" style="color:var(--danger)">${Utils.escapeHtml(lastPoll.error_message)}</span>
                    </div>` : ''}
                </div>

                <div class="settings-section">
                    <h3>Poll History</h3>
                    ${Components.pollLogTable(pollLog.polls)}
                </div>

                ${faAuth.has_cookies ? `
                <div class="settings-section">
                    <h3>FA Polling Status</h3>
                    <div class="settings-row">
                        <span class="settings-label">FA submissions tracked</span>
                        <span class="settings-value">${faStatus.total_submissions || 0}</span>
                    </div>
                    <div class="settings-row">
                        <span class="settings-label">FA snapshots stored</span>
                        <span class="settings-value">${Utils.formatNumber(faStatus.total_snapshots || 0)}</span>
                    </div>
                    <div class="settings-row">
                        <span class="settings-label">Last FA poll</span>
                        <span class="settings-value">${faStatus.last_poll ? Utils.formatDateTime(faStatus.last_poll.started_at) : 'Never'}</span>
                    </div>
                    <div class="settings-row">
                        <span class="settings-label">Last FA poll status</span>
                        <span class="settings-value" style="color:${faStatus.last_poll?.status === 'success' ? 'var(--success)' : faStatus.last_poll?.status === 'error' ? 'var(--danger)' : 'var(--text-primary)'}">
                            ${faStatus.last_poll?.status || '--'}
                        </span>
                    </div>
                    ${faStatus.last_poll?.error_message ? `
                    <div class="settings-row">
                        <span class="settings-label">Last FA error</span>
                        <span class="settings-value" style="color:var(--danger)">${Utils.escapeHtml(faStatus.last_poll.error_message)}</span>
                    </div>` : ''}
                </div>

                <div class="settings-section">
                    <h3>FA Poll History</h3>
                    ${Components.faPollLogTable(faPollLog.polls)}
                </div>
                ` : ''}

                ${wsAuth.has_key ? `
                <div class="settings-section">
                    <h3>WS Polling Status</h3>
                    <div class="settings-row">
                        <span class="settings-label">WS submissions tracked</span>
                        <span class="settings-value">${wsStatus.total_submissions || 0}</span>
                    </div>
                    <div class="settings-row">
                        <span class="settings-label">WS snapshots stored</span>
                        <span class="settings-value">${Utils.formatNumber(wsStatus.total_snapshots || 0)}</span>
                    </div>
                    <div class="settings-row">
                        <span class="settings-label">Last WS poll</span>
                        <span class="settings-value">${wsStatus.last_poll ? Utils.formatDateTime(wsStatus.last_poll.started_at) : 'Never'}</span>
                    </div>
                    <div class="settings-row">
                        <span class="settings-label">Last WS poll status</span>
                        <span class="settings-value" style="color:${wsStatus.last_poll?.status === 'success' ? 'var(--success)' : wsStatus.last_poll?.status === 'error' ? 'var(--danger)' : 'var(--text-primary)'}">
                            ${wsStatus.last_poll?.status || '--'}
                        </span>
                    </div>
                    ${wsStatus.last_poll?.error_message ? `
                    <div class="settings-row">
                        <span class="settings-label">Last WS error</span>
                        <span class="settings-value" style="color:var(--danger)">${Utils.escapeHtml(wsStatus.last_poll.error_message)}</span>
                    </div>` : ''}
                </div>

                <div class="settings-section">
                    <h3>WS Poll History</h3>
                    ${Components.wsPollLogTable(wsPollLog.polls)}
                </div>
                ` : ''}

                ${sfAuth.has_credentials ? `
                <div class="settings-section">
                    <h3>SF Polling Status</h3>
                    <div class="settings-row">
                        <span class="settings-label">SF submissions tracked</span>
                        <span class="settings-value">${sfStatus.total_submissions || 0}</span>
                    </div>
                    <div class="settings-row">
                        <span class="settings-label">SF snapshots stored</span>
                        <span class="settings-value">${Utils.formatNumber(sfStatus.total_snapshots || 0)}</span>
                    </div>
                    <div class="settings-row">
                        <span class="settings-label">Last SF poll</span>
                        <span class="settings-value">${sfStatus.last_poll ? Utils.formatDateTime(sfStatus.last_poll.started_at) : 'Never'}</span>
                    </div>
                    <div class="settings-row">
                        <span class="settings-label">Last SF poll status</span>
                        <span class="settings-value" style="color:${sfStatus.last_poll?.status === 'success' ? 'var(--success)' : sfStatus.last_poll?.status === 'error' ? 'var(--danger)' : 'var(--text-primary)'}">
                            ${sfStatus.last_poll?.status || '--'}
                        </span>
                    </div>
                    ${sfStatus.last_poll?.error_message ? `
                    <div class="settings-row">
                        <span class="settings-label">Last SF error</span>
                        <span class="settings-value" style="color:var(--danger)">${Utils.escapeHtml(sfStatus.last_poll.error_message)}</span>
                    </div>` : ''}
                </div>

                <div class="settings-section">
                    <h3>SF Poll History</h3>
                    ${Components.sfPollLogTable(sfPollLog.polls)}
                </div>
                ` : ''}
            `;

            this._setContent(html);

            // ── Settings Event Handlers ──────────────────────────────
            // All controls save immediately on interaction (no "Save All" button).
            // Toggles revert on failure. Buttons show loading text and re-render
            // the settings page after completion via setTimeout.

            // Poll Now: triggers an IB poll, shows progress, re-renders on complete
            document.getElementById('poll-now-btn').addEventListener('click', async (e) => {
                const btn = e.target;
                btn.disabled = true;
                btn.textContent = 'Polling...';
                try {
                    await API.triggerPoll();
                    btn.textContent = 'Done!';
                    setTimeout(() => this.renderSettings(), 1500);
                } catch (err) {
                    btn.textContent = 'Error';
                    alert('Poll failed: ' + err.message);
                    setTimeout(() => this.renderSettings(), 2000);
                }
            });

            // Full Resync: re-scrapes all faves and comments for every IB submission.
            // Confirms with the user first since this is a long operation.
            document.getElementById('full-resync-btn').addEventListener('click', async (e) => {
                const btn = e.target;
                if (!confirm('Full resync will re-scrape all faves and comments for every submission. This may take a while. Continue?')) return;
                btn.disabled = true;
                btn.textContent = 'Syncing...';
                try {
                    const result = await API.fullResync();
                    btn.textContent = 'Done!';
                    alert(`Resync complete: ${result.stats.new_faves_found} new faves, ${result.stats.new_comments_found} new comments`);
                    setTimeout(() => this.renderSettings(), 1500);
                } catch (err) {
                    btn.textContent = 'Error';
                    alert('Resync failed: ' + err.message);
                    setTimeout(() => this.renderSettings(), 2000);
                }
            });

            // Save Credentials: sends username (always) and password (only if changed)
            // to the API. Shows inline success/error message next to the button.
            document.getElementById('save-creds-btn').addEventListener('click', async () => {
                const btn = document.getElementById('save-creds-btn');
                const msg = document.getElementById('creds-msg');
                const username = document.getElementById('cred-username').value.trim();
                const password = document.getElementById('cred-password').value;
                if (!username) { msg.textContent = 'Username is required'; msg.style.color = 'var(--danger)'; return; }
                btn.disabled = true;
                btn.textContent = 'Saving...';
                try {
                    const payload = { username };
                    if (password) payload.password = password;
                    await API.saveCredentials(payload);
                    msg.textContent = 'Saved!';
                    msg.style.color = 'var(--success)';
                    btn.textContent = 'Save Credentials';
                    btn.disabled = false;
                } catch (err) {
                    msg.textContent = 'Error: ' + err.message;
                    msg.style.color = 'var(--danger)';
                    btn.textContent = 'Save Credentials';
                    btn.disabled = false;
                }
            });

            // Sign Out: clears IB credentials and navigates to the login page
            document.getElementById('settings-logout-btn').addEventListener('click', async () => {
                if (!confirm('Sign out and clear saved credentials?')) return;
                try {
                    await API.authLogout();
                } catch { /* ignore */ }
                this.navigate('/login');
            });

            // Preference toggles — each saves immediately via API. On failure,
            // the toggle reverts to its previous state and shows an alert.
            // Minimize to tray toggle
            document.getElementById('pref-tray').addEventListener('change', async (e) => {
                try {
                    await API.savePreferences({ minimize_to_tray: e.target.checked });
                } catch (err) {
                    e.target.checked = !e.target.checked;
                    alert('Failed to save preference: ' + err.message);
                }
            });

            document.getElementById('pref-startup').addEventListener('change', async (e) => {
                try {
                    await API.savePreferences({ run_on_startup: e.target.checked });
                } catch (err) {
                    e.target.checked = !e.target.checked;
                    alert('Failed to save preference: ' + err.message);
                }
            });

            document.getElementById('pref-notifications').addEventListener('change', async (e) => {
                try {
                    await API.savePreferences({ notifications_enabled: e.target.checked });
                } catch (err) {
                    e.target.checked = !e.target.checked;
                    alert('Failed to save preference: ' + err.message);
                }
            });

            document.getElementById('pref-poll-interval').addEventListener('change', async (e) => {
                try {
                    await API.savePreferences({ poll_interval_minutes: parseInt(e.target.value) });
                } catch (err) {
                    alert('Failed to save: ' + err.message);
                }
            });

            document.getElementById('pref-fa-poll-interval').addEventListener('change', async (e) => {
                try {
                    await API.savePreferences({ fa_poll_interval_minutes: parseInt(e.target.value) });
                } catch (err) {
                    alert('Failed to save: ' + err.message);
                }
            });

            // Clear Session: clears cached API session, forces fresh auth on next request
            document.getElementById('clear-session-btn').addEventListener('click', async (e) => {
                const btn = e.target;
                btn.disabled = true;
                btn.textContent = 'Clearing...';
                try {
                    await API.clearSession();
                    btn.textContent = 'Cleared!';
                    setTimeout(() => this.renderSettings(), 1500);
                } catch (err) {
                    btn.textContent = 'Error';
                    alert('Clear session failed: ' + err.message);
                    setTimeout(() => this.renderSettings(), 2000);
                }
            });

            // Telegram Connect: sends bot token to API, validates via getUpdates.
            // Strips API error prefix for cleaner error display. Only rendered
            // when Telegram is not already connected.
            const telegramConnectBtn = document.getElementById('telegram-connect-btn');
            if (telegramConnectBtn) {
                telegramConnectBtn.addEventListener('click', async () => {
                    const btn = telegramConnectBtn;
                    const msg = document.getElementById('telegram-msg');
                    const token = document.getElementById('telegram-token').value.trim();
                    if (!token) { msg.textContent = 'Paste your bot token first'; msg.style.color = 'var(--danger)'; return; }
                    btn.disabled = true;
                    btn.textContent = 'Connecting...';
                    msg.textContent = '';
                    try {
                        await API.connectTelegram({ bot_token: token });
                        msg.textContent = 'Connected!';
                        msg.style.color = 'var(--success)';
                        setTimeout(() => this.renderSettings(), 1000);
                    } catch (err) {
                        let detail = err.message.replace(/^API \d+:\s*/, '');
                        try { detail = JSON.parse(detail).detail || detail; } catch {}
                        msg.textContent = detail;
                        msg.style.color = 'var(--danger)';
                        btn.textContent = 'Connect';
                        btn.disabled = false;
                    }
                });
            }

            // Telegram Test: sends a test message to verify the integration works
            const telegramTestBtn = document.getElementById('telegram-test-btn');
            if (telegramTestBtn) {
                telegramTestBtn.addEventListener('click', async () => {
                    const btn = telegramTestBtn;
                    const msg = document.getElementById('telegram-msg');
                    btn.disabled = true;
                    btn.textContent = 'Sending...';
                    msg.textContent = '';
                    try {
                        await API.testTelegram();
                        msg.textContent = 'Test message sent!';
                        msg.style.color = 'var(--success)';
                        btn.textContent = 'Test';
                        btn.disabled = false;
                    } catch (err) {
                        msg.textContent = 'Failed: ' + err.message;
                        msg.style.color = 'var(--danger)';
                        btn.textContent = 'Test';
                        btn.disabled = false;
                    }
                });
            }

            // Telegram Disconnect: removes bot token/chat_id, re-renders to show connect form
            const telegramDisconnectBtn = document.getElementById('telegram-disconnect-btn');
            if (telegramDisconnectBtn) {
                telegramDisconnectBtn.addEventListener('click', async () => {
                    if (!confirm('Disconnect Telegram notifications?')) return;
                    try {
                        await API.disconnectTelegram();
                        this.renderSettings();
                    } catch (err) {
                        alert('Failed: ' + err.message);
                    }
                });
            }

            // Telegram Enable/Disable: controls whether notifications are sent
            // (separate from being connected -- can be connected but disabled)
            const telegramToggle = document.getElementById('pref-telegram');
            if (telegramToggle) {
                telegramToggle.addEventListener('change', async (e) => {
                    try {
                        await API.savePreferences({ telegram_enabled: e.target.checked });
                    } catch (err) {
                        e.target.checked = !e.target.checked;
                        alert('Failed to save preference: ' + err.message);
                    }
                });
            }

            // FA Connect: sends username + cookie_a + cookie_b to authenticate
            // with FurAffinity via browser cookies. All three fields required.
            const faConnectBtn = document.getElementById('fa-connect-btn');
            if (faConnectBtn) {
                faConnectBtn.addEventListener('click', async () => {
                    const msg = document.getElementById('fa-msg');
                    const username = document.getElementById('fa-username').value.trim();
                    const cookieA = document.getElementById('fa-cookie-a').value.trim();
                    const cookieB = document.getElementById('fa-cookie-b').value.trim();
                    if (!username || !cookieA || !cookieB) {
                        msg.textContent = 'All three fields are required';
                        msg.style.color = 'var(--danger)';
                        return;
                    }
                    faConnectBtn.disabled = true;
                    faConnectBtn.textContent = 'Connecting...';
                    msg.textContent = '';
                    try {
                        await API.faConnect({ username, cookie_a: cookieA, cookie_b: cookieB });
                        msg.textContent = 'Connected!';
                        msg.style.color = 'var(--success)';
                        setTimeout(() => this.renderSettings(), 1000);
                    } catch (err) {
                        let detail = err.message.replace(/^API \d+:\s*/, '');
                        try { detail = JSON.parse(detail).detail || detail; } catch {}
                        msg.textContent = detail;
                        msg.style.color = 'var(--danger)';
                        faConnectBtn.textContent = 'Connect';
                        faConnectBtn.disabled = false;
                    }
                });
            }

            // FA Disconnect: clears saved cookies, re-renders to show connect form
            const faDisconnectBtn = document.getElementById('fa-disconnect-btn');
            if (faDisconnectBtn) {
                faDisconnectBtn.addEventListener('click', async () => {
                    if (!confirm('Disconnect FurAffinity? This clears saved cookies.')) return;
                    try {
                        await API.faDisconnect();
                        this.renderSettings();
                    } catch (err) {
                        alert('Failed: ' + err.message);
                    }
                });
            }

            // FA Poll Now: triggers an immediate FA data-fetch cycle
            const faPollBtn = document.getElementById('fa-poll-btn');
            if (faPollBtn) {
                faPollBtn.addEventListener('click', async () => {
                    const msg = document.getElementById('fa-msg');
                    faPollBtn.disabled = true;
                    faPollBtn.textContent = 'Polling...';
                    if (msg) msg.textContent = '';
                    try {
                        await API.triggerFAPoll();
                        faPollBtn.textContent = 'Done!';
                        setTimeout(() => this.renderSettings(), 1500);
                    } catch (err) {
                        faPollBtn.textContent = 'Error';
                        if (msg) { msg.textContent = err.message; msg.style.color = 'var(--danger)'; }
                        setTimeout(() => this.renderSettings(), 2000);
                    }
                });
            }

            // FA Full Resync: re-fetches all FA submission details and comments.
            // Confirms first since this is a long-running operation.
            const faResyncBtn = document.getElementById('fa-resync-btn');
            if (faResyncBtn) {
                faResyncBtn.addEventListener('click', async () => {
                    if (!confirm('FA full resync will re-fetch all submission details and comments. This may take a while. Continue?')) return;
                    const msg = document.getElementById('fa-msg');
                    faResyncBtn.disabled = true;
                    faResyncBtn.textContent = 'Syncing...';
                    if (msg) msg.textContent = '';
                    try {
                        await API.fullFAResync();
                        faResyncBtn.textContent = 'Done!';
                        setTimeout(() => this.renderSettings(), 1500);
                    } catch (err) {
                        faResyncBtn.textContent = 'Error';
                        if (msg) { msg.textContent = err.message; msg.style.color = 'var(--danger)'; }
                        setTimeout(() => this.renderSettings(), 2000);
                    }
                });
            }

            // FA Notifications toggle: enables/disables FA desktop + Telegram alerts
            const faNotifToggle = document.getElementById('pref-fa-notifications');
            if (faNotifToggle) {
                faNotifToggle.addEventListener('change', async (e) => {
                    try {
                        await API.savePreferences({ fa_notifications_enabled: e.target.checked });
                    } catch (err) {
                        e.target.checked = !e.target.checked;
                        alert('Failed to save preference: ' + err.message);
                    }
                });
            }

            // WS poll interval dropdown (15/30/60/120/240 minutes)
            document.getElementById('pref-ws-poll-interval')?.addEventListener('change', async (e) => {
                try {
                    await API.savePreferences({ ws_poll_interval_minutes: parseInt(e.target.value) });
                } catch (err) {
                    alert('Failed to save: ' + err.message);
                }
            });

            // Watcher notification toggles
            document.getElementById('pref-watcher-notif')?.addEventListener('change', async (e) => {
                try { await API.savePreferences({ watcher_notifications_enabled: e.target.checked }); }
                catch (err) { e.target.checked = !e.target.checked; alert('Failed: ' + err.message); }
            });
            document.getElementById('pref-fa-watcher-notif')?.addEventListener('change', async (e) => {
                try { await API.savePreferences({ fa_watcher_notifications_enabled: e.target.checked }); }
                catch (err) { e.target.checked = !e.target.checked; alert('Failed: ' + err.message); }
            });

            // Notification filter toggles
            document.getElementById('pref-notif-comments-only')?.addEventListener('change', async (e) => {
                try { await API.savePreferences({ notification_comments_only: e.target.checked }); }
                catch (err) { e.target.checked = !e.target.checked; alert('Failed: ' + err.message); }
            });
            document.getElementById('pref-fa-notif-comments-only')?.addEventListener('change', async (e) => {
                try { await API.savePreferences({ fa_notification_comments_only: e.target.checked }); }
                catch (err) { e.target.checked = !e.target.checked; alert('Failed: ' + err.message); }
            });
            document.getElementById('pref-ws-notif-comments-only')?.addEventListener('change', async (e) => {
                try { await API.savePreferences({ ws_notification_comments_only: e.target.checked }); }
                catch (err) { e.target.checked = !e.target.checked; alert('Failed: ' + err.message); }
            });
            document.getElementById('pref-min-views-delta')?.addEventListener('change', async (e) => {
                try { await API.savePreferences({ notification_min_views_delta: parseInt(e.target.value) || 0 }); }
                catch (err) { alert('Failed: ' + err.message); }
            });
            document.getElementById('pref-min-faves-delta')?.addEventListener('change', async (e) => {
                try { await API.savePreferences({ notification_min_faves_delta: parseInt(e.target.value) || 0 }); }
                catch (err) { alert('Failed: ' + err.message); }
            });

            // WS: Connect
            const wsConnectBtn = document.getElementById('ws-connect-btn');
            if (wsConnectBtn) {
                wsConnectBtn.addEventListener('click', async () => {
                    const msg = document.getElementById('ws-msg');
                    const apiKey = document.getElementById('ws-api-key').value.trim();
                    if (!apiKey) { msg.textContent = 'API key is required'; msg.style.color = 'var(--danger)'; return; }
                    wsConnectBtn.disabled = true;
                    wsConnectBtn.textContent = 'Connecting...';
                    msg.textContent = '';
                    try {
                        await API.wsConnect({ api_key: apiKey });
                        msg.textContent = 'Connected!';
                        msg.style.color = 'var(--success)';
                        setTimeout(() => this.renderSettings(), 1000);
                    } catch (err) {
                        let detail = err.message.replace(/^API \d+:\s*/, '');
                        try { detail = JSON.parse(detail).detail || detail; } catch {}
                        msg.textContent = detail;
                        msg.style.color = 'var(--danger)';
                        wsConnectBtn.textContent = 'Connect';
                        wsConnectBtn.disabled = false;
                    }
                });
            }

            // WS: Disconnect
            const wsDisconnectBtn = document.getElementById('ws-disconnect-btn');
            if (wsDisconnectBtn) {
                wsDisconnectBtn.addEventListener('click', async () => {
                    if (!confirm('Disconnect Weasyl? This clears saved API key.')) return;
                    try {
                        await API.wsDisconnect();
                        this.renderSettings();
                    } catch (err) {
                        alert('Failed: ' + err.message);
                    }
                });
            }

            // WS: Poll Now
            const wsPollBtn = document.getElementById('ws-poll-btn');
            if (wsPollBtn) {
                wsPollBtn.addEventListener('click', async () => {
                    const msg = document.getElementById('ws-msg');
                    wsPollBtn.disabled = true;
                    wsPollBtn.textContent = 'Polling...';
                    if (msg) msg.textContent = '';
                    try {
                        await API.triggerWSPoll();
                        wsPollBtn.textContent = 'Done!';
                        setTimeout(() => this.renderSettings(), 1500);
                    } catch (err) {
                        wsPollBtn.textContent = 'Error';
                        if (msg) { msg.textContent = err.message; msg.style.color = 'var(--danger)'; }
                        setTimeout(() => this.renderSettings(), 2000);
                    }
                });
            }

            // WS: Full Resync
            const wsResyncBtn = document.getElementById('ws-resync-btn');
            if (wsResyncBtn) {
                wsResyncBtn.addEventListener('click', async () => {
                    if (!confirm('WS full resync will re-fetch all submission details. Continue?')) return;
                    const msg = document.getElementById('ws-msg');
                    wsResyncBtn.disabled = true;
                    wsResyncBtn.textContent = 'Syncing...';
                    if (msg) msg.textContent = '';
                    try {
                        await API.fullWSResync();
                        wsResyncBtn.textContent = 'Done!';
                        setTimeout(() => this.renderSettings(), 1500);
                    } catch (err) {
                        wsResyncBtn.textContent = 'Error';
                        if (msg) { msg.textContent = err.message; msg.style.color = 'var(--danger)'; }
                        setTimeout(() => this.renderSettings(), 2000);
                    }
                });
            }

            // WS: Notifications toggle
            const wsNotifToggle = document.getElementById('pref-ws-notifications');
            if (wsNotifToggle) {
                wsNotifToggle.addEventListener('change', async (e) => {
                    try {
                        await API.savePreferences({ ws_notifications_enabled: e.target.checked });
                    } catch (err) {
                        e.target.checked = !e.target.checked;
                        alert('Failed to save preference: ' + err.message);
                    }
                });
            }

            // SF poll interval dropdown
            document.getElementById('pref-sf-poll-interval')?.addEventListener('change', async (e) => {
                try {
                    await API.savePreferences({ sf_poll_interval_minutes: parseInt(e.target.value) });
                } catch (err) {
                    alert('Failed to save: ' + err.message);
                }
            });

            // SF notification filter toggle
            document.getElementById('pref-sf-notif-comments-only')?.addEventListener('change', async (e) => {
                try { await API.savePreferences({ sf_notification_comments_only: e.target.checked }); }
                catch (err) { e.target.checked = !e.target.checked; alert('Failed: ' + err.message); }
            });

            // SF: Connect
            const sfConnectBtn = document.getElementById('sf-connect-btn');
            if (sfConnectBtn) {
                sfConnectBtn.addEventListener('click', async () => {
                    const msg = document.getElementById('sf-msg');
                    const username = document.getElementById('sf-username').value.trim();
                    const password = document.getElementById('sf-password').value;
                    const display_name = (document.getElementById('sf-display-name')?.value || '').trim();
                    const totp_code = (document.getElementById('sf-totp')?.value || '').trim();
                    if (!username || !password || !display_name) {
                        msg.textContent = 'Email, password, and display name are required';
                        msg.style.color = 'var(--danger)';
                        return;
                    }
                    sfConnectBtn.disabled = true;
                    sfConnectBtn.textContent = 'Connecting...';
                    msg.textContent = '';
                    try {
                        await API.sfConnect({ username, password, display_name, totp_code });
                        msg.textContent = 'Connected!';
                        msg.style.color = 'var(--success)';
                        setTimeout(() => this.renderSettings(), 1000);
                    } catch (err) {
                        let detail = err.message.replace(/^API \d+:\s*/, '');
                        try { detail = JSON.parse(detail).detail || detail; } catch {}
                        msg.textContent = detail;
                        msg.style.color = 'var(--danger)';
                        sfConnectBtn.textContent = 'Connect';
                        sfConnectBtn.disabled = false;
                    }
                });
            }

            // SF: Disconnect
            const sfDisconnectBtn = document.getElementById('sf-disconnect-btn');
            if (sfDisconnectBtn) {
                sfDisconnectBtn.addEventListener('click', async () => {
                    if (!confirm('Disconnect SoFurry? This clears saved credentials.')) return;
                    try {
                        await API.sfDisconnect();
                        this.renderSettings();
                    } catch (err) {
                        alert('Failed: ' + err.message);
                    }
                });
            }

            // SF: Poll Now
            const sfPollBtn = document.getElementById('sf-poll-btn');
            if (sfPollBtn) {
                sfPollBtn.addEventListener('click', async () => {
                    const msg = document.getElementById('sf-msg');
                    sfPollBtn.disabled = true;
                    sfPollBtn.textContent = 'Polling...';
                    if (msg) msg.textContent = '';
                    try {
                        await API.triggerSFPoll();
                        sfPollBtn.textContent = 'Done!';
                        setTimeout(() => this.renderSettings(), 1500);
                    } catch (err) {
                        sfPollBtn.textContent = 'Error';
                        if (msg) { msg.textContent = err.message; msg.style.color = 'var(--danger)'; }
                        setTimeout(() => this.renderSettings(), 2000);
                    }
                });
            }

            // SF: Full Resync
            const sfResyncBtn = document.getElementById('sf-resync-btn');
            if (sfResyncBtn) {
                sfResyncBtn.addEventListener('click', async () => {
                    if (!confirm('SF full resync will re-fetch all submission details. Continue?')) return;
                    const msg = document.getElementById('sf-msg');
                    sfResyncBtn.disabled = true;
                    sfResyncBtn.textContent = 'Syncing...';
                    if (msg) msg.textContent = '';
                    try {
                        await API.fullSFResync();
                        sfResyncBtn.textContent = 'Done!';
                        setTimeout(() => this.renderSettings(), 1500);
                    } catch (err) {
                        sfResyncBtn.textContent = 'Error';
                        if (msg) { msg.textContent = err.message; msg.style.color = 'var(--danger)'; }
                        setTimeout(() => this.renderSettings(), 2000);
                    }
                });
            }

            // SF: Notifications toggle
            const sfNotifToggle = document.getElementById('pref-sf-notifications');
            if (sfNotifToggle) {
                sfNotifToggle.addEventListener('change', async (e) => {
                    try {
                        await API.savePreferences({ sf_notifications_enabled: e.target.checked });
                    } catch (err) {
                        e.target.checked = !e.target.checked;
                        alert('Failed to save preference: ' + err.message);
                    }
                });
            }

            // Auto-Update
            const applyUpdateBtn = document.getElementById('apply-update-btn');
            if (applyUpdateBtn) {
                applyUpdateBtn.addEventListener('click', async () => {
                    if (!confirm('Download and apply the update? The app will restart.')) return;
                    applyUpdateBtn.disabled = true;
                    applyUpdateBtn.textContent = 'Updating...';
                    try {
                        await API.applyUpdate({ download_url: updateInfo.download_url });
                        applyUpdateBtn.textContent = 'Restarting...';
                    } catch (err) {
                        applyUpdateBtn.textContent = 'Failed';
                        alert('Update failed: ' + err.message);
                    }
                });
            }
        } catch (err) {
            this._setContent(`<div class="empty-state"><h3>Error</h3><p>${Utils.escapeHtml(err.message)}</p></div>`);
        }
    },

    // ── Auto-refresh ──────────────────────────────────────────
    // 60-second polling loop that re-renders the current page to show fresh
    // data from the latest poll cycle. Skips the re-render when the browser
    // tab is hidden (document.hidden) to avoid wasted API calls. Preserves
    // the user's scroll position across refreshes. Shows a brief "Refreshing..."
    // toast indicator during the update. Cleared on every route change via
    // _stopAutoRefresh() so stale timers don't fire on the wrong page.

    _startAutoRefresh(renderFn) {
        this._stopAutoRefresh();
        this._autoRefreshTimer = setInterval(async () => {
            if (document.hidden) return;
            const indicator = document.getElementById('refresh-indicator');
            if (indicator) indicator.style.opacity = '1';
            const scrollY = window.scrollY;
            try {
                await renderFn();
                window.scrollTo(0, scrollY);
            } catch { /* ignore — next tick will retry */ }
            const ind2 = document.getElementById('refresh-indicator');
            if (ind2) setTimeout(() => { ind2.style.opacity = '0'; }, 800);
        }, this._autoRefreshInterval);
    },

    // Clears both the auto-refresh timer and the loading-screen poll interval.
    // Called at the start of every route change (in route()) and at the start
    // of _startAutoRefresh() to prevent timer stacking.
    _stopAutoRefresh() {
        if (this._autoRefreshTimer) {
            clearInterval(this._autoRefreshTimer);
            this._autoRefreshTimer = null;
        }
        if (this._loadingPollInterval) {
            clearInterval(this._loadingPollInterval);
            this._loadingPollInterval = null;
        }
    },

    // Returns the HTML for the "Refreshing..." toast indicator. Placed at the
    // top of every page's HTML template. Starts invisible (opacity:0 in CSS)
    // and is briefly faded in by _startAutoRefresh during a refresh cycle.
    _refreshIndicatorHtml() {
        return '<div id="refresh-indicator" class="refresh-indicator">Refreshing...</div>';
    },

    // ── Helpers ────────────────────────────────────────────────
    // Shared utility methods used across multiple page renderers. These handle
    // common UI patterns: date range bar binding, table column sorting,
    // client-side search/filter, and per-platform variants of each.

    // Binds click handlers to the date range bar buttons (All / 7d / 30d / 90d / Year).
    // Updates _dateRange state, toggles the .active CSS class on the clicked button,
    // and invokes the callback (which typically re-fetches data with the new range).
    _bindDateRange(callback) {
        const bar = document.getElementById('date-range-bar');
        if (!bar) return;
        bar.querySelectorAll('.range-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                this._dateRange = btn.dataset.range;
                bar.querySelectorAll('.range-btn').forEach(b => b.classList.remove('active'));
                btn.classList.add('active');
                callback();
            });
        });
    },

    // Binds click handlers to sortable column headers in the IB submissions table.
    // Clicking a header toggles asc/desc if already sorted by that column, or
    // switches to that column in desc order. Triggers a full re-render via
    // renderSubmissions() which re-fetches with the new sort from the API.
    _bindTableSort() {
        document.querySelectorAll('#submissions-table th[data-sort]').forEach(th => {
            th.addEventListener('click', () => {
                const field = th.dataset.sort;
                if (this._sortState.field === field) {
                    this._sortState.order = this._sortState.order === 'desc' ? 'asc' : 'desc';
                } else {
                    this._sortState.field = field;
                    this._sortState.order = 'desc';
                }
                this.renderSubmissions();
            });
        });
    },

    // Client-side search and filter for the IB submissions table. Filters by:
    // - Text query: matches against title and keywords (case-insensitive substring)
    // - Rating: matches numeric rating_id (0=General, 1=Mature, 2=Adult)
    // - Type: matches type_name (Picture/Pinup, Writing, etc.)
    // Operates on the full allSubmissions array (already fetched) rather than
    // re-fetching from the API, so filtering is instant. Re-renders the table
    // HTML and re-binds sort handlers after each filter change.
    _bindSearch(allSubmissions) {
        const input = document.getElementById('search-input');
        const ratingSelect = document.getElementById('filter-rating');
        const typeSelect = document.getElementById('filter-type');

        const doFilter = () => {
            const q = (input?.value || '').toLowerCase();
            const rating = ratingSelect?.value || '';
            const type = typeSelect?.value || '';

            let filtered = allSubmissions;
            if (q) {
                filtered = filtered.filter(s =>
                    (s.title || '').toLowerCase().includes(q) || (s.keywords || '').toLowerCase().includes(q)
                );
            }
            if (rating) {
                filtered = filtered.filter(s => String(s.rating_id) === rating);
            }
            if (type) {
                filtered = filtered.filter(s => (s.type_name || '') === type);
            }

            document.getElementById('table-container').innerHTML = Components.submissionsTable(filtered);
            this._bindTableSort();
        };

        input?.addEventListener('input', doFilter);
        ratingSelect?.addEventListener('change', doFilter);
        typeSelect?.addEventListener('change', doFilter);
    },

    // FA variant of _bindTableSort(). Same toggle-sort pattern but targets
    // #fa-submissions-table headers and uses _faSortState + renderFASubmissions().
    _bindFATableSort() {
        document.querySelectorAll('#fa-submissions-table th[data-sort]').forEach(th => {
            th.addEventListener('click', () => {
                const field = th.dataset.sort;
                if (this._faSortState.field === field) {
                    this._faSortState.order = this._faSortState.order === 'desc' ? 'asc' : 'desc';
                } else {
                    this._faSortState.field = field;
                    this._faSortState.order = 'desc';
                }
                this.renderFASubmissions();
            });
        });
    },

    // FA variant of _bindSearch(). Filters by text (title/keywords) and rating
    // (General/Mature/Adult string values instead of IB's numeric rating_id).
    // No type filter (FA doesn't have IB's type_name taxonomy).
    _bindFASearch(allSubmissions) {
        const input = document.getElementById('search-input');
        const ratingSelect = document.getElementById('filter-rating');

        const doFilter = () => {
            const q = (input?.value || '').toLowerCase();
            const rating = ratingSelect?.value || '';

            let filtered = allSubmissions;
            if (q) {
                filtered = filtered.filter(s =>
                    (s.title || '').toLowerCase().includes(q) || (s.keywords || '').toLowerCase().includes(q)
                );
            }
            if (rating) {
                filtered = filtered.filter(s => (s.rating || '') === rating);
            }

            document.getElementById('table-container').innerHTML = Components.faSubmissionsTable(filtered);
            this._bindFATableSort();
        };

        input?.addEventListener('input', doFilter);
        ratingSelect?.addEventListener('change', doFilter);
    },

    // WS variant of _bindTableSort(). Targets #ws-submissions-table headers,
    // uses _wsSortState + renderWSSubmissions().
    _bindWSTableSort() {
        document.querySelectorAll('#ws-submissions-table th[data-sort]').forEach(th => {
            th.addEventListener('click', () => {
                const field = th.dataset.sort;
                if (this._wsSortState.field === field) {
                    this._wsSortState.order = this._wsSortState.order === 'desc' ? 'asc' : 'desc';
                } else {
                    this._wsSortState.field = field;
                    this._wsSortState.order = 'desc';
                }
                this.renderWSSubmissions();
            });
        });
    },

    // WS variant of _bindSearch(). Filters by text (title/keywords) and rating
    // (General/Mature/Explicit — Weasyl's terminology). No type filter.
    _bindWSSearch(allSubmissions) {
        const input = document.getElementById('search-input');
        const ratingSelect = document.getElementById('filter-rating');

        const doFilter = () => {
            const q = (input?.value || '').toLowerCase();
            const rating = ratingSelect?.value || '';

            let filtered = allSubmissions;
            if (q) {
                filtered = filtered.filter(s =>
                    (s.title || '').toLowerCase().includes(q) || (s.keywords || '').toLowerCase().includes(q)
                );
            }
            if (rating) {
                filtered = filtered.filter(s => (s.rating || '') === rating);
            }

            document.getElementById('table-container').innerHTML = Components.wsSubmissionsTable(filtered);
            this._bindWSTableSort();
        };

        input?.addEventListener('input', doFilter);
        ratingSelect?.addEventListener('change', doFilter);
    },

    // SF variant of _bindTableSort(). Targets #sf-submissions-table headers,
    // uses _sfSortState + renderSFSubmissions().
    _bindSFTableSort() {
        document.querySelectorAll('#sf-submissions-table th[data-sort]').forEach(th => {
            th.addEventListener('click', () => {
                const field = th.dataset.sort;
                if (this._sfSortState.field === field) {
                    this._sfSortState.order = this._sfSortState.order === 'desc' ? 'asc' : 'desc';
                } else {
                    this._sfSortState.field = field;
                    this._sfSortState.order = 'desc';
                }
                this.renderSFSubmissions();
            });
        });
    },

    // SF variant of _bindSearch(). Filters by text (title/keywords) and rating
    // (Clean/Mature/Adult — SoFurry's terminology).
    _bindSFSearch(allSubmissions) {
        const input = document.getElementById('search-input');
        const ratingSelect = document.getElementById('filter-rating');

        const doFilter = () => {
            const q = (input?.value || '').toLowerCase();
            const rating = ratingSelect?.value || '';

            let filtered = allSubmissions;
            if (q) {
                filtered = filtered.filter(s =>
                    (s.title || '').toLowerCase().includes(q) || (s.keywords || '').toLowerCase().includes(q)
                );
            }
            if (rating) {
                filtered = filtered.filter(s => (s.rating || '') === rating);
            }

            document.getElementById('table-container').innerHTML = Components.sfSubmissionsTable(filtered);
            this._bindSFTableSort();
        };

        input?.addEventListener('input', doFilter);
        ratingSelect?.addEventListener('change', doFilter);
    },

    // Sidebar footer poll status ticker. Called on a 60-second interval set up
    // in init(). Fetches the latest poll log entry and updates the small
    // "Last poll: X ago" badge at the bottom of the sidebar. Failures are
    // silently ignored since this is purely cosmetic.
    async _updatePollStatus() {
        try {
            const status = await API.getStatus();
            const el = document.getElementById('poll-status-mini');
            if (el && status.last_poll) {
                el.textContent = `Last poll: ${Utils.timeAgo(status.last_poll.started_at)}`;
            }
        } catch { /* ignore */ }
    },
};

// Boot
document.addEventListener('DOMContentLoaded', () => App.init());
