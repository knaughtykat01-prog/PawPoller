"""Probe SqW work page structure for the importer parser."""
import asyncio
import httpx


async def main():
    async with httpx.AsyncClient(
        timeout=30,
        follow_redirects=True,
        headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
    ) as c:
        r = await c.get(
            "https://squidgeworld.org/works/88317?view_full_work=true&view_adult=true"
        )
        print("status:", r.status_code, "len:", len(r.text))
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
        ]:
            print(f"  {sel!r}: {r.text.count(sel)} occurrences")
        # Dump the first <h2 ...> for inspection
        import re
        m = re.search(r'<h2[^>]*>.*?</h2>', r.text, re.DOTALL)
        if m:
            print("first h2:", m.group(0)[:300])
        m2 = re.search(r'<h3[^>]*>.*?</h3>', r.text, re.DOTALL)
        if m2:
            print("first h3:", m2.group(0)[:300])
        # Dump first 1500 chars of body to see what we got
        bm = re.search(r'<body[^>]*>(.*?)$', r.text, re.DOTALL)
        if bm:
            print("body start:", bm.group(1)[:1500])

asyncio.run(main())
