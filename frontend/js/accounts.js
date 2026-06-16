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
            <div class="page-header">
                <h1>Accounts</h1>
                <p class="muted">Run more than one account per platform. Each platform's
                default account keeps your existing credentials; add extra accounts below.</p>
            </div>
            <div id="fa-polling-card" class="card" style="margin-bottom:1rem;"></div>
            <div id="accounts-add" class="card" style="margin-bottom:1rem;"></div>
            <div id="accounts-list">Loading…</div>`;

        this._renderFaPollingToggle(document.getElementById('fa-polling-card'));

        let data;
        try {
            data = await API.getAccounts();
        } catch (err) {
            document.getElementById('accounts-list').innerHTML =
                `<div class="card error">Failed to load accounts: ${this.esc(err.message)}</div>`;
            return;
        }
        this._meta = data;
        this._renderAddForm(document.getElementById('accounts-add'), data);
        this._renderList(document.getElementById('accounts-list'), data);
    },

    async _renderFaPollingToggle(el) {
        if (!el || !window.API) return;
        let checked = false;
        try {
            const prefs = await API.getPreferences();
            checked = !!prefs.fa_direct_polling;
        } catch (e) { /* default off */ }
        el.innerHTML = `
            <h3>FurAffinity polling</h3>
            <label><input type="checkbox" id="fa-direct-toggle" ${checked ? 'checked' : ''}>
                Poll FurAffinity directly (bypass FAExport)</label>
            <p class="muted" style="margin:.35rem 0 0;">FAExport (the proxy PawPoller normally
            uses for FA stats) is blocked by Cloudflare. Enable this to scrape FA directly with
            your cookies instead. <strong>Only works from the desktop app</strong> — FA blocks the
            datacenter server's IP.</p>`;
        const cb = el.querySelector('#fa-direct-toggle');
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
            <div class="form-row" style="display:flex;gap:.5rem;flex-wrap:wrap;align-items:flex-end;">
                <label>Platform<br><select id="acct-platform">${options}</select></label>
                <label>Label<br><input id="acct-label" type="text" placeholder="e.g. Alt account"></label>
            </div>
            <div id="acct-cred-fields" style="margin:.5rem 0;display:flex;gap:.5rem;flex-wrap:wrap;"></div>
            <button id="acct-create-btn" class="btn btn-primary">Create account</button>
            <span id="acct-create-msg" class="muted"></span>`;

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
            `<label>${this.esc(f.field)}<br>
                <input class="acct-cred" data-field="${this.esc(f.field)}"
                       type="${f.secret ? 'password' : 'text'}" autocomplete="off"></label>`
        ).join('') || '<span class="muted">No credential fields for this platform.</span>';
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
            el.innerHTML = '<div class="card muted">No accounts configured yet.</div>';
            return;
        }
        // Group by platform.
        const byPlatform = {};
        accounts.forEach(a => { (byPlatform[a.platform] ||= []).push(a); });

        el.innerHTML = Object.keys(byPlatform).map(platform => {
            const rows = byPlatform[platform].map(a => this._accountRow(a)).join('');
            return `<div class="card" style="margin-bottom:1rem;">
                        <h3>${this.esc(names[platform] || platform)}</h3>
                        <table class="data-table"><tbody>${rows}</tbody></table>
                    </div>`;
        }).join('');

        el.querySelectorAll('[data-toggle]').forEach(btn =>
            btn.addEventListener('click', () => this._toggle(btn.dataset.toggle, btn.dataset.enabled === '1')));
        el.querySelectorAll('[data-delete]').forEach(btn =>
            btn.addEventListener('click', () => this._delete(btn.dataset.delete)));
    },

    _fmt(n) {
        n = Number(n) || 0;
        if (n >= 1000000) return (n / 1000000).toFixed(1) + 'M';
        if (n >= 1000) return (n / 1000).toFixed(1) + 'k';
        return String(n);
    },

    _statsCell(s) {
        if (!s) return '<span class="muted">—</span>';
        return `${this._fmt(s.submissions)} subs · ${this._fmt(s.views)} views · `
             + `${this._fmt(s.favorites)} faves · ${this._fmt(s.comments)} comments`;
    },

    _accountRow(a) {
        const badge = a.is_default
            ? '<span class="badge" title="Owns the legacy credentials and history">default</span>' : '';
        const status = a.enabled
            ? '<span class="badge badge-ok">enabled</span>'
            : '<span class="badge badge-off">disabled</span>';
        const toggle = `<button class="btn btn-sm" data-toggle="${a.account_id}" data-enabled="${a.enabled ? 1 : 0}">
                            ${a.enabled ? 'Disable' : 'Enable'}</button>`;
        const del = a.is_default ? ''
            : `<button class="btn btn-sm btn-danger" data-delete="${a.account_id}">Delete</button>`;
        return `<tr>
            <td><strong>${this.esc(a.label || '(unnamed)')}</strong> ${badge}</td>
            <td>${this.esc(a.handle || '')}</td>
            <td class="muted">${this._statsCell(a.stats)}</td>
            <td>${status}</td>
            <td style="text-align:right;white-space:nowrap;">${toggle} ${del}</td>
        </tr>`;
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
