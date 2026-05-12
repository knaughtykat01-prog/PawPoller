"""Story archive diagnostics.

All read-only: list stories, validate every story.json, optional
pawsync dry-run.
"""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from pathlib import Path

from posting import story_reader
from testing.registry import TestContext, register_test


_REQUIRED_STORY_JSON_FIELDS = ("title",)  # name is implicit from the folder


@register_test(
    test_id="archive.local_readable",
    name="Local archive listable",
    category="Archive",
    description="The configured archive directory exists and contains story folders.",
)
async def t_archive_listable(ctx: TestContext) -> None:
    path = story_reader.get_archive_path()
    ctx.detail("path", str(path))
    assert path.is_dir(), f"archive not a directory: {path}"
    entries = [p for p in path.iterdir() if p.is_dir()]
    ctx.detail("entry_count", len(entries))
    assert entries, "archive is empty"


@register_test(
    test_id="archive.story_json_valid",
    name="Every story.json is valid JSON with required fields",
    category="Archive",
    description=(
        "Iterate every story folder; any with a story.json must parse "
        "as JSON and include at minimum the 'title' field."
    ),
    timeout_seconds=60.0,
)
async def t_story_json_valid(ctx: TestContext) -> None:
    path = story_reader.get_archive_path()
    failures: list[dict] = []
    checked = 0
    for p in sorted(path.iterdir()):
        if not p.is_dir():
            continue
        sj = p / "story.json"
        if not sj.is_file():
            continue
        checked += 1
        try:
            data = json.loads(sj.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            failures.append({"story": p.name, "reason": f"parse: {exc}"})
            continue
        for field in _REQUIRED_STORY_JSON_FIELDS:
            if not data.get(field):
                failures.append({"story": p.name, "reason": f"missing {field}"})
                break
    ctx.detail("checked", checked)
    ctx.detail("failures", failures)
    assert not failures, f"{len(failures)} story.json failures"


@register_test(
    test_id="archive.pawsync.dry_run",
    name="pawsync.py --dry-run reports cleanly",
    category="Archive",
    description=(
        "Run the local pawsync script in --dry-run mode and confirm it "
        "exits 0. Skipped when the script isn't present (server) or "
        "remote not configured (test instance)."
    ),
    timeout_seconds=60.0,
)
async def t_pawsync_dry_run(ctx: TestContext) -> None:
    script = Path(__file__).resolve().parent.parent.parent / "deploy" / "pawsync.py"
    if not script.is_file():
        raise ctx.skip(f"pawsync.py not present at {script}")
    proc = await asyncio.create_subprocess_exec(
        sys.executable,
        str(script),
        "--dry-run",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=45.0)
    except asyncio.TimeoutError:
        proc.kill()
        raise AssertionError("pawsync dry-run timed out")
    ctx.detail("returncode", proc.returncode)
    ctx.detail("stdout_tail", stdout.decode("utf-8", "replace")[-400:])
    if proc.returncode != 0:
        ctx.detail("stderr_tail", stderr.decode("utf-8", "replace")[-400:])
    # Treat non-zero as a soft skip when the script complains about
    # missing config (test environment) but raise on actual errors.
    if proc.returncode != 0:
        tail = stderr.decode("utf-8", "replace")
        if "not configured" in tail or "remote" in tail.lower():
            raise TestSkippedReason(tail.strip().splitlines()[-1] if tail else "remote not configured")
        raise AssertionError(f"pawsync returned {proc.returncode}: {tail[-200:]}")


# Local alias so the import at the top stays tidy
from testing.registry import TestSkipped as TestSkippedReason  # noqa: E402
