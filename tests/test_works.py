"""Unit tests for the unified Submissions hub logic (routes.submissions_api).

`assemble_works` merges stories + artwork into per-work entries with their
posted platforms and persona(s). It's a pure function over already-fetched
data, so these tests pass fixtures directly — no DB or on-disk archives.
"""
from routes.submissions_api import assemble_works

PUBS = [
    # My_Story: posted to ib + sf (account 1); one queued (not posted) on fa.
    {"content_type": "story", "story_name": "My_Story", "platform": "ib", "account_id": 1, "status": "posted"},
    {"content_type": "story", "story_name": "My_Story", "platform": "sf", "account_id": 1, "status": "posted"},
    {"content_type": "story", "story_name": "My_Story", "platform": "fa", "account_id": 1, "status": "queued"},
    # My_Art: posted to fa (account 2).
    {"content_type": "artwork", "story_name": "My_Art", "platform": "fa", "account_id": 2, "status": "posted"},
]
ACCT_TO_PERSONA = {1: 10, 2: 20}
PERSONAS = {
    10: {"persona_id": 10, "name": "Main", "color": "#fff"},
    20: {"persona_id": 20, "name": "Alt", "color": "#000"},
}
STORIES = [
    {"name": "My_Story", "title": "My Story", "rating": "explicit",
     "images": {"cover": "cover.png"}, "word_count": 1200, "chapters": 3},
]
ARTWORKS = [
    {"name": "My_Art", "title": "My Art", "rating": "mature",
     "image": "img.png", "created_at": "2026-01-01"},
]


def _run(**kw):
    return assemble_works(
        stories=STORIES, artworks=ARTWORKS, pubs=PUBS,
        acct_to_persona=ACCT_TO_PERSONA, personas=PERSONAS, **kw,
    )


def test_lists_both_types_grouped_per_work():
    res = _run(type="all")
    works = {w["name"]: w for w in res["works"]}
    assert set(works) == {"My_Story", "My_Art"}
    # Platforms come ONLY from posted publications, grouped per work.
    assert works["My_Story"]["platforms"] == ["ib", "sf"]
    assert works["My_Story"]["publication_count"] == 3
    assert works["My_Art"]["platforms"] == ["fa"]
    # Personas resolved via account_id -> persona.
    assert works["My_Story"]["persona_names"] == ["Main"]
    assert works["My_Art"]["persona_names"] == ["Alt"]
    # The personas list is returned for the filter UI.
    assert {p["name"] for p in res["personas"]} == {"Main", "Alt"}


def test_type_filter():
    assert [w["content_type"] for w in _run(type="story")["works"]] == ["story"]
    assert [w["content_type"] for w in _run(type="artwork")["works"]] == ["artwork"]


def test_persona_filter():
    assert [w["name"] for w in _run(type="all", persona=20)["works"]] == ["My_Art"]


def test_search_filter():
    assert [w["name"] for w in _run(type="all", search="story")["works"]] == ["My_Story"]


def test_thumb_and_detail_routes():
    works = {w["name"]: w for w in _run(type="all")["works"]}
    assert works["My_Story"]["thumb_url"].startswith("/api/posting/image?story=My_Story")
    assert works["My_Story"]["detail_route"] == "#/posting/story/My_Story"
    assert works["My_Art"]["thumb_url"].startswith("/api/artwork/image?name=My_Art")
    assert works["My_Art"]["detail_route"] == "#/artwork/image/My_Art"
