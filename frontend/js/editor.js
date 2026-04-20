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
    // WYSIWYG state
    _wysiwygEditSource: null,   // 'cm' | 'wysiwyg' | null — prevents sync loops
    _wysiwygSyncTimer: null,    // debounce for WYSIWYG→CM conversion
    _turndown: null,            // TurndownService instance
    _frontMatterMd: '',         // cached front matter (above <!-- @body -->)
    _bodyStartLine: 0,          // line index of <!-- @body -->

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
                <div style="margin-bottom:16px">
                    <button class="btn btn-sm" id="create-story-btn">+ Create New Story</button>
                </div>
                <div class="card-grid">${cards || '<p>No stories found in the archive.</p>'}</div>

                <div class="create-story-overlay" id="create-story-overlay">
                    <div class="create-story-dialog">
                        <h3>Create New Story</h3>
                        <label class="create-story-label">
                            Title
                            <input type="text" id="create-story-title" class="create-story-input" placeholder="My New Story" autocomplete="off">
                        </label>
                        <label class="create-story-label">
                            Folder name
                            <input type="text" id="create-story-name" class="create-story-input" placeholder="My_New_Story" autocomplete="off">
                            <span class="create-story-hint">Letters, digits, and underscores only</span>
                        </label>
                        <label class="create-story-label">
                            Author
                            <input type="text" id="create-story-author" class="create-story-input" placeholder="Author name" autocomplete="off">
                        </label>
                        <label class="create-story-label">
                            Genre template <span class="create-story-hint">(optional — pre-fills tags + rating)</span>
                            <select id="create-story-genre" class="create-story-input">
                                <option value="">None</option>
                                <option value="romance">Romance</option>
                                <option value="erotica">Erotica</option>
                                <option value="adventure">Adventure</option>
                                <option value="comedy">Comedy</option>
                                <option value="drama">Drama</option>
                                <option value="fantasy">Fantasy</option>
                                <option value="sci_fi">Sci-Fi</option>
                                <option value="slice_of_life">Slice of Life</option>
                                <option value="horror">Horror</option>
                            </select>
                        </label>
                        <div style="display:flex;gap:12px">
                            <label class="create-story-label" style="flex:1">
                                Chapters
                                <select id="create-story-chapters" class="create-story-input">
                                    ${Array.from({length: 20}, (_, i) => `<option value="${i+1}"${i === 0 ? ' selected' : ''}>${i+1}</option>`).join('')}
                                </select>
                            </label>
                            <label class="create-story-label" style="flex:1">
                                Rating
                                <select id="create-story-rating" class="create-story-input">
                                    <option value="general">General</option>
                                    <option value="mature">Mature</option>
                                    <option value="explicit" selected>Explicit</option>
                                </select>
                            </label>
                        </div>
                        <div id="create-story-error" class="create-story-error" style="display:none"></div>
                        <div class="create-story-actions">
                            <button class="btn btn-sm btn-outline" id="create-story-cancel">Cancel</button>
                            <button class="btn btn-sm" id="create-story-submit">Create</button>
                        </div>
                    </div>
                </div>
            `);

            // Bind create-story dialog
            const overlay = document.getElementById('create-story-overlay');
            const titleInput = document.getElementById('create-story-title');
            const nameInput = document.getElementById('create-story-name');

            // Genre template rating map — keeps frontend in sync with backend GENRE_TEMPLATES
            const genreRatings = {
                romance: 'mature', erotica: 'explicit', adventure: 'general',
                comedy: 'general', drama: 'mature', fantasy: 'general',
                sci_fi: 'general', slice_of_life: 'general', horror: 'mature',
            };

            document.getElementById('create-story-btn').addEventListener('click', () => {
                overlay.classList.add('open');
                titleInput.value = '';
                nameInput.value = '';
                document.getElementById('create-story-author').value = '';
                document.getElementById('create-story-genre').value = '';
                document.getElementById('create-story-chapters').value = '1';
                document.getElementById('create-story-rating').value = 'explicit';
                document.getElementById('create-story-error').style.display = 'none';
                titleInput.focus();
            });

            // Auto-generate folder name from title
            titleInput.addEventListener('input', () => {
                nameInput.value = titleInput.value.trim().replace(/[^A-Za-z0-9_ ]/g, '').replace(/ +/g, '_');
            });

            // When genre changes, auto-update rating to the template default
            document.getElementById('create-story-genre').addEventListener('change', (e) => {
                const genre = e.target.value;
                if (genre && genreRatings[genre]) {
                    document.getElementById('create-story-rating').value = genreRatings[genre];
                }
            });

            document.getElementById('create-story-cancel').addEventListener('click', () => {
                overlay.classList.remove('open');
            });
            overlay.addEventListener('click', (e) => {
                if (e.target === overlay) overlay.classList.remove('open');
            });

            document.getElementById('create-story-submit').addEventListener('click', () => {
                Editor._submitCreateStory();
            });
            // Enter key submits
            overlay.addEventListener('keydown', (e) => {
                if (e.key === 'Enter') { e.preventDefault(); Editor._submitCreateStory(); }
                if (e.key === 'Escape') overlay.classList.remove('open');
            });

        } catch (err) {
            App._setContent(`<div class="empty-state"><h3>Error loading stories</h3><p>${err.message}</p></div>`);
        }
    },

    async _submitCreateStory() {
        const errEl = document.getElementById('create-story-error');
        const name = (document.getElementById('create-story-name').value || '').trim();
        const title = (document.getElementById('create-story-title').value || '').trim();
        const author = (document.getElementById('create-story-author').value || '').trim();
        const genre = document.getElementById('create-story-genre').value || '';
        const chapters = parseInt(document.getElementById('create-story-chapters').value, 10) || 1;
        const rating = document.getElementById('create-story-rating').value || 'explicit';

        if (!title) {
            errEl.textContent = 'Title is required.';
            errEl.style.display = 'block';
            return;
        }
        if (!name) {
            errEl.textContent = 'Folder name is required.';
            errEl.style.display = 'block';
            return;
        }
        if (!/^[A-Za-z0-9_]+$/.test(name)) {
            errEl.textContent = 'Folder name may only contain letters, digits, and underscores.';
            errEl.style.display = 'block';
            return;
        }

        const submitBtn = document.getElementById('create-story-submit');
        submitBtn.disabled = true;
        submitBtn.textContent = 'Creating...';
        errEl.style.display = 'none';

        try {
            const resp = await fetch('/api/editor/stories/create', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ name, title, author, genre, chapters, rating }),
            });
            const data = await resp.json();
            if (!resp.ok) {
                throw new Error(data.detail || 'Failed to create story');
            }
            document.getElementById('create-story-overlay').classList.remove('open');
            location.hash = '#/editor/' + data.story_name;
        } catch (err) {
            errEl.textContent = err.message;
            errEl.style.display = 'block';
        } finally {
            submitBtn.disabled = false;
            submitBtn.textContent = 'Create';
        }
    },

    // ---------------------------------------------------------------------------
    // Editor page
    // ---------------------------------------------------------------------------

    async renderEditor(storyName) {
        // Clean up previous editor state
        clearInterval(this.autoSaveTimer);
        if (this._beforeUnloadHandler) {
            window.removeEventListener('beforeunload', this._beforeUnloadHandler);
        }
        if (this.cmView) { this.cmView.destroy(); this.cmView = null; }
        if (this.cmSourceView) { this.cmSourceView.destroy(); this.cmSourceView = null; }
        if (this.cmCssView) { this.cmCssView.destroy(); this.cmCssView = null; }
        this._wysiwygEditSource = null;
        clearTimeout(this._wysiwygSyncTimer);

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
                        <button id="editor-metadata-btn" class="btn btn-sm btn-outline">Metadata</button>
                        <button id="editor-css-btn" class="btn btn-sm btn-outline">CSS</button>
                        <div class="regen-dropdown" id="regen-dropdown">
                            <button id="editor-regen-btn" class="btn btn-sm btn-outline">Regenerate &#9662;</button>
                            <div class="regen-dropdown-menu" id="regen-dropdown-menu">
                                <button data-regen="all">All formats</button>
                                <button data-regen="html">HTML only (SF/AO3/SQW)</button>
                                <button data-regen="bbcode">BBCode only (IB/WS)</button>
                                <button data-regen="styled">Styled HTML + CSS</button>
                                <button data-regen="sqw">SquidgeWorld only</button>
                                <button data-regen="pdf">PDF only</button>
                                <button data-regen="chapters">Chapter splits only</button>
                            </div>
                        </div>
                        <button id="editor-publish-btn" class="btn btn-sm btn-outline" title="Check publishability across all platforms">Publish</button>
                        <button id="editor-format-btn" class="btn btn-sm btn-outline" title="Format source code (Shift+Alt+F)">Format</button>
                        <div class="format-tabs" id="format-tabs">
                            <button class="format-tab active" data-fmt="clean_html">Clean HTML</button>
                            <button class="format-tab" data-fmt="sofurry_html">SoFurry</button>
                            <button class="format-tab" data-fmt="bbcode">BBCode</button>
                            <button class="format-tab" data-fmt="styled_html">Styled</button>
                        </div>
                    </div>
                </div>
                <div class="editor-quad" id="editor-quad">
                    <div class="editor-quad-panel" id="panel-md-code">
                        <div class="preview-panel-header"><button class="panel-toggle" data-panel="panel-md-code" title="Hide panel">&#128065;</button> Markdown Source</div>
                        <div id="editor-cm-container" class="editor-cm-container"></div>
                    </div>
                    <div class="editor-quad-panel" id="panel-md-preview">
                        <div class="preview-panel-header"><button class="panel-toggle" data-panel="panel-md-preview" title="Hide panel">&#128065;</button> Rich Editor</div>
                        <div class="wysiwyg-toolbar" id="wysiwyg-toolbar">
                            <button data-cmd="undo" title="Undo (Ctrl+Z)">&#8630;</button>
                            <button data-cmd="redo" title="Redo (Ctrl+Y)">&#8631;</button>
                            <span class="toolbar-sep"></span>
                            <button data-cmd="bold" title="Bold (Ctrl+B)"><strong>B</strong></button>
                            <button data-cmd="italic" title="Italic (Ctrl+I)"><em>I</em></button>
                            <span class="toolbar-sep"></span>
                            <button data-cmd="heading" title="Chapter Heading">H1</button>
                            <button data-cmd="hr" title="Section Break">&#8213;</button>
                            <span class="toolbar-sep"></span>
                            <button data-anchor="title" title="Insert @title anchor">T</button>
                            <button data-anchor="subtitle" title="Insert @subtitle anchor">Sub</button>
                            <button data-anchor="body" title="Insert @body anchor">Body</button>
                            <button data-anchor="warning" title="Insert @warning anchor">&#9888;</button>
                            <button data-anchor="text-sent" title="Insert text-sent block">&#8594;</button>
                            <button data-anchor="text-received" title="Insert text-received block">&#8592;</button>
                            <button data-anchor="phone" title="Insert phone block">&#9742;</button>
                            <button data-anchor="story-end" title="Insert story-end anchor">End</button>
                        </div>
                        <div class="preview-panel-body preview-html" id="editor-preview-rendered-body" contenteditable="true" spellcheck="true">
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
            document.querySelectorAll('#format-tabs .format-tab').forEach(btn => {
                btn.addEventListener('click', () => {
                    document.querySelectorAll('#format-tabs .format-tab').forEach(b => b.classList.remove('active'));
                    btn.classList.add('active');
                    this.switchFormat(btn.dataset.fmt);
                });
            });
            document.getElementById('editor-css-btn')?.addEventListener('click', () => this.toggleCssEditor());
            document.getElementById('editor-metadata-btn')?.addEventListener('click', () => MetaEditor.toggle());
            document.getElementById('editor-save-btn')?.addEventListener('click', () => this.save());
            // Regen dropdown toggle + menu items
            document.getElementById('editor-regen-btn')?.addEventListener('click', (e) => {
                e.stopPropagation();
                document.getElementById('regen-dropdown-menu')?.classList.toggle('open');
            });
            document.querySelectorAll('#regen-dropdown-menu button[data-regen]').forEach(btn => {
                btn.addEventListener('click', (e) => {
                    e.stopPropagation();
                    document.getElementById('regen-dropdown-menu')?.classList.remove('open');
                    this.regenerate(btn.dataset.regen === 'all' ? null : [btn.dataset.regen]);
                });
            });
            // Close dropdown on outside click
            document.addEventListener('click', () => {
                document.getElementById('regen-dropdown-menu')?.classList.remove('open');
            });
            document.getElementById('editor-publish-btn')?.addEventListener('click', () => PublishCheck.open(storyName));
            document.getElementById('editor-format-btn')?.addEventListener('click', () => this.formatSource());
            document.getElementById('editor-chapter-nav')?.addEventListener('change', (e) => this._jumpToChapter(parseInt(e.target.value)));
            document.querySelectorAll('.panel-toggle').forEach(btn => {
                btn.addEventListener('click', () => this.togglePanel(btn.dataset.panel));
            });

            // Initialize WYSIWYG
            this._initTurndown();
            this._initWysiwygToolbar();
            this._initWysiwygInput();

            // Cache front matter from initial content
            this._cacheFrontMatter(initialContent);

            // Beforeunload warning (single handler, cleaned up on re-render)
            this._beforeUnloadHandler = (e) => {
                if (this.isDirty) { e.preventDefault(); e.returnValue = ''; }
            };
            window.addEventListener('beforeunload', this._beforeUnloadHandler);

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
        const saveKeymap = CM.keymap.of([
            { key: 'Mod-s', run: () => { this.save(); return true; } },
            { key: 'Shift-Alt-f', run: () => { this.formatSource(); return true; } },
        ]);

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
                // Scroll sync: editor → other panels
                CM.EditorView.domEventHandlers({
                    scroll: () => { this._syncScroll('cm-editor'); },
                    mouseup: () => { this._syncSelectionFromCM(); },
                }),
            ],
            parent: container,
        });

        // Scroll sync: preview panels → other panels
        for (const id of ['editor-preview-rendered-body', 'editor-preview-source-body', 'editor-preview-fmt-body']) {
            const el = document.getElementById(id);
            if (el) el.addEventListener('scroll', () => this._syncScroll(id));
        }

        // Selection sync: selecting text in any panel highlights it in the others
        for (const id of ['editor-preview-rendered-body', 'editor-preview-fmt-body']) {
            const el = document.getElementById(id);
            if (el) el.addEventListener('mouseup', () => this._syncSelection(id));
        }
    },

    _syncSelectionFromCM() {
        this._clearSelectionHighlights();
        if (!this.cmView) return;
        const { from, to } = this.cmView.state.selection.main;
        if (from === to) return;
        const text = this.cmView.state.sliceDoc(from, to).trim();
        if (text.length < 3 || text.length > 500) return;

        // Strip markdown formatting to get the plain text for HTML panel search
        const plain = text.replace(/\*+/g, '').replace(/_+/g, '').trim();
        if (!plain) return;

        // Highlight in format preview only (skip contenteditable panel 2 to avoid DOM corruption)
        const fmtPreview = document.getElementById('editor-preview-fmt-body');
        if (fmtPreview) this._highlightInHtml(fmtPreview, plain);
        // Highlight in CM source view
        if (this.cmSourceView) this._highlightInCM(this.cmSourceView, plain);
    },

    _syncSelectionFromCMSource() {
        this._clearSelectionHighlights();
        if (!this.cmSourceView) return;
        const { from, to } = this.cmSourceView.state.selection.main;
        if (from === to) return;
        const text = this.cmSourceView.state.sliceDoc(from, to).trim();
        if (text.length < 3 || text.length > 500) return;

        // Strip HTML tags to get plain text
        const plain = text.replace(/<[^>]+>/g, '').replace(/&[a-z]+;/gi, ' ').trim();
        if (!plain) return;

        // Highlight in CM editor and format preview (skip contenteditable panel 2)
        if (this.cmView) this._highlightInCM(this.cmView, plain);
        const fmtPreview = document.getElementById('editor-preview-fmt-body');
        if (fmtPreview) this._highlightInHtml(fmtPreview, plain);
    },

    _selectionHighlights: [],  // track active highlights for cleanup

    _syncSelection(sourceId) {
        const sel = window.getSelection();
        const text = sel?.toString().trim();

        // Clear previous highlights
        this._clearSelectionHighlights();

        if (!text || text.length < 3 || text.length > 500) return;

        // Strip HTML tags to get plain text for searching in source
        const searchText = text;

        // Highlight in CM editor (panel 1)
        if (this.cmView) this._highlightInCM(this.cmView, searchText);

        // Highlight in CM source view (panel 3)
        if (this.cmSourceView) this._highlightInCM(this.cmSourceView, searchText);

        // Highlight in format preview only (skip contenteditable panel 2)
        if (sourceId !== 'editor-preview-fmt-body') {
            const fmtPreview = document.getElementById('editor-preview-fmt-body');
            if (fmtPreview) this._highlightInHtml(fmtPreview, searchText);
        }
    },

    _highlightInCM(view, text) {
        // Find the text in the CM document and scroll to + select it
        const doc = view.state.doc.toString();
        const idx = doc.indexOf(text);
        if (idx === -1) {
            // Try stripped version (markdown has * for italic, HTML has tags)
            const stripped = text.replace(/[*_]/g, '');
            const idx2 = doc.replace(/[*_]/g, '').indexOf(stripped);
            if (idx2 === -1) return;
            // Map stripped position back to original — approximate by using same offset
            view.dispatch({
                selection: { anchor: idx2, head: idx2 + text.length },
                effects: CM.EditorView.scrollIntoView(idx2, { y: 'center' }),
            });
            return;
        }
        view.dispatch({
            selection: { anchor: idx, head: idx + text.length },
            effects: CM.EditorView.scrollIntoView(idx, { y: 'center' }),
        });
    },

    _highlightInHtml(container, text) {
        // Walk text nodes and wrap first match in a <mark>
        const walker = document.createTreeWalker(container, NodeFilter.SHOW_TEXT);
        let accumulated = '';
        const nodes = [];

        while (walker.nextNode()) {
            nodes.push({ node: walker.currentNode, start: accumulated.length });
            accumulated += walker.currentNode.textContent;
        }

        const matchIdx = accumulated.indexOf(text);
        if (matchIdx === -1) return;

        // Find which text node(s) contain the match
        for (const { node, start } of nodes) {
            const nodeEnd = start + node.textContent.length;
            if (nodeEnd <= matchIdx) continue;
            if (start >= matchIdx + text.length) break;

            const localStart = Math.max(0, matchIdx - start);
            const localEnd = Math.min(node.textContent.length, matchIdx + text.length - start);

            const range = document.createRange();
            range.setStart(node, localStart);
            range.setEnd(node, localEnd);

            const mark = document.createElement('mark');
            mark.className = 'selection-sync-highlight';
            mark.style.cssText = 'background: rgba(255, 200, 50, 0.4); border-radius: 2px;';
            range.surroundContents(mark);
            this._selectionHighlights.push(mark);

            // Scroll the first highlight into view
            if (this._selectionHighlights.length === 1) {
                mark.scrollIntoView({ block: 'center', behavior: 'smooth' });
            }
        }
    },

    _clearSelectionHighlights() {
        for (const mark of this._selectionHighlights) {
            const parent = mark.parentNode;
            if (parent) {
                parent.replaceChild(document.createTextNode(mark.textContent), mark);
                parent.normalize();  // merge adjacent text nodes
            }
        }
        this._selectionHighlights = [];
    },

    _syncScroll(sourceId) {
        if (this._syncingScroll || this._wysiwygEditSource) return;
        this._syncingScroll = true;
        clearTimeout(this._scrollLockTimer);
        try {
            // Get scroll percentage from whichever panel triggered the scroll
            let pct = 0;
            const _pct = (el) => el.scrollTop / (el.scrollHeight - el.clientHeight || 1);

            if (sourceId === 'cm-editor') {
                const s = this.cmView?.dom.querySelector('.cm-scroller');
                if (s) pct = _pct(s);
            } else if (sourceId === 'cm-source') {
                const s = this.cmSourceView?.dom.querySelector('.cm-scroller');
                if (s) pct = _pct(s);
            } else {
                const el = document.getElementById(sourceId);
                if (el) pct = _pct(el);
            }

            const _apply = (el) => { el.scrollTop = pct * (el.scrollHeight - el.clientHeight); };

            // Sync to CM editor (panel 1)
            if (sourceId !== 'cm-editor') {
                const s = this.cmView?.dom.querySelector('.cm-scroller');
                if (s) _apply(s);
            }
            // Sync to CM source view (panel 3)
            if (sourceId !== 'cm-source' && this.cmSourceView) {
                const s = this.cmSourceView.dom.querySelector('.cm-scroller');
                if (s) _apply(s);
            }
            // Sync to HTML preview panels (panel 2 + panel 4)
            for (const id of ['editor-preview-rendered-body', 'editor-preview-fmt-body']) {
                if (id === sourceId) continue;
                const el = document.getElementById(id);
                if (el) _apply(el);
            }
        } finally {
            // Keep the lock active for 60ms so cascading scroll events
            // (fired async by the browser after setting scrollTop) are ignored
            this._scrollLockTimer = setTimeout(() => { this._syncingScroll = false; }, 60);
        }
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

        // Debounced preview — if WYSIWYG is source, still refresh format panels (3+4)
        // but skip panel 2 (the user is actively editing there)
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
            // Save scroll positions before re-rendering
            const savedScrolls = {};
            for (const id of ['editor-preview-rendered-body', 'editor-preview-source-body', 'editor-preview-fmt-body']) {
                const el = document.getElementById(id);
                if (el) savedScrolls[id] = el.scrollTop;
            }
            // Save iframe internal scroll (styled_html)
            let savedIframePct = 0;
            if (this.previewFormat === 'styled_html' && fmtPreview) {
                try {
                    const oldIframe = fmtPreview.querySelector('iframe');
                    const iDoc = oldIframe?.contentDocument?.documentElement;
                    if (iDoc && iDoc.scrollHeight > iDoc.clientHeight) {
                        savedIframePct = iDoc.scrollTop / (iDoc.scrollHeight - iDoc.clientHeight);
                    }
                } catch {}
            }

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

            // Panel 2: WYSIWYG editor (contenteditable)
            // Skip panel 2 update if the user is actively editing in it
            if (this._wysiwygEditSource !== 'wysiwyg') {
                if (mdData) {
                    this._wysiwygEditSource = 'cm';
                    const html = mdData.html || '';
                    // Wrap front matter (everything before first <hr />) as non-editable
                    const hrIdx = html.indexOf('<hr');
                    if (hrIdx > 0) {
                        const frontHtml = html.substring(0, hrIdx);
                        const bodyHtml = html.substring(hrIdx);
                        mdPreview.innerHTML = '<div class="preview-html">' +
                            '<div contenteditable="false" class="wysiwyg-frontmatter">' + frontHtml + '</div>' +
                            bodyHtml + '</div>';
                    } else {
                        mdPreview.innerHTML = '<div class="preview-html">' + html + '</div>';
                    }
                    setTimeout(() => { this._wysiwygEditSource = null; }, 0);
                } else {
                    mdPreview.innerHTML = `<p style="color:var(--color-error)">MD preview failed</p>`;
                }
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
                    // Attach scroll + selection sync to the new CM source view
                    const srcScroller = this.cmSourceView.dom.querySelector('.cm-scroller');
                    if (srcScroller) {
                        srcScroller.addEventListener('scroll', () => this._syncScroll('cm-source'));
                        srcScroller.addEventListener('mouseup', () => this._syncSelectionFromCMSource());
                    }
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
                        // Reuse existing iframe if possible (avoids full recreate + scroll loss)
                        let iframe = fmtPreview.querySelector('iframe.preview-iframe');
                        if (!iframe) {
                            fmtPreview.innerHTML = '<iframe class="preview-iframe" sandbox="allow-same-origin"></iframe>';
                            iframe = fmtPreview.querySelector('iframe');
                        }
                        iframe.srcdoc = fmtData.preview_html || fmtData.html || '';
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

            // Restore scroll positions after re-rendering
            for (const [id, pos] of Object.entries(savedScrolls)) {
                const el = document.getElementById(id);
                if (el) el.scrollTop = pos;
            }
            // For styled_html iframe, restore internal scroll after it loads
            if (this.previewFormat === 'styled_html' && fmtPreview && savedIframePct > 0) {
                const iframe = fmtPreview.querySelector('iframe');
                if (iframe) {
                    iframe.addEventListener('load', () => {
                        try {
                            const iDoc = iframe.contentDocument?.documentElement;
                            if (iDoc) {
                                iDoc.scrollTop = savedIframePct * (iDoc.scrollHeight - iDoc.clientHeight);
                            }
                        } catch {}
                    }, { once: true });
                }
            }
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
    // Format Source
    // ---------------------------------------------------------------------------

    async formatSource() {
        if (typeof html_beautify === 'undefined' && typeof css_beautify === 'undefined') {
            this._updateStatus('Formatter not loaded');
            return;
        }

        const opts = { indent_size: 4, wrap_line_length: 0, preserve_newlines: true, max_preserve_newlines: 2 };
        const cssOpts = { indent_size: 4 };
        let formatted = false;

        // Format the CM source view (panel 3) — HTML or BBCode
        if (this.cmSourceView) {
            const content = this.cmSourceView.state.doc.toString();
            const isHtml = content.includes('<') && content.includes('>');
            if (isHtml && typeof html_beautify !== 'undefined') {
                const pretty = html_beautify(content, opts);
                this._updateCmContent(this.cmSourceView, pretty);
                formatted = true;

                // Save formatted content to disk
                this._updateStatus('Formatting + saving...');
                try {
                    const resp = await fetch(`/api/editor/stories/${encodeURIComponent(this.storyName)}/format-file`, {
                        method: 'PUT',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ format: this.previewFormat, content: pretty }),
                    });
                    if (resp.ok) {
                        const data = await resp.json();
                        this._updateStatus(`Formatted + saved ${data.file} (${data.bytes.toLocaleString()}b)`);
                    } else {
                        const errText = await resp.text();
                        let detail = `HTTP ${resp.status}`;
                        try { const j = JSON.parse(errText); detail = j.detail || j.error || detail; } catch {}
                        this._updateStatus(`Formatted (save failed: ${detail})`);
                    }
                } catch (err) {
                    this._updateStatus(`Formatted (save error: ${err.message})`);
                }
                return;
            }
        }

        // Format the CSS editor if open
        if (this.cmCssView && this.themeSourceMode && typeof css_beautify !== 'undefined') {
            const content = this.cmCssView.state.doc.toString();
            const pretty = css_beautify(content, cssOpts);
            this._updateCmContent(this.cmCssView, pretty);
            formatted = true;
        }

        // Format the MD source (panel 1) — light cleanup only
        if (this.cmView && !formatted) {
            const content = this.cmView.state.doc.toString();
            const cleaned = content
                .split('\n')
                .map(line => line.trimEnd())
                .join('\n')
                .replace(/\n{3,}/g, '\n\n')
                .trim() + '\n';
            if (cleaned !== content) {
                this.cmView.dispatch({
                    changes: { from: 0, to: this.cmView.state.doc.length, insert: cleaned },
                });
                formatted = true;
            }
        }

        this._updateStatus(formatted ? 'Formatted' : 'Nothing to format');
    },

    // ---------------------------------------------------------------------------
    // Regenerate
    // ---------------------------------------------------------------------------

    async regenerate(formats) {
        // formats: null = all (skip_pdf still true), or array e.g. ["html"], ["bbcode"]
        const btn = document.getElementById('editor-regen-btn');
        if (btn) btn.disabled = true;

        // Save first if dirty
        if (this.isDirty) {
            await this.save();
        }

        const label = formats ? formats.join(', ') : 'all';
        this._updateStatus(`Regenerating ${label}...`);
        try {
            const body = { skip_pdf: true };
            if (formats) {
                body.formats = formats;
                // If explicitly requesting PDF, don't skip it
                if (formats.includes('pdf')) body.skip_pdf = false;
            }
            const resp = await fetch(`/api/editor/stories/${encodeURIComponent(this.storyName)}/regenerate`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body),
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
    // WYSIWYG Editor
    // ---------------------------------------------------------------------------

    _initTurndown() {
        if (typeof TurndownService === 'undefined') return;
        this._turndown = new TurndownService({
            headingStyle: 'atx',
            hr: '---',
            emDelimiter: '*',
            strongDelimiter: '**',
            bulletListMarker: '-',
        });

        // Chapter headings: centered <strong> paragraphs → # Heading
        this._turndown.addRule('chapterHeading', {
            filter: (node) => {
                if (node.nodeName !== 'P') return false;
                const style = node.getAttribute('style') || '';
                if (!style.includes('text-align:center') && !style.includes('text-align: center')) return false;
                const children = node.childNodes;
                return children.length === 1 && children[0].nodeName === 'STRONG';
            },
            replacement: (content, node) => {
                const text = node.textContent.trim();
                return `\n# ${text}\n`;
            },
        });

        // Centered paragraphs (subtitles, etc) — preserve as italic centered
        this._turndown.addRule('centeredParagraph', {
            filter: (node) => {
                if (node.nodeName !== 'P') return false;
                const style = node.getAttribute('style') || '';
                if (!style.includes('text-align:center') && !style.includes('text-align: center')) return false;
                const children = node.childNodes;
                // Only match single <em> child (subtitles)
                return children.length === 1 && children[0].nodeName === 'EM';
            },
            replacement: (content, node) => {
                return `\n*${node.textContent.trim()}*\n`;
            },
        });

        // Section breaks
        this._turndown.addRule('sectionBreak', {
            filter: (node) => {
                if (node.nodeName !== 'P' && node.nodeName !== 'DIV') return false;
                return (node.getAttribute('class') || '').includes('section-break') ||
                    (node.textContent.trim().match(/^[*·✦\s]+$/) && (node.getAttribute('style') || '').includes('center'));
            },
            replacement: () => '\n---\n',
        });

        // Non-editable front matter — skip entirely
        this._turndown.addRule('frontMatterBlock', {
            filter: (node) => {
                return node.getAttribute && node.getAttribute('contenteditable') === 'false';
            },
            replacement: () => '',
        });

        // HR elements
        this._turndown.addRule('hrRule', {
            filter: 'hr',
            replacement: () => '\n---\n',
        });
    },

    _cacheFrontMatter(markdown) {
        const lines = markdown.split('\n');
        let bodyIdx = -1;
        for (let i = 0; i < lines.length; i++) {
            if (lines[i].trim() === '<!-- @body -->') { bodyIdx = i; break; }
        }
        if (bodyIdx >= 0) {
            // Include the @body line and the --- after it
            let endIdx = bodyIdx;
            for (let i = bodyIdx + 1; i < lines.length && i <= bodyIdx + 2; i++) {
                if (lines[i].trim() === '---' || lines[i].trim() === '') endIdx = i;
                else break;
            }
            this._frontMatterMd = lines.slice(0, endIdx + 1).join('\n');
            this._bodyStartLine = endIdx + 1;
        } else {
            this._frontMatterMd = '';
            this._bodyStartLine = 0;
        }
    },

    _initWysiwygToolbar() {
        const toolbar = document.getElementById('wysiwyg-toolbar');
        if (!toolbar) return;
        toolbar.querySelectorAll('button[data-cmd]').forEach(btn => {
            btn.addEventListener('mousedown', (e) => {
                e.preventDefault();
                this._execWysiwygCmd(btn.dataset.cmd);
            });
        });
        toolbar.querySelectorAll('button[data-anchor]').forEach(btn => {
            btn.addEventListener('mousedown', (e) => {
                e.preventDefault();
                this._insertAnchor(btn.dataset.anchor);
            });
        });
    },

    _insertAnchor(type) {
        const anchors = {
            'title': '<!-- @title -->',
            'subtitle': '<!-- @subtitle -->',
            'body': '<!-- @body -->',
            'warning': '<!-- @warning -->',
            'text-sent': '<!-- @text-sent -->\n\n<!-- @text-end -->',
            'text-received': '<!-- @text-received -->\n\n<!-- @text-end -->',
            'phone': '<!-- @phone -->\n\n<!-- @phone-end -->',
            'story-end': '<!-- @story-end -->',
        };
        const text = anchors[type];
        if (!text || !this._cm) return;
        const cursor = this._cm.state.selection.main.head;
        this._cm.dispatch({
            changes: { from: cursor, insert: '\n' + text + '\n' },
            selection: { anchor: cursor + text.indexOf('\n\n') + 1 || cursor + text.length + 1 },
        });
        this._cm.focus();
    },

    _execWysiwygCmd(cmd) {
        // Don't call body.focus() — the mousedown preventDefault keeps focus in contenteditable
        switch (cmd) {
            case 'bold':
                document.execCommand('bold', false, null);
                break;
            case 'italic':
                document.execCommand('italic', false, null);
                break;
            case 'undo':
                document.execCommand('undo', false, null);
                break;
            case 'redo':
                document.execCommand('redo', false, null);
                break;
            case 'heading': {
                // Wrap current line/selection as a chapter heading
                const sel = window.getSelection();
                if (!sel.rangeCount) break;
                const text = sel.toString().trim() || 'Chapter Heading';
                document.execCommand('insertHTML', false,
                    `<p style="text-align:center"><strong>${Utils.escapeHtml(text)}</strong></p>`);
                break;
            }
            case 'hr':
                document.execCommand('insertHTML', false, '<hr />');
                break;
        }
    },

    _initWysiwygInput() {
        const body = document.getElementById('editor-preview-rendered-body');
        if (!body) return;

        body.addEventListener('input', () => {
            if (this._wysiwygEditSource === 'cm') return; // ignore CM-triggered updates
            clearTimeout(this._wysiwygSyncTimer);
            this._wysiwygSyncTimer = setTimeout(() => this._syncWysiwygToCM(), 400);
        });

        // Paste handler — sanitize to plain text with basic formatting
        body.addEventListener('paste', (e) => {
            e.preventDefault();
            const text = e.clipboardData.getData('text/plain');
            document.execCommand('insertText', false, text);
        });
    },

    _syncWysiwygToCM() {
        if (!this._turndown || !this.cmView) return;
        const body = document.getElementById('editor-preview-rendered-body');
        if (!body) return;

        this._wysiwygEditSource = 'wysiwyg';

        // Convert HTML → markdown (only the editable body, not front matter)
        let bodyMd = this._turndown.turndown(body.innerHTML);

        // Clean up: normalize multiple blank lines to double
        bodyMd = bodyMd.replace(/\n{3,}/g, '\n\n').trim();

        // Re-extract front matter from current CM content (not stale cache)
        const currentMd = this.cmView.state.doc.toString();
        const bodyMarker = '<!-- @body -->';
        const bodyMarkerIdx = currentMd.indexOf(bodyMarker);
        let frontMatter = '';
        if (bodyMarkerIdx >= 0) {
            // Include @body line + any trailing --- separator
            let endIdx = bodyMarkerIdx + bodyMarker.length;
            const after = currentMd.substring(endIdx);
            const trailMatch = after.match(/^\n(---\n|\n)/);
            if (trailMatch) endIdx += trailMatch[0].length;
            frontMatter = currentMd.substring(0, endIdx);
        }

        // Reconstruct full markdown: front matter + body
        const fullMd = frontMatter
            ? frontMatter + '\n' + bodyMd + '\n'
            : bodyMd + '\n';

        // Save CM scroll position before replacing content
        const cmScroller = this.cmView.dom.querySelector('.cm-scroller');
        const savedScroll = cmScroller ? cmScroller.scrollTop : 0;

        // Update CM editor without triggering a preview refresh
        this.cmView.dispatch({
            changes: {
                from: 0,
                to: this.cmView.state.doc.length,
                insert: fullMd,
            },
        });

        // Restore CM scroll position
        if (cmScroller) cmScroller.scrollTop = savedScroll;

        this.isDirty = true;
        this._updateWordCount(fullMd.split(/\s+/).length);

        // Clear the flag after a microtask so CM's updateListener sees it
        setTimeout(() => { this._wysiwygEditSource = null; }, 0);
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
                <h4>Text Messages</h4>
                ${colorRow('Sent Background', 'TEXT_SENT_COLOUR')}
                ${colorRow('Received Background', 'TEXT_RECEIVED_COLOUR')}
            </div>
            <div class="theme-section">
                <h4>Typography</h4>
                ${textRow('Title Shadow', 'TITLE_TEXT_SHADOW', 'text-shadow: 0 0 25px rgba(...)')}
            </div>
            <div class="theme-section">
                <h4>Decorations</h4>
                ${this._iconSelector('WARNING_ICON')}
                ${this._breakSelector('SECTION_BREAK_SYMBOL')}
            </div>
            <div class="theme-section">
                <h4>Print</h4>
                ${selectRow('Approach', 'PRINT_APPROACH', [
                    {value: 'colour-preserve', label: 'Colour Preserve (dark bg)'},
                    {value: 'grayscale', label: 'Grayscale (light bg)'},
                ])}
            </div>
        `;

        // Bind custom inputs (icon + break selectors have their own text fields)
        body.querySelectorAll('.theme-combo-select').forEach(sel => {
            const key = sel.dataset.key;
            const textInput = body.querySelector(`.theme-combo-text[data-key="${key}"]`);
            sel.addEventListener('change', () => {
                if (sel.value === '__custom__') {
                    if (textInput) textInput.style.display = '';
                } else {
                    if (textInput) { textInput.style.display = 'none'; textInput.value = sel.value; }
                    this._pushThemeUndo();
                    this.themeVars[key] = sel.value;
                    this._onThemeChange();
                }
            });
            if (textInput) {
                textInput.addEventListener('change', () => {
                    this._pushThemeUndo();
                    this.themeVars[key] = textInput.value;
                    this._onThemeChange();
                });
            }
        });

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

    _iconSelector(key) {
        const val = this.themeVars[key] || '&#9888;';
        const icons = [
            // Classic warnings
            ['&#9888;', '⚠ Warning Triangle'],
            ['&#9762;', '☢ Radioactive'],
            ['&#9763;', '☣ Biohazard'],
            ['&#9760;', '☠ Skull & Crossbones'],
            ['&#10060;', '❌ Cross Mark'],
            ['&#10071;', '❗ Exclamation'],
            // Stars & celestial
            ['&#9733;', '★ Black Star'],
            ['&#9734;', '☆ White Star'],
            ['&#10022;', '✦ Six-Point Star'],
            ['&#10023;', '✧ Open Star'],
            ['&#10038;', '✶ Six-Point Solid'],
            ['&#10041;', '✹ Twelve-Point Star'],
            ['&#10043;', '✻ Heavy Teardrop'],
            ['&#10045;', '✽ Balloon Asterisk'],
            ['&#10037;', '✵ Pinwheel Star'],
            ['&#9789;', '☽ Crescent Moon'],
            ['&#9790;', '☾ Last Quarter Moon'],
            // Geometric
            ['&#9670;', '◆ Black Diamond'],
            ['&#9671;', '◇ White Diamond'],
            ['&#9830;', '♦ Diamond Suit'],
            ['&#10070;', '❖ Black Diamond Minus'],
            ['&#9679;', '● Black Circle'],
            ['&#9675;', '○ White Circle'],
            ['&#9632;', '■ Black Square'],
            ['&#9650;', '▲ Triangle Up'],
            ['&#11044;', '⬤ Large Circle'],
            // Nature & ornamental
            ['&#10048;', '✿ Black Florette'],
            ['&#10049;', '❁ Eight-Petal Flower'],
            ['&#10053;', '❅ Tight Snowflake'],
            ['&#10054;', '❆ Heavy Snowflake'],
            ['&#9884;', '⚜ Fleur-de-lis'],
            ['&#9752;', '☘ Shamrock'],
            ['&#9773;', '☭ Hammer (industrial)'],
            // Hearts & suits
            ['&#9829;', '♥ Heart'],
            ['&#9827;', '♣ Club'],
            ['&#9824;', '♠ Spade'],
            ['&#10084;', '❤ Heavy Heart'],
            // Misc symbols
            ['&#10016;', '✠ Maltese Cross'],
            ['&#10013;', '✝ Latin Cross'],
            ['&#10014;', '✞ Outlined Cross'],
            ['&#9876;', '⚔ Crossed Swords'],
            ['&#9873;', '⚑ Black Flag'],
            ['&#9883;', '⚫ Medium Circle (dark)'],
            ['&#10026;', '✪ Circled Star'],
            ['&#10031;', '✯ Six-Point Pinwheel'],
            // Emoji-style
            ['&#128293;', '🔥 Fire'],
            ['&#128420;', '🖤 Black Heart'],
            ['&#127801;', '🌹 Rose'],
            ['&#128128;', '💀 Skull'],
            ['&#9889;', '⚡ Lightning'],
            ['&#127775;', '🌟 Glowing Star'],
        ];
        const isCustom = !icons.some(([v]) => v === val);
        const opts = icons.map(([v, l]) => `<option value="${v}" ${v === val ? 'selected' : ''}>${l}</option>`).join('');
        return `<div class="theme-row">
            <label>Warning Icon</label>
            <select data-key="${key}" class="theme-combo-select">
                ${opts}
                <option value="__custom__" ${isCustom ? 'selected' : ''}>✏ Custom...</option>
            </select>
            <input type="text" value="${val}" data-key="${key}" class="theme-combo-text theme-text" style="${isCustom ? '' : 'display:none'}" placeholder="HTML entity e.g. &#9888;">
        </div>`;
    },

    _breakSelector(key) {
        const val = this.themeVars[key] || '* &ensp; * &ensp; *';
        const breaks = [
            // Classic
            ['* &ensp; * &ensp; *', '* * * (classic)'],
            ['• • •', '• • • (bullets)'],
            ['· · · · ·', '· · · · · (dots)'],
            ['~ ~ ~', '~ ~ ~ (tildes)'],
            ['— — —', '— — — (em dashes)'],
            // Star patterns
            ['&#10022; &ensp; &#10022; &ensp; &#10022;', '✦ ✦ ✦ (solid stars)'],
            ['&#10023; &ensp; &#10023; &ensp; &#10023;', '✧ ✧ ✧ (open stars)'],
            ['&#9733; &ensp; &#10022; &ensp; &#9733;', '★ ✦ ★ (Chosen)'],
            ['· &ensp; &#10022; &ensp; ·', '· ✦ · (dot star dot)'],
            ['~ &ensp; &#10023; &ensp; ~', '~ ✧ ~ (tilde star)'],
            ['&#10022; &#11824; &#10022;', '✦ ⸰ ✦ (Abstinent Bet)'],
            ['&#10043; &ensp; &#10043; &ensp; &#10043;', '✻ ✻ ✻ (Ruins)'],
            // Diamond patterns
            ['&mdash; &#10022; &mdash;', '— ✦ — (Drumheller)'],
            ['&mdash; &#10070; &mdash;', '— ❖ — (dash diamond)'],
            ['&#9670; &middot; &#9670;', '◆ · ◆ (Extra Credit)'],
            ['&#9671; &ensp; &#9670; &ensp; &#9671;', '◇ ◆ ◇ (diamonds)'],
            ['&#9830; &ensp; &#9830; &ensp; &#9830;', '♦ ♦ ♦ (suits)'],
            // Celestial
            ['&#9789; &ensp; &#10022; &ensp; &#9790;', '☽ ✦ ☾ (Silk moons)'],
            ['&#9789; &ensp; &#9733; &ensp; &#9790;', '☽ ★ ☾ (moon star moon)'],
            ['&#9733; &ensp; &#9789; &ensp; &#9733;', '★ ☽ ★ (star moon star)'],
            ['&#10023; &ensp; &#9789; &ensp; &#10023;', '✧ ☽ ✧ (open star moon)'],
            // Ornamental
            ['&#10023; &#9884; &#10023;', '✧ ⚜ ✧ (Velvet fleur-de-lis)'],
            ['&#8258; &#9830; &#8258;', '⁂ ♦ ⁂ (NSES)'],
            ['&#9884; &ensp; &#9884; &ensp; &#9884;', '⚜ ⚜ ⚜ (three fleur-de-lis)'],
            ['&#10048; &ensp; &#10048; &ensp; &#10048;', '✿ ✿ ✿ (flowers)'],
            ['&#10049; &ensp; &#10049; &ensp; &#10049;', '❁ ❁ ❁ (eight-petal)'],
            ['&#9752; &ensp; &#9752; &ensp; &#9752;', '☘ ☘ ☘ (shamrocks)'],
            // Rules & lines
            ['─── &#10022; ───', '─── ✦ ─── (ruled star)'],
            ['─── &#10070; ───', '─── ❖ ─── (ruled diamond)'],
            ['─── &#9884; ───', '─── ⚜ ─── (ruled fleur-de-lis)'],
            ['═══════', '═══════ (double rule)'],
            ['───────', '─────── (single rule)'],
            ['─ · ─ · ─', '─ · ─ · ─ (morse)'],
            // Singles & pairs
            ['&#8258;', '⁂ (asterism)'],
            ['&#10087;', '❧ (rotated floral)'],
            ['&#10086;', '❦ (floral heart)'],
            ['§', '§ (section sign)'],
            ['&#8224; &ensp; &#8224; &ensp; &#8224;', '† † † (daggers)'],
            ['&#8225; &ensp; &#8225; &ensp; &#8225;', '‡ ‡ ‡ (double daggers)'],
            ['&#8734;', '∞ (infinity)'],
            ['&#9876;', '⚔ (crossed swords)'],
            // Hearts
            ['&#9829; &ensp; &#9829; &ensp; &#9829;', '♥ ♥ ♥ (hearts)'],
            ['&#10084;', '❤ (heavy heart)'],
            ['&#9825; &ensp; &#9829; &ensp; &#9825;', '♡ ♥ ♡ (open heart)'],
            // Arrows & misc
            ['&#10148; &ensp; &#10148; &ensp; &#10148;', '➤ ➤ ➤ (arrows)'],
            ['&#8226; &#10022; &#8226;', '• ✦ • (bullet star)'],
            ['&#10040; &ensp; &#10040; &ensp; &#10040;', '✸ ✸ ✸ (heavy stars)'],
            ['&#10059;', '❋ (heavy asterisk)'],
            ['&#10056; &ensp; &#10056; &ensp; &#10056;', '❈ ❈ ❈ (asterisk flowers)'],
        ];
        const isCustom = !breaks.some(([v]) => v === val);
        const opts = breaks.map(([v, l]) => `<option value="${v}" ${v === val ? 'selected' : ''}>${l}</option>`).join('');
        return `<div class="theme-row">
            <label>Section Break</label>
            <select data-key="${key}" class="theme-combo-select">
                ${opts}
                <option value="__custom__" ${isCustom ? 'selected' : ''}>✏ Custom...</option>
            </select>
            <input type="text" value="${val}" data-key="${key}" class="theme-combo-text theme-text" style="${isCustom ? '' : 'display:none'}" placeholder="HTML entities or text">
        </div>`;
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
                const payload = { variables: this.themeVars };
                resp = await fetch(`/api/editor/stories/${encodeURIComponent(this.storyName)}/theme`, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload),
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
