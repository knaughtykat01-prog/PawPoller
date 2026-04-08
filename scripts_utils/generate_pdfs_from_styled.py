"""Generate PDFs from existing Styled HTML files.

Unlike regenerate_story.py which rebuilds Styled HTML from MASTER.md
(which we DON'T want — Styled HTML is manually maintained), this script
ONLY runs Edge headless on the existing styled HTML files and writes the
PDFs to PDF/ and Chapters/PDF/.

For each story under m_x/Archives/Complete_Stories/:
  - Full story:  HTML/<Story>_Styled.html  -> PDF/<Story>.pdf
  - Per chapter: Chapters/Styled_HTML/Chapter_*.html
                 -> Chapters/PDF/Chapter_*.pdf

Multi-version stories (e.g. The_Abstinent_Bet/Nice_Version) are handled
via the same logic — pass the subfolder path as the story.

Usage:
    python generate_pdfs_from_styled.py <story>            # one story
    python generate_pdfs_from_styled.py <story> --full     # full only, no chapters
    python generate_pdfs_from_styled.py <story> --chapters # chapters only
    python generate_pdfs_from_styled.py --all              # every story in archive
    python generate_pdfs_from_styled.py --all --dry-run    # show what would be done

Requires: Microsoft Edge installed at one of:
    C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe
    C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

ARCHIVE_ROOT = Path(r"C:\Users\rhysc\claude\m_x\Archives\Complete_Stories")

EDGE_PATHS = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]

# Stories with version subfolders (their Styled HTML lives one level deeper)
VERSIONED_STORIES: dict[str, list[str]] = {
    "The_Abstinent_Bet": ["Nice_Version", "Naughty_Version"],
}


def find_edge() -> str | None:
    for p in EDGE_PATHS:
        if os.path.isfile(p):
            return p
    return None


def html_to_pdf(html_path: Path, pdf_path: Path, edge_exe: str) -> tuple[bool, int, str]:
    """Run Edge headless to convert HTML to PDF.

    Returns (success, size_kb, error_message).
    """
    if not html_path.is_file():
        return False, 0, f"input does not exist: {html_path}"

    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    if pdf_path.exists():
        pdf_path.unlink()  # Edge appends to existing files in some configs

    html_url = "file:///" + str(html_path.resolve()).replace("\\", "/")
    pdf_arg = str(pdf_path.resolve()).replace("\\", "/")
    cmd = [
        edge_exe,
        "--headless",
        "--disable-gpu",
        "--no-margins",
        f"--print-to-pdf={pdf_arg}",
        html_url,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    except subprocess.TimeoutExpired:
        return False, 0, "edge timed out (>180s)"

    # Edge often returns non-zero even on success — trust the file presence + size check
    if not pdf_path.exists():
        return False, 0, f"PDF not created: {result.stderr.strip()[:200]}"
    size = pdf_path.stat().st_size
    if size < 500:
        return False, 0, f"PDF created but too small ({size} bytes)"
    return True, size // 1024, ""


def collect_styled_files(story_path: Path) -> tuple[Path | None, list[Path]]:
    """Find the full-story styled HTML and the per-chapter styled HTML files for a story.

    Returns (full_html or None, chapter_html_list_sorted).
    """
    full = None
    html_dir = story_path / "HTML"
    if html_dir.is_dir():
        for f in sorted(html_dir.glob("*_Styled.html")):
            full = f
            break

    chapters: list[Path] = []
    ch_dir = story_path / "Chapters" / "Styled_HTML"
    if ch_dir.is_dir():
        chapters = sorted(ch_dir.glob("Chapter_*.html"))

    return full, chapters


def expand_story_paths(story_arg: str | None) -> list[Path]:
    """Expand a story name (or --all) into a list of story directories.

    Multi-version stories produce one entry per version subfolder.
    """
    out: list[Path] = []
    if story_arg is None:
        # --all
        for entry in sorted(ARCHIVE_ROOT.iterdir()):
            if not entry.is_dir() or entry.name in ("Reference_Guides",):
                continue
            if entry.name in VERSIONED_STORIES:
                for v in VERSIONED_STORIES[entry.name]:
                    out.append(entry / v)
            else:
                out.append(entry)
    else:
        path = ARCHIVE_ROOT / story_arg
        if not path.is_dir():
            raise SystemExit(f"story not found: {path}")
        # If the user gave a top-level versioned story, expand to its versions
        if story_arg in VERSIONED_STORIES:
            for v in VERSIONED_STORIES[story_arg]:
                out.append(path / v)
        else:
            out.append(path)
    return out


def process_story(
    story_path: Path,
    edge_exe: str,
    do_full: bool,
    do_chapters: bool,
    dry_run: bool,
) -> tuple[int, int]:
    """Generate PDFs for one story directory. Returns (n_ok, n_fail)."""
    rel = story_path.relative_to(ARCHIVE_ROOT)
    print(f"\n=== {rel} ===")

    full_html, chapter_htmls = collect_styled_files(story_path)
    n_ok = 0
    n_fail = 0

    # Full story PDF
    if do_full:
        if full_html is None:
            print(f"  [skip] no full-story styled HTML in HTML/")
        else:
            # Output: PDF/<Story>.pdf — name from the styled file stem (drop _Styled)
            stem = full_html.stem.replace("_Styled", "")
            pdf_path = story_path / "PDF" / f"{stem}.pdf"
            if dry_run:
                print(f"  [dry] {full_html.name}  ->  PDF/{pdf_path.name}")
                n_ok += 1
            else:
                t0 = time.time()
                ok, size_kb, err = html_to_pdf(full_html, pdf_path, edge_exe)
                dt = time.time() - t0
                if ok:
                    print(f"  [OK] PDF/{pdf_path.name}  ({size_kb} KB, {dt:.1f}s)")
                    n_ok += 1
                else:
                    print(f"  [FAIL] PDF/{pdf_path.name}  ({err})")
                    n_fail += 1

    # Per-chapter PDFs
    if do_chapters:
        if not chapter_htmls:
            print(f"  [skip] no chapter styled HTML in Chapters/Styled_HTML/")
        else:
            for ch_html in chapter_htmls:
                # Output: Chapters/PDF/<same name>.pdf
                pdf_path = story_path / "Chapters" / "PDF" / f"{ch_html.stem}.pdf"
                if dry_run:
                    print(f"  [dry] Chapters/Styled_HTML/{ch_html.name}  ->  Chapters/PDF/{pdf_path.name}")
                    n_ok += 1
                else:
                    t0 = time.time()
                    ok, size_kb, err = html_to_pdf(ch_html, pdf_path, edge_exe)
                    dt = time.time() - t0
                    if ok:
                        print(f"  [OK] Chapters/PDF/{pdf_path.name}  ({size_kb} KB, {dt:.1f}s)")
                        n_ok += 1
                    else:
                        print(f"  [FAIL] Chapters/PDF/{pdf_path.name}  ({err})")
                        n_fail += 1

    return n_ok, n_fail


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate PDFs from styled HTML")
    parser.add_argument("story", nargs="?", help="story name or --all")
    parser.add_argument("--all", action="store_true", help="process every story under Complete_Stories/")
    parser.add_argument("--full", action="store_true", help="full-story PDFs only")
    parser.add_argument("--chapters", action="store_true", help="chapter PDFs only")
    parser.add_argument("--dry-run", action="store_true", help="show what would be done, don't run Edge")
    args = parser.parse_args()

    if not args.all and args.story is None:
        parser.print_help()
        return 1

    edge_exe = find_edge() or ""
    if not edge_exe and not args.dry_run:
        print("ERROR: Microsoft Edge not found at any expected path:", file=sys.stderr)
        for p in EDGE_PATHS:
            print(f"  - {p}", file=sys.stderr)
        return 1

    do_full = args.full or not args.chapters
    do_chapters = args.chapters or not args.full

    story_arg = None if args.all else args.story
    story_paths = expand_story_paths(story_arg)
    print(f"Edge: {edge_exe or '(dry-run)'}")
    print(f"Stories to process: {len(story_paths)}")
    print(f"Mode: full={do_full}  chapters={do_chapters}  dry_run={args.dry_run}")

    total_ok = 0
    total_fail = 0
    t0 = time.time()
    for sp in story_paths:
        n_ok, n_fail = process_story(sp, edge_exe, do_full, do_chapters, args.dry_run)
        total_ok += n_ok
        total_fail += n_fail
    dt = time.time() - t0

    print()
    print("=" * 70)
    print(f"Done in {dt:.0f}s — {total_ok} succeeded, {total_fail} failed")
    return 0 if total_fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
