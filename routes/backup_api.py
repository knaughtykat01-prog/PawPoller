"""Backup & restore (backlog Y) — "download my everything" / "restore from file".

A backup is a .zip of the user's own data under DATA_DIR: the SQLite database
(all analytics, publications, masterpieces, links…), settings.json + the
encrypted credential vault, and the app-managed media folders (artwork,
posts_media, and the story-archive when it lives under DATA_DIR). Logs and
transient caches (ig_media) are excluded.

Restore is DESTRUCTIVE — it replaces the DB + settings + vault and merges media
over the current data — so it writes a timestamped safety copy of the current
critical files first, guards against zip-slip, and tells the user to restart
(get_settings() re-reads from disk, and get_connection() opens the DB fresh, but
module-level constants + long-lived singletons only re-read on restart).
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

import config

logger = logging.getLogger(__name__)
backup_router = APIRouter(prefix="/api/backup", tags=["backup"])

BACKUP_KIND = "pawpoller-backup"
_MAX_BACKUP_BYTES = 2 * 1024 * 1024 * 1024      # 2 GB restore-upload cap

# Relative to DATA_DIR. Files are replaced on restore; dirs are merged (restored
# files overwrite same-named, existing extras are left alone — never a blind
# media wipe). ig_media (transient IG image stash) is deliberately not included.
_BACKUP_FILES = ["pawpoller.db", "settings.json", "settings.vault.json"]
_BACKUP_DIRS = ["artwork", "posts_media", "story-archive"]


def _data_dir() -> Path:
    return Path(config.DATA_DIR)


def _dir_size(p: Path) -> int:
    return sum(x.stat().st_size for x in p.rglob("*") if x.is_file())


@backup_router.get("/info")
def backup_info():
    """What a backup would contain + its rough size, for the Settings UI."""
    dd = _data_dir()
    items, total = [], 0
    for f in _BACKUP_FILES:
        p = dd / f
        if p.is_file():
            sz = p.stat().st_size
            total += sz
            items.append({"name": f, "bytes": sz})
    for d in _BACKUP_DIRS:
        p = dd / d
        if p.is_dir():
            sz = _dir_size(p)
            total += sz
            items.append({"name": d + "/", "bytes": sz})
    return {"items": items, "total_bytes": total, "app_version": config.APP_VERSION}


@backup_router.get("/export")
def export_backup():
    """Stream a .zip of the user's data. Includes the credential vault — it's a
    full backup of the user's own instance; the UI warns that it holds secrets."""
    dd = _data_dir()
    fd, tmp = tempfile.mkstemp(suffix=".zip", prefix="pawpoller-backup-")
    os.close(fd)
    try:
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
            manifest = {
                "kind": BACKUP_KIND,
                "app_version": config.APP_VERSION,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "files": [], "dirs": [],
            }
            for f in _BACKUP_FILES:
                p = dd / f
                if p.is_file():
                    z.write(p, f"data/{f}")
                    manifest["files"].append(f)
            for d in _BACKUP_DIRS:
                p = dd / d
                if not p.is_dir():
                    continue
                manifest["dirs"].append(d)
                for x in p.rglob("*"):
                    if x.is_file():
                        z.write(x, f"data/{x.relative_to(dd).as_posix()}")
            z.writestr("manifest.json", json.dumps(manifest, indent=2))
    except Exception as e:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        logger.error("Backup export failed: %s", e, exc_info=True)
        raise HTTPException(500, detail=f"Backup failed: {e}")

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return FileResponse(
        tmp, media_type="application/zip",
        filename=f"pawpoller-backup-{stamp}.zip",
        background=BackgroundTask(lambda: os.path.exists(tmp) and os.unlink(tmp)),
    )


def _safe_extract(z: zipfile.ZipFile, dest: Path) -> None:
    """Extract with a zip-slip guard — refuse any member that would escape dest."""
    dest = dest.resolve()
    for member in z.namelist():
        target = (dest / member).resolve()
        if dest != target and dest not in target.parents:
            raise HTTPException(400, detail="Unsafe path in backup archive.")
    z.extractall(dest)


def _merge_tree(src: Path, dst: Path) -> None:
    dst.mkdir(parents=True, exist_ok=True)
    for item in src.rglob("*"):
        target = dst / item.relative_to(src)
        if item.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, target)


@backup_router.post("/import")
async def import_backup(file: UploadFile = File(...)):
    """Restore from a backup .zip. DESTRUCTIVE — replaces DB + settings + vault
    and merges media over the current data. A timestamped safety copy of the
    current critical files is written first; a restart is required to finish."""
    data = await file.read()
    if not data:
        raise HTTPException(400, detail="Empty upload.")
    if len(data) > _MAX_BACKUP_BYTES:
        raise HTTPException(413, detail="Backup file exceeds the 2 GB limit.")

    dd = _data_dir()
    tmpdir = Path(tempfile.mkdtemp(prefix="pawpoller-restore-"))
    try:
        zpath = tmpdir / "upload.zip"
        zpath.write_bytes(data)
        try:
            with zipfile.ZipFile(zpath) as z:
                _safe_extract(z, tmpdir)
        except zipfile.BadZipFile:
            raise HTTPException(400, detail="Not a valid .zip file.")

        manifest_p = tmpdir / "manifest.json"
        if not manifest_p.is_file():
            raise HTTPException(400, detail="Not a PawPoller backup (no manifest).")
        try:
            manifest = json.loads(manifest_p.read_text("utf-8"))
        except ValueError:
            raise HTTPException(400, detail="Backup manifest is unreadable.")
        if manifest.get("kind") != BACKUP_KIND:
            raise HTTPException(400, detail="This isn't a PawPoller backup.")

        src_data = tmpdir / "data"
        if not (src_data / "pawpoller.db").is_file():
            raise HTTPException(400, detail="Backup is missing the database.")

        # Safety copy of the current critical state BEFORE overwriting anything.
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        safety = dd / f"restore-safety-{stamp}"
        safety.mkdir(parents=True, exist_ok=True)
        for f in _BACKUP_FILES:
            cur = dd / f
            if cur.is_file():
                shutil.copy2(cur, safety / f)

        restored = []
        for f in _BACKUP_FILES:
            sp = src_data / f
            if sp.is_file():
                shutil.copy2(sp, dd / f)
                restored.append(f)
        for d in _BACKUP_DIRS:
            sd = src_data / d
            if sd.is_dir():
                _merge_tree(sd, dd / d)
                restored.append(d + "/")

        logger.info("Backup restored (%s); safety copy at %s", ", ".join(restored), safety.name)
        return {
            "ok": True,
            "restored": restored,
            "safety_copy": safety.name,
            "app_version": manifest.get("app_version", ""),
            "message": "Restored. Restart PawPoller to finish loading the restored data.",
        }
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
