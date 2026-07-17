/* ── Masterpieces — the managed master-record-per-image surface (Phase 2) ──────
 *
 * A Masterpiece is the image analog of a story's MASTER.md: one canonical image
 * + masterpiece.json, and (Phase 1) a membership table linking every site-upload
 * of that image so their stats pool. See docs/specs/masterpieces.md.
 *
 *   - renderGrid(gridEl, filters)  — the managed grid, shown inside Library under
 *                                    the "Masterpieces" segment (bookshelf.js).
 *   - renderDetail(name)           — the #/masterpieces/{name} detail view.
 *
 * Phase 3 adds membership management to the detail view: same-image **suggestions**
 * (native perceptual-hash, no AI) with one-click **attach**, and **detach** on each
 * linked location. Editing the canonical metadata + Sync-all still land in Phase 5.
 * Rendering mirrors collections.js (template strings + a document-level click
 * delegate, CSP-safe — no inline handlers) and reuses Charts.aggregateLine.
 */
window.Masterpieces = {
    _personas: {},          // persona_id -> {name, color}
    _personasLoaded: false,
    _cache: null,           // [] of masterpiece list rows, per Library session
    _current: null,         // name of the Masterpiece the detail view is showing
    _wired: false,          // document click delegate attached once
    // Platforms whose poster can't edit in place (supports_edit=False, mirrors the
    // backend) — Sync skips them; they render "post-only" in the Locations table.
    _POST_ONLY: new Set(['bsky', 'e621', 'ik', 'ig']),

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

        const newBtn = `<a class="btn btn-primary btn-sm" href="#/artwork/new"
            title="Upload a new image, describe it once, and publish it across sites">＋ New Masterpiece</a>`;
        const dupBtn = `<a class="btn btn-sm" href="#/masterpieces/duplicates"
            title="Find Masterpieces of the same image and merge them into one">🔍 Find duplicates</a>`;
        if (!list.length) {
            gridEl.className = '';
            gridEl.innerHTML = `<div class="mp-gridbar">${newBtn}</div>
                <div class="empty-state"><h3>No masterpieces yet</h3>
                <p class="muted">Every artwork folder is a masterpiece. Create one, or promote a gallery image
                (★ Master) to link its copies across sites and pool their stats.</p></div>`;
            return;
        }
        gridEl.className = '';
        gridEl.innerHTML = `<div class="mp-gridbar">${newBtn}${dupBtn}</div>
            <div class="mp-grid">${list.map(m => this._card(m)).join('')}</div>`;
    },

    /* ── Duplicate finder / merge (2.144.0) ─────────────────────
     * The same image can become two separate Masterpieces (imported as two
     * folders). This scans hero images by perceptual hash, groups look-alikes,
     * and lets the user merge each group into one survivor (folding the others'
     * site-links in and deleting the redundant records). */
    async renderDuplicates() {
        const app = document.getElementById('app');
        app.innerHTML = `
            <div class="page-header">
                <h1>Merge duplicate Masterpieces</h1>
                <p class="muted"><a href="#/masterpieces">← Back to Masterpieces</a> · Same image, more than one
                Masterpiece? Pick the one to keep and merge the rest into it — their site-links move over and the
                duplicate record is removed (the image is identical, so nothing is lost).</p>
            </div>
            <div id="mp-dups"><div class="loading-spinner">Scanning your images…</div></div>`;
        this._loadDuplicates();
    },

    async _loadDuplicates() {
        const wrap = document.getElementById('mp-dups');
        if (!wrap) return;
        let groups;
        try {
            const d = await API.getMasterpieceDuplicates();
            groups = (d && d.groups) || [];
        } catch (err) {
            wrap.innerHTML = `<div class="card error">Scan failed: ${this.esc(err.message)}</div>`;
            return;
        }
        if (!groups.length) {
            wrap.innerHTML = `<div class="empty-state"><h3>No duplicates found 🎉</h3>
                <p class="muted">No two Masterpieces share the same image.</p></div>`;
            return;
        }
        wrap.innerHTML = groups.map((g, gi) => this._dupGroup(g, gi)).join('');
        wrap.querySelectorAll('[data-merge]').forEach(btn =>
            btn.addEventListener('click', () => this._mergeGroup(parseInt(btn.dataset.merge, 10), groups)));
        wrap.querySelectorAll('[data-notdup]').forEach(btn =>
            btn.addEventListener('click', () => this._notDuplicate(parseInt(btn.dataset.notdup, 10), groups)));
    },

    /* "Not the same" — remember that this group's images are actually different,
     * so the finder stops flagging them. Persisted server-side (2.145.0). */
    async _notDuplicate(gi, groups) {
        const items = groups[gi];
        const groupEl = document.querySelector(`.mp-dup-group[data-group="${gi}"]`);
        const msg = groupEl ? groupEl.querySelector(`[data-msg="${gi}"]`) : null;
        if (msg) msg.textContent = 'Remembering…';
        try {
            await API.dismissMasterpieceDuplicate(items.map(m => m.name));
            if (groupEl) { groupEl.style.opacity = '.5'; groupEl.querySelectorAll('button').forEach(b => b.disabled = true); }
            if (msg) msg.textContent = 'Won’t flag these again ✓';
            this._toast('success', 'Marked as different — won’t be flagged again');
        } catch (err) {
            if (msg) msg.textContent = 'Failed: ' + err.message;
        }
    },

    _dupGroup(items, gi) {
        // items[0] is the recommended survivor (most views, then most sites).
        const cards = items.map((m, i) => {
            const cover = m.cover_thumb
                ? `<img class="mp-dup-thumb" src="${this.esc(this._thumbSrc(m.cover_platform, m.cover_thumb))}" alt="" loading="lazy">`
                : (this._canonUrl(m.name, m.image)
                    ? `<img class="mp-dup-thumb" src="${this.esc(this._canonUrl(m.name, m.image))}" alt="" loading="lazy">`
                    : `<span class="mp-dup-thumb mp-dup-thumb--none">🖼️</span>`);
            const keepTag = i === 0
                ? `<span class="mp-dup-keep">✓ keeps</span>`
                : `<label class="mp-dup-pick"><input type="radio" name="dup-keep-${gi}" value="${i}"> keep this instead</label>`;
            return `
                <div class="mp-dup-card${i === 0 ? ' is-keep' : ''}" data-idx="${i}">
                    ${cover}
                    <div class="mp-dup-meta">
                        <div class="mp-dup-title">${this.esc(m.title || m.name)}</div>
                        <div class="mp-dup-stats muted">${this._fmt(m.views)} views · ${m.sites} site${m.sites === 1 ? '' : 's'}</div>
                        ${keepTag}
                    </div>
                </div>`;
        }).join('');
        return `
            <div class="mp-dup-group card" data-group="${gi}">
                <div class="mp-dup-row">${cards}</div>
                <div class="mp-dup-actions">
                    <button class="btn btn-primary btn-sm" data-merge="${gi}">Merge ${items.length} into one</button>
                    <button class="btn btn-sm" data-notdup="${gi}"
                        title="These are different images — don't flag them as duplicates again">✗ Not the same</button>
                    <span class="mp-dup-msg muted" data-msg="${gi}"></span>
                </div>
            </div>`;
    },

    async _mergeGroup(gi, groups) {
        const items = groups[gi];
        const groupEl = document.querySelector(`.mp-dup-group[data-group="${gi}"]`);
        const msg = groupEl ? groupEl.querySelector(`[data-msg="${gi}"]`) : null;
        // Survivor = the radio the user picked, else the recommended items[0].
        let keepIdx = 0;
        const picked = groupEl && groupEl.querySelector(`input[name="dup-keep-${gi}"]:checked`);
        if (picked) keepIdx = parseInt(picked.value, 10);
        const keep = items[keepIdx];
        const drops = items.filter((_m, i) => i !== keepIdx);
        if (!window.confirm(`Merge ${drops.length} duplicate${drops.length === 1 ? '' : 's'} into “${keep.title || keep.name}”? `
            + `Their site-links move over and the duplicate records are deleted. This can't be undone.`)) return;
        const btn = groupEl && groupEl.querySelector('[data-merge]');
        if (btn) btn.disabled = true;
        if (msg) msg.textContent = 'Merging…';
        let ok = 0, fail = 0;
        for (const d of drops) {
            try { await API.mergeMasterpieces(keep.name, d.name); ok++; }
            catch (e) { fail++; }
        }
        this._cache = null;   // grid is stale after a merge
        if (msg) msg.textContent = fail ? `Merged ${ok}, ${fail} failed` : 'Merged ✓';
        if (groupEl) { groupEl.style.opacity = '.55'; }
        this._toast(fail ? 'error' : 'success',
            fail ? `Merged ${ok}, ${fail} failed` : `Merged into ${keep.title || keep.name}`);
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
        this._current = name;
        this._init();
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
        const curRating = (m.rating || '').toLowerCase();
        const ratingOpts = ['general', 'mature', 'adult'].map(r =>
            `<option value="${r}"${curRating === r ? ' selected' : ''}>${r[0].toUpperCase() + r.slice(1)}</option>`).join('');
        const charsStr = (m.characters || []).join(', ');
        const tagsStr = tagList.join(', ');

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
            // Platforms whose poster can't edit in place are Sync-exempt (§0-A1).
            const postOnly = this._POST_ONLY.has(l.platform)
                ? `<span class="mp-role mp-role--postonly" title="This site can't be edited in place — re-post to update">post-only</span>` : '';
            const safe = window.Utils && Utils.safeUrl ? Utils.safeUrl(l.url) : l.url;
            const link = safe ? `<a href="${this.esc(safe)}" target="_blank" rel="noopener">open&nbsp;&#8599;</a>` : '';
            const title = l.title ? `<div class="muted" style="font-size:.8rem">${this.esc(l.title)}</div>` : '';
            const detach = `<button class="mp-loc-detach" title="Unlink this upload from the Masterpiece"
                data-mp-detach data-platform="${this.esc(l.platform)}" data-sid="${this.esc(l.submission_id)}">✕</button>`;
            return `
                <tr>
                    <td>${thumb}</td>
                    <td><span class="mp-loc-plat">${p.emoji || ''} ${this.esc(p.label)}</span> ${role}${postOnly}${title}</td>
                    <td>${this._fmt(st.views)}</td>
                    <td>${this._fmt(st.favorites)}</td>
                    <td>${this._fmt(st.comments)}</td>
                    <td>${link}</td>
                    <td>${detach}</td>
                </tr>`;
        }).join('');
        const locTable = locs.length
            ? `<table class="mp-loc-table">
                    <thead><tr><th></th><th>Platform</th><th>Views</th><th>Faves</th><th>Comments</th><th></th><th></th></tr></thead>
                    <tbody>${locRows}</tbody>
               </table>`
            : `<div class="mp-empty">No linked uploads yet — use <strong>Link the same image elsewhere</strong>
               below to attach this image's copies on other sites. (Publishing will also auto-link, Phase 4.)</div>`;

        root.innerHTML = `
            <div class="mp-detail-head">
                <div class="mp-hero">${hero}</div>
                <div class="mp-head-info">
                    <div class="mp-title">${this.esc(m.title || name)}</div>
                    <div style="display:flex;gap:.5rem;align-items:center;flex-wrap:wrap">${rating}
                        ${personas ? `<span class="mp-personas">${personas}</span>` : ''}
                        <button class="btn btn-sm" data-add-collection data-mtype="masterpiece"
                            data-mref="${this.esc(name)}" data-label="${this.esc(m.title || name)}"
                            title="Bundle this piece (with its companion story / announcement posts) into a Collection">＋ Add to Collection</button></div>
                    <div class="mp-headline">
                        <div class="mp-headline-item"><span class="mp-headline-num">${this._fmt(t.views)}</span><span class="mp-headline-label">Views</span></div>
                        <div class="mp-headline-item"><span class="mp-headline-num">${this._fmt(t.favorites)}</span><span class="mp-headline-label">Favorites</span></div>
                        <div class="mp-headline-item"><span class="mp-headline-num">${this._fmt(t.comments)}</span><span class="mp-headline-label">Comments</span></div>
                        <div class="mp-headline-item"><span class="mp-headline-num">${t.locations || 0}</span><span class="mp-headline-label">Sites</span></div>
                    </div>
                </div>
            </div>

            <div class="mp-section">
                <div class="mp-section-title">Canonical record
                    <span class="muted" style="font-weight:400;font-size:.8rem">— edit once, then sync to every editable site</span>
                </div>
                <div class="mp-edit">
                    <label class="mp-field"><span>Title</span>
                        <input class="mp-input" id="mp-e-title" value="${this.esc(m.title || '')}"></label>
                    <label class="mp-field"><span>Description</span>
                        <textarea class="mp-input" id="mp-e-desc" rows="4">${this.esc(m.description || '')}</textarea></label>
                    <div class="mp-field-row">
                        <label class="mp-field"><span>Rating</span>
                            <select class="mp-input" id="mp-e-rating">${ratingOpts}</select></label>
                        <label class="mp-field"><span>Characters <span class="muted">(comma-separated)</span></span>
                            <input class="mp-input" id="mp-e-chars" value="${this.esc(charsStr)}"></label>
                    </div>
                    <label class="mp-field"><span>Tags <span class="muted">(canonical / default)</span>
                            <button class="btn btn-sm" data-mp-tagbrowse type="button">🏷️ Browse</button></span>
                        <input class="mp-input" id="mp-e-tags" value="${this.esc(tagsStr)}"></label>
                    <div class="mp-edit-actions">
                        <button class="btn btn-primary btn-sm" data-mp-save type="button">Save canonical</button>
                        <button class="btn btn-sm" data-mp-sync type="button"
                            title="Push this record to every editable site (metadata only — never re-uploads the image)">↑ Sync to sites</button>
                        <span class="mp-edit-msg muted" id="mp-edit-msg"></span>
                    </div>
                </div>
            </div>

            <div class="mp-section">
                <div class="mp-section-title">Published to</div>
                ${locTable}
            </div>

            <div class="mp-section">
                <div class="mp-section-title">Link the same image elsewhere
                    <button class="btn btn-sm mp-scan-btn" data-mp-scan
                        title="Hash platform thumbnails to find this exact image on other sites (native, no AI)">↻ Scan for matches</button>
                </div>
                <div id="mp-suggest-body"><div class="muted">Looking for the same image on other sites…</div></div>
            </div>

            <div class="mp-section" id="mp-chart-card" style="display:none">
                <div class="mp-section-title">Combined growth <span class="muted" style="font-weight:400">— summed across every site</span></div>
                <div class="mp-chart-wrap"><canvas id="mp-combined-chart"></canvas></div>
            </div>`;

        // Same-image suggestions (native pHash) + combined time-series (≥2 points).
        this._loadSuggestions();
        this._loadChart(name);
    },

    /* ── Membership management (Phase 3) ── */

    _init() {
        if (this._wired) return;
        this._wired = true;
        document.addEventListener('click', (e) => {
            const save = e.target.closest('[data-mp-save]');
            if (save) { e.preventDefault(); this._saveCanonical(); return; }
            const sync = e.target.closest('[data-mp-sync]');
            if (sync) { e.preventDefault(); this._syncAll(sync); return; }
            const tb = e.target.closest('[data-mp-tagbrowse]');
            if (tb) { e.preventDefault(); this._openTagBrowse(); return; }
            const scan = e.target.closest('[data-mp-scan]');
            if (scan) { e.preventDefault(); this._scanForMatches(scan); return; }
            const att = e.target.closest('[data-mp-attach]');
            if (att) { e.preventDefault(); this._attach(att); return; }
            const det = e.target.closest('[data-mp-detach]');
            if (det) { e.preventDefault(); this._detach(det.dataset.platform, det.dataset.sid); return; }
        });
    },

    _toast(kind, msg) {
        if (window.toast && window.toast[kind]) window.toast[kind](msg);
        else if (window.toast && window.toast.info) window.toast.info(msg);
    },

    /* ── Canonical edit + Sync-all (Phase 5) ── */

    _readCanonical() {
        const val = (id) => { const el = document.getElementById(id); return el ? el.value : ''; };
        const list = (s) => s.split(',').map(x => x.trim()).filter(Boolean);
        return {
            title: val('mp-e-title').trim(),
            description: val('mp-e-desc'),
            rating: val('mp-e-rating'),
            characters: list(val('mp-e-chars')),
            tags: list(val('mp-e-tags')),
        };
    },

    _msg(text, isErr) {
        const el = document.getElementById('mp-edit-msg');
        if (el) { el.textContent = text; el.className = 'mp-edit-msg ' + (isErr ? 'mp-err' : 'muted'); }
    },

    async _saveCanonical() {
        if (!this._current) return;
        this._msg('Saving…', false);
        try {
            await API.patchMasterpiece(this._current, this._readCanonical());
            this._toast('success', 'Canonical record saved');
            await this.renderDetail(this._current);   // reflect the new title/rating in the header
        } catch (err) {
            this._msg('Save failed: ' + (err.message || err), true);
        }
    },

    async _syncAll(btn) {
        if (!this._current) return;
        if (!window.confirm('Push this canonical record (title, description, tags, rating) to every editable site? '
            + 'It overwrites those fields on the live uploads. Bluesky / e621 / Itaku are skipped (post-only).')) return;
        btn.disabled = true;
        try {
            await API.patchMasterpiece(this._current, this._readCanonical());   // save first, then push
            this._msg('Syncing…', false);
            const res = await API.syncMasterpiece(this._current);
            const parts = [`synced ${res.synced}`];
            if (res.skipped) parts.push(`${res.skipped} post-only`);
            if (res.failed) parts.push(`${res.failed} failed`);
            const fails = (res.results || []).filter(r => r.error).map(r => `${r.platform}: ${r.error}`);
            this._toast(res.failed ? 'warn' : 'success', 'Sync: ' + parts.join(' · '));
            this._msg('Sync: ' + parts.join(' · ') + (fails.length ? ' — ' + fails.join('; ') : ''), !!res.failed);
        } catch (err) {
            this._msg('Sync failed: ' + (err.message || err), true);
        } finally {
            btn.disabled = false;
        }
    },

    _openTagBrowse() {
        const input = document.getElementById('mp-e-tags');
        if (!input || !window.TagPicker) { this._toast('info', 'Tag browser unavailable'); return; }
        const selected = input.value.split(',').map(x => x.trim()).filter(Boolean);
        TagPicker.open({
            title: 'Canonical tags',
            selected,
            onConfirm: (names) => { input.value = (names || []).join(', '); },
        });
    },

    async _loadSuggestions() {
        const body = document.getElementById('mp-suggest-body');
        if (!body || !this._current) return;
        let sug = [];
        try {
            const d = await API.getMasterpieceSuggestions(this._current);
            sug = (d && d.suggestions) || [];
        } catch { body.innerHTML = `<div class="muted">Couldn't load suggestions.</div>`; return; }
        if (!sug.length) {
            body.innerHTML = `<div class="muted">No matches found yet. If you've uploaded this image elsewhere,
                hit <strong>Scan for matches</strong> above to hash platform thumbnails and look again.</div>`;
            return;
        }
        body.className = '';
        body.innerHTML = `<div class="mp-suggest-grid">${sug.map(s => this._suggestCard(s)).join('')}</div>`;
    },

    _suggestCard(s) {
        const p = this._plat(s.platform);
        const thumbUrl = this._thumbSrc(s.platform, s.thumbnail_url);
        const thumb = thumbUrl
            ? `<img class="mp-suggest-thumb" src="${this.esc(thumbUrl)}" alt="" loading="lazy">`
            : `<div class="mp-suggest-thumb"></div>`;
        const pct = Math.round((s.similarity || 0) * 100);
        return `
            <div class="mp-suggest">
                ${thumb}
                <div class="mp-suggest-body">
                    <div class="mp-suggest-title" title="${this.esc(s.title || '')}">${this.esc(s.title || ('#' + s.submission_id))}</div>
                    <div class="mp-suggest-meta">${p.emoji || ''} ${this.esc(p.label)} · ${pct}% match</div>
                    <button class="btn btn-sm btn-primary" data-mp-attach
                        data-platform="${this.esc(s.platform)}" data-sid="${this.esc(s.submission_id)}"
                        data-account="${s.account_id != null ? this.esc(s.account_id) : ''}">＋ Link</button>
                </div>
            </div>`;
    },

    async _scanForMatches(btn) {
        const orig = btn.textContent;
        btn.disabled = true; btn.textContent = 'Scanning…';
        try {
            if (API.scanImageHashes) await API.scanImageHashes();
            await this._loadSuggestions();
            this._toast('success', 'Scan complete');
        } catch (err) {
            this._toast('error', 'Scan failed: ' + (err.message || err));
        } finally {
            btn.disabled = false; btn.textContent = orig;
        }
    },

    async _attach(btn) {
        if (!this._current) return;
        const platform = btn.dataset.platform, sid = btn.dataset.sid;
        const account = btn.dataset.account;
        btn.disabled = true; btn.textContent = 'Linking…';
        try {
            const body = { platform, submission_id: sid, linked_via: 'phash' };
            if (account) body.account_id = parseInt(account, 10);
            await API.addMasterpieceMember(this._current, body);
            this._toast('success', 'Linked');
            await this.renderDetail(this._current);   // re-pool stats + refresh suggestions
        } catch (err) {
            btn.disabled = false; btn.textContent = '＋ Link';
            this._toast('error', 'Link failed: ' + (err.message || err));
        }
    },

    async _detach(platform, sid) {
        if (!this._current) return;
        try {
            await API.removeMasterpieceMember(this._current, platform, sid);
            this._toast('success', 'Unlinked');
            await this.renderDetail(this._current);
        } catch (err) {
            this._toast('error', 'Unlink failed: ' + (err.message || err));
        }
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
