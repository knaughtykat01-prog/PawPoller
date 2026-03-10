"""REST API endpoints for the X/Twitter (TW) analytics dashboard.

X/Twitter uses internal GraphQL endpoints with cookie-based auth.
Same cookie-based scraping approach as the DeviantArt integration.
Users provide auth_token + ct0 cookies from their browser.

Stats tracked: views, likes, retweets, replies, quotes, bookmarks (6 metrics).
Tweet IDs are numeric strings (TEXT — 64-bit ints exceed JS safe range).
"""

from __future__ import annotations
import csv
import io
import logging
from typing import Optional

from fastapi import APIRouter, Query, HTTPException
from fastapi.responses import StreamingResponse

from database.db import get_connection
from database import tw_queries
from polling.tw_poller import run_tw_poll_cycle, tw_poll_progress
from tw_client.client import TWClient
import config

logger = logging.getLogger(__name__)
tw_router = APIRouter(prefix="/api/tw")


# -- TW Auth ------------------------------------------------------------------

@tw_router.get("/auth/status")
def tw_auth_status():
    """Check whether X/Twitter credentials are configured and whether there is any TW data."""
    settings = config.get_settings()
    has_credentials = bool(settings.get("tw_auth_token") and settings.get("tw_ct0"))
    has_data = False
    conn = get_connection()
    try:
        count = conn.execute("SELECT COUNT(*) as c FROM tw_submissions").fetchone()["c"]
        has_data = count > 0
    except Exception:
        pass
    finally:
        conn.close()
    return {
        "has_credentials": has_credentials,
        "has_data": has_data,
        "username": settings.get("tw_target_user", ""),
    }


@tw_router.post("/auth/connect")
async def tw_connect(body: dict):
    """Validate X/Twitter cookies and save to settings.

    Auth flow:
      1. Receive auth_token, ct0, and target_user from the frontend
      2. Create a temporary TWClient and validate cookies
      3. If validation succeeds, save credentials to settings.json

    Cookie acquisition: Open x.com → F12 → Application → Cookies →
    copy auth_token and ct0 values.
    """
    auth_token = body.get("auth_token", "").strip()
    ct0 = body.get("ct0", "").strip()
    target_user = body.get("target_user", "").strip()

    if not auth_token:
        raise HTTPException(400, "auth_token cookie is required (F12 → Application → Cookies on x.com)")
    if not ct0:
        raise HTTPException(400, "ct0 cookie is required (F12 → Application → Cookies on x.com)")
    if not target_user:
        raise HTTPException(400, "Target user is required (the X/Twitter user to track, without @)")

    client = TWClient(auth_token=auth_token, ct0=ct0, target_user=target_user)
    try:
        valid = await client.validate_cookies()
    except Exception as e:
        raise HTTPException(502, f"Failed to validate cookies: {e}")
    finally:
        await client.close()

    if not valid:
        raise HTTPException(401, "Cookies appear invalid — could not resolve user. Check values and try again.")

    config.save_settings({
        "tw_auth_token": auth_token,
        "tw_ct0": ct0,
        "tw_target_user": target_user,
        "tw_notifications_enabled": True,
    })

    return {"status": "success", "message": f"Connected — tracking @{target_user}"}


@tw_router.post("/auth/disconnect")
def tw_disconnect():
    """Clear X/Twitter credentials from settings."""
    config.delete_settings_keys(["tw_auth_token", "tw_ct0", "tw_target_user"])
    config.save_settings({"tw_notifications_enabled": False})
    return {"status": "success", "message": "X/Twitter disconnected"}


# -- TW Polling ---------------------------------------------------------------

@tw_router.get("/poll/progress")
def get_tw_poll_progress():
    return dict(tw_poll_progress)


@tw_router.post("/poll/trigger")
async def trigger_tw_poll():
    """Manual poll trigger for X/Twitter."""
    try:
        stats = await run_tw_poll_cycle()
        return {"status": "success", "stats": stats}
    except Exception as e:
        logger.error("Error in TW poll trigger: %s", e, exc_info=True)
        raise HTTPException(500, detail=str(e))


@tw_router.post("/poll/full-resync")
async def tw_full_resync():
    """Force full X/Twitter resync."""
    try:
        stats = await run_tw_poll_cycle(force_full=True)
        return {"status": "success", "stats": stats}
    except Exception as e:
        logger.error("Error in TW full resync: %s", e, exc_info=True)
        raise HTTPException(500, detail=str(e))


# -- TW Data ------------------------------------------------------------------

@tw_router.get("/status")
def get_tw_status():
    conn = get_connection()
    try:
        last_poll = tw_queries.get_tw_last_poll(conn)
        count = conn.execute("SELECT COUNT(*) as c FROM tw_submissions").fetchone()["c"]
        snap_count = conn.execute("SELECT COUNT(*) as c FROM tw_snapshots").fetchone()["c"]
        return {
            "total_submissions": count,
            "total_snapshots": snap_count,
            "last_poll": last_poll,
        }
    except Exception as e:
        logger.error("Error in /api/tw/status: %s", e, exc_info=True)
        raise HTTPException(500, detail=str(e))
    finally:
        conn.close()


@tw_router.get("/summary")
def get_tw_summary():
    conn = get_connection()
    try:
        summary = tw_queries.get_tw_summary(conn)
        summary["growth_rates"] = tw_queries.get_tw_growth_rates(conn)
        return summary
    except Exception as e:
        logger.error("Error in /api/tw/summary: %s", e, exc_info=True)
        raise HTTPException(500, detail=str(e))
    finally:
        conn.close()


@tw_router.get("/submissions")
def get_tw_submissions(
    sort_by: str = Query("views", description="Sort field"),
    order: str = Query("desc", description="Sort order"),
    search: str = Query("", description="Search title/keywords"),
    content_type: str = Query("", description="Filter by content type (tweet/reply/quote)"),
):
    conn = get_connection()
    try:
        subs = tw_queries.get_all_tw_submissions(conn, sort_by=sort_by, order=order)
        deltas = tw_queries.get_tw_submission_deltas(conn)

        if search:
            search_lower = search.lower()
            subs = [s for s in subs if search_lower in s["title"].lower() or search_lower in (s.get("keywords") or "").lower()]
        if content_type:
            subs = [s for s in subs if (s.get("content_type") or "").lower() == content_type.lower()]

        for s in subs:
            d = deltas.get(s["submission_id"], {})
            s["views_delta"] = d.get("views_delta", 0)
            s["likes_delta"] = d.get("likes_delta", 0)
            s["retweets_delta"] = d.get("retweets_delta", 0)
            s["replies_delta"] = d.get("replies_delta", 0)
            s["quotes_delta"] = d.get("quotes_delta", 0)
            s["bookmarks_delta"] = d.get("bookmarks_delta", 0)

        return {"submissions": subs, "total": len(subs)}
    except Exception as e:
        logger.error("Error in /api/tw/submissions: %s", e, exc_info=True)
        raise HTTPException(500, detail=str(e))
    finally:
        conn.close()


@tw_router.get("/submissions/{submission_id}")
def get_tw_submission(submission_id: str):
    conn = get_connection()
    try:
        sub = tw_queries.get_tw_submission(conn, submission_id)
        if not sub:
            raise HTTPException(status_code=404, detail="Tweet not found")
        snapshots = tw_queries.get_tw_snapshots(conn, submission_id)
        growth_rates = tw_queries.get_tw_submission_growth_rates(conn, submission_id)
        try:
            tags = conn.execute(
                "SELECT t.tag_id, t.name, t.color FROM tags t JOIN submission_tags st ON t.tag_id = st.tag_id WHERE st.platform = 'tw' AND st.submission_id = ?",
                (submission_id,),
            ).fetchall()
        except Exception:
            tags = []
        sub_dict = dict(sub) if not isinstance(sub, dict) else sub
        sub_dict["tags"] = [dict(r) for r in tags]
        return {
            "submission": sub_dict,
            "snapshots": snapshots,
            "growth_rates": growth_rates,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error in /api/tw/submissions/%s: %s", submission_id, e, exc_info=True)
        raise HTTPException(500, detail=str(e))
    finally:
        conn.close()


@tw_router.get("/submissions/{submission_id}/snapshots")
def get_tw_submission_snapshots(
    submission_id: str,
    start: Optional[str] = Query(None),
    end: Optional[str] = Query(None),
):
    conn = get_connection()
    try:
        return {"snapshots": tw_queries.get_tw_snapshots(conn, submission_id, start, end)}
    except Exception as e:
        logger.error("Error in /api/tw/submissions/%s/snapshots: %s", submission_id, e, exc_info=True)
        raise HTTPException(500, detail=str(e))
    finally:
        conn.close()


@tw_router.get("/aggregate")
def get_tw_aggregate(
    start: Optional[str] = Query(None),
    end: Optional[str] = Query(None),
):
    conn = get_connection()
    try:
        return {"snapshots": tw_queries.get_tw_aggregate_snapshots(conn, start, end)}
    except Exception as e:
        logger.error("Error in /api/tw/aggregate: %s", e, exc_info=True)
        raise HTTPException(500, detail=str(e))
    finally:
        conn.close()


@tw_router.get("/comparison")
def get_tw_comparison(
    ids: str = Query(..., description="Comma-separated tweet IDs"),
    start: Optional[str] = Query(None),
    end: Optional[str] = Query(None),
):
    submission_ids = [x.strip() for x in ids.split(",") if x.strip()]
    if len(submission_ids) > 10:
        raise HTTPException(400, "Max 10 tweets for comparison")

    conn = get_connection()
    try:
        data = tw_queries.get_tw_comparison_snapshots(conn, submission_ids, start, end)
        titles = {}
        for sid in submission_ids:
            sub = tw_queries.get_tw_submission(conn, sid)
            if sub:
                titles[sid] = sub["title"]
        return {"series": data, "titles": titles}
    except Exception as e:
        logger.error("Error in /api/tw/comparison: %s", e, exc_info=True)
        raise HTTPException(500, detail=str(e))
    finally:
        conn.close()


@tw_router.get("/poll_log")
def get_tw_poll_log(limit: int = Query(50, ge=1, le=200)):
    conn = get_connection()
    try:
        return {"polls": tw_queries.get_tw_poll_log(conn, limit)}
    except Exception as e:
        logger.error("Error in /api/tw/poll_log: %s", e, exc_info=True)
        raise HTTPException(500, detail=str(e))
    finally:
        conn.close()


# -- TW CSV Export ------------------------------------------------------------

def _csv_response(rows: list[dict], filename: str) -> StreamingResponse:
    if not rows:
        return StreamingResponse(iter(["No data"]), media_type="text/csv",
                                 headers={"Content-Disposition": f'attachment; filename="{filename}"'})
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=rows[0].keys())
    writer.writeheader()
    writer.writerows(rows)
    output.seek(0)
    return StreamingResponse(iter([output.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@tw_router.get("/export/submissions")
def export_tw_submissions():
    conn = get_connection()
    try:
        subs = tw_queries.get_all_tw_submissions(conn)
        return _csv_response(subs, "tw_submissions.csv")
    finally:
        conn.close()


@tw_router.get("/export/snapshots")
def export_tw_snapshots(id: str | None = Query(None)):
    conn = get_connection()
    try:
        if id:
            snaps = tw_queries.get_tw_snapshots(conn, id)
        else:
            snaps = [dict(r) for r in conn.execute("SELECT * FROM tw_snapshots ORDER BY polled_at ASC").fetchall()]
        return _csv_response(snaps, f"tw_snapshots{'_' + id if id else ''}.csv")
    finally:
        conn.close()
