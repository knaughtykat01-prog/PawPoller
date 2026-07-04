"""REST API endpoints for the DeviantArt (DA) analytics dashboard.

Polling uses the official OAuth2 API (2.47.0) -- users register a DA app and
provide its client_id + client_secret plus a target username to track. The
legacy cookie path is a fallback only.

Stats tracked: views, favourites, comments, downloads.
Downloads is unique to DeviantArt among PawPoller platforms.
No thumbnail proxy needed (DA images are served with CORS headers).
"""

from __future__ import annotations
import csv
import io
import logging
from typing import Optional

from fastapi import APIRouter, Query, HTTPException
from fastapi.responses import StreamingResponse

from database.db import get_connection
from database import da_queries
from polling.da_poller import run_da_poll_cycle, da_poll_progress
from polling.background import spawn
from clients.da.client import DAClient
import config

logger = logging.getLogger(__name__)
da_router = APIRouter(prefix="/api/da")


# -- DA Auth -----------------------------------------------------------

@da_router.get("/auth/status")
def da_auth_status():
    """Check whether DA credentials exist and whether there is any DA data."""
    settings = config.get_settings()
    has_credentials = bool(
        settings.get("da_client_id")
        and settings.get("da_client_secret")
        and settings.get("da_target_user")
    )
    has_data = False
    conn = get_connection()
    try:
        count = conn.execute("SELECT COUNT(*) as c FROM da_submissions").fetchone()["c"]
        has_data = count > 0
    except Exception:
        pass
    finally:
        conn.close()
    return {
        "has_credentials": has_credentials,
        "has_data": has_data,
        "username": settings.get("da_target_user", ""),
    }


@da_router.post("/auth/connect")
async def da_connect(body: dict):
    """Validate DA app credentials and save to settings.

    Auth flow:
      1. Receive client_id + client_secret + target_user from the frontend
      2. Mint a client-credentials token and confirm the target gallery responds
      3. If validation succeeds, save credentials to settings.json
    """
    client_id = body.get("client_id", "").strip()
    client_secret = body.get("client_secret", "").strip()
    target_user = body.get("target_user", "").strip()

    if not client_id or not client_secret:
        raise HTTPException(400, "client_id and client_secret are required")
    if not target_user:
        raise HTTPException(400, "Target user is required (the DA user to track)")

    # Validate with a throwaway client so we never mutate the shared poll
    # singleton mid-cycle (the OAuth path re-reads creds from settings on every
    # cycle, so there's no live session to preserve). Avoids a connect/poll race.
    client = DAClient(client_id=client_id, client_secret=client_secret,
                      target_user=target_user)
    try:
        valid = await client.validate_credentials()
    except Exception as e:
        raise HTTPException(502, f"Failed to validate credentials: {e}")
    finally:
        await client.close()

    if not valid:
        raise HTTPException(401, "Could not authenticate — check the client_id/client_secret "
                                 "and that the username exists.")

    config.save_settings({
        "da_client_id": client_id,
        "da_client_secret": client_secret,
        "da_target_user": target_user,
        "da_notifications_enabled": True,
    })

    return {"status": "success", "message": f"Connected — tracking {target_user}"}


@da_router.post("/auth/disconnect")
def da_disconnect():
    """Disconnect DA polling.

    Clears the target user (which flips auth/status to disconnected) and the
    legacy cookie, but deliberately KEEPS da_client_id/da_client_secret: those
    are shared with the DA *poster* (which also refreshes tokens from them), so
    deleting them here could break posting. Reconnecting just re-saves them.
    """
    config.delete_settings_keys(["da_target_user", "da_cookie"])
    config.save_settings({"da_notifications_enabled": False})
    return {"status": "success", "message": "DeviantArt disconnected"}


# -- DA Polling --------------------------------------------------------

@da_router.get("/poll/progress")
def get_da_poll_progress():
    return dict(da_poll_progress)


@da_router.post("/poll/trigger")
async def trigger_da_poll():
    """Manual poll trigger for DA."""
    try:
        spawn(run_da_poll_cycle(), "run_da_poll_cycle")
        return {"status": "started"}
    except Exception as e:
        logger.error("Error in DA poll trigger: %s", e, exc_info=True)
        raise HTTPException(500, detail=str(e))


@da_router.post("/poll/full-resync")
async def da_full_resync():
    """Force full DA resync."""
    try:
        spawn(run_da_poll_cycle(force_full=True), "run_da_poll_cycle full-resync")
        return {"status": "started"}
    except Exception as e:
        logger.error("Error in DA full resync: %s", e, exc_info=True)
        raise HTTPException(500, detail=str(e))


# -- DA Data -----------------------------------------------------------

@da_router.get("/status")
def get_da_status():
    conn = get_connection()
    try:
        last_poll = da_queries.get_da_last_poll(conn)
        count = conn.execute("SELECT COUNT(*) as c FROM da_submissions").fetchone()["c"]
        snap_count = conn.execute("SELECT COUNT(*) as c FROM da_snapshots").fetchone()["c"]
        return {
            "total_submissions": count,
            "total_snapshots": snap_count,
            "last_poll": last_poll,
        }
    except Exception as e:
        logger.error("Error in /api/da/status: %s", e, exc_info=True)
        raise HTTPException(500, detail=str(e))
    finally:
        conn.close()


@da_router.get("/summary")
def get_da_summary(account_id: int | None = Query(None)):
    conn = get_connection()
    try:
        summary = da_queries.get_da_summary(conn, account_id=account_id)
        # growth_rates stays aggregate (unscoped) — mirrors the IB /summary route.
        summary["growth_rates"] = da_queries.get_da_growth_rates(conn)
        return summary
    except Exception as e:
        logger.error("Error in /api/da/summary: %s", e, exc_info=True)
        raise HTTPException(500, detail=str(e))
    finally:
        conn.close()


@da_router.get("/submissions")
def get_da_submissions(
    sort_by: str = Query("views", description="Sort field"),
    order: str = Query("desc", description="Sort order"),
    search: str = Query("", description="Search title/keywords"),
    rating: str = Query("", description="Filter by rating"),
    account_id: int | None = Query(None),
):
    conn = get_connection()
    try:
        subs = da_queries.get_all_da_submissions(conn, sort_by=sort_by, order=order, account_id=account_id)
        deltas = da_queries.get_da_submission_deltas(conn)

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
            s["downloads_delta"] = d.get("downloads_delta", 0)

        return {"submissions": subs, "total": len(subs)}
    except Exception as e:
        logger.error("Error in /api/da/submissions: %s", e, exc_info=True)
        raise HTTPException(500, detail=str(e))
    finally:
        conn.close()


@da_router.get("/submissions/{submission_id}")
def get_da_submission(submission_id: int):
    conn = get_connection()
    try:
        sub = da_queries.get_da_submission(conn, submission_id)
        if not sub:
            raise HTTPException(status_code=404, detail="DA deviation not found")
        snapshots = da_queries.get_da_snapshots(conn, submission_id)
        growth_rates = da_queries.get_da_submission_growth_rates(conn, submission_id)
        try:
            tags = conn.execute(
                "SELECT t.tag_id, t.name, t.color FROM tags t JOIN submission_tags st ON t.tag_id = st.tag_id WHERE st.platform = 'da' AND st.submission_id = ?",
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
        logger.error("Error in /api/da/submissions/%s: %s", submission_id, e, exc_info=True)
        raise HTTPException(500, detail=str(e))
    finally:
        conn.close()


@da_router.get("/submissions/{submission_id}/snapshots")
def get_da_submission_snapshots(
    submission_id: int,
    start: Optional[str] = Query(None),
    end: Optional[str] = Query(None),
):
    conn = get_connection()
    try:
        return {"snapshots": da_queries.get_da_snapshots(conn, submission_id, start, end)}
    except Exception as e:
        logger.error("Error in /api/da/submissions/%s/snapshots: %s", submission_id, e, exc_info=True)
        raise HTTPException(500, detail=str(e))
    finally:
        conn.close()


@da_router.get("/aggregate")
def get_da_aggregate(
    start: Optional[str] = Query(None),
    end: Optional[str] = Query(None),
    account_id: int | None = Query(None),
):
    conn = get_connection()
    try:
        return {"snapshots": da_queries.get_da_aggregate_snapshots(conn, start, end, account_id=account_id)}
    except Exception as e:
        logger.error("Error in /api/da/aggregate: %s", e, exc_info=True)
        raise HTTPException(500, detail=str(e))
    finally:
        conn.close()


@da_router.get("/comparison")
def get_da_comparison(
    ids: str = Query(..., description="Comma-separated deviation IDs"),
    start: Optional[str] = Query(None),
    end: Optional[str] = Query(None),
):
    submission_ids = [int(x.strip()) for x in ids.split(",") if x.strip().isdigit()]
    if len(submission_ids) > 10:
        raise HTTPException(400, "Max 10 deviations for comparison")

    conn = get_connection()
    try:
        data = da_queries.get_da_comparison_snapshots(conn, submission_ids, start, end)
        titles = {}
        for sid in submission_ids:
            sub = da_queries.get_da_submission(conn, sid)
            if sub:
                titles[str(sid)] = sub["title"]
        return {"series": data, "titles": titles}
    except Exception as e:
        logger.error("Error in /api/da/comparison: %s", e, exc_info=True)
        raise HTTPException(500, detail=str(e))
    finally:
        conn.close()


@da_router.get("/poll_log")
def get_da_poll_log(limit: int = Query(50, ge=1, le=200)):
    conn = get_connection()
    try:
        return {"polls": da_queries.get_da_poll_log(conn, limit)}
    except Exception as e:
        logger.error("Error in /api/da/poll_log: %s", e, exc_info=True)
        raise HTTPException(500, detail=str(e))
    finally:
        conn.close()


# -- DA CSV Export -----------------------------------------------------

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


@da_router.get("/export/submissions")
def export_da_submissions():
    conn = get_connection()
    try:
        subs = da_queries.get_all_da_submissions(conn)
        return _csv_response(subs, "deviantart_submissions.csv")
    finally:
        conn.close()


@da_router.get("/export/snapshots")
def export_da_snapshots(id: int | None = Query(None)):
    conn = get_connection()
    try:
        if id:
            snaps = da_queries.get_da_snapshots(conn, id)
        else:
            snaps = [dict(r) for r in conn.execute("SELECT * FROM da_snapshots ORDER BY polled_at ASC").fetchall()]
        return _csv_response(snaps, f"da_snapshots{'_' + str(id) if id else ''}.csv")
    finally:
        conn.close()
