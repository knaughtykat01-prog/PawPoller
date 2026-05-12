"""One-shot: inject `# Chapter N: Title` markers into a story's MASTER.md.

For stories whose chapters live only in `chapters.json` line-ranges
(or in `Chapters/Markdown/Chapter_*.md` files) but lack `# Chapter X`
headings in the MASTER.md body, this script locates each chapter's
first content line in MASTER.md by matching the corresponding
per-chapter file's first content line, then inserts a heading
directly before it.

Backs up MASTER.md → MASTER.md.bak before writing. Idempotent: if
markers are already present, exits without changes.

Usage:
    python scripts/inject_chapter_markers.py <story_folder>
    # e.g.
    python scripts/inject_chapter_markers.py \
        ../m_x/Archives/Complete_Stories/Extra_Credit
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path


def first_content_line(md_path: Path) -> str:
    """Return the first non-empty, non-heading, non-separator line of
    a chapter markdown file. Used as the anchor to find this chapter
    in MASTER.md."""
    text = md_path.read_text(encoding="utf-8-sig")  # strip BOM
    for line in text.split("\n"):
        s = line.strip()
        if not s:
            continue
        if s.startswith("#"):  # title / heading lines we don't anchor on
            continue
        if s == "---":  # horizontal rule separators
            continue
        return s
    return ""


def main():
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(1)
    story_dir = Path(sys.argv[1]).resolve()
    if not story_dir.is_dir():
        sys.exit(f"not a directory: {story_dir}")

    master = story_dir / "Markdown" / "MASTER.md"
    if not master.is_file():
        sys.exit(f"no MASTER.md at {master}")

    chapters_json = story_dir / "chapters.json"
    if not chapters_json.is_file():
        sys.exit(f"no chapters.json at {chapters_json}")

    chapters_md_dir = story_dir / "Chapters" / "Markdown"
    if not chapters_md_dir.is_dir():
        sys.exit(f"no Chapters/Markdown/ at {chapters_md_dir}")

    meta = json.loads(chapters_json.read_text(encoding="utf-8"))
    chapter_specs = meta.get("chapters", [])
    if not chapter_specs:
        sys.exit("chapters.json has empty 'chapters' array")

    # Pair each spec with its on-disk per-chapter file. The convention is
    # Chapter_{N}_{TitleSafe}.md where N is 1-indexed. Sort by N (numeric)
    # so Chapter_10 lands AFTER Chapter_9, not between Chapter_1 and Chapter_2
    # like a lexicographic sort would.
    import re
    def _chnum(p: Path) -> int:
        m = re.match(r"Chapter_(\d+)_", p.name)
        return int(m.group(1)) if m else 0
    pairs = []
    ch_files = sorted(chapters_md_dir.glob("Chapter_*.md"), key=_chnum)
    if len(ch_files) != len(chapter_specs):
        sys.exit(
            f"chapter count mismatch: chapters.json has {len(chapter_specs)} "
            f"but Chapters/Markdown/ has {len(ch_files)} files"
        )
    for idx, (spec, ch_file) in enumerate(zip(chapter_specs, ch_files), start=1):
        anchor = first_content_line(ch_file)
        if not anchor:
            sys.exit(f"chapter {idx} ({ch_file.name}) — no content line found")
        pairs.append({
            "number": idx,
            "title": spec.get("title", ch_file.stem),
            "file": ch_file.name,
            "anchor": anchor[:120],  # truncate for matching reliability
        })

    master_text = master.read_text(encoding="utf-8")
    master_lines = master_text.split("\n")

    # Sanity: refuse to operate on a master that already has `# Chapter` headings.
    body_anchor_idx = None
    for i, line in enumerate(master_lines):
        if line.strip() == "<!-- @body -->":
            body_anchor_idx = i
            break
    if body_anchor_idx is None:
        sys.exit("MASTER.md has no `<!-- @body -->` anchor")

    existing_chapters_after_body = [
        i for i, line in enumerate(master_lines)
        if i > body_anchor_idx and line.strip().startswith("# ")
    ]
    if existing_chapters_after_body:
        print("MASTER.md already has the following `# ...` headings after @body:")
        for i in existing_chapters_after_body[:5]:
            print(f"  line {i + 1}: {master_lines[i]}")
        sys.exit("refusing to inject — markers already present (or unrelated headings exist)")

    # Locate each chapter's anchor in MASTER.md (must appear AFTER @body)
    inserts: list[tuple[int, str]] = []  # (line_index, heading_text)
    for pair in pairs:
        anchor_prefix = pair["anchor"][:80]  # match against a stable prefix
        found = None
        for i in range(body_anchor_idx + 1, len(master_lines)):
            if anchor_prefix in master_lines[i]:
                # Only accept the FIRST occurrence so duplicate phrases
                # (e.g. recurring sentences) don't anchor wrong.
                # Subsequent chapters look from later in the file.
                found = i
                break
        if found is None:
            sys.exit(
                f"could not locate chapter {pair['number']} ({pair['title']}) "
                f"in MASTER.md — anchor: {anchor_prefix!r}"
            )
        # Heading text: "# Chapter N: Title" (matches PawPoller convention)
        heading = f"# Chapter {pair['number']}: {pair['title']}"
        inserts.append((found, heading))
        # Advance the search window for next chapter so we don't re-match
        body_anchor_idx = found

    # Build new text: insert heading + blank line before each anchor's line.
    # Iterate from BACK to FRONT so earlier indices stay valid.
    new_lines = list(master_lines)
    for line_idx, heading in reversed(inserts):
        new_lines.insert(line_idx, "")        # blank after heading
        new_lines.insert(line_idx, heading)   # the heading itself
        # Optionally: also strip a preceding `---` if it was acting as the
        # chapter separator (so we don't end up with `# Chapter 2` directly
        # under a horizontal rule). Keep things conservative for now.

    # Backup + write
    backup_path = master.with_suffix(master.suffix + ".bak")
    if not backup_path.exists():
        shutil.copy2(master, backup_path)
        print(f"backed up: {backup_path}")
    else:
        print(f"backup already exists, leaving as-is: {backup_path}")

    master.write_text("\n".join(new_lines), encoding="utf-8")
    print(f"wrote: {master}")
    print(f"injected {len(inserts)} chapter headings:")
    for (line_idx, heading), pair in zip(inserts, pairs):
        # line_idx now reflects the OLD position; new line will be a bit later.
        print(f"  before line {line_idx + 1}: {heading}")


if __name__ == "__main__":
    main()
