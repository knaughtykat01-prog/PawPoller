/* ── Posts hub (microblog / "tweet-like" publishing) ─────────────
 *
 * A compose box + feed for short-form posts, parallel to the Stories and
 * Artwork hubs but for microblog platforms. Write once, pick Bluesky / Mastodon
 * (Threads / Tumblr / X land in a later phase), publish to all at once, and see
 * each post's per-platform result in the feed. Renders into #app, dispatched
 * from the SPA router on #/posts.
 */
window.Posts = {

    /* Platforms this module can post to today (Phase 2). Threads/Tumblr/X follow. */
    _PLATFORMS: ['bsky', 'mast'],

    /* Bluesky caps a post at 300 graphemes; Mastodon's default is 500. Warn at
     * the tighter limit so a cross-post to Bluesky won't silently truncate. */
    _SOFT_LIMIT: 300,

    _pendingFile: null,   // File awaiting upload
    _previewUrl: null,    // object URL for the compose preview

    esc(s) {
        return String(s == null ? '' : s).replace(/[&<>"']/g, c => (
            { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
        ));
    },

    _plat(code) {
        return (window.PLATFORMS || []).find(p => p.code === code)
            || { code, label: code, emoji: '', color: '#888' };
    },

    _toast(kind, msg) {
        if (window.toast && window.toast[kind]) window.toast[kind](msg);
    },

    /* ── Page: compose + feed ───────────────────────────────── */

    async render() {
        const app = document.getElementById('app');
        app.innerHTML = `
            <div class="page-header">
                <h1>Posts</h1>
                <p class="muted">Write a short post once and publish it to your microblog accounts
                at once. Bluesky and Mastodon are live; Threads, Tumblr and X are coming.</p>
            </div>
            <div id="post-compose"></div>
            <h2 class="posts-feed-heading">Recent posts</h2>
            <div id="post-feed"><div class="loading-spinner">Loading…</div></div>`;

        this._renderCompose(document.getElementById('post-compose'));
        await this._loadFeed();
    },

    _renderCompose(el) {
        el.innerHTML = `
            <div class="card post-compose">
                <textarea id="post-body" class="post-body" rows="4"
                    placeholder="What's happening?"></textarea>
                <div id="post-image-preview" class="post-image-preview" hidden>
                    <img id="post-image-img" alt="attachment preview">
                    <button type="button" class="btn btn-sm" id="post-image-remove">Remove image</button>
                </div>
                <div class="post-compose-row">
                    <label class="btn btn-sm">📎 Image
                        <input type="file" id="post-image" accept="image/png,image/jpeg,image/gif,image/webp" hidden>
                    </label>
                    <label class="post-inline">Rating
                        <select id="post-rating">
                            <option value="general" selected>General</option>
                            <option value="mature">Mature</option>
                            <option value="adult">Adult</option>
                        </select>
                    </label>
                    <span id="post-count" class="post-count muted">0/${this._SOFT_LIMIT}</span>
                </div>
                <div class="post-platforms" id="post-platforms"></div>
                <div class="post-compose-actions">
                    <button class="btn btn-primary" id="post-submit">Post</button>
                    <span id="post-msg" class="muted"></span>
                </div>
            </div>`;

        this._renderPlatformRows(document.getElementById('post-platforms'));
        this._wireCompose();
        this._populateAccountSelectors();
    },

    _renderPlatformRows(el) {
        el.innerHTML = this._PLATFORMS.map(code => {
            const p = this._plat(code);
            return `
            <label class="post-plat" data-platform="${code}">
                <input type="checkbox" class="post-plat-check" value="${code}" checked>
                <span class="post-plat-emoji">${p.emoji || ''}</span>
                <span>${this.esc(p.label)}</span>
                <span class="post-acct-slot" data-platform="${code}"></span>
            </label>`;
        }).join('');
    },

    async _populateAccountSelectors() {
        for (const code of this._PLATFORMS) {
            const slot = document.querySelector(`.post-acct-slot[data-platform="${code}"]`);
            if (!slot) continue;
            try {
                const data = await API.getAccounts(code);
                const accts = (data.accounts || []).filter(a => a.enabled);
                if (accts.length < 2) continue;   // single account → no picker
                const opts = accts.map(a =>
                    `<option value="${a.account_id}"${a.is_default ? ' selected' : ''}>` +
                    `${this.esc(a.label || a.handle || ('account ' + a.account_id))}</option>`).join('');
                slot.innerHTML = `<select class="post-acct-select" data-platform="${code}"
                    onclick="event.preventDefault()">${opts}</select>`;
            } catch (e) { /* default account on any failure */ }
        }
    },

    _wireCompose() {
        const body = document.getElementById('post-body');
        const count = document.getElementById('post-count');
        const updateCount = () => {
            const n = [...body.value].length;   // grapheme-ish (code points)
            count.textContent = `${n}/${this._SOFT_LIMIT}`;
            const bskyOn = !!document.querySelector('.post-plat-check[value="bsky"]:checked');
            count.classList.toggle('over', bskyOn && n > this._SOFT_LIMIT);
        };
        body.addEventListener('input', updateCount);
        document.querySelectorAll('.post-plat-check').forEach(c =>
            c.addEventListener('change', updateCount));

        const fileInput = document.getElementById('post-image');
        fileInput.addEventListener('change', () => {
            if (fileInput.files && fileInput.files[0]) this._setFile(fileInput.files[0]);
        });
        document.getElementById('post-image-remove').addEventListener('click', () => this._clearFile());
        document.getElementById('post-submit').addEventListener('click', () => this._submit());
    },

    _setFile(file) {
        if (!/\.(png|jpe?g|gif|webp)$/i.test(file.name)) {
            this._toast('error', 'Please choose a PNG, JPG, GIF or WebP image.');
            return;
        }
        this._pendingFile = file;
        if (this._previewUrl) URL.revokeObjectURL(this._previewUrl);
        this._previewUrl = URL.createObjectURL(file);
        document.getElementById('post-image-img').src = this._previewUrl;
        document.getElementById('post-image-preview').hidden = false;
    },

    _clearFile() {
        this._pendingFile = null;
        if (this._previewUrl) { URL.revokeObjectURL(this._previewUrl); this._previewUrl = null; }
        const fi = document.getElementById('post-image');
        if (fi) fi.value = '';
        document.getElementById('post-image-preview').hidden = true;
    },

    _selectedPlatforms() {
        return Array.from(document.querySelectorAll('.post-plat-check:checked')).map(c => c.value);
    },

    _accountIds(platforms) {
        const ids = {};
        document.querySelectorAll('.post-acct-select').forEach(sel => {
            if (platforms.includes(sel.dataset.platform)) ids[sel.dataset.platform] = parseInt(sel.value, 10);
        });
        return ids;
    },

    async _submit() {
        const msg = document.getElementById('post-msg');
        const body = document.getElementById('post-body').value.trim();
        const rating = document.getElementById('post-rating').value;
        const platforms = this._selectedPlatforms();

        if (!body && !this._pendingFile) { msg.textContent = 'Write something or attach an image.'; return; }
        if (!platforms.length) { msg.textContent = 'Pick at least one platform.'; return; }

        const btn = document.getElementById('post-submit');
        btn.disabled = true;
        msg.textContent = 'Posting…';

        try {
            const fd = new FormData();
            fd.append('body', body);
            fd.append('rating', rating);
            if (this._pendingFile) fd.append('file', this._pendingFile);
            const { post_id } = await API.createPost(fd);

            const res = await API.publishPost(post_id, {
                platforms, account_ids: this._accountIds(platforms),
            });
            const ok = res.successes || 0, fail = res.failures || 0;
            this._toast(fail ? 'error' : 'success', `Posted: ${ok} ok, ${fail} failed`);
            if (fail) {
                const errs = (res.results || []).filter(r => !r.success)
                    .map(r => `${this._plat(r.platform).label}: ${r.error}`).join(' · ');
                msg.textContent = errs;
            } else {
                msg.textContent = '';
            }
            // Reset the composer, keep platform selection.
            document.getElementById('post-body').value = '';
            document.getElementById('post-count').textContent = `0/${this._SOFT_LIMIT}`;
            this._clearFile();
            await this._loadFeed();
        } catch (err) {
            msg.textContent = 'Failed: ' + (err.message || err);
        } finally {
            btn.disabled = false;
        }
    },

    /* ── Feed ───────────────────────────────────────────────── */

    async _loadFeed() {
        const feed = document.getElementById('post-feed');
        if (!feed) return;
        let posts;
        try {
            const data = await API.getPosts();
            posts = (data && data.posts) || [];
        } catch (err) {
            feed.innerHTML = `<div class="card error">Failed to load posts: ${this.esc(err.message)}</div>`;
            return;
        }
        if (!posts.length) {
            feed.innerHTML = `<div class="empty-state"><p class="muted">No posts yet — write your first one above.</p></div>`;
            return;
        }
        feed.innerHTML = posts.map(p => this._postCard(p)).join('');
        feed.querySelectorAll('.post-del').forEach(b =>
            b.addEventListener('click', () => this._delete(b.dataset.id)));
    },

    _postCard(p) {
        const img = p.image_path
            ? `<img class="post-card-img" src="${API.postImageUrl(p.post_id)}" alt="${this.esc(p.image_alt)}">` : '';
        const rating = p.rating && p.rating !== 'general'
            ? `<span class="artwork-badge artwork-badge--${this.esc(p.rating)}">${this.esc(p.rating)}</span>` : '';
        const pubs = (p.publications || []).map(pub => {
            const plat = this._plat(pub.platform);
            if (pub.status === 'posted') {
                const link = pub.external_url
                    ? `<a href="${this.esc(pub.external_url)}" target="_blank" rel="noopener">${plat.emoji || ''} ${this.esc(plat.label)} ↗</a>`
                    : `${plat.emoji || ''} ${this.esc(plat.label)}`;
                return `<span class="post-pub post-pub--ok">${link}</span>`;
            }
            return `<span class="post-pub post-pub--fail" title="${this.esc(pub.error)}">${plat.emoji || ''} ${this.esc(plat.label)} — failed</span>`;
        }).join('');
        return `
            <div class="card post-card">
                <div class="post-card-main">
                    <div class="post-card-body">
                        ${rating}
                        <p class="post-card-text">${this.esc(p.body) || '<span class="muted">(image only)</span>'}</p>
                        <div class="post-card-pubs">${pubs || '<span class="muted">not published</span>'}</div>
                        <div class="post-card-meta muted">${this.esc(p.created_at)}</div>
                    </div>
                    ${img}
                </div>
                <button class="btn btn-sm btn-danger post-del" data-id="${p.post_id}">Delete</button>
            </div>`;
    },

    async _delete(id) {
        if (!confirm('Delete this post from your library? Any already-published posts stay live on each platform.')) return;
        try {
            await API.deletePost(id);
            this._toast('success', 'Deleted');
            await this._loadFeed();
        } catch (err) {
            this._toast('error', 'Delete failed: ' + (err.message || err));
        }
    },
};
