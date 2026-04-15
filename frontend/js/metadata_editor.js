/**
 * Metadata Editor — slide-in drawer for editing story.json metadata.
 *
 * Phase 1 scope:
 *   - Story Info (title, author, fandom, rating)
 *   - Description & Summary (with character counters)
 *
 * Later phases will add: classifications (warnings/categories/characters/
 * relationships), per-chapter editing, tag autocomplete, cover uploads,
 * platform toggles, and raw JSON view.
 */
const MetaEditor = {
    // State
    isOpen: false,
    metadata: null,           // current loaded story.json
    initialMetadata: null,    // snapshot for dirty check
    lastMtime: 0,
    storyName: null,

    // Canonical ratings (must match backend whitelist)
    RATINGS: [
        'Not Rated',
        'General Audiences',
        'Teen And Up Audiences',
        'Mature',
        'Explicit',
    ],

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
        `;

        this._updateCharCounter('meta-description', 'meta-desc-counter', this.DESC_MAX);
        this._updateCharCounter('meta-summary', 'meta-summary-counter', this.SUMMARY_MAX);
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
            // Scroll to first errored field
            const first = document.getElementById(`meta-${errors[0].field}`);
            if (first) {
                first.focus();
                first.scrollIntoView({ behavior: 'smooth', block: 'center' });
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
