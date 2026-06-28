/* ── Submissions hub (unified works library) ─────────────────────
 *
 * The central place to see every WORK — stories + artwork — grouped per work,
 * with All / Stories / Artwork subtabs, a persona filter, search, and sort.
 * Cards link to the existing per-work detail (story detail / artwork detail).
 * Read-only aggregation served by /api/works. Phase 1 of the Submissions hub
 * spec (docs/specs/submissions-hub.md). Dispatched from the router on
 * #/submissions.
 *
 * Filtering is client-side over a single fetched list for snappy controls; the
 * /api/works endpoint also accepts the same params for direct/API use.
 */
window.Submissions = {
    _works: [],
    _personas: [],
    _type: 'all',     // all | story | artwork
    _persona: 0,      // 0 = all personas
    _search: '',
    _sort: 'recent',  // recent | title | platforms

    esc(s) {
        return String(s == null ? '' : s).replace(/[&<>"']/g, c => (
            { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
        ));
    },

    _plat(code) {
        return (window.PLATFORMS || []).find(p => p.code === code)
            || { code, label: code, emoji: '', color: '#888' };
    },

    _inputStyle:
        'padding:.45rem .65rem;border-radius:8px;border:1px solid var(--card-border-inner);' +
        'background:var(--bg-elev,transparent);color:inherit;font:inherit;',

    _toast(kind, msg) {
        if (window.toast && window.toast[kind]) window.toast[kind](msg);
    },

    async render() {
        const app = document.getElementById('app');
        app.innerHTML = `
            <div class="page-header" style="display:flex;justify-content:space-between;align-items:flex-start;gap:1rem;flex-wrap:wrap;">
                <div>
                    <h1>Submissions</h1>
                    <p class="muted">Everything you've made — stories and artwork — in one place.
                    Filter by type or persona, then open any work for its full per-platform detail.</p>
                </div>
                <a class="btn" href="#/submissions/discovered" style="flex-shrink:0;">Discovered &rarr;</a>
            </div>
            <div id="subs-controls"></div>
            <div id="subs-grid"><div class="loading-spinner">Loading…</div></div>`;

        let data;
        try {
            data = await API.getWorks();
        } catch (err) {
            document.getElementById('subs-grid').innerHTML =
                `<div class="card error">Failed to load submissions: ${this.esc(err.message)}</div>`;
            return;
        }
        this._works = (data && data.works) || [];
        this._personas = (data && data.personas) || [];
        this._renderControls();
        this._paint();
    },

    _renderControls() {
        const seg = (val, label) => `
            <button class="btn ${this._type === val ? 'btn-primary' : ''}" data-type="${val}"
                style="border-radius:0;border:none;">${label}</button>`;
        // Persona filter only shown when there's more than one persona to choose.
        const personaSel = this._personas.length > 1 ? `
            <select id="subs-persona" style="${this._inputStyle}max-width:180px;">
                <option value="0">All personas</option>
                ${this._personas.map(p =>
                    `<option value="${p.id}">${this.esc(p.name)}</option>`).join('')}
            </select>` : '';
        document.getElementById('subs-controls').innerHTML = `
            <div style="display:flex;gap:.75rem;flex-wrap:wrap;align-items:center;margin-bottom:1.25rem;">
                <div style="display:inline-flex;border:1px solid var(--card-border-inner);border-radius:8px;overflow:hidden;">
                    ${seg('all', 'All')}${seg('story', 'Stories')}${seg('artwork', 'Artwork')}
                </div>
                ${personaSel}
                <input id="subs-search" type="search" placeholder="Search…"
                    style="${this._inputStyle}max-width:220px;" value="${this.esc(this._search)}">
                <select id="subs-sort" style="${this._inputStyle}max-width:160px;margin-left:auto;">
                    <option value="recent">Most recent</option>
                    <option value="title">Title A–Z</option>
                    <option value="platforms">Most platforms</option>
                </select>
            </div>`;

        document.querySelectorAll('#subs-controls [data-type]').forEach(b =>
            b.addEventListener('click', () => {
                this._type = b.dataset.type;
                this._renderControls();   // refresh active segment
                this._paint();
            }));
        const ps = document.getElementById('subs-persona');
        if (ps) ps.addEventListener('change', () => {
            this._persona = parseInt(ps.value) || 0; this._paint();
        });
        const se = document.getElementById('subs-search');
        if (se) se.addEventListener('input', () => { this._search = se.value; this._paint(); });
        const so = document.getElementById('subs-sort');
        if (so) { so.value = this._sort; so.addEventListener('change', () => { this._sort = so.value; this._paint(); }); }
    },

    _filtered() {
        let list = this._works.slice();
        if (this._type !== 'all') list = list.filter(w => w.content_type === this._type);
        if (this._persona) list = list.filter(w => (w.persona_ids || []).includes(this._persona));
        if (this._search) {
            const q = this._search.toLowerCase();
            list = list.filter(w =>
                (w.title || '').toLowerCase().includes(q) || (w.name || '').toLowerCase().includes(q));
        }
        if (this._sort === 'title') list.sort((a, b) => (a.title || '').localeCompare(b.title || ''));
        else if (this._sort === 'platforms') list.sort((a, b) => (b.platforms || []).length - (a.platforms || []).length);
        else list.sort((a, b) => (b.created_at || '').localeCompare(a.created_at || ''));
        return list;
    },

    _paint() {
        const grid = document.getElementById('subs-grid');
        if (!grid) return;
        const list = this._filtered();
        if (!list.length) {
            grid.className = '';
            grid.innerHTML = `<div class="empty-state"><h3>Nothing here yet</h3>
                <p class="muted">No works match this filter.</p></div>`;
            return;
        }
        grid.className = 'story-card-grid';
        grid.innerHTML = list.map(w => this._card(w)).join('');
    },

    _card(w) {
        const cover = w.thumb_url
            ? `<div class="story-card-cover" style="background-image:url('${w.thumb_url}')"></div>`
            : `<div class="story-card-cover" style="display:flex;align-items:center;justify-content:center;color:var(--text-muted);">no image</div>`;
        const typeChip = `<span class="chip" style="text-transform:capitalize;">${this.esc(w.content_type)}</span>`;
        const rating = w.rating ? `<span class="chip">${this.esc(w.rating)}</span>` : '';
        const plats = (w.platforms || []).map(c =>
            `<span title="${this.esc(this._plat(c).label)}">${this._plat(c).emoji || c}</span>`).join(' ');
        const persona = (w.persona_names && w.persona_names.length)
            ? `<div class="muted" style="font-size:.78rem;margin-top:.3rem;">${this.esc(w.persona_names.join(', '))}</div>` : '';
        const meta = w.meta ? `<div class="story-card-stats">${this.esc(w.meta)}</div>` : '';
        return `
            <a class="story-card" href="${w.detail_route}">
                ${cover}
                <div class="story-card-body">
                    <div class="story-card-title">${this.esc(w.title || w.name)}</div>
                    <div class="story-card-meta">${typeChip}${rating}</div>
                    ${meta}
                    <div class="story-card-platforms" style="margin-top:.4rem;">${plats}</div>
                    ${persona}
                </div>
            </a>`;
    },

    /* ── Discovered (unlinked) bucket + link-to-work (Phase 2) ──── */

    async renderDiscovered() {
        const app = document.getElementById('app');
        app.innerHTML = `
            <div class="page-header" style="display:flex;justify-content:space-between;align-items:flex-start;gap:1rem;flex-wrap:wrap;">
                <div>
                    <h1>Discovered submissions</h1>
                    <p class="muted">Posts the pollers found on your platforms that aren't linked to a
                    local work yet. Link one to an existing work to fold it into the hub.</p>
                </div>
                <a class="btn" href="#/submissions" style="flex-shrink:0;">&larr; Submissions</a>
            </div>
            <div id="disc-list"><div class="loading-spinner">Loading…</div></div>`;

        let disc, works;
        try {
            [disc, works] = await Promise.all([API.getDiscovered(), API.getWorks()]);
        } catch (err) {
            document.getElementById('disc-list').innerHTML =
                `<div class="card error">Failed to load: ${this.esc(err.message)}</div>`;
            return;
        }
        this._discItems = (disc && disc.discovered) || [];
        this._workOptions = ((works && works.works) || []).map(w => ({
            value: `${w.content_type}:${w.name}`,
            label: `[${w.content_type}] ${w.title}`,
        }));
        this._paintDiscovered();
    },

    _paintDiscovered() {
        const el = document.getElementById('disc-list');
        if (!el) return;
        if (!this._discItems.length) {
            el.innerHTML = `<div class="empty-state"><h3>Nothing unlinked</h3>
                <p class="muted">Every discovered submission is already linked to a work.</p></div>`;
            return;
        }
        el.innerHTML = this._discItems.map((d, i) => this._discRow(d, i)).join('');
        this._discItems.forEach((_d, i) => {
            const btn = document.getElementById(`disc-link-btn-${i}`);
            if (btn) btn.addEventListener('click', () => this._linkOne(i));
        });
    },

    _discRow(d, i) {
        const thumb = d.thumbnail_url
            ? `<img src="${this.esc(d.thumbnail_url)}" alt="" style="width:56px;height:56px;object-fit:cover;border-radius:8px;flex-shrink:0;">`
            : `<div style="width:56px;height:56px;border-radius:8px;background:var(--bg-elev);flex-shrink:0;"></div>`;
        const plat = this._plat(d.platform);
        const opts = this._workOptions.map(o =>
            `<option value="${this.esc(o.value)}">${this.esc(o.label)}</option>`).join('');
        return `
            <div class="card" style="display:flex;gap:1rem;align-items:center;padding:.85rem 1rem;margin-bottom:.6rem;flex-wrap:wrap;">
                ${thumb}
                <div style="flex:1;min-width:160px;">
                    <div style="font-weight:600;">${this.esc(d.title)}</div>
                    <div class="muted" style="font-size:.8rem;">
                        <span title="${this.esc(plat.label)}">${plat.emoji || ''} ${this.esc(plat.label)}</span>${d.type ? ` &middot; ${this.esc(d.type)}` : ''}
                        &middot; <a href="${this.esc(d.url)}" target="_blank" rel="noopener">view &#8599;</a>
                    </div>
                </div>
                <select id="disc-sel-${i}" style="${this._inputStyle}max-width:240px;">
                    <option value="">Link to work…</option>
                    ${opts}
                </select>
                <button class="btn btn-primary" id="disc-link-btn-${i}">Link</button>
            </div>`;
    },

    async _linkOne(i) {
        const sel = document.getElementById(`disc-sel-${i}`);
        if (!sel || !sel.value) { this._toast('error', 'Pick a work to link to first'); return; }
        const d = this._discItems[i];
        const [content_type, ...rest] = sel.value.split(':');
        const name = rest.join(':');
        try {
            await API.linkSubmission({
                platform: d.platform, submission_id: d.submission_id,
                content_type, name, title: d.title, url: d.url,
            });
            this._toast('success', `Linked to ${name}`);
            this._discItems.splice(i, 1);
            this._paintDiscovered();
        } catch (err) {
            this._toast('error', `Link failed: ${err.message}`);
        }
    },
};
