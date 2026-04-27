# PawPoller

**Multi-platform story publishing pipeline for furry fiction writers.**

🌐 **[pawpoller.pages.dev](https://pawpoller.pages.dev)** — features, screenshots, download

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11+-3776AB.svg)](https://python.org)
[![Platform: Windows](https://img.shields.io/badge/Platform-Windows-0078D6.svg)](#quick-start)
[![Docker](https://img.shields.io/badge/Docker-supported-2496ED.svg)](#server--docker-deployment)

PawPoller is a desktop app and self-hosted server for publishing fiction across furry writing platforms. Write your stories in Markdown, convert them to every format (BBCode, HTML, Styled HTML, PDF), publish to 11 platforms with per-chapter tags and descriptions, and track views, favourites, and comments from a single dashboard. Think of it as [PostyBirb](https://www.postybirb.com/) but built for writers instead of visual artists -- chaptered posting, format conversion, story analytics, and drift detection.

---

## Features

- **Multi-format conversion** -- Markdown to BBCode (Inkbunny), HTML (SoFurry), Styled HTML (AO3 work skins), PDF, and SquidgeWorld format, all from one source file
- **11-platform support** -- Inkbunny, FurAffinity, SoFurry, Weasyl, AO3, DeviantArt, SquidgeWorld, Wattpad, Itaku, Bluesky, and X/Twitter
- **Chaptered publishing** -- Split multi-chapter stories automatically, with per-chapter tags, descriptions, and thumbnails
- **Analytics dashboard** -- Track views, favourites, comments, and other metrics across all platforms with historical charts
- **Polling engine** -- Automatically fetches stats on a schedule, detects new comments and favourites
- **Telegram notifications** -- Get alerts for milestones, new comments, and goal completions
- **Built-in editor** -- Markdown editor with live preview, slop scoring, and format conversion
- **Tag database** -- 4,600+ tags with per-platform validation and chapter-level tagging
- **Goal tracking** -- Set targets for views/favourites/comments and track progress
- **Two deployment modes** -- Desktop app (Windows .exe) or headless Docker server
- **Credential vault** -- Optional encrypted credential storage with system keyring integration
- **Dashboard auth** -- Session-based login with bcrypt, TOTP 2FA, Cloudflare Turnstile, and API keys

---

## Screenshots

*Screenshots coming soon.*

<!-- TODO: Add screenshots of the dashboard, editor, analytics charts, and posting workflow -->

---

## Quick Start

Full walkthrough: [**docs/SETUP.md**](docs/SETUP.md) — covers desktop, Docker self-hosting (including reverse proxy / Cloudflare Tunnel for public access), and running from source.

### Option A: Download the release (Windows)

1. Download the latest `PawPoller-windows-x64.zip` from [Releases](../../releases)
2. Extract and run `PawPoller.exe`
3. The setup wizard guides you through connecting your platforms
4. Add stories and start publishing

### Option B: Run from source

```bash
git clone https://github.com/knaughtykat01-prog/PawPoller.git
cd PawPoller
pip install -r requirements.txt
python main.py
```

### Option C: Docker (headless server)

```bash
git clone https://github.com/knaughtykat01-prog/PawPoller.git
cd PawPoller
cp .env.example .env    # Edit with your credentials — set DASHBOARD_PASSWORD!
# Edit docker-compose.yml: change the story-archive bind-mount path to yours
docker compose up -d --build
```

The dashboard is available at `http://localhost:8420`. For public/web access behind TLS, see [docs/SETUP.md §2.5](docs/SETUP.md#25-exposing-it-to-the-web).

---

## Supported Platforms

| Platform | Auth | Poll | Post | Edit | Notes |
|----------|------|------|------|------|-------|
| Inkbunny | Username/password | Yes | Yes | Yes | Full API support, chaptered |
| FurAffinity | Session cookies (a/b) | Yes | Yes | Yes | Scraping-based (no official API) |
| SoFurry | Email/password | Yes | Yes | Yes | Scraping-based, chaptered |
| Weasyl | API key | Yes | Yes | Yes | Official API |
| AO3 | Username/password | Yes | Yes | Yes | Rails CSRF login, work skins, chaptered |
| DeviantArt | Session cookie | Yes | Yes | Yes | Eclipse API, CF proxy for server |
| SquidgeWorld | Username/password | Yes | Yes | Yes | Scraping-based, chaptered |
| Wattpad | Public (read-only) | Yes | -- | -- | Public stats polling only |
| Itaku | Public (read-only) | Yes | -- | -- | Public stats polling only |
| Bluesky | Handle/app password | Yes | -- | -- | AT Protocol |
| X/Twitter | Auth token/ct0 | Yes | -- | -- | GraphQL scraping |

---

## Architecture

PawPoller has two entry points:

- **`main.py`** -- Desktop mode. Runs a pywebview native window with a pystray system tray icon. Per-platform poller threads run in the background. Best for personal use on Windows.
- **`server.py`** -- Headless/server mode. Runs just the FastAPI dashboard and a unified poll orchestrator. Designed for Docker or Linux VPS deployment for 24/7 polling.

Both modes share:
- **`dashboard.py`** -- FastAPI application serving the web UI and API
- **`config.py`** -- Settings, credentials, and path resolution
- **`database/`** -- SQLite database with per-platform schemas
- **`frontend/`** -- Plain HTML/JS/CSS dashboard (no build step, no framework)

Each platform follows a consistent file pattern:
```
{xx}_client/client.py      -- HTTP client for the platform API
polling/{xx}_poller.py     -- Poll cycle orchestration
database/{xx}_queries.py   -- Database queries
database/{xx}_schema.sql   -- SQL schema
routes/{xx}_api.py         -- Dashboard API endpoints
posting/platforms/{xx}.py  -- Upload/edit logic (where supported)
```

---

## Development

### Prerequisites

- Python 3.11+
- pip

### Setup

```bash
git clone https://github.com/knaughtykat01-prog/PawPoller.git
cd PawPoller
pip install -r requirements.txt
cp .env.example .env          # Optional: for env-based credential config
python main.py                # Desktop mode
# or
python server.py              # Headless mode
```

### Server-only dependencies

For Docker/server deployments, use the pinned server requirements:

```bash
pip install -r requirements-server.txt
```

### Building the Windows executable

```bash
pip install pyinstaller
python -m PyInstaller pawpoller.spec --noconfirm
# Output: dist/PawPoller/PawPoller.exe
```

### Running tests

```bash
python -m unittest discover -s tests -p "test_*.py" -v
```

### Project documentation

See [`docs/documentation_guide.md`](docs/documentation_guide.md) for the full technical reference covering every module, database schema, API endpoint, and platform client.

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines on development setup, adding new platforms, code style, and pull requests.

---

## License

[MIT](LICENSE)

---

## Credits

- Inspired by [PostyBirb](https://www.postybirb.com/) -- PawPoller takes the multi-platform publishing concept and rebuilds it for fiction writers with chaptered stories, format conversion, and analytics
- Built with [FastAPI](https://fastapi.tiangolo.com/), [pywebview](https://pywebview.flowrl.com/), [Chart.js](https://www.chartjs.org/)
