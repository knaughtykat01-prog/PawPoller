/* ── Bookshelf — the Library (concept-layer Slice A · "Atelier") ──────────────
 *
 * A cover-forward, editorial take on the works library: your stories + artwork
 * as a shelf of covers ("the cover speaks the truth" — publish status reads off
 * each spine), plus a rich per-work detail page (big cover · per-platform
 * "published to" list with live counts · chapter × platform reach).
 *
 * A NEW top-level "Library" destination (#/library), peer to Overview — it does
 * NOT replace the Submissions hub (#/submissions), which stays under Publishing.
 * Path A: reuses the real endpoints, adds no backend —
 *   - list          → API.getWorks()            (GET /api/works)
 *   - story detail  → API.getPostingStory(name) (GET /api/posting/stories/{name})
 * Artwork keeps its existing detail route (#/artwork/image/{name}); only the
 * richer STORY detail is rebuilt here (the one with chapters + per-platform).
 *
 * Template-string rendering + a document-level click delegate for filters, to
 * match the rest of the SPA (no build step, CSP-safe — no inline handlers).
 */
window.Bookshelf = {
    _works: [],
    _personas: [],
    _type: 'all',      // all | story | artwork
    _persona: 0,       // 0 = all
    _search: '',
    _sort: 'recent',   // recent | title | platforms

    esc(s) {
        return (window.Utils && Utils.escapeHtml)
            ? Utils.escapeHtml(String(s == null ? '' : s))
            : String(s == null ? '' : s).replace(/[&<>"']/g, c =>
                ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
    },

    _plat(code) {
        return (window.PLATFORMS || []).find(p => p.code === code)
            || { code, label: code, emoji: '', color: '#888' };
    },

    _num(n) {
        return (window.Utils && Utils.formatNumber) ? Utils.formatNumber(n || 0) : String(n || 0);
    },

    /* Per-platform metric names differ (views/hits/reads, faves/kudos/votes);
       pull the first present. */
    _pick(stats, keys) {
        if (!stats) return 0;
        for (const k of keys) if (stats[k] != null) return Number(stats[k]) || 0;
        return 0;
    },
    _views(s) { return this._pick(s, ['views', 'hits', 'reads']); },
    _faves(s) { return this._pick(s, ['favorites_count', 'kudos', 'votes', 'favorites']); },
    _comments(s) { return this._pick(s, ['comments_count', 'comments']); },

    /* ── Library home ──────────────────────────────────────────── */

    async render() {
        const app = document.getElementById('app');
        app.innerHTML = `
            <div class="shelf-head">
                <div class="shelf-eyebrow">Your works</div>
                <h1 class="shelf-title">Library</h1>
                <p class="shelf-sub">Every story and piece you've made, on the shelf — each cover
                carries its own truth: where it's live, and where it isn't yet.</p>
            </div>
            <div id="shelf-controls"></div>
            <div id="shelf-grid"><div class="loading-spinner">Loading your shelf…</div></div>`;

        let data;
        try {
            data = await API.getWorks();
        } catch (err) {
            document.getElementById('shelf-grid').innerHTML =
                `<div class="card error">Couldn't open the library: ${this.esc(err.message)}</div>`;
            return;
        }
        this._works = (data && data.works) || [];
        this._personas = (data && data.personas) || [];
        this._renderControls();
        this._paint();
    },

    _renderControls() {
        const el = document.getElementById('shelf-controls');
        if (!el) return;
        const seg = (val, label) => `
            <button class="shelf-seg ${this._type === val ? 'is-active' : ''}" data-shelf-type="${val}"
                type="button">${label}</button>`;
        const personaSel = this._personas.length > 1 ? `
            <select id="shelf-persona" class="shelf-input">
                <option value="0">All personas</option>
                ${this._personas.map(p => `<option value="${p.id}"${p.id === this._persona ? ' selected' : ''}>${this.esc(p.name)}</option>`).join('')}
            </select>` : '';
        el.innerHTML = `
            <div class="shelf-controls">
                <div class="shelf-segs">${seg('all', 'All')}${seg('story', 'Stories')}${seg('artwork', 'Artwork')}</div>
                ${personaSel}
                <input id="shelf-search" class="shelf-input" type="search" placeholder="Search the shelf…" value="${this.esc(this._search)}">
                <select id="shelf-sort" class="shelf-input shelf-sort">
                    <option value="recent">Most recent</option>
                    <option value="title">Title A–Z</option>
                    <option value="platforms">Most platforms</option>
                </select>
            </div>`;

        el.querySelectorAll('[data-shelf-type]').forEach(b =>
            b.addEventListener('click', () => { this._type = b.dataset.shelfType; this._renderControls(); this._paint(); }));
        const ps = el.querySelector('#shelf-persona');
        if (ps) ps.addEventListener('change', () => { this._persona = parseInt(ps.value) || 0; this._paint(); });
        const se = el.querySelector('#shelf-search');
        if (se) se.addEventListener('input', () => { this._search = se.value; this._paint(); });
        const so = el.querySelector('#shelf-sort');
        if (so) { so.value = this._sort; so.addEventListener('change', () => { this._sort = so.value; this._paint(); }); }
    },

    _filtered() {
        let list = this._works.slice();
        if (this._type !== 'all') list = list.filter(w => w.content_type === this._type);
        if (this._persona) list = list.filter(w => (w.persona_ids || []).includes(this._persona));
        if (this._search) {
            const q = this._search.toLowerCase();
            list = list.filter(w => (w.title || '').toLowerCase().includes(q) || (w.name || '').toLowerCase().includes(q));
        }
        if (this._sort === 'title') list.sort((a, b) => (a.title || '').localeCompare(b.title || ''));
        else if (this._sort === 'platforms') list.sort((a, b) => (b.platforms || []).length - (a.platforms || []).length);
        else list.sort((a, b) => (b.created_at || '').localeCompare(a.created_at || ''));
        return list;
    },

    _paint() {
        const grid = document.getElementById('shelf-grid');
        if (!grid) return;
        const list = this._filtered();
        if (!list.length) {
            grid.className = '';
            grid.innerHTML = `<div class="empty-state"><h3>An empty shelf</h3>
                <p class="muted">No works match this filter yet.</p></div>`;
            return;
        }
        grid.className = 'shelf-grid';
        grid.innerHTML = list.map(w => this._book(w)).join('');
    },

    /* A single "book" on the shelf. The cover is the hero; a small gilt ribbon
       tells the truth (how many platforms it's live on, or "Draft"). Stories
       open the rich Library detail; artwork keeps its own detail route. */
    _book(w) {
        const isStory = w.content_type === 'story';
        const href = isStory ? `#/library/work/${w.name}` : (w.detail_route || '#/library');
        // Truth-telling: a gilt ribbon only when a work is actually out there —
        // "N live" (platforms it's posted to), or "published" when we know it has
        // publications but no posted-status platforms. Unpublished works stay
        // clean (no cover ribbon), marked only by a quiet "Draft" in the meta.
        const nPlat = (w.platforms || []).length;
        let ribbon = '';
        if (nPlat) ribbon = `<span class="book-ribbon" title="Live on ${nPlat} platform${nPlat === 1 ? '' : 's'}">${nPlat} live</span>`;
        else if (w.publication_count) ribbon = `<span class="book-ribbon" title="Published">published</span>`;
        const draftTag = (!nPlat && !w.publication_count) ? `<span class="book-draft">Draft</span>` : '';
        const initials = this.esc((w.title || w.name || '?').trim().charAt(0).toUpperCase());
        const cover = w.thumb_url
            ? `<div class="book-cover" style="background-image:url('${this.esc(w.thumb_url)}')">${ribbon}</div>`
            : `<div class="book-cover book-cover--blank"><span class="book-initial">${initials}</span>${ribbon}</div>`;
        const rating = w.rating ? `<span class="book-rating">${this.esc(w.rating)}</span>` : '';
        const plats = (w.platforms || []).slice(0, 8).map(c =>
            `<span class="book-plat" title="${this.esc(this._plat(c).label)}">${this._plat(c).emoji || c}</span>`).join('');
        return `
            <a class="book" href="${this.esc(href)}">
                ${cover}
                <div class="book-spine">
                    <div class="book-title">${this.esc(w.title || w.name)}</div>
                    <div class="book-meta">${w.meta ? this.esc(w.meta) : (isStory ? 'Story' : 'Artwork')}${rating ? ' · ' : ''}${rating}${draftTag ? ' ' + draftTag : ''}</div>
                    <div class="book-plats">${plats}</div>
                </div>
            </a>`;
    },

    /* ── Work detail (stories) ─────────────────────────────────── */

    async renderWork(name) {
        const app = document.getElementById('app');
        app.innerHTML = `
            <div class="work-back"><a href="#/library">&larr; Library</a></div>
            <div id="work-body"><div class="loading-spinner">Opening the work…</div></div>`;

        let d;
        try {
            d = await API.getPostingStory(name);
        } catch (err) {
            document.getElementById('work-body').innerHTML =
                `<div class="card error">Couldn't open this work: ${this.esc(err.message)}</div>`;
            return;
        }
        this._paintWork(name, d);
    },

    _paintWork(name, d) {
        const body = document.getElementById('work-body');
        if (!body) return;

        const coverFile = d.images && d.images.cover;
        const coverUrl = coverFile
            ? `/api/posting/image?story=${encodeURIComponent(name)}&file=${encodeURIComponent(coverFile)}`
            : '';
        const initials = this.esc((d.title || name || '?').trim().charAt(0).toUpperCase());
        const coverEl = coverUrl
            ? `<div class="work-cover" style="background-image:url('${this.esc(coverUrl)}')"></div>`
            : `<div class="work-cover work-cover--blank"><span class="book-initial">${initials}</span></div>`;

        // Aggregate per-platform stats from publications[] (views summed across a
        // platform's rows; faves/comments taken as the max, since those tend to be
        // per-work not per-chapter). Approximate but honest headline numbers.
        const pubs = d.publications || [];
        const byPlat = {};
        pubs.forEach(p => {
            const b = byPlat[p.platform] || (byPlat[p.platform] = { views: 0, faves: 0, comments: 0, url: '', chapters: new Set() });
            b.views += this._views(p.stats);
            b.faves = Math.max(b.faves, this._faves(p.stats));
            b.comments = Math.max(b.comments, this._comments(p.stats));
            if (p.external_url && !b.url) b.url = p.external_url;
            b.chapters.add(p.chapter_index == null ? 0 : p.chapter_index);
        });
        const published = (d.published_platforms && d.published_platforms.length)
            ? d.published_platforms : Object.keys(byPlat);
        const totalViews = Object.values(byPlat).reduce((s, b) => s + b.views, 0);
        const totalFaves = Object.values(byPlat).reduce((s, b) => s + b.faves, 0);
        const totalComments = Object.values(byPlat).reduce((s, b) => s + b.comments, 0);

        // Marginalia (right-side "this work" stats).
        const margin = `
            <div class="work-margin">
                <div class="work-margin-row"><span class="wm-v">${this._num(totalViews)}</span><span class="wm-l">views</span></div>
                <div class="work-margin-row"><span class="wm-v">${this._num(totalFaves)}</span><span class="wm-l">faves</span></div>
                <div class="work-margin-row"><span class="wm-v">${this._num(totalComments)}</span><span class="wm-l">comments</span></div>
                <div class="work-margin-row"><span class="wm-v">${published.length}</span><span class="wm-l">platforms</span></div>
            </div>`;

        const ratingPill = d.rating ? `<span class="work-tag">${this.esc(d.rating)}</span>` : '';
        const wordsPill = d.total_words ? `<span class="work-tag">${this._num(d.total_words)} words</span>` : '';
        const chapPill = d.total_chapters ? `<span class="work-tag">${d.total_chapters} chapter${d.total_chapters === 1 ? '' : 's'}</span>` : '';
        const summary = d.summary || d.description || '';

        // "Published to" — one row per platform with live counts + a link.
        const pubRows = published.map(code => {
            const b = byPlat[code] || { views: 0, faves: 0, comments: 0, url: '' };
            const p = this._plat(code);
            const link = b.url ? `<a class="pub-open" href="${this.esc(b.url)}" target="_blank" rel="noopener">open &#8599;</a>` : '';
            return `
                <div class="pub-row">
                    <span class="pub-plat"><span class="pub-emoji">${p.emoji || ''}</span>${this.esc(p.label)}</span>
                    <span class="pub-stat">${this._num(b.views)} <em>views</em></span>
                    <span class="pub-stat">${this._num(b.faves)} <em>faves</em></span>
                    <span class="pub-stat">${this._num(b.comments)} <em>comments</em></span>
                    ${link}
                </div>`;
        }).join('');
        const notYet = (d.unpublished_platforms || []).filter(c => !byPlat[c]);
        const notYetLine = notYet.length
            ? `<div class="pub-notyet">Not yet on: ${notYet.map(c => this.esc(this._plat(c).label)).join(', ')}</div>`
            : '';

        // Chapter × platform reach. Multi-chapter platforms carry per-chapter
        // publication rows (chapter_index > 0); single-post platforms publish the
        // whole story (chapter_index 0). For each chapter we light the platforms
        // that reached it, and flag gaps on multi-chapter platforms.
        const chapters = d.chapters || [];
        const multiChapPlats = published.filter(c => {
            const ch = byPlat[c] && byPlat[c].chapters;
            return ch && [...ch].some(i => i > 0);
        });
        const reach = {};   // chapter_index -> Set(platform)
        pubs.forEach(p => {
            const idx = p.chapter_index == null ? 0 : p.chapter_index;
            (reach[idx] || (reach[idx] = new Set())).add(p.platform);
        });
        const chapterRows = chapters.map(ch => {
            const idx = ch.index;
            // A chapter is "on" a platform if that platform has this chapter, OR
            // the platform posts the whole story in one (chapter_index 0).
            const lit = published.map(code => {
                const onThis = (reach[idx] && reach[idx].has(code)) || (reach[0] && reach[0].has(code) && !multiChapPlats.includes(code));
                const p = this._plat(code);
                return `<span class="ch-dot ${onThis ? 'is-on' : 'is-off'}" title="${this.esc(p.label)}${onThis ? '' : ' — not here'}">${p.emoji || '•'}</span>`;
            }).join('');
            const gaps = multiChapPlats.filter(code => !(reach[idx] && reach[idx].has(code)));
            const gapFlag = gaps.length
                ? `<span class="ch-gap" title="Missing from ${gaps.map(c => this._plat(c).label).join(', ')}">incomplete</span>` : '';
            return `
                <div class="chapter-row">
                    <span class="chapter-idx">${idx}</span>
                    <span class="chapter-name">${this.esc(ch.title || 'Chapter ' + idx)}${ch.word_count ? ` <em>${this._num(ch.word_count)}w</em>` : ''}</span>
                    <span class="chapter-reach">${lit}</span>
                    ${gapFlag}
                </div>`;
        }).join('');
        const chapterCard = chapters.length ? `
            <section class="work-card">
                <h2 class="work-h2">Chapters <span class="work-h2-note">where each one is live</span></h2>
                <div class="chapter-list">${chapterRows}</div>
            </section>` : '';

        body.innerHTML = `
            <article class="work-hero">
                ${coverEl}
                <div class="work-head">
                    <div class="shelf-eyebrow">${this.esc(d.author ? 'by ' + d.author : 'A work')}</div>
                    <h1 class="work-title">${this.esc(d.title || name)}</h1>
                    <div class="work-tags">${ratingPill}${chapPill}${wordsPill}</div>
                    ${summary ? `<p class="work-summary">${this.esc(summary)}</p>` : ''}
                </div>
                ${margin}
            </article>

            <div class="work-tabs" id="work-tabs">
                <button class="work-tab is-active" data-work-tab="overview">Overview</button>
                <button class="work-tab" data-work-tab="timeline">Timeline</button>
            </div>

            <div class="work-pane" data-pane="overview">
                <section class="work-card">
                    <h2 class="work-h2">Published to <span class="work-h2-note">live counts across your platforms</span></h2>
                    <div class="pub-list">${pubRows || '<div class="muted">Not published anywhere yet.</div>'}</div>
                    ${notYetLine}
                </section>

                ${chapterCard}
            </div>
            <div class="work-pane" data-pane="timeline" hidden>
                <div class="loading-spinner">Tracing this work's history…</div>
            </div>`;

        // Tab switch — lazily render the Ledger timeline on first open, reusing
        // the already-fetched `d` (no extra request). Slice D · "Almanac".
        const tabs = document.getElementById('work-tabs');
        let timelineDone = false;
        if (tabs) {
            tabs.addEventListener('click', (e) => {
                const btn = e.target.closest('.work-tab');
                if (!btn) return;
                const which = btn.dataset.workTab;
                tabs.querySelectorAll('.work-tab').forEach(b => b.classList.toggle('is-active', b === btn));
                body.querySelectorAll('.work-pane').forEach(p => { p.hidden = (p.dataset.pane !== which); });
                if (which === 'timeline' && !timelineDone && window.Ledger) {
                    timelineDone = true;
                    window.Ledger.renderWorkTimeline(body.querySelector('.work-pane[data-pane="timeline"]'), name, d);
                }
            });
        }
    },
};
