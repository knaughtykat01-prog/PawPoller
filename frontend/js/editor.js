/**
 * Story Editor — edit MASTER.md with live format preview.
 *
 * Phase 1: textarea editor + live Clean HTML preview + save + regenerate.
 * Future phases add CodeMirror, format tabs, theme editor, platform push.
 */
const Editor = {
    // State
    storyName: null,
    lastSavedContent: '',
    lastMtime: 0,
    previewFormat: 'clean_html',
    previewDebounceTimer: null,
    previewRequestId: 0,
    isDirty: false,
    chapters: [],
    _syncingScroll: false,  // prevents scroll event loops

    // ---------------------------------------------------------------------------
    // Story list page
    // ---------------------------------------------------------------------------

    async renderStoryList() {
        App._setContent('<div class="loading-spinner">Loading stories...</div>');
        try {
            const resp = await fetch('/api/editor/stories');
            const data = await resp.json();
            const stories = data.stories || [];

            const cards = stories.map(s => {
                const wc = s.word_count ? `${(s.word_count / 1000).toFixed(1)}K words` : 'no word count';
                const ch = s.chapters ? `${s.chapters} ch` : '';
                const hasMaster = s.has_master ? '' : '<span style="color:var(--color-error)">No MASTER.md</span>';
                return `
                    <a href="#/editor/${s.name}" class="stat-card" style="text-decoration:none;color:inherit;cursor:pointer">
                        <h4>${Utils.escapeHtml(s.title)}</h4>
                        <p style="color:var(--text-secondary);font-size:0.85rem">${wc}${ch ? ' · ' + ch : ''} ${hasMaster}</p>
                    </a>`;
            }).join('');

            App._setContent(`
                <div class="page-header">
                    <h2>Story Editor</h2>
                    <p class="subtitle">Select a story to edit MASTER.md and preview in all formats</p>
                </div>
                <div class="card-grid">${cards || '<p>No stories found in the archive.</p>'}</div>
            `);
        } catch (err) {
            App._setContent(`<div class="empty-state"><h3>Error loading stories</h3><p>${err.message}</p></div>`);
        }
    },

    // ---------------------------------------------------------------------------
    // Editor page
    // ---------------------------------------------------------------------------

    async renderEditor(storyName) {
        this.storyName = storyName;
        this.isDirty = false;

        App._setContent(`
            <div class="editor-container">
                <div class="editor-toolbar">
                    <a href="#/editor" class="editor-back">← Stories</a>
                    <span class="editor-title" id="editor-title">${Utils.escapeHtml(storyName.replace(/_/g, ' '))}</span>
                    <div class="editor-actions">
                        <span id="editor-status" class="editor-status"></span>
                        <span id="editor-wordcount" class="editor-wordcount"></span>
                        <button id="editor-save-btn" class="btn btn-sm" onclick="Editor.save()">Save</button>
                        <button id="editor-regen-btn" class="btn btn-sm btn-outline" onclick="Editor.regenerate()">Regenerate</button>
                        <select id="editor-format-select">
                            <option value="clean_html">Clean HTML</option>
                            <option value="bbcode">BBCode</option>
                        </select>
                    </div>
                </div>
                <div class="editor-split">
                    <div class="editor-pane">
                        <textarea id="editor-textarea" spellcheck="true" placeholder="Loading..."></textarea>
                    </div>
                    <div class="editor-divider" id="editor-divider"></div>
                    <div class="editor-preview-col" id="editor-preview">
                        <div class="editor-preview-panel" id="editor-preview-rendered">
                            <div class="preview-panel-header">Rendered Preview</div>
                            <div class="preview-panel-body" id="editor-preview-rendered-body">
                                <p style="color:var(--text-secondary)">Loading...</p>
                            </div>
                        </div>
                        <div class="editor-preview-panel" id="editor-preview-source-panel">
                            <div class="preview-panel-header" id="editor-source-header">Clean HTML output</div>
                            <div class="preview-panel-body" id="editor-preview-source-body">
                                <p style="color:var(--text-secondary)">Loading...</p>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        `);

        // Load content
        try {
            const resp = await fetch(`/api/editor/stories/${encodeURIComponent(storyName)}/content`);
            if (!resp.ok) throw new Error(await resp.text());
            const data = await resp.json();

            const ta = document.getElementById('editor-textarea');
            ta.value = data.content;
            ta.placeholder = '';
            this.lastSavedContent = data.content;
            this.lastMtime = data.last_modified;
            this.chapters = data.chapters || [];
            this._updateWordCount(data.word_count);
            this._updateStatus('Loaded');

            // Bind events
            const formatSelect = document.getElementById('editor-format-select');
            if (formatSelect) {
                formatSelect.addEventListener('change', (e) => {
                    this.switchFormat(e.target.value);
                });
            }
            ta.addEventListener('input', () => this._onInput());
            ta.addEventListener('keydown', (e) => {
                if ((e.ctrlKey || e.metaKey) && e.key === 's') {
                    e.preventDefault();
                    this.save();
                }
                // Tab inserts spaces
                if (e.key === 'Tab') {
                    e.preventDefault();
                    const start = ta.selectionStart;
                    ta.value = ta.value.substring(0, start) + '  ' + ta.value.substring(ta.selectionEnd);
                    ta.selectionStart = ta.selectionEnd = start + 2;
                    this._onInput();
                }
            });

            // Beforeunload warning
            window.addEventListener('beforeunload', (e) => {
                if (this.isDirty) {
                    e.preventDefault();
                    e.returnValue = '';
                }
            });

            // Sync scrolling between editor and both preview panel bodies
            const renderedPanel = document.getElementById('editor-preview-rendered-body');
            const sourcePanel = document.getElementById('editor-preview-source-body');
            const syncTargets = [renderedPanel, sourcePanel].filter(Boolean);

            ta.addEventListener('scroll', () => {
                if (this._syncingScroll) return;
                this._syncingScroll = true;
                const pct = ta.scrollTop / (ta.scrollHeight - ta.clientHeight || 1);
                syncTargets.forEach(el => {
                    el.scrollTop = pct * (el.scrollHeight - el.clientHeight);
                });
                requestAnimationFrame(() => { this._syncingScroll = false; });
            });
            syncTargets.forEach(panel => {
                panel.addEventListener('scroll', () => {
                    if (this._syncingScroll) return;
                    this._syncingScroll = true;
                    const pct = panel.scrollTop / (panel.scrollHeight - panel.clientHeight || 1);
                    ta.scrollTop = pct * (ta.scrollHeight - ta.clientHeight);
                    syncTargets.filter(el => el !== panel).forEach(el => {
                        el.scrollTop = pct * (el.scrollHeight - el.clientHeight);
                    });
                    requestAnimationFrame(() => { this._syncingScroll = false; });
                });
            });

            // Initial preview
            this._requestPreview();

            // Setup divider drag
            this._setupDivider();

        } catch (err) {
            document.getElementById('editor-textarea').value = `Error loading: ${err.message}`;
        }
    },

    // ---------------------------------------------------------------------------
    // Input handling
    // ---------------------------------------------------------------------------

    _onInput() {
        const ta = document.getElementById('editor-textarea');
        if (!ta) return;

        this.isDirty = ta.value !== this.lastSavedContent;
        this._updateStatus(this.isDirty ? 'Unsaved changes' : 'Saved');
        this._updateWordCount(ta.value.split(/\s+/).filter(Boolean).length);

        // Debounced preview
        clearTimeout(this.previewDebounceTimer);
        this.previewDebounceTimer = setTimeout(() => this._requestPreview(), 400);
    },

    // ---------------------------------------------------------------------------
    // Preview
    // ---------------------------------------------------------------------------

    async _requestPreview() {
        const ta = document.getElementById('editor-textarea');
        const renderedBody = document.getElementById('editor-preview-rendered-body');
        const sourceBody = document.getElementById('editor-preview-source-body');
        const sourceHeader = document.getElementById('editor-source-header');
        if (!ta || !renderedBody || !sourceBody) return;

        let content = ta.value;
        const MAX_PREVIEW = 100000;
        if (content.length > MAX_PREVIEW) {
            content = content.substring(0, MAX_PREVIEW) + '\n\n[... truncated for preview ...]';
        }

        const thisRequestId = ++this.previewRequestId;

        try {
            renderedBody.style.opacity = '0.6';
            sourceBody.style.opacity = '0.6';

            // Fire both requests in parallel: rendered (always clean_html) + source format
            const [renderedResp, sourceResp] = await Promise.all([
                fetch(`/api/editor/stories/${encodeURIComponent(this.storyName)}/preview`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ content, format: 'clean_html' }),
                }),
                fetch(`/api/editor/stories/${encodeURIComponent(this.storyName)}/preview`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ content, format: this.previewFormat }),
                }),
            ]);

            if (thisRequestId !== this.previewRequestId) return;

            // Rendered preview (always HTML, displayed as formatted text)
            if (renderedResp.ok) {
                const renderedData = await renderedResp.json();
                renderedBody.innerHTML = '<div class="preview-html">' + (renderedData.html || '') + '</div>';
            } else {
                renderedBody.innerHTML = `<p style="color:var(--color-error)">Render failed (${renderedResp.status})</p>`;
            }

            // Source output (raw tags visible)
            if (sourceResp.ok) {
                const sourceData = await sourceResp.json();
                const raw = sourceData.html || '(empty)';
                const escaped = raw.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
                const label = sourceData.format === 'bbcode' ? 'BBCode' : 'Clean HTML';
                if (sourceHeader) sourceHeader.textContent = `${label} output (${raw.length.toLocaleString()} bytes)`;
                sourceBody.innerHTML = `<pre class="preview-source">${escaped}</pre>`;
            } else {
                sourceBody.innerHTML = `<p style="color:var(--color-error)">Source failed (${sourceResp.status})</p>`;
            }

            renderedBody.style.opacity = '1';
            sourceBody.style.opacity = '1';
        } catch (err) {
            renderedBody.innerHTML = `<p style="color:var(--color-error)">Error: ${err.message}</p>`;
            sourceBody.innerHTML = '';
            renderedBody.style.opacity = '1';
            sourceBody.style.opacity = '1';
        }
    },

    switchFormat(fmt) {
        console.log('[Editor] switchFormat called:', fmt);
        this.previewFormat = fmt;
        // Cancel any pending debounce so it doesn't overwrite with stale format
        clearTimeout(this.previewDebounceTimer);
        this._requestPreview();
    },

    _bbcodeToHtml(bbcode) {
        // Minimal BBCode→HTML for preview rendering
        let html = Utils.escapeHtml(bbcode);
        html = html.replace(/\[b\](.*?)\[\/b\]/gs, '<strong>$1</strong>');
        html = html.replace(/\[i\](.*?)\[\/i\]/gs, '<em>$1</em>');
        html = html.replace(/\[center\](.*?)\[\/center\]/gs, '<div style="text-align:center">$1</div>');
        html = html.replace(/\[color=(.*?)\](.*?)\[\/color\]/gs, '<span style="color:$1">$2</span>');
        html = html.replace(/\[right\](.*?)\[\/right\]/gs, '<div style="text-align:right">$1</div>');
        html = html.replace(/\[left\](.*?)\[\/left\]/gs, '<div style="text-align:left">$1</div>');
        html = html.replace(/\[t\](.*?)\[\/t\]/gs, '<h2 style="text-align:center">$1</h2>');
        // Line breaks
        html = html.replace(/\n/g, '<br>');
        return html;
    },

    // ---------------------------------------------------------------------------
    // Save
    // ---------------------------------------------------------------------------

    async save() {
        const ta = document.getElementById('editor-textarea');
        if (!ta) return;

        this._updateStatus('Saving...');
        try {
            const resp = await fetch(`/api/editor/stories/${encodeURIComponent(this.storyName)}/content`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    content: ta.value,
                    expected_mtime: this.lastMtime,
                }),
            });

            if (resp.status === 409) {
                this._updateStatus('Conflict! File changed externally. Reload to merge.');
                return;
            }

            const data = await resp.json();
            if (data.ok) {
                this.lastSavedContent = ta.value;
                this.lastMtime = data.last_modified;
                this.isDirty = false;
                this._updateStatus('Saved');
                this._updateWordCount(data.word_count);
            } else {
                this._updateStatus('Save failed');
            }
        } catch (err) {
            this._updateStatus(`Save error: ${err.message}`);
        }
    },

    // ---------------------------------------------------------------------------
    // Regenerate
    // ---------------------------------------------------------------------------

    async regenerate() {
        const btn = document.getElementById('editor-regen-btn');
        if (btn) btn.disabled = true;

        // Save first if dirty
        if (this.isDirty) {
            await this.save();
        }

        this._updateStatus('Regenerating...');
        try {
            const resp = await fetch(`/api/editor/stories/${encodeURIComponent(this.storyName)}/regenerate`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ skip_pdf: true }),
            });
            const data = await resp.json();

            if (data.ok) {
                const summary = data.results.join(', ');
                this._updateStatus(`Regenerated: ${summary}`);
            } else {
                this._updateStatus(`Regen errors: ${(data.errors || []).join(', ')}`);
            }
        } catch (err) {
            this._updateStatus(`Regen error: ${err.message}`);
        } finally {
            if (btn) btn.disabled = false;
        }
    },

    // ---------------------------------------------------------------------------
    // UI helpers
    // ---------------------------------------------------------------------------

    _updateStatus(text) {
        const el = document.getElementById('editor-status');
        if (el) el.textContent = text;
    },

    _updateWordCount(count) {
        const el = document.getElementById('editor-wordcount');
        if (el) el.textContent = `${(count || 0).toLocaleString()} words`;
    },

    _setupDivider() {
        const divider = document.getElementById('editor-divider');
        const container = document.querySelector('.editor-split');
        if (!divider || !container) return;

        let isDragging = false;
        divider.addEventListener('mousedown', (e) => {
            isDragging = true;
            e.preventDefault();
        });
        document.addEventListener('mousemove', (e) => {
            if (!isDragging) return;
            const rect = container.getBoundingClientRect();
            const pct = ((e.clientX - rect.left) / rect.width) * 100;
            const clamped = Math.min(80, Math.max(20, pct));
            container.style.gridTemplateColumns = `${clamped}% 4px ${100 - clamped}%`;
        });
        document.addEventListener('mouseup', () => { isDragging = false; });
    },
};
