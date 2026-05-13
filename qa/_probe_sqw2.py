"""Probe SqW work page via the authenticated client + Anubis solver."""
import asyncio, sys
sys.path.insert(0, "/app")

import config
from clients.sqw.client import SquidgeWorldClient


async def main():
    settings = config.get_settings()
    client = SquidgeWorldClient(
        username=settings.get("sqw_username", ""),
        password=settings.get("sqw_password", ""),
        target_user=settings.get("sqw_target_user", "") or settings.get("sqw_username", ""),
    )
    try:
        url = "https://squidgeworld.org/works/88317?view_full_work=true&view_adult=true"
        html = await client._get_page(url)
        if not html:
            print("got None")
            return
        print("len:", len(html))
        for sel in [
            "title heading",
            "byline heading",
            'class="summary',
            'class="rating',
            'class="freeform',
            'id="chapter-',
            'class="userstuff',
            'class="work meta',
            "<h2",
            "preface group",
            "Making sure you",
        ]:
            print(f"  {sel!r}: {html.count(sel)}")
        # dump first 800 chars after the body open
        import re
        # find <h2> + userstuff context
        for m in re.finditer(r"<h2[^>]*>(.*?)</h2>", html, re.DOTALL):
            print("H2:", m.group(0)[:300])
        for m in re.finditer(r'<div[^>]*class="[^"]*userstuff[^"]*"[^>]*>(.{0,500})', html, re.DOTALL):
            print("USERSTUFF:", m.group(0)[:500])
        # Save full to disk
        with open("/tmp/_sqw_dump.html", "w") as fh:
            fh.write(html)
        print("dumped to /tmp/_sqw_dump.html")
    finally:
        await client.close()


asyncio.run(main())
