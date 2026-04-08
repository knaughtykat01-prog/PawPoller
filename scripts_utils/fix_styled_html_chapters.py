"""Convert <p><strong>Chapter X: Title</strong></p> markers to
<h2 class="chapter-heading">Chapter X: Title</h2> in styled HTML files,
and add the matching CSS rule + print rule if missing.

Designed for the stories that have the bold-paragraph chapter style:
  - Drumheller_Detour (already done manually)
  - The_Haunting_Desires
  - The_Silk_Threaded_Bonds
  - Velvet_And_Vice
  - The_Abstinent_Bet/Nice_Version
  - The_Abstinent_Bet/Naughty_Version

Usage:
    python fix_styled_html_chapters.py <html_file> <chapter_color> <accent_rgb>

    chapter_color: hex color for h2 text (matches story-title)
    accent_rgb:    "R,G,B" for text-shadow (matches title-rule)

Example:
    python fix_styled_html_chapters.py \\
        ".../The_Haunting_Desires_Styled.html" "#d0ccc8" "122,101,48"

The script:
  1. Finds all `<p><strong>Chapter N: Title</strong></p>` markers
  2. Replaces each with `<h2 class="chapter-heading">Chapter N: Title</h2>`
  3. Inserts a `.chapter-heading { ... }` CSS rule before `/* Print Styles */`
     (skips if a .chapter-heading rule already exists)
  4. Inserts `.chapter-heading:first-of-type { page-break-before: avoid; }`
     in the @media print block (skips if already present)
  5. Reports counts and writes back

DOES NOT touch the body theme colors, page margins, or any other CSS.
"""
from __future__ import annotations
import re
import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) != 4:
        print(__doc__)
        return 1

    html_path = Path(sys.argv[1])
    chapter_color = sys.argv[2].strip()
    accent_rgb = sys.argv[3].strip()

    if not html_path.is_file():
        print(f"file not found: {html_path}")
        return 1

    text = html_path.read_text(encoding="utf-8")

    # ── 1. Convert chapter markers ─────────────────────────────────────
    # Match: <p><strong>Chapter N: Title</strong></p>
    # Also handle: Part One — Title, Prelude: Title, Epilogue
    pattern = re.compile(
        r'<p><strong>((?:Chapter|Part|Prelude|Epilogue|Interlude)\b[^<]*?)</strong></p>'
    )
    matches = pattern.findall(text)
    new_text, n_replaced = pattern.subn(
        lambda m: f'<h2 class="chapter-heading">{m.group(1)}</h2>',
        text,
    )
    print(f"Replaced {n_replaced} chapter markers:")
    for m in matches:
        print(f"  - {m}")

    if n_replaced == 0:
        print("WARNING: no chapter markers found — nothing to convert")

    # ── 2. Add .chapter-heading CSS rule if missing ────────────────────
    # Check if the BASE CSS rule actually exists (not :first-of-type or
    # other pseudo-selectors). The base rule must be ".chapter-heading"
    # immediately followed by whitespace and "{", with no `:` or `,`
    # in between.
    css_rule_pattern = re.compile(
        r'\.chapter-heading[ \t\r\n]*\{[^}]*\}', re.DOTALL,
    )
    if css_rule_pattern.search(new_text):
        print("CSS rule .chapter-heading (base) already exists — skipping insertion")
    else:
        css_rule = (
            "\n        /* Chapter Heading */\n"
            "        .chapter-heading {\n"
            "            text-align: center;\n"
            "            font-size: 1.8rem;\n"
            "            font-weight: normal;\n"
            "            letter-spacing: 0.06em;\n"
            f"            color: {chapter_color};\n"
            "            font-variant: small-caps;\n"
            "            margin-top: 2rem;\n"
            "            margin-bottom: 2rem;\n"
            f"            text-shadow: 0 0 15px rgba({accent_rgb}, 0.1);\n"
            "        }\n"
        )
        anchor = "/* Print Styles */"
        if anchor in new_text:
            new_text = new_text.replace(
                anchor,
                css_rule + "\n        " + anchor,
                1,
            )
            print("Inserted .chapter-heading CSS rule before /* Print Styles */")
        else:
            # Fallback: anchor on @media print
            new_text = new_text.replace(
                "@media print {",
                css_rule + "\n        @media print {",
                1,
            )
            print("Inserted .chapter-heading CSS rule before @media print")

    # ── 3. Add print rule for first chapter ────────────────────────────
    if ".chapter-heading:first-of-type" not in new_text:
        # Find the @media print block and add the rule near the end
        # Anchor: the last `}` before the closing `}` of @media print
        # Simpler approach: insert after a known existing print rule like
        # `.section-break { ... color: ... }` or similar.
        # Even simpler: insert right before the closing of @media print.
        media_print_match = re.search(
            r'(@media\s+print\s*\{)', new_text,
        )
        if media_print_match:
            # Find the matching closing brace by counting
            start = media_print_match.end()
            depth = 1
            i = start
            while i < len(new_text) and depth > 0:
                if new_text[i] == "{":
                    depth += 1
                elif new_text[i] == "}":
                    depth -= 1
                i += 1
            if depth == 0:
                # Insert before the closing brace
                close_pos = i - 1
                indent = "            "
                rule = (
                    f"\n{indent}.chapter-heading:first-of-type {{\n"
                    f"{indent}    page-break-before: avoid;\n"
                    f"{indent}}}\n        "
                )
                new_text = new_text[:close_pos] + rule + new_text[close_pos:]
                print("Inserted .chapter-heading:first-of-type print rule")

    # ── 4. Write back ──────────────────────────────────────────────────
    if new_text == text:
        print("No changes to write")
        return 0

    html_path.write_text(new_text, encoding="utf-8")
    print(f"OK — wrote {html_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
