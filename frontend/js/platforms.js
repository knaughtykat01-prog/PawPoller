/* ===========================================================================
 * PawPoller — canonical platform registry
 * ---------------------------------------------------------------------------
 * Single source of truth for the 11 platforms. Loaded FIRST (before every
 * other frontend script) so the command palette, shell, Platforms hub and the
 * context-bar switcher all read `window.PLATFORMS` instead of re-declaring the
 * list (it used to be hand-duplicated in 5 places). Brand colours are the
 * theme-invariant `--platform-*` tokens from tokens.css.
 * ===========================================================================*/
(function () {
    const PLATFORMS = [
        { code: 'ib',   label: 'Inkbunny',     emoji: '\u{1F43E}', color: 'var(--platform-ib)',   pollOnly: false },
        { code: 'fa',   label: 'FurAffinity',  emoji: '\u{1F98A}', color: 'var(--platform-fa)',   pollOnly: false },
        { code: 'ws',   label: 'Weasyl',       emoji: '\u{1F98E}', color: 'var(--platform-ws)',   pollOnly: false },
        { code: 'sf',   label: 'SoFurry',      emoji: '\u{1F4DC}', color: 'var(--platform-sf)',   pollOnly: false },
        { code: 'sqw',  label: 'SquidgeWorld', emoji: '\u{1F999}', color: 'var(--platform-sqw)',  pollOnly: false },
        { code: 'ao3',  label: 'AO3',          emoji: '\u{1F4D6}', color: 'var(--platform-ao3)',  pollOnly: false },
        { code: 'da',   label: 'DeviantArt',   emoji: '\u{1F3A8}', color: 'var(--platform-da)',   pollOnly: false },
        { code: 'wp',   label: 'Wattpad',      emoji: '\u{1F4D3}', color: 'var(--platform-wp)',   pollOnly: true  },
        { code: 'ik',   label: 'Itaku',        emoji: '\u{1F5BC}', color: 'var(--platform-ik)',   pollOnly: true  },
        { code: 'bsky', label: 'Bluesky',      emoji: '\u{1F98B}', color: 'var(--platform-bsky)', pollOnly: true  },
        { code: 'tw',   label: 'X / Twitter',  emoji: '\u{1F426}', color: 'var(--platform-tw)',   pollOnly: true  },
    ];

    const byCode = {};
    PLATFORMS.forEach(p => { byCode[p.code] = p; });

    /* platformRoute(code, sub) — hash route for a platform sub-view.
     *
     * Inkbunny is the legacy "default" platform: its dashboard is `#/ib`, but
     * its submissions/compare/detail live at UN-prefixed routes
     * (`#/submissions`, `#/compare`, `#/submission/{id}`). Every other platform
     * is `#/{code}`, `#/{code}/submissions`, `#/{code}/compare`. The router
     * (app.js route()) special-cases IB the same way, so this helper is the one
     * place that knowledge is encoded for the nav/switcher/sub-tabs.
     *
     *   sub: undefined → dashboard, 'submissions', or 'compare'
     */
    function platformRoute(code, sub) {
        if (!sub) return '#/' + code;
        if (code === 'ib') return '#/' + sub;
        return '#/' + code + '/' + sub;
    }

    window.PLATFORMS = PLATFORMS;
    window.platformByCode = function (code) { return byCode[code] || null; };
    window.platformRoute = platformRoute;
})();
