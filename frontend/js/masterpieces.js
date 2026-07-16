/* ── Masterpieces — the managed master-record-per-image surface (Phase 2) ──────
 *
 * A Masterpiece is the image analog of a story's MASTER.md: one canonical image
 * + masterpiece.json, and (Phase 1) a membership table linking every site-upload
 * of that image so their stats pool. See docs/specs/masterpieces.md.
 *
 * This module is READ-ONLY in Phase 2:
 *   - renderGrid(gridEl, filters)  — the managed grid, shown inside Library under
 *                                    the "Masterpieces" segment (bookshelf.js).
 *   - renderDetail(name)           — the #/masterpieces/{name} detail view.
 *
 * Editing / promote / publish / sync land in Phases 3–5. Rendering mirrors
 * collections.js (template strings + a document-level click delegate, CSP-safe —
 * no inline handlers) and reuses Charts.aggregateLine for the combined chart.
 */
window.Masterpieces = {
    _personas: {},          // persona_id -> {name, color}
    _personasLoaded: false,
    _cache: null,           // [] of masterpiece list rows, per Library session

    /* Drop the list cache so the next grid render refetches (called on each
       Library open by bookshelf.render). */
    resetCache() { this._cache = null; },

    /* ── small shared helpers (same shape as collections.js) ── */
    esc(s) {
        return (window.Utils && Utils.escapeHtml)
            ? Utils.escapeHtml(String(s == null ? '' : s))
            : String(s == null ? '' : s).replace(/[&<>"']/g, c =>
                ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
    },
    _fmt(n) {
        if (n == null) return '—';   // platform doesn't track this metric
        return (window.Utils && Utils.formatNumber) ? Utils.formatNumber(n) : String(n);
    },
    _plat(code) {
        return (window.PLATFORMS || []).find(p => p.code === code)
            || { code, label: code, emoji: '', color: '#888' };
    },
    /* Route platform thumbnails through the backend relays (FA/IB/Pixiv); others
       are hotlinkable. Identical to collections.js._thumbSrc / artwork.js. */
    _thumbSrc(platform, url) {
        if (!url) return '';
        if (platform === 'fa' && Utils.faThumbUrl) return Utils.faThumbUrl(url);
        if (platform === 'ib' && Utils.thumbUrl) return Utils.thumbUrl(url);
        if (platform === 'pix' && Utils.pixThumbUrl) return Utils.pixThumbUrl(url);
        return url;
    },
    /* The canonical local image is served from the artwork archive by name+file. */
    _canonUrl(name, file) {
        if (!file) return '';
        return `/api/artwork/image?name=${encodeURIComponent(name)}&file=${encodeURIComponent(file)}`;
    },

    async _loadPersonas() {
        if (this._personasLoaded) return;
        try {
            const d = await API.getPersonas();
            const arr = Array.isArray(d) ? d : ((d && d.personas) || []);
            arr.forEach(p => { this._personas[p.id] = { name: p.name, color: p.color || 'var(--accent)' }; });
        } catch { /* personas are decorative here — never block the view */ }
        this._personasLoaded = true;
    },
    _personaChips(ids, cls) {
        return (ids || []).map(id => {
            const p = this._personas[id];
            if (!p) return '';
            return `<span class="mp-persona" title="${this.esc(p.name)}"><span class="mp-persona-dot" `
                + `style="background:${this.esc(p.color)}"></span>${this.esc(p.name)}</span>`;
        }).join('');
    },

    /* ── Grid (rendered into Library's #shelf-grid) ── */

    async renderGrid(gridEl, filters) {
        if (!gridEl) return;
        filters = filters || {};
        await this._loadPersonas();
        if (this._cache === null) {
            gridEl.className = '';
            gridEl.innerHTML = `<div class="loading-spinner">Loading your masterpieces…</div>`;
            try {
                const d = await API.getMasterpieces();
                this._cache = (d && d.masterpieces) || [];
            } catch (err) {
                gridEl.className = '';
                gridEl.innerHTML = `<div class="card error">Couldn't load masterpieces: ${this.esc(err.message)}</div>`;
                return;
            }
        }

        let list = this._cache.slice();
        const persona = filters.persona || 0;
        const q = (filters.search || '').toLowerCase();
        const sort = filters.sort || 'recent';
        if (persona) list = list.filter(m => ((m.summary && m.summary.persona_ids) || []).includes(persona));
        if (q) list = list.filter(m => (m.title || '').toLowerCase().includes(q) || (m.name || '').toLowerCase().includes(q));
        if (sort === 'title') list.sort((a, b) => (a.title || '').localeCompare(b.title || ''));
        else if (sort === 'platforms') list.sort((a, b) =>
            (((b.summary && b.summary.platforms) || []).length) - (((a.summary && a.summary.platforms) || []).length));
        else list.sort((a, b) => (b.created_at || '').localeCompare(a.created_at || ''));

        if (!list.length) {
            gridEl.className = '';
            gridEl.innerHTML = `<div class="empty-state"><h3>No masterpieces yet</h3>
                <p class="muted">Every artwork folder is a masterpiece. Promote a gallery image to link its
                copies across sites and pool their stats — coming soon.</p></div>`;
            return;
        }
        gridEl.className = 'mp-grid';
        gridEl.innerHTML = list.map(m => this._card(m)).join('');
    },

    _cover(m, cls) {
        const canon = this._canonUrl(m.name, m.image);
        if (canon) return `<img class="${cls}" src="${this.esc(canon)}" alt="" loading="lazy">`;
        const s = m.summary || {};
        if (s.cover_thumb) return `<img class="${cls}" src="${this.esc(this._thumbSrc(s.cover_platform, s.cover_thumb))}" alt="" loading="lazy">`;
        return `<div class="mp-cover-ph">🖼️</div>`;
    },

    _card(m) {
        const s = m.summary || {};
        const t = s.totals || {};
        const nSites = s.member_count || 0;
        // Live member platforms if we have them, else the master's configured targets.
        const plats = (s.platforms && s.platforms.length ? s.platforms : (m.platforms || []));
        const badges = plats.slice(0, 8).map(c =>
            `<span class="mp-plat" title="${this.esc(this._plat(c).label)}">${this._plat(c).emoji || c}</span>`).join('');
        const personas = this._personaChips(s.persona_ids);
        // Raw slug in the href (folder names are [\w-] slugs); the API layer
        // encodes once when fetching — mirrors Bookshelf's #/library/work/{name}.
        return `
            <a class="mp-card" href="#/masterpieces/${this.esc(m.name)}">
                <div class="mp-cover">${this._cover(m, 'mp-cover-img')}</div>
                <div class="mp-body">
                    <div class="mp-name" title="${this.esc(m.title || m.name)}">${this.esc(m.title || m.name)}</div>
                    <div class="mp-meta">${badges}<span class="muted">· ${nSites} site${nSites === 1 ? '' : 's'}</span></div>
                    <div class="mp-stats">👁 ${this._fmt(t.views)} · ❤ ${this._fmt(t.favorites)} · 💬 ${this._fmt(t.comments)}</div>
                    ${personas ? `<div class="mp-personas-inline">${personas}</div>` : ''}
                </div>
            </a>`;
    },

    /* ── Detail (#/masterpieces/{name}) ── */

    async renderDetail(name) {
        const app = document.getElementById('app');
        app.innerHTML = `
            <div class="work-back"><a href="#/library">&larr; Library</a></div>
            <div id="mp-detail"><div class="loading-spinner">Opening the masterpiece…</div></div>`;
        await this._loadPersonas();
        let m;
        try {
            m = await API.getMasterpiece(name);
        } catch (err) {
            const status = (err && /404/.test(err.message)) ? 'This masterpiece no longer exists.' : this.esc(err.message);
            document.getElementById('mp-detail').innerHTML =
                `<div class="card error">Couldn't open this masterpiece: ${status}</div>`;
            return;
        }
        this._paintDetail(name, m);
    },

    _ratingCls(r) {
        const v = (r || '').toLowerCase();
        if (v === 'adult' || v === 'explicit') return 'mp-rating mp-rating--adult';
        if (v === 'mature') return 'mp-rating mp-rating--mature';
        return 'mp-rating';
    },

    _paintDetail(name, m) {
        const root = document.getElementById('mp-detail');
        if (!root) return;

        const t = m.totals || {};
        const heroUrl = this._canonUrl(name, m.image);
        const hero = heroUrl
            ? `<img class="mp-hero-img" src="${this.esc(heroUrl)}" alt="${this.esc(m.title || name)}">`
            : `<div class="mp-hero-ph">🖼️</div>`;
        const rating = m.rating ? `<span class="${this._ratingCls(m.rating)}">${this.esc(m.rating)}</span>` : '';
        const personas = this._personaChips(m.persona_ids);

        // Canonical tags: prefer the "default" set, else the union across platforms.
        const ct = m.canonical_tags || {};
        let tagList = (ct.default || []).slice();
        if (!tagList.length) {
            const seen = new Set();
            Object.values(ct).forEach(arr => (arr || []).forEach(x => seen.add(x)));
            tagList = [...seen];
        }
        const tagsHtml = tagList.length
            ? tagList.map(x => `<span class="mp-tag">${this.esc(x)}</span>`).join('')
            : '<span class="muted">No tags yet.</span>';
        const charsHtml = (m.characters && m.characters.length)
            ? m.characters.map(c => `<span class="mp-tag">${this.esc(c)}</span>`).join('')
            : '';

        // Locations ("Published to") — one row per linked site-upload.
        const locs = m.locations || [];
        const locRows = locs.map(l => {
            const p = this._plat(l.platform);
            const st = l.stats || {};
            const thumbUrl = this._thumbSrc(l.platform, l.thumbnail_url);
            const thumb = thumbUrl
                ? `<img class="mp-loc-thumb" src="${this.esc(thumbUrl)}" alt="" loading="lazy">`
                : `<span class="mp-loc-thumb mp-loc-thumb--none"></span>`;
            const roleCls = l.role === 'primary' ? 'mp-role mp-role--primary' : 'mp-role';
            const role = l.role ? `<span class="${roleCls}">${this.esc(l.role)}</span>` : '';
            const safe = window.Utils && Utils.safeUrl ? Utils.safeUrl(l.url) : l.url;
            const link = safe ? `<a href="${this.esc(safe)}" target="_blank" rel="noopener">open&nbsp;&#8599;</a>` : '';
            const title = l.title ? `<div class="muted" style="font-size:.8rem">${this.esc(l.title)}</div>` : '';
            return `
                <tr>
                    <td>${thumb}</td>
                    <td><span class="mp-loc-plat">${p.emoji || ''} ${this.esc(p.label)}</span> ${role}${title}</td>
                    <td>${this._fmt(st.views)}</td>
                    <td>${this._fmt(st.favorites)}</td>
                    <td>${this._fmt(st.comments)}</td>
                    <td>${link}</td>
                </tr>`;
        }).join('');
        const locTable = locs.length
            ? `<table class="mp-loc-table">
                    <thead><tr><th></th><th>Platform</th><th>Views</th><th>Faves</th><th>Comments</th><th></th></tr></thead>
                    <tbody>${locRows}</tbody>
               </table>`
            : `<div class="mp-empty">No linked uploads yet. Linking this image's copies across sites (and
               auto-linking on publish) arrives in the promote &amp; publish flows — Phases 3–4.</div>`;

        root.innerHTML = `
            <div class="mp-detail-head">
                <div class="mp-hero">${hero}</div>
                <div class="mp-head-info">
                    <div class="mp-title">${this.esc(m.title || name)}</div>
                    <div style="display:flex;gap:.5rem;align-items:center;flex-wrap:wrap">${rating}
                        ${personas ? `<span class="mp-personas">${personas}</span>` : ''}</div>
                    <div class="mp-headline">
                        <div class="mp-headline-item"><span class="mp-headline-num">${this._fmt(t.views)}</span><span class="mp-headline-label">Views</span></div>
                        <div class="mp-headline-item"><span class="mp-headline-num">${this._fmt(t.favorites)}</span><span class="mp-headline-label">Favorites</span></div>
                        <div class="mp-headline-item"><span class="mp-headline-num">${this._fmt(t.comments)}</span><span class="mp-headline-label">Comments</span></div>
                        <div class="mp-headline-item"><span class="mp-headline-num">${t.locations || 0}</span><span class="mp-headline-label">Sites</span></div>
                    </div>
                </div>
            </div>

            <div class="mp-section">
                <div class="mp-section-title">Canonical record</div>
                ${m.description ? `<p class="mp-desc">${this.esc(m.description)}</p>` : '<p class="muted">No description yet.</p>'}
                ${charsHtml ? `<div style="margin-top:.7rem"><div class="mp-section-title" style="font-size:.82rem">Characters</div><div class="mp-tags">${charsHtml}</div></div>` : ''}
                <div style="margin-top:.7rem"><div class="mp-section-title" style="font-size:.82rem">Tags</div><div class="mp-tags">${tagsHtml}</div></div>
                <p class="muted" style="margin-top:.7rem;font-size:.82rem">Editing the canonical record &amp; syncing it to every site arrives in Phase 5.</p>
            </div>

            <div class="mp-section">
                <div class="mp-section-title">Published to</div>
                ${locTable}
            </div>

            <div class="mp-section" id="mp-chart-card" style="display:none">
                <div class="mp-section-title">Combined growth <span class="muted" style="font-weight:400">— summed across every site</span></div>
                <div class="mp-chart-wrap"><canvas id="mp-combined-chart"></canvas></div>
            </div>`;

        // Combined time-series — only when there are ≥2 points (same as Collections).
        this._loadChart(name);
    },

    async _loadChart(name) {
        try {
            const snap = await API.getMasterpieceSnapshots(name);
            const rows = (snap && snap.snapshots) || [];
            if (rows.length > 1 && window.Charts) {
                const card = document.getElementById('mp-chart-card');
                if (card) card.style.display = '';
                Charts.aggregateLine('mp-combined-chart', rows, ['views', 'favorites_count', 'comments_count']);
            }
        } catch { /* chart is best-effort */ }
    },
};
