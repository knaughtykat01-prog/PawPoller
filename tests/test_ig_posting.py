"""Unit tests for Instagram (ig) posting — the container→publish flow + guards.

No network: the HTTP helpers are monkeypatched. Covers the single-image and
carousel flows, the require-image guard, and the pending-image token validation
(path-traversal guard on the public-hosting endpoint).
"""

import asyncio

import pytest

from clients.ig.client import IgClient
from posting import ig_media


def test_create_post_requires_image():
    c = IgClient(access_token="t", user_id="42")
    c._logged_in = True
    with pytest.raises(RuntimeError):
        asyncio.run(c.create_post("a caption", []))


def test_create_post_single_image_flow():
    c = IgClient(access_token="t", user_id="42")
    c._logged_in = True
    calls = {"containers": 0, "publishes": 0}

    async def fake_post(url, data):
        if url.endswith("/media"):
            calls["containers"] += 1
            assert data.get("image_url") == "https://x/img.jpg"
            assert data.get("caption") == "hello"
            return {"id": "CONTAINER123"}
        if url.endswith("/media_publish"):
            calls["publishes"] += 1
            assert data["creation_id"] == "CONTAINER123"
            return {"id": "MEDIA999"}
        return {}

    async def fake_get(url, params=None):
        if url.endswith("CONTAINER123"):
            return {"status_code": "FINISHED"}
        if url.endswith("MEDIA999"):
            return {"permalink": "https://www.instagram.com/p/xyz/"}
        return {}

    c._post_json = fake_post
    c._get_json = fake_get
    r = asyncio.run(c.create_post("hello", ["https://x/img.jpg"]))
    assert r["id"] == "MEDIA999"
    assert r["url"] == "https://www.instagram.com/p/xyz/"
    assert calls["containers"] == 1 and calls["publishes"] == 1


def test_create_post_carousel_flow():
    c = IgClient(access_token="t", user_id="42")
    c._logged_in = True
    made = []

    async def fake_post(url, data):
        if url.endswith("/media"):
            if data.get("media_type") == "CAROUSEL":
                made.append("carousel")
                assert data.get("children")   # child ids joined
                return {"id": "CARO"}
            made.append("child")
            assert data.get("is_carousel_item") == "true"
            return {"id": f"CH{made.count('child')}"}
        if url.endswith("/media_publish"):
            assert data["creation_id"] == "CARO"
            return {"id": "MEDIA_CARO"}
        return {}

    async def fake_get(url, params=None):
        return {"status_code": "FINISHED"}

    c._post_json = fake_post
    c._get_json = fake_get
    r = asyncio.run(c.create_post("cap", ["u1", "u2"]))
    assert r["id"] == "MEDIA_CARO"
    assert made.count("child") == 2 and made.count("carousel") == 1


def test_create_post_raises_on_container_error():
    c = IgClient(access_token="t", user_id="42")
    c._logged_in = True

    async def fake_post(url, data):
        return {"id": "C1"}

    async def fake_get(url, params=None):
        return {"status_code": "ERROR"}   # Meta couldn't process the image

    c._post_json = fake_post
    c._get_json = fake_get
    with pytest.raises(RuntimeError):
        asyncio.run(c.create_post("cap", ["https://x/bad.jpg"]))


def test_ig_media_path_for_rejects_bad_tokens():
    # Path-traversal + malformed tokens never resolve to a file.
    assert ig_media.path_for("../etc/passwd") is None
    assert ig_media.path_for("not-a-token") is None
    assert ig_media.path_for("g" * 32) is None          # 32 chars but non-hex
    assert ig_media.path_for("abc") is None
    # A well-formed but non-existent token is also None (no file on disk).
    assert ig_media.path_for("a" * 32) is None


def test_ig_media_public_url():
    url = ig_media.public_url("https://pawpoller.syncopates.app/", "a" * 32)
    assert url == "https://pawpoller.syncopates.app/api/ig/pubmedia/" + ("a" * 32) + ".jpg"
