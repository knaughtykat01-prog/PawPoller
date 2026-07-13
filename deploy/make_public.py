#!/usr/bin/env python3
"""Assemble a clean, public-safe copy of PawPoller.

This repository stays PRIVATE: it holds personal dev docs, VM ops scripts,
live-account test harnesses, and a git history full of personal references.
This tool copies only the *distributable app* into a separate output tree,
excluding the private dev/ops layer, then scans the result for personal data
and FAILS LOUDLY if anything leaked. Re-run it on every public release.

    python deploy/make_public.py [OUTPUT_DIR]        # build + scan (default ../PawPoller-public)
    python deploy/make_public.py --check-only DIR    # only re-run the leak scan on DIR

The exclude lists are the source of truth for "what is safe to publish".
When you add a new dir/file, decide here whether it ships.
"""
from __future__ import annotations

import argparse
import re
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DEFAULT_OUT = REPO.parent / "PawPoller-public"

# ── What does NOT ship ───────────────────────────────────────────────
# Whole directories excluded from the public copy (matched on the path
# prefix, forward-slash normalised, relative to the repo root).
EXCLUDE_DIRS = {
    "deploy",          # personal VM sync/ops scripts (this tool included)
    "qa",              # personal QA checklists + probe scripts + result CSVs
    "site",            # marketing site — separate Cloudflare Pages project
    "scripts",         # story-authoring helper (inject_chapter_markers)
    "scripts_utils",   # authoring / writing-quality tooling (not imported by the app)
    "docs/reference",  # internal reverse-engineering notes
    "docs/specs",      # internal design specs
    "docs/research",   # internal research notes (live-account validation refs)
    ".plan",           # session planning scratch (VM/user refs)
    "prototype",       # UI-redesign walking skeleton (mock data uses real accounts)
    # runtime / build / vcs — mostly gitignored already; belt-and-braces:
    ".git", ".github/ISSUE_TEMPLATE", "data", "logs", "dist", "build",
    "__pycache__", ".pytest_cache", ".ruff_cache", ".idea", ".vscode",
}

# Individual files excluded (path relative to repo root, forward slashes).
EXCLUDE_FILES = {
    "TODO.md",                       # internal task list
    "CHANGELOG.md",                  # detailed internal history (VM/story refs) — curate a public one separately
    "docs/HANDOFF.md",               # internal session handoff (VM identity, story names)
    "docs/documentation_guide.md",   # internal dev reference (VM identity, story names)
    "cli/pp.sh",                     # personal VM launcher (symlinks into /usr/local/bin on the VM)
    "cli/pawcli.bat",                # personal VM launcher (gcloud-ssh to a specific instance)
    "CLAUDE.md",                     # Claude context router (local only; also gitignored)
    "auto_test_results_2026-05-22.csv",
    ".env", ".env.test", "settings.json", ".vault_key", "settings.vault.json",
    # UI-redesign mockups (untracked working files; mock data uses real accounts)
    "storyboard.html", "ui-directions.html", "ui-directions-2.html",
    "ui-directions-3.html",
}


def keep_test_file(rel: str) -> bool:
    """tests/ holds both the CI unit suite AND personal live/ops harnesses.

    Ship only what pytest collects (test_*.py) plus its fixtures/config;
    drop everything else (live_test_*, verify_*, sf_*, ao3_*, bulk_*,
    debug_*, *.pdf, ...) — those hit live accounts and hardcode the
    private story archive.
    """
    name = Path(rel).name
    if name in ("__init__.py", "conftest.py"):
        return True
    return name.startswith("test_") and name.endswith(".py")


# ── Leak scan — the safety net ───────────────────────────────────────
# If any of these appear in the OUTPUT tree, the build is not publishable.
LEAK_PATTERNS = [
    (re.compile(r"rhysc"), "personal username"),
    (re.compile(r"kithetiger"), "VM username"),
    (re.compile(r"scott\.m\.taylor"), "personal email"),
    (re.compile(r"rhyscharlie"), "personal email"),
    (re.compile(r"knaughtykat01@"), "personal email"),
    (re.compile(r"C:[\\/]Users[\\/]rhysc"), "personal absolute path"),
    (re.compile(r"/home/kithetiger"), "VM absolute path"),
    (re.compile(r"Hypnotic_Claim"), "personal story title"),
    (re.compile(r"Velvet_And_Vice"), "personal story title"),
    (re.compile(r"Extra_Credit"), "personal story title"),
    # Persona separation: "KnaughtyKat" is the app's public brand (installer
    # publisher, GitHub org) and allowed — but the OTHER personas must never
    # be linked to it in a public copy.
    (re.compile(r"hustlestick", re.IGNORECASE), "persona handle"),
    (re.compile(r"kiikinar", re.IGNORECASE), "persona handle"),
    (re.compile(r"kiithetiger", re.IGNORECASE), "persona handle"),
]

# Files we never text-scan (binary / vendored).
_SKIP_SCAN_SUFFIXES = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".pdf", ".woff",
    ".woff2", ".ttf", ".eot", ".zip", ".gz", ".db", ".pyc",
}
# Vendored third-party files legitimately carry an author's email in a
# copyright header — not a personal-data leak.
_SCAN_ALLOWLIST_SUBSTR = ("frontend/js/vendor/",)


def _rel(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def is_excluded(rel: str) -> bool:
    if rel in EXCLUDE_FILES:
        return True
    if Path(rel).name in EXCLUDE_FILES:
        return True
    parts = rel.split("/")
    for i in range(1, len(parts) + 1):
        if "/".join(parts[:i]) in EXCLUDE_DIRS:
            return True
    if parts[0] == "tests" and len(parts) > 1:
        return not keep_test_file(rel)
    return False


def build(out: Path) -> tuple[int, int]:
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    included = excluded = 0
    for src in sorted(REPO.rglob("*")):
        if src.is_dir():
            continue
        rel = _rel(src, REPO)
        if rel.split("/")[0] in {".git"} or "__pycache__" in rel:
            continue
        if is_excluded(rel):
            excluded += 1
            continue
        dst = out / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        included += 1
    return included, excluded


def scan(root: Path) -> list[tuple[str, int, str, str]]:
    """Return [(relpath, lineno, label, line)] for every leak found."""
    hits: list[tuple[str, int, str, str]] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = _rel(path, root)
        if path.suffix.lower() in _SKIP_SCAN_SUFFIXES:
            continue
        if any(s in rel for s in _SCAN_ALLOWLIST_SUBSTR):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            for rx, label in LEAK_PATTERNS:
                if rx.search(line):
                    hits.append((rel, lineno, label, line.strip()[:120]))
    return hits


def main() -> int:
    ap = argparse.ArgumentParser(description="Assemble a public-safe copy of PawPoller.")
    ap.add_argument("output", nargs="?", default=str(DEFAULT_OUT))
    ap.add_argument("--check-only", metavar="DIR",
                    help="skip the build; only re-run the leak scan on DIR")
    args = ap.parse_args()

    if args.check_only:
        target = Path(args.check_only)
        print(f"Leak scan only: {target}")
    else:
        target = Path(args.output).resolve()
        print(f"Building public copy: {REPO}  ->  {target}")
        inc, exc = build(target)
        print(f"  included {inc} files, excluded {exc}")

    hits = scan(target)
    if hits:
        print(f"\n[FAIL] {len(hits)} personal-data leak(s) in the public copy:\n")
        for rel, lineno, label, line in hits:
            safe = line.encode("ascii", "replace").decode("ascii")
            print(f"  {rel}:{lineno}  ({label})")
            print(f"      {safe}")
        print("\nFix: genericise the file in the private repo, or add it to "
              "EXCLUDE_DIRS/EXCLUDE_FILES in deploy/make_public.py.")
        return 1

    print("\n[OK] Leak scan clean — no personal data found in the public copy.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
