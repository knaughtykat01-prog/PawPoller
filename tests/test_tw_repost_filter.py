"""X/Twitter poller skips reposts (retweets of other accounts).

The UserTweets timeline interleaves the account's own posts/replies with its
retweets. A retweet's engagement belongs to the original author, so the poller
must skip reposts while keeping the account's own posts, replies, and quotes.
"""

from clients.tw.client import (
    _is_repost, _user_tagged_in, _repost_original, TWClient,
)


def _result(legacy: dict) -> dict:
    return {"rest_id": "123", "legacy": legacy}


def _repost(original_legacy: dict) -> dict:
    return {"rest_id": "1", "legacy": {
        "retweeted_status_result": {"result": {"rest_id": "99", "legacy": original_legacy}}}}


def test_repost_is_skipped():
    assert _is_repost(_result({"retweeted_status_result": {"result": {"rest_id": "999"}}})) is True


def test_original_tweet_is_kept():
    assert _is_repost(_result({"full_text": "hello world", "favorite_count": 3})) is False


def test_reply_is_kept():
    # A reply (comment) by the account is its own content — keep it.
    assert _is_repost(_result({"in_reply_to_status_id_str": "555", "full_text": "agreed"})) is False


def test_quote_tweet_is_kept():
    # A quote is the account's own post quoting another — not a repost.
    assert _is_repost(_result({"quoted_status_id_str": "777", "full_text": "look at this"})) is False


def test_missing_or_empty_is_not_repost():
    assert _is_repost({}) is False
    assert _is_repost({"legacy": {}}) is False
    assert _is_repost(None) is False


# ── Tagged-repost handling (keep reposts that @mention the account) ──

def test_repost_that_tags_user_is_kept():
    r = _repost({"entities": {"user_mentions": [{"screen_name": "KiiKinar"}]}})
    assert _is_repost(r) is True
    assert _user_tagged_in(r, "KiiKinar") is True
    assert _user_tagged_in(r, "@kiikinar") is True   # @ + case-insensitive


def test_repost_without_user_mention_is_not_tagged():
    r = _repost({"entities": {"user_mentions": [{"screen_name": "someoneelse"}]}})
    assert _user_tagged_in(r, "KiiKinar") is False


def test_repost_original_is_extracted():
    orig = _repost_original(_repost({"full_text": "hi", "entities": {}}))
    assert orig and orig.get("rest_id") == "99"


def test_mention_in_own_tweet_counts():
    t = {"rest_id": "5", "legacy": {"entities": {"user_mentions": [{"screen_name": "KiiKinar"}]}}}
    assert _user_tagged_in(t, "kiikinar") is True


def test_empty_target_never_tagged():
    t = {"legacy": {"entities": {"user_mentions": [{"screen_name": "x"}]}}}
    assert _user_tagged_in(t, "") is False


# ── Core fix: stats parsed straight from the timeline result ──

def test_extract_stats_from_timeline_result():
    c = TWClient("a", "b", "KiiKinar")
    result = {
        "rest_id": "123",
        "legacy": {"full_text": "hello world", "favorite_count": 5, "retweet_count": 2,
                   "reply_count": 1, "quote_count": 0, "created_at": "x", "entities": {}},
        "views": {"count": "100"},
        "core": {"user_results": {"result": {"legacy": {"screen_name": "KiiKinar"}}}},
    }
    d = c._extract_tweet_stats(result)
    assert d["tweet_id"] == "123"
    assert d["likes"] == 5 and d["retweets"] == 2 and d["views"] == 100
    assert d["title"].startswith("hello world")
    assert d["link"] == "https://x.com/KiiKinar/status/123"
