/* ── API fetch wrapper with error handling ─────────────────── */
/*
 * API — singleton object that centralises all backend communication.
 *
 * Every method returns a Promise that resolves to parsed JSON on success
 * or rejects with an Error whose message includes the HTTP status and
 * response body text.  Two core methods (get / post) handle the actual
 * fetch; every other property is a thin convenience wrapper that calls
 * one of those two so callers never need to remember endpoint paths.
 *
 * Usage:  const data = await API.getSubmissions({ page: 1, limit: 20 });
 */

// Debug logging — enable via: localStorage.setItem('pawpoller_debug', '1')
const _API_DEBUG = localStorage.getItem('pawpoller_debug') === '1';

const API = {

    /* ── Core transport: GET ────────────────────────────────────
     * Builds a fully-qualified URL from `path` and optional `params`,
     * stripping any null or empty-string values so the backend never
     * receives "?key=" noise.  Returns the parsed JSON body on a 2xx
     * response; throws an Error for network failures or non-OK status.
     */
    async get(path, params = {}) {
        const url = new URL(path, window.location.origin);
        Object.entries(params).forEach(([k, v]) => {
            if (v != null && v !== '') url.searchParams.set(k, v);
        });
        if (_API_DEBUG) console.log('[API] GET', url.toString());
        let resp;
        try {
            resp = await fetch(url);
        } catch (err) {
            console.error('[API] Network error:', err);
            throw new Error(`Network error: ${err.message}`);
        }
        if (!resp.ok) {
            const text = await resp.text();
            console.error(`[API] ${resp.status} on GET ${path}:`, text);
            throw new Error(`API ${resp.status}: ${text}`);
        }
        const data = await resp.json();
        if (_API_DEBUG) console.log('[API] Response:', path, data);
        return data;
    },

    /* ── Core transport: POST ───────────────────────────────────
     * Sends `body` as a JSON-encoded payload with the appropriate
     * Content-Type header.  Same error-handling pattern as get():
     * throws on network failure or non-OK HTTP status.
     */
    async post(path, body = {}) {
        if (_API_DEBUG) console.log('[API] POST', path, body);
        let resp;
        try {
            resp = await fetch(path, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body),
            });
        } catch (err) {
            console.error('[API] Network error:', err);
            throw new Error(`Network error: ${err.message}`);
        }
        if (!resp.ok) {
            const text = await resp.text();
            console.error(`[API] ${resp.status} on POST ${path}:`, text);
            throw new Error(`API ${resp.status}: ${text}`);
        }
        return resp.json();
    },

    /* ── IB (Inkbunny) convenience methods ─────────────────────
     * General status, submission CRUD, snapshot history, aggregation,
     * comparison, polling control, session management, authentication,
     * credential/preference storage, and Telegram notification wiring.
     * These are the "default" platform endpoints (no /fa/ or /ws/ prefix).
     */
    getStatus() { return this.get('/api/status'); },
    getSummary() { return this.get('/api/summary'); },
    getSubmissions(params) { return this.get('/api/submissions', params); },
    getSubmission(id) { return this.get(`/api/submissions/${id}`); },
    getSnapshots(id, params) { return this.get(`/api/submissions/${id}/snapshots`, params); },
    getAggregate(params) { return this.get('/api/aggregate', params); },
    getComparison(ids, params) { return this.get('/api/comparison', { ids: ids.join(','), ...params }); },
    getPollLog(limit) { return this.get('/api/poll_log', { limit }); },
    triggerPoll() { return this.post('/api/poll/trigger'); },
    fullResync() { return this.post('/api/poll/full-resync'); },
    pausePolling() { return this.post('/api/poll/pause'); },
    resumePolling() { return this.post('/api/poll/resume'); },
    getPollPaused() { return this.get('/api/poll/paused'); },
    getLogs(params = {}) { return this.get('/api/logs', params); },
    clearSession() { return this.post('/api/session/clear'); },
    getAuthStatus() { return this.get('/api/auth/status'); },
    authLogin(data) { return this.post('/api/auth/login', data); },
    authLogout() { return this.post('/api/auth/logout'); },
    getPollProgress() { return this.get('/api/poll/progress'); },
    getCredentials() { return this.get('/api/settings/credentials'); },
    saveCredentials(data) { return this.post('/api/settings/credentials', data); },
    getPreferences() { return this.get('/api/settings/preferences'); },
    savePreferences(data) { return this.post('/api/settings/preferences', data); },
    getTelegram() { return this.get('/api/settings/telegram'); },
    connectTelegram(data) { return this.post('/api/settings/telegram', data); },
    testTelegram() { return this.post('/api/settings/telegram/test'); },
    disconnectTelegram() { return this.post('/api/settings/telegram/disconnect'); },
    /* ── FA (FurAffinity) convenience methods ──────────────────
     * Mirror of the IB methods above, namespaced under /api/fa/.
     * Covers auth connection, status, submissions, snapshots,
     * aggregation, comparison, poll control, and resync.
     */
    getFAAuthStatus() { return this.get('/api/fa/auth/status'); },
    faConnect(data) { return this.post('/api/fa/auth/connect', data); },
    faDisconnect() { return this.post('/api/fa/auth/disconnect'); },
    getFAStatus() { return this.get('/api/fa/status'); },
    getFASummary() { return this.get('/api/fa/summary'); },
    getFASubmissions(params) { return this.get('/api/fa/submissions', params); },
    getFASubmission(id) { return this.get(`/api/fa/submissions/${id}`); },
    getFASnapshots(id, params) { return this.get(`/api/fa/submissions/${id}/snapshots`, params); },
    getFAAggregate(params) { return this.get('/api/fa/aggregate', params); },
    getFAComparison(ids, params) { return this.get('/api/fa/comparison', { ids: ids.join(','), ...params }); },
    getFAPollLog(limit) { return this.get('/api/fa/poll_log', { limit }); },
    triggerFAPoll() { return this.post('/api/fa/poll/trigger'); },
    fullFAResync() { return this.post('/api/fa/poll/full-resync'); },
    getFAPollProgress() { return this.get('/api/fa/poll/progress'); },
    getWatchers() { return this.get('/api/watchers'); },
    getFAWatchers() { return this.get('/api/fa/watchers'); },
    /* ── WS (Weasyl) convenience methods ───────────────────────
     * Mirror of the IB/FA methods, namespaced under /api/ws/.
     * Covers auth connection, status, submissions, snapshots,
     * aggregation, comparison, poll control, and resync.
     */
    getWSAuthStatus() { return this.get('/api/ws/auth/status'); },
    wsConnect(data) { return this.post('/api/ws/auth/connect', data); },
    wsDisconnect() { return this.post('/api/ws/auth/disconnect'); },
    getWSStatus() { return this.get('/api/ws/status'); },
    getWSSummary() { return this.get('/api/ws/summary'); },
    getWSSubmissions(params) { return this.get('/api/ws/submissions', params); },
    getWSSubmission(id) { return this.get(`/api/ws/submissions/${id}`); },
    getWSSnapshots(id, params) { return this.get(`/api/ws/submissions/${id}/snapshots`, params); },
    getWSAggregate(params) { return this.get('/api/ws/aggregate', params); },
    getWSComparison(ids, params) { return this.get('/api/ws/comparison', { ids: ids.join(','), ...params }); },
    getWSPollLog(limit) { return this.get('/api/ws/poll_log', { limit }); },
    triggerWSPoll() { return this.post('/api/ws/poll/trigger'); },
    fullWSResync() { return this.post('/api/ws/poll/full-resync'); },
    getWSPollProgress() { return this.get('/api/ws/poll/progress'); },
    /* ── SF (SoFurry) convenience methods ────────────────────────
     * Mirror of the WS methods, namespaced under /api/sf/.
     * SoFurry uses email/password auth instead of API key.
     */
    getSFAuthStatus() { return this.get('/api/sf/auth/status'); },
    sfConnect(data) { return this.post('/api/sf/auth/connect', data); },
    sfDisconnect() { return this.post('/api/sf/auth/disconnect'); },
    getSFStatus() { return this.get('/api/sf/status'); },
    getSFSummary() { return this.get('/api/sf/summary'); },
    getSFSubmissions(params) { return this.get('/api/sf/submissions', params); },
    getSFSubmission(id) { return this.get(`/api/sf/submissions/${id}`); },
    getSFSnapshots(id, params) { return this.get(`/api/sf/submissions/${id}/snapshots`, params); },
    getSFAggregate(params) { return this.get('/api/sf/aggregate', params); },
    getSFComparison(ids, params) { return this.get('/api/sf/comparison', { ids: ids.join(','), ...params }); },
    getSFPollLog(limit) { return this.get('/api/sf/poll_log', { limit }); },
    triggerSFPoll() { return this.post('/api/sf/poll/trigger'); },
    fullSFResync() { return this.post('/api/sf/poll/full-resync'); },
    getSFPollProgress() { return this.get('/api/sf/poll/progress'); },
    /* ── SQW (SquidgeWorld) convenience methods ──────────────────
     * Mirror of the SF methods, namespaced under /api/sqw/.
     * SquidgeWorld uses username/password auth to track a target user.
     */
    getSQWAuthStatus() { return this.get('/api/sqw/auth/status'); },
    sqwConnect(data) { return this.post('/api/sqw/auth/connect', data); },
    sqwDisconnect() { return this.post('/api/sqw/auth/disconnect'); },
    getSQWStatus() { return this.get('/api/sqw/status'); },
    getSQWSummary() { return this.get('/api/sqw/summary'); },
    getSQWSubmissions(params) { return this.get('/api/sqw/submissions', params); },
    getSQWSubmission(id) { return this.get(`/api/sqw/submissions/${id}`); },
    getSQWSnapshots(id, params) { return this.get(`/api/sqw/submissions/${id}/snapshots`, params); },
    getSQWAggregate(params) { return this.get('/api/sqw/aggregate', params); },
    getSQWComparison(ids, params) { return this.get('/api/sqw/comparison', { ids: ids.join(','), ...params }); },
    getSQWPollLog(limit) { return this.get('/api/sqw/poll_log', { limit }); },
    triggerSQWPoll() { return this.post('/api/sqw/poll/trigger'); },
    fullSQWResync() { return this.post('/api/sqw/poll/full-resync'); },
    getSQWPollProgress() { return this.get('/api/sqw/poll/progress'); },
    /* ── AO3 (Archive of Our Own) convenience methods ──────────────
     * Mirror of the SQW methods, namespaced under /api/ao3/.
     * AO3 uses username/password auth to track a target user.
     */
    getAO3AuthStatus() { return this.get('/api/ao3/auth/status'); },
    ao3Connect(data) { return this.post('/api/ao3/auth/connect', data); },
    ao3Disconnect() { return this.post('/api/ao3/auth/disconnect'); },
    getAO3Status() { return this.get('/api/ao3/status'); },
    getAO3Summary() { return this.get('/api/ao3/summary'); },
    getAO3Submissions(params) { return this.get('/api/ao3/submissions', params); },
    getAO3Submission(id) { return this.get(`/api/ao3/submissions/${id}`); },
    getAO3Snapshots(id, params) { return this.get(`/api/ao3/submissions/${id}/snapshots`, params); },
    getAO3Aggregate(params) { return this.get('/api/ao3/aggregate', params); },
    getAO3Comparison(ids, params) { return this.get('/api/ao3/comparison', { ids: ids.join(','), ...params }); },
    getAO3PollLog(limit) { return this.get('/api/ao3/poll_log', { limit }); },
    triggerAO3Poll() { return this.post('/api/ao3/poll/trigger'); },
    fullAO3Resync() { return this.post('/api/ao3/poll/full-resync'); },
    getAO3PollProgress() { return this.get('/api/ao3/poll/progress'); },
    /* ── DA (DeviantArt) convenience methods ────────────────────────
     * Mirror of the FA methods, namespaced under /api/da/.
     * DeviantArt uses cookie-based auth with a target user to track.
     */
    getDAAuthStatus() { return this.get('/api/da/auth/status'); },
    daConnect(data) { return this.post('/api/da/auth/connect', data); },
    daDisconnect() { return this.post('/api/da/auth/disconnect'); },
    getDAStatus() { return this.get('/api/da/status'); },
    getDASummary() { return this.get('/api/da/summary'); },
    getDASubmissions(params) { return this.get('/api/da/submissions', params); },
    getDASubmission(id) { return this.get(`/api/da/submissions/${id}`); },
    getDASnapshots(id, params) { return this.get(`/api/da/submissions/${id}/snapshots`, params); },
    getDAAggregate(params) { return this.get('/api/da/aggregate', params); },
    getDAComparison(ids, params) { return this.get('/api/da/comparison', { ids: ids.join(','), ...params }); },
    getDAPollLog(limit) { return this.get('/api/da/poll_log', { limit }); },
    triggerDAPoll() { return this.post('/api/da/poll/trigger'); },
    fullDAResync() { return this.post('/api/da/poll/full-resync'); },
    getDAPollProgress() { return this.get('/api/da/poll/progress'); },
    /* ── WP (Wattpad) convenience methods ─────────────────────────
     * Mirror of the DA methods, namespaced under /api/wp/.
     * Wattpad uses username-only auth (no password or cookie needed).
     */
    getWPAuthStatus() { return this.get('/api/wp/auth/status'); },
    wpConnect(data) { return this.post('/api/wp/auth/connect', data); },
    wpDisconnect() { return this.post('/api/wp/auth/disconnect'); },
    getWPStatus() { return this.get('/api/wp/status'); },
    getWPSummary() { return this.get('/api/wp/summary'); },
    getWPSubmissions(params) { return this.get('/api/wp/submissions', params); },
    getWPSubmission(id) { return this.get(`/api/wp/submissions/${id}`); },
    getWPSnapshots(id, params) { return this.get(`/api/wp/submissions/${id}/snapshots`, params); },
    getWPAggregate(params) { return this.get('/api/wp/aggregate', params); },
    getWPComparison(ids, params) { return this.get('/api/wp/comparison', { ids: ids.join(','), ...params }); },
    getWPPollLog(limit) { return this.get('/api/wp/poll_log', { limit }); },
    triggerWPPoll() { return this.post('/api/wp/poll/trigger'); },
    fullWPResync() { return this.post('/api/wp/poll/full-resync'); },
    getWPPollProgress() { return this.get('/api/wp/poll/progress'); },
    /* ── IK (Itaku) convenience methods ──────────────────────────
     * Mirror of the WP methods, namespaced under /api/ik/.
     * Itaku uses username-only auth (no password or cookie needed).
     * Tracks likes, comments, reshares (no views).
     */
    getIKAuthStatus() { return this.get('/api/ik/auth/status'); },
    ikConnect(data) { return this.post('/api/ik/auth/connect', data); },
    ikDisconnect() { return this.post('/api/ik/auth/disconnect'); },
    getIKStatus() { return this.get('/api/ik/status'); },
    getIKSummary() { return this.get('/api/ik/summary'); },
    getIKSubmissions(params) { return this.get('/api/ik/submissions', params); },
    getIKSubmission(id) { return this.get(`/api/ik/submissions/${id}`); },
    getIKSnapshots(id, params) { return this.get(`/api/ik/submissions/${id}/snapshots`, params); },
    getIKAggregate(params) { return this.get('/api/ik/aggregate', params); },
    getIKComparison(ids, params) { return this.get('/api/ik/comparison', { ids: ids.join(','), ...params }); },
    getIKPollLog(limit) { return this.get('/api/ik/poll_log', { limit }); },
    triggerIKPoll() { return this.post('/api/ik/poll/trigger'); },
    fullIKResync() { return this.post('/api/ik/poll/full-resync'); },
    getIKPollProgress() { return this.get('/api/ik/poll/progress'); },
    /* ── BSKY (Bluesky) convenience methods ───────────────────────
     * AT Protocol API with app password auth. Posts identified by AT URIs.
     * Tracks likes, reposts, replies, quotes (no views).
     */
    getBSKYAuthStatus() { return this.get('/api/bsky/auth/status'); },
    bskyConnect(data) { return this.post('/api/bsky/auth/connect', data); },
    bskyDisconnect() { return this.post('/api/bsky/auth/disconnect'); },
    getBSKYStatus() { return this.get('/api/bsky/status'); },
    getBSKYSummary() { return this.get('/api/bsky/summary'); },
    getBSKYSubmissions(params) { return this.get('/api/bsky/submissions', params); },
    getBSKYSubmission(id) { return this.get(`/api/bsky/submissions/${encodeURIComponent(id)}`); },
    getBSKYSnapshots(id, params) { return this.get(`/api/bsky/submissions/${encodeURIComponent(id)}/snapshots`, params); },
    getBSKYAggregate(params) { return this.get('/api/bsky/aggregate', params); },
    getBSKYComparison(ids, params) { return this.get('/api/bsky/comparison', { ids: ids.join(','), ...params }); },
    getBSKYPollLog(limit) { return this.get('/api/bsky/poll_log', { limit }); },
    triggerBSKYPoll() { return this.post('/api/bsky/poll/trigger'); },
    fullBSKYResync() { return this.post('/api/bsky/poll/full-resync'); },
    getBSKYPollProgress() { return this.get('/api/bsky/poll/progress'); },
    /* ── TW (X/Twitter) convenience methods ───────────────────────
     * Cookie-based GraphQL API. Tweets identified by numeric ID strings.
     * Tracks views, likes, retweets, replies, quotes, bookmarks.
     */
    getTWAuthStatus() { return this.get('/api/tw/auth/status'); },
    twConnect(data) { return this.post('/api/tw/auth/connect', data); },
    twDisconnect() { return this.post('/api/tw/auth/disconnect'); },
    getTWStatus() { return this.get('/api/tw/status'); },
    getTWSummary() { return this.get('/api/tw/summary'); },
    getTWSubmissions(params) { return this.get('/api/tw/submissions', params); },
    getTWSubmission(id) { return this.get(`/api/tw/submissions/${id}`); },
    getTWSnapshots(id, params) { return this.get(`/api/tw/submissions/${id}/snapshots`, params); },
    getTWAggregate(params) { return this.get('/api/tw/aggregate', params); },
    getTWComparison(ids, params) { return this.get('/api/tw/comparison', { ids: ids.join(','), ...params }); },
    getTWPollLog(limit) { return this.get('/api/tw/poll_log', { limit }); },
    triggerTWPoll() { return this.post('/api/tw/poll/trigger'); },
    fullTWResync() { return this.post('/api/tw/poll/full-resync'); },
    getTWPollProgress() { return this.get('/api/tw/poll/progress'); },
    /* ── Export methods ───────────────────────────────────────────
     * These trigger browser-native file downloads by opening the
     * streaming CSV endpoint in a new tab via window.open().
     * They do NOT use get()/post() because the response is a file
     * download, not JSON to be parsed in-page.
     */
    exportSubmissions(platform) {
        const urls = { ib: '/api/export/submissions', fa: '/api/fa/export/submissions', ws: '/api/ws/export/submissions', sf: '/api/sf/export/submissions', sqw: '/api/sqw/export/submissions', ao3: '/api/ao3/export/submissions', da: '/api/da/export/submissions', wp: '/api/wp/export/submissions', ik: '/api/ik/export/submissions', bsky: '/api/bsky/export/submissions', tw: '/api/tw/export/submissions' };
        window.open(urls[platform] || urls.ib, '_blank');
    },
    exportSnapshots(platform, id) {
        const bases = { ib: '/api/export/snapshots', fa: '/api/fa/export/snapshots', ws: '/api/ws/export/snapshots', sf: '/api/sf/export/snapshots', sqw: '/api/sqw/export/snapshots', ao3: '/api/ao3/export/snapshots', da: '/api/da/export/snapshots', wp: '/api/wp/export/snapshots', ik: '/api/ik/export/snapshots', bsky: '/api/bsky/export/snapshots', tw: '/api/tw/export/snapshots' };
        const url = (bases[platform] || bases.ib) + (id ? `?id=${id}` : '');
        window.open(url, '_blank');
    },
    /* ── Groups methods ──────────────────────────────────────────
     * CRUD for user-defined submission groups.  deleteGroup and
     * removeGroupMember use raw fetch() with method: 'DELETE' because
     * the post() wrapper only supports POST — there is no delete()
     * core transport method.
     */
    getGroups() { return this.get('/api/groups'); },
    createGroup(data) { return this.post('/api/groups', data); },
    updateGroup(id, data) { return this.post(`/api/groups/${id}`, data); },
    deleteGroup(id) {
        return fetch(`/api/groups/${id}`, { method: 'DELETE' }).then(r => {
            if (!r.ok) throw new Error(`Delete failed: ${r.status}`);
            return r.json();
        });
    },
    addGroupMember(groupId, data) { return this.post(`/api/groups/${groupId}/members`, data); },
    removeGroupMember(groupId, platform, subId) {
        return fetch(`/api/groups/${groupId}/members?platform=${platform}&submission_id=${subId}`, { method: 'DELETE' }).then(r => {
            if (!r.ok) throw new Error(`Remove member failed: ${r.status}`);
            return r.json();
        });
    },
    getGroupStats(id) { return this.get(`/api/groups/${id}/stats`); },
    /* ── Analytics methods ──────────────────────────────────────
     * Aggregated cross-submission analytics: top commenters/faves
     * and trending submission discovery.
     */
    getTopFans(limit) { return this.get('/api/analytics/top-fans', { limit }); },
    getTrending(params) { return this.get('/api/analytics/trending', params); },
    /* ── Cross-Platform Links methods ────────────────────────────
     * Manages links that tie the same submission across IB/FA/WS so
     * stats can be viewed together.  deleteLink uses raw fetch() with
     * method: 'DELETE' for the same reason as deleteGroup above.
     */
    getLinks() { return this.get('/api/links'); },
    createLink(data) { return this.post('/api/links', data); },
    deleteLink(id) {
        return fetch(`/api/links/${id}`, { method: 'DELETE' }).then(r => {
            if (!r.ok) throw new Error(`Delete link failed: ${r.status}`);
            return r.json();
        });
    },
    getLinkStats(id) { return this.get(`/api/links/${id}/stats`); },
    getLinkSnapshots(id) { return this.get(`/api/links/${id}/snapshots`); },
    getLinkSuggestions() { return this.get('/api/links/suggestions'); },
    /* ── Auto-Update methods ─────────────────────────────────────
     * Checks for new PawPoller releases and applies updates
     * through the backend's self-update mechanism.
     */
    checkUpdate() { return this.get('/api/update/check'); },
    applyUpdate(data) { return this.post('/api/update/apply', data); },
    /* ── Pins methods ─────────────────────────────────────────────
     * Pin/unpin favourite submissions to dashboard tops.
     */
    getPins() { return this.get('/api/pins'); },
    addPin(data) { return this.post('/api/pins', data); },
    removePin(platform, submissionId) {
        return fetch(`/api/pins?platform=${platform}&submission_id=${submissionId}`, { method: 'DELETE' }).then(r => {
            if (!r.ok) throw new Error(`Unpin failed: ${r.status}`);
            return r.json();
        });
    },
    /* ── Goals methods ────────────────────────────────────────────
     * Track progress toward user-defined metric targets.
     */
    getGoals() { return this.get('/api/goals'); },
    createGoal(data) { return this.post('/api/goals', data); },
    deleteGoal(id) {
        return fetch(`/api/goals/${id}`, { method: 'DELETE' }).then(r => {
            if (!r.ok) throw new Error(`Delete goal failed: ${r.status}`);
            return r.json();
        });
    },
    /* ── Tags methods ─────────────────────────────────────────────
     * User-defined submission categorisation labels.
     */
    getTags() { return this.get('/api/tags'); },
    createTag(data) { return this.post('/api/tags', data); },
    deleteTag(id) {
        return fetch(`/api/tags/${id}`, { method: 'DELETE' }).then(r => {
            if (!r.ok) throw new Error(`Delete tag failed: ${r.status}`);
            return r.json();
        });
    },
    addTagToSubmission(tagId, data) { return this.post(`/api/tags/${tagId}/submissions`, data); },
    removeTagFromSubmission(tagId, platform, submissionId) {
        return fetch(`/api/tags/${tagId}/submissions?platform=${platform}&submission_id=${submissionId}`, { method: 'DELETE' }).then(r => {
            if (!r.ok) throw new Error(`Remove tag failed: ${r.status}`);
            return r.json();
        });
    },
    getTagStats(id) { return this.get(`/api/tags/${id}/stats`); },
    /* ── Backup methods ───────────────────────────────────────────
     * Database backup and restore.
     */
    downloadBackup() { window.open('/api/backup/database', '_blank'); },
    restoreBackup(formData) {
        return fetch('/api/backup/restore', { method: 'POST', body: formData }).then(r => {
            if (!r.ok) throw new Error(`Restore failed: ${r.status}`);
            return r.json();
        });
    },
    /* ── Historical Analytics ─────────────────────────────────────
     * Best periods, fastest growing, weekly growth reports.
     */
    getHistoricalAnalytics(params) { return this.get('/api/analytics/historical', params); },
};
