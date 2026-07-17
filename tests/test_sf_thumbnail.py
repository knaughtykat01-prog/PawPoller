"""SoFurry .data parsing — thumbnail extraction (2.146.0).

The beta /s/{id}.data payload embeds the artwork thumbnail as a full CDN URL
under /submissions/thumbnails/ (distinct from /users/avatars/). Previously
get_submission_detail never pulled it out, so SF thumbnails/images were blank.
Fake _http → no network.
"""
import asyncio


class _Resp:
    def __init__(self, text, status=200):
        self.text = text
        self.status_code = status


def _client_with_payload(payload):
    from clients.sf.client import SoFurryClient
    c = SoFurryClient()

    async def fake_get(url, **kw):
        return _Resp(payload)

    c._http.get = fake_get
    return c


def test_extracts_thumbnail_and_stats():
    payload = (
        '["title","A Sample Piece","description","a ref","publishedAt","2026-02-19",'
        '"category","artwork","views",858,"likes",42,'
        '"avatarUrl","https://cdn.sofurryfiles.com/users/avatars/large/2a/c9/2ac9bb76",'
        '"thumbnail","https://cdn.sofurryfiles.com/submissions/thumbnails/6b/e3/6be33fb0-7dbd-45ab-9fde-1819a0c65f98",'
        '"author",{},"total",12,"hasMore",false]'
    )
    d = asyncio.run(_client_with_payload(payload).get_submission_detail("1YAApVD1"))
    assert d["thumbnail_url"] == \
        "https://cdn.sofurryfiles.com/submissions/thumbnails/6b/e3/6be33fb0-7dbd-45ab-9fde-1819a0c65f98"
    assert d["title"] == "A Sample Piece"
    assert d["views"] == 858
    assert d["favorites_count"] == 42
    assert d["comments_count"] == 12


def test_avatar_url_is_not_mistaken_for_thumbnail():
    # Only an avatar URL present (a text work) → thumbnail stays "".
    payload = (
        '["title","My Story","views",10,"likes",3,'
        '"avatarUrl","https://cdn.sofurryfiles.com/users/avatars/large/2a/c9/2ac9bb76",'
        '"total",0,"hasMore",false]'
    )
    d = asyncio.run(_client_with_payload(payload).get_submission_detail("abc"))
    assert d["thumbnail_url"] == ""
    assert d["title"] == "My Story"
