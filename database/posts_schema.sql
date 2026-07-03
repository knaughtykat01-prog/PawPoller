-- Posts module (microblog / "tweet-like" publishing) — 2.49.0
--
-- A self-contained store for short-form posts composed IN PawPoller and pushed
-- to microblog platforms (Bluesky, Mastodon, and — later — Threads/Tumblr/X).
-- Deliberately NOT the story/artwork `publications` registry: a post has no
-- title/chapters/file, so forcing it onto the Package/publications model buys
-- nothing. Analytics for what these posts *earn* still flows through the normal
-- per-platform pollers (bsky_submissions etc.); this pair only tracks the
-- compose→publish side.

CREATE TABLE IF NOT EXISTS posts (
    post_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    body         TEXT NOT NULL DEFAULT '',        -- the post text
    rating       TEXT NOT NULL DEFAULT 'general', -- general | mature | adult
    image_path   TEXT NOT NULL DEFAULT '',        -- optional local media (DATA_DIR/posts_media/…)
    image_alt    TEXT NOT NULL DEFAULT '',        -- alt text for the image
    created_at   TEXT NOT NULL DEFAULT '',
    updated_at   TEXT NOT NULL DEFAULT ''
);

-- One row per (post, platform, account) publish attempt.
CREATE TABLE IF NOT EXISTS post_publications (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    post_id      INTEGER NOT NULL,
    platform     TEXT NOT NULL,
    account_id   INTEGER NOT NULL DEFAULT 0,
    status       TEXT NOT NULL DEFAULT 'pending', -- pending | posted | failed
    external_id  TEXT NOT NULL DEFAULT '',        -- platform post id / URI
    external_url TEXT NOT NULL DEFAULT '',         -- canonical link to the live post
    error        TEXT NOT NULL DEFAULT '',
    created_at   TEXT NOT NULL DEFAULT '',
    UNIQUE(post_id, platform, account_id)
);

CREATE INDEX IF NOT EXISTS idx_post_pub_post ON post_publications(post_id);
