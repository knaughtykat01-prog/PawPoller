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
    _sqwSortState: { field: 'views', order: 'desc' },
    _sqwCompareIds: new Set(),
    _sqwCompareMetric: 'views',
    _ao3SortState: { field: 'views', order: 'desc' },
    _ao3CompareIds: new Set(),
    _ao3CompareMetric: 'views',
    _daSortState: { field: 'views', order: 'desc' },
    _daCompareIds: new Set(),
    _daCompareMetric: 'views',
    _wpSortState: { field: 'reads', order: 'desc' },
    _wpCompareIds: new Set(),
    _wpCompareMetric: 'reads',
    _ikSortState: { field: 'likes', order: 'desc' },
    _ikCompareIds: new Set(),
    _ikCompareMetric: 'likes',
    _bskySortState: { field: 'likes', order: 'desc' },
    _bskyCompareIds: new Set(),
    _bskyCompareMetric: 'likes',
    _twSortState: { field: 'views', order: 'desc' },
    _twCompareIds: new Set(),
    _twCompareMetric: 'views',

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
        if (this._pollStatusInterval) clearInterval(this._pollStatusInterval);
        this._pollStatusInterval = setInterval(() => this._updatePollStatus(), 60000);
        this._initPollProgressBar();

        /* Hamburger menu — overlay is now in HTML, just query it */
        const sidebar = document.querySelector('.sidebar');
        const overlay = document.getElementById('sidebar-overlay');

        const closeSidebar = () => {
            sidebar?.classList.remove('open');
            overlay?.classList.remove('open');
        };
        const openSidebar = () => {
            sidebar?.classList.add('open');
            overlay?.classList.add('open');
        };

        /* Toggle sidebar open/closed when the hamburger icon is tapped */
        document.getElementById('hamburger-btn')?.addEventListener('click', () => {
            if (sidebar?.classList.contains('open')) closeSidebar();
            else openSidebar();
        });

        /* Tapping the translucent overlay closes the sidebar */
        overlay?.addEventListener('click', closeSidebar);

        /* Close sidebar on nav click (mobile) so the page behind is visible */
        document.querySelectorAll('.nav-link').forEach(link => {
            link.addEventListener('click', closeSidebar);
        });

        /* Platform grid popover — opens from both nav button and bottom nav */
        const platformOverlay = document.getElementById('platform-grid-overlay');
        const openPlatformGrid = () => platformOverlay?.classList.add('open');
        const closePlatformGrid = () => platformOverlay?.classList.remove('open');

        document.getElementById('nav-platform-btn')?.addEventListener('click', openPlatformGrid);
        document.getElementById('bottom-nav-menu')?.addEventListener('click', () => {
            /* On mobile, open the platform grid popover instead of the sidebar */
            openPlatformGrid();
        });
        document.getElementById('platform-grid-close')?.addEventListener('click', closePlatformGrid);
        platformOverlay?.addEventListener('click', (e) => {
            if (e.target === platformOverlay) closePlatformGrid();
        });

        /* Accordion nav groups — toggle .expanded on click (mobile).
           On desktop the groups are always visible via CSS. */
        document.querySelectorAll('[data-nav-toggle]').forEach(toggle => {
            toggle.addEventListener('click', () => {
                const group = toggle.closest('.nav-group');
                if (group) group.classList.toggle('expanded');
            });
        });

        /* Logout button — fire-and-forget the API call, then redirect */
        document.getElementById('logout-btn')?.addEventListener('click', async () => {
            try {
                await API.authLogout();
            } catch { /* ignore */ }
            this.navigate('/login');
        });

        /* Theme toggle — restore saved theme from localStorage */
        const savedTheme = localStorage.getItem('pawpoller-theme') || 'dark';
        document.documentElement.dataset.theme = savedTheme;
        this._updateThemeButton(savedTheme);
        document.getElementById('theme-toggle-btn')?.addEventListener('click', () => {
            const current = document.documentElement.dataset.theme || 'dark';
            const next = current === 'dark' ? 'light' : 'dark';
            document.documentElement.dataset.theme = next;
            localStorage.setItem('pawpoller-theme', next);
            this._updateThemeButton(next);
            Charts.destroyAll();
            this.route(); // re-render current page with new theme colors
        });

        /* Sidebar version + update check */
        this._initSidebarVersion();
    },

    _updateThemeButton(theme) {
        const btn = document.getElementById('theme-toggle-btn');
        if (btn) {
            btn.innerHTML = theme === 'dark' ? '&#9788; <span class="nav-label">Light</span>' : '&#9790; <span class="nav-label">Dark</span>';
        }
    },

    async _initSidebarVersion() {
        const container = document.getElementById('sidebar-version');
        if (!container) return;
        try {
            const info = await API.checkUpdate().catch(() => ({ available: false, current: '?', latest: '?' }));
            this._renderSidebarVersion(container, info);
        } catch {
            container.innerHTML = '';
        }
    },

    _renderSidebarVersion(container, info) {
        if (info.available) {
            container.innerHTML = `
                <span class="update-available">v${Utils.escapeHtml(info.latest)} available</span>
                <button class="btn-update-now" id="sidebar-update-btn">Update Now</button>`;
            document.getElementById('sidebar-update-btn')?.addEventListener('click', async () => {
                if (!confirm('Download and apply the update? The app will restart.')) return;
                const btn = document.getElementById('sidebar-update-btn');
                btn.disabled = true;
                btn.textContent = 'Updating...';
                try {
                    await API.applyUpdate({ download_url: info.download_url });
                    btn.textContent = 'Restarting...';
                } catch (err) {
                    btn.textContent = 'Failed';
                    alert('Update failed: ' + err.message);
                }
            });
        } else {
            container.innerHTML = `
                <span class="version-text">v${Utils.escapeHtml(info.current)}</span>
                <button class="btn-check-update" id="sidebar-check-btn">Check for Updates</button>`;
            document.getElementById('sidebar-check-btn')?.addEventListener('click', async () => {
                const btn = document.getElementById('sidebar-check-btn');
                btn.disabled = true;
                btn.textContent = 'Checking...';
                try {
                    const result = await API.checkUpdate();
                    this._renderSidebarVersion(container, result);
                } catch {
                    btn.textContent = 'Failed';
                    setTimeout(() => { btn.textContent = 'Check for Updates'; btn.disabled = false; }, 3000);
                }
            });
        }
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

        /* Full-screen pages (login, loading) hide the sidebar, bottom nav, and remove left margin */
        const isFullScreen = parts[0] === 'login' || parts[0] === 'loading';
        const sidebar = document.querySelector('.sidebar');
        const main = document.getElementById('app');
        const bottomNav = document.getElementById('bottom-nav');
        if (sidebar) sidebar.style.display = isFullScreen ? 'none' : '';
        if (main) main.style.marginLeft = isFullScreen ? '0' : '';
        if (bottomNav) bottomNav.style.display = isFullScreen ? 'none' : '';

        /* Highlight the active nav link in the sidebar */
        document.querySelectorAll('.nav-link').forEach(link => {
            link.classList.toggle('active', link.getAttribute('href') === '#' + hash ||
                (hash === '/' && link.getAttribute('href') === '#/'));
        });

        /* Auto-expand the nav-group containing the active link, collapse others */
        document.querySelectorAll('.nav-group').forEach(group => {
            const hasActive = group.querySelector('.nav-link.active');
            group.classList.toggle('expanded', !!hasActive);
        });

        /* Update bottom nav active state */
        if (bottomNav) {
            bottomNav.querySelectorAll('.bottom-nav-item[data-page]').forEach(item => {
                const page = item.dataset.page;
                item.classList.toggle('active', page === parts[0] ||
                    (page === 'overview' && parts[0] === 'overview'));
            });
        }

        /* Destroy old Chart.js instances to free canvas memory */
        Charts.destroyAll();

        if (parts[0] === 'login') {
            this.renderLogin();
        } else if (parts[0] === 'loading') {
            this.renderLoading();
        } else if (hash === '/' || hash === '' || parts[0] === 'overview') {
            this.renderOverview();
        } else if (parts[0] === 'ib' && !parts[1]) {
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
        } else if (parts[0] === 'sqw' && (!parts[1] || parts[1] === '')) {
            this.renderSQWDashboard();
        } else if (parts[0] === 'sqw' && parts[1] === 'submissions' && !parts[2]) {
            this.renderSQWSubmissions();
        } else if (parts[0] === 'sqw' && parts[1] === 'submission' && parts[2]) {
            this.renderSQWDetail(parseInt(parts[2]));
        } else if (parts[0] === 'sqw' && parts[1] === 'compare') {
            this.renderSQWCompare();
        } else if (parts[0] === 'ao3' && (!parts[1] || parts[1] === '')) {
            this.renderAO3Dashboard();
        } else if (parts[0] === 'ao3' && parts[1] === 'submissions' && !parts[2]) {
            this.renderAO3Submissions();
        } else if (parts[0] === 'ao3' && parts[1] === 'submission' && parts[2]) {
            this.renderAO3Detail(parseInt(parts[2]));
        } else if (parts[0] === 'ao3' && parts[1] === 'compare') {
            this.renderAO3Compare();
        } else if (parts[0] === 'da' && (!parts[1] || parts[1] === '')) {
            this.renderDADashboard();
        } else if (parts[0] === 'da' && parts[1] === 'submissions' && !parts[2]) {
            this.renderDASubmissions();
        } else if (parts[0] === 'da' && parts[1] === 'submission' && parts[2]) {
            this.renderDADetail(parseInt(parts[2]));
        } else if (parts[0] === 'da' && parts[1] === 'compare') {
            this.renderDACompare();
        } else if (parts[0] === 'wp' && (!parts[1] || parts[1] === '')) {
            this.renderWPDashboard();
        } else if (parts[0] === 'wp' && parts[1] === 'submissions' && !parts[2]) {
            this.renderWPSubmissions();
        } else if (parts[0] === 'wp' && parts[1] === 'submission' && parts[2]) {
            this.renderWPDetail(parseInt(parts[2]));
        } else if (parts[0] === 'wp' && parts[1] === 'compare') {
            this.renderWPCompare();
        } else if (parts[0] === 'ik' && (!parts[1] || parts[1] === '')) {
            this.renderIKDashboard();
        } else if (parts[0] === 'ik' && parts[1] === 'submissions' && !parts[2]) {
            this.renderIKSubmissions();
        } else if (parts[0] === 'ik' && parts[1] === 'submission' && parts[2]) {
            this.renderIKDetail(parseInt(parts[2]));
        } else if (parts[0] === 'ik' && parts[1] === 'compare') {
            this.renderIKCompare();
        } else if (parts[0] === 'bsky' && (!parts[1] || parts[1] === '')) {
            this.renderBSKYDashboard();
        } else if (parts[0] === 'bsky' && parts[1] === 'submissions' && !parts[2]) {
            this.renderBSKYSubmissions();
        } else if (parts[0] === 'bsky' && parts[1] === 'submission' && parts[2]) {
            this.renderBSKYDetail(parts[2]);
        } else if (parts[0] === 'bsky' && parts[1] === 'compare') {
            this.renderBSKYCompare();
        } else if (parts[0] === 'tw' && (!parts[1] || parts[1] === '')) {
            this.renderTWDashboard();
        } else if (parts[0] === 'tw' && parts[1] === 'submissions' && !parts[2]) {
            this.renderTWSubmissions();
        } else if (parts[0] === 'tw' && parts[1] === 'submission' && parts[2]) {
            this.renderTWDetail(parts[2]);
        } else if (parts[0] === 'tw' && parts[1] === 'compare') {
            this.renderTWCompare();
        } else if (parts[0] === 'groups' && !parts[1]) {
            this.renderGroups();
        } else if (parts[0] === 'group' && parts[1]) {
            this.renderGroupDetail(parseInt(parts[1]));
        } else if (parts[0] === 'cross-platform') {
            this.renderCrossPlatform();
        } else if (parts[0] === 'analytics') {
            this.renderAnalytics();
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

    /* _loadLogs() — Fetch and display application log file in the Logs settings tab. */
    async _loadLogs() {
        const output = document.getElementById('log-output');
        const info = document.getElementById('log-info');
        if (!output) return;
        const file = document.getElementById('log-file-select')?.value || 'server';
        const lines = document.getElementById('log-lines-select')?.value || '200';
        const autoScroll = document.getElementById('log-auto-scroll')?.checked !== false;
        output.textContent = 'Loading...';
        try {
            const data = await API.getLogs({ file, lines });
            if (data.lines && data.lines.length > 0) {
                output.textContent = data.lines.join('\n');
            } else {
                output.textContent = '(no log entries)';
            }
            if (info) info.textContent = `Showing ${data.lines?.length || 0} of ${data.total_lines || 0} lines from ${file}.log`;
            if (autoScroll) output.scrollTop = output.scrollHeight;
        } catch (err) {
            output.textContent = `Error loading logs: ${err.message}`;
        }
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
        if (this._pollProgressTimer) {
            clearInterval(this._pollProgressTimer);
            this._pollProgressTimer = null;
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
        if (this._loadingPollInterval) clearInterval(this._loadingPollInterval);
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
            const [ibSummary, faSummary, wsSummary, sfSummary, sqwSummary, ao3Summary, daSummary, wpSummary, ikSummary, bskySummary, twSummary, ibAgg, faAgg, wsAgg, sfAgg, sqwAgg, ao3Agg, daAgg, wpAgg, ikAgg, bskyAgg, twAgg, topFans, trending] = await Promise.all([
                API.getSummary().catch(() => null),
                API.getFASummary().catch(() => null),
                API.getWSSummary().catch(() => null),
                API.getSFSummary().catch(() => null),
                API.getSQWSummary().catch(() => null),
                API.getAO3Summary().catch(() => null),
                API.getDASummary().catch(() => null),
                API.getWPSummary().catch(() => null),
                API.getIKSummary().catch(() => null),
                API.getBSKYSummary().catch(() => null),
                API.getTWSummary().catch(() => null),
                API.getAggregate(Utils.getDateRange(this._dateRange)).catch(() => null),
                API.getFAAggregate(Utils.getDateRange(this._dateRange)).catch(() => null),
                API.getWSAggregate(Utils.getDateRange(this._dateRange)).catch(() => null),
                API.getSFAggregate(Utils.getDateRange(this._dateRange)).catch(() => null),
                API.getSQWAggregate(Utils.getDateRange(this._dateRange)).catch(() => null),
                API.getAO3Aggregate(Utils.getDateRange(this._dateRange)).catch(() => null),
                API.getDAAggregate(Utils.getDateRange(this._dateRange)).catch(() => null),
                API.getWPAggregate(Utils.getDateRange(this._dateRange)).catch(() => null),
                API.getIKAggregate(Utils.getDateRange(this._dateRange)).catch(() => null),
                API.getBSKYAggregate(Utils.getDateRange(this._dateRange)).catch(() => null),
                API.getTWAggregate(Utils.getDateRange(this._dateRange)).catch(() => null),
                API.getTopFans(10).catch(() => ({ fans: [] })),
                API.getTrending({ hours: 24, threshold: 2.0 }).catch(() => ({ trending: [] })),
            ]);

            const ib = ibSummary || {};
            const fa = faSummary || {};
            const ws = wsSummary || {};
            const sf = sfSummary || {};
            const sqw = sqwSummary || {};
            const ao3 = ao3Summary || {};
            const da = daSummary || {};
            const wp = wpSummary || {};
            const ik = ikSummary || {};
            const bsky = bskySummary || {};
            const tw = twSummary || {};

            /* Sum totals across all platforms for the top-level stat cards.
             * Wattpad uses 'reads' instead of 'views' and 'votes' instead of 'favorites',
             * so we map them into the unified totals here.
             * Itaku has NO views — only likes (mapped to favorites), comments, and reshares. */
            const totalSubs = (ib.total_submissions || 0) + (fa.total_submissions || 0) + (ws.total_submissions || 0) + (sf.total_submissions || 0) + (sqw.total_submissions || 0) + (ao3.total_submissions || 0) + (da.total_submissions || 0) + (wp.total_submissions || 0) + (ik.total_submissions || 0) + (bsky.total_submissions || 0) + (tw.total_submissions || 0);
            const totalViews = (ib.total_views || 0) + (fa.total_views || 0) + (ws.total_views || 0) + (sf.total_views || 0) + (sqw.total_views || 0) + (ao3.total_views || 0) + (da.total_views || 0) + (wp.total_reads || wp.total_views || 0) + (tw.total_views || 0);
            const totalFaves = (ib.total_favorites || 0) + (fa.total_favorites || 0) + (ws.total_favorites || 0) + (sf.total_favorites || 0) + (sqw.total_favorites || 0) + (ao3.total_favorites || 0) + (da.total_favorites || 0) + (wp.total_votes || wp.total_favorites || 0) + (ik.total_likes || 0) + (bsky.total_likes || 0) + (tw.total_likes || 0);
            const totalComments = (ib.total_comments || 0) + (fa.total_comments || 0) + (ws.total_comments || 0) + (sf.total_comments || 0) + (sqw.total_comments || 0) + (ao3.total_comments || 0) + (da.total_comments || 0) + (wp.total_comments || 0) + (ik.total_comments || 0) + (bsky.total_comments || 0) + (tw.total_comments || 0);
            const totalDownloads = (da.total_downloads || 0);

            /* Merge top lists across platforms: tag each with _platform, sort desc, take top 10 */
            const mergeTop = (ibList, faList, wsList, sfList, sqwList, ao3List, daList, wpList, ikList, bskyList, twList, key) => {
                const merged = [];
                (ibList || []).forEach(item => merged.push({ ...item, _platform: 'ib' }));
                (faList || []).forEach(item => merged.push({ ...item, _platform: 'fa' }));
                (wsList || []).forEach(item => merged.push({ ...item, _platform: 'ws' }));
                (sfList || []).forEach(item => merged.push({ ...item, _platform: 'sf' }));
                (sqwList || []).forEach(item => merged.push({ ...item, _platform: 'sqw' }));
                (ao3List || []).forEach(item => merged.push({ ...item, _platform: 'ao3' }));
                (daList || []).forEach(item => merged.push({ ...item, _platform: 'da' }));
                /* Wattpad uses 'reads' for views and 'votes' for favorites — map to unified keys */
                (wpList || []).forEach(item => merged.push({ ...item, views: item.reads || item.views || 0, favorites_count: item.votes || item.favorites_count || 0, _platform: 'wp' }));
                /* Itaku has no views — map likes to favorites_count for unified merging */
                (ikList || []).forEach(item => merged.push({ ...item, favorites_count: item.likes || item.favorites_count || 0, _platform: 'ik' }));
                /* Bluesky has no views — map likes to favorites_count for unified merging */
                (bskyList || []).forEach(item => merged.push({ ...item, favorites_count: item.likes || item.favorites_count || 0, _platform: 'bsky' }));
                /* X/Twitter maps likes to favorites_count for unified merging */
                (twList || []).forEach(item => merged.push({ ...item, favorites_count: item.likes || item.favorites_count || 0, _platform: 'tw' }));
                merged.sort((a, b) => (b[key] || 0) - (a[key] || 0));
                return merged.slice(0, 10);
            };

            const topViewed = mergeTop(ib.top_viewed, fa.top_viewed, ws.top_viewed, sf.top_viewed, sqw.top_viewed, ao3.top_viewed, da.top_viewed, wp.top_viewed || wp.top_read, null, null, tw.top_viewed, 'views');
            const topFaved = mergeTop(ib.top_faved, fa.top_faved, ws.top_faved, sf.top_faved, sqw.top_faved, ao3.top_faved, da.top_faved, wp.top_faved || wp.top_voted, ik.top_liked || ik.top_faved, bsky.top_liked || bsky.top_faved, tw.top_liked || tw.top_faved, 'favorites_count');

            /* Merge recent faves + comments into a unified timeline, sorted newest first */
            const recentActivity = [];
            (ib.recent_faves || []).forEach(item => recentActivity.push({ ...item, _platform: 'ib', _type: 'fave' }));
            (ib.recent_comments || []).forEach(item => recentActivity.push({ ...item, _platform: 'ib', _type: 'comment' }));
            (fa.recent_faves || []).forEach(item => recentActivity.push({ ...item, _platform: 'fa', _type: 'fave' }));
            (fa.recent_comments || []).forEach(item => recentActivity.push({ ...item, _platform: 'fa', _type: 'comment' }));
            (ws.recent_faves || []).forEach(item => recentActivity.push({ ...item, _platform: 'ws', _type: 'fave' }));
            (ws.recent_comments || []).forEach(item => recentActivity.push({ ...item, _platform: 'ws', _type: 'comment' }));
            (sf.recent_faves || []).forEach(item => recentActivity.push({ ...item, _platform: 'sf', _type: 'fave' }));
            (sf.recent_comments || []).forEach(item => recentActivity.push({ ...item, _platform: 'sf', _type: 'comment' }));
            (sqw.recent_faves || []).forEach(item => recentActivity.push({ ...item, _platform: 'sqw', _type: 'fave' }));
            (sqw.recent_comments || []).forEach(item => recentActivity.push({ ...item, _platform: 'sqw', _type: 'comment' }));
            (ao3.recent_faves || []).forEach(item => recentActivity.push({ ...item, _platform: 'ao3', _type: 'fave' }));
            (ao3.recent_comments || []).forEach(item => recentActivity.push({ ...item, _platform: 'ao3', _type: 'comment' }));
            (da.recent_faves || []).forEach(item => recentActivity.push({ ...item, _platform: 'da', _type: 'fave' }));
            (da.recent_comments || []).forEach(item => recentActivity.push({ ...item, _platform: 'da', _type: 'comment' }));
            (wp.recent_faves || wp.recent_votes || []).forEach(item => recentActivity.push({ ...item, _platform: 'wp', _type: 'fave' }));
            (wp.recent_comments || []).forEach(item => recentActivity.push({ ...item, _platform: 'wp', _type: 'comment' }));
            (ik.recent_faves || ik.recent_likes || []).forEach(item => recentActivity.push({ ...item, _platform: 'ik', _type: 'fave' }));
            (ik.recent_comments || []).forEach(item => recentActivity.push({ ...item, _platform: 'ik', _type: 'comment' }));
            (bsky.recent_faves || bsky.recent_likes || []).forEach(item => recentActivity.push({ ...item, _platform: 'bsky', _type: 'fave' }));
            (bsky.recent_comments || []).forEach(item => recentActivity.push({ ...item, _platform: 'bsky', _type: 'comment' }));
            (tw.recent_faves || tw.recent_likes || []).forEach(item => recentActivity.push({ ...item, _platform: 'tw', _type: 'fave' }));
            (tw.recent_comments || []).forEach(item => recentActivity.push({ ...item, _platform: 'tw', _type: 'comment' }));
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
                        <button class="btn btn-secondary" onclick="API.exportSubmissions('sqw')" title="Export SqW CSV">Export SqW</button>
                        <button class="btn btn-secondary" onclick="API.exportSubmissions('ao3')" title="Export AO3 CSV">Export AO3</button>
                        <button class="btn btn-secondary" onclick="API.exportSubmissions('da')" title="Export DA CSV">Export DA</button>
                        <button class="btn btn-secondary" onclick="API.exportSubmissions('wp')" title="Export WP CSV">Export WP</button>
                        <button class="btn btn-secondary" onclick="API.exportSubmissions('ik')" title="Export IK CSV">Export IK</button>
                        <button class="btn btn-secondary" onclick="API.exportSubmissions('bsky')" title="Export BSKY CSV">Export BSKY</button>
                        <button class="btn btn-secondary" onclick="API.exportSubmissions('tw')" title="Export TW CSV">Export TW</button>
                    </div>
                </div>

                <div class="stats-grid">
                    ${Components.statCard('Total Submissions', totalSubs)}
                    ${Components.statCard('Total Views', totalViews)}
                    ${Components.statCard('Total Favorites', totalFaves)}
                    ${Components.statCard('Total Comments', totalComments)}
                    ${totalDownloads > 0 ? Components.statCard('Total Downloads', totalDownloads) : ''}
                </div>

                <div class="stats-grid" style="grid-template-columns:repeat(auto-fit,minmax(200px,1fr));margin-top:0">
                    ${platformCard('<span class="platform-badge ib">IB</span>', 'Inkbunny', ib)}
                    ${platformCard('<span class="platform-badge fa">FA</span>', 'FurAffinity', fa)}
                    ${platformCard('<span class="platform-badge ws">WS</span>', 'Weasyl', ws)}
                    ${platformCard('<span class="platform-badge sf">SF</span>', 'SoFurry', sf)}
                    ${platformCard('<span class="platform-badge sqw">SqW</span>', 'SquidgeWorld', sqw)}
                    ${platformCard('<span class="platform-badge ao3">AO3</span>', 'AO3', ao3)}
                    ${platformCard('<span class="platform-badge da">\u{1F3A8} DA</span>', 'DeviantArt', da)}
                    ${platformCard('<span class="platform-badge wp">\u{1F4D9} WP</span>', 'Wattpad', { total_views: wp.total_reads || wp.total_views || 0, total_favorites: wp.total_votes || wp.total_favorites || 0, total_submissions: wp.total_submissions || 0 })}
                    ${ ik.total_submissions ? `
                    <div class="stat-card">
                        <div class="label"><span class="platform-badge ik">\u{1F3AF} IK</span> Itaku</div>
                        <div style="display:flex;gap:16px;margin-top:6px">
                            <div><span style="font-size:18px;font-weight:600">${Utils.formatCompact(ik.total_likes || 0)}</span> <span style="font-size:11px;color:var(--text-muted)">likes</span></div>
                            <div><span style="font-size:18px;font-weight:600">${Utils.formatCompact(ik.total_comments || 0)}</span> <span style="font-size:11px;color:var(--text-muted)">comments</span></div>
                            <div><span style="font-size:18px;font-weight:600">${Utils.formatCompact(ik.total_reshares || 0)}</span> <span style="font-size:11px;color:var(--text-muted)">reshares</span></div>
                            <div><span style="font-size:18px;font-weight:600">${Utils.formatCompact(ik.total_submissions || 0)}</span> <span style="font-size:11px;color:var(--text-muted)">subs</span></div>
                        </div>
                    </div>` : platformCard('<span class="platform-badge ik">\u{1F3AF} IK</span>', 'Itaku', ik) }
                    ${ bsky.total_submissions ? `
                    <div class="stat-card">
                        <div class="label"><span class="platform-badge bsky">\u{1F98B} BSKY</span> Bluesky</div>
                        <div style="display:flex;gap:16px;margin-top:6px">
                            <div><span style="font-size:18px;font-weight:600">${Utils.formatCompact(bsky.total_likes || 0)}</span> <span style="font-size:11px;color:var(--text-muted)">likes</span></div>
                            <div><span style="font-size:18px;font-weight:600">${Utils.formatCompact(bsky.total_comments || bsky.total_replies || 0)}</span> <span style="font-size:11px;color:var(--text-muted)">replies</span></div>
                            <div><span style="font-size:18px;font-weight:600">${Utils.formatCompact(bsky.total_reposts || 0)}</span> <span style="font-size:11px;color:var(--text-muted)">reposts</span></div>
                            <div><span style="font-size:18px;font-weight:600">${Utils.formatCompact(bsky.total_submissions || 0)}</span> <span style="font-size:11px;color:var(--text-muted)">posts</span></div>
                        </div>
                    </div>` : platformCard('<span class="platform-badge bsky">\u{1F98B} BSKY</span>', 'Bluesky', bsky) }
                    ${ tw.total_submissions ? `
                    <div class="stat-card">
                        <div class="label"><span class="platform-badge tw">\u{1F426} TW</span> X/Twitter</div>
                        <div style="display:flex;gap:16px;margin-top:6px">
                            <div><span style="font-size:18px;font-weight:600">${Utils.formatCompact(tw.total_views || 0)}</span> <span style="font-size:11px;color:var(--text-muted)">views</span></div>
                            <div><span style="font-size:18px;font-weight:600">${Utils.formatCompact(tw.total_likes || 0)}</span> <span style="font-size:11px;color:var(--text-muted)">likes</span></div>
                            <div><span style="font-size:18px;font-weight:600">${Utils.formatCompact(tw.total_comments || tw.total_replies || 0)}</span> <span style="font-size:11px;color:var(--text-muted)">replies</span></div>
                            <div><span style="font-size:18px;font-weight:600">${Utils.formatCompact(tw.total_submissions || 0)}</span> <span style="font-size:11px;color:var(--text-muted)">tweets</span></div>
                        </div>
                    </div>` : platformCard('<span class="platform-badge tw">\u{1F426} TW</span>', 'X/Twitter', tw) }
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

                ${sqwAgg?.snapshots?.length > 0 ? `
                <div class="chart-container">
                    <h3>SquidgeWorld Views</h3>
                    <div class="chart-wrap"><canvas id="chart-sqw-views"></canvas></div>
                </div>` : ''}

                ${ao3Agg?.snapshots?.length > 0 ? `
                <div class="chart-container">
                    <h3>AO3 Views</h3>
                    <div class="chart-wrap"><canvas id="chart-ao3-views"></canvas></div>
                </div>` : ''}

                ${daAgg?.snapshots?.length > 0 ? `
                <div class="chart-container">
                    <h3>DeviantArt Views</h3>
                    <div class="chart-wrap"><canvas id="chart-da-views"></canvas></div>
                </div>` : ''}

                ${wpAgg?.snapshots?.length > 0 ? `
                <div class="chart-container">
                    <h3>Wattpad Reads</h3>
                    <div class="chart-wrap"><canvas id="chart-wp-reads"></canvas></div>
                </div>` : ''}

                ${ikAgg?.snapshots?.length > 0 ? `
                <div class="chart-container">
                    <h3>Itaku Likes</h3>
                    <div class="chart-wrap"><canvas id="chart-ik-likes"></canvas></div>
                </div>` : ''}

                ${bskyAgg?.snapshots?.length > 0 ? `
                <div class="chart-container">
                    <h3>Bluesky Likes</h3>
                    <div class="chart-wrap"><canvas id="chart-bsky-likes"></canvas></div>
                </div>` : ''}

                ${twAgg?.snapshots?.length > 0 ? `
                <div class="chart-container">
                    <h3>X/Twitter Views</h3>
                    <div class="chart-wrap"><canvas id="chart-tw-views"></canvas></div>
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
            if (sqwAgg?.snapshots?.length > 0) {
                Charts.aggregateLine('chart-sqw-views', sqwAgg.snapshots, ['views']);
            }
            if (ao3Agg?.snapshots?.length > 0) {
                Charts.aggregateLine('chart-ao3-views', ao3Agg.snapshots, ['views']);
            }
            if (daAgg?.snapshots?.length > 0) {
                Charts.aggregateLine('chart-da-views', daAgg.snapshots, ['views']);
            }
            if (wpAgg?.snapshots?.length > 0) {
                Charts.aggregateLine('chart-wp-reads', wpAgg.snapshots, ['reads']);
            }
            if (ikAgg?.snapshots?.length > 0) {
                Charts.aggregateLine('chart-ik-likes', ikAgg.snapshots, ['likes']);
            }
            if (bskyAgg?.snapshots?.length > 0) {
                Charts.aggregateLine('chart-bsky-likes', bskyAgg.snapshots, ['likes']);
            }
            if (twAgg?.snapshots?.length > 0) {
                Charts.aggregateLine('chart-tw-views', twAgg.snapshots, ['views']);
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
            /* Fetch IB summary stats, aggregate snapshots, pins, and goals in parallel */
            const [summary, agg, pins, goals] = await Promise.all([
                API.getSummary(),
                API.getAggregate(Utils.getDateRange(this._dateRange)),
                API.getPins().catch(() => ({ pins: [] })),
                API.getGoals().catch(() => ({ goals: [] })),
            ]);
            const ibPins = (pins.pins || []).filter(p => p.platform === 'ib');
            const ibGoals = (goals.goals || []).filter(g => g.platform === 'ib' || g.platform === 'all');

            const html = `
                ${this._refreshIndicatorHtml()}
                <div class="page-header"><h2>Dashboard</h2></div>

                ${ibPins.length ? Components.pinnedSubmissions(ibPins, 'ib') : ''}
                ${ibGoals.length ? `<div class="goals-section"><h3>Goals</h3>${Components.goalProgressCards(ibGoals)}</div>` : ''}

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
            this._bindPinAndGoalActions(() => this.renderDashboard());

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

            const _vm = localStorage.getItem('pp-view-mode') || 'grid';
            const gridHtml = Components.submissionCardGrid(data.submissions, {
                idKey: 'submission_id', titleKey: 'title', thumbKey: 'thumb_url',
                detailRoute: '/submission', dateKey: 'create_datetime',
                stats: [
                    { key: 'views', deltaKey: 'views_delta', label: 'views' },
                    { key: 'favorites_count', deltaKey: 'faves_delta', label: 'faves' },
                    { key: 'comments_count', deltaKey: 'comments_delta', label: 'comments' },
                ],
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
                    <div class="view-toggle">
                        <button class="view-toggle-btn ${_vm === 'grid' ? 'active' : ''}" data-view="grid" title="Grid view">&#9638;</button>
                        <button class="view-toggle-btn ${_vm === 'list' ? 'active' : ''}" data-view="list" title="List view">&#9776;</button>
                    </div>
                </div>
                <div id="grid-container" style="${_vm !== 'grid' ? 'display:none' : ''}">${gridHtml}</div>
                <div id="table-container" class="table-scroll" style="${_vm !== 'list' ? 'display:none' : ''}">
                    ${Components.submissionsTable(data.submissions)}
                </div>
            `;

            this._setContent(html);
            this._bindViewToggle();
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
            const [data, pins, allTags] = await Promise.all([
                API.getSubmission(id),
                API.getPins().catch(() => ({ pins: [] })),
                API.getTags().catch(() => ({ tags: [] })),
            ]);
            const sub = data.submission;
            const isPinned = (pins.pins || []).some(p => p.platform === 'ib' && p.submission_id === id);
            const currentTags = sub.tags || [];

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
                        <div style="margin-top:8px;display:flex;gap:8px;align-items:center;flex-wrap:wrap">
                            <button class="btn ${isPinned ? 'btn-danger' : 'btn-secondary'} btn-pin" data-platform="ib" data-id="${id}" style="padding:4px 10px;font-size:12px">${isPinned ? 'Unpin' : 'Pin'}</button>
                            ${currentTags.map(t => Components.tagBadge(t)).join('')}
                            <button class="btn btn-secondary btn-add-tag" data-platform="ib" data-id="${id}" style="padding:4px 10px;font-size:12px">+ Tag</button>
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

            this._bindDetailPinTag('ib', id, allTags.tags || [], () => this.renderDetail(id));
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
            const [summary, agg, pins, goals] = await Promise.all([
                API.getFASummary(),
                API.getFAAggregate(Utils.getDateRange(this._dateRange)),
                API.getPins().catch(() => ({ pins: [] })),
                API.getGoals().catch(() => ({ goals: [] })),
            ]);
            const faPins = (pins.pins || []).filter(p => p.platform === 'fa');
            const faGoals = (goals.goals || []).filter(g => g.platform === 'fa' || g.platform === 'all');

            const html = `
                ${this._refreshIndicatorHtml()}
                <div class="page-header"><h2>FurAffinity Dashboard</h2></div>

                ${faPins.length ? Components.pinnedSubmissions(faPins, 'fa') : ''}
                ${faGoals.length ? `<div class="goals-section"><h3>Goals</h3>${Components.goalProgressCards(faGoals)}</div>` : ''}

                <div class="stats-grid">
                    ${Components.statCard('Total Submissions', summary.total_submissions)}
                    ${Components.statCard('Total Views', summary.total_views)}
                    ${Components.statCard('Total Favorites', summary.total_favorites)}
                    ${Components.statCard('Total Comments', summary.total_comments)}
                    ${Components.statCard('Total Watchers', summary.total_watchers || 0)}
                    ${Components.statCard('Profile Views', summary.profile_pageviews || 0)}
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

            this._bindDateRange(() => this.renderFADashboard());
            this._bindPinAndGoalActions(() => this.renderFADashboard());
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

            const _vm = localStorage.getItem('pp-view-mode') || 'grid';
            const _faSubs = data.submissions.map(s => ({ ...s, _thumb: s.thumbnail_url ? Utils.faThumbUrl(s.thumbnail_url) : null }));
            const gridHtml = Components.submissionCardGrid(_faSubs, {
                idKey: 'submission_id', titleKey: 'title', thumbKey: '_thumb',
                detailRoute: '/fa/submission', dateKey: 'posted_at',
                proxyThumb: false,
                stats: [
                    { key: 'views', deltaKey: 'views_delta', label: 'views' },
                    { key: 'favorites_count', deltaKey: 'faves_delta', label: 'faves' },
                    { key: 'comments_count', deltaKey: 'comments_delta', label: 'comments' },
                ],
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
                    <div class="view-toggle">
                        <button class="view-toggle-btn ${_vm === 'grid' ? 'active' : ''}" data-view="grid" title="Grid view">&#9638;</button>
                        <button class="view-toggle-btn ${_vm === 'list' ? 'active' : ''}" data-view="list" title="List view">&#9776;</button>
                    </div>
                </div>
                <div id="grid-container" style="${_vm !== 'grid' ? 'display:none' : ''}">${gridHtml}</div>
                <div id="table-container" class="table-scroll" style="${_vm !== 'list' ? 'display:none' : ''}">
                    ${Components.faSubmissionsTable(data.submissions)}
                </div>
            `;

            this._setContent(html);
            this._bindViewToggle();
            this._bindFATableSort();
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
            const [data, pins, allTags] = await Promise.all([
                API.getFASubmission(id),
                API.getPins().catch(() => ({ pins: [] })),
                API.getTags().catch(() => ({ tags: [] })),
            ]);
            const sub = data.submission;
            const isPinned = (pins.pins || []).some(p => p.platform === 'fa' && p.submission_id === id);
            const currentTags = sub.tags || [];

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
                        <div style="margin-top:8px;display:flex;gap:8px;align-items:center;flex-wrap:wrap">
                            <button class="btn ${isPinned ? 'btn-danger' : 'btn-secondary'} btn-pin" data-platform="fa" data-id="${id}" style="padding:4px 10px;font-size:12px">${isPinned ? 'Unpin' : 'Pin'}</button>
                            ${currentTags.map(t => Components.tagBadge(t)).join('')}
                            <button class="btn btn-secondary btn-add-tag" data-platform="fa" data-id="${id}" style="padding:4px 10px;font-size:12px">+ Tag</button>
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

            this._bindDetailPinTag('fa', id, allTags.tags || [], () => this.renderFADetail(id));
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
            const [summary, agg, pins, goals] = await Promise.all([
                API.getWSSummary(),
                API.getWSAggregate(Utils.getDateRange(this._dateRange)),
                API.getPins().catch(() => ({ pins: [] })),
                API.getGoals().catch(() => ({ goals: [] })),
            ]);
            const wsPins = (pins.pins || []).filter(p => p.platform === 'ws');
            const wsGoals = (goals.goals || []).filter(g => g.platform === 'ws' || g.platform === 'all');

            const html = `
                ${this._refreshIndicatorHtml()}
                <div class="page-header">
                    <h2>Weasyl Dashboard</h2>
                    <button class="btn btn-secondary" onclick="API.exportSubmissions('ws')">Export CSV</button>
                </div>

                ${wsPins.length ? Components.pinnedSubmissions(wsPins, 'ws') : ''}
                ${wsGoals.length ? `<div class="goals-section"><h3>Goals</h3>${Components.goalProgressCards(wsGoals)}</div>` : ''}

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
            this._bindPinAndGoalActions(() => this.renderWSDashboard());
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

            const _vm = localStorage.getItem('pp-view-mode') || 'grid';
            const gridHtml = Components.submissionCardGrid(data.submissions, {
                idKey: 'submission_id', titleKey: 'title', thumbKey: 'thumbnail_url',
                detailRoute: '/ws/submission', dateKey: 'posted_at', proxyThumb: false,
                stats: [
                    { key: 'views', deltaKey: 'views_delta', label: 'views' },
                    { key: 'favorites_count', deltaKey: 'faves_delta', label: 'faves' },
                    { key: 'comments_count', deltaKey: 'comments_delta', label: 'comments' },
                ],
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
                    <div class="view-toggle">
                        <button class="view-toggle-btn ${_vm === 'grid' ? 'active' : ''}" data-view="grid" title="Grid view">&#9638;</button>
                        <button class="view-toggle-btn ${_vm === 'list' ? 'active' : ''}" data-view="list" title="List view">&#9776;</button>
                    </div>
                </div>
                <div id="grid-container" style="${_vm !== 'grid' ? 'display:none' : ''}">${gridHtml}</div>
                <div id="table-container" class="table-scroll" style="${_vm !== 'list' ? 'display:none' : ''}">
                    ${Components.wsSubmissionsTable(data.submissions)}
                </div>
            `;

            this._setContent(html);
            this._bindViewToggle();
            this._bindWSTableSort();
            this._bindWSSearch(data.submissions);
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
            const [data, pins, allTags] = await Promise.all([
                API.getWSSubmission(id),
                API.getPins().catch(() => ({ pins: [] })),
                API.getTags().catch(() => ({ tags: [] })),
            ]);
            const sub = data.submission;
            const isPinned = (pins.pins || []).some(p => p.platform === 'ws' && p.submission_id === id);
            const currentTags = sub.tags || [];

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
                        <div style="margin-top:8px;display:flex;gap:8px;align-items:center;flex-wrap:wrap">
                            <button class="btn ${isPinned ? 'btn-danger' : 'btn-secondary'} btn-pin" data-platform="ws" data-id="${id}" style="padding:4px 10px;font-size:12px">${isPinned ? 'Unpin' : 'Pin'}</button>
                            ${currentTags.map(t => Components.tagBadge(t)).join('')}
                            <button class="btn btn-secondary btn-add-tag" data-platform="ws" data-id="${id}" style="padding:4px 10px;font-size:12px">+ Tag</button>
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

            this._bindDetailPinTag('ws', id, allTags.tags || [], () => this.renderWSDetail(id));
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
            const [summary, agg, pins, goals] = await Promise.all([
                API.getSFSummary(),
                API.getSFAggregate(Utils.getDateRange(this._dateRange)),
                API.getPins().catch(() => ({ pins: [] })),
                API.getGoals().catch(() => ({ goals: [] })),
            ]);
            const sfPins = (pins.pins || []).filter(p => p.platform === 'sf');
            const sfGoals = (goals.goals || []).filter(g => g.platform === 'sf' || g.platform === 'all');

            const html = `
                ${this._refreshIndicatorHtml()}
                <div class="page-header">
                    <h2>SoFurry Dashboard</h2>
                    <button class="btn btn-secondary" onclick="API.exportSubmissions('sf')">Export CSV</button>
                </div>

                ${sfPins.length ? Components.pinnedSubmissions(sfPins, 'sf') : ''}
                ${sfGoals.length ? `<div class="goals-section"><h3>Goals</h3>${Components.goalProgressCards(sfGoals)}</div>` : ''}

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
            this._bindPinAndGoalActions(() => this.renderSFDashboard());
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

            const _vm = localStorage.getItem('pp-view-mode') || 'grid';
            const gridHtml = Components.submissionCardGrid(data.submissions, {
                idKey: 'submission_id', titleKey: 'title', thumbKey: 'thumbnail_url',
                detailRoute: '/sf/submission', dateKey: 'posted_at', proxyThumb: false,
                stats: [
                    { key: 'views', deltaKey: 'views_delta', label: 'views' },
                    { key: 'favorites_count', deltaKey: 'faves_delta', label: 'likes' },
                    { key: 'comments_count', deltaKey: 'comments_delta', label: 'comments' },
                ],
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
                    <div class="view-toggle">
                        <button class="view-toggle-btn ${_vm === 'grid' ? 'active' : ''}" data-view="grid" title="Grid view">&#9638;</button>
                        <button class="view-toggle-btn ${_vm === 'list' ? 'active' : ''}" data-view="list" title="List view">&#9776;</button>
                    </div>
                </div>
                <div id="grid-container" style="${_vm !== 'grid' ? 'display:none' : ''}">${gridHtml}</div>
                <div id="table-container" class="table-scroll" style="${_vm !== 'list' ? 'display:none' : ''}">
                    ${Components.sfSubmissionsTable(data.submissions)}
                </div>
            `;

            this._setContent(html);
            this._bindViewToggle();
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
            const [data, pins, allTags] = await Promise.all([
                API.getSFSubmission(id),
                API.getPins().catch(() => ({ pins: [] })),
                API.getTags().catch(() => ({ tags: [] })),
            ]);
            const sub = data.submission;
            const isPinned = (pins.pins || []).some(p => p.platform === 'sf' && String(p.submission_id) === String(id));
            const currentTags = sub.tags || [];

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
                        <div style="margin-top:8px;display:flex;gap:8px;align-items:center;flex-wrap:wrap">
                            <button class="btn ${isPinned ? 'btn-danger' : 'btn-secondary'} btn-pin" data-platform="sf" data-id="${id}" style="padding:4px 10px;font-size:12px">${isPinned ? 'Unpin' : 'Pin'}</button>
                            ${currentTags.map(t => Components.tagBadge(t)).join('')}
                            <button class="btn btn-secondary btn-add-tag" data-platform="sf" data-id="${id}" style="padding:4px 10px;font-size:12px">+ Tag</button>
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

            this._bindDetailPinTag('sf', id, allTags.tags || [], () => this.renderSFDetail(id));
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
                    const id = parseInt(chip.dataset.id);
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

    // ── SQW Dashboard ──────────────────────────────────────────

    async renderSQWDashboard() {
        this._loading();
        try {
            const [summary, agg, pins, goals] = await Promise.all([
                API.getSQWSummary(),
                API.getSQWAggregate(Utils.getDateRange(this._dateRange)),
                API.getPins().catch(() => ({ pins: [] })),
                API.getGoals().catch(() => ({ goals: [] })),
            ]);
            const sqwPins = (pins.pins || []).filter(p => p.platform === 'sqw');
            const sqwGoals = (goals.goals || []).filter(g => g.platform === 'sqw' || g.platform === 'all');

            const html = `
                ${this._refreshIndicatorHtml()}
                <div class="page-header">
                    <h2>SquidgeWorld Dashboard</h2>
                    <button class="btn btn-secondary" onclick="API.exportSubmissions('sqw')">Export CSV</button>
                </div>

                ${sqwPins.length ? Components.pinnedSubmissions(sqwPins, 'sqw') : ''}
                ${sqwGoals.length ? `<div class="goals-section"><h3>Goals</h3>${Components.goalProgressCards(sqwGoals)}</div>` : ''}

                <div class="stats-grid">
                    ${Components.statCard('Total Works', summary.total_submissions)}
                    ${Components.statCard('Total Hits', summary.total_views)}
                    ${Components.statCard('Total Kudos', summary.total_favorites)}
                    ${Components.statCard('Total Comments', summary.total_comments)}
                </div>

                ${Components.growthRateCards(summary.growth_rates)}

                ${Components.dateRangeBar(this._dateRange)}

                <div class="chart-container">
                    <h3>Hits Over Time (Aggregate)</h3>
                    <div class="chart-wrap"><canvas id="chart-agg-views"></canvas></div>
                </div>

                <div class="chart-row">
                    <div class="chart-container">
                        <h3>Top Viewed</h3>
                        <div class="chart-wrap"><canvas id="chart-top-views"></canvas></div>
                    </div>
                    <div class="chart-container">
                        <h3>Most Kudos</h3>
                        <div class="chart-wrap"><canvas id="chart-top-faves"></canvas></div>
                    </div>
                </div>

                <div class="chart-row">
                    <div class="chart-container" style="grid-column: 1 / -1">
                        <h3>Fastest Growing (24h)</h3>
                        ${Components.sqwTopList(summary.fastest_growing, 'views_gained')}
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

            this._bindDateRange(() => this.renderSQWDashboard());
            this._bindPinAndGoalActions(() => this.renderSQWDashboard());
            this._startAutoRefresh(() => this.renderSQWDashboard());
        } catch (err) {
            this._setContent(`<div class="empty-state"><h3>Error loading SqW dashboard</h3><p>${Utils.escapeHtml(err.message)}</p></div>`);
        }
    },

    // ── SQW Submissions ────────────────────────────────────────

    async renderSQWSubmissions() {
        this._loading();
        try {
            const data = await API.getSQWSubmissions({
                sort_by: this._sqwSortState.field,
                order: this._sqwSortState.order,
            });

            const _vm = localStorage.getItem('pp-view-mode') || 'grid';
            const gridHtml = Components.submissionCardGrid(data.submissions, {
                idKey: 'submission_id', titleKey: 'title', thumbKey: null,
                detailRoute: '/sqw/submission', dateKey: 'posted_at',
                stats: [
                    { key: 'views', deltaKey: 'views_delta', label: 'hits' },
                    { key: 'favorites_count', deltaKey: 'faves_delta', label: 'kudos' },
                    { key: 'comments_count', deltaKey: 'comments_delta', label: 'comments' },
                ],
            });
            const html = `
                ${this._refreshIndicatorHtml()}
                <div class="page-header"><h2>SquidgeWorld Works</h2></div>
                <div class="toolbar">
                    <input type="text" class="search-input" id="search-input" placeholder="Search titles and tags...">
                    <select class="filter-select" id="filter-rating">
                        <option value="">All Ratings</option>
                        <option value="General Audiences">General</option>
                        <option value="Teen And Up Audiences">Teen</option>
                        <option value="Mature">Mature</option>
                        <option value="Explicit">Explicit</option>
                    </select>
                    <div class="view-toggle">
                        <button class="view-toggle-btn ${_vm === 'grid' ? 'active' : ''}" data-view="grid" title="Grid view">&#9638;</button>
                        <button class="view-toggle-btn ${_vm === 'list' ? 'active' : ''}" data-view="list" title="List view">&#9776;</button>
                    </div>
                </div>
                <div id="grid-container" style="${_vm !== 'grid' ? 'display:none' : ''}">${gridHtml}</div>
                <div id="table-container" class="table-scroll" style="${_vm !== 'list' ? 'display:none' : ''}">
                    ${Components.sqwSubmissionsTable(data.submissions)}
                </div>
            `;

            this._setContent(html);
            this._bindViewToggle();
            this._bindSQWTableSort();
            this._bindSQWSearch(data.submissions);
            this._startAutoRefresh(() => this.renderSQWSubmissions());
        } catch (err) {
            this._setContent(`<div class="empty-state"><h3>Error loading SqW submissions</h3><p>${Utils.escapeHtml(err.message)}</p></div>`);
        }
    },

    // ── SQW Submission Detail ──────────────────────────────────

    async renderSQWDetail(id) {
        this._loading();
        try {
            const [data, pins, allTags] = await Promise.all([
                API.getSQWSubmission(id),
                API.getPins().catch(() => ({ pins: [] })),
                API.getTags().catch(() => ({ tags: [] })),
            ]);
            const sub = data.submission;
            const isPinned = (pins.pins || []).some(p => p.platform === 'sqw' && String(p.submission_id) === String(id));
            const currentTags = sub.tags || [];

            const html = `
                ${this._refreshIndicatorHtml()}
                <a href="#/sqw/submissions" class="back-link">&larr; Back to SqW Works</a>
                <div class="detail-header">
                    <div class="detail-info">
                        <h2>${Utils.escapeHtml(sub.title)}</h2>
                        <div class="detail-meta">by ${Utils.escapeHtml(sub.username)} &middot; ${Utils.escapeHtml(sub.posted_at || '')} &middot; ${Utils.escapeHtml(sub.rating || '')}</div>
                        <div class="detail-meta"><a href="${Utils.escapeHtml(sub.link || '#')}" target="_blank">View on SquidgeWorld</a></div>
                        <div class="detail-stats">
                            <div class="detail-stat">${Utils.formatNumber(sub.views)} <span class="lbl">hits</span></div>
                            <div class="detail-stat">${Utils.formatNumber(sub.favorites_count)} <span class="lbl">kudos</span></div>
                            <div class="detail-stat">${Utils.formatNumber(sub.comments_count)} <span class="lbl">comments</span></div>
                            <div class="detail-stat">${Utils.formatNumber(sub.bookmarks_count || 0)} <span class="lbl">bookmarks</span></div>
                        </div>
                        <div style="margin-top:8px;display:flex;gap:8px;align-items:center;flex-wrap:wrap">
                            <button class="btn ${isPinned ? 'btn-danger' : 'btn-secondary'} btn-pin" data-platform="sqw" data-id="${id}" style="padding:4px 10px;font-size:12px">${isPinned ? 'Unpin' : 'Pin'}</button>
                            ${currentTags.map(t => Components.tagBadge(t)).join('')}
                            <button class="btn btn-secondary btn-add-tag" data-platform="sqw" data-id="${id}" style="padding:4px 10px;font-size:12px">+ Tag</button>
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
                const snaps = await API.getSQWSnapshots(id, range);
                Charts.submissionLine('chart-detail', snaps.snapshots);
            });

            this._bindDetailPinTag('sqw', id, allTags.tags || [], () => this.renderSQWDetail(id));
            this._startAutoRefresh(() => this.renderSQWDetail(id));
        } catch (err) {
            this._setContent(`<div class="empty-state"><h3>Error loading SqW work</h3><p>${Utils.escapeHtml(err.message)}</p></div>`);
        }
    },

    // ── SQW Compare ────────────────────────────────────────────

    async renderSQWCompare() {
        this._loading();
        try {
            const data = await API.getSQWSubmissions({ sort_by: 'views', order: 'desc' });
            const subs = data.submissions;

            const chips = subs.map(s => `
                <label class="compare-chip ${this._sqwCompareIds.has(s.submission_id) ? 'selected' : ''}" data-id="${s.submission_id}">
                    <input type="checkbox" ${this._sqwCompareIds.has(s.submission_id) ? 'checked' : ''}>
                    ${Utils.escapeHtml(Utils.truncate(s.title, 25))}
                </label>
            `).join('');

            const html = `
                ${this._refreshIndicatorHtml()}
                <div class="page-header">
                    <h2>Compare SqW Works</h2>
                    <div>
                        <select class="filter-select" id="compare-metric">
                            <option value="views" ${this._sqwCompareMetric === 'views' ? 'selected' : ''}>Hits</option>
                            <option value="favorites_count" ${this._sqwCompareMetric === 'favorites_count' ? 'selected' : ''}>Kudos</option>
                            <option value="comments_count" ${this._sqwCompareMetric === 'comments_count' ? 'selected' : ''}>Comments</option>
                        </select>
                    </div>
                </div>
                <p style="font-size:13px;color:var(--text-muted);margin-bottom:12px">Select 2-5 SquidgeWorld works to compare their trends over time.</p>
                <div class="compare-select">${chips}</div>

                ${Components.dateRangeBar(this._dateRange)}

                <div class="chart-container" id="compare-chart-container" style="${this._sqwCompareIds.size < 2 ? 'display:none' : ''}">
                    <h3>Comparison</h3>
                    <div class="chart-wrap"><canvas id="chart-compare"></canvas></div>
                </div>
                ${this._sqwCompareIds.size < 2 ? '<div class="empty-state"><p>Select at least 2 works above to see their trends compared.</p></div>' : ''}
            `;

            this._setContent(html);

            document.querySelectorAll('.compare-chip').forEach(chip => {
                chip.addEventListener('click', (e) => {
                    e.preventDefault();
                    const id = parseInt(chip.dataset.id);
                    if (this._sqwCompareIds.has(id)) {
                        this._sqwCompareIds.delete(id);
                    } else if (this._sqwCompareIds.size < 5) {
                        this._sqwCompareIds.add(id);
                    }
                    this.renderSQWCompare();
                });
            });

            const metricSelect = document.getElementById('compare-metric');
            if (metricSelect) {
                metricSelect.addEventListener('change', () => {
                    this._sqwCompareMetric = metricSelect.value;
                    this._loadSQWComparisonChart();
                });
            }

            this._bindDateRange(() => this._loadSQWComparisonChart());

            if (this._sqwCompareIds.size >= 2) {
                await this._loadSQWComparisonChart();
            }

            this._startAutoRefresh(() => this.renderSQWCompare());
        } catch (err) {
            this._setContent(`<div class="empty-state"><h3>Error</h3><p>${Utils.escapeHtml(err.message)}</p></div>`);
        }
    },

    async _loadSQWComparisonChart() {
        try {
            if (this._sqwCompareIds.size < 2) return;
            const range = Utils.getDateRange(this._dateRange);
            const data = await API.getSQWComparison([...this._sqwCompareIds], range);
            const container = document.getElementById('compare-chart-container');
            if (container) container.style.display = '';
            Charts.comparisonLine('chart-compare', data.series, data.titles, this._sqwCompareMetric);
        } catch (e) {
            console.error('Failed to load SqW comparison chart:', e);
        }
    },

    // ── AO3 Dashboard ──────────────────────────────────────────

    async renderAO3Dashboard() {
        this._loading();
        try {
            const [summary, agg, pins, goals] = await Promise.all([
                API.getAO3Summary(),
                API.getAO3Aggregate(Utils.getDateRange(this._dateRange)),
                API.getPins().catch(() => ({ pins: [] })),
                API.getGoals().catch(() => ({ goals: [] })),
            ]);
            const ao3Pins = (pins.pins || []).filter(p => p.platform === 'ao3');
            const ao3Goals = (goals.goals || []).filter(g => g.platform === 'ao3' || g.platform === 'all');

            const html = `
                ${this._refreshIndicatorHtml()}
                <div class="page-header">
                    <h2>AO3 Dashboard</h2>
                    <button class="btn btn-secondary" onclick="API.exportSubmissions('ao3')">Export CSV</button>
                </div>

                ${ao3Pins.length ? Components.pinnedSubmissions(ao3Pins, 'ao3') : ''}
                ${ao3Goals.length ? `<div class="goals-section"><h3>Goals</h3>${Components.goalProgressCards(ao3Goals)}</div>` : ''}

                <div class="stats-grid">
                    ${Components.statCard('Total Works', summary.total_submissions)}
                    ${Components.statCard('Total Hits', summary.total_views)}
                    ${Components.statCard('Total Kudos', summary.total_favorites)}
                    ${Components.statCard('Total Comments', summary.total_comments)}
                </div>

                ${Components.growthRateCards(summary.growth_rates)}

                ${Components.dateRangeBar(this._dateRange)}

                <div class="chart-container">
                    <h3>Hits Over Time (Aggregate)</h3>
                    <div class="chart-wrap"><canvas id="chart-agg-views"></canvas></div>
                </div>

                <div class="chart-row">
                    <div class="chart-container">
                        <h3>Top Viewed</h3>
                        <div class="chart-wrap"><canvas id="chart-top-views"></canvas></div>
                    </div>
                    <div class="chart-container">
                        <h3>Most Kudos</h3>
                        <div class="chart-wrap"><canvas id="chart-top-faves"></canvas></div>
                    </div>
                </div>

                <div class="chart-row">
                    <div class="chart-container" style="grid-column: 1 / -1">
                        <h3>Fastest Growing (24h)</h3>
                        ${Components.ao3TopList(summary.fastest_growing, 'views_gained')}
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

            this._bindDateRange(() => this.renderAO3Dashboard());
            this._bindPinAndGoalActions(() => this.renderAO3Dashboard());
            this._startAutoRefresh(() => this.renderAO3Dashboard());
        } catch (err) {
            this._setContent(`<div class="empty-state"><h3>Error loading AO3 dashboard</h3><p>${Utils.escapeHtml(err.message)}</p></div>`);
        }
    },

    // ── AO3 Submissions ────────────────────────────────────────

    async renderAO3Submissions() {
        this._loading();
        try {
            const data = await API.getAO3Submissions({
                sort_by: this._ao3SortState.field,
                order: this._ao3SortState.order,
            });

            const _vm = localStorage.getItem('pp-view-mode') || 'grid';
            const gridHtml = Components.submissionCardGrid(data.submissions, {
                idKey: 'submission_id', titleKey: 'title', thumbKey: null,
                detailRoute: '/ao3/submission', dateKey: 'posted_at',
                stats: [
                    { key: 'views', deltaKey: 'views_delta', label: 'hits' },
                    { key: 'favorites_count', deltaKey: 'faves_delta', label: 'kudos' },
                    { key: 'comments_count', deltaKey: 'comments_delta', label: 'comments' },
                ],
            });
            const html = `
                ${this._refreshIndicatorHtml()}
                <div class="page-header"><h2>AO3 Works</h2></div>
                <div class="toolbar">
                    <input type="text" class="search-input" id="search-input" placeholder="Search titles and tags...">
                    <select class="filter-select" id="filter-rating">
                        <option value="">All Ratings</option>
                        <option value="General Audiences">General</option>
                        <option value="Teen And Up Audiences">Teen</option>
                        <option value="Mature">Mature</option>
                        <option value="Explicit">Explicit</option>
                    </select>
                    <div class="view-toggle">
                        <button class="view-toggle-btn ${_vm === 'grid' ? 'active' : ''}" data-view="grid" title="Grid view">&#9638;</button>
                        <button class="view-toggle-btn ${_vm === 'list' ? 'active' : ''}" data-view="list" title="List view">&#9776;</button>
                    </div>
                </div>
                <div id="grid-container" style="${_vm !== 'grid' ? 'display:none' : ''}">${gridHtml}</div>
                <div id="table-container" class="table-scroll" style="${_vm !== 'list' ? 'display:none' : ''}">
                    ${Components.ao3SubmissionsTable(data.submissions)}
                </div>
            `;

            this._setContent(html);
            this._bindViewToggle();
            this._bindAO3TableSort();
            this._bindAO3Search(data.submissions);
            this._startAutoRefresh(() => this.renderAO3Submissions());
        } catch (err) {
            this._setContent(`<div class="empty-state"><h3>Error loading AO3 submissions</h3><p>${Utils.escapeHtml(err.message)}</p></div>`);
        }
    },

    // ── AO3 Submission Detail ──────────────────────────────────

    async renderAO3Detail(id) {
        this._loading();
        try {
            const [data, pins, allTags] = await Promise.all([
                API.getAO3Submission(id),
                API.getPins().catch(() => ({ pins: [] })),
                API.getTags().catch(() => ({ tags: [] })),
            ]);
            const sub = data.submission;
            const isPinned = (pins.pins || []).some(p => p.platform === 'ao3' && String(p.submission_id) === String(id));
            const currentTags = sub.tags || [];

            const html = `
                ${this._refreshIndicatorHtml()}
                <a href="#/ao3/submissions" class="back-link">&larr; Back to AO3 Works</a>
                <div class="detail-header">
                    <div class="detail-info">
                        <h2>${Utils.escapeHtml(sub.title)}</h2>
                        <div class="detail-meta">by ${Utils.escapeHtml(sub.username)} &middot; ${Utils.escapeHtml(sub.posted_at || '')} &middot; ${Utils.escapeHtml(sub.rating || '')}</div>
                        <div class="detail-meta"><a href="${Utils.escapeHtml(sub.link || '#')}" target="_blank">View on AO3</a></div>
                        <div class="detail-stats">
                            <div class="detail-stat">${Utils.formatNumber(sub.views)} <span class="lbl">hits</span></div>
                            <div class="detail-stat">${Utils.formatNumber(sub.favorites_count)} <span class="lbl">kudos</span></div>
                            <div class="detail-stat">${Utils.formatNumber(sub.comments_count)} <span class="lbl">comments</span></div>
                            <div class="detail-stat">${Utils.formatNumber(sub.bookmarks_count || 0)} <span class="lbl">bookmarks</span></div>
                        </div>
                        <div style="margin-top:8px;display:flex;gap:8px;align-items:center;flex-wrap:wrap">
                            <button class="btn ${isPinned ? 'btn-danger' : 'btn-secondary'} btn-pin" data-platform="ao3" data-id="${id}" style="padding:4px 10px;font-size:12px">${isPinned ? 'Unpin' : 'Pin'}</button>
                            ${currentTags.map(t => Components.tagBadge(t)).join('')}
                            <button class="btn btn-secondary btn-add-tag" data-platform="ao3" data-id="${id}" style="padding:4px 10px;font-size:12px">+ Tag</button>
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
                const snaps = await API.getAO3Snapshots(id, range);
                Charts.submissionLine('chart-detail', snaps.snapshots);
            });

            this._bindDetailPinTag('ao3', id, allTags.tags || [], () => this.renderAO3Detail(id));
            this._startAutoRefresh(() => this.renderAO3Detail(id));
        } catch (err) {
            this._setContent(`<div class="empty-state"><h3>Error loading AO3 work</h3><p>${Utils.escapeHtml(err.message)}</p></div>`);
        }
    },

    // ── AO3 Compare ────────────────────────────────────────────

    async renderAO3Compare() {
        this._loading();
        try {
            const data = await API.getAO3Submissions({ sort_by: 'views', order: 'desc' });
            const subs = data.submissions;

            const chips = subs.map(s => `
                <label class="compare-chip ${this._ao3CompareIds.has(s.submission_id) ? 'selected' : ''}" data-id="${s.submission_id}">
                    <input type="checkbox" ${this._ao3CompareIds.has(s.submission_id) ? 'checked' : ''}>
                    ${Utils.escapeHtml(Utils.truncate(s.title, 25))}
                </label>
            `).join('');

            const html = `
                ${this._refreshIndicatorHtml()}
                <div class="page-header">
                    <h2>Compare AO3 Works</h2>
                    <div>
                        <select class="filter-select" id="compare-metric">
                            <option value="views" ${this._ao3CompareMetric === 'views' ? 'selected' : ''}>Hits</option>
                            <option value="favorites_count" ${this._ao3CompareMetric === 'favorites_count' ? 'selected' : ''}>Kudos</option>
                            <option value="comments_count" ${this._ao3CompareMetric === 'comments_count' ? 'selected' : ''}>Comments</option>
                        </select>
                    </div>
                </div>
                <p style="font-size:13px;color:var(--text-muted);margin-bottom:12px">Select 2-5 AO3 works to compare their trends over time.</p>
                <div class="compare-select">${chips}</div>

                ${Components.dateRangeBar(this._dateRange)}

                <div class="chart-container" id="compare-chart-container" style="${this._ao3CompareIds.size < 2 ? 'display:none' : ''}">
                    <h3>Comparison</h3>
                    <div class="chart-wrap"><canvas id="chart-compare"></canvas></div>
                </div>
                ${this._ao3CompareIds.size < 2 ? '<div class="empty-state"><p>Select at least 2 works above to see their trends compared.</p></div>' : ''}
            `;

            this._setContent(html);

            document.querySelectorAll('.compare-chip').forEach(chip => {
                chip.addEventListener('click', (e) => {
                    e.preventDefault();
                    const id = parseInt(chip.dataset.id);
                    if (this._ao3CompareIds.has(id)) {
                        this._ao3CompareIds.delete(id);
                    } else if (this._ao3CompareIds.size < 5) {
                        this._ao3CompareIds.add(id);
                    }
                    this.renderAO3Compare();
                });
            });

            const metricSelect = document.getElementById('compare-metric');
            if (metricSelect) {
                metricSelect.addEventListener('change', () => {
                    this._ao3CompareMetric = metricSelect.value;
                    this._loadAO3ComparisonChart();
                });
            }

            this._bindDateRange(() => this._loadAO3ComparisonChart());

            if (this._ao3CompareIds.size >= 2) {
                await this._loadAO3ComparisonChart();
            }

            this._startAutoRefresh(() => this.renderAO3Compare());
        } catch (err) {
            this._setContent(`<div class="empty-state"><h3>Error</h3><p>${Utils.escapeHtml(err.message)}</p></div>`);
        }
    },

    async _loadAO3ComparisonChart() {
        try {
            if (this._ao3CompareIds.size < 2) return;
            const range = Utils.getDateRange(this._dateRange);
            const data = await API.getAO3Comparison([...this._ao3CompareIds], range);
            const container = document.getElementById('compare-chart-container');
            if (container) container.style.display = '';
            Charts.comparisonLine('chart-compare', data.series, data.titles, this._ao3CompareMetric);
        } catch (e) {
            console.error('Failed to load AO3 comparison chart:', e);
        }
    },

    // ── DA Dashboard ──────────────────────────────────────────
    // DeviantArt dashboard with stat cards including Downloads (unique to DA),
    // growth rates, top lists (top viewed, top faved, top downloaded), and poll log.

    async renderDADashboard() {
        this._loading();
        try {
            const [summary, agg, pins, goals] = await Promise.all([
                API.getDASummary(),
                API.getDAAggregate(Utils.getDateRange(this._dateRange)),
                API.getPins().catch(() => ({ pins: [] })),
                API.getGoals().catch(() => ({ goals: [] })),
            ]);
            const daPins = (pins.pins || []).filter(p => p.platform === 'da');
            const daGoals = (goals.goals || []).filter(g => g.platform === 'da' || g.platform === 'all');

            const html = `
                ${this._refreshIndicatorHtml()}
                <div class="page-header">
                    <h2>DeviantArt Dashboard</h2>
                    <button class="btn btn-secondary" onclick="API.exportSubmissions('da')">Export CSV</button>
                </div>

                ${daPins.length ? Components.pinnedSubmissions(daPins, 'da') : ''}
                ${daGoals.length ? `<div class="goals-section"><h3>Goals</h3>${Components.goalProgressCards(daGoals)}</div>` : ''}

                <div class="stats-grid">
                    ${Components.statCard('Total Submissions', summary.total_submissions)}
                    ${Components.statCard('Total Views', summary.total_views)}
                    ${Components.statCard('Total Favourites', summary.total_favorites)}
                    ${Components.statCard('Total Comments', summary.total_comments)}
                    ${Components.statCard('Total Downloads', summary.total_downloads || 0)}
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
                        <h3>Top Downloaded</h3>
                        <div class="chart-wrap"><canvas id="chart-top-downloads"></canvas></div>
                    </div>
                    <div class="chart-container">
                        <h3>Fastest Growing (24h)</h3>
                        ${Components.daTopList(summary.fastest_growing, 'views_gained')}
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
            if (summary.top_downloaded && summary.top_downloaded.length > 0) {
                Charts.topBar('chart-top-downloads', summary.top_downloaded, 'downloads');
            }

            this._bindDateRange(() => this.renderDADashboard());
            this._bindPinAndGoalActions(() => this.renderDADashboard());
            this._startAutoRefresh(() => this.renderDADashboard());
        } catch (err) {
            this._setContent(`<div class="empty-state"><h3>Error loading DA dashboard</h3><p>${Utils.escapeHtml(err.message)}</p></div>`);
        }
    },

    // ── DA Submissions ─────────────────────────────────────────
    // DA submissions table with text search (title/keywords) and rating filter.
    // Includes Downloads column unique to DeviantArt.

    async renderDASubmissions() {
        this._loading();
        try {
            const data = await API.getDASubmissions({
                sort_by: this._daSortState.field,
                order: this._daSortState.order,
            });

            const _vm = localStorage.getItem('pp-view-mode') || 'grid';
            const gridHtml = Components.submissionCardGrid(data.submissions, {
                idKey: 'submission_id', titleKey: 'title', thumbKey: null,
                detailRoute: '/da/submission', dateKey: 'posted_at',
                stats: [
                    { key: 'views', deltaKey: 'views_delta', label: 'views' },
                    { key: 'favorites_count', deltaKey: 'faves_delta', label: 'faves' },
                    { key: 'comments_count', deltaKey: 'comments_delta', label: 'comments' },
                ],
            });
            const html = `
                ${this._refreshIndicatorHtml()}
                <div class="page-header"><h2>DA Submissions</h2></div>
                <div class="toolbar">
                    <input type="text" class="search-input" id="search-input" placeholder="Search titles and keywords...">
                    <select class="filter-select" id="filter-rating">
                        <option value="">All Ratings</option>
                        <option value="General">General</option>
                        <option value="Mature">Mature</option>
                    </select>
                    <div class="view-toggle">
                        <button class="view-toggle-btn ${_vm === 'grid' ? 'active' : ''}" data-view="grid" title="Grid view">&#9638;</button>
                        <button class="view-toggle-btn ${_vm === 'list' ? 'active' : ''}" data-view="list" title="List view">&#9776;</button>
                    </div>
                </div>
                <div id="grid-container" style="${_vm !== 'grid' ? 'display:none' : ''}">${gridHtml}</div>
                <div id="table-container" class="table-scroll" style="${_vm !== 'list' ? 'display:none' : ''}">
                    ${Components.daSubmissionsTable(data.submissions)}
                </div>
            `;

            this._setContent(html);
            this._bindViewToggle();
            this._bindDATableSort();
            this._bindDASearch(data.submissions);
            this._startAutoRefresh(() => this.renderDASubmissions());
        } catch (err) {
            this._setContent(`<div class="empty-state"><h3>Error loading DA submissions</h3><p>${Utils.escapeHtml(err.message)}</p></div>`);
        }
    },

    // ── DA Submission Detail ───────────────────────────────────
    // Individual DA submission detail page with 4 metrics including Downloads.

    async renderDADetail(id) {
        this._loading();
        try {
            const [data, pins, allTags] = await Promise.all([
                API.getDASubmission(id),
                API.getPins().catch(() => ({ pins: [] })),
                API.getTags().catch(() => ({ tags: [] })),
            ]);
            const sub = data.submission;
            const isPinned = (pins.pins || []).some(p => p.platform === 'da' && p.submission_id === id);
            const currentTags = sub.tags || [];

            const html = `
                ${this._refreshIndicatorHtml()}
                <a href="#/da/submissions" class="back-link">&larr; Back to DA Submissions</a>
                <div class="detail-header">
                    <div class="detail-info">
                        <h2>${Utils.escapeHtml(sub.title)}</h2>
                        <div class="detail-meta">by ${Utils.escapeHtml(sub.username)} &middot; ${Utils.formatDate(sub.posted_at)} &middot; ${Utils.escapeHtml(sub.rating || '')}</div>
                        <div class="detail-meta"><a href="${Utils.escapeHtml(sub.link || '#')}" target="_blank">View on DeviantArt</a></div>
                        <div class="detail-stats">
                            <div class="detail-stat">${Utils.formatNumber(sub.views)} <span class="lbl">views</span></div>
                            <div class="detail-stat">${Utils.formatNumber(sub.favorites_count)} <span class="lbl">faves</span></div>
                            <div class="detail-stat">${Utils.formatNumber(sub.comments_count)} <span class="lbl">comments</span></div>
                            <div class="detail-stat">${Utils.formatNumber(sub.downloads || 0)} <span class="lbl">downloads</span></div>
                        </div>
                        <div style="margin-top:8px;display:flex;gap:8px;align-items:center;flex-wrap:wrap">
                            <button class="btn ${isPinned ? 'btn-danger' : 'btn-secondary'} btn-pin" data-platform="da" data-id="${id}" style="padding:4px 10px;font-size:12px">${isPinned ? 'Unpin' : 'Pin'}</button>
                            ${currentTags.map(t => Components.tagBadge(t)).join('')}
                            <button class="btn btn-secondary btn-add-tag" data-platform="da" data-id="${id}" style="padding:4px 10px;font-size:12px">+ Tag</button>
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
                const snaps = await API.getDASnapshots(id, range);
                Charts.submissionLine('chart-detail', snaps.snapshots);
            });

            this._bindDetailPinTag('da', id, allTags.tags || [], () => this.renderDADetail(id));
            this._startAutoRefresh(() => this.renderDADetail(id));
        } catch (err) {
            this._setContent(`<div class="empty-state"><h3>Error loading DA submission</h3><p>${Utils.escapeHtml(err.message)}</p></div>`);
        }
    },

    // ── DA Compare ─────────────────────────────────────────────
    // DA comparison page with Downloads as an additional metric option.

    async renderDACompare() {
        this._loading();
        try {
            const data = await API.getDASubmissions({ sort_by: 'views', order: 'desc' });
            const subs = data.submissions;

            const chips = subs.map(s => `
                <label class="compare-chip ${this._daCompareIds.has(s.submission_id) ? 'selected' : ''}" data-id="${s.submission_id}">
                    <input type="checkbox" ${this._daCompareIds.has(s.submission_id) ? 'checked' : ''}>
                    ${Utils.escapeHtml(Utils.truncate(s.title, 25))}
                </label>
            `).join('');

            const html = `
                ${this._refreshIndicatorHtml()}
                <div class="page-header">
                    <h2>Compare DA Submissions</h2>
                    <div>
                        <select class="filter-select" id="compare-metric">
                            <option value="views" ${this._daCompareMetric === 'views' ? 'selected' : ''}>Views</option>
                            <option value="favorites_count" ${this._daCompareMetric === 'favorites_count' ? 'selected' : ''}>Favourites</option>
                            <option value="comments_count" ${this._daCompareMetric === 'comments_count' ? 'selected' : ''}>Comments</option>
                            <option value="downloads" ${this._daCompareMetric === 'downloads' ? 'selected' : ''}>Downloads</option>
                        </select>
                    </div>
                </div>
                <p style="font-size:13px;color:var(--text-muted);margin-bottom:12px">Select 2-5 DA submissions to compare their trends over time.</p>
                <div class="compare-select">${chips}</div>

                ${Components.dateRangeBar(this._dateRange)}

                <div class="chart-container" id="compare-chart-container" style="${this._daCompareIds.size < 2 ? 'display:none' : ''}">
                    <h3>Comparison</h3>
                    <div class="chart-wrap"><canvas id="chart-compare"></canvas></div>
                </div>
                ${this._daCompareIds.size < 2 ? '<div class="empty-state"><p>Select at least 2 submissions above to see their trends compared.</p></div>' : ''}
            `;

            this._setContent(html);

            document.querySelectorAll('.compare-chip').forEach(chip => {
                chip.addEventListener('click', (e) => {
                    e.preventDefault();
                    const id = parseInt(chip.dataset.id);
                    if (this._daCompareIds.has(id)) {
                        this._daCompareIds.delete(id);
                    } else if (this._daCompareIds.size < 5) {
                        this._daCompareIds.add(id);
                    }
                    this.renderDACompare();
                });
            });

            const metricSelect = document.getElementById('compare-metric');
            if (metricSelect) {
                metricSelect.addEventListener('change', () => {
                    this._daCompareMetric = metricSelect.value;
                    this._loadDAComparisonChart();
                });
            }

            this._bindDateRange(() => this._loadDAComparisonChart());

            if (this._daCompareIds.size >= 2) {
                await this._loadDAComparisonChart();
            }

            this._startAutoRefresh(() => this.renderDACompare());
        } catch (err) {
            this._setContent(`<div class="empty-state"><h3>Error</h3><p>${Utils.escapeHtml(err.message)}</p></div>`);
        }
    },

    async _loadDAComparisonChart() {
        try {
            if (this._daCompareIds.size < 2) return;
            const range = Utils.getDateRange(this._dateRange);
            const data = await API.getDAComparison([...this._daCompareIds], range);
            const container = document.getElementById('compare-chart-container');
            if (container) container.style.display = '';
            Charts.comparisonLine('chart-compare', data.series, data.titles, this._daCompareMetric);
        } catch (e) {
            console.error('Failed to load DA comparison chart:', e);
        }
    },

    // ── WP Dashboard ─────────────────────────────────────────
    // Wattpad dashboard showing Reads, Votes, Comments, Lists stats.
    // Uses Wattpad-specific metric names throughout.

    async renderWPDashboard() {
        this._loading();
        try {
            const [summary, agg, pins, goals] = await Promise.all([
                API.getWPSummary(),
                API.getWPAggregate(Utils.getDateRange(this._dateRange)),
                API.getPins().catch(() => ({ pins: [] })),
                API.getGoals().catch(() => ({ goals: [] })),
            ]);
            const wpPins = (pins.pins || []).filter(p => p.platform === 'wp');
            const wpGoals = (goals.goals || []).filter(g => g.platform === 'wp' || g.platform === 'all');

            const html = `
                ${this._refreshIndicatorHtml()}
                <div class="page-header">
                    <h2>Wattpad Dashboard</h2>
                    <button class="btn btn-secondary" onclick="API.exportSubmissions('wp')">Export CSV</button>
                </div>

                ${wpPins.length ? Components.pinnedSubmissions(wpPins, 'wp') : ''}
                ${wpGoals.length ? `<div class="goals-section"><h3>Goals</h3>${Components.goalProgressCards(wpGoals)}</div>` : ''}

                <div class="stats-grid">
                    ${Components.statCard('Total Submissions', summary.total_submissions)}
                    ${Components.statCard('Total Reads', summary.total_reads || summary.total_views || 0)}
                    ${Components.statCard('Total Votes', summary.total_votes || summary.total_favorites || 0)}
                    ${Components.statCard('Total Comments', summary.total_comments)}
                    ${Components.statCard('Total Lists', summary.total_lists || summary.total_num_lists || 0)}
                </div>

                ${summary.growth_rates ? (() => {
                    /* Map Wattpad growth rate field names for the growthRateCards component */
                    const rates = {};
                    for (const period of ['24h', '7d', '30d']) {
                        const r = summary.growth_rates[period];
                        if (r) {
                            rates[period] = {
                                views_per_day: r.reads_per_day != null ? r.reads_per_day : r.views_per_day,
                                faves_per_day: r.votes_per_day != null ? r.votes_per_day : r.faves_per_day,
                                comments_per_day: r.comments_per_day,
                            };
                        }
                    }
                    return Components.growthRateCards(rates, { views: 'reads/day', faves: 'votes/day', comments: 'comments/day' });
                })() : ''}

                ${Components.dateRangeBar(this._dateRange)}

                <div class="chart-container">
                    <h3>Reads Over Time (Aggregate)</h3>
                    <div class="chart-wrap"><canvas id="chart-agg-reads"></canvas></div>
                </div>

                <div class="chart-row">
                    <div class="chart-container">
                        <h3>Top Read</h3>
                        ${Components.wpTopList(summary.top_read || summary.top_viewed, 'reads', 'title', 'submission_id')}
                    </div>
                    <div class="chart-container">
                        <h3>Top Voted</h3>
                        ${Components.wpTopList(summary.top_voted || summary.top_faved, 'votes', 'title', 'submission_id')}
                    </div>
                </div>

                <div class="chart-row">
                    <div class="chart-container">
                        <h3>Most Listed</h3>
                        ${Components.wpTopList(summary.top_listed, 'num_lists', 'title', 'submission_id')}
                    </div>
                    <div class="chart-container">
                        <h3>Fastest Growing (24h)</h3>
                        ${Components.wpTopList(summary.fastest_growing, 'reads_gained', 'title', 'submission_id')}
                    </div>
                </div>
            `;

            this._setContent(html);

            if (agg.snapshots && agg.snapshots.length > 0) {
                Charts.aggregateLine('chart-agg-reads', agg.snapshots, ['reads']);
            }

            this._bindDateRange(() => this.renderWPDashboard());
            this._bindPinAndGoalActions(() => this.renderWPDashboard());
            this._startAutoRefresh(() => this.renderWPDashboard());
        } catch (err) {
            this._setContent(`<div class="empty-state"><h3>Error loading WP dashboard</h3><p>${Utils.escapeHtml(err.message)}</p></div>`);
        }
    },

    // ── WP Submissions ─────────────────────────────────────────
    // Wattpad submissions table with Reads, Votes, Comments, Lists columns.

    async renderWPSubmissions() {
        this._loading();
        try {
            const data = await API.getWPSubmissions({
                sort_by: this._wpSortState.field,
                order: this._wpSortState.order,
            });

            const _vm = localStorage.getItem('pp-view-mode') || 'grid';
            const gridHtml = Components.submissionCardGrid(data.submissions, {
                idKey: 'submission_id', titleKey: 'title', thumbKey: null,
                detailRoute: '/wp/submission', dateKey: 'posted_at',
                stats: [
                    { key: 'reads', deltaKey: 'reads_delta', label: 'reads' },
                    { key: 'votes', deltaKey: 'votes_delta', label: 'votes' },
                    { key: 'comments_count', deltaKey: 'comments_delta', label: 'comments' },
                ],
            });
            const html = `
                ${this._refreshIndicatorHtml()}
                <div class="page-header"><h2>WP Submissions</h2></div>
                <div class="toolbar">
                    <input type="text" class="search-input" id="search-input" placeholder="Search titles...">
                    <div class="view-toggle">
                        <button class="view-toggle-btn ${_vm === 'grid' ? 'active' : ''}" data-view="grid" title="Grid view">&#9638;</button>
                        <button class="view-toggle-btn ${_vm === 'list' ? 'active' : ''}" data-view="list" title="List view">&#9776;</button>
                    </div>
                </div>
                <div id="grid-container" style="${_vm !== 'grid' ? 'display:none' : ''}">${gridHtml}</div>
                <div id="table-container" class="table-scroll" style="${_vm !== 'list' ? 'display:none' : ''}">
                    ${Components.wpSubmissionsTable(data.submissions)}
                </div>
            `;

            this._setContent(html);
            this._bindViewToggle();
            this._bindWPTableSort();
            this._bindWPSearch(data.submissions);
            this._startAutoRefresh(() => this.renderWPSubmissions());
        } catch (err) {
            this._setContent(`<div class="empty-state"><h3>Error loading WP submissions</h3><p>${Utils.escapeHtml(err.message)}</p></div>`);
        }
    },

    // ── WP Submission Detail ───────────────────────────────────
    // Individual Wattpad submission detail with 4 metrics: reads, votes, comments, num_lists.

    async renderWPDetail(id) {
        this._loading();
        try {
            const [data, pins, allTags] = await Promise.all([
                API.getWPSubmission(id),
                API.getPins().catch(() => ({ pins: [] })),
                API.getTags().catch(() => ({ tags: [] })),
            ]);
            const sub = data.submission;
            const isPinned = (pins.pins || []).some(p => p.platform === 'wp' && p.submission_id === id);
            const currentTags = sub.tags || [];

            const html = `
                ${this._refreshIndicatorHtml()}
                <a href="#/wp/submissions" class="back-link">&larr; Back to WP Submissions</a>
                <div class="detail-header">
                    <div class="detail-info">
                        <h2>${Utils.escapeHtml(sub.title)}</h2>
                        <div class="detail-meta">by ${Utils.escapeHtml(sub.username)} &middot; ${Utils.formatDate(sub.posted_at)}</div>
                        <div class="detail-meta"><a href="${Utils.escapeHtml(sub.link || '#')}" target="_blank">View on Wattpad</a></div>
                        <div class="detail-stats">
                            <div class="detail-stat">${Utils.formatNumber(sub.reads || sub.views || 0)} <span class="lbl">reads</span></div>
                            <div class="detail-stat">${Utils.formatNumber(sub.votes || sub.favorites_count || 0)} <span class="lbl">votes</span></div>
                            <div class="detail-stat">${Utils.formatNumber(sub.comments_count || 0)} <span class="lbl">comments</span></div>
                            <div class="detail-stat">${Utils.formatNumber(sub.num_lists || 0)} <span class="lbl">lists</span></div>
                        </div>
                        <div style="margin-top:8px;display:flex;gap:8px;align-items:center;flex-wrap:wrap">
                            <button class="btn ${isPinned ? 'btn-danger' : 'btn-secondary'} btn-pin" data-platform="wp" data-id="${id}" style="padding:4px 10px;font-size:12px">${isPinned ? 'Unpin' : 'Pin'}</button>
                            ${currentTags.map(t => Components.tagBadge(t)).join('')}
                            <button class="btn btn-secondary btn-add-tag" data-platform="wp" data-id="${id}" style="padding:4px 10px;font-size:12px">+ Tag</button>
                        </div>
                        <div style="margin-top:8px">${Components.keywords(sub.keywords)}</div>
                    </div>
                </div>

                ${Components.growthRateCards(data.growth_rates, { views: 'reads/day', faves: 'votes/day', comments: 'comments/day' })}

                ${Components.dateRangeBar(this._dateRange)}

                <div class="chart-container">
                    <h3>Stats Over Time</h3>
                    <div class="chart-wrap"><canvas id="chart-detail"></canvas></div>
                </div>
            `;

            this._setContent(html);

            if (data.snapshots && data.snapshots.length > 0) {
                Charts.submissionLine('chart-detail', data.snapshots, ['reads', 'votes', 'comments_count', 'num_lists']);
            }

            this._bindDateRange(async () => {
                const range = Utils.getDateRange(this._dateRange);
                const snaps = await API.getWPSnapshots(id, range);
                Charts.submissionLine('chart-detail', snaps.snapshots, ['reads', 'votes', 'comments_count', 'num_lists']);
            });

            this._bindDetailPinTag('wp', id, allTags.tags || [], () => this.renderWPDetail(id));
            this._startAutoRefresh(() => this.renderWPDetail(id));
        } catch (err) {
            this._setContent(`<div class="empty-state"><h3>Error loading WP submission</h3><p>${Utils.escapeHtml(err.message)}</p></div>`);
        }
    },

    // ── WP Compare ─────────────────────────────────────────────
    // Wattpad comparison page with reads, votes, comments_count, num_lists metrics.

    async renderWPCompare() {
        this._loading();
        try {
            const data = await API.getWPSubmissions({ sort_by: 'reads', order: 'desc' });
            const subs = data.submissions;

            const chips = subs.map(s => `
                <label class="compare-chip ${this._wpCompareIds.has(s.submission_id) ? 'selected' : ''}" data-id="${s.submission_id}">
                    <input type="checkbox" ${this._wpCompareIds.has(s.submission_id) ? 'checked' : ''}>
                    ${Utils.escapeHtml(Utils.truncate(s.title, 25))}
                </label>
            `).join('');

            const html = `
                ${this._refreshIndicatorHtml()}
                <div class="page-header">
                    <h2>Compare WP Submissions</h2>
                    <div>
                        <select class="filter-select" id="compare-metric">
                            <option value="reads" ${this._wpCompareMetric === 'reads' ? 'selected' : ''}>Reads</option>
                            <option value="votes" ${this._wpCompareMetric === 'votes' ? 'selected' : ''}>Votes</option>
                            <option value="comments_count" ${this._wpCompareMetric === 'comments_count' ? 'selected' : ''}>Comments</option>
                            <option value="num_lists" ${this._wpCompareMetric === 'num_lists' ? 'selected' : ''}>Lists</option>
                        </select>
                    </div>
                </div>
                <p style="font-size:13px;color:var(--text-muted);margin-bottom:12px">Select 2-5 WP submissions to compare their trends over time.</p>
                <div class="compare-select">${chips}</div>

                ${Components.dateRangeBar(this._dateRange)}

                <div class="chart-container" id="compare-chart-container" style="${this._wpCompareIds.size < 2 ? 'display:none' : ''}">
                    <h3>Comparison</h3>
                    <div class="chart-wrap"><canvas id="chart-compare"></canvas></div>
                </div>
                ${this._wpCompareIds.size < 2 ? '<div class="empty-state"><p>Select at least 2 submissions above to see their trends compared.</p></div>' : ''}
            `;

            this._setContent(html);

            document.querySelectorAll('.compare-chip').forEach(chip => {
                chip.addEventListener('click', (e) => {
                    e.preventDefault();
                    const id = parseInt(chip.dataset.id);
                    if (this._wpCompareIds.has(id)) {
                        this._wpCompareIds.delete(id);
                    } else if (this._wpCompareIds.size < 5) {
                        this._wpCompareIds.add(id);
                    }
                    this.renderWPCompare();
                });
            });

            const metricSelect = document.getElementById('compare-metric');
            if (metricSelect) {
                metricSelect.addEventListener('change', () => {
                    this._wpCompareMetric = metricSelect.value;
                    this._loadWPComparisonChart();
                });
            }

            this._bindDateRange(() => this._loadWPComparisonChart());

            if (this._wpCompareIds.size >= 2) {
                await this._loadWPComparisonChart();
            }

            this._startAutoRefresh(() => this.renderWPCompare());
        } catch (err) {
            this._setContent(`<div class="empty-state"><h3>Error</h3><p>${Utils.escapeHtml(err.message)}</p></div>`);
        }
    },

    async _loadWPComparisonChart() {
        try {
            if (this._wpCompareIds.size < 2) return;
            const range = Utils.getDateRange(this._dateRange);
            const data = await API.getWPComparison([...this._wpCompareIds], range);
            const container = document.getElementById('compare-chart-container');
            if (container) container.style.display = '';
            Charts.comparisonLine('chart-compare', data.series, data.titles, this._wpCompareMetric);
        } catch (e) {
            console.error('Failed to load WP comparison chart:', e);
        }
    },

    // ── IK Dashboard ─────────────────────────────────────────
    // Itaku dashboard with Likes, Comments, Reshares stat cards (NO views).

    async renderIKDashboard() {
        this._loading();
        try {
            const [summary, agg, pins, goals] = await Promise.all([
                API.getIKSummary(),
                API.getIKAggregate(Utils.getDateRange(this._dateRange)),
                API.getPins().catch(() => ({ pins: [] })),
                API.getGoals().catch(() => ({ goals: [] })),
            ]);
            const ikPins = (pins.pins || []).filter(p => p.platform === 'ik');
            const ikGoals = (goals.goals || []).filter(g => g.platform === 'ik' || g.platform === 'all');

            const html = `
                ${this._refreshIndicatorHtml()}
                <div class="page-header">
                    <h2>Itaku Dashboard</h2>
                    <button class="btn btn-secondary" onclick="API.exportSubmissions('ik')">Export CSV</button>
                </div>

                ${ikPins.length ? Components.pinnedSubmissions(ikPins, 'ik') : ''}
                ${ikGoals.length ? `<div class="goals-section"><h3>Goals</h3>${Components.goalProgressCards(ikGoals)}</div>` : ''}

                <div class="stats-grid">
                    ${Components.statCard('Total Submissions', summary.total_submissions)}
                    ${Components.statCard('Total Likes', summary.total_likes || 0)}
                    ${Components.statCard('Total Comments', summary.total_comments)}
                    ${Components.statCard('Total Reshares', summary.total_reshares || 0)}
                </div>

                ${summary.growth_rates ? (() => {
                    const rates = {};
                    for (const period of ['24h', '7d', '30d']) {
                        const r = summary.growth_rates[period];
                        if (r) {
                            rates[period] = {
                                views_per_day: r.likes_per_day != null ? r.likes_per_day : 0,
                                faves_per_day: r.reshares_per_day != null ? r.reshares_per_day : 0,
                                comments_per_day: r.comments_per_day,
                            };
                        }
                    }
                    return Components.growthRateCards(rates, { views: 'likes/day', faves: 'reshares/day', comments: 'comments/day' });
                })() : ''}

                ${Components.dateRangeBar(this._dateRange)}

                <div class="chart-container">
                    <h3>Likes Over Time (Aggregate)</h3>
                    <div class="chart-wrap"><canvas id="chart-agg-likes"></canvas></div>
                </div>

                <div class="chart-row">
                    <div class="chart-container">
                        <h3>Top Liked</h3>
                        ${Components.ikTopList(summary.top_liked || summary.top_faved, 'likes', 'title', 'submission_id')}
                    </div>
                    <div class="chart-container">
                        <h3>Top Reshared</h3>
                        ${Components.ikTopList(summary.top_reshared, 'reshares', 'title', 'submission_id')}
                    </div>
                </div>

                <div class="chart-row">
                    <div class="chart-container">
                        <h3>Fastest Growing (24h)</h3>
                        ${Components.ikTopList(summary.fastest_growing, 'likes_gained', 'title', 'submission_id')}
                    </div>
                </div>
            `;

            this._setContent(html);

            if (agg.snapshots && agg.snapshots.length > 0) {
                Charts.aggregateLine('chart-agg-likes', agg.snapshots, ['likes']);
            }

            this._bindDateRange(() => this.renderIKDashboard());
            this._bindPinAndGoalActions(() => this.renderIKDashboard());
            this._startAutoRefresh(() => this.renderIKDashboard());
        } catch (err) {
            this._setContent(`<div class="empty-state"><h3>Error loading IK dashboard</h3><p>${Utils.escapeHtml(err.message)}</p></div>`);
        }
    },

    // ── IK Submissions ─────────────────────────────────────────
    // Itaku submissions table with Type, Likes, Comments, Reshares columns (no views).

    async renderIKSubmissions() {
        this._loading();
        try {
            const data = await API.getIKSubmissions({
                sort_by: this._ikSortState.field,
                order: this._ikSortState.order,
            });

            const _vm = localStorage.getItem('pp-view-mode') || 'grid';
            const gridHtml = Components.submissionCardGrid(data.submissions, {
                idKey: 'submission_id', titleKey: 'title', thumbKey: null,
                detailRoute: '/ik/submission', dateKey: 'posted_at',
                stats: [
                    { key: 'likes', deltaKey: 'likes_delta', label: 'likes' },
                    { key: 'comments_count', deltaKey: 'comments_delta', label: 'comments' },
                    { key: 'reshares', deltaKey: 'reshares_delta', label: 'reshares' },
                ],
            });
            const html = `
                ${this._refreshIndicatorHtml()}
                <div class="page-header"><h2>IK Submissions</h2></div>
                <div class="toolbar">
                    <input type="text" class="search-input" id="search-input" placeholder="Search titles...">
                    <div class="view-toggle">
                        <button class="view-toggle-btn ${_vm === 'grid' ? 'active' : ''}" data-view="grid" title="Grid view">&#9638;</button>
                        <button class="view-toggle-btn ${_vm === 'list' ? 'active' : ''}" data-view="list" title="List view">&#9776;</button>
                    </div>
                </div>
                <div id="grid-container" style="${_vm !== 'grid' ? 'display:none' : ''}">${gridHtml}</div>
                <div id="table-container" class="table-scroll" style="${_vm !== 'list' ? 'display:none' : ''}">
                    ${Components.ikSubmissionsTable(data.submissions)}
                </div>
            `;

            this._setContent(html);
            this._bindViewToggle();
            this._bindIKTableSort();
            this._bindIKSearch(data.submissions);
            this._startAutoRefresh(() => this.renderIKSubmissions());
        } catch (err) {
            this._setContent(`<div class="empty-state"><h3>Error loading IK submissions</h3><p>${Utils.escapeHtml(err.message)}</p></div>`);
        }
    },

    // ── IK Submission Detail ───────────────────────────────────
    // Individual Itaku submission detail with 3 metrics: likes, comments, reshares (no views).

    async renderIKDetail(id) {
        this._loading();
        try {
            const [data, pins, allTags] = await Promise.all([
                API.getIKSubmission(id),
                API.getPins().catch(() => ({ pins: [] })),
                API.getTags().catch(() => ({ tags: [] })),
            ]);
            const sub = data.submission;
            const isPinned = (pins.pins || []).some(p => p.platform === 'ik' && p.submission_id === id);
            const currentTags = sub.tags || [];

            const html = `
                ${this._refreshIndicatorHtml()}
                <a href="#/ik/submissions" class="back-link">&larr; Back to IK Submissions</a>
                <div class="detail-header">
                    <div class="detail-info">
                        <h2>${Utils.escapeHtml(sub.title)}</h2>
                        <div class="detail-meta">by ${Utils.escapeHtml(sub.username)} &middot; ${Utils.formatDate(sub.posted_at)} &middot; ${Utils.escapeHtml(sub.content_type || 'image')}</div>
                        <div class="detail-meta"><a href="${Utils.escapeHtml(sub.link || '#')}" target="_blank">View on Itaku</a></div>
                        <div class="detail-stats">
                            <div class="detail-stat">${Utils.formatNumber(sub.likes || 0)} <span class="lbl">likes</span></div>
                            <div class="detail-stat">${Utils.formatNumber(sub.comments_count || 0)} <span class="lbl">comments</span></div>
                            <div class="detail-stat">${Utils.formatNumber(sub.reshares || 0)} <span class="lbl">reshares</span></div>
                        </div>
                        <div style="margin-top:8px;display:flex;gap:8px;align-items:center;flex-wrap:wrap">
                            <button class="btn ${isPinned ? 'btn-danger' : 'btn-secondary'} btn-pin" data-platform="ik" data-id="${id}" style="padding:4px 10px;font-size:12px">${isPinned ? 'Unpin' : 'Pin'}</button>
                            ${currentTags.map(t => Components.tagBadge(t)).join('')}
                            <button class="btn btn-secondary btn-add-tag" data-platform="ik" data-id="${id}" style="padding:4px 10px;font-size:12px">+ Tag</button>
                        </div>
                        <div style="margin-top:8px">${Components.keywords(sub.keywords)}</div>
                    </div>
                </div>

                ${Components.growthRateCards(data.growth_rates, { views: 'likes/day', faves: 'reshares/day', comments: 'comments/day' })}

                ${Components.dateRangeBar(this._dateRange)}

                <div class="chart-container">
                    <h3>Stats Over Time</h3>
                    <div class="chart-wrap"><canvas id="chart-detail"></canvas></div>
                </div>
            `;

            this._setContent(html);

            if (data.snapshots && data.snapshots.length > 0) {
                Charts.submissionLine('chart-detail', data.snapshots, ['likes', 'comments_count', 'reshares']);
            }

            this._bindDateRange(async () => {
                const range = Utils.getDateRange(this._dateRange);
                const snaps = await API.getIKSnapshots(id, range);
                Charts.submissionLine('chart-detail', snaps.snapshots, ['likes', 'comments_count', 'reshares']);
            });

            this._bindDetailPinTag('ik', id, allTags.tags || [], () => this.renderIKDetail(id));
            this._startAutoRefresh(() => this.renderIKDetail(id));
        } catch (err) {
            this._setContent(`<div class="empty-state"><h3>Error loading IK submission</h3><p>${Utils.escapeHtml(err.message)}</p></div>`);
        }
    },

    // ── IK Compare ─────────────────────────────────────────────
    // Itaku comparison page with likes, comments_count, reshares metrics (no views).

    async renderIKCompare() {
        this._loading();
        try {
            const data = await API.getIKSubmissions({ sort_by: 'likes', order: 'desc' });
            const subs = data.submissions;

            const chips = subs.map(s => `
                <label class="compare-chip ${this._ikCompareIds.has(s.submission_id) ? 'selected' : ''}" data-id="${s.submission_id}">
                    <input type="checkbox" ${this._ikCompareIds.has(s.submission_id) ? 'checked' : ''}>
                    ${Utils.escapeHtml(Utils.truncate(s.title, 25))}
                </label>
            `).join('');

            const html = `
                ${this._refreshIndicatorHtml()}
                <div class="page-header">
                    <h2>Compare IK Submissions</h2>
                    <div>
                        <select class="filter-select" id="compare-metric">
                            <option value="likes" ${this._ikCompareMetric === 'likes' ? 'selected' : ''}>Likes</option>
                            <option value="comments_count" ${this._ikCompareMetric === 'comments_count' ? 'selected' : ''}>Comments</option>
                            <option value="reshares" ${this._ikCompareMetric === 'reshares' ? 'selected' : ''}>Reshares</option>
                        </select>
                    </div>
                </div>
                <p style="font-size:13px;color:var(--text-muted);margin-bottom:12px">Select 2-5 IK submissions to compare their trends over time.</p>
                <div class="compare-select">${chips}</div>

                ${Components.dateRangeBar(this._dateRange)}

                <div class="chart-container" id="compare-chart-container" style="${this._ikCompareIds.size < 2 ? 'display:none' : ''}">
                    <h3>Comparison</h3>
                    <div class="chart-wrap"><canvas id="chart-compare"></canvas></div>
                </div>
                ${this._ikCompareIds.size < 2 ? '<div class="empty-state"><p>Select at least 2 submissions above to see their trends compared.</p></div>' : ''}
            `;

            this._setContent(html);

            document.querySelectorAll('.compare-chip').forEach(chip => {
                chip.addEventListener('click', (e) => {
                    e.preventDefault();
                    const id = parseInt(chip.dataset.id);
                    if (this._ikCompareIds.has(id)) {
                        this._ikCompareIds.delete(id);
                    } else if (this._ikCompareIds.size < 5) {
                        this._ikCompareIds.add(id);
                    }
                    this.renderIKCompare();
                });
            });

            const metricSelect = document.getElementById('compare-metric');
            if (metricSelect) {
                metricSelect.addEventListener('change', () => {
                    this._ikCompareMetric = metricSelect.value;
                    this._loadIKComparisonChart();
                });
            }

            this._bindDateRange(() => this._loadIKComparisonChart());

            if (this._ikCompareIds.size >= 2) {
                await this._loadIKComparisonChart();
            }

            this._startAutoRefresh(() => this.renderIKCompare());
        } catch (err) {
            this._setContent(`<div class="empty-state"><h3>Error</h3><p>${Utils.escapeHtml(err.message)}</p></div>`);
        }
    },

    async _loadIKComparisonChart() {
        try {
            if (this._ikCompareIds.size < 2) return;
            const range = Utils.getDateRange(this._dateRange);
            const data = await API.getIKComparison([...this._ikCompareIds], range);
            const container = document.getElementById('compare-chart-container');
            if (container) container.style.display = '';
            Charts.comparisonLine('chart-compare', data.series, data.titles, this._ikCompareMetric);
        } catch (e) {
            console.error('Failed to load IK comparison chart:', e);
        }
    },

    // ── BSKY Dashboard ─────────────────────────────────────────
    // Bluesky dashboard with Likes, Reposts, Replies, Quotes stat cards (NO views).

    async renderBSKYDashboard() {
        this._loading();
        try {
            const [summary, agg, pins, goals] = await Promise.all([
                API.getBSKYSummary(),
                API.getBSKYAggregate(Utils.getDateRange(this._dateRange)),
                API.getPins().catch(() => ({ pins: [] })),
                API.getGoals().catch(() => ({ goals: [] })),
            ]);
            const bskyPins = (pins.pins || []).filter(p => p.platform === 'bsky');
            const bskyGoals = (goals.goals || []).filter(g => g.platform === 'bsky' || g.platform === 'all');

            const html = `
                ${this._refreshIndicatorHtml()}
                <div class="page-header">
                    <h2>Bluesky Dashboard</h2>
                    <button class="btn btn-secondary" onclick="API.exportSubmissions('bsky')">Export CSV</button>
                </div>

                ${bskyPins.length ? Components.pinnedSubmissions(bskyPins, 'bsky') : ''}
                ${bskyGoals.length ? `<div class="goals-section"><h3>Goals</h3>${Components.goalProgressCards(bskyGoals)}</div>` : ''}

                <div class="stats-grid">
                    ${Components.statCard('Total Posts', summary.total_submissions)}
                    ${Components.statCard('Total Likes', summary.total_likes || 0)}
                    ${Components.statCard('Total Reposts', summary.total_reposts || 0)}
                    ${Components.statCard('Total Replies', summary.total_comments || summary.total_replies || 0)}
                    ${Components.statCard('Total Quotes', summary.total_quotes || 0)}
                </div>

                ${summary.growth_rates ? (() => {
                    const rates = {};
                    for (const period of ['24h', '7d', '30d']) {
                        const r = summary.growth_rates[period];
                        if (r) {
                            rates[period] = {
                                views_per_day: r.likes_per_day != null ? r.likes_per_day : 0,
                                faves_per_day: r.reposts_per_day != null ? r.reposts_per_day : 0,
                                comments_per_day: r.comments_per_day || r.replies_per_day || 0,
                            };
                        }
                    }
                    return Components.growthRateCards(rates, { views: 'likes/day', faves: 'reposts/day', comments: 'replies/day' });
                })() : ''}

                ${Components.dateRangeBar(this._dateRange)}

                <div class="chart-container">
                    <h3>Likes Over Time (Aggregate)</h3>
                    <div class="chart-wrap"><canvas id="chart-agg-likes"></canvas></div>
                </div>

                <div class="chart-row">
                    <div class="chart-container">
                        <h3>Top Liked</h3>
                        ${Components.bskyTopList(summary.top_liked || summary.top_faved, 'likes', 'title', 'submission_id')}
                    </div>
                    <div class="chart-container">
                        <h3>Top Reposted</h3>
                        ${Components.bskyTopList(summary.top_reposted, 'reposts', 'title', 'submission_id')}
                    </div>
                </div>

                <div class="chart-row">
                    <div class="chart-container">
                        <h3>Fastest Growing (24h)</h3>
                        ${Components.bskyTopList(summary.fastest_growing, 'likes_gained', 'title', 'submission_id')}
                    </div>
                </div>
            `;

            this._setContent(html);

            if (agg.snapshots && agg.snapshots.length > 0) {
                Charts.aggregateLine('chart-agg-likes', agg.snapshots, ['likes']);
            }

            this._bindDateRange(() => this.renderBSKYDashboard());
            this._bindPinAndGoalActions(() => this.renderBSKYDashboard());
            this._startAutoRefresh(() => this.renderBSKYDashboard());
        } catch (err) {
            this._setContent(`<div class="empty-state"><h3>Error loading BSKY dashboard</h3><p>${Utils.escapeHtml(err.message)}</p></div>`);
        }
    },

    // ── BSKY Submissions ─────────────────────────────────────────

    async renderBSKYSubmissions() {
        this._loading();
        try {
            const data = await API.getBSKYSubmissions({
                sort_by: this._bskySortState.field,
                order: this._bskySortState.order,
            });

            const _vm = localStorage.getItem('pp-view-mode') || 'grid';
            // BSKY uses rkey (last segment of submission_id URI) for routing
            const bskyGridSubs = data.submissions.map(s => ({
                ...s, _rkey: String(s.submission_id).split('/').pop()
            }));
            const gridHtml = Components.submissionCardGrid(bskyGridSubs, {
                idKey: '_rkey', titleKey: 'title', thumbKey: null,
                detailRoute: '/bsky/submission', dateKey: 'posted_at',
                stats: [
                    { key: 'likes', deltaKey: 'likes_delta', label: 'likes' },
                    { key: 'reposts', deltaKey: 'reposts_delta', label: 'reposts' },
                    { key: 'replies', deltaKey: 'replies_delta', label: 'replies' },
                ],
            });
            const html = `
                ${this._refreshIndicatorHtml()}
                <div class="page-header"><h2>Bluesky Posts</h2></div>
                <div class="toolbar">
                    <input type="text" class="search-input" id="search-input" placeholder="Search posts...">
                    <div class="view-toggle">
                        <button class="view-toggle-btn ${_vm === 'grid' ? 'active' : ''}" data-view="grid" title="Grid view">&#9638;</button>
                        <button class="view-toggle-btn ${_vm === 'list' ? 'active' : ''}" data-view="list" title="List view">&#9776;</button>
                    </div>
                </div>
                <div id="grid-container" style="${_vm !== 'grid' ? 'display:none' : ''}">${gridHtml}</div>
                <div id="table-container" class="table-scroll" style="${_vm !== 'list' ? 'display:none' : ''}">
                    ${Components.bskySubmissionsTable(data.submissions)}
                </div>
            `;

            this._setContent(html);
            this._bindViewToggle();
            this._bindBSKYTableSort();
            this._bindBSKYSearch(data.submissions);
            this._startAutoRefresh(() => this.renderBSKYSubmissions());
        } catch (err) {
            this._setContent(`<div class="empty-state"><h3>Error loading BSKY submissions</h3><p>${Utils.escapeHtml(err.message)}</p></div>`);
        }
    },

    // ── BSKY Submission Detail ───────────────────────────────────

    async renderBSKYDetail(rkey) {
        this._loading();
        try {
            const [data, pins, allTags] = await Promise.all([
                API.getBSKYSubmission(rkey),
                API.getPins().catch(() => ({ pins: [] })),
                API.getTags().catch(() => ({ tags: [] })),
            ]);
            const sub = data.submission;
            const fullId = sub.submission_id;
            const isPinned = (pins.pins || []).some(p => p.platform === 'bsky' && String(p.submission_id) === String(fullId));
            const currentTags = sub.tags || [];

            const html = `
                ${this._refreshIndicatorHtml()}
                <a href="#/bsky/submissions" class="back-link">&larr; Back to Bluesky Posts</a>
                <div class="detail-header">
                    <div class="detail-info">
                        <h2>${Utils.escapeHtml(sub.title)}</h2>
                        <div class="detail-meta">by ${Utils.escapeHtml(sub.username)} &middot; ${Utils.formatDate(sub.posted_at)}</div>
                        <div class="detail-meta"><a href="${Utils.escapeHtml(sub.link || '#')}" target="_blank">View on Bluesky</a></div>
                        <div class="detail-stats">
                            <div class="detail-stat">${Utils.formatNumber(sub.likes || 0)} <span class="lbl">likes</span></div>
                            <div class="detail-stat">${Utils.formatNumber(sub.reposts || 0)} <span class="lbl">reposts</span></div>
                            <div class="detail-stat">${Utils.formatNumber(sub.replies || 0)} <span class="lbl">replies</span></div>
                            <div class="detail-stat">${Utils.formatNumber(sub.quotes || 0)} <span class="lbl">quotes</span></div>
                        </div>
                        <div style="margin-top:8px;display:flex;gap:8px;align-items:center;flex-wrap:wrap">
                            <button class="btn ${isPinned ? 'btn-danger' : 'btn-secondary'} btn-pin" data-platform="bsky" data-id="${Utils.escapeHtml(fullId)}" style="padding:4px 10px;font-size:12px">${isPinned ? 'Unpin' : 'Pin'}</button>
                            ${currentTags.map(t => Components.tagBadge(t)).join('')}
                            <button class="btn btn-secondary btn-add-tag" data-platform="bsky" data-id="${Utils.escapeHtml(fullId)}" style="padding:4px 10px;font-size:12px">+ Tag</button>
                        </div>
                        <div style="margin-top:8px">${Components.keywords(sub.keywords)}</div>
                    </div>
                </div>

                ${Components.growthRateCards(data.growth_rates, { views: 'likes/day', faves: 'reposts/day', comments: 'replies/day' })}

                ${Components.dateRangeBar(this._dateRange)}

                <div class="chart-container">
                    <h3>Stats Over Time</h3>
                    <div class="chart-wrap"><canvas id="chart-detail"></canvas></div>
                </div>
            `;

            this._setContent(html);

            if (data.snapshots && data.snapshots.length > 0) {
                Charts.submissionLine('chart-detail', data.snapshots, ['likes', 'reposts', 'replies', 'quotes']);
            }

            this._bindDateRange(async () => {
                const range = Utils.getDateRange(this._dateRange);
                const snaps = await API.getBSKYSnapshots(rkey, range);
                Charts.submissionLine('chart-detail', snaps.snapshots, ['likes', 'reposts', 'replies', 'quotes']);
            });

            this._bindDetailPinTag('bsky', fullId, allTags.tags || [], () => this.renderBSKYDetail(rkey));
            this._startAutoRefresh(() => this.renderBSKYDetail(rkey));
        } catch (err) {
            this._setContent(`<div class="empty-state"><h3>Error loading BSKY post</h3><p>${Utils.escapeHtml(err.message)}</p></div>`);
        }
    },

    // ── BSKY Compare ─────────────────────────────────────────────

    async renderBSKYCompare() {
        this._loading();
        try {
            const data = await API.getBSKYSubmissions({ sort_by: 'likes', order: 'desc' });
            const subs = data.submissions;

            const chips = subs.map(s => {
                const rkey = String(s.submission_id).split('/').pop();
                return `
                <label class="compare-chip ${this._bskyCompareIds.has(rkey) ? 'selected' : ''}" data-id="${rkey}" data-full-id="${Utils.escapeHtml(s.submission_id)}">
                    <input type="checkbox" ${this._bskyCompareIds.has(rkey) ? 'checked' : ''}>
                    ${Utils.escapeHtml(Utils.truncate(s.title, 25))}
                </label>
            `;
            }).join('');

            const html = `
                ${this._refreshIndicatorHtml()}
                <div class="page-header">
                    <h2>Compare Bluesky Posts</h2>
                    <div>
                        <select class="filter-select" id="compare-metric">
                            <option value="likes" ${this._bskyCompareMetric === 'likes' ? 'selected' : ''}>Likes</option>
                            <option value="reposts" ${this._bskyCompareMetric === 'reposts' ? 'selected' : ''}>Reposts</option>
                            <option value="replies" ${this._bskyCompareMetric === 'replies' ? 'selected' : ''}>Replies</option>
                            <option value="quotes" ${this._bskyCompareMetric === 'quotes' ? 'selected' : ''}>Quotes</option>
                        </select>
                    </div>
                </div>
                <p style="font-size:13px;color:var(--text-muted);margin-bottom:12px">Select 2-5 Bluesky posts to compare their trends over time.</p>
                <div class="compare-select">${chips}</div>

                ${Components.dateRangeBar(this._dateRange)}

                <div class="chart-container" id="compare-chart-container" style="${this._bskyCompareIds.size < 2 ? 'display:none' : ''}">
                    <h3>Comparison</h3>
                    <div class="chart-wrap"><canvas id="chart-compare"></canvas></div>
                </div>
                ${this._bskyCompareIds.size < 2 ? '<div class="empty-state"><p>Select at least 2 posts above to see their trends compared.</p></div>' : ''}
            `;

            this._setContent(html);

            document.querySelectorAll('.compare-chip').forEach(chip => {
                chip.addEventListener('click', (e) => {
                    e.preventDefault();
                    const id = chip.dataset.id;
                    if (this._bskyCompareIds.has(id)) {
                        this._bskyCompareIds.delete(id);
                    } else if (this._bskyCompareIds.size < 5) {
                        this._bskyCompareIds.add(id);
                    }
                    this.renderBSKYCompare();
                });
            });

            const metricSelect = document.getElementById('compare-metric');
            if (metricSelect) {
                metricSelect.addEventListener('change', () => {
                    this._bskyCompareMetric = metricSelect.value;
                    this._loadBSKYComparisonChart();
                });
            }

            this._bindDateRange(() => this._loadBSKYComparisonChart());

            if (this._bskyCompareIds.size >= 2) {
                await this._loadBSKYComparisonChart();
            }

            this._startAutoRefresh(() => this.renderBSKYCompare());
        } catch (err) {
            this._setContent(`<div class="empty-state"><h3>Error</h3><p>${Utils.escapeHtml(err.message)}</p></div>`);
        }
    },

    async _loadBSKYComparisonChart() {
        try {
            if (this._bskyCompareIds.size < 2) return;
            const range = Utils.getDateRange(this._dateRange);
            const data = await API.getBSKYComparison([...this._bskyCompareIds], range);
            const container = document.getElementById('compare-chart-container');
            if (container) container.style.display = '';
            Charts.comparisonLine('chart-compare', data.series, data.titles, this._bskyCompareMetric);
        } catch (e) {
            console.error('Failed to load BSKY comparison chart:', e);
        }
    },

    // ── TW Dashboard ─────────────────────────────────────────
    // X/Twitter dashboard with Views, Likes, Retweets, Replies, Quotes, Bookmarks.

    async renderTWDashboard() {
        this._loading();
        try {
            const [summary, agg, pins, goals] = await Promise.all([
                API.getTWSummary(),
                API.getTWAggregate(Utils.getDateRange(this._dateRange)),
                API.getPins().catch(() => ({ pins: [] })),
                API.getGoals().catch(() => ({ goals: [] })),
            ]);
            const twPins = (pins.pins || []).filter(p => p.platform === 'tw');
            const twGoals = (goals.goals || []).filter(g => g.platform === 'tw' || g.platform === 'all');

            const html = `
                ${this._refreshIndicatorHtml()}
                <div class="page-header">
                    <h2>X/Twitter Dashboard</h2>
                    <button class="btn btn-secondary" onclick="API.exportSubmissions('tw')">Export CSV</button>
                </div>

                ${twPins.length ? Components.pinnedSubmissions(twPins, 'tw') : ''}
                ${twGoals.length ? `<div class="goals-section"><h3>Goals</h3>${Components.goalProgressCards(twGoals)}</div>` : ''}

                <div class="stats-grid">
                    ${Components.statCard('Total Tweets', summary.total_submissions)}
                    ${Components.statCard('Total Views', summary.total_views || 0)}
                    ${Components.statCard('Total Likes', summary.total_likes || 0)}
                    ${Components.statCard('Total Retweets', summary.total_retweets || 0)}
                    ${Components.statCard('Total Replies', summary.total_comments || summary.total_replies || 0)}
                    ${Components.statCard('Total Quotes', summary.total_quotes || 0)}
                    ${Components.statCard('Total Bookmarks', summary.total_bookmarks || 0)}
                </div>

                ${summary.growth_rates ? (() => {
                    const rates = {};
                    for (const period of ['24h', '7d', '30d']) {
                        const r = summary.growth_rates[period];
                        if (r) {
                            rates[period] = {
                                views_per_day: r.views_per_day != null ? r.views_per_day : 0,
                                faves_per_day: r.likes_per_day != null ? r.likes_per_day : 0,
                                comments_per_day: r.comments_per_day || r.replies_per_day || 0,
                            };
                        }
                    }
                    return Components.growthRateCards(rates, { views: 'views/day', faves: 'likes/day', comments: 'replies/day' });
                })() : ''}

                ${Components.dateRangeBar(this._dateRange)}

                <div class="chart-container">
                    <h3>Views Over Time (Aggregate)</h3>
                    <div class="chart-wrap"><canvas id="chart-agg-views"></canvas></div>
                </div>

                <div class="chart-row">
                    <div class="chart-container">
                        <h3>Top Viewed</h3>
                        ${Components.twTopList(summary.top_viewed, 'views', 'title', 'submission_id')}
                    </div>
                    <div class="chart-container">
                        <h3>Top Liked</h3>
                        ${Components.twTopList(summary.top_liked || summary.top_faved, 'likes', 'title', 'submission_id')}
                    </div>
                </div>

                <div class="chart-row">
                    <div class="chart-container">
                        <h3>Top Retweeted</h3>
                        ${Components.twTopList(summary.top_retweeted, 'retweets', 'title', 'submission_id')}
                    </div>
                    <div class="chart-container">
                        <h3>Fastest Growing (24h)</h3>
                        ${Components.twTopList(summary.fastest_growing, 'views_gained', 'title', 'submission_id')}
                    </div>
                </div>
            `;

            this._setContent(html);

            if (agg.snapshots && agg.snapshots.length > 0) {
                Charts.aggregateLine('chart-agg-views', agg.snapshots, ['views']);
            }

            this._bindDateRange(() => this.renderTWDashboard());
            this._bindPinAndGoalActions(() => this.renderTWDashboard());
            this._startAutoRefresh(() => this.renderTWDashboard());
        } catch (err) {
            this._setContent(`<div class="empty-state"><h3>Error loading TW dashboard</h3><p>${Utils.escapeHtml(err.message)}</p></div>`);
        }
    },

    // ── TW Submissions ─────────────────────────────────────────

    async renderTWSubmissions() {
        this._loading();
        try {
            const data = await API.getTWSubmissions({
                sort_by: this._twSortState.field,
                order: this._twSortState.order,
            });

            const _vm = localStorage.getItem('pp-view-mode') || 'grid';
            const gridHtml = Components.submissionCardGrid(data.submissions, {
                idKey: 'submission_id', titleKey: 'title', thumbKey: null,
                detailRoute: '/tw/submission', dateKey: 'posted_at',
                stats: [
                    { key: 'views', deltaKey: 'views_delta', label: 'views' },
                    { key: 'likes', deltaKey: 'likes_delta', label: 'likes' },
                    { key: 'retweets', deltaKey: 'retweets_delta', label: 'retweets' },
                ],
            });
            const html = `
                ${this._refreshIndicatorHtml()}
                <div class="page-header"><h2>X/Twitter Tweets</h2></div>
                <div class="toolbar">
                    <input type="text" class="search-input" id="search-input" placeholder="Search tweets...">
                    <div class="view-toggle">
                        <button class="view-toggle-btn ${_vm === 'grid' ? 'active' : ''}" data-view="grid" title="Grid view">&#9638;</button>
                        <button class="view-toggle-btn ${_vm === 'list' ? 'active' : ''}" data-view="list" title="List view">&#9776;</button>
                    </div>
                </div>
                <div id="grid-container" style="${_vm !== 'grid' ? 'display:none' : ''}">${gridHtml}</div>
                <div id="table-container" class="table-scroll" style="${_vm !== 'list' ? 'display:none' : ''}">
                    ${Components.twSubmissionsTable(data.submissions)}
                </div>
            `;

            this._setContent(html);
            this._bindViewToggle();
            this._bindTWTableSort();
            this._bindTWSearch(data.submissions);
            this._startAutoRefresh(() => this.renderTWSubmissions());
        } catch (err) {
            this._setContent(`<div class="empty-state"><h3>Error loading TW submissions</h3><p>${Utils.escapeHtml(err.message)}</p></div>`);
        }
    },

    // ── TW Submission Detail ───────────────────────────────────

    async renderTWDetail(id) {
        this._loading();
        try {
            const [data, pins, allTags] = await Promise.all([
                API.getTWSubmission(id),
                API.getPins().catch(() => ({ pins: [] })),
                API.getTags().catch(() => ({ tags: [] })),
            ]);
            const sub = data.submission;
            const isPinned = (pins.pins || []).some(p => p.platform === 'tw' && String(p.submission_id) === String(id));
            const currentTags = sub.tags || [];

            const html = `
                ${this._refreshIndicatorHtml()}
                <a href="#/tw/submissions" class="back-link">&larr; Back to X/Twitter Tweets</a>
                <div class="detail-header">
                    <div class="detail-info">
                        <h2>${Utils.escapeHtml(sub.title)}</h2>
                        <div class="detail-meta">by ${Utils.escapeHtml(sub.username)} &middot; ${Utils.formatDate(sub.posted_at)} &middot; ${Utils.escapeHtml(sub.content_type || 'tweet')}</div>
                        <div class="detail-meta"><a href="${Utils.escapeHtml(sub.link || '#')}" target="_blank">View on X</a></div>
                        <div class="detail-stats">
                            <div class="detail-stat">${Utils.formatNumber(sub.views || 0)} <span class="lbl">views</span></div>
                            <div class="detail-stat">${Utils.formatNumber(sub.likes || 0)} <span class="lbl">likes</span></div>
                            <div class="detail-stat">${Utils.formatNumber(sub.retweets || 0)} <span class="lbl">retweets</span></div>
                            <div class="detail-stat">${Utils.formatNumber(sub.replies || 0)} <span class="lbl">replies</span></div>
                            <div class="detail-stat">${Utils.formatNumber(sub.quotes || 0)} <span class="lbl">quotes</span></div>
                            <div class="detail-stat">${Utils.formatNumber(sub.bookmarks || 0)} <span class="lbl">bookmarks</span></div>
                        </div>
                        <div style="margin-top:8px;display:flex;gap:8px;align-items:center;flex-wrap:wrap">
                            <button class="btn ${isPinned ? 'btn-danger' : 'btn-secondary'} btn-pin" data-platform="tw" data-id="${id}" style="padding:4px 10px;font-size:12px">${isPinned ? 'Unpin' : 'Pin'}</button>
                            ${currentTags.map(t => Components.tagBadge(t)).join('')}
                            <button class="btn btn-secondary btn-add-tag" data-platform="tw" data-id="${id}" style="padding:4px 10px;font-size:12px">+ Tag</button>
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
                Charts.submissionLine('chart-detail', data.snapshots, ['views', 'likes', 'retweets', 'replies']);
            }

            this._bindDateRange(async () => {
                const range = Utils.getDateRange(this._dateRange);
                const snaps = await API.getTWSnapshots(id, range);
                Charts.submissionLine('chart-detail', snaps.snapshots, ['views', 'likes', 'retweets', 'replies']);
            });

            this._bindDetailPinTag('tw', id, allTags.tags || [], () => this.renderTWDetail(id));
            this._startAutoRefresh(() => this.renderTWDetail(id));
        } catch (err) {
            this._setContent(`<div class="empty-state"><h3>Error loading tweet</h3><p>${Utils.escapeHtml(err.message)}</p></div>`);
        }
    },

    // ── TW Compare ─────────────────────────────────────────────

    async renderTWCompare() {
        this._loading();
        try {
            const data = await API.getTWSubmissions({ sort_by: 'views', order: 'desc' });
            const subs = data.submissions;

            const chips = subs.map(s => `
                <label class="compare-chip ${this._twCompareIds.has(s.submission_id) ? 'selected' : ''}" data-id="${s.submission_id}">
                    <input type="checkbox" ${this._twCompareIds.has(s.submission_id) ? 'checked' : ''}>
                    ${Utils.escapeHtml(Utils.truncate(s.title, 25))}
                </label>
            `).join('');

            const html = `
                ${this._refreshIndicatorHtml()}
                <div class="page-header">
                    <h2>Compare X/Twitter Tweets</h2>
                    <div>
                        <select class="filter-select" id="compare-metric">
                            <option value="views" ${this._twCompareMetric === 'views' ? 'selected' : ''}>Views</option>
                            <option value="likes" ${this._twCompareMetric === 'likes' ? 'selected' : ''}>Likes</option>
                            <option value="retweets" ${this._twCompareMetric === 'retweets' ? 'selected' : ''}>Retweets</option>
                            <option value="replies" ${this._twCompareMetric === 'replies' ? 'selected' : ''}>Replies</option>
                            <option value="quotes" ${this._twCompareMetric === 'quotes' ? 'selected' : ''}>Quotes</option>
                            <option value="bookmarks" ${this._twCompareMetric === 'bookmarks' ? 'selected' : ''}>Bookmarks</option>
                        </select>
                    </div>
                </div>
                <p style="font-size:13px;color:var(--text-muted);margin-bottom:12px">Select 2-5 tweets to compare their trends over time.</p>
                <div class="compare-select">${chips}</div>

                ${Components.dateRangeBar(this._dateRange)}

                <div class="chart-container" id="compare-chart-container" style="${this._twCompareIds.size < 2 ? 'display:none' : ''}">
                    <h3>Comparison</h3>
                    <div class="chart-wrap"><canvas id="chart-compare"></canvas></div>
                </div>
                ${this._twCompareIds.size < 2 ? '<div class="empty-state"><p>Select at least 2 tweets above to see their trends compared.</p></div>' : ''}
            `;

            this._setContent(html);

            document.querySelectorAll('.compare-chip').forEach(chip => {
                chip.addEventListener('click', (e) => {
                    e.preventDefault();
                    const id = chip.dataset.id;
                    if (this._twCompareIds.has(id)) {
                        this._twCompareIds.delete(id);
                    } else if (this._twCompareIds.size < 5) {
                        this._twCompareIds.add(id);
                    }
                    this.renderTWCompare();
                });
            });

            const metricSelect = document.getElementById('compare-metric');
            if (metricSelect) {
                metricSelect.addEventListener('change', () => {
                    this._twCompareMetric = metricSelect.value;
                    this._loadTWComparisonChart();
                });
            }

            this._bindDateRange(() => this._loadTWComparisonChart());

            if (this._twCompareIds.size >= 2) {
                await this._loadTWComparisonChart();
            }

            this._startAutoRefresh(() => this.renderTWCompare());
        } catch (err) {
            this._setContent(`<div class="empty-state"><h3>Error</h3><p>${Utils.escapeHtml(err.message)}</p></div>`);
        }
    },

    async _loadTWComparisonChart() {
        try {
            if (this._twCompareIds.size < 2) return;
            const range = Utils.getDateRange(this._dateRange);
            const data = await API.getTWComparison([...this._twCompareIds], range);
            const container = document.getElementById('compare-chart-container');
            if (container) container.style.display = '';
            Charts.comparisonLine('chart-compare', data.series, data.titles, this._twCompareMetric);
        } catch (e) {
            console.error('Failed to load TW comparison chart:', e);
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
                const badgeMap = { fa: '<span class="platform-badge fa">FA</span>', ws: '<span class="platform-badge ws">WS</span>', sf: '<span class="platform-badge sf">SF</span>', sqw: '<span class="platform-badge sqw">SqW</span>', ao3: '<span class="platform-badge ao3">AO3</span>', da: '<span class="platform-badge da">DA</span>', wp: '<span class="platform-badge wp">WP</span>', ik: '<span class="platform-badge ik">IK</span>', bsky: '<span class="platform-badge bsky">BSKY</span>', tw: '<span class="platform-badge tw">TW</span>', ib: '<span class="platform-badge ib">IB</span>' };
                const badge = badgeMap[m.platform] || badgeMap.ib;
                const prefixMap = { fa: '/fa/submission/', ws: '/ws/submission/', sf: '/sf/submission/', sqw: '/sqw/submission/', ao3: '/ao3/submission/', da: '/da/submission/', wp: '/wp/submission/', ik: '/ik/submission/', bsky: '/bsky/submission/', tw: '/tw/submission/', ib: '/submission/' };
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
                const platform = prompt('Platform (ib, fa, ws, sf, sqw, ao3, da, wp, ik):');
                if (!platform || !['ib', 'fa', 'ws', 'sf', 'sqw', 'ao3', 'da', 'wp', 'ik'].includes(platform)) { alert('Invalid platform'); return; }
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
            const [status, pollLog, creds, prefs, telegram, pollPausedState, faAuth, faStatus, faPollLog, wsAuth, wsStatus, wsPollLog, sfAuth, sfStatus, sfPollLog, sqwAuth, sqwStatus, sqwPollLog, ao3Auth, ao3Status, ao3PollLog, daAuth, daStatus, daPollLog, wpAuth, wpStatus, wpPollLog, ikAuth, ikStatus, ikPollLog, bskyAuth, bskyStatus, bskyPollLog, twAuth, twStatus, twPollLog, updateInfo] = await Promise.all([
                API.getStatus(),
                API.getPollLog(20),
                API.getCredentials(),
                API.getPreferences(),
                API.getTelegram(),
                API.getPollPaused().catch(() => ({ polling_paused: false })),
                API.getFAAuthStatus().catch(() => ({ has_cookies: false })),
                API.getFAStatus().catch(() => ({})),
                API.getFAPollLog(20).catch(() => ({ polls: [] })),
                API.getWSAuthStatus().catch(() => ({ has_key: false })),
                API.getWSStatus().catch(() => ({})),
                API.getWSPollLog(20).catch(() => ({ polls: [] })),
                API.getSFAuthStatus().catch(() => ({ has_credentials: false })),
                API.getSFStatus().catch(() => ({})),
                API.getSFPollLog(20).catch(() => ({ polls: [] })),
                API.getSQWAuthStatus().catch(() => ({ has_credentials: false })),
                API.getSQWStatus().catch(() => ({})),
                API.getSQWPollLog(20).catch(() => ({ polls: [] })),
                API.getAO3AuthStatus().catch(() => ({ has_credentials: false })),
                API.getAO3Status().catch(() => ({})),
                API.getAO3PollLog(20).catch(() => ({ polls: [] })),
                API.getDAAuthStatus().catch(() => ({ has_credentials: false })),
                API.getDAStatus().catch(() => ({})),
                API.getDAPollLog(20).catch(() => ({ polls: [] })),
                API.getWPAuthStatus().catch(() => ({ has_credentials: false })),
                API.getWPStatus().catch(() => ({})),
                API.getWPPollLog(20).catch(() => ({ polls: [] })),
                API.getIKAuthStatus().catch(() => ({ has_credentials: false })),
                API.getIKStatus().catch(() => ({})),
                API.getIKPollLog(20).catch(() => ({ polls: [] })),
                API.getBSKYAuthStatus().catch(() => ({ has_credentials: false })),
                API.getBSKYStatus().catch(() => ({})),
                API.getBSKYPollLog(20).catch(() => ({ polls: [] })),
                API.getTWAuthStatus().catch(() => ({ has_credentials: false })),
                API.getTWStatus().catch(() => ({})),
                API.getTWPollLog(20).catch(() => ({ polls: [] })),
                API.checkUpdate().catch(() => ({ available: false, current: '?', latest: '?' })),
            ]);

            const lastPoll = status.last_poll;

            const _settingsTab = (window.location.hash.match(/^#\/settings\/(\w+)/) || [])[1] || 'general';

            const html = `
                <div class="page-header">
                    <h2>Settings</h2>
                    <div style="display:flex;gap:8px">
                        <button class="btn btn-success" id="save-all-settings-btn" title="Save all settings on this page">Save Settings</button>
                        <button class="btn btn-primary" id="poll-now-btn">Poll Now</button>
                        <button class="btn btn-secondary" id="full-resync-btn" title="Re-scrape all faves and comments">Full Resync</button>
                        <button class="btn btn-secondary" id="clear-session-btn" title="Clear cached API session">Clear Session</button>
                    </div>
                </div>

                <div class="settings-tabs" id="settings-tabs">
                    <button class="settings-tab ${_settingsTab === 'general' ? 'active' : ''}" data-stab="general">General</button>
                    <button class="settings-tab ${_settingsTab === 'platforms' ? 'active' : ''}" data-stab="platforms">Platforms</button>
                    <button class="settings-tab ${_settingsTab === 'polling' ? 'active' : ''}" data-stab="polling">Polling</button>
                    <button class="settings-tab ${_settingsTab === 'telegram' ? 'active' : ''}" data-stab="telegram">Telegram</button>
                    <button class="settings-tab ${_settingsTab === 'data' ? 'active' : ''}" data-stab="data">Data</button>
                    <button class="settings-tab ${_settingsTab === 'logs' ? 'active' : ''}" data-stab="logs">Logs</button>
                    <button class="settings-tab ${_settingsTab === 'about' ? 'active' : ''}" data-stab="about">About</button>
                </div>

                <!-- ═══ TAB: General ═══ -->
                <div class="settings-tab-content" data-tab-content="general" ${_settingsTab !== 'general' ? 'style="display:none"' : ''}>

                <details class="settings-accordion" open>
                    <summary>Inkbunny Credentials <span class="summary-meta">${creds.username ? '— ' + Utils.escapeHtml(creds.username) : ''}</span></summary>
                    <div class="accordion-body">
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
                </details>

                <details class="settings-accordion" open>
                    <summary>App Preferences</summary>
                    <div class="accordion-body">
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
                    </div>
                </details>

                <details class="settings-accordion">
                    <summary>Poll Intervals <span class="summary-meta">— controls how often each platform is checked</span></summary>
                    <div class="accordion-body">
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
                    <div class="settings-row">
                        <div>
                            <span class="settings-label">SqW poll interval</span>
                            <div style="font-size:11px;color:var(--text-muted);margin-top:2px">How often to check for new SquidgeWorld data</div>
                        </div>
                        <select class="filter-select" id="pref-sqw-poll-interval" style="width:auto">
                            <option value="15" ${prefs.sqw_poll_interval_minutes === 15 ? 'selected' : ''}>15 min</option>
                            <option value="30" ${prefs.sqw_poll_interval_minutes === 30 ? 'selected' : ''}>30 min</option>
                            <option value="60" ${prefs.sqw_poll_interval_minutes === 60 || !prefs.sqw_poll_interval_minutes ? 'selected' : ''}>1 hour</option>
                            <option value="120" ${prefs.sqw_poll_interval_minutes === 120 ? 'selected' : ''}>2 hours</option>
                            <option value="240" ${prefs.sqw_poll_interval_minutes === 240 ? 'selected' : ''}>4 hours</option>
                        </select>
                    </div>
                    <div class="settings-row">
                        <div>
                            <span class="settings-label">AO3 poll interval</span>
                            <div style="font-size:11px;color:var(--text-muted);margin-top:2px">How often to check for new AO3 data</div>
                        </div>
                        <select class="filter-select" id="pref-ao3-poll-interval" style="width:auto">
                            <option value="15" ${prefs.ao3_poll_interval_minutes === 15 ? 'selected' : ''}>15 min</option>
                            <option value="30" ${prefs.ao3_poll_interval_minutes === 30 ? 'selected' : ''}>30 min</option>
                            <option value="60" ${prefs.ao3_poll_interval_minutes === 60 || !prefs.ao3_poll_interval_minutes ? 'selected' : ''}>1 hour</option>
                            <option value="120" ${prefs.ao3_poll_interval_minutes === 120 ? 'selected' : ''}>2 hours</option>
                            <option value="240" ${prefs.ao3_poll_interval_minutes === 240 ? 'selected' : ''}>4 hours</option>
                        </select>
                    </div>
                    <div class="settings-row">
                        <div>
                            <span class="settings-label">DA poll interval</span>
                            <div style="font-size:11px;color:var(--text-muted);margin-top:2px">How often to check for new DeviantArt data</div>
                        </div>
                        <select class="filter-select" id="pref-da-poll-interval" style="width:auto">
                            <option value="15" ${prefs.da_poll_interval_minutes === 15 ? 'selected' : ''}>15 min</option>
                            <option value="30" ${prefs.da_poll_interval_minutes === 30 ? 'selected' : ''}>30 min</option>
                            <option value="60" ${prefs.da_poll_interval_minutes === 60 || !prefs.da_poll_interval_minutes ? 'selected' : ''}>1 hour</option>
                            <option value="120" ${prefs.da_poll_interval_minutes === 120 ? 'selected' : ''}>2 hours</option>
                            <option value="240" ${prefs.da_poll_interval_minutes === 240 ? 'selected' : ''}>4 hours</option>
                        </select>
                    </div>
                    <div class="settings-row">
                        <div>
                            <span class="settings-label">WP poll interval</span>
                            <div style="font-size:11px;color:var(--text-muted);margin-top:2px">How often to check for new Wattpad data</div>
                        </div>
                        <select class="filter-select" id="pref-wp-poll-interval" style="width:auto">
                            <option value="15" ${prefs.wp_poll_interval_minutes === 15 ? 'selected' : ''}>15 min</option>
                            <option value="30" ${prefs.wp_poll_interval_minutes === 30 ? 'selected' : ''}>30 min</option>
                            <option value="60" ${prefs.wp_poll_interval_minutes === 60 || !prefs.wp_poll_interval_minutes ? 'selected' : ''}>1 hour</option>
                            <option value="120" ${prefs.wp_poll_interval_minutes === 120 ? 'selected' : ''}>2 hours</option>
                            <option value="240" ${prefs.wp_poll_interval_minutes === 240 ? 'selected' : ''}>4 hours</option>
                        </select>
                    </div>
                    <div class="settings-row">
                        <div>
                            <span class="settings-label">IK poll interval</span>
                            <div style="font-size:11px;color:var(--text-muted);margin-top:2px">How often to check for new Itaku data</div>
                        </div>
                        <select class="filter-select" id="pref-ik-poll-interval" style="width:auto">
                            <option value="15" ${prefs.ik_poll_interval_minutes === 15 ? 'selected' : ''}>15 min</option>
                            <option value="30" ${prefs.ik_poll_interval_minutes === 30 ? 'selected' : ''}>30 min</option>
                            <option value="60" ${prefs.ik_poll_interval_minutes === 60 || !prefs.ik_poll_interval_minutes ? 'selected' : ''}>1 hour</option>
                            <option value="120" ${prefs.ik_poll_interval_minutes === 120 ? 'selected' : ''}>2 hours</option>
                            <option value="240" ${prefs.ik_poll_interval_minutes === 240 ? 'selected' : ''}>4 hours</option>
                        </select>
                    </div>
                    <div class="settings-row">
                        <div>
                            <span class="settings-label">BSKY poll interval</span>
                            <div style="font-size:11px;color:var(--text-muted);margin-top:2px">How often to check for new Bluesky data</div>
                        </div>
                        <select class="filter-select" id="pref-bsky-poll-interval" style="width:auto">
                            <option value="15" ${prefs.bsky_poll_interval_minutes === 15 ? 'selected' : ''}>15 min</option>
                            <option value="30" ${prefs.bsky_poll_interval_minutes === 30 ? 'selected' : ''}>30 min</option>
                            <option value="60" ${prefs.bsky_poll_interval_minutes === 60 || !prefs.bsky_poll_interval_minutes ? 'selected' : ''}>1 hour</option>
                            <option value="120" ${prefs.bsky_poll_interval_minutes === 120 ? 'selected' : ''}>2 hours</option>
                            <option value="240" ${prefs.bsky_poll_interval_minutes === 240 ? 'selected' : ''}>4 hours</option>
                        </select>
                    </div>
                    <div class="settings-row">
                        <div>
                            <span class="settings-label">TW poll interval</span>
                            <div style="font-size:11px;color:var(--text-muted);margin-top:2px">How often to check for new X/Twitter data</div>
                        </div>
                        <select class="filter-select" id="pref-tw-poll-interval" style="width:auto">
                            <option value="15" ${prefs.tw_poll_interval_minutes === 15 ? 'selected' : ''}>15 min</option>
                            <option value="30" ${prefs.tw_poll_interval_minutes === 30 ? 'selected' : ''}>30 min</option>
                            <option value="60" ${prefs.tw_poll_interval_minutes === 60 || !prefs.tw_poll_interval_minutes ? 'selected' : ''}>1 hour</option>
                            <option value="120" ${prefs.tw_poll_interval_minutes === 120 ? 'selected' : ''}>2 hours</option>
                            <option value="240" ${prefs.tw_poll_interval_minutes === 240 ? 'selected' : ''}>4 hours</option>
                        </select>
                    </div>
                    <div class="settings-row">
                        <div>
                            <span class="settings-label">Display timezone</span>
                            <div style="font-size:11px;color:var(--text-muted);margin-top:2px">Timezone for Telegram messages and timestamps</div>
                        </div>
                        <select class="filter-select" id="pref-timezone" style="width:auto">
                            ${[
                                ['UTC', 'UTC'],
                                ['Australia/Sydney', 'Sydney (AEST/AEDT)'],
                                ['Australia/Melbourne', 'Melbourne (AEST/AEDT)'],
                                ['Australia/Brisbane', 'Brisbane (AEST)'],
                                ['Australia/Adelaide', 'Adelaide (ACST/ACDT)'],
                                ['Australia/Perth', 'Perth (AWST)'],
                                ['Australia/Darwin', 'Darwin (ACST)'],
                                ['Australia/Hobart', 'Hobart (AEST/AEDT)'],
                                ['Pacific/Auckland', 'Auckland (NZST/NZDT)'],
                                ['Asia/Tokyo', 'Tokyo (JST)'],
                                ['Asia/Singapore', 'Singapore (SGT)'],
                                ['Asia/Hong_Kong', 'Hong Kong (HKT)'],
                                ['Asia/Kolkata', 'India (IST)'],
                                ['Europe/London', 'London (GMT/BST)'],
                                ['Europe/Paris', 'Paris (CET/CEST)'],
                                ['Europe/Berlin', 'Berlin (CET/CEST)'],
                                ['America/New_York', 'New York (EST/EDT)'],
                                ['America/Chicago', 'Chicago (CST/CDT)'],
                                ['America/Denver', 'Denver (MST/MDT)'],
                                ['America/Los_Angeles', 'Los Angeles (PST/PDT)'],
                            ].map(([val, label]) => `<option value="${val}" ${prefs.display_timezone === val ? 'selected' : ''}>${label}</option>`).join('')}
                        </select>
                    </div>
                    </div>
                </details>

                <details class="settings-accordion">
                    <summary>Notification Filters</summary>
                    <div class="accordion-body">
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
                </details>

                <details class="settings-accordion">
                    <summary>Milestone Thresholds</summary>
                    <div class="accordion-body">
                    <p style="font-size:12px;color:var(--text-muted);margin-bottom:12px">Comma-separated numbers. Telegram will notify when a submission crosses any of these thresholds.</p>
                    <div class="settings-row" style="flex-direction:column;align-items:stretch;gap:8px">
                        <label style="font-size:13px;color:var(--text-muted)">View milestones</label>
                        <input type="text" id="pref-milestone-views" class="search-input" value="${(prefs.milestone_views || [100,250,500,1000,2500,5000,10000,25000,50000,100000]).join(', ')}" style="max-width:500px">
                    </div>
                    <div class="settings-row" style="flex-direction:column;align-items:stretch;gap:8px;margin-top:8px">
                        <label style="font-size:13px;color:var(--text-muted)">Fave milestones</label>
                        <input type="text" id="pref-milestone-faves" class="search-input" value="${(prefs.milestone_faves || [10,25,50,100,250,500,1000,2500,5000]).join(', ')}" style="max-width:500px">
                    </div>
                    <div class="settings-row" style="flex-direction:column;align-items:stretch;gap:8px;margin-top:8px">
                        <label style="font-size:13px;color:var(--text-muted)">Comment milestones</label>
                        <input type="text" id="pref-milestone-comments" class="search-input" value="${(prefs.milestone_comments || [10,25,50,100,250,500,1000]).join(', ')}" style="max-width:500px">
                    </div>
                    <div style="margin-top:12px;display:flex;align-items:center;gap:12px">
                        <button class="btn btn-primary" id="save-milestones-btn">Save Milestones</button>
                        <span id="milestones-msg" style="font-size:13px"></span>
                    </div>
                    </div>
                </details>

                </div><!-- /tab:general -->

                <!-- ═══ TAB: Data ═══ -->
                <div class="settings-tab-content" data-tab-content="data" ${_settingsTab !== 'data' ? 'style="display:none"' : ''}>

                <div class="settings-section">
                    <h3>Backup &amp; Restore</h3>
                    <div class="settings-row">
                        <div>
                            <span class="settings-label">Download database backup</span>
                            <div style="font-size:11px;color:var(--text-muted);margin-top:2px">Download a complete copy of your database</div>
                        </div>
                        <button class="btn btn-secondary" id="backup-download-btn">Download Backup</button>
                    </div>
                    <div class="settings-row" style="margin-top:8px">
                        <div>
                            <span class="settings-label">Restore from backup</span>
                            <div style="font-size:11px;color:var(--text-muted);margin-top:2px">Replace current database with a backup file</div>
                        </div>
                        <div style="display:flex;align-items:center;gap:8px">
                            <input type="file" id="restore-file-input" accept=".db,.sqlite,.sqlite3" style="font-size:12px">
                            <button class="btn btn-danger" id="backup-restore-btn" disabled>Restore</button>
                        </div>
                    </div>
                    <span id="backup-msg" style="font-size:13px;margin-top:8px;display:block"></span>
                </div>

                </div><!-- /tab:data -->

                <!-- ═══ TAB: Logs ═══ -->
                <div class="settings-tab-content" data-tab-content="logs" ${_settingsTab !== 'logs' ? 'style="display:none"' : ''}>

                <div class="settings-section">
                    <h3>Application Logs</h3>
                    <div style="display:flex;gap:8px;align-items:center;margin-bottom:12px;flex-wrap:wrap">
                        <select id="log-file-select" class="filter-select" style="max-width:160px">
                            <option value="server">server.log</option>
                            <option value="polling">polling.log</option>
                            <option value="app">app.log</option>
                        </select>
                        <select id="log-lines-select" class="filter-select" style="max-width:130px">
                            <option value="100">Last 100 lines</option>
                            <option value="200" selected>Last 200 lines</option>
                            <option value="500">Last 500 lines</option>
                            <option value="1000">Last 1000 lines</option>
                        </select>
                        <button class="btn btn-secondary" id="log-refresh-btn" style="padding:4px 12px;font-size:12px">Refresh</button>
                        <label style="display:flex;align-items:center;gap:4px;font-size:12px;color:var(--text-muted);margin-left:auto">
                            <input type="checkbox" id="log-auto-scroll" checked> Auto-scroll
                        </label>
                    </div>
                    <div style="font-size:11px;color:var(--text-muted);margin-bottom:8px" id="log-info"></div>
                    <pre id="log-output" style="background:var(--bg-primary);border:1px solid var(--border);border-radius:var(--radius);padding:12px;font-size:11px;line-height:1.5;max-height:500px;overflow:auto;white-space:pre-wrap;word-break:break-all;color:var(--text-secondary);font-family:'Cascadia Code','Fira Code','Consolas',monospace"></pre>
                </div>

                </div><!-- /tab:logs -->

                <!-- ═══ TAB: About ═══ -->
                <div class="settings-tab-content" data-tab-content="about" ${_settingsTab !== 'about' ? 'style="display:none"' : ''}>

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
                        <div style="display:flex;align-items:center;gap:10px">
                            <span class="settings-value" style="color:var(--success)" id="update-status-text">Up to date</span>
                            <button class="btn btn-secondary" id="check-update-btn" style="padding:4px 12px;font-size:12px">Check for Updates</button>
                        </div>
                    </div>
                </div>`}

                </div><!-- /tab:about -->

                <!-- ═══ TAB: Telegram ═══ -->
                <div class="settings-tab-content" data-tab-content="telegram" ${_settingsTab !== 'telegram' ? 'style="display:none"' : ''}>

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

                </div><!-- /tab:telegram -->

                <!-- ═══ TAB: Platforms ═══ -->
                <div class="settings-tab-content" data-tab-content="platforms" ${_settingsTab !== 'platforms' ? 'style="display:none"' : ''}>

                <details class="settings-accordion">
                    <summary><span class="status-dot ${faAuth.has_cookies ? 'connected' : 'disconnected'}"></span>FurAffinity${faAuth.has_cookies ? ` <span class="summary-meta">— ${Utils.escapeHtml(faAuth.username || '')}</span>` : ''}</summary>
                    <div class="accordion-body">
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
                </details>

                <details class="settings-accordion">
                    <summary><span class="status-dot ${wsAuth.has_key ? 'connected' : 'disconnected'}"></span>Weasyl${wsAuth.has_key ? ` <span class="summary-meta">— ${Utils.escapeHtml(wsAuth.username || '')}</span>` : ''}</summary>
                    <div class="accordion-body">
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
                </details>

                <details class="settings-accordion">
                    <summary><span class="status-dot ${sfAuth.has_credentials ? 'connected' : 'disconnected'}"></span>SoFurry${sfAuth.has_credentials ? ` <span class="summary-meta">— ${Utils.escapeHtml(sfAuth.username || '')}</span>` : ''}</summary>
                    <div class="accordion-body">
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
                </details>

                <details class="settings-accordion">
                    <summary><span class="status-dot ${sqwAuth.has_credentials ? 'connected' : 'disconnected'}"></span>SquidgeWorld${sqwAuth.has_credentials ? ` <span class="summary-meta">— ${Utils.escapeHtml(sqwAuth.username || '')}</span>` : ''}</summary>
                    <div class="accordion-body">
                    ${sqwAuth.has_credentials ? `
                    <div class="settings-row">
                        <div>
                            <span class="settings-label">Status</span>
                        </div>
                        <span class="telegram-status connected">Connected — tracking ${Utils.escapeHtml(sqwAuth.username || '')}</span>
                    </div>
                    <div class="settings-row" style="margin-top:8px">
                        <div>
                            <span class="settings-label">SqW desktop notifications</span>
                            <div style="font-size:11px;color:var(--text-muted);margin-top:2px">Toast + Telegram alerts for SqW activity</div>
                        </div>
                        <label class="toggle-switch">
                            <input type="checkbox" id="pref-sqw-notifications" ${prefs.sqw_notifications_enabled ? 'checked' : ''}>
                            <span class="toggle-slider"></span>
                        </label>
                    </div>
                    <div style="margin-top:12px;display:flex;align-items:center;gap:8px;flex-wrap:wrap">
                        <button class="btn btn-primary" id="sqw-poll-btn">SqW Poll Now</button>
                        <button class="btn btn-secondary" id="sqw-resync-btn">SqW Full Resync</button>
                        <button class="btn btn-danger" id="sqw-disconnect-btn">Disconnect</button>
                        <span id="sqw-msg" style="font-size:13px"></span>
                    </div>
                    ` : `
                    <p style="color:var(--text-muted);font-size:13px;margin-bottom:12px">Connect to SquidgeWorld with a login account and specify the user to track.</p>
                    <div style="display:flex;flex-direction:column;gap:8px;max-width:400px">
                        <input type="text" id="sqw-username" class="search-input" placeholder="Login username (e.g. PawPoller)">
                        <input type="password" id="sqw-password" class="search-input" placeholder="Login password">
                        <input type="text" id="sqw-target-user" class="search-input" placeholder="Target user to track (e.g. KnaughtyKat)">
                    </div>
                    <div style="margin-top:12px;display:flex;align-items:center;gap:8px">
                        <button class="btn btn-primary" id="sqw-connect-btn">Connect</button>
                        <span id="sqw-msg" style="font-size:13px"></span>
                    </div>
                    `}
                    </div>
                </details>

                <details class="settings-accordion">
                    <summary><span class="status-dot ${ao3Auth.has_credentials ? 'connected' : 'disconnected'}"></span>AO3${ao3Auth.has_credentials ? ` <span class="summary-meta">— ${Utils.escapeHtml(ao3Auth.username || '')}</span>` : ''}</summary>
                    <div class="accordion-body">
                    ${ao3Auth.has_credentials ? `
                    <div class="settings-row">
                        <div>
                            <span class="settings-label">Status</span>
                        </div>
                        <span class="telegram-status connected">Connected — tracking ${Utils.escapeHtml(ao3Auth.username || '')}</span>
                    </div>
                    <div class="settings-row" style="margin-top:8px">
                        <div>
                            <span class="settings-label">AO3 desktop notifications</span>
                            <div style="font-size:11px;color:var(--text-muted);margin-top:2px">Toast + Telegram alerts for AO3 activity</div>
                        </div>
                        <label class="toggle-switch">
                            <input type="checkbox" id="pref-ao3-notifications" ${prefs.ao3_notifications_enabled ? 'checked' : ''}>
                            <span class="toggle-slider"></span>
                        </label>
                    </div>
                    <div style="margin-top:12px;display:flex;align-items:center;gap:8px;flex-wrap:wrap">
                        <button class="btn btn-primary" id="ao3-poll-btn">AO3 Poll Now</button>
                        <button class="btn btn-secondary" id="ao3-resync-btn">AO3 Full Resync</button>
                        <button class="btn btn-danger" id="ao3-disconnect-btn">Disconnect</button>
                        <span id="ao3-msg" style="font-size:13px"></span>
                    </div>
                    ` : `
                    <p style="color:var(--text-muted);font-size:13px;margin-bottom:12px">Connect to AO3 with a login account and specify the user to track.</p>
                    <div style="display:flex;flex-direction:column;gap:8px;max-width:400px">
                        <input type="text" id="ao3-username" class="search-input" placeholder="Login username">
                        <input type="password" id="ao3-password" class="search-input" placeholder="Login password">
                        <input type="text" id="ao3-target-user" class="search-input" placeholder="Target user to track">
                    </div>
                    <div style="margin-top:12px;display:flex;align-items:center;gap:8px">
                        <button class="btn btn-primary" id="ao3-connect-btn">Connect</button>
                        <span id="ao3-msg" style="font-size:13px"></span>
                    </div>
                    `}
                    </div>
                </details>

                <details class="settings-accordion">
                    <summary><span class="status-dot ${daAuth.has_credentials ? 'connected' : 'disconnected'}"></span>DeviantArt${daAuth.has_credentials ? ` <span class="summary-meta">— ${Utils.escapeHtml(daAuth.username || '')}</span>` : ''}</summary>
                    <div class="accordion-body">
                    ${daAuth.has_credentials ? `
                    <div class="settings-row">
                        <div>
                            <span class="settings-label">Status</span>
                        </div>
                        <span class="telegram-status connected">Connected — tracking ${Utils.escapeHtml(daAuth.username || '')}</span>
                    </div>
                    <div class="settings-row" style="margin-top:8px">
                        <div>
                            <span class="settings-label">DA desktop notifications</span>
                            <div style="font-size:11px;color:var(--text-muted);margin-top:2px">Toast + Telegram alerts for DA activity</div>
                        </div>
                        <label class="toggle-switch">
                            <input type="checkbox" id="pref-da-notifications" ${prefs.da_notifications_enabled ? 'checked' : ''}>
                            <span class="toggle-slider"></span>
                        </label>
                    </div>
                    <div style="margin-top:12px;display:flex;align-items:center;gap:8px;flex-wrap:wrap">
                        <button class="btn btn-primary" id="da-poll-btn">DA Poll Now</button>
                        <button class="btn btn-secondary" id="da-resync-btn">DA Full Resync</button>
                        <button class="btn btn-danger" id="da-disconnect-btn">Disconnect</button>
                        <span id="da-msg" style="font-size:13px"></span>
                    </div>
                    ` : `
                    <p style="color:var(--text-muted);font-size:13px;margin-bottom:12px">Connect your DeviantArt account using your full browser cookie string and specify the username to track.</p>
                    <div style="display:flex;flex-direction:column;gap:8px;max-width:400px">
                        <textarea id="da-cookie" class="search-input" placeholder="Full cookie string from browser" rows="3" style="resize:vertical;font-family:monospace;font-size:12px"></textarea>
                        <input type="text" id="da-target-user" class="search-input" placeholder="DeviantArt username to track">
                    </div>
                    <div style="margin-top:12px;display:flex;align-items:center;gap:8px">
                        <button class="btn btn-primary" id="da-connect-btn">Connect</button>
                        <span id="da-msg" style="font-size:13px"></span>
                    </div>
                    `}
                    </div>
                </details>

                <details class="settings-accordion">
                    <summary><span class="status-dot ${wpAuth.has_credentials ? 'connected' : 'disconnected'}"></span>Wattpad${wpAuth.has_credentials ? ` <span class="summary-meta">— ${Utils.escapeHtml(wpAuth.username || '')}</span>` : ''}</summary>
                    <div class="accordion-body">
                    ${wpAuth.has_credentials ? `
                    <div class="settings-row">
                        <div>
                            <span class="settings-label">Status</span>
                        </div>
                        <span class="telegram-status connected">Connected — tracking ${Utils.escapeHtml(wpAuth.username || '')}</span>
                    </div>
                    <div class="settings-row" style="margin-top:8px">
                        <div>
                            <span class="settings-label">WP desktop notifications</span>
                            <div style="font-size:11px;color:var(--text-muted);margin-top:2px">Toast + Telegram alerts for Wattpad activity</div>
                        </div>
                        <label class="toggle-switch">
                            <input type="checkbox" id="pref-wp-notifications" ${prefs.wp_notifications_enabled ? 'checked' : ''}>
                            <span class="toggle-slider"></span>
                        </label>
                    </div>
                    <div style="margin-top:12px;display:flex;align-items:center;gap:8px;flex-wrap:wrap">
                        <button class="btn btn-primary" id="wp-poll-btn">WP Poll Now</button>
                        <button class="btn btn-secondary" id="wp-resync-btn">WP Full Resync</button>
                        <button class="btn btn-danger" id="wp-disconnect-btn">Disconnect</button>
                        <span id="wp-msg" style="font-size:13px"></span>
                    </div>
                    ` : `
                    <p style="color:var(--text-muted);font-size:13px;margin-bottom:12px">Connect to Wattpad by entering the username to track. No auth required — just enter the username.</p>
                    <div style="display:flex;flex-direction:column;gap:8px;max-width:400px">
                        <input type="text" id="wp-target-user" class="search-input" placeholder="Wattpad username to track">
                    </div>
                    <div style="margin-top:12px;display:flex;align-items:center;gap:8px">
                        <button class="btn btn-primary" id="wp-connect-btn">Connect</button>
                        <span id="wp-msg" style="font-size:13px"></span>
                    </div>
                    `}
                    </div>
                </details>

                <details class="settings-accordion">
                    <summary><span class="status-dot ${ikAuth.has_credentials ? 'connected' : 'disconnected'}"></span>Itaku${ikAuth.has_credentials ? ` <span class="summary-meta">— ${Utils.escapeHtml(ikAuth.username || '')}</span>` : ''}</summary>
                    <div class="accordion-body">
                    ${ikAuth.has_credentials ? `
                    <div class="settings-row">
                        <div>
                            <span class="settings-label">Status</span>
                        </div>
                        <span class="telegram-status connected">Connected — tracking ${Utils.escapeHtml(ikAuth.username || '')}</span>
                    </div>
                    <div class="settings-row" style="margin-top:8px">
                        <div>
                            <span class="settings-label">IK desktop notifications</span>
                            <div style="font-size:11px;color:var(--text-muted);margin-top:2px">Toast + Telegram alerts for Itaku activity</div>
                        </div>
                        <label class="toggle-switch">
                            <input type="checkbox" id="pref-ik-notifications" ${prefs.ik_notifications_enabled ? 'checked' : ''}>
                            <span class="toggle-slider"></span>
                        </label>
                    </div>
                    <div style="margin-top:12px;display:flex;align-items:center;gap:8px;flex-wrap:wrap">
                        <button class="btn btn-primary" id="ik-poll-btn">IK Poll Now</button>
                        <button class="btn btn-secondary" id="ik-resync-btn">IK Full Resync</button>
                        <button class="btn btn-danger" id="ik-disconnect-btn">Disconnect</button>
                        <span id="ik-msg" style="font-size:13px"></span>
                    </div>
                    ` : `
                    <p style="color:var(--text-muted);font-size:13px;margin-bottom:12px">Connect to Itaku by entering the username to track. No auth required — just enter the username.</p>
                    <div style="display:flex;flex-direction:column;gap:8px;max-width:400px">
                        <input type="text" id="ik-target-user" class="search-input" placeholder="Itaku username to track">
                    </div>
                    <div style="margin-top:12px;display:flex;align-items:center;gap:8px">
                        <button class="btn btn-primary" id="ik-connect-btn">Connect</button>
                        <span id="ik-msg" style="font-size:13px"></span>
                    </div>
                    `}
                    </div>
                </details>

                <details class="settings-accordion">
                    <summary><span class="status-dot ${bskyAuth.has_credentials ? 'connected' : 'disconnected'}"></span>Bluesky${bskyAuth.has_credentials ? ` <span class="summary-meta">— ${Utils.escapeHtml(bskyAuth.username || '')}</span>` : ''}</summary>
                    <div class="accordion-body">
                    ${bskyAuth.has_credentials ? `
                    <div class="settings-row">
                        <div>
                            <span class="settings-label">Status</span>
                        </div>
                        <span class="telegram-status connected">Connected — tracking ${Utils.escapeHtml(bskyAuth.username || '')}</span>
                    </div>
                    <div class="settings-row" style="margin-top:8px">
                        <div>
                            <span class="settings-label">BSKY desktop notifications</span>
                            <div style="font-size:11px;color:var(--text-muted);margin-top:2px">Toast + Telegram alerts for Bluesky activity</div>
                        </div>
                        <label class="toggle-switch">
                            <input type="checkbox" id="pref-bsky-notifications" ${prefs.bsky_notifications_enabled ? 'checked' : ''}>
                            <span class="toggle-slider"></span>
                        </label>
                    </div>
                    <div style="margin-top:12px;display:flex;align-items:center;gap:8px;flex-wrap:wrap">
                        <button class="btn btn-primary" id="bsky-poll-btn">BSKY Poll Now</button>
                        <button class="btn btn-secondary" id="bsky-resync-btn">BSKY Full Resync</button>
                        <button class="btn btn-danger" id="bsky-disconnect-btn">Disconnect</button>
                        <span id="bsky-msg" style="font-size:13px"></span>
                    </div>
                    ` : `
                    <p style="color:var(--text-muted);font-size:13px;margin-bottom:12px">Connect to Bluesky with your handle and app password. Create an app password at Settings > App Passwords on bsky.app.</p>
                    <div style="display:flex;flex-direction:column;gap:8px;max-width:400px">
                        <input type="text" id="bsky-identifier" class="search-input" placeholder="Handle (e.g. user.bsky.social)">
                        <input type="password" id="bsky-app-password" class="search-input" placeholder="App password (xxxx-xxxx-xxxx-xxxx)">
                    </div>
                    <div style="margin-top:12px;display:flex;align-items:center;gap:8px">
                        <button class="btn btn-primary" id="bsky-connect-btn">Connect</button>
                        <span id="bsky-msg" style="font-size:13px"></span>
                    </div>
                    `}
                    </div>
                </details>

                <details class="settings-accordion">
                    <summary><span class="status-dot ${twAuth.has_credentials ? 'connected' : 'disconnected'}"></span>X / Twitter${twAuth.has_credentials ? ` <span class="summary-meta">— ${Utils.escapeHtml(twAuth.username || '')}</span>` : ''}</summary>
                    <div class="accordion-body">
                    ${twAuth.has_credentials ? `
                    <div class="settings-row">
                        <div>
                            <span class="settings-label">Status</span>
                        </div>
                        <span class="telegram-status connected">Connected — tracking ${Utils.escapeHtml(twAuth.username || '')}</span>
                    </div>
                    <div class="settings-row" style="margin-top:8px">
                        <div>
                            <span class="settings-label">TW desktop notifications</span>
                            <div style="font-size:11px;color:var(--text-muted);margin-top:2px">Toast + Telegram alerts for X/Twitter activity</div>
                        </div>
                        <label class="toggle-switch">
                            <input type="checkbox" id="pref-tw-notifications" ${prefs.tw_notifications_enabled ? 'checked' : ''}>
                            <span class="toggle-slider"></span>
                        </label>
                    </div>
                    <div style="margin-top:12px;display:flex;align-items:center;gap:8px;flex-wrap:wrap">
                        <button class="btn btn-primary" id="tw-poll-btn">TW Poll Now</button>
                        <button class="btn btn-secondary" id="tw-resync-btn">TW Full Resync</button>
                        <button class="btn btn-danger" id="tw-disconnect-btn">Disconnect</button>
                        <span id="tw-msg" style="font-size:13px"></span>
                    </div>
                    ` : `
                    <p style="color:var(--text-muted);font-size:13px;margin-bottom:12px">Connect to X/Twitter using browser cookies. Open x.com, press F12, go to Application > Cookies, and copy the auth_token and ct0 values.</p>
                    <div style="display:flex;flex-direction:column;gap:8px;max-width:400px">
                        <input type="text" id="tw-auth-token" class="search-input" placeholder="auth_token cookie">
                        <input type="text" id="tw-ct0" class="search-input" placeholder="ct0 cookie">
                        <input type="text" id="tw-target-user" class="search-input" placeholder="Username to track (without @)">
                    </div>
                    <div style="margin-top:12px;display:flex;align-items:center;gap:8px">
                        <button class="btn btn-primary" id="tw-connect-btn">Connect</button>
                        <span id="tw-msg" style="font-size:13px"></span>
                    </div>
                    `}
                    </div>
                </details>

                </div><!-- /tab:platforms -->

                <!-- ═══ TAB: Polling ═══ -->
                <div class="settings-tab-content" data-tab-content="polling" ${_settingsTab !== 'polling' ? 'style="display:none"' : ''}>

                <div class="settings-section">
                    <h3>Polling Control</h3>
                    <div class="settings-row">
                        <span class="settings-label">Background polling</span>
                        <span class="settings-value">
                            <span id="poll-pause-status" style="color:${pollPausedState.polling_paused ? 'var(--warning, #f0a050)' : 'var(--success)'}; font-weight:600;">
                                ${pollPausedState.polling_paused ? 'Paused' : 'Active'}
                            </span>
                        </span>
                    </div>
                    <div class="settings-row">
                        <span class="settings-label">${pollPausedState.polling_paused ? 'Resume scheduled polling for all platforms' : 'Pause scheduled polling for all platforms'}</span>
                        <button class="btn ${pollPausedState.polling_paused ? 'btn-primary' : 'btn-danger'}" id="poll-pause-btn">
                            ${pollPausedState.polling_paused ? 'Resume Polling' : 'Pause Polling'}
                        </button>
                    </div>
                    <p style="font-size:12px;color:var(--text-muted);margin-top:8px;">
                        When paused, scheduled background polls are skipped. Manual "Poll Now" buttons still work.
                    </p>
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

                ${daAuth.has_credentials ? `
                <div class="settings-section">
                    <h3>DA Polling Status</h3>
                    <div class="settings-row">
                        <span class="settings-label">DA submissions tracked</span>
                        <span class="settings-value">${daStatus.total_submissions || 0}</span>
                    </div>
                    <div class="settings-row">
                        <span class="settings-label">DA snapshots stored</span>
                        <span class="settings-value">${Utils.formatNumber(daStatus.total_snapshots || 0)}</span>
                    </div>
                    <div class="settings-row">
                        <span class="settings-label">Last DA poll</span>
                        <span class="settings-value">${daStatus.last_poll ? Utils.formatDateTime(daStatus.last_poll.started_at) : 'Never'}</span>
                    </div>
                    <div class="settings-row">
                        <span class="settings-label">Last DA poll status</span>
                        <span class="settings-value" style="color:${daStatus.last_poll?.status === 'success' ? 'var(--success)' : daStatus.last_poll?.status === 'error' ? 'var(--danger)' : 'var(--text-primary)'}">
                            ${daStatus.last_poll?.status || '--'}
                        </span>
                    </div>
                    ${daStatus.last_poll?.error_message ? `
                    <div class="settings-row">
                        <span class="settings-label">Last DA error</span>
                        <span class="settings-value" style="color:var(--danger)">${Utils.escapeHtml(daStatus.last_poll.error_message)}</span>
                    </div>` : ''}
                </div>

                <div class="settings-section">
                    <h3>DA Poll History</h3>
                    ${Components.daPollLogTable(daPollLog.polls)}
                </div>
                ` : ''}

                ${wpAuth.has_credentials ? `
                <div class="settings-section">
                    <h3>WP Polling Status</h3>
                    <div class="settings-row">
                        <span class="settings-label">WP submissions tracked</span>
                        <span class="settings-value">${wpStatus.total_submissions || 0}</span>
                    </div>
                    <div class="settings-row">
                        <span class="settings-label">WP snapshots stored</span>
                        <span class="settings-value">${Utils.formatNumber(wpStatus.total_snapshots || 0)}</span>
                    </div>
                    <div class="settings-row">
                        <span class="settings-label">Last WP poll</span>
                        <span class="settings-value">${wpStatus.last_poll ? Utils.formatDateTime(wpStatus.last_poll.started_at) : 'Never'}</span>
                    </div>
                    <div class="settings-row">
                        <span class="settings-label">Last WP poll status</span>
                        <span class="settings-value" style="color:${wpStatus.last_poll?.status === 'success' ? 'var(--success)' : wpStatus.last_poll?.status === 'error' ? 'var(--danger)' : 'var(--text-primary)'}">
                            ${wpStatus.last_poll?.status || '--'}
                        </span>
                    </div>
                    ${wpStatus.last_poll?.error_message ? `
                    <div class="settings-row">
                        <span class="settings-label">Last WP error</span>
                        <span class="settings-value" style="color:var(--danger)">${Utils.escapeHtml(wpStatus.last_poll.error_message)}</span>
                    </div>` : ''}
                </div>

                <div class="settings-section">
                    <h3>WP Poll History</h3>
                    ${Components.wpPollLogTable(wpPollLog.polls)}
                </div>
                ` : ''}

                ${ikAuth.has_credentials ? `
                <div class="settings-section">
                    <h3>IK Polling Status</h3>
                    <div class="settings-row">
                        <span class="settings-label">IK submissions tracked</span>
                        <span class="settings-value">${ikStatus.total_submissions || 0}</span>
                    </div>
                    <div class="settings-row">
                        <span class="settings-label">IK snapshots stored</span>
                        <span class="settings-value">${Utils.formatNumber(ikStatus.total_snapshots || 0)}</span>
                    </div>
                    <div class="settings-row">
                        <span class="settings-label">Last IK poll</span>
                        <span class="settings-value">${ikStatus.last_poll ? Utils.formatDateTime(ikStatus.last_poll.started_at) : 'Never'}</span>
                    </div>
                    <div class="settings-row">
                        <span class="settings-label">Last IK poll status</span>
                        <span class="settings-value" style="color:${ikStatus.last_poll?.status === 'success' ? 'var(--success)' : ikStatus.last_poll?.status === 'error' ? 'var(--danger)' : 'var(--text-primary)'}">
                            ${ikStatus.last_poll?.status || '--'}
                        </span>
                    </div>
                    ${ikStatus.last_poll?.error_message ? `
                    <div class="settings-row">
                        <span class="settings-label">Last IK error</span>
                        <span class="settings-value" style="color:var(--danger)">${Utils.escapeHtml(ikStatus.last_poll.error_message)}</span>
                    </div>` : ''}
                </div>

                <div class="settings-section">
                    <h3>IK Poll History</h3>
                    ${Components.ikPollLogTable(ikPollLog.polls)}
                </div>
                ` : ''}

                </div><!-- /tab:polling -->
            `;

            this._setContent(html);

            // ── Settings Tab Switching ───────────────────────────────
            const tabBar = document.getElementById('settings-tabs');
            if (tabBar) {
                tabBar.addEventListener('click', (e) => {
                    const btn = e.target.closest('.settings-tab');
                    if (!btn) return;
                    const tab = btn.dataset.stab;
                    // Update active tab button
                    tabBar.querySelectorAll('.settings-tab').forEach(t => t.classList.remove('active'));
                    btn.classList.add('active');
                    // Show/hide tab content panels
                    document.querySelectorAll('.settings-tab-content').forEach(panel => {
                        panel.style.display = panel.dataset.tabContent === tab ? '' : 'none';
                    });
                    // Update URL hash without re-rendering
                    const newHash = tab === 'general' ? '#/settings' : `#/settings/${tab}`;
                    history.replaceState(null, '', newHash);
                    // Auto-load logs when switching to logs tab
                    if (tab === 'logs') this._loadLogs();
                });
            }

            // Load logs on initial render if logs tab is active
            if (_settingsTab === 'logs') this._loadLogs();

            // Log tab event handlers
            document.getElementById('log-refresh-btn')?.addEventListener('click', () => this._loadLogs());
            document.getElementById('log-file-select')?.addEventListener('change', () => this._loadLogs());
            document.getElementById('log-lines-select')?.addEventListener('change', () => this._loadLogs());

            // ── Settings Event Handlers ──────────────────────────────
            // All controls save immediately on interaction (no "Save All" button).
            // Toggles revert on failure. Buttons show loading text and re-render
            // the settings page after completion via setTimeout.

            // Poll Now: triggers an IB poll, shows progress, re-renders on complete
            document.getElementById('poll-pause-btn')?.addEventListener('click', async (e) => {
                const btn = e.target;
                btn.disabled = true;
                const isPaused = btn.textContent.trim() === 'Resume Polling';
                btn.textContent = isPaused ? 'Resuming...' : 'Pausing...';
                try {
                    if (isPaused) {
                        await API.resumePolling();
                    } else {
                        await API.pausePolling();
                    }
                    setTimeout(() => this.renderSettings(), 500);
                } catch (err) {
                    btn.textContent = 'Error';
                    alert('Failed: ' + err.message);
                    setTimeout(() => this.renderSettings(), 2000);
                }
            });

            document.getElementById('save-all-settings-btn').addEventListener('click', async (e) => {
                const btn = e.target;
                btn.disabled = true;
                btn.textContent = 'Saving...';
                try {
                    // Collect all preferences from the form
                    const prefs = {};
                    const val = (id) => document.getElementById(id)?.value;
                    const chk = (id) => document.getElementById(id)?.checked;

                    // General toggles
                    prefs.minimize_to_tray = !!chk('pref-tray');
                    prefs.run_on_startup = !!chk('pref-startup');
                    prefs.notifications_enabled = !!chk('pref-notifications');
                    prefs.watcher_notifications_enabled = !!chk('pref-watcher-notif');

                    // Poll intervals
                    prefs.poll_interval_minutes = parseInt(val('pref-poll-interval')) || 60;
                    prefs.fa_poll_interval_minutes = parseInt(val('pref-fa-poll-interval')) || 60;
                    prefs.ws_poll_interval_minutes = parseInt(val('pref-ws-poll-interval')) || 60;
                    prefs.sf_poll_interval_minutes = parseInt(val('pref-sf-poll-interval')) || 60;
                    prefs.sqw_poll_interval_minutes = parseInt(val('pref-sqw-poll-interval')) || 60;
                    prefs.ao3_poll_interval_minutes = parseInt(val('pref-ao3-poll-interval')) || 60;
                    prefs.da_poll_interval_minutes = parseInt(val('pref-da-poll-interval')) || 60;
                    prefs.wp_poll_interval_minutes = parseInt(val('pref-wp-poll-interval')) || 60;
                    prefs.ik_poll_interval_minutes = parseInt(val('pref-ik-poll-interval')) || 60;
                    prefs.bsky_poll_interval_minutes = parseInt(val('pref-bsky-poll-interval')) || 60;
                    prefs.tw_poll_interval_minutes = parseInt(val('pref-tw-poll-interval')) || 60;

                    // Timezone
                    if (val('pref-timezone')) prefs.display_timezone = val('pref-timezone');

                    // Notification filters
                    prefs.notification_comments_only = !!chk('pref-notif-comments-only');
                    prefs.fa_notification_comments_only = !!chk('pref-fa-notif-comments-only');
                    prefs.ws_notification_comments_only = !!chk('pref-ws-notif-comments-only');
                    prefs.sf_notification_comments_only = !!chk('pref-sf-notif-comments-only');
                    prefs.notification_min_views_delta = parseInt(val('pref-min-views-delta')) || 0;
                    prefs.notification_min_faves_delta = parseInt(val('pref-min-faves-delta')) || 0;

                    // Milestones
                    const parseList = (id) => (val(id) || '').split(',').map(s => parseInt(s.trim())).filter(n => n > 0);
                    prefs.milestone_views = parseList('pref-milestone-views');
                    prefs.milestone_faves = parseList('pref-milestone-faves');
                    prefs.milestone_comments = parseList('pref-milestone-comments');

                    // Platform notification toggles
                    if (document.getElementById('pref-fa-notifications')) prefs.fa_notifications_enabled = !!chk('pref-fa-notifications');
                    if (document.getElementById('pref-fa-watcher-notif')) prefs.fa_watcher_notifications_enabled = !!chk('pref-fa-watcher-notif');
                    if (document.getElementById('pref-ws-notifications')) prefs.ws_notifications_enabled = !!chk('pref-ws-notifications');
                    if (document.getElementById('pref-sf-notifications')) prefs.sf_notifications_enabled = !!chk('pref-sf-notifications');
                    if (document.getElementById('pref-sqw-notifications')) prefs.sqw_notifications_enabled = !!chk('pref-sqw-notifications');
                    if (document.getElementById('pref-ao3-notifications')) prefs.ao3_notifications_enabled = !!chk('pref-ao3-notifications');
                    if (document.getElementById('pref-da-notifications')) prefs.da_notifications_enabled = !!chk('pref-da-notifications');
                    if (document.getElementById('pref-wp-notifications')) prefs.wp_notifications_enabled = !!chk('pref-wp-notifications');
                    if (document.getElementById('pref-ik-notifications')) prefs.ik_notifications_enabled = !!chk('pref-ik-notifications');
                    if (document.getElementById('pref-bsky-notifications')) prefs.bsky_notifications_enabled = !!chk('pref-bsky-notifications');
                    if (document.getElementById('pref-tw-notifications')) prefs.tw_notifications_enabled = !!chk('pref-tw-notifications');

                    await API.savePreferences(prefs);

                    // Save credentials if username field has a value
                    const username = val('cred-username');
                    const password = document.getElementById('cred-password')?.value;
                    if (username && password) {
                        await API.saveCredentials({ username, password });
                    }

                    btn.textContent = 'Saved!';
                    btn.style.background = 'var(--success)';
                    setTimeout(() => {
                        btn.textContent = 'Save Settings';
                        btn.style.background = '';
                        btn.disabled = false;
                    }, 2000);
                } catch (err) {
                    btn.textContent = 'Error';
                    alert('Save failed: ' + err.message);
                    setTimeout(() => {
                        btn.textContent = 'Save Settings';
                        btn.disabled = false;
                    }, 2000);
                }
            });

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

            // SqW poll interval dropdown
            document.getElementById('pref-sqw-poll-interval')?.addEventListener('change', async (e) => {
                try {
                    await API.savePreferences({ sqw_poll_interval_minutes: parseInt(e.target.value) });
                } catch (err) {
                    alert('Failed to save: ' + err.message);
                }
            });

            // AO3 poll interval dropdown
            document.getElementById('pref-ao3-poll-interval')?.addEventListener('change', async (e) => {
                try {
                    await API.savePreferences({ ao3_poll_interval_minutes: parseInt(e.target.value) });
                } catch (err) {
                    alert('Failed to save: ' + err.message);
                }
            });

            // DA poll interval dropdown
            document.getElementById('pref-da-poll-interval')?.addEventListener('change', async (e) => {
                try {
                    await API.savePreferences({ da_poll_interval_minutes: parseInt(e.target.value) });
                } catch (err) {
                    alert('Failed to save: ' + err.message);
                }
            });

            // WP poll interval dropdown
            document.getElementById('pref-wp-poll-interval')?.addEventListener('change', async (e) => {
                try {
                    await API.savePreferences({ wp_poll_interval_minutes: parseInt(e.target.value) });
                } catch (err) {
                    alert('Failed to save: ' + err.message);
                }
            });

            // IK poll interval dropdown
            document.getElementById('pref-ik-poll-interval')?.addEventListener('change', async (e) => {
                try {
                    await API.savePreferences({ ik_poll_interval_minutes: parseInt(e.target.value) });
                } catch (err) {
                    alert('Failed to save: ' + err.message);
                }
            });

            // BSKY poll interval dropdown
            document.getElementById('pref-bsky-poll-interval')?.addEventListener('change', async (e) => {
                try {
                    await API.savePreferences({ bsky_poll_interval_minutes: parseInt(e.target.value) });
                } catch (err) {
                    alert('Failed to save: ' + err.message);
                }
            });

            // TW poll interval dropdown
            document.getElementById('pref-tw-poll-interval')?.addEventListener('change', async (e) => {
                try {
                    await API.savePreferences({ tw_poll_interval_minutes: parseInt(e.target.value) });
                } catch (err) {
                    alert('Failed to save: ' + err.message);
                }
            });

            // Display timezone dropdown
            document.getElementById('pref-timezone')?.addEventListener('change', async (e) => {
                try {
                    await API.savePreferences({ display_timezone: e.target.value });
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

            // SQW: Connect
            const sqwConnectBtn = document.getElementById('sqw-connect-btn');
            if (sqwConnectBtn) {
                sqwConnectBtn.addEventListener('click', async () => {
                    const msg = document.getElementById('sqw-msg');
                    const username = document.getElementById('sqw-username').value.trim();
                    const password = document.getElementById('sqw-password').value;
                    const target_user = document.getElementById('sqw-target-user').value.trim();
                    if (!username || !password || !target_user) {
                        msg.textContent = 'All fields required';
                        msg.style.color = 'var(--danger)';
                        return;
                    }
                    sqwConnectBtn.disabled = true;
                    sqwConnectBtn.textContent = 'Connecting...';
                    msg.textContent = '';
                    try {
                        await API.sqwConnect({ username, password, target_user });
                        msg.textContent = 'Connected!';
                        msg.style.color = 'var(--success)';
                        setTimeout(() => this.renderSettings(), 1000);
                    } catch (err) {
                        let detail = err.message.replace(/^API \d+:\s*/, '');
                        try { detail = JSON.parse(detail).detail || detail; } catch {}
                        msg.textContent = detail;
                        msg.style.color = 'var(--danger)';
                        sqwConnectBtn.textContent = 'Connect';
                        sqwConnectBtn.disabled = false;
                    }
                });
            }

            // SQW: Disconnect
            const sqwDisconnectBtn = document.getElementById('sqw-disconnect-btn');
            if (sqwDisconnectBtn) {
                sqwDisconnectBtn.addEventListener('click', async () => {
                    if (!confirm('Disconnect SquidgeWorld? This clears saved credentials.')) return;
                    try {
                        await API.sqwDisconnect();
                        this.renderSettings();
                    } catch (err) {
                        alert('Failed: ' + err.message);
                    }
                });
            }

            // SQW: Poll Now
            const sqwPollBtn = document.getElementById('sqw-poll-btn');
            if (sqwPollBtn) {
                sqwPollBtn.addEventListener('click', async () => {
                    const msg = document.getElementById('sqw-msg');
                    sqwPollBtn.disabled = true;
                    sqwPollBtn.textContent = 'Polling...';
                    if (msg) msg.textContent = '';
                    try {
                        await API.triggerSQWPoll();
                        sqwPollBtn.textContent = 'Done!';
                        setTimeout(() => this.renderSettings(), 1500);
                    } catch (err) {
                        sqwPollBtn.textContent = 'Error';
                        if (msg) { msg.textContent = err.message; msg.style.color = 'var(--danger)'; }
                        setTimeout(() => this.renderSettings(), 2000);
                    }
                });
            }

            // SQW: Full Resync
            const sqwResyncBtn = document.getElementById('sqw-resync-btn');
            if (sqwResyncBtn) {
                sqwResyncBtn.addEventListener('click', async () => {
                    if (!confirm('SqW full resync will re-fetch all work details. Continue?')) return;
                    const msg = document.getElementById('sqw-msg');
                    sqwResyncBtn.disabled = true;
                    sqwResyncBtn.textContent = 'Syncing...';
                    if (msg) msg.textContent = '';
                    try {
                        await API.fullSQWResync();
                        sqwResyncBtn.textContent = 'Done!';
                        setTimeout(() => this.renderSettings(), 1500);
                    } catch (err) {
                        sqwResyncBtn.textContent = 'Error';
                        if (msg) { msg.textContent = err.message; msg.style.color = 'var(--danger)'; }
                        setTimeout(() => this.renderSettings(), 2000);
                    }
                });
            }

            // SQW: Notifications toggle
            const sqwNotifToggle = document.getElementById('pref-sqw-notifications');
            if (sqwNotifToggle) {
                sqwNotifToggle.addEventListener('change', async (e) => {
                    try {
                        await API.savePreferences({ sqw_notifications_enabled: e.target.checked });
                    } catch (err) {
                        e.target.checked = !e.target.checked;
                        alert('Failed to save preference: ' + err.message);
                    }
                });
            }

            // AO3: Connect
            const ao3ConnectBtn = document.getElementById('ao3-connect-btn');
            if (ao3ConnectBtn) {
                ao3ConnectBtn.addEventListener('click', async () => {
                    const msg = document.getElementById('ao3-msg');
                    const username = document.getElementById('ao3-username').value.trim();
                    const password = document.getElementById('ao3-password').value;
                    const target_user = document.getElementById('ao3-target-user').value.trim();
                    if (!username || !password || !target_user) {
                        msg.textContent = 'All fields required';
                        msg.style.color = 'var(--danger)';
                        return;
                    }
                    ao3ConnectBtn.disabled = true;
                    ao3ConnectBtn.textContent = 'Connecting...';
                    msg.textContent = '';
                    try {
                        await API.ao3Connect({ username, password, target_user });
                        msg.textContent = 'Connected!';
                        msg.style.color = 'var(--success)';
                        setTimeout(() => this.renderSettings(), 1000);
                    } catch (err) {
                        let detail = err.message.replace(/^API \d+:\s*/, '');
                        try { detail = JSON.parse(detail).detail || detail; } catch {}
                        msg.textContent = detail;
                        msg.style.color = 'var(--danger)';
                        ao3ConnectBtn.textContent = 'Connect';
                        ao3ConnectBtn.disabled = false;
                    }
                });
            }

            // AO3: Disconnect
            const ao3DisconnectBtn = document.getElementById('ao3-disconnect-btn');
            if (ao3DisconnectBtn) {
                ao3DisconnectBtn.addEventListener('click', async () => {
                    if (!confirm('Disconnect AO3? This clears saved credentials.')) return;
                    try {
                        await API.ao3Disconnect();
                        this.renderSettings();
                    } catch (err) {
                        alert('Failed: ' + err.message);
                    }
                });
            }

            // AO3: Poll Now
            const ao3PollBtn = document.getElementById('ao3-poll-btn');
            if (ao3PollBtn) {
                ao3PollBtn.addEventListener('click', async () => {
                    const msg = document.getElementById('ao3-msg');
                    ao3PollBtn.disabled = true;
                    ao3PollBtn.textContent = 'Polling...';
                    if (msg) msg.textContent = '';
                    try {
                        await API.triggerAO3Poll();
                        ao3PollBtn.textContent = 'Done!';
                        setTimeout(() => this.renderSettings(), 1500);
                    } catch (err) {
                        ao3PollBtn.textContent = 'Error';
                        if (msg) { msg.textContent = err.message; msg.style.color = 'var(--danger)'; }
                        setTimeout(() => this.renderSettings(), 2000);
                    }
                });
            }

            // AO3: Full Resync
            const ao3ResyncBtn = document.getElementById('ao3-resync-btn');
            if (ao3ResyncBtn) {
                ao3ResyncBtn.addEventListener('click', async () => {
                    if (!confirm('AO3 full resync will re-fetch all work details. Continue?')) return;
                    const msg = document.getElementById('ao3-msg');
                    ao3ResyncBtn.disabled = true;
                    ao3ResyncBtn.textContent = 'Syncing...';
                    if (msg) msg.textContent = '';
                    try {
                        await API.fullAO3Resync();
                        ao3ResyncBtn.textContent = 'Done!';
                        setTimeout(() => this.renderSettings(), 1500);
                    } catch (err) {
                        ao3ResyncBtn.textContent = 'Error';
                        if (msg) { msg.textContent = err.message; msg.style.color = 'var(--danger)'; }
                        setTimeout(() => this.renderSettings(), 2000);
                    }
                });
            }

            // AO3: Notifications toggle
            const ao3NotifToggle = document.getElementById('pref-ao3-notifications');
            if (ao3NotifToggle) {
                ao3NotifToggle.addEventListener('change', async (e) => {
                    try {
                        await API.savePreferences({ ao3_notifications_enabled: e.target.checked });
                    } catch (err) {
                        e.target.checked = !e.target.checked;
                        alert('Failed to save preference: ' + err.message);
                    }
                });
            }

            // DA Connect: sends cookie string + target_user to authenticate with DeviantArt
            const daConnectBtn = document.getElementById('da-connect-btn');
            if (daConnectBtn) {
                daConnectBtn.addEventListener('click', async () => {
                    const msg = document.getElementById('da-msg');
                    const cookie = document.getElementById('da-cookie').value.trim();
                    const target_user = document.getElementById('da-target-user').value.trim();
                    if (!cookie || !target_user) {
                        msg.textContent = 'Both cookie and username are required';
                        msg.style.color = 'var(--danger)';
                        return;
                    }
                    daConnectBtn.disabled = true;
                    daConnectBtn.textContent = 'Connecting...';
                    msg.textContent = '';
                    try {
                        await API.daConnect({ cookie, target_user });
                        msg.textContent = 'Connected!';
                        msg.style.color = 'var(--success)';
                        setTimeout(() => this.renderSettings(), 1000);
                    } catch (err) {
                        let detail = err.message.replace(/^API \d+:\s*/, '');
                        try { detail = JSON.parse(detail).detail || detail; } catch {}
                        msg.textContent = detail;
                        msg.style.color = 'var(--danger)';
                        daConnectBtn.textContent = 'Connect';
                        daConnectBtn.disabled = false;
                    }
                });
            }

            // DA Disconnect: clears saved credentials, re-renders to show connect form
            const daDisconnectBtn = document.getElementById('da-disconnect-btn');
            if (daDisconnectBtn) {
                daDisconnectBtn.addEventListener('click', async () => {
                    if (!confirm('Disconnect DeviantArt? This clears saved cookies.')) return;
                    try {
                        await API.daDisconnect();
                        this.renderSettings();
                    } catch (err) {
                        alert('Failed: ' + err.message);
                    }
                });
            }

            // DA Poll Now: triggers an immediate DA data-fetch cycle
            const daPollBtn = document.getElementById('da-poll-btn');
            if (daPollBtn) {
                daPollBtn.addEventListener('click', async () => {
                    const msg = document.getElementById('da-msg');
                    daPollBtn.disabled = true;
                    daPollBtn.textContent = 'Polling...';
                    if (msg) msg.textContent = '';
                    try {
                        await API.triggerDAPoll();
                        daPollBtn.textContent = 'Done!';
                        setTimeout(() => this.renderSettings(), 1500);
                    } catch (err) {
                        daPollBtn.textContent = 'Error';
                        if (msg) { msg.textContent = err.message; msg.style.color = 'var(--danger)'; }
                        setTimeout(() => this.renderSettings(), 2000);
                    }
                });
            }

            // DA Full Resync: re-fetches all DA submission details.
            const daResyncBtn = document.getElementById('da-resync-btn');
            if (daResyncBtn) {
                daResyncBtn.addEventListener('click', async () => {
                    if (!confirm('DA full resync will re-fetch all submission details. This may take a while. Continue?')) return;
                    const msg = document.getElementById('da-msg');
                    daResyncBtn.disabled = true;
                    daResyncBtn.textContent = 'Syncing...';
                    if (msg) msg.textContent = '';
                    try {
                        await API.fullDAResync();
                        daResyncBtn.textContent = 'Done!';
                        setTimeout(() => this.renderSettings(), 1500);
                    } catch (err) {
                        daResyncBtn.textContent = 'Error';
                        if (msg) { msg.textContent = err.message; msg.style.color = 'var(--danger)'; }
                        setTimeout(() => this.renderSettings(), 2000);
                    }
                });
            }

            // DA: Notifications toggle
            const daNotifToggle = document.getElementById('pref-da-notifications');
            if (daNotifToggle) {
                daNotifToggle.addEventListener('change', async (e) => {
                    try {
                        await API.savePreferences({ da_notifications_enabled: e.target.checked });
                    } catch (err) {
                        e.target.checked = !e.target.checked;
                        alert('Failed to save preference: ' + err.message);
                    }
                });
            }

            // WP Connect: sends just target_user (username-only auth, no password/cookie)
            const wpConnectBtn = document.getElementById('wp-connect-btn');
            if (wpConnectBtn) {
                wpConnectBtn.addEventListener('click', async () => {
                    const msg = document.getElementById('wp-msg');
                    const target_user = document.getElementById('wp-target-user').value.trim();
                    if (!target_user) {
                        msg.textContent = 'Username is required';
                        msg.style.color = 'var(--danger)';
                        return;
                    }
                    wpConnectBtn.disabled = true;
                    wpConnectBtn.textContent = 'Connecting...';
                    msg.textContent = '';
                    try {
                        await API.wpConnect({ target_user });
                        msg.textContent = 'Connected!';
                        msg.style.color = 'var(--success)';
                        setTimeout(() => this.renderSettings(), 1000);
                    } catch (err) {
                        let detail = err.message.replace(/^API \d+:\s*/, '');
                        try { detail = JSON.parse(detail).detail || detail; } catch {}
                        msg.textContent = detail;
                        msg.style.color = 'var(--danger)';
                        wpConnectBtn.textContent = 'Connect';
                        wpConnectBtn.disabled = false;
                    }
                });
            }

            // WP Disconnect: clears saved credentials, re-renders to show connect form
            const wpDisconnectBtn = document.getElementById('wp-disconnect-btn');
            if (wpDisconnectBtn) {
                wpDisconnectBtn.addEventListener('click', async () => {
                    if (!confirm('Disconnect Wattpad? This clears the tracked username.')) return;
                    try {
                        await API.wpDisconnect();
                        this.renderSettings();
                    } catch (err) {
                        alert('Failed: ' + err.message);
                    }
                });
            }

            // WP Poll Now: triggers an immediate Wattpad data-fetch cycle
            const wpPollBtn = document.getElementById('wp-poll-btn');
            if (wpPollBtn) {
                wpPollBtn.addEventListener('click', async () => {
                    const msg = document.getElementById('wp-msg');
                    wpPollBtn.disabled = true;
                    wpPollBtn.textContent = 'Polling...';
                    if (msg) msg.textContent = '';
                    try {
                        await API.triggerWPPoll();
                        wpPollBtn.textContent = 'Done!';
                        setTimeout(() => this.renderSettings(), 1500);
                    } catch (err) {
                        wpPollBtn.textContent = 'Error';
                        if (msg) { msg.textContent = err.message; msg.style.color = 'var(--danger)'; }
                        setTimeout(() => this.renderSettings(), 2000);
                    }
                });
            }

            // WP Full Resync: re-fetches all WP submission details.
            const wpResyncBtn = document.getElementById('wp-resync-btn');
            if (wpResyncBtn) {
                wpResyncBtn.addEventListener('click', async () => {
                    if (!confirm('WP full resync will re-fetch all submission details. This may take a while. Continue?')) return;
                    const msg = document.getElementById('wp-msg');
                    wpResyncBtn.disabled = true;
                    wpResyncBtn.textContent = 'Syncing...';
                    if (msg) msg.textContent = '';
                    try {
                        await API.fullWPResync();
                        wpResyncBtn.textContent = 'Done!';
                        setTimeout(() => this.renderSettings(), 1500);
                    } catch (err) {
                        wpResyncBtn.textContent = 'Error';
                        if (msg) { msg.textContent = err.message; msg.style.color = 'var(--danger)'; }
                        setTimeout(() => this.renderSettings(), 2000);
                    }
                });
            }

            // WP: Notifications toggle
            const wpNotifToggle = document.getElementById('pref-wp-notifications');
            if (wpNotifToggle) {
                wpNotifToggle.addEventListener('change', async (e) => {
                    try {
                        await API.savePreferences({ wp_notifications_enabled: e.target.checked });
                    } catch (err) {
                        e.target.checked = !e.target.checked;
                        alert('Failed to save preference: ' + err.message);
                    }
                });
            }

            // IK Connect: sends just target_user (username-only auth, no password/cookie)
            const ikConnectBtn = document.getElementById('ik-connect-btn');
            if (ikConnectBtn) {
                ikConnectBtn.addEventListener('click', async () => {
                    const msg = document.getElementById('ik-msg');
                    const target_user = document.getElementById('ik-target-user').value.trim();
                    if (!target_user) {
                        msg.textContent = 'Username is required';
                        msg.style.color = 'var(--danger)';
                        return;
                    }
                    ikConnectBtn.disabled = true;
                    ikConnectBtn.textContent = 'Connecting...';
                    msg.textContent = '';
                    try {
                        await API.ikConnect({ target_user });
                        msg.textContent = 'Connected!';
                        msg.style.color = 'var(--success)';
                        setTimeout(() => this.renderSettings(), 1000);
                    } catch (err) {
                        let detail = err.message.replace(/^API \d+:\s*/, '');
                        try { detail = JSON.parse(detail).detail || detail; } catch {}
                        msg.textContent = detail;
                        msg.style.color = 'var(--danger)';
                        ikConnectBtn.textContent = 'Connect';
                        ikConnectBtn.disabled = false;
                    }
                });
            }

            // IK Disconnect: clears saved credentials, re-renders to show connect form
            const ikDisconnectBtn = document.getElementById('ik-disconnect-btn');
            if (ikDisconnectBtn) {
                ikDisconnectBtn.addEventListener('click', async () => {
                    if (!confirm('Disconnect Itaku? This clears the tracked username.')) return;
                    try {
                        await API.ikDisconnect();
                        this.renderSettings();
                    } catch (err) {
                        alert('Failed: ' + err.message);
                    }
                });
            }

            // IK Poll Now: triggers an immediate Itaku data-fetch cycle
            const ikPollBtn = document.getElementById('ik-poll-btn');
            if (ikPollBtn) {
                ikPollBtn.addEventListener('click', async () => {
                    const msg = document.getElementById('ik-msg');
                    ikPollBtn.disabled = true;
                    ikPollBtn.textContent = 'Polling...';
                    if (msg) msg.textContent = '';
                    try {
                        await API.triggerIKPoll();
                        ikPollBtn.textContent = 'Done!';
                        setTimeout(() => this.renderSettings(), 1500);
                    } catch (err) {
                        ikPollBtn.textContent = 'Error';
                        if (msg) { msg.textContent = err.message; msg.style.color = 'var(--danger)'; }
                        setTimeout(() => this.renderSettings(), 2000);
                    }
                });
            }

            // IK Full Resync: re-fetches all IK submission details.
            const ikResyncBtn = document.getElementById('ik-resync-btn');
            if (ikResyncBtn) {
                ikResyncBtn.addEventListener('click', async () => {
                    if (!confirm('IK full resync will re-fetch all submission details. This may take a while. Continue?')) return;
                    const msg = document.getElementById('ik-msg');
                    ikResyncBtn.disabled = true;
                    ikResyncBtn.textContent = 'Syncing...';
                    if (msg) msg.textContent = '';
                    try {
                        await API.fullIKResync();
                        ikResyncBtn.textContent = 'Done!';
                        setTimeout(() => this.renderSettings(), 1500);
                    } catch (err) {
                        ikResyncBtn.textContent = 'Error';
                        if (msg) { msg.textContent = err.message; msg.style.color = 'var(--danger)'; }
                        setTimeout(() => this.renderSettings(), 2000);
                    }
                });
            }

            // IK: Notifications toggle
            const ikNotifToggle = document.getElementById('pref-ik-notifications');
            if (ikNotifToggle) {
                ikNotifToggle.addEventListener('change', async (e) => {
                    try {
                        await API.savePreferences({ ik_notifications_enabled: e.target.checked });
                    } catch (err) {
                        e.target.checked = !e.target.checked;
                        alert('Failed to save preference: ' + err.message);
                    }
                });
            }

            // BSKY Connect: sends identifier + app_password
            const bskyConnectBtn = document.getElementById('bsky-connect-btn');
            if (bskyConnectBtn) {
                bskyConnectBtn.addEventListener('click', async () => {
                    const msg = document.getElementById('bsky-msg');
                    const identifier = document.getElementById('bsky-identifier').value.trim();
                    const app_password = document.getElementById('bsky-app-password').value.trim();
                    if (!identifier || !app_password) {
                        msg.textContent = 'Handle and app password are required';
                        msg.style.color = 'var(--danger)';
                        return;
                    }
                    bskyConnectBtn.disabled = true;
                    bskyConnectBtn.textContent = 'Connecting...';
                    msg.textContent = '';
                    try {
                        await API.bskyConnect({ identifier, app_password });
                        msg.textContent = 'Connected!';
                        msg.style.color = 'var(--success)';
                        setTimeout(() => this.renderSettings(), 1000);
                    } catch (err) {
                        let detail = err.message.replace(/^API \d+:\s*/, '');
                        try { detail = JSON.parse(detail).detail || detail; } catch {}
                        msg.textContent = detail;
                        msg.style.color = 'var(--danger)';
                        bskyConnectBtn.textContent = 'Connect';
                        bskyConnectBtn.disabled = false;
                    }
                });
            }

            // BSKY Disconnect
            const bskyDisconnectBtn = document.getElementById('bsky-disconnect-btn');
            if (bskyDisconnectBtn) {
                bskyDisconnectBtn.addEventListener('click', async () => {
                    if (!confirm('Disconnect Bluesky? This clears your credentials.')) return;
                    try {
                        await API.bskyDisconnect();
                        this.renderSettings();
                    } catch (err) {
                        alert('Failed: ' + err.message);
                    }
                });
            }

            // BSKY Poll Now
            const bskyPollBtn = document.getElementById('bsky-poll-btn');
            if (bskyPollBtn) {
                bskyPollBtn.addEventListener('click', async () => {
                    const msg = document.getElementById('bsky-msg');
                    bskyPollBtn.disabled = true;
                    bskyPollBtn.textContent = 'Polling...';
                    if (msg) msg.textContent = '';
                    try {
                        await API.triggerBSKYPoll();
                        bskyPollBtn.textContent = 'Done!';
                        setTimeout(() => this.renderSettings(), 1500);
                    } catch (err) {
                        bskyPollBtn.textContent = 'Error';
                        if (msg) { msg.textContent = err.message; msg.style.color = 'var(--danger)'; }
                        setTimeout(() => this.renderSettings(), 2000);
                    }
                });
            }

            // BSKY Full Resync
            const bskyResyncBtn = document.getElementById('bsky-resync-btn');
            if (bskyResyncBtn) {
                bskyResyncBtn.addEventListener('click', async () => {
                    if (!confirm('BSKY full resync will re-fetch all post details. This may take a while. Continue?')) return;
                    const msg = document.getElementById('bsky-msg');
                    bskyResyncBtn.disabled = true;
                    bskyResyncBtn.textContent = 'Syncing...';
                    if (msg) msg.textContent = '';
                    try {
                        await API.fullBSKYResync();
                        bskyResyncBtn.textContent = 'Done!';
                        setTimeout(() => this.renderSettings(), 1500);
                    } catch (err) {
                        bskyResyncBtn.textContent = 'Error';
                        if (msg) { msg.textContent = err.message; msg.style.color = 'var(--danger)'; }
                        setTimeout(() => this.renderSettings(), 2000);
                    }
                });
            }

            // BSKY: Notifications toggle
            const bskyNotifToggle = document.getElementById('pref-bsky-notifications');
            if (bskyNotifToggle) {
                bskyNotifToggle.addEventListener('change', async (e) => {
                    try {
                        await API.savePreferences({ bsky_notifications_enabled: e.target.checked });
                    } catch (err) {
                        e.target.checked = !e.target.checked;
                        alert('Failed to save preference: ' + err.message);
                    }
                });
            }

            // TW Connect: sends auth_token + ct0 + target_user
            const twConnectBtn = document.getElementById('tw-connect-btn');
            if (twConnectBtn) {
                twConnectBtn.addEventListener('click', async () => {
                    const msg = document.getElementById('tw-msg');
                    const auth_token = document.getElementById('tw-auth-token').value.trim();
                    const ct0 = document.getElementById('tw-ct0').value.trim();
                    const target_user = document.getElementById('tw-target-user').value.trim();
                    if (!auth_token || !target_user) {
                        msg.textContent = 'auth_token and username are required';
                        msg.style.color = 'var(--danger)';
                        return;
                    }
                    twConnectBtn.disabled = true;
                    twConnectBtn.textContent = 'Connecting...';
                    msg.textContent = '';
                    try {
                        await API.twConnect({ auth_token, ct0, target_user });
                        msg.textContent = 'Connected!';
                        msg.style.color = 'var(--success)';
                        setTimeout(() => this.renderSettings(), 1000);
                    } catch (err) {
                        let detail = err.message.replace(/^API \d+:\s*/, '');
                        try { detail = JSON.parse(detail).detail || detail; } catch {}
                        msg.textContent = detail;
                        msg.style.color = 'var(--danger)';
                        twConnectBtn.textContent = 'Connect';
                        twConnectBtn.disabled = false;
                    }
                });
            }

            // TW Disconnect
            const twDisconnectBtn = document.getElementById('tw-disconnect-btn');
            if (twDisconnectBtn) {
                twDisconnectBtn.addEventListener('click', async () => {
                    if (!confirm('Disconnect X/Twitter? This clears your cookies.')) return;
                    try {
                        await API.twDisconnect();
                        this.renderSettings();
                    } catch (err) {
                        alert('Failed: ' + err.message);
                    }
                });
            }

            // TW Poll Now
            const twPollBtn = document.getElementById('tw-poll-btn');
            if (twPollBtn) {
                twPollBtn.addEventListener('click', async () => {
                    const msg = document.getElementById('tw-msg');
                    twPollBtn.disabled = true;
                    twPollBtn.textContent = 'Polling...';
                    if (msg) msg.textContent = '';
                    try {
                        await API.triggerTWPoll();
                        twPollBtn.textContent = 'Done!';
                        setTimeout(() => this.renderSettings(), 1500);
                    } catch (err) {
                        twPollBtn.textContent = 'Error';
                        if (msg) { msg.textContent = err.message; msg.style.color = 'var(--danger)'; }
                        setTimeout(() => this.renderSettings(), 2000);
                    }
                });
            }

            // TW Full Resync
            const twResyncBtn = document.getElementById('tw-resync-btn');
            if (twResyncBtn) {
                twResyncBtn.addEventListener('click', async () => {
                    if (!confirm('TW full resync will re-fetch all tweet details. This may take a while. Continue?')) return;
                    const msg = document.getElementById('tw-msg');
                    twResyncBtn.disabled = true;
                    twResyncBtn.textContent = 'Syncing...';
                    if (msg) msg.textContent = '';
                    try {
                        await API.fullTWResync();
                        twResyncBtn.textContent = 'Done!';
                        setTimeout(() => this.renderSettings(), 1500);
                    } catch (err) {
                        twResyncBtn.textContent = 'Error';
                        if (msg) { msg.textContent = err.message; msg.style.color = 'var(--danger)'; }
                        setTimeout(() => this.renderSettings(), 2000);
                    }
                });
            }

            // TW: Notifications toggle
            const twNotifToggle = document.getElementById('pref-tw-notifications');
            if (twNotifToggle) {
                twNotifToggle.addEventListener('change', async (e) => {
                    try {
                        await API.savePreferences({ tw_notifications_enabled: e.target.checked });
                    } catch (err) {
                        e.target.checked = !e.target.checked;
                        alert('Failed to save preference: ' + err.message);
                    }
                });
            }

            // Save Milestones
            document.getElementById('save-milestones-btn')?.addEventListener('click', async () => {
                const msg = document.getElementById('milestones-msg');
                const parse = (id) => document.getElementById(id).value.split(',').map(s => parseInt(s.trim())).filter(n => n > 0).sort((a, b) => a - b);
                try {
                    const payload = {
                        milestone_views: parse('pref-milestone-views'),
                        milestone_faves: parse('pref-milestone-faves'),
                        milestone_comments: parse('pref-milestone-comments'),
                    };
                    await API.savePreferences(payload);
                    msg.textContent = 'Saved!'; msg.style.color = 'var(--success)';
                } catch (err) {
                    msg.textContent = 'Error: ' + err.message; msg.style.color = 'var(--danger)';
                }
            });

            // Backup Download
            document.getElementById('backup-download-btn')?.addEventListener('click', () => API.downloadBackup());

            // Backup Restore
            const restoreFileInput = document.getElementById('restore-file-input');
            const restoreBtn = document.getElementById('backup-restore-btn');
            if (restoreFileInput && restoreBtn) {
                restoreFileInput.addEventListener('change', () => {
                    restoreBtn.disabled = !restoreFileInput.files.length;
                });
                restoreBtn.addEventListener('click', async () => {
                    if (!confirm('Replace current database with this backup? This cannot be undone.')) return;
                    const msg = document.getElementById('backup-msg');
                    restoreBtn.disabled = true;
                    restoreBtn.textContent = 'Restoring...';
                    try {
                        const formData = new FormData();
                        formData.append('file', restoreFileInput.files[0]);
                        await API.restoreBackup(formData);
                        msg.textContent = 'Restored! Reloading...'; msg.style.color = 'var(--success)';
                        setTimeout(() => window.location.reload(), 1500);
                    } catch (err) {
                        msg.textContent = 'Error: ' + err.message; msg.style.color = 'var(--danger)';
                        restoreBtn.textContent = 'Restore';
                        restoreBtn.disabled = false;
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

            // Check for Updates button (shown when already up to date)
            const checkUpdateBtn = document.getElementById('check-update-btn');
            if (checkUpdateBtn) {
                checkUpdateBtn.addEventListener('click', async () => {
                    checkUpdateBtn.disabled = true;
                    checkUpdateBtn.textContent = 'Checking...';
                    try {
                        const result = await API.checkUpdate();
                        if (result.available) {
                            // Re-render settings to show the update section
                            this.renderSettings();
                        } else {
                            const statusText = document.getElementById('update-status-text');
                            if (statusText) statusText.textContent = 'Up to date';
                            checkUpdateBtn.textContent = 'No updates';
                            setTimeout(() => { checkUpdateBtn.textContent = 'Check for Updates'; checkUpdateBtn.disabled = false; }, 3000);
                        }
                    } catch (err) {
                        checkUpdateBtn.textContent = 'Check failed';
                        setTimeout(() => { checkUpdateBtn.textContent = 'Check for Updates'; checkUpdateBtn.disabled = false; }, 3000);
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

    // View toggle: grid ↔ list. Stores preference in localStorage, swaps visibility.
    _bindViewToggle() {
        document.querySelectorAll('.view-toggle-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                const mode = btn.dataset.view;
                localStorage.setItem('pp-view-mode', mode);
                document.querySelectorAll('.view-toggle-btn').forEach(b => b.classList.remove('active'));
                btn.classList.add('active');
                const grid = document.getElementById('grid-container');
                const table = document.getElementById('table-container');
                if (grid) grid.style.display = mode === 'grid' ? '' : 'none';
                if (table) table.style.display = mode === 'list' ? '' : 'none';
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

    // SQW variant of _bindTableSort(). Targets #sqw-submissions-table headers,
    // uses _sqwSortState + renderSQWSubmissions().
    _bindSQWTableSort() {
        document.querySelectorAll('#sqw-submissions-table th[data-sort]').forEach(th => {
            th.addEventListener('click', () => {
                const field = th.dataset.sort;
                if (this._sqwSortState.field === field) {
                    this._sqwSortState.order = this._sqwSortState.order === 'desc' ? 'asc' : 'desc';
                } else {
                    this._sqwSortState.field = field;
                    this._sqwSortState.order = 'desc';
                }
                this.renderSQWSubmissions();
            });
        });
    },

    // SQW variant of _bindSearch(). Filters by text (title/tags) and rating.
    _bindSQWSearch(allSubmissions) {
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

            document.getElementById('table-container').innerHTML = Components.sqwSubmissionsTable(filtered);
            this._bindSQWTableSort();
        };

        input?.addEventListener('input', doFilter);
        ratingSelect?.addEventListener('change', doFilter);
    },

    // AO3 variant of _bindTableSort(). Targets #ao3-submissions-table headers,
    // uses _ao3SortState + renderAO3Submissions().
    _bindAO3TableSort() {
        document.querySelectorAll('#ao3-submissions-table th[data-sort]').forEach(th => {
            th.addEventListener('click', () => {
                const field = th.dataset.sort;
                if (this._ao3SortState.field === field) {
                    this._ao3SortState.order = this._ao3SortState.order === 'desc' ? 'asc' : 'desc';
                } else {
                    this._ao3SortState.field = field;
                    this._ao3SortState.order = 'desc';
                }
                this.renderAO3Submissions();
            });
        });
    },

    // AO3 variant of _bindSearch(). Filters by text (title/tags) and rating.
    _bindAO3Search(allSubmissions) {
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

            document.getElementById('table-container').innerHTML = Components.ao3SubmissionsTable(filtered);
            this._bindAO3TableSort();
        };

        input?.addEventListener('input', doFilter);
        ratingSelect?.addEventListener('change', doFilter);
    },

    // DA variant of _bindTableSort(). Targets #da-submissions-table headers,
    // uses _daSortState + renderDASubmissions().
    _bindDATableSort() {
        document.querySelectorAll('#da-submissions-table th[data-sort]').forEach(th => {
            th.addEventListener('click', () => {
                const field = th.dataset.sort;
                if (this._daSortState.field === field) {
                    this._daSortState.order = this._daSortState.order === 'desc' ? 'asc' : 'desc';
                } else {
                    this._daSortState.field = field;
                    this._daSortState.order = 'desc';
                }
                this.renderDASubmissions();
            });
        });
    },

    // DA variant of _bindSearch(). Filters by text (title/keywords) and rating.
    _bindDASearch(allSubmissions) {
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

            document.getElementById('table-container').innerHTML = Components.daSubmissionsTable(filtered);
            this._bindDATableSort();
        };

        input?.addEventListener('input', doFilter);
        ratingSelect?.addEventListener('change', doFilter);
    },

    // WP variant of _bindTableSort(). Targets #wp-submissions-table headers,
    // uses _wpSortState + renderWPSubmissions().
    _bindWPTableSort() {
        document.querySelectorAll('#wp-submissions-table th[data-sort]').forEach(th => {
            th.addEventListener('click', () => {
                const field = th.dataset.sort;
                if (this._wpSortState.field === field) {
                    this._wpSortState.order = this._wpSortState.order === 'desc' ? 'asc' : 'desc';
                } else {
                    this._wpSortState.field = field;
                    this._wpSortState.order = 'desc';
                }
                this.renderWPSubmissions();
            });
        });
    },

    // WP variant of _bindSearch(). Filters by text (title only — Wattpad has no rating filter).
    _bindWPSearch(allSubmissions) {
        const input = document.getElementById('search-input');

        const doFilter = () => {
            const q = (input?.value || '').toLowerCase();

            let filtered = allSubmissions;
            if (q) {
                filtered = filtered.filter(s =>
                    (s.title || '').toLowerCase().includes(q)
                );
            }

            document.getElementById('table-container').innerHTML = Components.wpSubmissionsTable(filtered);
            this._bindWPTableSort();
        };

        input?.addEventListener('input', doFilter);
    },

    // IK variant of _bindTableSort(). Targets #ik-submissions-table headers,
    // uses _ikSortState + renderIKSubmissions().
    _bindIKTableSort() {
        document.querySelectorAll('#ik-submissions-table th[data-sort]').forEach(th => {
            th.addEventListener('click', () => {
                const field = th.dataset.sort;
                if (this._ikSortState.field === field) {
                    this._ikSortState.order = this._ikSortState.order === 'desc' ? 'asc' : 'desc';
                } else {
                    this._ikSortState.field = field;
                    this._ikSortState.order = 'desc';
                }
                this.renderIKSubmissions();
            });
        });
    },

    // IK variant of _bindSearch(). Filters by text (title only).
    _bindIKSearch(allSubmissions) {
        const input = document.getElementById('search-input');

        const doFilter = () => {
            const q = (input?.value || '').toLowerCase();

            let filtered = allSubmissions;
            if (q) {
                filtered = filtered.filter(s =>
                    (s.title || '').toLowerCase().includes(q)
                );
            }

            document.getElementById('table-container').innerHTML = Components.ikSubmissionsTable(filtered);
            this._bindIKTableSort();
        };

        input?.addEventListener('input', doFilter);
    },

    // BSKY table sort binding — same pattern as IK but for BSKY.
    _bindBSKYTableSort() {
        document.querySelectorAll('#bsky-submissions-table th[data-sort]').forEach(th => {
            th.addEventListener('click', () => {
                const field = th.dataset.sort;
                if (this._bskySortState.field === field) {
                    this._bskySortState.order = this._bskySortState.order === 'desc' ? 'asc' : 'desc';
                } else {
                    this._bskySortState.field = field;
                    this._bskySortState.order = 'desc';
                }
                this.renderBSKYSubmissions();
            });
        });
    },

    // BSKY variant of _bindSearch(). Filters by text (title only).
    _bindBSKYSearch(allSubmissions) {
        const input = document.getElementById('search-input');

        const doFilter = () => {
            const q = (input?.value || '').toLowerCase();

            let filtered = allSubmissions;
            if (q) {
                filtered = filtered.filter(s =>
                    (s.title || '').toLowerCase().includes(q)
                );
            }

            document.getElementById('table-container').innerHTML = Components.bskySubmissionsTable(filtered);
            this._bindBSKYTableSort();
        };

        input?.addEventListener('input', doFilter);
    },

    // TW table sort binding — same pattern as IK but for TW.
    _bindTWTableSort() {
        document.querySelectorAll('#tw-submissions-table th[data-sort]').forEach(th => {
            th.addEventListener('click', () => {
                const field = th.dataset.sort;
                if (this._twSortState.field === field) {
                    this._twSortState.order = this._twSortState.order === 'desc' ? 'asc' : 'desc';
                } else {
                    this._twSortState.field = field;
                    this._twSortState.order = 'desc';
                }
                this.renderTWSubmissions();
            });
        });
    },

    // TW variant of _bindSearch(). Filters by text (title only).
    _bindTWSearch(allSubmissions) {
        const input = document.getElementById('search-input');

        const doFilter = () => {
            const q = (input?.value || '').toLowerCase();

            let filtered = allSubmissions;
            if (q) {
                filtered = filtered.filter(s =>
                    (s.title || '').toLowerCase().includes(q)
                );
            }

            document.getElementById('table-container').innerHTML = Components.twSubmissionsTable(filtered);
            this._bindTWTableSort();
        };

        input?.addEventListener('input', doFilter);
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

    // ── Pin/Goal/Tag action helpers ──────────────────────────

    // Binds click handlers for unpin buttons and goal delete buttons on dashboards
    _bindPinAndGoalActions(rerender) {
        document.querySelectorAll('.pinned-card[data-nav]').forEach(card => {
            card.addEventListener('click', (e) => {
                if (e.target.closest('.btn-unpin')) return;
                const nav = card.dataset.nav;
                if (nav) this.navigate('/' + nav);
            });
            card.style.cursor = 'pointer';
        });
        document.querySelectorAll('.btn-unpin').forEach(btn => {
            btn.addEventListener('click', async (e) => {
                e.stopPropagation();
                try {
                    await API.removePin(btn.dataset.platform, btn.dataset.id);
                    rerender();
                } catch (err) { alert('Failed to unpin: ' + err.message); }
            });
        });
        document.querySelectorAll('.btn-goal-delete').forEach(btn => {
            btn.addEventListener('click', async () => {
                if (!confirm('Delete this goal?')) return;
                try {
                    await API.deleteGoal(parseInt(btn.dataset.goalId));
                    rerender();
                } catch (err) { alert('Failed to delete goal: ' + err.message); }
            });
        });
    },

    // Binds pin toggle button and tag add button on detail pages
    _bindDetailPinTag(platform, subId, allTags, rerender) {
        document.querySelectorAll('.btn-pin').forEach(btn => {
            btn.addEventListener('click', async () => {
                const isPinned = btn.textContent.trim() === 'Unpin';
                try {
                    if (isPinned) {
                        await API.removePin(platform, subId);
                    } else {
                        await API.addPin({ platform, submission_id: subId });
                    }
                    rerender();
                } catch (err) { alert('Failed: ' + err.message); }
            });
        });
        document.querySelectorAll('.btn-add-tag').forEach(btn => {
            btn.addEventListener('click', async () => {
                if (!allTags.length) {
                    const name = prompt('Create a new tag (enter name):');
                    if (!name) return;
                    try {
                        const result = await API.createTag({ name });
                        await API.addTagToSubmission(result.tag_id, { platform, submission_id: subId });
                        rerender();
                    } catch (err) { alert('Failed: ' + err.message); }
                    return;
                }
                const options = allTags.map(t => `${t.tag_id}: ${t.name}`).join('\n');
                const choice = prompt(`Enter tag ID to add (or "new" to create):\n${options}`);
                if (!choice) return;
                try {
                    if (choice.toLowerCase() === 'new') {
                        const name = prompt('New tag name:');
                        if (!name) return;
                        const result = await API.createTag({ name });
                        await API.addTagToSubmission(result.tag_id, { platform, submission_id: subId });
                    } else {
                        const tagId = parseInt(choice);
                        if (isNaN(tagId)) return;
                        await API.addTagToSubmission(tagId, { platform, submission_id: subId });
                    }
                    rerender();
                } catch (err) { alert('Failed: ' + err.message); }
            });
        });
        document.querySelectorAll('.tag-badge[data-tag-id]').forEach(badge => {
            badge.style.cursor = 'pointer';
            badge.title = 'Click to remove tag';
            badge.addEventListener('click', async () => {
                try {
                    await API.removeTagFromSubmission(parseInt(badge.dataset.tagId), platform, subId);
                    rerender();
                } catch (err) { alert('Failed: ' + err.message); }
            });
        });
    },

    // ── Analytics Page ──────────────────────────────────────────

    async renderAnalytics() {
        this._loading();
        try {
            const data = await API.getHistoricalAnalytics({ weeks: 12 });

            const bestMonth = data.best_month || {};
            const fastest = data.fastest_growing || [];
            const weekly = data.weekly_growth || [];

            const html = `
                ${this._refreshIndicatorHtml()}
                <div class="page-header"><h2>Analytics</h2></div>

                <div class="stats-grid">
                    ${Components.highlightCard('Best Month (Views)', bestMonth.views ? `+${Utils.formatNumber(bestMonth.views.delta)}` : '--', bestMonth.views ? bestMonth.views.period : '')}
                    ${Components.highlightCard('Best Month (Faves)', bestMonth.faves ? `+${Utils.formatNumber(bestMonth.faves.delta)}` : '--', bestMonth.faves ? bestMonth.faves.period : '')}
                    ${Components.highlightCard('Best Month (Comments)', bestMonth.comments ? `+${Utils.formatNumber(bestMonth.comments.delta)}` : '--', bestMonth.comments ? bestMonth.comments.period : '')}
                </div>

                ${fastest.length ? `
                <div class="chart-container">
                    <h3>Fastest Growing All-Time</h3>
                    <div class="table-scroll">
                        <table class="data-table">
                            <thead><tr><th>Platform</th><th>Title</th><th>Views</th><th>Faves</th><th>Growth/Day</th></tr></thead>
                            <tbody>
                                ${fastest.map(f => {
                                    const isIK = (f.platform || '').toLowerCase() === 'ik';
                                    const isWP = (f.platform || '').toLowerCase() === 'wp';
                                    return `<tr>
                                    <td>${Utils.escapeHtml(f.platform || '')}</td>
                                    <td>${Utils.escapeHtml(f.title || '')}</td>
                                    <td>${isIK ? '--' : Utils.formatNumber(isWP ? (f.reads || f.views || 0) : (f.views || 0))}</td>
                                    <td>${Utils.formatNumber(f.faves || 0)}</td>
                                    <td>${(f.views_per_day || 0).toFixed(1)} ${isIK ? 'likes' : isWP ? 'reads' : 'views'}</td>
                                </tr>`;
                                }).join('')}
                            </tbody>
                        </table>
                    </div>
                </div>` : ''}

                ${weekly.length ? `
                <div class="chart-container">
                    <h3>Weekly Growth (Last 12 Weeks)</h3>
                    <div class="chart-wrap" style="min-height:300px"><canvas id="chart-weekly-growth"></canvas></div>
                </div>` : ''}
            `;

            this._setContent(html);

            if (weekly.length) {
                Charts.weeklyGrowthBar('chart-weekly-growth', weekly);
            }
        } catch (err) {
            this._setContent(`<div class="empty-state"><h3>Error loading analytics</h3><p>${Utils.escapeHtml(err.message)}</p></div>`);
        }
    },

    // Sidebar footer poll status ticker. Called on a 60-second interval set up
    // in init(). Fetches the latest poll log entry and updates the small
    // "Last poll: X ago" badge at the bottom of the sidebar. Failures are
    // silently ignored since this is purely cosmetic.
    async _updatePollStatus() {
        try {
            const [status, pauseState] = await Promise.all([
                API.getStatus(),
                API.getPollPaused().catch(() => ({ polling_paused: false })),
            ]);
            const el = document.getElementById('poll-status-mini');
            if (el) {
                if (pauseState.polling_paused) {
                    el.textContent = 'Polling paused';
                    el.style.color = 'var(--warning, #f0a050)';
                } else if (status.last_poll) {
                    el.textContent = `Last poll: ${Utils.timeAgo(status.last_poll.started_at)}`;
                    el.style.color = '';
                }
            }
        } catch { /* ignore */ }
    },

    // ── Global Poll Progress Bar ──────────────────────────────
    // Polls all 4 platform progress endpoints on a timer. When any platform
    // is actively polling, shows a thin progress bar at the top of the page.
    // Uses a fast interval (1.5s) when active, slow (10s) when idle.

    _pollProgressActive: false,
    _pollProgressTimer: null,

    _initPollProgressBar() {
        this._pollProgressTick();
        if (this._pollProgressTimer) clearInterval(this._pollProgressTimer);
        this._pollProgressTimer = setInterval(() => this._pollProgressTick(), 10000);
    },

    async _pollProgressTick() {
        const bar = document.getElementById('poll-progress-bar');
        const fill = document.getElementById('poll-progress-fill');
        const label = document.getElementById('poll-progress-label');
        if (!bar || !fill || !label) return;

        try {
            const [ib, fa, ws, sf, sqw, ao3, da, wp, ik] = await Promise.all([
                API.getPollProgress().catch(() => null),
                API.getFAPollProgress().catch(() => null),
                API.getWSPollProgress().catch(() => null),
                API.getSFPollProgress().catch(() => null),
                API.getSQWPollProgress().catch(() => null),
                API.getAO3PollProgress().catch(() => null),
                API.getDAPollProgress().catch(() => null),
                API.getWPPollProgress().catch(() => null),
                API.getIKPollProgress().catch(() => null),
            ]);

            const platforms = [
                { name: 'Inkbunny', data: ib },
                { name: 'FurAffinity', data: fa },
                { name: 'Weasyl', data: ws },
                { name: 'SoFurry', data: sf },
                { name: 'SquidgeWorld', data: sqw },
                { name: 'AO3', data: ao3 },
                { name: 'DeviantArt', data: da },
                { name: 'Wattpad', data: wp },
                { name: 'Itaku', data: ik },
            ];

            const active = platforms.filter(p => p.data && p.data.active);

            if (active.length === 0) {
                bar.style.display = 'none';
                if (this._pollProgressActive) {
                    this._pollProgressActive = false;
                    clearInterval(this._pollProgressTimer);
                    this._pollProgressTimer = setInterval(() => this._pollProgressTick(), 10000);
                }
                return;
            }

            // Switch to fast polling when active
            if (!this._pollProgressActive) {
                this._pollProgressActive = true;
                clearInterval(this._pollProgressTimer);
                this._pollProgressTimer = setInterval(() => this._pollProgressTick(), 1500);
            }

            bar.style.display = 'block';

            // Aggregate progress: average across active pollers
            let totalPct = 0;
            const labels = [];
            for (const p of active) {
                const d = p.data;
                let pct = 0;
                if (d.total > 0) {
                    pct = Math.round((d.current / d.total) * 100);
                } else if (d.phase === 'complete') {
                    pct = 100;
                } else if (d.phase === 'starting' || d.phase === 'logging_in') {
                    pct = 10;
                } else if (d.phase === 'searching') {
                    pct = 20;
                } else if (d.phase === 'fetching_details') {
                    pct = 35;
                } else {
                    pct = 5;
                }
                totalPct += pct;
                const msg = d.message || d.phase || '';
                if (d.total > 0) {
                    labels.push(`${p.name}: ${d.current}/${d.total}`);
                } else {
                    labels.push(`${p.name}: ${msg}`);
                }
            }

            const avgPct = Math.round(totalPct / active.length);
            fill.style.width = Math.min(100, Math.max(2, avgPct)) + '%';
            label.textContent = labels.join('  ·  ');

        } catch { /* ignore */ }
    },
};

// Boot
document.addEventListener('DOMContentLoaded', () => App.init());
