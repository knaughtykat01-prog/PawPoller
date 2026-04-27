# Test Fixtures

Sample upload payloads referenced by `TESTING_CHECKLIST_WEBAPP.html` and
`TESTING_CHECKLIST_NATIVE.html`. Use these whenever a test row says
"upload a sample file" so results are repeatable across QA runs.

## File index

| File | Used by tests | Purpose |
|------|---------------|---------|
| `sample_story.md`        | Story wizard upload (Markdown)          | Single-chapter MASTER.md with all the common anchor types |
| `sample_story.html`      | Story wizard upload (HTML)              | HTML with headings, bold/italic, lists, blockquote |
| `sample_story.bbcode`    | Story wizard upload (BBCode)            | `[b]`, `[i]`, `[hr]`, `[url]` to verify converter |
| `sample_story.txt`       | Story wizard upload (Plain text)        | Pure body text, no markup |
| `sample_story.rtf`       | Story wizard upload (RTF)               | Minimal RTF doc with bold + italic runs |
| `sample_multichapter.md` | Editor / Publish Check / Regen tests    | 3-chapter MASTER.md with chapter breaks, POV markers, anchors |
| `sample_cover.jpg`       | Cover upload tests                      | 800×1200 cover image (small JPEG) |
| `sample_chapter_thumb.jpg` | Per-chapter thumbnail upload tests    | 600×900 thumbnail JPEG |

## Conventions

- All Markdown samples follow the **MASTER.md convention** documented at
  `m_x/Archives/Complete_Stories/Reference_Guides/MASTER_MD_CONVENTION.md`
  (chapters open with `# Chapter N: Title`, `---` for chapter break,
  POV markers `**⟨ Name ⟩**` on their own line).
- All sample author/character names are fictional and exist only here.
- Image fixtures are intentionally small (under 50 KB each) so the repo
  doesn't bloat. Real-world covers are 200 KB+ — any test that
  validates upload size limits should still reach for a larger file.

## Adding a fixture

1. Drop the file in this directory.
2. Add a row to the table above explaining what it's for.
3. If a checklist test references it, cite the relative path
   from the checklist file: `fixtures/<filename>`.
