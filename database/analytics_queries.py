"""Analytics queries: Top Fans, Trending/Spike Detection, Cross-Platform Linking.

This module provides advanced analytics that span across platforms, unlike
the platform-specific query modules (queries.py, fa_queries.py, ws_queries.py)
which are scoped to a single platform each.

Major features:
  - Top Fans leaderboard: weighted scoring of user engagement across platforms
  - Trending/Spike Detection: z-score analysis to find unusual activity
  - Cross-Platform Linking: 1:1 mappings of the same content posted to
    multiple platforms, with combined stats and time-series
  - Auto-Suggest Links: Jaccard title similarity to suggest likely matches
"""

from __future__ import annotations
import math
import sqlite3
from typing import Any


# ── Top Fans Leaderboard ─────────────────────────────────────

def get_top_fans(conn: sqlite3.Connection, limit: int = 20) -> list[dict]:
    """Aggregate fave and comment activity per user across platforms.

    Data sources by platform:
      IB: faving_users table (individual fave tracking) + comments table
      FA: fa_comments table (comment tracking only -- no individual fave data)
      WS: Not included (Weasyl exposes no user-level activity data at all)

    Scoring formula: score = (fave_count * 2) + (comment_count * 1)
    Faves are weighted 2x because they represent a deliberate action of
    appreciation, whereas comments are weighted 1x. This means a user who
    faved 5 submissions (score: 10) ranks higher than a user who left 9
    comments (score: 9).

    Platform aggregation uses a set() for the platforms field because a user
    can appear on multiple platforms with the same username. Using a set
    naturally deduplicates platform entries (e.g. if a user is found in both
    IB faving_users and IB comments, "ib" only appears once).

    Each platform query is wrapped in try/except to gracefully handle cases
    where the table does not exist (e.g. fresh database without FA data).
    """
    # Accumulator dict: keyed by username, value is aggregated stats + platform set.
    user_stats: dict[str, dict] = {}  # username -> {fave_count, comment_count, platforms}

    # IB faving users -- COUNT(DISTINCT submission_id) gives unique submissions
    # faved per user (a user faving the same submission twice is impossible due
    # to the UNIQUE constraint, but DISTINCT is defensive).
    try:
        rows = conn.execute(
            "SELECT username, COUNT(DISTINCT submission_id) as fave_count FROM faving_users GROUP BY username"
        ).fetchall()
        for r in rows:
            name = r["username"]
            if name not in user_stats:
                user_stats[name] = {"fave_count": 0, "comment_count": 0, "platforms": set()}
            user_stats[name]["fave_count"] += r["fave_count"]
            user_stats[name]["platforms"].add("ib")
    except Exception:
        pass

    # IB comments -- COUNT(*) gives total comments per user across all submissions.
    try:
        rows = conn.execute(
            "SELECT username, COUNT(*) as comment_count FROM comments GROUP BY username"
        ).fetchall()
        for r in rows:
            name = r["username"]
            if name not in user_stats:
                user_stats[name] = {"fave_count": 0, "comment_count": 0, "platforms": set()}
            user_stats[name]["comment_count"] += r["comment_count"]
            user_stats[name]["platforms"].add("ib")
    except Exception:
        pass

    # FA comments -- FA does not provide individual fave user data, so only
    # comment activity contributes to FA users' scores.
    try:
        rows = conn.execute(
            "SELECT username, COUNT(*) as comment_count FROM fa_comments GROUP BY username"
        ).fetchall()
        for r in rows:
            name = r["username"]
            if name not in user_stats:
                user_stats[name] = {"fave_count": 0, "comment_count": 0, "platforms": set()}
            user_stats[name]["comment_count"] += r["comment_count"]
            user_stats[name]["platforms"].add("fa")
    except Exception:
        pass

    # WS is intentionally excluded -- Weasyl does not expose any user-level
    # engagement data (no faving users, no individual comments).

    # Calculate weighted scores and sort descending by score.
    result = []
    for username, stats in user_stats.items():
        # Weighted formula: faves are worth 2 points each, comments 1 point.
        score = stats["fave_count"] * 2 + stats["comment_count"]
        result.append({
            "username": username,
            "platforms": sorted(stats["platforms"]),  # Convert set to sorted list for JSON serialization.
            "fave_count": stats["fave_count"],
            "comment_count": stats["comment_count"],
            "score": score,
        })

    result.sort(key=lambda x: x["score"], reverse=True)
    return result[:limit]


# ── Trending / Spike Detection ───────────────────────────────
# Uses z-score statistical analysis to detect unusual activity spikes.
# A "spike" is when the most recent change in a metric (views, faves,
# or comments) is significantly larger than the typical change over the
# past 30 days. This surfaces content that is suddenly getting more
# attention than its historical baseline.

def get_trending_submissions(conn: sqlite3.Connection, hours: int = 24, z_threshold: float = 2.0) -> list[dict]:
    """Find submissions with unusual activity based on z-score analysis.

    Algorithm overview:
    1. For each submission on each platform, get the delta between the
       two most recent snapshots (the "current delta").
    2. Build a 30-day baseline of consecutive-snapshot deltas.
    3. Compute the mean and standard deviation of the baseline deltas.
    4. Calculate z-score: z = (current_delta - mean) / stddev
    5. If z >= z_threshold (default 2.0), the submission is "spiking".

    A z-score of 2.0 means the current activity is 2 standard deviations
    above the 30-day average -- roughly the top 2.3% of expected variation.

    Results are sorted by max_z (highest spike first) across all platforms.
    """
    trending = []

    # Process each platform using its specific table names.
    # Each platform is wrapped in try/except to handle missing tables gracefully.
    for platform, sub_table, snap_table in [
        ("ib", "submissions", "snapshots"),
        ("fa", "fa_submissions", "fa_snapshots"),
        ("ws", "ws_submissions", "ws_snapshots"),
        ("sf", "sf_submissions", "sf_snapshots"),
        ("sqw", "sqw_submissions", "sqw_snapshots"),
        ("ao3", "ao3_submissions", "ao3_snapshots"),
        ("da", "da_submissions", "da_snapshots"),
        ("wp", "wp_submissions", "wp_snapshots"),
        ("ik", "ik_submissions", "ik_snapshots"),
        ("bsky", "bsky_submissions", "bsky_snapshots"),
        ("tw", "tw_submissions", "tw_snapshots"),
    ]:
        try:
            _find_spikes(conn, platform, sub_table, snap_table, hours, z_threshold, trending)
        except Exception:
            pass

    # Sort all results across platforms by maximum z-score, highest first.
    trending.sort(key=lambda x: x.get("max_z", 0), reverse=True)
    return trending


def _find_spikes(conn: sqlite3.Connection, platform: str, sub_table: str, snap_table: str,
                 hours: int, z_threshold: float, results: list[dict]) -> None:
    """Find spike submissions for a single platform.

    Step-by-step z-score spike detection per submission:

    1. CURRENT DELTA: Fetch the 2 most recent snapshots. The difference
       between them is the "current delta" -- how much the metric changed
       in the most recent poll interval.

    2. BASELINE WINDOW (30 days): Fetch all snapshots from the last 30 days,
       ordered chronologically. Compute consecutive deltas (snap[i] - snap[i-1])
       to build a list of historical changes. This is the baseline distribution.
       Requires at least 3 snapshots (yielding at least 2 deltas) to compute
       meaningful statistics.

    3. STATISTICS: Calculate the sample mean and sample standard deviation
       (using Bessel's correction: N-1 denominator) of the baseline deltas.

    4. Z-SCORE: z = (current_delta - mean) / stddev. If stddev is 0 (all
       baseline deltas are identical), we skip -- can't compute a meaningful
       z-score.

    5. THRESHOLD: If z >= z_threshold, this metric is spiking. Record the
       delta, z-score, mean, and stddev for reporting.

    Results are appended to the shared `results` list (mutated in place).
    Uses platform-aware column names for Wattpad (reads/votes) and Itaku (likes, no views).
    """
    # Platform-specific metric column mapping
    _platform_cols = {
        "ib":  ["views", "favorites_count", "comments_count"],
        "fa":  ["views", "favorites_count", "comments_count"],
        "ws":  ["views", "favorites_count", "comments_count"],
        "sf":  ["views", "favorites_count", "comments_count"],
        "sqw": ["views", "favorites_count", "comments_count"],
        "ao3": ["views", "favorites_count", "comments_count"],
        "da":  ["views", "favorites_count", "comments_count"],
        "wp":  ["reads", "votes", "comments_count"],
        "ik":  ["likes", "comments_count"],  # No views column
        "bsky": ["likes", "reposts", "replies"],  # No views column
        "tw":  ["views", "likes", "retweets", "replies"],
    }
    metric_cols = _platform_cols.get(platform, ["views", "favorites_count", "comments_count"])

    # Get all submission IDs and titles from this platform.
    subs = conn.execute(f"SELECT submission_id, title FROM {sub_table}").fetchall()

    for sub_row in subs:
        sub_id = sub_row["submission_id"]
        title = sub_row["title"]

        # Step 1: Get the 2 most recent snapshots to compute the current delta.
        cols_str = ", ".join(metric_cols)
        latest = conn.execute(
            f"SELECT {cols_str}, polled_at FROM {snap_table} "
            f"WHERE submission_id = ? ORDER BY polled_at DESC LIMIT 2",
            (sub_id,),
        ).fetchall()

        if len(latest) < 2:
            # Need at least 2 snapshots to compute a delta.
            continue

        current = dict(latest[0])   # Most recent snapshot
        previous = dict(latest[1])  # Second most recent snapshot

        # Step 2: Get all snapshots from the last 30 days for the baseline.
        # The 30-day window provides enough data points for reliable statistics
        # while being recent enough to reflect current activity patterns.
        baseline_snaps = conn.execute(
            f"SELECT {cols_str} FROM {snap_table} "
            f"WHERE submission_id = ? AND polled_at >= datetime('now', '-30 days') "
            f"ORDER BY polled_at ASC",
            (sub_id,),
        ).fetchall()

        if len(baseline_snaps) < 3:
            # Need at least 3 snapshots to compute 2+ baseline deltas.
            continue

        # Step 3-5: Compute z-scores for each metric independently.
        spike_info = {}
        max_z = 0

        for metric in metric_cols:
            # Current delta: change in this metric between the two most recent snapshots.
            current_delta = current[metric] - previous[metric]
            if current_delta <= 0:
                # No increase -- not a spike. Skip this metric.
                continue

            # Compute consecutive deltas from the 30-day baseline snapshots.
            # Each delta represents the change between two adjacent poll cycles.
            deltas = []
            for i in range(1, len(baseline_snaps)):
                d = baseline_snaps[i][metric] - baseline_snaps[i - 1][metric]
                deltas.append(d)

            if len(deltas) < 2:
                # Need at least 2 deltas for meaningful standard deviation.
                continue

            # Sample mean of baseline deltas.
            mean = sum(deltas) / len(deltas)
            # Sample variance using Bessel's correction (N-1 denominator)
            # for unbiased estimation from a sample.
            variance = sum((d - mean) ** 2 for d in deltas) / (len(deltas) - 1)
            stddev = math.sqrt(variance) if variance > 0 else 0

            if stddev == 0:
                # All baseline deltas are identical -- z-score is undefined.
                continue

            # Z-score: how many standard deviations the current delta is
            # above the baseline mean.
            z = (current_delta - mean) / stddev
            if z >= z_threshold:
                spike_info[metric] = {
                    "delta": current_delta,
                    "z_score": round(z, 2),
                    "mean": round(mean, 2),
                    "stddev": round(stddev, 2),
                }
                max_z = max(max_z, z)

        if spike_info:
            results.append({
                "platform": platform,
                "submission_id": sub_id,
                "title": title,
                "spikes": spike_info,
                "max_z": round(max_z, 2),
            })


# ── Cross-Platform Linking ───────────────────────────────────
# Links represent 1:1 mappings of the SAME content posted to multiple platforms
# (e.g. the same story posted to IB, FA, and WS). Unlike groups (which are
# arbitrary user-defined collections), links are specifically for tracking
# cross-posted content and computing combined performance metrics.
#
# The data model uses link_id as a grouping key:
# - submission_links: Auto-increment link_id with a created_at timestamp.
# - submission_link_members: Junction table (link_id, platform, submission_id)
#   mapping each link to its constituent submissions across platforms.
#
# Combined stats and time-series are computed dynamically by querying each
# member's platform-specific tables, same dynamic table lookup pattern as
# group_queries.py.

def create_link(conn: sqlite3.Connection, members: list[dict]) -> int:
    """Create a submission link with members. Each member: {platform, submission_id}.

    The link_id is auto-generated (INSERT DEFAULT VALUES creates a row with
    only the auto-increment primary key and default created_at). Members are
    then inserted into the junction table referencing this link_id.
    """
    cur = conn.execute("INSERT INTO submission_links DEFAULT VALUES")
    link_id = cur.lastrowid
    for m in members:
        conn.execute(
            "INSERT INTO submission_link_members (link_id, platform, submission_id) VALUES (?, ?, ?)",
            (link_id, m["platform"], m["submission_id"]),
        )
    conn.commit()
    return link_id


def delete_link(conn: sqlite3.Connection, link_id: int) -> None:
    # Cascade deletes junction table entries via ON DELETE CASCADE in schema.
    conn.execute("DELETE FROM submission_links WHERE link_id = ?", (link_id,))
    conn.commit()


def get_links(conn: sqlite3.Connection) -> list[dict]:
    """Get all links with their member details eagerly loaded.

    For each link, fetches its members from the junction table and enriches
    each member with title and current stats from the platform-specific
    submissions table. Uses the same dynamic table lookup pattern as
    group_queries.get_group_stats.
    """
    links = conn.execute("SELECT * FROM submission_links ORDER BY created_at DESC").fetchall()
    result = []
    for link in links:
        l = dict(link)
        members = conn.execute(
            "SELECT * FROM submission_link_members WHERE link_id = ?", (l["link_id"],)
        ).fetchall()
        l["members"] = []
        for m in members:
            md = dict(m)
            # Enrich each member with title and stats from the platform's table.
            table = {"ib": "submissions", "fa": "fa_submissions", "ws": "ws_submissions", "sf": "sf_submissions", "sqw": "sqw_submissions", "ao3": "ao3_submissions", "da": "da_submissions", "wp": "wp_submissions", "ik": "ik_submissions"}.get(md["platform"])
            if table:
                try:
                    sub = conn.execute(
                        f"SELECT * FROM {table} WHERE submission_id = ?",
                        (md["submission_id"],),
                    ).fetchone()
                    if sub:
                        md.update(dict(sub))
                except Exception:
                    pass
            l["members"].append(md)
        result.append(l)
    return result


def get_link_combined_stats(conn: sqlite3.Connection, link_id: int) -> dict:
    """Get aggregate stats for a linked set of submissions.

    Sums views, faves, and comments across all linked platform submissions
    to show the total reach of cross-posted content. Same dynamic table
    lookup pattern as group_queries.get_group_stats.
    """
    members = conn.execute(
        "SELECT platform, submission_id FROM submission_link_members WHERE link_id = ?",
        (link_id,),
    ).fetchall()

    total_views = 0
    total_faves = 0
    total_comments = 0
    subs = []

    _table_map = {"ib": "submissions", "fa": "fa_submissions", "ws": "ws_submissions", "sf": "sf_submissions", "sqw": "sqw_submissions", "ao3": "ao3_submissions", "da": "da_submissions", "wp": "wp_submissions", "ik": "ik_submissions", "bsky": "bsky_submissions", "tw": "tw_submissions"}
    _metrics = {
        "ib": ("views", "favorites_count", "comments_count"),
        "fa": ("views", "favorites_count", "comments_count"),
        "ws": ("views", "favorites_count", "comments_count"),
        "sf": ("views", "favorites_count", "comments_count"),
        "sqw": ("views", "favorites_count", "comments_count"),
        "ao3": ("views", "favorites_count", "comments_count"),
        "da": ("views", "favorites_count", "comments_count"),
        "wp": ("reads", "votes", "comments_count"),
        "ik": (None, "likes", "comments_count"),
        "bsky": (None, "likes", "replies"),
        "tw":  ("views", "likes", "replies"),
    }

    for m in members:
        plat = m["platform"]
        table = _table_map.get(plat)
        if not table:
            continue
        try:
            row = conn.execute(
                f"SELECT * FROM {table} WHERE submission_id = ?",
                (m["submission_id"],),
            ).fetchone()
        except Exception:
            continue
        if row:
            r = dict(row)
            r["platform"] = plat
            v_col, f_col, c_col = _metrics.get(plat, ("views", "favorites_count", "comments_count"))
            total_views += (r.get(v_col, 0) or 0) if v_col else 0
            total_faves += (r.get(f_col, 0) or 0) if f_col else 0
            total_comments += (r.get(c_col, 0) or 0) if c_col else 0
            subs.append(r)

    return {
        "total_views": total_views,
        "total_favorites": total_faves,
        "total_comments": total_comments,
        "submissions": subs,
    }


def get_link_combined_snapshots(conn: sqlite3.Connection, link_id: int) -> list[dict]:
    """Get merged time-series (sum views/faves/comments at each timestamp) for linked submissions.

    Merges snapshots from different platforms by timestamp. Because different
    platforms may be polled at slightly different times (or have different poll
    cadences), the merge is keyed by exact polled_at timestamp string. When
    two platforms happen to have snapshots at the same timestamp, their values
    are summed. When they don't overlap, each timestamp only contains data
    from whichever platform(s) had a snapshot at that moment.

    This produces a combined time-series suitable for charting the total
    performance of cross-posted content over time.
    """
    members = conn.execute(
        "SELECT platform, submission_id FROM submission_link_members WHERE link_id = ?",
        (link_id,),
    ).fetchall()

    # Accumulate snapshots across platforms, indexed by timestamp string.
    # Each timestamp entry sums values from all linked submissions that
    # have a snapshot at that exact time.
    time_data: dict[str, dict] = {}

    _snap_map = {"ib": "snapshots", "fa": "fa_snapshots", "ws": "ws_snapshots", "sf": "sf_snapshots", "sqw": "sqw_snapshots", "ao3": "ao3_snapshots", "da": "da_snapshots", "wp": "wp_snapshots", "ik": "ik_snapshots", "bsky": "bsky_snapshots", "tw": "tw_snapshots"}
    _metrics = {
        "ib": ("views", "favorites_count", "comments_count"),
        "fa": ("views", "favorites_count", "comments_count"),
        "ws": ("views", "favorites_count", "comments_count"),
        "sf": ("views", "favorites_count", "comments_count"),
        "sqw": ("views", "favorites_count", "comments_count"),
        "ao3": ("views", "favorites_count", "comments_count"),
        "da": ("views", "favorites_count", "comments_count"),
        "wp": ("reads", "votes", "comments_count"),
        "ik": (None, "likes", "comments_count"),
        "bsky": (None, "likes", "replies"),
        "tw":  ("views", "likes", "replies"),
    }

    for m in members:
        plat = m["platform"]
        # Dynamic table lookup for the platform's snapshot table.
        snap_table = _snap_map.get(plat)
        if not snap_table:
            continue
        v_col, f_col, c_col = _metrics.get(plat, ("views", "favorites_count", "comments_count"))
        # Build SELECT with only existing columns
        select_cols = ["polled_at"]
        if v_col:
            select_cols.append(v_col)
        if f_col:
            select_cols.append(f_col)
        if c_col:
            select_cols.append(c_col)
        try:
            rows = conn.execute(
                f"SELECT {', '.join(select_cols)} FROM {snap_table} "
                f"WHERE submission_id = ? ORDER BY polled_at ASC",
                (m["submission_id"],),
            ).fetchall()
        except Exception:
            continue
        for r in rows:
            ts = r["polled_at"]
            if ts not in time_data:
                time_data[ts] = {"polled_at": ts, "views": 0, "favorites_count": 0, "comments_count": 0}
            # Sum values from multiple platforms at the same timestamp.
            # Map platform-specific columns to the canonical output keys.
            time_data[ts]["views"] += (r[v_col] or 0) if v_col else 0
            time_data[ts]["favorites_count"] += (r[f_col] or 0) if f_col else 0
            time_data[ts]["comments_count"] += (r[c_col] or 0) if c_col else 0

    # Return sorted by timestamp for chronological chart rendering.
    return sorted(time_data.values(), key=lambda x: x["polled_at"])


def auto_suggest_links(conn: sqlite3.Connection) -> list[dict]:
    """Find potential cross-platform matches by title similarity.

    Algorithm:
    1. Load all submissions from all nine platforms.
    2. Build a set of (platform, submission_id) pairs that are already linked,
       so we can exclude them from suggestions. This prevents suggesting links
       for content that has already been linked by the user.
    3. Compare every pair of submissions across different platforms (not within
       the same platform -- cross-posting to the same site is not meaningful).
       Uses nested loops over platform pairs (IB-FA, IB-WS, FA-WS).
    4. For each cross-platform pair, compute title similarity using the Jaccard
       index on word sets. If the similarity meets the 0.6 threshold (60% word
       overlap), it is considered a likely match.
    5. Results are sorted by similarity score (highest first) and capped at 20.

    The 0.6 Jaccard threshold was chosen as a balance: high enough to avoid
    false positives from generic titles, low enough to catch titles that differ
    slightly across platforms (e.g. minor wording changes, added chapter numbers).

    Note: This is an O(N*M) comparison across platforms, which is acceptable
    for the expected submission counts (hundreds, not millions).
    """
    suggestions = []

    # Step 1: Load all submissions from each platform.
    # IB uses create_datetime; most others use posted_at for the post date column.
    date_col = {
        "ib": "create_datetime", "fa": "posted_at", "ws": "posted_at",
        "sf": "posted_at", "sqw": "posted_at", "ao3": "posted_at",
        "da": "posted_at", "wp": "posted_at", "ik": "posted_at",
    }
    platforms = {}
    for platform, table in [
        ("ib", "submissions"), ("fa", "fa_submissions"), ("ws", "ws_submissions"),
        ("sf", "sf_submissions"), ("sqw", "sqw_submissions"), ("ao3", "ao3_submissions"),
        ("da", "da_submissions"), ("wp", "wp_submissions"), ("ik", "ik_submissions"),
    ]:
        try:
            rows = conn.execute(
                f"SELECT submission_id, title, {date_col[platform]} as posted_at FROM {table}"
            ).fetchall()
            platforms[platform] = [dict(r) for r in rows]
        except Exception:
            platforms[platform] = []

    # Step 2: Build exclusion set of already-linked submissions.
    # Any submission that is already part of a link should not be suggested
    # again, to avoid duplicate link proposals.
    existing = set()
    try:
        link_members = conn.execute("SELECT platform, submission_id FROM submission_link_members").fetchall()
        for m in link_members:
            existing.add((m["platform"], m["submission_id"]))
    except Exception:
        pass

    # Step 3-4: Compare across platforms (not within the same platform).
    # Iterates over all unique platform pairs: (ib, fa), (ib, ws), (fa, ws).
    platform_keys = list(platforms.keys())
    for i in range(len(platform_keys)):
        for j in range(i + 1, len(platform_keys)):
            p1, p2 = platform_keys[i], platform_keys[j]
            for s1 in platforms[p1]:
                # Skip submissions already linked on this platform.
                if (p1, s1["submission_id"]) in existing:
                    continue
                for s2 in platforms[p2]:
                    # Skip submissions already linked on the other platform.
                    if (p2, s2["submission_id"]) in existing:
                        continue
                    similarity = _title_similarity(s1["title"], s2["title"])
                    # Jaccard threshold of 0.6: at least 60% word overlap
                    # required to consider titles a potential match.
                    if similarity >= 0.6:
                        suggestions.append({
                            "similarity": round(similarity, 2),
                            "submissions": [
                                {"platform": p1, "submission_id": s1["submission_id"], "title": s1["title"]},
                                {"platform": p2, "submission_id": s2["submission_id"], "title": s2["title"]},
                            ],
                        })

    # Step 5: Sort by similarity (best matches first) and cap at 20 results.
    suggestions.sort(key=lambda x: x["similarity"], reverse=True)
    return suggestions[:20]


def _title_similarity(a: str, b: str) -> float:
    """Compute title similarity using the Jaccard index on word sets.

    Jaccard index = |intersection| / |union| of the two word sets.
    - Returns 1.0 for identical titles (after lowercasing).
    - Returns 0.0 for titles with no words in common.
    - Returns 0.0 if either title is empty.

    Example: "The Quick Fox" vs "The Quick Brown Fox"
      words_a = {"the", "quick", "fox"}
      words_b = {"the", "quick", "brown", "fox"}
      intersection = {"the", "quick", "fox"} (3 words)
      union = {"the", "quick", "brown", "fox"} (4 words)
      Jaccard = 3/4 = 0.75
    """
    if not a or not b:
        return 0.0
    words_a = set(a.lower().split())
    words_b = set(b.lower().split())
    if not words_a or not words_b:
        return 0.0
    intersection = words_a & words_b
    union = words_a | words_b
    return len(intersection) / len(union)
