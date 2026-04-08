"""Archive of Our Own (AO3) HTTP client.

AO3 runs the OTW Archive software (same as SquidgeWorld). Authentication
is via standard Rails form login with CSRF token. Data is collected by
scraping the web UI since there is no public API.

Key details:
  - Work IDs are integers (e.g. 12345678)
  - Stats: hits, kudos, comments, bookmarks
  - Auth: username/password login (separate from the user being tracked)
  - AO3 uses Cloudflare; realistic headers and respectful rate limiting required
"""

from __future__ import annotations
import asyncio
import logging
import re
from html import unescape

import httpx

import config

logger = logging.getLogger(__name__)

_BASE = "https://archiveofourown.org"

# Realistic browser headers
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}


class AO3Client:
    """Async HTTP client for Archive of Our Own (OTW Archive)."""

    def __init__(self, username: str, password: str, target_user: str):
        self.username = username
        self.password = password
        self.target_user = target_user
        transport = httpx.AsyncHTTPTransport(retries=2)
        self._http = httpx.AsyncClient(
            timeout=60.0,
            follow_redirects=True,
            headers=_HEADERS,
            transport=transport,
        )
        self._logged_in = False
        self._pseud_id: str | None = None  # cached after first form fetch

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        await self.close()

    def update_credentials(self, username: str, password: str, target_user: str) -> None:
        if username != self.username or password != self.password:
            self._logged_in = False
        self.username = username
        self.password = password
        self.target_user = target_user

    async def close(self) -> None:
        await self._http.aclose()

    # ── Page Fetching ────────────────────────────────────────────

    async def _get_page(self, url: str, *, max_attempts: int = 3) -> str | None:
        """Fetch a page, handling Cloudflare errors and timeouts gracefully.

        AO3 from datacenter IPs sees intermittent ReadTimeouts (~1 in 5
        requests). The transport-level retries=2 in __init__ only helps with
        connect failures, not read timeouts after the headers arrive. We
        retry the whole GET up to max_attempts times with a brief pause.
        """
        last_exc: Exception | None = None
        for attempt in range(1, max_attempts + 1):
            try:
                resp = await self._http.get(url)
                if resp.status_code == 403:
                    # Could be a hard CF block OR AO3's "Shields are up!" defensive page
                    if "Shields are up" in resp.text:
                        logger.error("AO3: 'Shields are up!' page returned for %s", url)
                    else:
                        logger.error("AO3: 403 Forbidden for %s", url)
                    return None
                if resp.status_code == 429:
                    logger.warning("AO3: Rate limited (429), waiting 30s before retry...")
                    await asyncio.sleep(30)
                    resp = await self._http.get(url)
                if resp.status_code == 525:
                    # CF↔origin SSL handshake fail. Retry-able.
                    logger.warning("AO3: 525 SSL handshake from origin (attempt %d/%d)", attempt, max_attempts)
                    last_exc = RuntimeError("525 origin SSL")
                    await asyncio.sleep(2 * attempt)
                    continue
                resp.raise_for_status()
                return resp.text
            except (httpx.ReadTimeout, httpx.ConnectTimeout, httpx.PoolTimeout) as e:
                last_exc = e
                logger.warning(
                    "AO3: timeout fetching %s (attempt %d/%d): %s",
                    url, attempt, max_attempts, type(e).__name__,
                )
                await asyncio.sleep(2 * attempt)
                continue
            except httpx.HTTPError as e:
                last_exc = e
                logger.error("AO3: HTTPError fetching %s: %s %r", url, type(e).__name__, e)
                return None

        logger.error(
            "AO3: failed to fetch %s after %d attempts (last error: %s %r)",
            url, max_attempts, type(last_exc).__name__ if last_exc else "?", last_exc,
        )
        return None

    # ── Authentication ──────────────────────────────────────────

    async def login(self) -> bool:
        """Authenticate via OTW Archive Rails login form."""
        logger.info("AO3: Logging in as %s...", self.username)

        html = await self._get_page(f"{_BASE}/users/login")
        if not html:
            logger.error("AO3: Failed to fetch login page")
            return False

        # Extract authenticity_token
        token_match = re.search(
            r'<input[^>]*name="authenticity_token"[^>]*value="([^"]+)"',
            html,
        )
        if not token_match:
            token_match = re.search(
                r'<input[^>]*value="([^"]+)"[^>]*name="authenticity_token"',
                html,
            )
        if not token_match:
            logger.error("AO3: Could not find authenticity_token on login page")
            return False

        token = token_match.group(1)

        login_data = {
            "authenticity_token": token,
            "user[login]": self.username,
            "user[password]": self.password,
            "user[remember_me]": "1",
            "commit": "Log In",
        }

        try:
            resp = await self._http.post(
                f"{_BASE}/users/login",
                data=login_data,
                headers={
                    **_HEADERS,
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Referer": f"{_BASE}/users/login",
                },
            )
        except httpx.HTTPError as e:
            logger.error("AO3: Login POST failed: %s", e)
            return False

        page = resp.text
        if f"Hi, {self.username}" in page or "Log Out" in page or 'class="greeting"' in page:
            self._logged_in = True
            logger.info("AO3: Successfully logged in as %s", self.username)
            return True

        if resp.url and "/users/" in str(resp.url):
            self._logged_in = True
            logger.info("AO3: Login redirect successful for %s", self.username)
            return True

        logger.error("AO3: Login appears to have failed (no logged-in indicators)")
        return False

    async def ensure_logged_in(self) -> bool:
        if self._logged_in:
            html = await self._get_page(f"{_BASE}/users/{self.username}")
            if html and "Log Out" in html:
                return True
            self._logged_in = False
        return await self.login()

    async def validate_session(self) -> str | None:
        if await self.ensure_logged_in():
            return self.target_user
        return None

    # ── Works Discovery ─────────────────────────────────────────

    async def get_all_work_ids(self) -> list[dict]:
        """Scrape the target user's works page to discover all work IDs."""
        if not await self.ensure_logged_in():
            raise ValueError("AO3: Not authenticated")

        all_works: list[dict] = []
        page = 1
        seen_ids: set[int] = set()

        for _page_safety in range(1000):
            url = f"{_BASE}/users/{self.target_user}/works?page={page}"
            logger.info("AO3: Fetching works page %d for %s", page, self.target_user)

            html = await self._get_page(url)
            if not html:
                logger.error("AO3: Failed to fetch works page %d", page)
                break

            # Extract only works from the main work listing, not sidebar/related works.
            # AO3 wraps the user's works in <ol class="work index group">.
            work_list_match = re.search(
                r'<ol[^>]*class="[^"]*work\s+index[^"]*"[^>]*>(.*?)</ol>',
                html, re.DOTALL,
            )
            work_section = work_list_match.group(1) if work_list_match else html
            works = re.findall(
                r'<a\s+href="/works/(\d+)"[^>]*>([^<]+)</a>',
                work_section,
            )

            if not works:
                break

            new_this_page = 0
            for work_id_str, title in works:
                work_id = int(work_id_str)
                if work_id not in seen_ids:
                    seen_ids.add(work_id)
                    all_works.append({
                        "work_id": work_id,
                        "title": unescape(title.strip()),
                    })
                    new_this_page += 1

            if new_this_page == 0:
                break

            if f'page={page + 1}' not in html and 'rel="next"' not in html:
                break

            page += 1
            await asyncio.sleep(config.AO3_REQUEST_DELAY_SECONDS)

        logger.info("AO3: Found %d works for %s", len(all_works), self.target_user)
        return all_works

    # ── Work Details ────────────────────────────────────────────

    async def get_work_detail(self, work_id: int) -> dict:
        """Fetch stats and metadata for a single work."""
        url = f"{_BASE}/works/{work_id}?view_adult=true"

        html = await self._get_page(url)
        if not html:
            logger.error("AO3: Failed to fetch work %d", work_id)
            return {"work_id": work_id, "title": "", "hits": 0, "kudos_count": 0,
                    "comments_count": 0, "bookmarks_count": 0}

        detail: dict = {"work_id": work_id}

        # Title
        m = re.search(r'<h2\s+class="title[^"]*heading"[^>]*>(.*?)</h2>', html, re.DOTALL)
        if m:
            title_html = m.group(1)
            detail["title"] = unescape(re.sub(r'<[^>]+>', '', title_html).strip())
        else:
            detail["title"] = ""

        # Author
        m = re.search(r'<a\s+rel="author"[^>]*>([^<]+)</a>', html)
        detail["username"] = unescape(m.group(1).strip()) if m else self.target_user

        # Fandom
        m = re.search(r'class="fandom[^"]*"[^>]*>.*?<a[^>]*>([^<]+)</a>', html, re.DOTALL)
        detail["fandom"] = unescape(m.group(1).strip()) if m else ""

        # Rating
        m = re.search(r'class="rating[^"]*"[^>]*>.*?<a[^>]*>([^<]+)</a>', html, re.DOTALL)
        detail["rating"] = unescape(m.group(1).strip()) if m else ""

        # Summary
        m = re.search(
            r'class="summary[^"]*"[^>]*>.*?<blockquote[^>]*>(.*?)</blockquote>',
            html, re.DOTALL,
        )
        if m:
            summary_html = m.group(1).strip()
            detail["description"] = re.sub(r'<[^>]+>', '', summary_html).strip()
        else:
            detail["description"] = ""

        # Tags/keywords
        tags = re.findall(r'class="tag"[^>]*>([^<]+)</a>', html)
        detail["keywords"] = [unescape(t.strip()) for t in tags]

        # Stats extraction
        def _extract_stat(stat_class: str) -> int:
            pattern = rf'<dd\s+class="{stat_class}"[^>]*>\s*(\d[\d,]*)\s*</dd>'
            m = re.search(pattern, html)
            if m:
                return int(m.group(1).replace(",", ""))
            pattern2 = rf'<dd\s+class="{stat_class}"[^>]*>\s*<a[^>]*>\s*(\d[\d,]*)\s*</a>'
            m = re.search(pattern2, html)
            if m:
                return int(m.group(1).replace(",", ""))
            return 0

        detail["hits"] = _extract_stat("hits")
        detail["kudos_count"] = _extract_stat("kudos")
        detail["comments_count"] = _extract_stat("comments")
        detail["bookmarks_count"] = _extract_stat("bookmarks")

        # Word count and chapters
        detail["word_count"] = _extract_stat("words")
        m = re.search(r'<dd\s+class="chapters"[^>]*>(\d+)/(\d+|\?)', html)
        if m:
            detail["chapters_current"] = int(m.group(1))
            detail["chapters_total"] = m.group(2)
            detail["chapters"] = f"{m.group(1)}/{m.group(2)}"
        else:
            detail["chapters_current"] = 1
            detail["chapters_total"] = "1"
            detail["chapters"] = "1/1"

        # Dates
        m = re.search(r'class="published"[^>]*>(\d{4}-\d{2}-\d{2})</dd>', html)
        detail["posted_at"] = m.group(1) if m else None

        m = re.search(r'class="status"[^>]*>(\d{4}-\d{2}-\d{2})</dd>', html)
        detail["updated_date"] = m.group(1) if m else detail.get("posted_at")

        # Link
        detail["link"] = f"{_BASE}/works/{work_id}"

        # Map to consistent schema column names
        detail["views"] = detail["hits"]
        detail["favorites_count"] = detail["kudos_count"]

        return detail

    async def get_work_details_batch(self, work_ids: list[int]) -> list[dict]:
        details = []
        for i, work_id in enumerate(work_ids):
            if i > 0:
                await asyncio.sleep(config.AO3_REQUEST_DELAY_SECONDS)
            try:
                detail = await self.get_work_detail(work_id)
                details.append(detail)
            except Exception as e:
                logger.warning("AO3: Failed to fetch work %d: %s", work_id, e)
        return details

    # ── Kudos Users ─────────────────────────────────────────────

    async def get_kudos_users(self, work_id: int) -> list[str]:
        """Extract the list of users who left kudos on a work."""
        url = f"{_BASE}/works/{work_id}?view_adult=true"
        html = await self._get_page(url)
        if not html:
            return []

        kudos_section = re.search(
            r'id="kudos"[^>]*>(.*?)</p>', html, re.DOTALL,
        )
        if not kudos_section:
            kudos_section = re.search(
                r'class="kudos"[^>]*>(.*?)</p>', html, re.DOTALL,
            )
        if not kudos_section:
            return []

        users = re.findall(
            r'<a\s+href="/users/([^"]+)"', kudos_section.group(1),
        )
        return [unescape(u) for u in users]

    # ── Posting / Upload ────────────────────────────────────────

    async def _get_authenticity_token(self, url: str) -> str | None:
        """Fetch a page and extract the Rails authenticity_token."""
        html = await self._get_page(url)
        if not html:
            return None
        m = re.search(r'name="authenticity_token"[^>]*value="([^"]+)"', html)
        if not m:
            m = re.search(r'value="([^"]+)"[^>]*name="authenticity_token"', html)
        return m.group(1) if m else None

    async def create_work(
        self,
        *,
        title: str,
        content: str,
        fandom: str = "Original Work",
        rating: str = "Explicit",
        warnings: list[str] | None = None,
        categories: list[str] | None = None,
        relationship: str = "",
        characters: str = "",
        additional_tags: str = "",
        summary: str = "",
        notes_begin: str = "",
        notes_end: str = "",
        language_id: str = "1",  # AO3 numeric language ID; 1 = English
        chapter_title: str = "",
        work_skin_id: str = "",
        # Backwards-compat single-value parameters
        warning: str | None = None,
        category: str | None = None,
    ) -> dict:
        """Create a new work on AO3 as a DRAFT (preview state).

        Same OTW form as SquidgeWorld. Uses ``preview_button`` so the work
        lands in the user's drafts at /works/{id}/preview without being
        published. Click "Post" on the preview page (or call ``post_work()``)
        to publish.

        Args:
            title: Work title.
            content: HTML chapter content (first chapter body).
            fandom: Fandom name (default: "Original Work").
            rating: "General Audiences", "Teen And Up Audiences", "Mature", "Explicit".
            warnings: List of canonical archive warnings. Defaults to
                ``["No Archive Warnings Apply"]``. Each must be one of:
                "Choose Not To Use Archive Warnings", "Graphic Depictions Of Violence",
                "Major Character Death", "No Archive Warnings Apply",
                "Rape/Non-Con", "Underage", "Suicide/Suicidal Ideation",
                "Incest and/or Incestuous Relationship(s)".
            categories: List of relationship categories (e.g. ["M/M"]).
            relationship: Comma-separated relationship tags.
            characters: Comma-separated character tags.
            additional_tags: Comma-separated freeform tags.
            summary: Work summary (HTML allowed, 1250 char max).
            notes_begin: Beginning notes.
            notes_end: End notes.
            language_id: Language ID. AO3 uses ISO codes (e.g. "en"); SQW
                uses numeric IDs ("15"). AO3 form accepts both.
            chapter_title: Optional title for the first chapter.
            work_skin_id: Optional Work Skin ID.
            warning: (deprecated) Single warning string.
            category: (deprecated) Single category string.

        Returns:
            Dict with 'work_id' and 'url'.
        """
        # Backwards compat
        if warnings is None:
            warnings = [warning] if warning else ["No Archive Warnings Apply"]
        if categories is None:
            categories = [category] if category else []

        if not self._logged_in:
            if not await self.ensure_logged_in():
                raise RuntimeError("AO3: Not logged in")

        # GET the new work form to extract CSRF token AND the author pseud ID.
        # The pseud ID is REQUIRED — every OTW work must have at least one
        # creator linked via work[author_attributes][ids][]. Without it the
        # form silently fails validation.
        form_html = await self._get_page(f"{_BASE}/works/new")
        if not form_html:
            raise RuntimeError("AO3: Could not fetch /works/new form")

        token_m = re.search(
            r'name="authenticity_token"[^>]*value="([^"]+)"', form_html
        )
        if not token_m:
            raise RuntimeError("AO3: Could not get CSRF token from /works/new")
        token = token_m.group(1)

        pseud_m = re.search(
            r'<input[^>]*value="(\d+)"[^>]*name="work\[author_attributes\]\[ids\]\[\]"',
            form_html,
        ) or re.search(
            r'<input[^>]*name="work\[author_attributes\]\[ids\]\[\]"[^>]*value="(\d+)"',
            form_html,
        )
        if not pseud_m:
            raise RuntimeError("AO3: Could not extract author pseud ID from /works/new")
        pseud_id = pseud_m.group(1)
        self._pseud_id = pseud_id

        clean_content = _collapse_html_whitespace(content)

        form_data: list[tuple[str, str]] = [
            ("authenticity_token", token),
            ("work[title]", title),
            ("work[author_attributes][ids][]", pseud_id),
            ("work[fandom_string]", fandom),
            ("work[rating_string]", rating),
        ]
        # Warnings: array notation. Hidden empty value first, then each warning.
        form_data.append(("work[archive_warning_strings][]", ""))
        for w in warnings:
            form_data.append(("work[archive_warning_strings][]", w))
        # Categories: array notation. Hidden empty value first, then each category.
        form_data.append(("work[category_strings][]", ""))
        for c in categories:
            form_data.append(("work[category_strings][]", c))
        form_data.extend([
            ("work[relationship_string]", relationship),
            ("work[character_string]", characters),
            ("work[freeform_string]", additional_tags),
            ("work[summary]", summary[:1250]),
            ("work[notes]", notes_begin),
            ("work[endnotes]", notes_end),
            ("work[language_id]", language_id),
            ("work[work_skin_id]", work_skin_id),
            ("work[wip_length]", "1"),
            ("work[chapter_attributes][title]", chapter_title),
            ("work[chapter_attributes][content]", clean_content),
            ("preview_button", "Preview"),
        ])

        # Manual urlencode because httpx 0.28.x AsyncClient has a bug with
        # list-of-tuples data= (raises "sync request with an AsyncClient").
        from urllib.parse import urlencode
        body = urlencode(form_data, doseq=True)

        await asyncio.sleep(config.AO3_REQUEST_DELAY_SECONDS)
        resp = await self._http.post(
            f"{_BASE}/works",
            content=body,
            headers={
                "Referer": f"{_BASE}/works/new",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            timeout=60.0,
        )

        final_url = str(resp.url)
        if "/works/new" in final_url or resp.status_code >= 400:
            errors = re.findall(r'class="error"[^>]*>(.*?)</li>', resp.text, re.DOTALL)
            err_text = "; ".join(re.sub(r'<[^>]+>', '', e).strip() for e in errors[:5])
            raise RuntimeError(f"AO3: Work creation failed (status {resp.status_code}): {err_text or 'unknown error'}")

        work_match = re.search(r'/works/(\d+)', final_url)
        if work_match:
            work_id = work_match.group(1)
            url = f"{_BASE}/works/{work_id}"
            logger.info("AO3: Created work %s (preview/draft) — %s", work_id, url)
            return {"work_id": work_id, "url": url}

        # Dump body for debugging
        import time
        debug_path = f"/tmp/ao3_create_debug_{int(time.time())}.html"
        try:
            with open(debug_path, "w", encoding="utf-8") as f:
                f.write(f"<!-- final_url: {final_url} -->\n")
                f.write(f"<!-- status: {resp.status_code} -->\n")
                f.write(resp.text)
            logger.error("AO3: response body saved to %s", debug_path)
        except Exception:
            pass
        errors = re.findall(r'class="[^"]*error[^"]*"[^>]*>(.*?)</', resp.text, re.DOTALL)
        err_text = "; ".join(re.sub(r'<[^>]+>', '', e).strip()[:200] for e in errors[:5])
        raise RuntimeError(
            f"AO3: Could not extract work ID from {final_url} "
            f"(status={resp.status_code}, errors={err_text or 'none found'})"
        )

    async def edit_work(
        self,
        work_id: str,
        *,
        title: str | None = None,
        summary: str | None = None,
        additional_tags: str | None = None,
        notes_begin: str | None = None,
        notes_end: str | None = None,
    ) -> dict:
        """Edit metadata on an existing AO3 work."""
        if not self._logged_in:
            if not await self.ensure_logged_in():
                raise RuntimeError("AO3: Not logged in")

        edit_url = f"{_BASE}/works/{work_id}/edit"
        token = await self._get_authenticity_token(edit_url)
        if not token:
            raise RuntimeError("AO3: Could not get CSRF token from edit page")

        form_data: dict[str, str] = {
            "authenticity_token": token,
            "_method": "patch",
        }
        if title is not None:
            form_data["work[title]"] = title
        if summary is not None:
            form_data["work[summary]"] = summary[:1250]
        if additional_tags is not None:
            form_data["work[freeform_string]"] = additional_tags
        if notes_begin is not None:
            form_data["work[notes]"] = notes_begin
        if notes_end is not None:
            form_data["work[endnotes]"] = notes_end

        await asyncio.sleep(config.AO3_REQUEST_DELAY_SECONDS)
        resp = await self._http.post(
            f"{_BASE}/works/{work_id}",
            data=form_data,
            headers={"Referer": edit_url},
            timeout=30.0,
        )

        if resp.status_code >= 400:
            raise RuntimeError(f"AO3: Edit failed — status {resp.status_code}")

        logger.info("AO3: Edited work %s", work_id)
        return {"work_id": work_id, "url": f"{_BASE}/works/{work_id}"}

    async def edit_chapter(
        self,
        work_id: str,
        chapter_id: str,
        *,
        content: str,
        title: str | None = None,
    ) -> dict:
        """Edit the content of a specific chapter.

        Collapses HTML whitespace to prevent AO3's auto-formatter from
        inserting <br /> tags within elements.
        """
        if not self._logged_in:
            if not await self.ensure_logged_in():
                raise RuntimeError("AO3: Not logged in")

        clean_content = _collapse_html_whitespace(content)
        edit_url = f"{_BASE}/works/{work_id}/chapters/{chapter_id}/edit"

        page = await self._get_page(edit_url)
        if not page:
            raise RuntimeError("AO3: Could not load chapter edit page")

        token = re.search(r'name="authenticity_token"[^>]*value="([^"]+)"', page)
        if not token:
            token = re.search(r'value="([^"]+)"[^>]*name="authenticity_token"', page)
        if not token:
            raise RuntimeError("AO3: Could not get CSRF token from chapter edit")

        form_data: dict[str, str] = {
            "authenticity_token": token.group(1),
            "_method": "patch",
            "chapter[content]": clean_content,
        }
        if title is not None:
            form_data["chapter[title]"] = title

        # Include commit button
        commit = re.search(r'name="commit"[^>]*value="([^"]*)"', page)
        form_data["commit"] = commit.group(1) if commit else "Update"

        utf8 = re.search(r'name="utf8"[^>]*value="([^"]*)"', page)
        if utf8:
            form_data["utf8"] = utf8.group(1)

        await asyncio.sleep(config.AO3_REQUEST_DELAY_SECONDS)
        resp = await self._http.post(
            f"{_BASE}/works/{work_id}/chapters/{chapter_id}",
            data=form_data,
            headers={"Referer": edit_url},
            timeout=60.0,
        )

        if resp.status_code >= 400:
            raise RuntimeError(f"AO3: Chapter edit failed — status {resp.status_code}")

        errors = re.findall(r'class="error"[^>]*>(.*?)</li>', resp.text[:3000], re.DOTALL)
        if errors:
            err_text = "; ".join(re.sub(r'<[^>]+>', '', e).strip() for e in errors[:3])
            raise RuntimeError(f"AO3: Chapter edit errors: {err_text}")

        logger.info("AO3: Edited chapter %s of work %s", chapter_id, work_id)
        return {"work_id": work_id, "chapter_id": chapter_id}

    async def get_chapter_ids(self, work_id: str) -> list[dict]:
        """Get all chapter IDs and titles for a work."""
        url = f"{_BASE}/works/{work_id}/navigate"
        html = await self._get_page(url)
        if not html:
            return []

        chapters = re.findall(
            r'href="/works/\d+/chapters/(\d+)"[^>]*>(\d+)\.\s*([^<]*)',
            html,
        )
        return [
            {"chapter_id": ch_id, "index": int(idx), "title": title.strip()}
            for ch_id, idx, title in chapters
        ]

    # ── Safety / Cleanup ────────────────────────────────────────

    async def delete_work(self, work_id: str) -> bool:
        """Delete a work via the OTW confirm_delete flow.

        Returns True on success, raises on failure. USE WITH CARE - destructive.
        """
        if not self._logged_in:
            if not await self.ensure_logged_in():
                raise RuntimeError("AO3: Not logged in")

        confirm_url = f"{_BASE}/works/{work_id}/confirm_delete"
        confirm_resp = await self._http.get(confirm_url)
        if confirm_resp.status_code != 200:
            raise RuntimeError(
                f"AO3: Could not load confirm_delete page (status {confirm_resp.status_code})"
            )

        token_m = re.search(
            r'name="authenticity_token"[^>]*value="([^"]+)"', confirm_resp.text
        ) or re.search(
            r'value="([^"]+)"[^>]*name="authenticity_token"', confirm_resp.text
        )
        if not token_m:
            raise RuntimeError("AO3: Could not get CSRF token from confirm_delete page")

        from urllib.parse import urlencode
        body = urlencode([
            ("authenticity_token", token_m.group(1)),
            ("_method", "delete"),
            ("commit", "Yes, Delete Work"),
        ])

        await asyncio.sleep(config.AO3_REQUEST_DELAY_SECONDS)
        resp = await self._http.post(
            f"{_BASE}/works/{work_id}",
            content=body,
            headers={
                "Referer": confirm_url,
                "Content-Type": "application/x-www-form-urlencoded",
            },
            timeout=60.0,
        )

        if resp.status_code >= 400:
            raise RuntimeError(f"AO3: Delete failed — status {resp.status_code}")
        if "successfully deleted" not in resp.text and "has been deleted" not in resp.text:
            check = await self._http.get(
                f"{_BASE}/works/{work_id}", follow_redirects=False
            )
            if check.status_code != 404:
                logger.warning(
                    "AO3: delete_work returned %s but work %s may still exist",
                    resp.status_code, work_id,
                )

        logger.info("AO3: Deleted work %s", work_id)
        return True

    async def is_work_in_drafts(self, work_id: str) -> bool | None:
        """Check whether a work is in /users/{user}/works/drafts.

        Returns:
            True   — work is in the drafts listing
            False  — drafts page fetched, work not present
            None   — fetch failed (network/timeout/CF) — caller cannot conclude
        """
        if not self._logged_in:
            await self.ensure_logged_in()
        url = f"{_BASE}/users/{self.username}/works/drafts"
        html = await self._get_page(url)
        if html is None:
            return None
        return f"/works/{work_id}" in html

    async def is_work_published(self, work_id: str) -> bool | None:
        """Check whether a work is in /users/{user}/works (the published listing).

        Returns:
            True   — work is in the published listing
            False  — published page fetched, work not present
            None   — fetch failed (caller cannot conclude)
        """
        if not self._logged_in:
            await self.ensure_logged_in()
        url = f"{_BASE}/users/{self.username}/works"
        html = await self._get_page(url)
        if html is None:
            return None
        return f"/works/{work_id}" in html


def _collapse_html_whitespace(html: str) -> str:
    """Collapse multi-line HTML so each element is on a single line.

    OTW Archive's chapter editor converts internal newlines within HTML tags
    to <br /> tags, causing unwanted line breaks.
    """
    def _collapse_tag(match: re.Match) -> str:
        text = match.group(0)
        collapsed = re.sub(r'\n\s*', ' ', text)
        collapsed = re.sub(r'  +', ' ', collapsed)
        return collapsed

    result = re.sub(r'<p[^>]*>.*?</p>', _collapse_tag, html, flags=re.DOTALL)
    result = re.sub(r'<div[^>]*>.*?</div>', _collapse_tag, result, flags=re.DOTALL)
    result = re.sub(r'\n{3,}', '\n\n', result)
    return result
