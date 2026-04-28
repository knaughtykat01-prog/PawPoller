"""PawPoller story-archive reverse sync — pull from GCP server to local.

The inverse of pawsync.py: packs the server's story archive, downloads
it, and extracts to the local m_x/Archives/Complete_Stories/ directory.

Usage:
    python deploy/pawpull.py           # full sync
    python deploy/pawpull.py Story     # single story only

Behaviour:
    - Tars the story archive on the server (excluding Backups/Drafts)
    - Downloads to %TEMP%/story-archive-pull.tar.gz
    - Extracts to the local archive directory
    - Removes the temp tarball on both ends
"""
from __future__ import annotations

import os
import re
import sys
import subprocess
import tarfile
import tempfile
from pathlib import Path

# Story folder names in the archive are alphanumeric + a small set of
# safe punctuation (underscores, hyphens, forward slashes for nested
# variants like "The_Abstinent_Bet/Nice_Version"). Reject anything else
# so a wonky argv value can't inject shell metacharacters into the
# remote ssh command — `gcloud --command="..."` runs through cmd.exe
# locally AND bash on the server, so two layers of escaping to get
# wrong. A whitelist is simpler and stricter than shlex.quote().
_SAFE_STORY_NAME = re.compile(r"^[A-Za-z0-9_./-]+$")

# ── Configuration ──────────────────────────────────────────────────────────

LOCAL_ARCHIVE = Path(r"C:\Users\rhysc\claude\m_x\Archives\Complete_Stories")
GCP_INSTANCE = "pawpoller"
GCP_ZONE = "us-east1-c"
GCP_USER = "kithetiger"
GCP_ARCHIVE = "/home/kithetiger/story-archive"
GCP_TMP_PATH = "/tmp/story-archive-pull.tar.gz"


def _local_tarball() -> Path:
    return Path(tempfile.gettempdir()) / "story-archive-pull.tar.gz"


def ssh_pack(story: str | None = None) -> None:
    """Pack the story archive on the server into a tarball."""
    if story:
        source = f"{GCP_ARCHIVE}/{story}"
        print(f"[1/4] Packing {story} on server...")
    else:
        source = GCP_ARCHIVE
        print(f"[1/4] Packing full archive on server...")

    # Exclude Backups, Drafts, Styled_HTML backups
    exclude = "--exclude='Backups' --exclude='Drafts' --exclude='Chapters_backup_*'"
    remote_cmd = f"cd {GCP_ARCHIVE} && tar czf {GCP_TMP_PATH} {exclude} -C {GCP_ARCHIVE} {'.' if not story else story}"

    cmd = (
        f'gcloud --quiet compute ssh '
        f'--zone={GCP_ZONE} '
        f'{GCP_USER}@{GCP_INSTANCE} '
        f'--command="{remote_cmd}"'
    )
    result = subprocess.run(cmd, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=300, shell=True)
    if result.returncode != 0:
        print(f"  stderr: {result.stderr}", file=sys.stderr)
        raise RuntimeError(f"Server pack failed with exit code {result.returncode}")
    print("  packed")


def scp_download(local_tar: Path) -> None:
    """Download the tarball from the server."""
    print(f"[2/4] Downloading from server...")
    if local_tar.exists():
        local_tar.unlink()

    cmd = (
        f'gcloud --quiet compute scp '
        f'--zone={GCP_ZONE} '
        f'{GCP_USER}@{GCP_INSTANCE}:{GCP_TMP_PATH} '
        f'"{local_tar}"'
    )
    result = subprocess.run(cmd, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=600, shell=True)
    if result.returncode != 0:
        print(f"  stderr: {result.stderr}", file=sys.stderr)
        raise RuntimeError(f"Download failed with exit code {result.returncode}")

    size_mb = local_tar.stat().st_size / (1024 * 1024)
    print(f"  downloaded ({size_mb:.1f} MB)")


def extract_local(local_tar: Path) -> None:
    """Extract the tarball to the local archive directory."""
    print(f"[3/4] Extracting to {LOCAL_ARCHIVE}...")
    n_files = 0
    with tarfile.open(local_tar, "r:gz") as tar:
        for member in tar.getmembers():
            tar.extract(member, path=LOCAL_ARCHIVE)
            n_files += 1
    print(f"  extracted {n_files:,} files")


def cleanup(local_tar: Path) -> None:
    """Remove temp tarballs on both ends."""
    print(f"[4/4] Cleaning up...")
    # Remote
    cmd = (
        f'gcloud --quiet compute ssh '
        f'--zone={GCP_ZONE} '
        f'{GCP_USER}@{GCP_INSTANCE} '
        f'--command="rm -f {GCP_TMP_PATH}"'
    )
    subprocess.run(cmd, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=60, shell=True)
    # Local
    if local_tar.exists():
        local_tar.unlink()
    print("  done")


def main() -> int:
    print("=" * 70)
    print("PawPoller story pull (server -> local)")
    print("=" * 70)

    story = sys.argv[1] if len(sys.argv) > 1 else None
    if story and not _SAFE_STORY_NAME.match(story):
        print(
            f"ERROR: story name {story!r} contains unsafe characters. "
            "Only letters, digits, underscores, hyphens, dots and "
            "forward slashes are allowed.",
            file=sys.stderr,
        )
        return 1
    local_tar = _local_tarball()

    try:
        ssh_pack(story)
        scp_download(local_tar)
        extract_local(local_tar)
        cleanup(local_tar)
    except subprocess.TimeoutExpired as e:
        print(f"\nERROR: command timed out: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"\nERROR: {type(e).__name__}: {e}", file=sys.stderr)
        return 1

    print()
    print("Done. Local archive synced from server.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
