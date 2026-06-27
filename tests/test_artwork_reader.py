"""Artwork archive reader tests — create / load / build_artwork_package."""

import pytest

from posting import artwork_reader
from posting.platforms.base import StoryUploadPackage


@pytest.fixture
def artwork_archive(tmp_path, monkeypatch):
    """Point the artwork archive at a temp dir for the duration of a test."""
    arch = tmp_path / "Artwork"
    arch.mkdir()
    monkeypatch.setattr(artwork_reader, "get_artwork_archive_path", lambda: arch)
    return arch


def test_create_and_load_artwork(artwork_archive):
    name = artwork_reader.create_artwork(
        title="Autumn Study",
        image_filename="study.png",
        image_bytes=b"\x89PNG\r\n\x1a\n fake",
        description="A study.",
        rating="mature",
        tags={"default": ["autumn", "study"], "fa": ["autumn", "figure_study"]},
        platforms=["ib", "fa"],
    )
    assert name == "Autumn_Study"

    art = artwork_reader.load_artwork(name)
    assert art.title == "Autumn Study"
    assert art.rating == "mature"
    assert art.image == "study.png"
    # default cascades to ib; fa's explicit list is retained
    assert art.tags_by_platform["fa"] == ["autumn", "figure_study"]
    assert art.tags_by_platform["ib"] == ["autumn", "study"]
    assert (artwork_archive / name / "study.png").is_file()
    assert (artwork_archive / name / "artwork.json").is_file()


def test_build_artwork_package(artwork_archive):
    name = artwork_reader.create_artwork(
        title="Pkg Test", image_filename="a.jpg", image_bytes=b"jpgdata",
        rating="adult",
        tags={"default": ["x"], "ib": ["a", "b"]},
        titles={"fa": "FA Title"},
        descriptions={"default": "desc", "bsky": "announce!"},
        categories={"fa": {"cat": "13", "species": "wolf"}},
    )
    art = artwork_reader.load_artwork(name)

    pkg_ib = artwork_reader.build_artwork_package(art, "ib")
    assert isinstance(pkg_ib, StoryUploadPackage)
    assert pkg_ib.chapter_index == 0
    assert pkg_ib.file_type == "jpg"
    assert pkg_ib.file_path.endswith("a.jpg")
    assert pkg_ib.tags == ["a", "b"]
    assert pkg_ib.title == "Pkg Test"
    assert pkg_ib.rating == "adult"

    pkg_fa = artwork_reader.build_artwork_package(art, "fa")
    assert pkg_fa.title == "FA Title"                 # per-platform title override
    assert pkg_fa.extra == {"cat": "13", "species": "wolf"}
    assert pkg_fa.tags == ["x"]                        # fa cascaded from default

    pkg_bsky = artwork_reader.build_artwork_package(art, "bsky")
    assert pkg_bsky.description == "announce!"         # bsky announcement override


def test_create_dedupes_same_title(artwork_archive):
    n1 = artwork_reader.create_artwork(
        title="Dup", image_filename="a.png", image_bytes=b"1")
    n2 = artwork_reader.create_artwork(
        title="Dup", image_filename="a.png", image_bytes=b"2")
    assert n1 == "Dup"
    assert n2 == "Dup_2"


def test_list_artworks_newest_first(artwork_archive):
    artwork_reader.create_artwork(title="One", image_filename="a.png", image_bytes=b"1")
    artwork_reader.create_artwork(title="Two", image_filename="b.png", image_bytes=b"2")
    items = artwork_reader.list_artworks()
    assert {i["name"] for i in items} == {"One", "Two"}


def test_load_artwork_traversal_guard(artwork_archive):
    with pytest.raises(FileNotFoundError):
        artwork_reader.load_artwork("../../etc/passwd")
