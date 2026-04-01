"""Shared fixtures for posting module tests."""

import json
import os
import sqlite3
import tempfile
from pathlib import Path

import pytest

# Patch config before any PawPoller imports so DB/settings point to temp locations
_tmpdir = tempfile.mkdtemp(prefix="pawpoller_test_")
os.environ["PAWPOLLER_TEST_MODE"] = "1"

import config
config.DB_PATH = Path(_tmpdir) / "test.db"
config.SETTINGS_PATH = Path(_tmpdir) / "test_settings.json"
# Write minimal settings
config.SETTINGS_PATH.write_text("{}", encoding="utf-8")


@pytest.fixture(autouse=False)
def db_conn():
    """Fresh database connection with posting tables wiped between tests."""
    from database.db import init_db, get_connection
    init_db()
    conn = get_connection()
    # Wipe ALL posting tables for test isolation (order matters for FK)
    conn.execute("DELETE FROM posting_log")
    conn.execute("DELETE FROM posting_queue")
    conn.execute("DELETE FROM publications")
    conn.commit()
    yield conn
    conn.close()

    # Also wipe with a separate connection to ensure cross-test isolation
    conn2 = get_connection()
    conn2.execute("DELETE FROM posting_log")
    conn2.execute("DELETE FROM posting_queue")
    conn2.execute("DELETE FROM publications")
    conn2.commit()
    conn2.close()


@pytest.fixture
def story_archive(tmp_path):
    """Create a minimal story archive structure for testing."""
    story_dir = tmp_path / "Test_Story"
    story_dir.mkdir()

    # Markdown/MASTER.md
    md_dir = story_dir / "Markdown"
    md_dir.mkdir()
    (md_dir / "MASTER.md").write_text(
        "# Test Story\n\nOnce upon a time...\n\n---\n\n# Chapter 2: The End\n\nThe end.\n",
        encoding="utf-8",
    )

    # Chapters structure
    chapters_dir = story_dir / "Chapters"
    chapters_dir.mkdir()
    bb_dir = chapters_dir / "BBCode"
    bb_dir.mkdir()
    (bb_dir / "Chapter_1_Beginning.txt").write_text(
        "[center][b]Test Story[/b][/center]\n\nOnce upon a time...\n",
        encoding="utf-8",
    )
    (bb_dir / "Chapter_2_The_End.txt").write_text(
        "[center][b]Chapter 2: The End[/b][/center]\n\nThe end.\n",
        encoding="utf-8",
    )

    sf_dir = chapters_dir / "SoFurry_HTML"
    sf_dir.mkdir()
    (sf_dir / "Chapter_1_Beginning.html").write_text(
        "<p>Once upon a time...</p>",
        encoding="utf-8",
    )

    # split_manifest.json
    manifest = {
        "story": "Test Story",
        "author": "TestAuthor",
        "total_chapters": 2,
        "total_words": 100,
        "split_date": "2026-04-01",
        "chapters": [
            {
                "index": 1,
                "title": "Beginning",
                "filename": "Chapter_1_Beginning",
                "word_count": 60,
                "files": {
                    "markdown": "Markdown/Chapter_1_Beginning.md",
                    "bbcode": "BBCode/Chapter_1_Beginning.txt",
                    "sofurry_html": "SoFurry_HTML/Chapter_1_Beginning.html",
                },
            },
            {
                "index": 2,
                "title": "The End",
                "filename": "Chapter_2_The_End",
                "word_count": 40,
                "files": {
                    "markdown": "Markdown/Chapter_2_The_End.md",
                    "bbcode": "BBCode/Chapter_2_The_End.txt",
                },
            },
        ],
    }
    (chapters_dir / "split_manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )

    # Tags/tags_upload.txt
    tags_dir = story_dir / "Tags"
    tags_dir.mkdir()
    (tags_dir / "tags_upload.txt").write_text(
        """TEST STORY - Master Upload File
=====================================
Total Parts: 2 | Total Words: ~100

STORY DESCRIPTION:
A test story for unit testing.

=============================================
PART 1 OF 2: "Beginning" (~60 words)
=============================================

DESCRIPTION:
Chapter 1 of the test story.

TAGS (5):
furry, anthro, test, story, fiction

INKBUNNY TAGS (Categorized):

Sex/Gender:
male, female

Species:
anthro, furry

Themes/Kinks:
test, fiction

Other Keywords:
story

WATTPAD TAGS (5 max):
furry anthro test story fiction

=============================================
PART 2 OF 2: "The End" (~40 words)
=============================================

DESCRIPTION:
The conclusion.

TAGS (3):
furry, anthro, ending
""",
        encoding="utf-8",
    )

    return tmp_path


@pytest.fixture
def upload_file(tmp_path):
    """Create a small test file for upload testing."""
    f = tmp_path / "test_upload.txt"
    f.write_text("This is a test story for uploading.", encoding="utf-8")
    return str(f)
