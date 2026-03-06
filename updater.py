"""Self-contained update module for checking and applying updates from GitHub releases."""

from __future__ import annotations
import logging
import os
import sys
import tempfile
import zipfile
from pathlib import Path

import httpx

from config import APP_VERSION
import config

logger = logging.getLogger(__name__)
# Set to "owner/repo" (e.g. "user/PawPoller") to enable update checks.
# Left empty to disable update checks until the repo is public/ready.
GITHUB_REPO = "knaughtykat01-prog/PawPoller"


def check_for_update() -> dict:
    """Check GitHub releases for a newer version.

    Returns dict with keys: available, current, latest, download_url, release_notes
    """
    # Early exit when no repo is configured — returns a "no update" response
    # so callers don't need to know whether update checking is enabled.
    if not GITHUB_REPO:
        return {"available": False, "current": APP_VERSION, "latest": APP_VERSION, "download_url": None, "release_notes": ""}

    try:
        # GitHub Releases API — the /releases/latest endpoint returns the most
        # recent non-prerelease, non-draft release. Auth token required for
        # private repos; read from settings.json "github_pat" key.
        headers = {"Accept": "application/vnd.github+json"}
        settings = config.get_settings()
        pat = settings.get("github_pat", "")
        if pat:
            headers["Authorization"] = f"token {pat}"

        with httpx.Client(timeout=15.0) as client:
            resp = client.get(
                f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest",
                headers=headers,
            )
            resp.raise_for_status()
            data = resp.json()

        # Strip leading "v" prefix (e.g. "v1.2.0" -> "1.2.0") so both sides
        # are plain numeric semver strings for comparison.
        latest_tag = data.get("tag_name", "").lstrip("v")
        current = APP_VERSION.lstrip("v")

        # Semantic version comparison — splits on "." and compares tuples
        # numerically (see _version_newer below).
        available = _version_newer(latest_tag, current)

        # Scan release assets for a ZIP file containing the updated build.
        # Takes the first .zip found — releases should have exactly one.
        download_url = None
        for asset in data.get("assets", []):
            if asset.get("name", "").endswith(".zip"):
                download_url = asset.get("browser_download_url")
                break

        return {
            "available": available,
            "current": APP_VERSION,
            "latest": latest_tag or APP_VERSION,
            "download_url": download_url,
            "release_notes": data.get("body", ""),
        }
    except Exception as e:
        logger.warning("Update check failed: %s", e)
        return {"available": False, "current": APP_VERSION, "latest": APP_VERSION, "download_url": None, "error": str(e)}


def download_update(download_url: str) -> Path:
    """Download update ZIP to temp directory. Returns path to downloaded file."""
    temp_dir = Path(tempfile.mkdtemp(prefix="iba_update_"))
    zip_path = temp_dir / "update.zip"

    # Auth header for private repo asset downloads.
    headers = {"Accept": "application/octet-stream"}
    settings = config.get_settings()
    pat = settings.get("github_pat", "")
    if pat:
        headers["Authorization"] = f"token {pat}"

    # Streaming download pattern — instead of loading the entire ZIP into memory
    # (which could be tens of MB), we stream it in 8KB chunks and write directly
    # to disk. follow_redirects=True is needed because GitHub asset URLs redirect
    # through their CDN. The generous 120s timeout accommodates slow connections.
    with httpx.Client(timeout=120.0, follow_redirects=True) as client:
        with client.stream("GET", download_url, headers=headers) as resp:
            resp.raise_for_status()
            with open(zip_path, "wb") as f:
                for chunk in resp.iter_bytes(chunk_size=8192):
                    f.write(chunk)

    logger.info("Update downloaded to %s", zip_path)
    return zip_path


def apply_update(zip_path: Path) -> None:
    """Extract update and write a batch script to copy files and restart.

    The batch script waits for the current process to exit, copies new files,
    and restarts the application.
    """
    # Auto-update only works in frozen (PyInstaller) builds because:
    # 1. In dev, files are spread across source directories and venvs — robocopy
    #    would clobber the dev environment.
    # 2. sys.executable points to the .exe in frozen builds, but to the Python
    #    interpreter in dev — so the restart command would be wrong.
    # 3. Developers should update via git pull, not self-update.
    if not getattr(sys, "frozen", False):
        raise RuntimeError("Auto-update is only supported in frozen (exe) builds")

    # Extract the downloaded ZIP into a sibling "extracted" folder inside temp.
    extract_dir = zip_path.parent / "extracted"
    with zipfile.ZipFile(zip_path, "r") as zf:
        zf.extractall(extract_dir)

    app_dir = Path(sys.executable).parent
    exe_name = Path(sys.executable).name

    # Self-update batch script mechanism:
    # The running .exe can't overwrite itself, so we write a .bat script that:
    #   1. `timeout /t 2` — waits 2 seconds for the current process to exit
    #      and release file locks on its own .exe and DLLs.
    #   2. `robocopy /MIR` — mirrors the extracted update into the app directory,
    #      replacing all files with the new version. /MIR deletes files in the
    #      target that don't exist in the source (cleaning up removed files).
    #   3. `/XD data logs` — SAFETY: excludes the "data" and "logs" directories
    #      from mirroring so the user's database, config, and log history are
    #      never deleted or overwritten during an update.
    #   4. `start` — launches the updated .exe.
    #   5. `del "%~f0"` — the batch script deletes itself (cleanup).
    bat_path = zip_path.parent / "_update.bat"
    bat_content = f"""@echo off
timeout /t 2 /nobreak > nul
robocopy "{extract_dir}" "{app_dir}" /MIR /XD data logs
start "" "{app_dir}\\{exe_name}"
del "%~f0"
"""
    bat_path.write_text(bat_content, encoding="utf-8")
    logger.info("Update script written to %s", bat_path)

    # os.startfile launches the .bat asynchronously (detached from this process).
    # The caller is expected to exit the app immediately after this call so the
    # batch script's timeout elapses while the process is shutting down.
    os.startfile(str(bat_path))


def _version_newer(latest: str, current: str) -> bool:
    """Compare semantic version strings. Returns True if latest > current."""
    try:
        # Split "1.2.3" into (1, 2, 3) tuples. Python's tuple comparison is
        # lexicographic over elements, which matches semver ordering:
        #   (1, 2, 3) > (1, 2, 2)  -> True  (patch bump)
        #   (2, 0, 0) > (1, 9, 9)  -> True  (major bump)
        # Falls back to False on malformed version strings (non-numeric parts).
        lat = tuple(int(x) for x in latest.split("."))
        cur = tuple(int(x) for x in current.split("."))
        return lat > cur
    except (ValueError, AttributeError):
        return False
