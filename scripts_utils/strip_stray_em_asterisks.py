"""Clean up stray markdown asterisks left inside <em> tags in styled HTML files.

Three bug patterns this fixes (all caused by an old converter mishandling
unmatched asterisks in MASTER.md):

  1. <em>*</em>          → (deleted entirely)
                            Orphaned italic-with-just-asterisk block.

  2. <em>*Text...</em>   → <em>Text...</em>
                            Leading * inside an <em> opener — caused when
                            the source MD had an unclosed `*` before the
                            italic, and the converter wrapped both as one.

  3. *...</em>           → ...</em>
                            Trailing * inside an </em> closer — caused when
                            the source MD had a stray `*` after the italic.

The script reports counts before/after for each file.

Usage:
    python strip_stray_em_asterisks.py <file>...
    python strip_stray_em_asterisks.py path1.html path2.html path3.html

Use bash globbing to expand directories:
    python strip_stray_em_asterisks.py story/Chapters/Styled_HTML/*.html
"""
from __future__ import annotations
import re
import sys
from pathlib import Path


PATTERNS = [
    (re.compile(r'<em>\*</em>'),        ''),       # 1. orphans → delete
    (re.compile(r'<em>\*'),             '<em>'),   # 2. <em>* → <em>
    (re.compile(r'\*</em>'),            '</em>'),  # 3. *</em> → </em>
]


def fix_file(path: Path) -> tuple[int, int]:
    """Apply the 3 substitutions. Returns (before_count, after_count)."""
    text = path.read_text(encoding="utf-8")
    bug_re = re.compile(r'<em>\*|\*</em>')
    before = len(bug_re.findall(text))
    if before == 0:
        return 0, 0
    for pat, repl in PATTERNS:
        text = pat.sub(repl, text)
    after = len(bug_re.findall(text))
    if before != after:
        path.write_text(text, encoding="utf-8")
    return before, after


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    files = [Path(p) for p in sys.argv[1:]]
    total_before = 0
    total_after = 0
    n_files_changed = 0
    for f in files:
        if not f.is_file():
            print(f"  [SKIP] not a file: {f}")
            continue
        b, a = fix_file(f)
        total_before += b
        total_after += a
        if b == 0:
            print(f"  [clean] {f}")
        else:
            print(f"  [FIXED] {f}: {b} -> {a}")
            if a == 0:
                n_files_changed += 1
    print()
    print(f"Total: {total_before} bad asterisks across {len(files)} files")
    print(f"After: {total_after} remaining; {n_files_changed} files modified")
    return 0 if total_after == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
