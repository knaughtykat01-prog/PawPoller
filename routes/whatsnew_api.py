"""What's-new — serves CHANGELOG.md entries the user hasn't seen yet, for the
in-app "what changed after this update" popup (frontend/js/app.js).

The app pops a changelog when the running version differs from the one this
browser last saw. Pure read of the bundled CHANGELOG.md — no state stored here;
the "last seen" version lives in the browser (localStorage) and arrives as the
``since`` query param.
"""
import logging
import re

from fastapi import APIRouter

import config

logger = logging.getLogger(__name__)

whatsnew_router = APIRouter(prefix="/api", tags=["whatsnew"])

# "## [2.133.0] - 2026-07-17 - Title"
_HEADER = re.compile(r"(?m)^##\s*\[(\d+\.\d+\.\d+)\]([^\n]*)\n")

# Cap so a big version jump (e.g. desktop v2.53 → v2.133) doesn't return a wall
# of text; the modal notes when older entries were trimmed.
_MAX_ENTRIES = 12


def _vtuple(v: str) -> tuple:
    try:
        return tuple(int(x) for x in str(v).split("."))
    except Exception:
        return ()


def _parse_changelog(text: str) -> list[dict]:
    """Every entry as ``{version, header, body}``, in file order (newest first)."""
    matches = list(_HEADER.finditer(text or ""))
    out = []
    for i, m in enumerate(matches):
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = re.sub(r"\n*-{3,}\s*$", "", text[start:end]).strip()   # drop trailing '---'
        out.append({"version": m.group(1), "header": m.group(2).strip(" -\t"), "body": body})
    return out


def _load_changelog() -> str:
    try:
        return config.resource_path("CHANGELOG.md").read_text(encoding="utf-8")
    except Exception as e:  # bundled in the desktop build; present at /app on server
        logger.warning("Could not read CHANGELOG.md for /api/whatsnew: %s", e)
        return ""


@whatsnew_router.get("/whatsnew")
def whatsnew(since: str = ""):
    """CHANGELOG entries newer than ``since`` (the version this browser last saw),
    up to the running version. Returns ``{current, entries, truncated}``. When
    ``since`` is empty (first run) or already current, ``entries`` is empty so the
    frontend shows nothing."""
    current = config.APP_VERSION
    since_t, cur_t = _vtuple(since), _vtuple(current)

    if not since or (since_t and since_t >= cur_t):
        return {"current": current, "entries": [], "truncated": False}

    newer = [e for e in _parse_changelog(_load_changelog())
             if since_t < _vtuple(e["version"]) <= cur_t]
    return {
        "current": current,
        "entries": newer[:_MAX_ENTRIES],
        "truncated": len(newer) > _MAX_ENTRIES,
    }
