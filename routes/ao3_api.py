"""REST API endpoints for the AO3 (Archive of Our Own) analytics dashboard.

AO3 runs OTW Archive software (same as SquidgeWorld). Auth uses
username/password login with a separate target_user for tracking.
Tracks hits, kudos, comments, bookmarks — plus individual kudos users.
"""

from __future__ import annotations
import csv
import io
import logging
from typing import Optional

from fastapi import APIRouter, Query, HTTPException
from fastapi.responses import StreamingResponse

from database.db import get_connection
from database import ao3_queries
from polling.ao3_poller import run_ao3_poll_cycle, ao3_poll_progress
from ao3_client.client import AO3Client
import config

logger = logging.getLogger(__name__)
ao3_router = APIRouter(prefix="/api/ao3")


# -- AO3 Auth ----------------------------------------------------------

@ao3_router.get("/auth/status")
def ao3_auth_status():
    """Check whether AO3 credentials exist and whether there is any AO3 data."""
    settings = config.get_settings()
    has_credentials = bool(settings.get("ao3_username")) and bool(settings.get("ao3_password"))
    has_data = False
    conn = get_connection()
    try:
        count = conn.execute("SELECT COUNT(*) as c FROM ao3_submissions").fetchone()["c"]
        has_data = count > 0
    except Exception:
        pass
    finally:
        conn.close()
    return {
        "has_credentials": has_credentials,
        "has_data": has_data,
        "username": settings.get("ao3_target_user", ""),
    }


@ao3_router.post("/auth/connect")
async def ao3_connect(body: dict):
    """Validate AO3 credentials by attempting login.

    Auth flow:
      1. Receive login username + password + target user from the frontend
      2. Create a temporary AO3Client and attempt login
      3. If login succeeds, save credentials to settings.json
    """
    username = body.get("username", "").strip()
    password = body.get("password", "").strip()
    target_user = body.get("target_user", "").strip()

    if not username or not password:
        raise HTTPException(400, "Username and password are required")
    if not target_user:
        raise HTTPException(400, "Target user is required (the AO3 user to track)")

    client = AO3Client(username=username, password=password, target_user=target_user)
    try:
        result = await client.validate_session()
    except Exception as e:
        raise HTTPException(502, f"Failed to validate credentials: {e}")
    finally:
        await client.close()

    if not result:
        raise HTTPException(401, "Login failed — check your username and password.")

    config.save_settings({
        "ao3_username": username,
        "ao3_password": password,
        "ao3_target_user": target_user,
        "ao3_notifications_enabled": True,
    })

    return {"status": "success", "message": f"Connected — tracking {target_user}"}


@ao3_router.post("/auth/disconnect")
def ao3_disconnect():
    """Clear AO3 credentials from settings."""
    config.delete_settings_keys(["ao3_username", "ao3_password", "ao3_target_user"])
    config.save_settings({"ao3_notifications_enabled": False})
    return {"status": "success", "message": "AO3 disconnected"}


# -- AO3 Polling -------------------------------------------------------

@ao3_router.get("/poll/progress")
def get_ao3_poll_progress():
    return dict(ao3_poll_progress)


@ao3_router.post("/poll/trigger")
async def trigger_ao3_poll():
    """Manual poll trigger for AO3."""
    try:
        stats = await run_ao3_poll_cycle()
        return {"status": "success", "stats": stats}
    except Exception as e:
        logger.error("Error in AO3 poll trigger: %s", e, exc_info=True)
        raise HTTPException(500, detail=str(e))


@ao3_router.post("/poll/full-resync")
async def ao3_full_resync():
    """Force full AO3 resync."""
    try:
        stats = await run_ao3_poll_cycle(force_full=True)
        return {"status": "success", "stats": stats}
    except Exception as e:
        logger.error("Error in AO3 full resync: %s", e, exc_info=True)
        raise HTTPException(500, detail=str(e))


# -- AO3 Data ----------------------------------------------------------

@ao3_router.get("/status")
def get_ao3_status():
    conn = get_connection()
    try:
        last_poll = ao3_queries.get_ao3_last_poll(conn)
        count = conn.execute("SELECT COUNT(*) as c FROM ao3_submissions").fetchone()["c"]
        snap_count = conn.execute("SELECT COUNT(*) as c FROM ao3_snapshots").fetchone()["c"]
        return {
            "total_submissions": count,
            "total_snapshots": snap_count,
            "last_poll": last_poll,
        }
    except Exception as e:
        logger.error("Error in /api/ao3/status: %s", e, exc_info=True)
        raise HTTPException(500, detail=str(e))
    finally:
        conn.close()


@ao3_router.get("/summary")
def get_ao3_summary():
    conn = get_connection()
    try:
        summary = ao3_queries.get_ao3_summary(conn)
        summary["growth_rates"] = ao3_queries.get_ao3_growth_rates(conn)
        return summary
    except Exception as e:
        logger.error("Error in /api/ao3/summary: %s", e, exc_info=True)
        raise HTTPException(500, detail=str(e))
    finally:
        conn.close()


@ao3_router.get("/submissions")
def get_ao3_submissions(
    sort_by: str = Query("views", description="Sort field"),
    order: str = Query("desc", description="Sort order"),
    search: str = Query("", description="Search title/keywords"),
    rating: str = Query("", description="Filter by rating"),
):
    conn = get_connection()
    try:
        subs = ao3_queries.get_all_ao3_submissions(conn, sort_by=sort_by, order=order)
        deltas = ao3_queries.get_ao3_submission_deltas(conn)

        if search:
            search_lower = search.lower()
            subs = [s for s in subs if search_lower in s["title"].lower() or search_lower in (s.get("keywords") or "").lower()]
        if rating:
            subs = [s for s in subs if (s.get("rating") or "").lower() == rating.lower()]

        for s in subs:
            d = deltas.get(str(s["submission_id"]), {})
            s["views_delta"] = d.get("views_delta", 0)
            s["faves_delta"] = d.get("faves_delta", 0)
            s["comments_delta"] = d.get("comments_delta", 0)
            s["bookmarks_delta"] = d.get("bookmarks_delta", 0)

        return {"submissions": subs, "total": len(subs)}
    except Exception as e:
        logger.error("Error in /api/ao3/submissions: %s", e, exc_info=True)
        raise HTTPException(500, detail=str(e))
    finally:
        conn.close()


@ao3_router.get("/submissions/{submission_id}")
def get_ao3_submission(submission_id: int):
    conn = get_connection()
    try:
        sub = ao3_queries.get_ao3_submission(conn, submission_id)
        if not sub:
            raise HTTPException(status_code=404, detail="AO3 work not found")
        snapshots = ao3_queries.get_ao3_snapshots(conn, submission_id)
        growth_rates = ao3_queries.get_ao3_submission_growth_rates(conn, submission_id)
        kudos_users = ao3_queries.get_ao3_kudos_users(conn, submission_id)
        try:
            tags = conn.execute(
                "SELECT t.tag_id, t.name, t.color FROM tags t JOIN submission_tags st ON t.tag_id = st.tag_id WHERE st.platform = 'ao3' AND st.submission_id = ?",
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
            "kudos_users": kudos_users,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error in /api/ao3/submissions/%s: %s", submission_id, e, exc_info=True)
        raise HTTPException(500, detail=str(e))
    finally:
        conn.close()


@ao3_router.get("/submissions/{submission_id}/snapshots")
def get_ao3_submission_snapshots(
    submission_id: int,
    start: Optional[str] = Query(None),
    end: Optional[str] = Query(None),
):
    conn = get_connection()
    try:
        return {"snapshots": ao3_queries.get_ao3_snapshots(conn, submission_id, start, end)}
    except Exception as e:
        logger.error("Error in /api/ao3/submissions/%s/snapshots: %s", submission_id, e, exc_info=True)
        raise HTTPException(500, detail=str(e))
    finally:
        conn.close()


@ao3_router.get("/aggregate")
def get_ao3_aggregate(
    start: Optional[str] = Query(None),
    end: Optional[str] = Query(None),
):
    conn = get_connection()
    try:
        return {"snapshots": ao3_queries.get_ao3_aggregate_snapshots(conn, start, end)}
    except Exception as e:
        logger.error("Error in /api/ao3/aggregate: %s", e, exc_info=True)
        raise HTTPException(500, detail=str(e))
    finally:
        conn.close()


@ao3_router.get("/comparison")
def get_ao3_comparison(
    ids: str = Query(..., description="Comma-separated work IDs"),
    start: Optional[str] = Query(None),
    end: Optional[str] = Query(None),
):
    submission_ids = [int(x.strip()) for x in ids.split(",") if x.strip().isdigit()]
    if len(submission_ids) > 10:
        raise HTTPException(400, "Max 10 works for comparison")

    conn = get_connection()
    try:
        data = ao3_queries.get_ao3_comparison_snapshots(conn, submission_ids, start, end)
        titles = {}
        for sid in submission_ids:
            sub = ao3_queries.get_ao3_submission(conn, sid)
            if sub:
                titles[str(sid)] = sub["title"]
        return {"series": data, "titles": titles}
    except Exception as e:
        logger.error("Error in /api/ao3/comparison: %s", e, exc_info=True)
        raise HTTPException(500, detail=str(e))
    finally:
        conn.close()


@ao3_router.get("/poll_log")
def get_ao3_poll_log(limit: int = Query(50, ge=1, le=200)):
    conn = get_connection()
    try:
        return {"polls": ao3_queries.get_ao3_poll_log(conn, limit)}
    except Exception as e:
        logger.error("Error in /api/ao3/poll_log: %s", e, exc_info=True)
        raise HTTPException(500, detail=str(e))
    finally:
        conn.close()


# -- AO3 CSV Export ----------------------------------------------------

def _sanitize_csv_value(val):
    """Prevent CSV formula injection — prefix dangerous chars with single quote."""
    if isinstance(val, str) and val and val[0] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + val
    return val


def _csv_response(rows: list[dict], filename: str) -> StreamingResponse:
    if not rows:
        return StreamingResponse(iter(["No data"]), media_type="text/csv",
                                 headers={"Content-Disposition": f'attachment; filename="{filename}"'})
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=rows[0].keys())
    writer.writeheader()
    writer.writerows({k: _sanitize_csv_value(v) for k, v in r.items()} for r in rows)
    output.seek(0)
    return StreamingResponse(iter([output.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@ao3_router.get("/export/submissions")
def export_ao3_submissions():
    conn = get_connection()
    try:
        subs = ao3_queries.get_all_ao3_submissions(conn)
        return _csv_response(subs, "ao3_submissions.csv")
    finally:
        conn.close()


@ao3_router.get("/export/snapshots")
def export_ao3_snapshots(id: int | None = Query(None)):
    conn = get_connection()
    try:
        if id:
            snaps = ao3_queries.get_ao3_snapshots(conn, id)
        else:
            snaps = [dict(r) for r in conn.execute("SELECT * FROM ao3_snapshots ORDER BY polled_at ASC").fetchall()]
        return _csv_response(snaps, f"ao3_snapshots{'_' + str(id) if id else ''}.csv")
    finally:
        conn.close()
