"""Regenerate Chosen's SquidgeWorld body HTML files using the fixed
converter output. Preserves the existing wrapper structure (warning page
on Ch1, chapter-subtitle on others, story-end div on Ch5).

For each chapter:
  1. Read the existing SQW file - extract the WRAPPER (everything before the
     first <p><em>) and the FOOTER (everything after the last <p>).
  2. Read the regenerated SoFurry HTML chapter file - extract just the body
     paragraphs (skip the chapter heading <p><strong>Chapter N: ...</strong></p>).
  3. Concatenate: wrapper + new paragraphs + footer.
  4. Single-line collapse for SQW auto-formatter compatibility.
  5. Save back to the SQW file.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path


CHOSEN_ROOT = Path("C:/Users/rhysc/claude/m_x/Archives/Complete_Stories/Chosen")
SQW_DIR = CHOSEN_ROOT / "SquidgeWorld"
SOURCE_DIR = CHOSEN_ROOT / "Chapters" / "SoFurry_HTML"

CHAPTERS = [
    "Chapter_1_The_Heat",
    "Chapter_2_The_Market",
    "Chapter_3_The_Clearing",
    "Chapter_4_Chosen",
    "Chapter_5_After",
]


def extract_body_paragraphs(sofurry_html: str) -> list[str]:
    """Extract <p>...</p> blocks from the regenerated SoFurry HTML.

    Skips the chapter-heading paragraph (<p><strong>Chapter N: ...</strong></p>).
    Returns single-line versions of each <p> block.
    """
    paragraphs: list[str] = []
    # The SoFurry HTML is body-only with one paragraph per line
    for line in sofurry_html.splitlines():
        line = line.strip()
        if not line:
            continue
        if not line.startswith("<p"):
            continue
        # Skip the chapter heading
        if re.match(r'^<p><strong>Chapter \d+', line):
            continue
        paragraphs.append(line)
    return paragraphs


def split_sqw_file(sqw_html: str) -> tuple[str, str]:
    """Split an existing SQW file into (wrapper, footer).

    Wrapper = everything before the first body paragraph (`<p><em>` or
    `<p>"`).
    Footer = everything after the last body paragraph (typically
    `<p class="section-break">` and any `<div class="story-end">`).
    """
    lines = sqw_html.splitlines()
    body_start = None
    body_end = None
    for i, line in enumerate(lines):
        s = line.strip()
        if body_start is None and (s.startswith('<p><em>') or s.startswith('<p>"')):
            body_start = i
        if s.startswith('<p><em>') or s.startswith('<p>"'):
            body_end = i

    if body_start is None or body_end is None:
        raise RuntimeError("Could not find body paragraphs in SQW file")

    wrapper = "\n".join(lines[:body_start]).rstrip() + "\n"
    footer_lines = lines[body_end + 1:]
    footer = "\n".join(footer_lines).rstrip()
    return wrapper, footer


def regen_chapter(name: str) -> tuple[bool, str]:
    sqw_path = SQW_DIR / f"{name}.html"
    src_path = SOURCE_DIR / f"{name}.html"

    if not sqw_path.is_file():
        return False, f"missing SQW file: {sqw_path}"
    if not src_path.is_file():
        return False, f"missing source: {src_path}"

    old_sqw = sqw_path.read_text(encoding="utf-8")
    new_source = src_path.read_text(encoding="utf-8")

    try:
        wrapper, footer = split_sqw_file(old_sqw)
    except RuntimeError as e:
        return False, str(e)

    new_paragraphs = extract_body_paragraphs(new_source)
    if not new_paragraphs:
        return False, "no paragraphs extracted from source"

    body = "\n".join(new_paragraphs)
    new_content = wrapper + body
    if footer:
        new_content += "\n" + footer
    new_content = new_content.rstrip() + "\n"

    sqw_path.write_text(new_content, encoding="utf-8")
    return True, f"{len(new_paragraphs)} paragraphs"


def main() -> int:
    print(f"Regenerating Chosen SquidgeWorld files using fixed source...")
    print()
    all_ok = True
    for name in CHAPTERS:
        ok, msg = regen_chapter(name)
        symbol = "OK" if ok else "FAIL"
        print(f"  [{symbol}] {name}.html — {msg}")
        if not ok:
            all_ok = False

    print()
    print("Verifying strong tag counts (should be reasonable, not 86)...")
    for name in CHAPTERS:
        sqw_path = SQW_DIR / f"{name}.html"
        if sqw_path.is_file():
            content = sqw_path.read_text(encoding="utf-8")
            strong_count = content.count("<strong>")
            print(f"  {name}: {strong_count} strong tags")

    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
