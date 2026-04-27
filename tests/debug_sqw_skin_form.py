"""Debug: dump /skins/new form fields."""
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

    r = await c._http.get('https://www.squidgeworld.org/skins/new?skin_type=WorkSkin')
    Path('sqw_skins_new.html').write_text(r.text, encoding='utf-8')
    print(f'Saved {len(r.text)} bytes, status={r.status_code}, final={r.url}')

    # Extract action URL of the form
    form_action = re.search(r'<form[^>]*action="([^"]+)"[^>]*>', r.text)
    print(f'Form action: {form_action.group(1) if form_action else "?"}')

    # Find all input/select/textarea with name="skin[*]"
    print()
    print('=== skin[*] form fields ===')
    for inp in re.finditer(r'<input([^>]*?)>', r.text):
        attrs = inp.group(1)
        name_m = re.search(r'\bname="(skin\[[^"]+\])"', attrs)
        if not name_m:
            continue
        type_m = re.search(r'\btype="([^"]+)"', attrs)
        value_m = re.search(r'\bvalue="([^"]*)"', attrs)
        t = type_m.group(1) if type_m else 'text'
        v = value_m.group(1)[:60] if value_m else ''
        print(f'  [{t:8}] {name_m.group(1)} = {v}')

    for sel in re.finditer(r'<select([^>]*?)>(.*?)</select>', r.text, re.DOTALL):
        attrs, body = sel.group(1), sel.group(2)
        name_m = re.search(r'\bname="(skin\[[^"]+\])"', attrs)
        if not name_m:
            continue
        # Find all options
        opts = re.findall(r'<option[^>]*value="([^"]*)"[^>]*>([^<]*)</option>', body)
        print(f'  [select  ] {name_m.group(1)}')
        for v, label in opts[:5]:
            print(f'              value={v!r} label={label.strip()!r}')

    for ta in re.finditer(r'<textarea([^>]*?)>', r.text):
        attrs = ta.group(1)
        name_m = re.search(r'\bname="(skin\[[^"]+\])"', attrs)
        if not name_m:
            continue
        print(f'  [textarea] {name_m.group(1)}')

    # Submit button
    submit = re.findall(r'<input[^>]*type="submit"[^>]*name="([^"]+)"[^>]*value="([^"]*)"', r.text)
    print()
    print('=== submit buttons ===')
    for n, v in submit:
        print(f'  name={n!r} value={v!r}')


if __name__ == '__main__':
    asyncio.run(main())
