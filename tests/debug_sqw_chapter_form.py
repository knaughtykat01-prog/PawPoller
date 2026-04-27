"""Debug: dump /works/91374/chapters/new and /skins/2820/edit form fields."""
import asyncio, re, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config
from clients.sqw.client import SquidgeWorldClient


async def main():
    s = config.get_settings()
    c = SquidgeWorldClient(
        s.get('sqw_author_username') or s.get('sqw_username'),
        s.get('sqw_author_password') or s.get('sqw_password'),
        s.get('sqw_target_user', ''),
    )
    await c.ensure_logged_in()

    for url, save_to in [
        ('https://www.squidgeworld.org/works/91374/chapters/new', 'sqw_chapter_new.html'),
        ('https://www.squidgeworld.org/skins/2820/edit', 'sqw_skin_edit.html'),
    ]:
        print(f'=== {url} ===')
        r = await c._http.get(url)
        print(f'  status={r.status_code} final={r.url}')
        Path(save_to).write_text(r.text, encoding='utf-8')
        print(f'  saved {len(r.text)} bytes to {save_to}')

        # form action
        forms = re.findall(r'<form[^>]*action="([^"]+)"[^>]*>', r.text)
        print(f'  forms: {forms[:5]}')

        # submit buttons
        submits = re.findall(r'<input[^>]*type="submit"[^>]*name="([^"]*)"[^>]*value="([^"]*)"', r.text)
        print(f'  submit buttons: {submits[:8]}')

        # field names
        names = set()
        for inp in re.finditer(r'<input([^>]*?)>', r.text):
            attrs = inp.group(1)
            n = re.search(r'\bname="([^"]+)"', attrs)
            t = re.search(r'\btype="([^"]+)"', attrs)
            if n and (t and t.group(1).lower() not in ('submit', 'button', 'image', 'file')):
                if 'chapter[' in n.group(1) or 'skin[' in n.group(1) or 'pseud' in n.group(1):
                    names.add(n.group(1))
        for sel in re.finditer(r'<select([^>]*?)>', r.text):
            n = re.search(r'\bname="([^"]+)"', sel.group(1))
            if n and ('chapter[' in n.group(1) or 'skin[' in n.group(1)):
                names.add(n.group(1))
        for ta in re.finditer(r'<textarea([^>]*?)>', r.text):
            n = re.search(r'\bname="([^"]+)"', ta.group(1))
            if n and ('chapter[' in n.group(1) or 'skin[' in n.group(1)):
                names.add(n.group(1))
        for n in sorted(names):
            print(f'    field: {n}')
        print()


if __name__ == '__main__':
    asyncio.run(main())
