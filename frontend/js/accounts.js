/* ── Accounts page (multi-account registry) ──────────────────────
 *
 * Manages multiple accounts per platform. Each platform's *default* account
 * (badge "default") owns the legacy flat credentials and the pre-multi-account
 * history; additional accounts are added here and store their credentials under
 * namespaced keys server-side. Renders into #app and is dispatched from the SPA
 * router on #/accounts.
 */
window.Accounts = {

    _meta: null,   // { platform_names, platform_fields } from the last fetch

    esc(s) {
        return String(s == null ? '' : s).replace(/[&<>"']/g, c => (
            { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
        ));
    },

    async render() {
        const app = document.getElementById('app');
        app.innerHTML = `
            <div class="page-header"><h2>Accounts</h2></div>
            <p class="acct-intro muted">Run more than one account per platform. Each platform's
            default account keeps your existing credentials; add extra accounts below. Group accounts
            across platforms into a <strong>persona</strong> for scoped views and per-persona digests.</p>
            <div class="acct-page">
                <section id="personas-card" class="acct-section">Loading…</section>
                <section id="accounts-add" class="acct-section"></section>
                <div id="accounts-list">Loading…</div>
                <section id="fa-polling-card" class="acct-section"></section>
                <p class="logo-disclaimer">Platform names and logos are trademarks of their respective
                owners, shown only to identify each service. PawPoller is not affiliated with them.</p>
            </div>`;

        this._renderFaPollingToggle(document.getElementById('fa-polling-card'));

        let data, personas;
        try {
            [data, personas] = await Promise.all([
                API.getAccounts(),
                API.getPersonas().catch(() => ({ personas: [] })),
            ]);
        } catch (err) {
            document.getElementById('accounts-list').innerHTML =
                `<section class="acct-section">Failed to load accounts: ${this.esc(err.message)}</section>`;
            return;
        }
        this._meta = data;
        this._personas = (personas && personas.personas) || [];
        this._renderPersonasCard(document.getElementById('personas-card'));
        this._renderAddForm(document.getElementById('accounts-add'), data);
        this._renderList(document.getElementById('accounts-list'), data);
    },

    _renderPersonasCard(el) {
        if (!el) return;
        const rows = (this._personas || []).map(p => {
            const n = (p.accounts || []).length;
            return `
            <div class="persona-row">
                <span class="persona-dot" style="background:${this.esc(p.color || 'var(--accent)')}"></span>
                <a class="persona-name" href="#/persona/${p.persona_id}" title="Open persona overview">${this.esc(p.name)}</a>
                <span class="persona-meta">${n} account${n === 1 ? '' : 's'}</span>
                <span class="acct-stats">${this._statChips(p.stats && p.stats.combined)}</span>
                <span class="spacer"></span>
                <span class="acct-actions">
                    <a class="btn btn-sm" href="#/persona/${p.persona_id}">Overview</a>
                    <button class="btn btn-sm" data-persona-rename="${p.persona_id}" data-name="${this.esc(p.name)}">Rename</button>
                    <button class="btn btn-sm btn-danger" data-persona-delete="${p.persona_id}">Delete</button>
                </span>
            </div>`;
        }).join('');
        el.innerHTML = `
            <h3>Personas</h3>
            <p class="acct-section-sub">A persona bundles accounts across platforms into one identity.
            Assign accounts to a persona in the list below.</p>
            ${rows ? `<div class="persona-list">${rows}</div>` : '<p class="muted">No personas yet.</p>'}
            <div class="acct-form" style="margin-top:14px;">
                <label class="acct-field"><span>New persona</span>
                    <input class="acct-input" id="persona-name" type="text" placeholder="e.g. KitheTiger"></label>
                <label class="acct-field"><span>Colour</span>
                    <input class="acct-color" id="persona-color" type="color" value="#9b7dff"></label>
                <button id="persona-create-btn" class="btn btn-primary">Create persona</button>
                <span id="persona-msg" class="muted"></span>
            </div>`;
        el.querySelector('#persona-create-btn').addEventListener('click', () => this._createPersona(el));
        el.querySelectorAll('[data-persona-delete]').forEach(btn =>
            btn.addEventListener('click', () => this._deletePersona(btn.dataset.personaDelete)));
        el.querySelectorAll('[data-persona-rename]').forEach(btn =>
            btn.addEventListener('click', () => this._renamePersona(btn.dataset.personaRename, btn.dataset.name)));
    },

    async _createPersona(el) {
        const name = el.querySelector('#persona-name').value.trim();
        const color = el.querySelector('#persona-color').value || '#6c8cff';
        const msg = el.querySelector('#persona-msg');
        if (!name) { msg.textContent = 'Enter a name.'; return; }
        msg.textContent = 'Creating…';
        try {
            await API.createPersona({ name, color });
            this.render();
        } catch (err) { msg.textContent = 'Error: ' + err.message; }
    },

    async _renamePersona(id, current) {
        const name = prompt('Rename persona', current || '');
        if (name == null || !name.trim()) return;
        try {
            await API.updatePersona(id, { name: name.trim() });
            this.render();
        } catch (err) { alert('Failed to rename: ' + err.message); }
    },

    async _deletePersona(id) {
        if (!confirm('Delete this persona? Its accounts will be unassigned (not deleted).')) return;
        try {
            await API.deletePersona(id);
            this.render();
        } catch (err) { alert('Failed to delete persona: ' + err.message); }
    },

    _personaSelect(a) {
        const opts = ['<option value="">Unassigned</option>'].concat(
            (this._personas || []).map(p =>
                `<option value="${p.persona_id}"${a.persona_id === p.persona_id ? ' selected' : ''}>${this.esc(p.name)}</option>`)
        ).join('');
        return `<select class="acct-select sm persona-assign" data-account="${a.account_id}">${opts}</select>`;
    },

    async _assignPersona(accountId, value) {
        try {
            await API.assignAccountPersona(accountId, value === '' ? null : Number(value));
            this.render();
        } catch (err) { alert('Failed to assign persona: ' + err.message); }
    },

    async _renderFaPollingToggle(el) {
        if (!el || !window.API) return;
        // Render synchronously (the toggle state fills in after the fetch) so
        // this is never a blank card while preferences load.
        el.innerHTML = `
            <h3>FurAffinity polling</h3>
            <p class="acct-section-sub">FAExport (the proxy PawPoller normally uses for FA stats) is
            blocked by Cloudflare. Enable this to scrape FA directly with your cookies instead.
            <strong>Only works from the desktop app</strong> — FA blocks the datacenter server's IP.</p>
            <label class="acct-setting-row">
                <span class="toggle-switch"><input type="checkbox" id="fa-direct-toggle"><span class="toggle-slider"></span></span>
                <span>Poll FurAffinity directly (bypass FAExport)</span>
            </label>`;
        const cb = el.querySelector('#fa-direct-toggle');
        try {
            const prefs = await API.getPreferences();
            cb.checked = !!prefs.fa_direct_polling;
        } catch (e) { /* default off */ }
        cb.addEventListener('change', async () => {
            try {
                await API.savePreferences({ fa_direct_polling: cb.checked });
            } catch (err) {
                alert('Failed to save: ' + err.message);
                cb.checked = !cb.checked;
            }
        });
    },

    _renderAddForm(el, data) {
        const names = data.platform_names || {};
        const options = Object.keys(names).map(p =>
            `<option value="${p}">${this.esc(names[p])}</option>`).join('');
        el.innerHTML = `
            <h3>Add account</h3>
            <p class="acct-section-sub">Pick a platform, give the account a label, and enter its
            credentials. The first account on a platform becomes its default.</p>
            <div class="acct-form">
                <label class="acct-field"><span>Platform</span>
                    <select class="acct-select" id="acct-platform">${options}</select></label>
                <label class="acct-field"><span>Label</span>
                    <input class="acct-input" id="acct-label" type="text" placeholder="e.g. Alt account"></label>
            </div>
            <div id="acct-cred-fields" class="acct-form" style="margin-top:12px;"></div>
            <div class="acct-form" style="margin-top:14px;">
                <button id="acct-create-btn" class="btn btn-primary">Create account</button>
                <span id="acct-create-msg" class="muted"></span>
            </div>`;

        const platformSel = el.querySelector('#acct-platform');
        const renderFields = () => this._renderCredFields(
            el.querySelector('#acct-cred-fields'), platformSel.value, data);
        platformSel.addEventListener('change', renderFields);
        renderFields();

        el.querySelector('#acct-create-btn').addEventListener('click', () => this._create(el));
    },

    _renderCredFields(el, platform, data) {
        const fields = (data.platform_fields || {})[platform] || [];
        el.innerHTML = fields.map(f =>
            `<label class="acct-field"><span>${this.esc(this._prettyField(platform, f.field))}</span>
                <input class="acct-input acct-cred" data-field="${this.esc(f.field)}"
                       type="${f.secret ? 'password' : 'text'}" autocomplete="off"></label>`
        ).join('') || '<span class="muted">No credential fields for this platform.</span>';
    },

    /* Turn a canonical field name into a human label: drop the platform prefix
     * and the underscores (e.g. "tw_auth_token" → "auth token"). */
    _prettyField(platform, field) {
        let f = String(field || '');
        if (f.startsWith(platform + '_')) f = f.slice(platform.length + 1);
        return f.replace(/_/g, ' ');
    },

    async _create(el) {
        const platform = el.querySelector('#acct-platform').value;
        const label = el.querySelector('#acct-label').value.trim();
        const credentials = {};
        el.querySelectorAll('.acct-cred').forEach(inp => {
            if (inp.value) credentials[inp.dataset.field] = inp.value;
        });
        const msg = el.querySelector('#acct-create-msg');
        msg.textContent = 'Creating…';
        try {
            await API.createAccount({ platform, label, credentials });
            msg.textContent = '';
            this.render();   // refresh the whole page
        } catch (err) {
            msg.textContent = 'Error: ' + err.message;
        }
    },

    _renderList(el, data) {
        const accounts = data.accounts || [];
        const names = data.platform_names || {};
        if (!accounts.length) {
            el.innerHTML = '<section class="acct-section"><p class="muted">No accounts configured yet.</p></section>';
            return;
        }
        // Group by platform.
        const byPlatform = {};
        accounts.forEach(a => { (byPlatform[a.platform] ||= []).push(a); });

        el.innerHTML = Object.keys(byPlatform).map(platform => {
            const meta = (window.platformByCode && window.platformByCode(platform)) || null;
            const color = meta ? meta.color : 'var(--accent)';
            const emoji = meta ? meta.emoji : '';
            const logo = meta ? meta.logo : '';
            const label = (meta && meta.label) || names[platform] || platform;
            const icon = logo
                ? `<span class="plat-logo"><img src="${logo}" alt="${this.esc(label)} logo" loading="lazy"></span>`
                : (emoji ? `<span class="plat-emoji">${emoji}</span>` : '');
            const list = byPlatform[platform];
            const rows = list.map(a => this._accountRow(a, color)).join('');
            return `<div class="acct-plat-card" style="--pc:${color}">
                        <div class="acct-plat-head">
                            ${icon}
                            <span class="plat-name">${this.esc(label)}</span>
                            <span class="plat-count">${list.length} account${list.length === 1 ? '' : 's'}</span>
                        </div>
                        ${rows}
                    </div>`;
        }).join('');

        // Enabled/disabled is a toggle switch now — listen for change, not click.
        el.querySelectorAll('[data-toggle]').forEach(cb =>
            cb.addEventListener('change', () => this._toggle(cb.dataset.toggle, cb.dataset.enabled === '1')));
        el.querySelectorAll('[data-delete]').forEach(btn =>
            btn.addEventListener('click', () => this._delete(btn.dataset.delete)));
        el.querySelectorAll('[data-rename]').forEach(btn =>
            btn.addEventListener('click', () => this._renameAccount(btn.dataset.rename, btn.dataset.label)));
        el.querySelectorAll('[data-view-acct]').forEach(btn =>
            btn.addEventListener('click', () => this._viewAccount(btn.dataset.viewAcct, btn.dataset.plat)));
        el.querySelectorAll('.persona-assign').forEach(sel =>
            sel.addEventListener('change', () => this._assignPersona(sel.dataset.account, sel.value)));
    },

    _fmt(n) {
        n = Number(n) || 0;
        if (n >= 1000000) return (n / 1000000).toFixed(1) + 'M';
        if (n >= 1000) return (n / 1000).toFixed(1) + 'k';
        return String(n);
    },

    /* Per-platform noun for the submissions count — X has "tweets", not "subs". */
    _unit(platform) {
        return {
            tw: 'tweets', bsky: 'posts', mast: 'posts', tum: 'posts', ik: 'posts', da: 'deviations',
            pix: 'works', ao3: 'works', sqw: 'works', wp: 'stories',
            ib: 'submissions', fa: 'submissions', ws: 'submissions', sf: 'submissions',
        }[platform] || 'subs';
    },

    _statsCell(s, platform) {
        if (!s) return '<span class="muted">—</span>';
        return `${this._fmt(s.submissions)} ${this._unit(platform)} · ${this._fmt(s.views)} views · `
             + `${this._fmt(s.favorites)} faves · ${this._fmt(s.comments)} comments`;
    },

    /* Stat chips for the account/persona rows. With platform + accountId, the
     * count chip becomes a link that opens that platform's submissions list
     * scoped to the account — so you can pull up the actual tweets/posts. */
    _statChips(s, platform, accountId) {
        if (!s) return '<span class="muted">No data yet</span>';
        const unit = this._unit(platform);
        const count = this._fmt(s.submissions);
        const subs = (platform && accountId)
            ? `<button class="acct-stat acct-stat-link" data-view-acct="${accountId}" data-plat="${this.esc(platform)}" title="View ${unit}"><b>${count}</b> ${unit} →</button>`
            : `<span class="acct-stat"><b>${count}</b> ${unit}</span>`;
        return subs
             + `<span class="acct-stat"><b>${this._fmt(s.views)}</b> views</span>`
             + `<span class="acct-stat"><b>${this._fmt(s.favorites)}</b> faves</span>`
             + `<span class="acct-stat"><b>${this._fmt(s.comments)}</b> comments</span>`;
    },

    /* Open a platform's submissions list scoped to one account. */
    _viewAccount(accountId, platform) {
        App._accountFilter = App._accountFilter || {};
        App._accountFilter[platform] = Number(accountId);
        window.location.hash = window.platformRoute
            ? window.platformRoute(platform, 'submissions')
            : '#/' + platform;
    },

    _accountRow(a, color) {
        const badge = a.is_default
            ? '<span class="badge badge-default" title="Owns the legacy credentials and history">default</span>' : '';
        const del = a.is_default ? ''
            : `<button class="btn btn-sm btn-danger" data-delete="${a.account_id}">Delete</button>`;
        const toggle = `<label class="toggle-switch" title="${a.enabled ? 'Enabled — click to disable' : 'Disabled — click to enable'}">
                <input type="checkbox" data-toggle="${a.account_id}" data-enabled="${a.enabled ? 1 : 0}" ${a.enabled ? 'checked' : ''}>
                <span class="toggle-slider"></span></label>`;
        const rename = `<button class="btn btn-sm" data-rename="${a.account_id}" data-label="${this.esc(a.label || '')}">Rename</button>`;
        return `<div class="acct-card${a.enabled ? '' : ' disabled'}" style="--pc:${color || 'var(--accent)'}">
            <div class="acct-id">
                <span class="acct-name">${this.esc(a.label || '(unnamed)')} ${badge}</span>
                ${a.handle ? `<span class="acct-handle">${this.esc(a.handle)}</span>` : ''}
            </div>
            <span class="acct-stats">${this._statChips(a.stats, a.platform, a.account_id)}</span>
            <span class="acct-actions">
                <span class="persona-wrap"><span>Persona</span>${this._personaSelect(a)}</span>
                ${toggle}
                ${rename}
                ${del}
            </span>
        </div>`;
    },

    async _renameAccount(id, current) {
        const label = prompt('Account label', current || '');
        if (label == null) return;          // cancelled
        const trimmed = label.trim();
        if (!trimmed) return;               // don't blank the label
        try {
            await API.updateAccount(id, { label: trimmed });
            this.render();
        } catch (err) {
            alert('Failed to rename account: ' + err.message);
        }
    },

    /* renderPersonaDetail(id) — the per-persona overview page (#/persona/:id):
     * combined scalar totals + a per-platform breakdown + the member accounts,
     * each linking through to that platform's dashboard scoped to the account. */
    async renderPersonaDetail(id) {
        const app = document.getElementById('app');
        app.innerHTML = `
            <div class="page-header"><h1>Persona</h1></div>
            <div id="persona-detail">Loading…</div>`;
        let resp;
        try {
            resp = await API.getPersona(id);
        } catch (err) {
            document.getElementById('persona-detail').innerHTML =
                `<div class="card error">Failed to load persona: ${this.esc(err.message)}</div>`;
            return;
        }
        const p = resp.persona;
        if (!p) {
            document.getElementById('persona-detail').innerHTML =
                '<div class="card muted">Persona not found. <a href="#/accounts">Back to Accounts</a></div>';
            return;
        }
        const names = resp.platform_names || {};
        const combined = (p.stats && p.stats.combined) || {};
        const byPlat = (p.stats && p.stats.by_platform) || {};
        const accts = p.accounts || [];

        const swatch = `<span style="display:inline-block;width:16px;height:16px;border-radius:4px;`
            + `background:${this.esc(p.color || '#6c8cff')};vertical-align:middle;margin-right:.5rem;"></span>`;

        const cards = [
            Components.statCard('Submissions', combined.submissions || 0),
            Components.statCard('Views', combined.views || 0),
            Components.statCard('Favorites', combined.favorites || 0),
            Components.statCard('Comments', combined.comments || 0),
        ].join('');

        const platRows = Object.keys(byPlat).map(plat => {
            const s = byPlat[plat] || {};
            return `<tr>
                <td><strong>${this.esc(names[plat] || plat)}</strong></td>
                <td class="muted">${this._fmt(s.submissions)} subs</td>
                <td class="muted">${this._fmt(s.views)} views</td>
                <td class="muted">${this._fmt(s.favorites)} faves</td>
                <td class="muted">${this._fmt(s.comments)} comments</td>
            </tr>`;
        }).join('');

        const acctRows = accts.map(a => `
            <tr>
                <td><strong>${this.esc(a.label || '(unnamed)')}</strong></td>
                <td class="muted">${this.esc(names[a.platform] || a.platform)}</td>
                <td class="muted">${this.esc(a.handle || '')}</td>
                <td class="muted">${this._statsCell(a.stats, a.platform)}</td>
                <td style="text-align:right;">
                    <button class="btn btn-sm" data-view-acct="${a.account_id}" data-plat="${this.esc(a.platform)}">View →</button>
                </td>
            </tr>`).join('');

        document.getElementById('persona-detail').innerHTML = `
            <p style="margin:.2rem 0 .8rem;"><a href="#/accounts">← Accounts</a></p>
            <div class="card" style="margin-bottom:1rem;">
                <h2 style="margin:.2rem 0;">${swatch}${this.esc(p.name)}</h2>
                <p class="muted">${accts.length} account(s) across ${Object.keys(byPlat).length} platform(s) with data</p>
            </div>
            <div class="stats-grid" style="margin-bottom:1rem;">${cards}</div>
            <div class="card" style="margin-bottom:1rem;">
                <h3>Per-platform breakdown</h3>
                ${platRows ? `<table class="data-table"><tbody>${platRows}</tbody></table>`
                           : '<p class="muted">No platform data polled yet.</p>'}
            </div>
            <div class="card">
                <h3>Accounts in this persona</h3>
                ${acctRows ? `<table class="data-table"><tbody>${acctRows}</tbody></table>`
                           : '<p class="muted">No accounts assigned. Assign some on the <a href="#/accounts">Accounts</a> page.</p>'}
            </div>`;

        // "View →" opens the platform dashboard pre-scoped to that account.
        document.querySelectorAll('[data-view-acct]').forEach(btn =>
            btn.addEventListener('click', () => {
                const aid = Number(btn.dataset.viewAcct);
                const plat = btn.dataset.plat;
                App._accountFilter = App._accountFilter || {};
                App._accountFilter[plat] = aid;
                window.location.hash = (window.platformRoute ? window.platformRoute(plat) : '#/' + plat);
            }));
    },

    async _toggle(accountId, currentlyEnabled) {
        try {
            await API.updateAccount(accountId, { enabled: !currentlyEnabled });
            this.render();
        } catch (err) {
            alert('Failed to update account: ' + err.message);
        }
    },

    async _delete(accountId) {
        if (!confirm('Delete this account? Its credentials will be removed. Polled history is left in place.')) return;
        try {
            await API.deleteAccount(accountId);
            this.render();
        } catch (err) {
            alert('Failed to delete account: ' + err.message);
        }
    },
};
