/* ===========================================================================
 * PawPoller — canonical platform registry
 * ---------------------------------------------------------------------------
 * Single source of truth for the 17 platforms. Loaded FIRST (before every
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
        { code: 'mast', label: 'Mastodon',     emoji: '\u{1F418}', color: 'var(--platform-mast)', pollOnly: true  },
        { code: 'tum',  label: 'Tumblr',       emoji: '\u{1F4D8}', color: 'var(--platform-tum)',  pollOnly: true  },
        { code: 'pix',  label: 'Pixiv',        emoji: '\u{1F58C}', color: 'var(--platform-pix)',  pollOnly: true  },
        { code: 'thr',  label: 'Threads',      emoji: '\u{1F9F5}', color: 'var(--platform-thr)',  pollOnly: true  },
        { code: 'ig',   label: 'Instagram',    emoji: '\u{1F4F8}', color: 'var(--platform-ig)',   pollOnly: true  },
        { code: 'e621', label: 'e621',         emoji: '\u{1F43E}', color: 'var(--platform-e621)', pollOnly: false },
    ];

    // Display order is alphabetical by label (case-insensitive) everywhere that
    // reads window.PLATFORMS — the Platforms hub, command palette, context-bar
    // switcher and Overview tiles. Sort once here so all consumers agree.
    PLATFORMS.sort((a, b) => a.label.toLowerCase().localeCompare(b.label.toLowerCase()));

    const byCode = {};
    PLATFORMS.forEach(p => { byCode[p.code] = p; });

    // Each platform's official logo, bundled under /img/platforms/. Itaku and
    // Weasyl ship SVGs (scalable); the rest are PNGs. Trademarks of their owners
    // — see the disclaimer on the Platforms hub.
    const _svgLogos = ['ik', 'ws', 'mast', 'tum', 'pix', 'thr', 'ig', 'e621'];
    PLATFORMS.forEach(p => { p.logo = '/img/platforms/' + p.code + (_svgLogos.includes(p.code) ? '.svg' : '.png'); });

    /* platformRoute(code, sub) — hash route for a platform sub-view.
     *
     * Every platform (including Inkbunny, as of 2.68.0) is uniform:
     * `#/{code}`, `#/{code}/submissions`, `#/{code}/compare`,
     * `#/{code}/submission/{id}`. The top-level `#/submissions` is now the
     * cross-platform Submissions hub, not IB's table.
     *
     *   sub: undefined → dashboard, 'submissions', or 'compare'
     */
    function platformRoute(code, sub) {
        if (!sub) return '#/' + code;
        return '#/' + code + '/' + sub;
    }

    window.PLATFORMS = PLATFORMS;
    window.platformByCode = function (code) { return byCode[code] || null; };
    window.platformRoute = platformRoute;
})();
