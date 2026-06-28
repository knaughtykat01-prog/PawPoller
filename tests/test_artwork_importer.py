"""Unit tests for the generic artwork importer's pure helpers
(posting.artwork_importer). The full import_artwork() path needs DB + network +
filesystem, so it's exercised live, not here; these cover the mapping logic that
makes one importer work across platforms.
"""
from posting.artwork_importer import norm_rating, image_url, ext_from_url, parse_tags


def test_norm_rating_maps_per_platform_terms():
    assert norm_rating("General") == "general"    # FA
    assert norm_rating("Clean") == "general"      # SoFurry
    assert norm_rating("explicit") == "adult"     # Weasyl
    assert norm_rating("Adult") == "adult"        # FA / SF
    assert norm_rating("Mature") == "mature"
    assert norm_rating("") == ""
    assert norm_rating(None) == ""


def test_image_url_prefers_full_res():
    assert image_url({"download_url": "full", "thumbnail_url": "t"}) == "full"  # FA
    assert image_url({"media_url": "full", "thumbnail_url": "t"}) == "full"     # Weasyl
    assert image_url({"thumbnail_url": "t"}) == "t"                            # SF fallback
    assert image_url({}) == ""


def test_ext_from_url():
    assert ext_from_url("https://d.fa.net/art/x/file.jpg") == ".jpg"
    assert ext_from_url("https://x/y/FILE.PNG?token=1") == ".png"
    assert ext_from_url("https://x/y/noextension") == ".png"  # default


def test_parse_tags_handles_json_list_csv_and_empty():
    assert parse_tags('["wolf", "anthro"]') == ["wolf", "anthro"]
    assert parse_tags(["a", "b"]) == ["a", "b"]
    assert parse_tags("a, b, c") == ["a", "b", "c"]
    assert parse_tags("") == []
    assert parse_tags(None) == []
