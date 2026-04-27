"""Inspect what happens when you POST a chapter to a draft work via
preview_button. Dumps the response so we can see what buttons / form
the OTW Archive expects for the next step.

Cleans up the test work afterwards.
"""
from __future__ import annotations

import asyncio
import re
import sys
from pathlib import Path
from urllib.parse import urlencode

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
from clients.sqw.client import SquidgeWorldClient


async def main() -> int:
    settings = config.get_settings()
    client = SquidgeWorldClient(
        settings.get("sqw_author_username") or settings.get("sqw_username"),
        settings.get("sqw_author_password") or settings.get("sqw_password"),
        settings.get("sqw_target_user", ""),
    )
    await client.ensure_logged_in()
    print(f"Logged in as {client.username}")

    work_id: str | None = None
    try:
        # 1. Create a tiny test draft
        print("Creating test draft...")
        result = await client.create_work(
            title="DELETE ME — Inspect Draft Chapter Form 2026-04-07",
            content="<p>Test chapter 1.</p>",
            fandom="Original Work",
            rating="General Audiences",
            warnings=["No Archive Warnings Apply"],
            categories=["Gen"],
            additional_tags="test",
            summary="Inspection test.",
            chapter_title="Chapter 1",
        )
        work_id = result["work_id"]
        print(f"  Created work {work_id}")

        # 2. Inspect the /chapters/new form for THIS draft work
        print()
        print(f"Fetching /works/{work_id}/chapters/new...")
        form_resp = await client._http.get(f"https://www.squidgeworld.org/works/{work_id}/chapters/new")
        form_html = form_resp.text
        Path(f"draft_chapter_new_form_{work_id}.html").write_text(form_html, encoding="utf-8")
        print(f"  Saved {len(form_html)} bytes")
        submits = re.findall(
            r'<input[^>]*type="submit"[^>]*name="([^"]*)"[^>]*value="([^"]*)"',
            form_html,
        )
        print(f"  Submit buttons on /chapters/new for DRAFT work:")
        for n, v in submits:
            print(f"    name={n!r} value={v!r}")
        form_action = re.search(r'<form[^>]*action="(/works/\d+/chapters)"', form_html)
        print(f"  Form action: {form_action.group(1) if form_action else '?'}")

        # 3. POST a chapter with preview_button
        print()
        print("POSTing chapter 2 with preview_button...")
        token_m = re.search(r'name="authenticity_token"[^>]*value="([^"]+)"', form_html)
        token = token_m.group(1) if token_m else None
        pseud_m = re.search(
            r'<input[^>]*value="(\d+)"[^>]*name="chapter\[author_attributes\]\[ids\]\[\]"',
            form_html,
        ) or re.search(
            r'<input[^>]*name="chapter\[author_attributes\]\[ids\]\[\]"[^>]*value="(\d+)"',
            form_html,
        )
        pseud_id = pseud_m.group(1) if pseud_m else None
        print(f"  token: {token[:20] if token else None}...")
        print(f"  pseud_id: {pseud_id}")

        post_data = [
            ("authenticity_token", token),
            ("chapter[author_attributes][ids][]", pseud_id),
            ("chapter[title]", "Chapter 2 Test"),
            ("chapter[summary]", ""),
            ("chapter[notes]", ""),
            ("chapter[endnotes]", ""),
            ("chapter[content]", "<p>Test chapter 2.</p>"),
            ("chapter[position]", "2"),
            ("preview_button", "Preview"),
        ]
        post_body = urlencode(post_data, doseq=True)

        post_resp = await client._http.post(
            f"https://www.squidgeworld.org/works/{work_id}/chapters",
            content=post_body,
            headers={
                "Referer": f"https://www.squidgeworld.org/works/{work_id}/chapters/new",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            timeout=60.0,
        )
        Path(f"draft_chapter_preview_response_{work_id}.html").write_text(post_resp.text, encoding="utf-8")
        print(f"  Status: {post_resp.status_code}")
        print(f"  Final URL: {post_resp.url}")
        print(f"  Body saved ({len(post_resp.text)} bytes)")

        # Look for buttons on the preview/response page
        preview_submits = re.findall(
            r'<input[^>]*type="submit"[^>]*name="([^"]*)"[^>]*value="([^"]*)"',
            post_resp.text,
        )
        print(f"  Submit buttons on preview/response page:")
        for n, v in preview_submits:
            print(f"    name={n!r} value={v!r}")

        # Look for forms
        forms = re.findall(r'<form[^>]*action="([^"]+)"[^>]*method="([^"]+)"', post_resp.text)
        print(f"  Forms on preview page:")
        for action, method in forms:
            print(f"    {method.upper()} {action}")

        # Find the save form and dump its fields
        print()
        print("  Preview form fields (input + textarea + select with name=chapter[*] or _method):")
        preview_form_match = re.search(
            rf'<form[^>]*action="/works/{work_id}/chapters/\d+"[^>]*>(.*?)</form>',
            post_resp.text, re.DOTALL,
        )
        if preview_form_match:
            preview_form_body = preview_form_match.group(1)
            for inp in re.finditer(r'<input([^>]*?)>', preview_form_body):
                attrs = inp.group(1)
                t_m = re.search(r'\btype="([^"]+)"', attrs)
                t = t_m.group(1) if t_m else 'text'
                n_m = re.search(r'\bname="([^"]+)"', attrs)
                v_m = re.search(r'\bvalue="([^"]*)"', attrs)
                if n_m:
                    name = n_m.group(1)
                    val = v_m.group(1)[:60] if v_m else ''
                    if 'authenticity' in name:
                        val = '...'
                    print(f"    [{t:7}] {name} = {val}")
            for ta in re.finditer(r'<textarea([^>]*?)>', preview_form_body):
                attrs = ta.group(1)
                n_m = re.search(r'\bname="([^"]+)"', attrs)
                if n_m:
                    print(f"    [textarea] {n_m.group(1)}")
        else:
            print("    (no form found matching /chapters/{id})")

        # Flash message
        flash = re.search(
            r'<div[^>]*class="[^"]*flash[^"]*"[^>]*>(.*?)</div>',
            post_resp.text, re.DOTALL,
        )
        if flash:
            print(f"  Flash: {re.sub(r'<[^>]+>', '', flash.group(1)).strip()[:200]}")

        # Verify draft state still
        print()
        print("Verifying draft state after preview POST...")
        in_drafts = await client.is_work_in_drafts(work_id)
        in_published = await client.is_work_published(work_id)
        print(f"  in drafts:    {in_drafts}")
        print(f"  in published: {in_published}")

    finally:
        if work_id:
            print()
            print(f"[CLEANUP] Deleting test work {work_id}...")
            try:
                await client.delete_work(work_id)
                print(f"[CLEANUP] Deleted")
            except Exception as e:
                print(f"[CLEANUP] FAILED: {e}")
                print(f"  MANUALLY DELETE: https://www.squidgeworld.org/works/{work_id}/confirm_delete")

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
