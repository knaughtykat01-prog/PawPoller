"""Publish composed microblog posts to their platforms — 2.49.0.

The compose→publish engine for the Posts module. Deliberately lightweight: it
constructs a **fresh** platform client per publish from the account's resolved
credentials (never the poller singletons — posting must not mutate a client
mid-poll), calls that client's create method, and records the outcome in
``post_publications``.

Phase 2 wires Bluesky + Mastodon (both post fine from any IP). Threads, Tumblr
and X are recognised but return a clear "not wired yet" error until Phase 3.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import config
from database.db import get_connection
from database import accounts as accounts_db
from database import posts_queries

logger = logging.getLogger(__name__)

# Platforms this module can post to today. (Others are poll-only until Phase 3.)
SUPPORTED = ("bsky", "mast")

# Rating → Bluesky self-labels. General adds none.
_BSKY_LABELS = {"mature": ["sexual"], "adult": ["porn"]}
_SENSITIVE_RATINGS = ("mature", "adult")


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _resolve_creds(platform: str, account_id: int | None,
                   settings: dict | None) -> tuple[int, dict]:
    """Return (account_id, {canonical_field: value}) for the target account.

    Mirrors the pollers: an explicit account_id wins, else the platform's
    default account; falls back to the legacy single-account keys (is_default)
    when no account row exists.
    """
    conn = get_connection()
    try:
        if account_id is None:
            account_id = accounts_db.get_default_account_id(conn, platform, create=False)
        acct = accounts_db.get_account(conn, account_id) if account_id else None
    finally:
        conn.close()
    is_default = bool(acct["is_default"]) if acct else True
    creds = config.resolve_account_credentials(platform, account_id or 0, is_default, settings)
    return (account_id or 0, creds)


async def _publish_one(post: dict, platform: str, account_id: int | None,
                       settings: dict | None) -> dict[str, Any]:
    """Post one composed post to one platform. Returns a result dict; never raises."""
    result: dict[str, Any] = {
        "platform": platform, "account_id": account_id or 0,
        "success": False, "external_id": "", "external_url": "", "error": "",
    }
    if platform not in SUPPORTED:
        result["error"] = f"posting to {platform} isn't wired yet"
        return result

    account_id, creds = _resolve_creds(platform, account_id, settings)
    result["account_id"] = account_id

    body = post.get("body", "")
    rating = (post.get("rating") or "general").lower()
    image_path = post.get("image_path") or None
    image_alt = post.get("image_alt", "")

    try:
        if platform == "bsky":
            from clients.bsky.client import BskyClient
            ident = creds.get("bsky_identifier", "")
            pw = creds.get("bsky_app_password", "")
            if not (ident and pw):
                result["error"] = "Bluesky account isn't connected"
                return result
            client = BskyClient(identifier=ident, app_password=pw)
            try:
                r = await client.create_post(
                    body, image_path=image_path, image_alt=image_alt,
                    labels=_BSKY_LABELS.get(rating) or None,
                )
            finally:
                await client.close()
            if r and r.get("uri"):
                result.update(success=True, external_id=r.get("uri", ""),
                              external_url=r.get("url", ""))
            else:
                result["error"] = "Bluesky rejected the post (check the app password / logs)"

        elif platform == "mast":
            from clients.mast.client import MastClient
            instance = creds.get("mast_instance_url", "")
            token = creds.get("mast_access_token", "")
            if not (instance and token):
                result["error"] = "Mastodon account isn't connected"
                return result
            client = MastClient(instance_url=instance, access_token=token)
            try:
                r = await client.create_status(
                    body, image_path=image_path, image_alt=image_alt,
                    sensitive=(rating in _SENSITIVE_RATINGS),
                    idempotency_key=f"pp-{post.get('post_id')}-mast",
                )
            finally:
                await client.close()
            if r and (r.get("id") or r.get("uri")):
                result.update(success=True, external_id=r.get("id", "") or r.get("uri", ""),
                              external_url=r.get("url", ""))
            else:
                result["error"] = ("Mastodon rejected the post — the access token likely "
                                    "needs a write scope (check the app / logs)")
    except Exception as e:
        logger.error("Post publish to %s failed: %s", platform, e, exc_info=True)
        result["error"] = str(e)
    return result


async def publish_post(post_id: int, platforms: list[str],
                       account_ids: dict[str, int] | None = None,
                       settings: dict | None = None) -> list[dict[str, Any]]:
    """Publish a composed post to each platform, recording every outcome.

    Returns one result dict per platform. Each publication row is upserted so a
    re-publish of a failed platform overwrites its prior failure.
    """
    account_ids = account_ids or {}
    conn = get_connection()
    try:
        post = posts_queries.get_post(conn, post_id)
    finally:
        conn.close()
    if not post:
        raise ValueError(f"post {post_id} not found")

    results: list[dict[str, Any]] = []
    for platform in platforms:
        res = await _publish_one(post, platform, account_ids.get(platform), settings)
        results.append(res)
        conn = get_connection()
        try:
            posts_queries.upsert_post_publication(
                conn, post_id=post_id, platform=platform, account_id=res["account_id"],
                status="posted" if res["success"] else "failed",
                external_id=res.get("external_id", ""),
                external_url=res.get("external_url", ""),
                error=res.get("error", ""), now=_now(),
            )
        finally:
            conn.close()
    return results
