"""FurryNetwork API client — polling (own submissions + stats) and posting.

FurryNetwork (furrynetwork.com) organises a user's work under one or more
**characters** (a persona layer). Auth is OAuth2 password grant against
``https://furrynetwork.com/api`` with the public web ``client_id=123``; the
access token lasts ~1h and is renewed from the stored refresh token.

References: CrosspostSharp's `FurryNetworkClient.cs` (posting flow, endpoints)
and JustAnOpossum/FurryNetworkAPI (OAuth). PostyBirb dropped FN in its rewrite,
so those are the best available references — several response shapes here are
built to the documented model and should be **verified live** against a real
account (the Threads/IG pattern). Confirmed 2026-07-31: the API host is up and
reachable from the GCP VM (no datacenter block, unlike FurAffinity).

The client mirrors the same contract the pollers/posters expect elsewhere:
``validate_session`` → username, ``get_all_post_uris`` → discovery list,
``get_post_details_batch`` → normalised submission dicts, ``upload_artwork``.
"""
from __future__ import annotations

import logging
import os
import time
from typing import Any

import httpx

logger = logging.getLogger(__name__)

API_BASE = "https://furrynetwork.com/api"
SITE_BASE = "https://furrynetwork.com"
CLIENT_ID = "123"                 # FN's public web client
HTTP_TIMEOUT = 30.0
UPLOAD_TIMEOUT = 120.0
UPLOAD_CHUNK = 512 * 1024         # 512 KB — FN's resumable chunk size

# FN rating is an int 0..2. Map to our internal rating vocabulary and back.
_RATING_FROM_FN = {0: "general", 1: "mature", 2: "adult"}
_RATING_TO_FN = {"general": 0, "mature": 1, "adult": 2, "explicit": 2, "extreme": 2}


def _safe_int(v: Any) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0


class FnAuthError(Exception):
    """Raised on a genuine auth failure (bad credentials / revoked token) so the
    session-check can distinguish it from a transient network blip."""


class FnClient:
    def __init__(self, username: str = "", password: str = "",
                 access_token: str = "", refresh_token: str = ""):
        # `username` here is the FN login email; the display name comes from /user.
        self.username = username
        self.password = password
        self.access_token = access_token
        self.refresh_token = refresh_token
        self._token_expiry = 0.0
        self._client: httpx.AsyncClient | None = None
        self._user: dict | None = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        await self.close()

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=HTTP_TIMEOUT)
        return self._client

    # -- OAuth ----------------------------------------------------------------

    async def _token_request(self, data: dict) -> dict:
        data = {**data, "client_id": CLIENT_ID}
        r = await self._http().post(f"{API_BASE}/oauth/token", data=data)
        try:
            body = r.json()
        except Exception:
            body = {}
        if r.status_code >= 400 or body.get("error"):
            msg = body.get("error_description") or body.get("error") or f"HTTP {r.status_code}"
            raise FnAuthError(f"FurryNetwork auth failed: {msg}")
        self.access_token = body.get("access_token", "") or self.access_token
        self.refresh_token = body.get("refresh_token", "") or self.refresh_token
        # Renew a minute early to avoid a mid-request expiry.
        self._token_expiry = time.monotonic() + max(60, _safe_int(body.get("expires_in")) - 60)
        return body

    async def login(self) -> bool:
        """Obtain a token: refresh if we have one, else password grant."""
        if self.refresh_token:
            try:
                await self._token_request({"grant_type": "refresh_token",
                                           "refresh_token": self.refresh_token})
                return True
            except FnAuthError:
                # Refresh token dead → fall back to password grant if we can.
                if not (self.username and self.password):
                    raise
        if self.username and self.password:
            await self._token_request({"grant_type": "password",
                                       "username": self.username,
                                       "password": self.password})
            return True
        return False

    async def _ensure_token(self) -> None:
        if not self.access_token or time.monotonic() >= self._token_expiry:
            await self.login()

    async def _get(self, path: str, params: dict | None = None) -> Any:
        await self._ensure_token()
        r = await self._http().get(
            f"{API_BASE}/{path.lstrip('/')}", params=params,
            headers={"Authorization": f"Bearer {self.access_token}"})
        if r.status_code == 401:
            # Token may have died early — one forced refresh, then retry once.
            await self.login()
            r = await self._http().get(
                f"{API_BASE}/{path.lstrip('/')}", params=params,
                headers={"Authorization": f"Bearer {self.access_token}"})
        if r.status_code == 401:
            raise FnAuthError("FurryNetwork rejected the token (401)")
        if r.status_code >= 400:
            return None
        try:
            return r.json()
        except Exception:
            return None

    # -- User / characters ----------------------------------------------------

    async def get_user(self) -> dict | None:
        if self._user is None:
            self._user = await self._get("user") or None
        return self._user

    async def get_characters(self) -> list[dict]:
        user = await self.get_user()
        if not user:
            return []
        chars = user.get("characters") or []
        return [c for c in chars if isinstance(c, dict)]

    async def validate_session(self) -> str | None:
        """Confirm the credentials/token work. Returns the FN display name.

        Raises FnAuthError on a real auth failure so session-check shows the true
        reason; returns None only when nothing is configured.
        """
        if not (self.refresh_token or (self.username and self.password)):
            return None
        user = await self.get_user()
        if not user:
            return None
        # Prefer the account's own name; fall back to the login email.
        return user.get("email") or user.get("name") or self.username or "FurryNetwork"

    # -- Discovery ------------------------------------------------------------

    async def get_all_post_uris(self, types: tuple[str, ...] = ("artwork",)) -> list[dict]:
        """List the connected user's own submissions across all their characters.

        FN groups work under characters, so we page each character's gallery. The
        `search` endpoint carries full engagement data per hit, so no per-item
        fetch is needed — the raw hit is stashed for get_post_details_batch().
        """
        items: list[dict] = []
        seen: set[str] = set()
        for ch in await self.get_characters():
            name = ch.get("name")
            if not name:
                continue
            for t in types:
                frm = 0
                for _safety in range(200):        # 200*30 = 6k per char/type ceiling
                    data = await self._get("search", {
                        "character": name, "types[]": t, "sort": "created", "from": frm})
                    hits = _search_hits(data)
                    if not hits:
                        break
                    for h in hits:
                        sid = str(_safe_int(h.get("id")))
                        if not sid or sid in seen:
                            continue
                        seen.add(sid)
                        items.append({"post_uri": sid, "raw": h, "character": name})
                    if len(hits) < 30:
                        break
                    frm += len(hits)
        logger.info("FurryNetwork: found %d submissions across characters", len(items))
        return items

    async def get_post_details_batch(self, items: list[dict]) -> list[dict]:
        """Parse the raw hits gathered in discovery — no extra API calls."""
        return [self._parse_submission(it.get("raw") or {}, it.get("character", ""))
                for it in items]

    # -- Parsing --------------------------------------------------------------

    def _parse_submission(self, s: dict, character: str = "") -> dict:
        sid = str(_safe_int(s.get("id")))
        images = s.get("images") or {}
        file_url = images.get("original") or s.get("url") or ""
        thumb = (images.get("thumbnail") or images.get("small")
                 or images.get("medium") or file_url or "")
        tags = s.get("tags") or []
        keywords = [str(t.get("tag") if isinstance(t, dict) else t)
                    for t in tags if t]
        return {
            "post_uri": sid,
            "title": s.get("title") or f"#{sid}",
            "full_text": s.get("description", "") or "",
            "username": character or self.username,
            "posted_at": s.get("published") or s.get("created") or "",
            "content_type": "image",
            "rating": _RATING_FROM_FN.get(_safe_int(s.get("rating")), ""),
            "description": s.get("description", "") or "",
            "keywords": keywords,
            "link": f"{SITE_BASE}/{character}/artwork/{sid}" if character else f"{SITE_BASE}/artwork/{sid}",
            "thumbnail_url": thumb,
            "file_url": file_url,
            "views": _safe_int(s.get("views")),
            "favorites_count": _safe_int(s.get("favorites")),
            "comments_count": _safe_int(s.get("comments")),
            "has_media": 1 if file_url else 0,
        }

    async def get_follower_count(self) -> int | None:
        """Total followers across the account's characters (for the follower series)."""
        chars = await self.get_characters()
        if not chars:
            return None
        total = 0
        seen_any = False
        for c in chars:
            f = c.get("followers")
            if f is not None:
                total += _safe_int(f)
                seen_any = True
        return total if seen_any else None

    # -- Posting --------------------------------------------------------------

    async def upload_artwork(self, *, character: str, file_path: str, title: str,
                             description: str = "", tags: list[str] | None = None,
                             rating: str = "general", status: str = "public") -> dict:
        """Upload one artwork under `character`: chunked/resumable upload of the
        bytes, then PATCH the metadata. Returns {"success", "id", "url"}.

        Built to CrosspostSharp's flow; verify live before trusting in prod.
        """
        if not os.path.isfile(file_path):
            return {"success": False, "error": f"file not found: {file_path}"}
        await self._ensure_token()
        size = os.path.getsize(file_path)
        filename = os.path.basename(file_path)
        total_chunks = max(1, (size + UPLOAD_CHUNK - 1) // UPLOAD_CHUNK)
        identifier = f"{size}-{filename.replace('.', '')}"
        upload_path = f"{API_BASE}/submission/{character}/artwork/upload"
        headers = {"Authorization": f"Bearer {self.access_token}"}

        new_id = ""
        async with httpx.AsyncClient(timeout=UPLOAD_TIMEOUT) as up:
            with open(file_path, "rb") as fh:
                for chunk_no in range(1, total_chunks + 1):
                    blob = fh.read(UPLOAD_CHUNK)
                    params = {
                        "resumableChunkNumber": chunk_no,
                        "resumableChunkSize": UPLOAD_CHUNK,
                        "resumableCurrentChunkSize": len(blob),
                        "resumableTotalSize": size,
                        "resumableType": "application/octet-stream",
                        "resumableIdentifier": identifier,
                        "resumableFilename": filename,
                        "resumableRelativePath": filename,
                        "resumableTotalChunks": total_chunks,
                    }
                    r = await up.post(upload_path, params=params, content=blob,
                                      headers={**headers, "Content-Type": "application/octet-stream"})
                    if r.status_code >= 400:
                        return {"success": False,
                                "error": f"chunk {chunk_no}/{total_chunks} failed (HTTP {r.status_code})"}
                    # The final chunk's response carries the created submission.
                    if chunk_no == total_chunks:
                        try:
                            body = r.json()
                            new_id = str(body.get("id") or "")
                        except Exception:
                            new_id = ""

        if not new_id:
            return {"success": False, "error": "upload finished but no submission id returned"}

        # PATCH the metadata onto the freshly-uploaded artwork.
        patch = {
            "title": title,
            "description": description,
            "tags": tags or [],
            "rating": _RATING_TO_FN.get((rating or "general").lower(), 0),
            "status": status if status in ("draft", "unlisted", "public") else "public",
        }
        pr = await self._http().patch(
            f"{API_BASE}/artwork/{new_id}", json=patch,
            headers={**headers, "Content-Type": "application/json"})
        if pr.status_code >= 400:
            return {"success": False, "id": new_id,
                    "error": f"uploaded (id {new_id}) but metadata PATCH failed (HTTP {pr.status_code})"}
        url = f"{SITE_BASE}/{character}/artwork/{new_id}"
        return {"success": True, "id": new_id, "url": url}


def _search_hits(data: Any) -> list[dict]:
    """FN's search response shape isn't fully documented; tolerate the common
    envelopes — a bare list, {"hits": [...]}, or ES-style {"hits": {"hits": [...]}}."""
    if isinstance(data, list):
        return [h for h in data if isinstance(h, dict)]
    if isinstance(data, dict):
        hits = data.get("hits")
        if isinstance(hits, list):
            return [h.get("_source", h) if isinstance(h, dict) else h for h in hits]
        if isinstance(hits, dict) and isinstance(hits.get("hits"), list):
            return [h.get("_source", h) for h in hits["hits"] if isinstance(h, dict)]
        if isinstance(data.get("results"), list):
            return [h for h in data["results"] if isinstance(h, dict)]
    return []
