# PawPoller Setup Guide

This is a new-user install guide. Pick the mode that fits you:

| Mode | Who it's for | Data stays on | Dashboard reachable from |
|------|--------------|---------------|--------------------------|
| **Desktop (Windows)** | One user, one machine | Your PC | `127.0.0.1:8420` only |
| **Docker / headless** | Self-hosted, always-on polling, access from phone/laptop | Your server | LAN or the public internet (you choose) |
| **From source** | Devs, Linux/macOS users, anyone wanting to hack on it | Wherever you clone | Same as whichever entry point you run |

All three share the same code, database, and UI — the only difference is how it's packaged and where the process runs.

---

## 1. Desktop (Windows)

The simplest path. A single `.exe` with the dashboard, all pollers, and the publishing pipeline bundled.

### 1.1 Requirements

- Windows 10 or 11 (x64)
- Microsoft Edge installed (used for PDF generation — it's preinstalled on modern Windows)
- ~200 MB disk space for the app, more for stories

### 1.2 Install

1. Open the [Releases page](https://github.com/knaughtykat01-prog/PawPoller/releases/latest).
2. Download `PawPoller-windows-x64.zip`.
3. Right-click → Properties → **Unblock** (Windows sometimes flags unsigned zips). Then extract anywhere — e.g. `C:\PawPoller`.
4. Double-click `PawPoller.exe`.

On first launch a pywebview window opens with the setup wizard. The app also installs a tray icon — right-click it for **Show / Hide / Quit**.

### 1.3 First-run wizard

The wizard walks you through four steps:

1. **Welcome** — overview.
2. **Story archive path** — point at a folder where your stories live (or will live). See §4 for the expected layout.
3. **Platform connections** — cards for all 11 platforms. You can skip this and fill it in later from Settings.
4. **Done**. Dashboard opens.

### 1.4 Where your data lives

```
%APPDATA%\PawPoller\           (equivalent to C:\Users\<you>\AppData\Roaming\PawPoller)
├── data\
│   ├── pawpoller.db            SQLite database (polling stats, publications, queue)
│   ├── settings.json           Non-secret settings
│   └── settings.vault.json     Encrypted credentials (if vault enabled — see §5.4)
└── logs\                       Rotated log files
```

Back these two folders up and you've got everything.

### 1.5 Updating

Download the new release zip, extract over the old folder (keep your `data\` and `logs\` folders untouched), re-launch. The database auto-migrates.

### 1.6 Build from source (advanced)

If you'd rather build the exe yourself:

```powershell
git clone https://github.com/knaughtykat01-prog/PawPoller.git
cd PawPoller
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
pip install pyinstaller
python -m PyInstaller pawpoller.spec --noconfirm
# Output: dist\PawPoller\PawPoller.exe
```

---

## 2. Docker / headless (self-hosted, web-accessible)

Best for leaving PawPoller polling 24/7 and reaching the dashboard from any device on your LAN — or behind a reverse proxy, from the public internet. This is how the author runs it on a GCP VM.

### 2.1 Requirements

- Linux host (any distro with Docker — tested on Debian 12 and Ubuntu 22/24). Windows/WSL and macOS Docker Desktop also work.
- Docker Engine ≥ 24 and Docker Compose v2 (ships with modern Docker).
- A directory on the host for your story archive (shared via bind mount).

### 2.2 Clone and configure

```bash
git clone https://github.com/knaughtykat01-prog/PawPoller.git
cd PawPoller
cp .env.example .env
```

Edit `.env`. Uncomment only the platforms you use — fill in credentials or leave blank and configure via the UI later. **Always set `DASHBOARD_PASSWORD`** if the container will be reachable by anything other than `localhost`:

```
DASHBOARD_USER=admin
DASHBOARD_PASSWORD=pick-something-long-and-random
```

Without a password, anyone who can hit port 8420 gets full control — including your credentials.

### 2.3 Point docker-compose at your story archive

`docker-compose.yml` bind-mounts the story archive. The shipped file points at the author's path — change it:

```yaml
volumes:
  - pawpoller-data:/app/data
  - pawpoller-logs:/app/logs
  - /home/YOU/story-archive:/app/story-archive   # ← change this path
```

The two named volumes (`pawpoller-data`, `pawpoller-logs`) are managed by Docker and survive container rebuilds. The bind mount is where your `MASTER.md` files and generated formats live — put it somewhere you back up.

### 2.4 Start it

```bash
docker compose up -d --build
```

Check it's up:

```bash
docker compose ps
docker compose logs --tail=50
curl -s http://localhost:8420/health
```

Visit `http://<host>:8420` (or `http://localhost:8420` on the same machine) and log in with the credentials you set.

### 2.5 Exposing it to the web

**Don't just open port 8420 to the internet directly.** The dashboard is hardened (bcrypt, optional TOTP, optional Turnstile, rate limiting) but sits behind a single password — you want TLS in front of it. Pick one:

**Option A — Cloudflare Tunnel (easiest, no port-forwarding, no public IP needed):**

```bash
# On the host:
curl -L --output cloudflared.deb https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb
sudo dpkg -i cloudflared.deb
cloudflared tunnel login                       # opens browser, pick your domain
cloudflared tunnel create pawpoller
cloudflared tunnel route dns pawpoller pawpoller.yourdomain.com
cloudflared tunnel --url http://localhost:8420 run pawpoller
# Run as a service:  sudo cloudflared service install
```

Now `https://pawpoller.yourdomain.com` reaches the dashboard over TLS, no inbound ports open. You can also enable Cloudflare Access in front of it for an extra auth layer.

**Option B — Caddy reverse proxy (if you already have a domain pointed at your server):**

```caddy
pawpoller.yourdomain.com {
    reverse_proxy localhost:8420
}
```

Caddy provisions a Let's Encrypt cert automatically.

**Option C — nginx reverse proxy:**

```nginx
server {
    listen 443 ssl http2;
    server_name pawpoller.yourdomain.com;
    ssl_certificate     /etc/letsencrypt/live/pawpoller.yourdomain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/pawpoller.yourdomain.com/privkey.pem;

    location / {
        proxy_pass http://127.0.0.1:8420;
        proxy_set_header Host              $host;
        proxy_set_header X-Real-IP         $remote_addr;
        proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

Whichever proxy you use, **don't forget to close public access to port 8420 itself** — bind Docker to localhost instead:

```yaml
# docker-compose.yml
ports:
  - "127.0.0.1:8420:8420"   # only reachable from the host; proxy handles the rest
```

### 2.6 Updating

```bash
cd PawPoller
git pull
docker compose up -d --build
```

The SQLite schema auto-migrates on startup. Your `data` and `logs` volumes are preserved; the `story-archive` bind mount is never touched by the container except on explicit saves from the editor.

### 2.7 Watching what it's doing

```bash
docker compose logs -f pawpoller       # stream live logs
docker compose logs --tail=200         # last 200 lines
docker compose restart pawpoller       # bounce without rebuild
```

### 2.8 Backup

Three things to snapshot:

1. `.env` (your credentials, if you used it — otherwise settings.vault.json has them).
2. The `pawpoller-data` named volume — or just the DB inside it:
   ```bash
   docker compose exec pawpoller sqlite3 /app/data/pawpoller.db ".backup /app/data/backup.db"
   docker cp $(docker compose ps -q pawpoller):/app/data/backup.db ./pawpoller-backup.db
   ```
3. Your story archive directory (the bind mount).

---

## 3. From source (Linux / macOS / Windows dev)

If you want to run it outside Docker — for development, custom packaging, or a Linux desktop install.

### 3.1 Requirements

- Python 3.11 or 3.12 (3.13+ untested)
- pip + venv
- For PDF rendering on Linux: `weasyprint` needs `libpango`, `libcairo`, `libgdk-pixbuf`. Ubuntu: `sudo apt-get install libpango-1.0-0 libpangoft2-1.0-0`.
- For desktop mode: a display server (won't launch pywebview headlessly).

### 3.2 Clone and install

```bash
git clone https://github.com/knaughtykat01-prog/PawPoller.git
cd PawPoller
python -m venv .venv
source .venv/bin/activate               # Windows: .venv\Scripts\Activate.ps1

# Pick the right requirements file:
pip install -r requirements.txt         # desktop (includes pywebview + pystray)
# or
pip install -r requirements-server.txt  # headless (no GUI deps)
```

### 3.3 Run

```bash
python main.py      # desktop mode — opens a pywebview window + tray icon
# or
python server.py    # headless — serves the dashboard on 0.0.0.0:8420
```

Visit `http://localhost:8420` in a browser.

### 3.4 Run as a systemd service (Linux headless)

Create `/etc/systemd/system/pawpoller.service`:

```ini
[Unit]
Description=PawPoller
After=network.target

[Service]
Type=simple
User=pawpoller
WorkingDirectory=/opt/PawPoller
Environment="PATH=/opt/PawPoller/.venv/bin"
EnvironmentFile=/opt/PawPoller/.env
ExecStart=/opt/PawPoller/.venv/bin/python server.py
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

Then:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now pawpoller
sudo systemctl status pawpoller
journalctl -u pawpoller -f
```

Same reverse-proxy advice as §2.5 applies.

---

## 4. Story archive layout

PawPoller reads and writes stories from a single parent directory. Each story is one subfolder:

```
story-archive/
├── Late_Shift/
│   ├── story.json                  metadata (title, author, chapters, tags, platform IDs, …)
│   ├── Markdown/
│   │   └── MASTER.md               canonical source — you edit this
│   ├── BBCode/                     auto-generated from MASTER.md (Inkbunny)
│   ├── SoFurry_HTML/               auto-generated (SoFurry)
│   ├── Styled_HTML/                auto-generated (AO3 work skin / preview)
│   ├── SquidgeWorld_HTML/          auto-generated (SqW)
│   ├── PDF/                        auto-generated (WeasyPrint / Edge)
│   └── cover.png                   optional cover image
└── The_Abstinent_Bet/
    └── Nice_Version/               stories can be nested one level deep
        └── Markdown/MASTER.md
```

You can either:

- **Create new stories from the UI** — the "Create New Story" wizard scaffolds everything with a template MASTER.md.
- **Import from a platform** — Settings → Import → paste an Inkbunny/SoFurry/FurAffinity URL. Content is downloaded, converted to Markdown, and saved as a new story folder.
- **Drop in existing files manually** — put a `MASTER.md` under `<StoryName>/Markdown/`, regenerate formats from the editor, and fill out the metadata drawer.

MASTER.md uses HTML-comment anchors (`<!-- @title -->`, `<!-- @body -->`, etc.) to tell the converter how to render each section. The editor's toolbar inserts them for you — hover any button for a tooltip with an example.

---

## 5. Platform credentials

Different platforms need different auth mechanisms. Most of the awkward ones (FA, DA, X) need session cookies — the desktop app's **"Login via Browser"** button pops up a real browser window, you log in, and it captures the cookies for you. In headless/Docker mode you paste cookies manually (instructions are on each platform's settings card).

Short version per platform:

| Platform | Needs | Where to get it |
|----------|-------|-----------------|
| Inkbunny | Username + password | Your IB account — and tick "Enable API access" in IB's account settings |
| FurAffinity | `a` and `b` cookies | Log in to FA, DevTools → Application → Cookies → copy `a` and `b` |
| SoFurry | Email + password | Your SF account |
| Weasyl | API key | weasyl.com → Settings → API keys → generate |
| AO3 | Username + password | Your AO3 account |
| SquidgeWorld | Username + password | Your SqW account |
| DeviantArt | Session cookie | DevTools → Cookies → copy `auth`/`auth_secure`/`userinfo` |
| Wattpad / Itaku / Bluesky / X | Public or app-password — see the in-app settings cards | |

### 5.1 Credential vault (optional, recommended for Docker)

If you'd rather not leave credentials sitting in plaintext `settings.json`, enable the vault:

- Settings → Credential Security → **Enable Vault**
- On Windows desktop, the encryption key goes in Windows Credential Manager.
- On Linux/Docker with no keyring, the key is written to `data/.vault_key` (chmod 600). Back that up separately from `settings.vault.json` — losing one makes the other useless.

### 5.2 Two-factor auth

Settings → Security → Enable 2FA. Scan the QR into any TOTP app (Aegis, 1Password, etc.). Recovery codes are shown once — write them down.

### 5.3 API keys

For scripting (pause/resume polling, trigger regens), Settings → Security → API Keys → generate. Use as `Authorization: Bearer pp_xxx`.

### 5.4 Cloudflare Turnstile (optional)

Adds a Turnstile challenge to the login form. Useful if you've exposed the dashboard publicly and want bot-protection in front of password auth. Set the site key + secret in Settings → Security → Turnstile.

---

## 6. Common gotchas

- **"Port 8420 already in use"** — another PawPoller or unrelated process. `lsof -i :8420` (Linux) or `Get-NetTCPConnection -LocalPort 8420` (PowerShell) to find it.
- **PDFs blank on Linux/Docker** — missing WeasyPrint system libs. `apt-get install libpango-1.0-0 libpangoft2-1.0-0` and rebuild.
- **"AO3 login keeps failing from my server"** — AO3 sometimes puts Cloudflare Shields-up on datacenter IPs. Route through the Cloudflare Worker proxy (CF_WORKER_URL in `.env`) or run AO3 posting from the desktop.
- **"FurAffinity only works on desktop"** — correct, by design. FA blocks most datacenter IPs; the server mode auto-queues FA posts for the desktop app to process when it's next online.
- **"My stories disappeared after `docker compose up`"** — you probably didn't fix the bind-mount path in §2.3 and the container is reading someone else's empty folder. Check `docker compose config` to see the resolved path.
- **"I forgot the dashboard password"** — with Docker running, `docker compose exec pawpoller python -c "from auth import reset_admin_password; reset_admin_password('newpassword')"`.

---

## 7. Where to go next

- `documentation_guide.md` — full technical reference (architecture, threading, database schema, every API endpoint)
- `CHANGELOG.md` — what shipped in each version
- `CONTRIBUTING.md` — dev setup, adding a new platform, code style
- `ROADMAP_PUBLIC.md` — what's planned

If something's missing or wrong, open an issue — this guide gets updated as the app evolves.
