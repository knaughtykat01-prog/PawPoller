"""AO3 diagnostic — figure out why _get_page fails when raw _http.get works."""
from __future__ import annotations
import asyncio
import sys
import traceback
from pathlib import Path

sys.path.insert(0, "/app")

from ao3_client.client import AO3Client


async def main() -> int:
    c = AO3Client("x", "y", "")

    print("=== test 1: _get_page (wrapped) x 5 ===")
    for i in range(5):
        try:
            html = await c._get_page("https://archiveofourown.org/users/login")
            ok = "None" if html is None else f"OK len={len(html)}"
        except Exception as e:
            ok = f"EXC {type(e).__name__}: {e!r}"
        print(f"  attempt {i+1}: {ok}")
        await asyncio.sleep(2)

    print()
    print("=== test 2: _http.get (raw) x 5 ===")
    for i in range(5):
        try:
            resp = await c._http.get("https://archiveofourown.org/users/login")
            ok = f"{resp.status_code} len={len(resp.text)}"
        except Exception as e:
            ok = f"EXC {type(e).__name__}: {e!r}"
        print(f"  attempt {i+1}: {ok}")
        await asyncio.sleep(2)

    print()
    print("=== test 3: full _get_page with traceback exposed ===")
    # Monkey-patch to expose the exception
    import httpx
    original_method = c._get_page

    async def debug_get_page(url):
        try:
            resp = await c._http.get(url)
            print(f"  raw status: {resp.status_code}, len={len(resp.text)}")
            if resp.status_code == 403:
                print("    -> 403 branch hit")
                return None
            if resp.status_code == 429:
                print("    -> 429 branch hit")
                await asyncio.sleep(30)
                resp = await c._http.get(url)
            resp.raise_for_status()
            return resp.text
        except httpx.HTTPError as e:
            print(f"    -> EXCEPTION httpx.HTTPError: {type(e).__name__} repr={e!r} str='{e}'")
            traceback.print_exc()
            return None
        except Exception as e:
            print(f"    -> EXCEPTION other: {type(e).__name__} repr={e!r}")
            traceback.print_exc()
            return None

    result = await debug_get_page("https://archiveofourown.org/users/login")
    print(f"  result: {None if result is None else f'OK len={len(result)}'}")

    await c.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
