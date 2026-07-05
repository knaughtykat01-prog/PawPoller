"""Tests for the notification-centre endpoints (routes/api.py).

Covers timestamp normalisation across the two on-disk formats, the feed
shape + per-item unread flags, mark-read clearing unread, and session-expiry
events being merged into the feed.
"""
import routes.api as api


def test_norm_ts_collapses_formats():
    a = api._norm_ts("2026-07-05 09:24:31")           # poll/posting format
    b = api._norm_ts("2026-07-05T09:24:31.569+00:00")  # session/last_read format
    assert a == b == "2026-07-05 09:24:31"
    assert api._norm_ts(None) == ""


def test_notifications_shape_and_per_item_unread():
    r = api.get_notifications(10)
    assert set(r.keys()) == {"items", "unread", "last_read_at"}
    assert isinstance(r["items"], list) and isinstance(r["unread"], int)
    for it in r["items"]:
        assert isinstance(it.get("unread"), bool)
        assert "timestamp" in it and "summary" in it and "status" in it
    # Count matches the per-item flags.
    assert r["unread"] == sum(1 for it in r["items"] if it["unread"])


def test_mark_read_clears_unread():
    # Marking read sets the server-side marker to now; a quiescent feed
    # (all events in the past) then reports zero unread.
    api.mark_notifications_read()
    r = api.get_notifications(10)
    assert r["unread"] == 0
    assert all(it["unread"] is False for it in r["items"])


def test_session_expiry_merged_into_feed(monkeypatch):
    from polling import session_check as sc
    monkeypatch.setattr(sc, "_session_health", {
        "ao3": {"status": "expired", "detail": "dead cookie",
                "checked_at": "2099-01-01T00:00:00+00:00"},
        "sf": {"status": "valid", "detail": None, "checked_at": "2099-01-01T00:00:00+00:00"},
    })
    r = api.get_notifications(30)
    session_items = [it for it in r["items"] if it.get("kind") == "session"]
    # Only the expired one surfaces (valid is healthy → omitted).
    assert len(session_items) == 1
    assert "AO3" in session_items[0]["summary"] and "expired" in session_items[0]["summary"]
    assert session_items[0]["status"] == "error"
