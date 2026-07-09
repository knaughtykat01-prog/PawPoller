/* PawPoller getting-started tour — a lightweight coach-mark / spotlight
 * overlay with zero dependencies.
 *
 * Design choices worth knowing across sessions:
 *   - Every step targets *persistent shell chrome* (the sidebar nav items,
 *     the poll badge, the footer help button) rather than route-specific
 *     content. Those elements live in the static index.html, so the tour
 *     never races an async route render and never breaks when a page's
 *     internals change. The trade-off: the tour teaches "where things live",
 *     not deep per-screen workflows.
 *   - The dim + spotlight is done with a single box-shadow trick: `.pp-tour-spot`
 *     is a small box positioned over the target whose enormous spread shadow
 *     (`0 0 0 9999px …`) paints everything *outside* it dark. A separate
 *     transparent `.pp-tour-blocker` swallows background clicks so the tour
 *     drives navigation via its own Next/Back buttons. Centered steps (no
 *     target) hide the spot and dim the blocker instead.
 *   - "Seen" is a per-browser localStorage flag (`pp_tour_done`). It gates the
 *     auto-fire only; replaying from the sidebar "?" always works regardless.
 *
 * Public API (window.Tour):
 *   start({ auto })  begin the tour (auto=true suppresses nothing today but
 *                    marks the run as the first-time auto-fire for analytics)
 *   end(completed)   tear down + persist the seen flag
 *   isDone()         has the user seen/dismissed it before
 */
window.Tour = (function () {
    'use strict';

    const DONE_KEY = 'pp_tour_done';

    /* The steps. Order flows the way a new user actually moves: connect →
     * see your library → publish → measure → configure → replay. Keep the
     * body copy short — this is a 60-second orientation, not a manual. */
    const STEPS = [
        {
            target: null,
            title: 'Welcome to PawPoller 👋',
            body: 'PawPoller tracks and publishes your stories and art across 15 sites from one place. Here’s a quick tour of the essentials — about a minute.',
        },
        {
            target: '.nav-link[data-page="platforms"]',
            title: 'Platforms',
            body: 'Start here. Connect the sites you use — Inkbunny, FurAffinity, AO3, Bluesky and more. PawPoller only ever tracks the platforms you connect.',
        },
        {
            target: '.nav-link[data-page="submissions"]',
            title: 'Submissions',
            body: 'Every work you track — stories and artwork alike — lives here as one library, with views, faves and comments pulled in from each platform.',
        },
        {
            target: '.nav-link[data-page="posting"]',
            title: 'Stories',
            body: 'Publish a story to several platforms at once, and keep them in sync when you edit — no re-uploading to each site by hand.',
        },
        {
            target: '.nav-link[data-page="editor"]',
            title: 'Story Editor',
            body: 'Write or import a story, tag it per platform, then run a Publish Check to catch problems <em>before</em> anything goes live.',
        },
        {
            target: '.nav-link[data-page="analytics"]',
            title: 'Analytics',
            body: 'Views, favourites and comments over time — combined across every platform, or broken down site by site.',
        },
        {
            target: '#poll-status-mini',
            title: 'Polling',
            body: 'PawPoller checks your platforms on a schedule and refreshes these numbers on its own. This badge shows the current cycle at a glance.',
        },
        {
            target: '.nav-link[data-page="settings"]',
            title: 'Settings',
            body: 'Connect accounts, set how often each platform is polled, schedule posts, and secure the dashboard — it’s all in here.',
        },
        {
            target: '#help-tour-btn',
            title: 'Replay anytime',
            body: 'That’s the tour. Tap this “?” whenever you’d like to run through it again.',
        },
        {
            target: null,
            title: 'You’re all set 🎉',
            body: 'The best first step is to connect a platform, then add your first story.<br><br><a href="#/platforms" class="pp-tour-link" data-tour-go>Connect a platform →</a>',
            cta: 'Finish',
        },
    ];

    let _idx = 0;
    let _auto = false;
    let _blocker = null, _spot = null, _pop = null;
    let _prevSidebar = null;
    let _onResize = null, _onKey = null;
    let _running = false;

    function el(tag, cls) { const n = document.createElement(tag); n.className = cls; return n; }
    function isMobile() { return document.documentElement.dataset.mobile === '1'; }

    /* Force the sidebar visible + expanded for the duration of the tour so
     * its nav items are legible under the spotlight, then restore exactly
     * what the user had (collapsed rail on desktop, off-canvas on mobile). */
    function forceSidebarOpen() {
        const sb = document.querySelector('.sidebar');
        if (!sb) return;
        _prevSidebar = { collapsed: sb.classList.contains('collapsed'), open: sb.classList.contains('open') };
        sb.classList.remove('collapsed');
        sb.classList.add('open');
        document.getElementById('sidebar-overlay')?.classList.remove('open');
    }
    function restoreSidebar() {
        const sb = document.querySelector('.sidebar');
        if (!sb || !_prevSidebar) return;
        sb.classList.toggle('collapsed', _prevSidebar.collapsed);
        sb.classList.toggle('open', _prevSidebar.open);
        _prevSidebar = null;
    }

    /* Resolve a target selector, retrying briefly in case a step navigated
     * to a route whose element hasn't rendered yet. Chrome targets resolve
     * on the first try; the retry is insurance for any future route steps. */
    async function findTarget(sel, tries) {
        if (!sel) return null;
        tries = tries || 12;
        for (let i = 0; i < tries; i++) {
            const t = document.querySelector(sel);
            if (t) return t;
            await new Promise(r => setTimeout(r, 60));
        }
        return null;
    }

    function renderPop(step) {
        const n = _idx + 1, total = STEPS.length;
        const isFirst = _idx === 0, isLast = _idx === total - 1;
        _pop.innerHTML =
            '<div class="pp-tour-pop-head">'
                + '<span class="pp-tour-step">' + n + ' / ' + total + '</span>'
                + '<button class="pp-tour-x" type="button" aria-label="Close tour">&times;</button>'
            + '</div>'
            + '<div class="pp-tour-pop-title">' + step.title + '</div>'
            + '<div class="pp-tour-pop-body">' + step.body + '</div>'
            + '<div class="pp-tour-pop-foot">'
                + (isLast ? '<span></span>' : '<button class="pp-tour-skip" type="button">Skip</button>')
                + '<div class="pp-tour-nav">'
                    + (isFirst ? '' : '<button class="pp-tour-back" type="button">Back</button>')
                    + '<button class="pp-tour-next" type="button">' + (isLast ? (step.cta || 'Finish') : 'Next') + '</button>'
                + '</div>'
            + '</div>';

        _pop.querySelector('.pp-tour-x').onclick = () => end(false);
        const skip = _pop.querySelector('.pp-tour-skip'); if (skip) skip.onclick = () => end(false);
        const back = _pop.querySelector('.pp-tour-back'); if (back) back.onclick = () => prev();
        _pop.querySelector('.pp-tour-next').onclick = () => (isLast ? end(true) : next());
        /* Any in-body link (e.g. "Connect a platform") also closes the tour;
         * its href handles the actual navigation. */
        _pop.querySelectorAll('.pp-tour-link').forEach(a => a.addEventListener('click', () => end(true)));
    }

    function positionPop(r) {
        const vw = window.innerWidth, vh = window.innerHeight;
        const pw = _pop.offsetWidth, ph = _pop.offsetHeight, gap = 14;
        let left, top;
        if (isMobile()) {
            left = Math.max(12, (vw - pw) / 2);
            top = Math.max(12, vh - ph - 88);          /* clear the bottom nav */
        } else if (r.right < vw * 0.45) {
            left = r.right + gap;                        /* sidebar target → popover to its right */
            top = Math.min(Math.max(8, r.top), vh - ph - 8);
        } else if (vh - r.bottom > ph + gap) {
            top = r.bottom + gap;
            left = Math.min(Math.max(8, r.left + r.width / 2 - pw / 2), vw - pw - 8);
        } else {
            top = Math.max(8, r.top - ph - gap);
            left = Math.min(Math.max(8, r.left + r.width / 2 - pw / 2), vw - pw - 8);
        }
        _pop.style.left = left + 'px';
        _pop.style.top = top + 'px';
    }

    function position(target) {
        const step = STEPS[_idx];
        target = target || (step.target ? document.querySelector(step.target) : null);
        if (!target) {
            _spot.style.display = 'none';
            _blocker.classList.add('pp-tour-blocker--dim');
            _pop.classList.add('pp-tour-pop--center');
            _pop.style.transform = 'translate(-50%, -50%)';
            _pop.style.left = '50%';
            _pop.style.top = '50%';
            return;
        }
        _spot.style.display = 'block';
        _blocker.classList.remove('pp-tour-blocker--dim');
        _pop.classList.remove('pp-tour-pop--center');
        _pop.style.transform = '';
        const r = target.getBoundingClientRect();
        const pad = 6;
        _spot.style.left = Math.max(0, r.left - pad) + 'px';
        _spot.style.top = Math.max(0, r.top - pad) + 'px';
        _spot.style.width = (r.width + pad * 2) + 'px';
        _spot.style.height = (r.height + pad * 2) + 'px';
        positionPop(r);
    }

    async function show(i) {
        _idx = Math.max(0, Math.min(STEPS.length - 1, i));
        const step = STEPS[_idx];
        if (step.route && location.hash.replace(/^#\/?/, '') !== step.route.replace(/^#\/?/, '')) {
            location.hash = step.route;
            await new Promise(r => setTimeout(r, 250));
        }
        const target = await findTarget(step.target);
        if (target && target.scrollIntoView) target.scrollIntoView({ block: 'nearest' });
        renderPop(step);
        position(target);
    }

    function next() { if (_idx < STEPS.length - 1) show(_idx + 1); else end(true); }
    function prev() { if (_idx > 0) show(_idx - 1); }

    function start(opts) {
        if (_running) return;
        _running = true;
        _auto = !!(opts && opts.auto);
        _idx = 0;
        forceSidebarOpen();
        document.documentElement.classList.add('pp-tour-active');

        _blocker = el('div', 'pp-tour-blocker');
        _spot = el('div', 'pp-tour-spot');
        _pop = el('div', 'pp-tour-pop');
        /* Clicking the dim background does nothing (swallow it) so the user
         * can't half-navigate out from under the overlay. */
        _blocker.addEventListener('click', (e) => e.stopPropagation());
        document.body.appendChild(_blocker);
        document.body.appendChild(_spot);
        document.body.appendChild(_pop);

        _onResize = () => position();
        window.addEventListener('resize', _onResize);
        window.addEventListener('scroll', _onResize, true);
        _onKey = (e) => {
            if (e.key === 'Escape') end(false);
            else if (e.key === 'ArrowRight') next();
            else if (e.key === 'ArrowLeft') prev();
        };
        document.addEventListener('keydown', _onKey);

        show(0);
    }

    function end(completed) {
        if (!_running) return;
        _running = false;
        try { localStorage.setItem(DONE_KEY, '1'); } catch (e) { /* private mode — fine, it'll just re-offer */ }
        if (_onResize) {
            window.removeEventListener('resize', _onResize);
            window.removeEventListener('scroll', _onResize, true);
            _onResize = null;
        }
        if (_onKey) { document.removeEventListener('keydown', _onKey); _onKey = null; }
        [_blocker, _spot, _pop].forEach(n => n && n.remove());
        _blocker = _spot = _pop = null;
        document.documentElement.classList.remove('pp-tour-active');
        restoreSidebar();
        _idx = 0;
    }

    function isDone() {
        try { return localStorage.getItem(DONE_KEY) === '1'; } catch (e) { return false; }
    }

    return { start, end, isDone };
})();
