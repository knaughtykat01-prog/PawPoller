// In-app EPUB viewer logic. Extracted to its own file so the page's
// inline-script CSP hash doesn't have to maintain a second entry —
// 'self' covers /js/ and /vendor/, so external files load freely.
(function () {
    const params = new URLSearchParams(window.location.search);
    const story = params.get('story');
    const file  = params.get('file');
    const status = document.getElementById('viewer-status');
    const titleEl = document.getElementById('viewer-title');
    const locEl   = document.getElementById('viewer-location');
    const dl      = document.getElementById('btn-download');

    function fail(msg) {
        status.textContent = msg;
        status.classList.add('error');
    }

    if (!story || !file) {
        fail('Missing ?story or ?file in URL.');
        return;
    }

    const epubUrl = `/api/posting/file?story=${encodeURIComponent(story)}&file=${encodeURIComponent(file)}`;
    dl.href = epubUrl;
    titleEl.textContent = file.split('/').pop().replace(/\.epub$/i, '');

    // Resolve parent-page CSS tokens to concrete colours — the EPUB
    // renders in a sandboxed iframe that doesn't inherit CSS custom
    // properties from this page, so var(--…) references injected via
    // rendition.themes would fall back to defaults.
    const cs = getComputedStyle(document.documentElement);
    const bg     = cs.getPropertyValue('--bg-primary').trim()   || '#fafaf6';
    const text   = cs.getPropertyValue('--text-primary').trim() || '#1a1a1a';
    const accent = cs.getPropertyValue('--accent').trim()       || '#9b7dff';

    // openAs: 'epub' forces zip-archive parsing. Without it, epub.js
    // sniffs the URL's file extension to pick archive vs. directory
    // mode — and our URL path is `/api/posting/file` (the .epub lives
    // in the query string), so the sniff fails and the load hangs
    // trying to read META-INF/container.xml as a directory. Same-
    // origin fetch carries the pp_session cookie automatically.
    const book = ePub(epubUrl, { openAs: 'epub' });
    const rendition = book.renderTo('viewer', {
        width:  '100%',
        height: '100%',
        flow:   'paginated',
        spread: 'auto',
    });

    rendition.themes.default({
        'body': {
            'background': bg,
            'color':      text,
            'font-family': "'Crimson Pro', Georgia, 'Times New Roman', serif",
            'line-height': '1.55',
            'padding':    '0 1em',
        },
        'p': { 'margin': '0 0 0.8em 0' },
        'a': { 'color': accent },
        'h1, h2, h3, h4': { 'color': text },
    });

    rendition.display().then(() => {
        status.style.display = 'none';
    }).catch((err) => {
        fail('Failed to open EPUB: ' + (err && err.message ? err.message : err));
    });

    book.loaded.metadata.then((meta) => {
        if (meta && meta.title) titleEl.textContent = meta.title;
    }).catch(() => { /* ignore — title falls back to filename */ });

    // Pagination/location indicator. Generated on the fly the first
    // time the book is rendered.
    book.ready.then(() => book.locations.generate(1024)).then(() => {
        updateLocation();
    }).catch(() => { /* locations are optional */ });

    function updateLocation() {
        try {
            const loc = rendition.currentLocation();
            if (!loc || !loc.start) return;
            const cfi = loc.start.cfi;
            const pct = book.locations && book.locations.length()
                ? Math.round(book.locations.percentageFromCfi(cfi) * 100)
                : null;
            locEl.textContent = pct !== null ? pct + '%' : '';
        } catch (e) { /* ignore */ }
    }

    rendition.on('relocated', updateLocation);

    const prev = () => rendition.prev();
    const next = () => rendition.next();

    document.getElementById('btn-prev').addEventListener('click', prev);
    document.getElementById('btn-next').addEventListener('click', next);
    document.getElementById('tap-prev').addEventListener('click', prev);
    document.getElementById('tap-next').addEventListener('click', next);
    document.getElementById('btn-close').addEventListener('click', () => window.close());

    document.addEventListener('keydown', (e) => {
        if (e.key === 'ArrowLeft')  prev();
        if (e.key === 'ArrowRight') next();
    });

    rendition.on('keyup', (e) => {
        if (e.key === 'ArrowLeft')  prev();
        if (e.key === 'ArrowRight') next();
    });
})();
