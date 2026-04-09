# scripts_utils

**Mirrored copies of writing-pipeline helper scripts that live in
`m_x/Scripts_Utils/`** (which is not under any git repo). These are
backed up here so they don't get lost.

The canonical home for these scripts is `m_x/Scripts_Utils/` on the local
desktop. Run them from there. The copies in this folder are stale by
default — sync them by hand when the canonical versions change, or
delete this folder and re-mirror with `cp` if it gets out of date.

## Scripts

### `generate_pdfs_from_styled.py`

Edge headless HTML→PDF generator that uses **existing styled HTML as
input** (not regenerated from MASTER.md). Used for both full-story PDFs
(`HTML/<Story>_Styled.html` → `PDF/<Story>.pdf`) and per-chapter PDFs
(`Chapters/Styled_HTML/Chapter_*.html` → `Chapters/PDF/Chapter_*.pdf`).

```
python generate_pdfs_from_styled.py <story>            # one story
python generate_pdfs_from_styled.py <story> --full     # full only
python generate_pdfs_from_styled.py <story> --chapters # chapters only
python generate_pdfs_from_styled.py --all              # every story
python generate_pdfs_from_styled.py --all --dry-run    # preview
```

Requires Microsoft Edge installed at one of the standard Windows paths.
Used during the 2026-04-08 styled HTML standardisation pass to
regenerate every story's PDFs after the chapter-heading fix.

### `fix_styled_html_chapters.py`

Bulk converter that takes a styled HTML file with `<p><strong>Chapter X:
Title</strong></p>` markers (the bold-paragraph fallback from a
markdown-to-HTML pass that lost heading semantics) and rewrites them as
`<h2 class="chapter-heading">Chapter X: Title</h2>`. Also auto-inserts
the missing `.chapter-heading` CSS rule and the `:first-of-type`
print-mode rule if absent.

```
python fix_styled_html_chapters.py <html_file> <chapter_color> <accent_rgb>
```

Used during the 2026-04-08 standardisation pass to fix Drumheller, the
Haunting Desires, Silk Threaded Bonds, Velvet & Vice, and both Abstinent
Bet versions. Chosen and Ruins of Breeding had no chapter markers at all
and had to be done manually with content-anchor matching against
MASTER.md.

The script handles `Chapter|Part|Prelude|Epilogue|Interlude` prefixes.

### `strip_stray_em_asterisks.py`

Cleanup helper for styled HTML files that have stray markdown asterisks
left inside `<em>` tags from an old converter mishandling unmatched
italics in MASTER.md. Three bug patterns it fixes:

1. `<em>*</em>` → (deleted entirely) — orphaned italic block from a stray `*`
2. `<em>*Text...</em>` → `<em>Text...</em>` — leading `*` from an unclosed opener
3. `*</em>` → `</em>` — trailing `*` from a stray closing marker

```
python strip_stray_em_asterisks.py <file>...
python strip_stray_em_asterisks.py story/Chapters/Styled_HTML/*.html
```

Idempotent. Returns 0 if all files end up with zero bug patterns.

Used during the 2026-04-09 FA push to clean 47 stray asterisks across
11 files (Silk Threaded Bonds × 5 + Hypnotic × 2 + Extra Credit × 2 +
Ruins of Breeding × 2 + Silk full-story HTML, which was already clean).
The standalone `*read*` emphasis case in Ruins ch2 had to be fixed
manually because that's a different bug class (bare `*word*` standalone
emphasis the old converter never recognised, not a `<em>*` cleanup case).
