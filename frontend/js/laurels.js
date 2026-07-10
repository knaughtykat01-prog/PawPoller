/* ── Laurels — achievements & milestones (concept-layer Slice C · "Den") ──────
 *
 * A motivational view: the reward side of all the numbers. Big view-milestone
 * tracker ("your den has been visited N times") with a progress bar to the next
 * rung, a grid of earned/locked medals, per-persona trophy cards ("account
 * medals"), and a light publishing-rhythm strip.
 *
 * Path A — reuses the real endpoints, adds NO backend:
 *   - API.getPersonas()      → normalized cross-platform totals + per-persona breakdown
 *   - API.getPreferences()   → the app's existing milestone ladders (reused as medal rungs)
 *   - API.getWorks()         → catalogue medals (first story/art, N works, platform spread)
 *   - API.getSummary()       → breakout piece (top-viewed) + watchers
 *   - API.getAggregate()     → tracking-active days (distinct poll dates)
 *   - API.getPostingLog()    → publishing rhythm (weeks with a publish)
 *
 * Milestones read the *current cumulative* totals each platform reports, so they
 * are effectively ALL-TIME (credit for everything achieved) — stated in the page
 * footnote. Template-string rendering, CSP-safe (no inline handlers). */
window.Laurels = {

    esc(s) {
        return (window.Utils && Utils.escapeHtml)
            ? Utils.escapeHtml(String(s == null ? '' : s))
            : String(s == null ? '' : s).replace(/[&<>"']/g, c =>
                ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
    },
    _num(n) {
        return (window.Utils && Utils.formatNumber) ? Utils.formatNumber(n || 0) : String(n || 0);
    },

    // Default rungs mirror the server defaults (routes/api.py) so the medals line
    // up with the milestone alerts even if /preferences omits them.
    _LADDER_V: [100, 250, 500, 1000, 2500, 5000, 10000, 25000, 50000, 100000],
    _LADDER_F: [10, 25, 50, 100, 250, 500, 1000, 2500, 5000],
    _LADDER_C: [10, 25, 50, 100, 250, 500, 1000],

    /* next rung above `total`, the rung just below, and % of the way there */
    _progress(total, ladder) {
        const next = ladder.find(t => t > total);
        const prevArr = ladder.filter(t => t <= total);
        const prev = prevArr.length ? prevArr[prevArr.length - 1] : 0;
        const pct = next ? Math.min(100, Math.round(((total - prev) / (next - prev)) * 100)) : 100;
        return { next, prev, pct, crossed: prevArr, top: prevArr.length ? prevArr[prevArr.length - 1] : 0 };
    },

    /* metal tier for a persona, by its view total */
    _tier(views) {
        if (views >= 100000) return { name: 'Diamond', cls: 'is-diamond' };
        if (views >= 50000)  return { name: 'Platinum', cls: 'is-plat' };
        if (views >= 10000)  return { name: 'Gold', cls: 'is-gold' };
        if (views >= 1000)   return { name: 'Silver', cls: 'is-silver' };
        return { name: 'Bronze', cls: 'is-bronze' };
    },

    async render() {
        const app = document.getElementById('app');
        app.innerHTML = `
            <div class="lr-head">
                <div class="lr-eyebrow">Your den</div>
                <h1 class="lr-title">Laurels</h1>
                <p class="lr-sub">Every view, fave and comment you've ever earned — turned into
                milestones and medals. The reward side of the numbers.</p>
            </div>
            <div id="lr-body"><div class="loading-spinner">Tallying your laurels…</div></div>`;

        const safe = (p, fallback) => p.then(r => r).catch(() => fallback);
        const [personasResp, prefs, worksResp, summary, agg, postLog] = await Promise.all([
            safe(API.getPersonas(), { personas: [], unassigned: [] }),
            safe(API.getPreferences(), {}),
            safe(API.getWorks({ type: 'all' }), { works: [], personas: [] }),
            safe(API.getSummary(), {}),
            safe(API.getAggregate(), { snapshots: [] }),
            safe(API.getPostingLog({ limit: 250, content_type: null }), { log: [] }),
        ]);

        const body = document.getElementById('lr-body');
        if (!body) return;  // navigated away

        // ── Aggregate the grand totals from the normalized persona stats ──
        const personas = personasResp.personas || [];
        const unassigned = personasResp.unassigned || [];
        const totals = { views: 0, favorites: 0, comments: 0, submissions: 0 };
        const addStats = (c) => {
            if (!c) return;
            totals.views += Number(c.views) || 0;
            totals.favorites += Number(c.favorites) || 0;
            totals.comments += Number(c.comments) || 0;
            totals.submissions += Number(c.submissions) || 0;
        };
        personas.forEach(p => addStats(p.stats && p.stats.combined));
        unassigned.forEach(a => addStats(a.stats));  // unassigned accounts, if they carry stats

        const ladderV = (Array.isArray(prefs.milestone_views) && prefs.milestone_views.length) ? prefs.milestone_views : this._LADDER_V;
        const ladderF = (Array.isArray(prefs.milestone_faves) && prefs.milestone_faves.length) ? prefs.milestone_faves : this._LADDER_F;
        const ladderC = (Array.isArray(prefs.milestone_comments) && prefs.milestone_comments.length) ? prefs.milestone_comments : this._LADDER_C;

        const works = worksResp.works || [];
        const stories = works.filter(w => w.content_type === 'story');
        const artworks = works.filter(w => w.content_type === 'artwork');
        // Platform spread across the whole catalogue
        const allPlats = new Set();
        let maxPlatsOnWork = 0;
        works.forEach(w => {
            const ps = w.platforms || [];
            ps.forEach(c => allPlats.add(c));
            if (ps.length > maxPlatsOnWork) maxPlatsOnWork = ps.length;
        });
        const totalPlatforms = (window.PLATFORMS || []).length || 16;

        const topViewed = (summary.top_viewed && summary.top_viewed[0]) || null;
        const breakoutViews = topViewed ? (Number(topViewed.views) || 0) : 0;
        const watchers = Number(summary.total_watchers) || 0;

        // Empty state — nothing published yet
        if (!works.length && totals.views === 0 && totals.favorites === 0) {
            body.innerHTML = `
                <div class="lr-empty">
                    <div class="lr-empty-emoji">🌱</div>
                    <h2>No laurels yet — but that's where everyone starts.</h2>
                    <p>Publish and connect your accounts, and this page fills with milestones,
                    medals and per-persona trophies as the views come in.</p>
                    <a class="btn btn-primary" href="#/library">Go to your Library</a>
                </div>`;
            return;
        }

        const pV = this._progress(totals.views, ladderV);
        const pF = this._progress(totals.favorites, ladderF);
        const pC = this._progress(totals.comments, ladderC);

        // ── Medals ──────────────────────────────────────────────────
        const medals = this._buildMedals({
            totals, pV, pF, pC, ladderV, ladderF, ladderC,
            stories, artworks, works, allPlats, maxPlatsOnWork, totalPlatforms,
            breakoutViews, breakoutTitle: topViewed ? topViewed.title : '', watchers,
        });
        const earned = medals.filter(m => m.earned);
        const locked = medals.filter(m => !m.earned);

        // ── Publishing rhythm (last 12 ISO weeks with a publish) ─────
        const logRows = Array.isArray(postLog) ? postLog
            : (postLog.log || postLog.entries || postLog.publications || []);
        const rhythm = this._rhythm(logRows);
        // Tracking-active days from distinct snapshot dates
        const days = new Set((agg.snapshots || []).map(s => String(s.polled_at || '').slice(0, 10)).filter(Boolean));
        const trackingDays = days.size;

        body.innerHTML = `
            ${this._heroCard(totals, pV, pF, pC)}

            <section class="lr-section">
                <h2 class="lr-h2">Medals <span class="lr-h2-note">${earned.length} earned${locked.length ? ` · ${locked.length} to go` : ''}</span></h2>
                <div class="lr-medals">
                    ${earned.map(m => this._medal(m)).join('')}
                    ${locked.map(m => this._medal(m)).join('')}
                </div>
            </section>

            ${personas.length ? `
            <section class="lr-section">
                <h2 class="lr-h2">Personas <span class="lr-h2-note">a trophy shelf per identity</span></h2>
                <div class="lr-personas">
                    ${personas.map(p => this._personaCard(p, ladderV)).join('')}
                </div>
            </section>` : ''}

            <section class="lr-section">
                <h2 class="lr-h2">Rhythm <span class="lr-h2-note">momentum, not just totals</span></h2>
                <div class="lr-rhythm-wrap">
                    <div class="lr-rhythm-card">
                        <div class="lr-rhythm-lead">${rhythm.active} of the last 12 weeks had a publish${rhythm.streak >= 2 ? ` · <strong>${rhythm.streak}-week streak</strong>` : ''}</div>
                        <div class="lr-weeks">
                            ${rhythm.weeks.map(w => `<span class="lr-week ${w.on ? 'is-on' : ''}" title="${w.label}"></span>`).join('')}
                        </div>
                    </div>
                    <div class="lr-rhythm-card">
                        <div class="lr-rhythm-big">${this._num(trackingDays)}</div>
                        <div class="lr-rhythm-small">days PawPoller has been tracking your work</div>
                    </div>
                </div>
            </section>

            <p class="lr-foot">Milestones reflect your <strong>all-time</strong> totals as each platform
            currently reports them — you keep credit for everything you've earned.</p>`;
    },

    /* ── Hero milestone card ─────────────────────────────────────── */
    _heroCard(totals, pV, pF, pC) {
        const nextLine = pV.next
            ? `${this._num(pV.next - totals.views)} more to <strong>${this._num(pV.next)}</strong>`
            : `every view milestone cleared`;
        return `
            <div class="lr-hero">
                <div class="lr-hero-main">
                    <div class="lr-hero-eyebrow">Your den has been visited</div>
                    <div class="lr-hero-num">${this._num(totals.views)}<span class="lr-hero-unit">times</span></div>
                    <div class="lr-hero-bar">
                        <div class="lr-hero-fill" style="width:${pV.pct}%"></div>
                        ${pV.prev ? `<span class="lr-hero-prev">${this._num(pV.prev)}</span>` : ''}
                        ${pV.next ? `<span class="lr-hero-next">${this._num(pV.next)}</span>` : ''}
                    </div>
                    <div class="lr-hero-caption">${nextLine}</div>
                </div>
                <div class="lr-hero-side">
                    ${this._miniTrack('Favourites', totals.favorites, pF, '❤')}
                    ${this._miniTrack('Comments', totals.comments, pC, '💬')}
                </div>
            </div>`;
    },

    _miniTrack(label, total, p, icon) {
        return `
            <div class="lr-mini">
                <div class="lr-mini-top"><span class="lr-mini-ico" aria-hidden="true">${icon}</span>
                    <span class="lr-mini-val">${this._num(total)}</span>
                    <span class="lr-mini-label">${label}</span></div>
                <div class="lr-mini-bar"><div class="lr-mini-fill" style="width:${p.pct}%"></div></div>
                <div class="lr-mini-cap">${p.next ? `${this._num(p.next)} next` : 'maxed'}</div>
            </div>`;
    },

    /* ── Medal derivation (all real, all earned from thresholds) ──── */
    _buildMedals(d) {
        const m = [];
        // Metric-tier medals — one per metric at the highest rung reached, plus
        // the next rung as a "locked, in progress" badge.
        const tierMedal = (crossed, next, kind, icon, total) => {
            if (crossed.length) {
                const top = crossed[crossed.length - 1];
                m.push({ icon, name: `${this._num(top)} ${kind}`, desc: `You've passed ${this._num(top)} total ${kind.toLowerCase()}.`, earned: true, tier: crossed.length });
            }
            if (next) {
                m.push({ icon, name: `${this._num(next)} ${kind}`, desc: `${this._num(next - total)} more ${kind.toLowerCase()} to earn this.`, earned: false });
            }
        };
        tierMedal(d.pV.crossed, d.pV.next, 'Views', '👁', d.totals.views);
        tierMedal(d.pF.crossed, d.pF.next, 'Favourites', '⭐', d.totals.favorites);
        tierMedal(d.pC.crossed, d.pC.next, 'Comments', '💬', d.totals.comments);

        // Catalogue + special medals
        const badge = (cond, icon, name, desc, sub) => m.push({ icon, name, desc, earned: !!cond, sub });
        badge(d.stories.length >= 1, '📖', 'First Words', 'Publish your first story.');
        badge(d.artworks.length >= 1, '🎨', 'First Canvas', 'Add your first piece of artwork.');
        badge(d.works.length >= 10, '📚', 'Shelf of Ten', 'Have 10 works in your library.',
            d.works.length >= 10 ? '' : `${d.works.length}/10`);
        badge(d.works.length >= 25, '🗂', 'Prolific', 'Have 25 works in your library.',
            d.works.length >= 25 ? '' : `${d.works.length}/25`);
        badge(d.maxPlatsOnWork >= 5, '🔗', 'Cross-Poster', 'Publish a single work to 5+ platforms.',
            d.maxPlatsOnWork >= 5 ? '' : `best ${d.maxPlatsOnWork}/5`);
        badge(d.allPlats.size >= 10, '🌐', 'Wide Reach', 'Publish across 10+ different platforms.',
            d.allPlats.size >= 10 ? '' : `${d.allPlats.size}/10`);
        badge(d.allPlats.size >= d.totalPlatforms, '🏆', 'Full Spread', `Publish to all ${d.totalPlatforms} platforms.`,
            d.allPlats.size >= d.totalPlatforms ? '' : `${d.allPlats.size}/${d.totalPlatforms}`);
        badge(d.breakoutViews >= 5000, '🚀', 'Breakout', 'Land a single work over 5,000 views.',
            d.breakoutViews >= 5000 ? (d.breakoutTitle || '') : `best ${this._num(d.breakoutViews)}`);
        if (d.watchers >= 100 || d.watchers > 0) {
            badge(d.watchers >= 100, '👥', 'Following of 100', 'Gather 100 watchers across platforms.',
                d.watchers >= 100 ? '' : `${this._num(d.watchers)}/100`);
        }
        return m;
    },

    _medal(m) {
        return `
            <div class="lr-medal ${m.earned ? 'is-earned' : 'is-locked'}">
                <div class="lr-medal-ico" aria-hidden="true">${m.icon}</div>
                <div class="lr-medal-name">${this.esc(m.name)}</div>
                <div class="lr-medal-desc">${this.esc(m.desc)}</div>
                ${m.sub ? `<div class="lr-medal-sub">${this.esc(m.sub)}</div>` : ''}
                ${m.earned ? '<div class="lr-medal-check" aria-hidden="true">✓</div>' : ''}
            </div>`;
    },

    /* ── Per-persona trophy card ─────────────────────────────────── */
    _personaCard(p, ladderV) {
        const c = (p.stats && p.stats.combined) || { views: 0, favorites: 0, comments: 0, submissions: 0 };
        const views = Number(c.views) || 0;
        const tier = this._tier(views);
        const level = ladderV.filter(t => t <= views).length;  // rungs cleared
        const color = p.color || 'var(--accent)';
        return `
            <div class="lr-persona">
                <div class="lr-persona-top">
                    <span class="lr-persona-dot" style="background:${this.esc(color)}"></span>
                    <span class="lr-persona-name">${this.esc(p.name)}</span>
                    <span class="lr-persona-tier ${tier.cls}">${tier.name}</span>
                </div>
                <div class="lr-persona-level">Level ${level} <span>· ${this._num(c.submissions || 0)} works</span></div>
                <div class="lr-persona-stats">
                    <div><span class="lr-ps-v">${this._num(views)}</span><span class="lr-ps-l">views</span></div>
                    <div><span class="lr-ps-v">${this._num(c.favorites || 0)}</span><span class="lr-ps-l">faves</span></div>
                    <div><span class="lr-ps-v">${this._num(c.comments || 0)}</span><span class="lr-ps-l">comments</span></div>
                </div>
            </div>`;
    },

    /* ── Publishing rhythm: last 12 ISO weeks that saw a publish ──── */
    _rhythm(rows) {
        // Bucket event timestamps to a YYYY-Www key; build 12 trailing weeks.
        const keyOf = (d) => {
            // ISO week number
            const dt = new Date(d.getTime());
            dt.setHours(0, 0, 0, 0);
            dt.setDate(dt.getDate() + 3 - ((dt.getDay() + 6) % 7));  // nearest Thursday
            const week1 = new Date(dt.getFullYear(), 0, 4);
            const wk = 1 + Math.round(((dt - week1) / 86400000 - 3 + ((week1.getDay() + 6) % 7)) / 7);
            return `${dt.getFullYear()}-W${String(wk).padStart(2, '0')}`;
        };
        const active = new Set();
        (rows || []).forEach(r => {
            const ts = r.created_at || r.first_posted_at || r.posted_at || r.timestamp || r.last_updated_at;
            if (!ts) return;
            const dt = new Date(ts);
            if (isNaN(dt)) return;
            active.add(keyOf(dt));
        });
        // Walk back 12 weeks from now
        const weeks = [];
        const now = new Date();
        for (let i = 11; i >= 0; i--) {
            const d = new Date(now.getTime());
            d.setDate(d.getDate() - i * 7);
            const k = keyOf(d);
            weeks.push({ key: k, on: active.has(k), label: k });
        }
        const activeCount = weeks.filter(w => w.on).length;
        // Current streak: consecutive active weeks ending at the current week
        let streak = 0;
        for (let i = weeks.length - 1; i >= 0; i--) {
            if (weeks[i].on) streak++; else break;
        }
        return { weeks, active: activeCount, streak };
    },
};
