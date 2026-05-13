"""PawPoller story-archive sync to GCP server.

Replaces the original pawsync.bat which suffered two intermittent bugs:

1. **Windows tar batch hang.** Windows tar (libarchive port) interprets
   ``C:\\...`` paths as remote SSH hosts and silently fails unless given
   ``--force-local``. Without it the pack would emit a "Cannot connect to C:"
   error and the script would proceed to upload whatever stale tarball was
   left in %TEMP% from the last run. The Python ``tarfile`` module is
   cross-platform and doesn't have this gotcha.

2. **gcloud batch-context hang.** When ``gcloud compute scp`` was invoked
   from inside a .bat file, it would silently hang somewhere after the
   upload reached 100% — never reaching the next command, never returning
   control to cmd.exe. The same gcloud command worked fine in interactive
   contexts and in inline ``cmd /c "..."`` chains. Adding ``--quiet`` and
   ``< nul`` did not fix it. Python's ``subprocess.run`` with explicit
   ``stdin=subprocess.DEVNULL`` is deterministic and doesn't have this
   problem.

Usage:
    python deploy/pawsync.py [--prune] [--dry-run] [--force]
    pawsync.bat                  # Thin wrapper around this script

Behaviour:
    - **Pre-flight freshness check:** before upload, compares every
      ``story.json`` on the server with the local copy. If any server
      file is newer by >60s (the threshold above tar's mtime-restore
      precision), aborts with an actionable message telling the user
      to run ``pawpull`` first. This catches the failure mode where a
      dashboard edit on the running container is silently clobbered by
      a pawsync run from a stale local copy. ``--force`` skips the
      check — use only when you intentionally want local to win.
    - Packs every story under ``m_x/Archives/Complete_Stories/`` (excluding
      ``Backups/``, ``Drafts/``, ``Styled_HTML/``) into a tar.gz in %TEMP%.
    - Uploads to ``/tmp/story-archive.tar.gz`` on the GCP VM as user
      ``kithetiger`` (must match the extract user — sticky bit on /tmp).
    - Extracts to ``/home/kithetiger/story-archive/`` and chmods o+rX.
    - Removes the temp tarball on both ends.
    - Aborts on any failure (no silent stale uploads).

    With ``--prune``: after extract, removes any top-level directory under
    ``/home/kithetiger/story-archive/`` that doesn't exist locally. Useful
    after deleting test stories. Top-level only — does not recurse into
    stories. The local exclude set (``Backups/Drafts/Styled_HTML``) is
    treated as untouchable so server-side housekeeping folders survive.

    With ``--dry-run``: prints what prune would remove without removing it.
    Implies ``--prune``. Still uploads + extracts.

    With ``--force``: skips the pre-flight freshness check. Local wins
    unconditionally. Equivalent to the pre-2.22.7 behaviour.

Exit codes:
    0  success
    1  generic error (tar pack, scp, ssh, extract)
    2  user-cancelled / unexpected
    3  freshness check failed — server has newer story.json than local
"""
from __future__ import annotations

import argparse
import datetime
import os
import sys
import subprocess
import tarfile
import tempfile
from pathlib import Path

# ── Configuration ──────────────────────────────────────────────────────────

ARCHIVE_ROOT = Path(r"C:\Users\rhysc\claude\m_x\Archives\Complete_Stories")
GCP_INSTANCE = "pawpoller"
GCP_ZONE = "us-east1-c"
GCP_USER = "kithetiger"          # MUST be a user on the VM, not your Google identity
GCP_TMP_PATH = "/tmp/story-archive.tar.gz"
GCP_DEST_DIR = "/home/kithetiger/story-archive"

# Patterns to exclude from the archive (substring match against the relative path)
EXCLUDE_DIR_NAMES = {"Backups", "Drafts", "Styled_HTML"}


def _local_tarball() -> Path:
    return Path(tempfile.gettempdir()) / "story-archive.tar.gz"


def _filter_member(tarinfo: tarfile.TarInfo) -> tarfile.TarInfo | None:
    """Skip Backups/Drafts/Styled_HTML directories anywhere in the path."""
    parts = Path(tarinfo.name).parts
    for excluded in EXCLUDE_DIR_NAMES:
        if excluded in parts:
            return None
    return tarinfo


def pack(local_tar: Path) -> list[str]:
    """Pack the archive and return the list of top-level story names included."""
    print(f"[1/4] Packing stories from {ARCHIVE_ROOT} -> {local_tar}")
    if local_tar.exists():
        local_tar.unlink()
    if not ARCHIVE_ROOT.is_dir():
        raise RuntimeError(f"Archive root not found: {ARCHIVE_ROOT}")

    # Pack each top-level entry under ARCHIVE_ROOT individually so the
    # tarball mirrors a flat layout (Tombstone/, Chosen/, ...).
    n_files = 0
    n_skipped = 0
    top_level: list[str] = []
    with tarfile.open(local_tar, "w:gz") as tar:
        for entry in sorted(ARCHIVE_ROOT.iterdir()):
            if entry.name in EXCLUDE_DIR_NAMES:
                continue
            if entry.is_dir():
                top_level.append(entry.name)
            for fp in entry.rglob("*"):
                if fp.is_file():
                    rel = fp.relative_to(ARCHIVE_ROOT)
                    if any(p in EXCLUDE_DIR_NAMES for p in rel.parts):
                        n_skipped += 1
                        continue
                    tar.add(fp, arcname=str(rel).replace("\\", "/"), filter=_filter_member)
                    n_files += 1

    size_mb = local_tar.stat().st_size / (1024 * 1024)
    print(f"  packed {n_files:,} files ({size_mb:.1f} MB), skipped {n_skipped:,} from {len(top_level)} stories")
    return top_level


def scp_upload(local_tar: Path) -> None:
    print(f"[2/4] Uploading to {GCP_USER}@{GCP_INSTANCE}:{GCP_TMP_PATH}")
    # On Windows, gcloud is `gcloud.cmd`. shell=True lets the OS find it.
    cmd = (
        f'gcloud --quiet compute scp '
        f'--zone={GCP_ZONE} '
        f'"{local_tar}" '
        f'{GCP_USER}@{GCP_INSTANCE}:{GCP_TMP_PATH}'
    )
    result = subprocess.run(
        cmd,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=600,  # 10 minutes max for upload
        shell=True,
    )
    if result.stdout:
        # gcloud writes scp progress to stderr; stdout is usually empty
        for line in result.stdout.splitlines():
            if line.strip():
                print(f"    {line}")
    if result.returncode != 0:
        print(f"  scp stderr: {result.stderr}", file=sys.stderr)
        raise RuntimeError(f"scp failed with exit code {result.returncode}")
    print("  upload complete")


def ssh_extract() -> None:
    remote_cmd = (
        f"cd {GCP_DEST_DIR} && "
        f"tar xzf {GCP_TMP_PATH} && "
        f"sudo chmod -R o+rwX {GCP_DEST_DIR} && "
        f"rm -f {GCP_TMP_PATH}"
    )
    print(f"[3/4] Extracting on server ({GCP_USER}@{GCP_INSTANCE})")
    # Escape any double-quotes in the remote command for the shell wrapper
    safe_remote = remote_cmd.replace('"', '\\"')
    cmd = (
        f'gcloud --quiet compute ssh '
        f'--zone={GCP_ZONE} '
        f'{GCP_USER}@{GCP_INSTANCE} '
        f'--command="{safe_remote}"'
    )
    result = subprocess.run(
        cmd,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=300,  # 5 minutes max for extract
        shell=True,
    )
    if result.stdout.strip():
        print(f"  stdout: {result.stdout.strip()}")
    if result.stderr.strip():
        # gcloud often writes informational messages to stderr that are not errors
        print(f"  stderr: {result.stderr.strip()}", file=sys.stderr)
    if result.returncode != 0:
        raise RuntimeError(f"extract failed with exit code {result.returncode}")
    print("  extract complete")


def _ssh(remote_cmd: str, *, timeout: int = 120) -> str:
    """Run a remote shell command, return stdout. Raises on non-zero exit."""
    safe_remote = remote_cmd.replace('"', '\\"')
    cmd = (
        f'gcloud --quiet compute ssh '
        f'--zone={GCP_ZONE} '
        f'{GCP_USER}@{GCP_INSTANCE} '
        f'--command="{safe_remote}"'
    )
    result = subprocess.run(
        cmd,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=timeout,
        shell=True,
    )
    if result.returncode != 0:
        if result.stderr.strip():
            print(f"  stderr: {result.stderr.strip()}", file=sys.stderr)
        raise RuntimeError(f"ssh command failed with exit code {result.returncode}")
    return result.stdout


# ── Freshness check (added 2.22.7) ─────────────────────────────────────────

# Threshold above which a server-newer story.json is considered an
# independent server-side edit rather than tar-restore noise. Tar
# preserves mtimes to whole-second precision; in practice post-extract
# server mtime equals local mtime exactly. 60s gives generous headroom
# for clock skew without masking real dashboard edits (which always
# produce deltas of minutes or more).
_FRESHNESS_SKEW_SECONDS = 60


def _server_story_json_mtimes() -> dict[str, float]:
    """Return {relative_path: unix_mtime} for every story.json on the server.

    Relative path is rooted at GCP_DEST_DIR, e.g. "Tombstone/story.json"
    or "The_Abstinent_Bet/Nice_Version/story.json". Matches the relative
    layout used by ARCHIVE_ROOT locally, so paths can be compared 1:1.
    """
    # find ... -printf "%T@ %P\n" gives "1778210960.1234567890 Tombstone/story.json"
    # per line. Sorting and parsing is trivial.
    out = _ssh(
        f"find {GCP_DEST_DIR} -name story.json -type f -printf '%T@ %P\\n'"
    )
    result: dict[str, float] = {}
    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            ts_str, rel = line.split(" ", 1)
            result[rel] = float(ts_str)
        except ValueError:
            # Defensive: if find emits anything malformed, skip rather than crash
            continue
    return result


def _local_story_json_mtimes() -> dict[str, float]:
    """Return {relative_path: unix_mtime} for every story.json locally.

    Relative path is rooted at ARCHIVE_ROOT, using forward slashes to
    match server-side output regardless of host OS.
    """
    result: dict[str, float] = {}
    for p in ARCHIVE_ROOT.rglob("story.json"):
        # Skip excluded directories
        rel_parts = p.relative_to(ARCHIVE_ROOT).parts
        if any(part in EXCLUDE_DIR_NAMES for part in rel_parts):
            continue
        rel = p.relative_to(ARCHIVE_ROOT).as_posix()
        result[rel] = p.stat().st_mtime
    return result


def check_server_freshness() -> list[tuple[str, float, float]]:
    """Return list of (path, server_ts, local_ts) where server is meaningfully newer.

    Empty list means it's safe to overwrite — nothing on the server has
    state that pawsync would clobber. A non-empty list is the failure
    mode this check exists to catch.
    """
    print("[0/4] Checking server freshness (story.json mtimes)")
    server = _server_story_json_mtimes()
    local = _local_story_json_mtimes()
    newer: list[tuple[str, float, float]] = []
    for path, server_ts in server.items():
        local_ts = local.get(path)
        if local_ts is None:
            # File exists only on server — pawsync's tar doesn't touch
            # paths it doesn't include, so this isn't a clobber risk.
            # (It'd only be lost on --prune, which only affects top-level
            # story dirs missing locally, not individual files.)
            continue
        if server_ts - local_ts > _FRESHNESS_SKEW_SECONDS:
            newer.append((path, server_ts, local_ts))
    if newer:
        print(f"  {len(newer)} story.json file(s) newer on server than local")
    else:
        print(f"  ok — {len(server)} server story.json files checked, none newer than local")
    return newer


def _list_remote_top_level() -> list[str]:
    """Return server-side top-level directory names under GCP_DEST_DIR."""
    # find ... -printf '%f\n' lists basenames, one per line, no trailing slashes.
    out = _ssh(
        f"find {GCP_DEST_DIR} -mindepth 1 -maxdepth 1 -type d -printf '%f\\n'"
    )
    return [line for line in (l.strip() for l in out.splitlines()) if line]


def ssh_prune(local_top_level: list[str], dry_run: bool) -> None:
    """Remove server-side top-level story folders that don't exist locally.

    Server-side housekeeping folders matching EXCLUDE_DIR_NAMES are kept
    even if they're missing locally — those are the same folders that
    pack() skips, so we'd never know whether they should exist or not.
    """
    label = "[3b/4] Pruning server orphans" + (" (dry-run)" if dry_run else "")
    print(label)
    keep = set(local_top_level) | EXCLUDE_DIR_NAMES
    remote = _list_remote_top_level()
    orphans = sorted(name for name in remote if name not in keep)
    if not orphans:
        print("  no orphans found")
        return
    for name in orphans:
        print(f"  {'would remove' if dry_run else 'removing'}: {name}")
    if dry_run:
        return
    # Delete one-by-one so a single bad name doesn't abort the rest.
    # Each name goes in its own single-quoted shell argument with embedded
    # quotes escaped (' → '\''). Path always anchored at GCP_DEST_DIR.
    for name in orphans:
        safe_name = name.replace("'", "'\\''")
        _ssh(f"rm -rf -- '{GCP_DEST_DIR}/{safe_name}'")


def cleanup_local(local_tar: Path) -> None:
    print(f"[4/4] Cleaning up local tarball")
    if local_tar.exists():
        local_tar.unlink()
        print(f"  removed {local_tar}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Sync the story archive to the GCP server.")
    parser.add_argument(
        "--prune",
        action="store_true",
        help="After upload, remove server-side top-level story folders that don't exist locally.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="With --prune, print what would be removed instead of removing. Implies --prune.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help=(
            "Skip the pre-flight server freshness check. Local wins "
            "unconditionally. Use only when you intentionally want to "
            "overwrite dashboard-side edits on the server."
        ),
    )
    args = parser.parse_args(argv)
    do_prune = args.prune or args.dry_run

    print("=" * 70)
    print("PawPoller story sync" + (" (with prune)" if do_prune else ""))
    print("=" * 70)
    local_tar = _local_tarball()
    try:
        # Pre-flight freshness check (2.22.7). Catches the failure mode
        # where a dashboard edit on the server would be clobbered by a
        # pawsync run from a stale local copy. --force bypasses.
        if not args.force:
            newer = check_server_freshness()
            if newer:
                print()
                print("ERROR: Server has newer story.json files than local:", file=sys.stderr)
                for path, server_ts, local_ts in sorted(newer):
                    server_dt = datetime.datetime.fromtimestamp(server_ts).strftime("%Y-%m-%d %H:%M:%S")
                    local_dt = datetime.datetime.fromtimestamp(local_ts).strftime("%Y-%m-%d %H:%M:%S")
                    delta_min = (server_ts - local_ts) / 60
                    print(f"  {path}", file=sys.stderr)
                    print(f"    server: {server_dt}  local: {local_dt}  (server +{delta_min:.1f} min)", file=sys.stderr)
                print(file=sys.stderr)
                print(
                    "These are dashboard edits that pawsync would overwrite.\n"
                    "Run `deploy\\pawpull.bat` first to bring them down to local,\n"
                    "or re-run with --force to discard them intentionally.",
                    file=sys.stderr,
                )
                return 3

        top_level = pack(local_tar)
        scp_upload(local_tar)
        ssh_extract()
        if do_prune:
            ssh_prune(top_level, dry_run=args.dry_run)
        cleanup_local(local_tar)
    except subprocess.TimeoutExpired as e:
        print(f"\nERROR: command timed out: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"\nERROR: {type(e).__name__}: {e}", file=sys.stderr)
        return 1
    print()
    print("Done. Story archive synced to server.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
