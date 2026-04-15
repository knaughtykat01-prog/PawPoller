/**
 * Metadata Editor — slide-in drawer for editing story.json metadata.
 *
 * Phase 1 scope:
 *   - Story Info (title, author, fandom, rating)
 *   - Description & Summary (with character counters)
 *
 * Phase 2 scope:
 *   - Classifications (warnings, categories, characters, relationships)
 *   - Per-Platform Tags (stub textareas — autocomplete in Phase 3)
 *   - Platform Toggles
 *
 * Later phases will add: tag autocomplete (P3), per-chapter editing (P4),
 * cover uploads + raw JSON view (P5).
 */
const MetaEditor = {
    // State
    isOpen: false,
    metadata: null,           // current loaded story.json
    initialMetadata: null,    // snapshot for dirty check
    lastMtime: 0,
    storyName: null,

    // Phase 3a: tag database (lazy-loaded on first autocomplete interaction).
    _tagDb: null,             // { tags: [], aliases: {}, byName: Map, names: [], version }
    _tagDbLoading: null,      // in-flight promise (dedupe concurrent loads)
    _activeTagPlatform: 'default',
    _tagDropdownOpenFor: null,   // platform key the dropdown is currently open for
    _tagDropdownIndex: 0,
    _tagDropdownResults: [],     // last rendered result set

    // Phase 3a+: expanded tag browser modal state
    _tagBrowserOpen: false,
    _tagBrowserQuery: '',
    _tagBrowserFilters: new Set(),
    _tagBrowserPage: 1,           // page size = 100 results
    _TAG_BROWSER_PAGE_SIZE: 100,
    _TAG_BROWSER_CATEGORIES: ['physical', 'acts', 'kink', 'meta', 'image'],

    // Platform tag caps (∞ = no cap)
    TAG_LIMITS: {
        sofurry: 97,
        wattpad: 24,
        inkbunny: Infinity,
        default: Infinity,
    },

    // Canonical ratings (must match backend whitelist)
    RATINGS: [
        'Not Rated',
        'General Audiences',
        'Teen And Up Audiences',
        'Mature',
        'Explicit',
    ],

    // AO3 archive warnings (canonical list)
    WARNINGS: [
        'No Archive Warnings Apply',
        'Choose Not To Use Archive Warnings',
        'Graphic Depictions Of Violence',
        'Major Character Death',
        'Rape/Non-Con',
        'Underage Sex',
    ],

    // AO3 categories
    CATEGORIES: ['F/F', 'F/M', 'Gen', 'M/M', 'Multi', 'Other'],

    // Platform keys (order controls render)
    PLATFORMS: ['sofurry', 'inkbunny', 'squidgeworld', 'ao3', 'furaffinity', 'wattpad'],

    // Platforms that support per-platform tag overrides (Section 4)
    TAG_PLATFORMS: ['default', 'sofurry', 'inkbunny', 'wattpad'],

    // Human-readable platform names
    PLATFORM_LABELS: {
        sofurry: 'SoFurry',
        inkbunny: 'Inkbunny',
        squidgeworld: 'SquidgeWorld',
        ao3: 'AO3',
        furaffinity: 'FurAffinity',
        wattpad: 'Wattpad',
        default: 'Default',
    },

    // Character limits (soft — warns in counter, no hard validation)
    DESC_MAX: 500,
    SUMMARY_MAX: 2000,

    // ---------------------------------------------------------------------
    // Public entry point
    // ---------------------------------------------------------------------

    async toggle() {
        if (this.isOpen) {
            this.close();
            return;
        }
        if (!Editor.storyName) {
            alert('No story loaded.');
            return;
        }
        this.storyName = Editor.storyName;

        this._mountDrawer();
        this.isOpen = true;

        try {
            await this._loadMetadata();
            this._renderForm();
            this._initFormBindings();
        } catch (err) {
            this._renderError(err.message || String(err));
        }
    },

    close() {
        if (!this.isOpen) return;
        if (this._isDirty()) {
            if (!confirm('Discard unsaved metadata changes?')) return;
        }
        const root = document.getElementById('metadata-drawer-root');
        if (root) {
            // Trigger slide-out then remove
            const drawer = root.querySelector('.metadata-drawer');
            if (drawer) drawer.classList.remove('open');
            setTimeout(() => root.remove(), 200);
        }
        this.isOpen = false;
        this.metadata = null;
        this.initialMetadata = null;
        this.lastMtime = 0;
        this.storyName = null;
    },

    // ---------------------------------------------------------------------
    // Mount / unmount drawer shell
    // ---------------------------------------------------------------------

    _mountDrawer() {
        // Remove any stale instance first
        const existing = document.getElementById('metadata-drawer-root');
        if (existing) existing.remove();

        const root = document.createElement('div');
        root.id = 'metadata-drawer-root';
        root.innerHTML = `
            <div class="metadata-drawer-backdrop" id="metadata-drawer-backdrop"></div>
            <aside class="metadata-drawer" id="metadata-drawer" role="dialog" aria-label="Story metadata">
                <div class="metadata-drawer-header">
                    <div class="metadata-drawer-title">
                        <span>Metadata</span>
                        <span class="metadata-drawer-subtitle" id="metadata-drawer-subtitle"></span>
                    </div>
                    <div class="metadata-drawer-actions">
                        <span class="metadata-drawer-status" id="metadata-drawer-status"></span>
                        <button class="btn btn-sm" id="metadata-save-btn">Save</button>
                        <button class="btn btn-sm btn-outline" id="metadata-close-btn" title="Close">&times;</button>
                    </div>
                </div>
                <div class="metadata-drawer-body" id="metadata-drawer-body">
                    <div class="metadata-loading">Loading metadata...</div>
                </div>
            </aside>
        `;
        document.body.appendChild(root);

        // Trigger slide-in on next frame (so transition plays)
        requestAnimationFrame(() => {
            document.getElementById('metadata-drawer')?.classList.add('open');
        });

        // Wire up shell buttons once (form bindings happen after _renderForm)
        document.getElementById('metadata-close-btn')?.addEventListener('click', () => this.close());
        document.getElementById('metadata-drawer-backdrop')?.addEventListener('click', () => this.close());
        document.getElementById('metadata-save-btn')?.addEventListener('click', () => this.save());
    },

    _renderError(msg) {
        const body = document.getElementById('metadata-drawer-body');
        if (body) {
            body.innerHTML = `<div class="metadata-error-banner">Failed to load metadata: ${this._escape(msg)}</div>`;
        }
    },

    // ---------------------------------------------------------------------
    // Load metadata from backend
    // ---------------------------------------------------------------------

    async _loadMetadata() {
        const resp = await fetch(`/api/editor/stories/${encodeURIComponent(this.storyName)}/metadata`);
        if (!resp.ok) {
            const txt = await resp.text();
            throw new Error(txt || `HTTP ${resp.status}`);
        }
        const data = await resp.json();
        this.metadata = data.metadata || {};
        this.lastMtime = data.last_modified || 0;
        // Snapshot initial state for dirty tracking (deep clone via JSON)
        this.initialMetadata = JSON.parse(JSON.stringify(this.metadata));
        // Drawer subtitle shows story title for context
        const sub = document.getElementById('metadata-drawer-subtitle');
        if (sub) sub.textContent = this.metadata.title || this.storyName;
    },

    // ---------------------------------------------------------------------
    // Form rendering
    // ---------------------------------------------------------------------

    _renderForm() {
        const body = document.getElementById('metadata-drawer-body');
        if (!body) return;

        // Normalise Phase 2 fields on the live metadata so later reads/writes
        // operate on arrays/objects instead of undefined.
        this._normaliseMetadata();

        const md = this.metadata || {};
        const ratingOptions = ['', ...this.RATINGS]
            .map(r => {
                const selected = (md.rating || '').toString().toLowerCase() === r.toLowerCase() ? ' selected' : '';
                const label = r || '(unset)';
                return `<option value="${this._escape(r)}"${selected}>${this._escape(label)}</option>`;
            })
            .join('');

        const descVal = md.description || '';
        const summaryVal = md.summary || '';

        body.innerHTML = `
            <section class="metadata-section" data-section="info" data-expanded="true">
                <button type="button" class="metadata-section-header" data-section-toggle="info">
                    <span class="metadata-section-chevron">&#9660;</span>
                    <span>Story Info</span>
                </button>
                <div class="metadata-section-body">
                    <div class="metadata-field">
                        <label for="meta-title">Title <span class="metadata-required">*</span></label>
                        <input type="text" id="meta-title" data-field="title" value="${this._escape(md.title || '')}" autocomplete="off" />
                        <div class="metadata-error" id="meta-error-title"></div>
                    </div>
                    <div class="metadata-field">
                        <label for="meta-author">Author</label>
                        <input type="text" id="meta-author" data-field="author" value="${this._escape(md.author || '')}" autocomplete="off" />
                    </div>
                    <div class="metadata-field">
                        <label for="meta-fandom">Fandom</label>
                        <input type="text" id="meta-fandom" data-field="fandom" value="${this._escape(md.fandom || '')}" autocomplete="off" />
                    </div>
                    <div class="metadata-field">
                        <label for="meta-rating">Rating</label>
                        <select id="meta-rating" data-field="rating">
                            ${ratingOptions}
                        </select>
                        <div class="metadata-error" id="meta-error-rating"></div>
                    </div>
                </div>
            </section>

            <section class="metadata-section" data-section="desc" data-expanded="false">
                <button type="button" class="metadata-section-header" data-section-toggle="desc">
                    <span class="metadata-section-chevron">&#9654;</span>
                    <span>Description &amp; Summary</span>
                </button>
                <div class="metadata-section-body">
                    <div class="metadata-field">
                        <label for="meta-description">Description <span class="metadata-char-counter" id="meta-desc-counter"></span></label>
                        <textarea id="meta-description" data-field="description" rows="3">${this._escape(descVal)}</textarea>
                    </div>
                    <div class="metadata-field">
                        <label for="meta-summary">Summary <span class="metadata-char-counter" id="meta-summary-counter"></span></label>
                        <textarea id="meta-summary" data-field="summary" rows="8">${this._escape(summaryVal)}</textarea>
                    </div>
                </div>
            </section>

            ${this._renderClassificationsSection()}
            ${this._renderPlatformTagsSection()}
            ${this._renderPlatformTogglesSection()}
        `;

        this._updateCharCounter('meta-description', 'meta-desc-counter', this.DESC_MAX);
        this._updateCharCounter('meta-summary', 'meta-summary-counter', this.SUMMARY_MAX);
    },

    /**
     * Ensure all Phase 2 metadata fields exist as the right JS type so
     * subsequent renderers/binders can assume arrays + objects.
     */
    _normaliseMetadata() {
        const md = this.metadata = this.metadata || {};

        if (!Array.isArray(md.warnings)) {
            md.warnings = [];
        }

        // Legacy: `category` (string) → `categories` (array)
        if (!Array.isArray(md.categories)) {
            if (typeof md.category === 'string' && md.category.trim()) {
                md.categories = [md.category.trim()];
            } else {
                md.categories = [];
            }
        }

        if (!Array.isArray(md.characters)) md.characters = [];
        if (!Array.isArray(md.relationships)) md.relationships = [];

        if (!md.tags || typeof md.tags !== 'object' || Array.isArray(md.tags)) {
            md.tags = {};
        }
        this.TAG_PLATFORMS.forEach(p => {
            if (!Array.isArray(md.tags[p])) md.tags[p] = [];
        });

        if (!md.platforms || typeof md.platforms !== 'object' || Array.isArray(md.platforms)) {
            md.platforms = {};
        }
        this.PLATFORMS.forEach(p => {
            if (typeof md.platforms[p] !== 'boolean') md.platforms[p] = !!md.platforms[p];
        });
    },

    // ---------------------------------------------------------------------
    // Section 3: Classifications
    // ---------------------------------------------------------------------

    _renderClassificationsSection() {
        const md = this.metadata;

        const warningsHtml = this.WARNINGS.map((w, i) => {
            const checked = md.warnings.includes(w) ? ' checked' : '';
            const id = `meta-warning-${i}`;
            return `
                <label class="metadata-checkbox" for="${id}">
                    <input type="checkbox" id="${id}" data-classification="warning" value="${this._escape(w)}"${checked} />
                    <span>${this._escape(w)}</span>
                </label>
            `;
        }).join('');

        const categoriesHtml = this.CATEGORIES.map((c, i) => {
            const checked = md.categories.includes(c) ? ' checked' : '';
            const id = `meta-category-${i}`;
            return `
                <label class="metadata-checkbox" for="${id}">
                    <input type="checkbox" id="${id}" data-classification="category" value="${this._escape(c)}"${checked} />
                    <span>${this._escape(c)}</span>
                </label>
            `;
        }).join('');

        return `
            <section class="metadata-section" data-section="classifications" data-expanded="false">
                <button type="button" class="metadata-section-header" data-section-toggle="classifications">
                    <span class="metadata-section-chevron">&#9654;</span>
                    <span>Classifications</span>
                </button>
                <div class="metadata-section-body">
                    <div class="metadata-field">
                        <label>Archive Warnings <span class="metadata-required">*</span></label>
                        <div class="metadata-checkbox-list" id="meta-warnings-list">
                            ${warningsHtml}
                        </div>
                        <div class="metadata-error" id="meta-error-warnings"></div>
                    </div>
                    <div class="metadata-field">
                        <label>Categories</label>
                        <div class="metadata-checkbox-row" id="meta-categories-list">
                            ${categoriesHtml}
                        </div>
                    </div>
                    <div class="metadata-field">
                        <label for="meta-characters-input">Characters</label>
                        ${this._renderPillInput('characters', md.characters, 'Type a character and press Enter')}
                    </div>
                    <div class="metadata-field">
                        <label for="meta-relationships-input">Relationships</label>
                        ${this._renderPillInput('relationships', md.relationships, 'e.g. Alice/Bob, Alice & Bob')}
                    </div>
                </div>
            </section>
        `;
    },

    // ---------------------------------------------------------------------
    // Section 4: Per-Platform Tags (Phase 3a — autocomplete)
    //
    // UI: one section containing a tab strip (Default/SoFurry/Wattpad/Inkbunny);
    // active tab shows a pill list + autocomplete input + a footer counter.
    // Pills write back to `metadata.tags.<platform>` so the standard dirty
    // check picks up changes with no extra wiring.
    // ---------------------------------------------------------------------

    _renderPlatformTagsSection() {
        const tabs = this.TAG_PLATFORMS.map(p => {
            const active = p === this._activeTagPlatform ? ' metadata-tag-tab-active' : '';
            return `<button type="button" class="metadata-tag-tab${active}" data-tag-tab="${this._escape(p)}">${this._escape(this.PLATFORM_LABELS[p] || p)}</button>`;
        }).join('');

        return `
            <section class="metadata-section" data-section="platform-tags" data-expanded="false">
                <button type="button" class="metadata-section-header" data-section-toggle="platform-tags">
                    <span class="metadata-section-chevron">&#9654;</span>
                    <span>Per-Platform Tags</span>
                </button>
                <div class="metadata-section-body">
                    <div class="metadata-tag-tabs" role="tablist">${tabs}</div>
                    <div class="metadata-tag-tab-body" id="metadata-tag-tab-body">
                        ${this._renderTagTabBody(this._activeTagPlatform)}
                    </div>
                </div>
            </section>
        `;
    },

    _renderTagTabBody(platform) {
        const md = this.metadata;
        const tags = md.tags[platform] || [];
        const aliases = this._tagDb ? this._tagDb.aliases : {};
        const byName = this._tagDb ? this._tagDb.byName : null;

        const pills = tags.map((t, i) => {
            const inDb = byName ? byName.has(t) : false;
            const aliasTarget = (!inDb && aliases[t]) ? aliases[t] : null;
            let cls = 'metadata-tag-pill';
            if (byName && !inDb && !aliasTarget) cls += ' metadata-tag-pill-unknown';
            const aliasNote = aliasTarget ? `<span class="metadata-tag-pill-alias">&rarr; ${this._escape(aliasTarget)}</span>` : '';
            return `
                <span class="${cls}" data-tag-pill-index="${i}">
                    <span class="metadata-tag-pill-text">${this._escape(t)}</span>
                    ${aliasNote}
                    <button type="button" class="metadata-tag-pill-remove" data-tag-remove="${this._escape(platform)}" data-index="${i}" aria-label="Remove tag">&times;</button>
                </span>
            `;
        }).join('');

        const limit = this.TAG_LIMITS[platform];
        const limitLabel = (limit === Infinity) ? '&infin;' : limit;
        const overLimit = (limit !== Infinity) && tags.length > limit;

        return `
            <div class="metadata-tag-pills" id="metadata-tag-pills-${this._escape(platform)}">${pills}</div>
            <div class="metadata-tag-input-wrap">
                <input type="text"
                       class="metadata-tag-input"
                       id="metadata-tag-input"
                       data-tag-platform-input="${this._escape(platform)}"
                       placeholder="Add tag..."
                       autocomplete="off" />
                <div class="metadata-tag-dropdown" id="metadata-tag-dropdown" hidden></div>
            </div>
            <div class="metadata-tag-count ${overLimit ? 'metadata-tag-count-over' : ''}">
                <span id="metadata-tag-count-text">${tags.length} tags</span>
                <span class="metadata-tag-count-sep">&middot;</span>
                <span>Platform max: ${limitLabel}</span>
            </div>
        `;
    },

    _rerenderTagTabBody() {
        const host = document.getElementById('metadata-tag-tab-body');
        if (!host) return;
        host.innerHTML = this._renderTagTabBody(this._activeTagPlatform);
        this._bindTagTabBodyEvents();
    },

    _updateTagTabs() {
        document.querySelectorAll('[data-tag-tab]').forEach(b => {
            const p = b.getAttribute('data-tag-tab');
            b.classList.toggle('metadata-tag-tab-active', p === this._activeTagPlatform);
        });
    },

    // ---- Tag DB loading (lazy, cached in sessionStorage by version hash) ----

    async _loadTagDb() {
        if (this._tagDb) return this._tagDb;
        if (this._tagDbLoading) return this._tagDbLoading;

        this._tagDbLoading = (async () => {
            // Try sessionStorage cache first, but still fetch to check version.
            // We could optimise by sending If-None-Match, but the payload is
            // tiny gzipped and parsed once per session — keep it simple.
            try {
                const cachedRaw = sessionStorage.getItem('pawpoller_tag_db_v1');
                if (cachedRaw) {
                    const cached = JSON.parse(cachedRaw);
                    if (cached && cached.version && cached.tags) {
                        this._tagDb = this._indexTagDb(cached);
                        // Fire off a background refresh so stale versions self-heal
                        this._refreshTagDbBackground();
                        return this._tagDb;
                    }
                }
            } catch (_) { /* corrupted cache — ignore */ }

            const resp = await fetch('/api/editor/tags');
            if (!resp.ok) {
                const t = await resp.text();
                throw new Error(`Tag DB load failed: ${t || resp.status}`);
            }
            const data = await resp.json();
            try { sessionStorage.setItem('pawpoller_tag_db_v1', JSON.stringify(data)); } catch (_) { /* quota */ }
            this._tagDb = this._indexTagDb(data);
            return this._tagDb;
        })();

        try {
            return await this._tagDbLoading;
        } finally {
            this._tagDbLoading = null;
        }
    },

    async _refreshTagDbBackground() {
        try {
            const resp = await fetch('/api/editor/tags');
            if (!resp.ok) return;
            const data = await resp.json();
            if (this._tagDb && data.version === this._tagDb.version) return;
            try { sessionStorage.setItem('pawpoller_tag_db_v1', JSON.stringify(data)); } catch (_) {}
            this._tagDb = this._indexTagDb(data);
            // Refresh current view so any unknown-tag styling gets re-evaluated
            if (this.isOpen) this._rerenderTagTabBody();
        } catch (_) { /* silent */ }
    },

    _indexTagDb(data) {
        const byName = new Map();
        for (const t of data.tags) byName.set(t.name, t);
        // Pre-lowercase names for cheap case-insensitive filtering
        const names = data.tags.map(t => ({
            name: t.name,
            lower: t.name.toLowerCase(),
            tag: t,
        }));
        return {
            tags: data.tags,
            aliases: data.aliases || {},
            version: data.version,
            byName,
            names,
        };
    },

    // ---- Dropdown rendering + filtering ----

    _filterTagResults(query) {
        if (!this._tagDb) return [];
        const q = (query || '').toLowerCase().trim();
        if (!q) return [];

        const { names, aliases, byName } = this._tagDb;
        const exact = [];
        const prefix = [];
        const substring = [];

        for (const entry of names) {
            if (entry.lower === q) exact.push({ kind: 'tag', tag: entry.tag });
            else if (entry.lower.startsWith(q)) prefix.push({ kind: 'tag', tag: entry.tag });
            else if (entry.lower.includes(q)) substring.push({ kind: 'tag', tag: entry.tag });
            if (exact.length + prefix.length + substring.length >= 120) break;
        }

        // Alias matches — show canonical tag with "(alias)" badge
        const aliasResults = [];
        const qAliasExact = aliases[q];
        if (qAliasExact && byName.has(qAliasExact)) {
            aliasResults.push({ kind: 'alias', from: q, tag: byName.get(qAliasExact) });
        }
        // Also substring match on aliases (cheap — ~23K entries)
        let aliasCount = 0;
        for (const [aliasKey, canonical] of Object.entries(aliases)) {
            if (aliasCount >= 10) break;
            if (aliasKey === q) continue; // already added above
            if (aliasKey.toLowerCase().includes(q) && byName.has(canonical)) {
                aliasResults.push({ kind: 'alias', from: aliasKey, tag: byName.get(canonical) });
                aliasCount++;
            }
        }

        const combined = [...exact, ...aliasResults, ...prefix, ...substring];

        // Dedup by canonical tag name, keeping first occurrence (preserves priority)
        const seen = new Set();
        const out = [];
        for (const r of combined) {
            if (seen.has(r.tag.name)) continue;
            seen.add(r.tag.name);
            out.push(r);
            if (out.length >= 30) break;
        }
        return out;
    },

    _positionDropdown() {
        const dd = document.getElementById('metadata-tag-dropdown');
        const input = document.getElementById('metadata-tag-input');
        if (!dd || !input) return;
        const rect = input.getBoundingClientRect();
        const viewportH = window.innerHeight;
        const spaceBelow = viewportH - rect.bottom;
        const spaceAbove = rect.top;
        // Prefer below; flip up if cramped
        if (spaceBelow < 200 && spaceAbove > spaceBelow) {
            dd.style.top = '';
            dd.style.bottom = (viewportH - rect.top + 4) + 'px';
            dd.style.maxHeight = Math.min(480, spaceAbove - 16) + 'px';
        } else {
            dd.style.bottom = '';
            dd.style.top = (rect.bottom + 4) + 'px';
            dd.style.maxHeight = Math.min(480, spaceBelow - 16) + 'px';
        }
        dd.style.left = rect.left + 'px';
        dd.style.width = Math.max(380, rect.width) + 'px';
    },

    _renderDropdown(results, query) {
        const dd = document.getElementById('metadata-tag-dropdown');
        if (!dd) return;
        this._tagDropdownResults = results;
        const footer = `
            <div class="metadata-tag-dropdown-footer">
                <button type="button" class="metadata-tag-browse-btn" data-action="open-tag-browser">
                    &#128269; Browse all matches in expanded view &rarr;
                </button>
            </div>
        `;
        if (!results.length) {
            const q = (query || '').trim();
            if (q) {
                dd.innerHTML = `<div class="metadata-tag-result-empty">No matches &mdash; Press Enter to add "<span>${this._escape(q)}</span>" anyway</div>${footer}`;
                dd.hidden = false;
            } else {
                // Empty query, no results — still show footer so user can open browser
                dd.innerHTML = footer;
                dd.hidden = false;
            }
            this._positionDropdown();
            return;
        }
        const rows = results.map((r, i) => {
            const t = r.tag;
            const active = i === this._tagDropdownIndex ? ' metadata-tag-result-active' : '';
            const aliasBadge = r.kind === 'alias'
                ? `<span class="metadata-tag-result-alias">alias of &ldquo;${this._escape(r.from)}&rdquo;</span>` : '';
            const desc = t.desc ? `<div class="metadata-tag-result-desc">${this._escape(this._truncate(t.desc, 110))}</div>` : '';
            return `
                <div class="metadata-tag-result${active}" data-tag-result-index="${i}">
                    <div class="metadata-tag-result-row">
                        <span class="metadata-tag-result-name">${this._escape(t.name)}</span>
                        <span class="metadata-tag-result-cat metadata-tag-cat-${this._escape(t.category)}">${this._escape(t.category)}</span>
                        ${aliasBadge}
                    </div>
                    ${desc}
                </div>
            `;
        }).join('');
        dd.innerHTML = rows + footer;
        dd.hidden = false;
        this._positionDropdown();
    },

    _closeDropdown() {
        const dd = document.getElementById('metadata-tag-dropdown');
        if (dd) {
            dd.hidden = true;
            dd.innerHTML = '';
        }
        this._tagDropdownOpenFor = null;
        this._tagDropdownResults = [];
        this._tagDropdownIndex = 0;
    },

    async _openDropdownFor(platform, query) {
        this._tagDropdownOpenFor = platform;
        this._tagDropdownIndex = 0;
        if (!this._tagDb) {
            // Show loading state while fetching
            const dd = document.getElementById('metadata-tag-dropdown');
            if (dd) {
                dd.innerHTML = `<div class="metadata-tag-result-empty">Loading tag database...</div>`;
                dd.hidden = false;
            }
            try {
                await this._loadTagDb();
            } catch (err) {
                if (dd) dd.innerHTML = `<div class="metadata-tag-result-empty">Failed to load tags: ${this._escape(err.message || err)}</div>`;
                return;
            }
            // User may have moved on — check still focused
            if (this._tagDropdownOpenFor !== platform) return;
        }
        const results = this._filterTagResults(query);
        this._renderDropdown(results, query);
    },

    // Platform-specific transforms: convert a default canonical tag into the
    // form expected by each target platform.
    _transformTagForPlatform(canonicalTag, platform) {
        if (platform === 'default') return canonicalTag;
        if (platform === 'wattpad') {
            // camelCase: "slow_burn" → "slowBurn"
            return canonicalTag.replace(/_([a-z])/g, (_, c) => c.toUpperCase());
        }
        // sofurry, inkbunny: spaces instead of underscores
        return canonicalTag.replace(/_/g, ' ');
    },

    _addTagToPlatform(platform, rawName) {
        const name = (rawName || '').trim();
        if (!name) return;
        const tags = this.metadata.tags[platform] || [];
        // Case-insensitive dedup
        if (tags.some(t => t.toLowerCase() === name.toLowerCase())) return;

        // If this matches an alias, add the canonical tag instead
        let final = name;
        if (this._tagDb) {
            const alias = this._tagDb.aliases[name.toLowerCase()];
            if (alias && this._tagDb.byName.has(alias)) {
                if (tags.some(t => t.toLowerCase() === alias.toLowerCase())) return;
                final = alias;
            }
        }

        tags.push(final);
        this.metadata.tags[platform] = tags;

        // Default tab is canonical — propagate to other platforms with transforms
        if (platform === 'default') {
            for (const p of this.TAG_PLATFORMS) {
                if (p === 'default') continue;
                const transformed = this._transformTagForPlatform(final, p);
                const otherTags = this.metadata.tags[p] || [];
                if (!otherTags.some(t => t.toLowerCase() === transformed.toLowerCase())) {
                    otherTags.push(transformed);
                    this.metadata.tags[p] = otherTags;
                }
            }
        }

        this._clearStatus();
        this._rerenderTagTabBody();
        requestAnimationFrame(() => {
            const input = document.getElementById('metadata-tag-input');
            if (input) input.focus();
        });
    },

    _removeTagFromPlatform(platform, index) {
        const tags = this.metadata.tags[platform] || [];
        if (index < 0 || index >= tags.length) return;
        const removed = tags[index];
        tags.splice(index, 1);
        this.metadata.tags[platform] = tags;

        // Default removal cascades to other platforms (using transformed name)
        if (platform === 'default') {
            for (const p of this.TAG_PLATFORMS) {
                if (p === 'default') continue;
                const transformed = this._transformTagForPlatform(removed, p);
                const otherTags = this.metadata.tags[p] || [];
                const idx = otherTags.findIndex(t => t.toLowerCase() === transformed.toLowerCase());
                if (idx >= 0) {
                    otherTags.splice(idx, 1);
                    this.metadata.tags[p] = otherTags;
                }
            }
        }

        this._clearStatus();
        this._rerenderTagTabBody();
    },

    _bindTagTabBodyEvents() {
        // Remove-pill buttons
        document.querySelectorAll('[data-tag-remove]').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.preventDefault();
                const platform = btn.getAttribute('data-tag-remove');
                const idx = parseInt(btn.getAttribute('data-index'), 10);
                if (!Number.isNaN(idx)) this._removeTagFromPlatform(platform, idx);
            });
        });

        const input = document.getElementById('metadata-tag-input');
        if (!input) return;
        const platform = input.getAttribute('data-tag-platform-input');

        input.addEventListener('focus', () => {
            this._openDropdownFor(platform, input.value);
        });

        input.addEventListener('input', () => {
            this._openDropdownFor(platform, input.value);
        });

        input.addEventListener('keydown', (e) => {
            const results = this._tagDropdownResults;
            if (e.key === 'ArrowDown') {
                e.preventDefault();
                if (!results.length) return;
                this._tagDropdownIndex = Math.min(results.length - 1, this._tagDropdownIndex + 1);
                this._renderDropdown(results, input.value);
            } else if (e.key === 'ArrowUp') {
                e.preventDefault();
                if (!results.length) return;
                this._tagDropdownIndex = Math.max(0, this._tagDropdownIndex - 1);
                this._renderDropdown(results, input.value);
            } else if (e.key === 'Enter') {
                e.preventDefault();
                const picked = results[this._tagDropdownIndex];
                if (picked) {
                    this._addTagToPlatform(platform, picked.tag.name);
                } else if (input.value.trim()) {
                    // No matches — add raw (allows arbitrary tags)
                    this._addTagToPlatform(platform, input.value);
                }
                // _rerenderTagTabBody replaces the input; nothing else to clear
            } else if (e.key === 'Escape') {
                this._closeDropdown();
                input.blur();
            } else if (e.key === 'Backspace' && input.value === '') {
                // Remove last pill
                const tags = this.metadata.tags[platform] || [];
                if (tags.length) {
                    tags.pop();
                    this.metadata.tags[platform] = tags;
                    this._clearStatus();
                    this._rerenderTagTabBody();
                }
            }
        });

        input.addEventListener('blur', () => {
            // Small delay so click-on-result registers before we close
            setTimeout(() => this._closeDropdown(), 150);
        });

        const dd = document.getElementById('metadata-tag-dropdown');
        if (dd) {
            dd.addEventListener('mousedown', (e) => {
                // Prevent blur from firing before click
                e.preventDefault();
            });
            dd.addEventListener('click', (e) => {
                const actionBtn = e.target.closest('[data-action="open-tag-browser"]');
                if (actionBtn) {
                    e.preventDefault();
                    const input = document.getElementById('metadata-tag-input');
                    const q = input ? input.value : '';
                    this._closeDropdown();
                    this._openTagBrowser(q);
                    return;
                }
                const row = e.target.closest('[data-tag-result-index]');
                if (!row) return;
                const idx = parseInt(row.getAttribute('data-tag-result-index'), 10);
                const picked = this._tagDropdownResults[idx];
                if (picked) this._addTagToPlatform(platform, picked.tag.name);
            });
        }
    },

    _truncate(s, n) {
        if (!s) return '';
        return s.length > n ? (s.slice(0, n - 1) + '\u2026') : s;
    },

    // ---------------------------------------------------------------------
    // Section 4b: Expanded Tag Browser Modal (Phase 3a+)
    //
    // Full-screen modal giving users a card grid view of all matching tags
    // with category filter chips + pagination. Mounted on document.body
    // (not inside the drawer) so it can overlay at a higher z-index.
    // ---------------------------------------------------------------------

    /**
     * Public entry point — opens the expanded tag browser for the currently
     * active tag platform. Can be called from anywhere once the drawer is
     * open (e.g. via console, or by future keyboard shortcuts).
     */
    openTagBrowser(query) {
        this._openTagBrowser(query || '');
    },

    async _openTagBrowser(initialQuery) {
        if (!this.isOpen) return;
        this._tagBrowserOpen = true;
        this._tagBrowserQuery = initialQuery || '';
        this._tagBrowserFilters = new Set();
        this._tagBrowserPage = 1;

        // Mount shell immediately with a loading state so the modal pops
        // up even if the tag DB is still loading.
        this._mountTagBrowser();

        if (!this._tagDb) {
            try {
                await this._loadTagDb();
            } catch (err) {
                const host = document.getElementById('tag-browser-results');
                if (host) host.innerHTML = `<div class="tag-browser-empty">Failed to load tags: ${this._escape(err.message || err)}</div>`;
                return;
            }
            // If closed during load, bail
            if (!this._tagBrowserOpen) return;
        }
        this._renderTagBrowserResults();
        this._updateTagBrowserFilterCounts();
        this._updateTagBrowserSelectedStrip();
        this._updateTagBrowserFooter();
    },

    _closeTagBrowser() {
        if (!this._tagBrowserOpen) return;
        this._tagBrowserOpen = false;
        const root = document.getElementById('tag-browser-root');
        if (root) {
            const modal = root.querySelector('.tag-browser-modal');
            if (modal) modal.classList.remove('open');
            setTimeout(() => root.remove(), 200);
        }
        // Unhook escape handler
        if (this._tagBrowserKeyHandler) {
            document.removeEventListener('keydown', this._tagBrowserKeyHandler);
            this._tagBrowserKeyHandler = null;
        }
        // Re-render the underlying drawer tag pills so they reflect any
        // additions/removals made through the browser.
        this._rerenderTagTabBody();
    },

    _mountTagBrowser() {
        // Remove any stale instance
        const stale = document.getElementById('tag-browser-root');
        if (stale) stale.remove();

        const root = document.createElement('div');
        root.id = 'tag-browser-root';
        root.innerHTML = this._renderTagBrowser();
        document.body.appendChild(root);

        // Slide-in on next frame so CSS transition plays
        requestAnimationFrame(() => {
            root.querySelector('.tag-browser-modal')?.classList.add('open');
            const search = document.getElementById('tag-browser-search');
            if (search) {
                search.focus();
                // Put cursor at end so typing appends
                const v = search.value;
                search.value = '';
                search.value = v;
            }
        });

        this._bindTagBrowserEvents();
    },

    _renderTagBrowser() {
        const platform = this._activeTagPlatform;
        const platformLabel = this.PLATFORM_LABELS[platform] || platform;
        const q = this._tagBrowserQuery || '';
        const filters = this._tagBrowserFilters;

        const chips = ['all', ...this._TAG_BROWSER_CATEGORIES].map(cat => {
            const active = (cat === 'all' && filters.size === 0) || filters.has(cat);
            const label = cat === 'all' ? 'All' : (cat.charAt(0).toUpperCase() + cat.slice(1));
            return `<button type="button" class="tag-browser-chip${active ? ' tag-browser-chip-active' : ''}" data-tb-filter="${this._escape(cat)}"><span class="tag-browser-chip-label">${this._escape(label)}</span> <span class="tag-browser-chip-count" data-tb-count="${this._escape(cat)}"></span></button>`;
        }).join('');

        return `
            <div class="tag-browser-backdrop" data-tb-backdrop></div>
            <div class="tag-browser-modal" role="dialog" aria-label="Browse tags">
                <div class="tag-browser-header">
                    <div class="tag-browser-title-row">
                        <div class="tag-browser-title">Browse Tags &mdash; ${this._escape(platformLabel)}</div>
                        <button type="button" class="tag-browser-close" data-tb-close aria-label="Close">&times;</button>
                    </div>
                    <input type="text" id="tag-browser-search" class="tag-browser-search" placeholder="Search tags..." value="${this._escape(q)}" autocomplete="off" />
                    <div class="tag-browser-filters">${chips}</div>
                </div>
                <div class="tag-browser-selected" id="tag-browser-selected"></div>
                <div class="tag-browser-body">
                    <div class="tag-browser-grid" id="tag-browser-results">
                        <div class="tag-browser-empty">Loading...</div>
                    </div>
                    <div class="tag-browser-loadmore-wrap" id="tag-browser-loadmore-wrap"></div>
                </div>
                <div class="tag-browser-footer">
                    <div class="tag-browser-count" id="tag-browser-count"></div>
                    <button type="button" class="btn btn-sm" data-tb-close>Done</button>
                </div>
            </div>
        `;
    },

    _bindTagBrowserEvents() {
        const root = document.getElementById('tag-browser-root');
        if (!root) return;

        // Close (×, Done, backdrop)
        root.querySelectorAll('[data-tb-close]').forEach(el => {
            el.addEventListener('click', (e) => {
                e.preventDefault();
                this._closeTagBrowser();
            });
        });
        const backdrop = root.querySelector('[data-tb-backdrop]');
        if (backdrop) {
            backdrop.addEventListener('click', () => this._closeTagBrowser());
        }

        // Escape key
        this._tagBrowserKeyHandler = (e) => {
            if (e.key === 'Escape' && this._tagBrowserOpen) {
                e.preventDefault();
                this._closeTagBrowser();
            }
        };
        document.addEventListener('keydown', this._tagBrowserKeyHandler);

        // Search input — live filter
        const search = document.getElementById('tag-browser-search');
        if (search) {
            search.addEventListener('input', () => {
                this._tagBrowserQuery = search.value;
                this._tagBrowserPage = 1;
                this._renderTagBrowserResults();
                this._updateTagBrowserFilterCounts();
            });
        }

        // Filter chips — toggle multi-select
        root.querySelectorAll('[data-tb-filter]').forEach(btn => {
            btn.addEventListener('click', () => {
                const cat = btn.getAttribute('data-tb-filter');
                if (cat === 'all') {
                    this._tagBrowserFilters.clear();
                } else {
                    if (this._tagBrowserFilters.has(cat)) {
                        this._tagBrowserFilters.delete(cat);
                    } else {
                        this._tagBrowserFilters.add(cat);
                    }
                }
                this._tagBrowserPage = 1;
                this._updateTagBrowserChipStates();
                this._renderTagBrowserResults();
            });
        });
    },

    _updateTagBrowserChipStates() {
        const root = document.getElementById('tag-browser-root');
        if (!root) return;
        const filters = this._tagBrowserFilters;
        root.querySelectorAll('[data-tb-filter]').forEach(btn => {
            const cat = btn.getAttribute('data-tb-filter');
            const active = (cat === 'all' && filters.size === 0) || filters.has(cat);
            btn.classList.toggle('tag-browser-chip-active', active);
        });
    },

    /**
     * Build the filtered list of tags based on current query + category
     * filters. Returns the full list (unpaginated) — pagination applied
     * by the renderer.
     */
    _filterTagBrowserResults() {
        if (!this._tagDb) return [];
        const q = (this._tagBrowserQuery || '').toLowerCase().trim();
        const filters = this._tagBrowserFilters;
        const hasCat = filters.size > 0;
        const { names } = this._tagDb;

        // Ranking: exact match → prefix → substring → alphabetical (within buckets)
        const exact = [];
        const prefix = [];
        const substring = [];
        const all = [];

        for (const entry of names) {
            if (hasCat && !filters.has(entry.tag.category)) continue;
            if (!q) {
                all.push(entry.tag);
            } else if (entry.lower === q) {
                exact.push(entry.tag);
            } else if (entry.lower.startsWith(q)) {
                prefix.push(entry.tag);
            } else if (entry.lower.includes(q)) {
                substring.push(entry.tag);
            }
        }

        // Category priority: fiction first (physical/acts/kink/meta), image last
        const catPriority = { physical: 0, acts: 1, kink: 2, meta: 3, image: 4 };
        const sortByCatThenName = (a, b) => {
            const pa = catPriority[a.category] ?? 99;
            const pb = catPriority[b.category] ?? 99;
            if (pa !== pb) return pa - pb;
            return a.name.localeCompare(b.name);
        };

        if (!q) {
            all.sort(sortByCatThenName);
            return all;
        }
        // Bias each ranking bucket toward fiction first
        exact.sort(sortByCatThenName);
        prefix.sort(sortByCatThenName);
        substring.sort(sortByCatThenName);
        return [...exact, ...prefix, ...substring];
    },

    _renderTagBrowserResults() {
        const host = document.getElementById('tag-browser-results');
        const loadMoreWrap = document.getElementById('tag-browser-loadmore-wrap');
        if (!host) return;

        const all = this._filterTagBrowserResults();
        const pageSize = this._TAG_BROWSER_PAGE_SIZE;
        const limit = pageSize * this._tagBrowserPage;
        const shown = all.slice(0, limit);

        if (!shown.length) {
            const q = (this._tagBrowserQuery || '').trim();
            host.innerHTML = `<div class="tag-browser-empty">No tags match${q ? ` "${this._escape(q)}"` : ''}.</div>`;
            if (loadMoreWrap) loadMoreWrap.innerHTML = '';
            this._updateTagBrowserFooter(all.length);
            return;
        }

        const platform = this._activeTagPlatform;
        const platformTags = (this.metadata.tags[platform] || []).map(t => t.toLowerCase());
        const platformTagSet = new Set(platformTags);

        const cards = shown.map(t => {
            // A tag counts as "added" to the current platform if its name (or
            // platform-transformed name) is in the platform's list.
            const canonical = t.name;
            const transformed = this._transformTagForPlatform(canonical, platform).toLowerCase();
            const isAdded = platformTagSet.has(canonical.toLowerCase()) || platformTagSet.has(transformed);
            const addedCls = isAdded ? ' tag-browser-card-added' : '';
            const btnLabel = isAdded ? '&#10003; Added' : '+ Add';
            const btnCls = isAdded ? 'tag-browser-card-btn tag-browser-card-btn-added' : 'tag-browser-card-btn';
            const desc = t.desc ? `<div class="tag-browser-card-desc">${this._escape(t.desc)}</div>` : '';
            return `
                <div class="tag-browser-card${addedCls}" data-tb-tag="${this._escape(canonical)}">
                    <div class="tag-browser-card-head">
                        <div class="tag-browser-card-name">${this._escape(canonical)}</div>
                        <span class="tag-browser-card-cat metadata-tag-cat-${this._escape(t.category)}">${this._escape(t.category)}</span>
                    </div>
                    ${desc}
                    <div class="tag-browser-card-footer">
                        <button type="button" class="${btnCls}" data-tb-toggle="${this._escape(canonical)}">${btnLabel}</button>
                    </div>
                </div>
            `;
        }).join('');

        host.innerHTML = cards;

        // "Load more" button
        if (loadMoreWrap) {
            if (all.length > shown.length) {
                loadMoreWrap.innerHTML = `
                    <button type="button" class="btn btn-sm btn-outline tag-browser-loadmore" data-tb-loadmore>
                        Load ${Math.min(pageSize, all.length - shown.length)} more (${shown.length} of ${all.length})
                    </button>
                `;
                const btn = loadMoreWrap.querySelector('[data-tb-loadmore]');
                if (btn) {
                    btn.addEventListener('click', () => {
                        this._tagBrowserPage += 1;
                        this._renderTagBrowserResults();
                    });
                }
            } else {
                loadMoreWrap.innerHTML = '';
            }
        }

        // Wire card interactions — click card or button toggles add/remove
        host.querySelectorAll('[data-tb-tag]').forEach(card => {
            const tagName = card.getAttribute('data-tb-tag');
            card.addEventListener('click', (e) => {
                // Ignore clicks on the button directly — button has its own
                // handler to avoid a double-fire. Matching [data-tb-toggle]
                // ancestor catches clicks on text inside the button too.
                if (e.target.closest('[data-tb-toggle]')) return;
                this._tagBrowserToggleTag(tagName);
            });
        });
        host.querySelectorAll('[data-tb-toggle]').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.preventDefault();
                e.stopPropagation();
                const tagName = btn.getAttribute('data-tb-toggle');
                this._tagBrowserToggleTag(tagName);
            });
        });

        this._updateTagBrowserFooter(all.length);
    },

    _tagBrowserToggleTag(canonicalName) {
        const platform = this._activeTagPlatform;
        const tags = this.metadata.tags[platform] || [];
        const transformed = this._transformTagForPlatform(canonicalName, platform);
        const lcTransformed = transformed.toLowerCase();
        const lcCanonical = canonicalName.toLowerCase();

        // Find existing entry matching either canonical or transformed name
        const idx = tags.findIndex(t => {
            const lc = t.toLowerCase();
            return lc === lcCanonical || lc === lcTransformed;
        });

        if (idx >= 0) {
            // Route through the shared removal path so default→platform
            // cascade semantics stay identical to the inline dropdown.
            this._removeTagFromPlatformSilent(platform, idx);
        } else {
            this._addTagToPlatformSilent(platform, canonicalName);
        }

        // Re-render just the grid + selected strip + footer (no full
        // drawer rebuild — that would kick focus back to the drawer input).
        this._renderTagBrowserResults();
        this._updateTagBrowserSelectedStrip();
        this._updateTagBrowserFooter();
    },

    /**
     * Mutation wrappers that mirror _addTagToPlatform / _removeTagFromPlatform
     * but DON'T rerender the drawer tag body (that happens lazily on close,
     * to avoid stealing focus from the browser modal).
     */
    _addTagToPlatformSilent(platform, rawName) {
        const name = (rawName || '').trim();
        if (!name) return;
        const tags = this.metadata.tags[platform] || [];
        if (tags.some(t => t.toLowerCase() === name.toLowerCase())) return;

        let final = name;
        if (this._tagDb) {
            const alias = this._tagDb.aliases[name.toLowerCase()];
            if (alias && this._tagDb.byName.has(alias)) {
                if (tags.some(t => t.toLowerCase() === alias.toLowerCase())) return;
                final = alias;
            }
        }

        tags.push(final);
        this.metadata.tags[platform] = tags;

        if (platform === 'default') {
            for (const p of this.TAG_PLATFORMS) {
                if (p === 'default') continue;
                const transformed = this._transformTagForPlatform(final, p);
                const otherTags = this.metadata.tags[p] || [];
                if (!otherTags.some(t => t.toLowerCase() === transformed.toLowerCase())) {
                    otherTags.push(transformed);
                    this.metadata.tags[p] = otherTags;
                }
            }
        }
        this._clearStatus();
    },

    _removeTagFromPlatformSilent(platform, index) {
        const tags = this.metadata.tags[platform] || [];
        if (index < 0 || index >= tags.length) return;
        const removed = tags[index];
        tags.splice(index, 1);
        this.metadata.tags[platform] = tags;

        if (platform === 'default') {
            for (const p of this.TAG_PLATFORMS) {
                if (p === 'default') continue;
                const transformed = this._transformTagForPlatform(removed, p);
                const otherTags = this.metadata.tags[p] || [];
                const idx = otherTags.findIndex(t => t.toLowerCase() === transformed.toLowerCase());
                if (idx >= 0) {
                    otherTags.splice(idx, 1);
                    this.metadata.tags[p] = otherTags;
                }
            }
        }
        this._clearStatus();
    },

    _updateTagBrowserFilterCounts() {
        const root = document.getElementById('tag-browser-root');
        if (!root || !this._tagDb) return;
        const q = (this._tagBrowserQuery || '').toLowerCase().trim();
        const counts = { all: 0, physical: 0, acts: 0, kink: 0, meta: 0, image: 0 };
        for (const entry of this._tagDb.names) {
            if (q && !entry.lower.includes(q)) continue;
            counts.all += 1;
            if (counts[entry.tag.category] !== undefined) counts[entry.tag.category] += 1;
        }
        root.querySelectorAll('[data-tb-count]').forEach(el => {
            const cat = el.getAttribute('data-tb-count');
            const n = counts[cat] || 0;
            el.textContent = `(${n.toLocaleString()})`;
        });
    },

    _updateTagBrowserSelectedStrip() {
        const host = document.getElementById('tag-browser-selected');
        if (!host) return;
        const platform = this._activeTagPlatform;
        const tags = this.metadata.tags[platform] || [];
        if (!tags.length) {
            host.innerHTML = `<div class="tag-browser-selected-empty">No tags on ${this._escape(this.PLATFORM_LABELS[platform] || platform)} yet.</div>`;
            return;
        }
        const pills = tags.map((t, i) => `
            <span class="tag-browser-selected-pill" data-tb-selected-index="${i}">
                <span>${this._escape(t)}</span>
                <button type="button" class="tag-browser-selected-remove" data-tb-remove-selected="${i}" aria-label="Remove">&times;</button>
            </span>
        `).join('');
        host.innerHTML = `
            <div class="tag-browser-selected-label">On ${this._escape(this.PLATFORM_LABELS[platform] || platform)}:</div>
            <div class="tag-browser-selected-pills">${pills}</div>
        `;
        host.querySelectorAll('[data-tb-remove-selected]').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.preventDefault();
                const idx = parseInt(btn.getAttribute('data-tb-remove-selected'), 10);
                if (Number.isNaN(idx)) return;
                this._removeTagFromPlatformSilent(platform, idx);
                this._renderTagBrowserResults();
                this._updateTagBrowserSelectedStrip();
                this._updateTagBrowserFooter();
            });
        });
    },

    _updateTagBrowserFooter(totalMatches) {
        const el = document.getElementById('tag-browser-count');
        if (!el) return;
        const platform = this._activeTagPlatform;
        const count = (this.metadata.tags[platform] || []).length;
        const limit = this.TAG_LIMITS[platform];
        const limitLabel = (limit === Infinity) ? '\u221E' : limit;
        const overLimit = (limit !== Infinity) && count > limit;
        const matchFrag = (typeof totalMatches === 'number') ? ` &middot; ${totalMatches.toLocaleString()} matches` : '';
        el.innerHTML = `<span class="${overLimit ? 'tag-browser-count-over' : ''}">Selected: ${count} &middot; Platform max: ${this._escape(String(limitLabel))}</span>${matchFrag}`;
    },

    // ---------------------------------------------------------------------
    // Section 5: Platform Toggles
    // ---------------------------------------------------------------------

    _renderPlatformTogglesSection() {
        const md = this.metadata;

        const rows = this.PLATFORMS.map(p => {
            const checked = md.platforms[p] ? ' checked' : '';
            const id = `meta-platform-${p}`;
            return `
                <label class="metadata-checkbox" for="${id}">
                    <input type="checkbox" id="${id}" data-platform-toggle="${this._escape(p)}"${checked} />
                    <span>${this._escape(this.PLATFORM_LABELS[p] || p)}</span>
                </label>
            `;
        }).join('');

        return `
            <section class="metadata-section" data-section="platforms" data-expanded="false">
                <button type="button" class="metadata-section-header" data-section-toggle="platforms">
                    <span class="metadata-section-chevron">&#9654;</span>
                    <span>Platform Toggles</span>
                </button>
                <div class="metadata-section-body">
                    <div class="metadata-checkbox-list">
                        ${rows}
                    </div>
                </div>
            </section>
        `;
    },

    // ---------------------------------------------------------------------
    // Pill input component (characters, relationships, etc.)
    // ---------------------------------------------------------------------

    /**
     * Render a tag-pill input. Pills come first, then an input field that
     * grows to fill the rest of the row.
     *
     * @param {string} fieldName  Metadata key (e.g. 'characters') that holds
     *                            the backing array on this.metadata.
     * @param {string[]} values   Current pill values to prerender.
     * @param {string} placeholder  Placeholder text for the free-text input.
     */
    _renderPillInput(fieldName, values, placeholder) {
        const pills = (values || []).map((v, i) => `
            <span class="metadata-pill" data-pill-index="${i}">
                <span class="metadata-pill-text">${this._escape(v)}</span>
                <button type="button" class="metadata-pill-remove" data-pill-remove="${this._escape(fieldName)}" data-index="${i}" aria-label="Remove">&times;</button>
            </span>
        `).join('');

        const inputId = `meta-${fieldName}-input`;
        return `
            <div class="metadata-pill-input" data-pill-field="${this._escape(fieldName)}">
                <div class="metadata-pill-list" data-pill-list="${this._escape(fieldName)}">${pills}</div>
                <input type="text" id="${inputId}" class="metadata-pill-entry" data-pill-entry="${this._escape(fieldName)}" placeholder="${this._escape(placeholder || '')}" autocomplete="off" />
            </div>
        `;
    },

    /**
     * Re-render pill list for a given field without rebuilding the whole
     * form. Called after any pill add/remove.
     */
    _refreshPillList(fieldName) {
        const list = document.querySelector(`[data-pill-list="${fieldName}"]`);
        if (!list) return;
        const values = this.metadata[fieldName] || [];
        list.innerHTML = values.map((v, i) => `
            <span class="metadata-pill" data-pill-index="${i}">
                <span class="metadata-pill-text">${this._escape(v)}</span>
                <button type="button" class="metadata-pill-remove" data-pill-remove="${this._escape(fieldName)}" data-index="${i}" aria-label="Remove">&times;</button>
            </span>
        `).join('');
        this._bindPillRemoveButtons(fieldName);
    },

    _bindPillRemoveButtons(fieldName) {
        document.querySelectorAll(`[data-pill-remove="${fieldName}"]`).forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.preventDefault();
                const idx = parseInt(btn.getAttribute('data-index'), 10);
                if (Number.isNaN(idx)) return;
                const arr = this.metadata[fieldName] || [];
                arr.splice(idx, 1);
                this.metadata[fieldName] = arr;
                this._refreshPillList(fieldName);
                this._clearStatus();
            });
        });
    },

    _addPill(fieldName, value) {
        const trimmed = (value || '').trim();
        if (!trimmed) return;
        const arr = this.metadata[fieldName] || [];
        // Prevent exact duplicates (case-insensitive)
        const exists = arr.some(v => v.toLowerCase() === trimmed.toLowerCase());
        if (exists) return;
        arr.push(trimmed);
        this.metadata[fieldName] = arr;
        this._refreshPillList(fieldName);
        this._clearStatus();
    },

    _initFormBindings() {
        // Section accordion toggles
        document.querySelectorAll('[data-section-toggle]').forEach(btn => {
            btn.addEventListener('click', () => {
                const key = btn.getAttribute('data-section-toggle');
                const section = document.querySelector(`[data-section="${key}"]`);
                if (!section) return;
                const expanded = section.getAttribute('data-expanded') === 'true';
                section.setAttribute('data-expanded', expanded ? 'false' : 'true');
                const chev = btn.querySelector('.metadata-section-chevron');
                if (chev) chev.innerHTML = expanded ? '&#9654;' : '&#9660;';
            });
        });

        // Field inputs — live-update this.metadata + counters
        document.querySelectorAll('[data-field]').forEach(el => {
            const field = el.getAttribute('data-field');
            el.addEventListener('input', () => {
                this.metadata[field] = el.value;
                this._clearStatus();
                // Refresh counters for description/summary
                if (field === 'description') {
                    this._updateCharCounter('meta-description', 'meta-desc-counter', this.DESC_MAX);
                } else if (field === 'summary') {
                    this._updateCharCounter('meta-summary', 'meta-summary-counter', this.SUMMARY_MAX);
                }
                // Update drawer subtitle if title changes
                if (field === 'title') {
                    const sub = document.getElementById('metadata-drawer-subtitle');
                    if (sub) sub.textContent = el.value || this.storyName;
                }
            });
            el.addEventListener('change', () => {
                this.metadata[field] = el.value;
            });
        });

        // Classifications — warning/category checkboxes
        document.querySelectorAll('[data-classification]').forEach(cb => {
            cb.addEventListener('change', () => {
                const kind = cb.getAttribute('data-classification');
                const value = cb.value;
                const key = kind === 'warning' ? 'warnings' : 'categories';
                const arr = this.metadata[key] || [];
                const idx = arr.indexOf(value);
                if (cb.checked && idx === -1) arr.push(value);
                else if (!cb.checked && idx !== -1) arr.splice(idx, 1);
                this.metadata[key] = arr;
                this._clearStatus();
                // Clear warnings error banner once user picks anything
                if (key === 'warnings') {
                    const errEl = document.getElementById('meta-error-warnings');
                    if (errEl) errEl.textContent = '';
                }
            });
        });

        // Pill inputs — bind entry fields + existing remove buttons
        document.querySelectorAll('[data-pill-entry]').forEach(input => {
            const field = input.getAttribute('data-pill-entry');
            input.addEventListener('keydown', (e) => {
                if (e.key === 'Enter' || e.key === ',') {
                    e.preventDefault();
                    this._addPill(field, input.value);
                    input.value = '';
                } else if (e.key === 'Backspace' && input.value === '') {
                    // Remove last pill on backspace-in-empty
                    const arr = this.metadata[field] || [];
                    if (arr.length) {
                        arr.pop();
                        this.metadata[field] = arr;
                        this._refreshPillList(field);
                        this._clearStatus();
                    }
                }
            });
            input.addEventListener('blur', () => {
                // Convert any pending text on blur so nothing is silently lost
                if (input.value.trim()) {
                    this._addPill(field, input.value);
                    input.value = '';
                }
            });
        });
        // Bind remove buttons for each pill field currently on screen
        const pillFields = new Set();
        document.querySelectorAll('[data-pill-remove]').forEach(btn => {
            pillFields.add(btn.getAttribute('data-pill-remove'));
        });
        pillFields.forEach(f => this._bindPillRemoveButtons(f));

        // Per-platform tag tabs (Phase 3a)
        document.querySelectorAll('[data-tag-tab]').forEach(btn => {
            btn.addEventListener('click', () => {
                const p = btn.getAttribute('data-tag-tab');
                if (p === this._activeTagPlatform) return;
                this._activeTagPlatform = p;
                this._closeDropdown();
                this._updateTagTabs();
                this._rerenderTagTabBody();
            });
        });
        // Initial tag body bindings (pills + input for active tab)
        this._bindTagTabBodyEvents();

        // Platform toggle checkboxes
        document.querySelectorAll('[data-platform-toggle]').forEach(cb => {
            cb.addEventListener('change', () => {
                const p = cb.getAttribute('data-platform-toggle');
                this.metadata.platforms[p] = cb.checked;
                this._clearStatus();
            });
        });
    },

    _updateCharCounter(inputId, counterId, max) {
        const input = document.getElementById(inputId);
        const counter = document.getElementById(counterId);
        if (!input || !counter) return;
        const len = (input.value || '').length;
        counter.textContent = `${len}/${max}`;
        counter.classList.toggle('metadata-char-counter-over', len > max);
    },

    // ---------------------------------------------------------------------
    // Validation
    // ---------------------------------------------------------------------

    _validate() {
        const errors = [];
        // Clear previous errors
        document.querySelectorAll('.metadata-error').forEach(el => { el.textContent = ''; });

        const title = (this.metadata.title || '').trim();
        if (!title) {
            errors.push({ field: 'title', msg: 'Title is required.' });
        }

        const rating = this.metadata.rating;
        if (rating && rating !== '') {
            const valid = this.RATINGS.some(r => r.toLowerCase() === rating.toString().toLowerCase());
            if (!valid) {
                errors.push({ field: 'rating', msg: `Rating must be one of: ${this.RATINGS.join(', ')}` });
            }
        }

        // Tier 1: at least one archive warning required (AO3 standard)
        const warnings = Array.isArray(this.metadata.warnings) ? this.metadata.warnings : [];
        if (warnings.length === 0) {
            errors.push({ field: 'warnings', msg: 'Select at least one archive warning (AO3 standard).' });
            // Also auto-expand the Classifications section so user can see it
            const sec = document.querySelector('[data-section="classifications"]');
            if (sec && sec.getAttribute('data-expanded') !== 'true') {
                sec.setAttribute('data-expanded', 'true');
                const chev = sec.querySelector('.metadata-section-chevron');
                if (chev) chev.innerHTML = '&#9660;';
            }
        }

        // Render errors inline
        errors.forEach(e => {
            const el = document.getElementById(`meta-error-${e.field}`);
            if (el) el.textContent = e.msg;
        });

        return errors;
    },

    // ---------------------------------------------------------------------
    // Save
    // ---------------------------------------------------------------------

    async save() {
        const errors = this._validate();
        if (errors.length) {
            // Scroll to first errored field (or the error banner if the
            // field is a checkbox group like warnings with no single input)
            const firstField = errors[0].field;
            let target = document.getElementById(`meta-${firstField}`);
            if (!target) {
                target = document.getElementById(`meta-error-${firstField}`)
                    || document.getElementById(`meta-${firstField}-list`);
            }
            if (target) {
                if (typeof target.focus === 'function') target.focus();
                target.scrollIntoView({ behavior: 'smooth', block: 'center' });
            }
            this._setStatus('Fix errors before saving', 'error');
            return;
        }

        this._setStatus('Saving...', 'info');
        try {
            const resp = await fetch(`/api/editor/stories/${encodeURIComponent(this.storyName)}/metadata`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    metadata: this.metadata,
                    expected_mtime: this.lastMtime,
                }),
            });
            if (resp.status === 409) {
                if (confirm('Story metadata changed externally — reload?')) {
                    await this._loadMetadata();
                    this._renderForm();
                    this._initFormBindings();
                    this._setStatus('Reloaded', 'info');
                } else {
                    this._setStatus('Save aborted (conflict)', 'error');
                }
                return;
            }
            if (!resp.ok) {
                const txt = await resp.text();
                this._setStatus(`Save failed: ${txt}`, 'error');
                return;
            }
            const data = await resp.json();
            this.lastMtime = data.last_modified || this.lastMtime;
            // Snapshot new clean state
            this.initialMetadata = JSON.parse(JSON.stringify(this.metadata));
            this._setStatus('Saved', 'ok');
        } catch (err) {
            this._setStatus(`Save failed: ${err.message || err}`, 'error');
        }
    },

    _setStatus(msg, kind) {
        const el = document.getElementById('metadata-drawer-status');
        if (!el) return;
        el.textContent = msg;
        el.className = 'metadata-drawer-status';
        if (kind) el.classList.add(`metadata-drawer-status-${kind}`);
    },

    _clearStatus() {
        const el = document.getElementById('metadata-drawer-status');
        if (el && el.classList.contains('metadata-drawer-status-ok')) {
            // Clear "Saved" once user starts editing again
            el.textContent = '';
            el.className = 'metadata-drawer-status';
        }
    },

    // ---------------------------------------------------------------------
    // Dirty check
    // ---------------------------------------------------------------------

    _isDirty() {
        if (!this.metadata || !this.initialMetadata) return false;
        try {
            return JSON.stringify(this.metadata) !== JSON.stringify(this.initialMetadata);
        } catch (_) {
            return false;
        }
    },

    // ---------------------------------------------------------------------
    // Helpers
    // ---------------------------------------------------------------------

    _escape(s) {
        if (s === null || s === undefined) return '';
        return String(s)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    },
};

// Expose globally so editor.js (and users) can reach it
window.MetaEditor = MetaEditor;
