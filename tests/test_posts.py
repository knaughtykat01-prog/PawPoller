"""Unit tests for the Posts (microblog) module — queries + publisher logic.

DB tests use the shared `db_conn` fixture (real init_db → posts schema applied).
Publisher tests drive the async helpers via asyncio.run (no pytest-asyncio
dependency) and never hit the network — they exercise the unsupported-platform
short-circuit and the not-connected credential path only.
"""
import asyncio

from database import posts_queries as q
from posting import post_publisher


# ── posts_queries CRUD ─────────────────────────────────────────────

def test_posts_crud_and_publication_upsert(db_conn):
    pid = q.create_post(db_conn, body="hello world", rating="mature",
                        image_alt="alt", now="2026-07-03 00:00:00")
    assert pid > 0
    p = q.get_post(db_conn, pid)
    assert p["body"] == "hello world" and p["rating"] == "mature"

    # Upsert twice on the same (post, platform, account) → one row, latest wins.
    q.upsert_post_publication(db_conn, post_id=pid, platform="bsky", account_id=0,
                              status="posted", external_url="https://x/1", now="t1")
    q.upsert_post_publication(db_conn, post_id=pid, platform="bsky", account_id=0,
                              status="failed", error="oops", now="t2")
    pubs = q.get_post_publications(db_conn, pid)
    assert len(pubs) == 1
    assert pubs[0]["status"] == "failed" and pubs[0]["error"] == "oops"

    # A different platform is a separate row.
    q.upsert_post_publication(db_conn, post_id=pid, platform="mast", account_id=0,
                              status="posted", now="t3")
    assert len(q.get_post_publications(db_conn, pid)) == 2

    lst = q.list_posts(db_conn)
    top = next(x for x in lst if x["post_id"] == pid)
    assert len(top["publications"]) == 2

    q.delete_post(db_conn, pid)
    assert q.get_post(db_conn, pid) is None
    assert q.get_post_publications(db_conn, pid) == []


def test_update_post_only_touches_allowed_fields(db_conn):
    pid = q.create_post(db_conn, body="draft", now="t0")
    # created_at is a real column but NOT in the allowed set → must be ignored.
    q.update_post(db_conn, pid, body="edited", rating="adult",
                  created_at="HACKED", now="t1")
    p = q.get_post(db_conn, pid)
    assert p["post_id"] == pid and p["body"] == "edited" and p["rating"] == "adult"
    assert p["created_at"] == "t0"


# ── publisher: pure/guard behaviour (no network) ───────────────────

def test_bsky_label_map():
    assert post_publisher._BSKY_LABELS["mature"] == ["sexual"]
    assert post_publisher._BSKY_LABELS["adult"] == ["porn"]
    assert post_publisher._BSKY_LABELS.get("general") is None


def test_publish_unsupported_platform_short_circuits():
    post = {"body": "hi", "rating": "general", "post_id": 1}
    res = asyncio.run(post_publisher._publish_one(post, "thr", None, {}))
    assert res["success"] is False and "isn't wired yet" in res["error"]


def test_publish_supported_platform_without_creds(db_conn):
    # No accounts configured + empty settings → clear "not connected" error, no network.
    post = {"body": "hi", "rating": "general", "post_id": 1}
    res_b = asyncio.run(post_publisher._publish_one(post, "bsky", None, {}))
    assert res_b["success"] is False and "isn't connected" in res_b["error"]
    res_m = asyncio.run(post_publisher._publish_one(post, "mast", None, {}))
    assert res_m["success"] is False and "isn't connected" in res_m["error"]


def test_publish_post_records_a_publication_row(db_conn):
    # End-to-end publisher path: create → publish (fails, not connected) →
    # a failed post_publications row is written (proves the DB record path).
    pid = q.create_post(db_conn, body="hello", now="t0")
    results = asyncio.run(post_publisher.publish_post(pid, ["bsky"], {}, {}))
    assert results and results[0]["success"] is False
    pubs = q.get_post_publications(db_conn, pid)
    assert len(pubs) == 1
    assert pubs[0]["platform"] == "bsky" and pubs[0]["status"] == "failed"
    assert "isn't connected" in pubs[0]["error"]
