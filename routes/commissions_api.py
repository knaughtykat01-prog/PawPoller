"""Commissions API — a lightweight client/commission tracker (gap-wave-5 §4).

Single self-contained resource (no polymorphic members like Collections). Money
is data only — no payment integration. `artwork_name` deep-links a delivered
piece; `deliver_sites` is a JSON array of platform codes from the poster set.
"""
import logging

from fastapi import APIRouter, HTTPException

from database.db import get_connection
from database import commissions_queries as cq

logger = logging.getLogger(__name__)

commissions_router = APIRouter(prefix="/api/commissions", tags=["commissions"])


@commissions_router.get("")
def list_commissions():
    """All commissions, soonest-due first. Includes the status vocabulary so the
    frontend renders the board columns / advance control without hardcoding."""
    conn = get_connection()
    try:
        return {"commissions": cq.list_commissions(conn), "statuses": list(cq.STATUSES)}
    finally:
        conn.close()


@commissions_router.post("")
def create_commission(body: dict):
    """Create a commission. Body: {client_name, description?, price?, currency?,
    status?, due_date?, artwork_name?, deliver_sites?, notes?}."""
    client = (body.get("client_name") or "").strip()
    if not client:
        raise HTTPException(400, detail="client_name is required")
    status = body.get("status", "quote")
    if status and status not in cq.STATUSES:
        raise HTTPException(400, detail=f"status must be one of: {', '.join(cq.STATUSES)}")
    conn = get_connection()
    try:
        cid = cq.create_commission(
            conn, client_name=client, description=body.get("description", ""),
            price=body.get("price", 0), currency=body.get("currency", "USD"),
            status=status or "quote", due_date=body.get("due_date", ""),
            artwork_name=body.get("artwork_name", ""),
            deliver_sites=body.get("deliver_sites", []), notes=body.get("notes", ""))
        conn.commit()
        return {"status": "created", "id": cid}
    finally:
        conn.close()


@commissions_router.get("/{cid}")
def get_commission(cid: int):
    conn = get_connection()
    try:
        row = cq.get_commission(conn, cid)
        if not row:
            raise HTTPException(404, detail="Commission not found")
        return row
    finally:
        conn.close()


@commissions_router.patch("/{cid}")
def update_commission(cid: int, body: dict):
    """Update any of the commission fields (status validated against the set)."""
    status = body.get("status")
    if status is not None and status not in cq.STATUSES:
        raise HTTPException(400, detail=f"status must be one of: {', '.join(cq.STATUSES)}")
    conn = get_connection()
    try:
        if not cq.get_commission(conn, cid):
            raise HTTPException(404, detail="Commission not found")
        cq.update_commission(
            conn, cid, client_name=body.get("client_name"),
            description=body.get("description"), price=body.get("price"),
            currency=body.get("currency"), status=status,
            due_date=body.get("due_date"), artwork_name=body.get("artwork_name"),
            deliver_sites=body.get("deliver_sites"), notes=body.get("notes"))
        conn.commit()
        return {"status": "updated"}
    finally:
        conn.close()


@commissions_router.delete("/{cid}")
def delete_commission(cid: int):
    conn = get_connection()
    try:
        cq.delete_commission(conn, cid)
        conn.commit()
        return {"status": "deleted"}
    finally:
        conn.close()
