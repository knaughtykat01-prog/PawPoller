"""Masterpiece variants (2.158.0): per-variant stats, one cohort.

Members carry variant_key; per-variant stats = the member rollup filtered by
key; cohort totals = all members (unchanged). merge_as_variant folds another
Masterpiece in as a labeled variant, keeping its members' attribution.
"""
import pytest
from fastapi.testclient import TestClient

from database.db import get_connection
from database import masterpiece_queries as mq
from posting import artwork_reader


def test_member_variant_key_roundtrip_and_filter():
    conn = get_connection()
    mq.add_member(conn, "VarPiece", "fa", "1", variant_key="")
    mq.add_member(conn, "VarPiece", "e621", "2", variant_key="nsfw")
    mq.add_member(conn, "VarPiece", "ib", "3", variant_key="nsfw")
    conn.commit()
    assert len(mq.get_members(conn, "VarPiece")) == 3            # cohort
    assert len(mq.get_members(conn, "VarPiece", "nsfw")) == 2    # one variant
    assert len(mq.get_members(conn, "VarPiece", "")) == 1        # primary
    roll_all = mq.rollup_members(conn, "VarPiece")
    roll_nsfw = mq.rollup_members(conn, "VarPiece", "nsfw")
    assert len(roll_all["members"]) == 3 and len(roll_nsfw["members"]) == 2
    conn.close()


def test_set_and_clear_member_variant():
    conn = get_connection()
    mq.add_member(conn, "VP2", "fa", "9")
    mq.set_member_variant(conn, "VP2", "fa", "9", "alt")
    conn.commit()
    assert mq.get_members(conn, "VP2")[0]["variant_key"] == "alt"
    mq.clear_variant_members(conn, "VP2", "alt")
    conn.commit()
    assert mq.get_members(conn, "VP2")[0]["variant_key"] == ""
    conn.close()


def test_merge_as_variant_moves_members_with_attribution():
    conn = get_connection()
    mq.add_member(conn, "KeepP", "fa", "10")
    mq.add_member(conn, "AbsorbP", "e621", "20")
    mq.add_member(conn, "AbsorbP", "ib", "30")
    conn.commit()
    moved = mq.merge_as_variant(conn, "KeepP", "AbsorbP", "nsfw")
    assert moved == 2
    assert len(mq.get_members(conn, "KeepP", "nsfw")) == 2
    assert len(mq.get_members(conn, "KeepP", "")) == 1
    assert mq.get_members(conn, "AbsorbP") == []
    assert conn.execute("SELECT COUNT(*) FROM masterpieces WHERE name='AbsorbP'").fetchone()[0] == 0
    conn.close()


@pytest.fixture
def artwork_archive(tmp_path, monkeypatch):
    arch = tmp_path / "Artwork"
    arch.mkdir()
    monkeypatch.setattr(artwork_reader, "get_artwork_archive_path", lambda: arch)
    return arch


def _mk(arch, name, images):
    d = arch / name
    d.mkdir()
    (d / "masterpiece.json").write_text(
        '{"title": "T", "rating": "general", "image": "%s"}' % images[0], encoding="utf-8")
    for img in images:
        (d / img).write_bytes(b"\x89PNG\r\n\x1a\nfake")


def test_declare_and_delete_variant_endpoints(artwork_archive):
    _mk(artwork_archive, "DecPiece", ["image.png", "image_2.png"])
    from dashboard import app
    c = TestClient(app)
    r = c.post("/api/masterpieces/DecPiece/variants",
               json={"key": "nsfw", "image": "image_2.png", "label": "NSFW", "rating": "adult"})
    assert r.status_code == 200
    detail = c.get("/api/masterpieces/DecPiece").json()
    keys = [v["key"] for v in detail["variants"]]
    assert keys == ["", "nsfw"]                     # primary auto-seeded
    assert detail["variants"][1]["rating"] == "adult"
    # duplicate key rejected; bad image rejected
    assert c.post("/api/masterpieces/DecPiece/variants",
                  json={"key": "nsfw", "image": "image_2.png"}).status_code == 409
    assert c.post("/api/masterpieces/DecPiece/variants",
                  json={"key": "x", "image": "nope.png"}).status_code == 422
    # delete demotes
    assert c.delete("/api/masterpieces/DecPiece/variants/nsfw").status_code == 200
    assert [v["key"] for v in c.get("/api/masterpieces/DecPiece").json()["variants"]] == [""]


def test_merge_as_variant_endpoint(artwork_archive):
    _mk(artwork_archive, "KeepE", ["image.png"])
    _mk(artwork_archive, "AbsorbE", ["image.png"])
    conn = get_connection()
    mq.add_member(conn, "AbsorbE", "fa", "77")
    conn.commit()
    conn.close()
    from dashboard import app
    c = TestClient(app)
    r = c.post("/api/masterpieces/merge-as-variant",
               json={"keep": "KeepE", "absorb": "AbsorbE", "key": "nsfw", "label": "NSFW"})
    assert r.status_code == 200
    body = r.json()
    assert body["members_moved"] == 1
    assert (artwork_archive / "KeepE" / body["variant_image"]).exists()
    assert not (artwork_archive / "AbsorbE").exists()
    detail = c.get("/api/masterpieces/KeepE").json()
    nsfw = [v for v in detail["variants"] if v["key"] == "nsfw"][0]
    assert nsfw["member_count"] == 1
