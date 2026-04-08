"""Audit CF proxy + SF state on the server."""
from __future__ import annotations
import sys
sys.path.insert(0, "/app")
import config

s = config.get_settings()

print("=== CF proxy settings ===")
print(f"  cf_worker_url:  {'<set>' if s.get('cf_worker_url') else '<EMPTY>'}")
print(f"  cf_worker_key:  {'<set>' if s.get('cf_worker_key') else '<EMPTY>'}")
url = s.get("cf_worker_url", "")
if url:
    # Just show the host so we know which worker
    from urllib.parse import urlparse
    p = urlparse(url)
    print(f"  worker host:    {p.hostname}")

print()
print("=== SF settings ===")
print(f"  sf_username:        {s.get('sf_username', '<EMPTY>')[:8] + '...' if s.get('sf_username') else '<EMPTY>'}")
print(f"  sf_password:        {'<set>' if s.get('sf_password') else '<EMPTY>'}")
print(f"  sf_display_name:    {s.get('sf_display_name', '')}")
print(f"  sf_session_cookies: {'<set>' if s.get('sf_session_cookies') else '<EMPTY>'}")

print()
print("=== which mode would SoFurryPoster pick? ===")
proxy_url = s.get("cf_worker_url", "")
proxy_key = s.get("cf_worker_key", "")
if proxy_url and proxy_key:
    print(f"  PROXY MODE — routed through {proxy_url[:60]}")
else:
    print(f"  DIRECT MODE — direct httpx (will hit datacenter IP block on SF)")
