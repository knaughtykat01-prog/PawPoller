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
    python deploy/pawsync.py
    pawsync.bat                  # Thin wrapper around this script

Behaviour:
    - Packs every story under ``m_x/Archives/Complete_Stories/`` (excluding
      ``Backups/``, ``Drafts/``, ``Styled_HTML/``) into a tar.gz in %TEMP%.
    - Uploads to ``/tmp/story-archive.tar.gz`` on the GCP VM as user
      ``kithetiger`` (must match the extract user — sticky bit on /tmp).
    - Extracts to ``/home/kithetiger/story-archive/`` and chmods o+rX.
    - Removes the temp tarball on both ends.
    - Aborts on any failure (no silent stale uploads).

Exit codes:
    0  success
    1  generic error (tar pack, scp, ssh, extract)
    2  user-cancelled / unexpected
"""
from __future__ import annotations

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


def pack(local_tar: Path) -> None:
    print(f"[1/4] Packing stories from {ARCHIVE_ROOT} -> {local_tar}")
    if local_tar.exists():
        local_tar.unlink()
    if not ARCHIVE_ROOT.is_dir():
        raise RuntimeError(f"Archive root not found: {ARCHIVE_ROOT}")

    # Pack each top-level entry under ARCHIVE_ROOT individually so the
    # tarball mirrors a flat layout (Tombstone/, Chosen/, ...).
    n_files = 0
    n_skipped = 0
    with tarfile.open(local_tar, "w:gz") as tar:
        for entry in sorted(ARCHIVE_ROOT.iterdir()):
            if entry.name in EXCLUDE_DIR_NAMES:
                continue
            for fp in entry.rglob("*"):
                if fp.is_file():
                    rel = fp.relative_to(ARCHIVE_ROOT)
                    if any(p in EXCLUDE_DIR_NAMES for p in rel.parts):
                        n_skipped += 1
                        continue
                    tar.add(fp, arcname=str(rel).replace("\\", "/"), filter=_filter_member)
                    n_files += 1

    size_mb = local_tar.stat().st_size / (1024 * 1024)
    print(f"  packed {n_files:,} files ({size_mb:.1f} MB), skipped {n_skipped:,}")


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


def cleanup_local(local_tar: Path) -> None:
    print(f"[4/4] Cleaning up local tarball")
    if local_tar.exists():
        local_tar.unlink()
        print(f"  removed {local_tar}")


def main() -> int:
    print("=" * 70)
    print("PawPoller story sync")
    print("=" * 70)
    local_tar = _local_tarball()
    try:
        pack(local_tar)
        scp_upload(local_tar)
        ssh_extract()
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
