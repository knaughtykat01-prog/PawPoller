# PawPoller Story Editor — Implementation Plan

## File Architecture & Sync Model

### The problem the editor solves

Currently, the story pipeline is:
```
MASTER.md → [manual scripts] → BBCode, Clean HTML, Styled HTML, SQW, PDF
           → [pawsync] → server archive
           → [manual posting scripts] → SQW, SF, AO3, IB, FA
```

The editor collapses this to:
```
MASTER.md → [editor auto-regen] → all formats → [one-click push] → all platforms
```

### File ownership model

**MASTER.md is the single source of truth.** The editor reads it, the user edits it, the editor writes it back. ALL other files are derived and can be regenerated at any time.

The editor generates into the SAME folder structure that currently exists:

```
<Story>/
  Markdown/MASTER.md              ← editor reads/writes this
  BBCode/<Story>_bbcode.txt       ← editor generates (full-story BBCode)
  HTML/<Story>_Clean.html         ← editor generates (SoFurry/AO3 body HTML)
  HTML/<Story>_Styled.html        ← editor generates (full HTML doc + CSS)
  PDF/<Story>.pdf                 ← editor generates (from styled HTML)
  SquidgeWorld/Chapter_*.html     ← editor generates (per-chapter body HTML)
  SquidgeWorld/Work_Skin.css      ← editor generates (from theme)
  Chapters/Markdown/Chapter_*.md  ← editor generates (split from MASTER.md)
  Chapters/BBCode/Chapter_*.txt   ← editor generates
  Chapters/SoFurry_HTML/Ch_*.html ← editor generates
  Chapters/Styled_HTML/Ch_*.html  ← editor generates
  Chapters/PDF/Chapter_*.pdf      ← editor generates
  story.json                      ← editor reads (metadata for posting)
  CHAPTER_STYLING.md              ← editor reads/writes (theme variables)
  CHANGELOG.md                    ← editor appends (on regenerate/push)
```

### Sync model

**Desktop mode** (primary use case):
- Editor runs in pywebview, reads/writes `C:/Users/rhysc/claude/m_x/Archives/Complete_Stories/`
- User edits → saves → regenerates → all files updated locally
- `pawsync` pushes the whole archive to the GCP server
- Platform pushes work from either local or server

**Server mode** (Docker):
- Editor runs in the Docker container, reads/writes the Docker-mounted archive volume
- Changes are immediately available for polling/posting
- Local archive is NOT auto-updated (pawsync is one-way local→server)
- For bidirectional sync, a future "pull" command could reverse the sync

**For existing stories**: The editor regenerates files IN PLACE. Existing files are overwritten. The editor creates a backup (`MASTER.md.bak.{timestamp}`) before each save. For the first regeneration of each story, the editor logs what files were overwritten in the CHANGELOG.

### What the editor generates vs what it leaves alone

| File type | Editor generates? | Notes |
|---|---|---|
| MASTER.md | Reads/writes | The source — user edits directly |
| story.json | Reads only (Phase 1) | Metadata for posting; future: editor updates word_count/chapters |
| CHAPTER_STYLING.md | Reads/writes | Theme editor modifies CSS variables |
| CHANGELOG.md | Appends | Auto-entry on regenerate/push |
| BBCode (full + chapters) | Generates | From MASTER.md via converter |
| Clean HTML (full + chapters) | Generates | From MASTER.md via converter |
| Styled HTML (full + chapters) | Generates | From MASTER.md + theme CSS |
| SQW chapters + Work_Skin.css | Generates | From styled HTML + theme |
| PDFs (full + chapters) | Generates | From styled HTML via Edge headless |
| Chapter Markdown splits | Generates | From MASTER.md via chapter splitter |
| Tags/ | Leaves alone | Tag files are manually curated |
| Backups/ | Leaves alone | Historical backups preserved |

## Architecture

### Backend: `editor/` package

```
PawPoller/
  editor/
    __init__.py
    converter.py      ← core parser + format renderers (shared by all)
    pipeline.py       ← full regeneration pipeline (writes files)
    theme.py          ← CHAPTER_STYLING.md ↔ theme variables
    validator.py      ← story validation checks
    slop.py           ← slop score computation
```

### API: `routes/editor_api.py`

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/editor/stories` | List all stories |
| GET | `/api/editor/{story}/content` | Read MASTER.md |
| PUT | `/api/editor/{story}/content` | Save MASTER.md (with backup) |
| POST | `/api/editor/{story}/preview` | Convert markdown → format (in-memory) |
| POST | `/api/editor/{story}/regenerate` | Full pipeline → write all files |
| POST | `/api/editor/{story}/push/{platform}` | Push to platform |
| GET | `/api/editor/{story}/theme` | Read theme variables |
| PUT | `/api/editor/{story}/theme` | Save theme variables |
| POST | `/api/editor/{story}/validate` | Run validation |
| POST | `/api/editor/{story}/slop` | Run slop scorer |

### Frontend: `editor.js` + `editor.css`

Split-pane layout:
- Left: textarea editor (Phase 1) → CodeMirror 6 (Phase 2+)
- Right: live preview with format tabs
- Top: toolbar (save, regenerate, push)
- Bottom: status bar (word count, slop score, dirty state)

## Implementation Phases

### Phase 1: MVP Editor ✅ DONE
- Edit MASTER.md + live preview + save + regenerate
- Backend: converter.py (1800+ lines), editor_api.py, slop.py
- Frontend: editor.js (4-panel quad layout), editor.css

### Phase 2: All format tabs ✅ DONE
- Clean HTML (AO3), SoFurry HTML, BBCode (IB), Styled HTML (PDF) — all 4 in dropdown
- SQW chapter auto-generation from anchored source
- Styled HTML rendered in sandboxed iframe

### Phase 3: Anchor system + converters ✅ DONE
- 7 HTML comment anchors (@title, @subtitle, @byline, @warning, @disclaimer, @fanfiction, @body)
- Standalone converters unified as thin wrappers importing editor/converter.py
- Slop score in editor toolbar (colour-coded badge)

### Phase 4: CSS theme editor ✅ DONE
- External style.css generation from CHAPTER_STYLING.md
- CSS editor panel (5th column toggle)
- Styled HTML uses `<link>` instead of embedded `<style>`
- Live CSS editing with styled preview refresh
- parse_chapter_styling() reads 14 colour variables
- generate_styled_css() produces standalone CSS

### Phase 5: Remaining TODO
- PDF generation via Edge headless (button in editor)
- One-click platform push (reuse existing poster code)
- CodeMirror 6 upgrade (replace textarea with syntax highlighting)
- Anchor highlighting in editor
- Validation panel (asterisk balance, format checks)
- Auto-changelog entries on regenerate/push
