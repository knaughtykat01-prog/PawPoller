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
        console.log('[API] GET', url.toString());
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
        console.log('[API] Response:', path, data);
        return data;
    },

    /* ── Core transport: POST ───────────────────────────────────
     * Sends `body` as a JSON-encoded payload with the appropriate
     * Content-Type header.  Same error-handling pattern as get():
     * throws on network failure or non-OK HTTP status.
     */
    async post(path, body = {}) {
        console.log('[API] POST', path, body);
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
    /* ── Export methods ───────────────────────────────────────────
     * These trigger browser-native file downloads by opening the
     * streaming CSV endpoint in a new tab via window.open().
     * They do NOT use get()/post() because the response is a file
     * download, not JSON to be parsed in-page.
     */
    exportSubmissions(platform) {
        const urls = { ib: '/api/export/submissions', fa: '/api/fa/export/submissions', ws: '/api/ws/export/submissions', sf: '/api/sf/export/submissions' };
        window.open(urls[platform] || urls.ib, '_blank');
    },
    exportSnapshots(platform, id) {
        const bases = { ib: '/api/export/snapshots', fa: '/api/fa/export/snapshots', ws: '/api/ws/export/snapshots', sf: '/api/sf/export/snapshots' };
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
};
