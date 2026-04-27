"""Live test: edit the draft created by live_test_sqw_draft.py.

Demonstrates the EDIT pipeline by modifying the title and summary of the
existing draft work (work_id 91374) so the change is clearly visible.

Strategy (safe form-fetch pattern):
  1. Login as KnaughtyKat
  2. GET /works/{id}/edit — fetch the full form with current values
  3. Parse out every work[*] input/select/textarea + the array fields
  4. Modify only title and summary
  5. POST the full form back with _method=patch and preview_button (keeps draft)

This avoids the Rails-PATCH-clears-omitted-fields trap.

Usage:
  cd C:/Users/rhysc/claude/PawPoller
  python tests/live_test_sqw_edit.py
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


WORK_ID = "91374"
EDIT_MARKER = "[EDITED 2026-04-07]"


def extract_form_fields(html: str) -> tuple[str, list[tuple[str, str]]]:
    """Parse all form fields from the work edit page.

    Returns (csrf_token, list_of_(name,value)_tuples).

    Handles:
      - hidden / text inputs (value either before or after name attr)
      - checkboxes (only those with `checked` attribute)
      - select fields (the option marked `selected`)
      - textareas
    """
    # CSRF token
    token_m = re.search(r'name="authenticity_token"[^>]*value="([^"]+)"', html)
    if not token_m:
        token_m = re.search(r'value="([^"]+)"[^>]*name="authenticity_token"', html)
    if not token_m:
        raise RuntimeError("Could not find CSRF token in edit form")
    token = token_m.group(1)

    # Find the work edit form scope so we don't pick up unrelated forms
    form_match = re.search(
        r'<form[^>]*action="[^"]*works/\d+[^"]*"[^>]*>(.*?)</form>',
        html,
        re.DOTALL,
    )
    form_html = form_match.group(1) if form_match else html

    fields: list[tuple[str, str]] = []

    # 1. Hidden + text inputs (skip image/button/submit)
    for inp_match in re.finditer(r'<input([^>]*?)>', form_html):
        attrs = inp_match.group(1)
        type_m = re.search(r'\btype="([^"]+)"', attrs)
        inp_type = type_m.group(1).lower() if type_m else "text"
        if inp_type in ("submit", "button", "image", "reset", "file"):
            continue
        name_m = re.search(r'\bname="([^"]+)"', attrs)
        if not name_m:
            continue
        name = name_m.group(1)
        # Skip the CSRF and method fields - we'll add them explicitly
        if name in ("authenticity_token", "_method", "utf8"):
            continue
        # Only include work[*] and pseud fields
        if not (name.startswith("work[") or "pseud" in name or "author" in name):
            continue
        value_m = re.search(r'\bvalue="([^"]*)"', attrs)
        value = value_m.group(1) if value_m else ""
        if inp_type == "checkbox":
            # Only include checkboxes that are checked (or hidden array placeholders)
            if "checked" not in attrs.lower():
                continue
        elif inp_type == "radio":
            if "checked" not in attrs.lower():
                continue
        # Decode HTML entities in value
        value = value.replace("&amp;", "&").replace("&quot;", '"').replace("&#39;", "'").replace("&lt;", "<").replace("&gt;", ">")
        fields.append((name, value))

    # 2. Select fields - get the selected option
    for sel_match in re.finditer(r'<select([^>]*?)>(.*?)</select>', form_html, re.DOTALL):
        attrs = sel_match.group(1)
        body = sel_match.group(2)
        name_m = re.search(r'\bname="([^"]+)"', attrs)
        if not name_m:
            continue
        name = name_m.group(1)
        if not name.startswith("work["):
            continue
        # Find selected option
        sel_opt = re.search(r'<option[^>]*\bselected[^>]*\bvalue="([^"]*)"', body)
        if not sel_opt:
            sel_opt = re.search(r'<option[^>]*\bvalue="([^"]*)"[^>]*\bselected', body)
        value = sel_opt.group(1) if sel_opt else ""
        fields.append((name, value))

    # 3. Textareas - body content
    for ta_match in re.finditer(r'<textarea([^>]*?)>(.*?)</textarea>', form_html, re.DOTALL):
        attrs = ta_match.group(1)
        body = ta_match.group(2)
        name_m = re.search(r'\bname="([^"]+)"', attrs)
        if not name_m:
            continue
        name = name_m.group(1)
        if not name.startswith("work["):
            continue
        # Decode entities in textarea body
        value = body.replace("&amp;", "&").replace("&quot;", '"').replace("&#39;", "'").replace("&lt;", "<").replace("&gt;", ">")
        fields.append((name, value))

    return token, fields


async def main() -> int:
    print("=" * 70)
    print(f"SquidgeWorld Edit Test — Work ID {WORK_ID}")
    print("=" * 70)

    settings = config.get_settings()
    username = settings.get("sqw_author_username") or settings.get("sqw_username")
    password = settings.get("sqw_author_password") or settings.get("sqw_password")
    target = settings.get("sqw_target_user", "")

    client = SquidgeWorldClient(username, password, target)
    if not await client.ensure_logged_in():
        print("LOGIN FAILED")
        return 1
    print(f"  Logged in as {username}")

    # 1. Fetch edit form
    edit_url = f"https://squidgeworld.org/works/{WORK_ID}/edit"
    print(f"  Fetching {edit_url}")
    resp = await client._http.get(edit_url)
    if resp.status_code >= 400:
        print(f"  Edit form fetch failed: status {resp.status_code}")
        return 1
    html = resp.text
    Path(f"sqw_edit_form_{WORK_ID}.html").write_text(html, encoding="utf-8")
    print(f"  Form HTML saved ({len(html)} bytes)")

    # 2. Parse all current field values
    token, fields = extract_form_fields(html)
    print(f"  Extracted {len(fields)} form fields")

    # Show current title and summary
    current_title = next((v for n, v in fields if n == "work[title]"), "")
    current_summary = next((v for n, v in fields if n == "work[summary]"), "")
    print(f"  Current title:   {current_title!r}")
    print(f"  Current summary: {current_summary[:80]!r}...")
    print()

    # 3. Modify title and summary
    new_title = f"Chosen [DRAFT TEST 2026-04-07] {EDIT_MARKER}"
    new_summary = (
        f"<p><strong>{EDIT_MARKER}</strong> — this draft was edited by the "
        f"PawPoller live test at {asyncio.get_event_loop().time():.0f}.</p>"
        f"<p>Original summary follows:</p>"
        f"{current_summary}"
    )

    new_fields: list[tuple[str, str]] = []
    title_set = False
    summary_set = False
    for name, value in fields:
        if name == "work[title]":
            new_fields.append((name, new_title))
            title_set = True
        elif name == "work[summary]":
            new_fields.append((name, new_summary))
            summary_set = True
        else:
            new_fields.append((name, value))
    if not title_set:
        new_fields.append(("work[title]", new_title))
    if not summary_set:
        new_fields.append(("work[summary]", new_summary))

    # 4. Add the form mechanics: CSRF, method override, preview button
    submit_data: list[tuple[str, str]] = [
        ("authenticity_token", token),
        ("_method", "patch"),
    ]
    submit_data.extend(new_fields)
    # Use save_button to save as draft directly (skips the preview step which
    # for edits doesn't actually persist changes — it just shows a preview).
    submit_data.append(("save_button", "Save As Draft"))

    print(f"  New title:   {new_title!r}")
    print(f"  New summary: {new_summary[:120]!r}...")
    print()
    print(f"  Submitting {len(submit_data)} form fields to /works/{WORK_ID}")

    # 5. POST the edit
    body = urlencode(submit_data, doseq=True)
    resp = await client._http.post(
        f"https://squidgeworld.org/works/{WORK_ID}",
        content=body,
        headers={
            "Referer": edit_url,
            "Content-Type": "application/x-www-form-urlencoded",
        },
        timeout=60.0,
    )

    print(f"  Response: status={resp.status_code} url={resp.url}")
    # Always dump the response body for inspection
    body_path = f"sqw_edit_response_{WORK_ID}.html"
    Path(body_path).write_text(resp.text, encoding="utf-8")
    print(f"  Response body saved to {body_path} ({len(resp.text)} bytes)")
    print()

    # Look for any flash notice or error
    flash = re.search(r'<div[^>]*class="[^"]*flash[^"]*"[^>]*>(.*?)</div>', resp.text, re.DOTALL)
    if flash:
        print(f"  Flash message: {re.sub(r'<[^>]+>', '', flash.group(1)).strip()[:200]}")

    # Look for any error
    err_block = re.search(r'<(?:div|ul)[^>]*id="error"[^>]*>(.*?)</(?:div|ul)>', resp.text, re.DOTALL)
    if err_block:
        print(f"  ERROR BLOCK: {re.sub(r'<[^>]+>', ' ', err_block.group(1)).strip()[:300]}")

    # Check title in the response body
    title_in_resp = re.search(r'<title>([^<]+)</title>', resp.text)
    if title_in_resp:
        print(f"  Page <title>: {title_in_resp.group(1).strip()[:120]}")

    # Check for errors
    if "Sorry! We couldn" in resp.text or "errorlist" in resp.text:
        errors = re.findall(
            r'<(?:li|div)[^>]*class="[^"]*error[^"]*"[^>]*>(.*?)</(?:li|div)>',
            resp.text,
            re.DOTALL,
        )
        err_text = "; ".join(re.sub(r"<[^>]+>", "", e).strip()[:200] for e in errors[:5])
        print(f"EDIT FAILED. Errors: {err_text or '(none parsed)'}")
        debug_path = f"sqw_edit_debug_{WORK_ID}.html"
        Path(debug_path).write_text(resp.text, encoding="utf-8")
        print(f"  Debug body saved to {debug_path}")
        return 1

    final_url = str(resp.url)
    if f"/works/{WORK_ID}" in final_url:
        print(f"EDIT OK — response URL: {final_url}")
        print()
        print(f"Verify: https://squidgeworld.org/works/{WORK_ID}/preview")
        print(f"  Title should now contain: {EDIT_MARKER}")
        print(f"  Summary should start with: {EDIT_MARKER}")
        return 0
    else:
        print(f"UNEXPECTED REDIRECT: {final_url}")
        debug_path = f"sqw_edit_unexpected_{WORK_ID}.html"
        Path(debug_path).write_text(resp.text, encoding="utf-8")
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
