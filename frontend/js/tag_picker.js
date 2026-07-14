/* TagPicker — reusable tag-library picker modal.
 *
 * Gives any screen the story-editor's tag-library experience WITHOUT touching the
 * editor's tightly-coupled tag browser (metadata_editor.js writes straight into
 * `this.metadata.tags`). Instead this is a standalone picker that reuses the same
 * `.tag-browser-*` modal chrome + the same tag database (`/api/editor/tags`), with
 * category filter chips and multi-select. On confirm it hands back the selected
 * tag names; the caller decides what to do with them.
 *
 * Built for the Art module (artwork.js) but reusable anywhere.
 *
 * Usage:
 *   TagPicker.open({
 *     title: 'Tag library',
 *     selected: ['dragon', 'macro'],          // pre-checked (case-insensitive)
 *     onConfirm: (names) => { ... },           // final selected canonical names
 *   });
 */
(function () {
    const CATS = ['physical', 'acts', 'kink', 'meta', 'image', 'user'];
    let _cache = null;

    const esc = (s) => (window.Utils && Utils.escapeHtml)
        ? Utils.escapeHtml(String(s == null ? '' : s))
        : String(s == null ? '' : s).replace(/[&<>"']/g, c => (
            { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

    async function loadTags() {
        if (_cache) return _cache;
        try {
            const raw = sessionStorage.getItem('pawpoller_tag_db_v1');
            if (raw) { const c = JSON.parse(raw); if (c && c.tags) { _cache = c.tags; return _cache; } }
        } catch (_) { /* corrupted cache */ }
        const resp = await fetch('/api/editor/tags');
        if (!resp.ok) throw new Error('Tag database failed to load');
        const data = await resp.json();
        try { sessionStorage.setItem('pawpoller_tag_db_v1', JSON.stringify(data)); } catch (_) { /* quota */ }
        _cache = data.tags || [];
        return _cache;
    }

    function open(opts) {
        opts = opts || {};
        const selected = new Set((opts.selected || []).map(s => String(s).toLowerCase()));
        let tags = [];
        let cat = 'all';
        let query = '';
        let searchTimer = null;

        const chips = ['all', ...CATS].map(k =>
            `<button type="button" class="tag-browser-chip${k === cat ? ' tag-browser-chip-active' : ''}" data-tp-cat="${k}">
                <span class="tag-browser-chip-label">${k === 'all' ? 'All' : esc(k.charAt(0).toUpperCase() + k.slice(1))}</span></button>`).join('');

        const root = document.createElement('div');
        root.className = 'tp-root';
        root.innerHTML = `
            <div class="tag-browser-backdrop" data-tp-backdrop></div>
            <div class="tag-browser-modal tp-modal" role="dialog" aria-label="${esc(opts.title || 'Tag library')}">
                <div class="tag-browser-header">
                    <div class="tag-browser-title-row">
                        <div class="tag-browser-title">${esc(opts.title || 'Tag library')}</div>
                        <button type="button" class="tag-browser-close" data-tp-close aria-label="Close">&times;</button>
                    </div>
                    <input type="search" id="tp-search" class="tag-browser-search" placeholder="Search tags…" autocomplete="off">
                    <div class="tag-browser-filters">${chips}</div>
                </div>
                <div class="tag-browser-selected" id="tp-selected"></div>
                <div class="tag-browser-body">
                    <div class="tp-grid" id="tp-grid"><div class="tag-browser-empty">Loading…</div></div>
                </div>
                <div class="tag-browser-footer">
                    <div class="tag-browser-count" id="tp-count">0 selected</div>
                    <button type="button" class="btn btn-primary" id="tp-confirm">Apply</button>
                </div>
            </div>`;
        document.body.appendChild(root);
        requestAnimationFrame(() => root.querySelector('.tag-browser-modal')?.classList.add('open'));

        const grid = root.querySelector('#tp-grid');
        const countEl = root.querySelector('#tp-count');
        const searchEl = root.querySelector('#tp-search');
        const selectedEl = root.querySelector('#tp-selected');

        const close = () => {
            root.querySelector('.tag-browser-modal')?.classList.remove('open');
            document.removeEventListener('keydown', onKey);
            setTimeout(() => root.remove(), 180);
        };
        function onKey(e) { if (e.key === 'Escape') close(); }
        document.addEventListener('keydown', onKey);
        root.querySelector('[data-tp-backdrop]').addEventListener('click', close);
        root.querySelector('[data-tp-close]').addEventListener('click', close);

        // Canonical-case name lookup for the selected set (DB names win; freeform
        // pre-selected tags not in the DB are preserved with their original text).
        const byLower = new Map();
        const preserve = new Map((opts.selected || []).map(s => [String(s).toLowerCase(), String(s)]));

        const renderSelected = () => {
            if (!selected.size) { selectedEl.innerHTML = '<span class="tag-browser-selected-empty">No tags selected</span>'; return; }
            const pills = Array.from(selected).map(low => {
                const name = byLower.get(low) || preserve.get(low) || low;
                return `<span class="tag-browser-selected-pill">${esc(name)}<button type="button" class="tag-browser-selected-remove" data-tp-unpick="${esc(low)}" aria-label="Remove">&times;</button></span>`;
            }).join('');
            selectedEl.innerHTML = `<span class="tag-browser-selected-label">Selected</span><span class="tag-browser-selected-pills">${pills}</span>`;
        };
        const updateCount = () => { countEl.textContent = `${selected.size} selected`; renderSelected(); };

        const visible = () => {
            const q = query.toLowerCase();
            return tags.filter(t =>
                (cat === 'all' || t.category === cat) &&
                (!q || t.name.toLowerCase().includes(q)));
        };

        const render = () => {
            const items = visible().slice(0, 400);
            grid.innerHTML = items.length
                ? items.map(t => {
                    const low = t.name.toLowerCase();
                    return `<button type="button" class="tp-chip${selected.has(low) ? ' is-selected' : ''}" data-tp-name="${esc(t.name)}">
                        <span class="tp-chip-name">${esc(t.name)}</span>
                        <span class="tp-chip-cat">${esc(t.category || '')}</span>
                    </button>`;
                }).join('')
                : '<div class="tag-browser-empty">No tags match.</div>';
        };

        grid.addEventListener('click', (e) => {
            const chip = e.target.closest('.tp-chip');
            if (!chip) return;
            const name = chip.getAttribute('data-tp-name');
            const low = name.toLowerCase();
            byLower.set(low, name);
            if (selected.has(low)) { selected.delete(low); chip.classList.remove('is-selected'); }
            else { selected.add(low); chip.classList.add('is-selected'); }
            updateCount();
        });
        selectedEl.addEventListener('click', (e) => {
            const rm = e.target.closest('[data-tp-unpick]');
            if (!rm) return;
            const low = rm.getAttribute('data-tp-unpick');
            selected.delete(low);
            const chip = grid.querySelector(`.tp-chip[data-tp-name="${CSS.escape(byLower.get(low) || low)}"]`);
            if (chip) chip.classList.remove('is-selected');
            updateCount();
        });
        root.querySelectorAll('[data-tp-cat]').forEach(btn => btn.addEventListener('click', () => {
            cat = btn.getAttribute('data-tp-cat');
            root.querySelectorAll('[data-tp-cat]').forEach(b => b.classList.toggle('tag-browser-chip-active', b === btn));
            render();
        }));
        searchEl.addEventListener('input', () => {
            clearTimeout(searchTimer);
            searchTimer = setTimeout(() => { query = searchEl.value.trim(); render(); }, 200);
        });

        root.querySelector('#tp-confirm').addEventListener('click', () => {
            const names = Array.from(selected).map(low => byLower.get(low) || preserve.get(low) || low);
            if (opts.onConfirm) opts.onConfirm(names);
            close();
        });

        (async () => {
            try { tags = await loadTags(); tags.forEach(t => byLower.set(t.name.toLowerCase(), t.name)); render(); }
            catch (err) { grid.innerHTML = `<div class="tag-browser-empty">${esc(err.message || err)}</div>`; }
        })();
        updateCount();
        setTimeout(() => searchEl.focus(), 60);
        return { close };
    }

    window.TagPicker = { open };
})();
