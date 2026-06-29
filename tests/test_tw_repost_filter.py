"""X/Twitter poller skips reposts (retweets of other accounts).

The UserTweets timeline interleaves the account's own posts/replies with its
retweets. A retweet's engagement belongs to the original author, so the poller
must skip reposts while keeping the account's own posts, replies, and quotes.
"""

from clients.tw.client import _is_repost


def _result(legacy: dict) -> dict:
    return {"rest_id": "123", "legacy": legacy}


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
