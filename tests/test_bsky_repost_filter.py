"""Bluesky poller skips reposts (the actor reposting someone else's post).

getAuthorFeed interleaves the actor's own posts/replies with reposts. A repost
item's `post` is the original author's, so its stats aren't the actor's and must
be skipped. Pinned posts (reasonPin) are the actor's own and are kept.
"""

from clients.bsky.client import _is_repost_item


def test_repost_item_is_skipped():
    item = {
        "post": {"uri": "at://did:plc:other/app.bsky.feed.post/abc"},
        "reason": {"$type": "app.bsky.feed.defs#reasonRepost"},
    }
    assert _is_repost_item(item) is True


def test_own_post_is_kept():
    assert _is_repost_item({"post": {"uri": "at://did:plc:me/app.bsky.feed.post/abc"}}) is False


def test_reply_is_kept():
    # A reply item (no reason) is the actor's own comment — keep it.
    item = {"post": {"uri": "at://did:plc:me/app.bsky.feed.post/r1"}, "reply": {"parent": {}}}
    assert _is_repost_item(item) is False


def test_pinned_post_is_kept():
    item = {
        "post": {"uri": "at://did:plc:me/app.bsky.feed.post/pinned"},
        "reason": {"$type": "app.bsky.feed.defs#reasonPin"},
    }
    assert _is_repost_item(item) is False


def test_missing_or_malformed_reason():
    assert _is_repost_item({}) is False
    assert _is_repost_item({"reason": None}) is False
    assert _is_repost_item({"reason": "weird"}) is False
