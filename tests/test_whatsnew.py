"""What's-new endpoint (2.134.0) — CHANGELOG parse + `since` filtering for the
in-app update popup."""
import config
from routes import whatsnew_api as wn


def test_parse_changelog_extracts_entries():
    text = ("# CL\n\n---\n\n## [2.2.0] - 2026-01-02 - Title B\n\nbody B\n\n---\n\n"
            "## [2.1.0] - 2026-01-01 - Title A\n\nbody A\n")
    entries = wn._parse_changelog(text)
    assert [e["version"] for e in entries] == ["2.2.0", "2.1.0"]
    assert entries[0]["header"].endswith("Title B")
    assert "body B" in entries[0]["body"] and "---" not in entries[0]["body"]


def test_whatsnew_since_filters(monkeypatch):
    text = ("## [2.3.0] - d - C\n\nc\n\n---\n\n## [2.2.0] - d - B\n\nb\n\n---\n\n"
            "## [2.1.0] - d - A\n\na\n")
    monkeypatch.setattr(wn, "_load_changelog", lambda: text)
    monkeypatch.setattr(config, "APP_VERSION", "2.3.0")
    r = wn.whatsnew(since="2.1.0")               # 2.1.0 (exclusive) → 2.3.0 (current)
    assert r["current"] == "2.3.0"
    assert [e["version"] for e in r["entries"]] == ["2.3.0", "2.2.0"]
    assert r["truncated"] is False


def test_whatsnew_first_run_empty(monkeypatch):
    monkeypatch.setattr(config, "APP_VERSION", "2.3.0")
    assert wn.whatsnew(since="")["entries"] == []          # first run → show nothing


def test_whatsnew_already_current_empty(monkeypatch):
    text = "## [2.3.0] - d - C\n\nc\n"
    monkeypatch.setattr(wn, "_load_changelog", lambda: text)
    monkeypatch.setattr(config, "APP_VERSION", "2.3.0")
    assert wn.whatsnew(since="2.3.0")["entries"] == []     # already on current


def test_whatsnew_truncates(monkeypatch):
    text = "\n".join(f"## [1.0.{i}] - d - v{i}\n\nbody{i}\n\n---\n" for i in range(20, 0, -1))
    monkeypatch.setattr(wn, "_load_changelog", lambda: text)
    monkeypatch.setattr(config, "APP_VERSION", "1.0.20")
    r = wn.whatsnew(since="1.0.1")               # 1.0.2..1.0.20 = 19 → capped at 12
    assert len(r["entries"]) == wn._MAX_ENTRIES
    assert r["truncated"] is True
