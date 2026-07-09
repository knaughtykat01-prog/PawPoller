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

-- One row per attached image (2.58.0). Posts can carry up to 4 images (the
-- X/Bluesky/Mastodon cap). The legacy posts.image_path/image_alt columns are
-- kept and still hold the FIRST image, so anything that reads them (feed
-- thumbnail, /image?post_id=) keeps working; this table holds the full ordered
-- set that the publisher fans out per platform.
CREATE TABLE IF NOT EXISTS post_media (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    post_id  INTEGER NOT NULL,
    ordinal  INTEGER NOT NULL DEFAULT 0,      -- display / upload order (0-based)
    path     TEXT NOT NULL DEFAULT '',        -- DATA_DIR/posts_media/…
    alt      TEXT NOT NULL DEFAULT ''         -- per-image alt text
);
CREATE INDEX IF NOT EXISTS idx_post_media_post ON post_media(post_id);

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
