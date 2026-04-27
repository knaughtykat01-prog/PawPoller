"""Debug: fetch /works/new form HTML and dump all input fields."""
import asyncio
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
from clients.sqw.client import SquidgeWorldClient


async def main():
    settings = config.get_settings()
    username = settings.get("sqw_author_username") or settings.get("sqw_username")
    password = settings.get("sqw_author_password") or settings.get("sqw_password")
    target = settings.get("sqw_target_user", "")

    client = SquidgeWorldClient(username, password, target)
    await client.ensure_logged_in()

    resp = await client._http.get("https://squidgeworld.org/works/new")
    html = resp.text

    # Save raw form
    Path("sqw_works_new_form.html").write_text(html, encoding="utf-8")
    print(f"Form saved to sqw_works_new_form.html ({len(html)} bytes)")
    print()

    # Extract every <input ... name="..." value="..." ...>
    print("=== Input fields ===")
    inputs = re.findall(r'<input([^>]+)>', html)
    for inp in inputs:
        name_m = re.search(r'name="([^"]+)"', inp)
        value_m = re.search(r'value="([^"]*)"', inp)
        type_m = re.search(r'type="([^"]+)"', inp)
        if name_m and ("work[" in name_m.group(1) or "author" in name_m.group(1) or "pseud" in name_m.group(1)):
            n = name_m.group(1)
            v = value_m.group(1) if value_m else ""
            t = type_m.group(1) if type_m else "?"
            if "authenticity_token" in n:
                v = "..."
            print(f"  [{t}] {n} = {v[:80]}")

    print()
    print("=== Select fields and their selected option ===")
    # Find <select> blocks with name and capture selected option
    selects = re.findall(r'<select([^>]+)>(.*?)</select>', html, re.DOTALL)
    for attrs, body in selects:
        name_m = re.search(r'name="([^"]+)"', attrs)
        if not name_m:
            continue
        name = name_m.group(1)
        if "work[" not in name and "language" not in name:
            continue
        # Find selected option
        sel = re.search(r'<option[^>]*selected[^>]*value="([^"]*)"[^>]*>([^<]*)</option>', body)
        if not sel:
            sel = re.search(r'<option[^>]*value="([^"]*)"[^>]*selected[^>]*>([^<]*)</option>', body)
        if sel:
            print(f"  [select] {name} = {sel.group(1)} ({sel.group(2).strip()})")
        else:
            print(f"  [select] {name} = (no default)")

    print()
    print("=== Warning tags allowed ===")
    warning_section = re.search(r'archive_warning.*?</fieldset>', html, re.DOTALL)
    if warning_section:
        warnings = re.findall(r'value="([^"]+)"[^>]*>\s*([^<]+)</label>', warning_section.group(0))
        for v, label in warnings:
            print(f"  value=\"{v}\" label=\"{label.strip()}\"")


if __name__ == "__main__":
    asyncio.run(main())
