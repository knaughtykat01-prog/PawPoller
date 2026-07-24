/* Commissions hub + detail — a lightweight client/commission tracker
 * (gap-wave-5 §4). A board grouped by status, soonest-due first, with an inline
 * status-advance control. Money is data only (no payment integration).
 *
 * CSP-safe: no inline handlers — one delegated click listener keyed on data-*
 * attributes, mirroring Collections. */
window.Commissions = {
    _statuses: ['quote', 'accepted', 'wip', 'paid', 'delivered'],
    _statusLabel: {
        quote: 'Quote', accepted: 'Accepted', wip: 'In progress',
        paid: 'Paid', delivered: 'Delivered',
    },
    _current: null,

    esc(s) {
        return String(s == null ? '' : s).replace(/[&<>"']/g, c => (
            { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
    },
    _toast(kind, msg) { if (window.toast && window.toast[kind]) window.toast[kind](msg); },
    _plat(code) { return (window.platformByCode && window.platformByCode(code)) || { code, label: (code || '').toUpperCase(), emoji: '' }; },

    _money(c) {
        const p = Number(c.price || 0);
        if (!p) return '';
        // Keep it simple: symbol-less, currency code appended (e.g. "45 USD").
        return `${p % 1 === 0 ? p : p.toFixed(2)} ${this.esc(c.currency || 'USD')}`;
    },

    /* Due-date badge: overdue (unless delivered/paid) turns it red. */
    _dueBadge(c) {
        if (!c.due_date) return '';
        const overdue = c.status !== 'delivered' && c.status !== 'paid'
            && c.due_date < new Date().toISOString().slice(0, 10);
        return `<span class="comm-due${overdue ? ' comm-due--over' : ''}" title="Due ${this.esc(c.due_date)}">${overdue ? '⚠ ' : ''}due ${this.esc(c.due_date)}</span>`;
    },

    _platBadges(codes) {
        return (codes || []).map(c => {
            const p = this._plat(c);
            return `<span class="comm-plat" title="${this.esc(p.label)}">${p.emoji || this.esc((c || '').toUpperCase())}</span>`;
        }).join('');
    },

    _nextStatus(status) {
        const i = this._statuses.indexOf(status);
        return (i >= 0 && i < this._statuses.length - 1) ? this._statuses[i + 1] : null;
    },

    // ── Hub board ────────────────────────────────────────────────
    async render() {
        const app = document.getElementById('app');
        app.innerHTML = `
            <div class="page-header" style="display:flex;justify-content:space-between;align-items:flex-start;gap:1rem;flex-wrap:wrap;">
                <div>
                    <h1>Commissions</h1>
                    <p class="muted">Track clients and commissions — price, due date, status, and where each piece was
                    delivered. Money is just noted here; there's no payment processing.</p>
                </div>
                <button class="btn btn-primary" data-comm-new>+ New commission</button>
            </div>
            <div id="comm-board"><div class="loading-spinner">Loading…</div></div>`;
        let items = [];
        try {
            const d = await API.getCommissions();
            items = d.commissions || [];
            if (Array.isArray(d.statuses) && d.statuses.length) this._statuses = d.statuses;
        } catch (err) {
            document.getElementById('comm-board').innerHTML =
                `<div class="card error">Failed to load commissions: ${this.esc(err.message)}</div>`;
            return;
        }
        const board = document.getElementById('comm-board');
        if (!items.length) {
            board.innerHTML = `
                <div class="empty-state">
                    <h3>No commissions yet</h3>
                    <p class="muted">Add a commission to track a client, a price, a due date, and where you delivered it.</p>
                    <button class="btn btn-primary" data-comm-new>+ New commission</button>
                </div>`;
            return;
        }
        // Group by status; keep the canonical column order, only render columns
        // that have cards (active statuses first — an empty "delivered" pile is noise).
        const byStatus = {};
        items.forEach(c => { (byStatus[c.status] || (byStatus[c.status] = [])).push(c); });
        board.className = 'comm-board';
        board.innerHTML = this._statuses
            .filter(s => (byStatus[s] || []).length)
            .map(s => `
                <section class="comm-col">
                    <h2 class="comm-col-head">${this.esc(this._statusLabel[s] || s)}
                        <span class="comm-col-count">${byStatus[s].length}</span></h2>
                    <div class="comm-col-body">${byStatus[s].map(c => this._card(c)).join('')}</div>
                </section>`).join('');
    },

    _card(c) {
        const money = this._money(c);
        const next = this._nextStatus(c.status);
        const advance = next
            ? `<button class="btn btn-sm comm-advance" data-comm-advance="${c.id}" data-next="${next}"
                    title="Advance to ${this.esc(this._statusLabel[next] || next)}">→ ${this.esc(this._statusLabel[next] || next)}</button>`
            : '';
        return `
            <div class="comm-card" data-comm-open="${c.id}" role="button" tabindex="0">
                <div class="comm-card-top">
                    <span class="comm-client">${this.esc(c.client_name || 'Unnamed client')}</span>
                    ${money ? `<span class="comm-price">${money}</span>` : ''}
                </div>
                ${c.description ? `<p class="comm-desc">${this.esc(c.description.slice(0, 140))}${c.description.length > 140 ? '…' : ''}</p>` : ''}
                <div class="comm-meta">
                    ${this._dueBadge(c)}
                    ${this._platBadges(c.deliver_sites)}
                </div>
                <div class="comm-card-actions">${advance}</div>
            </div>`;
    },

    // ── Detail ───────────────────────────────────────────────────
    async renderDetail(id) {
        const app = document.getElementById('app');
        app.innerHTML = `<div class="work-back"><a href="#/commissions">&larr; Commissions</a></div>
            <div id="comm-detail"><div class="loading-spinner">Loading…</div></div>`;
        let c;
        try {
            c = await API.getCommission(id);
        } catch (err) {
            document.getElementById('comm-detail').innerHTML =
                `<div class="card error">Couldn't open this commission: ${this.esc(err.message)}</div>`;
            return;
        }
        this._current = c;
        const money = this._money(c);
        const artLink = c.artwork_name
            ? `<a href="#/artwork/image/${encodeURIComponent(c.artwork_name)}">${this.esc(c.artwork_name)}</a>`
            : '<span class="muted">none linked</span>';
        const sites = (c.deliver_sites || []).length
            ? this._platBadges(c.deliver_sites) : '<span class="muted">none</span>';
        document.getElementById('comm-detail').innerHTML = `
            <article class="comm-detail-card">
                <div class="comm-detail-head">
                    <div>
                        <div class="shelf-eyebrow">${this.esc(this._statusLabel[c.status] || c.status)}</div>
                        <h1 class="comm-detail-title">${this.esc(c.client_name || 'Unnamed client')}</h1>
                    </div>
                    <div class="comm-detail-actions">
                        <button class="btn btn-sm" data-comm-edit>Edit</button>
                        <button class="btn btn-sm btn-danger" data-comm-delete>Delete</button>
                    </div>
                </div>
                <dl class="comm-fields">
                    <div><dt>Price</dt><dd>${money || '<span class="muted">—</span>'}</dd></div>
                    <div><dt>Status</dt><dd>${this._statusControl(c)}</dd></div>
                    <div><dt>Due date</dt><dd>${c.due_date ? this.esc(c.due_date) : '<span class="muted">—</span>'}</dd></div>
                    <div><dt>Delivered to</dt><dd>${sites}</dd></div>
                    <div><dt>Linked artwork</dt><dd>${artLink}</dd></div>
                </dl>
                ${c.description ? `<h3 class="comm-h3">Description</h3><p class="comm-body">${this.esc(c.description)}</p>` : ''}
                ${c.notes ? `<h3 class="comm-h3">Notes</h3><p class="comm-body">${this.esc(c.notes)}</p>` : ''}
            </article>`;
    },

    /* Inline status <select> on the detail page — changes save immediately. */
    _statusControl(c) {
        return `<select class="comm-status-select" data-comm-status="${c.id}">
            ${this._statuses.map(s =>
                `<option value="${s}"${s === c.status ? ' selected' : ''}>${this.esc(this._statusLabel[s] || s)}</option>`).join('')}
        </select>`;
    },

    // ── Wiring ───────────────────────────────────────────────────
    _init() {
        if (this._wired) return;
        this._wired = true;
        document.addEventListener('click', (e) => {
            const nw = e.target.closest('[data-comm-new]');
            if (nw) { e.preventDefault(); this._newModal(); return; }
            const adv = e.target.closest('[data-comm-advance]');
            if (adv) { e.preventDefault(); e.stopPropagation(); this._advance(Number(adv.dataset.commAdvance), adv.dataset.next); return; }
            const ed = e.target.closest('[data-comm-edit]');
            if (ed) { e.preventDefault(); this._editModal(); return; }
            const del = e.target.closest('[data-comm-delete]');
            if (del) { e.preventDefault(); this._delete(); return; }
            const open = e.target.closest('[data-comm-open]');
            if (open) { e.preventDefault(); location.hash = `#/commissions/${open.dataset.commOpen}`; return; }
        });
        document.addEventListener('keydown', (e) => {
            if (e.key !== 'Enter' && e.key !== ' ') return;
            const open = e.target.closest && e.target.closest('[data-comm-open]');
            if (open) { e.preventDefault(); location.hash = `#/commissions/${open.dataset.commOpen}`; }
        });
        document.addEventListener('change', (e) => {
            const sel = e.target.closest('[data-comm-status]');
            if (sel) this._setStatus(Number(sel.dataset.commStatus), sel.value);
        });
    },

    async _advance(id, next) {
        try {
            await API.updateCommission(id, { status: next });
            this._toast('success', `Moved to ${this._statusLabel[next] || next}`);
            this.render();
        } catch (err) { this._toast('error', 'Update failed: ' + (err.message || err)); }
    },

    async _setStatus(id, status) {
        try {
            await API.updateCommission(id, { status });
            this._toast('success', 'Status updated');
            if (this._current && this._current.id === id) this._current.status = status;
        } catch (err) { this._toast('error', 'Update failed: ' + (err.message || err)); }
    },

    async _delete() {
        const c = this._current;
        if (!c || !confirm(`Delete the commission for "${c.client_name}"? This can't be undone.`)) return;
        try {
            await API.deleteCommission(c.id);
            this._toast('success', 'Commission deleted');
            location.hash = '#/commissions';
        } catch (err) { this._toast('error', 'Delete failed: ' + (err.message || err)); }
    },

    _newModal() {
        this._modal('New commission', {
            client_name: '', description: '', price: '', currency: 'USD',
            status: 'quote', due_date: '', artwork_name: '', deliver_sites: [], notes: '',
        }, async (vals) => {
            const r = await API.createCommission(vals);
            this._toast('success', 'Commission created');
            location.hash = `#/commissions/${r.id}`;
        });
    },

    _editModal() {
        const c = this._current || {};
        this._modal('Edit commission', {
            client_name: c.client_name || '', description: c.description || '',
            price: c.price || '', currency: c.currency || 'USD', status: c.status || 'quote',
            due_date: c.due_date || '', artwork_name: c.artwork_name || '',
            deliver_sites: c.deliver_sites || [], notes: c.notes || '',
        }, async (vals) => {
            await API.updateCommission(c.id, vals);
            this._toast('success', 'Saved');
            this.renderDetail(c.id);
        });
    },

    /* All poster codes that can appear as a delivery target. Kept in sync with
     * posting/artwork_reader._ALL_POSTER_IDS. */
    _deliverCodes: ['ib', 'fa', 'ws', 'sf', 'da', 'ik', 'bsky', 'e621', 'ig'],

    /* Self-contained modal (CSP-safe: built + wired in JS, no inline handlers). */
    _modal(title, vals, onSave) {
        const wrap = document.createElement('div');
        wrap.className = 'guide-modal';
        const siteBoxes = this._deliverCodes.map(code => {
            const p = this._plat(code);
            const on = (vals.deliver_sites || []).includes(code);
            return `<label class="comm-site-box"><input type="checkbox" value="${code}"${on ? ' checked' : ''}>
                <span>${p.emoji || ''} ${this.esc(p.label)}</span></label>`;
        }).join('');
        const statusOpts = this._statuses.map(s =>
            `<option value="${s}"${s === vals.status ? ' selected' : ''}>${this.esc(this._statusLabel[s] || s)}</option>`).join('');
        wrap.innerHTML = `
            <div class="guide-modal-card comm-modal-card" role="dialog" aria-modal="true">
                <div class="guide-modal-head">
                    <h3 class="guide-modal-title">${this.esc(title)}</h3>
                    <button class="guide-modal-close" type="button" aria-label="Close">&times;</button></div>
                <div class="guide-modal-body">
                    <label class="comm-field"><span>Client name</span>
                        <input class="comm-input" id="comm-f-client" type="text" value="${this.esc(vals.client_name)}" placeholder="e.g. @someone"></label>
                    <label class="comm-field"><span>Description</span>
                        <textarea class="comm-input" id="comm-f-desc" rows="2" placeholder="What's the piece?">${this.esc(vals.description)}</textarea></label>
                    <div class="comm-field-row">
                        <label class="comm-field comm-field--sm"><span>Price</span>
                            <input class="comm-input" id="comm-f-price" type="number" min="0" step="0.01" value="${this.esc(String(vals.price))}"></label>
                        <label class="comm-field comm-field--sm"><span>Currency</span>
                            <input class="comm-input" id="comm-f-currency" type="text" maxlength="5" value="${this.esc(vals.currency)}"></label>
                        <label class="comm-field comm-field--sm"><span>Status</span>
                            <select class="comm-input" id="comm-f-status">${statusOpts}</select></label>
                    </div>
                    <div class="comm-field-row">
                        <label class="comm-field comm-field--sm"><span>Due date</span>
                            <input class="comm-input" id="comm-f-due" type="date" value="${this.esc(vals.due_date)}"></label>
                        <label class="comm-field"><span>Linked artwork (name, optional)</span>
                            <input class="comm-input" id="comm-f-art" type="text" value="${this.esc(vals.artwork_name)}" placeholder="artwork folder name"></label>
                    </div>
                    <div class="comm-field"><span>Delivered to</span>
                        <div class="comm-sites" id="comm-f-sites">${siteBoxes}</div></div>
                    <label class="comm-field"><span>Notes (optional)</span>
                        <textarea class="comm-input" id="comm-f-notes" rows="2">${this.esc(vals.notes)}</textarea></label>
                    <div class="comm-msg" id="comm-f-msg"></div>
                    <div class="comm-actions">
                        <button class="btn btn-primary" id="comm-f-save">Save</button>
                        <button class="btn" id="comm-f-cancel">Cancel</button>
                    </div>
                </div>
            </div>`;
        document.body.appendChild(wrap);
        const close = () => wrap.remove();
        wrap.addEventListener('click', (e) => { if (e.target === wrap) close(); });
        wrap.querySelector('.guide-modal-close').addEventListener('click', close);
        wrap.querySelector('#comm-f-cancel').addEventListener('click', close);
        wrap.querySelector('#comm-f-save').addEventListener('click', async () => {
            const client = wrap.querySelector('#comm-f-client').value.trim();
            const msg = wrap.querySelector('#comm-f-msg');
            if (!client) { msg.textContent = 'Client name is required.'; return; }
            const sites = [...wrap.querySelectorAll('#comm-f-sites input:checked')].map(i => i.value);
            const payload = {
                client_name: client,
                description: wrap.querySelector('#comm-f-desc').value,
                price: parseFloat(wrap.querySelector('#comm-f-price').value) || 0,
                currency: wrap.querySelector('#comm-f-currency').value.trim() || 'USD',
                status: wrap.querySelector('#comm-f-status').value,
                due_date: wrap.querySelector('#comm-f-due').value,
                artwork_name: wrap.querySelector('#comm-f-art').value.trim(),
                deliver_sites: sites,
                notes: wrap.querySelector('#comm-f-notes').value,
            };
            const btn = wrap.querySelector('#comm-f-save');
            btn.disabled = true; btn.textContent = 'Saving…';
            try { await onSave(payload); close(); }
            catch (err) { msg.textContent = (err.message || err); btn.disabled = false; btn.textContent = 'Save'; }
        });
    },
};
Commissions._init();
