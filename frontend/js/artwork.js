/* ── Artwork hub (PostyBirb-style image posting) ─────────────────
 *
 * A standalone image uploader parallel to the Stories hub: drop in an image,
 * fill per-platform metadata, publish to multiple art sites at once. Posted art
 * is tracked in the same analytics as stories (pollers auto-discover it).
 * Renders into #app, dispatched from the SPA router on #/artwork.
 *
 * Works on both runtimes: the browser file input + FormData upload works
 * everywhere; on the desktop app a native file-dialog bridge
 * (window.pywebview.api.open_image_dialog) lets you pick a local file by path.
 */
window.Artwork = {

    /* Image-capable platforms the hub posts to (v1), in display order. */
    _PLATFORMS: ['ib', 'fa', 'sf', 'bsky', 'ik', 'ws', 'da'],

    _pendingFile: null,    // browser File awaiting upload
    _pendingPath: null,    // desktop local path awaiting copy
    _previewUrl: null,     // object URL for the live preview (revoked on re-pick)

    _selectMode: false,    // gallery "Select to unify" mode active
    _selected: new Set(),  // keys ("platform:submission_id") of ticked discovered tiles

    esc(s) {
        return String(s == null ? '' : s).replace(/[&<>"']/g, c => (
            { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
        ));
    },

    _plat(code) {
        return (window.PLATFORMS || []).find(p => p.code === code)
            || { code, label: code, emoji: '', color: '#888' };
    },

    _isDesktop() {
        return !!(window.pywebview && window.pywebview.api
            && window.pywebview.api.open_image_dialog);
    },

    _imgUrl(name, file) {
        return `/api/artwork/image?name=${encodeURIComponent(name)}&file=${encodeURIComponent(file)}`;
    },

    _toast(kind, msg) {
        if (window.toast && window.toast[kind]) window.toast[kind](msg);
    },

    /* ── Hub: grid of artworks (library + discovered) ───────────
     *
     * Two sources merged into one grid, "like Stories":
     *   • Library    — art you uploaded/imported into PawPoller. Clickable to the
     *                  per-work detail, badged with the platforms it's posted to.
     *   • Discovered — art the pollers found on your art accounts that isn't in
     *                  your library yet. Badged with its source platform + views,
     *                  with View ↗ + Import actions. Filtered to visual work via
     *                  the backend `kind` tag + the art-capable platform set.
     */
    async render() {
        this._selectMode = false;
        this._selected.clear();

        const app = document.getElementById('app');
        app.innerHTML = `
            <div class="page-header" style="display:flex;justify-content:space-between;align-items:flex-start;gap:1rem;flex-wrap:wrap;">
                <div>
                    <h1>Artwork</h1>
                    <p class="muted">Everything you've got — art you've uploaded here plus pieces the
                    pollers found on your accounts — in one place. Upload new work to publish it to
                    multiple art sites at once.</p>
                </div>
                <div style="display:flex;gap:.5rem;flex-shrink:0;">
                    <button class="btn" id="art-select-toggle">Select</button>
                    <a class="btn" href="#/artwork/log">History</a>
                    <a class="btn btn-primary" href="#/artwork/new">+ New artwork</a>
                </div>
            </div>
            <div id="art-select-bar" class="artwork-select-bar" hidden>
                <span id="art-select-count">0 selected</span>
                <button class="btn btn-primary btn-sm" id="art-unify-btn" disabled>Unify selected</button>
                <button class="btn btn-sm" id="art-select-cancel">Cancel</button>
                <span class="muted artwork-select-hint">Tick 2 or more posts of the same piece, then Unify
                to merge them into one master with pooled stats.</span>
            </div>
            <div id="artwork-grid"><div class="loading-spinner">Loading…</div></div>`;

        const grid = document.getElementById('artwork-grid');

        // Library is essential; discovered is additive — never block the grid on it.
        let library = [];
        try {
            const data = await API.getArtworks();
            library = (data && data.artworks) || [];
        } catch (err) {
            grid.innerHTML = `<div class="card error">Failed to load artworks: ${this.esc(err.message)}</div>`;
            return;
        }
        let discovered = [];
        try {
            const dd = await API.getDiscovered();
            discovered = ((dd && dd.discovered) || []).filter(d => this._isArt(d));
        } catch (e) { /* show the library regardless of discovered errors */ }

        // Cross-platform links fold same-piece discovered tiles into one master.
        // A master IS a generic submission_link whose members happen to be art
        // tiles — additive and best-effort, so plain tiles show if links fail.
        let links = [];
        try {
            const ld = await API.getLinks();
            links = (ld && ld.links) || [];
        } catch (e) { /* masters are additive; fall back to ungrouped tiles */ }

        const { masters, standalone } = this._foldMasters(discovered, links);

        if (!library.length && !masters.length && !standalone.length) {
            grid.className = '';
            grid.innerHTML = `
                <div class="empty-state">
                    <h3>No artwork yet</h3>
                    <p class="muted">Upload your first image, or once the pollers have run they'll
                    surface art from your connected accounts here.</p>
                    <a class="btn btn-primary" href="#/artwork/new">+ New artwork</a>
                </div>`;
            return;
        }

        // Merge into one grid, newest first. Library cards link to their detail;
        // master cards pool a linked set; discovered cards carry View ↗ + Import.
        const merged = [
            ...library.map(a => ({ _src: 'lib', _date: a.created_at || '', a })),
            ...masters.map(m => ({ _src: 'master', _date: m._date || '', m })),
            ...standalone.map(d => ({ _src: 'disc', _date: d.posted_at || '', d })),
        ].sort((x, y) => (y._date || '').localeCompare(x._date || ''));

        grid.className = 'artwork-grid';
        grid.innerHTML = merged.map(m =>
            m._src === 'lib' ? this._card(m.a)
                : m._src === 'master' ? this._masterCard(m.m)
                    : this._discoveredCard(m.d)).join('');

        grid.addEventListener('click', e => {
            // Master controls stay live in and out of select mode.
            const split = e.target.closest('.art-master-split');
            if (split) { e.preventDefault(); this._splitMaster(split.dataset.linkId); return; }
            const tog = e.target.closest('.art-master-toggle');
            if (tog) { e.preventDefault(); this._toggleMaster(tog); return; }
            // While selecting, a tap on a selectable tile toggles its tick and
            // swallows the tile's own navigation / import.
            if (this._selectMode) {
                const card = e.target.closest('.artwork-card--selectable');
                if (card) { e.preventDefault(); this._toggleSelect(card); }
                return;
            }
            const imp = e.target.closest('.art-import-btn');
            if (imp) { e.preventDefault(); this._importDiscovered(imp); }
        });

        document.getElementById('art-select-toggle')
            .addEventListener('click', () => this._enterSelect());
        document.getElementById('art-select-cancel')
            .addEventListener('click', () => this._exitSelect());
        document.getElementById('art-unify-btn')
            .addEventListener('click', () => this._unifySelected());
    },

    /* ── Masters (unify) ────────────────────────────────────────
     *
     * A "master" coalesces the same artwork posted to several sites — each with
     * its own per-site submission id — into one tile with pooled stats. It reuses
     * the generic cross-platform link tables (submission_links /
     * submission_link_members): an artwork master is simply a link whose members
     * are art tiles. See prototype/docs/ARTWORK_UNIFY.md.
     */

    _key(platform, sid) { return String(platform) + ':' + String(sid); },
    _unkey(k) {
        const i = k.indexOf(':');
        return { platform: k.slice(0, i), submission_id: k.slice(i + 1) };
    },

    /* Group discovered art tiles that share a submission_link into masters,
       returning the masters plus the still-standalone tiles. A link becomes a
       master only when 2+ of its members are art tiles present in this gallery,
       so story links (and links with a single art member here) fall through and
       their members stay as plain tiles. */
    _foldMasters(discovered, links) {
        const byKey = new Map();
        discovered.forEach(d => byKey.set(this._key(d.platform, d.submission_id), d));
        const claimed = new Set();
        const masters = [];
        (links || []).forEach(link => {
            const members = (link.members || [])
                .map(m => byKey.get(this._key(m.platform, m.submission_id)))
                .filter(Boolean);
            if (members.length < 2) return;
            members.forEach(d => claimed.add(this._key(d.platform, d.submission_id)));
            const _date = members.map(d => d.posted_at || '').sort().pop() || '';
            masters.push({ link_id: link.link_id, members, _date });
        });
        const standalone = discovered.filter(
            d => !claimed.has(this._key(d.platform, d.submission_id)));
        return { masters, standalone };
    },

    _masterCover(members) {
        const withThumb = members.find(d => this._thumbSrc(d));
        const src = withThumb ? this._thumbSrc(withThumb) : '';
        return src
            ? `<div class="artwork-card-cover" style="background-image:url('${this.esc(src)}')"></div>`
            : `<div class="artwork-card-cover artwork-card-cover--empty">no image</div>`;
    },

    _masterTitle(members) {
        const m = members.find(d => d.title);
        return (m && m.title) || ('#' + members[0].submission_id);
    },

    _masterCard(m) {
        const members = m.members;
        const cover = this._masterCover(members);
        const totalViews = members.reduce((s, d) => s + (Number(d.views) || 0), 0);
        const emojis = members.map(d => {
            const p = this._plat(d.platform);
            return `<span class="artwork-plat" title="${this.esc(p.label)}">${p.emoji || this.esc(p.label)}</span>`;
        }).join('');
        const rows = members.map(d => {
            const p = this._plat(d.platform);
            const v = (d.views != null)
                ? `<span class="artwork-master-member-stat">${Utils.formatNumber(d.views)} views</span>` : '';
            return `
                <div class="artwork-master-member">
                    <span class="artwork-plat" title="${this.esc(p.label)}">${p.emoji || this.esc(p.label)}</span>
                    <span class="artwork-master-member-title">${this.esc(d.title || ('#' + d.submission_id))}</span>
                    ${v}
                    <a class="btn btn-sm" href="${this.esc(d.url)}" target="_blank" rel="noopener">View ↗</a>
                </div>`;
        }).join('');
        return `
            <div class="artwork-card artwork-card--master" data-link-id="${this.esc(m.link_id)}">
                <button type="button" class="art-master-toggle" data-link-id="${this.esc(m.link_id)}"
                    title="Expand this master">
                    ${cover}
                    <span class="artwork-disc-badge artwork-master-badge">${members.length} sites</span>
                </button>
                <div class="artwork-card-body">
                    <div class="artwork-card-title">${this.esc(this._masterTitle(members))}</div>
                    <div class="artwork-card-meta">
                        <span class="artwork-plats">${emojis}</span>
                        <span class="artwork-disc-stat" style="margin-left:auto;">${Utils.formatNumber(totalViews)} views</span>
                    </div>
                    <div class="artwork-master-panel">
                        ${rows}
                        <div class="artwork-master-panel-actions">
                            <button type="button" class="btn btn-sm btn-danger art-master-split"
                                data-link-id="${this.esc(m.link_id)}">Split</button>
                        </div>
                    </div>
                </div>
            </div>`;
    },

    _toggleMaster(btn) {
        const card = btn.closest('.artwork-card--master');
        if (card) card.classList.toggle('expanded');
    },

    async _splitMaster(linkId) {
        if (!confirm('Split this master? The pieces go back to separate tiles — nothing is deleted from any site.')) return;
        try {
            await API.deleteLink(linkId);
            this._toast('success', 'Split');
            const y = window.scrollY;
            await this.render();
            window.scrollTo(0, y);
        } catch (err) {
            this._toast('error', 'Split failed: ' + (err.message || err));
        }
    },

    /* ── Select-to-unify mode ── */

    _enterSelect() {
        this._selectMode = true;
        this._selected.clear();
        const grid = document.getElementById('artwork-grid');
        if (grid) grid.classList.add('selecting');
        const bar = document.getElementById('art-select-bar');
        if (bar) bar.hidden = false;
        const t = document.getElementById('art-select-toggle');
        if (t) t.hidden = true;
        this._updateSelectBar();
    },

    _exitSelect() {
        this._selectMode = false;
        this._selected.clear();
        const grid = document.getElementById('artwork-grid');
        if (grid) {
            grid.classList.remove('selecting');
            grid.querySelectorAll('.artwork-card.selected').forEach(c => c.classList.remove('selected'));
        }
        const bar = document.getElementById('art-select-bar');
        if (bar) bar.hidden = true;
        const t = document.getElementById('art-select-toggle');
        if (t) t.hidden = false;
    },

    _toggleSelect(card) {
        const key = card.dataset.key;
        if (!key) return;
        if (this._selected.has(key)) { this._selected.delete(key); card.classList.remove('selected'); }
        else { this._selected.add(key); card.classList.add('selected'); }
        this._updateSelectBar();
    },

    _updateSelectBar() {
        const n = this._selected.size;
        const countEl = document.getElementById('art-select-count');
        if (countEl) countEl.textContent = `${n} selected`;
        const unify = document.getElementById('art-unify-btn');
        if (unify) unify.disabled = n < 2;
    },

    async _unifySelected() {
        const keys = [...this._selected];
        if (keys.length < 2) return;
        const members = keys.map(k => this._unkey(k));
        const btn = document.getElementById('art-unify-btn');
        btn.disabled = true; btn.textContent = 'Unifying…';
        try {
            await API.createLink({ members });
            this._toast('success', `Unified ${members.length} pieces into one master`);
            this._exitSelect();
            const y = window.scrollY;
            await this.render();
            window.scrollTo(0, y);
        } catch (err) {
            this._toast('error', 'Unify failed: ' + (err.message || err));
            btn.disabled = false; btn.textContent = 'Unify selected';
        }
    },

    /* Keep only art-capable, visual (non-text), thumbnailed discovered items. */
    _isArt(d) {
        return !!d && this._PLATFORMS.includes(d.platform)
            && d.kind !== 'text' && !!d.thumbnail_url;
    },

    /* FA / Inkbunny / Pixiv thumbnails can't be hotlinked from the browser
       (CORS + mixed-content), so they must go through the backend relay
       endpoints — same as the submissions tables do via Utils.*ThumbUrl.
       Other platforms' thumbnails load directly. Without this the discovered
       cards for those three platforms render as blank tiles. */
    _thumbSrc(d) {
        const url = d && d.thumbnail_url;
        if (!url) return '';
        if (d.platform === 'fa') return Utils.faThumbUrl(url);
        if (d.platform === 'ib') return Utils.thumbUrl(url);
        if (d.platform === 'pix') return Utils.pixThumbUrl(url);
        return url;
    },

    _discoveredCard(d) {
        const plat = this._plat(d.platform);
        const src = this._thumbSrc(d);
        const cover = src
            ? `<div class="artwork-card-cover" style="background-image:url('${this.esc(src)}')"></div>`
            : `<div class="artwork-card-cover artwork-card-cover--empty">no image</div>`;
        const views = (d.views != null)
            ? `<span class="artwork-disc-stat">${Utils.formatNumber(d.views)} views</span>` : '';
        const key = this._key(d.platform, d.submission_id);
        return `
            <div class="artwork-card artwork-card--disc artwork-card--selectable" data-key="${this.esc(key)}">
                <span class="artwork-select-check" aria-hidden="true">✓</span>
                <a href="${this.esc(d.url)}" target="_blank" rel="noopener" class="artwork-card-coverlink">
                    ${cover}
                    <span class="artwork-disc-badge" title="Found on ${this.esc(plat.label)}">${plat.emoji || this.esc(plat.label)}</span>
                </a>
                <div class="artwork-card-body">
                    <div class="artwork-card-title">${this.esc(d.title || ('#' + d.submission_id))}</div>
                    <div class="artwork-card-meta">${views}</div>
                    <div class="artwork-disc-actions">
                        <a class="btn btn-sm" href="${this.esc(d.url)}" target="_blank" rel="noopener">View ↗</a>
                        <button class="btn btn-sm btn-primary art-import-btn"
                            data-platform="${this.esc(d.platform)}" data-sid="${this.esc(d.submission_id)}">Import</button>
                    </div>
                </div>
            </div>`;
    },

    async _importDiscovered(btn) {
        const platform = btn.dataset.platform, sid = btn.dataset.sid;
        btn.disabled = true; btn.textContent = 'Importing…';
        try {
            await API.importArtwork(platform, sid);
            this._toast('success', 'Imported to your library');
            /* Re-render so the piece leaves Discovered and becomes a library
             * card — but preserve scroll. render() rebuilds #app from the top
             * (loading spinner), which otherwise jumps the viewport to the top
             * mid-list while importing down a long Discovered grid. (2.51.7) */
            const scrollY = window.scrollY;
            await this.render();
            window.scrollTo(0, scrollY);
        } catch (err) {
            btn.disabled = false; btn.textContent = 'Import';
            this._toast('error', 'Import failed: ' + (err.message || err));
        }
    },

    _card(a) {
        const cover = a.image
            ? `<div class="artwork-card-cover" style="background-image:url('${this._imgUrl(a.name, a.image)}')"></div>`
            : `<div class="artwork-card-cover artwork-card-cover--empty">no image</div>`;
        const rating = a.rating
            ? `<span class="artwork-badge artwork-badge--${this.esc(a.rating)}">${this.esc(a.rating)}</span>` : '';
        const plats = (a.platforms || []).map(c =>
            `<span class="artwork-plat" title="${this.esc(this._plat(c).label)}">${this._plat(c).emoji || c}</span>`).join('');
        return `
            <a class="artwork-card" href="#/artwork/image/${encodeURIComponent(a.name)}">
                ${cover}
                <div class="artwork-card-body">
                    <div class="artwork-card-title">${this.esc(a.title || a.name)}</div>
                    <div class="artwork-card-meta">${rating}<span class="artwork-plats">${plats}</span></div>
                </div>
            </a>`;
    },

    /* ── Create / upload flow ───────────────────────────────── */

    async renderUpload() {
        this._pendingFile = null;
        this._pendingPath = null;
        if (this._previewUrl) { URL.revokeObjectURL(this._previewUrl); this._previewUrl = null; }

        const app = document.getElementById('app');
        const desktopBtn = this._isDesktop()
            ? `<button type="button" class="btn" id="art-pick-local">Choose local file…</button>` : '';

        app.innerHTML = `
            <div class="page-header">
                <h1>New artwork</h1>
                <p class="muted"><a href="#/artwork">← Back to Artwork</a></p>
            </div>
            <div class="artwork-upload">
                <div class="artwork-upload-col">
                    <div id="art-drop" class="artwork-drop">
                        <div class="artwork-drop-inner" id="art-drop-inner">
                            <div class="artwork-drop-icon">&#128444;</div>
                            <p>Drag an image here, or</p>
                            <label class="btn btn-primary">Choose image
                                <input type="file" id="art-file" accept="image/png,image/jpeg,image/gif,image/webp" hidden>
                            </label>
                            ${desktopBtn}
                            <p class="muted artwork-drop-hint">PNG, JPG, GIF or WebP</p>
                        </div>
                        <img id="art-preview" class="artwork-preview" alt="preview" hidden>
                    </div>
                </div>
                <div class="artwork-upload-col">
                    <div class="card">
                        <label class="field">Title
                            <input type="text" id="art-title" placeholder="Artwork title">
                        </label>
                        <label class="field">Description
                            <textarea id="art-desc" rows="4" placeholder="Caption / description"></textarea>
                        </label>
                        <div class="field-row">
                            <label class="field">Rating
                                <select id="art-rating">
                                    <option value="general">General</option>
                                    <option value="mature">Mature</option>
                                    <option value="adult" selected>Adult</option>
                                </select>
                            </label>
                        </div>
                        <label class="field">Tags <span class="muted">(comma-separated, used as the default for every platform)</span>
                            <textarea id="art-tags" rows="2" placeholder="tag one, tag two, tag three"></textarea>
                        </label>
                    </div>
                    <div class="card">
                        <h3>Publish to</h3>
                        <p class="muted" style="margin:.2rem 0 .6rem;">Tick a platform to publish, pick the account,
                        and optionally override its tags.</p>
                        <div id="art-platforms"></div>
                    </div>
                    <div class="artwork-actions">
                        <button class="btn" id="art-save">Save to library</button>
                        <button class="btn btn-primary" id="art-publish">Save &amp; publish</button>
                        <span id="art-msg" class="muted"></span>
                    </div>
                </div>
            </div>`;

        this._renderPlatformRows(document.getElementById('art-platforms'));
        this._wireUpload();
        await this._populateAccountSelectors();
    },

    _renderPlatformRows(el) {
        el.innerHTML = this._PLATFORMS.map(code => {
            const p = this._plat(code);
            return `
            <div class="artwork-plat-row" data-platform="${code}">
                <label class="artwork-plat-toggle">
                    <input type="checkbox" class="art-plat-check" value="${code}">
                    <span class="artwork-plat-emoji">${p.emoji || ''}</span>
                    <span class="artwork-plat-name">${this.esc(p.label)}</span>
                </label>
                <span class="art-acct-slot" data-platform="${code}"></span>
                <details class="artwork-plat-adv">
                    <summary>Override</summary>
                    <label class="field">Tags for ${this.esc(p.label)}
                        <input type="text" class="art-plat-tags" data-platform="${code}" placeholder="(defaults to the tags above)">
                    </label>
                </details>
            </div>`;
        }).join('');
    },

    async _populateAccountSelectors() {
        for (const code of this._PLATFORMS) {
            const slot = document.querySelector(`.art-acct-slot[data-platform="${code}"]`);
            if (!slot) continue;
            try {
                const data = await API.getAccounts(code);
                const accts = (data.accounts || []).filter(a => a.enabled);
                if (accts.length < 2) continue;   // single account → no picker needed
                const opts = accts.map(a =>
                    `<option value="${a.account_id}"${a.is_default ? ' selected' : ''}>` +
                    `${this.esc(a.label || a.handle || ('account ' + a.account_id))}</option>`).join('');
                slot.innerHTML = `<label class="art-acct">as <select class="art-acct-select" data-platform="${code}">${opts}</select></label>`;
            } catch (e) { /* default account on any failure */ }
        }
    },

    _wireUpload() {
        const fileInput = document.getElementById('art-file');
        const drop = document.getElementById('art-drop');
        fileInput.addEventListener('change', () => {
            if (fileInput.files && fileInput.files[0]) this._setFile(fileInput.files[0]);
        });
        ['dragenter', 'dragover'].forEach(ev => drop.addEventListener(ev, e => {
            e.preventDefault(); drop.classList.add('dragover');
        }));
        ['dragleave', 'drop'].forEach(ev => drop.addEventListener(ev, e => {
            e.preventDefault(); drop.classList.remove('dragover');
        }));
        drop.addEventListener('drop', e => {
            const f = e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0];
            if (f) this._setFile(f);
        });

        const localBtn = document.getElementById('art-pick-local');
        if (localBtn) localBtn.addEventListener('click', () => this._pickDesktopFile());

        document.getElementById('art-save').addEventListener('click', () => this._save(false));
        document.getElementById('art-publish').addEventListener('click', () => this._save(true));

        // Auto-fill the title from the filename if the user hasn't typed one.
        const titleInput = document.getElementById('art-title');
        titleInput.dataset.touched = '';
        titleInput.addEventListener('input', () => { titleInput.dataset.touched = '1'; });
    },

    _setFile(file) {
        if (!/\.(png|jpe?g|gif|webp)$/i.test(file.name)) {
            this._toast('error', 'Please choose a PNG, JPG, GIF or WebP image.');
            return;
        }
        this._pendingFile = file;
        this._pendingPath = null;
        if (this._previewUrl) URL.revokeObjectURL(this._previewUrl);
        this._previewUrl = URL.createObjectURL(file);
        this._showPreview(this._previewUrl, file.name);
    },

    async _pickDesktopFile() {
        try {
            const result = await window.pywebview.api.open_image_dialog();
            const path = Array.isArray(result) ? result[0] : result;
            if (!path) return;
            this._pendingPath = path;
            this._pendingFile = null;
            // Desktop can't object-URL a disk path; show the filename + serve via
            // a transient name? Simplest: show the basename and a generic icon.
            const base = String(path).split(/[\\/]/).pop();
            this._showPreview('', base);
        } catch (e) {
            this._toast('error', 'File dialog failed: ' + (e.message || e));
        }
    },

    _showPreview(url, label) {
        const img = document.getElementById('art-preview');
        const inner = document.getElementById('art-drop-inner');
        const titleInput = document.getElementById('art-title');
        if (titleInput && !titleInput.dataset.touched && !titleInput.value) {
            titleInput.value = (label || '').replace(/\.[^.]+$/, '').replace(/[_-]+/g, ' ');
        }
        if (url) {
            img.src = url; img.hidden = false; inner.style.display = 'none';
        } else {
            img.hidden = true; inner.style.display = '';
            inner.querySelector('.artwork-drop-hint').textContent = 'Selected: ' + (label || 'file');
        }
    },

    _parseTags(s) {
        if (!s) return [];
        const sep = s.indexOf(',') >= 0 ? ',' : /\s/;
        return s.split(sep).map(t => t.trim()).filter(Boolean);
    },

    _collectMetadata() {
        const title = document.getElementById('art-title').value.trim();
        const description = document.getElementById('art-desc').value;
        const rating = document.getElementById('art-rating').value;
        const defaultTags = this._parseTags(document.getElementById('art-tags').value);

        const tags = {};
        if (defaultTags.length) tags.default = defaultTags;

        const checked = Array.from(document.querySelectorAll('.art-plat-check:checked')).map(c => c.value);
        // Per-platform tag overrides
        document.querySelectorAll('.art-plat-tags').forEach(inp => {
            const code = inp.dataset.platform;
            if (!checked.includes(code)) return;
            const over = this._parseTags(inp.value);
            if (over.length) tags[code] = over;
        });

        const accountIds = {};
        document.querySelectorAll('.art-acct-select').forEach(sel => {
            if (checked.includes(sel.dataset.platform)) accountIds[sel.dataset.platform] = parseInt(sel.value, 10);
        });

        return {
            title, description, rating, tags,
            platforms: checked,
            _accountIds: accountIds,
        };
    },

    async _save(publish) {
        const msg = document.getElementById('art-msg');
        const meta = this._collectMetadata();
        if (!this._pendingFile && !this._pendingPath) {
            msg.textContent = 'Choose an image first.'; return;
        }
        if (!meta.title) { msg.textContent = 'Enter a title.'; return; }
        if (publish && !meta.platforms.length) { msg.textContent = 'Tick at least one platform to publish.'; return; }

        const accountIds = meta._accountIds;
        delete meta._accountIds;

        const saveBtn = document.getElementById('art-save');
        const pubBtn = document.getElementById('art-publish');
        saveBtn.disabled = pubBtn.disabled = true;
        msg.textContent = 'Saving…';

        let name;
        try {
            if (this._pendingPath) {
                const r = await API.createArtworkFromPath({ path: this._pendingPath, metadata: meta });
                name = r.name;
            } else {
                const r = await API.uploadArtwork(this._pendingFile, meta, null,
                    pct => { msg.textContent = `Uploading… ${pct}%`; });
                name = r.name;
            }
        } catch (err) {
            msg.textContent = 'Save failed: ' + err.message;
            saveBtn.disabled = pubBtn.disabled = false;
            return;
        }

        if (!publish) {
            this._toast('success', 'Saved to library');
            window.location.hash = `#/artwork/image/${encodeURIComponent(name)}`;
            return;
        }

        msg.textContent = 'Publishing…';
        try {
            const res = await API.publishArtwork({
                artwork_name: name,
                platforms: meta.platforms,
                account_ids: accountIds,
            });
            const ok = res.successes || 0, fail = res.failures || 0;
            this._toast(fail ? 'error' : 'success', `Published: ${ok} ok, ${fail} failed`);
            window.location.hash = `#/artwork/image/${encodeURIComponent(name)}`;
        } catch (err) {
            msg.textContent = 'Saved, but publish failed: ' + err.message;
            saveBtn.disabled = pubBtn.disabled = false;
        }
    },

    /* ── Detail ─────────────────────────────────────────────── */

    async renderDetail(name) {
        const app = document.getElementById('app');
        app.innerHTML = `<div class="loading-spinner">Loading…</div>`;
        let data;
        try {
            data = await API.getArtwork(name);
        } catch (err) {
            app.innerHTML = `<div class="card error">Artwork not found: ${this.esc(name)}</div>`;
            return;
        }
        const cover = data.image
            ? `<img class="artwork-detail-img" src="${this._imgUrl(name, data.image)}" alt="${this.esc(data.title)}">` : '';
        const pubRows = (data.publications || []).map(p => {
            const plat = this._plat(p.platform);
            const st = p.stats || {};
            const link = p.external_url
                ? `<a href="${this.esc(p.external_url)}" target="_blank" rel="noopener">view ↗</a>` : '—';
            const stats = p.stats
                ? `${Utils.formatNumber(st.views || 0)} views · ${Utils.formatNumber(st.favorites_count || 0)} faves · ${Utils.formatNumber(st.comments_count || 0)} comments`
                : '<span class="muted">not yet polled</span>';
            return `<tr>
                <td>${plat.emoji || ''} ${this.esc(plat.label)}</td>
                <td><span class="artwork-status artwork-status--${this.esc(p.status)}">${this.esc(p.status)}</span></td>
                <td>${stats}</td>
                <td>${link}</td>
            </tr>`;
        }).join('');

        app.innerHTML = `
            <div class="page-header" style="display:flex;justify-content:space-between;align-items:flex-start;gap:1rem;flex-wrap:wrap;">
                <div>
                    <h1>${this.esc(data.title || name)}</h1>
                    <p class="muted"><a href="#/artwork">← Back to Artwork</a></p>
                </div>
                <div style="display:flex;gap:.5rem;flex-shrink:0;">
                    <button class="btn btn-danger" id="art-delete">Delete</button>
                </div>
            </div>
            <div class="artwork-detail">
                <div class="artwork-detail-col">${cover}</div>
                <div class="artwork-detail-col">
                    <div class="card">
                        <div class="artwork-detail-meta">
                            ${data.rating ? `<span class="artwork-badge artwork-badge--${this.esc(data.rating)}">${this.esc(data.rating)}</span>` : ''}
                        </div>
                        ${data.description ? `<p>${this.esc(data.description)}</p>` : '<p class="muted">No description.</p>'}
                    </div>
                    <div class="card">
                        <h3>Published</h3>
                        ${pubRows
                            ? `<table class="data-table"><thead><tr><th>Platform</th><th>Status</th><th>Stats</th><th></th></tr></thead><tbody>${pubRows}</tbody></table>`
                            : '<p class="muted">Not published anywhere yet.</p>'}
                    </div>
                    <div class="card">
                        <h3>Publish to more</h3>
                        <div id="art-detail-platforms"></div>
                        <div class="artwork-actions">
                            <button class="btn btn-primary" id="art-detail-publish">Publish</button>
                            <span id="art-detail-msg" class="muted"></span>
                        </div>
                    </div>
                </div>
            </div>`;

        // A compact platform picker for "publish to more", excluding already-posted.
        const posted = new Set((data.publications || [])
            .filter(p => p.status === 'posted').map(p => p.platform));
        this._renderPlatformRows(document.getElementById('art-detail-platforms'));
        // Pre-disable already-posted platforms.
        document.querySelectorAll('#art-detail-platforms .art-plat-row').forEach(row => {
            if (posted.has(row.dataset.platform)) {
                row.style.opacity = '.5';
                const cb = row.querySelector('.art-plat-check');
                if (cb) { cb.disabled = true; cb.title = 'Already posted'; }
            }
        });
        await this._populateAccountSelectors();

        document.getElementById('art-delete').addEventListener('click', () => this._delete(name));
        document.getElementById('art-detail-publish').addEventListener('click', () => this._publishMore(name));
    },

    async _publishMore(name) {
        const msg = document.getElementById('art-detail-msg');
        const checked = Array.from(document.querySelectorAll('#art-detail-platforms .art-plat-check:checked'))
            .map(c => c.value);
        if (!checked.length) { msg.textContent = 'Tick at least one platform.'; return; }
        const accountIds = {};
        document.querySelectorAll('#art-detail-platforms .art-acct-select').forEach(sel => {
            if (checked.includes(sel.dataset.platform)) accountIds[sel.dataset.platform] = parseInt(sel.value, 10);
        });
        msg.textContent = 'Publishing…';
        try {
            const res = await API.publishArtwork({ artwork_name: name, platforms: checked, account_ids: accountIds });
            const ok = res.successes || 0, fail = res.failures || 0;
            this._toast(fail ? 'error' : 'success', `Published: ${ok} ok, ${fail} failed`);
            this.renderDetail(name);
        } catch (err) {
            msg.textContent = 'Publish failed: ' + err.message;
        }
    },

    async _delete(name) {
        if (!confirm('Delete this artwork from your library? Any already-published posts stay live on each platform.')) return;
        try {
            await API.deleteArtwork(name);
            this._toast('success', 'Deleted');
            window.location.hash = '#/artwork';
        } catch (err) {
            this._toast('error', 'Delete failed: ' + err.message);
        }
    },

    /* ── Log ────────────────────────────────────────────────── */

    async renderLog() {
        const app = document.getElementById('app');
        app.innerHTML = `
            <div class="page-header">
                <h1>Artwork history</h1>
                <p class="muted"><a href="#/artwork">← Back to Artwork</a></p>
            </div>
            <div id="art-log"><div class="loading-spinner">Loading…</div></div>`;
        let data;
        try {
            data = await API.getArtworkLog();
        } catch (err) {
            document.getElementById('art-log').innerHTML =
                `<div class="card error">Failed to load: ${this.esc(err.message)}</div>`;
            return;
        }
        const rows = (data.log || []).map(e => `
            <tr>
                <td>${this.esc(e.created_at || '')}</td>
                <td>${this._plat(e.platform).emoji || ''} ${this.esc(this._plat(e.platform).label)}</td>
                <td>${this.esc(e.story_name || '')}</td>
                <td>${this.esc(e.action || '')}</td>
                <td><span class="artwork-status artwork-status--${this.esc(e.status)}">${this.esc(e.status)}</span></td>
                <td class="muted">${this.esc(e.error_message || '')}</td>
            </tr>`).join('');
        document.getElementById('art-log').innerHTML = rows
            ? `<table class="data-table"><thead><tr><th>When</th><th>Platform</th><th>Artwork</th><th>Action</th><th>Status</th><th>Error</th></tr></thead><tbody>${rows}</tbody></table>`
            : '<div class="empty-state"><p class="muted">No artwork posts yet.</p></div>';
    },
};
