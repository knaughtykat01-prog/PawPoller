/**
 * Story Editor — edit MASTER.md with CodeMirror, live format preview,
 * chapter navigation, auto-save recovery, and per-chapter word count.
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
    isDirty: false,
    chapters: [],
    hiddenPanels: new Set(),
    _syncingScroll: false,
    cmView: null,           // CodeMirror EditorView instance (MD source)
    cmSourceView: null,     // CodeMirror for format source (read-only)
    cmCssView: null,        // CodeMirror for CSS editor
    autoSaveTimer: null,    // localStorage auto-save interval

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
                        <select id="editor-chapter-nav" title="Jump to chapter"></select>
                        <span id="editor-slop" class="editor-slop" title="Slop score"></span>
                        <span id="editor-status" class="editor-status"></span>
                        <span id="editor-wordcount" class="editor-wordcount"></span>
                        <button id="editor-save-btn" class="btn btn-sm">Save</button>
                        <button id="editor-css-btn" class="btn btn-sm btn-outline">CSS</button>
                        <button id="editor-regen-btn" class="btn btn-sm btn-outline">Regenerate</button>
                        <select id="editor-format-select">
                            <option value="clean_html">Clean HTML (AO3)</option>
                            <option value="sofurry_html">SoFurry HTML</option>
                            <option value="bbcode">BBCode (IB)</option>
                            <option value="styled_html">Styled HTML (PDF)</option>
                        </select>
                    </div>
                </div>
                <div class="editor-quad" id="editor-quad">
                    <div class="editor-quad-panel" id="panel-md-code">
                        <div class="preview-panel-header"><button class="panel-toggle" data-panel="panel-md-code" title="Hide panel">&#128065;</button> Markdown Source</div>
                        <div id="editor-cm-container" class="editor-cm-container"></div>
                    </div>
                    <div class="editor-quad-panel" id="panel-md-preview">
                        <div class="preview-panel-header"><button class="panel-toggle" data-panel="panel-md-preview" title="Hide panel">&#128065;</button> Markdown Preview</div>
                        <div class="preview-panel-body" id="editor-preview-rendered-body">
                            <p style="color:var(--text-secondary)">Loading...</p>
                        </div>
                    </div>
                    <div class="editor-quad-panel" id="panel-fmt-source">
                        <div class="preview-panel-header"><button class="panel-toggle" data-panel="panel-fmt-source" title="Hide panel">&#128065;</button> <span id="editor-source-header">Format Source</span></div>
                        <div class="preview-panel-body" id="editor-preview-source-body">
                            <p style="color:var(--text-secondary)">Loading...</p>
                        </div>
                    </div>
                    <div class="editor-quad-panel" id="panel-fmt-preview">
                        <div class="preview-panel-header"><button class="panel-toggle" data-panel="panel-fmt-preview" title="Hide panel">&#128065;</button> <span id="editor-fmt-preview-header">Format Preview</span></div>
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

            this.lastSavedContent = data.content;
            this.lastMtime = data.last_modified;
            this.chapters = data.chapters || [];
            this._updateWordCount(data.word_count);
            this._updateStatus('Loaded');

            // Check for crash recovery draft in localStorage
            const recoveryKey = `editor_recovery_${storyName}`;
            const recovered = localStorage.getItem(recoveryKey);
            let initialContent = data.content;
            if (recovered && recovered !== data.content) {
                const useRecovery = confirm('A recovery draft was found (unsaved changes from a previous session). Restore it?');
                if (useRecovery) {
                    initialContent = recovered;
                    this.isDirty = true;
                    this._updateStatus('Recovered from auto-save');
                } else {
                    localStorage.removeItem(recoveryKey);
                }
            }

            // Initialize CodeMirror
            this._initCodeMirror(initialContent);

            // Bind toolbar events
            document.getElementById('editor-format-select')?.addEventListener('change', (e) => this.switchFormat(e.target.value));
            document.getElementById('editor-css-btn')?.addEventListener('click', () => this.toggleCssEditor());
            document.getElementById('editor-save-btn')?.addEventListener('click', () => this.save());
            document.getElementById('editor-regen-btn')?.addEventListener('click', () => this.regenerate());
            document.getElementById('editor-chapter-nav')?.addEventListener('change', (e) => this._jumpToChapter(parseInt(e.target.value)));
            document.querySelectorAll('.panel-toggle').forEach(btn => {
                btn.addEventListener('click', () => this.togglePanel(btn.dataset.panel));
            });

            // Beforeunload warning
            window.addEventListener('beforeunload', (e) => {
                if (this.isDirty) { e.preventDefault(); e.returnValue = ''; }
            });

            // Auto-save to localStorage every 30s
            this.autoSaveTimer = setInterval(() => {
                if (this.isDirty && this.cmView) {
                    localStorage.setItem(recoveryKey, this.cmView.state.doc.toString());
                }
            }, 30000);

            // Build chapter nav + initial preview
            this._updateChapterNav();
            this._requestPreview();
            this._requestSlopScore();

        } catch (err) {
            const container = document.getElementById('editor-cm-container');
            if (container) container.innerHTML = `<p style="color:var(--color-error);padding:20px">Error loading: ${err.message}</p>`;
        }
    },

    // ---------------------------------------------------------------------------
    // CodeMirror initialization
    // ---------------------------------------------------------------------------

    _initCodeMirror(content) {
        const container = document.getElementById('editor-cm-container');
        if (!container || typeof CM === 'undefined') {
            // Fallback to textarea if CM bundle didn't load
            container.innerHTML = '<textarea id="editor-textarea" spellcheck="true"></textarea>';
            const ta = container.querySelector('textarea');
            ta.value = content;
            ta.addEventListener('input', () => this._onInput());
            return;
        }

        // Custom anchor highlighting
        const anchorHighlight = CM.ViewPlugin.fromClass(class {
            constructor(view) { this.decorations = this.buildDecos(view); }
            update(update) { if (update.docChanged || update.viewportChanged) this.decorations = this.buildDecos(update.view); }
            buildDecos(view) {
                const builder = new CM.Decoration.none.constructor();
                // Can't easily build decorations without RangeSetBuilder — skip for now
                return CM.Decoration.none;
            }
        }, { decorations: v => v.decorations });

        const darkTheme = CM.EditorView.theme({
            '&': { height: '100%', fontSize: '13px' },
            '.cm-scroller': { overflow: 'auto', fontFamily: "'Consolas', 'Monaco', 'Courier New', monospace" },
            '.cm-content': { padding: '10px 0' },
            '.cm-line': { padding: '0 12px' },
            '.cm-gutters': { background: 'var(--surface-elevated)', color: 'var(--text-tertiary)', border: 'none', minWidth: '3em' },
            '.cm-activeLineGutter': { background: 'var(--surface-primary)' },
            '.cm-activeLine': { background: 'rgba(255,255,255,0.03)' },
        });

        // Ctrl+S keybinding
        const saveKeymap = CM.keymap.of([{
            key: 'Mod-s',
            run: () => { this.save(); return true; },
        }]);

        this.cmView = new CM.EditorView({
            doc: content,
            extensions: [
                CM.basicSetup,
                CM.markdown(),
                CM.oneDark,
                darkTheme,
                saveKeymap,
                CM.lineNumbers(),
                CM.highlightActiveLine(),
                CM.highlightActiveLineGutter(),
                CM.EditorView.lineWrapping,
                CM.EditorView.updateListener.of(update => {
                    if (update.docChanged) this._onInput();
                }),
            ],
            parent: container,
        });
    },

    /** BBCode language definition for CodeMirror */
    _bbcodeLang: null,
    _getBBCodeLang() {
        if (this._bbcodeLang) return this._bbcodeLang;
        if (typeof CM === 'undefined' || !CM.StreamLanguage) return null;

        this._bbcodeLang = CM.StreamLanguage.define({
            token(stream) {
                // Opening tags: [b], [i], [center], [t], [color=#hex], [size=N], [right], [left]
                if (stream.match(/^\[\/?(b|i|u|s|center|right|left|t|url|img|quote)\]/i)) {
                    return 'keyword';
                }
                // Tags with attributes: [color=#hex], [size=N], [url=...]
                if (stream.match(/^\[\/?(?:color|size|url|font)=[^\]]*\]/i)) {
                    return 'keyword';
                }
                // Closing tags catch-all
                if (stream.match(/^\[\/[a-z]+\]/i)) {
                    return 'keyword';
                }
                // Unicode decorative chars (section breaks, separators)
                if (stream.match(/^[─✦✧⚜★☆·⸰✹❀☽☾◆⚝✿❋⁕✶📱❤♥⟨⟩]+/)) {
                    return 'atom';
                }
                // Advance one char
                stream.next();
                return null;
            },
        });
        return this._bbcodeLang;
    },

    /** Create a CodeMirror instance for viewing/editing non-MD content */
    _createCmInstance(container, content, lang, readOnly = false) {
        if (typeof CM === 'undefined') return null;
        container.innerHTML = '';
        const extensions = [
            CM.oneDark,
            CM.EditorView.theme({
                '&': { height: '100%', fontSize: '12px' },
                '.cm-scroller': { overflow: 'auto', fontFamily: "'Consolas', 'Monaco', monospace" },
                '.cm-gutters': { background: 'var(--surface-elevated)', color: 'var(--text-tertiary)', border: 'none' },
            }),
            CM.lineNumbers(),
            CM.EditorView.lineWrapping,
        ];
        if (lang === 'html') extensions.push(CM.html());
        else if (lang === 'css') extensions.push(CM.css());
        else if (lang === 'bbcode') {
            const bbLang = this._getBBCodeLang();
            if (bbLang) extensions.push(bbLang);
        }
        if (readOnly) extensions.push(CM.EditorState.readOnly.of(true));
        else extensions.push(CM.basicSetup);

        return new CM.EditorView({ doc: content, extensions, parent: container });
    },

    /** Update a CM instance's content without recreating it */
    _updateCmContent(view, content) {
        if (!view) return;
        view.dispatch({ changes: { from: 0, to: view.state.doc.length, insert: content } });
    },

    /** Get the current editor content (works with both CM and textarea fallback) */
    _getContent() {
        if (this.cmView) return this.cmView.state.doc.toString();
        const ta = document.getElementById('editor-textarea');
        return ta ? ta.value : '';
    },

    /** Set the editor content */
    _setEditorContent(text) {
        if (this.cmView) {
            this.cmView.dispatch({
                changes: { from: 0, to: this.cmView.state.doc.length, insert: text },
            });
        } else {
            const ta = document.getElementById('editor-textarea');
            if (ta) ta.value = text;
        }
    },

    // ---------------------------------------------------------------------------
    // Chapter navigation
    // ---------------------------------------------------------------------------

    _updateChapterNav() {
        const sel = document.getElementById('editor-chapter-nav');
        if (!sel) return;

        const content = this._getContent();
        const lines = content.split('\n');
        const chapters = [];
        let currentChapterWords = 0;

        for (let i = 0; i < lines.length; i++) {
            const m = lines[i].match(/^#\s+(.+)$/);
            if (m) {
                if (chapters.length > 0) {
                    chapters[chapters.length - 1].words = currentChapterWords;
                }
                chapters.push({ title: m[1], line: i, words: 0 });
                currentChapterWords = 0;
            } else {
                currentChapterWords += lines[i].split(/\s+/).filter(Boolean).length;
            }
        }
        if (chapters.length > 0) chapters[chapters.length - 1].words = currentChapterWords;

        this.chapters = chapters;
        sel.innerHTML = '<option value="-1">Chapters</option>' +
            chapters.map((ch, idx) =>
                `<option value="${idx}">${ch.title} (${ch.words.toLocaleString()}w)</option>`
            ).join('');
    },

    _jumpToChapter(idx) {
        if (idx < 0 || idx >= this.chapters.length) return;
        const line = this.chapters[idx].line;

        if (this.cmView) {
            const lineInfo = this.cmView.state.doc.line(line + 1); // CM lines are 1-based
            this.cmView.dispatch({
                selection: { anchor: lineInfo.from },
                effects: CM.EditorView.scrollIntoView(lineInfo.from, { y: 'start' }),
            });
            this.cmView.focus();
        }
        // Reset dropdown
        const sel = document.getElementById('editor-chapter-nav');
        if (sel) sel.value = '-1';
    },

    // ---------------------------------------------------------------------------
    // Input handling
    // ---------------------------------------------------------------------------

    _onInput() {
        const content = this._getContent();
        if (!content && content !== '') return;

        this.isDirty = content !== this.lastSavedContent;
        this._updateStatus(this.isDirty ? 'Unsaved changes' : 'Saved');
        this._updateWordCount(content.split(/\s+/).filter(Boolean).length);

        // Debounced preview
        clearTimeout(this.previewDebounceTimer);
        this.previewDebounceTimer = setTimeout(() => this._requestPreview(), 400);
    },

    // ---------------------------------------------------------------------------
    // Preview
    // ---------------------------------------------------------------------------

    async _requestPreview() {
        const mdPreview = document.getElementById('editor-preview-rendered-body');
        const fmtSource = document.getElementById('editor-preview-source-body');
        const fmtPreview = document.getElementById('editor-preview-fmt-body');
        const sourceHeader = document.getElementById('editor-source-header');
        const fmtPreviewHeader = document.getElementById('editor-fmt-preview-header');
        if (!mdPreview) return;

        let content = this._getContent();
        const MAX_PREVIEW = 500000;
        if (content.length > MAX_PREVIEW) {
            content = content.substring(0, MAX_PREVIEW) + '\n\n[... truncated for preview ...]';
        }

        const thisRequestId = ++this.previewRequestId;
        const fmtLabels = { 'bbcode': 'BBCode', 'clean_html': 'Clean HTML', 'sofurry_html': 'SoFurry HTML', 'styled_html': 'Styled HTML' };

        try {
            [mdPreview, fmtSource, fmtPreview].forEach(el => { if (el) el.style.opacity = '0.6'; });

            // 2 parallel requests: MD preview (clean_html) + selected format
            const url = `/api/editor/stories/${encodeURIComponent(this.storyName)}/preview`;
            // Pass live theme vars for styled_html so preview reflects GUI changes
            const fmtBody = { content, format: this.previewFormat };
            if (this.previewFormat === 'styled_html' && Object.keys(this.themeVars).length > 0) {
                fmtBody.theme = this.themeVars;
            }
            const [mdResp, fmtResp] = await Promise.all([
                fetch(url, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ content, format: 'clean_html' }),
                }),
                fetch(url, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(fmtBody),
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

            // Panel 3: Format source (syntax highlighted, read-only)
            if (fmtData && fmtSource) {
                const raw = fmtData.html || '(empty)';
                const label = fmtLabels[fmtData.format] || fmtData.format;
                if (sourceHeader) sourceHeader.textContent = `${label} Source (${raw.length.toLocaleString()} bytes)`;
                const lang = (this.previewFormat === 'bbcode') ? 'bbcode' : 'html';
                if (this.cmSourceView) {
                    this._updateCmContent(this.cmSourceView, raw);
                } else if (typeof CM !== 'undefined') {
                    this.cmSourceView = this._createCmInstance(fmtSource, raw, lang, true);
                } else {
                    const escaped = raw.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
                    fmtSource.innerHTML = `<pre class="preview-source">${escaped}</pre>`;
                }
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

            // Sync CSS source view if theme editor is in source mode and styled_html returned CSS
            if (fmtData && fmtData.css && this.themeSourceMode && this.cmCssView) {
                this._updateCmContent(this.cmCssView, fmtData.css);
            }

            [mdPreview, fmtSource, fmtPreview].forEach(el => { if (el) el.style.opacity = '1'; });
        } catch (err) {
            if (mdPreview) mdPreview.innerHTML = `<p style="color:var(--color-error)">Error: ${err.message}</p>`;
            [mdPreview, fmtSource, fmtPreview].forEach(el => { if (el) el.style.opacity = '1'; });
        }
    },

    switchFormat(fmt) {
        this.previewFormat = fmt;
        // Destroy source CM so it gets recreated with the right language
        if (this.cmSourceView) { this.cmSourceView.destroy(); this.cmSourceView = null; }
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
        const content = this._getContent();

        this._updateStatus('Saving...');
        try {
            const resp = await fetch(`/api/editor/stories/${encodeURIComponent(this.storyName)}/content`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    content: content,
                    expected_mtime: this.lastMtime,
                }),
            });

            if (resp.status === 409) {
                this._updateStatus('Conflict! File changed externally. Reload to merge.');
                return;
            }

            const data = await resp.json();
            if (data.ok) {
                this.lastSavedContent = content;
                this.lastMtime = data.last_modified;
                this.isDirty = false;
                this._updateStatus('Saved');
                this._updateWordCount(data.word_count);
                this._updateChapterNav();
                this._requestSlopScore();
                // Clear recovery draft on successful save
                localStorage.removeItem(`editor_recovery_${this.storyName}`);
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
        const el = document.getElementById('editor-slop');
        if (!el) return;

        try {
            const resp = await fetch(`/api/editor/stories/${encodeURIComponent(this.storyName)}/slop`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ content: this._getContent() }),
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
    // Panel visibility toggles
    // ---------------------------------------------------------------------------

    togglePanel(panelId) {
        const panel = document.getElementById(panelId);
        if (!panel) return;

        if (this.hiddenPanels.has(panelId)) {
            // Show
            this.hiddenPanels.delete(panelId);
            panel.style.display = '';
        } else {
            // Hide
            this.hiddenPanels.add(panelId);
            panel.style.display = 'none';
        }
        this._updateGridColumns();
        this._updateRestoreBar();
    },

    _updateGridColumns() {
        const quad = document.getElementById('editor-quad');
        if (!quad) return;
        const visible = quad.querySelectorAll('.editor-quad-panel:not([style*="display: none"])').length;
        quad.style.gridTemplateColumns = Array(visible).fill('1fr').join(' ');
    },

    _updateRestoreBar() {
        let bar = document.getElementById('panel-restore-bar');
        if (this.hiddenPanels.size === 0) {
            if (bar) bar.remove();
            return;
        }
        if (!bar) {
            bar = document.createElement('div');
            bar.id = 'panel-restore-bar';
            bar.className = 'panel-restore-bar';
            const toolbar = document.querySelector('.editor-toolbar');
            if (toolbar) toolbar.after(bar);
        }
        const labels = {
            'panel-md-code': 'MD Source',
            'panel-md-preview': 'MD Preview',
            'panel-fmt-source': 'Format Source',
            'panel-fmt-preview': 'Format Preview',
            'panel-css-editor': 'CSS',
        };
        bar.innerHTML = 'Hidden: ' + [...this.hiddenPanels].map(id =>
            `<button class="restore-btn" data-restore="${id}">&#128065;&#8203;&#822; ${labels[id] || id}</button>`
        ).join('');
        bar.querySelectorAll('.restore-btn').forEach(btn => {
            btn.addEventListener('click', () => this.togglePanel(btn.dataset.restore));
        });
    },

    // ---------------------------------------------------------------------------
    // CSS Editor
    // ---------------------------------------------------------------------------

    cssEditorOpen: false,
    themeVars: {},
    themeSavedVars: {},      // snapshot from server — for Revert
    themeHistory: [],        // undo stack
    themeSourceMode: false,  // false = GUI, true = raw CSS source

    async toggleCssEditor() {
        this.cssEditorOpen = !this.cssEditorOpen;
        const quad = document.getElementById('editor-quad');
        let cssPanel = document.getElementById('panel-css-editor');

        if (this.cssEditorOpen) {
            if (!cssPanel) {
                const panel = document.createElement('div');
                panel.className = 'editor-quad-panel editor-css-panel';
                panel.id = 'panel-css-editor';
                panel.innerHTML = `
                    <div class="preview-panel-header">
                        <button class="panel-toggle" data-panel="panel-css-editor" title="Hide panel">&#128065;</button>
                        Theme Editor
                        <button class="btn-tiny" id="theme-save-btn">Save</button>
                        <button class="btn-tiny" id="theme-undo-btn" disabled title="Undo last change">Undo</button>
                        <button class="btn-tiny" id="theme-revert-btn" title="Revert to saved">Revert</button>
                        <button class="btn-tiny" id="theme-source-btn">Source</button>
                    </div>
                    <div id="theme-editor-body" class="preview-panel-body theme-editor-body"></div>
                `;
                quad.appendChild(panel);
                document.getElementById('theme-save-btn')?.addEventListener('click', () => this.saveTheme());
                document.getElementById('theme-undo-btn')?.addEventListener('click', () => this.undoTheme());
                document.getElementById('theme-revert-btn')?.addEventListener('click', () => this.revertTheme());
                document.getElementById('theme-source-btn')?.addEventListener('click', () => this._toggleThemeSource());
                document.querySelector('#panel-css-editor .panel-toggle')?.addEventListener('click', () => this.togglePanel('panel-css-editor'));
            }
            await this._loadThemeEditor();
            this._updateGridColumns();
        } else {
            if (this.cmCssView) { this.cmCssView.destroy(); this.cmCssView = null; }
            if (cssPanel) cssPanel.remove();
            this._updateGridColumns();
        }
    },

    async _loadThemeEditor() {
        const body = document.getElementById('theme-editor-body');
        if (!body) return;

        try {
            const resp = await fetch(`/api/editor/stories/${encodeURIComponent(this.storyName)}/theme`);
            const data = await resp.json();
            this.themeVars = data.variables || {};
            this.themeSavedVars = { ...this.themeVars };
            this.themeHistory = [];
            if (data.error) { this._updateStatus(`Theme: ${data.error}`); return; }
            this._renderThemeGUI();
            this._updateUndoBtn();
        } catch (err) {
            body.innerHTML = `<p style="color:var(--color-error)">Error: ${err.message}</p>`;
        }
    },

    _renderThemeGUI() {
        const body = document.getElementById('theme-editor-body');
        if (!body) return;

        const colorRow = (label, key) => {
            const val = this.themeVars[key] || '#000000';
            return `<div class="theme-row">
                <label>${label}</label>
                <input type="color" value="${val.startsWith('#') ? val : '#000000'}" data-key="${key}">
                <input type="text" value="${val}" data-key="${key}" class="theme-hex">
            </div>`;
        };

        const textRow = (label, key, placeholder) => {
            const val = this.themeVars[key] || '';
            return `<div class="theme-row">
                <label>${label}</label>
                <input type="text" value="${val}" data-key="${key}" class="theme-text" placeholder="${placeholder || ''}">
            </div>`;
        };

        const selectRow = (label, key, options) => {
            const val = this.themeVars[key] || options[0]?.value || '';
            const opts = options.map(o => `<option value="${o.value}" ${o.value === val ? 'selected' : ''}>${o.label}</option>`).join('');
            return `<div class="theme-row">
                <label>${label}</label>
                <select data-key="${key}">${opts}</select>
            </div>`;
        };

        body.innerHTML = `
            <div class="theme-section">
                <h4>Colours</h4>
                ${colorRow('Background', 'BACKGROUND')}
                ${colorRow('Body Text', 'TEXT_COLOUR')}
                ${colorRow('Title', 'TITLE_COLOUR')}
                ${colorRow('Byline', 'BYLINE_COLOUR')}
                ${colorRow('Accent', 'ACCENT_COLOUR')}
                ${colorRow('Warning Heading', 'WARNING_HEADING_COLOUR')}
                ${colorRow('Warning Body', 'WARNING_BODY_COLOUR')}
                ${colorRow('Disclaimer', 'DISCLAIMER_HEADING_COLOUR')}
                ${colorRow('Story End', 'STORY_END_COLOUR')}
                ${colorRow('Signature', 'SIGNATURE_COLOUR')}
            </div>
            <div class="theme-section">
                <h4>Typography</h4>
                ${textRow('Title Shadow', 'TITLE_TEXT_SHADOW', 'text-shadow: 0 0 25px rgba(...)')}
            </div>
            <div class="theme-section">
                <h4>Decorations</h4>
                ${textRow('Warning Icon', 'WARNING_ICON', '&#9888;')}
                ${textRow('Section Break', 'SECTION_BREAK_SYMBOL', '· ✦ ·')}
            </div>
            <div class="theme-section">
                <h4>Print</h4>
                ${selectRow('Approach', 'PRINT_APPROACH', [
                    {value: 'colour-preserve', label: 'Colour Preserve (dark bg)'},
                    {value: 'grayscale', label: 'Grayscale (light bg)'},
                ])}
            </div>
        `;

        // Bind colour picker ↔ hex input sync
        // Colour pickers fire 'input' continuously while dragging — only push
        // one undo entry per drag (on first input), not hundreds.
        body.querySelectorAll('input[type="color"]').forEach(picker => {
            const key = picker.dataset.key;
            const hex = body.querySelector(`.theme-hex[data-key="${key}"]`);
            let dragging = false;
            picker.addEventListener('input', () => {
                if (!dragging) { this._pushThemeUndo(); dragging = true; }
                if (hex) hex.value = picker.value;
                this.themeVars[key] = picker.value;
                this._onThemeChange();
            });
            picker.addEventListener('change', () => { dragging = false; });
        });
        body.querySelectorAll('.theme-hex').forEach(input => {
            const key = input.dataset.key;
            const picker = body.querySelector(`input[type="color"][data-key="${key}"]`);
            input.addEventListener('change', () => {
                this._pushThemeUndo();
                if (picker && input.value.match(/^#[0-9a-fA-F]{6}$/)) picker.value = input.value;
                this.themeVars[key] = input.value;
                this._onThemeChange();
            });
        });
        body.querySelectorAll('.theme-text, select[data-key]').forEach(input => {
            input.addEventListener('change', () => {
                this._pushThemeUndo();
                this.themeVars[input.dataset.key] = input.value;
                this._onThemeChange();
            });
        });
    },

    _pushThemeUndo() {
        // Snapshot current state before a change — cap at 50 entries
        this.themeHistory.push({ ...this.themeVars });
        if (this.themeHistory.length > 50) this.themeHistory.shift();
        this._updateUndoBtn();
    },

    _updateUndoBtn() {
        const btn = document.getElementById('theme-undo-btn');
        if (btn) btn.disabled = this.themeHistory.length === 0;
    },

    undoTheme() {
        if (this.themeHistory.length === 0) return;
        this.themeVars = this.themeHistory.pop();
        this._updateUndoBtn();
        this._renderThemeGUI();
        this._onThemeChange();
    },

    revertTheme() {
        if (Object.keys(this.themeSavedVars).length === 0) return;
        // Push current state so the revert itself is undoable
        this._pushThemeUndo();
        this.themeVars = { ...this.themeSavedVars };
        this._renderThemeGUI();
        this._onThemeChange();
        this._updateStatus('Theme reverted to saved');
    },

    _onThemeChange() {
        // Live preview refresh — always trigger when theme changes so CSS stays in sync
        clearTimeout(this.previewDebounceTimer);
        this.previewDebounceTimer = setTimeout(() => {
            // If styled_html preview is active, preview request carries the theme vars
            // and returns generated CSS which we use to sync the source view
            if (this.previewFormat === 'styled_html') {
                this._requestPreview();
            }
        }, 300);
    },

    _toggleThemeSource() {
        this.themeSourceMode = !this.themeSourceMode;
        const body = document.getElementById('theme-editor-body');
        const btn = document.getElementById('theme-source-btn');
        if (!body) return;

        if (this.themeSourceMode) {
            // Show raw CSS
            if (btn) btn.textContent = 'GUI';
            (async () => {
                const resp = await fetch(`/api/editor/stories/${encodeURIComponent(this.storyName)}/css`);
                const data = await resp.json();
                if (this.cmCssView) { this.cmCssView.destroy(); this.cmCssView = null; }
                this.cmCssView = this._createCmInstance(body, data.css || '', 'css', false);
            })();
        } else {
            // Back to GUI
            if (btn) btn.textContent = 'Source';
            if (this.cmCssView) { this.cmCssView.destroy(); this.cmCssView = null; }
            this._renderThemeGUI();
        }
    },

    async saveTheme() {
        this._updateStatus('Saving theme...');
        try {
            let resp, data;
            if (this.themeSourceMode && this.cmCssView) {
                // Save raw CSS directly
                resp = await fetch(`/api/editor/stories/${encodeURIComponent(this.storyName)}/css`, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ css: this.cmCssView.state.doc.toString() }),
                });
            } else {
                // Save theme variables → regenerate CSS
                resp = await fetch(`/api/editor/stories/${encodeURIComponent(this.storyName)}/theme`, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ variables: this.themeVars }),
                });
            }
            if (!resp.ok) {
                const errText = await resp.text();
                let detail = `HTTP ${resp.status}`;
                try { const j = JSON.parse(errText); detail = j.detail || j.error || detail; } catch {}
                this._updateStatus(`Save failed: ${detail}`);
                return;
            }
            data = await resp.json();
            if (this.themeSourceMode) {
                this._updateStatus(`CSS saved (${data.bytes}b)`);
            } else {
                // Update saved snapshot so Revert goes back to this state
                this.themeSavedVars = { ...this.themeVars };
                this.themeHistory = [];
                this._updateUndoBtn();
                this._updateStatus(`Theme saved (${data.css_bytes}b CSS)`);
            }
            if (this.previewFormat === 'styled_html') this._requestPreview();
        } catch (err) {
            this._updateStatus(`Theme save error: ${err.message}`);
        }
    },

};
