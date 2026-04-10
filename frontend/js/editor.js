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
    slopScore: null,
    slopDebounceTimer: null,
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
                        <span id="editor-slop" class="editor-slop" title="Click to refresh slop score"></span>
                        <span id="editor-status" class="editor-status"></span>
                        <span id="editor-wordcount" class="editor-wordcount"></span>
                        <button id="editor-save-btn" class="btn btn-sm" onclick="Editor.save()">Save</button>
                        <button id="editor-css-btn" class="btn btn-sm btn-outline">CSS</button>
                        <button id="editor-regen-btn" class="btn btn-sm btn-outline" onclick="Editor.regenerate()">Regenerate</button>
                        <select id="editor-format-select">
                            <option value="clean_html">Clean HTML (AO3)</option>
                            <option value="sofurry_html">SoFurry HTML</option>
                            <option value="bbcode">BBCode (IB)</option>
                            <option value="styled_html">Styled HTML (PDF)</option>
                        </select>
                    </div>
                </div>
                <div class="editor-quad">
                    <div class="editor-quad-panel" id="panel-md-code">
                        <div class="preview-panel-header">Markdown Source</div>
                        <textarea id="editor-textarea" spellcheck="true" placeholder="Loading..."></textarea>
                    </div>
                    <div class="editor-quad-panel" id="panel-md-preview">
                        <div class="preview-panel-header">Markdown Preview</div>
                        <div class="preview-panel-body" id="editor-preview-rendered-body">
                            <p style="color:var(--text-secondary)">Loading...</p>
                        </div>
                    </div>
                    <div class="editor-quad-panel" id="panel-fmt-source">
                        <div class="preview-panel-header" id="editor-source-header">Format Source</div>
                        <div class="preview-panel-body" id="editor-preview-source-body">
                            <p style="color:var(--text-secondary)">Loading...</p>
                        </div>
                    </div>
                    <div class="editor-quad-panel" id="panel-fmt-preview">
                        <div class="preview-panel-header" id="editor-fmt-preview-header">Format Preview</div>
                        <div class="preview-panel-body" id="editor-preview-fmt-body">
                            <p style="color:var(--text-secondary)">Loading...</p>
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
            const cssBtn = document.getElementById('editor-css-btn');
            if (cssBtn) {
                cssBtn.addEventListener('click', () => this.toggleCssEditor());
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

            // Sync scrolling: MD code ↔ MD preview ↔ format preview (proportional)
            // Format source excluded from sync when styled_html (CSS preamble breaks mapping)
            const mdPanel = document.getElementById('editor-preview-rendered-body');
            const fmtSrcPanel = document.getElementById('editor-preview-source-body');
            const fmtPrvPanel = document.getElementById('editor-preview-fmt-body');

            const _doSync = (source, targets) => {
                if (this._syncingScroll) return;
                this._syncingScroll = true;
                const pct = source.scrollTop / (source.scrollHeight - source.clientHeight || 1);
                targets.forEach(el => {
                    if (el) el.scrollTop = pct * (el.scrollHeight - el.clientHeight);
                });
                requestAnimationFrame(() => { this._syncingScroll = false; });
            };

            // MD code syncs with MD preview + format preview (not format source for styled)
            ta.addEventListener('scroll', () => {
                const targets = [mdPanel];
                if (this.previewFormat !== 'styled_html') targets.push(fmtSrcPanel, fmtPrvPanel);
                _doSync(ta, targets.filter(Boolean));
            });
            // MD preview syncs back to editor + others
            if (mdPanel) mdPanel.addEventListener('scroll', () => {
                const targets = [ta];
                if (this.previewFormat !== 'styled_html') targets.push(fmtSrcPanel, fmtPrvPanel);
                _doSync(mdPanel, targets.filter(Boolean));
            });

            // Initial preview + slop score
            this._requestPreview();
            this._requestSlopScore();

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
        const mdPreview = document.getElementById('editor-preview-rendered-body');
        const fmtSource = document.getElementById('editor-preview-source-body');
        const fmtPreview = document.getElementById('editor-preview-fmt-body');
        const sourceHeader = document.getElementById('editor-source-header');
        const fmtPreviewHeader = document.getElementById('editor-fmt-preview-header');
        if (!ta || !mdPreview) return;

        let content = ta.value;
        const MAX_PREVIEW = 100000;
        if (content.length > MAX_PREVIEW) {
            content = content.substring(0, MAX_PREVIEW) + '\n\n[... truncated for preview ...]';
        }

        const thisRequestId = ++this.previewRequestId;
        const fmtLabels = { 'bbcode': 'BBCode', 'clean_html': 'Clean HTML', 'sofurry_html': 'SoFurry HTML', 'styled_html': 'Styled HTML' };

        try {
            [mdPreview, fmtSource, fmtPreview].forEach(el => { if (el) el.style.opacity = '0.6'; });

            // 2 parallel requests: MD preview (clean_html) + selected format
            const url = `/api/editor/stories/${encodeURIComponent(this.storyName)}/preview`;
            const [mdResp, fmtResp] = await Promise.all([
                fetch(url, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ content, format: 'clean_html' }),
                }),
                fetch(url, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ content, format: this.previewFormat }),
                }),
            ]);

            if (thisRequestId !== this.previewRequestId) return;

            // Parse responses once
            const mdData = mdResp.ok ? await mdResp.json() : null;
            const fmtData = fmtResp.ok ? await fmtResp.json() : null;

            // Panel 2: MD rendered preview
            if (mdData) {
                mdPreview.innerHTML = '<div class="preview-html">' + (mdData.html || '') + '</div>';
            } else {
                mdPreview.innerHTML = `<p style="color:var(--color-error)">MD preview failed</p>`;
            }

            // Panel 3: Format source (raw tags)
            if (fmtData && fmtSource) {
                const raw = fmtData.html || '(empty)';
                const escaped = raw.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
                const label = fmtLabels[fmtData.format] || fmtData.format;
                if (sourceHeader) sourceHeader.textContent = `${label} Source (${raw.length.toLocaleString()} bytes)`;
                fmtSource.innerHTML = `<pre class="preview-source">${escaped}</pre>`;
            }

            // Panel 4: Format rendered preview
            if (fmtPreview) {
                const label = fmtLabels[this.previewFormat] || this.previewFormat;
                if (fmtPreviewHeader) fmtPreviewHeader.textContent = `${label} Preview`;

                if (this.previewFormat === 'clean_html' && mdData) {
                    fmtPreview.innerHTML = '<div class="preview-html">' + (mdData.html || '') + '</div>';
                } else if (fmtData) {
                    if (this.previewFormat === 'styled_html') {
                        // Use preview_html (CSS inlined) for iframe, html (external link) for source
                        fmtPreview.innerHTML = '<iframe class="preview-iframe" sandbox="allow-same-origin"></iframe>';
                        fmtPreview.querySelector('iframe').srcdoc = fmtData.preview_html || fmtData.html || '';
                    } else if (this.previewFormat === 'bbcode') {
                        fmtPreview.innerHTML = '<div class="preview-html">' + this._bbcodeToHtml(fmtData.html || '') + '</div>';
                    } else {
                        fmtPreview.innerHTML = '<div class="preview-html">' + (fmtData.html || '') + '</div>';
                    }
                }
            }

            [mdPreview, fmtSource, fmtPreview].forEach(el => { if (el) el.style.opacity = '1'; });
        } catch (err) {
            if (mdPreview) mdPreview.innerHTML = `<p style="color:var(--color-error)">Error: ${err.message}</p>`;
            [mdPreview, fmtSource, fmtPreview].forEach(el => { if (el) el.style.opacity = '1'; });
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
                this._requestSlopScore();
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

    // ---------------------------------------------------------------------------
    // Slop score
    // ---------------------------------------------------------------------------

    async _requestSlopScore() {
        const ta = document.getElementById('editor-textarea');
        const el = document.getElementById('editor-slop');
        if (!ta || !el) return;

        try {
            const resp = await fetch(`/api/editor/stories/${encodeURIComponent(this.storyName)}/slop`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ content: ta.value }),
            });
            if (!resp.ok) { el.textContent = 'Slop: ?'; return; }
            const data = await resp.json();
            this.slopScore = data;

            const score = data.score.toFixed(1);
            const rating = data.rating;
            let color = 'var(--color-success)';
            if (rating === 'BORDERLINE') color = 'var(--color-warning)';
            if (rating === 'SLOP') color = 'var(--color-error)';
            el.innerHTML = `<span style="color:${color}" title="${rating}: ${Object.keys(data.word_hits || {}).slice(0, 5).join(', ')}">Slop: ${score}</span>`;
        } catch (err) {
            el.textContent = 'Slop: error';
        }
    },

    // ---------------------------------------------------------------------------
    // CSS Editor
    // ---------------------------------------------------------------------------

    cssEditorOpen: false,

    async toggleCssEditor() {
        this.cssEditorOpen = !this.cssEditorOpen;
        const quad = document.querySelector('.editor-quad');
        let cssPanel = document.getElementById('panel-css-editor');

        if (this.cssEditorOpen) {
            if (!cssPanel) {
                // Create CSS panel
                const panel = document.createElement('div');
                panel.className = 'editor-quad-panel editor-css-panel';
                panel.id = 'panel-css-editor';
                panel.innerHTML = `
                    <div class="preview-panel-header">
                        Style CSS
                        <button class="btn-tiny" onclick="Editor.saveCss()">Save CSS</button>
                    </div>
                    <textarea id="css-textarea" spellcheck="false" placeholder="Loading CSS..."></textarea>
                `;
                quad.appendChild(panel);
            }
            // Load CSS
            try {
                const resp = await fetch(`/api/editor/stories/${encodeURIComponent(this.storyName)}/css`, { credentials: 'same-origin' });
                const data = await resp.json();
                const ta = document.getElementById('css-textarea');
                if (ta) ta.value = data.css || '';
                if (data.error) this._updateStatus(`CSS: ${data.error}`);
            } catch (err) {
                this._updateStatus(`CSS load error: ${err.message}`);
            }
            // Expand grid to 5 columns
            quad.style.gridTemplateColumns = '1fr 1fr 1fr 1fr 1fr';
        } else {
            if (cssPanel) cssPanel.remove();
            quad.style.gridTemplateColumns = '1fr 1fr 1fr 1fr';
        }
    },

    async saveCss() {
        const ta = document.getElementById('css-textarea');
        if (!ta) return;
        this._updateStatus('Saving CSS...');
        try {
            const resp = await fetch(`/api/editor/stories/${encodeURIComponent(this.storyName)}/css`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ css: ta.value }),
            });
            const data = await resp.json();
            if (data.ok) {
                this._updateStatus(`CSS saved (${data.bytes} bytes)`);
                // Refresh styled preview if active
                if (this.previewFormat === 'styled_html') this._requestPreview();
            } else {
                this._updateStatus('CSS save failed');
            }
        } catch (err) {
            this._updateStatus(`CSS save error: ${err.message}`);
        }
    },

};
